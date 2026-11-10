"""Use the MRCAT model gateway and audit trail for every report stage."""
import json
import re
from time import perf_counter
from mrcat.state.store import now
from typing import Any
from .scientific import report_spec_example, validate_report_spec
from .review import report_judgement_example, validate_report_judgement

class ReporterRoleClient:
    def __init__(self, agent, state, execution=None):
        self.agent, self.state, self.execution = agent, state, execution

    def _request_json(self, *, prompt, instructions, example, validator):
        request = dict(prompt['sections'], instruction=instructions, response_example=example)
        for attempt in range(2):
            user = json.dumps(request, ensure_ascii=False, default=str)
            row = dict(stage=prompt['stage'], attempt='json_repair' if attempt else 'initial',
                       started_at=now(), status='running', input_chars=len(prompt['system']) + len(user))
            if self.execution:
                progress = self.execution.progress
                progress.setdefault('llm_calls', []).append(row)
                progress['json_repair_count'] = progress.get('json_repair_count', 0) + int(bool(attempt))
                self.execution.flush()
            started = perf_counter()
            try:
                raw = self.agent._call(self.state, prompt['stage'], prompt['system'], user)
                row['output_chars'] = len(raw)
                try:
                    text = raw.strip()
                    if text.startswith('```') and text.endswith('```'):
                        text = text.split('\n', 1)[1].rsplit('```', 1)[0]
                    payload = json.loads(text)
                    if not isinstance(payload, dict):
                        raise ValueError('Return a JSON object.')
                    result = validator(payload)
                    row['status'] = 'validated'
                    return result
                except (ValueError, TypeError, KeyError) as exc:
                    row.update(status='invalid', parse_error=str(exc))
                    if attempt:
                        raise
                    request.update(format_error=str(exc), previous_response=raw)
            except Exception:
                if row['status'] == 'running':
                    row['status'] = 'failed'
                raise
            finally:
                if row['status'] == 'running':
                    row['status'] = 'interrupted'
                row['duration_seconds'] = round(perf_counter() - started, 3)
                if self.execution:
                    self.execution.flush()

    def select_session_report_evidence(
            self,
            *,
            prompt: dict,
            example: dict[str, Any],
            validator: Any,
        ) -> dict[str, Any]:
            return self._request_json(
                prompt=prompt,
                instructions=(
                    "Select the session steps that should inform one coherent "
                    "scientific report. Exercise scientific judgement rather than "
                    "selecting every available step."
                ),
                example=example,
                validator=validator,
            )

    def extract_literature_claims(
            self,
            *,
            prompt: dict,
        ) -> dict[str, Any]:
            return self._request_json(
                prompt=prompt,
                instructions=(
                    "Plan one research-background question and up to two MR result "
                    "comparison claims when supported by the supplied task. Background "
                    "queries need not include Mendelian randomization. Use English "
                    "queries grounded in the documented traits and objective; do not "
                    "invent mechanisms or treat search questions as established facts."
                ),
                example={
                    "claims": [
                        {
                            "claim_id": "LC1",
                            "claim": "What prior evidence motivates studying exposure in relation to outcome?",
                            "claim_type": "background",
                            "search_queries": ['"exposure" "outcome"'],
                        },
                        {
                            "claim_id": "LC2",
                            "claim": "The supplied MR evidence evaluates the association between exposure and outcome.",
                            "claim_type": "main_result",
                            "search_queries": ['"exposure" "outcome" Mendelian randomization'],
                        }
                    ]
                },
                validator=_validate_literature_claims,
            )

    def verify_literature_evidence(
            self,
            *,
            prompt: dict,
            valid_claim_ids: list[str],
            background_claim_ids: list[str],
            valid_reference_ids: list[str],
        ) -> dict[str, Any]:
            return self._request_json(
                prompt=prompt,
                instructions=(
                    "Check each candidate abstract against the literature questions "
                    "and result claims. Background-only evidence can receive only "
                    "background_support or not_supporting. Use the smallest defensible "
                    "grade and do not infer missing results from titles or metadata."
                ),
                example={
                    "evaluations": [
                        {
                            "reference_id": "PMID:12345678",
                            "claim_ids": ["LC1"],
                            "support_grade": "background_support",
                            "reasoning": "The abstract provides observational context for the research question.",
                            "citation_wording": "Prior observations motivate assessing whether the relationship is causal.",
                        }
                    ]
                },
                validator=lambda payload: _validate_literature_evaluations(
                    payload,
                    valid_claim_ids=set(valid_claim_ids),
                    background_claim_ids=set(background_claim_ids),
                    valid_reference_ids=set(valid_reference_ids),
                ),
            )

    def draft_scientific_report(
            self,
            *,
            prompt: dict,
            available_figure_ids: list[str],
            available_reference_ids: list[str],
        ) -> dict[str, Any]:
            return self._request_json(
                prompt=prompt,
                instructions=(
                    "Draft or revise the complete semantic scientific report. Use only "
                    "Original Analysis Evidence for this run's facts and numbers. Use "
                    "Verified Literature Evidence for cited research background and "
                    "comparison with prior findings. Explain the research motivation "
                    "without inventing mechanisms, clinical benefits, or evidence gaps. "
                    "Select only the figures that materially support the report."
                ),
                example=report_spec_example(
                    available_figure_ids[:2],
                    reference_ids=available_reference_ids,
                ),
                validator=lambda payload: validate_report_spec(
                    payload,
                    available_figure_ids=available_figure_ids,
                    available_reference_ids=available_reference_ids,
                ),
            )

    def judge_scientific_report(
            self,
            *,
            prompt: dict,
        ) -> dict[str, Any]:
            return self._request_json(
                prompt=prompt,
                instructions=(
                    "Check only for substantive scientific problems: essential missing "
                    "content, evidence mismatches, unsupported causal conclusions, and "
                    "fabricated or misattributed evidence. Return decision and a flat "
                    "issues list with location, problem, and required_change strings. "
                    "If no substantive issue exists, return accept with an empty list. "
                    "Do not enforce a publication checklist or stylistic preferences. "
                    "Never invent, derive, or supply a replacement value."
                ),
                example=report_judgement_example(),
                validator=validate_report_judgement,
            )

