from __future__ import annotations

from contextlib import redirect_stdout

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mrcat.tool.skill_runner.subprocess_stream import run_streaming


@dataclass(frozen=True)
class RMethodSpec:
    skill_id: str
    script_path: Path
    input_filename: str
    output_filename: str
    failure_class: str
    failure_summary: str
    cli_description: str
    required_inputs: tuple[str, ...] = ("mrdat_path",)


def compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def load_json_arg(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    candidate = Path(value)
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(value)


def execution_dir(skill_id: str) -> Path:
    default_name = f"tmp_{skill_id.replace('-', '_')}"
    target = Path(os.getenv("MRCAT_EXECUTION_DIR") or Path.cwd() / default_name).resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def _blocked_missing_input(spec: RMethodSpec, key: str) -> dict[str, Any]:
    return {
        "summary": f"{spec.skill_id} blocked: missing {key}.",
        "outputs": {"status": "blocked", "failure_class": "missing_input", "missing_input": key},
        "details": {"failure_class": "missing_input", "missing_input": key},
    }


def _blocked_method_failure(
    spec: RMethodSpec,
    *,
    summary: str | None = None,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, Any]:
    details = {"failure_class": spec.failure_class}
    if stdout or stderr:
        details.update(
            {
                "stdout_tail": compact_text(stdout)[-1000:],
                "stderr_tail": compact_text(stderr)[-1000:],
            }
        )
    return {
        "summary": summary or spec.failure_summary,
        "outputs": {"status": "blocked", "failure_class": spec.failure_class},
        "details": details,
    }


def run_r_method(payload: dict[str, Any], spec: RMethodSpec) -> dict[str, Any]:
    method_input = dict(payload or {})
    for key in spec.required_inputs:
        raw_path = compact_text(method_input.get(key))
        if not raw_path or not Path(raw_path).exists():
            return _blocked_missing_input(spec, key)
        method_input[key] = str(Path(raw_path).resolve())

    exec_dir = execution_dir(spec.skill_id)
    output_path = exec_dir / "reports" / spec.output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    input_path = exec_dir / spec.input_filename
    input_path.write_text(
        json.dumps(method_input, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    script_path = spec.script_path.resolve()
    completed = run_streaming(
        [
            os.environ.get("RSCRIPT_BIN") or "Rscript",
            str(script_path),
            str(input_path),
            str(output_path),
            str(exec_dir),
        ],
        on_stdout_line=lambda line: print(line, flush=True),
        on_stderr_line=lambda line: print(line, file=sys.stderr, flush=True),
        cwd=str(exec_dir),
    )
    if completed.returncode != 0:
        return _blocked_method_failure(
            spec,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    if not output_path.exists():
        return _blocked_method_failure(
            spec,
            summary=f"{spec.skill_id} blocked: R runner did not write output JSON.",
        )
    return json.loads(output_path.read_text(encoding="utf-8"))


def run_method_cli(spec: RMethodSpec) -> None:
    parser = argparse.ArgumentParser(description=spec.cli_description)
    parser.add_argument("--input-json")
    args = parser.parse_args()
    with redirect_stdout(sys.stderr):
        result = run_r_method(load_json_arg(args.input_json), spec)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
