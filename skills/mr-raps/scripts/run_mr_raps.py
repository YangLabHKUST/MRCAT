from __future__ import annotations

from pathlib import Path
from typing import Any

from mrcat.tool.MRTool import RMethodSpec, run_method_cli, run_r_method


SPEC = RMethodSpec(
    skill_id="mr-raps",
    script_path=Path(__file__).resolve().parent / "mr_raps" / "run_mr_raps.R",
    input_filename="mr_raps_input.json",
    output_filename="mr_raps_output.json",
    failure_class="mr_raps_failed",
    failure_summary="mr-raps blocked: mr.raps::mr.raps failed.",
    cli_description="Run MR-RAPS from prepared MRdat.",
)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_r_method(payload, SPEC)


if __name__ == "__main__":
    run_method_cli(SPEC)
