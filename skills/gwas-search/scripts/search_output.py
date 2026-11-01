from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .common import log_step
from .trait_resolver import compact_text, unique_strings


SOURCE_LABELS = {
    "local": "Local",
    "opengwas": "OpenGWAS",
    "gwas_catalog": "GWAS Catalog",
    "finngen": "FinnGen",
    "pan_ukb": "Pan-UKB",
}

SHORTLIST_WORKBOOK_COLUMNS = (
    "Rank",
    "Trait",
    "Study ID",
    "Source",
    "Ancestry",
    "Sample Size",
    "Cases",
    "Controls",
    "Downloadable",
    "Auth Required",
    "Download Status",
    "Download Method",
    "Publication Year",
    "Consortium",
    "Download Location / URL",
    "Selection Reason",
    "Notes",
)


def _ready_existing_descriptor(descriptor: Dict[str, Any]) -> bool:
    status = str(descriptor.get("status") or "").strip().lower()
    method = str(descriptor.get("method") or "").strip().lower()
    if status != "ready" or method not in {"url", "api", "local_path"}:
        return False
    return any(str(descriptor.get(key) or "").strip() for key in ("url", "api", "local_path"))


def download_descriptor(item: Dict[str, Any]) -> Dict[str, Any]:
    source = str(item.get("source") or "").strip()
    study_id = str(item.get("study_id") or "").strip()
    url = str(item.get("download_url") or "").strip()
    metadata = item.get("study_metadata") if isinstance(item.get("study_metadata"), dict) else {}
    requires_auth = bool(item.get("auth_required") or metadata.get("auth_required"))
    existing = item.get("download_descriptor")
    if isinstance(existing, dict) and _ready_existing_descriptor(existing):
        descriptor = dict(existing)
        descriptor.setdefault("source", source)
        descriptor.setdefault("study_id", study_id)
        descriptor.setdefault("requires_auth", requires_auth)
        return descriptor
    descriptor = {
        "source": source,
        "study_id": study_id,
        "status": "ready" if bool(item.get("downloadable")) and url else "unavailable",
        "method": "url" if url else "none",
        "requires_auth": requires_auth,
    }
    if url:
        descriptor["url"] = url
    return descriptor


