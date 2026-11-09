from __future__ import annotations

from pathlib import Path
from typing import Any

from mrcat.tool.MRTool import RMethodSpec, run_method_cli, run_r_method


SPEC = RMethodSpec(
    skill_id="mr-bwmr",
    script_path=Path(__file__).resolve().parent / "bwmr" / "run_mr_bwmr.R",
    input_filename="mr_bwmr_input.json",
    output_filename="mr_bwmr_output.json",
    failure_class="mr_bwmr_failed",
    failure_summary="mr-bwmr blocked: BWMR fitting failed.",
    cli_description="Run BWMR from prepared MRdat.",
)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_r_method(payload, SPEC)


if __name__ == "__main__":
    run_method_cli(SPEC)
