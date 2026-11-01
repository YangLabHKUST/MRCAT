from __future__ import annotations

import argparse
import base64
import copy
import csv
import gzip
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = int(os.getenv("GWAS_SEARCH_HTTP_TIMEOUT", "30"))
DEFAULT_USER_AGENT = os.getenv(
    "GWAS_SEARCH_USER_AGENT",
    "gwas-search-skill/0.1 (+https://anthropic.com/claude-code-skill)"
)
_REFERENCE_FILE = Path(__file__).resolve().parents[1] / "reference" / "databases.md"
_CACHE_VERSION = "2026-04-01-gwas-search-v1"
_PROCESS_MEMO: dict[str, Any] = {}
MISSING_TEXT_VALUES = frozenset({"", "na", "n/a", "null", "none"})
DEFAULT_SEMANTIC_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "had",
        "has",
        "have",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "versus",
        "vs",
        "was",
        "were",
        "with",
    }
)


def display_text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in MISSING_TEXT_VALUES else text


def normalize_search_text(text: Any) -> str:
    normalized = str(text or "").lower().strip()
    normalized = re.sub(r"[_\-/]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def semantic_tokens(
    text: Any,
    *,
    stopwords: Iterable[str] | None = None,
) -> list[str]:
    stopword_set = set(stopwords or DEFAULT_SEMANTIC_STOPWORDS)
    normalized = normalize_search_text(display_text(text))
    return [
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if token and token not in stopword_set
    ]


def token_overlap(query_tokens: Iterable[str], value_tokens: Iterable[str]) -> int:
    return len(set(query_tokens) & set(value_tokens))


def token_coverage(
    query_tokens: Iterable[str],
    values: Iterable[Any],
    *,
    stopwords: Iterable[str] | None = None,
) -> float:
    query_token_list = list(dict.fromkeys(token for token in query_tokens if token))
    if not query_token_list:
        return 0.0
    value_tokens: set[str] = set()
    for value in values:
        value_tokens.update(semantic_tokens(value, stopwords=stopwords))
    if not value_tokens:
        return 0.0
    matched = sum(1 for token in query_token_list if token in value_tokens)
    return matched / float(len(query_token_list))


def required_token_overlap(
    query_tokens: Iterable[str],
    *,
    short_query_token_count: int = 3,
    min_coverage: float = 0.7,
) -> int:
    query_token_list = list(dict.fromkeys(token for token in query_tokens if token))
    token_count = len(query_token_list)
    if token_count <= 0:
        return 0
    if token_count <= short_query_token_count:
        return token_count
    return max(1, min(token_count, int(token_count * min_coverage + 0.999)))


