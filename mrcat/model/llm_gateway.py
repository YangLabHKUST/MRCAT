from __future__ import annotations

import http.client
import json
import os
import random
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from mrcat.config.llm_limits import LLM_MAX_OUTPUT_TOKENS, LLM_TIMEOUT_SECONDS
from mrcat.config.loader import AgentConfig
from mrcat.model.llm_usage import record_llm_usage

JsonValidator = Callable[[dict[str, Any]], dict[str, Any]]
JsonTraceSink = Callable[[str, dict[str, Any]], None]


class OutputTruncatedError(RuntimeError):
    """The provider stopped at its output budget; partial text is not usable."""


class ProviderResponseError(RuntimeError):
    """A provider error or unusable native response; retain response evidence."""

    def __init__(self, message, *, response=None):
        super().__init__(message)
        self.provider_response = response


def _check_provider_error(body: Any) -> None:
    error = body.get("error") if isinstance(body, dict) else getattr(body, "error", None)
    if error:
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise ProviderResponseError(f"Model API error: {message or error}")


def _check_output_complete(body: Any) -> None:
    def field(obj, name, default=None):
        return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)

    reason = field(body, "stop_reason")
    if reason != "max_tokens":
        choices = field(body, "choices", []) or []
        reason = "length" if choices and field(choices[0], "finish_reason") == "length" else None
    if reason is None and field(body, "status") == "incomplete":
        reason = field(field(body, "incomplete_details"), "reason")
    if reason in {"length", "max_tokens", "max_output_tokens"}:
        raise OutputTruncatedError(
            f"Model output was truncated ({reason}); partial output was discarded. "
            "Increase the output token budget within the model's supported limit and retry."
        )

SUPPORTED_PROVIDERS = {"anthropic", "openai", "deepseek", "qwen", "glm", "grok", "custom"}
OPENAI_COMPATIBLE_PROVIDERS = {"openai", "deepseek", "qwen", "glm", "grok", "custom"}

_DEFAULT_PROVIDER = "anthropic"
_DEFAULT_TIMEOUT = LLM_TIMEOUT_SECONDS
_DEFAULT_RETRIES = 3
_DEFAULT_MIN_INTERVAL_SEC = 0.0
_DEFAULT_RETRY_BASE_DELAY_SEC = 1.5
_DEFAULT_RETRY_MAX_DELAY_SEC = 30.0
_DEFAULT_RETRY_JITTER_SEC = 0.5
_DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 5
_DEFAULT_CIRCUIT_BREAKER_COOLDOWN_SEC = 120.0
_ANTHROPIC_VERSION = "2023-06-01"

_RESILIENCE_LOCK = threading.Lock()
_PROVIDER_LAST_REQUEST_AT: dict[str, float] = {}
_PROVIDER_FAILURE_STATE: dict[str, dict[str, float]] = {}

_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "anthropic": {
        "label": "Anthropic",
        "model": "claude-opus-4-6",
        "base_url": "https://api.anthropic.com",
    },
    "openai": {
        "label": "OpenAI-compatible",
        "model": "gpt-4.1",
        "base_url": "https://api.openai.com/v1",
    },
    "deepseek": {
        "label": "DeepSeek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
    },
    "qwen": {
        "label": "Qwen",
        "model": "qwen-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "glm": {
        "label": "GLM",
        "model": "glm-4-plus",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
    },
    "grok": {
        "label": "Grok",
        "model": "grok-2-latest",
        "base_url": "https://api.x.ai/v1",
    },
    "custom": {
        "label": "Custom OpenAI-compatible",
        "model": "custom-model",
        "base_url": "",
    },
}


def current_provider(agent_config: AgentConfig | None = None) -> str:
    raw = _clean(os.environ.get("LLM_PROVIDER")).lower()
    if raw:
        return _normalize_provider(raw, source="environment variable LLM_PROVIDER")
    if agent_config is not None:
        configured = _clean(agent_config.llm.gateway.provider).lower()
        if configured:
            return _normalize_provider(configured, source="config llm.gateway.provider")
    return _DEFAULT_PROVIDER


def provider_label(agent_config: AgentConfig | None = None) -> str:
    return _PROVIDER_DEFAULTS[current_provider(agent_config)]["label"]


def api_key_env_name(agent_config: AgentConfig | None = None) -> str:
    provider = current_provider(agent_config)
    for env_name in _provider_env_names(provider, "API_KEY"):
        if _clean(os.environ.get(env_name)):
            return env_name
    return _provider_env_names(provider, "API_KEY")[0]


def has_api_key(agent_config: AgentConfig | None = None) -> bool:
    provider = current_provider(agent_config)
    return any(_clean(os.environ.get(env_name)) for env_name in _provider_env_names(provider, "API_KEY"))


