from __future__ import annotations

import time
from typing import Any, Dict, List

from .common import SearchError, build_source_report, log_step, sort_results
from .search_output import build_raw_result_entry, with_download_descriptor
from .search_sources import (
    SEARCHERS,
    SOURCE_METADATA_MULTIPLIER,
    SOURCE_PROBE_BUDGETS,
    normalize_requested_ancestry,
    requested_ancestry_terms,
)
from .trait_resolver import compact_text, unique_strings


def merge_priority_results(
    priority: List[Dict[str, Any]],
    discovered: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged_by_key: dict[tuple[str, str], Dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for item in [*priority, *discovered]:
        key = (
            str(item.get("source") or "").strip(),
            str(item.get("study_id") or item.get("id") or "").strip(),
        )
        if not key[0] or not key[1]:
            continue
        current = merged_by_key.get(key)
        if current is None:
            merged_by_key[key] = dict(item)
            order.append(key)
            continue
        if bool(item.get("downloadable")) and not bool(current.get("downloadable")):
            merged_by_key[key] = dict(item)
    return [merged_by_key[key] for key in order]


def downloadable_candidate_pool(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sort_results(
        [item for item in results if _ready_downloadable(item)],
        strip_internal=True,
    )


def search_one_side(
    *,
    side: str,
    query: str,
    aliases: List[str],
    sources: List[str],
    limit_per_source: int,
    check_download: bool,
    ancestry: str | None = None,
) -> tuple[
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    Dict[str, Any],
    List[Dict[str, Any]],
]:
    variants = unique_strings([query, *aliases])
    dedup: dict[tuple[str, str], Dict[str, Any]] = {}
    reports: List[Dict[str, Any]] = []
    source_timings: dict[str, Any] = {}

    log_step(f"Searching {side}.")
    for source in sources:
        searcher = SEARCHERS[source]()
        supports_post_probe = callable(getattr(searcher, "probe_candidates", None))
        source_started_at = time.perf_counter()
        last_error: SearchError | Exception | None = None
        source_probe_total = 0
        source_probe_success_count = 0
        source_probe_failure_count = 0
        source_stats: dict[str, Any] = {}
        endpoint_failures: list[dict[str, Any]] = []
        cache_stats = getattr(searcher, "cache_stats", None)
        if callable(cache_stats):
            source_stats.update(cache_stats())
        source_dedup: dict[tuple[str, str], Dict[str, Any]] = {}
        raw_candidate_count = 0
        ancestry_filter_drop_count = 0
        log_step(f"Searching {side} in {source}: query variants={len(variants)}.")
        expanded_limit = (
            _search_limit_for_source(source, limit_per_source)
            if supports_post_probe
            else limit_per_source
        )
        for variant in variants:
            try:
                search_kwargs = {
                    "query": variant,
                    "limit": expanded_limit,
                    "check_download": check_download if not supports_post_probe else False,
                }
                if source == "pan_ukb":
                    search_kwargs["ancestry"] = ancestry
                results = searcher.search(**search_kwargs)
                raw_candidate_count += len(results)
                for item in results:
                    enriched = dict(item)
                    enriched["side"] = side
                    enriched["_matched_query"] = variant
                    if not candidate_matches_requested_ancestry(
                        enriched,
                        ancestry,
                    ):
                        ancestry_filter_drop_count += 1
                        continue
                    key = _candidate_dedup_key(enriched, source)
                    if not key[1]:
                        continue
                    existing = source_dedup.get(key)
                    if existing is None or int(enriched.get("_match_score", 0)) > int(
                        existing.get("_match_score", 0)
                    ):
                        source_dedup[key] = enriched
                probe_summary = getattr(searcher, "last_probe_summary", None) or {}
                source_probe_total += int(probe_summary.get("probe_total") or 0)
                source_probe_success_count += int(
                    probe_summary.get("probe_success_count") or 0
                )
                source_probe_failure_count += int(
                    probe_summary.get("probe_failure_count") or 0
                )
                last_source_stats = getattr(searcher, "last_source_stats", None) or {}
                if isinstance(last_source_stats, dict):
                    source_stats.update(last_source_stats)
                    endpoint_failures.extend(last_source_stats.get("endpoint_failures", []))
            except SearchError as exc:
                last_error = exc
                break
            except Exception as exc:
                last_error = exc
                break

        if last_error is None and supports_post_probe and source_dedup:
            try:
                probed_results = searcher.probe_candidates(
                    list(source_dedup.values()),
                    probe_limit=SOURCE_PROBE_BUDGETS.get(source, limit_per_source),
                    check_download=check_download,
                )
                source_dedup = {
                    _candidate_dedup_key({**item, "source": source}, source): {
                        **item,
                        "side": side,
                    }
                    for item in probed_results
                    if _candidate_dedup_key({**item, "source": source}, source)[1]
                }
                probe_summary = getattr(searcher, "last_probe_summary", None) or {}
                source_probe_total = int(probe_summary.get("probe_total") or 0)
                source_probe_success_count = int(
                    probe_summary.get("probe_success_count") or 0
                )
                source_probe_failure_count = int(
                    probe_summary.get("probe_failure_count") or 0
                )
                last_source_stats = getattr(searcher, "last_source_stats", None) or {}
                if isinstance(last_source_stats, dict):
                    source_stats.update(last_source_stats)
            except SearchError as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc

        if last_error is None:
            dedup.update(source_dedup)
        side_count = len(source_dedup)
        executable_count = (
            sum(1 for item in source_dedup.values() if bool(item.get("downloadable")))
            if check_download
            else side_count
        )
        elapsed_ms = int((time.perf_counter() - source_started_at) * 1000)
        source_stats.update(
            {
                "raw_candidate_count": raw_candidate_count,
                "ancestry_filter_drop_count": ancestry_filter_drop_count,
                "unique_candidate_count": side_count,
                "executable_candidate_count": executable_count,
                "dedup_drop_count": max(raw_candidate_count - side_count, 0),
                "probe_budget": int(
                    source_stats.get("probe_budget")
                    or SOURCE_PROBE_BUDGETS.get(
                        source,
                        limit_per_source if check_download else 0,
                    )
                ),
                "probe_count": int(source_stats.get("probe_count") or source_probe_total),
            }
        )
        if isinstance(last_error, SearchError):
            reports.append(
                build_source_report(
                    source=source,
                    status=last_error.status,
                    n_results=0,
                    message=f"{side}: {last_error}",
                    metadata_endpoint=last_error.metadata_endpoint,
                )
            )
            source_timings[source] = {
                "status": last_error.status,
                "n_results": 0,
                "elapsed_ms": elapsed_ms,
                "probe_total": source_probe_total,
                "probe_success_count": source_probe_success_count,
                "probe_failure_count": source_probe_failure_count,
                **source_stats,
            }
            log_step(f"Failed {side} in {source}: {last_error}.",
                error=True,
            )
            continue
        if last_error is not None:
            reports.append(
                build_source_report(
                    source=source,
                    status="error",
                    n_results=0,
                    message=f"{side}: {last_error.__class__.__name__}: {last_error}",
                )
            )
            source_timings[source] = {
                "status": "error",
                "n_results": 0,
                "elapsed_ms": elapsed_ms,
                "probe_total": source_probe_total,
                "probe_success_count": source_probe_success_count,
                "probe_failure_count": source_probe_failure_count,
                **source_stats,
            }
            log_step(
                f"Failed {side} in {source}: "
                f"{last_error.__class__.__name__}: {last_error}.",
                error=True,
            )
            continue

        source_status = "partial" if endpoint_failures else ("ok" if side_count else "empty")
        if endpoint_failures:
            source_stats.update(search_complete=False, endpoint_failures=endpoint_failures)
        reports.append(
            build_source_report(
                source=source,
                status=source_status,
                n_results=side_count,
                message=(
                    f"{side}: retained candidates; incomplete search: {endpoint_failures}"
                    if endpoint_failures else
                    f"{side}: searched {len(variants)} query variant(s)."
                    if side_count
                    else f"{side}: no matches across {len(variants)} query variant(s)."
                ),
            )
        )
        source_timings[source] = {
            "status": source_status,
            "n_results": side_count,
            "elapsed_ms": elapsed_ms,
            "probe_total": source_probe_total,
            "probe_success_count": source_probe_success_count,
            "probe_failure_count": source_probe_failure_count,
            **source_stats,
        }
        log_step(
            f"Finished {side} in {source}: candidates={side_count}; "
            f"probes={source_probe_total}; downloadable={executable_count}; "
            f"elapsed_ms={elapsed_ms}."
        )
        if executable_count >= limit_per_source:
            log_step(
                f"Found enough downloadable {side} candidates in {source}; "
                "skipping remaining sources."
            )
            break

    ordered = sort_results(list(dedup.values()), strip_internal=False)
    raw_results = [build_raw_result_entry(item) for item in ordered]
    downloadable_pool = downloadable_candidate_pool(ordered)
    log_step(f"Finished {side}: downloadable_candidates={len(downloadable_pool)}.")
    return downloadable_pool, reports, raw_results, source_timings, ordered


def candidate_matches_requested_ancestry(
    candidate: Dict[str, Any],
    ancestry: str | None,
) -> bool:
    requested = normalize_requested_ancestry(ancestry)
    if not requested:
        return ancestry in (None, "")

    source = str(candidate.get("source") or "").strip().lower()
    candidate_ancestry = str(candidate.get("ancestry") or "").strip().lower()
    if candidate_ancestry == requested:
        return True
    if source == "finngen" and requested in {"finnish", "european"}:
        return True

    evidence_values: List[Any] = [
        candidate.get("ancestry_raw"),
        candidate.get("study_id"),
    ]
    metadata = candidate.get("study_metadata")
    if isinstance(metadata, dict):
        evidence_values.extend(
            metadata.get(key)
            for key in (
                "population",
                "initialSampleSize",
                "replicationSampleSize",
                "initial_sample_size",
                "cohort",
                "consortium",
            )
        )
    raw_record = candidate.get("_raw_record")
    if isinstance(raw_record, dict):
        evidence_values.extend(
            raw_record.get(key)
            for key in (
                "population",
                "ancestry",
                "pop",
                "ancestries",
                "ancestryCategory",
                "initialSampleDescription",
                "initialSampleSize",
                "replicationSampleSize",
                "cohort",
                "consortium",
            )
        )
    evidence = _normalized_population_evidence(evidence_values)
    padded_evidence = f" {evidence} "
    return any(
        f" {term} " in padded_evidence
        for term in requested_ancestry_terms(requested)
    )


def _normalized_population_evidence(values: List[Any]) -> str:
    parts: List[str] = []

    def collect(value: Any) -> None:
        if value in (None, "", [], {}):
            return
        if isinstance(value, list):
            for item in value:
                collect(item)
            return
        if isinstance(value, dict):
            for item in value.values():
                collect(item)
            return
        text = "".join(
            character.lower() if character.isalnum() else " "
            for character in str(value)
        )
        normalized = " ".join(text.split())
        if normalized:
            parts.append(normalized)

    for value in values:
        collect(value)
    return " ".join(parts)


def _ready_downloadable(item: Dict[str, Any]) -> bool:
    if not bool(item.get("downloadable")):
        return False
    descriptor = with_download_descriptor(item).get("download_descriptor")
    if not isinstance(descriptor, dict):
        return False
    status = compact_text(descriptor.get("status")).lower()
    method = compact_text(descriptor.get("method")).lower()
    if status != "ready" or method not in {"url", "api", "local_path"}:
        return False
    return bool(
        compact_text(descriptor.get("url"))
        or compact_text(descriptor.get("api"))
        or compact_text(descriptor.get("local_path"))
    )


def _candidate_dedup_key(item: Dict[str, Any], source: str) -> tuple[str, str]:
    source_name = str(item.get("source") or source)
    candidate_key = str(
        item.get("_candidate_key") or item.get("study_id") or ""
    ).strip()
    return source_name, candidate_key


def _search_limit_for_source(source: str, limit_per_source: int) -> int:
    budget = SOURCE_PROBE_BUDGETS.get(source)
    if budget is None:
        return limit_per_source
    return max(limit_per_source, budget * SOURCE_METADATA_MULTIPLIER)
