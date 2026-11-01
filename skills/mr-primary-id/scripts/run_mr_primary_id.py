from __future__ import annotations

from contextlib import redirect_stdout

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from mrcat.tool.skill_runner.subprocess_stream import run_streaming


def compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def load_json_arg(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    candidate = Path(value)
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(value)


def execution_dir() -> Path:
    target = Path(os.getenv("MRCAT_EXECUTION_DIR") or Path.cwd() / "tmp_mr_primary_id").resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def rscript_bin() -> str:
    return os.environ.get("RSCRIPT_BIN") or "Rscript"


def run(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload or {})
    missing = [
        key
        for key in ("exposure_gwas_id", "outcome_gwas_id")
        if not compact_text(payload.get(key))
    ]
    if missing:
        return {
            "summary": "mr-primary-id blocked: missing OpenGWAS study ID input.",
            "outputs": {"status": "blocked", "failure_class": "missing_input", "missing_inputs": missing},
            "details": {"failure_class": "missing_input", "missing_inputs": missing},
        }
    raw_threshold = payload.get("pvalue_threshold", 5e-8)
    thresholds = raw_threshold if isinstance(raw_threshold, list) else [raw_threshold]
    if (not thresholds
            or any(isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 < p <= 1 for p in thresholds)
            or any(left >= right for left, right in zip(thresholds, thresholds[1:]))):
        message = "pvalue_threshold must be a number in (0, 1] or a nonempty strictly increasing list of such numbers."
        return {"summary": "mr-primary-id blocked: " + message,
                "outputs": {"status": "blocked", "failure_class": "invalid_threshold"},
                "details": {"failure_class": "invalid_threshold", "message": message}}
    out_json = execution_dir() / "reports" / "mr_primary_id_output.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    input_json = execution_dir() / "mr_primary_id_input.json"
    input_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    script = Path(__file__).resolve().parent / "mr_primary_id" / "run_mr_primary_id.R"
    completed = run_streaming(
        [rscript_bin(), str(script), str(input_json), str(out_json), str(execution_dir())],
        on_stdout_line=lambda line: print(line, flush=True),
        on_stderr_line=lambda line: print(line, file=sys.stderr, flush=True),
        cwd=str(execution_dir()),
    )
    if completed.returncode != 0:
        return {
            "summary": "mr-primary-id blocked: TwoSampleMR OpenGWAS primary analysis failed.",
            "outputs": {"status": "blocked", "failure_class": "mr_primary_id_failed"},
            "details": {
                "failure_class": "mr_primary_id_failed",
                "stdout_tail": compact_text(completed.stdout)[-1000:],
                "stderr_tail": compact_text(completed.stderr)[-1000:],
            },
        }
    if not out_json.exists():
        return {
            "summary": "mr-primary-id blocked: R runner did not write output JSON.",
            "outputs": {"status": "blocked", "failure_class": "mr_primary_id_failed"},
            "details": {"failure_class": "mr_primary_id_failed"},
        }
    result = json.loads(out_json.read_text(encoding="utf-8"))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TwoSampleMR primary MR from OpenGWAS study IDs.")
    parser.add_argument("--input-json")
    args = parser.parse_args()
    with redirect_stdout(sys.stderr):
        result = run(load_json_arg(args.input_json))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
