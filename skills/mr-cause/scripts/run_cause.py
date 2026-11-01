from __future__ import annotations

from contextlib import redirect_stdout

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from mrcat.tool.ld_reference import recorded_ld_reference_details
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
    target = Path(os.getenv("MRCAT_EXECUTION_DIR") or Path.cwd() / "tmp_cause").resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def run(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload or {})
    for key in ("canonical_exposure_path", "canonical_outcome_path"):
        path_text = compact_text(payload.get(key))
        path = Path(path_text) if path_text else None
        if path is None or not path.is_file():
            return {
                "summary": f"mr-cause blocked: missing {key}.",
                "outputs": {"status": "blocked", "failure_class": "missing_input", "missing_input": key},
                "details": {"failure_class": "missing_input", "missing_input": key},
            }
        payload[key] = str(path.resolve())
    out_json = execution_dir() / "reports" / "cause_output.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    (out_json.parent / "ld_clumping_reference.json").unlink(missing_ok=True)
    input_json = execution_dir() / "cause_input.json"
    input_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    script = Path(__file__).resolve().parent / "cause" / "run_cause.R"
    completed = run_streaming(
        [os.environ.get("RSCRIPT_BIN") or "Rscript", str(script), str(input_json), str(out_json), str(execution_dir())],
        on_stdout_line=lambda line: print(line, flush=True),
        on_stderr_line=lambda line: print(line, file=sys.stderr, flush=True),
        cwd=str(execution_dir()),
    )
    if completed.returncode != 0:
        return {
            "summary": "mr-cause blocked: CAUSE fitting failed.",
            "outputs": {"status": "blocked", "failure_class": "cause_failed"},
            "details": {
                **recorded_ld_reference_details(execution_dir()),
                "failure_class": "cause_failed",
                "stdout_tail": compact_text(completed.stdout)[-1000:],
                "stderr_tail": compact_text(completed.stderr)[-1000:],
            },
        }
    if not out_json.exists():
        return {
            "summary": "mr-cause blocked: R runner did not write output JSON.",
            "outputs": {"status": "blocked", "failure_class": "cause_failed"},
            "details": {"failure_class": "cause_failed"},
        }
    result = json.loads(out_json.read_text(encoding="utf-8"))
    result.setdefault("details", {}).update(recorded_ld_reference_details(execution_dir()))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CAUSE from canonical exposure/outcome studies.")
    parser.add_argument("--input-json")
    args = parser.parse_args()
    with redirect_stdout(sys.stderr):
        result = run(load_json_arg(args.input_json))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
