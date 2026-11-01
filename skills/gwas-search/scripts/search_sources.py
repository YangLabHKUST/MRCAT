from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List

from .common import load_reference_config
from .search_finngen import FinnGenSearcher
from .search_gwas_catalog import GWASCatalogSearcher
from .search_opengwas import OpenGWASSearcher
from .search_pan_ukb import PanUKBSearcher
from .trait_resolver import compact_text


SEARCHERS = {
    "opengwas": OpenGWASSearcher,
    "gwas_catalog": GWASCatalogSearcher,
    "finngen": FinnGenSearcher,
    "pan_ukb": PanUKBSearcher,
}
SOURCE_ALIASES = {
    "gwas_catalog": ("gwas catalog", "gwascatalog"),
    "opengwas": ("open gwas", "opengwas"),
    "finngen": ("finngen",),
    "pan_ukb": (
        "pan ukb",
        "pan-ukb",
        "panukb",
        "pan uk biobank",
    ),
}
SOURCE_PROBE_BUDGETS = {
    "gwas_catalog": 12,
    "pan_ukb": 12,
}
SOURCE_METADATA_MULTIPLIER = 4


def _normalized_token(value: Any) -> str:
    return " ".join(
        str(value or "")
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )


def normalize_source_name(value: Any) -> str:
    source = str(value or "").strip().lower()
    if not source:
        return ""
    normalized = _normalized_token(source)
    for canonical, aliases in SOURCE_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            return canonical
    if source in SEARCHERS:
        return source
    return ""


def normalize_requested_ancestry(value: Any) -> str:
    normalized = _normalized_token(value)
    if not normalized:
        return ""
    aliases_by_ancestry = _ancestry_aliases_from_config()
    for raw_canonical, raw_aliases in aliases_by_ancestry.items():
        canonical = _normalized_token(raw_canonical).replace(" ", "_")
        aliases = raw_aliases if isinstance(raw_aliases, list) else []
        accepted = {
            _normalized_token(raw_canonical),
            *(_normalized_token(alias) for alias in aliases),
        }
        if normalized in accepted:
            return canonical
    return ""


def ancestry_source_order(ancestry: str) -> List[str]:
    if not ancestry:
        return []
    raw_routes = _ancestry_routes_from_config()
    raw_sources = raw_routes.get(ancestry) or []
    if not isinstance(raw_sources, list):
        return []
    ordered: List[str] = []
    for raw_source in raw_sources:
        source = normalize_source_name(raw_source)
        if source and source not in ordered:
            ordered.append(source)
    return ordered


def requested_ancestry_terms(ancestry: str) -> List[str]:
    normalized_ancestry = normalize_requested_ancestry(ancestry)
    if not normalized_ancestry:
        return []
    aliases_by_ancestry = _ancestry_aliases_from_config()
    raw_aliases = (
        aliases_by_ancestry.get(normalized_ancestry) or []
        if isinstance(aliases_by_ancestry, dict)
        else []
    )
    aliases = raw_aliases if isinstance(raw_aliases, list) else []
    terms: List[str] = []
    for raw_term in [normalized_ancestry, *aliases]:
        term = _normalized_token(raw_term)
        if term and term not in terms:
            terms.append(term)
    return terms


@lru_cache(maxsize=1)
def _ancestry_aliases_from_config() -> Dict[str, Any]:
    config = load_reference_config()
    raw_aliases = (config.get("source-config") or {}).get("ancestry-aliases") or {}
    return dict(raw_aliases) if isinstance(raw_aliases, dict) else {}


@lru_cache(maxsize=1)
def _ancestry_routes_from_config() -> Dict[str, Any]:
    config = load_reference_config()
    raw_routes = (config.get("source-config") or {}).get("ancestry-routes") or {}
    return dict(raw_routes) if isinstance(raw_routes, dict) else {}


