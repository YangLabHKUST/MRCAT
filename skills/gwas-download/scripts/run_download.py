from __future__ import annotations

from contextlib import redirect_stdout

# Support the documented standalone CLI as well as package imports.
if not __package__:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    __package__ = "skills.gwas-download.scripts"

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict
from urllib.parse import unquote, urlparse

from .common import (
    ensure_writable_output_dir,
    extract_sample_counts,
    missing_auth_requirement,
    resolve_output_dir,
    resolve_study_download_url,
)
from .download_finngen import download_finngen
from .download_gwas_catalog import (
    catalog_metadata_for_url,
    download_gwas_catalog,
)
from .download_opengwas import download_opengwas
from .download_pan_ukb import download_pan_ukb
from .download_user_url import download_user_url


DOWNLOADERS = {
    "opengwas": download_opengwas,
    "gwas_catalog": download_gwas_catalog,
    "finngen": download_finngen,
    "pan_ukb": download_pan_ukb,
    "user_url": download_user_url,
}


def log_step(message: str, *, error: bool = False) -> None:
    print(f"[gwas-download] {message}", file=sys.stderr if error else sys.stdout, flush=True)


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _unwrap_payload(input_data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(input_data, dict):
        return {}
    payload = input_data.get("payload")
    if not isinstance(payload, dict):
        return dict(input_data)
    merged = dict(payload)
    for key, value in input_data.items():
        if key != "payload" and key not in merged:
            merged[key] = value
    return merged


def _safe_cache_component(value: Any) -> str:
    text = _compact_text(value)
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in text)
    return safe[:120].strip("._-") or "unknown"


def _study_id(study: Dict[str, Any]) -> str:
    return _compact_text(study.get("study_id") or study.get("id"))


