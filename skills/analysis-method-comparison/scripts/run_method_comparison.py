from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any, TextIO

from mrcat.tool.mr.input_scale import input_scale_issue


PALETTE = [
    "#0F4D92",
    "#42949E",
    "#7C6CCF",
    "#D9544D",
    "#5B7FCA",
    "#B89BD9",
    "#767676",
    "#272727",
]
REQUIRED_PLOT_IDS = {
    "method_comparison_summary",
    "method_comparison_pvalues",
}
def compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def load_json_arg(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    candidate = Path(value)
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(value)


def execution_dir() -> Path:
    target = Path(
        os.getenv("MRCAT_EXECUTION_DIR") or Path.cwd() / "tmp_method_comparison"
    ).resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def run(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload or {})
    method_result_paths = payload.get("method_result_paths")
    if not isinstance(method_result_paths, list) or not method_result_paths:
        return blocked("analysis-method-comparison blocked: method_result_paths is required.", "missing_input")

    method_records, warnings, invalid_paths = load_method_records(method_result_paths)
    if invalid_paths:
        return blocked(
            "analysis-method-comparison blocked: invalid method result record path(s): "
            + ", ".join(invalid_paths),
            "invalid_method_result_record",
        )
    rows, normalization_warnings = normalize_method_results(method_records)
    warnings.extend(normalization_warnings)
    scale_issue = input_scale_issue(rows)
    if scale_issue:
        return blocked(scale_issue, "incompatible_input_scale")
    actual_scale = rows[0].get("input_scale", "unknown") if rows else "unknown"
    if actual_scale == "unknown":
        warnings.append("Legacy results lack input_scale; effect-unit comparability is unverified.")
    if len(rows) < 2:
        return blocked(
            "analysis-method-comparison blocked: at least two finite method estimates are required.",
            "insufficient_method_results",
        )
    missing_ci = [row["display_label"] for row in rows if not ci_ranges(row)]
    if missing_ci:
        return blocked(
            "analysis-method-comparison blocked: valid ci.ranges is required for every method: "
            + ", ".join(missing_ci)
            + ".",
            "missing_method_ci",
        )

    exec_dir = execution_dir()
    matplotlib_config_dir = exec_dir / ".matplotlib"
    cache_dir = exec_dir / ".cache"
    matplotlib_config_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_config_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
    except Exception as exc:
        return blocked(
            f"analysis-method-comparison blocked: matplotlib is unavailable: {compact_text(exc)}",
            "plot_dependency_unavailable",
        )

    configure_plot_style(plt)
    reports_dir = exec_dir / "reports"
    plots_dir = exec_dir / "plots"
    reports_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    table_path = reports_dir / "method_comparison_estimates.tsv"
    write_estimates_table(rows, table_path)

    exposure_label = compact_text(payload.get("exposure_label")) or "Exposure"
    outcome_label = compact_text(payload.get("outcome_label")) or "Outcome"
    plots = generate_core_plots(
        plt,
        rows,
        plots_dir,
    )
    selected_paths = [record.get("selected_mrdat_path") for record in method_records.values() if record.get("selected_mrdat_path")]
    mrdat_path = payload_path(selected_paths[0]) if selected_paths else None
    if mrdat_path is None:
        warnings.append("SNP plots require an actual selected method input; a cached pair table may use a different scale.")
    max_snp_points = max(100, min(as_int(payload.get("max_snp_points")) or 5000, 50000))
    points = read_mrdat_points(mrdat_path, limit=max_snp_points)
    selected_points = select_comparison_points(points, rows)
    if selected_points:
        plots.extend(
            generate_snp_plots(
                plt,
                rows,
                selected_points,
                plots_dir,
                exposure_label=exposure_label,
                outcome_label=outcome_label,
            )
        )
    elif mrdat_path:
        warnings.append("SNP-level plots were skipped because no compatible finite MRdat rows were found.")
    else:
        warnings.append("SNP-level plots were skipped because mrdat_path was not available.")

    generated_ids = {plot["plot_id"] for plot in plots}
    missing_core = sorted(REQUIRED_PLOT_IDS.difference(generated_ids))
    if missing_core:
        return blocked(
            f"analysis-method-comparison blocked: failed to generate required plots: {', '.join(missing_core)}",
            "plot_generation_failed",
        )

    deterministic_interpretation = build_interpretation(rows, warnings)
    result_record_path = reports_dir / "method_comparison_result_record.json"
    result = {
        "method": "method_comparison",
        "input_scale": actual_scale,
        "methods": rows,
        "comparison_table_path": str(table_path),
        "diagnostics": {
            "source_result_count": len(method_records),
            "source_result_paths": sorted(method_records),
            "estimate_count": len(rows),
            "valid_pvalue_count": sum(row.get("pval") is not None for row in rows),
            "mrdat_points_read": len(points),
            "snp_points_plotted": len(selected_points),
            "warnings": warnings,
        },
        "interpretation": {
            "summary": deterministic_interpretation,
            "recommendations": [],
        },
        "plot_manifest": {
            "plots": plots,
            "standard_bundle": {
                "expected_plot_ids": sorted(REQUIRED_PLOT_IDS),
                "generated_plot_ids": sorted(generated_ids),
                "missing_plot_ids": missing_core,
                "degraded": not bool(selected_points),
            },
        },
        "result_record_path": str(result_record_path),
    }
    result_record_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    artifacts = [
        {"path": str(table_path), "kind": "tsv", "summary": "Normalized MR method comparison table"},
        {"path": str(result_record_path), "kind": "json", "summary": "MR method comparison result record"},
    ]
    artifacts.extend(
        {"path": plot["path"], "kind": "png", "summary": plot["title"]}
        for plot in plots
    )
    summary = (
        f"analysis-method-comparison completed: compared {len(rows)} method "
        f"estimates and generated {len(plots)} plots. "
        f"{result['interpretation']['summary']}"
    )
    details: dict[str, Any] = {"result_status": "ok", "failure_class": None}
    return {
        "summary": summary,
        "outputs": {"status": "ok", "method_comparison_result": result},
        "details": details,
        "artifacts": artifacts,
    }


def blocked(summary: str, failure_class: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "outputs": {"status": "blocked", "failure_class": failure_class},
        "details": {"failure_class": failure_class},
    }


def load_method_records(
    raw_paths: list[Any],
) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    records: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    invalid_paths: list[str] = []
    for raw_path in raw_paths:
        path = payload_path(raw_path)
        path_text = compact_text(raw_path)
        if path is None:
            invalid_paths.append(path_text or "<empty>")
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            invalid_paths.append(str(path))
            continue
        if not isinstance(record, dict):
            invalid_paths.append(str(path))
            continue
        if compact_text(record.get("method")) == "method_comparison":
            invalid_paths.append(str(path))
            continue
        key = str(path)
        if key in records:
            warnings.append(f"Skipped duplicate method result record: {key}")
            continue
        records[key] = record
    return records, warnings, invalid_paths


def normalize_method_results(
    method_records: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    warnings: list[str] = []
    for result_path, result in method_records.items():
        methods = result.get("methods")
        if not isinstance(methods, list):
            continue
        endpoint = compact_text(result.get("method")) or Path(result_path).stem
        diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
        for index, raw_row in enumerate(methods):
            if not isinstance(raw_row, dict):
                continue
            beta = to_float(raw_row.get("beta.hat"))
            if beta is None:
                beta = to_float(raw_row.get("beta"))
            method_name = compact_text(raw_row.get("method")) or f"{endpoint}_{index + 1}"
            if beta is None:
                warnings.append(f"Skipped {method_name}: beta estimate is missing or non-finite.")
                continue
            raw_se = to_float(raw_row.get("se"))
            se = raw_se if raw_se is not None and raw_se > 0 else None
            if raw_se is not None and raw_se <= 0:
                warnings.append(f"{method_name}: non-positive standard error was treated as unavailable.")
            ci = normalize_ci(raw_row.get("ci"), method_name=method_name, warnings=warnings)
            pval = to_float(raw_row.get("pval"))
            if pval is not None and not 0 <= pval <= 1:
                warnings.append(f"{method_name}: p-value outside [0, 1] was treated as unavailable.")
                pval = None
            threshold = to_float(raw_row.get("Threshold"))
            selection_threshold = to_float(diagnostics.get("pvalue_threshold"))
            valid_iv = to_float(raw_row.get("Valid"))
            if valid_iv is None:
                valid_iv = to_float(raw_row.get("nvalid"))
            normalized.append(
                {
                    "method": method_name,
                    "display_label": method_name,
                    "source_result_path": str(result_path),
                    "input_scale": result.get("input_scale") or "unknown",
                    "endpoint": endpoint,
                    "Threshold": threshold,
                    "selection_threshold": selection_threshold,
                    "nsnp": as_int(raw_row.get("nsnp")),
                    "nvalid": valid_iv,
                    "beta.hat": beta,
                    "se": se,
                    "pval": pval,
                    "ci": ci,
                }
            )
    add_unique_display_labels(normalized)
    return normalized, warnings


def normalize_ci(
    raw_ci: Any,
    *,
    method_name: str,
    warnings: list[str],
) -> dict[str, Any]:
    if not isinstance(raw_ci, dict):
        warnings.append(f"{method_name}: ci is missing or is not an object.")
        return {"level": None, "ranges": []}
    level = to_float(raw_ci.get("level"))
    if level is None or not 0 < level < 1:
        warnings.append(f"{method_name}: ci.level must be between 0 and 1.")
        level = None
    raw_ranges = raw_ci.get("ranges")
    ranges: list[dict[str, float]] = []
    if isinstance(raw_ranges, list):
        for raw_range in raw_ranges:
            if not isinstance(raw_range, dict):
                continue
            lower = to_float(raw_range.get("lower"))
            upper = to_float(raw_range.get("upper"))
            if lower is None or upper is None:
                continue
            if lower > upper:
                lower, upper = upper, lower
            ranges.append({"lower": lower, "upper": upper})
    if not ranges:
        warnings.append(f"{method_name}: ci.ranges has no finite interval.")
    ranges.sort(key=lambda interval: (interval["lower"], interval["upper"]))
    return {"level": level, "ranges": ranges}


def add_unique_display_labels(rows: list[dict[str, Any]]) -> None:
    counts = Counter(str(row["method"]) for row in rows)
    for row in rows:
        if counts[str(row["method"])] > 1:
            endpoint = str(row.get("endpoint") or row.get("source_result_path") or "result")
            row["display_label"] = f"{row['method']} [{endpoint}]"


def write_estimates_table(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "display_label",
        "method",
        "endpoint",
        "source_result_path",
        "input_scale",
        "beta.hat",
        "se",
        "CILevel",
        "CIIntervals",
        "pval",
        "nsnp",
        "nvalid",
        "Threshold",
        "selection_threshold",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            table_row = dict(row)
            table_row["CILevel"] = ci_level(row)
            table_row["CIIntervals"] = format_ci_ranges(row, separator=" | ")
            writer.writerow(table_row)


def generate_core_plots(
    plt: Any,
    rows: list[dict[str, Any]],
    plots_dir: Path,
) -> list[dict[str, Any]]:
    explanation_dir = Path(__file__).resolve().parents[1] / "plot_explanations"
    plots: list[dict[str, Any]] = []

    summary_path = plots_dir / "method_comparison_summary.png"
    save_summary_plot(
        plt,
        rows,
        summary_path,
    )
    plots.append(
        plot_record(
            "method_comparison_summary",
            summary_path,
            "MR effect and instrument summary",
            explanation_dir,
        )
    )

    pvalue_path = plots_dir / "method_comparison_pvalues.png"
    save_pvalue_plot(plt, rows, pvalue_path)
    plots.append(plot_record("method_comparison_pvalues", pvalue_path, "MR p-value comparison", explanation_dir))

    return plots


def generate_snp_plots(
    plt: Any,
    rows: list[dict[str, Any]],
    points: list[dict[str, Any]],
    plots_dir: Path,
    *,
    exposure_label: str,
    outcome_label: str,
) -> list[dict[str, Any]]:
    explanation_dir = Path(__file__).resolve().parents[1] / "plot_explanations"
    plots: list[dict[str, Any]] = []
    scatter_path = plots_dir / "method_comparison_slope_overlay.png"
    save_slope_overlay(
        plt,
        rows,
        points,
        scatter_path,
        exposure_label=exposure_label,
        outcome_label=outcome_label,
    )
    plots.append(plot_record("method_comparison_slope_overlay", scatter_path, "SNP effects with method slope comparison", explanation_dir))

    funnel_points = wald_funnel_points(points)
    if funnel_points:
        funnel_path = plots_dir / "method_comparison_funnel.png"
        save_funnel_plot(plt, rows, funnel_points, funnel_path)
        plots.append(plot_record("method_comparison_funnel", funnel_path, "SNP-level method comparison funnel", explanation_dir))
    return plots


def save_summary_plot(
    plt: Any,
    rows: list[dict[str, Any]],
    path: Path,
) -> None:
    height = max(5.2, 0.58 * len(rows) + 2.2)
    effect_width = max(3.2, min(6.4, max(len(format_effect(row)) for row in rows) / 15))
    fig = plt.figure(figsize=(10.4 + effect_width, height))
    grid = fig.add_gridspec(1, 3, width_ratios=[5.4, effect_width, 1.15], wspace=0.04)
    forest_ax = fig.add_subplot(grid[0, 0])
    effect_ax = fig.add_subplot(grid[0, 1])
    iv_ax = fig.add_subplot(grid[0, 2])
    positions = list(range(len(rows)))
    x_min, x_max = forest_limits(rows)
    for index, (position, row) in enumerate(zip(positions, rows)):
        beta = row["beta.hat"]
        color = PALETTE[index % len(PALETTE)]
        for interval in ci_ranges(row):
            lower = interval["lower"]
            upper = interval["upper"]
            visible_lower = max(lower, x_min)
            visible_upper = min(upper, x_max)
            if visible_lower <= visible_upper:
                forest_ax.hlines(position, visible_lower, visible_upper, color=color, linewidth=2.4)
            if lower < x_min:
                forest_ax.scatter([x_min], [position], marker="<", color=color, s=52, zorder=3)
            else:
                forest_ax.vlines(lower, position - 0.08, position + 0.08, color=color, linewidth=1.4)
            if upper > x_max:
                forest_ax.scatter([x_max], [position], marker=">", color=color, s=52, zorder=3)
            else:
                forest_ax.vlines(upper, position - 0.08, position + 0.08, color=color, linewidth=1.4)
        plotted_beta = min(max(beta, x_min), x_max)
        if beta < x_min:
            marker = "<"
        elif beta > x_max:
            marker = ">"
        else:
            marker = "o"
        forest_ax.scatter(
            [plotted_beta],
            [position],
            marker=marker,
            s=76,
            facecolor="white",
            edgecolor=color,
            linewidth=2.0,
            zorder=4,
        )
        effect_ax.text(
            0.02,
            position,
            format_effect(row),
            va="center",
            ha="left",
            fontsize=12,
            fontweight="bold",
            color="#111827",
        )
        iv_ax.text(
            0.5,
            position,
            format_iv_count(row),
            va="center",
            ha="center",
            fontsize=12,
            fontweight="bold",
            color="#111827",
        )

    for axis in (forest_ax, effect_ax, iv_ax):
        axis.set_ylim(len(rows) - 0.5, -0.5)
        for position in range(len(rows) - 1):
            axis.axhline(position + 0.5, color="#E5E7EB", linewidth=0.55, zorder=0)

    forest_ax.axvline(0, color="#6B7280", linewidth=1.0, linestyle="--")
    forest_ax.set_xlim(x_min, x_max)
    forest_ax.set_yticks(positions)
    forest_ax.set_yticklabels(
        [row["display_label"] for row in rows],
        fontsize=12,
        fontweight="bold",
    )
    interval_label = comparison_interval_label(rows)
    forest_ax.set_xlabel("MR estimate (β)")
    forest_ax.set_title(f"Effect ({interval_label})", loc="left", fontsize=14, fontweight="bold", pad=14)
    style_axis(forest_ax)

    configure_text_column(effect_ax, title=rf"$\beta$ ({interval_label})")
    configure_text_column(iv_ax, title="#IV")
    fig.subplots_adjust(left=0.23, right=0.98, top=0.88, bottom=0.14)
    save_figure(fig, plt, path)


def configure_text_column(ax: Any, *, title: str) -> None:
    ax.set_xlim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, loc="left", fontsize=14, fontweight="bold", pad=14)
    for spine in ax.spines.values():
        spine.set_visible(False)


def save_pvalue_plot(plt: Any, rows: list[dict[str, Any]], path: Path) -> None:
    height = max(4.8, 0.46 * len(rows) + 1.8)
    fig, ax = plt.subplots(figsize=(10.5, height))
    positions = list(range(len(rows)))
    values: list[float] = []
    for index, (position, row) in enumerate(zip(positions, rows)):
        pval = row.get("pval")
        if pval is None:
            values.append(0.0)
            ax.scatter([0], [position], marker="x", color="#6B7280", s=45)
            ax.text(
                0.05,
                position,
                "Unavailable",
                va="center",
                fontsize=11,
                fontweight="bold",
                color="#6B7280",
            )
            continue
        value = -math.log10(max(float(pval), 1e-300))
        values.append(value)
        color = PALETTE[index % len(PALETTE)]
        ax.hlines(position, 0, value, color=color, linewidth=2.8, alpha=0.8)
        ax.scatter([value], [position], color=color, s=64, zorder=3)
    ax.axvline(-math.log10(0.05), color="#272727", linewidth=1.5, linestyle="--", label="P = 0.05")
    ax.set_yticks(positions)
    ax.set_yticklabels([row["display_label"] for row in rows])
    ax.invert_yaxis()
    ax.set_xlim(left=0, right=max(max(values, default=0.0) * 1.08, 1.7))
    ax.set_xlabel("−log10(P value)")
    ax.set_title("Statistical evidence across MR methods")
    ax.legend(frameon=False, loc="lower right")
    style_axis(ax)
    fig.tight_layout()
    save_figure(fig, plt, path)


def save_slope_overlay(
    plt: Any,
    rows: list[dict[str, Any]],
    points: list[dict[str, Any]],
    path: Path,
    *,
    exposure_label: str,
    outcome_label: str,
) -> None:
    fig, ax = plt.subplots(figsize=(12.0, 7.6))
    xs = [point["b_exp"] for point in points]
    ys = [point["b_out"] for point in points]
    ax.scatter(xs, ys, s=28, alpha=0.5, color="#5B7FCA", edgecolors="white", linewidths=0.35, label=f"Compared SNP union (n={len(points)})")
    x_min = min(min(xs), 0.0)
    x_max = max(max(xs), 0.0)
    if math.isclose(x_min, x_max):
        x_min, x_max = x_min - 1.0, x_max + 1.0
    line_x = [x_min, x_max]
    for index, row in enumerate(rows):
        color = PALETTE[index % len(PALETTE)]
        beta = row["beta.hat"]
        label = f"{row['display_label']}: beta={beta:.3g}"
        ax.plot(line_x, [beta * value for value in line_x], color=color, linewidth=2.4, label=label)
        for interval in ci_ranges(row):
            lower = interval["lower"]
            upper = interval["upper"]
            ax.plot(line_x, [lower * value for value in line_x], color=color, linewidth=1.1, linestyle="--", alpha=0.55)
            ax.plot(line_x, [upper * value for value in line_x], color=color, linewidth=1.1, linestyle="--", alpha=0.55)
    ax.axhline(0, color="#272727", linewidth=1.1)
    ax.axvline(0, color="#272727", linewidth=1.1)
    ax.set_xlabel(f"{short_label(exposure_label)} SNP effect")
    ax.set_ylabel(f"{short_label(outcome_label)} SNP effect")
    ax.set_title("SNP effects and causal slopes across methods")
    ax.legend(frameon=False, fontsize=10.5, loc="upper left", bbox_to_anchor=(1.02, 1.0))
    style_axis(ax)
    fig.tight_layout(rect=(0, 0, 0.76, 1))
    save_figure(fig, plt, path)


def save_funnel_plot(
    plt: Any,
    rows: list[dict[str, Any]],
    points: list[dict[str, float]],
    path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(12.0, 7.6))
    ratios = [point["ratio"] for point in points]
    precisions = [point["precision"] for point in points]
    ax.scatter(ratios, precisions, s=28, alpha=0.52, color="#5B7FCA", edgecolors="white", linewidths=0.35, label=f"SNP Wald ratios (n={len(points)})")
    min_precision = min(precisions)
    max_precision = max(precisions)
    reference = rows[0]["beta.hat"]
    lower_precision = max(min_precision * 0.9, max_precision / 100)
    precision_grid = [
        lower_precision + (max_precision - lower_precision) * index / 99
        for index in range(100)
    ]
    ax.fill_betweenx(
        precision_grid,
        [reference - 1.96 / value for value in precision_grid],
        [reference + 1.96 / value for value in precision_grid],
        color="#9CA3AF",
        alpha=0.16,
        label=f"Reference funnel: {rows[0]['display_label']}",
    )
    for index, row in enumerate(rows):
        color = PALETTE[index % len(PALETTE)]
        ax.axvline(row["beta.hat"], color=color, linewidth=1.5, label=row["display_label"])
    ax.set_xlabel("SNP Wald ratio")
    ax.set_ylabel("Approximate precision (1 / SE)")
    ax.set_title("SNP-level funnel with method estimates")
    ax.set_ylim(bottom=lower_precision)
    ax.legend(frameon=False, fontsize=10.5, loc="upper left", bbox_to_anchor=(1.02, 1.0))
    style_axis(ax)
    fig.tight_layout(rect=(0, 0, 0.76, 1))
    save_figure(fig, plt, path)


def read_mrdat_points(path: Path | None, *, limit: int) -> list[dict[str, Any]]:
    if not path or not path.exists() or not path.is_file():
        return []
    reservoir: list[dict[str, Any]] = []
    seen = 0
    rng = random.Random(20260710)
    with open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not {"b.exp", "b.out"}.issubset(set(reader.fieldnames or [])):
            return []
        for raw in reader:
            b_exp = to_float(raw.get("b.exp"))
            b_out = to_float(raw.get("b.out"))
            if b_exp is None or b_out is None:
                continue
            point = {
                "snp": compact_text(raw.get("SNP")),
                "b_exp": b_exp,
                "b_out": b_out,
                "se_exp": to_float(raw.get("se.exp")),
                "se_out": to_float(raw.get("se.out")),
                "pval_exp": to_float(raw.get("pval.exp")),
            }
            seen += 1
            if len(reservoir) < limit:
                reservoir.append(point)
                continue
            replacement = rng.randrange(seen)
            if replacement < limit:
                reservoir[replacement] = point
    return reservoir


def select_comparison_points(
    points: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not points:
        return []
    has_mrapss = any(str(row.get("endpoint") or "").lower() == "mrapss" for row in rows)
    thresholds = sorted(
        {
            float(row["selection_threshold"])
            for row in rows
            if row.get("selection_threshold") is not None and float(row["selection_threshold"]) > 0
        }
    )
    if has_mrapss or not thresholds:
        return points
    selected = [
        point
        for point in points
        if point.get("pval_exp") is not None
        and any(float(point["pval_exp"]) <= threshold for threshold in thresholds)
    ]
    return selected


def wald_funnel_points(points: list[dict[str, Any]]) -> list[dict[str, float]]:
    result: list[dict[str, float]] = []
    for point in points:
        b_exp = point["b_exp"]
        b_out = point["b_out"]
        se_out = point.get("se_out")
        if se_out is None or se_out <= 0 or abs(b_exp) <= 1e-15:
            continue
        ratio = b_out / b_exp
        se_ratio = se_out / abs(b_exp)
        precision = 1.0 / se_ratio
        if math.isfinite(ratio) and math.isfinite(precision):
            result.append({"ratio": ratio, "precision": precision})
    return result


def build_interpretation(rows: list[dict[str, Any]], warnings: list[str]) -> str:
    directions = {
        1 if row["beta.hat"] > 0 else -1 if row["beta.hat"] < 0 else 0
        for row in rows
    }
    if directions == {1}:
        direction_summary = "All supplied point estimates were positive."
    elif directions == {-1}:
        direction_summary = "All supplied point estimates were negative."
    elif directions == {0}:
        direction_summary = "All supplied point estimates were at the null."
    else:
        direction_summary = "The supplied point estimates had mixed directions."
    parts = [
        f"Compared {len(rows)} MR estimates. {direction_summary}",
        "Interpret direction, uncertainty intervals, instrument selection, and diagnostics under each method's assumptions; method-specific p-values are not votes and may test different null hypotheses.",
    ]
    multi_range = [row["display_label"] for row in rows if len(ci_ranges(row)) > 1]
    if multi_range:
        parts.append(
            "Disjoint supported ranges were retained for: " + ", ".join(multi_range) + "."
        )
    if warnings:
        parts.append("Warnings: " + " ".join(warnings))
    return " ".join(parts)


def forest_limits(rows: list[dict[str, Any]]) -> tuple[float, float]:
    betas = sorted(float(row["beta.hat"]) for row in rows)
    widths = sorted(
        interval["upper"] - interval["lower"]
        for row in rows
        for interval in ci_ranges(row)
    )
    beta_bounds = outlier_bounds(betas)
    width_bounds = outlier_bounds(widths)
    inliers: list[dict[str, Any]] = []
    for row in rows:
        beta = float(row["beta.hat"])
        row_widths = [interval["upper"] - interval["lower"] for interval in ci_ranges(row)]
        width = max(row_widths) if row_widths else None
        beta_ok = beta_bounds[0] <= beta <= beta_bounds[1]
        width_ok = width is None or width_bounds[0] <= width <= width_bounds[1]
        if beta_ok and width_ok:
            inliers.append(row)
    if len(inliers) < min(2, len(rows)):
        inliers = rows

    endpoints: list[float] = [0.0]
    for row in inliers:
        endpoints.append(float(row["beta.hat"]))
        for interval in ci_ranges(row):
            endpoints.extend([interval["lower"], interval["upper"]])
    lower = min(endpoints)
    upper = max(endpoints)
    span = upper - lower
    if span <= 1e-12:
        scale = max(abs(lower), 1e-3)
        lower -= scale
        upper += scale
        span = upper - lower
    padding = span * 0.1
    return lower - padding, upper + padding


def outlier_bounds(values: list[float]) -> tuple[float, float]:
    if len(values) < 4:
        return -math.inf, math.inf
    q1 = percentile(values, 0.25)
    q3 = percentile(values, 0.75)
    spread = q3 - q1
    if spread <= 0:
        return -math.inf, math.inf
    return q1 - 3.0 * spread, q3 + 3.0 * spread


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return ordered[lower_index]
    weight = position - lower_index
    return ordered[lower_index] * (1.0 - weight) + ordered[upper_index] * weight


def format_effect(row: dict[str, Any]) -> str:
    beta = format_estimate(row.get("beta.hat"))
    intervals = format_ci_ranges(row)
    if not intervals:
        return f"{beta} (CI unavailable)"
    return f"{beta} {intervals}"


def ci_ranges(row: dict[str, Any]) -> list[dict[str, float]]:
    ci = row.get("ci")
    if not isinstance(ci, dict):
        return []
    ranges = ci.get("ranges")
    if not isinstance(ranges, list):
        return []
    return [interval for interval in ranges if isinstance(interval, dict)]


def ci_level(row: dict[str, Any]) -> float | None:
    ci = row.get("ci")
    if not isinstance(ci, dict):
        return None
    return to_float(ci.get("level"))


def comparison_interval_label(rows: list[dict[str, Any]]) -> str:
    levels = {round(level, 10) for row in rows if (level := ci_level(row)) is not None}
    if len(levels) == 1:
        level = next(iter(levels))
        return f"{level * 100:g}% interval"
    return "interval"


def format_ci_ranges(row: dict[str, Any], *, separator: str = " ∪ ") -> str:
    return separator.join(
        f"[{format_estimate(interval['lower'])}, {format_estimate(interval['upper'])}]"
        for interval in ci_ranges(row)
    )


def format_iv_count(row: dict[str, Any]) -> str:
    nsnp = as_int(row.get("nsnp"))
    return str(nsnp) if nsnp is not None else "NA"


def format_estimate(value: Any) -> str:
    number = to_float(value)
    if number is None:
        return "NA"
    if number != 0 and (abs(number) < 0.001 or abs(number) >= 1000):
        return f"{number:.2e}"
    return f"{number:.3f}"


def configure_plot_style(plt: Any) -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "Liberation Sans", "sans-serif"],
            "font.weight": "bold",
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#272727",
            "axes.labelcolor": "#272727",
            "axes.titleweight": "bold",
            "axes.labelweight": "bold",
            "font.size": 12,
            "axes.titlesize": 15,
            "axes.labelsize": 13,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "legend.fontsize": 10.5,
            "legend.frameon": False,
            "axes.linewidth": 1.2,
            "xtick.color": "#4B5563",
            "ytick.color": "#4B5563",
            "savefig.facecolor": "white",
            "savefig.bbox": "tight",
        }
    )