class SearchError(RuntimeError):
    """Structured error for source-specific search failures."""

    def __init__(
        self,
        message: str,
        *,
        status: str = "error",
        metadata_endpoint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.metadata_endpoint = metadata_endpoint


@dataclass
class StudyRecord:
    trait: str
    study_id: str
    source: str
    downloadable: bool
    study_metadata: Dict[str, Any]
    download_url: Optional[str] = None
    auth_required: bool = False
    requires_user_confirmation: bool = False
    download_check: Optional[Dict[str, Any]] = None
    matched_fields: Optional[List[str]] = None


class BaseSearcher:
    source_name: str = "base"

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST", "HEAD"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._session_id = str(os.getenv("MRCAT_SESSION_ID") or "").strip() or None
        self._execution_dir = str(os.getenv("MRCAT_EXECUTION_DIR") or "").strip() or None
        self._session_cache_dir = self._resolve_session_cache_dir(
            session_id=self._session_id,
            execution_dir=self._execution_dir,
        )
        self.cache_scope = "session" if self._session_cache_dir is not None else "process_only"
        self.session_cache_hits = 0
        self.session_cache_misses = 0

    @staticmethod
    def _resolve_session_cache_dir(*, session_id: str | None, execution_dir: str | None) -> Path | None:
        if not session_id or not execution_dir:
            return None
        try:
            execution_path = Path(execution_dir).resolve()
        except OSError:
            return None
        for candidate in [execution_path, *execution_path.parents]:
            if candidate.name not in {"runs", "data_search_runs"}:
                continue
            session_dir = candidate.parent
            if session_dir.name == session_id:
                return session_dir / "cache" / "gwas-search"
            return None
        return None

    @staticmethod
    def stable_hash(value: Any) -> str:
        if isinstance(value, bytes):
            payload = value
        elif isinstance(value, str):
            payload = value.encode("utf-8")
        else:
            payload = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

    def reset_cache_stats(self) -> None:
        self.session_cache_hits = 0
        self.session_cache_misses = 0

    def cache_stats(self) -> dict[str, Any]:
        return {
            "cache_scope": self.cache_scope,
            "session_cache_hits": self.session_cache_hits,
            "session_cache_misses": self.session_cache_misses,
        }

    def with_cache_stats(self, stats: dict[str, Any]) -> dict[str, Any]:
        return {**stats, **self.cache_stats()}

    def _memo_key(self, namespace: str, key: str) -> str:
        return f"{self._session_id or 'no-session'}:{self.source_name}:{namespace}:{key}"

    def memo_get(self, namespace: str, key: str) -> tuple[bool, Any]:
        memo_key = self._memo_key(namespace, key)
        if memo_key not in _PROCESS_MEMO:
            return False, None
        return True, copy.deepcopy(_PROCESS_MEMO[memo_key])

    def memo_set(self, namespace: str, key: str, value: Any) -> None:
        _PROCESS_MEMO[self._memo_key(namespace, key)] = copy.deepcopy(value)

    def _session_cache_path(self, namespace: str, key: str) -> Path | None:
        if self._session_cache_dir is None:
            return None
        return self._session_cache_dir / self.source_name / namespace / f"{key}.json.gz"

    def _load_session_cache_envelope(self, namespace: str, key: str) -> tuple[bool, dict[str, Any] | None]:
        path = self._session_cache_path(namespace, key)
        if path is None:
            return False, None
        if not path.exists():
            self.session_cache_misses += 1
            return False, None
        try:
            raw = gzip.decompress(path.read_bytes()).decode("utf-8")
            payload = json.loads(raw)
        except Exception:
            self.session_cache_misses += 1
            return False, None
        if not isinstance(payload, dict) or payload.get("cache_version") != _CACHE_VERSION:
            self.session_cache_misses += 1
            return False, None
        self.session_cache_hits += 1
        return True, payload

    def _write_session_cache_envelope(self, namespace: str, key: str, payload: dict[str, Any]) -> None:
        path = self._session_cache_path(namespace, key)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = gzip.compress(
            json.dumps(
                {
                    "cache_version": _CACHE_VERSION,
                    **payload,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        temp_path = path.parent / f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}"
        try:
            temp_path.write_bytes(blob)
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def load_session_json(self, namespace: str, key: str) -> tuple[bool, Any]:
        found, payload = self._load_session_cache_envelope(namespace, key)
        if not found or not isinstance(payload, dict) or payload.get("kind") != "json":
            return False, None
        return True, payload.get("payload")

    def save_session_json(self, namespace: str, key: str, payload: Any) -> None:
        self._write_session_cache_envelope(
            namespace,
            key,
            {
                "kind": "json",
                "payload": payload,
            },
        )

    def load_session_bytes(self, namespace: str, key: str) -> tuple[bool, bytes | None]:
        found, payload = self._load_session_cache_envelope(namespace, key)
        if not found or not isinstance(payload, dict) or payload.get("kind") != "bytes":
            return False, None
        encoded = payload.get("payload_b64")
        if not isinstance(encoded, str):
            return False, None
        try:
            return True, base64.b64decode(encoded.encode("ascii"))
        except Exception:
            return False, None

    def save_session_bytes(self, namespace: str, key: str, payload: bytes) -> None:
        self._write_session_cache_envelope(
            namespace,
            key,
            {
                "kind": "bytes",
                "payload_b64": base64.b64encode(payload).decode("ascii"),
            },
        )

    def cached_json_get(self, namespace: str, key: str) -> tuple[bool, Any]:
        found, payload = self.memo_get(namespace, key)
        if found:
            return True, payload
        found, payload = self.load_session_json(namespace, key)
        if found:
            self.memo_set(namespace, key, payload)
            return True, payload
        return False, None

    def cached_json_set(
        self,
        namespace: str,
        key: str,
        payload: Any,
        *,
        persist_session: bool = True,
    ) -> None:
        self.memo_set(namespace, key, payload)
        if persist_session:
            self.save_session_json(namespace, key, payload)

    def cached_bytes_get(self, namespace: str, key: str) -> tuple[bool, bytes | None]:
        found, payload = self.memo_get(namespace, key)
        if found:
            return True, payload
        found, payload = self.load_session_bytes(namespace, key)
        if found:
            self.memo_set(namespace, key, payload)
            return True, payload
        return False, None

    def cached_bytes_set(
        self,
        namespace: str,
        key: str,
        payload: bytes,
        *,
        persist_session: bool = True,
    ) -> None:
        self.memo_set(namespace, key, payload)
        if persist_session:
            self.save_session_bytes(namespace, key, payload)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        r = self.session.get(url, timeout=self.timeout, **kwargs)
        r.raise_for_status()
        return r.json()

    def post_json(self, url: str, payload: dict[str, Any], **kwargs: Any) -> Any:
        r = self.session.post(url, json=payload, timeout=self.timeout, **kwargs)
        r.raise_for_status()
        return r.json()

    def get_text(self, url: str, **kwargs: Any) -> str:
        r = self.session.get(url, timeout=self.timeout, **kwargs)
        r.raise_for_status()
        return r.text

    def get_bytes(self, url: str, **kwargs: Any) -> bytes:
        r = self.session.get(url, timeout=self.timeout, **kwargs)
        r.raise_for_status()
        return r.content

    def download_bytes_with_progress(
        self,
        url: str,
        *,
        label: str = "manifest",
        chunk_size: int = 1024 * 1024,
        **kwargs: Any,
    ) -> bytes:
        log_step(f"Downloading {label}.")
        with self.session.get(url, timeout=self.timeout, stream=True, **kwargs) as response:
            response.raise_for_status()
            total_bytes_raw = response.headers.get("Content-Length", "0") or "0"
            try:
                total_bytes = int(total_bytes_raw)
            except (TypeError, ValueError):
                total_bytes = 0
            downloaded_bytes = 0
            last_emitted_bytes = 0
            chunks: list[bytes] = []
            for chunk in response.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                chunks.append(chunk)
                downloaded_bytes += len(chunk)
                if (
                    downloaded_bytes - last_emitted_bytes >= 8 * 1024 * 1024
                    or (total_bytes and downloaded_bytes >= total_bytes)
                ):
                    if total_bytes > 0:
                        percent = (downloaded_bytes / total_bytes) * 100.0
                        log_step(
                            f"Downloading {label}: {format_mib(downloaded_bytes)} / "
                            f"{format_mib(total_bytes)} ({percent:.1f}%)."
                        )
                    else:
                        log_step(f"Downloading {label}: {format_mib(downloaded_bytes)}.")
                    last_emitted_bytes = downloaded_bytes
        log_step(f"Completed download {label}: {format_mib(downloaded_bytes)}.")
        return b"".join(chunks)

    def head_or_get_check(self, url: str) -> Dict[str, Any]:
        try:
            r = self.session.head(url, timeout=self.timeout, allow_redirects=True)
            if r.status_code < 400:
                return {
                    "method": "HEAD",
                    "ok": True,
                    "status_code": r.status_code,
                    "content_type": r.headers.get("Content-Type"),
                    "content_length": r.headers.get("Content-Length"),
                    "final_url": r.url,
                }
        except requests.RequestException:
            pass

        try:
            r = self.session.get(url, timeout=self.timeout, stream=True, allow_redirects=True)
            ok = r.status_code < 400
            return {
                "method": "GET",
                "ok": ok,
                "status_code": r.status_code,
                "content_type": r.headers.get("Content-Type"),
                "content_length": r.headers.get("Content-Length"),
                "final_url": r.url,
            }
        except requests.RequestException as e:
            return {"method": "GET", "ok": False, "error": str(e)}

    def probe_download_url(
        self,
        url: str,
    ) -> Dict[str, Any]:
        started_at = time.perf_counter()
        log_step(f"Probing URL: {url}.")
        result = self.head_or_get_check(url)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        status = "ok" if result.get("ok") else "failed"
        http_status = result.get("status_code")
        status_text = f" with HTTP {http_status}" if http_status is not None else ""
        log_step(f"URL probe {status}{status_text} in {elapsed_ms} ms: {url}.")
        return result

    def evaluate_download(
        self,
        *,
        download_url: str | None,
        check_download: bool,
        auth_required: bool = False,
        reason_if_missing: str = "unresolved",
    ) -> tuple[bool, str, Optional[Dict[str, Any]]]:
        if auth_required:
            return False, "requires_auth", None
        if not download_url:
            return False, reason_if_missing, None
        if not check_download:
            return True, "resolved_url", None
        download_check = self.probe_download_url(download_url)
        if download_check.get("ok"):
            return True, "confirmed_url", download_check
        return False, "probe_failed", download_check

    @staticmethod
    def normalize_text(text: str) -> str:
        return normalize_search_text(text)

    @classmethod
    def score_match(cls, query: str, values: Iterable[Tuple[str, Any]]) -> Tuple[int, List[str]]:
        q = cls.normalize_text(query)
        score = 0
        fields: List[str] = []
        for field, value in values:
            v = cls.normalize_text(str(value))
            if not v:
                continue
            if q == v:
                score += 100
                fields.append(field)
            elif q in v:
                score += 25
                fields.append(field)
            else:
                q_tokens = [t for t in q.split() if t]
                overlap = sum(1 for t in q_tokens if t in v)
                if overlap:
                    score += overlap * 5
                    fields.append(field)
        return score, sorted(set(fields))

    @staticmethod
    def stable_sample_size(meta: Dict[str, Any]) -> int:
        for key in (
            "sample_size",
            "n_samples",
            "n",
            "samples",
            "n_total",
            "sampleSize",
            "effective_n",
            "initial_sample_size",
            "initialSampleSize",
        ):
            parsed = parse_initial_sample_size(meta.get(key)) if key == "initialSampleSize" else parse_int(meta.get(key))
            if parsed:
                return parsed
        n_cases = parse_int(meta.get("n_cases")) or parse_int(meta.get("ncase")) or parse_int(meta.get("num_cases"))
        n_controls = parse_int(meta.get("n_controls")) or parse_int(meta.get("ncontrol")) or parse_int(meta.get("num_controls"))
        if n_cases and n_controls:
            return n_cases + n_controls
        if n_cases:
            return n_cases
        if n_controls:
            return n_controls
        return 0

    @staticmethod
    def stable_publication_year(meta: Dict[str, Any]) -> int:
        for key in ("publication_year", "publicationYear", "pubYear", "year"):
            val = meta.get(key)
            if isinstance(val, int):
                return val
            if isinstance(val, str) and val.isdigit():
                return int(val)
        return 0


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _stringify_raw_ancestry(raw_value: Any) -> str | None:
    if raw_value in (None, "", [], {}):
        return None
    parts: list[str] = []

    def collect(value: Any) -> None:
        if value in (None, "", [], {}):
            return
        if isinstance(value, list):
            for item in value:
                collect(item)
            return
        if isinstance(value, dict):
            preferred_keys = (
                "ancestry",
                "ancestries",
                "ancestryCategory",
                "ancestralGroups",
                "population",
                "initialSampleDescription",
                "initialSampleSize",
                "replicationSampleSize",
            )
            collected = False
            for key in preferred_keys:
                if key in value and value.get(key) not in (None, "", [], {}):
                    collect(value.get(key))
                    collected = True
            if not collected:
                for item in value.values():
                    if not isinstance(item, (dict, list)):
                        collect(item)
            return
        text = str(value).strip()
        if text:
            parts.append(text)

    collect(raw_value)
    return ", ".join(parts) or None


def normalize_ancestry(raw_value: Any, *, source_name: str = "") -> tuple[str, str | None]:
    """Normalize source-specific ancestry/population text into shared labels.

    Return two layers:
    - ancestry: normalized short label for downstream sorting/filtering.
    - ancestry_raw: original source text for debugging and human review.
    """
    raw_text = _stringify_raw_ancestry(raw_value)
    lowered = (raw_text or "").lower()
    tokens = set(re.findall(r"[a-z0-9]+", lowered))
    canonical_labels = {
        "finnish",
        "european",
        "african",
        "east_asian",
        "admixed_american",
        "central_south_asian",
        "middle_eastern",
        "multi_ancestry",
    }
    if lowered in canonical_labels:
        return lowered, raw_text
    matched: list[str] = []

    def add(label: str) -> None:
        if label not in matched:
            matched.append(label)

    def has_code(*values: str) -> bool:
        return any(value.lower() in tokens for value in values)

    def has_text(*values: str) -> bool:
        return any(value in lowered for value in values)

    if has_code("fin") or has_text("finnish") or source_name == "finngen":
        add("finnish")
    if has_code("eur") or has_text(
        "european",
        "british",
        "british ancestry",
        "white british",
        "non-hispanic white",
        "caucasian",
        "ukb european",
    ):
        add("european")
    if has_code("afr", "african") or has_text(
        "african ancestry",
        "african american",
        "afro-caribbean",
        "african-like",
        "non-hispanic black",
    ):
        add("african")
    if has_code("eas") or has_text(
        "east asian",
        "japanese",
        "korean",
        "chinese",
        "taiwanese",
        "han chinese",
    ):
        add("east_asian")
    if has_code("amr") or has_text(
        "admixed american",
        "latin american",
        "latino",
        "hispanic",
        "native american",
    ):
        add("admixed_american")
    if has_code("sas", "csa") or has_text(
        "south asian",
        "central south asian",
        "central/south asian",
        "indian",
        "pakistani",
        "bangladeshi",
        "sri lankan",
    ):
        add("central_south_asian")
    if has_code("mid", "mea") or has_text(
        "middle eastern",
        "greater middle eastern",
        "north african",
        "arab",
        "persian",
    ):
        add("middle_eastern")
    if has_code("multi", "all", "meta") or has_text(
        "multi-ancestry",
        "multi ancestry",
        "mixed",
        "trans-ethnic",
        "trans ethnic",
    ):
        add("multi_ancestry")

    if len(matched) > 1:
        return "multi_ancestry", raw_text
    if matched:
        return matched[0], raw_text
    return ("finnish" if source_name == "finngen" else "unknown"), raw_text


def slim_study_metadata(raw_metadata: Dict[str, Any], *, extras: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Keep the smallest metadata subset needed downstream without bloating results."""
    allowed_keys = (
        "filename",
        "release",
        "endpoint",
        "endpoint_code",
        "population",
        "publication_date",
        "publication_year",
        "pmid",
        "doi",
        "publication_title",
        "publication_url",
        "author",
        "cohort",
        "cohorts",
        "note",
        "sample_size",
        "n_samples",
        "n_total",
        "n",
        "sampleSize",
        "initial_sample_size",
        "initialSampleSize",
        "replicationSampleSize",
        "initialSampleDescription",
        "replicationSampleDescription",
        "effective_n",
        "ncase",
        "ncontrol",
        "n_cases",
        "n_controls",
        "num_cases",
        "num_controls",
        "trait_type",
        "phenocode",
        "consortium",
        "build",
        "genome_build",
        "genome_assembly",
        "assembly",
        "coordinate_system",
        "is_harmonised",
        "is_harmonized",
        "unit",
        "effect_scale",
        "sex",
        "coverage",
        "nsnp",
        "qc_prior_to_upload",
    )
    metadata: Dict[str, Any] = {}
    for key in allowed_keys:
        value = raw_metadata.get(key)
        if _is_present(value):
            metadata[key] = value
    for key, value in (extras or {}).items():
        if _is_present(value):
            metadata[key] = value
    return metadata


def build_candidate(
    *,
    side: str | None,
    trait: str,
    study_id: str,
    source: str,
    ancestry_value: Any,
    sample_size: int | None,
    n_cases: int | None,
    n_controls: int | None,
    downloadable: bool,
    download_url: str | None,
    auth_required: bool,
    requires_user_confirmation: bool,
    downloadability_reason: str,
    download_check: Dict[str, Any] | None,
    matched_fields: List[str] | None,
    matched_query: str | None,
    raw_metadata: Dict[str, Any],
    metadata_extras: Dict[str, Any] | None = None,
    match_score: int = 0,
    raw_record: Dict[str, Any] | None = None,
    candidate_key: str | None = None,
    family_key: str | None = None,
) -> Dict[str, Any]:
    """Build the compact candidate written to formal outputs.

    Downstream-required fields are promoted to top level; `study_metadata` keeps
    lightweight download, sorting, and study provenance metadata. Full remote
    records go into `_raw_record` so run_search can write a separate raw artifact.
    """
    ancestry, ancestry_raw = normalize_ancestry(ancestry_value, source_name=source)
    metadata = slim_study_metadata(
        raw_metadata,
        extras={
            **(metadata_extras or {}),
        },
    )
    candidate = {
        "trait": trait,
        "study_id": study_id,
        "source": source,
        "ancestry": ancestry,
        "ancestry_raw": ancestry_raw,
        "sample_size": sample_size,
        "n_cases": n_cases,
        "n_controls": n_controls,
        "downloadable": downloadable,
        "download_url": download_url,
        "auth_required": auth_required,
        "requires_user_confirmation": requires_user_confirmation,
        "study_metadata": metadata,
        "downloadability_reason": downloadability_reason,
        "_match_score": match_score,
    }
    if side:
        candidate["side"] = side
    if download_check is not None:
        candidate["_download_check"] = download_check
    if matched_fields:
        candidate["_matched_fields"] = list(matched_fields)
    if matched_query:
        candidate["_matched_query"] = matched_query
    if raw_record is not None:
        candidate["_raw_record"] = raw_record
    if candidate_key:
        candidate["_candidate_key"] = candidate_key
    if family_key:
        candidate["_family_key"] = family_key
    return candidate


def _first_scalar_value(payloads: Iterable[Dict[str, Any]], keys: Iterable[str]) -> Any:
    for payload in payloads:
        for key in keys:
            value = payload.get(key)
            if _is_present(value) and not isinstance(value, (dict, list)):
                return value
    return None


def extract_publication_metadata(raw_metadata: Dict[str, Any]) -> Dict[str, Any]:
    payloads: list[Dict[str, Any]] = [raw_metadata]
    for key in ("publicationInfo", "publication", "publication_info"):
        nested = raw_metadata.get(key)
        if isinstance(nested, dict):
            payloads.append(nested)

    date_value = _first_scalar_value(
        payloads,
        (
            "publication_date",
            "publicationDate",
            "published_date",
            "publishedDate",
            "pubDate",
            "date",
        ),
    )
    year_value = _first_scalar_value(
        payloads,
        (
            "publication_year",
            "publicationYear",
            "published_year",
            "publishedYear",
            "year",
            "pubYear",
        ),
    )

    normalized: Dict[str, Any] = {}
    for field, keys in (
        ("pmid", ("pmid", "pubmedId")),
        ("doi", ("doi", "DOI")),
        ("publication_title", ("publication_title",)),
        ("publication_url", ("publication_url", "pubmedUrl")),
    ):
        value = _first_scalar_value(payloads, keys)
        if _is_present(value):
            normalized[field] = value
    # A nested publication title/URL describes the paper, not the phenotype.
    for field, key in (("publication_title", "title"), ("publication_url", "url")):
        value = _first_scalar_value(payloads[1:], (key,))
        if field not in normalized and _is_present(value):
            normalized[field] = value
    if _is_present(date_value):
        normalized["publication_date"] = str(date_value).strip()
    if _is_present(year_value):
        match = re.search(r"(19|20)\d{2}", str(year_value))
        if match:
            normalized["publication_year"] = int(match.group(0))
    elif "publication_date" in normalized:
        match = re.search(r"(19|20)\d{2}", normalized["publication_date"])
        if match:
            normalized["publication_year"] = int(match.group(0))
    return normalized


def load_reference_config() -> dict[str, Any]:
    text = _REFERENCE_FILE.read_text(encoding="utf-8").lstrip()
    if not text.startswith("---\n"):
        return {}
    _, _, remainder = text.partition("---\n")
    frontmatter_text, _, _ = remainder.partition("\n---")
    payload = yaml.safe_load(frontmatter_text) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def source_config(source_name: str) -> dict[str, Any]:
    config = load_reference_config()
    source_payload = ((config.get("source-config") or {}).get("sources") or {}).get(source_name) or {}
    if not isinstance(source_payload, dict):
        return {}
    return source_payload


def source_metadata_endpoint(source_name: str) -> str | None:
    config = source_config(source_name)
    for key in ("metadata_endpoint", "metadata_url", "manifest_url", "phenos_api", "gwasinfo_endpoint"):
        value = str(config.get(key) or "").strip()
        if value:
            return value
    return None


def build_source_report(
    *,
    source: str,
    status: str,
    n_results: int = 0,
    message: str | None = None,
    metadata_endpoint: str | None = None,
) -> dict[str, Any]:
    payload = {
        "source": source,
        "status": status,
        "n_results": int(n_results),
        "message": message or "",
        "metadata_endpoint": metadata_endpoint or source_metadata_endpoint(source) or "",
    }
    return payload


def read_tsv_rows(data: bytes, *, compressed: bool = False) -> list[dict[str, Any]]:
    if compressed:
        try:
            text = gzip.decompress(data).decode("utf-8")
        except OSError:
            text = data.decode("utf-8")
    else:
        text = data.decode("utf-8")
    reader = csv.DictReader(StringIO(text), delimiter="\t")
    return [{str(key): (value if value is not None else "") for key, value in row.items()} for row in reader]


def read_tsv_rows_with_progress(
    data: bytes,
    *,
    compressed: bool = False,
    label: str = "manifest",
    progress_every: int = 50000,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    log_step(f"Decompressing {label}.")
    decompress_started_at = time.perf_counter()
    if compressed:
        try:
            text = gzip.decompress(data).decode("utf-8")
        except OSError:
            text = data.decode("utf-8")
    else:
        text = data.decode("utf-8")
    decompressed_bytes = len(text.encode("utf-8"))
    log_step(
        f"Decompressed {label}: {format_mib(decompressed_bytes)} in "
        f"{int((time.perf_counter() - decompress_started_at) * 1000)} ms."
    )
    log_step(f"Scanning {label}.")
    rows: list[dict[str, Any]] = []
    scan_started_at = time.perf_counter()
    reader = csv.DictReader(StringIO(text), delimiter="\t")
    for index, row in enumerate(reader, start=1):
        rows.append({str(key): (value if value is not None else "") for key, value in row.items()})
        if progress_every > 0 and index % progress_every == 0:
            log_step(f"Scanning {label}: rows={index}.")
    log_step(
        f"Scanned {label}: rows={len(rows)} in "
        f"{int((time.perf_counter() - scan_started_at) * 1000)} ms."
    )
    return rows, {
        "decompressed_bytes": decompressed_bytes,
        "rows_scanned": len(rows),
        "decompress_elapsed_ms": int((time.perf_counter() - decompress_started_at) * 1000),
        "scan_elapsed_ms": int((time.perf_counter() - scan_started_at) * 1000),
    }


def log_step(message: str, *, error: bool = False) -> None:
    print(f"[gwas-search] {message}", file=sys.stderr if error else sys.stdout, flush=True)


def format_mib(value: int) -> str:
    return f"{value / (1024 * 1024):.1f} MiB"


def extract_trait_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("trait", "label", "name", "value"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return json.dumps(value, ensure_ascii=False)
    return str(value or "").strip()


def parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = re.sub(r"[^0-9.]", "", str(value))
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_initial_sample_size(value: Any) -> int | None:
    if value in (None, ""):
        return None
    matches = re.findall(r"\d[\d,]*", str(value))
    if not matches:
        return None
    total = 0
    for token in matches:
        total += int(token.replace(",", ""))
    return total or None


def write_json(data: Dict[str, Any], out: Optional[str] = None) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(payload)
    else:
        sys.stdout.write(payload + "\n")


def _strip_internal_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(item)
    cleaned.pop("_match_score", None)
    cleaned.pop("_download_check", None)
    cleaned.pop("_matched_fields", None)
    cleaned.pop("_matched_query", None)
    cleaned.pop("_raw_record", None)
    cleaned.pop("_candidate_key", None)
    cleaned.pop("_family_key", None)
    return cleaned


def sort_results(results: List[Dict[str, Any]], *, strip_internal: bool = True) -> List[Dict[str, Any]]:
    def key_fn(item: Dict[str, Any]) -> Tuple[int, int, int, int, int, str, str]:
        downloadable = 1 if item.get("downloadable") else 0
        has_download_url = 1 if item.get("download_url") else 0
        match_score = int(item.get("_match_score") or 0)
        size = BaseSearcher.stable_sample_size(
            {
                "sample_size": item.get("sample_size"),
                "n_cases": item.get("n_cases"),
                "n_controls": item.get("n_controls"),
                **(item.get("study_metadata", {}) or {}),
            }
        )
        publication_year = BaseSearcher.stable_publication_year(item.get("study_metadata", {}) or {})
        return (
            -downloadable,
            -has_download_url,
            -match_score,
            -size,
            -publication_year,
            item.get("source", ""),
            item.get("study_id", ""),
        )

    ordered = sorted(results, key=key_fn)
    if not strip_internal:
        return [dict(item) for item in ordered]
    return [_strip_internal_fields(item) for item in ordered]


def shortlist_results(
    results: List[Dict[str, Any]],
    *,
    per_source_limit: int = 4,
    total_limit: int = 12,
) -> List[Dict[str, Any]]:
    """Shortlist one-sided results to keep skill output bounded."""
    ordered = sort_results(results, strip_internal=False)
    counts_by_source: Dict[str, int] = {}
    shortlisted: List[Dict[str, Any]] = []
    seen_families: set[tuple[str, str]] = set()
    for item in ordered:
        source = str(item.get("source") or "")
        if counts_by_source.get(source, 0) >= per_source_limit:
            continue
        family_key = str(item.get("_family_key") or "").strip()
        if family_key and (source, family_key) in seen_families:
            continue
        shortlisted.append(dict(item))
        counts_by_source[source] = counts_by_source.get(source, 0) + 1
        if family_key:
            seen_families.add((source, family_key))
        if len(shortlisted) >= total_limit:
            break
    return sort_results(shortlisted, strip_internal=True)


def build_parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--query", required=True, help="Natural-language trait query")
    p.add_argument("--out", help="Output JSON path")
    p.add_argument("--limit", type=int, default=30, help="Maximum records to return")
    p.add_argument("--check-download", action="store_true", help="Actively verify download URLs")
    return p


def package_success(query: str, source: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "query": query,
        "source": source,
        "results": sort_results(results),
    }


def package_error(query: str, source: str, exc: Exception) -> Dict[str, Any]:
    status = exc.status if isinstance(exc, SearchError) else "error"
    metadata_endpoint = exc.metadata_endpoint if isinstance(exc, SearchError) else source_metadata_endpoint(source)
    return {
        "query": query,
        "source": source,
        "status": status,
        "metadata_endpoint": metadata_endpoint,
        "error": {
            "type": exc.__class__.__name__,
            "message": str(exc),
        },
        "results": [],
    }
