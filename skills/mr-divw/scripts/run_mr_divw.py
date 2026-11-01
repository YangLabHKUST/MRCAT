from __future__ import annotations

from pathlib import Path
from typing import Any

from mrcat.tool.mr import RMethodSpec, run_method_cli, run_r_method


SPEC = RMethodSpec(
    skill_id="mr-divw",
    script_path=Path(__file__).resolve().parent / "mr_divw" / "run_mr_divw.R",
    input_filename="mr_divw_input.json",
    output_filename="mr_divw_output.json",
    failure_class="mr_divw_failed",
    failure_summary="mr-divw blocked: mr.divw::mr.divw failed.",
    cli_description="Run dIVW from prepared MRdat.",
)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_r_method(payload, SPEC)


if __name__ == "__main__":
    run_method_cli(SPEC)
