from __future__ import annotations

from contextlib import redirect_stdout

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from mrcat.database import database, database_resource_ids
from mrcat.tool.ld_reference import recorded_ld_reference_details
from mrcat.tool.skill_runner.subprocess_stream import run_streaming


def compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def failure_class_for_process(stderr: str) -> str:
    normalized = compact_text(stderr).lower()
    auth_markers = (
        "jwt token is required",
        "invalid token",
        "opengwas api: 401",
        "opengwas api clumping failed because a jwt",
    )
    if any(marker in normalized for marker in auth_markers):
        return "opengwas_auth_required"
    if "opengwas http 502" in normalized:
        return "opengwas_http_502"
    return "gwas_pair_prepare_failed"


def load_json_arg(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    candidate = Path(value)
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(value)


def execution_dir() -> Path:
    target = Path(os.getenv("MRCAT_EXECUTION_DIR") or Path.cwd() / "tmp_gwas_pair_prepare").resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def run(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload or {})
    payload["ldscore_dir"] = str(database("ldsc.eur"))
    bfile = compact_text(payload.get("bfile"))
    if bfile:
        if bfile in database_resource_ids():
            payload["bfile"] = str(database(bfile))
        if not compact_text(payload.get("plink_bin")):
            payload["plink_bin"] = str(database("plink.binary"))
    for key in ("formatted_exposure_path", "formatted_outcome_path"):
        path = Path(compact_text(payload.get(key)))
        if not path.exists():
            return {
                "summary": f"gwas-pair-prepare blocked: missing {key}.",
                "outputs": {"status": "blocked"},
                "details": {"failure_class": "missing_input", "missing_input": key},
            }
    out_json = execution_dir() / "reports" / "gwas_pair_prepare_output.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    (out_json.parent / "ld_clumping_reference.json").unlink(missing_ok=True)
    input_json = execution_dir() / "gwas_pair_prepare_input.json"
    input_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    script = Path(__file__).resolve().parent / "gwas_pair_prepare" / "run_gwas_pair_prepare.R"
    completed = run_streaming(
        [os.environ.get("RSCRIPT_BIN") or "Rscript", str(script), str(input_json), str(out_json), str(execution_dir())],
        on_stdout_line=lambda line: print(line, flush=True),
        on_stderr_line=lambda line: print(line, file=sys.stderr, flush=True),
        cwd=str(script.parent),
    )
    if completed.returncode != 0:
        failure_class = failure_class_for_process(completed.stderr)
        return {
            "summary": (
                "gwas-pair-prepare blocked: OpenGWAS authentication is required."
                if failure_class == "opengwas_auth_required"
                else "gwas-pair-prepare blocked: OpenGWAS HTTP 502; no local clumping result was produced."
                if failure_class == "opengwas_http_502"
                else "gwas-pair-prepare blocked: background estimation or LD clumping failed."
            ),
            "outputs": {"status": "blocked"},
            "details": {
                **recorded_ld_reference_details(execution_dir()),
                "failure_class": failure_class,
                "stdout_tail": compact_text(completed.stdout)[-1000:],
                "stderr_tail": compact_text(completed.stderr)[-1000:],
            },
        }
    if not out_json.exists():
        return {
            "summary": "gwas-pair-prepare blocked: R runner did not write output JSON.",
            "outputs": {"status": "blocked"},
            "details": {"failure_class": "gwas_pair_prepare_failed"},
        }
    result = json.loads(out_json.read_text(encoding="utf-8"))
    result.setdefault("details", {}).update(recorded_ld_reference_details(execution_dir()))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a reusable harmonized and LD-clumped GWAS pair dataset.")
    parser.add_argument("--input-json")
    args = parser.parse_args()
    with redirect_stdout(sys.stderr):
        result = run(load_json_arg(args.input_json))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