def current_model(agent_config: AgentConfig | None = None) -> str:
    provider = current_provider(agent_config)
    for env_name in _provider_env_names(provider, "MODEL"):
        value = _clean(os.environ.get(env_name))
        if value:
            return value
    if agent_config is not None:
        configured = _clean(agent_config.llm.models.default)
        if configured:
            return configured
    return _PROVIDER_DEFAULTS[provider]["model"]


def current_timeout(default: int | None = None, agent_config: AgentConfig | None = None) -> int:
    provider = current_provider(agent_config)
    for env_name in _provider_env_names(provider, "TIMEOUT_SEC"):
        raw = _clean(os.environ.get(env_name))
        if raw:
            return int(raw)
    if agent_config is not None:
        return int(agent_config.llm.gateway.timeout_sec)
    return int(default if default is not None else _DEFAULT_TIMEOUT)


def current_retries(agent_config: AgentConfig | None = None) -> int:
    provider = current_provider(agent_config)
    for env_name in _provider_env_names(provider, "RETRY_COUNT"):
        raw = _clean(os.environ.get(env_name))
        if raw:
            return max(1, int(raw))
    if agent_config is not None:
        return max(1, int(agent_config.llm.gateway.retry_count))
    return _DEFAULT_RETRIES


def current_min_interval_sec(agent_config: AgentConfig | None = None) -> float:
    return _current_nonnegative_float(
        "MIN_INTERVAL_SEC",
        default=_DEFAULT_MIN_INTERVAL_SEC,
        agent_config=agent_config,
    )


def current_backend(agent_config: AgentConfig | None = None) -> str:
    env = _clean(os.environ.get("LLM_BACKEND")).lower()
    if env:
        if env not in {"sdk", "http"}:
            raise RuntimeError(f"Unsupported LLM_BACKEND={env!r}; expected 'sdk' or 'http'.")
        return env
    if agent_config is not None:
        configured = _clean(agent_config.llm.gateway.backend).lower()
        if configured:
            return configured
    return "sdk"


def call_text(
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = LLM_MAX_OUTPUT_TOKENS,
    timeout: int = LLM_TIMEOUT_SECONDS,
    agent_config: AgentConfig | None = None,
    thinking: bool | None = None,
    action_tool: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    request_messages: list[dict[str, Any]] | None = None,
) -> str:
    provider = current_provider(agent_config)
    resolved_model = model or current_model(agent_config)
    resolved_timeout = current_timeout(timeout, agent_config)

    if current_backend(agent_config) == "sdk":
        if provider == "anthropic":
            return _call_anthropic_sdk(
                system=system,
                user=user,
                model=resolved_model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=resolved_timeout,
                agent_config=agent_config,
                thinking=thinking,
                **({"action_tool": action_tool} if action_tool else {}),
                **({"tools": tools} if tools else {}),
                **({"request_messages": request_messages} if request_messages is not None else {}),
            )
        return _call_openai_compatible_sdk(
            system=system,
            user=user,
            model=resolved_model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=resolved_timeout,
            agent_config=agent_config,
            thinking=thinking,
            **({"action_tool": action_tool} if action_tool else {}),
            **({"tools": tools} if tools else {}),
            **({"request_messages": request_messages} if request_messages is not None else {}),
        )

    return _call_text_http(
        system=system,
        user=user,
        model=resolved_model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=resolved_timeout,
        agent_config=agent_config,
        thinking=thinking,
        **({"action_tool": action_tool} if action_tool else {}),
        **({"tools": tools} if tools else {}),
        **({"request_messages": request_messages} if request_messages is not None else {}),
    )


def extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Empty LLM output.")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    unfenced = re.sub(r"^\s*```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    unfenced = re.sub(r"\s*```\s*$", "", unfenced)
    if unfenced != raw:
        try:
            parsed = json.loads(unfenced.strip())
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed

    fenced = re.search(r"```(?:json)?\s*(\{.*?})\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1))

    start = raw.find("{")
    if start != -1:
        depth = 0
        for index, char in enumerate(raw[start:], start):
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(raw[start : index + 1])

    raise ValueError(f"No JSON object found in output: {raw[:240]}")


def call_json(
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = LLM_MAX_OUTPUT_TOKENS,
    timeout: int = LLM_TIMEOUT_SECONDS,
    agent_config: AgentConfig | None = None,
    thinking: bool | None = None,
) -> dict[str, Any]:
    return extract_json(
        call_text(
            system=system,
            user=user,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            agent_config=agent_config,
            thinking=thinking,
        )
    )


def call_validated_json(
    *,
    system: str,
    user: str,
    example: dict[str, Any],
    validator: JsonValidator,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = LLM_MAX_OUTPUT_TOKENS,
    timeout: int = LLM_TIMEOUT_SECONDS,
    agent_config: AgentConfig | None = None,
    compact: bool = False,
    trace_sink: JsonTraceSink | None = None,
    trace_context: dict[str, Any] | None = None,
    thinking: bool | None = None,
) -> dict[str, Any]:
    example_text = json.dumps(
        example,
        ensure_ascii=False,
        separators=(",", ":") if compact else None,
        indent=None if compact else 2,
    )
    request_system = (
        f"{str(system or '').strip()}\n\n"
        "Return exactly one JSON object. Do not wrap it in markdown. "
        "Do not include commentary outside JSON."
    ).strip()
    if compact:
        request_system += (
            " Return a compact single-line JSON object. "
            "Every string field must stay on one line with no raw control characters."
        )
    request_user = (
        f"{str(user or '').strip()}\n\n"
        f"Return JSON shaped like this example:\n{example_text}"
    ).strip()
    trace_base = dict(trace_context or {})
    _emit_json_trace(
        trace_sink,
        "llm_prompt",
        {
            **trace_base,
            "system": request_system,
            "user": request_user,
            "system_chars": len(request_system),
            "user_chars": len(request_user),
            "max_tokens": max_tokens,
            "compact": bool(compact),
        },
    )
    raw = call_text(
        system=request_system,
        user=request_user,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        agent_config=agent_config,
        thinking=thinking,
    )
    _emit_json_trace(
        trace_sink,
        "llm_raw_response",
        {
            **trace_base,
            "raw_response": raw,
            "raw_response_excerpt": _excerpt(raw),
        },
    )
    try:
        validated = validator(extract_json(raw))
        _emit_json_trace(
            trace_sink,
            "llm_validated_output",
            {
                **trace_base,
                "validated_output": validated,
                "validated_output_preview": _excerpt_json(validated),
                "repair_used": False,
            },
        )
        return validated
    except Exception as exc:
        _emit_json_trace(
            trace_sink,
            "llm_parse_error",
            {
                **trace_base,
                "parse_error": str(exc),
                "raw_response_excerpt": _excerpt(raw),
            },
        )
        return _repair_json_output(
            request_system=request_system,
            request_user=request_user,
            raw=raw,
            error=str(exc),
            example=example,
            validator=validator,
            model=model,
            max_tokens=max_tokens,
            timeout=timeout,
            agent_config=agent_config,
            compact=compact,
            trace_sink=trace_sink,
            trace_context=trace_base,
            thinking=thinking,
        )


def _repair_json_output(
    *,
    request_system: str,
    request_user: str,
    raw: str,
    error: str,
    example: dict[str, Any],
    validator: JsonValidator,
    model: str | None,
    max_tokens: int,
    timeout: int,
    agent_config: AgentConfig | None,
    compact: bool,
    trace_sink: JsonTraceSink | None = None,
    trace_context: dict[str, Any] | None = None,
    thinking: bool | None = None,
) -> dict[str, Any]:
    example_text = json.dumps(
        example,
        ensure_ascii=False,
        separators=(",", ":") if compact else None,
        indent=None if compact else 2,
    )
    repair_system = (
        "You repair invalid model outputs into one JSON object. "
        "Return JSON only and preserve the intended meaning."
    )
    if compact:
        repair_system += (
            " Return a compact single-line JSON object. "
            "Every string field must stay on one line with no raw control characters."
        )
    repair_user = (
        f"Original system prompt:\n{request_system}\n\n"
        f"Original user prompt:\n{request_user}\n\n"
        f"Validation error: {error}\n\n"
        f"Return JSON shaped like this example:\n{example_text}\n\n"
        f"Original output to repair:\n{raw}"
    )
    trace_base = dict(trace_context or {})
    _emit_json_trace(
        trace_sink,
        "llm_repair_prompt",
        {
            **trace_base,
            "system": repair_system,
            "user": repair_user,
            "system_chars": len(repair_system),
            "user_chars": len(repair_user),
            "max_tokens": max_tokens,
            "compact": bool(compact),
            "validation_error": error,
        },
    )
    repaired = call_text(
        system=repair_system,
        user=repair_user,
        model=model,
        temperature=0.0,
        max_tokens=max_tokens,
        timeout=timeout,
        agent_config=agent_config,
        thinking=thinking,
    )
    _emit_json_trace(
        trace_sink,
        "llm_repair_raw_response",
        {
            **trace_base,
            "raw_response": repaired,
            "raw_response_excerpt": _excerpt(repaired),
        },
    )
    try:
        validated = validator(extract_json(repaired))
        _emit_json_trace(
            trace_sink,
            "llm_validated_output",
            {
                **trace_base,
                "validated_output": validated,
                "validated_output_preview": _excerpt_json(validated),
                "repair_used": True,
            },
        )
        return validated
    except Exception as exc:
        _emit_json_trace(
            trace_sink,
            "llm_repair_failed",
            {
                **trace_base,
                "parse_error": str(exc),
                "raw_response_excerpt": _excerpt(repaired),
            },
        )
        raise RuntimeError(f"LLM JSON repair produced invalid output: {exc}") from exc


def _emit_json_trace(
    trace_sink: JsonTraceSink | None,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    if trace_sink is None:
        return
    trace_sink(event_type, payload)


def _excerpt(text: Any, *, limit: int = 500) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)] + "..."


