from __future__ import annotations

from contextlib import redirect_stdout
import sys

import os
from typing import Any, Dict, Iterable, List

from .common import (
    BaseSearcher,
    SearchError,
    build_candidate,
    build_parser,
    extract_publication_metadata,
    extract_trait_text,
    log_step,
    package_error,
    package_success,
    parse_int,
    semantic_tokens,
    source_config,
    source_metadata_endpoint,
    token_coverage,
    write_json,
)


class OpenGWASSearcher(BaseSearcher):
    source_name = "opengwas"
    default_initial_probe_budget = 10
    default_max_probe_budget = 20
    expired_download_url_status_codes = frozenset({403, 404, 410})
    min_semantic_token_coverage = 0.5
    short_query_token_count = 2
    semantic_match_fields = frozenset({"trait", "note"})
    semantic_stopwords = frozenset(
        {
            "a",
            "an",
            "and",
            "at",
            "by",
            "for",
            "in",
            "of",
            "on",
            "or",
            "the",
            "to",
            "versus",
            "vs",
            "with",
        }
    )

    def __init__(self, timeout: int = 30) -> None:
        super().__init__(timeout=timeout)
        config = source_config(self.source_name)
        self.jwt = (os.getenv(str(config.get("auth_env") or "OPENGWAS_JWT")) or "").strip()
        self.gwasinfo_endpoint = str(config.get("metadata_endpoint") or source_metadata_endpoint(self.source_name) or "").strip()
        self.files_endpoint = str(config.get("files_endpoint") or "").strip()
        if self.jwt:
            self.session.headers.update({"Authorization": f"Bearer {self.jwt}"})
        self.last_probe_summary: dict[str, int] = {}
        self.last_source_stats: dict[str, Any] = {}

    def search(
        self,
        query: str,
        limit: int = 30,
        check_download: bool = False,
    ) -> List[Dict[str, Any]]:
        self.last_probe_summary = {"probe_total": 0, "probe_success_count": 0, "probe_failure_count": 0}
        self.reset_cache_stats()
        self.last_source_stats = self.with_cache_stats({})
        if not self.jwt:
            raise SearchError(
                "OpenGWAS metadata search requires OPENGWAS_JWT; skipping this source without treating it as a 404.",
                status="auth_required",
                metadata_endpoint=self.gwasinfo_endpoint,
            )
        if not self.gwasinfo_endpoint:
            raise SearchError("OpenGWAS metadata endpoint is not configured.", metadata_endpoint=self.gwasinfo_endpoint)

        log_step(f'Fetching OpenGWAS metadata for query="{query}".')
        studies = self._fetch_metadata()
        log_step(f'Fetched OpenGWAS metadata for query="{query}": results={len(studies)}.')
        pre_filter_candidate_count = 0
        relevance_rejected_count = 0
        results: List[Dict[str, Any]] = []
        for study in studies:
            scored = self._score_study(query, study)
            if scored is None:
                continue
            pre_filter_candidate_count += 1
            match_score, matched_fields, study_id, trait_text, note_text = scored
            if not self._is_relevant_match(
                query=query,
                matched_fields=matched_fields,
                trait_text=trait_text,
                note_text=note_text,
            ):
                relevance_rejected_count += 1
                continue
            candidate = self._candidate_from_study(
                query=query,
                study=study,
                match_score=match_score,
                matched_fields=matched_fields,
            )
            if candidate is not None:
                results.append(candidate)

        ordered = sorted(results, key=self._candidate_sort_key)
        limited = ordered[:limit]
        self.last_source_stats = self.with_cache_stats(
            {
                "matched_candidate_count": len(ordered),
                "pre_filter_candidate_count": pre_filter_candidate_count,
                "relevance_rejected_count": relevance_rejected_count,
                "probe_budget_initial": 0,
                "probe_budget_final": 0,
                "probe_budget": 0,
                "probe_count": 0,
            }
        )
        if check_download and limited:
            probe_limit = min(max(limit, 1), self.default_max_probe_budget)
            limited = self.probe_candidates(
                limited,
                probe_limit=probe_limit,
                check_download=check_download,
            )
        return limited

    def search_by_id(
        self,
        study_id: str,
        *,
        check_download: bool = False,
    ) -> List[Dict[str, Any]]:
        """Resolve one OpenGWAS study ID into the same candidate shape as search()."""

        normalized_id = str(study_id or "").strip()
        self.last_probe_summary = {"probe_total": 0, "probe_success_count": 0, "probe_failure_count": 0}
        self.reset_cache_stats()
        self.last_source_stats = self.with_cache_stats({})
        if not normalized_id:
            return []
        if not self.jwt:
            raise SearchError(
                "OpenGWAS metadata search requires OPENGWAS_JWT; skipping this source without treating it as a 404.",
                status="auth_required",
                metadata_endpoint=self.gwasinfo_endpoint,
            )
        studies = self._fetch_metadata()
        for study in studies:
            candidate_id = str(study.get("id") or study.get("study_id") or study.get("ieu_id") or "").strip()
            if candidate_id != normalized_id:
                continue
            trait_text = extract_trait_text(study.get("trait")) or normalized_id
            (
                download_url,
                downloadable,
                downloadability_reason,
                probe_result,
            ) = self._evaluate_study_download(
                normalized_id,
                check_download=check_download,
            )
            if check_download and (download_url or probe_result is not None):
                self.last_probe_summary["probe_total"] = 1
                if downloadable:
                    self.last_probe_summary["probe_success_count"] = 1
                else:
                    self.last_probe_summary["probe_failure_count"] = 1
            candidate = self._candidate_from_study(
                query=trait_text,
                study=study,
                match_score=10000,
                matched_fields=["id"],
                download_url=download_url,
                downloadability_reason=downloadability_reason,
                download_check=probe_result,
                downloadable=downloadable,
            )
            self.last_source_stats = self.with_cache_stats(
                {
                    "search_mode": "id",
                    "matched_candidate_count": 1 if candidate else 0,
                    "pre_filter_candidate_count": 1,
                    "relevance_rejected_count": 0,
                    "probe_budget": self.last_probe_summary["probe_total"],
                    "probe_count": self.last_probe_summary["probe_total"],
                }
            )
            return [candidate] if candidate is not None else []
        self.last_source_stats = self.with_cache_stats(
            {
                "search_mode": "id",
                "matched_candidate_count": 0,
                "pre_filter_candidate_count": 0,
                "probe_budget": 0,
                "probe_count": 0,
            }
        )
        return []

    def probe_candidates(
        self,
        candidates: List[Dict[str, Any]],
        *,
        probe_limit: int,
        check_download: bool,
    ) -> List[Dict[str, Any]]:
        ordered = [dict(item) for item in sorted(candidates, key=self._candidate_sort_key)]
        total_candidates = len(ordered)
        self.last_probe_summary = {"probe_total": 0, "probe_success_count": 0, "probe_failure_count": 0}
        if not check_download or total_candidates == 0:
            stats = dict(self.last_source_stats)
            stats.update(
                {
                    "probe_budget_initial": 0,
                    "probe_budget_final": 0,
                    "probe_budget": 0,
                    "probe_count": 0,
                }
            )
            self.last_source_stats = self.with_cache_stats(stats)
            return ordered

        max_budget = min(max(probe_limit, 0), total_candidates, self.default_max_probe_budget)
        if max_budget <= 0:
            stats = dict(self.last_source_stats)
            stats.update(
                {
                    "probe_budget_initial": 0,
                    "probe_budget_final": 0,
                    "probe_budget": 0,
                    "probe_count": 0,
                }
            )
            self.last_source_stats = self.with_cache_stats(stats)
            return ordered

        initial_budget = min(self.default_initial_probe_budget, max_budget)
        self._probe_candidates_to_budget(
            ordered,
            target_budget=initial_budget,
            check_download=check_download,
        )
        has_downloadable = any(
            item.get("downloadable")
            for item in ordered
            if self._is_candidate_probed(item)
        )
        final_budget = initial_budget
        if not has_downloadable and max_budget > initial_budget:
            final_budget = max_budget
            self._probe_candidates_to_budget(
                ordered,
                target_budget=final_budget,
                check_download=check_download,
            )

        probed_items = [item for item in ordered if self._is_candidate_probed(item)]
        probe_success_count = sum(1 for item in probed_items if bool(item.get("downloadable")))
        self.last_probe_summary = {
            "probe_total": len(probed_items),
            "probe_success_count": probe_success_count,
            "probe_failure_count": max(len(probed_items) - probe_success_count, 0),
        }
        stats = dict(self.last_source_stats)
        stats.update(
            {
                "probe_budget_initial": initial_budget,
                "probe_budget_final": final_budget,
                "probe_budget": final_budget,
                "probe_count": self.last_probe_summary["probe_total"],
            }
        )
        self.last_source_stats = self.with_cache_stats(stats)
        return ordered

    def _probe_candidates_to_budget(
        self,
        candidates: List[Dict[str, Any]],
        *,
        target_budget: int,
        check_download: bool,
    ) -> None:
        if target_budget <= 0:
            return
        probe_index = sum(1 for item in candidates if self._is_candidate_probed(item))
        for item in candidates:
            if probe_index >= target_budget:
                break
            if self._is_candidate_probed(item):
                continue
            study_id = str(item.get("study_id") or "").strip()
            if not study_id:
                continue
            (
                download_url,
                downloadable,
                downloadability_reason,
                probe_result,
            ) = self._evaluate_study_download(
                study_id,
                check_download=check_download,
            )
            item["downloadable"] = downloadable
            item["download_url"] = download_url
            item["downloadability_reason"] = downloadability_reason
            if probe_result is not None:
                item["_download_check"] = probe_result
            metadata = dict(item.get("study_metadata") or {})
            if download_url:
                metadata["download_url"] = download_url
            item["study_metadata"] = metadata
            probe_index += 1

    def _score_study(
        self,
        query: str,
        study: dict[str, Any] | Any,
    ) -> tuple[int, list[str], str, str, str] | None:
        if not isinstance(study, dict):
            return None
        study_id = str(study.get("id") or study.get("study_id") or study.get("ieu_id") or "").strip()
        if not study_id:
            return None
        trait_text = extract_trait_text(study.get("trait"))
        note_text = extract_trait_text(study.get("note"))
        match_score, matched_fields = self.score_match(
            query,
            [
                ("trait", trait_text),
                ("note", note_text),
                ("consortium", study.get("consortium")),
                ("author", study.get("author")),
                ("category", study.get("category")),
                ("subcategory", study.get("subcategory")),
                ("population", study.get("population")),
                ("id", study_id),
            ],
        )
        if match_score <= 0:
            return None
        return match_score, matched_fields, study_id, trait_text, note_text

    def _is_relevant_match(
        self,
        *,
        query: str,
        matched_fields: list[str],
        trait_text: str,
        note_text: str,
    ) -> bool:
        if not any(field in self.semantic_match_fields for field in matched_fields):
            return False
        query_tokens = self._semantic_tokens(query)
        if not query_tokens:
            return False
        token_coverage = self._token_coverage_for_tokens(
            query_tokens,
            [trait_text, note_text],
        )
        required_coverage = (
            1.0
            if len(query_tokens) <= self.short_query_token_count
            else self.min_semantic_token_coverage
        )
        return token_coverage >= required_coverage

    def _token_coverage(self, query: str, values: list[str]) -> float:
        query_tokens = self._semantic_tokens(query)
        return self._token_coverage_for_tokens(query_tokens, values)

    def _token_coverage_for_tokens(
        self,
        query_tokens: list[str],
        values: list[str],
    ) -> float:
        return token_coverage(
            query_tokens,
            values,
            stopwords=self.semantic_stopwords,
        )

    def _semantic_tokens(self, text: str) -> list[str]:
        return semantic_tokens(text, stopwords=self.semantic_stopwords)

    def _is_candidate_probed(self, item: Dict[str, Any]) -> bool:
        return str(item.get("downloadability_reason") or "") != "unresolved"

    def _candidate_from_study(
        self,
        *,
        query: str,
        study: dict[str, Any],
        match_score: int,
        matched_fields: list[str],
        download_url: str | None = None,
        downloadability_reason: str = "unresolved",
        download_check: dict[str, Any] | None = None,
        downloadable: bool = False,
    ) -> dict[str, Any] | None:
        study_id = str(study.get("id") or study.get("study_id") or study.get("ieu_id") or "").strip()
        if not study_id:
            return None
        raw_study = dict(study)
        n_cases = parse_int(raw_study.get("ncase")) or parse_int(raw_study.get("n_cases"))
        n_controls = parse_int(raw_study.get("ncontrol")) or parse_int(raw_study.get("n_controls"))
        sample_size = self.stable_sample_size(raw_study)
        return build_candidate(
            side=None,
            trait=extract_trait_text(raw_study.get("trait")) or query,
            study_id=study_id,
            source=self.source_name,
            ancestry_value=raw_study.get("population") or raw_study.get("ancestry") or raw_study.get("pop"),
            sample_size=sample_size or None,
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
            raw_metadata=raw_study,
            metadata_extras={
                "population": raw_study.get("population"),
                "sample_size": raw_study.get("sample_size"),
                "ncase": raw_study.get("ncase"),
                "ncontrol": raw_study.get("ncontrol"),
                **extract_publication_metadata(raw_study),
            },
            match_score=match_score,
            raw_record=raw_study,
        )

    @staticmethod
    def _candidate_sort_key(item: Dict[str, Any]) -> tuple[int, int, int, str]:
        sample_size = BaseSearcher.stable_sample_size(
            {
                "sample_size": item.get("sample_size"),
                **(item.get("study_metadata", {}) or {}),
            }
        )
        publication_year = BaseSearcher.stable_publication_year(item.get("study_metadata", {}) or {})
        return (
            -int(item.get("_match_score") or 0),
            -sample_size,
            -publication_year,
            str(item.get("study_id") or ""),
        )

    def _fetch_metadata(self) -> list[dict[str, Any]]:
        cache_key = self.stable_hash(
            {
                "endpoint": self.gwasinfo_endpoint,
                "jwt_hash": self.stable_hash(self.jwt),
            }
        )
        found, payload = self.cached_json_get("metadata", cache_key)
        if found and isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        payload = self.get_json(self.gwasinfo_endpoint)
        if isinstance(payload, list):
            studies = [item for item in payload if isinstance(item, dict)]
            self.cached_json_set("metadata", cache_key, studies)
            return studies
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                studies = [item for item in payload["data"] if isinstance(item, dict)]
                self.cached_json_set("metadata", cache_key, studies)
                return studies
            dict_values = [item for item in payload.values() if isinstance(item, dict)]
            if dict_values:
                self.cached_json_set("metadata", cache_key, dict_values)
                return dict_values
        return []

    def _evaluate_study_download(
        self,
        study_id: str,
        *,
        check_download: bool,
    ) -> tuple[str | None, bool, str, dict[str, Any] | None]:
        download_url, download_check = self._resolve_download_url(study_id)
        downloadable, downloadability_reason, probe_result = self.evaluate_download(
            download_url=download_url,
            check_download=check_download,
            auth_required=False,
            reason_if_missing="no_summary_stats",
        )
        if probe_result is None:
            probe_result = download_check
        if not check_download or downloadable or not self._is_expired_download_url_check(probe_result):
            return download_url, downloadable, downloadability_reason, probe_result

        status_code = probe_result.get("status_code") if isinstance(probe_result, dict) else None
        status_text = f" with HTTP {status_code}" if status_code is not None else ""
        log_step(f"OpenGWAS URL probe failed{status_text}; refreshing files URL for {study_id}.", error=True)
        refreshed_url, refreshed_check = self._resolve_download_url(study_id, force_refresh=True)
        if not refreshed_url:
            return refreshed_url, False, "url_refresh_failed", refreshed_check
        refreshed_downloadable, refreshed_reason, refreshed_probe = self.evaluate_download(
            download_url=refreshed_url,
            check_download=True,
            auth_required=False,
            reason_if_missing="no_summary_stats",
        )
        if refreshed_probe is None:
            refreshed_probe = refreshed_check
        return refreshed_url, refreshed_downloadable, refreshed_reason, refreshed_probe

    @classmethod
    def _is_expired_download_url_check(cls, download_check: Any) -> bool:
        if not isinstance(download_check, dict):
            return False
        status_code = download_check.get("status_code")
        return isinstance(status_code, int) and status_code in cls.expired_download_url_status_codes

    def _resolve_download_url(self, study_id: str, *, force_refresh: bool = False) -> tuple[str | None, dict[str, Any] | None]:
        if not self.files_endpoint:
            return None, None
        cache_key = self.stable_hash(
            {
                "study_id": study_id,
                "jwt_hash": self.stable_hash(self.jwt),
            }
        )
        found, payload = self.memo_get("files", cache_key)
        if not force_refresh and found and isinstance(payload, dict):
            download_url = str(payload.get("download_url") or "").strip() or None
            download_check = payload.get("download_check")
            if isinstance(download_check, dict) or download_check is None:
                return download_url, download_check
        try:
            payload = self.post_json(self.files_endpoint, {"id": [study_id]})
        except Exception as exc:
            result = (None, {"method": "POST", "ok": False, "error": str(exc), "final_url": self.files_endpoint})
            self.memo_set(
                "files",
                cache_key,
                {"download_url": result[0], "download_check": result[1]},
            )
            return result
        urls = list(self._iter_urls(payload))
        chosen = self._pick_download_url(urls)
        if not chosen:
            result = (
                None,
                {"method": "POST", "ok": False, "error": "No downloadable file URL returned.", "final_url": self.files_endpoint},
            )
            self.memo_set(
                "files",
                cache_key,
                {"download_url": result[0], "download_check": result[1]},
            )
            return result
        result = (chosen, {"method": "POST", "ok": True, "final_url": self.files_endpoint, "resolved_url": chosen})
        self.memo_set(
            "files",
            cache_key,
            {"download_url": result[0], "download_check": result[1]},
        )
        return result

    def _iter_urls(self, payload: Any) -> Iterable[str]:
        if isinstance(payload, dict):
            for value in payload.values():
                yield from self._iter_urls(value)
            return
        if isinstance(payload, list):
            for item in payload:
                yield from self._iter_urls(item)
            return
        if isinstance(payload, str) and payload.startswith(("http://", "https://")):
            yield payload

    def _pick_download_url(self, urls: Iterable[str]) -> str | None:
        preferred: list[str] = []
        fallback: list[str] = []
        for url in urls:
            lowered = url.lower()
            if lowered.endswith((".vcf.gz", ".tsv.gz", ".txt.gz", ".gz")) and not lowered.endswith((".tbi", "_report.html")):
                preferred.append(url)
            elif "download" in lowered or "vcf" in lowered:
                fallback.append(url)
        if preferred:
            return preferred[0]
        if fallback:
            return fallback[0]
        return None


if __name__ == "__main__":
    parser = build_parser("Search OpenGWAS by trait query")
    args = parser.parse_args()
    searcher = OpenGWASSearcher()
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