def style_axis(ax: Any) -> None:
    ax.grid(axis="x", color="#D8DDE3", linewidth=0.7, alpha=0.7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(width=1.1, length=5)
    for label in [*ax.get_xticklabels(), *ax.get_yticklabels()]:
        label.set_fontweight("bold")


def save_figure(fig: Any, plt: Any, path: Path) -> None:
    fig.savefig(path.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    fig.savefig(path, dpi=600, bbox_inches="tight", facecolor="white")
    fig.savefig(
        path.with_suffix(".tiff"),
        dpi=600,
        bbox_inches="tight",
        facecolor="white",
        pil_kwargs={"compression": "tiff_lzw"},
    )
    plt.close(fig)


def plot_record(
    plot_id: str,
    path: Path,
    title: str,
    explanation_dir: Path,
) -> dict[str, Any]:
    return {
        "plot_id": plot_id,
        "path": str(path),
        "title": title,
        "source": "method_comparison_result",
        "explanation_path": str(explanation_dir / f"{plot_id}.md"),
    }


def open_text(path: Path) -> TextIO:
    if path.suffix.lower() in {".gz", ".bgz"}:
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def payload_path(value: Any) -> Path | None:
    text = compact_text(value)
    if not text:
        return None
    path = Path(text).expanduser()
    return path if path.exists() and path.is_file() else None


def to_float(value: Any) -> float | None:
    if value in (None, "", "NA", "NaN", "nan", "null"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def as_int(value: Any) -> int | None:
    number = to_float(value)
    return int(number) if number is not None else None


def short_label(value: Any, *, limit: int = 48) -> str:
    text = compact_text(value)
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate MR method comparison plots.")
    parser.add_argument("--input-json")
    args = parser.parse_args()
    print(json.dumps(run(load_json_arg(args.input_json)), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