def _excerpt_json(payload: Any, *, limit: int = 500) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    except TypeError:
        text = str(payload)
    return _excerpt(text, limit=limit)


def _wait_for_rate_limit(agent_config: AgentConfig | None) -> None:
    min_interval = current_min_interval_sec(agent_config)
    if min_interval <= 0:
        return

    provider = current_provider(agent_config)
    with _RESILIENCE_LOCK:
        now = time.monotonic()
        next_allowed_at = _PROVIDER_LAST_REQUEST_AT.get(provider, 0.0) + min_interval
        wait_seconds = max(0.0, next_allowed_at - now)
        _PROVIDER_LAST_REQUEST_AT[provider] = now + wait_seconds

    if wait_seconds > 0:
        time.sleep(wait_seconds)


def _check_provider_circuit(agent_config: AgentConfig | None) -> None:
    threshold = _current_nonnegative_int(
        "CIRCUIT_BREAKER_THRESHOLD",
        default=_DEFAULT_CIRCUIT_BREAKER_THRESHOLD,
        agent_config=agent_config,
    )
    if threshold <= 0:
        return

    provider = current_provider(agent_config)
    with _RESILIENCE_LOCK:
        state = _PROVIDER_FAILURE_STATE.get(provider) or {}
        opened_until = float(state.get("opened_until") or 0.0)
        now = time.monotonic()
        if opened_until > now:
            wait_seconds = opened_until - now
            label = provider_label(agent_config)
            raise RuntimeError(
                f"{label} API circuit breaker open for {wait_seconds:.1f}s "
                f"after {int(state.get('failures') or 0)} consecutive failed call(s)."
            )
        if opened_until:
            _PROVIDER_FAILURE_STATE[provider] = {"failures": 0.0, "opened_until": 0.0}


def _record_provider_success(agent_config: AgentConfig | None) -> None:
    provider = current_provider(agent_config)
    with _RESILIENCE_LOCK:
        _PROVIDER_FAILURE_STATE.pop(provider, None)


def _record_provider_failure(agent_config: AgentConfig | None) -> None:
    threshold = _current_nonnegative_int(
        "CIRCUIT_BREAKER_THRESHOLD",
        default=_DEFAULT_CIRCUIT_BREAKER_THRESHOLD,
        agent_config=agent_config,
    )
    if threshold <= 0:
        return

    provider = current_provider(agent_config)
    cooldown = _current_nonnegative_float(
        "CIRCUIT_BREAKER_COOLDOWN_SEC",
        default=_DEFAULT_CIRCUIT_BREAKER_COOLDOWN_SEC,
        agent_config=agent_config,
    )
    with _RESILIENCE_LOCK:
        state = _PROVIDER_FAILURE_STATE.get(provider) or {}
        failures = float(state.get("failures") or 0.0) + 1.0
        opened_until = time.monotonic() + cooldown if failures >= threshold else 0.0
        _PROVIDER_FAILURE_STATE[provider] = {"failures": failures, "opened_until": opened_until}


def _sleep_before_retry(attempt: int, agent_config: AgentConfig | None) -> None:
    base_delay = _current_nonnegative_float(
        "RETRY_BASE_DELAY_SEC",
        default=_DEFAULT_RETRY_BASE_DELAY_SEC,
        agent_config=agent_config,
    )
    max_delay = _current_nonnegative_float(
        "RETRY_MAX_DELAY_SEC",
        default=_DEFAULT_RETRY_MAX_DELAY_SEC,
        agent_config=agent_config,
    )
    jitter = _current_nonnegative_float(
        "RETRY_JITTER_SEC",
        default=_DEFAULT_RETRY_JITTER_SEC,
        agent_config=agent_config,
    )
    delay = min(base_delay * (2 ** max(0, attempt - 1)), max_delay)
    if jitter > 0:
        delay += random.uniform(0.0, jitter)
    if delay > 0:
        time.sleep(delay)


