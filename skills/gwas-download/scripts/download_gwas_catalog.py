from __future__ import annotations

import gzip
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import re
from typing import Any, Dict, Optional
from urllib.parse import unquote, urljoin, urlparse
import zipfile

import requests

from .common import (
    DEFAULT_TIMEOUT,
    build_error,
    build_success,
    choose_filename,
    download_file,
    http_headers,
    log_step,
    resolve_output_path,
)


ZIP_MEMBER_SUFFIXES = (
    ".tsv.gz",
    ".tsv",
    ".txt.gz",
    ".txt",
    ".csv.gz",
    ".csv",
)
ZIP_NON_DATA_NAME_TOKENS = (
    "readme",
    "metadata",
    "manifest",
    "documentation",
    "license",
    "notes",
)
NOTE_NAME_TOKENS = ("meta", "metadata", "readme", "notes")
MAX_NOTE_BYTES = 64 * 1024
MAX_INDEX_BYTES = 256 * 1024
MAX_FILE_NOTES_CHARS = 12000


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def _resolve_catalog_url(study: Dict[str, Any]) -> Optional[str]:
    if study.get("download_url"):
        return study["download_url"]

    metadata = study.get("study_metadata", {}) or {}
    for key in ("download_url", "summary_statistics_url", "ftp_url", "url"):
        if metadata.get(key):
            return metadata[key]
    return None


def _filename_from_url(url: str) -> Optional[str]:
    filename = Path(unquote(urlparse(str(url)).path)).name
    if not filename or "." not in filename:
        return None
    return filename


def _is_zip_filename(filename: str) -> bool:
    return str(filename or "").lower().endswith(".zip")


def _safe_member_basename(member_name: str) -> str:
    return Path(str(member_name or "").replace("\\", "/")).name


def _is_zip_summary_member(info: zipfile.ZipInfo) -> bool:
    if info.is_dir():
        return False
    basename = _safe_member_basename(info.filename)
    lower = basename.lower()
    if not lower:
        return False
    if any(token in lower for token in ZIP_NON_DATA_NAME_TOKENS):
        return False
    return lower.endswith(ZIP_MEMBER_SUFFIXES)


def _is_note_filename(filename: str) -> bool:
    basename = _safe_member_basename(filename)
    lower = basename.lower()
    if not lower:
        return False
    return any(
        re.search(rf"(?:^|[._-]){re.escape(token)}(?:$|[._-])", lower)
        for token in NOTE_NAME_TOKENS
    )


def _clean_note_text(text: str) -> str:
    text = text.replace("\ufeff", " ").replace("\ufffd", " ")
    text = "".join(ch if ch in "\n\t" or ord(ch) >= 32 else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def _decode_note_bytes(data: bytes) -> str:
    if data.startswith(b"\x1f\x8b"):
        try:
            with gzip.GzipFile(fileobj=BytesIO(data)) as handle:
                data = handle.read(MAX_NOTE_BYTES)
        except (EOFError, OSError):
            return ""
    if b"\x00" in data[:4096]:
        return ""
    candidates = []
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        decoded = data.decode(encoding, errors="replace")
        candidates.append(decoded)
        if "\ufffd" not in decoded:
            break
    text = min(candidates, key=lambda value: value.count("\ufffd"))
    return _clean_note_text(text)


def _format_file_notes(parts: list[str]) -> str | None:
    cleaned = [_clean_note_text(part) for part in parts]
    cleaned = [part for part in cleaned if part]
    if not cleaned:
        return None
    merged = " ".join(cleaned)
    if len(merged) > MAX_FILE_NOTES_CHARS:
        merged = merged[:MAX_FILE_NOTES_CHARS].rstrip()
    return f"GWAS Catalog file notes: {merged}"


def _read_limited_response_text(url: str, *, max_bytes: int) -> str | None:
    try:
        with requests.get(url, stream=True, timeout=DEFAULT_TIMEOUT, headers=http_headers()) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=16 * 1024):
                if not chunk:
                    continue
                remaining = max_bytes - total
                if remaining <= 0:
                    break
                chunks.append(chunk[:remaining])
                total += len(chunk[:remaining])
                if total >= max_bytes:
                    break
    except Exception as exc:
        log_step(f"Skipping GWAS Catalog file notes from {url}: {exc}.", error=True)
        return None
    return _decode_note_bytes(b"".join(chunks))


def _note_priority(url: str) -> tuple[int, str]:
    name = _safe_member_basename(unquote(urlparse(url).path)).lower()
    for index, token in enumerate(NOTE_NAME_TOKENS):
        if re.search(rf"(?:^|[._-]){re.escape(token)}(?:$|[._-])", name):
            return index, name
    return len(NOTE_NAME_TOKENS), name


def _catalog_directory_url(url: str) -> str | None:
    parsed = urlparse(str(url))
    if not parsed.scheme or not parsed.netloc or "/" not in parsed.path:
        return None
    return url.rsplit("/", 1)[0] + "/"


