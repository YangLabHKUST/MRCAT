from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests


DEFAULT_TIMEOUT = int(os.getenv("GWAS_DOWNLOAD_HTTP_TIMEOUT", "120"))
DEFAULT_USER_AGENT = os.getenv("GWAS_DOWNLOAD_USER_AGENT", "gwas-download/1.0")
DEFAULT_DOWNLOAD_ATTEMPTS = max(1, int(os.getenv("GWAS_DOWNLOAD_ATTEMPTS", "5")))
DEFAULT_RETRY_DELAY_SECONDS = max(0.0, float(os.getenv("GWAS_DOWNLOAD_RETRY_DELAY_SECONDS", "2")))
PAN_UKB_PREFIX = "https://pan-ukb-us-east-1.s3.amazonaws.com/sumstats_flat_files/"
DEFAULT_SESSION_DOWNLOAD_DIR = "downloads"


def ensure_dir(path: str | os.PathLike[str]) -> str:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def resolve_output_dir(requested_output_dir: str | None, default_output_dir: str) -> str:
    requested = str(requested_output_dir or "").strip()
    execution_dir_raw = str(os.getenv("MRCAT_EXECUTION_DIR") or "").strip()
    execution_dir = Path(execution_dir_raw) if execution_dir_raw else None

    if not requested:
        if execution_dir is not None:
            return str(execution_dir / DEFAULT_SESSION_DOWNLOAD_DIR)
        return str(default_output_dir)

    requested_path = Path(requested)
    if requested_path.is_absolute() or execution_dir is None:
        return str(requested_path)
    return str(execution_dir / requested_path)


def ensure_writable_output_dir(path: str | os.PathLike[str]) -> str:
    resolved = ensure_dir(path)
    target = Path(resolved)
    if not target.is_dir():
        raise NotADirectoryError(f"{resolved} is not a directory")
    if not os.access(target, os.W_OK):
        raise PermissionError(f"{resolved} is not writable")
    return resolved


def build_error(
    study: Dict[str, Any],
    error_type: str,
    message: str,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "status": "error",
        "study_id": study.get("study_id"),
        "source": source or study.get("source"),
        "trait": study.get("trait"),
        "error": {
            "type": error_type,
            "message": message,
        },
    }


def build_success(
    study: Dict[str, Any],
    saved_path: str,
    download_url: str,
    file_size: int,
    auth_used: bool,
    metadata_extras: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    counts = extract_sample_counts(study)
    payload = {
        "status": "success",
        "study_id": study.get("study_id"),
        "source": study.get("source"),
        "trait": study.get("trait"),
        "saved_path": saved_path,
        "download_url": download_url,
        "file_size": file_size,
        "auth_used": auth_used,
        "ancestry": study.get("ancestry"),
        "ancestry_raw": study.get("ancestry_raw"),
        "sample_size": counts["sample_size"],
        "n_cases": counts["n_cases"],
        "n_controls": counts["n_controls"],
    }
    metadata = download_result_metadata(study)
    for key, value in dict(metadata_extras or {}).items():
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple, set)):
            continue
        text = str(value).strip()
        if text:
            metadata[key] = value
    payload["study_metadata"] = metadata
    return payload


def choose_filename(study: Dict[str, Any], fallback_ext: str) -> str:
    study_id = study.get("study_id", "unknown_study")
    metadata = study.get("study_metadata", {}) or {}
    filename = metadata.get("filename")
    if filename:
        return str(filename)
    if fallback_ext.startswith("."):
        return f"{study_id}{fallback_ext}"
    return f"{study_id}.{fallback_ext}"


def resolve_output_path(output_dir: str, filename: str) -> str:
    ensure_dir(output_dir)
    return str(Path(output_dir) / filename)


def http_headers(auth_token: Optional[str] = None) -> Dict[str, str]:
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    return headers


