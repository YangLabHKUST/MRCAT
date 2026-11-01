"""Index installed-method notes that live beside the shared database.

``database.py`` registers reference data files. This module registers the
*how to use a method* notes that sit next to that data, so a coding agent can
discover a method, read its contract on demand, and then act — instead of
reverse-engineering a library interface from error messages.

Documents are Markdown files under ``database/docs/``. The catalog here is the
only place their ids and paths are defined. Tests and agents must not build
paths into that directory directly; call :func:`resource_doc` and
:func:`read_resource_doc`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ResourceDocError(RuntimeError):
    """A registered method note cannot be resolved or read."""

    def __init__(self, message: str, *, doc_id: str = '') -> None:
        super().__init__(message)
        self.doc_id = doc_id


@dataclass(frozen=True, slots=True)
class ResourceDoc:
    relative_path: str
    title: str
    summary: str
    resources: tuple[str, ...] = ()


# Paths are relative to the MRCAT workspace, alongside the data catalog.
_DOCS: dict[str, ResourceDoc] = {
    "mrlap": ResourceDoc(
        "database/docs/mrlap.md",
        "Reference data relevant to MRlap",
        "Installed MRlap version and the shared reference files it reads: LD "
        "scores, PLINK reference panels, and the HapMap3 SNP list. Resource "
        "inventory only; no workflow.",
        ("ldsc.eur", "plink.binary", "plink.eur.grch37", "plink.eur.grch38",
         "hapmap3.snplist_rdata", "hapmap3.mhc_rdata"),
    ),
}


def _workspace_dir(workspace_dir: str | os.PathLike[str] | None = None) -> Path:
    configured = workspace_dir or os.getenv("MRCAT_WORKSPACE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def resource_doc_ids() -> tuple[str, ...]:
    """List registered method-note identifiers."""
    return tuple(sorted(_DOCS))


def resource_docs(workspace_dir: str | os.PathLike[str] | None = None) -> list[dict]:
    """Return the compact index the agent sees in its context.

    Only identity and a short summary are exposed here; bodies are read on
    demand through :func:`read_resource_doc`.
    """
    root = _workspace_dir(workspace_dir)
    database_root = Path(os.getenv("MRCAT_DATABASE_DIR") or root / "database").expanduser().resolve()
    index = []
    for doc_id, spec in sorted(_DOCS.items()):
        path = (database_root / Path(spec.relative_path).relative_to("database")).resolve()
        index.append(dict(
            id=doc_id,
            title=spec.title,
            summary=spec.summary,
            resources=list(spec.resources),
            available=path.is_file(),
        ))
    return index


def resource_doc(doc_id: str, workspace_dir: str | os.PathLike[str] | None = None) -> Path:
    """Resolve one registered note to a validated absolute path."""
    normalized = str(doc_id or "").strip().lower()
    spec = _DOCS.get(normalized)
    if spec is None:
        raise ResourceDocError(
            f"Unknown method note: {doc_id!r}. Available: {', '.join(resource_doc_ids())}",
            doc_id=normalized,
        )
    root = _workspace_dir(workspace_dir)
    database_root = Path(os.getenv("MRCAT_DATABASE_DIR") or root / "database").expanduser().resolve()
    docs_root = database_root / "docs"
    path = (database_root / Path(spec.relative_path).relative_to("database")).resolve()
    try:
        path.relative_to(docs_root)
    except ValueError as exc:
        raise ResourceDocError(
            f"Method note escapes database/docs: {normalized}", doc_id=normalized
        ) from exc
    if not path.is_file():
        raise ResourceDocError(
            f"Method note {normalized!r} is not installed at {path}", doc_id=normalized
        )
    return path


def read_resource_doc(
    doc_id: str,
    workspace_dir: str | os.PathLike[str] | None = None,
    *,
    limit: int = 24000,
) -> str:
    """Read one note's Markdown body, bounded for a model request."""
    path = resource_doc(doc_id, workspace_dir)
    text = path.read_text(encoding="utf-8")
    if len(text) <= limit:
        return text
    marker = "\n\n[Document truncated; read the remaining sections with the read tool if needed.]\n"
    return text[:limit - len(marker)] + marker
