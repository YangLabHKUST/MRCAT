from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
from typing import Any

import yaml

from mrcat.config.llm_limits import LLM_TIMEOUT_SECONDS


_DEFAULT_PROVIDER = "anthropic"
_DEFAULT_MODEL = "claude-opus-4-6"
_DEFAULT_BASE_URL = "https://api.anthropic.com"
_DEFAULT_TIMEOUT_SEC = LLM_TIMEOUT_SECONDS
_DEFAULT_RETRY_COUNT = 3
_SUPPORTED_PROVIDERS = ("anthropic", "openai", "deepseek", "qwen", "glm", "grok", "custom")
_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "anthropic": {"model": "claude-opus-4-6", "base_url": "https://api.anthropic.com"},
    "openai": {"model": "gpt-4.1", "base_url": "https://api.openai.com/v1"},
    "deepseek": {"model": "deepseek-chat", "base_url": "https://api.deepseek.com"},
    "qwen": {"model": "qwen-plus", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
    "glm": {"model": "glm-4-plus", "base_url": "https://open.bigmodel.cn/api/paas/v4"},
    "grok": {"model": "grok-2-latest", "base_url": "https://api.x.ai/v1"},
    "custom": {"model": "custom-model", "base_url": ""},
}
_ROLE_MODEL_ENV_NAMES = {
    "reporter": "REPORTER_MODEL",
}


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    provider: str = _DEFAULT_PROVIDER
    backend: str = "sdk"
    base_url: str = _DEFAULT_BASE_URL
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC
    retry_count: int = _DEFAULT_RETRY_COUNT


@dataclass(frozen=True, slots=True)
class RoleModelOverrides:
    reporter: str | None = None

    def for_role(self, role_name: str) -> str | None:
        return getattr(self, role_name)


@dataclass(frozen=True, slots=True)
class ModelConfig:
    default: str = _DEFAULT_MODEL
    roles: RoleModelOverrides = RoleModelOverrides()

    def for_role(self, role_name: str) -> str:
        return self.roles.for_role(role_name) or self.default


@dataclass(frozen=True, slots=True)
class RoleTemperatureConfig:
    reporter: float = 0.0

    def for_role(self, role_name: str) -> float:
        return float(getattr(self, role_name))


@dataclass(frozen=True, slots=True)
class TemperatureConfig:
    roles: RoleTemperatureConfig = RoleTemperatureConfig()


@dataclass(frozen=True, slots=True)
class LLMConfig:
    gateway: GatewayConfig = GatewayConfig()
    models: ModelConfig = ModelConfig()
    temperatures: TemperatureConfig = TemperatureConfig()


@dataclass(frozen=True, slots=True)
class AgentConfig:
    llm: LLMConfig = LLMConfig()


@dataclass(frozen=True, slots=True)
class ConfigLoadResult:
    found: bool
    loaded: bool
    path: Path
    config: AgentConfig


def default_agent_config() -> AgentConfig:
    return AgentConfig()


def apply_env_overrides(config: AgentConfig) -> AgentConfig:
    resolved = config

    env_provider = _optional_provider(os.environ.get("LLM_PROVIDER"), "LLM_PROVIDER", resolved.llm.gateway.provider)
    provider_changed = env_provider != resolved.llm.gateway.provider
    if env_provider != resolved.llm.gateway.provider:
        resolved = replace(
            resolved,
            llm=replace(
                resolved.llm,
                gateway=replace(resolved.llm.gateway, provider=env_provider),
            ),
        )

    env_backend = (os.environ.get("LLM_BACKEND") or "").strip().lower()
    if env_backend:
        resolved = replace(
            resolved,
            llm=replace(
                resolved.llm,
                gateway=replace(
                    resolved.llm.gateway,
                    backend=_normalize_backend(env_backend, "LLM_BACKEND", source="env"),
                ),
            ),
        )

    provider = resolved.llm.gateway.provider

    env_model = _first_env_value(_provider_env_names(provider, "MODEL"))
    if provider_changed:
        default_model = env_model or _provider_default_model(provider)
        resolved = replace(
            resolved,
            llm=replace(
                resolved.llm,
                models=ModelConfig(default=default_model, roles=RoleModelOverrides()),
            ),
        )
    elif env_model:
        resolved = replace(
            resolved,
            llm=replace(
                resolved.llm,
                models=replace(resolved.llm.models, default=env_model),
            ),
        )

    role_model_overrides = _env_role_model_overrides(resolved.llm.models.roles)
    if role_model_overrides != resolved.llm.models.roles:
        resolved = replace(
            resolved,
            llm=replace(
                resolved.llm,
                models=replace(resolved.llm.models, roles=role_model_overrides),
            ),
        )

    env_base_url = _first_env_value(_provider_env_names(provider, "BASE_URL"))
    if provider == "custom" and not env_base_url and provider_changed:
        raise ValueError("Invalid environment override: custom provider requires CUSTOM_BASE_URL or LLM_BASE_URL.")
    if env_base_url or provider_changed:
        base_url = env_base_url or _provider_default_base_url(provider)
        resolved = replace(
            resolved,
            llm=replace(
                resolved.llm,
                gateway=replace(resolved.llm.gateway, base_url=base_url),
            ),
        )

    env_timeout_name, env_timeout = _first_named_env_value(_provider_env_names(provider, "TIMEOUT_SEC"))
    if env_timeout:
        resolved = replace(
            resolved,
            llm=replace(
                resolved.llm,
                gateway=replace(
                    resolved.llm.gateway,
                    timeout_sec=_env_positive_int(env_timeout, env_timeout_name),
                ),
            ),
        )

    env_retry_name, env_retries = _first_named_env_value(_provider_env_names(provider, "RETRY_COUNT"))
    if env_retries:
        resolved = replace(
            resolved,
            llm=replace(
                resolved.llm,
                gateway=replace(
                    resolved.llm.gateway,
                    retry_count=_env_positive_int(env_retries, env_retry_name),
                ),
            ),
        )

    return resolved