def resolve_search_route(
    *,
    study_id: str,
    source: str,
    ancestry: Any,
    default_sources: List[str],
    preferred_sources: List[str],
    allow_source_fallback: bool,
) -> Dict[str, Any]:
    raw_source = compact_text(source)
    normalized_source = normalize_source_name(raw_source)
    if raw_source and not normalized_source:
        return _route_failure(
            failure_class="unsupported_source",
            message=f"Unsupported GWAS source: {raw_source}.",
            diagnostics={"source": raw_source},
        )

    raw_ancestry = compact_text(ancestry)
    normalized_ancestry = normalize_requested_ancestry(raw_ancestry)
    if raw_ancestry and not normalized_ancestry:
        return _route_failure(
            failure_class="unsupported_ancestry",
            message=f"Unsupported GWAS ancestry route: {raw_ancestry}.",
            diagnostics={"ancestry": raw_ancestry},
        )

    study_id_text = compact_text(study_id)
    if study_id_text:
        inferred_source = infer_source_from_study_id(study_id_text)
        if (
            normalized_source
            and inferred_source
            and normalized_source != inferred_source
        ):
            return _route_failure(
                failure_class="source_id_namespace_conflict",
                message=(
                    f"Explicit source={normalized_source} conflicts "
                    f"with study_id={study_id_text} namespace "
                    f"source={inferred_source}."
                ),
                diagnostics={
                    "study_id": study_id_text,
                    "source": normalized_source,
                    "inferred_source": inferred_source,
                },
            )
        exact_source = normalized_source or inferred_source
        if not exact_source:
            return _route_failure(
                failure_class="exact_id_source_unresolved",
                message=(
                    f"Could not resolve a supported source for "
                    f"study_id={study_id_text}."
                ),
                diagnostics={
                    "study_id": study_id_text,
                    "source": raw_source or None,
                },
            )
        if normalized_ancestry and exact_source not in ancestry_source_order(
            normalized_ancestry
        ):
            return _route_failure(
                failure_class="study_id_ancestry_conflict",
                message=(
                    f"Source={exact_source} for study_id={study_id_text} "
                    f"does not support ancestry={normalized_ancestry}."
                ),
                diagnostics={
                    "study_id": study_id_text,
                    "source": exact_source,
                    "ancestry": normalized_ancestry,
                },
            )
        return {
            "mode": "study_id",
            "source": exact_source,
            "sources": [exact_source],
            "ancestry": normalized_ancestry or None,
            "preferred_sources": [exact_source],
            "allow_source_fallback": False,
            "failure_class": None,
        }

    if normalized_source:
        if normalized_ancestry and normalized_source not in ancestry_source_order(
            normalized_ancestry
        ):
            return _route_failure(
                failure_class="source_ancestry_conflict",
                message=(
                    f"Source={normalized_source} does not support "
                    f"ancestry={normalized_ancestry}."
                ),
                diagnostics={
                    "source": normalized_source,
                    "ancestry": normalized_ancestry,
                },
            )
        return {
            "mode": "trait",
            "source": normalized_source,
            "sources": [normalized_source],
            "ancestry": normalized_ancestry or None,
            "preferred_sources": [normalized_source],
            "allow_source_fallback": False,
            "failure_class": None,
        }

    if normalized_ancestry:
        routed_sources = ancestry_source_order(normalized_ancestry)
        if not routed_sources:
            return _route_failure(
                failure_class="ancestry_sources_unconfigured",
                message=(
                    f"No GWAS sources are configured for "
                    f"ancestry={normalized_ancestry}."
                ),
                diagnostics={"ancestry": normalized_ancestry},
            )
        return {
            "mode": "trait",
            "source": "",
            "sources": routed_sources,
            "ancestry": normalized_ancestry,
            "preferred_sources": routed_sources,
            "allow_source_fallback": True,
            "failure_class": None,
        }

    return {
        "mode": "trait",
        "source": "",
        "sources": list(default_sources),
        "ancestry": None,
        "preferred_sources": list(preferred_sources),
        "allow_source_fallback": bool(allow_source_fallback),
        "failure_class": None,
    }


