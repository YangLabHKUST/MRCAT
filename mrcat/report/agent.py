"""Report model stages adapted to the native MRCAT Agent."""
from datetime import UTC, datetime
from typing import Any
from .client import ReporterRoleClient
from .literature import PubMedLiteratureClient
from .policy import (ReportNotApplicable, validate_session_report_selection,
    _catalog_step_refs, _literature_evidence, _verified_reference_ids,
    _report_judge_evidence, _empty_literature_evidence, _error_summary, _literature_policy)

class ReportAgent:
    def __init__(self, agent, state, *, literature_client=None, execution=None):
        self.agent, self.state = agent, state
        self.reporter_client = ReporterRoleClient(agent, state, execution)
        self.literature_client = literature_client or PubMedLiteratureClient()

    def build_structured_prompt(self, *, stage, sections):
        base = self.agent.root / 'mrcat/prompts'
        system = (base / 'reporter.system.md').read_text() + '\n' + (base / f'reporter.{stage}.system.md').read_text()
        system += '\n' + self.agent.prompt('report')
        return dict(stage=stage, system=system, sections=sections)

    def select_session_report_evidence(
            self,
            *,
            catalog: dict[str, Any],
        ) -> dict[str, Any]:
            available_step_refs = _catalog_step_refs(catalog)
            if not available_step_refs:
                raise ReportNotApplicable("the session has no analysis steps to report")
            mr_step_refs = {
                str(step.get("step_ref") or "").strip()
                for task in list(catalog.get("tasks") or [])
                if isinstance(task, dict)
                for step in list(task.get("steps") or [])
                if isinstance(step, dict)
                and (
                    str(step.get("skill_id") or "").startswith("mr-")
                    or str(step.get("skill_id") or "") == "gwas-pair-prepare"
                    or step.get("is_mr", False)
                )
            }
            if not mr_step_refs:
                raise ReportNotApplicable("the session has no applicable MR evidence")
            prompt = self.build_structured_prompt(
                stage="report_selection",
                sections={"Session Evidence Catalog": catalog},
            )
            return self.reporter_client.select_session_report_evidence(
                prompt=prompt,
                example={
                    "selected_step_refs": available_step_refs[:2],
                    "selection_reason": (
                        "These steps provide the coherent evidence needed for the report."
                    ),
                },
                validator=lambda payload: validate_session_report_selection(
                    payload,
                    available_step_refs=available_step_refs,
                    mr_step_refs=mr_step_refs,
                ),
            )

    def draft_scientific_report(
            self,
            *,
            finalization_context: dict[str, Any],
            figure_catalog: list[dict[str, Any]],
            current_draft: dict[str, Any] | None = None,
            review_feedback: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            literature_evidence = _literature_evidence(finalization_context)
            analysis_evidence = dict(finalization_context)
            analysis_evidence.pop("literature_evidence", None)
            guidance = analysis_evidence.pop("skill_interpretation_guidance", [])
            task_memories = analysis_evidence.pop("task_memories", [])
            reference_ids = _verified_reference_ids(literature_evidence)
            prompt = self.build_structured_prompt(
                stage="report_writer",
                sections={
                    "Original Analysis Evidence": analysis_evidence,
                    "Task Memory": task_memories,
                    "Skill Interpretation Guidance": guidance,
                    "Verified Literature Evidence": literature_evidence,
                    "Allowed Reference IDs": reference_ids,
                    "Figure Catalog": figure_catalog,
                    "Current Validated Draft": current_draft or "None",
                    "Review Feedback": review_feedback or "None",
                },
            )
            return self.reporter_client.draft_scientific_report(
                prompt=prompt,
                available_figure_ids=[
                    str(item.get("figure_id") or "").strip()
                    for item in figure_catalog
                    if str(item.get("figure_id") or "").strip()
                ],
                available_reference_ids=reference_ids,
            )

    def judge_scientific_report(
            self,
            *,
            finalization_context: dict[str, Any],
            figure_catalog: list[dict[str, Any]],
            report_spec: dict[str, Any],
        ) -> dict[str, Any]:
            compact_evidence = _report_judge_evidence(finalization_context)
            literature_evidence = _literature_evidence(compact_evidence)
            compact_evidence.pop("literature_evidence", None)
            prompt = self.build_structured_prompt(
                stage="report_judge",
                sections={
                    "Original Analysis Evidence": compact_evidence,
                    "Task Memory": finalization_context.get("task_memories", []),
                    "Skill Interpretation Guidance": finalization_context.get("skill_interpretation_guidance", []),
                    "Verified Literature Evidence": literature_evidence,
                    "Figure Catalog": figure_catalog,
                    "Report Draft": report_spec,
                },
            )
            return self.reporter_client.judge_scientific_report(
                prompt=prompt,
            )

    def collect_literature_evidence(
            self,
            *,
            finalization_context: dict[str, Any],
        ) -> dict[str, Any]:
            prompt = self.build_structured_prompt(
                stage="literature_claims",
                sections={
                    "Original Analysis Evidence": _report_judge_evidence(
                        finalization_context
                    )
                },
            )
            claims_payload = self.reporter_client.extract_literature_claims(
                prompt=prompt,
            )
            claims = list(claims_payload.get("claims") or [])
            searched_at = datetime.now(UTC).isoformat()
            if not claims:
                return _empty_literature_evidence(
                    status="completed",
                    searched_at=searched_at,
                    claims=[],
                )

            candidates: dict[str, dict[str, Any]] = {}
            search_runs: list[dict[str, Any]] = []
            failures: list[dict[str, str]] = []
            for claim in claims:
                claim_id = str(claim["claim_id"])
                query = str(list(claim.get("search_queries") or [""])[0]).strip()
                try:
                    records = self.literature_client.search(query, max_results=3)
                except Exception as exc:
                    failures.append(
                        {
                            "claim_id": claim_id,
                            "query": query,
                            "error": _error_summary(exc),
                        }
                    )
                    continue
                search_runs.append(
                    {
                        "claim_id": claim_id,
                        "query": query,
                        "result_count": len(records),
                    }
                )
                for record in records:
                    reference_id = str(record.get("reference_id") or "").strip()
                    if not reference_id:
                        continue
                    if reference_id not in candidates and len(candidates) >= 9:
                        break
                    existing = candidates.setdefault(
                        reference_id,
                        {**record, "candidate_claim_ids": []},
                    )
                    if claim_id not in existing["candidate_claim_ids"]:
                        existing["candidate_claim_ids"].append(claim_id)

            candidate_records = list(candidates.values())
            verifiable = [
                record
                for record in candidate_records
                if str(record.get("abstract") or "").strip()
                and not bool(record.get("retracted"))
            ]
            metadata_only = [
                {
                    **record,
                    "support_grade": "metadata_only_candidate",
                    "reasoning": (
                        "The PubMed record has no abstract available for claim-level "
                        "verification."
                        if not str(record.get("abstract") or "").strip()
                        else "The record is retracted and cannot support the report."
                    ),
                }
                for record in candidate_records
                if record not in verifiable
            ]
            if not verifiable:
                status = "failed" if failures and not candidate_records else "completed"
                return {
                    **_empty_literature_evidence(
                        status=status,
                        searched_at=searched_at,
                        claims=claims,
                    ),
                    "search_runs": search_runs,
                    "screened_candidates": metadata_only,
                    "failures": failures,
                }

            verify_prompt = self.build_structured_prompt(
                stage="literature_verify",
                sections={
                    "Literature Questions and Claims": claims,
                    "Candidate PubMed Records": verifiable,
                },
            )
            try:
                verification = self.reporter_client.verify_literature_evidence(
                    prompt=verify_prompt,
                    valid_claim_ids=[str(item["claim_id"]) for item in claims],
                    background_claim_ids=[
                        str(item["claim_id"]) for item in claims
                        if item["claim_type"] == "background"
                    ],
                    valid_reference_ids=[
                        str(item["reference_id"]) for item in verifiable
                    ],
                )
            except Exception as exc:
                return {
                    "status": "failed",
                    "source": "PubMed ESearch and EFetch",
                    "searched_at": searched_at,
                    "policy": _literature_policy(),
                    "claims": claims,
                    "search_runs": search_runs,
                    "studies": [],
                    "screened_candidates": [
                        *metadata_only,
                        *[
                            {
                                **record,
                                "support_grade": "verification_failed",
                                "reasoning": (
                                    "The PubMed abstract was retrieved, but the "
                                    "claim-level verifier failed."
                                ),
                            }
                            for record in verifiable
                        ],
                    ],
                    "failures": [
                        *failures,
                        {
                            "phase": "literature_verification",
                            "error": _error_summary(exc),
                        },
                    ],
                }
            evaluation_by_id = {
                str(item["reference_id"]): item
                for item in list(verification.get("evaluations") or [])
            }
            evaluated = [
                {**record, **evaluation_by_id[str(record["reference_id"])]}
                for record in verifiable
                if str(record["reference_id"]) in evaluation_by_id
            ]
            studies = [
                record
                for record in evaluated
                if str(record.get("support_grade") or "") != "not_supporting"
            ]
            return {
                "status": "completed",
                "source": "PubMed ESearch and EFetch",
                "searched_at": searched_at,
                "policy": _literature_policy(),
                "claims": claims,
                "search_runs": search_runs,
                "studies": studies,
                "screened_candidates": [
                    *metadata_only,
                    *[
                        record
                        for record in evaluated
                        if str(record.get("support_grade") or "") == "not_supporting"
                    ],
                ],
                "failures": failures,
            }
