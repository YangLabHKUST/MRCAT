"""A published recording is static, credential-free and preserves the source."""
import importlib.util
import json
from pathlib import Path

import pytest

from mrcat.state.store import Store


def exporter():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("result4_export", root / "examples/result4/export_recording.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_result4_static_export_preserves_source_and_excludes_private_files(tmp_path):
    store = Store(tmp_path / "sessions")
    state = store.create("Synthetic completed analysis", "openai")
    session = store.directory(state["session_id"])
    report = session / "workspace/reports/fixture"
    report.mkdir(parents=True)
    (report / "final_summary.md").write_text("Completed report")
    (report / "scientific_report.html").write_text("<html><body>Recorded results</body></html>")
    state["role_memory"] = {"report": {"report_run_id": "fixture"}}
    secret = "synthetic-result4-secret-do-not-publish"
    env = tmp_path / ".env"
    env.write_text(f"OPENAI_API_KEY={secret}\n")
    result = session / "workspace/results.tsv"
    result.write_text(f"beta\tpath\ttoken\n0.2\t{session}\t{secret}\n")
    (session / "workspace/audit.py").write_text("private checks")
    (session / "workspace/.env").write_text(env.read_text())
    (session / "workspace/large.tsv").write_text("x" * 4_000_001)
    for kind in ["user_message", "task_created"] + ["code_execution"] * 10 + ["final", "user_message", "task_created", "final", "user_message", "report_started", "final"]:
        store.event(state, kind, "Recorded event", generated_files=["workspace/results.tsv", "workspace/audit.py"], stdout=secret)
    state["status"] = "completed"
    store.save(state)
    before = store.load(state["session_id"])
    module = exporter()
    output, site = tmp_path / "recording", tmp_path / "site"
    module.export(session, output, env_files=[env], site=site)
    saved = json.loads((output / "recording.json").read_text())
    assert saved["provenance"]["source_session_id"] == state["session_id"]
    assert saved["snapshot"]["state"]["status"] == "completed"
    assert saved["snapshot"]["active_job"] is None
    assert len(saved["stages"]) == 4
    assert saved["stages"][2]["start"] == 13  # Includes the replication request.
    assert "workspace/results.tsv" in saved["files"]
    assert not any("audit" in p or ".env" in p or "large.tsv" in p for p in saved["files"])
    for p in output.rglob("*"):
        if p.is_file():
            assert secret.encode() not in p.read_bytes()
            assert str(session).encode() not in p.read_bytes()
    preview = json.loads((output / saved["files"]["workspace/results.tsv"]["preview"]).read_text())
    assert preview["rows"][0][0] == "0.2"
    assert 'data-replay-only="true"' in (site / "index.html").read_text()
    assert not list(site.rglob("*.sqlite"))
    assert not list(site.rglob("*.py"))
    assert store.load(state["session_id"]) == before
    assert secret in result.read_text()


def test_reject_incomplete_session(tmp_path):
    store = Store(tmp_path / "sessions")
    state = store.create("Incomplete session", "openai")
    with pytest.raises(ValueError, match="completed, idle"):
        exporter().export(store.directory(state["session_id"]), tmp_path / "recording")
