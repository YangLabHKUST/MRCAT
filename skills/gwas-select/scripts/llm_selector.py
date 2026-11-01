from __future__ import annotations

from typing import Any
from importlib import import_module

from mrcat.config.llm_limits import LLM_MAX_OUTPUT_TOKENS, LLM_TIMEOUT_SECONDS
from mrcat.model import llm_gateway
from mrcat.model.prompt_assembler import PromptAssembler, PromptPackage


Candidate = dict[str, Any]
CandidatePools = dict[str, list[Candidate]]
TargetSpecs = dict[str, dict[str, Any]]
CandidateKey = tuple[str, str]
candidate_matches_exact_id = import_module(
    "skills.gwas-search.scripts.search_exact_id"
).candidate_matches_exact_id


class LLMSelectionError(RuntimeError):
    pass


def _has_api_key() -> bool:
    return llm_gateway.has_api_key()


def _candidate_key(item: Candidate) -> CandidateKey:
    return (
        str(item.get("source") or "").strip().lower(),
        str(item.get("study_id") or "").strip(),
    )


def _is_downloadable(item: Candidate) -> bool:
    if not bool(item.get("downloadable")):
        return False
    descriptor = item.get("download_descriptor")
    if isinstance(descriptor, dict):
        status = str(descriptor.get("status") or "").strip().lower()
        method = str(descriptor.get("method") or "").strip().lower()
        if status == "ready" and method in {"url", "api", "local_path"}:
            return bool(
                str(descriptor.get("url") or "").strip()
                or str(descriptor.get("api") or "").strip()
                or str(descriptor.get("local_path") or "").strip()
            )
    return bool(str(item.get("download_url") or "").strip())


def _download_descriptor(item: Candidate) -> dict[str, Any]:
    descriptor = item.get("download_descriptor")
    if isinstance(descriptor, dict):
        allowed = {
            "source",
            "study_id",
            "status",
            "method",
            "requires_auth",
            "url",
            "api",
            "headers",
            "query",
            "local_path",
        }
        return {
            key: value
            for key, value in descriptor.items()
            if key in allowed
        }
    url = str(item.get("download_url") or "").strip()
    return {
        "source": str(item.get("source") or "").strip(),
        "study_id": str(item.get("study_id") or "").strip(),
        "status": (
            "ready"
            if bool(item.get("downloadable")) and url
            else "unavailable"
        ),
        "method": "url" if url else "none",
        "requires_auth": bool(item.get("auth_required")),
        **({"url": url} if url else {}),
    }


def _compact_candidate(item: Candidate) -> Candidate:
    metadata = (
        item.get("study_metadata")
        if isinstance(item.get("study_metadata"), dict)
        else {}
    )
    return {
        "study_id": item.get("study_id"),
        "source": item.get("source"),
        "trait": item.get("trait"),
        "ancestry": item.get("ancestry"),
        "ancestry_raw": item.get("ancestry_raw"),
        "downloadable": bool(item.get("downloadable")),
        "download_descriptor": _download_descriptor(item),
        "sample_size": item.get("sample_size") or metadata.get("sample_size"),
        "n_cases": (
            item.get("n_cases")
            or metadata.get("ncase")
            or metadata.get("n_cases")
        ),
        "n_controls": (
            item.get("n_controls")
            or metadata.get("ncontrol")
            or metadata.get("n_controls")
        ),
        "consortium": item.get("consortium") or metadata.get("consortium"),
        "study_metadata": metadata,
        "matched_query": (
            item.get("_matched_query")
            or item.get("matched_query")
        ),
    }


def _matches_target_id(candidate: Candidate, target: dict[str, Any]) -> bool:
    source = str(target.get("source") or "").strip().lower()
    return (not source or _candidate_key(candidate)[0] == source) and candidate_matches_exact_id(
        candidate, str(target.get("value") or "").strip().casefold(), source,
    )


def _target_spec_payload(target: dict[str, Any], candidates: list[Candidate]) -> dict[str, Any]:
    return {
        "kind": str(target.get("kind") or "").strip() or None,
        "value": str(target.get("value") or "").strip() or None,
        "resolved_query": (
            str(target.get("resolved_query") or "").strip() or None
        ),
        "aliases": list(target.get("aliases") or []),
        "source": str(target.get("source") or "").strip() or None,
        "ancestry": target.get("ancestry"),
        "requested_identifier": (
            str(target.get("value") or "").strip()
            if str(target.get("kind") or "").strip() == "study_id"
            else None
        ),
        "resolved_candidate_keys": [
            {"source": item.get("source"), "study_id": item.get("study_id")}
            for item in candidates
            if target.get("kind") == "study_id" and _matches_target_id(item, target)
        ],
    }


def build_prompt_package(
    *,
    candidates_by_target: CandidatePools,
    target_specs: TargetSpecs,
    current_plan_item: str = "",
    memory_md: str = "",
    prompt_assembler: PromptAssembler | None = None,
) -> PromptPackage:
    assembler = prompt_assembler or PromptAssembler()
    sections: dict[str, Any] = {}
    if current_plan_item:
        sections["Current Plan Item"] = current_plan_item
    sections["Target Specs"] = {
        target_key: _target_spec_payload(target_specs.get(target_key, {}), candidates)
        for target_key, candidates in candidates_by_target.items()
    }
    memory_text = str(memory_md or "").strip()
    if memory_text:
        sections["Memory"] = memory_text
    sections["Candidate Pool"] = {
        target_key: [
            _compact_candidate(item)
            for item in candidates
        ]
        for target_key, candidates in candidates_by_target.items()
    }
    return assembler.build_structured_prompt(
        role_name="gwas_select",
        stage="selector",
        sections=sections,
    )


