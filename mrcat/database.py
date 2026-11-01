"""Resolve shared MRCAT reference data from one internal catalog.

Skills declare resource ids in the ``resources`` section of their input schema,
or call :func:`database` from Python helpers. They should not build paths to
shared reference data themselves.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class DatabaseResourceError(RuntimeError):
    """A registered MRCAT database resource cannot be resolved."""

    def __init__(
        self,
        message: str,
        *,
        resource_id: str,
        missing_paths: tuple[Path, ...] = (),
    ) -> None:
        super().__init__(message)
        self.resource_id = resource_id
        self.missing_paths = missing_paths


@dataclass(frozen=True, slots=True)
class DatabaseResource:
    relative_path: str
    kind: Literal["file", "directory", "prefix"]
    required_members: tuple[str, ...] = ()


_LDSC_EUR_MEMBERS = (
    "w_hm3.snplist",
    *(f"{chrom}.l2.ldscore.gz" for chrom in range(1, 23)),
    *(f"{chrom}.l2.M_5_50" for chrom in range(1, 23)),
)


# Paths are relative to the MRCAT workspace. This is the only place where the
# physical layout of shared reference data is defined.
_DATABASE: dict[str, DatabaseResource] = {
    "hapmap3.snplist_rdata": DatabaseResource(
        "database/hapmap3/w_hm3.snplist.rda",
        "file",
    ),
    "hapmap3.mhc_rdata": DatabaseResource(
        "database/hapmap3/MHC.SNPs.rda",
        "file",
    ),
    "ldsc.eur": DatabaseResource(
        "database/ldsc/eur_w_ld_chr",
        "directory",
        _LDSC_EUR_MEMBERS,
    ),
    "plink.binary": DatabaseResource(
        "database/plink/bin/plink1.9/plink",
        "file",
    ),
    "plink.eur.grch37": DatabaseResource(
        "database/plink/EUR/data_maf0.01_rs_ref",
        "prefix",
        (".bed", ".bim", ".fam"),
    ),
    "plink.eur.grch38": DatabaseResource(
        "database/plink/EUR/EUR_phase3_hg38_autosomes",
        "prefix",
        (".bed", ".bim", ".fam"),
    ),
    "plink.afr.grch38": DatabaseResource(
        "database/plink/AFR/AFR_phase3_hg38_autosomes",
        "prefix",
        (".bed", ".bim", ".fam"),
    ),
    "plink.eas.grch38": DatabaseResource(
        "database/plink/EAS/EAS_phase3_hg38_autosomes",
        "prefix",
        (".bed", ".bim", ".fam"),
    ),
    "plink.sas.grch38": DatabaseResource(
        "database/plink/SAS/SAS_phase3_hg38_autosomes",
        "prefix",
        (".bed", ".bim", ".fam"),
    ),
}


def database(
    resource_id: str,
    *,
    workspace_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Return a validated absolute path for a shared MRCAT resource."""

    normalized_id = str(resource_id or "").strip().lower()
    spec = _DATABASE.get(normalized_id)
    if spec is None:
        raise DatabaseResourceError(
            f"Unknown MRCAT database resource: {resource_id!r}",
            resource_id=normalized_id,
        )

    root = _workspace_dir(workspace_dir)
    data_root = Path(os.getenv("MRCAT_DATABASE_DIR") or root / "database").expanduser().resolve()
    path = (data_root / Path(spec.relative_path).relative_to("database")).resolve()
    try:
        path.relative_to(data_root)
    except ValueError as exc:
        raise DatabaseResourceError(
            f"MRCAT database resource escapes the workspace: {normalized_id}",
            resource_id=normalized_id,
        ) from exc

    missing = _missing_paths(path, spec)
    if missing:
        rendered = ", ".join(str(item) for item in missing[:5])
        if len(missing) > 5:
            rendered += f", ... ({len(missing)} missing paths)"
        raise DatabaseResourceError(
            f"MRCAT database resource '{normalized_id}' is incomplete: {rendered}",
            resource_id=normalized_id,
            missing_paths=missing,
        )
    return path


def database_resource_ids() -> tuple[str, ...]:
    """List registered resource identifiers for diagnostics and documentation."""

    return tuple(sorted(_DATABASE))


def _workspace_dir(
    workspace_dir: str | os.PathLike[str] | None,
) -> Path:
    configured = workspace_dir or os.getenv("MRCAT_WORKSPACE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def _missing_paths(
    path: Path,
    spec: DatabaseResource,
) -> tuple[Path, ...]:
    if spec.kind == "file":
        return () if path.is_file() else (path,)
    if spec.kind == "directory":
        if not path.is_dir():
            return (path,)
        return tuple(path / member for member in spec.required_members if not (path / member).is_file())
    return tuple(
        Path(f"{path}{suffix}")
        for suffix in spec.required_members
        if not Path(f"{path}{suffix}").is_file()
    )
