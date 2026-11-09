from __future__ import annotations

from pathlib import Path
from typing import Any

from mrcat.tool.MRTool import RMethodSpec, run_method_cli, run_r_method


SPEC = RMethodSpec(
    skill_id="mr-grip",
    script_path=Path(__file__).resolve().parent / "mr_grip" / "run_mr_grip.R",
    input_filename="mr_grip_input.json",
    output_filename="mr_grip_output.json",
    failure_class="mr_grip_failed",
    failure_summary="mr-grip blocked: MR-GRIP fitting failed.",
    cli_description="Run MR-GRIP from a prepared LD-clumped MRdat file.",
)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_r_method(payload, SPEC)


if __name__ == "__main__":
    run_method_cli(SPEC)
