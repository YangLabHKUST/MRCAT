"""Signed identities must scope every web operation to the caller's store."""
import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from mrcat.web.access import CloudflareAccess
from mrcat.web.server import create_app
from mrcat.web.service import Service
from test_agent import ROOT
from test_jobs import gateway, wait

ISSUER = "https://mrcat-test.cloudflareaccess.com"
AUDIENCE = "mrcat-test-app"


@pytest.fixture
def signing(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="test-key", use="sig", alg="RS256")
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", lambda self: {"keys": [jwk]})

    def headers(subject="alice", **overrides):
        claims = dict(iss=ISSUER, aud=AUDIENCE, sub=subject,
                      email=subject + "@example.org", iat=int(time.time()) - 1,
                      exp=int(time.time()) + 3600)
        claims.update(overrides)
        return {"Cf-Access-Jwt-Assertion": jwt.encode(
            claims, key, algorithm="RS256", headers={"kid": "test-key"})}
    return headers


def private_app(tmp_path):
    return create_app(repo_root=ROOT, artifact_dir=tmp_path, auth_mode="cloudflare",
                      access_team_domain=ISSUER, access_aud=AUDIENCE)


@pytest.fixture
def console(tmp_path, signing, monkeypatch):
    # Keep session creation, setup and forks real; do not start paid model calls.
    monkeypatch.setattr(Service, "reply", lambda self, sid, request: self.accepted(self.store.load(sid)))
    app = private_app(tmp_path)
    with TestClient(app) as client:
        yield app, client, signing


def start(client, headers, question):
    response = client.post("/api/sessions", headers=headers,
                           json={"question": question, "provider": "openai"})
    assert response.status_code == 200, response.text
    return response.json()["session"]["session_id"]


def service_for(app, headers):
    access = CloudflareAccess(ISSUER, AUDIENCE)
    return app.state.user_services.get(access.verify(headers["Cf-Access-Jwt-Assertion"]))


def test_identity_is_required_for_pages_and_api(console):
    app, client, headers = console
    for path in ["/", "/static/app.js", "/docs", "/openapi.json",
                 "/api/methods", "/api/sessions"]:
        for forged in [{}, {"Cf-Access-Authenticated-User-Email": "alice@example.org"},
                       {"Cf-Access-Jwt-Assertion": "not-a-signed-token"}]:
            response = client.get(path, headers=forged)
            assert response.status_code == 401
            assert "no-store" in response.headers["cache-control"]
    assert client.get("/", headers=headers()).status_code == 200
    assert client.get("/api/methods", headers=headers()).status_code == 200
    assert not list(app.state.user_services.services.values())[0].sessions()


@pytest.mark.parametrize("overrides", [
    {"exp": 1}, {"iat": int(time.time()) + 3600}, {"iss": "https://other.cloudflareaccess.com"},
    {"aud": "another-app"}, {"sub": ""}, {"email": ""}, {"email": None},
])
def test_invalid_claims_are_rejected(console, overrides):
    _, client, headers = console
    assert client.get("/api/sessions", headers=headers(**overrides)).status_code == 401


def test_forged_signature_is_rejected(console):
    _, client, headers = console
    token = headers()["Cf-Access-Jwt-Assertion"].split(".")
    token[-1] = ("A" if token[-1][0] != "A" else "B") + token[-1][1:]
    response = client.get("/api/sessions", headers={"Cf-Access-Jwt-Assertion": ".".join(token)})
    assert response.status_code == 401


def test_users_have_separate_tasks_after_restart_and_email_change(console, tmp_path):
    app, client, headers = console
    # Pre-existing private/local sessions are not assigned to the first visitor.
    legacy = Service(ROOT, tmp_path)
    old_sid = legacy.store.create("Old local research", "openai")["session_id"]
    legacy.views.close()
    alice = start(client, headers(), "Alice's private research")
    bob = start(client, headers("bob"), "Bob's private research")
    for who, sid in [("alice", alice), ("bob", bob)]:
        response = client.get("/api/sessions", headers=headers(who))
        assert [row["session_id"] for row in response.json()["sessions"]] == [sid]
        assert "no-store" in response.headers["cache-control"]
        assert client.get(f"/api/sessions/{sid}", headers=headers(who)).status_code == 200
        assert client.get(f"/api/sessions/{old_sid}", headers=headers(who)).status_code == 404
    # Caller-supplied identity fields do not select a different user's store.
    assert client.get("/api/sessions?user=bob&owner=bob", headers=headers()).json()["sessions"][0]["session_id"] == alice
    with TestClient(private_app(tmp_path)) as restarted:
        result = restarted.get("/api/sessions", headers=headers(email="renamed@example.org"))
        assert [row["session_id"] for row in result.json()["sessions"]] == [alice]


