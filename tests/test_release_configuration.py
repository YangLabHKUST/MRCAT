"""Public installation boundaries and explicit provider failure behavior."""
from pathlib import Path

import pytest

from mrcat.config.loader import load_repo_config
from mrcat.database import database
from mrcat.model import llm_gateway


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_sdk_error_is_reported_without_another_transport(monkeypatch, provider):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("LLM_BACKEND", "sdk")
    name = "_call_anthropic_sdk" if provider == "anthropic" else "_call_openai_compatible_sdk"

    def fail(**kwargs):
        raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(llm_gateway, name, fail)
    monkeypatch.setattr(llm_gateway, "_call_text_http", lambda **kwargs: pytest.fail("Unexpected transport switch"))
    with pytest.raises(RuntimeError, match="upstream unavailable"):
        llm_gateway.call_text("system", "user")


def test_configuration_directory_is_independent_of_installed_code(tmp_path, monkeypatch):
    config = tmp_path / "configuration"
    config.mkdir()
    (config / "config.yaml").write_text("llm:\n  gateway:\n    provider: custom\n    base_url: https://example.invalid/v1\n")
    monkeypatch.setenv("MRCAT_CONFIG_DIR", str(config))
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("CUSTOM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    loaded = load_repo_config(repo_root=tmp_path / "installed")
    assert loaded.path == config / "config.yaml"
    assert loaded.config.llm.gateway.provider == "custom"
    assert loaded.config.llm.gateway.base_url == "https://example.invalid/v1"


def test_database_override_does_not_require_code_in_the_data_directory(tmp_path, monkeypatch):
    reference = tmp_path / "references"
    data = reference / "hapmap3/w_hm3.snplist.rda"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"reference fixture")
    monkeypatch.setenv("MRCAT_DATABASE_DIR", str(reference))
    assert database("hapmap3.snplist_rdata", workspace_dir=tmp_path / "installed") == data


@pytest.mark.parametrize("removed", ["runtime: {recursion_limit: 200}", "llm: {max_tokens: {draft_plan: 1024}}"])
def test_obsolete_configuration_does_not_silently_appear_effective(tmp_path, monkeypatch, removed):
    monkeypatch.delenv("MRCAT_CONFIG_DIR", raising=False)
    (tmp_path / "config.yaml").write_text(removed)
    with pytest.raises(ValueError, match="unsupported key"):
        load_repo_config(repo_root=tmp_path)