def log_step(message: str, *, error: bool = False) -> None:
    print(f"[gwas-download] {message}", file=sys.stderr if error else sys.stdout, flush=True)


def format_mib(value: int) -> str:
    return f"{value / (1024 * 1024):.1f} MiB"


def _partial_paths(output_path: str) -> tuple[Path, Path, Path]:
    final_path = Path(output_path)
    partial_path = Path(f"{output_path}.part")
    metadata_path = Path(f"{output_path}.part.json")
    return final_path, partial_path, metadata_path


def _load_partial_metadata(metadata_path: Path, url: str) -> Dict[str, Any]:
    if not metadata_path.is_file():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or str(payload.get("url") or "") != url:
        return {}
    return payload


def _write_partial_metadata(
    metadata_path: Path,
    *,
    url: str,
    response_headers: Dict[str, Any],
    total_bytes: int,
) -> None:
    payload = {
        "url": url,
        "etag": str(response_headers.get("ETag") or "").strip() or None,
        "last_modified": str(response_headers.get("Last-Modified") or "").strip() or None,
        "total_bytes": total_bytes or None,
    }
    tmp_path = Path(f"{metadata_path}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, metadata_path)


def _parse_content_range(value: str) -> tuple[int | None, int | None, int | None]:
    match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", str(value or "").strip(), flags=re.IGNORECASE)
    if match:
        total = None if match.group(3) == "*" else int(match.group(3))
        return int(match.group(1)), int(match.group(2)), total
    complete_match = re.fullmatch(r"bytes\s+\*/(\d+)", str(value or "").strip(), flags=re.IGNORECASE)
    if complete_match:
        return None, None, int(complete_match.group(1))
    return None, None, None


def _response_total_bytes(response: Any, *, offset: int, status_code: int) -> int:
    headers = response.headers
    if status_code == 206:
        start, _end, total = _parse_content_range(headers.get("Content-Range", ""))
        if start != offset:
            raise RuntimeError(
                "Download resume rejected: "
                f"expected Content-Range to start at {offset}, received {headers.get('Content-Range')!r}."
            )
        if total is not None:
            return total
    content_length = _parse_int(headers.get("Content-Length")) or 0
    return offset + content_length if status_code == 206 else content_length


_RETRYABLE_DOWNLOAD_ERRORS = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ContentDecodingError,
)


