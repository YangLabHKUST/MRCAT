from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .common import (
    build_error,
    build_success,
    choose_filename,
    download_file,
    resolve_output_path,
)


def _resolve_finngen_url(study: Dict[str, Any]) -> Optional[str]:
    if study.get("download_url"):
        return str(study["download_url"])

    descriptor = study.get("download_descriptor")
    if isinstance(descriptor, dict) and descriptor.get("url"):
        return str(descriptor["url"])

    metadata = study.get("study_metadata", {}) or {}
    for key in ("download_url", "url", "path_https"):
        if metadata.get(key):
            return str(metadata[key])

    release = str(metadata.get("release") or "").strip().upper()
    endpoint = str(
        metadata.get("endpoint_code") or metadata.get("endpoint") or ""
    ).strip().upper()
    match = re.fullmatch(
        r"finngen_(R\d+)_(.+)",
        str(study.get("study_id") or "").strip(),
        flags=re.IGNORECASE,
    )
    if match:
        release = release or match.group(1).upper()
        endpoint = endpoint or match.group(2).upper()
    filename = metadata.get("filename")
    if filename and str(filename).startswith("http"):
        return str(filename)

    if release == "R12" and endpoint:
        return (
            "https://storage.googleapis.com/finngen-public-data-r12/"
            f"summary_stats/release/finngen_R12_{endpoint}.gz"
        )
    if release == "R10" and endpoint:
        return (
            "https://storage.googleapis.com/finngen-public-data-r10/"
            f"summary_stats/finngen_R10_{endpoint}.gz"
        )

    return None


def download_finngen(study: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    url = _resolve_finngen_url(study)
    if not url:
        return build_error(study, "download_error", "FinnGen study is missing a resolvable download URL.", source="finngen")

    filename = choose_filename(study, ".gz")
    output_path = resolve_output_path(output_dir, filename)
    description = f"{study.get('side') or 'study'} {study.get('study_id') or 'unknown'} from finngen"

    try:
        size = download_file(url, output_path, description=description)
    except Exception as exc:  # pragma: no cover
        return build_error(study, "download_error", f"FinnGen download failed: {exc}", source="finngen")

    return build_success(
        study=study,
        saved_path=output_path,
        download_url=url,
        file_size=size,
        auth_used=False,
    )
