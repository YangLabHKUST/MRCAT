from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .. import __version__ as mrcat_version


_R_PACKAGES = (
    "TwoSampleMR",
    "MRPRESSO",
    "MRAPSS",
    "MendelianRandomization",
    "MRMix",
    "MRcML",
    "mr.divw",
    "mr.raps",
    "cause",
    "glmnet",
    "robustbase",
    "data.table",
    "jsonlite",
    "ggplot2",
)


def build_reporting_metadata() -> dict[str, Any]:
    """Build evidence-backed report declarations with safe unavailable defaults."""

    software = _software_environment()
    return {
        "software": software,
        "preregistration": {
            "status": _env("MRCAT_PREREGISTRATION_STATUS", "not_supplied"),
            "statement": _env(
                "MRCAT_PREREGISTRATION_STATEMENT",
                "Preregistration information was not supplied for this analysis.",
            ),
        },
        "funding": {
            "statement": _env(
                "MRCAT_FUNDING_STATEMENT",
                "Funding information for this analysis was not supplied.",
            ),
            "funder_role": _env(
                "MRCAT_FUNDER_ROLE_STATEMENT",
                "The role of any funder was not supplied.",
            ),
        },
        "data_and_code": {
            "statement": _env(
                "MRCAT_DATA_CODE_STATEMENT",
                (
                    "GWAS identifiers and analysis provenance are reported in this "
                    "document. Public data and code availability were not otherwise "
                    "specified."
                ),
            ),
        },
        "conflicts": {
            "statement": _env(
                "MRCAT_CONFLICTS_STATEMENT",
                "Conflict-of-interest information was not supplied.",
            ),
        },
    }


def reporting_declaration_text(metadata: dict[str, Any]) -> dict[str, str]:
    """Render fixed disclosure text from the structured metadata evidence."""

    software = metadata.get("software") if isinstance(metadata, dict) else {}
    software = software if isinstance(software, dict) else {}
    r_packages = software.get("r_packages")
    package_text = ""
    if isinstance(r_packages, dict) and r_packages:
        package_text = "; R packages: " + ", ".join(
            f"{name} {version}" for name, version in sorted(r_packages.items())
        )
    elif software.get("r_version"):
        package_text = "; R package versions were unavailable"
    software_text = (
        f"Analyses were orchestrated using MRCAT {software.get('mrcat_version', 'unknown')} "
        f"with Python {software.get('python_version', 'unknown')}"
        f"{'; R ' + str(software['r_version']) if software.get('r_version') else ''}"
        f"{package_text}."
    )

    preregistration = _mapping(metadata, "preregistration")
    funding = _mapping(metadata, "funding")
    data_and_code = _mapping(metadata, "data_and_code")
    conflicts = _mapping(metadata, "conflicts")
    return {
        "software_and_preregistration": (
            software_text + " " + str(preregistration.get("statement") or "").strip()
        ).strip(),
        "funding": " ".join(
            part
            for part in (
                str(funding.get("statement") or "").strip(),
                str(funding.get("funder_role") or "").strip(),
            )
            if part
        ),
        "data_and_code": str(data_and_code.get("statement") or "").strip(),
        "conflicts": str(conflicts.get("statement") or "").strip(),
    }


def _mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    nested = value.get(key) if isinstance(value, dict) else None
    return nested if isinstance(nested, dict) else {}


def _env(name: str, default: str) -> str:
    return str(os.getenv(name) or default).strip()


def _software_environment() -> dict[str, Any]:
    result: dict[str, Any] = {
        "mrcat_version": mrcat_version,
        "python_version": platform.python_version(),
        "r_version": "",
        "r_packages": {},
    }
    configured_rscript = str(os.getenv("RSCRIPT_BIN") or "").strip()
    environment_rscript = Path(sys.executable).with_name("Rscript")
    rscript = (
        configured_rscript
        or (str(environment_rscript) if environment_rscript.is_file() else "")
        or shutil.which("Rscript")
    )
    if not rscript:
        return result

    quoted = ",".join(f'"{name}"' for name in _R_PACKAGES)
    expression = (
        f"pkgs <- c({quoted}); "
        "writeLines(paste(R.version$major, R.version$minor, sep='.')); flush(stdout()); "
        "for (p in pkgs) if (length(find.package(p, quiet=TRUE))) { "
        "writeLines(paste(p, as.character(packageVersion(p)), sep='\\t')); "
        "flush(stdout()) }"
    )
    try:
        completed = subprocess.run(
            [rscript, "--vanilla", "-e", expression],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        stdout = completed.stdout
    except subprocess.TimeoutExpired as exc:
        # TimeoutExpired can contain bytes even with text=True. Keep completed
        # records, but never report a version whose line was interrupted.
        stdout = exc.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return result
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    lines = [line.strip() for line in stdout.splitlines(keepends=True)
             if line.endswith("\n") and line.strip()]
    if not lines:
        return result
    result["r_version"] = lines[0]
    result["r_packages"] = {
        name: version
        for line in lines[1:]
        if "\t" in line
        for name, version in [line.split("\t", 1)]
        if name in _R_PACKAGES and version
    }
    return result