def _call_anthropic_sdk(
    *,
    system: str,
    user: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    agent_config: AgentConfig | None,
    thinking: bool | None,
    action_tool: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    request_messages: list[dict[str, Any]] | None = None,
) -> str:
    import anthropic

    client = anthropic.Anthropic(
        api_key=_get_api_key(agent_config),
        base_url=_anthropic_sdk_base_url(agent_config),
        timeout=float(timeout),
        max_retries=current_retries(agent_config),
    )
    _wait_for_rate_limit(agent_config)
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if thinking is False:
        request["thinking"] = {"type": "disabled"}
    request.update(_anthropic_action_options(action_tool, request_messages, tools))
    response = client.messages.create(
        **request,
    )
    record_llm_usage(getattr(response, "usage", None))
    _check_provider_error(response)
    _check_output_complete(response)
    text = (_extract_tool_message(response, tools, provider="anthropic") if tools else
            _extract_action_arguments(response, action_tool["function"]["name"], provider="anthropic")
            if action_tool else _extract_anthropic_sdk_text(response))
    if text:
        _record_provider_success(agent_config)
        return text
    dump = response.model_dump() if hasattr(response, "model_dump") else response
    raise RuntimeError(f"Anthropic SDK response missing text: {dump}")


def _call_openai_compatible_sdk(
    *,
    system: str,
    user: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    agent_config: AgentConfig | None,
    thinking: bool | None,
    action_tool: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    request_messages: list[dict[str, Any]] | None = None,
) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=_get_api_key(agent_config),
        base_url=_openai_compatible_base_url(agent_config),
        timeout=float(timeout),
        max_retries=current_retries(agent_config),
    )
    _wait_for_rate_limit(agent_config)
    request: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if thinking is not None and current_provider(agent_config) == "deepseek":
        request["extra_body"] = {"thinking": {"type": "enabled" if thinking else "disabled"}}
    if request_messages is not None:
        request["messages"] = (_deepseek_thinking_messages(request_messages)
                               if thinking is True and current_provider(agent_config) == "deepseek"
                               else request_messages)
    if action_tool:
        request.update(tools=[action_tool], tool_choice={"type": "function", "function": {"name": action_tool["function"]["name"]}})
    if tools:
        request.update(tools=tools, tool_choice=("auto" if thinking is True and
                       current_provider(agent_config) == "deepseek" else "required"))
    response = client.chat.completions.create(**request)
    record_llm_usage(getattr(response, "usage", None))
    _check_provider_error(response)
    _check_output_complete(response)
    text = (_extract_tool_message(response, tools) if tools else
            _extract_action_arguments(response, action_tool["function"]["name"])
            if action_tool else _extract_openai_sdk_text(response))
    if text:
        _record_provider_success(agent_config)
        return text
    dump = response.model_dump() if hasattr(response, "model_dump") else response
    raise RuntimeError(f"OpenAI-compatible SDK response missing text: {dump}")


def _call_text_http(
    *,
    system: str,
    user: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    agent_config: AgentConfig | None,
    thinking: bool | None,
    action_tool: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    request_messages: list[dict[str, Any]] | None = None,
) -> str:
    provider = current_provider(agent_config)
    payload = _build_payload(
        provider=provider,
        system=system,
        user=user,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        thinking=thinking,
        **({"action_tool": action_tool} if action_tool else {}),
        **({"tools": tools} if tools else {}),
        **({"request_messages": request_messages} if request_messages is not None else {}),
    )
    request = urllib.request.Request(
        _api_url(agent_config),
        data=payload,
        headers=_build_headers(agent_config),
    )
    retries = current_retries(agent_config)
    missing_text_retries = 1
    missing_text_attempt = 0
    label = provider_label(agent_config)

    while True:
        _check_provider_circuit(agent_config)
        for attempt in range(1, retries + 1):
            try:
                _wait_for_rate_limit(agent_config)
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    body = json.loads(response.read())
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="ignore")[:500]
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < retries:  # pragma: no cover - network path
                    _sleep_before_retry(attempt, agent_config)
                    continue
                _record_provider_failure(agent_config)
                raise RuntimeError(f"{label} API HTTP {exc.code}: {detail}") from exc
            except (
                TimeoutError,
                socket.timeout,
                urllib.error.URLError,
                ConnectionError,
                http.client.IncompleteRead,
            ) as exc:  # pragma: no cover - network path
                if attempt < retries:
                    _sleep_before_retry(attempt, agent_config)
                    continue
                _record_provider_failure(agent_config)
                raise RuntimeError(f"{label} API request failed after {attempt} attempt(s): {exc}") from exc
            except Exception as exc:  # pragma: no cover - network path
                _record_provider_failure(agent_config)
                raise RuntimeError(f"{label} API request failed: {exc}") from exc

        try:
            record_llm_usage(body.get("usage") if isinstance(body, dict) else None)
            _check_provider_error(body)
            _check_output_complete(body)
            text = (_extract_tool_message(body, tools, provider=provider) if tools else
                    _extract_action_arguments(body, action_tool["function"]["name"], provider=provider)
                    if action_tool else _extract_text(body, provider=provider))
        except OutputTruncatedError:
            # Truncation is not a provider outage or an empty-text retry.
            raise
        except ProviderResponseError:
            _record_provider_failure(agent_config)
            raise
        except RuntimeError:
            if missing_text_attempt < missing_text_retries:
                missing_text_attempt += 1
                time.sleep(0.4 * missing_text_attempt)
                continue
            _record_provider_failure(agent_config)
            raise
        _record_provider_success(agent_config)
        return text