def _directory_note_urls(summary_url: str) -> list[str]:
    directory_url = _catalog_directory_url(summary_url)
    if not directory_url:
        return []
    index_text = _read_limited_response_text(directory_url, max_bytes=MAX_INDEX_BYTES)
    if not index_text:
        return []
    parser = _HrefParser()
    try:
        parser.feed(index_text)
    except Exception:
        return []
    urls: list[str] = []
    directory_path = urlparse(directory_url).path
    for href in parser.hrefs:
        if href.startswith("?") or href.startswith("#"):
            continue
        absolute = urljoin(directory_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if not parsed.path.startswith(directory_path):
            continue
        if absolute.rsplit("/", 1)[0] + "/" != directory_url:
            continue
        if absolute.split("?", 1)[0] == summary_url.split("?", 1)[0]:
            continue
        if _is_note_filename(unquote(parsed.path.rsplit("/", 1)[-1])):
            urls.append(absolute)
    summary_filename = _safe_member_basename(
        unquote(urlparse(summary_url).path)
    ).lower()

    def priority(url: str) -> tuple[int, int, str]:
        name = _safe_member_basename(unquote(urlparse(url).path)).lower()
        exact_sidecar = int(not name.startswith(f"{summary_filename}-meta"))
        note_priority, _ = _note_priority(url)
        return exact_sidecar, note_priority, name

    return sorted(set(urls), key=priority)


def _download_directory_file_notes(summary_url: str) -> str | None:
    note_texts: list[str] = []
    for note_url in _directory_note_urls(summary_url):
        text = _read_limited_response_text(note_url, max_bytes=MAX_NOTE_BYTES)
        if text:
            filename = _safe_member_basename(unquote(urlparse(note_url).path))
            note_texts.append(f"{filename}: {text}")
    return _format_file_notes(note_texts)


def catalog_file_notes_for_url(summary_url: str) -> str | None:
    filename = _filename_from_url(summary_url) or ""
    if _is_zip_filename(filename):
        return None
    return _download_directory_file_notes(summary_url)


def _metadata_extras_from_file_notes(file_notes: str | None) -> dict[str, Any]:
    if not file_notes:
        return {}
    extras: dict[str, Any] = {"file_notes": file_notes}
    patterns = {
        "genome_assembly": r"\bgenome_assembly\s*:\s*['\"]?([A-Za-z0-9._/-]+)",
        "coordinate_system": r"\bcoordinate_system\s*:\s*['\"]?([A-Za-z0-9._/-]+)",
        "is_harmonised": r"\bis_harmonised\s*:\s*(true|false)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, file_notes, flags=re.IGNORECASE)
        if not match:
            continue
        value: Any = match.group(1)
        if key == "is_harmonised":
            value = str(value).lower() == "true"
        extras[key] = value
    return extras


def catalog_metadata_for_url(summary_url: str) -> dict[str, Any]:
    return _metadata_extras_from_file_notes(
        catalog_file_notes_for_url(summary_url)
    )


def _is_zip_note_member(info: zipfile.ZipInfo) -> bool:
    if info.is_dir():
        return False
    return _is_note_filename(info.filename)


def _zip_file_notes(zip_path: str) -> str | None:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            note_members = sorted(
                [info for info in archive.infolist() if _is_zip_note_member(info)],
                key=lambda info: _note_priority(info.filename),
            )
            note_texts: list[str] = []
            for member in note_members:
                with archive.open(member, "r") as source:
                    text = _decode_note_bytes(source.read(MAX_NOTE_BYTES))
                    if text:
                        note_texts.append(
                            f"{_safe_member_basename(member.filename)}: {text}"
                        )
            return _format_file_notes(note_texts)
    except zipfile.BadZipFile:
        return None


def _select_zip_summary_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo | None:
    candidates = [info for info in archive.infolist() if _is_zip_summary_member(info)]
    if not candidates:
        return None
    return max(candidates, key=lambda info: (int(info.file_size or 0), _safe_member_basename(info.filename)))


def _extract_zip_summary_stats(zip_path: str, output_dir: str) -> tuple[str, int] | tuple[None, None]:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            member = _select_zip_summary_member(archive)
            if member is None:
                return None, None
            basename = _safe_member_basename(member.filename)
            output_path = resolve_output_path(output_dir, basename)
            log_step(f"Extracting GWAS Catalog ZIP member: {member.filename} -> {output_path}.")
            with archive.open(member, "r") as source, open(output_path, "wb") as target:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
            return output_path, Path(output_path).stat().st_size
    except zipfile.BadZipFile:
        return None, None


def download_gwas_catalog(study: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    url = _resolve_catalog_url(study)
    if not url:
        return build_error(
            study,
            "download_error",
            "GWAS Catalog study is missing a resolvable download URL.",
            source="gwas_catalog",
        )

    filename = _filename_from_url(url) or choose_filename(study, ".tsv")
    output_path = resolve_output_path(output_dir, filename)
    description = f"{study.get('side') or 'study'} {study.get('study_id') or 'unknown'} from gwas_catalog"

    try:
        size = download_file(url, output_path, description=description)
    except Exception as exc:  # pragma: no cover
        return build_error(study, "download_error", f"GWAS Catalog download failed: {exc}", source="gwas_catalog")

    saved_path = output_path
    saved_size = size
    metadata_extras: dict[str, Any] = {}
    if _is_zip_filename(filename):
        extracted_path, extracted_size = _extract_zip_summary_stats(output_path, output_dir)
        if not extracted_path or extracted_size is None:
            return build_error(
                study,
                "download_error",
                "GWAS Catalog ZIP download did not contain a recognizable summary-statistics member.",
                source="gwas_catalog",
            )
        saved_path = extracted_path
        saved_size = extracted_size
        metadata_extras = _metadata_extras_from_file_notes(
            _zip_file_notes(output_path)
        )
    else:
        metadata_extras = catalog_metadata_for_url(url)

    return build_success(
        study=study,
        saved_path=saved_path,
        download_url=url,
        file_size=saved_size,
        auth_used=False,
        metadata_extras=metadata_extras or None,
    )