@pytest.mark.parametrize("historical", [False, True])
def test_every_session_endpoint_rejects_other_users_before_side_effects(console, historical):
    app, client, headers = console
    sid = start(client, headers(), "Private analysis")
    service = service_for(app, headers())
    if historical:
        state = service.store.load(sid)
        sid = "bridge_" + sid.removeprefix("session_")
        state["session_id"] = sid
        (service.store.directory(sid) / "workspace").mkdir(parents=True)
        service.store.save(state)
    before = service.store.load(sid)
    for route in app.routes:
        path = getattr(route, "path", "")
        if "{sid}" not in path:
            continue
        path = path.replace("{sid}", sid)
        for method in route.methods:
            response = client.request(method, path, headers=headers("bob"),
                                      params={"summary": "workspace/result.txt"})
            assert response.status_code == 404, (method, path, response.text)
    assert service.store.load(sid) == before
    assert not (service.store.directory(sid) / "STOP").exists()


def test_session_api_contract_and_historical_access(console):
    app, client, headers = console
    sid = start(client, headers(), "Session naming")
    assert sid.startswith("session_")
    service = service_for(app, headers())
    state = service.store.load(sid)
    historical = "bridge_" + sid.removeprefix("session_")
    state["session_id"] = historical
    directory = service.store.directory(historical)
    (directory / "workspace").mkdir(parents=True)
    service.store.save(state)
    (directory / "workspace/result.md").write_text("[Data](workspace/result.csv)")
    (directory / "workspace/result.csv").write_text("x,y\n1,2\n")
    before = service.store.checkpoint_path(historical).read_bytes()
    path = f"/api/sessions/{historical}"
    snapshot = client.get(path, headers=headers()).json()
    assert snapshot["session_id"] == snapshot["state"]["session_id"] == historical
    assert "bridge_id" not in snapshot and "bridge_id" not in snapshot["state"]
    link = client.get(path + "/artifacts/markdown", headers=headers(),
                      params={"summary": "workspace/result.md"}).json()["html"]
    assert f"/api/sessions/{historical}/artifacts/raw" in link
    assert client.get(path + "/artifacts/spreadsheet", headers=headers(),
                      params={"summary": "workspace/result.csv"}).json()["rows"] == [["1", "2"]]
    copied = client.post(path + "/fork", headers=headers()).json()["session"]["session_id"]
    assert copied.startswith("session_")
    assert service.store.checkpoint_path(historical).read_bytes() == before
    assert directory.is_dir()
    assert client.get(f"/api/sessions/{copied}", headers=headers("bob")).status_code == 404
    reply = client.post(path + "/mr/reply", headers=headers(), json={"reply": "Continue"})
    assert reply.json()["session"]["session_id"] == historical
    assert client.post(path + "/stop", headers=headers()).status_code == 200
    assert not any("/api/bridge" in route.path for route in app.routes)
    for obsolete in ["/api/bridge/sessions", f"/api/bridge/sessions/{historical}"]:
        assert client.get(obsolete, headers=headers()).status_code == 404


def test_manual_uploads_results_and_forks_stay_private(console):
    app, client, headers = console
    response = client.post("/api/manual-sessions", headers=headers(),
                           data={"analysis_request": "Uploaded data", "provider": "openai",
                                 "exposure_manifest": '[{"file_index":0}]'},
                           files={"exposure_files": ("input.csv", b"x,y\n1,2\n", "text/csv")})
    assert response.status_code == 200, response.text
    sid = response.json()["session"]["session_id"]
    service = service_for(app, headers())
    ref = service.store.load(sid)["study_setup"]["exposures"][0]["file_ref"]
    path = f"/api/sessions/{sid}"
    assert client.get(path + "/artifacts/raw", headers=headers(), params={"summary": ref}).content == b"x,y\n1,2\n"
    sheet = client.get(path + "/artifacts/spreadsheet", headers=headers(), params={"summary": ref})
    assert sheet.json()["rows"] == [["1", "2"]]
    (service.store.directory(sid) / "workspace/result.md").write_text("# Private finding")
    assert client.get(path + "/artifacts/markdown", headers=headers(), params={"summary": "workspace/result.md"}).status_code == 200
    forked = client.post(path + "/fork", headers=headers())
    assert forked.status_code == 200, forked.text
    copied = forked.json()["session"]["session_id"]
    assert copied != sid
    assert client.get(f"/api/sessions/{copied}", headers=headers("bob")).status_code == 404
    assert client.get("/api/sessions", headers=headers("bob")).json() == {"sessions": []}