def _normalize_provider(value: str, *, source: str) -> str:
    provider = str(value or "").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        allowed = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise RuntimeError(f"Unsupported LLM provider from {source}: {value!r}. Expected one of: {allowed}.")
    return provider


def _provider_prefix(provider: str) -> str:
    return provider.upper().replace("-", "_")


def _provider_env_names(provider: str, suffix: str) -> list[str]:
    return [f"{_provider_prefix(provider)}_{suffix}", f"LLM_{suffix}"]


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].strip()
    return text


def _current_nonnegative_float(
    suffix: str,
    *,
    default: float,
    agent_config: AgentConfig | None = None,
) -> float:
    provider = current_provider(agent_config)
    for env_name in _provider_env_names(provider, suffix):
        raw = _clean(os.environ.get(env_name))
        if raw:
            value = float(raw)
            if value < 0:
                raise RuntimeError(f"{env_name} must be non-negative.")
            return value
    return float(default)


def _current_nonnegative_int(
    suffix: str,
    *,
    default: int,
    agent_config: AgentConfig | None = None,
) -> int:
    provider = current_provider(agent_config)
    for env_name in _provider_env_names(provider, suffix):
        raw = _clean(os.environ.get(env_name))
        if raw:
            value = int(raw)
            if value < 0:
                raise RuntimeError(f"{env_name} must be non-negative.")
            return value
    return int(default)


def _get_api_key(agent_config: AgentConfig | None = None) -> str:
    provider = current_provider(agent_config)
    for env_name in _provider_env_names(provider, "API_KEY"):
        key = _clean(os.environ.get(env_name))
        if key:
            return key
    raise RuntimeError(f"{api_key_env_name(agent_config)} not set")


def _current_base_url(agent_config: AgentConfig | None = None) -> str:
    provider = current_provider(agent_config)
    for env_name in _provider_env_names(provider, "BASE_URL"):
        value = _clean(os.environ.get(env_name))
        if value:
            return value.rstrip("/")
    if agent_config is not None:
        configured = _clean(agent_config.llm.gateway.base_url)
        if configured:
            return configured.rstrip("/")
    default = _PROVIDER_DEFAULTS[provider]["base_url"]
    if default:
        return default.rstrip("/")
    raise RuntimeError(f"{_provider_env_names(provider, 'BASE_URL')[0]} or LLM_BASE_URL is required for provider={provider!r}.")


def _anthropic_sdk_base_url(agent_config: AgentConfig | None = None) -> str:
    base = _current_base_url(agent_config)
    if base.endswith("/v1/messages"):
        return base[: -len("/v1/messages")]
    return base


def _openai_compatible_base_url(agent_config: AgentConfig | None = None) -> str:
    base = _current_base_url(agent_config)
    if base.endswith("/chat/completions"):
        return base[: -len("/chat/completions")]
    return base


