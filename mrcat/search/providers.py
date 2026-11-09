from __future__ import annotations

import os
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from mrcat.config.llm_limits import LLM_MAX_OUTPUT_TOKENS, LLM_TIMEOUT_SECONDS
from mrcat.model.llm_usage import record_llm_usage
from .types import SearchRequest, SearchResponse, SearchTraceSink


DEEPSEEK_MAX_SEARCH_USES = 3
DEEPSEEK_MAX_OUTPUT_TOKENS = LLM_MAX_OUTPUT_TOKENS


class WebSearchProvider(Protocol):
    name: str

    def search(
        self,
        request: SearchRequest,
        *,
        trace_sink: SearchTraceSink | None = None,
    ) -> SearchResponse:
        ...


class WebSearchNoTextError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        raw_response: Any,
        output_item_types: list[str],
        provider: str,
    ) -> None:
        super().__init__(message)
        self.raw_response = raw_response
        self.output_item_types = output_item_types
        self.provider = provider


class DeepSeekWebSearchProvider:
    name = "deepseek"

    def __init__(self, client: Any | None = None, *, prompt_renderer=None) -> None:
        self._client = client
        self._prompt_renderer = prompt_renderer or render_search_input

    def search(
        self,
        request: SearchRequest,
        *,
        trace_sink: SearchTraceSink | None = None,
    ) -> SearchResponse:
        from anthropic import Anthropic

        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key and self._client is None:
            raise RuntimeError("DEEPSEEK_API_KEY is required for DeepSeek web search")
        model = os.environ.get(
            "DEEPSEEK_SEARCH_MODEL",
            os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        )
        client = self._client or Anthropic(
            auth_token=api_key,
            base_url=_anthropic_base_url(os.environ.get("DEEPSEEK_BASE_URL")),
            timeout=float(LLM_TIMEOUT_SECONDS),
        )
        message = _stream_deepseek_search_message(
            client=client,
            model=model,
            prompt=self._prompt_renderer(request),
            trace_sink=trace_sink,
        )
        content = list(getattr(message, "content", None) or [])
        raw = _to_plain_data(message)
        usage = _to_plain_data(getattr(message, "usage", None))
        record_llm_usage(usage)
        text = _message_text(content)
        if not text:
            raise WebSearchNoTextError(
                "DeepSeek web search returned no synthesized text",
                raw_response=raw,
                output_item_types=_deepseek_output_item_types(raw),
                provider=self.name,
            )
        if _looks_like_tool_protocol(text):
            raise WebSearchNoTextError(
                "DeepSeek web search returned tool protocol instead of a synthesized report",
                raw_response=raw,
                output_item_types=_deepseek_output_item_types(raw),
                provider=self.name,
            )
        citations = _deepseek_citations(content)
        queries = _deepseek_queries(content)
        return SearchResponse(
            text=text,
            citations=citations,
            queries=queries or [request.query],
            provider=self.name,
            model=str(getattr(message, "model", None) or model),
            usage=usage if isinstance(usage, dict) else {"value": usage},
            raw_response=raw,
        )


class _OpenAICompatibleResponsesWebSearchProvider:
    name = ""
    label = "OpenAI-compatible"
    api_key_env_names: tuple[str, ...] = ()
    model_env_names: tuple[str, ...] = ()
    default_model = ""
    base_url_env_name = ""
    default_base_url = ""
    missing_api_key_message = ""

    def __init__(self, client: Any | None = None, *, prompt_renderer=None) -> None:
        self._client = client
        self._prompt_renderer = prompt_renderer or render_search_input

    def search(
        self,
        request: SearchRequest,
        *,
        trace_sink: SearchTraceSink | None = None,
    ) -> SearchResponse:
        api_key = _first_env(self.api_key_env_names)
        if not api_key and self._client is None:
            raise RuntimeError(self.missing_api_key_message)
        model = _first_env(self.model_env_names) or self.default_model
        client = self._client
        if client is None:
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                base_url=os.environ.get(self.base_url_env_name, self.default_base_url),
                timeout=float(LLM_TIMEOUT_SECONDS),
            )
        _emit_trace(trace_sink, "search_started", {"provider": self.name})
        response = client.responses.create(
            model=model,
            tools=[{"type": "web_search"}],
            tool_choice="required",
            input=self._prompt_renderer(request),
        )
        _emit_trace(trace_sink, "search_synthesizing", {"provider": self.name})
        raw = _to_plain_data(response)
        usage = (
            dict(raw.get("usage") or {})
            if isinstance(raw, dict)
            else {}
        )
        record_llm_usage(usage)
        text = str(getattr(response, "output_text", "") or "").strip()
        if not text and self.name == "openai":
            text = _openai_message_text(raw)
        if not text:
            raise WebSearchNoTextError(
                f"{self.label} web search returned no synthesized text",
                raw_response=raw,
                output_item_types=_openai_output_item_types(raw),
                provider=self.name,
            )
        return SearchResponse(
            text=text,
            citations=_openai_citations(raw),
            queries=_openai_queries(raw) or [request.query],
            provider=self.name,
            model=str(getattr(response, "model", None) or model),
            usage=usage,
            raw_response=raw,
        )


