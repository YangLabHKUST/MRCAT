"""Prepare a validated local alternative to the OpenGWAS GRCh37 LD panel."""
from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any

from mrcat.database import DatabaseResourceError, database, database_resource_ids


def recorded_ld_reference_details(execution_dir: Path) -> dict[str, str]:
    path = execution_dir / "reports" / "ld_clumping_reference.json"
    if not path.is_file():
        return {}
    return {"reference_usage": json.loads(path.read_text())["summary"]}


def local_api_clumping_fallback(payload: dict[str, Any], *, resolver=database) -> dict[str, str] | None:
    if str(payload.get("bfile") or "").strip():
        return None
    population = str(payload.get("pop") or "EUR").strip().upper()
    resource_id = f"plink.{population.lower()}.grch37"
    if resource_id not in database_resource_ids():
        return {"unavailable_reason": f"No registered GRCh37 LD panel for API population {population}."}
    try:
        prefix = resolver(resource_id)
        binary = resolver("plink.binary")
    except DatabaseResourceError:
        return {"unavailable_reason": f"Local reference {resource_id} or plink.binary is incomplete."}
    if not os.access(binary, os.X_OK):
        return {"unavailable_reason": "The registered PLINK binary is not executable."}
    return {
        "resource_id": resource_id,
        "population": population,
        "genome_build": "GRCh37",
        "bfile": str(prefix),
        "plink_bin": str(binary),
    }