def _api_url(agent_config: AgentConfig | None = None) -> str:
    provider = current_provider(agent_config)
    base = _current_base_url(agent_config)
    if provider == "anthropic":
        return base if base.endswith("/v1/messages") else f"{base}/v1/messages"
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def _build_headers(agent_config: AgentConfig | None = None) -> dict[str, str]:
    provider = current_provider(agent_config)
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return {
            "authorization": f"Bearer {_get_api_key(agent_config)}",
            "content-type": "application/json",
        }
    headers = {
        "x-api-key": _get_api_key(agent_config),
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    auth_token = _clean(os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if auth_token:
        headers["authorization"] = f"Bearer {auth_token}"
    return headers


def _build_payload(
    *,
    provider: str,
    system: str,
    user: str,
    model: str,
    temperature: float,
    max_tokens: int,
    thinking: bool | None = None,
    action_tool: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    request_messages: list[dict[str, Any]] | None = None,
) -> bytes:
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if thinking is not None and provider == "deepseek":
            payload["thinking"] = {"type": "enabled" if thinking else "disabled"}
        if request_messages is not None:
            payload["messages"] = (_deepseek_thinking_messages(request_messages)
                                   if thinking is True and provider == "deepseek" else request_messages)
        if action_tool:
            payload.update(tools=[action_tool], tool_choice={"type": "function", "function": {"name": action_tool["function"]["name"]}})
        if tools:
            payload.update(tools=tools, tool_choice=("auto" if thinking is True and
                           provider == "deepseek" else "required"))
        return json.dumps(payload).encode("utf-8")
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if thinking is False:
        payload["thinking"] = {"type": "disabled"}
    payload.update(_anthropic_action_options(action_tool, request_messages, tools))
    return json.dumps(payload).encode("utf-8")


def _anthropic_action_options(action_tool, request_messages, tools=None):
    """Translate the shared action conversation to Anthropic's native blocks."""
    options = {}
    if action_tool:
        function = action_tool["function"]
        options.update(tools=[dict(name=function["name"], description=function["description"],
                                   input_schema=function["parameters"])],
                       tool_choice=dict(type="tool", name=function["name"], disable_parallel_tool_use=True))
    if tools:
        options.update(tools=[dict(name=t["function"]["name"], description=t["function"]["description"],
                                  input_schema=t["function"]["parameters"]) for t in tools],
                       tool_choice=dict(type="any"))
    if request_messages is not None:
        messages = []
        for row in request_messages:
            role = row["role"]
            if role == "system":
                continue  # The same system prompt is supplied at the top level.
            if role == "tool":
                result = dict(type="tool_result", tool_use_id=row["tool_call_id"], content=row["content"])
                if messages and messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], list):
                    messages[-1]["content"].append(result)
                else:
                    messages.append(dict(role="user", content=[result]))
            elif role == "assistant" and row.get("tool_calls"):
                blocks = [dict(type="text", text=row["content"])] if row.get("content") else []
                blocks.extend(dict(type="tool_use", id=call["id"], name=call["function"]["name"],
                                   input=json.loads(call["function"]["arguments"])) for call in row["tool_calls"])
                messages.append(dict(role=role, content=blocks))
            else:
                messages.append(dict(role=role, content=row["content"]))
        options["messages"] = messages
    return options


def _deepseek_thinking_messages(messages):
    """Old non-thinking turns have no reasoning; preserve all reasoning we received."""
    return [dict(row, reasoning_content=row.get("reasoning_content") or "")
            if row.get("role") == "assistant" else row for row in messages]


def _extract_tool_message(response, tools, *, provider="openai"):
    """Normalize all native calls without losing provider IDs or source text."""
    def field(obj, key, default=None):
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
    if provider == "anthropic":
        blocks = field(response, "content", []) or []
        calls = [b for b in blocks if field(b, "type") == "tool_use"]
        content = "\n".join(field(b, "text", "") for b in blocks if field(b, "type") == "text")
        stop = field(response, "stop_reason")
    else:
        choices = field(response, "choices", []) or []
        message = field(choices[0], "message") if choices else None
        calls = field(message, "tool_calls", []) or []
        content = field(message, "content")
        stop = field(choices[0], "finish_reason") if choices else None
    def reject(problem):
        dump = response.model_dump() if hasattr(response, "model_dump") else response
        if not isinstance(dump, dict) and hasattr(dump, "__dict__"):
            dump = vars(dump)
        raise ProviderResponseError(
            f"Expected advertised native tool calls with unique call IDs; {problem} "
            f"(stop_reason={stop!r}, text_present={bool(content)}).", response=dump)
    if not calls:
        reject("received 0 tool calls")
    advertised = {t["function"]["name"] for t in tools}
    normalized, ids = [], set()
    for call in calls:
        function = call if provider == "anthropic" else field(call, "function")
        name, call_id = field(function, "name"), field(call, "id")
        if name not in advertised:
            reject(f"unadvertised tool name {name!r}")
        if not isinstance(call_id, str) or not call_id:
            reject("tool call has no valid ID")
        if call_id in ids:
            reject(f"duplicate tool call ID {call_id!r}")
        ids.add(call_id)
        if provider == "anthropic":
            arguments = json.dumps(field(call, "input"), ensure_ascii=False)
        else:
            if field(call, "type") != "function":
                reject("tool call is not a function")
            arguments = field(function, "arguments")
            if not isinstance(arguments, str):
                reject("tool arguments must be a string")
        normalized.append(dict(id=call_id, type="function", function=dict(name=name, arguments=arguments)))
    result = dict(role="assistant", content=content, tool_calls=normalized)
    if provider != "anthropic" and field(message, "reasoning_content") is not None:
        result["reasoning_content"] = field(message, "reasoning_content")
    return json.dumps(result, ensure_ascii=False)