class OpenAIWebSearchProvider(_OpenAICompatibleResponsesWebSearchProvider):
    name = "openai"
    label = "OpenAI"
    api_key_env_names = ("OPENAI_API_KEY",)
    model_env_names = ("OPENAI_SEARCH_MODEL", "OPENAI_MODEL")
    default_model = "gpt-5.5"
    base_url_env_name = "OPENAI_BASE_URL"
    default_base_url = "https://api.openai.com/v1"
    missing_api_key_message = "OPENAI_API_KEY is required for OpenAI web search"


class QwenWebSearchProvider(_OpenAICompatibleResponsesWebSearchProvider):
    name = "qwen"
    label = "Qwen"
    api_key_env_names = ("DASHSCOPE_API_KEY", "QWEN_API_KEY")
    model_env_names = ("QWEN_SEARCH_MODEL", "QWEN_MODEL")
    default_model = "qwen3.6-plus"
    base_url_env_name = "QWEN_BASE_URL"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    missing_api_key_message = (
        "QWEN_API_KEY or DASHSCOPE_API_KEY is required for Qwen web search"
    )


def build_provider_registry(*, prompt_renderer=None) -> dict[str, WebSearchProvider]:
    return {
        "deepseek": DeepSeekWebSearchProvider(prompt_renderer=prompt_renderer),
        "openai": OpenAIWebSearchProvider(prompt_renderer=prompt_renderer),
        "qwen": QwenWebSearchProvider(prompt_renderer=prompt_renderer),
    }


def render_search_input(request: SearchRequest) -> str:
    return (
        "Task\n"
        "Search the web for evidence relevant to the research goal.\n"
        "Focus on concrete search findings: primary MR evidence, supporting genetic and contextual evidence, GWAS data resources, limitations and evidence gaps, and one downstream MR analysis plan.\n"
        "Prefer primary studies, official dataset pages, OpenGWAS, GWAS Catalog, FinnGen, Pan-UKB pages, and recent peer-reviewed sources.\n"
        "When searching for datasets or GWAS sources, prioritize OpenGWAS, GWAS Catalog, FinnGen, and Pan-UKB first because these sources align best with the downstream MR pipeline.\n"
        "Mention other pQTL/eQTL resources only as supporting or manual-file resources.\n"
        "State uncertainty and cite sources.\n"
        "Return only the search findings.\n\n"
        "Search Request\n"
        f"{request.query.strip()}\n\n"
        "Research Goal\n"
        f"{request.memory_summary.strip() or 'Not specified.'}\n\n"
        "Output Focus\n"
        "Structure the answer with these five level-2 Markdown headings:\n"
        "## 1. Primary Mendelian Randomization Evidence\n"
        "Include direct MR studies and MR meta-analyses, quantitative effect estimates when reported, and citations. If no direct MR evidence is found, state that explicitly.\n"
        "## 2. Supporting Genetic and Contextual Evidence\n"
        "Include relevant genetic, mechanistic, or observational context, and clearly distinguish it from direct MR causal evidence.\n"
        "## 3. GWAS Data Resources\n"
        "Prioritize candidate study IDs, data source, ancestry, sample size, and summary-statistics availability when reported.\n"
        "## 4. Limitations and Evidence Gaps\n"
        "Cover ancestry limitations, pleiotropy, sample overlap, conflicting findings, and missing information when relevant.\n"
        "## 5. Recommended MR Analysis Plan\n"
        "Provide one short, actionable paragraph for downstream MR analysis. Do not invent study IDs or unavailable metadata."
    )


_render_search_input = render_search_input


def _stream_deepseek_search_message(
    *,
    client: Any,
    model: str,
    prompt: str,
    trace_sink: SearchTraceSink | None,
) -> Any:
    _emit_trace(trace_sink, "search_started", {"provider": "deepseek"})
    search_count = 0
    synthesizing_emitted = False
    with client.messages.stream(
        model=model,
        max_tokens=DEEPSEEK_MAX_OUTPUT_TOKENS,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
        tool_choice={"type": "auto"},
        tools=[
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": DEEPSEEK_MAX_SEARCH_USES,
            }
        ],
    ) as stream:
        for event in stream:
            block = _stream_content_block(event)
            block_type = str(getattr(block, "type", "") or "")
            if block_type == "server_tool_use":
                search_count += 1
                _emit_trace(
                    trace_sink,
                    "search_tool_started",
                    {
                        "provider": "deepseek",
                        "index": search_count,
                        "max_uses": DEEPSEEK_MAX_SEARCH_USES,
                    },
                )
            elif block_type == "text" and not synthesizing_emitted:
                synthesizing_emitted = True
                _emit_trace(
                    trace_sink,
                    "search_synthesizing",
                    {"provider": "deepseek"},
                )
        message = stream.get_final_message()
    if _message_text(list(getattr(message, "content", None) or [])) and not synthesizing_emitted:
        _emit_trace(
            trace_sink,
            "search_synthesizing",
            {"provider": "deepseek"},
        )
    return message


