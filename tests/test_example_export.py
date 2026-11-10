"""A public example must not expose credentials or mutate the source session."""
import importlib.util
import json
from pathlib import Path

from mrcat.store import Store


def test_recording_export_redacts_private_paths_and_preserves_source(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("example_export", root / "examples/bmi_t2d/export_recording.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = Store(tmp_path / "sessions")
    state = store.create("Synthetic export test", "openai")
    sid = state["session_id"]
    session = store.directory(sid)
    secret = "synthetic-private-token-for-export-test"
    env = tmp_path / "private.env"
    env.write_text(f"OPENAI_API_KEY={secret}\n")
    source = session / "workspace/result.json"
    signed_url = "https://example.oci.customer-oci.com/p/private-download-token/n/bucket/data.vcf.gz"
    original = json.dumps({"beta": .2, "path": str(session), "token": secret, "download": signed_url})
    source.write_text(original)
    (session / "workspace/.env").write_text(env.read_text())
    (session / "workspace/large.tsv").write_text("x" * 4_000_001)
    state["status"] = "completed"
    store.event(state, "code_execution", str(session), execution_id="fixture", status="exited", returncode=0,
                generated_files=["workspace/result.json", "workspace/large.tsv"], stdout=secret,
                stderr_path="executions/not-exported/stderr.log")
    store.save(state)
    run = tmp_path / "run.json"
    run.write_text(json.dumps(dict(session_id=sid, store=str(store.base), source_commit="fixture",
                                  model="fixture", provider="openai", recorded_at="fixture",
                                  stages=[dict(title=str(i), description="fixture", start=0, end=1,
                                               question="Synthetic test") for i in range(4)])))
    (tmp_path / "source_hashes.json").write_text("{}")
    (tmp_path / "environment.json").write_text("{}")
    target = tmp_path / "public"
    module.export(root, run, target, [env])
    tutorial = (target / "tutorial.md").read_text()
    for heading in ("### 1. Install", "### 2. Configure a model", "### 3. Start and try a question"):
        assert heading in tutorial
    assert "mrcat-web --port 7869" in tutorial
    assert "\n## Using the workspace\n" not in tutorial
    assert "[Reference data](#reference-data-setup)" in tutorial
    assert "https://github.com/77JULIE/MRCAT/blob/main/docs/configuration.md#choose-a-provider" in tutorial
    recording = json.loads((target / "recording.json").read_text())
    assert set(recording["files"]) == {"workspace/result.json"}
    for path in target.rglob("*"):
        if path.is_file():
            text = path.read_text()
            assert secret not in text
            assert "private-download-token" not in text
            assert str(session) not in text
    event = recording["snapshot"]["mr"]["events"][-1]
    assert event["details"]["generated_files"] == ["workspace/result.json"]
    assert "stderr_path" not in event["details"]
    assert recording["snapshot"]["session_id"] == "example-bmi-t2d"
    assert json.loads((target / "files/workspace/result.json").read_text())["beta"] == .2
    assert source.read_text() == original
    assert store.load(sid)["events"][-1]["details"]["stdout"] == secret
