from __future__ import annotations

from pathlib import Path
from typing import Any

from mrcat.tool.mr import RMethodSpec, run_method_cli, run_r_method


SPEC = RMethodSpec(
    skill_id="mr-apss",
    script_path=Path(__file__).resolve().parent / "mrapss" / "run_mrapss.R",
    input_filename="mrapss_input.json",
    output_filename="mrapss_output.json",
    failure_class="mrapss_failed",
    failure_summary="mr-apss blocked: MRAPSS::MRAPSS failed.",
    cli_description="Fit MR-APSS from prepared MRdat/C/Omega.",
    required_inputs=("mrdat_path", "c_path", "omega_path"),
)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_r_method(payload, SPEC)


if __name__ == "__main__":
    run_method_cli(SPEC)
