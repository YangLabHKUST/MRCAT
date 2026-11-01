from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

LLM_USAGE_ENV = "MRCAT_LLM_USAGE_PATH"
LLM_USAGE_FILENAME = "llm_usage.json"
LLM_TOTAL_TOKENS_FIELD = "llm_total_tokens"
LLM_CALL_COUNT_FIELD = "llm_call_count"


@contextmanager
def llm_usage_scope(path: Path) -> Iterator[None]:
    previous = os.environ.get(LLM_USAGE_ENV)
    _ensure_usage_file(path)
    os.environ[LLM_USAGE_ENV] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(LLM_USAGE_ENV, None)
        else:
            os.environ[LLM_USAGE_ENV] = previous


def record_llm_usage(usage: Any) -> None:
    path_text = str(os.environ.get(LLM_USAGE_ENV) or "").strip()
    if not path_text:
        return
    total_tokens = total_tokens_from_usage(usage)
    payload = _to_plain_data(usage)
    keys = ("total_tokens", "prompt_tokens", "completion_tokens", "input_tokens", "output_tokens",
            "cache_creation_input_tokens", "cache_read_input_tokens")
    reported = isinstance(payload, dict) and any(
        isinstance(payload.get(key), (int, float)) and not isinstance(payload.get(key), bool)
        and payload[key] >= 0 for key in keys)
    try:
        _record_usage_call(Path(path_text), total_tokens, reported=reported)
    except Exception:
        return


def read_llm_total_tokens(session_dir: Path | str) -> int:
    path = Path(session_dir) / LLM_USAGE_FILENAME
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    return _positive_int(payload.get(LLM_TOTAL_TOKENS_FIELD))


def read_llm_call_count(session_dir: Path | str) -> int:
    path = Path(session_dir) / LLM_USAGE_FILENAME
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    return _positive_int(payload.get(LLM_CALL_COUNT_FIELD))


def total_tokens_from_usage(usage: Any) -> int:
    payload = _to_plain_data(usage)
    if not isinstance(payload, dict):
        return 0

    explicit_total = _positive_int(payload.get("total_tokens"))
    if explicit_total > 0:
        return explicit_total

    total = 0
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        total += _positive_int(payload.get(key))
    return total


def read_llm_unreported_calls(session_dir: Path | str) -> int:
    try:
        payload = json.loads((Path(session_dir) / LLM_USAGE_FILENAME).read_text())
        return _positive_int(payload.get("llm_unreported_usage_calls"))
    except (OSError, ValueError, AttributeError):
        return 0


def _record_usage_call(path: Path, tokens: int, *, reported: bool) -> None:
    _ensure_usage_file(path)
    with path.open("r+", encoding="utf-8") as handle:
        _lock_file(handle)
        try:
            handle.seek(0)
            raw = handle.read().strip()
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            current = _positive_int(payload.get(LLM_TOTAL_TOKENS_FIELD))
            calls = _positive_int(payload.get(LLM_CALL_COUNT_FIELD))
            unreported = _positive_int(payload.get("llm_unreported_usage_calls"))
            payload = {
                LLM_TOTAL_TOKENS_FIELD: current + max(0, int(tokens)),
                LLM_CALL_COUNT_FIELD: calls + 1,
                "llm_unreported_usage_calls": unreported + int(not reported),
            }
            handle.seek(0)
            handle.truncate()
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            _unlock_file(handle)


def _ensure_usage_file(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            _lock_file(handle)
            try:
                json.dump(
                    {
                        LLM_TOTAL_TOKENS_FIELD: 0,
                        LLM_CALL_COUNT_FIELD: 0,
                        "llm_unreported_usage_calls": 0,
                    },
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                _unlock_file(handle)
    except FileExistsError:
        return


def _lock_file(handle: Any) -> None:
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except (ImportError, OSError):
        return


def _unlock_file(handle: Any) -> None:
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except (ImportError, OSError):
        return


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _to_plain_data(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _to_plain_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain_data(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _to_plain_data(model_dump(mode="json"))
        except TypeError:
            return _to_plain_data(model_dump())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _to_plain_data(to_dict())
    if hasattr(value, "__dict__"):
        return {
            str(key): _to_plain_data(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)
