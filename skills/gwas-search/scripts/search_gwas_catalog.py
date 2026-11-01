from __future__ import annotations

from contextlib import redirect_stdout
import sys

import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote, urlencode, urljoin, urlparse

from requests import HTTPError, RequestException

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
    parse_initial_sample_size,
    required_token_overlap,
    semantic_tokens,
    source_config,
    token_overlap,
    write_json,
)


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
                return


class GWASCatalogSearcher(BaseSearcher):
    source_name = "gwas_catalog"
    default_probe_budget = 12
    tabular_summary_suffixes = (
        ".tsv.gz",
        ".tsv",
        ".txt.gz",
        ".txt",
        ".csv.gz",
        ".csv",
    )
    archive_summary_suffixes = (".zip",)
    non_data_name_tokens = (
        "readme",
        "metadata",
        "manifest",
        "documentation",
        "license",
        "notes",
        "md5sum",
        "checksum",
        "sha1sum",
        "sha256sum",
        "sha512sum",
    )

    def __init__(self, timeout: int = 30) -> None:
        super().__init__(timeout=timeout)
        config = source_config(self.source_name)
        self.base_api = "https://www.ebi.ac.uk/gwas/rest/api/v2"
        self.primary_endpoint = str(config.get("metadata_endpoint") or f"{self.base_api}/studies").strip()
        self.summary_statistics_base = str(config.get("summary_statistics_base") or "").rstrip("/")
        patterns = config.get("summary_statistics_patterns") or []
        self.summary_statistics_patterns = [str(item).strip() for item in patterns if str(item).strip()]
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
        log_step(f'Fetching GWAS Catalog studies for query="{query}".')
        studies = self._search_studies(query)
        log_step(f'Fetched GWAS Catalog studies for query="{query}": results={len(studies)}.')
        results: List[Dict[str, Any]] = []
        for study in studies:
            candidate = self._candidate_from_study(query, study)
            if candidate is not None:
                results.append(candidate)

        results.sort(key=self._candidate_sort_key)
        self.last_source_stats = {
            **self.last_source_stats,
            "matched_candidate_count": len(results),
            "matched_row_count": len(studies),
            "unique_candidate_count": len(results),
            "probe_budget": 0,
            "probe_count": 0,
        }
        self.last_source_stats = self.with_cache_stats(self.last_source_stats)
        if check_download and results:
            probe_budget = min(max(limit, 1), self.default_probe_budget)
            results = self.probe_candidates(
                results,
                probe_limit=probe_budget,
                check_download=check_download,
            )
        return results[:limit]

    def search_by_id(
        self,
        study_id: str,
        *,
        check_download: bool = False,
    ) -> List[Dict[str, Any]]:
        """Resolve one GWAS Catalog accession into the same candidate shape as search()."""

        normalized_id = str(study_id or "").strip()
        self.last_probe_summary = {"probe_total": 0, "probe_success_count": 0, "probe_failure_count": 0}
        self.reset_cache_stats()
        self.last_source_stats = self.with_cache_stats({})
        if not normalized_id:
            return []
        study = self._fetch_study_by_accession(normalized_id)
        if study is None:
            self.last_source_stats = self.with_cache_stats({"search_mode": "id", "matched_candidate_count": 0})
            return []
        candidate = self._candidate_from_study(
            normalized_id,
            study,
            allow_id_match=True,
        )
        if candidate is None:
            self.last_source_stats = self.with_cache_stats({"search_mode": "id", "matched_candidate_count": 0})
            return []
        candidate["_match_score"] = 10000
        if str(candidate.get("downloadability_reason") or "") == "no_summary_stats":
            self._log_no_full_summary_statistics(normalized_id)
        if check_download:
            candidate = self.probe_candidates([candidate], probe_limit=1, check_download=True)[0]
        self.last_source_stats = self.with_cache_stats(
            {
                **dict(self.last_source_stats or {}),
                "search_mode": "id",
                "matched_candidate_count": 1,
                "probe_budget": self.last_probe_summary["probe_total"],
                "probe_count": self.last_probe_summary["probe_total"],
            }
        )
        return [candidate]

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
        probeable = [
            item
            for item in ordered
            if str(item.get("downloadability_reason") or "") != "no_summary_stats"
        ]
        actual_budget = min(max(probe_limit, 0), len(probeable))
        probe_index = 0
        for item in ordered:
            if probe_index >= actual_budget:
                break
            if str(item.get("downloadability_reason") or "") == "no_summary_stats":
                continue
            study_id = str(item.get("study_id") or "").strip()
            if not study_id:
                continue
            probe_index += 1
            download_url, download_check = self._resolve_summary_stats_url(
                study_id,
            )
            downloadability_reason = str(item.get("downloadability_reason") or "unresolved")
            downloadable = False
            if download_url and isinstance(download_check, dict) and bool(download_check.get("ok")):
                downloadable = True
                downloadability_reason = "confirmed_url" if check_download else "resolved_url"
            elif download_check is not None:
                downloadability_reason = "probe_failed"
            item["downloadable"] = downloadable
            item["download_url"] = download_url
            item["downloadability_reason"] = downloadability_reason
            if download_check is not None:
                item["_download_check"] = download_check
            self.last_probe_summary["probe_total"] += 1
            if downloadable:
                self.last_probe_summary["probe_success_count"] += 1
            else:
                self.last_probe_summary["probe_failure_count"] += 1
        self.last_source_stats = {
            **self.last_source_stats,
            "matched_candidate_count": len(ordered),
            "matched_row_count": len(ordered),
            "unique_candidate_count": len(ordered),
            "probe_budget": probe_limit,
            "probe_count": self.last_probe_summary["probe_total"],
        }
        self.last_source_stats = self.with_cache_stats(self.last_source_stats)
        return ordered

    def _candidate_from_study(
        self,
        query: str,
        study: dict[str, Any] | Any,
        *,
        allow_id_match: bool = False,
    ) -> Dict[str, Any] | None:
        if not isinstance(study, dict):
            return None
        study_id = str(study.get("accession_id") or "").strip()
        if not study_id:
            return None
        disease_trait = extract_trait_text(study.get("disease_trait"))
        reported_trait = "; ".join(item.get("efo_trait", "") for item in study.get("efo_traits", []))

        match_score, matched_fields = self.score_match(
            query,
            [
                ("disease_trait", disease_trait),
                ("efo_traits", reported_trait),
                ("title", study.get("title")),
                ("accession_id", study_id),
            ],
        )
        if match_score <= 0:
            return None
        semantic_score, semantic_fields = self._score_trait_semantic_match(
            query,
            [
                ("disease_trait", disease_trait),
                ("efo_traits", reported_trait),
            ],
        )
        if semantic_score <= 0 and not allow_id_match:
            return None
        if semantic_score > 0:
            match_score = max(match_score, semantic_score)
            matched_fields = sorted(set([*matched_fields, *semantic_fields]))

        raw_study = {k: v for k, v in study.items() if k != "_links"}
        no_full_summary_stats = self._has_no_full_summary_statistics(raw_study)
        sample_size = parse_initial_sample_size(raw_study.get("initial_sample_size"))
        ancestry_value = raw_study.get("discovery_ancestry") or raw_study.get("initial_sample_size")
        flattened_trait = disease_trait or reported_trait or query
        publication = self._publication(raw_study.get("pubmed_id"))
        return build_candidate(
            side=None,
            trait=flattened_trait,
            study_id=study_id,
            source=self.source_name,
            ancestry_value=ancestry_value,
            sample_size=sample_size,
            n_cases=None,
            n_controls=None,
            downloadable=False,
            download_url=None,
            auth_required=False,
            requires_user_confirmation=False,
            downloadability_reason="no_summary_stats" if no_full_summary_stats else "unresolved",
            download_check=None,
            matched_fields=matched_fields,
            matched_query=None,
            raw_metadata=raw_study,
            metadata_extras={
                "population": ancestry_value,
                "sample_size": sample_size,
                "initialSampleSize": raw_study.get("initial_sample_size"),
                "replicationSampleSize": raw_study.get("replication_sample_size"),
                "pmid": raw_study.get("pubmed_id"),
                **extract_publication_metadata({"publication": publication}),
            },
            match_score=match_score,
            raw_record=raw_study,
            candidate_key=study_id,
        )

    def _score_trait_semantic_match(
        self,
        query: str,
        values: list[tuple[str, Any]],
    ) -> tuple[int, list[str]]:
        query_norm = self.normalize_text(query)
        query_tokens = list(dict.fromkeys(semantic_tokens(query)))
        if not query_norm or not query_tokens:
            return 0, []
        fields: list[str] = []
        score = 0
        value_tokens: set[str] = set()
        exact = False
        for field, value in values:
            value_norm = self.normalize_text(str(value or ""))
            tokens = set(semantic_tokens(value))
            if not value_norm and not tokens:
                continue
            if value_norm and query_norm == value_norm:
                exact = True
                score += 120
                fields.append(field)
            overlap = token_overlap(query_tokens, tokens)
            if overlap:
                score += overlap * 30
                fields.append(field)
                value_tokens.update(tokens)
        required_overlap = required_token_overlap(
            query_tokens,
            short_query_token_count=3,
            min_coverage=0.7,
        )
        if not exact and token_overlap(query_tokens, value_tokens) < required_overlap:
            return 0, []
        return score, sorted(set(fields))

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

    def _study_pages(self, **filters: str) -> list[dict[str, Any]]:
        url = f"{self.primary_endpoint}?{urlencode({**filters, 'size': 200})}"
        seen: set[str] = set()
        studies: dict[str, dict[str, Any]] = {}
        while url:
            if url in seen or not url.startswith(self.base_api + "/studies?"):
                raise SearchError("Invalid or repeated Catalog v2 pagination URL", metadata_endpoint=url)
            seen.add(url)
            data = self.get_json(url)
            if not isinstance(data, dict):
                raise SearchError("Invalid Catalog v2 collection response", metadata_endpoint=url)
            rows = data.get("_embedded", {}).get("studies")
            if rows is None and data.get("page", {}).get("totalElements") == 0:
                rows = []
            if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("accession_id") for row in rows):
                raise SearchError("Catalog v2 response lacks valid study records", metadata_endpoint=url)
            studies.update((row["accession_id"], row) for row in rows)
            link = data.get("_links", {}).get("next", {}).get("href")
            url = urljoin(url, link) if link else ""
        return list(studies.values())

    def _search_studies(self, query: str) -> list[dict[str, Any]]:
        cache_key = self.stable_hash({"query": self.normalize_text(query), "fields": ["disease_trait", "efo_trait"]})
        found, payload = self.cached_json_get("v2_study_search", cache_key)
        if found and isinstance(payload, list):
            return payload
        # Reported labels and ontology annotations cover complementary records.
        # A nonempty label search does not establish complete trait coverage.
        by_id = {}
        failures = []
        for filters in ({"disease_trait": query}, {"efo_trait": query, "show_child_traits": "false"}):
            try:
                for study in self._study_pages(**filters):
                    by_id.setdefault(study["accession_id"], study)
            except (RequestException, SearchError) as exc:
                failures.append((next(iter(filters)), exc))
        self.last_source_stats.update(
            search_complete=not failures,
            endpoint_failures=[{"field": field, "query": query, "error": str(exc)} for field, exc in failures],
        )
        if failures and not by_id:
            # A successful empty branch cannot establish absence when another failed.
            raise failures[0][1]
        studies = list(by_id.values())
        if not failures:
            self.cached_json_set("v2_study_search", cache_key, studies)
        return studies

    def _fetch_study_by_accession(self, study_id: str) -> dict[str, Any] | None:
        cache_key = self.stable_hash({"study_id": study_id})
        found, payload = self.cached_json_get("v2_study_by_accession", cache_key)
        if found and isinstance(payload, dict):
            return payload
        url = f"{self.base_api}/studies/{quote(study_id, safe='')}"
        try:
            payload = self.get_json(url)
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise
        if not isinstance(payload, dict) or payload.get("accession_id") != study_id:
            raise SearchError("Catalog v2 accession response does not match the requested study", metadata_endpoint=url)
        self.cached_json_set("v2_study_by_accession", cache_key, payload)
        return payload

    def _publication(self, pubmed_id: Any) -> dict[str, Any]:
        if not pubmed_id or self.last_source_stats.get("publication_enrichment_failed"):
            return {}
        cache_key = self.stable_hash({"pubmed_id": str(pubmed_id)})
        found, payload = self.cached_json_get("v2_publication", cache_key)
        if not found:
            try:
                payload = self.get_json(f"{self.base_api}/publications/{quote(str(pubmed_id), safe='')}")
            except RequestException as exc:
                # Bibliographic enrichment is optional. Keep the study's own
                # metadata and PMID, and stop hammering a failing endpoint.
                self.last_source_stats["publication_enrichment_failed"] = True
                self.last_source_stats.setdefault("endpoint_failures", []).append(
                    {"field": "publication", "pubmed_id": str(pubmed_id), "error": str(exc)}
                )
                return {}
            if not isinstance(payload, dict) or str(payload.get("pubmed_id")) != str(pubmed_id):
                raise SearchError("Invalid Catalog v2 publication response", metadata_endpoint=self.base_api)
            self.cached_json_set("v2_publication", cache_key, payload)
        return payload

    def _resolve_summary_stats_url(
        self,
        study_id: str,
    ) -> tuple[str | None, dict[str, Any] | None]:
        cache_key = self.stable_hash({"study_id": study_id})
        found, memo_value = self.memo_get("summary_url_probe", cache_key)
        if found and isinstance(memo_value, tuple) and len(memo_value) == 2:
            return memo_value[0], memo_value[1]
        found, payload = self.load_session_json("summary_url_success", cache_key)
        if found and isinstance(payload, dict):
            download_url = str(payload.get("download_url") or "").strip() or None
            download_check = payload.get("download_check")
            if download_url and isinstance(download_check, dict):
                result = (download_url, download_check)
                self.memo_set("summary_url_probe", cache_key, result)
                return result
        fixed_candidates = self._summary_url_candidates(study_id)
        for candidate in fixed_candidates:
            check = self.probe_download_url(candidate)
            if check.get("ok"):
                result = (candidate, check)
                self.memo_set("summary_url_probe", cache_key, result)
                self.save_session_json(
                    "summary_url_success",
                    cache_key,
                    {"download_url": candidate, "download_check": check},
                )
                return result
        fixed_candidate_set = set(fixed_candidates)
        discovered_candidates = [
            candidate
            for candidate in self._discovered_summary_url_candidates(study_id)
            if candidate not in fixed_candidate_set
        ]
        for candidate in discovered_candidates:
            check = self.probe_download_url(candidate)
            if check.get("ok"):
                result = (candidate, check)
                self.memo_set("summary_url_probe", cache_key, result)
                self.save_session_json(
                    "summary_url_success",
                    cache_key,
                    {"download_url": candidate, "download_check": check},
                )
                return result
        candidates = [*fixed_candidates, *discovered_candidates]
        if candidates:
            failed_url = candidates[0]
            result = (None, {"method": "HEAD", "ok": False, "final_url": failed_url})
            self.memo_set("summary_url_probe", cache_key, result)
            return result
        result = (None, None)
        self.memo_set("summary_url_probe", cache_key, result)
        return result

    def _summary_url_candidates(self, study_id: str) -> list[str]:
        study_dir = self._study_directory_url(study_id)
        if not study_dir:
            return []
        values = {
            "base": self.summary_statistics_base,
            "range_dir": self._study_range_dir(study_id),
            "study_id": study_id,
        }
        return [pattern.format(**values) for pattern in self.summary_statistics_patterns]

    def _discovered_summary_url_candidates(self, study_id: str) -> list[str]:
        study_dir = self._study_directory_url(study_id)
        if not study_dir:
            return []
        root_links = self._directory_links(study_dir)
        root_candidates = self._root_data_file_candidates(root_links)
        metadata_candidates = self._metadata_data_file_candidates(study_dir, root_links)
        harmonised_candidates = self._harmonised_data_file_candidates(study_dir, root_links)
        return self._dedupe_urls([*root_candidates, *metadata_candidates, *harmonised_candidates])

    def _study_directory_url(self, study_id: str) -> str | None:
        range_dir = self._study_range_dir(study_id)
        if not range_dir or not self.summary_statistics_base:
            return None
        return f"{self.summary_statistics_base}/{range_dir}/{study_id}/"

    def _study_range_dir(self, study_id: str) -> str | None:
        stem = study_id.replace("GCST", "")
        if not stem.isdigit():
            return None
        number = int(stem)
        if number <= 0:
            return None
        width = max(6, len(stem))
        lo = ((number - 1) // 1000) * 1000 + 1
        hi = lo + 999
        return f"GCST{lo:0{width}d}-GCST{hi:0{width}d}"

    def _directory_links(self, directory_url: str) -> list[str]:
        directory_url = self._ensure_directory_url(directory_url)
        cache_key = self.stable_hash({"directory_url": directory_url})
        found, payload = self.cached_json_get("ftp_directory_links", cache_key)
        if found and isinstance(payload, list):
            return [str(item) for item in payload if isinstance(item, str)]
        try:
            html = self.get_text(directory_url)
        except Exception:
            return []
        parser = _HrefParser()
        parser.feed(html)
        links: list[str] = []
        for href in parser.hrefs:
            href = href.strip()
            if not href or href.startswith("#") or href.startswith("?"):
                continue
            absolute = urljoin(directory_url, href)
            name = self._url_name(absolute)
            if name in {"", ".", ".."}:
                continue
            links.append(absolute)
        links = self._dedupe_urls(links)
        self.cached_json_set("ftp_directory_links", cache_key, links)
        return links

    def _root_data_file_candidates(self, links: list[str]) -> list[str]:
        tabular_files: list[str] = []
        archive_files: list[str] = []
        for link in links:
            if self._is_harmonised_url(link):
                continue
            if self._is_tabular_summary_url(link):
                tabular_files.append(link)
            elif self._is_archive_summary_url(link):
                archive_files.append(link)
        return self._dedupe_urls([*tabular_files, *archive_files])

    def _metadata_data_file_candidates(self, study_dir: str, links: list[str]) -> list[str]:
        candidates: list[str] = []
        for metadata_url in links:
            if not self._is_metadata_yaml_url(metadata_url):
                continue
            for file_name in self._metadata_data_file_names(metadata_url):
                quoted_name = quote(file_name, safe="/._-+%")
                candidates.append(urljoin(study_dir, quoted_name))
                lower_name = file_name.lower()
                if self._is_uncompressed_tabular_summary_name(lower_name):
                    candidates.append(urljoin(study_dir, quote(f"{file_name}.gz", safe="/._-+%")))
        return self._dedupe_urls(
            [candidate for candidate in candidates if self._is_root_data_file_url(candidate)]
        )

    def _metadata_data_file_names(self, metadata_url: str) -> list[str]:
        cache_key = self.stable_hash({"metadata_url": metadata_url})
        found, payload = self.cached_json_get("metadata_data_file_names", cache_key)
        if found and isinstance(payload, list):
            return [str(item) for item in payload if isinstance(item, str)]
        try:
            text = self.get_text(metadata_url)
        except Exception:
            return []
        names: list[str] = []
        for match in re.finditer(r"(?im)^\s*data_file_name\s*:\s*(.+?)\s*$", text):
            value = self._clean_metadata_value(match.group(1))
            if value:
                names.append(value)
        names = self._dedupe_strings(names)
        self.cached_json_set("metadata_data_file_names", cache_key, names)
        return names

    def _harmonised_data_file_candidates(self, study_dir: str, root_links: list[str]) -> list[str]:
        harmonised_dirs = [
            self._ensure_directory_url(link)
            for link in root_links
            if self._url_name(link).lower() == "harmonised"
        ]
        harmonised_dirs.append(urljoin(study_dir, "harmonised/"))
        h_files: list[str] = []
        f_files: list[str] = []
        for directory_url in self._dedupe_urls(harmonised_dirs):
            for link in self._directory_links(directory_url):
                name = self._url_name(link).lower()
                if name.endswith(".h.tsv.gz"):
                    h_files.append(link)
                elif name.endswith(".f.tsv.gz"):
                    f_files.append(link)
        return self._dedupe_urls([*h_files, *f_files])

    @staticmethod
    def _clean_metadata_value(value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if value[0] in {"'", '"'}:
            quote_char = value[0]
            end = value.find(quote_char, 1)
            if end > 0:
                return value[1:end].strip()
        value = value.split("#", 1)[0].strip()
        return value.strip("'\"")

    @staticmethod
    def _ensure_directory_url(url: str) -> str:
        return url if url.endswith("/") else f"{url}/"

    @staticmethod
    def _url_name(url: str) -> str:
        path = urlparse(url).path.rstrip("/")
        if not path:
            return ""
        return unquote(path.rsplit("/", 1)[-1])

    @classmethod
    def _is_metadata_yaml_url(cls, url: str) -> bool:
        name = cls._url_name(url).lower()
        return name.endswith(".yaml") or name.endswith(".yml")

    @classmethod
    def _is_root_data_file_url(cls, url: str) -> bool:
        return cls._is_tabular_summary_url(url) or cls._is_archive_summary_url(url)

    @classmethod
    def _is_tabular_summary_url(cls, url: str) -> bool:
        name = cls._url_name(url).lower()
        return cls._is_probable_data_name(name) and name.endswith(cls.tabular_summary_suffixes)

    @classmethod
    def _is_archive_summary_url(cls, url: str) -> bool:
        name = cls._url_name(url).lower()
        return cls._is_probable_data_name(name) and name.endswith(cls.archive_summary_suffixes)

    @classmethod
    def _is_uncompressed_tabular_summary_name(cls, name: str) -> bool:
        lower = str(name or "").lower()
        return cls._is_probable_data_name(lower) and lower.endswith((".tsv", ".txt", ".csv"))

    @classmethod
    def _is_probable_data_name(cls, name: str) -> bool:
        lower = str(name or "").lower()
        if not lower:
            return False
        return not any(token in lower for token in cls.non_data_name_tokens)

    @classmethod
    def _has_no_full_summary_statistics(cls, study: dict[str, Any]) -> bool:
        for key in ("full_summary_stats_available",):
            value = study.get(key)
            if cls._flag_is_false(value):
                return True
        return False

    @staticmethod
    def _flag_is_false(value: Any) -> bool:
        if isinstance(value, bool):
            return value is False
        if value is None:
            return False
        return str(value).strip().lower() in {"false", "0", "no", "n"}

    @staticmethod
    def _log_no_full_summary_statistics(study_id: str) -> None:
        log_step(
            f"GWAS Catalog study {study_id} has no full summary statistics available "
            "from GWAS Catalog; provide another downloadable GWAS ID or a local summary statistics file."
        )

    @staticmethod
    def _is_harmonised_url(url: str) -> bool:
        return "/harmonised/" in urlparse(url).path.lower()

    @staticmethod
    def _dedupe_urls(urls: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for url in urls:
            if not url or url in seen:
                continue
            seen.add(url)
            result.append(url)
        return result

    @staticmethod
    def _dedupe_strings(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result


if __name__ == "__main__":
    parser = build_parser("Search GWAS Catalog by trait query")
    args = parser.parse_args()
    searcher = GWASCatalogSearcher()
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