def load_repo_config(*, repo_root: Path) -> ConfigLoadResult:
    config_path = (Path(os.getenv("MRCAT_CONFIG_DIR") or repo_root) / "config.yaml").resolve()
    if not config_path.exists():
        config = apply_env_overrides(default_agent_config())
        return ConfigLoadResult(found=False, loaded=False, path=config_path, config=config)

    try:
        raw_payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid config.yaml: {exc}") from exc

    if raw_payload is None:
        raw_payload = {}
    if not isinstance(raw_payload, dict):
        raise ValueError("Invalid config.yaml: root must be a mapping.")

    config = _parse_agent_config(raw_payload)
    return ConfigLoadResult(found=True, loaded=True, path=config_path, config=apply_env_overrides(config))


def _parse_agent_config(payload: dict[str, Any]) -> AgentConfig:
    default = default_agent_config()
    _reject_unknown_keys(payload, {"llm"}, "root")
    llm_payload = _require_mapping(payload.get("llm"), "llm")
    _reject_unknown_keys(llm_payload, {"gateway", "models", "temperatures"}, "llm")

    gateway_payload = _require_mapping(llm_payload.get("gateway"), "llm.gateway")
    _reject_unknown_keys(
        gateway_payload,
        {"provider", "backend", "base_url", "timeout_sec", "retry_count"},
        "llm.gateway",
    )
    gateway_provider = _provider(
        gateway_payload.get("provider"),
        "llm.gateway.provider",
        default.llm.gateway.provider,
    )
    gateway_base_url = _string(
        gateway_payload.get("base_url"),
        "llm.gateway.base_url",
        _provider_default_base_url(gateway_provider),
    )
    if gateway_provider == "custom" and gateway_payload.get("base_url") is None:
        raise ValueError("Invalid config.yaml: llm.gateway.base_url is required when provider is 'custom'.")
    gateway = GatewayConfig(
        provider=gateway_provider,
        backend=_backend(
            gateway_payload.get("backend"),
            "llm.gateway.backend",
            default.llm.gateway.backend,
        ),
        base_url=gateway_base_url,
        timeout_sec=_positive_int(gateway_payload.get("timeout_sec"), "llm.gateway.timeout_sec", default.llm.gateway.timeout_sec),
        retry_count=_positive_int(gateway_payload.get("retry_count"), "llm.gateway.retry_count", default.llm.gateway.retry_count),
    )

    models_payload = _require_mapping(llm_payload.get("models"), "llm.models")
    role_models_payload = _require_mapping(models_payload.get("roles"), "llm.models.roles")
    _reject_unknown_keys(models_payload, {"default", "roles"}, "llm.models")
    _reject_unknown_keys(
        role_models_payload,
        {"reporter"},
        "llm.models.roles",
    )
    models = ModelConfig(
        default=_string(models_payload.get("default"), "llm.models.default", _provider_default_model(gateway_provider)),
        roles=RoleModelOverrides(
            reporter=_optional_string(
                role_models_payload.get("reporter"),
                "llm.models.roles.reporter",
                default.llm.models.roles.reporter,
            ),
        ),
    )

    temperatures_payload = _require_mapping(llm_payload.get("temperatures"), "llm.temperatures")
    role_temperatures_payload = _require_mapping(temperatures_payload.get("roles"), "llm.temperatures.roles")
    _reject_unknown_keys(temperatures_payload, {"roles"}, "llm.temperatures")
    _reject_unknown_keys(
        role_temperatures_payload,
        {"reporter"},
        "llm.temperatures.roles",
    )
    temperatures = TemperatureConfig(
        roles=RoleTemperatureConfig(
            reporter=_number(
                role_temperatures_payload.get("reporter"),
                "llm.temperatures.roles.reporter",
                default.llm.temperatures.roles.reporter,
            ),
        ),
    )

    return AgentConfig(llm=LLMConfig(gateway=gateway, models=models, temperatures=temperatures))


