from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    __package__ = "skills.gwas-select.scripts"

from .llm_selector import LLMSelectionError, select_shortlists


def log_step(message: str) -> None:
    print(f"[gwas-select] {message}", file=sys.stderr, flush=True)


def _load_input(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    candidate = Path(path)
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(path)


def _unwrap_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(input_data, dict):
        return {}
    payload = input_data.get("payload")
    if isinstance(payload, dict):
        merged = dict(payload)
        for key, value in input_data.items():
            if key == "payload" or key in merged:
                continue
            merged[key] = value
        return merged
    return dict(input_data)


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_source(value: Any) -> str:
    text = _compact_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "open_gwas": "opengwas",
        "gwascatalog": "gwas_catalog",
        "gwas_catalog": "gwas_catalog",
        "panukb": "pan_ukb",
        "pan_ukb": "pan_ukb",
        "pan_uk_biobank": "pan_ukb",
        "finngen": "finngen",
        "opengwas": "opengwas",
    }
    return aliases.get(text, text)


def _source_label(value: Any) -> str:
    source = _normalize_source(value)
    return {
        "opengwas": "OpenGWAS",
        "gwas_catalog": "GWAS Catalog",
        "finngen": "FinnGen",
        "local": "Local",
        "pan_ukb": "Pan-UKB",
    }.get(source, source or "unknown")


def _load_shortlist(
    path_value: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    path_text = _compact_text(path_value)
    if not path_text:
        return None, "shortlist path is required."
    path = Path(path_text).expanduser()
    if not path.exists() or not path.is_file():
        return None, f"shortlist path is not a readable file: {path_text}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"shortlist path must point to valid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "shortlist path JSON must be an object."
    if not isinstance(payload.get("target"), dict):
        return None, "shortlist path JSON target must be an object."
    if not isinstance(payload.get("candidates"), list):
        return None, "shortlist path JSON candidates must be a list."
    if not isinstance(payload.get("diagnostics"), dict):
        return None, "shortlist path JSON diagnostics must be an object."
    return {
        "target": dict(payload["target"]),
        "candidates": [
            dict(item)
            for item in payload["candidates"]
            if isinstance(item, dict)
        ],
        "diagnostics": dict(payload["diagnostics"]),
        "path": path_text,
    }, None


def _selection_context(raw):
    """Use the active task, not legacy directory-name or memory-file discovery."""
    context = {key: str(raw.get(key) or "") for key in ("request", "current_plan_item", "memory_md")}
    directory = os.environ.get("MRCAT_SESSION_DIR")
    if directory:
        from mrcat.store import Store
        session = Path(directory).resolve()
        state = Store(session.parent).load(session.name)
        task = state.get("active_task") or {}
        if task.get("task_id") == os.environ.get("MRCAT_RESULT_SCOPE"):
            from mrcat.plan_items import current_item
            context.update(request=task["request"], current_plan_item=json.dumps(current_item(task), ensure_ascii=False),
                           memory_md=task.get("memory", ""))
    if raw.get("ancestry"):
        context["request"] += "\nExplicit ancestry constraint: " + str(raw["ancestry"])
    return context


def _filter_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in candidates:
        source = _normalize_source(item.get("source"))
        study_id = _compact_text(item.get("study_id") or item.get("id"))
        if not source or not study_id:
            continue
        normalized = dict(item)
        normalized["source"] = source
        normalized["study_id"] = study_id
        normalized = _repair_candidate_ancestry(normalized)
        filtered.append(normalized)
    return filtered


def _download_descriptor_ready(item: dict[str, Any]) -> bool:
    if not bool(item.get("downloadable")):
        return False
    descriptor = item.get("download_descriptor")
    if isinstance(descriptor, dict):
        status = _compact_text(descriptor.get("status")).lower()
        method = _compact_text(descriptor.get("method")).lower()
        if status == "ready" and method in {"url", "api", "local_path"}:
            return bool(
                _compact_text(descriptor.get("url"))
                or _compact_text(descriptor.get("api"))
                or _compact_text(descriptor.get("local_path"))
            )
    return bool(_compact_text(item.get("download_url")))


def _download_descriptor_from_candidate(item: dict[str, Any]) -> dict[str, Any]:
    descriptor = item.get("download_descriptor")
    if isinstance(descriptor, dict) and descriptor:
        return dict(descriptor)
    url = _compact_text(item.get("download_url"))
    if not url:
        return {}
    return {
        "source": _normalize_source(item.get("source")),
        "study_id": _compact_text(item.get("study_id") or item.get("id")),
        "status": "ready",
        "method": "url",
        "requires_auth": bool(item.get("auth_required")),
        "url": url,
    }


def _filter_downloadable_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in candidates if _download_descriptor_ready(item)]


