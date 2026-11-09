"""Installed code must use separately configured settings and reference data."""
import os
from pathlib import Path

import yaml

from mrcat.config.env import load_repo_dotenv
from mrcat.config.loader import load_repo_config
from mrcat.database import database
from mrcat.resource_docs import read_resource_doc, resource_docs


def test_settings_directory_is_independent_of_installed_code(tmp_path, monkeypatch):
    settings = tmp_path / "settings"
    settings.mkdir()
    payload = yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text())
    payload["llm"]["gateway"].update(provider="custom", base_url="https://example.invalid/v1")
    (settings / "config.yaml").write_text(yaml.safe_dump(payload))
    (settings / ".env").write_text("MRCAT_INSTALLATION_FIXTURE=file\n")
    monkeypatch.setenv("MRCAT_CONFIG_DIR", str(settings))
    monkeypatch.setenv("MRCAT_INSTALLATION_FIXTURE", "exported")
    for name in ("LLM_PROVIDER", "LLM_BASE_URL", "CUSTOM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    installed = tmp_path / "installed"
    loaded = load_repo_config(repo_root=installed)
    assert loaded.path == settings / "config.yaml"
    assert loaded.config.llm.gateway.provider == "custom"
    assert loaded.config.llm.gateway.base_url == "https://example.invalid/v1"
    assert load_repo_dotenv(repo_root=installed).path == settings / ".env"
    assert os.environ["MRCAT_INSTALLATION_FIXTURE"] == "exported"


def test_reference_data_and_notes_share_the_external_directory(tmp_path, monkeypatch):
    reference = tmp_path / "references"
    data = reference / "hapmap3/w_hm3.snplist.rda"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"reference fixture")
    note = reference / "docs/mrlap.md"
    note.parent.mkdir()
    note.write_text("External method note.")
    monkeypatch.setenv("MRCAT_DATABASE_DIR", str(reference))
    installed = tmp_path / "installed"
    assert database("hapmap3.snplist_rdata", workspace_dir=installed) == data
    assert resource_docs(installed)[0]["available"]
    assert "External method note." in read_resource_doc("mrlap", workspace_dir=installed)