def _user_url_study(raw: Dict[str, Any]) -> Dict[str, Any]:
    download_url = _compact_text(raw.get("download_url"))
    parsed = urlparse(download_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _error(
            "invalid_download_url",
            "Direct download_url must be an absolute HTTP(S) URL.",
            output_dir="",
        )
    if parsed.username or parsed.password:
        return _error(
            "invalid_download_url",
            "Direct download_url must not include credentials.",
            output_dir="",
        )
    filename = Path(unquote(parsed.path)).name
    label = _compact_text(raw.get("label")) or filename or "User-provided GWAS"
    digest = hashlib.sha256(download_url.encode("utf-8")).hexdigest()[:16]
    metadata = raw.get("study_metadata")
    return {
        "source": "user_url",
        "study_id": f"user-url-{digest}",
        "trait": label,
        "ancestry": raw.get("ancestry"),
        "ancestry_raw": raw.get("ancestry_raw"),
        "sample_size": raw.get("sample_size"),
        "n_cases": raw.get("n_cases"),
        "n_controls": raw.get("n_controls"),
        "study_metadata": dict(metadata) if isinstance(metadata, dict) else {},
        "download_descriptor": {
            "status": "ready",
            "method": "url",
            "url": download_url,
        },
    }


def _download_cache_root(output_dir: str | os.PathLike[str]) -> Path:
    # CodeAct cells share a session, but each call has a fresh output directory.
    session_dir = os.getenv("MRCAT_SESSION_DIR", "").strip()
    if session_dir:
        return Path(session_dir).expanduser() / "cache" / "gwas-download"
    execution_dir = _compact_text(os.getenv("MRCAT_EXECUTION_DIR"))
    start = (
        Path(execution_dir).expanduser()
        if execution_dir
        else Path(output_dir).expanduser()
    )
    for candidate in (start, *start.parents):
        if candidate.parent.name == "sessions":
            return candidate / "cache" / "gwas-download"
    return Path(output_dir).expanduser()


def _cache_dir(cache_root: Path, study: Dict[str, Any]) -> Path:
    source = _compact_text(study.get("source"))
    study_id = _study_id(study)
    download_url = _compact_text(study.get("download_url"))
    digest = hashlib.sha256(
        f"{source}\n{study_id}\n{download_url}".encode("utf-8")
    ).hexdigest()[:16]
    return (
        cache_root
        / _safe_cache_component(source)
        / _safe_cache_component(study_id)
        / digest
    )


def _cache_marker_path(cache_dir: Path) -> Path:
    return cache_dir / ".gwas-download-complete.json"


def _cached_result(
    study: Dict[str, Any],
    cache_dir: Path,
) -> Dict[str, Any] | None:
    marker_path = _cache_marker_path(cache_dir)
    if not marker_path.is_file():
        return None
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if _compact_text(marker.get("source")) != _compact_text(study.get("source")):
        return None
    if _compact_text(marker.get("study_id")) != _study_id(study):
        return None
    if _compact_text(marker.get("download_url")) != _compact_text(
        study.get("download_url")
    ):
        return None
    saved_path = _compact_text(marker.get("saved_path"))
    path = Path(saved_path).expanduser()
    try:
        file_size = int(marker.get("file_size"))
    except (TypeError, ValueError):
        return None
    if not path.is_file() or path.stat().st_size != file_size:
        return None
    study_metadata = marker.get("study_metadata")
    if not isinstance(study_metadata, dict):
        return None
    log_step(
        f"Reusing cached study {_study_id(study)}: "
        f"path={path}; file_size={file_size}."
    )
    return {
        "status": "success",
        "saved_path": str(path),
        "file_size": file_size,
        "download_url": _compact_text(marker.get("download_url")),
        "auth_used": bool(marker.get("auth_used")),
        "study_metadata": study_metadata,
    }


def _write_cache_marker(
    study: Dict[str, Any],
    result: Dict[str, Any],
    cache_dir: Path,
) -> None:
    saved_path = _compact_text(result.get("saved_path"))
    path = Path(saved_path).expanduser()
    if not path.is_file():
        return
    try:
        file_size = int(result.get("file_size"))
    except (TypeError, ValueError):
        file_size = path.stat().st_size
    if path.stat().st_size != file_size:
        return
    marker = {
        "source": study.get("source"),
        "study_id": _study_id(study),
        "download_url": result.get("download_url") or study.get("download_url"),
        "file_size": file_size,
        "saved_path": str(path),
        "auth_used": bool(result.get("auth_used")),
        "study_metadata": (
            result.get("study_metadata")
            if isinstance(result.get("study_metadata"), dict)
            else dict(study.get("study_metadata") or {})
        ),
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    marker_path = _cache_marker_path(cache_dir)
    tmp_path = marker_path.with_suffix(marker_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(marker, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp_path, marker_path)


def _error(
    failure_class: str,
    message: str,
    *,
    study: Dict[str, Any] | None = None,
    output_dir: str,
) -> Dict[str, Any]:
    return {
        "status": "error",
        "error": {
            "type": failure_class,
            "message": message,
        },
        "study": dict(study or {}),
        "output_dir": output_dir,
    }


def _prepare_selected_study(
    study: Dict[str, Any],
    *,
    output_dir: str,
) -> Dict[str, Any]:
    if not isinstance(study, dict) or not study:
        return _error(
            "selected_study_required",
            "gwas-download requires one selected_study from gwas-select.",
            output_dir=output_dir,
        )
    source = _compact_text(study.get("source"))
    if source == "local":
        return _error(
            "local_study_not_downloadable",
            "Local GWAS files bypass gwas-download and enter gwas-qc.",
            study=study,
            output_dir=output_dir,
        )
    if source not in DOWNLOADERS:
        return _error(
            "unknown_source",
            f"Unsupported data source: {source or 'missing'}",
            study=study,
            output_dir=output_dir,
        )
    auth_message = missing_auth_requirement(study)
    if auth_message:
        return _error(
            "auth_required",
            auth_message,
            study=study,
            output_dir=output_dir,
        )
    resolved_url = resolve_study_download_url(study)
    if not resolved_url:
        return _error(
            "no_downloadable_study",
            "selected_study is missing a ready executable download descriptor.",
            study=study,
            output_dir=output_dir,
        )
    prepared = dict(study)
    prepared["source"] = source
    prepared["study_id"] = _study_id(study)
    prepared["download_url"] = resolved_url
    return prepared


def _prepare_input(raw: Dict[str, Any], *, output_dir: str) -> Dict[str, Any]:
    selected_study = raw.get("selected_study")
    download_url = _compact_text(raw.get("download_url"))
    has_selected_study = isinstance(selected_study, dict) and bool(selected_study)
    if has_selected_study and download_url:
        return _error(
            "input_mode_conflict",
            "Provide either selected_study or download_url, not both.",
            output_dir=output_dir,
        )
    if has_selected_study:
        return _prepare_selected_study(selected_study, output_dir=output_dir)
    if download_url:
        direct_study = _user_url_study(raw)
        if direct_study.get("status") == "error":
            direct_study["output_dir"] = output_dir
            return direct_study
        return _prepare_selected_study(direct_study, output_dir=output_dir)
    return _error(
        "download_input_required",
        "gwas-download requires either one selected_study or one direct download_url.",
        output_dir=output_dir,
    )


def run_download(
    input_data: Dict[str, Any],
    output_dir: str = "./downloads",
) -> Dict[str, Any]:
    log_step("Starting single-study GWAS download.")
    raw = _unwrap_payload(input_data)
    final_output_dir = resolve_output_dir(
        raw.get("output_dir") or raw.get("output_path"),
        output_dir,
    )
    prepared = _prepare_input(raw, output_dir=final_output_dir)
    if prepared.get("status") == "error":
        return prepared
    try:
        final_output_dir = ensure_writable_output_dir(final_output_dir)
    except Exception as exc:
        return _error(
            "output_dir_not_writable",
            f"Could not create or write output directory: {final_output_dir}. {exc}",
            study=prepared,
            output_dir=final_output_dir,
        )

    source = _compact_text(prepared.get("source"))
    cache_dir = _cache_dir(_download_cache_root(final_output_dir), prepared)
    result = _cached_result(prepared, cache_dir)
    if result is not None and source == "gwas_catalog":
        discovered_metadata = catalog_metadata_for_url(prepared["download_url"])
        if discovered_metadata:
            result["study_metadata"] = {
                **dict(result.get("study_metadata") or {}),
                **discovered_metadata,
            }
            _write_cache_marker(prepared, result, cache_dir)
    if result is None:
        log_step(
            f"Downloading source={source}; study_id={_study_id(prepared)}; "
            f"cache_dir={cache_dir}."
        )
        result = DOWNLOADERS[source](prepared, str(cache_dir))
        if result.get("status") == "success":
            _write_cache_marker(prepared, result, cache_dir)
    if result.get("status") != "success":
        error = (
            result.get("error")
            if isinstance(result.get("error"), dict)
            else {}
        )
        return _error(
            _compact_text(error.get("type")) or "download_error",
            _compact_text(error.get("message")) or "GWAS download failed.",
            study=prepared,
            output_dir=final_output_dir,
        )
    saved_path = _compact_text(result.get("saved_path"))
    file_size = int(result.get("file_size") or Path(saved_path).stat().st_size)
    study_metadata = (
        dict(result.get("study_metadata"))
        if isinstance(result.get("study_metadata"), dict)
        else dict(prepared.get("study_metadata") or {})
    )
    counts = extract_sample_counts(prepared)
    log_step(
        f"Completed single-study download: study_id={_study_id(prepared)}; "
        f"path={saved_path}; file_size={file_size}."
    )
    return {
        "status": "success",
        "saved_path": saved_path,
        "file_size": file_size,
        "output_dir": final_output_dir,
        "trait": prepared.get("trait"),
        "study_id": _study_id(prepared),
        "source": source,
        "ancestry": prepared.get("ancestry"),
        "ancestry_raw": prepared.get("ancestry_raw"),
        "sample_size": counts["sample_size"],
        "n_cases": counts["n_cases"],
        "n_controls": counts["n_controls"],
        "study_metadata": study_metadata,
    }


def _render_runner_output(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("status") == "success":
        downloaded_study = {
            "raw_path": result.get("saved_path"),
            "file_size": result.get("file_size"),
            "label": result.get("trait"),
            "study_id": result.get("study_id"),
            "source": result.get("source"),
            "ancestry": result.get("ancestry"),
            "ancestry_raw": result.get("ancestry_raw"),
            "sample_size": result.get("sample_size"),
            "n_cases": result.get("n_cases"),
            "n_controls": result.get("n_controls"),
            "study_metadata": result.get("study_metadata") or {},
        }
        return {
            "summary": (
                "GWAS download completed: downloaded "
                f"{result.get('source')}:{result.get('study_id')} to "
                f"{result.get('saved_path')}."
            ),
            "outputs": {
                "status": "ok",
                "gwas_download_result": {
                    "downloaded_study": downloaded_study,
                },
            },
            "details": {
                "result_status": "ok",
                "failure_class": None,
                "study_id": result.get("study_id"),
                "source": result.get("source"),
                "output_dir": result.get("output_dir"),
            },
        }
    error = (
        result.get("error")
        if isinstance(result.get("error"), dict)
        else {}
    )
    failure_class = _compact_text(error.get("type")) or "download_failed"
    message = _compact_text(error.get("message")) or "download failed"
    return {
        "summary": f"GWAS download blocked: {message}",
        "outputs": {"status": "blocked"},
        "details": {
            "result_status": "blocked",
            "failure_class": failure_class,
            "message": message,
            "output_dir": result.get("output_dir"),
        },
    }


def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Download one explicitly selected study or raw URL."""
    return _render_runner_output(run_download(payload, output_dir=os.environ["MRCAT_EXECUTION_DIR"]))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download one selected or direct-URL remote GWAS study."
    )
    parser.add_argument("--input", help="Input JSON file path")
    parser.add_argument("--input-json", help="Structured JSON input path")
    parser.add_argument(
        "--output-dir",
        default="./downloads",
        help="Download output directory",
    )
    args = parser.parse_args()

    input_path = args.input_json or args.input
    if not input_path:
        raise SystemExit("run_download.py requires --input or --input-json")
    with Path(input_path).open("r", encoding="utf-8") as handle:
        input_data = json.load(handle)
    with redirect_stdout(sys.stderr):
        result = run_download(input_data, output_dir=args.output_dir)
    print(
        json.dumps(
            _render_runner_output(result),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