def test_symlinks_and_paths_cannot_cross_user_stores(console):
    app, client, headers = console
    sid = start(client, headers(), "Alice")
    bob_sid = start(client, headers("bob"), "Bob")
    alice = service_for(app, headers())
    bob = service_for(app, headers("bob"))
    secret = alice.store.directory(sid) / "workspace/secret.txt"
    secret.write_text("private")
    bob.store.directory(sid).symlink_to(alice.store.directory(sid), target_is_directory=True)
    assert [row["session_id"] for row in client.get("/api/sessions", headers=headers("bob")).json()["sessions"]] == [bob_sid]
    assert client.get(f"/api/sessions/{sid}", headers=headers("bob")).status_code == 404
    (bob.store.directory(bob_sid) / "workspace/leak").symlink_to(secret)
    for ref in [str(secret), "workspace/leak", "../../" + sid + "/workspace/secret.txt"]:
        assert client.get(f"/api/sessions/{bob_sid}/artifacts/raw", headers=headers("bob"), params={"summary": ref}).status_code == 403


def test_simultaneous_requests_keep_their_identity(console):
    _, client, headers = console
    alice, bob = headers(), headers("bob")
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda pair: start(client, *pair),
                            [(alice, "a1"), (bob, "b1"), (alice, "a2"), (bob, "b2")]))
    for user, expected in [(alice, {ids[0], ids[2]}), (bob, {ids[1], ids[3]})]:
        actual = client.get("/api/sessions", headers=user).json()["sessions"]
        assert {row["session_id"] for row in actual} == expected


def test_cross_origin_changes_are_rejected(console):
    _, client, headers = console
    for extra in [{"Origin": "https://another-site.example"}, {"Sec-Fetch-Site": "cross-site"}]:
        response = client.post("/api/sessions", headers=headers() | extra,
                               json={"question": "Unwanted task"})
        assert response.status_code == 403
    assert client.get("/api/sessions", headers=headers()).json() == {"sessions": []}
    assert start(client, headers() | {"Origin": "http://testserver"}, "Allowed")


def test_stream_uses_its_user_store_and_stops_at_sign_in_expiry(console):
    app, client, headers = console
    sid = start(client, headers(), "Stream")
    service = service_for(app, headers())
    endpoint = next(route.endpoint for route in app.routes
                    if getattr(route, "path", "") == "/api/sessions/{sid}/events")
    class Request:
        state = SimpleNamespace(service=service, access_expires_at=time.time() - 1)
        async def is_disconnected(self): return False
    async def scenario():
        response = await endpoint(sid, Request())
        stream = response.body_iterator
        assert sid in await anext(stream)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    asyncio.run(scenario())


def test_unavailable_signing_keys_fail_closed(console):
    _, client, headers = console
    with patch.object(jwt.PyJWKClient, "get_signing_key_from_jwt",
                      side_effect=jwt.PyJWKClientConnectionError("unavailable")):
        assert client.get("/api/sessions", headers=headers()).status_code == 503


def test_cloudflare_configuration_is_required(tmp_path):
    for domain, aud in [(None, None), ("http://example.org", AUDIENCE),
                        (ISSUER, None), ("https://example.org/path", AUDIENCE)]:
        with pytest.raises(ValueError):
            create_app(repo_root=ROOT, artifact_dir=tmp_path, auth_mode="cloudflare",
                       access_team_domain=domain, access_aud=aud)


def test_local_console_rejects_access_logins(tmp_path, signing):
    with TestClient(create_app(repo_root=ROOT, artifact_dir=tmp_path)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/sessions", headers=signing()).status_code == 503


def test_authenticated_workers_keep_their_store_after_restart(tmp_path, signing, gateway, monkeypatch):
    monkeypatch.setenv("MRCAT_CONTEXT_TOKENS", "131072")
    monkeypatch.setenv("MRCAT_MAX_OUTPUT_TOKENS", "32768")
    monkeypatch.setenv("MRCAT_MODEL_CONTEXT_TOKENS", "{}")
    app = private_app(tmp_path)
    with TestClient(app) as browser:
        # Distinct clients simulate separate browser sign-ins, with real workers
        # and a local deterministic model gateway (no external model calls).
        with TestClient(app, headers=signing()) as alice, \
             TestClient(app, headers=signing("bob")) as bob:
            alice_sid = start(alice, {}, "calculate for Alice")
            bob_sid = start(bob, {}, "calculate for Bob")
            for client, sid, who in [(alice, alice_sid, "alice"), (bob, bob_sid, "bob")]:
                wait(client, sid, lambda snapshot: snapshot["state"]["status"] == "completed")
                service = service_for(app, signing(who))
                assert (service.store.directory(sid) / "workspace/answer.txt").read_text() == "42"
                assert client.get(f"/api/sessions/{sid}/artifacts/raw",
                                  params={"summary": "workspace/answer.txt"}).text == "42"
            assert bob.get(f"/api/sessions/{alice_sid}").status_code == 404
    with TestClient(private_app(tmp_path), headers=signing()) as alice:
        assert [row["session_id"] for row in alice.get("/api/sessions").json()["sessions"]] == [alice_sid]
        assert alice.get(f"/api/sessions/{alice_sid}").json()["state"]["status"] == "completed"
