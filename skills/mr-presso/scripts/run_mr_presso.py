from __future__ import annotations

from pathlib import Path
from typing import Any

from mrcat.tool.MRTool import RMethodSpec, run_method_cli, run_r_method


SPEC = RMethodSpec(
    skill_id="mr-presso",
    script_path=Path(__file__).resolve().parent / "mr_presso" / "run_mr_presso.R",
    input_filename="mr_presso_input.json",
    output_filename="mr_presso_output.json",
    failure_class="mr_presso_failed",
    failure_summary="mr-presso blocked: MRPRESSO::mr_presso failed.",
    cli_description="Run standalone MR-PRESSO from prepared MRdat.",
)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_r_method(payload, SPEC)


if __name__ == "__main__":
    run_method_cli(SPEC)
