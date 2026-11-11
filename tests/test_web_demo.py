"""Public demo admission, ownership and real service wiring (no paid model calls)."""
from hashlib import sha256
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from mrcat.web.server import create_app
from mrcat.web.service import Service
from test_agent import ROOT, Model
from mrcat.agent import Agent


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


def setup_payload(step, request):
    setup = step["setup"]
    return dict(exposure_manifest=json.dumps(setup["exposures"]),
                outcome_manifest=json.dumps(setup["outcomes"]),
                methods=json.dumps(setup["methods"]), sources=json.dumps(setup["sources"]),
                analysis_request=request)


def test_free_text_start_followup_and_pending_plan_reply(demo):
    app, client, _ = demo
    client.get("/")
    question = "What evidence would make an MR result convincing?"
    response = client.post("/api/sessions", json={"question": question, "provider": "untrusted"})
    assert response.status_code == 200
    sid = response.json()["session"]["session_id"]
    service = service_for(app, sid)
    assert service.store.load(sid)["provider"] == os.getenv("MRCAT_DEMO_PROVIDER", "deepseek")
    followup = "Please explain this in Chinese."
    endpoint = f"/api/sessions/{sid}/mr/reply"
    assert client.post(endpoint, json={"reply": followup}).status_code == 200
    saved = service.store.load(sid)
    saved.update(status="waiting_user", pending={"kind": "plan_confirmation", "question": "Confirm?"})
    service.store.save(saved)
    revision = "Change the proposed method before running."
    assert client.post(endpoint, json={"reply": revision}).status_code == 200
    messages = [e["content"] for e in service.store.load(sid)["events"] if e["type"] == "user_message"]
    assert messages == [question, followup, revision]
    assert client.post(endpoint, json={"reply": "  "}).status_code == 400
    second = client.post("/api/sessions", json={"question": "Another session"})
    assert second.status_code == 200
    second_sid = second.json()["session"]["session_id"]
    assert second_sid != sid
    assert {item["session_id"] for item in client.get("/api/sessions").json()["sessions"]} == {sid, second_sid}
    assert service.store.load(sid)["question"] == question
    assert service.store.load(second_sid)["question"] == "Another session"


def test_local_example_can_start_first_with_edited_request(demo):
    app, client, args = demo
    client.get("/")
    step = app.state.user_services.catalog["steps"][2]
    request = "Use these files for IVW and explain the uncertainty."
    response = client.post("/api/manual-sessions", data=setup_payload(step, request))
    assert response.status_code == 200, response.text
    sid = response.json()["session"]["session_id"]
    service = service_for(app, sid)
    saved = service.store.load(sid)
    assert saved["study_setup"]["analysis_request"] == request
    source = Path(args["demo_data_dir"]) / "bmi_mrapss.gz"
    target = service.store.directory(sid) / saved["study_setup"]["exposures"][0]["file_ref"]
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_ino != source.stat().st_ino
    assert [e["content"] for e in saved["events"] if e["type"] == "user_message"] == [request]
    followup = "Now compare this with MR-APSS."
    assert client.post(f"/api/sessions/{sid}/mr/reply", json={"reply": followup}).status_code == 200
    assert service.store.load(sid)["study_setup"] == saved["study_setup"]


def test_dataset_selection_rejects_unknown_files_and_running_job(demo):
    app, client, _ = demo
    client.get("/")
    step = app.state.user_services.catalog["steps"][2]
    payload = setup_payload(step, "Analyze these inputs.")
    payload["exposure_manifest"] = json.dumps([{"name": "BMI", "file_ref": "../../private.env"}])
    assert client.post("/api/manual-sessions", data=payload).status_code == 400
    assert client.get("/api/sessions").json() == {"sessions": []}
    sid = start(app, client)
    service = service_for(app, sid)
    saved = service.store.load(sid)
    saved["job"] = {"status": "running", "pid": os.getpid()}
    service.store.save(saved)
    assert client.post(f"/api/sessions/{sid}/study-setup", data=setup_payload(step, "Analyze these inputs.")).status_code == 409
    assert service.store.load(sid)["study_setup"] == {}


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
    for endpoint in (f"/api/sessions/{sid}/fork", f"/api/sessions/{sid}/scientific-report"):
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