def build_prompt(
    *,
    candidates_by_target: CandidatePools,
    target_specs: TargetSpecs,
    current_plan_item: str = "",
    memory_md: str = "",
) -> str:
    return build_prompt_package(
        candidates_by_target=candidates_by_target,
        target_specs=target_specs,
        current_plan_item=current_plan_item,
        memory_md=memory_md,
    ).user_prompt


def _materialize_target(
    selected: Any,
    *,
    target_key: str,
    candidate_index: dict[CandidateKey, Candidate],
) -> Candidate | None:
    if selected is None:
        return None
    if not isinstance(selected, dict):
        raise LLMSelectionError(
            "invalid_selection: "
            f"selected_studies.{target_key} must be an object or null"
        )
    extra_keys = set(selected) - {"source", "study_id"}
    if extra_keys:
        raise LLMSelectionError(
            "invalid_selection: "
            f"selected_studies.{target_key} may include only source/study_id"
        )
    source = str(selected.get("source") or "").strip().lower()
    study_id = str(selected.get("study_id") or "").strip()
    if not source or not study_id:
        raise LLMSelectionError(
            "invalid_selection: "
            f"selected_studies.{target_key} requires source/study_id"
        )
    matched = candidate_index.get((source, study_id))
    if matched is None:
        raise LLMSelectionError(
            "invalid_selection: "
            f"{target_key} selection {source}:{study_id} "
            "is not in its candidate pool"
        )
    if not _is_downloadable(matched):
        raise LLMSelectionError(
            "invalid_selection: "
            f"{target_key} selection {source}:{study_id} is not downloadable"
        )
    return dict(matched)


def validate_selection(
    selected_payload: dict[str, Any],
    *,
    candidates_by_target: CandidatePools,
    target_specs: TargetSpecs | None = None,
) -> dict[str, Any]:
    if not isinstance(selected_payload, dict):
        raise LLMSelectionError(
            "invalid_selection: selector output must be an object"
        )
    extra_keys = set(selected_payload) - {
        "selected_studies",
        "selection_reason",
    }
    if extra_keys:
        raise LLMSelectionError(
            "invalid_selection: selector output contains extra keys"
        )
    selection_reason = str(
        selected_payload.get("selection_reason") or ""
    ).strip()
    if not selection_reason:
        raise LLMSelectionError(
            "invalid_selection: selection_reason is required"
        )
    raw_selected = selected_payload.get("selected_studies")
    if not isinstance(raw_selected, dict):
        raise LLMSelectionError(
            "invalid_selection: selected_studies must be an object"
        )
    expected_keys = set(candidates_by_target)
    if set(raw_selected) != expected_keys:
        raise LLMSelectionError(
            "invalid_selection: selected_studies keys must exactly match "
            f"the target keys {sorted(expected_keys)}"
        )
    selected_studies: dict[str, Candidate | None] = {}
    for target_key, candidates in candidates_by_target.items():
        target = (target_specs or {}).get(target_key, {})
        selected = raw_selected.get(target_key)
        if target.get("kind") == "study_id":
            candidates = [item for item in candidates if _matches_target_id(item, target)]
            # Resolve a repeated source-native identifier only when unambiguous.
            # This changes representation, never which scientific study was chosen.
            if isinstance(selected, dict) and set(selected) == {"source", "study_id"}:
                source, identifier = _candidate_key(selected)
                matches = [item for item in candidates if _candidate_key(item)[0] == source]
                if identifier == str(target.get("value") or "").strip() and len(matches) == 1:
                    selected = dict(source=source, study_id=matches[0]["study_id"])
        candidate_index = {
            _candidate_key(item): item
            for item in candidates
        }
        selected_studies[target_key] = _materialize_target(
            selected,
            target_key=target_key,
            candidate_index=candidate_index,
        )
    return {
        "selected_studies": selected_studies,
        "selection_reason": selection_reason,
    }


def select_shortlists(
    *,
    candidates_by_target: CandidatePools,
    target_specs: TargetSpecs,
    current_plan_item: str = "",
    memory_md: str = "",
) -> dict[str, Any]:
    if not _has_api_key():
        raise LLMSelectionError(
            "llm_unavailable: configured LLM API key not set"
        )

    prompt_package = build_prompt_package(
        candidates_by_target=candidates_by_target,
        target_specs=target_specs,
        current_plan_item=current_plan_item,
        memory_md=memory_md,
    )
    example_selected = {
        target_key: {"source": "xxx", "study_id": "xxx"}
        for target_key in candidates_by_target
    }
    try:
        return llm_gateway.call_validated_json(
            system=prompt_package.system_prompt,
            user=prompt_package.user_prompt,
            example={
                "selected_studies": example_selected,
                "selection_reason": (
                    "Selected one semantically matched, executable study per "
                    "target; ancestry and source compatibility were preferred."
                ),
            },
            validator=lambda payload: validate_selection(
                payload,
                candidates_by_target=candidates_by_target,
                target_specs=target_specs,
            ),
            temperature=0.0,
            thinking=False,
            max_tokens=LLM_MAX_OUTPUT_TOKENS,
            timeout=LLM_TIMEOUT_SECONDS,
            compact=True,
        )
    except LLMSelectionError:
        raise
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if (
            "api request failed" in lowered
            or "urlopen" in lowered
            or "timed out" in lowered
        ):
            raise LLMSelectionError(
                f"llm_request_failed: {message}"
            ) from exc
        if message.startswith("invalid_selection:"):
            raise LLMSelectionError(message) from exc
        raise LLMSelectionError(
            f"llm_output_invalid_json: {message}"
        ) from exc
