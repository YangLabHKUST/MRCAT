from __future__ import annotations

from mrcat.tool.mr.input_scale import input_scale_issue

import argparse
import csv
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _float(value)
    return int(number) if number is not None else None


def _input(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    candidate = Path(value)
    if candidate.is_file():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(value)


def _execution_dir() -> Path:
    path = Path(
        os.getenv("MRCAT_EXECUTION_DIR")
        or Path.cwd() / "tmp_mr_result_synthesis"
    ).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _blocked(summary: str, failure_class: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "outputs": {"status": "blocked", "failure_class": failure_class},
        "details": {
            "result_status": "blocked",
            "failure_class": failure_class,
        },
    }


def _ci(raw_ci: Any) -> dict[str, Any]:
    if not isinstance(raw_ci, dict):
        return {"level": None, "ranges": []}
    ranges: list[dict[str, float]] = []
    for interval in list(raw_ci.get("ranges") or []):
        if not isinstance(interval, dict):
            continue
        lower = _float(interval.get("lower"))
        upper = _float(interval.get("upper"))
        if lower is None or upper is None:
            continue
        ranges.append(
            {
                "lower": min(lower, upper),
                "upper": max(lower, upper),
            }
        )
    ranges.sort(key=lambda interval: (interval["lower"], interval["upper"]))
    return {"level": _float(raw_ci.get("level")), "ranges": ranges}


def _load_record(path_text: str) -> tuple[dict[str, Any] | None, str | None]:
    path = Path(path_text).expanduser()
    if not path.is_file():
        return None, f"result record does not exist: {path_text}"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"result record is not readable JSON: {path_text}: {exc}"
    if not isinstance(record, dict) or not isinstance(record.get("methods"), list):
        return None, f"result record has no methods array: {path_text}"
    if _text(record.get("method")) in {
        "method_comparison",
        "mr_result_synthesis",
    }:
        return None, f"aggregate result records cannot be synthesized: {path_text}"
    return record, None


def _design(pairs: list[dict[str, Any]]) -> str:
    exposures = {_text(pair["exposure"]).casefold() for pair in pairs}
    outcomes = {_text(pair["outcome"]).casefold() for pair in pairs}
    if len(exposures) > 1 and len(outcomes) == 1:
        return "multi_exposure_single_outcome"
    if len(exposures) == 1 and len(outcomes) > 1:
        return "single_exposure_multi_outcome"
    return "multi_exposure_multi_outcome"


def _normalize(payload: dict[str, Any]) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
    str | None,
]:
    raw_pairs = payload.get("pair_results")
    if not isinstance(raw_pairs, list) or len(raw_pairs) < 2:
        return [], [], [], "pair_results must contain at least two directed pairs"
    pairs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()
    seen_paths: set[str] = set()
    for pair_index, raw_pair in enumerate(raw_pairs, start=1):
        if not isinstance(raw_pair, dict):
            return [], [], warnings, f"pair_results[{pair_index}] must be an object"
        exposure = _text(raw_pair.get("exposure"))
        outcome = _text(raw_pair.get("outcome"))
        paths = raw_pair.get("result_paths")
        if not exposure or not outcome:
            return [], [], warnings, f"pair_results[{pair_index}] requires exposure and outcome"
        pair_key = (exposure.casefold(), outcome.casefold())
        if pair_key in seen_pairs:
            return [], [], warnings, f"duplicate directed pair: {exposure} -> {outcome}"
        seen_pairs.add(pair_key)
        if not isinstance(paths, list) or not paths:
            return [], [], warnings, f"{exposure} -> {outcome} requires result_paths"
        pair_paths: list[str] = []
        pair_row_start = len(rows)
        for raw_path in paths:
            path_text = _text(raw_path)
            if not path_text:
                return [], [], warnings, f"{exposure} -> {outcome} contains an empty result path"
            if path_text in seen_paths:
                return [], [], warnings, f"result record is assigned more than once: {path_text}"
            seen_paths.add(path_text)
            record, error = _load_record(path_text)
            if error:
                return [], [], warnings, error
            assert record is not None
            pair_paths.append(path_text)
            source_method = _text(record.get("method")) or Path(path_text).stem
            for method_index, raw_method in enumerate(record["methods"], start=1):
                if not isinstance(raw_method, dict):
                    continue
                beta = _float(raw_method.get("beta.hat"))
                if beta is None:
                    beta = _float(raw_method.get("beta"))
                method = _text(raw_method.get("method")) or f"{source_method}_{method_index}"
                if beta is None:
                    warnings.append(
                        f"Skipped {exposure} -> {outcome} {method}: beta is unavailable."
                    )
                    continue
                ci = _ci(raw_method.get("ci"))
                if not ci["ranges"]:
                    return [], [], warnings, (
                        f"{exposure} -> {outcome} {method} has no finite ci.ranges"
                    )
                rows.append(
                    {
                        "exposure": exposure,
                        "outcome": outcome,
                        "method": method,
                        "source_method": source_method,
                        "source_result_path": path_text,
                        "input_scale": record.get("input_scale") or "unknown",
                        "beta.hat": beta,
                        "se": _float(raw_method.get("se")),
                        "pval": _float(raw_method.get("pval")),
                        "nsnp": _int(raw_method.get("nsnp")),
                        "ci": ci,
                    }
                )
        if len(rows) == pair_row_start:
            return [], [], warnings, f"{exposure} -> {outcome} has no finite estimates"
        pairs.append(
            {
                "exposure": exposure,
                "outcome": outcome,
                "result_paths": pair_paths,
            }
        )
    counts = Counter(
        (row["exposure"].casefold(), row["outcome"].casefold(), row["method"].casefold())
        for row in rows
    )
    for row in rows:
        key = (
            row["exposure"].casefold(),
            row["outcome"].casefold(),
            row["method"].casefold(),
        )
        row["display_label"] = (
            f"{row['exposure']} → {row['outcome']} | {row['method']}"
            + (f" [{row['source_method']}]" if counts[key] > 1 else "")
        )
    return pairs, rows, warnings, None


