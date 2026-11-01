"""Text normalization; query selection belongs to the calling agent."""
from typing import Any, List


def compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def unique_strings(values: List[Any]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(text)
    return ordered
