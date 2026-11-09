"""Result-level scale provenance, separate from phenotype units and task state."""
from __future__ import annotations

from typing import Any, Iterable


def input_scale_issue(rows: Iterable[dict[str, Any]], *, require_known: bool = False) -> str | None:
    scales = {str(row.get("input_scale") or "unknown") for row in rows}
    if len(scales) > 1:
        return "Mixed input scales: " + ", ".join(sorted(scales)) + ". Compare each scale separately or rerun methods on one scale."
    if require_known and (not scales or "unknown" in scales):
        return "Input scale is undocumented; rerun the source methods before combining effect estimates."
    return None
