from __future__ import annotations

from pathlib import Path
from typing import Any

from mrcat.tool.MRTool import RMethodSpec, run_method_cli, run_r_method


SPEC = RMethodSpec(
    skill_id="mr-lasso",
    script_path=Path(__file__).resolve().parent / "mr_lasso" / "run_mr_lasso.R",
    input_filename="mr_lasso_input.json",
    output_filename="mr_lasso_output.json",
    failure_class="mr_lasso_failed",
    failure_summary="mr-lasso blocked: MR-Lasso fitting failed.",
    cli_description="Run MR-Lasso from prepared MRdat.",
)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_r_method(payload, SPEC)


if __name__ == "__main__":
    run_method_cli(SPEC)
