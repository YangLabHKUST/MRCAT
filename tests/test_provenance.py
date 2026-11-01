import json
from pathlib import Path
import subprocess

import pytest

from mrcat.provenance import capture, file_record, source_version


def test_frozen_source_rejects_dirty_wrong_commit_and_ignored_code(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()
    git("init", "-q")
    (tmp_path / "config.yaml").write_text("{}")
    (tmp_path / ".gitignore").write_text("ignored.py\n")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "fixture")
    commit = git("rev-parse", "HEAD")
    assert source_version(tmp_path, commit)["dirty"] is False
    with pytest.raises(ValueError, match="expected full commit"):
        source_version(tmp_path, "0" * 40)
    (tmp_path / "config.yaml").write_text("changed")
    with pytest.raises(ValueError, match="clean checkout"):
        source_version(tmp_path, commit)
    git("restore", "config.yaml")
    (tmp_path / "mrcat").mkdir()
    (tmp_path / "mrcat/ignored.py").write_text("print('unexpected')")
    with pytest.raises(ValueError, match="Untracked executable"):
        source_version(tmp_path, commit)


def test_capture_records_input_changes_without_credentials(tmp_path, monkeypatch):
    from mrcat.config.loader import load_repo_config
    root = Path(__file__).resolve().parents[1]
    config = load_repo_config(repo_root=root).config
    data = tmp_path / "data.tsv"
    data.write_text("a\n1\n")
    query = tmp_path / "query.txt"
    query.write_text(f"Q01: Analyze {data}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-value-must-not-be-saved")
    monkeypatch.setenv("UNRELATED_SECRET", "secret-value-must-not-be-saved")
    record = capture(root, query, [dict(query=str(data))], config, dict(commit="fixture"))
    assert "secret-value-must-not-be-saved" not in json.dumps(record)
    assert record["input_files"] == [file_record(data)]
    before = record["input_files"][0]["sha256"]
    data.write_text("a\n2\n")
    assert file_record(data)["sha256"] != before
    assert file_record(tmp_path / "missing")["missing"] is True
