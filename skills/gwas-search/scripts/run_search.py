from __future__ import annotations

from contextlib import redirect_stdout
import sys

# Support the documented standalone CLI as well as package imports.
if not __package__:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    __package__ = "skills.gwas-search.scripts"

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from .common import write_json
from .search_orchestrator import run_target_search
from .search_sources import default_sources_from_config


def _load_input_json(path: str | None) -> Dict[str, Any]:
    if not path:
        return {}
    candidate = Path(path)
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(path)


def _unwrap_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("payload")
    if not isinstance(nested, dict):
        return dict(payload)
    merged = dict(nested)
    for key, value in payload.items():
        if key != "payload" and key not in merged:
            merged[key] = value
    return merged


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search downloadable GWAS candidates for one remote target"
    )
    parser.add_argument("--input-json", help="Structured JSON input path")
    parser.add_argument("--trait")
    parser.add_argument("--aliases", nargs="*", help="Equivalent terms chosen by the caller")
    parser.add_argument("--study-id")
    parser.add_argument("--source")
    parser.add_argument("--ancestry")
    parser.add_argument("--limit-per-source", type=int)
    parser.add_argument("--out")
    return parser


def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    return run_target_search(
        trait=str(payload.get("trait") or "").strip(),
        study_id=str(payload.get("study_id") or "").strip(),
        source=str(payload.get("source") or "").strip(),
        ancestry=payload.get("ancestry"),
        aliases=payload.get("aliases") or [],
        sources=default_sources_from_config(),
        preferred_sources=[],
        allow_source_fallback=True,
        limit_per_source=int(payload.get("limit_per_source", 20)),
        check_download=True,
        fallback_artifact_dir=Path(payload["output_dir"]) if payload.get("output_dir") else None,
    )


def main() -> None:
    args = _parser().parse_args()
    payload = _unwrap_payload(_load_input_json(args.input_json))
    for key in ("trait", "study_id", "source", "ancestry", "limit_per_source", "aliases"):
        value = getattr(args, key)
        if value is not None:
            payload[key] = value
    if args.out:
        payload["output_dir"] = str(Path(args.out).resolve().parent)
    with redirect_stdout(sys.stderr):
        result = run(payload)
    write_json(result, args.out)


if __name__ == "__main__":
    main()
