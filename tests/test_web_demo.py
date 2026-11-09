"""Public demo admission, ownership and real service wiring (no paid model calls)."""
from hashlib import sha256
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from mrcat.web.server import create_app
from mrcat.web.service import Service
from test_agent import ROOT


def demo_fixture(tmp_path):
    root = tmp_path / "root"
    (root / "mrcat/web").mkdir(parents=True)
    (root / "mrcat/web/static").symlink_to(ROOT / "mrcat/web/static", target_is_directory=True)
    (root / "skills").symlink_to(ROOT / "skills", target_is_directory=True)
    example = root / "examples/bmi_t2d"
    example.mkdir(parents=True)
    data = tmp_path / "data"
    data.mkdir()
    inventory = []
    for name in ("bmi_mrapss.gz", "t2d_mrapss.gz"):
        content = b"SNP\tA1\tA2\tbeta\tse\tP\nrs1\tA\tC\t0.1\t0.02\t1e-9\n"
        (data / name).write_bytes(content)
        inventory.append(dict(filename=name, size_bytes=len(content), sha256=sha256(content).hexdigest()))
    (example / "local_inputs.json").write_text(json.dumps(inventory))
    return dict(repo_root=root, artifact_dir=tmp_path / "runs", auth_mode="demo", demo_data_dir=data)


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.delenv("MRCAT_DEMO_ONLINE_CACHE", raising=False)
    monkeypatch.setenv("MRCAT_DEMO_DAILY_TURNS", "40")
    def complete(self, sid, request):
        saved = self.store.load(sid)
        saved.update(status="completed", pending=None, job=None, active_task=None)
        self.store.event(saved, "user_message", request)
        self.store.save(saved)
        return self.accepted(saved)
    monkeypatch.setattr(Service, "reply", complete)
    args = demo_fixture(tmp_path)
    app = create_app(**args)
    with TestClient(app) as client:
        yield app, client, args


def start(app, client):
    client.get("/")
    catalog = app.state.user_services.catalog
    response = client.post("/api/sessions", json={"question": catalog["steps"][0]["prompt"], "provider": "untrusted-provider"})
    assert response.status_code == 200, response.text
    return response.json()["session"]["session_id"]


def service_for(app, sid):
    return next(service for service in app.state.user_services.services.values() if service.store.directory(sid).is_dir())


def test_guided_sequence_native_files_and_followup(demo):
    app, client, args = demo
    sid = start(app, client)
    service = service_for(app, sid)
    assert service.store.load(sid)["provider"] == os.getenv("MRCAT_DEMO_PROVIDER", "deepseek")
    catalog = app.state.user_services.catalog
    def reply(prompt):
        return client.post(f"/api/sessions/{sid}/mr/reply", json={"reply": prompt})
    assert reply(catalog["steps"][3]["prompt"]).status_code == 400
    assert reply("Execute arbitrary code").status_code == 400
    assert reply(catalog["confirm"]).status_code == 400
    assert reply(catalog["steps"][1]["prompt"]).status_code == 200
    saved = service.store.load(sid)
    saved.update(status="waiting_user", pending={"kind": "plan_confirmation", "question": "Confirm?"})
    service.store.save(saved)
    assert reply(catalog["steps"][2]["prompt"]).status_code == 400
    assert reply(catalog["confirm"]).status_code == 200
    assert reply(catalog["steps"][2]["prompt"]).status_code == 200
    saved = service.store.load(sid)
    source = Path(args["demo_data_dir"]) / "bmi_mrapss.gz"
    target = service.store.directory(sid) / saved["study_setup"]["exposures"][0]["file_ref"]
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_ino != source.stat().st_ino
    assert reply(catalog["steps"][3]["prompt"]).status_code == 200
    assert reply(catalog["steps"][3]["prompt"]).status_code == 400
    snapshot = client.get(f"/api/sessions/{sid}").json()
    assert [e["content"] for e in snapshot["mr"]["events"] if e["type"] == "user_message"] == [
        catalog["steps"][0]["prompt"], catalog["steps"][1]["prompt"], catalog["confirm"],
        catalog["steps"][2]["prompt"], catalog["steps"][3]["prompt"],
    ]
    assert client.post("/api/sessions", json={"question": catalog["steps"][0]["prompt"]}).status_code == 400