def _stream_content_block(event: Any) -> Any:
    if str(getattr(event, "type", "") or "") == "content_block_start":
        return getattr(event, "content_block", None)
    return event


def _emit_trace(
    trace_sink: SearchTraceSink | None,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    if trace_sink is not None:
        trace_sink(event_type, payload)


def _first_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _message_text(content: list[Any]) -> str:
    return "\n".join(
        str(getattr(block, "text", "") or "").strip()
        for block in content
        if str(getattr(block, "type", "") or "") == "text"
    ).strip()


def _looks_like_tool_protocol(text: str) -> bool:
    normalized = str(text or "").lower()
    markers = (
        "dsml",
        "<tool_calls",
        "<tool_call",
        "<invoke name=",
        "server_tool_use",
    )
    return any(marker in normalized for marker in markers)


def _anthropic_base_url(value: str | None) -> str:
    base_url = (value or "https://api.deepseek.com").rstrip("/")
    if not base_url.endswith("/anthropic"):
        base_url += "/anthropic"
    return base_url


def _deepseek_citations(content: list[Any]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for block in content:
        block_type = str(getattr(block, "type", "") or "")
        if block_type == "web_search_tool_result":
            candidates = getattr(block, "content", None) or []
        elif block_type == "text":
            candidates = getattr(block, "citations", None) or []
        else:
            continue
        for candidate in candidates if isinstance(candidates, list) else []:
            url = _sanitize_url(str(getattr(candidate, "url", "") or ""))
            if not url or url in seen:
                continue
            title = str(getattr(candidate, "title", None) or url)
            citations.append(
                {
                    "citation_id": f"C{len(citations) + 1}",
                    "title": title,
                    "url": url,
                }
            )
            seen.add(url)
    return citations


def _deepseek_queries(content: list[Any]) -> list[str]:
    queries: list[str] = []
    for block in content:
        if str(getattr(block, "type", "") or "") != "server_tool_use":
            continue
        tool_input = getattr(block, "input", None)
        query = ""
        if isinstance(tool_input, dict):
            query = str(tool_input.get("query") or "").strip()
        else:
            query = str(getattr(tool_input, "query", "") or "").strip()
        if query and query not in queries:
            queries.append(query)
    return queries


def _deepseek_output_item_types(raw: Any) -> list[str]:
    if not isinstance(raw, dict):
        return []
    content = raw.get("content")
    if not isinstance(content, list):
        return []
    return [
        item_type
        for item in content
        if isinstance(item, dict)
        and (item_type := str(item.get("type") or "").strip())
    ]


def _openai_citations(raw: Any) -> list[dict[str, str]]:
    candidates: list[tuple[str, str]] = []
    for item in _walk_values(raw):
        if not isinstance(item, dict):
            continue
        url = _sanitize_url(str(item.get("url") or "").strip())
        if not url:
            continue
        item_type = str(item.get("type") or "").strip()
        if item_type not in {"url_citation", "source"} and not (
            "title" in item and "url" in item
        ):
            continue
        candidates.append((str(item.get("title") or url), url))
    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for title, url in candidates:
        if url in seen:
            continue
        citations.append(
            {
                "citation_id": f"C{len(citations) + 1}",
                "title": title,
                "url": url,
            }
        )
        seen.add(url)
    return citations


def _openai_queries(raw: Any) -> list[str]:
    queries: list[str] = []
    for item in _walk_values(raw):
        if not isinstance(item, dict):
            continue
        for key in ("query", "search_query"):
            query = str(item.get(key) or "").strip()
            if query and query not in queries:
                queries.append(query)
        value = item.get("queries")
        if isinstance(value, list):
            for candidate in value:
                query = str(candidate or "").strip()
                if query and query not in queries:
                    queries.append(query)
    return queries


def _openai_message_text(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    output = raw.get("output")
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if str(block.get("type") or "") not in {"output_text", "text"}:
                continue
            text = str(block.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _openai_output_item_types(raw: Any) -> list[str]:
    if not isinstance(raw, dict):
        return []
    output = raw.get("output")
    if not isinstance(output, list):
        return []
    types: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip()
        if item_type:
            types.append(item_type)
    return types


def _walk_values(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


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


def _sanitize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlsplit(url)
    if parsed.username is None and parsed.password is None:
        return url
    hostname = parsed.hostname or ""
    if ":" in hostname:
        hostname = f"[{hostname}]"
    if parsed.port is not None:
        hostname += f":{parsed.port}"
    return urlunsplit(
        (parsed.scheme, hostname, parsed.path, parsed.query, parsed.fragment)
    )
