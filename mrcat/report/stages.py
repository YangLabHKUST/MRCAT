"""Writer--Judge stages preserve the original report policies."""
from pathlib import Path
from . import policy as report

class ReportStages:
    def __init__(self, reporter, artifact_store):
        self.reporter = reporter
        self.store = artifact_store

    def evidence(self, state, data, execution):
        from .evidence import select_evidence
        select_evidence(self.reporter, state, data, execution)
        data['report_context'].setdefault('reporting_metadata', report.build_reporting_metadata())
        data.update(revision_attempts=0, revision_history=[])

    def literature(self, state, data, execution):
        context = data["report_context"]
        context["literature_evidence"] = execution.call(
            "literature", report._collect_literature_evidence,
            reporter=self.reporter, finalization_context=context)

    def writer(self, state, data, execution):
        data["draft"] = execution.call("writer", report._draft_report,
            reporter=self.reporter, finalization_context=data["report_context"], figure_catalog=data["figure_catalog"])

    def validate_spec(self, data, draft):
        context = data["report_context"]
        return report._ensure_reporting_declarations(report.validate_report_spec(
            draft, available_figure_ids=[x["figure_id"] for x in data["figure_catalog"]],
            available_reference_ids=report._verified_reference_ids(context["literature_evidence"])),
            context["reporting_metadata"])

    def validate(self, state, data, execution):
        data["draft"] = self.validate_spec(data, data["draft"])

    def save_draft(self, state, data, execution):
        refs = execution.call("save_draft", report._render_report_artifacts,
            artifact_store=self.store, state=state,
            spec=report._attach_verified_references(data["draft"], data["report_context"]["literature_evidence"]),
            literature_evidence=data["report_context"]["literature_evidence"],
            figure_catalog=data["figure_catalog"], figure_assets={k: Path(v) for k,v in data["figure_assets"].items()}, publish_final=False)
        execution.publish(list(refs.values()))

    def judge(self, state, data, execution):
        # Exceptions intentionally leave this native node pending. Resume reruns
        # Judge using the validated draft, without selecting or writing again.
        judgement = execution.call("judge_revision" if data["revision_attempts"] else "judge", report._judge_report,
            reporter=self.reporter, finalization_context=data["report_context"],
            figure_catalog=data["figure_catalog"], report_spec=data["draft"])
        if not data["revision_attempts"]:
            data["initial_judgement"] = judgement
        else:
            previous = data["final_judgement"]
            before, after = report._judge_finding_count(previous), report._judge_finding_count(judgement)
            accepted = judgement["decision"] == "accept" or after < before
            entry = {"attempt": data["revision_attempts"], "accepted": accepted,
                     "previous_finding_count": before, "candidate_finding_count": after}
            if accepted:
                entry["decision"] = judgement["decision"]
            else:
                entry["reason"] = "no_progress"
                data["revision_rejected"] = {"reason": "no_progress", **entry}
                data["draft"] = data["previous_draft"]
                judgement = previous
            data["revision_history"].append(entry)
        data["final_judgement"] = judgement

    def revise(self, state, data, execution):
        data["revision_attempts"] += 1
        attempt = data["revision_attempts"]
        previous = data["final_judgement"]
        before = report._judge_finding_count(previous)
        try:
            candidate = execution.call("writer_revision", report._draft_report, reporter=self.reporter,
                finalization_context=data["report_context"], figure_catalog=data["figure_catalog"],
                current_draft=data["draft"], review_feedback=previous)
            candidate = self.validate_spec(data, candidate)
        except Exception as exc:
            data["revision_rejected"] = {"reason": "revision_generation_failed", "attempt": attempt, "error": report._error_summary(exc)}
            data["revision_history"].append({"attempt": attempt, "accepted": False,
                "reason": "revision_generation_failed", "previous_finding_count": before})
            data["candidate_ready"] = False
            return
        data["candidate_ready"] = True
        data["previous_draft"] = data["draft"]
        data["draft"] = candidate

    def export(self, state, data, execution):
        result = report.export_report(data=data, artifact_store=self.store, state=state, execution=execution)
        return {"report_result": result}

def after_judge(data):
    return "revise" if (data.get("final_judgement", {}).get("decision") == "revise"
        and data["revision_attempts"] < report._MAX_REPORT_REVISIONS
        and not data.get("revision_rejected")) else "export"

def after_revision(data):
    return "save_draft" if data.get("candidate_ready") else after_judge(data)