def _extract_action_arguments(response: Any, expected_name: str, *, provider: str = "openai") -> str:
    """Accept exactly one native action, never execute content that resembles a tool."""
    def field(obj, key, default=None):
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
    if provider == "anthropic":
        calls = [block for block in field(response, "content", []) or [] if field(block, "type") == "tool_use"]
        if len(calls) != 1:
            raise ProviderResponseError("Expected exactly one native action tool call.")
        arguments = field(calls[0], "input")
        if field(calls[0], "name") != expected_name or not isinstance(arguments, dict):
            raise ProviderResponseError("Invalid native action tool response.")
        return json.dumps(arguments, ensure_ascii=False)
    choices = field(response, "choices", []) or []
    message = field(choices[0], "message") if choices else None
    calls = field(message, "tool_calls", []) or []
    if len(calls) != 1:
        raise ProviderResponseError("Expected exactly one native action tool call.")
    function = field(calls[0], "function")
    arguments = field(function, "arguments")
    if (field(calls[0], "type") != "function" or field(function, "name") != expected_name
            or not isinstance(arguments, str) or not arguments.strip()):
        raise ProviderResponseError("Invalid native action tool response.")
    return arguments


def _extract_text(body: dict[str, Any], *, provider: str) -> str:
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return _extract_openai_compatible_text(body)
    return _extract_anthropic_http_text(body)


def _extract_anthropic_sdk_text(response: Any) -> str:
    fragments: list[str] = []
    for block in getattr(response, "content", []) or []:
        block_type = getattr(block, "type", None)
        block_text = getattr(block, "text", None)
        if block_type == "text" and isinstance(block_text, str) and block_text.strip():
            fragments.append(block_text.strip())
    return "\n".join(fragments).strip()


def _extract_openai_sdk_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if choices:
        message = getattr(choices[0], "message", None)
        return "\n".join(_coerce_text_fragments(getattr(message, "content", None))).strip()
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    return ""


def _extract_anthropic_http_text(body: dict[str, Any]) -> str:
    content = body.get("content") or []
    if not content or not isinstance(content, list):
        raise RuntimeError(f"Anthropic response missing content: {body}")
    saw_thinking = False
    fragments: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip()
        if block_type == "thinking":
            saw_thinking = True
        if block_type in {"text", ""}:
            candidate = str(block.get("text") or "").strip()
            if candidate:
                fragments.append(candidate)
    if fragments:
        return "\n".join(fragments)
    if saw_thinking:
        raise RuntimeError(
            "Anthropic response returned thinking blocks but no text blocks. "
            f"Upstream gateway may be speaking Claude Code / non-standard Messages format: {body}"
        )
    raise RuntimeError(f"Anthropic response missing text: {body}")


def _extract_openai_compatible_text(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        # Choices are alternative completions, not consecutive program fragments.
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, dict) else None
        fragments = _coerce_text_fragments(message.get("content")) if isinstance(message, dict) else []
        if fragments:
            return "\n".join(fragments)
        raise RuntimeError("OpenAI-compatible response missing output text in the first choice.")

    # Some gateways return Responses-style bodies even on OpenAI-compatible routes.
    output_text = str(body.get("output_text") or "").strip()
    if output_text:
        return output_text
    output = body.get("output") or []
    if isinstance(output, list):
        fragments = []
        for item in output:
            if not isinstance(item, dict):
                continue
            fragments.extend(_coerce_text_fragments(item.get("content")))
        if fragments:
            return "\n".join(fragments)

    error = body.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        if message:
            raise ProviderResponseError(f"OpenAI-compatible API error: {message}")
    raise RuntimeError(f"OpenAI-compatible response missing output text: {body}")


def _coerce_text_fragments(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content.strip()] if content.strip() else []
    if not isinstance(content, list):
        return [str(content).strip()] if content is not None and str(content).strip() else []
    fragments: list[str] = []
    for part in content:
        if isinstance(part, str):
            if part.strip():
                fragments.append(part.strip())
            continue
        if not isinstance(part, dict):
            continue
        candidate = str(part.get("text") or part.get("output_text") or "").strip()
        part_type = str(part.get("type") or "").strip()
        if candidate and part_type in {"text", "output_text", "input_text", ""}:
            fragments.append(candidate)
    return fragments
