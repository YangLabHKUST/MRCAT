from __future__ import annotations

from contextlib import redirect_stdout
import sys

import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List

from .common import (
    BaseSearcher,
    build_candidate,
    display_text,
    log_step,
    SearchError,
    build_parser,
    package_error,
    package_success,
    parse_int,
    read_tsv_rows_with_progress,
    required_token_overlap,
    semantic_tokens,
    source_config,
    source_metadata_endpoint,
    token_overlap,
    write_json,
)


class PanUKBSearcher(BaseSearcher):
    source_name = "pan_ukb"
    default_probe_budget = 12
    generic_query_tokens = {
        "amount",
        "amounts",
        "consumed",
        "consumption",
        "intake",
        "level",
        "levels",
        "measurement",
        "measurements",
        "status",
        "trait",
        "traits",
        "type",
        "types",
    }
    semantic_stopwords = frozenset(
        {
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "be",
            "by",
            "for",
            "from",
            "had",
            "has",
            "have",
            "in",
            "is",
            "of",
            "on",
            "or",
            "the",
            "to",
            "was",
            "were",
            "with",
        }
    )
    negative_bucket_patterns = (
        "did not",
        "never",
        "rarely",
        "don't know",
        "do not know",
        "unknown",
        "other",
        "na",
    )

    def __init__(self, timeout: int = 30) -> None:
        super().__init__(timeout=timeout)
        config = source_config(self.source_name)
        self.manifest_url = str(config.get("metadata_endpoint") or source_metadata_endpoint(self.source_name) or "").strip()
        self.flat_base = str(config.get("flat_files_base") or "").rstrip("/")
        self.last_probe_summary: dict[str, int] = {}
        self.last_source_stats: dict[str, Any] = {}

    def search(
        self,
        query: str,
        limit: int = 30,
        check_download: bool = False,
        ancestry: str | None = None,
    ) -> List[Dict[str, Any]]:
        self.last_probe_summary = {"probe_total": 0, "probe_success_count": 0, "probe_failure_count": 0}
        self.reset_cache_stats()
        self.last_source_stats = self.with_cache_stats({})
        if not self.manifest_url:
            raise SearchError("Pan-UKB manifest URL is not configured.", metadata_endpoint=self.manifest_url)
        manifest_started_at = time.perf_counter()
        blob = self._load_manifest_blob()
        manifest_path = self._persist_manifest(blob)
        rows, manifest_stats = self._load_manifest_rows(blob)
        pan_ukb_scope = self._pan_ukb_scope(ancestry)
        results: List[Dict[str, Any]] = []
        rows_scanned = 0
        matches_found = 0

        for row in rows:
            rows_scanned += 1
            match_score, matched_fields, direct_coding_match = self._score_manifest_row(query, row)
            if match_score <= 0:
                if rows_scanned % 50000 == 0:
                    log_step(f"Scanning Pan-UKB candidates: rows={rows_scanned}; matches={matches_found}.")
                continue

            result = self._candidate_from_row(
                row=row,
                query=query,
                match_score=match_score,
                matched_fields=matched_fields,
                direct_coding_match=direct_coding_match,
                pan_ukb_scope=pan_ukb_scope,
            )
            results.append(result)
            matches_found += 1
            if rows_scanned % 50000 == 0:
                log_step(f"Scanning Pan-UKB candidates: rows={rows_scanned}; matches={matches_found}.")

        results.sort(key=self._candidate_sort_key)
        family_counter = self._family_counter(results)
        self.last_source_stats = {
            "manifest_path": manifest_path,
            "manifest_url": self.manifest_url,
            "downloaded_bytes": len(blob),
            "decompressed_bytes": int(manifest_stats.get("decompressed_bytes") or 0),
            "rows_scanned": rows_scanned,
            "matched_row_count": matches_found,
            "matches_found": matches_found,
            "unique_candidate_count": len({str(item.get("_candidate_key") or "") for item in results}),
            "family_capped_count": sum(max(count - 1, 0) for count in family_counter.values()),
            "probe_budget": 0,
            "probe_count": 0,
            "elapsed_ms": int((time.perf_counter() - manifest_started_at) * 1000),
        }
        self.last_source_stats = self.with_cache_stats(self.last_source_stats)
        if check_download and results:
            probe_budget = min(max(limit, 1), self.default_probe_budget)
            results = self.probe_candidates(
                results,
                probe_limit=probe_budget,
                check_download=check_download,
            )
        log_step(
            f"Scanned Pan-UKB candidates: rows={rows_scanned}; matches={matches_found}; "
            f"elapsed_ms={int((time.perf_counter() - manifest_started_at) * 1000)}."
        )
        return results[:limit]

    def search_by_id(
        self,
        study_id: str,
        *,
        ancestry: str | None = None,
        check_download: bool = False,
    ) -> List[Dict[str, Any]]:
        """Resolve one Pan-UKB manifest identifier into the same candidate shape as search()."""

        normalized_id = str(study_id or "").strip()
        self.last_probe_summary = {"probe_total": 0, "probe_success_count": 0, "probe_failure_count": 0}
        self.reset_cache_stats()
        self.last_source_stats = self.with_cache_stats({})
        if not normalized_id:
            return []
        if not self.manifest_url:
            raise SearchError("Pan-UKB manifest URL is not configured.", metadata_endpoint=self.manifest_url)
        blob = self._load_manifest_blob()
        manifest_path = self._persist_manifest(blob)
        rows, manifest_stats = self._load_manifest_rows(blob)
        pan_ukb_scope = self._pan_ukb_scope(ancestry)
        for row in rows:
            if not self._row_matches_id(row, normalized_id):
                continue
            candidate = self._candidate_from_row(
                row=row,
                query=normalized_id,
                match_score=10000,
                matched_fields=["id"],
                direct_coding_match=True,
                pan_ukb_scope=pan_ukb_scope,
            )
            if check_download:
                candidate = self.probe_candidates([candidate], probe_limit=1, check_download=True)[0]
            self.last_source_stats = self.with_cache_stats(
                {
                    **dict(self.last_source_stats or {}),
                    "search_mode": "id",
                    "manifest_path": manifest_path,
                    "decompressed_bytes": int(manifest_stats.get("decompressed_bytes") or 0),
                    "matched_candidate_count": 1,
                    "rows_scanned": len(rows),
                    "probe_budget": self.last_probe_summary["probe_total"],
                    "probe_count": self.last_probe_summary["probe_total"],
                }
            )
            return [candidate]
        self.last_source_stats = self.with_cache_stats(
            {
                "search_mode": "id",
                "manifest_path": manifest_path,
                "decompressed_bytes": int(manifest_stats.get("decompressed_bytes") or 0),
                "matched_candidate_count": 0,
                "rows_scanned": len(rows),
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
        self.last_probe_summary = {"probe_total": 0, "probe_success_count": 0, "probe_failure_count": 0}
        seen_keys: set[str] = set()
        probe_index = 0
        for item in ordered:
            candidate_key = str(item.get("_candidate_key") or item.get("study_id") or "").strip()
            if not candidate_key or candidate_key in seen_keys:
                continue
            if probe_index >= max(probe_limit, 0):
                break
            download_url = str(item.get("download_url") or "").strip() or None
            downloadable, downloadability_reason, download_check = self.evaluate_download(
                download_url=download_url,
                check_download=check_download,
                reason_if_missing="no_summary_stats",
            )
            item["downloadable"] = downloadable
            item["downloadability_reason"] = downloadability_reason
            if download_check is not None:
                item["_download_check"] = download_check
            self.last_probe_summary["probe_total"] += 1
            if downloadable:
                self.last_probe_summary["probe_success_count"] += 1
            else:
                self.last_probe_summary["probe_failure_count"] += 1
            probe_index += 1
            seen_keys.add(candidate_key)

        stats = dict(self.last_source_stats)
        stats["probe_budget"] = probe_limit
        stats["probe_count"] = self.last_probe_summary["probe_total"]
        self.last_source_stats = self.with_cache_stats(stats)
        return ordered

    def _load_manifest_blob(self) -> bytes:
        cache_key = self.stable_hash({"manifest_url": self.manifest_url})
        found, blob = self.cached_bytes_get("manifest_blob", cache_key)
        if found and isinstance(blob, bytes):
            return blob
        blob = self.download_bytes_with_progress(
            self.manifest_url,
            label="Pan-UKB manifest",
        )
        self.cached_bytes_set("manifest_blob", cache_key, blob)
        return blob

    def _load_manifest_rows(
        self,
        blob: bytes,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        blob_hash = self.stable_hash(blob)
        found, payload = self.cached_json_get("manifest_rows", blob_hash)
        if found and isinstance(payload, dict):
            rows = payload.get("rows")
            stats = payload.get("stats")
            if isinstance(rows, list) and isinstance(stats, dict):
                return rows, stats

        rows, stats = read_tsv_rows_with_progress(
            blob,
            compressed=True,
            label="Pan-UKB manifest",
        )
        self.cached_json_set(
            "manifest_rows",
            blob_hash,
            {
                "rows": rows,
                "stats": stats,
            },
        )
        return rows, stats

    def _persist_manifest(self, blob: bytes) -> str | None:
        execution_dir = str(os.getenv("MRCAT_EXECUTION_DIR") or "").strip()
        if not execution_dir:
            return None
        path = Path(execution_dir) / "pan_ukb_manifest.tsv.bgz"
        path.write_bytes(blob)
        return str(path)

    def _download_url(self, row: Dict[str, Any]) -> str | None:
        direct = str(row.get("aws_link") or "").strip()
        if direct:
            return direct
        aws_path = str(row.get("aws_path") or "").strip()
        if aws_path.startswith("s3://"):
            bucket_and_key = aws_path[len("s3://") :]
            bucket, _, key = bucket_and_key.partition("/")
            if bucket and key:
                return f"https://{bucket}.s3.amazonaws.com/{key}"
        filename = self._filename(row)
        if filename and self.flat_base:
            return f"{self.flat_base}/{filename}"
        return None

    @staticmethod
    def _filename(row: Dict[str, Any]) -> str:
        return str(row.get("filename") or "").strip()

    @staticmethod
    def _coding_description(row: Dict[str, Any]) -> str | None:
        value = str(row.get("coding_description") or "").strip()
        if not value or value.upper() in {"NA", "N/A", "NULL", "NONE"}:
            return None
        return value

    @staticmethod
    def _display_text(value: Any) -> str:
        return display_text(value)

    def _public_trait(self, row: Dict[str, Any], query: str) -> str:
        description = self._display_text(row.get("description"))
        coding_description = self._coding_description(row)
        description_more = self._display_text(row.get("description_more"))
        phenocode = self._display_text(row.get("phenocode"))
        if description and coding_description:
            return f"{description} [{coding_description}]"
        return description or coding_description or description_more or phenocode or query

    def _candidate_key(self, row: Dict[str, Any]) -> str:
        return self._filename(row) or str(row.get("phenocode") or "").strip()

    def _candidate_from_row(
        self,
        *,
        row: Dict[str, Any],
        query: str,
        match_score: int,
        matched_fields: list[str],
        direct_coding_match: bool,
        pan_ukb_scope: str,
    ) -> Dict[str, Any]:
        filename = self._filename(row)
        candidate_key = self._candidate_key(row)
        download_url = self._download_url(row)
        downloadable = bool(download_url)
        downloadability_reason = "resolved_url" if download_url else "no_summary_stats"
        sample_size, n_cases, n_controls = self._sample_size(row, scope=pan_ukb_scope)
        candidate = build_candidate(
            side=None,
            trait=self._public_trait(row, query),
            study_id=candidate_key,
            source=self.source_name,
            ancestry_value=row.get("pops"),
            sample_size=sample_size,
            n_cases=n_cases,
            n_controls=n_controls,
            downloadable=downloadable,
            download_url=download_url,
            auth_required=False,
            requires_user_confirmation=False,
            downloadability_reason=downloadability_reason,
            download_check=None,
            matched_fields=matched_fields,
            matched_query=None,
            raw_metadata=row,
            metadata_extras={
                "pan_ukb_scope": pan_ukb_scope,
                "filename": filename,
                "trait_type": row.get("trait_type"),
                "phenocode": row.get("phenocode"),
                "coding_description": self._coding_description(row),
                "population": row.get("population") or row.get("pops") or "Multi-ancestry",
                "download_url": download_url,
            },
            match_score=match_score,
            raw_record=dict(row),
            candidate_key=candidate_key,
            family_key=self._family_key(row, direct_coding_match=direct_coding_match),
        )
        candidate["ancestry"] = self._scope_ancestry_label(pan_ukb_scope)
        return candidate

    def _row_matches_id(self, row: Dict[str, Any], study_id: str) -> bool:
        wanted = str(study_id or "").strip()
        if not wanted:
            return False
        candidates = {
            self._candidate_key(row),
            self._filename(row),
            str(row.get("phenocode") or "").strip(),
            str(row.get("aws_path") or "").strip(),
            str(row.get("aws_link") or "").strip(),
        }
        return wanted in candidates

    def _family_key(self, row: Dict[str, Any], *, direct_coding_match: bool) -> str | None:
        phenocode = str(row.get("phenocode") or "").strip()
        coding_description = self._coding_description(row)
        if not phenocode or not coding_description or direct_coding_match:
            return None
        return phenocode

    def _query_tokens(self, query: str) -> list[str]:
        tokens = self._semantic_tokens(query)
        filtered = [token for token in tokens if token not in self.generic_query_tokens]
        return filtered or tokens

    def _semantic_tokens(self, text: Any) -> list[str]:
        return semantic_tokens(text, stopwords=self.semantic_stopwords)

    @staticmethod
    def _token_overlap(query_tokens: set[str], value_tokens: set[str]) -> int:
        return token_overlap(query_tokens, value_tokens)

    @staticmethod
    def _required_overlap(query_tokens: set[str]) -> int:
        return required_token_overlap(
            query_tokens,
            short_query_token_count=3,
            min_coverage=0.7,
        )

    def _score_manifest_row(self, query: str, row: Dict[str, Any]) -> tuple[int, list[str], bool]:
        query_norm = self.normalize_text(query)
        query_tokens = set(self._query_tokens(query))
        description = self.normalize_text(self._display_text(row.get("description")))
        phenocode = self.normalize_text(self._display_text(row.get("phenocode")))
        filename = self.normalize_text(self._filename(row))
        coding_description = self.normalize_text(self._coding_description(row) or "")

        token_fields = {
            "description": set(self._semantic_tokens(row.get("description"))),
            "coding_description": set(self._semantic_tokens(self._coding_description(row))),
            "description_more": set(self._semantic_tokens(row.get("description_more"))),
            "category": set(self._semantic_tokens(row.get("category"))),
            "phenocode": set(self._semantic_tokens(row.get("phenocode"))),
            "filename": set(self._semantic_tokens(self._filename(row))),
        }

        fields: list[str] = []
        score = 0
        if query_norm and query_norm == phenocode:
            score += 120
            fields.append("phenocode")
        if query_norm and query_norm == filename:
            score += 120
            fields.append("filename")
        if score:
            score += min(self._population_count(row.get("pops")), 6)
            return score, sorted(set(fields)), False

        if not query_tokens:
            return 0, [], False

        semantic_tokens = (
            token_fields["description"]
            | token_fields["coding_description"]
            | token_fields["description_more"]
            | token_fields["category"]
        )
        if self._token_overlap(query_tokens, semantic_tokens) < self._required_overlap(query_tokens):
            return 0, [], False

        if query_norm and query_norm == description:
            score = 105
            fields.append("description")
        else:
            description_overlap = self._token_overlap(query_tokens, token_fields["description"])
            coding_overlap_count = self._token_overlap(query_tokens, token_fields["coding_description"])
            description_more_overlap = self._token_overlap(query_tokens, token_fields["description_more"])
            category_overlap = self._token_overlap(query_tokens, token_fields["category"])
            phenocode_overlap = self._token_overlap(query_tokens, token_fields["phenocode"])
            filename_overlap = self._token_overlap(query_tokens, token_fields["filename"])
            primary_overlap = description_overlap + coding_overlap_count + description_more_overlap + category_overlap
            if description_overlap:
                score += description_overlap * 20
                fields.append("description")
            if coding_overlap_count:
                score += coding_overlap_count * 12
                fields.append("coding_description")
            if description_more_overlap:
                score += description_more_overlap * 8
                fields.append("description_more")
            if category_overlap:
                score += category_overlap * 3
                fields.append("category")
            if query_tokens and query_tokens <= token_fields["phenocode"]:
                score += phenocode_overlap * 5
                fields.append("phenocode")
            if query_tokens and query_tokens <= token_fields["filename"]:
                score += filename_overlap * 5
                fields.append("filename")
            if primary_overlap <= 0:
                return 0, [], False

        coding_overlap = bool(query_tokens & token_fields["coding_description"])
        direct_coding_match = bool(
            coding_description and query_norm and query_norm == coding_description
        )
        if coding_overlap and "coding_description" not in fields:
            fields.append("coding_description")
        if self._is_negative_bucket(row):
            score -= 8
        score += min(self._population_count(row.get("pops")), 6)
        return score, sorted(set(fields)), direct_coding_match

    def _is_negative_bucket(self, row: Dict[str, Any]) -> bool:
        coding_description = self.normalize_text(str(self._coding_description(row) or ""))
        return any(pattern in coding_description for pattern in self.negative_bucket_patterns)

    @staticmethod
    def _population_count(raw_pops: Any) -> int:
        text = str(raw_pops or "").strip()
        if not text:
            return 0
        return len([part for part in text.split(",") if part.strip()])

    def _candidate_sort_key(self, item: Dict[str, Any]) -> tuple[int, int, int, int, str]:
        sample_size = BaseSearcher.stable_sample_size(
            {
                "sample_size": item.get("sample_size"),
                "n_cases": item.get("n_cases"),
                "n_controls": item.get("n_controls"),
                **(item.get("study_metadata", {}) or {}),
            }
        )
        population_count = self._population_count(item.get("ancestry_raw"))
        negative_bucket = 1 if self._is_negative_bucket(item.get("_raw_record") or {}) else 0
        filename = str((item.get("study_metadata") or {}).get("filename") or "")
        return (
            -int(item.get("_match_score") or 0),
            negative_bucket,
            -population_count,
            -sample_size,
            filename,
        )

    @staticmethod
    def _family_counter(results: List[Dict[str, Any]]) -> Dict[str, int]:
        counts: dict[str, int] = {}
        for item in results:
            family_key = str(item.get("_family_key") or "").strip()
            if family_key:
                counts[family_key] = counts.get(family_key, 0) + 1
        return counts

    @staticmethod
    def _pan_ukb_scope(ancestry: Any) -> str:
        text = str(ancestry or "").strip().lower()
        normalized = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        aliases = {
            "eur": "EUR",
            "european": "EUR",
            "europe": "EUR",
            "afr": "AFR",
            "african": "AFR",
            "amr": "AMR",
            "admixed_american": "AMR",
            "american": "AMR",
            "csa": "CSA",
            "central_south_asian": "CSA",
            "south_asian": "CSA",
            "eas": "EAS",
            "east_asian": "EAS",
            "mid": "MID",
            "middle_eastern": "MID",
        }
        return aliases.get(normalized, "EUR")

    @staticmethod
    def _scope_ancestry_label(scope: str) -> str:
        return {
            "EUR": "european",
            "AFR": "african",
            "AMR": "admixed_american",
            "CSA": "central_south_asian",
            "EAS": "east_asian",
            "MID": "middle_eastern",
        }.get(scope, "european")

    def _sample_size(
        self,
        row: Dict[str, Any],
        *,
        scope: str,
    ) -> tuple[int | None, int | None, int | None]:
        trait_type = str(row.get("trait_type") or "").strip().lower()
        n_cases = self._scope_count(row, prefix="n_cases", scope=scope)
        n_controls = self._scope_count(row, prefix="n_controls", scope=scope)
        if trait_type in {"continuous", "biomarkers"}:
            return n_cases, None, None

        if n_cases is not None and n_controls is not None:
            return n_cases + n_controls, n_cases, n_controls
        return None, n_cases, n_controls

    @staticmethod
    def _scope_count(row: Dict[str, Any], *, prefix: str, scope: str) -> int | None:
        return parse_int(row.get(f"{prefix}_{scope}"))


if __name__ == "__main__":
    parser = build_parser("Search Pan-UKB by trait query")
    args = parser.parse_args()
    searcher = PanUKBSearcher()
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
