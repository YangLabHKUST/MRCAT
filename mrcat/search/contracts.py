"""Legacy brief and scan-design output contracts."""

from typing import Any

from mrcat.model.json_contract import clean_text, object_list, strict_object, text_list

BRIEF_REQUIRED_HEADINGS = (
    "Research Goal",
    "Trait Vocabulary",
    "Direct MR Evidence",
    "GWAS Search Handoff",
    "Candidate Analysis Designs",
    "Evidence Synthesis",
)

def validate_brief_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload = strict_object(
        payload,
        allowed_fields={"markdown", "pipeline_queries"},
        label="Search brief response",
    )
    markdown = clean_text(payload.get("markdown"))
    if not markdown:
        raise ValueError("Search brief requires markdown")
    if "pipeline_queries" not in payload:
        raise ValueError("Search brief requires pipeline_queries")
    pipeline_queries = text_list(
        payload.get("pipeline_queries"),
        field="pipeline_queries",
    )
    missing = [
        heading
        for heading in BRIEF_REQUIRED_HEADINGS
        if not _has_markdown_heading(markdown, heading)
    ]
    if missing:
        raise ValueError(
            "Search brief markdown missing required heading(s): "
            + ", ".join(missing)
        )
    if _has_markdown_heading(markdown, "Pipeline Queries"):
        raise ValueError("Search brief markdown must not include Pipeline Queries")
    return {"markdown": markdown, "pipeline_queries": pipeline_queries}

def validate_scan_design_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload = strict_object(
        payload,
        allowed_fields={"markdown", "scan_design"},
        label="Scan design response",
    )
    markdown = clean_text(payload.get("markdown"))
    if not markdown:
        raise ValueError("Scan design requires markdown")
    scan_design = payload.get("scan_design")
    if not isinstance(scan_design, dict):
        raise ValueError("Scan design requires scan_design object")
    scan_design = strict_object(
        scan_design,
        allowed_fields={"exposure_list", "outcome_list", "rationale", "citations"},
        label="scan_design",
    )
    exposure_list = object_list(scan_design.get("exposure_list"), field="exposure_list")
    outcome_list = object_list(scan_design.get("outcome_list"), field="outcome_list")
    if not exposure_list:
        raise ValueError("Scan design requires at least one exposure trait")
    if not outcome_list:
        raise ValueError("Scan design requires at least one outcome trait")
    normalized_exposure: list[dict[str, Any]] = []
    for item in exposure_list:
        item = strict_object(item, allowed_fields={"trait", "aliases"}, label="exposure_list[]")
        trait = clean_text(item.get("trait"))
        if not trait:
            raise ValueError("Each exposure entry requires a trait name")
        aliases = text_list(item.get("aliases"), field="exposure_list[].aliases")
        normalized_exposure.append({"trait": trait, "aliases": aliases})
    normalized_outcome: list[dict[str, Any]] = []
    for item in outcome_list:
        item = strict_object(item, allowed_fields={"trait", "aliases"}, label="outcome_list[]")
        trait = clean_text(item.get("trait"))
        if not trait:
            raise ValueError("Each outcome entry requires a trait name")
        aliases = text_list(item.get("aliases"), field="outcome_list[].aliases")
        normalized_outcome.append({"trait": trait, "aliases": aliases})
    rationale = clean_text(scan_design.get("rationale"))
    citations = text_list(scan_design.get("citations"), field="citations")
    return {
        "markdown": markdown,
        "scan_design": {
            "exposure_list": normalized_exposure,
            "outcome_list": normalized_outcome,
            "rationale": rationale or "",
            "citations": citations,
        },
    }

def _has_markdown_heading(markdown: str, heading: str) -> bool:
    expected = str(heading or "").strip().lower()
    for line in str(markdown or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        title = stripped.lstrip("#").strip().lower()
        if title == expected:
            return True
    return False
