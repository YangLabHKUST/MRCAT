"""Report policies and rendering ported from MRCAT; no legacy runtime dependency."""
from mrcat.runtime.diagnostics import redact
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any
from .metadata import build_reporting_metadata, reporting_declaration_text
from .review import validate_report_judgement
from .scientific import (collect_report_figures, render_scientific_report_html,
                         render_scientific_report_markdown, validate_report_spec)


_CITABLE_SUPPORT_GRADES = {
    "strong_support",
    "partial_support",
    "background_support",
    "contradictory_or_limiting",
}


_JUDGE_SCIENTIFIC_SKILLS = {
    "gwas-qc",
    "gwas-pair-prepare",
}


_JUDGE_DROPPED_KEYS = {
    "artifact",
    "artifacts",
    "download_url",
    "explanation_path",
    "path",
    "plot_manifest",
    "raw_path",
    "reports",
    "shortlists_path",
    "shortlists_xlsx_path",
    "url",
}


_MAX_REPORT_REVISIONS = 3


class ReportNotApplicable(ValueError):
    """Raised when a session has no MR evidence to report."""


@dataclass(frozen=True, slots=True)
class ReportAgentResult:
    final_summary: str
    artifacts: list[Any]
    report_spec: dict[str, Any]
    review: dict[str, Any]
    literature_evidence: dict[str, Any]


def validate_session_report_selection(
    payload: dict[str, Any],
    *,
    available_step_refs: list[str],
    mr_step_refs: set[str],
) -> dict[str, Any]:
    """Validate only provenance membership; scientific scope remains LLM-owned."""

    if not isinstance(payload, dict) or set(payload) != {
        "selected_step_refs",
        "selection_reason",
    }:
        raise ValueError(
            "report selection must contain exactly selected_step_refs and "
            "selection_reason"
        )
    raw_refs = payload.get("selected_step_refs")
    if not isinstance(raw_refs, list) or not raw_refs:
        raise ValueError("selected_step_refs must be a non-empty list")
    available = set(available_step_refs)
    selected: list[str] = []
    for index, raw_ref in enumerate(raw_refs):
        step_ref = str(raw_ref or "").strip()
        if not step_ref:
            raise ValueError(f"selected_step_refs[{index}] is required")
        if step_ref not in available:
            raise ValueError(f"unknown selected step reference: {step_ref}")
        if step_ref in selected:
            raise ValueError(f"duplicate selected step reference: {step_ref}")
        selected.append(step_ref)
    if not set(selected).intersection(mr_step_refs):
        raise ValueError(
            "report selection must include direct MR or pair-preparation evidence"
        )
    reason = str(payload.get("selection_reason") or "").strip()
    if not reason:
        raise ValueError("selection_reason is required")
    if len(reason) > 4000:
        raise ValueError("selection_reason exceeds 4000 characters")
    return {
        "selected_step_refs": selected,
        "selection_reason": reason,
    }


def add_required_report_evidence(
    *,
    catalog: dict[str, Any],
    selection: dict[str, Any],
) -> dict[str, Any]:
    """Add successful QC evidence belonging to each selected analysis task."""

    selected = list(selection.get("selected_step_refs") or [])
    selected_set = set(selected)
    selected_task_ids = {
        step_ref.split("/", 1)[0]
        for step_ref in selected
        if "/" in step_ref
    }
    added: list[str] = []
    for task in list(catalog.get("tasks") or []):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id") or "").strip()
        if task_id not in selected_task_ids:
            continue
        for step in list(task.get("steps") or []):
            if not isinstance(step, dict):
                continue
            if str(step.get("skill_id") or "").strip() != "gwas-qc":
                continue
            status = str(step.get("status") or "").strip().lower()
            if status in {"failed", "blocked", "skipped"}:
                continue
            step_ref = str(step.get("step_ref") or "").strip()
            if step_ref and step_ref not in selected_set:
                selected.append(step_ref)
                selected_set.add(step_ref)
                added.append(step_ref)

    reason = str(selection.get("selection_reason") or "").strip()
    if added:
        reason = (
            reason.rstrip(". ")
            + ". Required GWAS QC evidence was added for the selected analysis "
            "branches: "
            + ", ".join(added)
            + "."
        )
    return {
        "selected_step_refs": selected,
        "selection_reason": reason,
        "required_step_refs_added": added,
    }