def _write_table(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "exposure",
        "outcome",
        "method",
        "source_method",
        "input_scale", "beta.hat",
        "se",
        "pval",
        "nsnp",
        "CILevel",
        "CIIntervals",
        "source_result_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for row in rows:
            table_row = {field: row.get(field) for field in fields}
            table_row["CILevel"] = row["ci"].get("level")
            table_row["CIIntervals"] = " | ".join(
                f"[{interval['lower']:.8g}, {interval['upper']:.8g}]"
                for interval in row["ci"]["ranges"]
            )
            writer.writerow(table_row)


def _configure_plot_style(plt: Any) -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "Liberation Sans", "sans-serif"],
            "font.weight": "bold",
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": 12,
            "axes.titlesize": 17,
            "axes.labelsize": 13,
            "axes.labelweight": "bold",
            "axes.titleweight": "bold",
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "axes.linewidth": 1.2,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.bbox": "tight",
        }
    )


def _save_publication_figure(figure: Any, plt: Any, path: Path) -> None:
    figure.savefig(path.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    figure.savefig(path.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    figure.savefig(path, dpi=600, bbox_inches="tight", facecolor="white")
    figure.savefig(
        path.with_suffix(".tiff"),
        dpi=600,
        bbox_inches="tight",
        facecolor="white",
        pil_kwargs={"compression": "tiff_lzw"},
    )
    plt.close(figure)


def _forest_plot(
    plt: Any,
    rows: list[dict[str, Any]],
    path: Path,
    *,
    title: str,
) -> None:
    height = max(4.5, min(18.0, 0.48 * len(rows) + 2.2))
    figure, axis = plt.subplots(figsize=(12.5, height), facecolor="white")
    y_values = list(range(len(rows)))[::-1]
    for y_value, row in zip(y_values, rows):
        for interval in row["ci"]["ranges"]:
            axis.plot(
                [interval["lower"], interval["upper"]],
                [y_value, y_value],
                color="#0F4D92",
                linewidth=2.6,
                solid_capstyle="round",
            )
        axis.scatter(
            row["beta.hat"],
            y_value,
            s=72,
            facecolor="white",
            edgecolor="#B64342",
            linewidth=2.2,
            zorder=3,
        )
    axis.axvline(0.0, color="#4D4D4D", linewidth=1.4, linestyle="--")
    axis.set_yticks(y_values)
    axis.set_yticklabels(
        [row["display_label"] for row in rows],
        fontsize=11,
        fontweight="bold",
    )
    axis.set_xlabel("Reported causal-effect estimate (β)")
    axis.set_title(title, fontsize=17, fontweight="bold", pad=16)
    axis.grid(axis="x", color="#D8DDE3", linewidth=0.75)
    axis.tick_params(width=1.1, length=5)
    figure.tight_layout()
    _save_publication_figure(figure, plt, path)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    pairs, rows, warnings, error = _normalize(dict(payload or {}))
    if error:
        return _blocked(f"analysis-result-synthesis blocked: {error}.", "invalid_pair_results")
    scale_issue = input_scale_issue(rows)
    if scale_issue:
        return _blocked(scale_issue, "incompatible_input_scale")
    if rows and rows[0].get("input_scale") == "unknown":
        warnings.append("Legacy results lack input_scale; effect-unit comparability is unverified.")

    design = _design(pairs)
    exec_dir = _execution_dir()
    reports_dir = exec_dir / "reports"
    plots_dir = exec_dir / "plots"
    reports_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(exec_dir / ".matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(exec_dir / ".cache"))
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
    except Exception as exc:
        return _blocked(
            f"analysis-result-synthesis blocked: matplotlib is unavailable: {_text(exc)}.",
            "plot_dependency_unavailable",
        )
    _configure_plot_style(plt)

    table_path = reports_dir / "mr_result_synthesis.tsv"
    plot_path = plots_dir / "mr_result_synthesis_forest.png"
    record_path = reports_dir / "mr_result_synthesis_result_record.json"
    _write_table(rows, table_path)
    title = _text(payload.get("title")) or "MR results across directed trait pairs"
    _forest_plot(plt, rows, plot_path, title=title)
    explanation_path = (
        Path(__file__).resolve().parents[1]
        / "plot_explanations"
        / "mr_result_synthesis_forest.md"
    )
    significant = sum(
        row.get("pval") is not None and 0 <= float(row["pval"]) < 0.05
        for row in rows
    )
    summary = (
        f"Synthesized {len(rows)} MR estimate(s) across {len(pairs)} directed "
        f"pair(s) as {design}; {significant} estimate(s) had reported p<0.05."
    )
    plot_record = {
        "plot_id": "mr_result_synthesis_forest",
        "path": str(plot_path),
        "title": title,
        "source": "mr_result_synthesis",
        "explanation_path": str(explanation_path),
    }
    result = {
        "input_scale": rows[0].get("input_scale", "unknown"),
        "method": "mr_result_synthesis",
        "design": design,
        "pairs": pairs,
        "estimates": rows,
        "summary_table_path": str(table_path),
        "forest_plot_path": str(plot_path),
        "diagnostics": {
            "pair_count": len(pairs),
            "result_record_count": sum(len(pair["result_paths"]) for pair in pairs),
            "estimate_count": len(rows),
            "reported_p_lt_0_05_count": significant,
            "warnings": warnings,
        },
        "interpretation": {
            "summary": summary,
            "recommendations": [
                "Treat cross-pair differences as descriptive unless traits, units, instruments, samples, ancestries, and methods are comparable."
            ],
        },
        "plot_manifest": {"plots": [plot_record]},
        "result_record_path": str(record_path),
    }
    record_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "summary": summary,
        "outputs": {"status": "ok", "mr_result_synthesis": result},
        "details": {"result_status": "ok", "failure_class": None},
        "artifacts": [
            {"path": str(table_path), "kind": "tsv", "summary": "Cross-pair MR estimates"},
            {"path": str(plot_path), "kind": "png", "summary": title},
            {"path": str(record_path), "kind": "json", "summary": "MR result synthesis record"},
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize completed MR results across pairs")
    parser.add_argument("--input-json")
    parser.add_argument("--output-json")
    args = parser.parse_args()
    result = run(_input(args.input_json))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_json:
        Path(args.output_json).write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
