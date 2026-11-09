from __future__ import annotations

from pathlib import Path
from typing import Any

from mrcat.tool.MRTool import RMethodSpec, run_method_cli, run_r_method


SPEC = RMethodSpec(
    skill_id="mr-cml-ma",
    script_path=Path(__file__).resolve().parent / "mr_cml_ma" / "run_mr_cml_ma.R",
    input_filename="mr_cml_ma_input.json",
    output_filename="mr_cml_ma_output.json",
    failure_class="mr_cml_ma_failed",
    failure_summary="mr-cml-ma blocked: MRcML::mr_cML failed.",
    cli_description="Run cML-MA from prepared MRdat.",
)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_r_method(payload, SPEC)


if __name__ == "__main__":
    run_method_cli(SPEC)
