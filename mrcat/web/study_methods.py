from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mrcat.tool.skill_registry import SkillRegistry


# These are the MR endpoints that can consume the prepared local GWAS workflow.
# Preparation and reporting skills deliberately do not appear in the Study setup panel.
STUDY_METHOD_IDS = (
    "mr-primary",
    "mr-apss",
    "mr-bwmr",
    "mr-cml-ma",
    "mr-conmix",
    "mr-divw",
    "mr-lasso",
    "mr-mrmix",
    "mr-presso",
    "mr-raps",
    "mr-robust",
    "mr-cause",
)

STUDY_METHOD_LABELS = {
    "mr-primary": "Primary MR",
    "mr-bwmr": "BWMR",
    "mr-apss": "MR-APSS",
    "mr-cml-ma": "cML-MA",
    "mr-conmix": "ConMix",
    "mr-divw": "dIVW",
    "mr-lasso": "MR-Lasso",
    "mr-mrmix": "MRMix",
    "mr-presso": "MR-PRESSO",
    "mr-raps": "MR-RAPS",
    "mr-robust": "MR-Robust",
    "mr-cause": "CAUSE",
}

STUDY_METHOD_PURPOSES = {
    "mr-primary": (
        "Primary analysis for full local-data workflows; reports IVW, MR-Egger, "
        "weighted median, and weighted mode estimates."
    ),
    "mr-bwmr": (
        "Designed to account for SNP-exposure uncertainty and balanced horizontal "
        "pleiotropy while adaptively downweighting a small number of outlying instruments."
    ),
    "mr-apss": (
        "Designed for weak or moderately associated instruments when sample structure, "
        "sample overlap, and pleiotropy may bias conventional MR."
    ),
    "mr-cml-ma": (
        "Designed for settings where several instruments may be invalid; uses constrained "
        "likelihood and model averaging to handle invalid-IV configurations."
    ),
    "mr-conmix": (
        "Designed for invalid instruments when valid instruments are expected to form the "
        "largest cluster, while allowing multiple plausible ratio-estimate modes."
    ),
    "mr-divw": (
        "Designed to reduce weak-instrument and selection bias in IVW when many instruments "
        "are selected from noisy exposure associations."
    ),
    "mr-lasso": (
        "Designed to identify and penalize a small number of instruments with large direct "
        "pleiotropic effects."
    ),
    "mr-mrmix": (
        "Designed for widespread horizontal pleiotropy when valid instruments are expected "
        "to form an identifiable mixture component."
    ),
    "mr-presso": (
        "Designed to detect horizontal-pleiotropy outliers and compare prespecified raw "
        "and outlier-corrected causal estimates."
    ),
    "mr-raps": (
        "Designed for many weak or moderately associated instruments; corrects weak-IV bias "
        "and limits the influence of balanced pleiotropy and outliers."
    ),
    "mr-robust": (
        "Designed as a fast robustness check when a few influential or outlying instruments "
        "may be driving the ordinary IVW estimate."
    ),
    "mr-cause": (
        "Designed to distinguish a causal effect from correlated horizontal pleiotropy or "
        "genetic sharing between the exposure and outcome."
    ),
}

LEGACY_STUDY_METHOD_ALIASES = {
    "primary": "mr-primary",
    "mr_primary": "mr-primary",
    "bwmr": "mr-bwmr",
    "mr_bwmr": "mr-bwmr",
    "mrapss": "mr-apss",
    "mr_apss": "mr-apss",
    "divw": "mr-divw",
    "mr_divw": "mr-divw",
    "raps": "mr-raps",
    "mr_raps": "mr-raps",
    "mrmix": "mr-mrmix",
    "mr_mrmix": "mr-mrmix",
    "presso": "mr-presso",
    "mr_presso": "mr-presso",
    "cml": "mr-cml-ma",
    "cml_ma": "mr-cml-ma",
    "mr_cml_ma": "mr-cml-ma",
    "conmix": "mr-conmix",
    "mr_conmix": "mr-conmix",
    "lasso": "mr-lasso",
    "mr_lasso": "mr-lasso",
    "robust": "mr-robust",
    "mr_robust": "mr-robust",
    "cause": "mr-cause",
    "mr_cause": "mr-cause",
}


def canonical_study_method(value: Any) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized:
        return None
    candidate = LEGACY_STUDY_METHOD_ALIASES.get(normalized, normalized.replace("_", "-"))
    return candidate if candidate in STUDY_METHOD_IDS else None


def normalize_study_methods(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_text = value.strip()
        if not raw_text:
            raw_values: list[Any] = []
        else:
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError:
                raw_values = raw_text.split(",")
            else:
                raw_values = parsed if isinstance(parsed, list) else [parsed]
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = []

    methods: list[str] = []
    for item in raw_values:
        method = canonical_study_method(item)
        if method is None:
            raise ValueError(f"unsupported uploaded-data MR method: {item}")
        if method not in methods:
            methods.append(method)
    if not methods:
        raise ValueError("at least one uploaded-data MR method is required")
    return methods


def study_method_catalog(skills_dir: Path) -> list[dict[str, str]]:
    registry = SkillRegistry(Path(skills_dir))
    methods: list[dict[str, str]] = []
    for skill_id in STUDY_METHOD_IDS:
        bundle = registry.get(skill_id)
        if bundle is None:
            continue
        methods.append(
            {
                "id": skill_id,
                "label": STUDY_METHOD_LABELS[skill_id],
                "description": STUDY_METHOD_PURPOSES.get(skill_id, bundle.description),
            }
        )
    return methods