def _validate_literature_claims(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) != {"claims"}:
        raise ValueError("literature claim response must contain exactly claims")
    raw_claims = payload.get("claims")
    if not isinstance(raw_claims, list) or len(raw_claims) > 3:
        raise ValueError("claims must be a list containing at most three items")
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_claims):
        if not isinstance(raw, dict) or set(raw) != {
            "claim_id",
            "claim",
            "claim_type",
            "search_queries",
        }:
            raise ValueError(f"claims[{index}] has an invalid shape")
        claim_id = str(raw.get("claim_id") or "").strip()
        claim = str(raw.get("claim") or "").strip()
        claim_type = str(raw.get("claim_type") or "").strip()
        if not re.fullmatch(r"LC[1-9][0-9]*", claim_id) or claim_id in seen:
            raise ValueError(f"claims[{index}].claim_id is invalid or duplicated")
        if not claim or len(claim) > 1000:
            raise ValueError(f"claims[{index}].claim is required")
        if claim_type not in {"background", "main_result", "sensitivity_result", "null_result"}:
            raise ValueError(f"claims[{index}].claim_type is invalid")
        raw_queries = raw.get("search_queries")
        if not isinstance(raw_queries, list) or not 1 <= len(raw_queries) <= 3:
            raise ValueError(f"claims[{index}].search_queries must contain 1-3 queries")
        queries = []
        for query in raw_queries:
            clean = " ".join(str(query or "").split()).strip()
            if clean and clean not in queries:
                queries.append(clean[:500])
        if not queries:
            raise ValueError(f"claims[{index}].search_queries is empty")
        claims.append(
            {
                "claim_id": claim_id,
                "claim": claim,
                "claim_type": claim_type,
                "search_queries": queries,
            }
        )
        seen.add(claim_id)
    background_count = sum(item["claim_type"] == "background" for item in claims)
    if background_count > 1 or len(claims) - background_count > 2:
        raise ValueError("claims allow at most one background question and two result claims")
    return {"claims": claims}

def _validate_literature_evaluations(
    payload: dict[str, Any],
    *,
    valid_claim_ids: set[str],
    background_claim_ids: set[str],
    valid_reference_ids: set[str],
) -> dict[str, Any]:
    if set(payload) != {"evaluations"}:
        raise ValueError("literature verification response must contain exactly evaluations")
    raw_evaluations = payload.get("evaluations")
    if not isinstance(raw_evaluations, list):
        raise ValueError("evaluations must be a list")
    allowed_grades = {
        "strong_support",
        "partial_support",
        "background_support",
        "contradictory_or_limiting",
        "not_supporting",
    }
    evaluations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_evaluations):
        if not isinstance(raw, dict) or set(raw) != {
            "reference_id",
            "claim_ids",
            "support_grade",
            "reasoning",
            "citation_wording",
        }:
            raise ValueError(f"evaluations[{index}] has an invalid shape")
        reference_id = str(raw.get("reference_id") or "").strip()
        if reference_id not in valid_reference_ids or reference_id in seen:
            raise ValueError(f"evaluations[{index}].reference_id is invalid or duplicated")
        claim_ids = [
            str(value).strip()
            for value in list(raw.get("claim_ids") or [])
            if str(value).strip()
        ]
        if not claim_ids or any(value not in valid_claim_ids for value in claim_ids):
            raise ValueError(f"evaluations[{index}].claim_ids contains an unknown claim")
        support_grade = str(raw.get("support_grade") or "").strip()
        if support_grade not in allowed_grades:
            raise ValueError(f"evaluations[{index}].support_grade is invalid")
        if set(claim_ids) <= background_claim_ids and support_grade not in {
            "background_support", "not_supporting",
        }:
            raise ValueError(f"evaluations[{index}] cannot use background-only evidence as result support")
        reasoning = str(raw.get("reasoning") or "").strip()
        wording = str(raw.get("citation_wording") or "").strip()
        if not reasoning or len(reasoning) > 2000:
            raise ValueError(f"evaluations[{index}].reasoning is required")
        if len(wording) > 1000:
            raise ValueError(f"evaluations[{index}].citation_wording is too long")
        evaluations.append(
            {
                "reference_id": reference_id,
                "claim_ids": list(dict.fromkeys(claim_ids)),
                "support_grade": support_grade,
                "reasoning": reasoning,
                "citation_wording": wording,
                "evidence_basis": "abstract",
            }
        )
        seen.add(reference_id)
    missing = sorted(valid_reference_ids.difference(seen))
    if missing:
        raise ValueError(
            "evaluations must classify every candidate reference: "
            + ", ".join(missing)
        )
    return {"evaluations": evaluations}
