from __future__ import annotations

import time
from typing import Any, Dict, List

from .common import SearchError, build_source_report
from .search_sources import SEARCHERS, normalize_source_name
from .trait_resolver import compact_text


def search_one_side_by_id(
    *,
    side: str,
    study_id: str,
    source: str,
    check_download: bool,
    ancestry: str | None = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    normalized_id = compact_text(study_id)
    raw_source = compact_text(source)
    normalized_source = normalize_source_name(source)
    if not normalized_id:
        return [], [], {}
    if not normalized_source:
        status = "unsupported_source" if raw_source else "source_unresolved"
        report = build_source_report(
            source=raw_source or "unknown",
            status=status,
            n_results=0,
            message=(
                f"{side}: explicit source '{raw_source}' is unsupported."
                if raw_source
                else f"{side}: study_id was provided but source could not be "
                "resolved; exact-ID search cannot continue."
            ),
        )
        return [], [report], {
            "status": status,
            "study_id": normalized_id,
            "source": raw_source or None,
        }
    if normalized_source not in SEARCHERS:
        report = build_source_report(
            source=normalized_source,
            status="error",
            n_results=0,
            message=f"{side}: unsupported source for ID search.",
        )
        return [], [report], {
            "status": "error",
            "study_id": normalized_id,
            "source": normalized_source,
        }
    searcher = SEARCHERS[normalized_source]()
    started_at = time.perf_counter()
    try:
        resolver = getattr(searcher, "search_by_id", None)
        if not callable(resolver):
            raise SearchError(
                f"{normalized_source} does not support ID search.",
                status="unsupported",
            )
        if normalized_source == "pan_ukb":
            results = resolver(
                normalized_id,
                ancestry=ancestry,
                check_download=check_download,
            )
        else:
            results = resolver(
                normalized_id,
                check_download=check_download,
            )
    except SearchError as exc:
        error_message = str(exc)
        report = build_source_report(
            source=normalized_source,
            status=exc.status,
            n_results=0,
            message=(
                f"{side}: ID search failed for {normalized_id}: "
                f"{error_message}"
            ),
            metadata_endpoint=exc.metadata_endpoint,
        )
        return [], [report], {
            "status": exc.status,
            "study_id": normalized_id,
            "source": normalized_source,
            "message": error_message,
            "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
        }
    except Exception as exc:
        report = build_source_report(
            source=normalized_source,
            status="error",
            n_results=0,
            message=(
                f"{side}: ID search failed for {normalized_id}: "
                f"{exc.__class__.__name__}: {exc}"
            ),
        )
        return [], [report], {
            "status": "error",
            "study_id": normalized_id,
            "source": normalized_source,
            "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
        }
    enriched: List[Dict[str, Any]] = []
    for item in results:
        candidate = dict(item)
        candidate["side"] = side
        candidate["_matched_query"] = normalized_id
        candidate["_match_score"] = max(
            int(candidate.get("_match_score") or 0),
            10000,
        )
        enriched.append(candidate)
    downloadable_count = sum(
        1 for item in enriched if bool(item.get("downloadable"))
    )
    status = "ok" if enriched else "empty"
    report = build_source_report(
        source=normalized_source,
        status=status,
        n_results=len(enriched),
        message=(
            f"{side}: ID search for {normalized_id} returned "
            f"{len(enriched)} candidate(s), "
            f"downloadable={downloadable_count}."
        ),
    )
    return enriched, [report], {
        "status": status,
        "study_id": normalized_id,
        "source": normalized_source,
        "candidate_count": len(enriched),
        "downloadable_count": downloadable_count,
        "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
    }


def candidate_matches_exact_id(
    candidate: Dict[str, Any],
    requested: str,
    source: str,
) -> bool:
    if not requested:
        return False
    values: list[Any] = [candidate.get("study_id"), candidate.get("id")]
    candidate_source = compact_text(
        candidate.get("source") or source
    ).lower()
    if candidate_source == "pan_ukb":
        metadata = (
            candidate.get("study_metadata")
            if isinstance(candidate.get("study_metadata"), dict)
            else {}
        )
        raw_record = (
            candidate.get("_raw_record")
            if isinstance(candidate.get("_raw_record"), dict)
            else {}
        )
        values.extend(
            [
                metadata.get("phenocode"),
                metadata.get("filename"),
                raw_record.get("phenocode"),
                raw_record.get("filename"),
            ]
        )
    return any(
        compact_text(value).casefold() == requested
        for value in values
    )
