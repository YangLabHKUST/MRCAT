from __future__ import annotations

from pathlib import Path

from mrcat.skills import SkillRegistry


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
