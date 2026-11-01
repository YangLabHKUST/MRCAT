from __future__ import annotations

from pathlib import Path
from typing import Any

from mrcat.tool.mr import RMethodSpec, run_method_cli, run_r_method


SPEC = RMethodSpec(
    skill_id="mr-primary",
    script_path=Path(__file__).resolve().parent / "mr_primary" / "run_mr_primary.R",
    input_filename="mr_primary_input.json",
    output_filename="mr_primary_output.json",
    failure_class="mr_primary_failed",
    failure_summary="mr-primary blocked: primary MR fitting failed.",
    cli_description="Run primary MR methods from prepared MRdat.",
)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_r_method(payload, SPEC)


if __name__ == "__main__":
    run_method_cli(SPEC)
