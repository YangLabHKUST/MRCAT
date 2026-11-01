from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from urllib.parse import unquote, urlparse

from .common import (
    build_error,
    build_success,
    download_file,
    resolve_output_path,
)


def _filename_from_url(url: str) -> str:
    filename = Path(unquote(urlparse(url).path)).name
    return filename or "user-provided-gwas.tsv"


def download_user_url(study: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    url = str(study.get("download_url") or "").strip()
    if not url:
        return build_error(
            study,
            "download_url_required",
            "A direct user URL is required for this download.",
            source="user_url",
        )
    output_path = resolve_output_path(output_dir, _filename_from_url(url))
    description = f"user URL {study.get('study_id') or 'unknown'}"
    try:
        size = download_file(url, output_path, description=description)
    except Exception as exc:  # pragma: no cover
        return build_error(
            study,
            "download_error",
            f"User URL download failed: {exc}",
            source="user_url",
        )
    return build_success(
        study=study,
        saved_path=output_path,
        download_url=url,
        file_size=size,
        auth_used=False,
    )
