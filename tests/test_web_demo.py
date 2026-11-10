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
    assert client.post("/api/sessions", json={"question": "Another session"}).status_code == 400


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


def test_input_integrity_is_required(tmp_path, monkeypatch):
    monkeypatch.delenv("MRCAT_DEMO_ONLINE_CACHE", raising=False)
    args = demo_fixture(tmp_path)
    (args["demo_data_dir"] / "bmi_mrapss.gz").write_bytes(b"wrong input")
    with pytest.raises(ValueError, match="incorrect demo input"):
        create_app(**args)


@pytest.mark.parametrize("with_cache", [False, True])
def test_online_inputs_reach_planner_without_ids_in_query(demo, tmp_path, monkeypatch, with_cache):
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
    if with_cache:
        monkeypatch.setenv("MRCAT_DEMO_ONLINE_CACHE", str(cache))
    app = create_app(**args)
    with TestClient(app) as client:
        sid = start(app, client)
        prompt = app.state.user_services.catalog["steps"][1]["prompt"]
        assert client.post(f"/api/sessions/{sid}/study-setup", data=setup_payload(app.state.user_services.catalog["steps"][1], prompt)).status_code == 200
        service = service_for(app, sid)
        assert "ieu-b-40" not in prompt and "workspace/" not in prompt

        def planner_setup(request):
            saved = service.store.load(sid)
            saved["active_agent"] = "mr"
            model = Model()
            Agent(ROOT, service.store, model=model)._plan(saved, request, "Plan the example")
            return json.loads(model.calls[0]["user"])["study_setup"]

        setup = planner_setup(prompt)
        assert "ieu-b-40" in setup["exposures"][0]["name"]
        assert "ebi-a-GCST006867" in setup["outcomes"][0]["name"]
        assert setup["sources"] == ["opengwas"]
        inventory_path = service.store.directory(sid) / "workspace/inputs/online_gwas_sources.json"
        if with_cache:
            assert "temporary-download-token" not in inventory_path.read_text()
            for item, row in zip(json.loads(inventory_path.read_text()), setup["exposures"] + setup["outcomes"]):
                assert row["file_ref"] == item["file_ref"]
                target = service.store.directory(sid) / row["file_ref"]
                assert sha256(target.read_bytes()).hexdigest() == item["sha256"]
                assert service.artifact(sid, item["file_ref"]) == target
        else:
            assert not inventory_path.exists()
            assert all("file_ref" not in row for row in setup["exposures"] + setup["outcomes"])

        steps = app.state.user_services.catalog["steps"]
        assert client.post(f"/api/sessions/{sid}/study-setup", data=setup_payload(steps[2], steps[2]["prompt"])).status_code == 200
        local_setup = planner_setup(steps[2]["prompt"])
        assert local_setup["exposures"] == [{"name": "BMI", "file_ref": "workspace/inputs/bmi_mrapss.gz"}]
        assert local_setup["outcomes"] == [{"name": "Type 2 diabetes", "file_ref": "workspace/inputs/t2d_mrapss.gz"}]
        assert client.post(f"/api/sessions/{sid}/mr/reply", json={"reply": steps[3]["prompt"]}).status_code == 200
        assert planner_setup(steps[3]["prompt"]) == local_setup
