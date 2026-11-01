from __future__ import annotations

import csv
from contextlib import ExitStack
import gzip
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


CANONICAL_COLUMNS = [
    "SNP",
    "CHR",
    "BP",
    "effect_allele",
    "other_allele",
    "beta",
    "or",
    "se",
    "z",
    "pval",
    "neglog10_pval",
    "freq_qc",
    "info",
    "n",
    "n_cases",
    "n_controls",
]

CODEGEN_PROMPT_FILES = {
    "system": "canonicalize_code.codegen.system.md",
    "contract": "canonicalize_code.codegen.contract.md",
}
GENOME_BUILD_PROMPT_FILE = "genome_build.system.md"
GENOME_BUILD_MAX_OUTPUT_TOKENS = 8192
EXPLANATION_PROMPT_FILE = "canonicalize_code.explain.system.md"
SAMPLE_PREVIEW_ROWS = 10
GENOME_BUILD_COORDINATE_ROWS = 1000
_RSID_RE = re.compile(r"^rs\d+$", re.IGNORECASE)
_VALID_BASES = {"A", "C", "G", "T"}


class GwasQcCanonicalizationBlocked(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failure_class: str = "gwas_qc_canonicalization_blocked",
        details: dict[str, Any] | None = None,
        missing_requirements: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.details = dict(details or {})
        self.missing_requirements = list(missing_requirements or [])


@dataclass
class Preview:
    side: str
    path: Path
    physical_format: str
    header_fields: list[str]
    sample_rows: list[dict[str, str]]
    sample_raw_lines: list[str]
    header_line: str
    delimiter: str
    vcf_metadata: list[str] = field(default_factory=list)
    vcf_format_fields: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    rows_written: int
    snp_counts: dict[str, int]
    sample_rows: list[dict[str, str]]
    warnings: list[str] = field(default_factory=list)

    @property
    def rsid_available(self) -> bool:
        return int(self.snp_counts.get("rsid") or 0) > 0


def needs_hm3_mapping(validation: ValidationResult) -> bool:
    return any(int(validation.snp_counts.get(kind) or 0) > 0 for kind in ("missing", "coordinate", "other"))


def compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def side_pan_ukb_scope(payload: dict[str, Any], side: str) -> str | None:
    metadata = payload.get(f"{side}_study_metadata")
    if not isinstance(metadata, dict):
        return None
    scope = compact_text(metadata.get("pan_ukb_scope")).upper()
    return scope or None


def log_step(message: str, *, error: bool = False) -> None:
    skill_id = compact_text(
        os.getenv("MRCAT_INTERNAL_SKILL_ID")
    ) or "gwas-qc"
    print(f"[{skill_id}] {message}", file=sys.stderr if error else sys.stdout, flush=True)


def load_repo_dotenv_if_available() -> None:
    try:
        from mrcat.config.env import load_repo_dotenv
    except Exception:
        return
    workspace = compact_text(os.getenv("MRCAT_WORKSPACE_DIR"))
    candidates = [Path(workspace).expanduser().resolve()] if workspace else []
    candidates.append(Path(__file__).resolve().parents[3])
    for candidate in candidates:
        try:
            load_repo_dotenv(repo_root=candidate)
            return
        except Exception:
            continue


def execution_dir() -> Path:
    target = Path(os.getenv("MRCAT_EXECUTION_DIR") or Path.cwd() / "tmp_gwas_qc").resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def output_dir() -> Path:
    target = execution_dir() / "canonical"
    target.mkdir(parents=True, exist_ok=True)
    return target


def code_dir() -> Path:
    target = execution_dir() / "generated_code"
    target.mkdir(parents=True, exist_ok=True)
    return target


def samples_dir() -> Path:
    target = execution_dir() / "samples"
    target.mkdir(parents=True, exist_ok=True)
    return target


def is_gzip_path(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"\x1f\x8b"
    except OSError:
        return path.suffix.lower() == ".gz"


def open_text_auto(path: Path):
    if is_gzip_path(path):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="")
    return path.open("r", encoding="utf-8", errors="replace", newline="")


def write_text_auto(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "wt", encoding="utf-8", newline="")
    return path.open("w", encoding="utf-8", newline="")


def split_line(line: str, delimiter: str) -> list[str]:
    text = line.rstrip("\n\r")
    if delimiter == "\t":
        return text.split("\t")
    if delimiter == ",":
        return next(csv.reader([text]))
    return text.split()


def infer_delimiter(line: str) -> str:
    if "\t" in line:
        return "\t"
    if "," in line and line.count(",") >= max(1, line.count(" ")):
        return ","
    return "whitespace"


def looks_like_vcf(path: Path, first_lines: list[str]) -> bool:
    lower_name = path.name.lower()
    if lower_name.endswith(".vcf") or lower_name.endswith(".vcf.gz"):
        return True
    return any(line.startswith("##fileformat=VCF") or line.startswith("#CHROM") for line in first_lines)


def preview_raw_file(side: str, path_text: str, *, sample_limit: int) -> Preview:
    path = Path(compact_text(path_text)).expanduser().resolve()
    if not path.exists():
        raise GwasQcCanonicalizationBlocked(
            f"{side} raw GWAS file does not exist: {path}",
            failure_class="missing_input",
            details={"side": side, "path": str(path)},
        )
    first_lines: list[str] = []
    with open_text_auto(path) as handle:
        for line in handle:
            if line.strip():
                first_lines.append(line.rstrip("\n"))
            if len(first_lines) >= 50:
                break
    if looks_like_vcf(path, first_lines):
        return preview_vcf(side, path, sample_limit=sample_limit)
    return preview_table(side, path, sample_limit=sample_limit)


def preview_table(side: str, path: Path, *, sample_limit: int) -> Preview:
    with open_text_auto(path) as handle:
        header_line = ""
        for line in handle:
            if line.strip():
                header_line = line.rstrip("\n\r")
                break
        if not header_line:
            raise GwasQcCanonicalizationBlocked(
                f"{side} raw GWAS file has no readable header.",
                failure_class="unsupported_file_format",
                details={"side": side, "path": str(path)},
            )
        delimiter = infer_delimiter(header_line)
        fields = split_line(header_line, delimiter)
        sample_rows: list[dict[str, str]] = []
        sample_raw_lines: list[str] = []
        for line in handle:
            if not line.strip():
                continue
            raw = line.rstrip("\n\r")
            values = split_line(raw, delimiter)
            sample_rows.append({field: values[index] if index < len(values) else "" for index, field in enumerate(fields)})
            sample_raw_lines.append(raw)
            if len(sample_rows) >= sample_limit:
                break
    return Preview(
        side=side,
        path=path,
        physical_format="table",
        header_fields=fields,
        sample_rows=sample_rows,
        sample_raw_lines=sample_raw_lines,
        header_line=header_line,
        delimiter=delimiter,
    )


def vcf_format_ids(metadata: list[str]) -> list[str]:
    ids: list[str] = []
    for line in metadata:
        match = re.match(r"##FORMAT=<ID=([^,>]+)", line)
        if match:
            ids.append(match.group(1))
    return ids


def preview_vcf(side: str, path: Path, *, sample_limit: int) -> Preview:
    metadata: list[str] = []
    header_line = ""
    fields: list[str] = []
    sample_rows: list[dict[str, str]] = []
    sample_raw_lines: list[str] = []
    with open_text_auto(path) as handle:
        for line in handle:
            raw = line.rstrip("\n\r")
            if raw.startswith("##"):
                if len(metadata) < 100:
                    metadata.append(raw)
                continue
            if raw.startswith("#CHROM"):
                header_line = raw
                fields = raw.lstrip("#").split("\t")
                break
        if not header_line:
            raise GwasQcCanonicalizationBlocked(
                f"{side} VCF header #CHROM was not found.",
                failure_class="unsupported_file_format",
                details={"side": side, "path": str(path)},
            )
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            raw = line.rstrip("\n\r")
            values = raw.split("\t")
            row = {field: values[index] if index < len(values) else "" for index, field in enumerate(fields)}
            fmt = row.get("FORMAT") or ""
            sample_col = fields[-1] if len(fields) > 9 else ""
            sample_value = row.get(sample_col) if sample_col else ""
            keys = fmt.split(":") if fmt else []
            vals = str(sample_value or "").split(":") if sample_value else []
            for index, key in enumerate(keys):
                if key:
                    row[f"FORMAT.{key}"] = vals[index] if index < len(vals) else ""
            sample_rows.append(row)
            sample_raw_lines.append(raw)
            if len(sample_rows) >= sample_limit:
                break
    format_fields = sorted(set(vcf_format_ids(metadata)) | {field[7:] for row in sample_rows for field in row if field.startswith("FORMAT.")})
    return Preview(
        side=side,
        path=path,
        physical_format="vcf",
        header_fields=fields,
        sample_rows=sample_rows,
        sample_raw_lines=sample_raw_lines,
        header_line=header_line,
        delimiter="\t",
        vcf_metadata=metadata,
        vcf_format_fields=format_fields,
    )


def write_sample_input(preview: Preview) -> Path:
    suffix = ".vcf.gz" if preview.physical_format == "vcf" and is_gzip_path(preview.path) else ".txt.gz" if is_gzip_path(preview.path) else ".txt"
    sample_path = samples_dir() / f"{preview.side}.sample{suffix}"
    with write_text_auto(sample_path) as handle:
        if preview.physical_format == "vcf":
            for line in preview.vcf_metadata:
                handle.write(f"{line}\n")
            handle.write(f"{preview.header_line}\n")
            for line in preview.sample_raw_lines:
                handle.write(f"{line}\n")
        else:
            handle.write(f"{preview.header_line}\n")
            for line in preview.sample_raw_lines:
                handle.write(f"{line}\n")
    return sample_path


def prompt_dir_candidates() -> list[Path]:
    candidates: list[Path] = []
    workspace = compact_text(os.getenv("MRCAT_WORKSPACE_DIR"))
    if workspace:
        candidates.append(Path(workspace).expanduser().resolve() / "mrcat" / "prompts")
    candidates.append(Path(__file__).resolve().parents[3] / "mrcat" / "prompts")
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return deduped


def load_prompt_file(filename: str) -> tuple[str, str]:
    searched: list[str] = []
    for prompt_dir in prompt_dir_candidates():
        path = prompt_dir / filename
        searched.append(str(path))
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                raise GwasQcCanonicalizationBlocked(
                    f"Prompt file is empty: {path}",
                    failure_class="codegen_prompt_missing",
                    details={"prompt_file": filename, "path": str(path)},
                )
            return text, str(path)
    raise GwasQcCanonicalizationBlocked(
        f"Prompt file was not found: {filename}",
        failure_class="codegen_prompt_missing",
        details={"prompt_file": filename, "searched": searched},
    )


def prompt_files() -> tuple[dict[str, str], dict[str, str]]:
    system, system_path = load_prompt_file(CODEGEN_PROMPT_FILES["system"])
    contract, contract_path = load_prompt_file(CODEGEN_PROMPT_FILES["contract"])
    return {"system": system, "contract": contract}, {"system": system_path, "contract": contract_path}


def codegen_example() -> dict[str, Any]:
    return {
        "status": "ok",
        "code": "def transform(input_path, output_path, context):\n    raise RuntimeError('example only')\n",
        "reason": "example shape only",
        "assumptions": [],
    }


def normalize_codegen_assumptions(value: Any) -> list[dict[str, str]]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ValueError("codegen response.assumptions must be a list")
    normalized: list[dict[str, str]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError(f"codegen response.assumptions[{index}] must be an object")
        assumption = {
            key: compact_text(raw.get(key))
            for key in ("kind", "decision", "basis", "risk")
        }
        missing = [key for key, item in assumption.items() if not item]
        if missing:
            raise ValueError(
                f"codegen response.assumptions[{index}] is missing: {', '.join(missing)}"
            )
        normalized.append(assumption)
    return normalized


def normalize_codegen_response(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("codegen response must be a JSON object")
    status = compact_text(payload.get("status")).lower()
    if status not in {"ok", "blocked"}:
        raise ValueError("codegen response.status must be ok or blocked")
    if status == "blocked":
        reason = compact_text(payload.get("reason"))
        failure_class = (
            compact_text(payload.get("failure_class"))
            or "gwas_qc_codegen_blocked"
        )
        missing = payload.get("missing_requirements")
        if not isinstance(missing, list):
            missing = []
        if not reason:
            raise ValueError("blocked codegen response must include reason")
        return {
            "status": "blocked",
            "failure_class": failure_class,
            "missing_requirements": [item for item in missing if isinstance(item, dict)],
            "reason": reason,
        }
    code = payload.get("code")
    if not isinstance(code, str) or "def transform(" not in code:
        raise ValueError("ok codegen response must include Python code defining transform(input_path, output_path, context)")
    return {
        "status": "ok",
        "code": code,
        "reason": compact_text(payload.get("reason")) or None,
        "assumptions": normalize_codegen_assumptions(payload.get("assumptions")),
    }


def build_codegen_user_prompt(
    *,
    contract_prompt: str,
    side: str,
    preview: Preview,
    payload: dict[str, Any],
    previous_error: dict[str, Any] | None,
) -> str:
    mapping_notes = compact_text(payload.get(f"{side}_mapping_notes"))
    scope_hint = side_pan_ukb_scope(payload, side)
    sample_size_value = side_sample_size(payload, side) or payload.get(f"{side}_sample_size")
    study_metadata = payload.get(f"{side}_study_metadata")
    if not isinstance(study_metadata, dict):
        study_metadata = None
    prompt_payload = {
        "side": side,
        "file_name": preview.path.name,
        "physical_format": preview.physical_format,
        "study_metadata": study_metadata,
        "mapping_notes": mapping_notes or None,
        "trait_label": compact_text(payload.get(f"{side}_label")) or side,
        "source": compact_text(payload.get(f"{side}_source")) or None,
        "ancestry": compact_text(payload.get("ancestry")) or None,
        "pan_ukb_scope": scope_hint,
        "sample_size": sample_size_value,
        "input_delimiter": preview.delimiter,
        "header_fields": preview.header_fields,
        "sample_rows": preview.sample_rows,
        "vcf_metadata": preview.vcf_metadata,
        "vcf_format_fields": preview.vcf_format_fields,
        "required_canonical_columns": CANONICAL_COLUMNS,
        "previous_error": previous_error,
    }
    return (
        f"{contract_prompt}\n\n"
        "Generate the canonicalization code for this GWAS side from this JSON context:\n"
        f"{json.dumps(prompt_payload, ensure_ascii=False, indent=2, default=str)}"
    )


def call_codegen_llm(
    *,
    side: str,
    preview: Preview,
    payload: dict[str, Any],
    previous_error: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    try:
        from mrcat.config.llm_limits import (
            LLM_MAX_OUTPUT_TOKENS,
            LLM_TIMEOUT_SECONDS,
        )
        from mrcat.model import llm_gateway
    except Exception as exc:
        raise GwasQcCanonicalizationBlocked(
            f"LLM code generation is unavailable: {exc}",
            failure_class="codegen_llm_unavailable",
            details={"side": side, "error": str(exc)},
        ) from exc
    prompts, paths = prompt_files()
    if not llm_gateway.has_api_key():
        raise GwasQcCanonicalizationBlocked(
            "LLM code generation is unavailable because no configured LLM API key is set.",
            failure_class="codegen_llm_unavailable",
            details={"side": side, "prompt_files": paths},
        )
    user_prompt = build_codegen_user_prompt(
        contract_prompt=prompts["contract"],
        side=side,
        preview=preview,
        payload=payload,
        previous_error=previous_error,
    )
    try:
        response = llm_gateway.call_validated_json(
            system=prompts["system"],
            user=user_prompt,
            example=codegen_example(),
            validator=normalize_codegen_response,
            temperature=0.0,
            max_tokens=LLM_MAX_OUTPUT_TOKENS,
            timeout=LLM_TIMEOUT_SECONDS,
            compact=False,
            trace_context={
                "skill_id": compact_text(
                    os.getenv("MRCAT_INTERNAL_SKILL_ID")
                )
                or "gwas-qc",
                "side": side,
                "stage": "codegen",
            },
        )
    except Exception as exc:
        raise GwasQcCanonicalizationBlocked(
            f"LLM code generation failed for {side}: {exc}",
            failure_class="codegen_llm_failed",
            details={"side": side, "error": str(exc), "prompt_files": paths},
        ) from exc
    return dict(response), paths, {"system": prompts["system"], "user": user_prompt}


def normalize_genome_build_response(payload: dict[str, Any]) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("genome build response must be a JSON object")
    unexpected = set(payload) - {"genome_build", "reason"}
    if unexpected:
        raise ValueError(
            "genome build response contains unexpected fields: "
            + ", ".join(sorted(unexpected))
        )
    genome_build = compact_text(payload.get("genome_build")).lower()
    if genome_build not in {"grch37", "grch38", "unknown"}:
        raise ValueError(
            "genome build response.genome_build must be grch37, grch38, or unknown"
        )
    reason = compact_text(payload.get("reason"))
    if not reason:
        raise ValueError("genome build response.reason must be non-empty")
    return {"genome_build": genome_build, "reason": reason}


def build_genome_build_user_prompt(
    *,
    side: str,
    preview: Preview,
    payload: dict[str, Any],
    coordinate_check: dict[str, int] | None,
) -> str:
    study_metadata = payload.get(f"{side}_study_metadata")
    if not isinstance(study_metadata, dict):
        study_metadata = None
    evidence = {
        "file_name": preview.path.name,
        "physical_format": preview.physical_format,
        "source": compact_text(payload.get(f"{side}_source")) or None,
        "study_metadata": study_metadata,
        "mapping_notes": compact_text(payload.get(f"{side}_mapping_notes")) or None,
        "header_fields": preview.header_fields,
        "sample_rows": preview.sample_rows,
        "vcf_metadata": preview.vcf_metadata,
        "coordinate_check": coordinate_check,
    }
    return (
        "Determine the source genome build using all supplied study evidence.\n\n"
        f"{json.dumps(evidence, ensure_ascii=False, indent=2, default=str)}"
    )


def call_genome_build_llm(
    *,
    side: str,
    preview: Preview,
    payload: dict[str, Any],
    coordinate_check: dict[str, int] | None,
) -> dict[str, str]:
    try:
        from mrcat.config.llm_limits import LLM_TIMEOUT_SECONDS
        from mrcat.model import llm_gateway
    except Exception as exc:
        raise GwasQcCanonicalizationBlocked(
            f"Genome build inference is unavailable: {exc}",
            failure_class="genome_build_llm_unavailable",
            details={"side": side, "error": str(exc)},
        ) from exc
    system_prompt, prompt_path = load_prompt_file(GENOME_BUILD_PROMPT_FILE)
    if not llm_gateway.has_api_key():
        raise GwasQcCanonicalizationBlocked(
            "Genome build inference is unavailable because no configured LLM API key is set.",
            failure_class="genome_build_llm_unavailable",
            details={"side": side, "prompt_file": prompt_path},
        )
    user_prompt = build_genome_build_user_prompt(
        side=side,
        preview=preview,
        payload=payload,
        coordinate_check=coordinate_check,
    )
    try:
        response = llm_gateway.call_validated_json(
            system=system_prompt,
            user=user_prompt,
            example={
                "genome_build": "grch38",
                "reason": "The supplied metadata and coordinate check support GRCh38.",
            },
            validator=normalize_genome_build_response,
            temperature=0.0,
            max_tokens=GENOME_BUILD_MAX_OUTPUT_TOKENS,
            timeout=LLM_TIMEOUT_SECONDS,
            compact=True,
            trace_context={
                "skill_id": compact_text(os.getenv("MRCAT_INTERNAL_SKILL_ID"))
                or "gwas-qc",
                "side": side,
                "stage": "genome_build",
            },
        )
    except Exception as exc:
        raise GwasQcCanonicalizationBlocked(
            f"Genome build inference failed for {side}: {exc}",
            failure_class="genome_build_llm_failed",
            details={
                "side": side,
                "error": str(exc),
                "prompt_file": prompt_path,
                "coordinate_check": coordinate_check,
            },
        ) from exc
    return dict(response)


def write_generated_code(side: str, attempt: int, code: str) -> Path:
    path = code_dir() / f"{side}_attempt_{attempt}.py"
    path.write_text(code, encoding="utf-8")
    return path


def write_codegen_prompt(side: str, attempt: int, prompt: dict[str, str]) -> Path:
    path = code_dir() / f"{side}_attempt_{attempt}.prompt.txt"
    path.write_text(
        f"=== SYSTEM PROMPT ===\n{str(prompt.get('system') or '').strip()}\n\n"
        f"=== USER PROMPT ===\n{str(prompt.get('user') or '').strip()}\n",
        encoding="utf-8",
    )
    return path


def write_context(side: str, preview: Preview, payload: dict[str, Any], *, sample_mode: bool) -> Path:
    context = {
        "side": side,
        "sample_mode": sample_mode,
        "canonical_columns": CANONICAL_COLUMNS,
        "physical_format": preview.physical_format,
        "header_fields": preview.header_fields,
        "vcf_format_fields": preview.vcf_format_fields,
        "mapping_notes": compact_text(payload.get(f"{side}_mapping_notes")) or None,
        "study_metadata": payload.get(f"{side}_study_metadata") if isinstance(payload.get(f"{side}_study_metadata"), dict) else None,
        "trait_label": compact_text(payload.get(f"{side}_label")) or side,
        "source": compact_text(payload.get(f"{side}_source")) or None,
        "ancestry": compact_text(payload.get("ancestry")) or None,
        "pan_ukb_scope": side_pan_ukb_scope(payload, side),
        "sample_size": side_sample_size(payload, side) or payload.get(f"{side}_sample_size"),
    }
    path = code_dir() / f"{side}_{'sample' if sample_mode else 'full'}_context.json"
    path.write_text(json.dumps(context, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def _explanation_side_evidence(side: str, result: dict[str, Any]) -> dict[str, Any]:
    code_path = Path(str(result["generated_code_path"]))
    prompt_path = code_path.with_suffix(".prompt.txt")
    attempts = []
    for attempt in list(result.get("attempts") or []):
        if not isinstance(attempt, dict):
            continue
        attempts.append(
            {
                key: attempt.get(key)
                for key in (
                    "attempt",
                    "status",
                    "mapping_reason",
                    "assumptions",
                    "failure_class",
                    "exit_code",
                    "stdout_tail",
                    "stderr_tail",
                    "validation_details",
                )
                if attempt.get(key) not in (None, "", [], {})
            }
        )
    return {
        "side": side,
        "execution_summary": {
            key: result.get(key)
            for key in (
                "trait",
                "raw_path",
                "canonical_path",
                "rows_read",
                "rows_written",
                "source",
                "sample_size",
                "mapping_reason",
                "genome_build",
                "genome_build_reason",
                "risk_notes",
                "format",
                "coordinate_rsid_mapping",
                "validation_warnings",
                "snp_id_counts",
                "snp_id_type",
                "full_execution",
            )
        },
        "codegen_attempts": attempts,
        "final_generated_code": code_path.read_text(encoding="utf-8"),
        "final_codegen_prompt": prompt_path.read_text(encoding="utf-8"),
    }


def build_explanation_user_prompt(*, side: str, result: dict[str, Any]) -> str:
    evidence = _explanation_side_evidence(side, result)
    return (
        "Explain the completed canonicalization using only this execution evidence.\n\n"
        f"{json.dumps(evidence, ensure_ascii=False, indent=2, default=str)}"
    )


def generate_explanation_markdown(*, side: str, result: dict[str, Any]) -> str:
    try:
        from mrcat.config.llm_limits import (
            LLM_MAX_OUTPUT_TOKENS,
            LLM_TIMEOUT_SECONDS,
        )
        from mrcat.model import llm_gateway
    except Exception as exc:
        raise RuntimeError(f"LLM explanation is unavailable: {exc}") from exc
    if not llm_gateway.has_api_key():
        raise RuntimeError("LLM explanation is unavailable because no configured LLM API key is set.")
    system_prompt, _ = load_prompt_file(EXPLANATION_PROMPT_FILE)
    return llm_gateway.call_text(
        system=system_prompt,
        user=build_explanation_user_prompt(side=side, result=result),
        temperature=0.0,
        max_tokens=LLM_MAX_OUTPUT_TOKENS,
        timeout=LLM_TIMEOUT_SECONDS,
    ).strip()


def harness_path() -> Path:
    path = code_dir() / "run_generated_transform.py"
    if path.exists():
        return path
    path.write_text(
        """
from __future__ import annotations
import importlib.util
import json
import sys
from pathlib import Path

code_path = Path(sys.argv[1]).resolve()
input_path = sys.argv[2]
output_path = sys.argv[3]
context = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("gwas_qc_generated_transform", code_path)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)
transform = getattr(module, "transform")
result = transform(input_path, output_path, context)
print(json.dumps({"result": result}, ensure_ascii=False, default=str))
""".lstrip(),
        encoding="utf-8",
    )
    return path


def run_generated_transform(
    *,
    code_path: Path,
    input_path: Path,
    output_path: Path,
    context_path: Path,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(harness_path()), str(code_path), str(input_path), str(output_path), str(context_path)]
    try:
        return subprocess.run(
            command,
            cwd=str(Path.cwd()),
            text=True,
            capture_output=True,
            timeout=max(1, int(timeout_seconds or 1)),
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=str(exc.output or ""),
            stderr=f"timeout after {timeout_seconds} seconds\n{exc.stderr or ''}",
        )


def snp_value_type(value: Any) -> str:
    text = compact_text(value)
    if not text:
        return "missing"
    if _RSID_RE.match(text):
        return "rsid"
    if ":" in text:
        return "coordinate"
    return "other"


def is_valid_allele(value: Any) -> bool:
    text = compact_text(value).upper()
    return bool(text) and all(base in _VALID_BASES for base in text)


def numeric_values(rows: list[dict[str, str]], column: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        text = compact_text(row.get(column))
        if not text:
            continue
        try:
            value = float(text)
        except ValueError:
            continue
        if math.isfinite(value):
            values.append(value)
    return values


def canonical_reader(path: Path):
    handle = open_text_auto(path)
    return handle, csv.DictReader(handle, delimiter="\t")


def has_neale_signature(preview: Preview) -> bool:
    required = {"variant", "minor_allele", "minor_AF", "n_complete_samples",
                "AC", "ytx", "beta", "se", "tstat", "pval"}
    return (required.issubset(preview.header_fields)
            and "effect_allele" not in preview.header_fields
            and preview.physical_format != "vcf")


def validate_neale_mapping(raw: dict, canonical: dict, row_number: int) -> None:
    """Check the documented complete source signature, not a minor-allele guess."""
    parts = str(raw.get("variant", "")).split(":")
    if len(parts) != 4:
        raise GwasQcCanonicalizationBlocked(
            "Neale-format variant must contain CHR:BP:REF:ALT.",
            failure_class="source_mapping_conflict", details={"row": row_number})
    chrom, pos, ref, alt = parts
    if not (is_valid_allele(ref) and is_valid_allele(alt)):
        return  # Symbolic alleles retain the existing exclusion contract.
    errors = []
    if (canonical.get("effect_allele", "").upper(), canonical.get("other_allele", "").upper()) != (alt.upper(), ref.upper()):
        errors.append("effect_allele must be ALT and other_allele must be REF; minor_allele does not define beta direction")
    if str(canonical.get("CHR", "")).removeprefix("chr") != chrom.removeprefix("chr") or str(canonical.get("BP", "")) != pos:
        errors.append("CHR/BP must preserve the source variant and row order")
    for field in ("beta", "se"):
        try:
            original = float(raw.get(field, ""))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(original):
            continue
        try:
            preserved = math.isclose(float(canonical.get(field, "")), original, rel_tol=1e-10, abs_tol=0)
        except (TypeError, ValueError):
            preserved = False
        if not preserved:
            errors.append(f"{field} must preserve its signed source value without flipping")
    if errors:
        raise GwasQcCanonicalizationBlocked(
            "Canonical mapping contradicts the complete Neale source signature.",
            failure_class="source_mapping_conflict",
            details={"row": row_number, "variant": raw.get("variant"), "validation_errors": errors})


def validate_canonical_output(
    *,
    side: str,
    output_path: Path,
    expected_rows: int,
    sample_only: bool,
    strict_rsid: bool,
    side_sample_size: Any,
    source_preview: Preview | None = None,
    source_input: Path | None = None,
) -> ValidationResult:
    if not output_path.exists():
        raise GwasQcCanonicalizationBlocked(
            f"{side} generated code did not create output file: {output_path}",
            failure_class="codegen_output_missing",
            details={"side": side, "output_path": str(output_path)},
        )
    sample_rows: list[dict[str, str]] = []
    snp_counts = {"rsid": 0, "coordinate": 0, "other": 0, "missing": 0}
    rows_written = 0
    with ExitStack() as stack:
        handle = stack.enter_context(open_text_auto(output_path))
        source_reader = None
        if source_preview is not None and has_neale_signature(source_preview):
            raw_handle = stack.enter_context(open_text_auto(source_input or source_preview.path))
            source_reader = csv.DictReader(raw_handle, delimiter=source_preview.delimiter)
        reader = csv.DictReader(handle, delimiter="\t")
        header = list(reader.fieldnames or [])
        missing_columns = [column for column in CANONICAL_COLUMNS if column not in header]
        if missing_columns:
            raise GwasQcCanonicalizationBlocked(
                f"{side} generated canonical output is missing columns: {', '.join(missing_columns)}",
                failure_class="canonical_columns_missing",
                details={"side": side, "missing_columns": missing_columns, "header": header},
            )
        for row in reader:
            rows_written += 1
            if source_reader is not None:
                raw_row = next(source_reader, None)
                if raw_row is None:
                    raise GwasQcCanonicalizationBlocked("Canonical output has extra rows.", failure_class="row_count_mismatch")
                validate_neale_mapping(raw_row, row, rows_written)
            kind = snp_value_type(row.get("SNP"))
            snp_counts[kind] = snp_counts.get(kind, 0) + 1
            if len(sample_rows) < SAMPLE_PREVIEW_ROWS:
                sample_rows.append({column: compact_text(row.get(column)) for column in CANONICAL_COLUMNS})
    if rows_written != expected_rows:
        raise GwasQcCanonicalizationBlocked(
            f"{side} generated canonical output changed row count: input_rows={expected_rows}, output_rows={rows_written}",
            failure_class="row_count_mismatch",
            details={"side": side, "input_rows": expected_rows, "output_rows": rows_written},
        )
    validation_errors: list[str] = []
    if rows_written <= 0:
        validation_errors.append("output has no rows")
    has_coordinate_identity = any(compact_text(row.get("CHR")) and compact_text(row.get("BP")) for row in sample_rows)
    if strict_rsid and snp_counts.get("rsid", 0) <= 0:
        validation_errors.append("SNP has no rsid-like values after rsID mapping")
    elif not strict_rsid and snp_counts.get("rsid", 0) <= 0 and not has_coordinate_identity:
        validation_errors.append("SNP is not rsid-like and CHR/BP are not available for HM3 lookup")
    for allele_field in ("effect_allele", "other_allele"):
        nonempty = [row.get(allele_field) for row in sample_rows if compact_text(row.get(allele_field))]
        if not nonempty or sum(1 for value in nonempty if is_valid_allele(value)) / max(len(nonempty), 1) < 0.8:
            validation_errors.append(
                f"{allele_field} is missing or is not a valid A/C/G/T allele sequence"
            )
    if not any(any(compact_text(row.get(field)) for row in sample_rows) for field in ("beta", "or", "z")):
        validation_errors.append("missing signed statistic: beta, or, or z")
    if not any(any(compact_text(row.get(field)) for row in sample_rows) for field in ("se", "pval", "neglog10_pval", "z")):
        validation_errors.append("missing uncertainty/significance field: se, pval, neglog10_pval, or z")
    side_n = positive_int_or_none(side_sample_size)
    has_n = any(compact_text(row.get("n")) for row in sample_rows)
    has_case_control = any(compact_text(row.get("n_cases")) for row in sample_rows) and any(compact_text(row.get("n_controls")) for row in sample_rows)
    if side_n is None and not has_n and not has_case_control:
        validation_errors.append("missing sample size: n, n_cases/n_controls, or side-level sample size")
    p_values = numeric_values(sample_rows, "pval")
    if p_values and sum(1 for value in p_values if 0 <= value <= 1) / max(len(p_values), 1) < 0.9:
        validation_errors.append("pval values are not ordinary p-values in [0, 1]")
    neglog_values = numeric_values(sample_rows, "neglog10_pval")
    if neglog_values and sum(1 for value in neglog_values if value >= 0) / max(len(neglog_values), 1) < 0.9:
        validation_errors.append("neglog10_pval values are not non-negative")
    if validation_errors:
        raise GwasQcCanonicalizationBlocked(
            f"{side} generated canonical output failed validation.",
            failure_class="canonical_output_validation_failed",
            details={
                "side": side,
                "validation_errors": validation_errors,
                "sample_only": sample_only,
                "snp_counts": snp_counts,
                "sample_rows": sample_rows,
            },
            missing_requirements=[{"field": "canonical_output", "message": item} for item in validation_errors],
        )
    return ValidationResult(rows_written=rows_written, snp_counts=snp_counts, sample_rows=sample_rows)


def positive_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = compact_text(value)
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if parsed > 0 and parsed.is_integer():
        return int(parsed)
    return None


def positive_int_from_text(value: Any) -> int | None:
    if value in (None, ""):
        return None
    matches = re.findall(r"\d[\d,]*", str(value))
    if not matches:
        return None
    total = sum(int(token.replace(",", "")) for token in matches)
    return total or None


def side_sample_size(payload: dict[str, Any], side: str) -> int | None:
    direct = positive_int_or_none(payload.get(f"{side}_sample_size"))
    if direct is not None:
        return direct
    metadata = payload.get(f"{side}_study_metadata")
    if isinstance(metadata, dict):
        scope = side_pan_ukb_scope(payload, side)
        if scope:
            for key in (
                f"sample_size_{scope}",
                f"n_{scope}",
                f"total_n_{scope}",
                f"n_total_{scope}",
                f"num_samples_{scope}",
            ):
                parsed = positive_int_or_none(metadata.get(key))
                if parsed is not None:
                    return parsed
            n_cases = positive_int_or_none(metadata.get(f"n_cases_{scope}"))
            n_controls = positive_int_or_none(
                metadata.get(f"n_controls_{scope}")
            )
            if n_cases is not None and n_controls is not None:
                return n_cases + n_controls
            trait_type = compact_text(metadata.get("trait_type")).lower()
            if n_cases is not None and trait_type in {
                "continuous",
                "biomarkers",
            }:
                return n_cases
        for key in ("sample_size", "n", "total_n", "initialSampleSize", "initial_sample_size"):
            if key in {"initialSampleSize", "initial_sample_size"}:
                parsed = positive_int_from_text(metadata.get(key))
            else:
                parsed = positive_int_or_none(metadata.get(key))
            if parsed is not None:
                return parsed
        n_cases = positive_int_or_none(metadata.get("n_cases"))
        n_controls = positive_int_or_none(metadata.get("n_controls"))
        if n_cases is not None and n_controls is not None:
            return n_cases + n_controls
    return None


def count_input_rows(preview: Preview) -> int:
    count = 0
    with open_text_auto(preview.path) as handle:
        if preview.physical_format == "vcf":
            for line in handle:
                if line.strip() and not line.startswith("#"):
                    count += 1
            return count
        header_seen = False
        for line in handle:
            if not line.strip():
                continue
            if not header_seen:
                header_seen = True
                continue
            count += 1
    return count


def canonical_temp_path(path: Path, suffix: str) -> Path:
    return path.with_name(f"{path.stem}.{suffix}.tmp{''.join(path.suffixes[-1:]) or '.tsv'}")


def _load_hm3_mapping_helpers(side: str):
    helper_dir = str(Path(__file__).resolve().parent)
    added_to_path = helper_dir not in sys.path
    if added_to_path:
        sys.path.insert(0, helper_dir)
    try:
        from hm3_rsid_map import (
            count_bim_coordinate_matches,
            load_hm3_coord_to_rsid_map,
            lookup_hm3_rsid,
        )
    except Exception as exc:
        raise GwasQcCanonicalizationBlocked(
            f"{side} HM3 rsID mapping helpers could not be loaded: {exc}",
            failure_class="coordinate_rsid_mapping_failed",
            details={"side": side, "error": str(exc)},
        ) from exc
    finally:
        if added_to_path:
            sys.path.remove(helper_dir)
    return (
        load_hm3_coord_to_rsid_map,
        lookup_hm3_rsid,
        count_bim_coordinate_matches,
    )


def check_genome_build_coordinates(
    side: str,
    path: Path,
    *,
    max_rows: int = GENOME_BUILD_COORDINATE_ROWS,
) -> dict[str, int]:
    _, _, count_matches = _load_hm3_mapping_helpers(side)
    coordinates: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    with open_text_auto(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            chrom = compact_text(row.get("CHR"))
            pos = compact_text(row.get("BP"))
            allele1 = compact_text(row.get("effect_allele")).upper()
            allele2 = compact_text(row.get("other_allele")).upper()
            coordinate = (chrom, pos, allele1, allele2)
            if (
                not chrom
                or not pos
                or len(allele1) != 1
                or len(allele2) != 1
                or allele1 not in _VALID_BASES
                or allele2 not in _VALID_BASES
                or allele1 == allele2
                or coordinate in seen
            ):
                continue
            seen.add(coordinate)
            coordinates.append(coordinate)
            if len(coordinates) >= max(1, int(max_rows)):
                break
    try:
        matches = {
            build: count_matches(coordinates, build)
            for build in ("grch37", "grch38")
        }
    except Exception as exc:
        raise GwasQcCanonicalizationBlocked(
            f"{side} genome build reference check could not be loaded: {exc}",
            failure_class=getattr(
                exc,
                "failure_class",
                "coordinate_rsid_reference_missing",
            ),
            details={
                "side": side,
                "error": str(exc),
                **dict(getattr(exc, "details", {}) or {}),
            },
        ) from exc
    return {
        "checked": len(coordinates),
        "grch37_matches": matches["grch37"],
        "grch38_matches": matches["grch38"],
    }


def annotate_rsid_with_hm3(
    side: str,
    path: Path,
    genome_build: str,
) -> dict[str, Any]:
    load_map, lookup_rsid, _ = _load_hm3_mapping_helpers(side)
    try:
        coord_to_rsid = load_map(genome_build)
    except Exception as exc:
        raise GwasQcCanonicalizationBlocked(
            f"{side} HM3 rsID mapping reference could not be loaded: {exc}",
            failure_class=getattr(exc, "failure_class", "coordinate_rsid_reference_missing"),
            details={"side": side, "error": str(exc), **dict(getattr(exc, "details", {}) or {})},
        ) from exc
    tmp = path.with_name(f"{path.name}.hm3.tmp")
    counts = {
        "raw_rsid_retained": 0,
        "hm3_rsid_mapped": 0,
        "unmapped_rows": 0,
        "rows": 0,
        "genome_build": genome_build,
    }
    with open_text_auto(path) as in_handle, gzip.open(tmp, "wt", encoding="utf-8", newline="") as out_handle:
        reader = csv.DictReader(in_handle, delimiter="\t")
        fieldnames = list(reader.fieldnames or [])
        writer = csv.DictWriter(out_handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in reader:
            counts["rows"] += 1
            if snp_value_type(row.get("SNP")) == "rsid":
                counts["raw_rsid_retained"] += 1
                writer.writerow(row)
                continue
            rsid = lookup_rsid(
                chrom=row.get("CHR"),
                pos=row.get("BP"),
                allele1=row.get("effect_allele"),
                allele2=row.get("other_allele"),
                coord_to_rsid=coord_to_rsid,
            )
            if rsid:
                row["SNP"] = rsid
                counts["hm3_rsid_mapped"] += 1
            else:
                counts["unmapped_rows"] += 1
            writer.writerow(row)
    shutil.move(str(tmp), str(path))
    counts["enabled"] = True
    return counts


def ensure_gzip_file(path: Path) -> None:
    if is_gzip_path(path):
        return
    tmp = path.with_name(f"{path.name}.gzip.tmp")
    with path.open("rt", encoding="utf-8", errors="replace", newline="") as in_handle, gzip.open(
        tmp,
        "wt",
        encoding="utf-8",
        newline="",
    ) as out_handle:
        shutil.copyfileobj(in_handle, out_handle)
    shutil.move(str(tmp), str(path))


def blocked_from_llm(
    side: str,
    response: dict[str, Any],
) -> GwasQcCanonicalizationBlocked:
    missing = [item for item in list(response.get("missing_requirements") or []) if isinstance(item, dict)]
    return GwasQcCanonicalizationBlocked(
        f"{side} LLM codegen blocked: {compact_text(response.get('reason'))}",
        failure_class=(
            compact_text(response.get("failure_class"))
            or "gwas_qc_codegen_blocked"
        ),
        details={"side": side, "llm_response": response},
        missing_requirements=missing,
    )


def side_label(payload: dict[str, Any], side: str) -> str:
    return compact_text(payload.get(f"{side}_label")) or side


def canonicalize_side(side: str, payload: dict[str, Any]) -> dict[str, Any]:
    max_attempts = max(1, int(payload.get("max_attempts") or 3))
    sample_limit = max(1, int(payload.get("sample_rows") or 50))
    sample_timeout = max(1, int(payload.get("sample_timeout_seconds") or 120))
    full_timeout = max(1, int(payload.get("full_timeout_seconds") or 7200))
    raw_path = compact_text(payload.get(f"{side}_raw_path"))
    log_step(f"Starting {side} canonicalization: raw_path={raw_path}")
    log_step(f"{side} preview started.")
    preview = preview_raw_file(side, raw_path, sample_limit=sample_limit)
    log_step(
        f"{side} preview done: format={preview.physical_format}; "
        f"header_fields={len(preview.header_fields)}; sample_rows={len(preview.sample_rows)}."
    )
    sample_input = write_sample_input(preview)
    sample_expected_rows = len(preview.sample_raw_lines)
    log_step(f"{side} sample input written: {sample_input}")
    log_step(f"{side} counting input rows.")
    input_rows = count_input_rows(preview)
    log_step(f"{side} input rows counted: rows={input_rows}.")
    previous_error: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] = []
    prompt_paths: dict[str, str] = {}
    final_code_path: Path | None = None
    final_mapping_reason = ""
    final_assumptions: list[dict[str, str]] = []
    for attempt in range(1, max_attempts + 1):
        log_step(f"{side} LLM codegen attempt {attempt}/{max_attempts} started.")
        response, prompt_paths, rendered_prompt = call_codegen_llm(
            side=side,
            preview=preview,
            payload=payload,
            previous_error=previous_error,
        )
        if response.get("status") == "blocked":
            exc = blocked_from_llm(side, response)
            log_step(f"{side} LLM codegen blocked on attempt {attempt}: {exc}", error=True)
            attempts.append({"attempt": attempt, "status": "blocked", "failure_class": exc.failure_class, "reason": str(exc)})
            raise exc
        code_path = write_generated_code(side, attempt, str(response["code"]))
        log_step(f"{side} LLM code written for attempt {attempt}: {code_path}")
        sample_output = samples_dir() / f"{side}.sample.canonical.tsv.gz"
        if sample_output.exists():
            sample_output.unlink()
        context_path = write_context(side, preview, payload, sample_mode=True)
        log_step(f"{side} sample execution attempt {attempt} started: rows={sample_expected_rows}.")
        completed = run_generated_transform(
            code_path=code_path,
            input_path=sample_input,
            output_path=sample_output,
            context_path=context_path,
            timeout_seconds=sample_timeout,
        )
        log_step(f"{side} sample execution attempt {attempt} finished: exit_code={completed.returncode}.")
        attempt_record = {
            "attempt": attempt,
            "code_path": str(code_path),
            "mapping_reason": compact_text(response.get("reason")),
            "assumptions": list(response.get("assumptions") or []),
            "sample_output": str(sample_output),
            "exit_code": completed.returncode,
            "stdout_tail": compact_text(completed.stdout)[-2000:],
            "stderr_tail": compact_text(completed.stderr)[-2000:],
        }
        if completed.returncode != 0:
            previous_error = {
                "stage": "sample_execution",
                "exit_code": completed.returncode,
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
            }
            attempt_record["status"] = "failed"
            attempt_record["failure_class"] = "generated_code_sample_failed"
            attempts.append(attempt_record)
            log_step(f"{side} sample execution attempt {attempt} failed; sending feedback to LLM.", error=True)
            continue
        try:
            log_step(f"{side} sample validation attempt {attempt} started.")
            sample_validation = validate_canonical_output(
                side=side,
                output_path=sample_output,
                expected_rows=sample_expected_rows,
                sample_only=True,
                strict_rsid=False,
                side_sample_size=side_sample_size(payload, side),
                source_preview=preview,
                source_input=sample_input,
            )
            log_step(
                f"{side} sample validation attempt {attempt} passed: "
                f"rows={sample_validation.rows_written}; snp_counts={sample_validation.snp_counts}."
            )
            attempt_record["status"] = "sample_ok"
            attempt_record["sample_validation"] = {
                "rows_written": sample_validation.rows_written,
                "snp_counts": sample_validation.snp_counts,
                "sample_rows": sample_validation.sample_rows,
            }
            attempts.append(attempt_record)
            final_code_path = code_path
            final_mapping_reason = compact_text(response.get("reason"))
            final_assumptions = list(response.get("assumptions") or [])
            try:
                write_codegen_prompt(side, attempt, rendered_prompt)
            except OSError as exc:
                log_step(f"{side} final codegen prompt was not saved: {exc}", error=True)
            break
        except GwasQcCanonicalizationBlocked as exc:
            previous_error = {
                "stage": "sample_validation",
                "failure_class": exc.failure_class,
                "message": str(exc),
                "details": exc.details,
                "missing_requirements": exc.missing_requirements,
            }
            attempt_record["status"] = "failed"
            attempt_record["failure_class"] = exc.failure_class
            attempt_record["validation_details"] = exc.details
            attempts.append(attempt_record)
            log_step(f"{side} sample validation attempt {attempt} failed: {exc}", error=True)
            continue
    if final_code_path is None:
        raise GwasQcCanonicalizationBlocked(
            f"{side} LLM-generated code failed after {max_attempts} attempt(s).",
            failure_class="generated_code_attempts_exhausted",
            details={"side": side, "attempts": attempts, "last_error": previous_error},
        )
    canonical_path = output_dir() / f"{side}.canonical.tsv.gz"
    if canonical_path.exists():
        canonical_path.unlink()
    full_context = write_context(side, preview, payload, sample_mode=False)
    log_step(f"{side} full execution started: rows={input_rows}; code={final_code_path}.")
    full_completed = run_generated_transform(
        code_path=final_code_path,
        input_path=preview.path,
        output_path=canonical_path,
        context_path=full_context,
        timeout_seconds=full_timeout,
    )
    log_step(f"{side} full execution finished: exit_code={full_completed.returncode}.")
    full_record = {
        "code_path": str(final_code_path),
        "output_path": str(canonical_path),
        "exit_code": full_completed.returncode,
        "stdout_tail": compact_text(full_completed.stdout)[-3000:],
        "stderr_tail": compact_text(full_completed.stderr)[-3000:],
    }
    if full_completed.returncode != 0:
        raise GwasQcCanonicalizationBlocked(
            f"{side} generated code failed on full input.",
            failure_class="generated_code_full_failed",
            details={"side": side, "full_execution": full_record},
        )
    log_step(f"{side} pre-mapping validation started.")
    pre_mapping_validation = validate_canonical_output(
        side=side,
        output_path=canonical_path,
        expected_rows=input_rows,
        sample_only=False,
        strict_rsid=False,
        side_sample_size=side_sample_size(payload, side),
        source_preview=preview,
    )
    log_step(
        f"{side} pre-mapping validation passed: "
        f"rows={pre_mapping_validation.rows_written}; snp_counts={pre_mapping_validation.snp_counts}."
    )
    mapping_required = needs_hm3_mapping(pre_mapping_validation)
    coordinate_check = None
    if mapping_required:
        log_step(f"{side} genome build coordinate check started.")
        coordinate_check = check_genome_build_coordinates(side, canonical_path)
        log_step(
            f"{side} genome build coordinate check done: {coordinate_check}."
        )
    log_step(f"{side} genome build LLM inference started.")
    genome_build_result = call_genome_build_llm(
        side=side,
        preview=preview,
        payload=payload,
        coordinate_check=coordinate_check,
    )
    genome_build = genome_build_result["genome_build"]
    genome_build_reason = genome_build_result["reason"]
    log_step(
        f"{side} genome build inferred: genome_build={genome_build}; "
        f"reason={genome_build_reason}"
    )
    if mapping_required and genome_build == "unknown":
        raise GwasQcCanonicalizationBlocked(
            f"{side} genome build is unresolved, so coordinate-based rsID mapping is unsafe. "
            f"Reason: {genome_build_reason}",
            failure_class="genome_build_unresolved",
            details={
                "side": side,
                "genome_build": genome_build,
                "genome_build_reason": genome_build_reason,
                "coordinate_check": coordinate_check,
            },
            missing_requirements=[
                {
                    "field": "genome_build",
                    "message": (
                        "GRCh37 or GRCh38 must be determined before coordinate-based "
                        f"rsID mapping. LLM reason: {genome_build_reason}"
                    ),
                }
            ],
        )
    mapping_report = None
    if mapping_required:
        log_step(
            f"{side} HM3 rsID mapping started: genome_build={genome_build}."
        )
        mapping_report = annotate_rsid_with_hm3(
            side,
            canonical_path,
            genome_build,
        )
        log_step(f"{side} HM3 rsID mapping done: {mapping_report}.")
    ensure_gzip_file(canonical_path)
    log_step(f"{side} final strict validation started.")
    final_validation = validate_canonical_output(
        side=side,
        output_path=canonical_path,
        expected_rows=input_rows,
        sample_only=False,
        strict_rsid=True,
        side_sample_size=side_sample_size(payload, side),
    )
    log_step(
        f"{side} final strict validation passed: "
        f"rows={final_validation.rows_written}; snp_counts={final_validation.snp_counts}."
    )
    log_step(f"{side} canonical output ready: {canonical_path}")
    return {
        "trait": side_label(payload, side),
        "raw_path": str(preview.path),
        "canonical_path": str(canonical_path),
        "rows_read": input_rows,
        "rows_written": final_validation.rows_written,
        "snp_values_written": final_validation.rows_written - int(final_validation.snp_counts.get("missing") or 0),
        "missing_snp_id": not final_validation.rsid_available,
        "source": compact_text(payload.get(f"{side}_source")) or None,
        "sample_size": side_sample_size(payload, side),
        "sample_size_source": "input_or_study_metadata" if side_sample_size(payload, side) else None,
        "mapping_notes": compact_text(payload.get(f"{side}_mapping_notes")) or None,
        "mapping_reason": final_mapping_reason or None,
        "genome_build": genome_build,
        "genome_build_reason": genome_build_reason,
        "risk_notes": final_assumptions,
        "format": preview.physical_format,
        "column_map_mode": "codegen",
        "llm_prompt_files": prompt_paths,
        "generated_code_path": str(final_code_path),
        "attempts": attempts,
        "full_execution": full_record,
        "coordinate_rsid_mapping": mapping_report,
        "validation_errors": [],
        "validation_warnings": final_validation.warnings,
        "snp_id_counts": final_validation.snp_counts,
        "snp_id_type": "rsid" if final_validation.rsid_available else "unknown",
        "rsid_available": final_validation.rsid_available,
        "sample_rows": final_validation.sample_rows,
        "final_column_map": {column: column for column in CANONICAL_COLUMNS},
    }
