from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal


SearchProviderName = Literal["deepseek", "openai", "qwen"]
SearchTraceSink = Callable[[str, dict[str, Any]], None]


@dataclass(slots=True)
class SearchRequest:
    query: str
    memory_summary: str
    recent_turns: list[dict[str, str]]


@dataclass(slots=True)
class SearchResponse:
    text: str
    citations: list[dict[str, str]]
    queries: list[str]
    provider: str
    model: str
    usage: dict[str, Any]
    raw_response: Any
