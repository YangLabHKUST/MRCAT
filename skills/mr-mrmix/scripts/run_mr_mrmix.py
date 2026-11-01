from __future__ import annotations

from pathlib import Path
from typing import Any

from mrcat.tool.mr import RMethodSpec, run_method_cli, run_r_method


SPEC = RMethodSpec(
    skill_id="mr-mrmix",
    script_path=Path(__file__).resolve().parent / "mr_mrmix" / "run_mr_mrmix.R",
    input_filename="mr_mrmix_input.json",
    output_filename="mr_mrmix_output.json",
    failure_class="mr_mrmix_failed",
    failure_summary="mr-mrmix blocked: MRMix::MRMix failed.",
    cli_description="Run MRMix from prepared MRdat.",
)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_r_method(payload, SPEC)


if __name__ == "__main__":
    run_method_cli(SPEC)