def _catalog_step_refs(catalog: dict[str, Any]) -> list[str]:
    return [
        step_ref
        for task in list(catalog.get("tasks") or [])
        if isinstance(task, dict)
        for step in list(task.get("steps") or [])
        if isinstance(step, dict)
        and (step_ref := str(step.get("step_ref") or "").strip())
    ]


def _catalog_plot_metadata(outputs: dict[str, Any]) -> list[dict[str, str]]:
    figures: list[dict[str, str]] = []
    for result_name, payload in outputs.items():
        if not isinstance(payload, dict):
            continue
        manifest = (
            payload.get("plot_manifest")
            if isinstance(payload.get("plot_manifest"), dict)
            else {}
        )
        for raw_plot in list(manifest.get("plots") or []):
            if not isinstance(raw_plot, dict):
                continue
            plot_id = str(raw_plot.get("plot_id") or "").strip()
            title = str(raw_plot.get("title") or "").strip()
            if plot_id or title:
                figures.append(
                    {
                        "result_name": str(result_name),
                        "plot_id": plot_id,
                        "title": title,
                    }
                )
    return figures


def _collect_session_report_figures(
    selected_tasks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Path]]:
    catalog: list[dict[str, Any]] = []
    assets: dict[str, Path] = {}
    seen_paths: set[str] = set()
    for task in selected_tasks:
        task_id = str(task.get("task_id") or "task").strip() or "task"
        task_catalog, task_assets = collect_report_figures(task)
        for raw in task_catalog:
            old_id = str(raw.get("figure_id") or "figure").strip() or "figure"
            path = task_assets.get(old_id)
            if path is None:
                continue
            resolved = str(path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            base_id = re.sub(r"[^A-Za-z0-9_]+", "_", f"{task_id}_{old_id}")
            figure_id = base_id.strip("_") or "figure"
            suffix = 2
            while figure_id in assets:
                figure_id = f"{base_id}_{suffix}"
                suffix += 1
            catalog.append(
                {
                    **raw,
                    "figure_id": figure_id,
                    "source_task_id": task_id,
                }
            )
            assets[figure_id] = path
    return catalog, assets


def export_report(*, data, artifact_store, state, execution):
    final_spec = data["draft"]
    initial_judgement = data.get("initial_judgement")
    final_judgement = data.get("final_judgement")
    revision_rejected = data.get("revision_rejected")
    judge_failure = data.get("judge_failure")
    revision_attempts = data.get("revision_attempts", 0)
    revision_history = data.get("revision_history", [])
    literature_evidence = data["report_context"]["literature_evidence"]
    figure_catalog = data["figure_catalog"]
    figure_assets = {k: Path(v) for k, v in data["figure_assets"].items()}
    report_selection = data.get("report_selection")
    revision_attempted = revision_attempts > 0
    max_revisions_reached = bool(
        final_judgement is not None
        and final_judgement["decision"] == "revise"
        and revision_attempts >= _MAX_REPORT_REVISIONS
        and revision_rejected is None
        and judge_failure is None
    )

    review_status = _review_status(
        initial_judgement=initial_judgement,
        final_judgement=final_judgement,
        revision_rejected=revision_rejected,
        judge_failure=judge_failure,
    )
    review = {
        "status": review_status,
        "policy": {
            "evidence_priority": [
                "original_analysis_evidence",
                "verified_literature_evidence",
                "last_validated_draft",
                "judge_findings",
            ],
            "judge_may_supply_replacement_numbers": False,
            "judge_feedback_is_evidence": False,
            "max_judge_passes": 1 + _MAX_REPORT_REVISIONS,
            "max_revisions": _MAX_REPORT_REVISIONS,
            "stop_on_no_progress": True,
        },
        "initial_judgement": initial_judgement,
        "revision_attempted": revision_attempted,
        "revision_attempts": revision_attempts,
        "revision_history": revision_history,
        "max_revisions_reached": max_revisions_reached,
        "revision_rejected": revision_rejected,
        "final_judgement": final_judgement,
        "judge_failure": judge_failure,
        "literature_status": literature_evidence.get("status"),
    }
    publish_final = review_status in {"accepted", "accepted_after_revision"}

    execution.progress["status"] = review_status
    final_spec = _attach_verified_references(final_spec, literature_evidence)
    markdown = render_scientific_report_markdown(final_spec)
    source_refs = execution.call(
        "save_report", _render_report_artifacts,
        artifact_store=artifact_store,
        state=state,
        spec=final_spec,
        literature_evidence=literature_evidence,
        figure_catalog=figure_catalog,
        figure_assets=figure_assets,
        publish_final=publish_final,
    )
    review["rendering"] = {
        "html_generated": True,
        "published_as_final": publish_final,
        "standalone": True,
        "embedded_figure_count": sum(
            len(block.get("figure_ids", []))
            for section in final_spec["sections"] for block in section["blocks"]
            if block.get("type") == "figure"
        ),
    }
    review_ref = artifact_store.write_json(
        run_id=state["run_id"],
        session_id=state["session_id"],
        namespace="reporter",
        name="report_review",
        payload=review,
    )
    selection_ref = (
        artifact_store.write_json(
            run_id=state["run_id"],
            session_id=state["session_id"],
            namespace="reporter",
            name="report_selection",
            payload=report_selection,
        )
        if report_selection is not None
        else None
    )
    artifacts = [
        source_refs["summary"],
        source_refs["spec"],
        source_refs["literature_evidence"],
        *([selection_ref] if selection_ref is not None else []),
        review_ref,
        source_refs["html"],
        execution.progress_ref,
    ]
    return ReportAgentResult(
        final_summary=markdown,
        artifacts=artifacts,
        report_spec=final_spec,
        review=review,
        literature_evidence=literature_evidence,
    )


def _draft_report(
    *,
    reporter: Any,
    finalization_context: dict[str, Any],
    figure_catalog: list[dict[str, Any]],
    current_draft: dict[str, Any] | None = None,
    review_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    draft = getattr(reporter, "draft_scientific_report", None)
    if not callable(draft):
        raise AttributeError("reporter.draft_scientific_report is required")
    return draft(
        finalization_context=finalization_context,
        figure_catalog=figure_catalog,
        current_draft=current_draft,
        review_feedback=review_feedback,
    )


def _judge_report(
    *,
    reporter: Any,
    finalization_context: dict[str, Any],
    figure_catalog: list[dict[str, Any]],
    report_spec: dict[str, Any],
) -> dict[str, Any]:
    judge = getattr(reporter, "judge_scientific_report", None)
    if not callable(judge):
        raise AttributeError("reporter.judge_scientific_report is required")
    return validate_report_judgement(
        judge(
            finalization_context=finalization_context,
            figure_catalog=figure_catalog,
            report_spec=report_spec,
        )
    )


def _report_judge_evidence(
    finalization_context: dict[str, Any],
) -> dict[str, Any]:
    """Keep the scientific evidence needed for review without search/download noise."""

    evidence = {
        key: finalization_context.get(key)
        for key in (
            "task_contract",
            "workflow_completion",
            "selected_studies",
            "mr_evidence",
            "evidence_conflicts",
            "reporting_metadata",
        )
        if key in finalization_context
    }
    scientific_steps: list[dict[str, Any]] = []
    for raw in list(finalization_context.get("step_evidence") or []):
        if not isinstance(raw, dict):
            continue
        skill_id = str(raw.get("skill_id") or "").strip()
        if not (
            skill_id == "custom"
            or skill_id in _JUDGE_SCIENTIFIC_SKILLS
            or skill_id.startswith("mr-")
            or skill_id.startswith("analysis-")
        ):
            continue
        scientific_steps.append(
            {
                "step_id": str(raw.get("step_id") or "").strip(),
                "task_id": str(raw.get("task_id") or "").strip(),
                "task_status": str(raw.get("task_status") or "").strip(),
                "skill_id": skill_id,
                "status": str(raw.get("status") or "").strip(),
                "runtime_summary": str(raw.get("runtime_summary") or "").strip(),
                "sources": _drop_judge_runtime_refs(raw.get("sources", [])),
                "structured_outputs": _drop_judge_runtime_refs(
                    raw.get("structured_outputs")
                ),
            }
        )
    evidence["scientific_step_evidence"] = scientific_steps
    literature_evidence = finalization_context.get("literature_evidence")
    if isinstance(literature_evidence, dict):
        evidence["literature_evidence"] = literature_evidence
    return evidence


def _collect_literature_evidence(
    *,
    reporter: Any,
    finalization_context: dict[str, Any],
) -> dict[str, Any]:
    collect = getattr(reporter, "collect_literature_evidence", None)
    if not callable(collect):
        return _empty_literature_evidence(
            status="not_configured",
            searched_at=datetime.now(UTC).isoformat(),
            claims=[],
        )
    try:
        result = collect(finalization_context=finalization_context)
    except Exception as exc:
        return {
            **_empty_literature_evidence(
                status="failed",
                searched_at=datetime.now(UTC).isoformat(),
                claims=[],
            ),
            "failures": [
                {
                    "phase": "literature_evidence_collection",
                    "error": _error_summary(exc),
                }
            ],
        }
    if not isinstance(result, dict):
        return {
            **_empty_literature_evidence(
                status="failed",
                searched_at=datetime.now(UTC).isoformat(),
                claims=[],
            ),
            "failures": [
                {
                    "phase": "literature_evidence_collection",
                    "error": "Reporter literature evidence was not an object.",
                }
            ],
        }
    return result


def _empty_literature_evidence(
    *,
    status: str,
    searched_at: str,
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": status,
        "source": "PubMed ESearch and EFetch",
        "searched_at": searched_at,
        "policy": _literature_policy(),
        "claims": claims,
        "search_runs": [],
        "studies": [],
        "screened_candidates": [],
        "failures": [],
    }


def _literature_policy() -> dict[str, Any]:
    return {
        "max_claims": 3,
        "max_verified_studies": 9,
        "metadata_is_not_support": True,
        "abstract_verification_required": True,
        "analysis_and_literature_authority_are_separate": True,
        "support_grades": sorted(_CITABLE_SUPPORT_GRADES),
    }


def _literature_evidence(finalization_context: dict[str, Any]) -> dict[str, Any]:
    value = finalization_context.get("literature_evidence")
    return value if isinstance(value, dict) else {}


def _verified_reference_ids(literature_evidence: dict[str, Any]) -> list[str]:
    return [
        str(item.get("reference_id") or "").strip()
        for item in list(literature_evidence.get("studies") or [])
        if isinstance(item, dict)
        and str(item.get("reference_id") or "").strip()
        and str(item.get("abstract") or "").strip()
        and not bool(item.get("retracted"))
        and str(item.get("support_grade") or "") in _CITABLE_SUPPORT_GRADES
    ]


def _ensure_reporting_declarations(
    spec: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Append stable reporting declarations without asking the Writer to invent them."""

    declarations = reporting_declaration_text(metadata)
    sections = [
        dict(section)
        for section in list(spec.get("sections") or [])
        if str(section.get("heading") or "").strip().lower()
        != "reporting information"
    ]
    sections.append(
        {
            "heading": "Reporting information",
            "page_break_before": False,
            "blocks": [
                {
                    "type": "callout",
                    "title": "Software and preregistration",
                    "text": declarations["software_and_preregistration"],
                },
                {
                    "type": "callout",
                    "title": "Funding",
                    "text": declarations["funding"],
                },
                {
                    "type": "callout",
                    "title": "Data and code availability",
                    "text": declarations["data_and_code"],
                },
                {
                    "type": "callout",
                    "title": "Conflicts of interest",
                    "text": declarations["conflicts"],
                },
            ],
        }
    )
    return {**spec, "sections": sections}


def _attach_verified_references(
    spec: dict[str, Any],
    literature_evidence: dict[str, Any],
) -> dict[str, Any]:
    verified_ids = set(_verified_reference_ids(literature_evidence))
    study_by_id = {
        str(item.get("reference_id") or "").strip(): item
        for item in list(literature_evidence.get("studies") or [])
        if isinstance(item, dict)
        and str(item.get("reference_id") or "").strip() in verified_ids
    }
    cited_ids: list[str] = []
    for section in list(spec.get("sections") or []):
        for block in _iter_report_blocks(list(section.get("blocks") or [])):
            for reference_id in list(block.get("citation_ids") or []):
                clean = str(reference_id or "").strip()
                if clean and clean in study_by_id and clean not in cited_ids:
                    cited_ids.append(clean)
    attached = dict(spec)
    attached["references"] = [
        {
            key: study_by_id[reference_id].get(key)
            for key in (
                "reference_id",
                "title",
                "authors",
                "journal",
                "year",
                "doi",
                "pmid",
                "url",
                "support_grade",
                "claim_ids",
                "reasoning",
            )
        }
        for reference_id in cited_ids
    ]
    return attached


def _iter_report_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for block in blocks:
        flattened.append(block)
        if block.get("type") == "subsection":
            flattened.extend(_iter_report_blocks(list(block.get("blocks") or [])))
    return flattened


def _drop_judge_runtime_refs(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _drop_judge_runtime_refs(nested)
            for key, nested in value.items()
            if str(key) not in _JUDGE_DROPPED_KEYS
        }
    if isinstance(value, list):
        return [_drop_judge_runtime_refs(item) for item in value]
    return value


def _judge_failure(phase: str, exc: Exception) -> dict[str, str]:
    return {
        "phase": phase,
        "error_type": type(exc).__name__,
        "message": _error_summary(exc),
    }


def _error_summary(exc: Exception, *, limit: int = 2000) -> str:
    message = redact(str(exc)).strip() or type(exc).__name__
    return message if len(message) <= limit else message[:limit].rstrip() + "..."


def _render_report_artifacts(
    *, artifact_store: Any, state: dict[str, Any], spec: dict[str, Any],
    literature_evidence: dict[str, Any],
    figure_catalog: list[dict[str, Any]], figure_assets: dict[str, Path],
    publish_final: bool,
) -> dict[str, Any]:
    html = render_scientific_report_html(
        spec, figure_assets=figure_assets,
        figure_titles={item["figure_id"]: str(item.get("title") or item["figure_id"]) for item in figure_catalog},
    )
    if not publish_final:
        html = html.replace('<body>', '<body><aside role="status" style="padding:12px;text-align:center;background:#fff3cd">Draft — automated review has not passed.</aside>', 1)
    return _write_report_source_artifacts(
        artifact_store=artifact_store, state=state,
        markdown=render_scientific_report_markdown(spec), spec=spec,
        literature_evidence=literature_evidence,
        html=html, publish_final=publish_final,
    )


def _write_report_source_artifacts(
    *,
    artifact_store: Any,
    state: dict[str, Any],
    markdown: str,
    spec: dict[str, Any],
    literature_evidence: dict[str, Any],
    html: str,
    publish_final: bool,
) -> dict[str, Any]:
    common = {
        "run_id": state["run_id"],
        "session_id": state["session_id"],
        "namespace": "reporter",
    }
    return {
        "summary": artifact_store.write_text(
            **common,
            name="final_summary" if publish_final else "report_draft",
            content=markdown,
            suffix=".md",
        ),
        "spec": artifact_store.write_json(
            **common,
            name=(
                "scientific_report_spec"
                if publish_final
                else "scientific_report_draft_spec"
            ),
            payload=spec,
        ),
        "literature_evidence": artifact_store.write_json(
            **common,
            name="report_literature_evidence",
            payload=literature_evidence,
        ),
        "html": artifact_store.write_text(
            **common,
            name="scientific_report" if publish_final else "scientific_report_draft",
            content=html,
            suffix=".html",
        ),
    }


def _judge_finding_count(judgement: dict[str, Any]) -> int:
    return len(judgement["issues"])


def _review_status(
    *,
    initial_judgement: dict[str, Any] | None,
    final_judgement: dict[str, Any] | None,
    revision_rejected: dict[str, Any] | None,
    judge_failure: dict[str, str] | None,
) -> str:
    if judge_failure:
        return (
            "judge_failed_after_revision"
            if judge_failure["phase"] in {"final_review", "revision_review"}
            else "judge_failed"
        )
    if revision_rejected:
        return "last_valid_draft_retained"
    if initial_judgement is not None and initial_judgement["decision"] == "accept":
        return "accepted"
    if final_judgement is not None and final_judgement["decision"] == "accept":
        return "accepted_after_revision"
    return "needs_review"