def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Invalid config.yaml: {path} must be a mapping.")
    return value


def _reject_unknown_keys(payload: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(str(key) for key in payload if str(key) not in allowed)
    if unknown:
        raise ValueError(f"Invalid config.yaml: {path} contains unsupported key(s): {', '.join(unknown)}")


def _provider(value: Any, path: str, default: str) -> str:
    if value is None:
        return default
    return _normalize_provider(str(value), path, source="config")


def _optional_provider(value: Any, path: str, default: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    return _normalize_provider(raw, path, source="env")


def _normalize_provider(value: str, path: str, *, source: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _SUPPORTED_PROVIDERS:
        allowed = ", ".join(_SUPPORTED_PROVIDERS)
        if source == "env":
            raise ValueError(f"Invalid environment override: {path} must be one of [{allowed}].")
        raise ValueError(f"Invalid config.yaml: {path} must be one of [{allowed}].")
    return normalized


def _provider_prefix(provider: str) -> str:
    return provider.upper().replace("-", "_")


def _provider_env_names(provider: str, suffix: str) -> list[str]:
    return [f"{_provider_prefix(provider)}_{suffix}", f"LLM_{suffix}"]


def _clean_env_value(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].strip()
    return text


def _first_named_env_value(env_names: list[str]) -> tuple[str, str]:
    for env_name in env_names:
        value = _clean_env_value(os.environ.get(env_name))
        if value:
            return env_name, value
    return env_names[0], ""


def _first_env_value(env_names: list[str]) -> str:
    return _first_named_env_value(env_names)[1]


def _provider_default_model(provider: str) -> str:
    return _PROVIDER_DEFAULTS[provider]["model"]


def _provider_default_base_url(provider: str) -> str:
    return _PROVIDER_DEFAULTS[provider]["base_url"]


def _env_role_model_overrides(current: RoleModelOverrides) -> RoleModelOverrides:
    values: dict[str, str | None] = {}
    changed = False
    for role_name, env_name in _ROLE_MODEL_ENV_NAMES.items():
        value = _clean_env_value(os.environ.get(env_name))
        current_value = current.for_role(role_name)
        values[role_name] = value or current_value
        if value and value != current_value:
            changed = True
    if not changed:
        return current
    return RoleModelOverrides(**values)


def _backend(value: Any, path: str, default: str) -> str:
    if value is None:
        return default
    return _normalize_backend(str(value), path, source="config")


def _normalize_backend(value: str, path: str, *, source: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"sdk", "http"}:
        if source == "env":
            raise ValueError(f"Invalid environment override: {path} must be one of ['sdk', 'http'].")
        raise ValueError(f"Invalid config.yaml: {path} must be one of ['sdk', 'http'].")
    return normalized


def _positive_int(value: Any, path: str, default: int) -> int:
    if value is None:
        return default
    return _require_positive_int(value, path)


def _require_positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Invalid config.yaml: {path} must be a positive integer.")
    if value <= 0:
        raise ValueError(f"Invalid config.yaml: {path} must be a positive integer.")
    return value


def _env_positive_int(value: str, path: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid environment override: {path} must be a positive integer.") from exc
    if parsed <= 0:
        raise ValueError(f"Invalid environment override: {path} must be a positive integer.")
    return parsed


def _number(value: Any, path: str, default: float) -> float:
    if value is None:
        return float(default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Invalid config.yaml: {path} must be a number.")
    return float(value)


def _string(value: Any, path: str, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid config.yaml: {path} must be a non-empty string.")
    return value.strip()


def _optional_string(value: Any, path: str, default: str | None) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid config.yaml: {path} must be null or a non-empty string.")
    return value.strip()
