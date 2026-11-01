from __future__ import annotations

import csv
import gzip
import os
from pathlib import Path
from typing import Any

from mrcat.database import database


_VALID_BASES = {"A", "C", "G", "T"}
_COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C"}
_HM3_COORD_TO_RSID_CACHE: dict[str, dict[tuple[str, str, str, str], str]] = {}
_SUPPORTED_GENOME_BUILDS = {"grch37", "grch38"}


class CoordinateRsidMappingBlockedError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        failure_class: str = "coordinate_rsid_mapping_failed",
    ) -> None:
        super().__init__(message)
        self.details = dict(details or {})
        self.failure_class = failure_class
        self.pending_question = None


def _clean_value(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    return "" if text in {".", "NA", "NaN", "nan", "null", "None"} else text


def _hm3_reference_paths(
    ldscore_dir: str | os.PathLike[str] | None = None,
) -> tuple[Path, list[Path]]:
    base = _hm3_reference_dir(ldscore_dir)
    hm3_path = base / "w_hm3.snplist"
    ldscore_paths = [base / f"{chrom}.l2.ldscore.gz" for chrom in range(1, 23)]
    missing = [str(path) for path in [hm3_path, *ldscore_paths] if not path.exists()]
    if missing:
        raise CoordinateRsidMappingBlockedError(
            "Coordinate rsID mapping requires local HM3/ldscore reference files.",
            details={"missing_paths": missing, "ldscore_dir": str(base)},
            failure_class="coordinate_rsid_reference_missing",
        )
    return hm3_path, ldscore_paths


def _hm3_reference_dir(
    ldscore_dir: str | os.PathLike[str] | None = None,
) -> Path:
    return (
        Path(ldscore_dir).expanduser().resolve()
        if ldscore_dir
        else database("ldsc.eur")
    )


def _hm3_snplist_path(
    ldscore_dir: str | os.PathLike[str] | None = None,
) -> Path:
    path = _hm3_reference_dir(ldscore_dir) / "w_hm3.snplist"
    if not path.exists():
        raise CoordinateRsidMappingBlockedError(
            "Coordinate rsID mapping requires a local HM3 SNP list.",
            details={"missing_paths": [str(path)]},
            failure_class="coordinate_rsid_reference_missing",
        )
    return path


def _grch38_reference_path(
    bim_path: str | os.PathLike[str] | None = None,
) -> Path:
    path = (
        Path(bim_path).expanduser().resolve()
        if bim_path
        else Path(f"{database('plink.eur.grch38')}.bim")
    )
    if not path.exists():
        raise CoordinateRsidMappingBlockedError(
            "GRCh38 coordinate rsID mapping requires a local PLINK BIM reference.",
            details={"missing_paths": [str(path)], "genome_build": "grch38"},
            failure_class="coordinate_rsid_reference_missing",
        )
    return path


def _grch37_bim_reference_path(
    bim_path: str | os.PathLike[str] | None = None,
) -> Path:
    path = (
        Path(bim_path).expanduser().resolve()
        if bim_path
        else Path(f"{database('plink.eur.grch37')}.bim")
    )
    if not path.exists():
        raise CoordinateRsidMappingBlockedError(
            "GRCh37 coordinate checking requires a local PLINK BIM reference.",
            details={"missing_paths": [str(path)], "genome_build": "grch37"},
            failure_class="coordinate_rsid_reference_missing",
        )
    return path


def _sanitize_allele(value: Any) -> str:
    text = _clean_value(value).upper()
    return text if len(text) == 1 and text in _VALID_BASES else ""


def _normalize_chromosome(value: Any) -> str:
    chrom = _clean_value(value).upper()
    return chrom[3:] if chrom.startswith("CHR") else chrom


def _allele_pair_key(left: Any, right: Any) -> tuple[str, str] | None:
    left_text = _sanitize_allele(left)
    right_text = _sanitize_allele(right)
    if (
        left_text not in _VALID_BASES
        or right_text not in _VALID_BASES
        or left_text == right_text
    ):
        return None
    return tuple(sorted((left_text, right_text)))


def _coord_key(
    chrom: Any,
    pos: Any,
    left: Any,
    right: Any,
) -> tuple[str, str, str, str] | None:
    chrom_text = _normalize_chromosome(chrom)
    pos_text = _clean_value(pos)
    pair = _allele_pair_key(left, right)
    if not chrom_text or not pos_text or pair is None:
        return None
    return chrom_text, pos_text, pair[0], pair[1]


def _add_mapping_keys(
    coord_to_rsid: dict[tuple[str, str, str, str], str],
    ambiguous_keys: set[tuple[str, str, str, str]],
    *,
    chrom: Any,
    pos: Any,
    allele1: Any,
    allele2: Any,
    rsid: str,
) -> None:
    pair = _allele_pair_key(allele1, allele2)
    if pair is None:
        return
    keys = {
        _coord_key(chrom, pos, pair[0], pair[1]),
        _coord_key(
            chrom,
            pos,
            _COMPLEMENT[pair[0]],
            _COMPLEMENT[pair[1]],
        ),
    }
    for key in keys:
        if key is None:
            continue
        previous = coord_to_rsid.get(key)
        if previous is None:
            coord_to_rsid[key] = rsid
        elif previous != rsid:
            ambiguous_keys.add(key)


def load_hm3_coord_to_rsid_map(
    genome_build: str = "grch37",
    ldscore_dir: str | os.PathLike[str] | None = None,
    grch38_bim_path: str | os.PathLike[str] | None = None,
) -> dict[tuple[str, str, str, str], str]:
    build = _clean_value(genome_build).lower()
    if build not in _SUPPORTED_GENOME_BUILDS:
        raise CoordinateRsidMappingBlockedError(
            f"Unsupported genome build for coordinate rsID mapping: {genome_build}",
            details={"genome_build": build or None},
            failure_class="genome_build_unresolved",
        )
    if build == "grch37":
        hm3_path, ldscore_paths = _hm3_reference_paths(ldscore_dir)
    else:
        hm3_path = _hm3_snplist_path(ldscore_dir)
        ldscore_paths = []
    grch38_path = _grch38_reference_path(grch38_bim_path) if build == "grch38" else None
    reference_path = grch38_path or hm3_path.parent.resolve()
    cache_key = f"{build}:{reference_path}"
    cached = _HM3_COORD_TO_RSID_CACHE.get(cache_key)
    if cached is not None:
        return cached

    hm3_alleles: dict[str, tuple[str, str]] = {}
    with hm3_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            rsid = _clean_value(row.get("SNP")).lower()
            pair = _allele_pair_key(row.get("A1"), row.get("A2"))
            if rsid and pair is not None:
                hm3_alleles[rsid] = pair

    coord_to_rsid: dict[tuple[str, str, str, str], str] = {}
    ambiguous_keys: set[tuple[str, str, str, str]] = set()
    if build == "grch37":
        for path in ldscore_paths:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                for row in reader:
                    rsid = _clean_value(row.get("SNP"))
                    pair = hm3_alleles.get(rsid.lower())
                    if not rsid or pair is None:
                        continue
                    _add_mapping_keys(
                        coord_to_rsid,
                        ambiguous_keys,
                        chrom=row.get("CHR"),
                        pos=row.get("BP"),
                        allele1=pair[0],
                        allele2=pair[1],
                        rsid=rsid,
                    )
    else:
        assert grch38_path is not None
        with grch38_path.open("r", encoding="utf-8", newline="") as handle:
            for line in handle:
                fields = line.split()
                if len(fields) < 6:
                    continue
                chrom, rsid, _, pos, allele1, allele2 = fields[:6]
                if rsid.lower() not in hm3_alleles:
                    continue
                _add_mapping_keys(
                    coord_to_rsid,
                    ambiguous_keys,
                    chrom=chrom,
                    pos=pos,
                    allele1=allele1,
                    allele2=allele2,
                    rsid=rsid,
                )

    for key in ambiguous_keys:
        coord_to_rsid.pop(key, None)

    _HM3_COORD_TO_RSID_CACHE[cache_key] = coord_to_rsid
    return coord_to_rsid


def count_bim_coordinate_matches(
    coordinates: list[tuple[Any, Any, Any, Any]],
    genome_build: str,
    *,
    grch37_bim_path: str | os.PathLike[str] | None = None,
    grch38_bim_path: str | os.PathLike[str] | None = None,
) -> int:
    build = _clean_value(genome_build).lower()
    if build == "grch37":
        bim_path = _grch37_bim_reference_path(grch37_bim_path)
    elif build == "grch38":
        bim_path = _grch38_reference_path(grch38_bim_path)
    else:
        raise CoordinateRsidMappingBlockedError(
            f"Unsupported genome build for coordinate checking: {genome_build}",
            details={"genome_build": build or None},
            failure_class="genome_build_unresolved",
        )
    target_keys = {
        key
        for chrom, pos, allele1, allele2 in coordinates
        if (key := _coord_key(chrom, pos, allele1, allele2)) is not None
    }
    if not target_keys:
        return 0
    matched_keys: set[tuple[str, str, str, str]] = set()
    with bim_path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            fields = line.split()
            if len(fields) < 6:
                continue
            key = _coord_key(fields[0], fields[3], fields[4], fields[5])
            if key in target_keys:
                matched_keys.add(key)
                if len(matched_keys) == len(target_keys):
                    break
    return len(matched_keys)


def lookup_hm3_rsid(
    *,
    chrom: Any,
    pos: Any,
    allele1: Any = None,
    allele2: Any = None,
    ref: Any = None,
    alt: Any = None,
    coord_to_rsid: dict[tuple[str, str, str, str], str],
) -> str:
    left = allele1 if allele1 is not None else ref
    right = allele2 if allele2 is not None else alt
    key = _coord_key(chrom, pos, left, right)
    return _clean_value(coord_to_rsid.get(key)) if key is not None else ""
