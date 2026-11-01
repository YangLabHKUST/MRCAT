from __future__ import annotations

from pathlib import Path
from typing import Any

from mrcat.tool.mr import RMethodSpec, run_method_cli, run_r_method


SPEC = RMethodSpec(
    skill_id="mr-conmix",
    script_path=Path(__file__).resolve().parent / "mr_conmix" / "run_mr_conmix.R",
    input_filename="mr_conmix_input.json",
    output_filename="mr_conmix_output.json",
    failure_class="mr_conmix_failed",
    failure_summary="mr-conmix blocked: MR-ConMix fitting failed.",
    cli_description="Run MR-ConMix from prepared MRdat.",
)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_r_method(payload, SPEC)


if __name__ == "__main__":
    run_method_cli(SPEC)
