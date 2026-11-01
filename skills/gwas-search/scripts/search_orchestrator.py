from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .common import log_step, sort_results
from .search_exact_id import candidate_matches_exact_id, search_one_side_by_id
from .search_output import (
    build_raw_result_entry,
    build_summary,
    has_opengwas_auth_error,
    shortlist_workbook_path,
    with_download_descriptor,
    write_raw_artifact,
    write_shortlists_artifact,
)
from .search_side import candidate_matches_requested_ancestry, search_one_side
from .search_sources import (
    infer_source_from_study_id,
    normalize_source_name,
    resolve_search_route,
)
from .trait_resolver import (
    compact_text,
    unique_strings,
)


def run_target_search(
    *,
    trait: str,
    study_id: str,
    source: str,
    ancestry: str | None,
    sources: List[str],
    preferred_sources: List[str],
    allow_source_fallback: bool,
    limit_per_source: int,
    check_download: bool,
    fallback_artifact_dir: Path | None,
    aliases: List[str] | None = None,
) -> Dict[str, Any]:
    trait_text = compact_text(trait)
    study_id_text = compact_text(study_id)
    if not trait_text and not study_id_text:
        return _blocked(
            failure_class="invalid_target",
            message="gwas-search requires trait, study_id, or both.",
            diagnostics={},
        )

    route = resolve_search_route(
        study_id=study_id_text,
        source=source,
        ancestry=ancestry,
        default_sources=sources,
        preferred_sources=preferred_sources,
        allow_source_fallback=allow_source_fallback,
    )
    if route.get("failure_class"):
        return _blocked(
            failure_class=str(route["failure_class"]),
            message=str(route.get("message") or "GWAS search route is invalid."),
            diagnostics=dict(route.get("diagnostics") or {}),
        )
    normalized_input_source = str(route.get("source") or "")
    normalized_ancestry = route.get("ancestry")
    sources = list(route.get("sources") or [])
    preferred_sources = list(route.get("preferred_sources") or [])
    allow_source_fallback = bool(route.get("allow_source_fallback"))

    if study_id_text:
        return _run_exact_id_target(
            trait=trait_text,
            study_id=study_id_text,
            source=normalized_input_source,
            ancestry=normalized_ancestry,
            check_download=check_download,
            preferred_sources=preferred_sources,
            allow_source_fallback=allow_source_fallback,
            fallback_artifact_dir=fallback_artifact_dir,
        )

    if not sources:
        return _blocked(
            failure_class="search_sources_unconfigured",
            message="No GWAS sources are configured for trait search.",
            diagnostics={},
        )
    return _run_trait_target(
        aliases=aliases,
        trait=trait_text,
        ancestry=normalized_ancestry,
        sources=sources,
        preferred_sources=preferred_sources,
        allow_source_fallback=allow_source_fallback,
        limit_per_source=limit_per_source,
        check_download=check_download,
        fallback_artifact_dir=fallback_artifact_dir,
    )


