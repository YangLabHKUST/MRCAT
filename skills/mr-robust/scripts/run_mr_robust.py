from __future__ import annotations

from pathlib import Path
from typing import Any

from mrcat.tool.mr import RMethodSpec, run_method_cli, run_r_method


SPEC = RMethodSpec(
    skill_id="mr-robust",
    script_path=Path(__file__).resolve().parent / "mr_robust" / "run_mr_robust.R",
    input_filename="mr_robust_input.json",
    output_filename="mr_robust_output.json",
    failure_class="mr_robust_failed",
    failure_summary="mr-robust blocked: robustbase::lmrob failed.",
    cli_description="Run MR-Robust from prepared MRdat.",
)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_r_method(payload, SPEC)


if __name__ == "__main__":
    run_method_cli(SPEC)
