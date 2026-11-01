from __future__ import annotations

from collections.abc import Collection
from typing import Any


def strict_object(
    payload: Any,
    *,
    allowed_fields: Collection[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    unexpected = sorted(set(payload) - set(allowed_fields))
    if unexpected:
        raise ValueError(f"Unexpected {label} field(s): {unexpected}")
    return payload


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def text_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return [
        text
        for item in value
        if (text := clean_text(item))
    ]


def object_list(value: Any, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(
        isinstance(item, dict) for item in value
    ):
        raise ValueError(f"{field} must be a list of objects")
    return [dict(item) for item in value]
