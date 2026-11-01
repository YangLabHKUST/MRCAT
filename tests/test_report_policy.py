import unittest
from mrcat.report.review import validate_report_judgement, report_judgement_example

def _finding(index: int) -> dict:
    return {
        "location": f"Main results {index}",
        "problem": "The interpretation is not sufficiently bounded by the evidence.",
        "required_change": "Narrow the interpretation using only the supplied evidence.",
    }

def _judgement(revise_count: int = 0) -> dict:
    return {
        "decision": "revise" if revise_count else "accept",
        "issues": [_finding(index) for index in range(revise_count)],
    }

class ReportPolicyTests(unittest.TestCase):
    def test_judge_contract_accepts_no_issues_without_a_checklist(self):
        self.assertEqual(validate_report_judgement(_judgement()), _judgement())
        self.assertEqual(
            validate_report_judgement(report_judgement_example()),
            report_judgement_example(),
        )

    def test_judge_contract_may_reference_a_number_without_becoming_evidence(self):
        payload = _judgement(1)
        payload["issues"][0]["problem"] = "The draft reports 9.99 without supporting evidence."
        judgement = validate_report_judgement(payload)
        self.assertEqual(judgement, payload)

    def test_judge_contract_rejects_conflicting_decisions(self):
        for payload in (
            {"decision": "accept", "issues": [_finding(0)]},
            {"decision": "revise", "issues": []},
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "conflicts with issues"):
                    validate_report_judgement(payload)

    def test_judge_contract_rejects_nested_or_missing_issue_fields(self):
        for field in ("location", "problem", "required_change"):
            for value in ({"text": "Nested"}, ["Nested"], "", None):
                payload = _judgement(1)
                payload["issues"][0][field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValueError, "non-empty text"):
                        validate_report_judgement(payload)
            payload = _judgement(1)
            del payload["issues"][0][field]
            with self.assertRaisesRegex(ValueError, "must contain exactly"):
                validate_report_judgement(payload)

    def test_judge_contract_does_not_accept_the_old_checklist(self):
        with self.assertRaisesRegex(ValueError, "exactly decision and issues"):
            validate_report_judgement(
                {"decision": "accept", "checklist": [], "findings": []}
            )