def _run_exact_id_target(
    *,
    trait: str,
    study_id: str,
    source: str,
    ancestry: str | None,
    check_download: bool,
    preferred_sources: List[str],
    allow_source_fallback: bool,
    fallback_artifact_dir: Path | None,
) -> Dict[str, Any]:
    raw_source = compact_text(source)
    normalized_source = (
        normalize_source_name(raw_source)
        if raw_source
        else infer_source_from_study_id(study_id)
    )
    if not normalized_source:
        return _blocked(
            failure_class="exact_id_source_unresolved",
            message=(
                f"Could not resolve a supported source for study_id={study_id}."
            ),
            diagnostics={"study_id": study_id, "source": raw_source or None},
        )

    log_step(
        f"Starting exact-ID target search: source={normalized_source}; "
        f"study_id={study_id}."
    )
    candidates, reports, id_diagnostics = search_one_side_by_id(
        side="target",
        study_id=study_id,
        source=normalized_source,
        ancestry=ancestry,
        check_download=check_download,
    )
    exact_candidates = [
        with_download_descriptor(item)
        for item in candidates
        if candidate_matches_exact_id(
            item,
            compact_text(study_id).casefold(),
            normalized_source,
        )
    ]
    ancestry_matched_candidates = [
        item
        for item in exact_candidates
        if candidate_matches_requested_ancestry(item, ancestry)
    ]
    if ancestry and exact_candidates and not ancestry_matched_candidates:
        return _blocked(
            failure_class="study_id_ancestry_conflict",
            message=(
                f"Exact study_id={study_id} does not match "
                f"ancestry={ancestry}."
            ),
            diagnostics={
                "study_id": study_id,
                "source": normalized_source,
                "ancestry": ancestry,
                "candidate_ancestries": unique_strings(
                    [
                        item.get("ancestry_raw") or item.get("ancestry")
                        for item in exact_candidates
                    ]
                ),
            },
        )
    exact_candidates = ancestry_matched_candidates
    exact_candidates = [
        item for item in exact_candidates if _download_descriptor_ready(item)
    ][:1]
    status = compact_text(id_diagnostics.get("status")).lower()
    if not exact_candidates and status not in {"", "ok", "empty"}:
        return _blocked(
            failure_class=(
                "authentication_required"
                if status == "auth_required"
                else "exact_id_lookup_failed"
            ),
            message=(
                compact_text(id_diagnostics.get("message"))
                or f"Exact-ID lookup failed for {normalized_source}:{study_id}."
            ),
            diagnostics=id_diagnostics,
        )

    reported_trait = (
        compact_text(exact_candidates[0].get("trait"))
        if exact_candidates
        else ""
    )
    target = {
        "kind": "study_id",
        "value": study_id,
        "source": normalized_source,
        "resolved_query": trait or reported_trait or study_id,
        "aliases": [],
    }
    diagnostics = {
        "candidate_count": len(exact_candidates),
        "sources_attempted": [normalized_source],
        "search_exhausted": not exact_candidates,
        "preferred_sources": list(preferred_sources or []),
        "allow_source_fallback": bool(allow_source_fallback),
        "source_reports": list(reports),
        "id_search": dict(id_diagnostics or {}),
    }
    return _search_response(
        target=target,
        candidates=exact_candidates,
        diagnostics=diagnostics,
        raw_results=[build_raw_result_entry(item) for item in candidates],
        fallback_artifact_dir=fallback_artifact_dir,
    )


def _run_trait_target(
    *,
    aliases: List[str] | None,
    trait: str,
    ancestry: str | None,
    sources: List[str],
    preferred_sources: List[str],
    allow_source_fallback: bool,
    limit_per_source: int,
    check_download: bool,
    fallback_artifact_dir: Path | None,
) -> Dict[str, Any]:
    query = compact_text(trait)
    aliases = [value for value in unique_strings(aliases or []) if value.casefold() != query.casefold()]
    resolved = {"query": query, "aliases": aliases}
    log_step(
        f"Starting trait target search: trait={trait}; query={query}; "
        f"sources={','.join(sources)}."
    )
    output = _search_trait_once(
        query=query,
        aliases=aliases,
        ancestry=ancestry,
        sources=sources,
        limit_per_source=limit_per_source,
        check_download=check_download,
    )
    if (
        not output["candidates"]
        and _all_sources_failed(output["source_reports"])
    ):
        failure_class = (
            "authentication_required"
            if has_opengwas_auth_error(output["source_reports"])
            else "search_infrastructure_failure"
        )
        return _blocked(
            failure_class=failure_class,
            message=(
                f"All configured sources failed while searching trait={trait}."
            ),
            diagnostics={"source_reports": output["source_reports"]},
        )

    attempted_sources = unique_strings(
        [
            report.get("source")
            for report in output["source_reports"]
            if isinstance(report, dict)
        ]
    )
    target = {
        "kind": "trait",
        "value": trait,
        "resolved_query": compact_text(resolved.get("query")) or trait,
        "aliases": unique_strings(list(resolved.get("aliases") or [])),
    }
    diagnostics = {
        "candidate_count": len(output["candidates"]),
        "sources_attempted": attempted_sources,
        "search_exhausted": not output["candidates"] and all(
            report.get("status") in {"ok", "empty"} for report in output["source_reports"]
        ),
        "preferred_sources": list(preferred_sources or []),
        "allow_source_fallback": bool(allow_source_fallback),
        "source_reports": list(output["source_reports"]),
        "source_timings": dict(output["source_timings"]),
    }
    return _search_response(
        target=target,
        candidates=output["candidates"],
        diagnostics=diagnostics,
        raw_results=output["raw_results"],
        fallback_artifact_dir=fallback_artifact_dir,
    )


