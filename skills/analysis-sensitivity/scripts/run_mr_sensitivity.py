from pathlib import Path
from mrcat.tool.mr import RMethodSpec, run_r_method, run_method_cli

SPEC = RMethodSpec(
    skill_id="analysis-sensitivity",
    script_path=Path(__file__).resolve().parent / "mr_sensitivity" / "run_mr_sensitivity.R",
    input_filename="mr_sensitivity_input.json",
    output_filename="mr_sensitivity_output.json",
    failure_class="mr_sensitivity_failed",
    failure_summary="analysis-sensitivity blocked: sensitivity analysis failed.",
    cli_description="Run MR sensitivity analysis from a primary result record.",
    required_inputs=("primary_result_record_path",),
)

def run(payload: dict) -> dict:
    return run_r_method(payload, SPEC)


if __name__ == "__main__":
    run_method_cli(SPEC)
