from __future__ import annotations

import json
from typing import Any


STUDY_DATA_SOURCES = (
    {"id": "opengwas", "label": "OpenGWAS"},
    {"id": "gwas_catalog", "label": "GWAS Catalog"},
    {"id": "finngen", "label": "FinnGen"},
    {"id": "pan_ukb", "label": "Pan-UKB"},
)
STUDY_DATA_SOURCE_IDS = tuple(item["id"] for item in STUDY_DATA_SOURCES)


def normalize_study_sources(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_text = value.strip()
        if not raw_text:
            raw_values: list[Any] = []
        else:
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError:
                raw_values = [raw_text]
            else:
                raw_values = parsed if isinstance(parsed, list) else [parsed]
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = []

    sources: list[str] = []
    for item in raw_values:
        source = str(item or "").strip().lower()
        if not source:
            continue
        if source not in STUDY_DATA_SOURCE_IDS:
            raise ValueError(f"unsupported Study Setup data source: {item}")
        if source not in sources:
            sources.append(source)
    if len(sources) > 1:
        raise ValueError("Study Setup accepts one data source or Automatic")
    return sources


def study_source_catalog() -> list[dict[str, str]]:
    return [dict(item) for item in STUDY_DATA_SOURCES]