def with_download_descriptor(item: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(item or {})
    payload["download_descriptor"] = download_descriptor(payload)
    payload.pop("download_url", None)
    return payload


def build_raw_result_entry(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "side": item.get("side"),
        "trait": item.get("trait"),
        "study_id": item.get("study_id"),
        "source": item.get("source"),
        "matched_query": item.get("_matched_query"),
        "matched_fields": item.get("_matched_fields") or [],
        "downloadable": item.get("downloadable"),
        "download_descriptor": download_descriptor(item),
        "downloadability_reason": item.get("downloadability_reason"),
        "download_check": item.get("_download_check"),
        "raw_record": item.get("_raw_record") or {},
    }


def write_raw_artifact(raw_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    execution_dir = os.getenv("MRCAT_EXECUTION_DIR", "").strip()
    if not execution_dir:
        return []
    path = Path(execution_dir) / "gwas_search_raw.json"
    log_step(f"Writing raw search artifact: {path}.")
    path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return [{"path": str(path), "kind": "json", "summary": "gwas_search_raw.json"}]


def write_shortlists_artifact(
    candidates: List[Dict[str, Any]],
    *,
    target: Dict[str, Any],
    diagnostics: Dict[str, Any],
    fallback_dir: Path | None = None,
) -> tuple[str | None, List[Dict[str, Any]]]:
    artifact_dir = os.getenv("MRCAT_EXECUTION_DIR", "").strip()
    if not artifact_dir and fallback_dir is not None:
        artifact_dir = str(fallback_dir)
    if not artifact_dir:
        return None, []
    path = Path(artifact_dir) / "gwas_search_shortlists.json"
    log_step(f"Writing shortlist artifact: {path}.")
    path.write_text(
        json.dumps(
            {
                "target": dict(target or {}),
                "candidates": list(candidates or []),
                "diagnostics": dict(diagnostics or {}),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    workbook_path = path.with_suffix(".xlsx")
    log_step(f"Writing human-readable shortlist workbook: {workbook_path}.")
    write_shortlists_workbook(candidates, workbook_path)
    return str(path), [
        {
            "path": str(workbook_path),
            "kind": "xlsx",
            "summary": "gwas_search_shortlists.xlsx",
        },
        {
            "path": str(path),
            "kind": "json",
            "summary": "gwas_search_shortlists.json",
        }
    ]


def write_shortlists_workbook(
    candidates: List[Dict[str, Any]],
    path: Path,
) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheet = workbook.create_sheet("Candidates")
    sheet.append(SHORTLIST_WORKBOOK_COLUMNS)
    for rank, candidate in enumerate(list(candidates or []), start=1):
        if isinstance(candidate, dict):
            sheet.append(_shortlist_workbook_row(rank, candidate))
    _format_shortlist_sheet(sheet)
    workbook.save(path)


def shortlist_workbook_path(artifacts: List[Dict[str, Any]]) -> str | None:
    for artifact in artifacts:
        if str(artifact.get("summary") or "").strip() == "gwas_search_shortlists.xlsx":
            return str(artifact.get("path") or "").strip() or None
    return None


def _shortlist_workbook_row(rank: int, candidate: Dict[str, Any]) -> tuple[Any, ...]:
    metadata = (
        candidate.get("study_metadata")
        if isinstance(candidate.get("study_metadata"), dict)
        else {}
    )
    descriptor = (
        candidate.get("download_descriptor")
        if isinstance(candidate.get("download_descriptor"), dict)
        else (dict(status="unknown", url=candidate.get("download_url"))
              if candidate.get("downloadable") is None else download_descriptor(candidate))
    )
    location = next(
        (
            str(descriptor.get(key) or "").strip()
            for key in ("url", "local_path", "api")
            if str(descriptor.get(key) or "").strip()
        ),
        "",
    )
    notes = candidate.get("notes") or metadata.get("notes") or ""
    return (
        rank,
        candidate.get("trait") or "",
        candidate.get("study_id") or "",
        SOURCE_LABELS.get(str(candidate.get("source") or ""), candidate.get("source") or ""),
        candidate.get("ancestry") or candidate.get("ancestry_raw") or metadata.get("ancestry") or "",
        candidate.get("sample_size") or metadata.get("sample_size") or "",
        candidate.get("n_cases") or metadata.get("n_cases") or "",
        candidate.get("n_controls") or metadata.get("n_controls") or "",
        "Unknown" if candidate.get("downloadable") is None else ("Yes" if candidate["downloadable"] else "No"),
        "Yes" if candidate.get("auth_required") or metadata.get("auth_required") else "No",
        descriptor.get("status") or "",
        descriptor.get("method") or "",
        candidate.get("publication_year") or metadata.get("publication_year") or metadata.get("year") or "",
        candidate.get("consortium") or metadata.get("consortium") or "",
        location,
        candidate.get("reason") or candidate.get("selection_reason") or candidate.get("downloadability_reason") or "",
        notes,
    )


def _format_shortlist_sheet(sheet: Any) -> None:
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.row_dimensions[1].height = 24
    for column_cells in sheet.columns:
        width = min(
            max(len(str(cell.value or "")) for cell in column_cells) + 2,
            48,
        )
        sheet.column_dimensions[column_cells[0].column_letter].width = max(width, 10)
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        location_cell = row[14]
        location = str(location_cell.value or "")
        if location.startswith(("http://", "https://")):
            location_cell.hyperlink = location
            location_cell.style = "Hyperlink"


def build_summary(
    payload: Dict[str, Any],
    *,
    exposure_results: List[Dict[str, Any]] | None = None,
) -> str:
    target = (
        dict(payload.get("target") or {})
        if isinstance(payload.get("target"), dict)
        else {}
    )
    sources = _format_sources(payload.get("sources_searched"))
    diagnostics = (
        payload.get("search_diagnostics")
        if isinstance(payload.get("search_diagnostics"), dict)
        else {}
    )
    candidate_count = int(diagnostics.get("candidate_count") or 0)
    target_value = compact_text(
        target.get("value") or target.get("resolved_query")
    ) or "unspecified"
    if candidate_count == 0:
        return (
            "GWAS search completed: "
            f"searched {sources} for {target.get('kind') or 'target'}="
            f"\"{target_value}\"; no downloadable candidate was found."
        )
    return (
        "GWAS search completed: "
        f"searched {sources} for {target.get('kind') or 'target'}="
        f"\"{target_value}\"; found {candidate_count} downloadable "
        f"candidate(s) ({_format_trait_list(exposure_results)})."
    )


def has_opengwas_auth_error(source_reports: List[Dict[str, Any]]) -> bool:
    for report in source_reports:
        source = str(report.get("source") or "").strip().lower()
        if source != "opengwas":
            continue
        status = str(report.get("status") or "").strip().lower()
        message = str(report.get("message") or "").strip().lower()
        if status == "auth_required":
            return True
        if "401" in message or "unauthorized" in message or "invalid token" in message:
            return True
    return False


def _source_label(value: Any) -> str:
    source = str(value or "").strip()
    return SOURCE_LABELS.get(source, source or "unknown")


def _format_sources(values: Any) -> str:
    sources = [
        _source_label(item)
        for item in list(values or [])
        if str(item or "").strip()
    ]
    return ", ".join(sources) if sources else "none"


def _format_trait_list(candidates: Any) -> str:
    traits = unique_strings(
        [
            compact_text(item.get("trait"))
            for item in list(candidates or [])
            if isinstance(item, dict)
        ]
    )
    if not traits:
        return "no trait names recorded"
    display = " | ".join(traits[:3])
    if len(traits) > 3:
        display += f" | {len(traits) - 3} more"
    return display
