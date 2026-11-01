from __future__ import annotations

from typing import Any, Dict, Optional

from .common import (
    build_error,
    build_success,
    choose_filename,
    download_file,
    resolve_output_path,
)


PAN_UKB_PREFIX = "https://pan-ukb-us-east-1.s3.amazonaws.com/sumstats_flat_files/"


def _resolve_pan_ukb_url(study: Dict[str, Any]) -> Optional[str]:
    if study.get("download_url"):
        return study["download_url"]

    metadata = study.get("study_metadata", {}) or {}
    if metadata.get("download_url"):
        return metadata["download_url"]

    filename = metadata.get("filename")
    if filename:
        return PAN_UKB_PREFIX + str(filename)

    return None


def download_pan_ukb(study: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    url = _resolve_pan_ukb_url(study)
    if not url:
        return build_error(study, "download_error", "Pan-UKB study is missing a resolvable download URL.", source="pan_ukb")

    filename = choose_filename(study, ".tsv.bgz")
    output_path = resolve_output_path(output_dir, filename)
    description = f"{study.get('side') or 'study'} {study.get('study_id') or 'unknown'} from pan_ukb"

    try:
        size = download_file(url, output_path, description=description)
    except Exception as exc:  # pragma: no cover
        return build_error(study, "download_error", f"Pan-UKB download failed: {exc}", source="pan_ukb")

    return build_success(
        study=study,
        saved_path=output_path,
        download_url=url,
        file_size=size,
        auth_used=False,
    )
