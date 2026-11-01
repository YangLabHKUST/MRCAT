from __future__ import annotations

from contextlib import redirect_stdout

import argparse
import importlib.util
import json
import math
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from mrcat.database import database
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
    target = Path(
        os.getenv("MRCAT_EXECUTION_DIR")
        or Path.cwd() / "tmp_gwas_qc"
    ).resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def log_step(message: str, *, error: bool = False) -> None:
    print(f"[gwas-qc] {message}", file=sys.stderr if error else sys.stdout, flush=True)


def _load_canonicalizer():
    script = Path(__file__).resolve().with_name("canonicalize_study.py")
    spec = importlib.util.spec_from_file_location(
        "_mrcat_gwas_qc_canonicalizer",
        script,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load canonicalization component: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _canonical_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "study_raw_path": payload.get("raw_path"),
        "study_label": payload.get("label"),
        "study_sample_size": payload.get("sample_size"),
        "study_source": payload.get("source"),
        "study_study_metadata": payload.get("study_metadata"),
        "study_mapping_notes": payload.get("mapping_notes"),
        "ancestry": payload.get("ancestry"),
        "max_attempts": payload.get("max_attempts"),
        "sample_rows": payload.get("sample_rows"),
        "sample_timeout_seconds": payload.get("sample_timeout_seconds"),
        "full_timeout_seconds": payload.get("full_timeout_seconds"),
    }


_LOCAL_STUDY_FIELDS = (
    "raw_path",
    "label",
    "sample_size",
    "source",
    "study_metadata",
    "mapping_notes",
    "ancestry",
)


