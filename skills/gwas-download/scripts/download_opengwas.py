from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests

from .common import (
    build_error,
    build_success,
    choose_filename,
    download_file,
    http_headers,
    log_step,
    resolve_output_path,
)


OPENGWAS_FILES_ENDPOINT = os.getenv("OPENGWAS_FILES_ENDPOINT", "https://api.opengwas.io/api/gwasinfo/files")
EXPIRED_URL_STATUS_CODES = {403, 404, 410}


def _resolve_opengwas_url(study: Dict[str, Any]) -> Optional[str]:
    if study.get("download_url"):
        return study["download_url"]

    metadata = study.get("study_metadata", {}) or {}
    for key in ("download_url", "fullsumstats_url", "url"):
        if metadata.get(key):
            return metadata[key]

    return None


def _http_status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def _is_expired_url_error(exc: Exception) -> bool:
    return _http_status_code(exc) in EXPIRED_URL_STATUS_CODES


def _iter_urls(payload: Any):
    if isinstance(payload, dict):
        for value in payload.values():
            yield from _iter_urls(value)
        return
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_urls(item)
        return
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith(("http://", "https://")):
            yield text


def _pick_download_url(urls: list[str], study_id: str) -> str | None:
    exact_suffix = f"/{study_id}/{study_id}.vcf.gz"
    for url in urls:
        if exact_suffix in url:
            return url
    for url in urls:
        if url.endswith(".vcf.gz"):
            return url
    return urls[0] if urls else None


def _refresh_opengwas_url(study: Dict[str, Any], jwt: str | None) -> tuple[str | None, str | None]:
    study_id = str(study.get("study_id") or "").strip()
    if not study_id:
        return None, "OpenGWAS download URL expired, but the selected study is missing study_id."
    if not jwt:
        return None, "OpenGWAS download URL expired; set OPENGWAS_JWT and retry, or rerun data search."

    try:
        response = requests.post(
            OPENGWAS_FILES_ENDPOINT,
            json={"id": [study_id]},
            timeout=30,
            headers=http_headers(jwt),
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        return None, f"OpenGWAS download URL expired, and refreshing it from OpenGWAS failed: {exc}"

    refreshed_url = _pick_download_url(list(dict.fromkeys(_iter_urls(payload))), study_id)
    if not refreshed_url:
        return None, "OpenGWAS download URL expired, and OpenGWAS did not return a replacement download URL."
    return refreshed_url, None


def download_opengwas(study: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    url = _resolve_opengwas_url(study)
    if not url:
        return build_error(study, "download_error", "OpenGWAS study is missing a resolvable download URL.", source="opengwas")

    auth_required = bool(study.get("auth_required"))
    requires_user_confirmation = bool(study.get("requires_user_confirmation"))
    jwt = os.getenv("OPENGWAS_JWT")

    if auth_required and not jwt:
        return build_error(
            study,
            "auth_required",
            "This OpenGWAS download requires OPENGWAS_JWT, but the environment variable is not set.",
            source="opengwas",
        )

    if requires_user_confirmation and auth_required:
        return build_error(
            study,
            "auth_required",
            "This OpenGWAS download is marked as requiring user confirmation before using a token.",
            source="opengwas",
        )

    filename = choose_filename(study, ".tsv.gz")
    output_path = resolve_output_path(output_dir, filename)
    description = f"{study.get('side') or 'study'} {study.get('study_id') or 'unknown'} from opengwas"

    try:
        size = download_file(
            url,
            output_path,
            auth_token=jwt if auth_required else None,
            description=description,
        )
    except Exception as exc:  # pragma: no cover
        if not _is_expired_url_error(exc):
            return build_error(study, "download_error", f"OpenGWAS download failed: {exc}", source="opengwas")

        refreshed_url, refresh_error = _refresh_opengwas_url(study, jwt)
        if not refreshed_url:
            return build_error(study, "download_error", refresh_error or "OpenGWAS download URL expired.", source="opengwas")

        log_step(f"OpenGWAS URL for {study.get('study_id') or 'unknown'} expired; retrying with refreshed URL.", error=True)
        try:
            size = download_file(
                refreshed_url,
                output_path,
                auth_token=jwt if auth_required else None,
                description=description,
            )
            url = refreshed_url
        except Exception as retry_exc:  # pragma: no cover
            return build_error(
                study,
                "download_error",
                f"OpenGWAS download failed after refreshing expired URL: {retry_exc}",
                source="opengwas",
            )

    return build_success(
        study=study,
        saved_path=output_path,
        download_url=url,
        file_size=size,
        auth_used=bool(auth_required and jwt),
    )
