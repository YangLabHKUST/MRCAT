from __future__ import annotations

from contextlib import redirect_stdout
import sys

import re
from typing import Any, Dict, List

from .common import (
    BaseSearcher,
    SearchError,
    build_candidate,
    build_parser,
    log_step,
    package_error,
    package_success,
    parse_int,
    read_tsv_rows_with_progress,
    required_token_overlap,
    semantic_tokens,
    source_config,
    token_overlap,
    write_json,
)


class FinnGenSearcher(BaseSearcher):
    source_name = "finngen"
    _DEFAULT_RELEASE = "R12"

    def __init__(self, timeout: int = 30) -> None:
        super().__init__(timeout=timeout)
        config = source_config(self.source_name)
        raw_profiles = config.get("releases")
        self.release_profiles = {
            self._normalize_release(name): dict(profile)
            for name, profile in (raw_profiles.items() if isinstance(raw_profiles, dict) else [])
            if self._normalize_release(name) and isinstance(profile, dict)
        }
        if not self.release_profiles:
            legacy_release = self._normalize_release(config.get("release")) or "R10"
            self.release_profiles[legacy_release] = dict(config)
        self.default_release = (
            self._normalize_release(config.get("default_release"))
            or self._normalize_release(config.get("release"))
            or self._DEFAULT_RELEASE
        )
        self.last_probe_summary: dict[str, int] = {}
        self.last_source_stats: dict[str, Any] = {}
        self._activate_release(self.default_release)

    def search(
        self,
        query: str,
        limit: int = 30,
        check_download: bool = False,
    ) -> List[Dict[str, Any]]:
        self._activate_release(self.default_release)
        self.last_probe_summary = {"probe_total": 0, "probe_success_count": 0, "probe_failure_count": 0}
        self.reset_cache_stats()
        self.last_source_stats = self.with_cache_stats({})

        if self.mode == "manifest":
            results = self._search_via_manifest(
                query=query,
                check_download=check_download,
            )
            self.last_source_stats = self.with_cache_stats(
                {
                    **dict(self.last_source_stats),
                    "search_mode": "manifest",
                    "release": self.release,
                    "matched_candidate_count": len(results),
                }
            )
            return results[:limit]

        try:
            autocomplete_results = self._search_via_autocomplete(
                query=query,
                check_download=check_download,
            )
            self.last_source_stats = self.with_cache_stats(
                {
                    "search_mode": "autocomplete",
                    "matched_candidate_count": len(autocomplete_results),
                }
            )
            return autocomplete_results[:limit]
        except SearchError as exc:
            if exc.status != "network_error":
                raise
            log_step(f"FinnGen autocomplete failed; scanning phenotypes instead: {exc}.", error=True)
            fallback_results = self._search_via_phenos_scan(
                query=query,
                check_download=check_download,
            )
            self.last_source_stats = self.with_cache_stats(
                {
                    "search_mode": "phenos_scan",
                    "fallback_mode": "phenos_scan_network_failure",
                    "autocomplete_error": str(exc),
                    "matched_candidate_count": len(fallback_results),
                }
            )
            return fallback_results[:limit]

    def search_by_id(
        self,
        study_id: str,
        *,
        check_download: bool = False,
    ) -> List[Dict[str, Any]]:
        """Resolve one FinnGen phenotype ID into the same candidate shape as search()."""

        self.last_probe_summary = {"probe_total": 0, "probe_success_count": 0, "probe_failure_count": 0}
        self.reset_cache_stats()
        raw_id = str(study_id or "").strip()
        release, pheno = self._parse_study_id(raw_id)
        if not pheno:
            self.last_source_stats = self.with_cache_stats({"search_mode": "id", "matched_candidate_count": 0})
            return []
        self._activate_release(release)
        if self.mode == "manifest":
            row = self._find_manifest_row(pheno)
            candidate = (
                self._candidate_from_manifest_row(
                    row=row,
                    query=pheno,
                    match_score=10000,
                    matched_fields=["id"],
                    check_download=check_download,
                )
                if row
                else None
            )
        else:
            detail = self._fetch_pheno_detail(pheno)
            candidate = (
                self._candidate_from_pheno(
                    query=pheno,
                    pheno=pheno,
                    display="",
                    detail=detail,
                    check_download=check_download,
                    match_score=10000,
                    matched_fields=["id"],
                )
                if detail
                else None
            )
        if candidate is None:
            self.last_source_stats = self.with_cache_stats(
                {
                    **dict(self.last_source_stats),
                    "search_mode": "id",
                    "release": self.release,
                    "matched_candidate_count": 0,
                }
            )
            return []
        self.last_source_stats = self.with_cache_stats(
            {
                **dict(self.last_source_stats),
                "search_mode": "id",
                "release": self.release,
                "matched_candidate_count": 1,
                "probe_budget": self.last_probe_summary["probe_total"],
                "probe_count": self.last_probe_summary["probe_total"],
            }
        )
        return [candidate]

    def _parse_study_id(self, value: str) -> tuple[str, str]:
        text = str(value or "").strip()
        if not text:
            return self.default_release, ""
        match = re.fullmatch(r"finngen_(R\d+)_(.+)", text, flags=re.IGNORECASE)
        if match:
            return self._normalize_release(match.group(1)), match.group(2).strip().upper()
        if text.lower().startswith("finngen_"):
            return self.default_release, text[len("finngen_") :].strip().upper()
        return self.default_release, text.upper()

    @staticmethod
    def _normalize_release(value: Any) -> str:
        text = str(value or "").strip().upper()
        return text if re.fullmatch(r"R\d+", text) else ""

    def _activate_release(self, release: str) -> None:
        normalized = self._normalize_release(release)
        profile = self.release_profiles.get(normalized)
        if profile is None:
            supported = ", ".join(sorted(self.release_profiles))
            raise SearchError(
                f"Unsupported FinnGen release {release!r}; supported releases: {supported}.",
                status="unsupported",
            )
        self.release = normalized
        self.mode = str(profile.get("mode") or "api").strip().lower()
        if self.mode not in {"api", "manifest"}:
            raise SearchError(
                f"Unsupported FinnGen profile mode {self.mode!r} for {normalized}.",
                status="config_error",
            )
        self.manifest_url = str(
            profile.get("manifest_url") or profile.get("metadata_endpoint") or ""
        ).strip()
        self.phenos_api = str(profile.get("metadata_endpoint") or "").strip()
        self.download_url_template = str(
            profile.get("download_url_template")
            or profile.get("descriptor_url_template")
            or ""
        ).strip()
        self.autocomplete_endpoint = str(profile.get("autocomplete_endpoint") or "").strip()
        self.pheno_endpoint_template = str(profile.get("pheno_endpoint_template") or "").strip()

    def _search_via_manifest(
        self,
        *,
        query: str,
        check_download: bool,
    ) -> List[Dict[str, Any]]:
        if not self.manifest_url:
            raise SearchError(
                f"FinnGen {self.release} manifest URL is not configured.",
                status="config_error",
            )
        rows, manifest_stats = self._fetch_manifest_rows()
        results: List[Dict[str, Any]] = []
        for row in rows:
            phenocode = str(row.get("phenocode") or "").strip()
            if not phenocode:
                continue
            scored = self._score_trait_match(
                query,
                primary_values=[
                    ("phenotype", row.get("phenotype")),
                ],
                auxiliary_values=[
                    ("phenocode", phenocode),
                    ("category", row.get("category")),
                ],
            )
            if scored is None:
                continue
            match_score, matched_fields = scored
            results.append(
                self._candidate_from_manifest_row(
                    row=row,
                    query=query,
                    match_score=match_score,
                    matched_fields=matched_fields,
                    check_download=check_download,
                )
            )
        results.sort(key=self._candidate_sort_key)
        self.last_source_stats = {
            "release": self.release,
            "manifest_url": self.manifest_url,
            "rows_scanned": int(manifest_stats.get("rows_scanned") or len(rows)),
            "matched_candidate_count": len(results),
            "probe_budget": self.last_probe_summary["probe_total"],
            "probe_count": self.last_probe_summary["probe_total"],
        }
        return results

    def _find_manifest_row(self, phenocode: str) -> Dict[str, Any] | None:
        rows, manifest_stats = self._fetch_manifest_rows()
        target = phenocode.casefold()
        self.last_source_stats = {
            "release": self.release,
            "manifest_url": self.manifest_url,
            "rows_scanned": int(manifest_stats.get("rows_scanned") or len(rows)),
        }
        for row in rows:
            if str(row.get("phenocode") or "").strip().casefold() == target:
                return row
        return None

    def _candidate_from_manifest_row(
        self,
        *,
        row: Dict[str, Any],
        query: str,
        match_score: int,
        matched_fields: List[str],
        check_download: bool,
    ) -> Dict[str, Any]:
        phenocode = str(row.get("phenocode") or "").strip().upper()
        download_url = str(row.get("path_https") or "").strip() or None
        downloadable, downloadability_reason, download_check = self.evaluate_download(
            download_url=download_url,
            check_download=check_download,
            reason_if_missing="no_summary_stats",
        )
        if check_download and download_url:
            self.last_probe_summary["probe_total"] += 1
            if downloadable:
                self.last_probe_summary["probe_success_count"] += 1
            else:
                self.last_probe_summary["probe_failure_count"] += 1
        n_cases = parse_int(row.get("num_cases"))
        n_controls = parse_int(row.get("num_controls"))
        sample_size = (
            n_cases + n_controls
            if n_cases is not None and n_controls is not None
            else n_cases or n_controls
        )
        return build_candidate(
            side=None,
            trait=str(row.get("phenotype") or phenocode),
            study_id=f"finngen_{self.release}_{phenocode}",
            source=self.source_name,
            ancestry_value="Finnish",
            sample_size=sample_size,
            n_cases=n_cases,
            n_controls=n_controls,
            downloadable=downloadable,
            download_url=download_url,
            auth_required=False,
            requires_user_confirmation=False,
            downloadability_reason=downloadability_reason,
            download_check=download_check,
            matched_fields=matched_fields,
            matched_query=query,
            raw_metadata=row,
            metadata_extras={
                "release": self.release,
                "endpoint": phenocode,
                "endpoint_code": phenocode,
                "population": "Finnish",
                "num_cases": row.get("num_cases"),
                "num_controls": row.get("num_controls"),
                "download_url": download_url,
                "filename": download_url.rsplit("/", 1)[-1] if download_url else None,
            },
            match_score=match_score,
            raw_record=dict(row),
        )

    def probe_candidates(
        self,
        candidates: List[Dict[str, Any]],
        *,
        probe_limit: int,
        check_download: bool,
    ) -> List[Dict[str, Any]]:
        ordered = [dict(item) for item in sorted(candidates, key=self._candidate_sort_key)]
        self.last_probe_summary = {"probe_total": 0, "probe_success_count": 0, "probe_failure_count": 0}
        seen: set[str] = set()
        for item in ordered:
            key = str(item.get("study_id") or "").strip()
            if not key or key in seen or self.last_probe_summary["probe_total"] >= max(probe_limit, 0):
                continue
            downloadable, reason, check = self.evaluate_download(
                download_url=str(item.get("download_url") or "").strip() or None,
                check_download=check_download,
                reason_if_missing="no_summary_stats",
            )
            item["downloadable"] = downloadable
            item["downloadability_reason"] = reason
            if check is not None:
                item["_download_check"] = check
            self.last_probe_summary["probe_total"] += 1
            if downloadable:
                self.last_probe_summary["probe_success_count"] += 1
            else:
                self.last_probe_summary["probe_failure_count"] += 1
            seen.add(key)
        self.last_source_stats = self.with_cache_stats(
            {
                **dict(self.last_source_stats),
                "probe_budget": probe_limit,
                "probe_count": self.last_probe_summary["probe_total"],
            }
        )
        return ordered

    @staticmethod
    def _candidate_sort_key(item: Dict[str, Any]) -> tuple[int, int, str]:
        return (
            -int(item.get("_match_score") or 0),
            -int(item.get("sample_size") or 0),
            str(item.get("study_id") or ""),
        )

    def _fetch_manifest_rows(self) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        cache_key = self.stable_hash(
            {"manifest_url": self.manifest_url, "release": self.release}
        )
        found, payload = self.cached_json_get("manifest_rows", cache_key)
        if found and isinstance(payload, dict):
            rows = payload.get("rows")
            stats = payload.get("stats")
            if isinstance(rows, list) and isinstance(stats, dict):
                return [
                    dict(item)
                    for item in rows
                    if isinstance(item, dict)
                ], dict(stats)
        blob_found, blob = self.cached_bytes_get("manifest_blob", cache_key)
        if not blob_found or not isinstance(blob, bytes):
            blob = self.download_bytes_with_progress(
                self.manifest_url,
                label=f"FinnGen {self.release} manifest",
            )
            self.cached_bytes_set("manifest_blob", cache_key, blob)
        rows, stats = read_tsv_rows_with_progress(
            blob,
            label=f"FinnGen {self.release} manifest",
        )
        self.cached_json_set(
            "manifest_rows",
            cache_key,
            {"rows": rows, "stats": stats},
        )
        return rows, stats

    def _search_via_autocomplete(
        self,
        *,
        query: str,
        check_download: bool,
    ) -> List[Dict[str, Any]]:
        if not self.autocomplete_endpoint:
            raise SearchError("FinnGen autocomplete endpoint is not configured.", status="config_error")

        log_step(f'Fetching FinnGen autocomplete candidates for query="{query}".')
        autocomplete_items = self._fetch_autocomplete(query)
        log_step(f'Fetched FinnGen autocomplete candidates for query="{query}": results={len(autocomplete_items)}.')

        candidates = self._extract_pheno_candidates(autocomplete_items)
        results: List[Dict[str, Any]] = []
        for candidate in candidates:
            pheno = candidate["pheno"]
            display = candidate["display"]
            detail = self._fetch_pheno_detail(pheno)
            scored = self._score_trait_match(
                query,
                primary_values=[
                    ("display", display),
                    ("phenostring", detail.get("phenostring")),
                    ("longname", detail.get("longname")),
                    ("name", detail.get("name")),
                ],
                auxiliary_values=[
                    ("phenocode", pheno),
                    ("category", detail.get("category")),
                ],
            )
            if scored is None:
                continue
            match_score, matched_fields = scored
            result = self._candidate_from_pheno(
                query=query,
                pheno=pheno,
                display=display,
                detail=detail,
                check_download=check_download,
                match_score=match_score,
                matched_fields=matched_fields,
            )
            results.append(result)

        results.sort(key=lambda item: item.get("_match_score", 0), reverse=True)
        return results

    def _search_via_phenos_scan(
        self,
        *,
        query: str,
        check_download: bool,
    ) -> List[Dict[str, Any]]:
        if not self.phenos_api:
            raise SearchError("FinnGen phenotype API is not configured.", metadata_endpoint=self.phenos_api)

        log_step(f'Fetching FinnGen phenotypes for query="{query}".')
        phenos = self._fetch_phenos()
        if not isinstance(phenos, list):
            raise SearchError("FinnGen phenotype API returned an unexpected payload.", metadata_endpoint=self.phenos_api)
        log_step(f'Fetched FinnGen phenotypes for query="{query}": results={len(phenos)}.')

        results: List[Dict[str, Any]] = []
        for row in phenos:
            if not isinstance(row, dict):
                continue
            phenocode = str(row.get("phenocode") or "").strip()
            if not phenocode:
                continue
            scored = self._score_trait_match(
                query,
                primary_values=[
                    ("longname", row.get("longname")),
                    ("phenostring", row.get("phenostring")),
                ],
                auxiliary_values=[
                    ("phenocode", phenocode),
                    ("category", row.get("category")),
                ],
            )
            if scored is None:
                continue
            match_score, matched_fields = scored

            download_url = self._build_download_url(phenocode)
            downloadable, downloadability_reason, download_check = self.evaluate_download(
                download_url=download_url,
                check_download=check_download,
                reason_if_missing="no_summary_stats",
            )
            if check_download and download_url:
                self.last_probe_summary["probe_total"] += 1
                if downloadable:
                    self.last_probe_summary["probe_success_count"] += 1
                else:
                    self.last_probe_summary["probe_failure_count"] += 1
            n_cases = parse_int(row.get("num_cases"))
            n_controls = parse_int(row.get("num_controls"))
            sample_size = None
            if n_cases is not None and n_controls is not None:
                sample_size = n_cases + n_controls
            elif n_cases is not None:
                sample_size = n_cases
            elif n_controls is not None:
                sample_size = n_controls

            results.append(
                build_candidate(
                    side=None,
                    trait=str(row.get("longname") or row.get("phenostring") or query),
                    study_id=f"finngen_{self.release}_{phenocode}",
                    source=self.source_name,
                    ancestry_value=row.get("population") or "Finnish",
                    sample_size=sample_size,
                    n_cases=n_cases,
                    n_controls=n_controls,
                    downloadable=downloadable,
                    download_url=download_url,
                    auth_required=False,
                    requires_user_confirmation=False,
                    downloadability_reason=downloadability_reason,
                    download_check=download_check,
                    matched_fields=matched_fields,
                    matched_query=None,
                    raw_metadata=row,
                    metadata_extras={
                        "release": self.release,
                        "endpoint": phenocode,
                        "endpoint_code": phenocode,
                        "population": row.get("population") or "Finnish",
                        "num_cases": row.get("num_cases"),
                        "num_controls": row.get("num_controls"),
                        "download_url": download_url,
                    },
                    match_score=match_score,
                    raw_record=dict(row),
                )
            )

        results.sort(key=lambda item: item.get("_match_score", 0), reverse=True)
        return results

    def _extract_pheno_candidates(self, items: list[dict[str, Any]]) -> list[dict[str, str]]:
        seen: set[str] = set()
        candidates: list[dict[str, str]] = []
        for item in items:
            pheno = str(item.get("pheno") or "").strip()
            if not pheno or pheno in seen:
                continue
            seen.add(pheno)
            candidates.append(
                {
                    "pheno": pheno,
                    "display": str(item.get("display") or "").strip(),
                }
            )
        return candidates

    def _score_trait_match(
        self,
        query: str,
        *,
        primary_values: list[tuple[str, Any]],
        auxiliary_values: list[tuple[str, Any]] | None = None,
    ) -> tuple[int, list[str]] | None:
        query_norm = self.normalize_text(query)
        query_tokens = list(dict.fromkeys(semantic_tokens(query)))
        if not query_norm or not query_tokens:
            return None

        fields: list[str] = []
        score = 0
        primary_tokens: set[str] = set()
        primary_exact = False
        for field, value in primary_values:
            value_norm = self.normalize_text(str(value or ""))
            value_tokens = set(semantic_tokens(value))
            if not value_norm and not value_tokens:
                continue
            if value_norm and query_norm == value_norm:
                primary_exact = True
                score += 120
                fields.append(field)
            overlap = token_overlap(query_tokens, value_tokens)
            if overlap:
                score += overlap * 30
                fields.append(field)
                primary_tokens.update(value_tokens)

        required_overlap = required_token_overlap(
            query_tokens,
            short_query_token_count=3,
            min_coverage=0.7,
        )
        primary_overlap = token_overlap(query_tokens, primary_tokens)

        aux_exact_fields: list[str] = []
        aux_scored_fields: list[str] = []
        aux_score = 0
        for field, value in auxiliary_values or []:
            value_norm = self.normalize_text(str(value or ""))
            value_tokens = set(semantic_tokens(value))
            if value_norm and query_norm == value_norm:
                aux_exact_fields.append(field)
                aux_score += 40
                continue
            overlap = token_overlap(query_tokens, value_tokens)
            if overlap:
                aux_scored_fields.append(field)
                aux_score += overlap * 3

        if not primary_exact and primary_overlap < required_overlap:
            if aux_exact_fields:
                return 90 + aux_score, sorted(set(aux_exact_fields))
            return None

        fields.extend(aux_exact_fields)
        fields.extend(aux_scored_fields)
        score += aux_score
        return score, sorted(set(fields))

    def _fetch_autocomplete(self, query: str) -> list[dict[str, Any]]:
        cache_key = self.stable_hash({"endpoint": self.autocomplete_endpoint, "query": query})
        found, payload = self.cached_json_get("autocomplete", cache_key)
        if found and isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        try:
            result = self.get_json(self.autocomplete_endpoint, params={"query": query})
        except Exception as exc:
            raise SearchError(
                f"FinnGen autocomplete request failed: {exc}",
                status="network_error",
                metadata_endpoint=self.autocomplete_endpoint,
            ) from exc
        if not isinstance(result, list):
            return []
        filtered = [item for item in result if isinstance(item, dict)]
        self.cached_json_set("autocomplete", cache_key, filtered)
        return filtered

    def _fetch_pheno_detail(self, pheno: str) -> dict[str, Any]:
        cache_key = self.stable_hash({"template": self.pheno_endpoint_template, "pheno": pheno})
        found, payload = self.cached_json_get("pheno_detail", cache_key)
        if found and isinstance(payload, dict):
            return dict(payload)
        endpoint = self._pheno_endpoint(pheno)
        try:
            result = self.get_json(endpoint)
        except Exception:
            return {}
        if not isinstance(result, dict):
            return {}
        self.cached_json_set("pheno_detail", cache_key, result)
        return dict(result)

    def _pheno_endpoint(self, pheno: str) -> str:
        if "{pheno}" in self.pheno_endpoint_template:
            return self.pheno_endpoint_template.replace("{pheno}", pheno)
        return f"{self.pheno_endpoint_template.rstrip('/')}/{pheno}"

    def _candidate_from_pheno(
        self,
        *,
        query: str,
        pheno: str,
        display: str,
        detail: dict[str, Any],
        check_download: bool,
        match_score: int = 100,
        matched_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        n_cases = parse_int(detail.get("num_cases"))
        n_controls = parse_int(detail.get("num_controls"))
        sample_size = None
        if n_cases is not None and n_controls is not None:
            sample_size = n_cases + n_controls
        elif n_cases is not None:
            sample_size = n_cases
        elif n_controls is not None:
            sample_size = n_controls

        download_url = self._build_download_url(pheno)
        downloadable, downloadability_reason, download_check = self.evaluate_download(
            download_url=download_url,
            check_download=check_download,
            reason_if_missing="no_summary_stats",
        )
        if check_download and download_url:
            self.last_probe_summary["probe_total"] += 1
            if downloadable:
                self.last_probe_summary["probe_success_count"] += 1
            else:
                self.last_probe_summary["probe_failure_count"] += 1

        trait = self._resolve_trait_label(detail=detail, display=display, pheno=pheno, fallback=query)
        category = detail.get("category")
        if category in (None, ""):
            category = None
        return build_candidate(
            side=None,
            trait=trait,
            study_id=f"finngen_{self.release}_{pheno}",
            source=self.source_name,
            ancestry_value=detail.get("population") or "Finnish",
            sample_size=sample_size,
            n_cases=n_cases,
            n_controls=n_controls,
            downloadable=downloadable,
            download_url=download_url,
            auth_required=False,
            requires_user_confirmation=False,
            downloadability_reason=downloadability_reason,
            download_check=download_check,
            matched_fields=matched_fields or ["autocomplete"],
            matched_query=query,
            raw_metadata=detail,
            metadata_extras={
                "release": self.release,
                "endpoint": pheno,
                "endpoint_code": pheno,
                "population": detail.get("population") or "Finnish",
                "num_cases": detail.get("num_cases"),
                "num_controls": detail.get("num_controls"),
                "download_url": download_url,
                "category": category,
            },
            match_score=match_score,
            raw_record={"autocomplete_display": display, **dict(detail)},
        )

    def _resolve_trait_label(self, *, detail: dict[str, Any], display: str, pheno: str, fallback: str) -> str:
        for key in ("phenostring", "longname", "name"):
            value = str(detail.get(key) or "").strip()
            if value:
                return value
        text = str(display or "").strip()
        if text:
            suffix = f"({pheno})"
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip()
            if text:
                return text
        return str(fallback or pheno)

    def _fetch_phenos(self) -> list[dict[str, Any]]:
        cache_key = self.stable_hash({"endpoint": self.phenos_api, "release": self.release})
        found, payload = self.cached_json_get("phenos", cache_key)
        if found and isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        phenos = self.get_json(self.phenos_api)
        if isinstance(phenos, list):
            filtered = [item for item in phenos if isinstance(item, dict)]
            self.cached_json_set("phenos", cache_key, filtered)
            return filtered
        return []

    def _build_download_url(self, phenocode: str) -> str | None:
        if not self.download_url_template:
            return None
        return self.download_url_template.format(release=self.release, endpoint=phenocode)


if __name__ == "__main__":
    parser = build_parser("Search FinnGen by trait query")
    args = parser.parse_args()
    searcher = FinnGenSearcher()
    with redirect_stdout(sys.stderr):
        try:
            payload = package_success(
                query=args.query,
                source=searcher.source_name,
                results=searcher.search(args.query, limit=args.limit, check_download=args.check_download),
            )
        except Exception as exc:
            payload = package_error(args.query, searcher.source_name, exc)
    write_json(payload, args.out)