def _normalize_study_input(
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    normalized = dict(payload)
    downloaded_study = normalized.pop("downloaded_study", None)
    if downloaded_study:
        if not isinstance(downloaded_study, dict):
            return None, "downloaded_study must be an object."
        for field_name in _LOCAL_STUDY_FIELDS:
            normalized.pop(field_name, None)
            if field_name in downloaded_study:
                normalized[field_name] = downloaded_study[field_name]
    if not compact_text(normalized.get("raw_path")):
        return (
            None,
            "Provide downloaded_study from gwas-download or a local raw_path.",
        )
    study_metadata = normalized.get("study_metadata")
    if study_metadata is not None and not isinstance(study_metadata, dict):
        return None, "study_metadata must be an object."
    return normalized, None


def _blocked(
    message: str,
    *,
    failure_class: str,
    diagnostics: dict[str, Any] | None = None,
    missing_requirements: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    outputs: dict[str, Any] = {
        "status": "blocked",
        "failure_class": failure_class,
        "message": message,
    }
    missing = [
        item
        for item in list(missing_requirements or [])
        if isinstance(item, dict)
    ]
    if missing:
        outputs["missing_requirements"] = missing
        outputs["primary_missing_requirement"] = (
            missing[0].get("failure_class") or failure_class
        )
    return {
        "summary": f"gwas-qc blocked: {message}",
        "outputs": outputs,
        "details": {
            "result_status": "blocked",
            "failure_class": failure_class,
            "diagnostics": dict(diagnostics or {}),
            "missing_requirements": missing,
            "primary_missing_requirement": outputs.get(
                "primary_missing_requirement"
            ),
        },
        "artifacts": list(artifacts or []),
    }


def _write_explanation(
    canonicalizer: Any,
    canonical: dict[str, Any],
) -> tuple[Path, str | None]:
    path = execution_dir() / "reports" / "gwas_qc_explanation.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    warning = None
    try:
        explanation = canonicalizer.generate_explanation_markdown(
            side="study",
            result=canonical,
        )
        if not compact_text(explanation):
            raise RuntimeError("LLM explanation returned empty Markdown")
    except Exception as exc:
        warning = f"LLM explanation failed; deterministic fallback written: {exc}"
        explanation = (
            "# GWAS QC explanation\n\n"
            f"- Input: `{canonical.get('raw_path')}`\n"
            f"- Canonical rows: {int(canonical.get('rows_written') or 0)}\n"
            f"- SNP identifier type: {canonical.get('snp_id_type') or 'unknown'}\n"
            f"- Genome build: {canonical.get('genome_build') or 'unknown'}\n"
            f"- Genome build reason: {canonical.get('genome_build_reason') or 'not recorded'}\n"
            "- The canonical transform passed full-file validation. "
            "See the QC report for mapping and formatting diagnostics.\n"
        )
    path.write_text(str(explanation).rstrip() + "\n", encoding="utf-8")
    return path, warning


def _risk_summary(risk_notes: Any) -> str:
    rendered: list[str] = []
    for raw in list(risk_notes or []):
        if not isinstance(raw, dict):
            continue
        fields = {
            key: compact_text(raw.get(key))
            for key in ("kind", "decision", "basis", "risk")
        }
        if not fields["kind"] or not fields["decision"]:
            continue
        rendered.append(
            "[RISK][SOFT_ASSUMPTION] "
            f"kind={fields['kind']} decision={fields['decision']}; "
            f"basis={fields['basis']}; risk={fields['risk']}"
        )
    return " ".join(rendered)


def _genome_build_summary(canonical: dict[str, Any]) -> str:
    reason = compact_text(canonical.get("genome_build_reason")) or "not recorded"
    return (
        f"genome_build={compact_text(canonical.get('genome_build')) or 'unknown'}, "
        f"genome_build_reason={reason.rstrip('.')}."
    )


def _run_format(
    payload: dict[str, Any],
    *,
    canonical_path: str,
) -> dict[str, Any]:
    out_json = execution_dir() / "reports" / "gwas_qc_format_output.json"
    format_input = {
        "canonical_path": canonical_path,
        "label": payload.get("label"),
        "sample_size": payload.get("sample_size"),
        "ancestry": payload.get("ancestry"),
        "min_freq": payload.get("min_freq"),
        "hm3_path": str(database("hapmap3.snplist_rdata")),
        "mhc_path": str(database("hapmap3.mhc_rdata")),
    }
    input_json = execution_dir() / "gwas_qc_format_input.json"
    input_json.write_text(
        json.dumps(format_input, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    script = Path(__file__).resolve().with_name("format_study.R")
    completed = run_streaming(
        [
            os.environ.get("RSCRIPT_BIN") or "Rscript",
            str(script),
            str(input_json),
            str(out_json),
            str(execution_dir()),
        ],
        on_stdout_line=lambda line: print(line, flush=True),
        on_stderr_line=lambda line: print(line, file=sys.stderr, flush=True),
        cwd=str(script.parent),
    )
    if completed.returncode != 0:
        return _blocked(
            "MRAPSS::format_data failed.",
            failure_class="gwas_qc_format_failed",
            diagnostics={
                "stdout_tail": compact_text(completed.stdout)[-1000:],
                "stderr_tail": compact_text(completed.stderr)[-1000:],
            },
        )
    if not out_json.exists():
        return _blocked(
            "formatter did not write output JSON.",
            failure_class="gwas_qc_format_failed",
        )
    result = json.loads(out_json.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        return _blocked(
            "formatter returned an invalid result.",
            failure_class="gwas_qc_format_failed",
        )
    return result


def run(payload: dict[str, Any]) -> dict[str, Any]:
    payload, input_error = _normalize_study_input(dict(payload or {}))
    if input_error or payload is None:
        return _blocked(
            input_error or "Invalid GWAS QC input.",
            failure_class="invalid_input",
        )
    raw_path = Path(compact_text(payload.get("raw_path"))).expanduser()
    if not raw_path.is_file():
        return _blocked(
            f"raw GWAS file does not exist: {raw_path}",
            failure_class="missing_input",
            diagnostics={"missing_input": "raw_path"},
        )
    canonicalizer = _load_canonicalizer()
    canonicalizer.load_repo_dotenv_if_available()
    previous_internal_id = os.environ.get("MRCAT_INTERNAL_SKILL_ID")
    os.environ["MRCAT_INTERNAL_SKILL_ID"] = "gwas-qc"
    try:
        log_step(f"Canonicalizing one GWAS: {raw_path}")
        canonical = canonicalizer.canonicalize_side(
            "study",
            _canonical_payload(payload),
        )
    except canonicalizer.GwasQcCanonicalizationBlocked as exc:
        return _blocked(
            str(exc),
            failure_class=exc.failure_class,
            diagnostics=exc.details,
            missing_requirements=exc.missing_requirements,
        )
    except Exception as exc:
        return _blocked(
            f"unexpected canonicalization error: {exc}",
            failure_class="gwas_qc_unexpected_error",
            diagnostics={"traceback": traceback.format_exc()},
        )
    finally:
        if previous_internal_id is None:
            os.environ.pop("MRCAT_INTERNAL_SKILL_ID", None)
        else:
            os.environ["MRCAT_INTERNAL_SKILL_ID"] = previous_internal_id

    explanation_path, explanation_warning = _write_explanation(
        canonicalizer,
        canonical,
    )
    log_step("Formatting and filtering the canonical study.")
    formatted = _run_format(
        payload,
        canonical_path=str(canonical["canonical_path"]),
    )
    if (
        str(dict(formatted.get("outputs") or {}).get("status") or "").lower()
        != "ok"
    ):
        artifacts = [
            {
                "path": canonical["canonical_path"],
                "kind": "tsv",
                "summary": "validated canonical GWAS",
            },
            {
                "path": str(explanation_path),
                "kind": "md",
                "summary": "human-readable GWAS QC explanation",
            },
            *[
                dict(item)
                for item in list(formatted.get("artifacts") or [])
                if isinstance(item, dict)
            ],
        ]
        formatted["artifacts"] = artifacts
        build_summary = _genome_build_summary(canonical)
        formatted["summary"] = (
            f"{compact_text(formatted.get('summary'))} {build_summary}"
        ).strip()
        formatted_details = dict(formatted.get("details") or {})
        formatted_details["genome_build"] = canonical["genome_build"]
        formatted_details["genome_build_reason"] = canonical[
            "genome_build_reason"
        ]
        formatted["details"] = formatted_details
        return formatted

    format_result = dict(
        dict(formatted.get("outputs") or {}).get("gwas_qc_format_result")
        or {}
    )
    report = {
        "raw_path": str(raw_path.resolve()),
        "canonical": canonical,
        "format": format_result,
        "warnings": [explanation_warning] if explanation_warning else [],
    }
    report_path = execution_dir() / "reports" / "gwas_qc_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    result = {
        "canonical_path": canonical["canonical_path"],
        "formatted_path": format_result.get("formatted_path"),
        "report_path": str(report_path),
        "explanation_path": str(explanation_path),
        "genome_build": canonical["genome_build"],
        "genome_build_reason": canonical["genome_build_reason"],
    }
    risk_notes = list(canonical.get("risk_notes") or [])
    sample_size = payload.get("sample_size")
    if sample_size is not None:
        sample_size = float(sample_size)
        if math.isfinite(sample_size) and sample_size > 0:
            result["sample_size"] = sample_size
    if risk_notes:
        result["risk_notes"] = risk_notes
    for field_name in ("label", "ancestry"):
        value = compact_text(payload.get(field_name))
        if value:
            result[field_name] = value
    artifacts = [
        {
            "path": canonical["canonical_path"],
            "kind": "tsv",
            "summary": "validated canonical GWAS",
        },
        {
            "path": canonical["generated_code_path"],
            "kind": "py",
            "summary": "validated GWAS canonicalization transform",
        },
        {
            "path": result["formatted_path"],
            "kind": "tsv",
            "summary": "analysis-ready formatted GWAS",
        },
        {
            "path": str(report_path),
            "kind": "json",
            "summary": "GWAS QC report",
        },
        {
            "path": str(explanation_path),
            "kind": "md",
            "summary": "human-readable GWAS QC explanation",
        },
    ]
    log_step(
        "Completed successfully: "
        f"canonical_rows={canonical['rows_written']}; "
        f"formatted_rows={int(format_result.get('n_final') or 0)}; "
        f"genome_build={canonical['genome_build']}; "
        f"genome_build_reason={canonical['genome_build_reason']}"
    )
    risk_summary = _risk_summary(risk_notes)
    summary = (
        "gwas-qc completed: "
        f"canonical_rows={canonical['rows_written']}, "
        f"formatted_rows={int(format_result.get('n_final') or 0)}. "
        f"{_genome_build_summary(canonical)}"
    )
    format_summary = compact_text(formatted.get("summary"))
    if format_summary:
        summary = f"{summary} {format_summary}"
    if risk_summary:
        summary = f"{summary} {risk_summary}"
    return {
        "summary": summary,
        "outputs": {"status": "ok", "gwas_qc_result": result},
        "details": {
            "result_status": "ok",
            "failure_class": None,
            "risk_notes": risk_notes,
        },
        "artifacts": artifacts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert one raw GWAS into one analysis-ready formatted study."
    )
    parser.add_argument("--input-json")
    args = parser.parse_args()
    with redirect_stdout(sys.stderr):
        result = run(load_json_arg(args.input_json))
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