def test_anonymous_ownership_survives_restart_and_blocks_bypasses(demo):
    app, alice, args = demo
    sid = start(app, alice)
    cookie = alice.cookies.get("mrcat_demo_visitor")
    assert 'data-live-demo="true"' in alice.get("/").text
    with TestClient(app) as bob:
        assert bob.get("/api/sessions").json() == {"sessions": []}
        assert bob.get(f"/api/sessions/{sid}").status_code == 404
        assert bob.post(f"/api/sessions/{sid}/stop").status_code == 404
        assert bob.get(f"/api/sessions/{sid}/artifacts/raw?summary=workspace/test.txt").status_code == 404
    for endpoint in ("/api/manual-sessions", f"/api/sessions/{sid}/fork", f"/api/sessions/{sid}/study-setup", f"/api/sessions/{sid}/scientific-report"):
        assert alice.post(endpoint, json={}).status_code == 403
    assert alice.post(f"/api/sessions/{sid}/mr/reply", headers={"origin": "https://evil.example"}, json={"reply": "x"}).status_code == 403
    assert alice.post(f"/api/sessions/{sid}/mr/reply", content=b"x" * 20000).status_code == 413
    with TestClient(create_app(**args)) as restarted:
        restarted.cookies.set("mrcat_demo_visitor", cookie)
        assert restarted.get(f"/api/sessions/{sid}").status_code == 200
        assert len(restarted.get("/api/sessions").json()["sessions"]) == 1


def test_global_admission_and_daily_allowance(demo, monkeypatch):
    app, client, _ = demo
    sid = start(app, client)
    service = service_for(app, sid)
    saved = service.store.load(sid)
    saved["job"] = {"status": "running", "pid": os.getpid()}
    service.store.save(saved)
    with TestClient(app) as bob:
        bob.get("/")
        response = bob.post("/api/sessions", json={"question": app.state.user_services.catalog["steps"][0]["prompt"]})
        assert response.status_code == 409
    saved["job"] = None
    service.store.save(saved)
    monkeypatch.setenv("MRCAT_DEMO_DAILY_TURNS", "1")
    response = client.post(f"/api/sessions/{sid}/mr/reply", json={"reply": app.state.user_services.catalog["steps"][1]["prompt"]})
    assert response.status_code == 429


def test_input_integrity_is_required(tmp_path, monkeypatch):
    monkeypatch.delenv("MRCAT_DEMO_ONLINE_CACHE", raising=False)
    args = demo_fixture(tmp_path)
    (args["demo_data_dir"] / "bmi_mrapss.gz").write_bytes(b"wrong input")
    with pytest.raises(ValueError, match="incorrect demo input"):
        create_app(**args)


def test_online_cache_is_copied_without_temporary_download_urls(demo, tmp_path, monkeypatch):
    _, _, args = demo
    cache = tmp_path / "online-cache"
    for study_id in ("ieu-b-40", "ebi-a-GCST006867"):
        directory = cache / "opengwas" / study_id / "download-key"
        directory.mkdir(parents=True)
        content = b"SNP\tbeta\tse\nrs1\t0.1\t0.02\n"
        (directory / f"{study_id}.tsv.gz").write_bytes(content)
        (directory / ".gwas-download-complete.json").write_text(json.dumps({
            "source": "opengwas", "study_id": study_id, "file_size": len(content),
            "download_url": "https://example.org/private-temporary-download-token",
            "study_metadata": {"population": "European"},
        }))
    monkeypatch.setenv("MRCAT_DEMO_ONLINE_CACHE", str(cache))
    app = create_app(**args)
    with TestClient(app) as client:
        sid = start(app, client)
        prompt = app.state.user_services.catalog["steps"][1]["prompt"]
        assert client.post(f"/api/sessions/{sid}/mr/reply", json={"reply": prompt}).status_code == 200
        service = service_for(app, sid)
        inventory_path = service.store.directory(sid) / "workspace/inputs/online_gwas_sources.json"
        assert "temporary-download-token" not in inventory_path.read_text()
        for item in json.loads(inventory_path.read_text()):
            target = service.store.directory(sid) / item["file_ref"]
            assert sha256(target.read_bytes()).hexdigest() == item["sha256"]
            assert service.artifact(sid, item["file_ref"]) == target