def download_file(
    url: str,
    output_path: str,
    auth_token: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
    description: str = "file",
) -> int:
    log_step(f"Downloading {description}.")
    final_path, partial_path, metadata_path = _partial_paths(output_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if final_path.is_file() and not partial_path.exists():
        os.replace(final_path, partial_path)
        log_step(
            f"Preserved incomplete {description} for resume: "
            f"{format_mib(partial_path.stat().st_size)}."
        )

    last_error: BaseException | None = None
    for attempt in range(1, DEFAULT_DOWNLOAD_ATTEMPTS + 1):
        offset = partial_path.stat().st_size if partial_path.is_file() else 0
        metadata = _load_partial_metadata(metadata_path, url)
        headers = http_headers(auth_token)
        headers["Accept-Encoding"] = "identity"
        if offset:
            headers["Range"] = f"bytes={offset}-"
            validator = str(metadata.get("etag") or metadata.get("last_modified") or "").strip()
            if validator:
                headers["If-Range"] = validator
            log_step(
                f"Resuming {description} at byte {offset} "
                f"({format_mib(offset)}), attempt {attempt}/{DEFAULT_DOWNLOAD_ATTEMPTS}."
            )

        try:
            with requests.get(url, stream=True, timeout=timeout, headers=headers) as resp:
                status_code = int(getattr(resp, "status_code", 200) or 200)
                if offset and status_code == 416:
                    _start, _end, remote_total = _parse_content_range(
                        resp.headers.get("Content-Range", "")
                    )
                    if remote_total == offset:
                        os.replace(partial_path, final_path)
                        metadata_path.unlink(missing_ok=True)
                        log_step(
                            f"Completed download {description}: {format_mib(offset)}."
                        )
                        return final_path.stat().st_size
                    resp.raise_for_status()

                resp.raise_for_status()
                append = bool(offset and status_code == 206)
                if offset and status_code == 200:
                    log_step(
                        f"Server ignored Range for {description}; restarting the partial file."
                    )
                    offset = 0
                elif offset and status_code != 206:
                    raise RuntimeError(
                        f"Download resume expected HTTP 206, received HTTP {status_code}."
                    )

                total_bytes = _response_total_bytes(
                    resp,
                    offset=offset,
                    status_code=status_code,
                )
                _write_partial_metadata(
                    metadata_path,
                    url=url,
                    response_headers=resp.headers,
                    total_bytes=total_bytes,
                )
                downloaded_bytes = offset
                last_emitted_bytes = offset
                with partial_path.open("ab" if append else "wb") as handle:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded_bytes += len(chunk)
                        if (
                            downloaded_bytes - last_emitted_bytes >= 8 * 1024 * 1024
                            or (total_bytes and downloaded_bytes >= total_bytes)
                        ):
                            if total_bytes > 0:
                                percent = (downloaded_bytes / total_bytes) * 100.0
                                log_step(
                                    f"Downloading {description}: {format_mib(downloaded_bytes)} / "
                                    f"{format_mib(total_bytes)} ({percent:.1f}%)."
                                )
                            else:
                                log_step(
                                    f"Downloading {description}: {format_mib(downloaded_bytes)}."
                                )
                            last_emitted_bytes = downloaded_bytes
                    handle.flush()

                actual_size = partial_path.stat().st_size
                if total_bytes and actual_size != total_bytes:
                    raise requests.ConnectionError(
                        f"Incomplete download: received {actual_size} of {total_bytes} bytes."
                    )
                os.replace(partial_path, final_path)
                metadata_path.unlink(missing_ok=True)
                log_step(
                    f"Completed download {description}: {format_mib(actual_size)}."
                )
                return final_path.stat().st_size
        except _RETRYABLE_DOWNLOAD_ERRORS as exc:
            last_error = exc
            retained_bytes = partial_path.stat().st_size if partial_path.is_file() else 0
            if attempt >= DEFAULT_DOWNLOAD_ATTEMPTS:
                break
            log_step(
                f"Download connection interrupted for {description}; retained "
                f"{format_mib(retained_bytes)} and will resume: {exc}.",
                error=True,
            )
            if DEFAULT_RETRY_DELAY_SECONDS:
                time.sleep(min(DEFAULT_RETRY_DELAY_SECONDS * attempt, 10.0))

    retained_bytes = partial_path.stat().st_size if partial_path.is_file() else 0
    raise requests.ConnectionError(
        f"Download failed after {DEFAULT_DOWNLOAD_ATTEMPTS} attempt(s); "
        f"retained {retained_bytes} bytes for resume: {last_error}"
    ) from last_error


def _parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    compact = text.replace(",", "")
    try:
        return int(float(compact))
    except ValueError:
        digits = "".join(ch for ch in compact if ch.isdigit())
        if not digits:
            return None
        try:
            return int(digits)
        except ValueError:
            return None


def _parse_initial_sample_size(value: Any) -> int | None:
    if value in (None, ""):
        return None
    matches = re.findall(r"\d[\d,]*", str(value))
    if not matches:
        return None
    total = sum(int(token.replace(",", "")) for token in matches)
    return total or None


def _study_metadata(study: Dict[str, Any]) -> Dict[str, Any]:
    metadata = study.get("study_metadata")
    return metadata if isinstance(metadata, dict) else {}


def _without_download_url_fields(metadata: Dict[str, Any]) -> Dict[str, Any]:
    blocked = {"download_url", "summary_statistics_url", "ftp_url", "fullsumstats_url", "url"}
    return {key: value for key, value in dict(metadata or {}).items() if key not in blocked}


def download_result_metadata(study: Dict[str, Any]) -> Dict[str, Any]:
    source = str(study.get("source") or "").strip()
    metadata = _without_download_url_fields(_study_metadata(study))
    if source != "pan_ukb":
        return metadata

    raw_record = study.get("_raw_record")
    raw_record = raw_record if isinstance(raw_record, dict) else {}
    pan_ukb_keys = {
        "trait_type",
        "phenocode",
        "filename",
        "n_cases_AFR",
        "n_cases_AMR",
        "n_cases_CSA",
        "n_cases_EAS",
        "n_cases_EUR",
        "n_cases_MID",
        "n_controls_AFR",
        "n_controls_AMR",
        "n_controls_CSA",
        "n_controls_EAS",
        "n_controls_EUR",
        "n_controls_MID",
    }
    for key in pan_ukb_keys:
        value = raw_record.get(key)
        if value is not None and str(value).strip():
            metadata.setdefault(key, value)
    return metadata


def _first_int(study: Dict[str, Any], keys: tuple[str, ...]) -> int | None:
    metadata = _study_metadata(study)
    for key in keys:
        number = _parse_initial_sample_size(study.get(key)) if key == "initialSampleSize" else _parse_int(study.get(key))
        if number is not None and number > 0:
            return number
    for key in keys:
        number = _parse_initial_sample_size(metadata.get(key)) if key == "initialSampleSize" else _parse_int(metadata.get(key))
        if number is not None and number > 0:
            return number
    return None


def extract_sample_counts(study: Dict[str, Any]) -> Dict[str, int | None]:
    n_cases = _first_int(study, ("n_cases", "ncase", "cases", "num_cases", "case_count"))
    n_controls = _first_int(study, ("n_controls", "ncontrol", "controls", "num_controls", "control_count"))
    sample_size = _first_int(
        study,
        ("sample_size", "n_samples", "n_total", "n", "sampleSize", "initial_sample_size", "initialSampleSize", "effective_n"),
    )
    if sample_size is None and n_cases is not None and n_controls is not None:
        sample_size = n_cases + n_controls
    return {
        "sample_size": sample_size,
        "n_cases": n_cases,
        "n_controls": n_controls,
    }


def study_download_descriptor(study: Dict[str, Any]) -> Dict[str, Any]:
    descriptor = study.get("download_descriptor")
    return dict(descriptor or {}) if isinstance(descriptor, dict) else {}


def resolve_study_download_url(study: Dict[str, Any]) -> Optional[str]:
    descriptor = study_download_descriptor(study)
    if str(descriptor.get("status") or "").strip().lower() != "ready":
        return None
    method = str(descriptor.get("method") or "").strip().lower()
    if method not in {"url", "api"}:
        return None
    url = str(descriptor.get("url") or "").strip()
    return url or None


def missing_auth_requirement(study: Dict[str, Any]) -> Optional[str]:
    source = str(study.get("source") or "").strip()
    auth_required = bool(study.get("auth_required"))
    requires_user_confirmation = bool(study.get("requires_user_confirmation"))
    if requires_user_confirmation and auth_required:
        return "This download is marked as requiring user confirmation before using credentials."
    if source == "opengwas" and auth_required and not os.getenv("OPENGWAS_JWT"):
        return "This OpenGWAS download requires OPENGWAS_JWT, but the environment variable is not set."
    return None


def study_preview(study: Dict[str, Any], *, side: Optional[str] = None, status: str = "selected") -> Dict[str, Any]:
    preview = {
        "status": status,
        "study_id": study.get("study_id"),
        "source": study.get("source"),
        "trait": study.get("trait"),
        "downloadable": bool(study.get("downloadable")),
        "download_descriptor": study_download_descriptor(study),
    }
    if side:
        preview["side"] = side
    return preview