def test_public_example_is_live_read_only_and_visitors_stay_isolated(demo):
    app, alice, args = demo
    public = app.state.user_services.public
    saved = public.store.create("Public analysis", "deepseek")
    sid = saved["session_id"]
    directory = public.store.directory(sid)
    (directory / "workspace/result.csv").write_text("method,beta\nIVW,0.2\n")
    (directory / "workspace/report.md").write_text("# Public result\n")
    # A stale job must not cause a GET to rewrite the published checkpoint.
    saved["job"] = {"status": "running", "pid": 99999999}
    public.store.save(saved)
    before = public.store.load(sid)
    with TestClient(app) as bob:
        for client in (alice, bob):
            assert f'data-public-sessions="{sid}"' in client.get("/").text
            assert client.get("/api/sessions").json()["sessions"][0]["session_id"] == sid
            assert client.get(f"/api/sessions/{sid}").status_code == 200
            assert client.get(f"/api/sessions/{sid}/artifacts/raw?summary=workspace/result.csv").text == "method,beta\nIVW,0.2\n"
            assert client.get(f"/api/sessions/{sid}/artifacts/markdown?summary=workspace/report.md").json()["markdown"] == "# Public result\n"
            assert client.get(f"/api/sessions/{sid}/artifacts/spreadsheet?summary=workspace/result.csv").json()["rows"] == [["IVW", "0.2"]]
            for action in ("mr/reply", "stop", "study-setup", "fork", "scientific-report", "search/reply"):
                assert client.post(f"/api/sessions/{sid}/{action}", json={"reply": "Change this"}).status_code == 403
            assert client.delete(f"/api/sessions/{sid}").status_code == 403
            assert client.get(f"/api/sessions/{sid}/artifacts/raw?summary=graph.sqlite").status_code == 403
            assert client.get(f"/api/sessions/{sid}/artifacts/raw?summary=../.visitor-key").status_code == 403
            assert client.get(f"/api/sessions/{sid}/artifacts/raw?summary=./memory.md").status_code == 404
        assert public.store.load(sid) == before
        assert not (directory / "memory.md").exists()
        assert not (directory / "STOP").exists()
        alice_sid = start(app, alice)
        assert {row["session_id"] for row in alice.get("/api/sessions").json()["sessions"]} == {sid, alice_sid}
        assert {row["session_id"] for row in bob.get("/api/sessions").json()["sessions"]} == {sid}
        assert bob.get(f"/api/sessions/{alice_sid}").status_code == 404
        assert bob.post(f"/api/sessions/{alice_sid}/stop").status_code == 404
        # Publication does not copy the session into visitor stores.
        assert not any((service.store.base / sid).exists() for service in app.state.user_services.services.values())
        updated = dict(before, question="Updated public analysis", job=None)
        public.store.save(updated)
        assert bob.get(f"/api/sessions/{sid}").json()["state"]["question"] == "Updated public analysis"
    with TestClient(create_app(**args)) as restarted:
        assert restarted.get("/api/sessions").json()["sessions"][0]["session_id"] == sid
        assert restarted.get(f"/api/sessions/{sid}").status_code == 200


def test_input_integrity_is_required(tmp_path, monkeypatch):
    monkeypatch.delenv("MRCAT_DEMO_ONLINE_CACHE", raising=False)
    args = demo_fixture(tmp_path)
    (args["demo_data_dir"] / "bmi_mrapss.gz").write_bytes(b"wrong input")
    with pytest.raises(ValueError, match="incorrect demo input"):
        create_app(**args)


@pytest.mark.parametrize("start_first", [False, True])
def test_online_query_reaches_planner_without_preset_studies(demo, tmp_path, monkeypatch, start_first):
    _, _, args = demo
    # A leftover deployment setting must not preload studies into an online query.
    monkeypatch.setenv("MRCAT_DEMO_ONLINE_CACHE", str(tmp_path / "obsolete-cache"))
    app = create_app(**args)
    with TestClient(app) as client:
        client.get("/")
        steps = app.state.user_services.catalog["steps"]
        assert "setup" not in steps[1]
        assert [step["id"] for step in steps if step.get("setup")] == ["local"]
        prompt = steps[1]["prompt"]
        if start_first:
            response = client.post("/api/sessions", json={"question": prompt})
            assert response.status_code == 200, response.text
            sid = response.json()["session"]["session_id"]
        else:
            sid = start(app, client)
            response = client.post(f"/api/sessions/{sid}/mr/reply", json={"reply": prompt})
            assert response.status_code == 200, response.text
        service = service_for(app, sid)

        def planner_setup(request):
            saved = service.store.load(sid)
            saved["active_agent"] = "mr"
            model = Model()
            Agent(ROOT, service.store, model=model)._plan(saved, request, "Plan the example")
            return json.loads(model.calls[0]["user"])["study_setup"]

        assert planner_setup(prompt) == {}
        directory = service.store.directory(sid)
        assert not list((directory / "workspace/inputs").rglob("*"))
        messages = [e["content"] for e in service.store.load(sid)["events"] if e["type"] == "user_message"]
        assert messages[-1] == prompt

        assert client.post(f"/api/sessions/{sid}/study-setup", data=setup_payload(steps[2], steps[2]["prompt"])).status_code == 200
        local_setup = planner_setup(steps[2]["prompt"])
        assert local_setup["exposures"] == [{"name": "BMI", "file_ref": "workspace/inputs/bmi_mrapss.gz"}]
        assert local_setup["outcomes"] == [{"name": "Type 2 diabetes", "file_ref": "workspace/inputs/t2d_mrapss.gz"}]
        for row in local_setup["exposures"] + local_setup["outcomes"]:
            target = directory / row["file_ref"]
            original = Path(args["demo_data_dir"]) / target.name
            assert target.read_bytes() == original.read_bytes()
            assert target.stat().st_ino != original.stat().st_ino
        assert client.post(f"/api/sessions/{sid}/mr/reply", json={"reply": steps[3]["prompt"]}).status_code == 200
        assert planner_setup(steps[3]["prompt"]) == local_setup