def _canonical_ancestry(value: Any) -> str:
    text = _compact_text(value).lower()
    if not text or text in {"unspecified", "unknown", "na", "n/a", "none", "null"}:
        return ""
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
    if text in canonical_labels:
        return text
    tokens = set(re.findall(r"[a-z0-9]+", text))
    matched: list[str] = []

    def add(label: str) -> None:
        if label not in matched:
            matched.append(label)

    def has_code(*values: str) -> bool:
        return any(value.lower() in tokens for value in values)

    def has_text(*values: str) -> bool:
        return any(value in text for value in values)

    if has_code("fin") or has_text("finnish"):
        add("finnish")
    if has_code("eur") or has_text(
        "european",
        "british",
        "british ancestry",
        "white british",
        "non-hispanic white",
    ):
        add("european")
    if has_code("afr", "african") or has_text(
        "african ancestry",
        "african american",
        "afro-caribbean",
        "non-hispanic black",
    ):
        add("african")
    if has_code("eas") or has_text("east asian", "japanese", "korean", "chinese", "taiwanese"):
        add("east_asian")
    if has_code("amr") or has_text("admixed american", "latin american", "latino", "hispanic", "native american"):
        add("admixed_american")
    if has_code("sas", "csa") or has_text(
        "south asian",
        "central south asian",
        "central/south asian",
        "indian",
        "pakistani",
        "bangladeshi",
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
        return "multi_ancestry"
    return matched[0] if matched else ""


def _candidate_ancestry(item: dict[str, Any]) -> str:
    return _canonical_ancestry(item.get("ancestry"))


def _repair_candidate_ancestry(item: dict[str, Any]) -> dict[str, Any]:
    if _candidate_ancestry(item):
        return item
    metadata = item.get("study_metadata") if isinstance(item.get("study_metadata"), dict) else {}
    for key in ("population", "initialSampleDescription", "initialSampleSize", "replicationSampleSize"):
        raw = metadata.get(key)
        label = _canonical_ancestry(raw)
        if not label:
            continue
        repaired = dict(item)
        repaired["ancestry"] = label
        if not _compact_text(repaired.get("ancestry_raw")):
            repaired["ancestry_raw"] = _compact_text(raw)
        return repaired
    return item


def _pan_ukb_requested_scope(item: dict[str, Any], requested_ancestry: str) -> str:
    code_by_ancestry = {
        "african": "AFR",
        "admixed_american": "AMR",
        "central_south_asian": "CSA",
        "east_asian": "EAS",
        "european": "EUR",
        "middle_eastern": "MID",
    }
    code = code_by_ancestry.get(requested_ancestry)
    if not code:
        return ""
    metadata = item.get("study_metadata") if isinstance(item.get("study_metadata"), dict) else {}
    raw_text = " ".join(
        _compact_text(value)
        for value in (
            item.get("ancestry_raw"),
            metadata.get("population"),
            metadata.get("initialSampleDescription"),
        )
        if _compact_text(value)
    )
    tokens = {token.upper() for token in re.findall(r"[A-Za-z]+", raw_text)}
    return code if code in tokens else ""


def _apply_requested_ancestry_scope(item: dict[str, Any], requested_ancestry: str) -> dict[str, Any]:
    if not requested_ancestry:
        return item
    if _normalize_source(item.get("source")) != "pan_ukb":
        return item
    if _candidate_ancestry(item) != "multi_ancestry":
        return item
    scope = _pan_ukb_requested_scope(item, requested_ancestry)
    if not scope:
        return item
    scoped = dict(item)
    scoped["ancestry"] = requested_ancestry
    metadata = (
        dict(scoped["study_metadata"])
        if isinstance(scoped.get("study_metadata"), dict)
        else {}
    )
    metadata["pan_ukb_scope"] = scope
    scoped["study_metadata"] = metadata
    return scoped


def _study_selector(study: dict[str, Any], *, status: str = "selected") -> dict[str, Any]:
    payload = dict(study)
    payload["source"] = _normalize_source(payload.get("source"))
    payload["study_id"] = _compact_text(payload.get("study_id") or payload.get("id"))
    payload["trait"] = payload.get("trait")
    descriptor = _download_descriptor_from_candidate(payload)
    if descriptor:
        payload["download_descriptor"] = descriptor
    payload["status"] = status
    return payload


def _format_int(value: Any) -> str | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return f"{number:,}"


def _study_phrase(study: dict[str, Any], *, side: str) -> str:
    trait = _compact_text(study.get("trait")) or side
    source = _source_label(study.get("source"))
    study_id = _compact_text(study.get("study_id")) or "unknown"
    details = [f"{source} study_id={study_id}"]
    ancestry = _compact_text(study.get("ancestry"))
    if ancestry:
        details.append(f"ancestry={ancestry}")
    sample_size = _format_int(study.get("sample_size"))
    if sample_size:
        details.append(f"n={sample_size}")
    return f"{side} {trait} ({', '.join(details)})"


def _select_success_summary(
    *,
    selected_studies: dict[str, dict[str, Any]],
    selection_reason: str,
) -> str:
    selected_text = "; ".join(
        _study_phrase(study, side=target_key)
        for target_key, study in selected_studies.items()
    )
    summary = (
        "GWAS select completed: selected "
        f"{len(selected_studies)} reusable study/studies: {selected_text}."
    )
    reason = _compact_text(selection_reason)
    if reason:
        return f"{summary} Selection reason: {reason}"
    return summary


def _blocked_summary(
    failure_class: str,
    message: str,
    diagnostics: dict[str, Any],
    *,
    selection_reason: str = "",
) -> str:
    reason = _compact_text(selection_reason)
    if failure_class == "invalid_shortlists_path":
        return "GWAS select blocked: could not read the gwas-search shortlist artifact; confirm that gwas-search produced shortlists."
    if failure_class == "llm_no_selection":
        suffix = f" Reason: {reason}" if reason else ""
        return (
            "GWAS select blocked: the LLM did not choose one acceptable study "
            f"for every target.{suffix}"
        )
    if failure_class == "no_selectable_set":
        missing_targets = list(diagnostics.get("missing_targets") or [])
        suffix = (
            f" Missing target(s): {', '.join(missing_targets)}."
            if missing_targets
            else ""
        )
        return (
            "GWAS select blocked: no selectable GWAS study is available for "
            f"every requested target.{suffix}"
        )
    summary = f"GWAS select blocked: {_compact_text(message) or 'selection failed'}"
    if reason:
        summary += f" Reason: {reason}"
    return summary


def _blocked(
    failure_class: str,
    message: str,
    diagnostics: dict[str, Any] | None = None,
    *,
    selection_reason: str = "",
) -> dict[str, Any]:
    log_step(f"Blocked: {message}")
    reason = _compact_text(selection_reason)
    if reason:
        log_step(f"Selection reason: {reason}")
    details = {
        "result_status": "blocked",
        "failure_class": failure_class,
        "message": message,
    }
    if reason:
        details["selection_reason"] = reason
    if diagnostics:
        details["diagnostics"] = diagnostics
    return {
        "summary": _blocked_summary(
            failure_class,
            message,
            diagnostics or {},
            selection_reason=reason,
        ),
        "outputs": {"status": "blocked"},
        "details": details,
    }


def run_select(input_data: dict[str, Any]) -> dict[str, Any]:
    log_step("Starting GWAS selection.")
    raw = _unwrap_payload(input_data)
    shortlists = raw.get("shortlists")
    if not isinstance(shortlists, dict):
        return _blocked(
            "invalid_shortlists_path",
            "shortlists must be an object keyed by GWAS search step ID.",
            {},
        )
    target_keys = [
        _compact_text(target_key)
        for target_key, path in shortlists.items()
        if _compact_text(target_key) and _compact_text(path)
    ]
    if not target_keys:
        return _blocked(
            "invalid_shortlists_path",
            "shortlists must contain at least one target-keyed path.",
            {},
        )
    invalid_keys = [
        target_key
        for target_key in target_keys
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", target_key)
    ]
    if invalid_keys:
        return _blocked(
            "invalid_shortlists_path",
            "shortlists contains invalid target key(s): "
            + ", ".join(sorted(invalid_keys)),
            {},
        )
    if len(target_keys) != len(set(target_keys)):
        return _blocked(
            "invalid_shortlists_path",
            "shortlists target keys must be unique.",
            {},
        )

    loaded_by_target: dict[str, dict[str, Any]] = {}
    for target_key in target_keys:
        path = _compact_text(shortlists.get(target_key))
        log_step(f"Loading {target_key} shortlist artifact: {path}.")
        loaded, error = _load_shortlist(path)
        if error:
            return _blocked(
                "invalid_shortlists_path",
                f"{target_key}: {error}",
                {
                    "target_key": target_key,
                    "shortlists": dict(shortlists),
                },
            )
        assert loaded is not None
        loaded_by_target[target_key] = loaded

    requested_ancestry = _canonical_ancestry(raw.get("ancestry"))
    context = _selection_context(raw)
    current_plan_item = context["request"] + "\nCurrent item: " + context["current_plan_item"]
    candidates_by_target: dict[str, list[dict[str, Any]]] = {}
    targets: dict[str, dict[str, Any]] = {}
    search_diagnostics: dict[str, dict[str, Any]] = {}
    for target_key in target_keys:
        loaded = loaded_by_target[target_key]
        targets[target_key] = dict(loaded["target"])
        if raw.get("ancestry"):
            targets[target_key]["ancestry"] = raw["ancestry"]
        search_diagnostics[target_key] = dict(loaded["diagnostics"])
        valid_candidates = [
            _apply_requested_ancestry_scope(item, requested_ancestry)
            for item in _filter_candidates(list(loaded["candidates"]))
        ]
        candidates_by_target[target_key] = _filter_downloadable_candidates(
            valid_candidates
        )
        log_step(
            f"Loaded {target_key} shortlist: "
            f"raw={len(loaded['candidates'])}; "
            f"downloadable={len(candidates_by_target[target_key])}."
        )

    missing_targets = [
        target_key
        for target_key in target_keys
        if not candidates_by_target[target_key]
    ]
    diagnostics = {
        "eligible_candidate_counts": {
            target_key: len(candidates_by_target[target_key])
            for target_key in target_keys
        },
        "missing_targets": missing_targets,
        "targets": targets,
        "search_diagnostics": search_diagnostics,
        "search_exhausted": bool(missing_targets)
        and all(
            bool(search_diagnostics[target_key].get("search_exhausted"))
            for target_key in missing_targets
        ),
    }
    if missing_targets:
        missing_description = ", ".join(
            f"{target_key}={targets[target_key].get('value') or 'unknown'}"
            for target_key in missing_targets
        )
        return _blocked(
            "no_selectable_set",
            "no downloadable candidate is available for "
            f"{missing_description}.",
            diagnostics,
        )

    try:
        log_step(
            "Selecting one reusable GWAS study per target with the LLM: "
            + ", ".join(target_keys)
            + "."
        )
        memory_md = context["memory_md"]
        selector_kwargs = {
            "candidates_by_target": candidates_by_target,
            "target_specs": targets,
        }
        if current_plan_item:
            selector_kwargs["current_plan_item"] = current_plan_item
        if memory_md:
            selector_kwargs["memory_md"] = memory_md
        selected_shortlists = select_shortlists(
            **selector_kwargs,
        )
    except LLMSelectionError as exc:
        return _blocked("llm_selection_failed", str(exc), diagnostics)

    selected_by_target = selected_shortlists.get("selected_studies")
    if not isinstance(selected_by_target, dict):
        return _blocked(
            "llm_selection_failed",
            "selector did not return selected_studies.",
            diagnostics,
        )
    selection_reason = _compact_text(selected_shortlists.get("selection_reason"))
    unselected_targets = [
        target_key
        for target_key in target_keys
        if not isinstance(selected_by_target.get(target_key), dict)
    ]
    if unselected_targets:
        return _blocked(
            "llm_no_selection",
            "LLM selection did not return a study for target(s): "
            + ", ".join(unselected_targets),
            {**diagnostics, "missing_targets": unselected_targets, "selected_studies": selected_by_target},
            selection_reason=selection_reason,
        )
    if not selection_reason:
        selection_reason = "selection_reason was not returned by selector."

    selected_studies = {
        target_key: _study_selector(
            dict(selected_by_target[target_key])
        )
        for target_key in target_keys
    }
    for target_key, study in selected_studies.items():
        log_step(
            f"Selected {target_key}: source={study.get('source')}; "
            f"study_id={study.get('study_id')}; trait={study.get('trait')}."
        )
    log_step(f"Selection reason: {selection_reason}")
    payload = {
        "selected_studies": selected_studies,
        "selection_reason": selection_reason,
    }
    return {
        "summary": _select_success_summary(
            selected_studies=selected_studies,
            selection_reason=selection_reason,
        ),
        "outputs": {"status": "ok", "gwas_selection_result": payload},
        "details": {
            "result_status": "ok",
            "failure_class": None,
            "selected_studies": selected_studies,
            "selection_reason": selection_reason,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Select one reusable GWAS study per target."
    )
    parser.add_argument("--input-json", help="Structured JSON input path")
    parser.add_argument("--out", help="Optional output JSON path")
    args = parser.parse_args()

    payload = run_select(_load_input(args.input_json))
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