def _search_trait_once(
    *,
    query: str,
    aliases: List[str],
    ancestry: str | None,
    sources: List[str],
    limit_per_source: int,
    check_download: bool,
) -> Dict[str, Any]:
    candidates, reports, raw_results, timings, _ordered = search_one_side(
        side="target",
        query=query,
        aliases=aliases,
        ancestry=ancestry,
        sources=sources,
        limit_per_source=limit_per_source,
        check_download=check_download,
    )
    del _ordered
    return {
        "candidates": sort_results(
            [with_download_descriptor(item) for item in candidates],
            strip_internal=True,
        ),
        "source_reports": list(reports),
        "raw_results": list(raw_results),
        "source_timings": dict(timings),
    }


def _search_response(
    *,
    target: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    diagnostics: Dict[str, Any],
    raw_results: List[Dict[str, Any]],
    fallback_artifact_dir: Path | None,
) -> Dict[str, Any]:
    shortlist_path, shortlist_artifacts = write_shortlists_artifact(
        candidates,
        target=target,
        diagnostics=diagnostics,
        fallback_dir=fallback_artifact_dir,
    )
    payload: Dict[str, Any] = {
        "target": target,
        "sources_searched": list(diagnostics.get("sources_attempted") or []),
        "search_diagnostics": diagnostics,
    }
    if shortlist_path:
        payload["shortlists_path"] = shortlist_path
    workbook_path = shortlist_workbook_path(shortlist_artifacts)
    if workbook_path:
        payload["shortlists_xlsx_path"] = workbook_path
    artifacts = shortlist_artifacts + write_raw_artifact(
        {
            "target": target,
            "raw_results": raw_results,
            "search_diagnostics": diagnostics,
        }
    )
    if not candidates:
        target_kind = compact_text(target.get("kind"))
        target_value = compact_text(target.get("value")) or "unspecified"
        if target_kind == "study_id":
            failure_class = "exact_id_not_downloadable"
            message = (
                f"Exact study_id={target_value} did not resolve to an "
                "executable downloadable candidate."
            )
        else:
            failure_class = "no_downloadable_candidates"
            message = (
                f"No executable downloadable candidate was found for "
                f"trait={target_value}."
            )
        return _blocked(
            failure_class=failure_class,
            message=message,
            diagnostics=diagnostics,
            artifacts=artifacts,
        )
    summary = build_summary(payload, exposure_results=candidates)
    log_step(
        f"Completed target search: kind={target.get('kind')}; "
        f"value={target.get('value')}; candidates={len(candidates)}."
    )
    return {
        "summary": summary,
        "outputs": {"status": "ok", "gwas_search_results": payload},
        "details": {
            "result_status": "ok",
            "failure_class": None,
            "candidate_count": len(candidates),
            "search_exhausted": not candidates,
            "search_diagnostics": diagnostics,
        },
        "artifacts": artifacts,
    }


def _blocked(
    *,
    failure_class: str,
    message: str,
    diagnostics: Dict[str, Any],
    artifacts: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    log_step(f"Blocked: {message}", error=True)
    response = {
        "summary": f"GWAS search blocked: {message}",
        "outputs": {"status": "blocked"},
        "details": {
            "result_status": "blocked",
            "failure_class": failure_class,
            "message": message,
            "diagnostics": diagnostics,
        },
    }
    if artifacts:
        response["artifacts"] = artifacts
    return response


def _download_descriptor_ready(candidate: Dict[str, Any]) -> bool:
    if not bool(candidate.get("downloadable")):
        return False
    descriptor = candidate.get("download_descriptor")
    if not isinstance(descriptor, dict):
        return False
    if compact_text(descriptor.get("status")).lower() != "ready":
        return False
    if compact_text(descriptor.get("method")).lower() not in {"url", "api"}:
        return False
    return bool(
        compact_text(descriptor.get("url"))
        or compact_text(descriptor.get("api"))
    )


def _all_sources_failed(reports: List[Dict[str, Any]]) -> bool:
    statuses = [
        compact_text(report.get("status")).lower()
        for report in reports
        if isinstance(report, dict)
    ]
    if not statuses:
        return False
    return all(status not in {"ok", "empty"} for status in statuses)