def _route_failure(
    *,
    failure_class: str,
    message: str,
    diagnostics: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "mode": "",
        "source": "",
        "sources": [],
        "ancestry": None,
        "preferred_sources": [],
        "allow_source_fallback": False,
        "failure_class": failure_class,
        "message": message,
        "diagnostics": diagnostics,
    }


def normalize_contract_constraints(contract: Dict[str, Any]) -> Dict[str, Any]:
    raw_constraints = contract.get("constraints")
    constraints = dict(raw_constraints or {}) if isinstance(raw_constraints, dict) else {}
    preferred_sources = constraints.get("preferred_sources")
    normalized_sources: List[str] = []
    seen: set[str] = set()
    if isinstance(preferred_sources, list):
        for raw in preferred_sources:
            canonical = normalize_source_name(raw)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            normalized_sources.append(canonical)
    allow_source_fallback = constraints.get("allow_source_fallback")
    return {
        "preferred_sources": normalized_sources,
        "allow_source_fallback": (
            allow_source_fallback
            if isinstance(allow_source_fallback, bool)
            else True
        ),
    }


def default_sources_from_config() -> List[str]:
    config = load_reference_config()
    configured_sources = ((config.get("source-config") or {}).get("sources") or {})
    defaults: List[str] = []
    seen: set[str] = set()
    for raw in configured_sources.keys():
        name = str(raw or "").strip().lower()
        if not name or name in seen or name not in SEARCHERS:
            continue
        seen.add(name)
        defaults.append(name)
    return defaults


def resolve_source_order(
    *,
    raw_sources: List[Any],
    default_sources: List[str],
    preferred_sources: List[str],
    allow_source_fallback: bool,
) -> tuple[List[str], str]:
    normalized_preferred: List[str] = []
    seen: set[str] = set()
    for raw in preferred_sources:
        canonical = normalize_source_name(raw)
        if not canonical or canonical in seen or canonical not in SEARCHERS:
            continue
        seen.add(canonical)
        normalized_preferred.append(canonical)
    raw_or_default, reason = normalize_sources(
        raw_sources,
        fallback_sources=default_sources,
    )
    if normalized_preferred and not allow_source_fallback:
        return normalized_preferred, "contract_strict_preferred_only"
    if normalized_preferred:
        return (
            merge_sources_in_order(normalized_preferred, raw_or_default),
            "contract_preferred_then_runtime",
        )
    return raw_or_default, reason


def merge_sources_in_order(*source_groups: List[str]) -> List[str]:
    merged: List[str] = []
    seen: set[str] = set()
    for group in source_groups:
        for raw in group:
            name = str(raw or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            merged.append(name)
    return merged


def infer_source_from_study_id(study_id: str) -> str:
    value = compact_text(study_id)
    lowered = value.lower()
    if not value:
        return ""
    if value.upper().startswith("GCST"):
        return "gwas_catalog"
    if lowered.startswith("finngen_"):
        return "finngen"
    if (
        lowered.endswith((".tsv", ".tsv.gz", ".bgz"))
        or "pan-ukb" in lowered
        or "pan_ukb" in lowered
        or "panukb" in lowered
    ):
        return "pan_ukb"
    if lowered.startswith(
        (
            "ieu-",
            "ukb-",
            "ebi-",
            "bbj-",
            "eqtl-",
            "prot-",
            "met-",
            "finn-",
        )
    ):
        return "opengwas"
    return ""


def normalize_sources(
    raw_sources: List[Any],
    *,
    fallback_sources: List[str],
) -> tuple[List[str], str]:
    normalized: List[str] = []
    seen: set[str] = set()
    for raw in raw_sources:
        name = str(raw or "").strip().lower()
        if not name or name in seen or name not in SEARCHERS:
            continue
        seen.add(name)
        normalized.append(name)
    if normalized:
        return normalized, "llm_or_input_order"
    if fallback_sources:
        return list(fallback_sources), "fallback_config_default"
    raise SystemExit("run_search.py could not resolve any valid source")
