from __future__ import annotations

from typing import Any


def report_judgement_example() -> dict[str, Any]:
    return {
        "decision": "revise",
        "issues": [
            {
                "location": "Conclusion",
                "problem": "The causal claim is stronger than the supplied results support.",
                "required_change": "Match the conclusion to the estimates and uncertainty.",
            }
        ],
    }


def validate_report_judgement(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a shallow list of substantive scientific issues."""

    if not isinstance(payload, dict) or set(payload) != {"decision", "issues"}:
        raise ValueError("report judgement must contain exactly decision and issues")
    decision = payload["decision"]
    if decision not in ("accept", "revise"):
        raise ValueError("report judgement decision must be accept or revise")
    raw_issues = payload["issues"]
    if not isinstance(raw_issues, list):
        raise ValueError("report judgement issues must be a list")
    issues = []
    fields = ("location", "problem", "required_change")
    for index, raw in enumerate(raw_issues):
        if not isinstance(raw, dict) or set(raw) != set(fields):
            raise ValueError(
                f"report judgement issues[{index}] must contain exactly "
                "location, problem, and required_change"
            )
        issue = {}
        for field in fields:
            value = raw[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"report judgement issues[{index}].{field} must be non-empty text"
                )
            issue[field] = value.strip()
        issues.append(issue)
    expected = "revise" if issues else "accept"
    if decision != expected:
        raise ValueError(f"report judgement decision conflicts with issues: expected {expected}")
    return {"decision": decision, "issues": issues}
