from __future__ import annotations

from mrcat.tool.MRTool.input_scale import input_scale_issue

import argparse
import csv
import json
import math
import os
import re
from pathlib import Path
from statistics import median
from typing import Any


AGGREGATE_METHODS = {
    "method_comparison",
    "mr_bidirectional",
    "mr_mediation",
    "mr_replication",
    "mr_result_synthesis",
    "mr_risk_factor_prioritization",
}
CATEGORY_COLORS = {
    "Forward only": "#D9544D",
    "Reverse only": "#5B7FCA",
    "Bidirectional": "#42949E",
    "Null": "#767676",
}
FORWARD = "#AE647D"
REVERSE = "#5C7899"
FORWARD_BACKGROUND = "#FAF1F4"
REVERSE_BACKGROUND = "#F0F4F8"
METHOD_PALETTE = ("#3282B8", "#209F91", "#9463B5", "#D56B95", "#DC9A32", "#5D68B2")


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _probability(value: Any) -> float | None:
    number = _float(value)
    return number if number is not None and 0.0 <= number <= 1.0 else None


def _integer(value: Any) -> int | None:
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
        or Path.cwd() / "tmp_analysis_bidirectional"
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


def _configure_plot_style(plt: Any) -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "Liberation Sans", "sans-serif"],
            "font.weight": "bold",
            "font.size": 12,
            "axes.titlesize": 16,
            "axes.labelsize": 13,
            "axes.labelweight": "bold",
            "axes.titleweight": "bold",
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "legend.fontsize": 10.5,
            "legend.frameon": False,
            "axes.linewidth": 1.2,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.bbox": "tight",
        }
    )


def _save_publication_figure(figure: Any, plt: Any, path: Path) -> None:
    figure.savefig(path, dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _ci(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"level": None, "ranges": []}
    ranges: list[dict[str, float]] = []
    for interval in list(raw.get("ranges") or []):
        if not isinstance(interval, dict):
            continue
        lower = _float(interval.get("lower"))
        upper = _float(interval.get("upper"))
        if lower is None or upper is None:
            continue
        ranges.append({"lower": min(lower, upper), "upper": max(lower, upper)})
    ranges.sort(key=lambda item: (item["lower"], item["upper"]))
    return {"level": _float(raw.get("level")), "ranges": ranges}


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
    if _text(record.get("method")) in AGGREGATE_METHODS:
        return None, f"aggregate result records are not accepted: {path_text}"
    return record, None


def _method_rows(
    paths: list[Any],
    *,
    pair_index: int,
    trait_x: str,
    trait_y: str,
    direction: str,
    seen_paths: set[str],
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_methods: set[str] = set()
    for raw_path in paths:
        path_text = _text(raw_path)
        if not path_text:
            return [], warnings, f"pair_results[{pair_index}] contains an empty {direction} result path"
        if path_text in seen_paths:
            return [], warnings, f"result record is assigned more than once: {path_text}"
        seen_paths.add(path_text)
        record, error = _load_record(path_text)
        if error:
            return [], warnings, error
        assert record is not None
        source_method = _text(record.get("method")) or Path(path_text).stem
        for method_index, raw_method in enumerate(record["methods"], start=1):
            if not isinstance(raw_method, dict):
                continue
            method = _text(raw_method.get("method")) or f"{source_method}_{method_index}"
            method_key = method.casefold()
            if method_key in seen_methods:
                return [], warnings, (
                    f"pair_results[{pair_index}] has duplicate {direction} method: {method}"
                )
            beta = _float(raw_method.get("beta.hat"))
            if beta is None:
                beta = _float(raw_method.get("beta"))
            if beta is None:
                warnings.append(
                    f"Skipped {trait_x} and {trait_y} {direction} {method}: beta is unavailable."
                )
                continue
            interval = _ci(raw_method.get("ci"))
            if not interval["ranges"]:
                return [], warnings, (
                    f"pair_results[{pair_index}] {direction} {method} has no finite ci.ranges"
                )
            seen_methods.add(method_key)
            rows.append(
                {
                    "pair_index": pair_index,
                    "trait_x": trait_x,
                    "trait_y": trait_y,
                    "direction": direction,
                    "exposure": trait_x if direction == "forward" else trait_y,
                    "outcome": trait_y if direction == "forward" else trait_x,
                    "method": method,
                    "method_key": method_key,
                    "source_method": source_method,
                    "source_result_path": path_text,
                        "input_scale": record.get("input_scale") or "unknown",
                    "beta.hat": beta,
                    "se": _float(raw_method.get("se")),
                    "pval": _probability(raw_method.get("pval")),
                    "nsnp": _integer(raw_method.get("nsnp")),
                    "ci": interval,
                }
            )
    if not rows:
        return [], warnings, f"pair_results[{pair_index}] has no usable {direction} estimates"
    return rows, warnings, None


def _normalize(payload: dict[str, Any]) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[str], str | None
]:
    raw_pairs = payload.get("pair_results")
    if not isinstance(raw_pairs, list) or not raw_pairs:
        return [], [], [], "pair_results must contain at least one trait pair"
    pairs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()
    seen_paths: set[str] = set()
    for pair_index, raw_pair in enumerate(raw_pairs, start=1):
        if not isinstance(raw_pair, dict):
            return [], [], warnings, f"pair_results[{pair_index}] must be an object"
        trait_x = _text(raw_pair.get("trait_x"))
        trait_y = _text(raw_pair.get("trait_y"))
        if not trait_x or not trait_y or trait_x.casefold() == trait_y.casefold():
            return [], [], warnings, (
                f"pair_results[{pair_index}] requires two distinct trait labels"
            )
        pair_key = tuple(sorted((trait_x.casefold(), trait_y.casefold())))
        if pair_key in seen_pairs:
            return [], [], warnings, f"duplicate unordered trait pair: {trait_x} and {trait_y}"
        seen_pairs.add(pair_key)
        forward_paths = raw_pair.get("forward_result_paths")
        reverse_paths = raw_pair.get("reverse_result_paths")
        if not isinstance(forward_paths, list) or not forward_paths:
            return [], [], warnings, f"{trait_x} -> {trait_y} requires forward_result_paths"
        if not isinstance(reverse_paths, list) or not reverse_paths:
            return [], [], warnings, f"{trait_y} -> {trait_x} requires reverse_result_paths"
        forward_rows, forward_warnings, error = _method_rows(
            forward_paths,
            pair_index=pair_index,
            trait_x=trait_x,
            trait_y=trait_y,
            direction="forward",
            seen_paths=seen_paths,
        )
        warnings.extend(forward_warnings)
        if error:
            return [], [], warnings, error
        reverse_rows, reverse_warnings, error = _method_rows(
            reverse_paths,
            pair_index=pair_index,
            trait_x=trait_x,
            trait_y=trait_y,
            direction="reverse",
            seen_paths=seen_paths,
        )
        warnings.extend(reverse_warnings)
        if error:
            return [], [], warnings, error
        rows.extend(forward_rows)
        rows.extend(reverse_rows)
        pairs.append(
            {
                "pair_index": pair_index,
                "trait_x": trait_x,
                "trait_y": trait_y,
                "forward_result_paths": [_text(value) for value in forward_paths],
                "reverse_result_paths": [_text(value) for value in reverse_paths],
            }
        )
    return pairs, rows, warnings, None


def _bh(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    adjusted = [1.0] * len(values)
    running = 1.0
    total = len(values)
    for rank_index in range(total - 1, -1, -1):
        original_index = order[rank_index]
        rank = rank_index + 1
        candidate = min(1.0, values[original_index] * total / rank)
        running = min(running, candidate)
        adjusted[original_index] = running
    return adjusted


def _adjust(rows: list[dict[str, Any]], method: str) -> None:
    for direction in ("forward", "reverse"):
        eligible = [row for row in rows if row["direction"] == direction and row["pval"] is not None]
        values = [float(row["pval"]) for row in eligible]
        adjusted = _bh(values) if method == "bh" else values
        for row, qvalue in zip(eligible, adjusted):
            row["qval"] = qvalue
    for row in rows:
        row.setdefault("qval", None)


def _margin(qvalue: float, alpha: float) -> float:
    return math.log10(alpha / max(qvalue, 1e-300))


def _category(forward_score: float, reverse_score: float) -> str:
    if forward_score > 0 and reverse_score > 0:
        return "Bidirectional"
    if forward_score > 0:
        return "Forward only"
    if reverse_score > 0:
        return "Reverse only"
    return "Null"


def _summaries(
    pairs: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    alpha: float,
) -> tuple[list[dict[str, Any]], str | None]:
    summaries: list[dict[str, Any]] = []
    for pair in pairs:
        pair_rows = [row for row in rows if row["pair_index"] == pair["pair_index"]]
        forward = {row["method_key"]: row for row in pair_rows if row["direction"] == "forward"}
        reverse = {row["method_key"]: row for row in pair_rows if row["direction"] == "reverse"}
        common = sorted(set(forward).intersection(reverse))
        usable = [
            key for key in common
            if forward[key].get("qval") is not None and reverse[key].get("qval") is not None
        ]
        if not usable:
            return [], (
                f"{pair['trait_x']} and {pair['trait_y']} have no common method with finite "
                "p-values in both directions"
            )
        forward_margins = [_margin(float(forward[key]["qval"]), alpha) for key in usable]
        reverse_margins = [_margin(float(reverse[key]["qval"]), alpha) for key in usable]
        forward_score = median(forward_margins)
        reverse_score = median(reverse_margins)
        category = _category(forward_score, reverse_score)
        method_categories = [
            _category(forward_margin, reverse_margin)
            for forward_margin, reverse_margin in zip(forward_margins, reverse_margins)
        ]
        agreement = sum(value == category for value in method_categories) / len(method_categories)
        summaries.append(
            {
                "pair_index": pair["pair_index"],
                "trait_x": pair["trait_x"],
                "trait_y": pair["trait_y"],
                "pair_label": f"{pair['trait_x']} ↔ {pair['trait_y']}",
                "common_methods": [forward[key]["method"] for key in usable],
                "forward_evidence_score": forward_score,
                "reverse_evidence_score": reverse_score,
                "category": category,
                "method_agreement": agreement,
            }
        )
    return summaries, None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return slug[:80] or "pair"


def _axis_limits(rows: list[dict[str, Any]]) -> tuple[float, float]:
    values: list[float] = []
    for row in rows:
        values.append(float(row["beta.hat"]))
        for interval in row["ci"]["ranges"]:
            values.extend([float(interval["lower"]), float(interval["upper"])])
    low, high = min(values), max(values)
    low = min(low, 0.0)
    high = max(high, 0.0)
    span = high - low
    padding = 0.12 * span if span > 0 else max(abs(high), 1.0) * 0.2
    return low - padding, high + padding


def _draw_forest_side(
    axis: Any,
    rows: dict[str, dict[str, Any]],
    methods: list[str],
    *,
    method_colors: dict[str, Any],
    background: str,
    reverse_axis: bool,
) -> None:
    y_values = list(range(len(methods)))[::-1]
    present = [rows[key] for key in methods if key in rows]
    low, high = _axis_limits(present)
    for index, (method_key, y_value) in enumerate(zip(methods, y_values)):
        if index % 2 == 0:
            axis.axhspan(y_value - 0.48, y_value + 0.48, color=background, zorder=0)
        row = rows.get(method_key)
        if row is None:
            axis.text(0.5, y_value, "NA", transform=axis.get_yaxis_transform(), ha="center", va="center", color="#A0A8B2")
            continue
        color = method_colors[method_key]
        for interval in row["ci"]["ranges"]:
            axis.plot(
                [interval["lower"], interval["upper"]],
                [y_value, y_value],
                color=color,
                linewidth=1.6,
                solid_capstyle="round",
                zorder=2,
            )
            axis.vlines(
                [interval["lower"], interval["upper"]],
                y_value - 0.09,
                y_value + 0.09,
                color=color,
                linewidth=1.0,
                zorder=2,
            )
        axis.scatter(
            row["beta.hat"],
            y_value,
            s=68,
            facecolor=color,
            edgecolor="#26313D",
            linewidth=0.8,
            zorder=3,
        )
    axis.axvline(0.0, color="#84909D", linewidth=1.1, linestyle="--")
    axis.set_ylim(-0.65, len(methods) - 0.35)
    axis.set_yticks([])
    axis.set_xlim((high, low) if reverse_axis else (low, high))
    axis.grid(axis="x", color="#E3E8EE", linewidth=0.6)
    for spine in ("top", "right", "left"):
        axis.spines[spine].set_visible(False)
    axis.tick_params(axis="x", labelsize=11, width=1.1, length=5)
    for label in axis.get_xticklabels():
        label.set_fontweight("normal")


def _mirrored_plot(
    plt: Any,
    pair: dict[str, Any],
    rows: list[dict[str, Any]],
    path: Path,
) -> None:
    from matplotlib.gridspec import GridSpec
    from textwrap import fill

    forward = {row["method_key"]: row for row in rows if row["direction"] == "forward"}
    reverse = {row["method_key"]: row for row in rows if row["direction"] == "reverse"}
    methods = sorted(set(forward).union(reverse), key=lambda key: (forward.get(key) or reverse[key])["method"].casefold())
    labels = {key: (forward.get(key) or reverse[key])["method"] for key in methods}
    palette = METHOD_PALETTE if len(methods) <= len(METHOD_PALETTE) else plt.get_cmap("tab20").resampled(len(methods)).colors
    method_colors = dict(zip(methods, palette))
    height = max(4.8, 0.72 * len(methods) + 2.3)
    figure = plt.figure(figsize=(13.6, height), facecolor="white")
    grid = GridSpec(
        1, 5, width_ratios=[0.66, 1.10, 0.45, 1.10, 0.45], wspace=0.04,
        left=0.025, right=0.985, bottom=0.13, top=0.80, figure=figure,
    )
    method_axis = figure.add_subplot(grid[0, 0])
    forward_axis = figure.add_subplot(grid[0, 1], sharey=method_axis)
    forward_stats_axis = figure.add_subplot(grid[0, 2], sharey=method_axis)
    reverse_axis = figure.add_subplot(grid[0, 3], sharey=method_axis)
    reverse_stats_axis = figure.add_subplot(grid[0, 4], sharey=method_axis)
    _draw_forest_side(forward_axis, forward, methods, method_colors=method_colors, background=FORWARD_BACKGROUND, reverse_axis=False)
    _draw_forest_side(reverse_axis, reverse, methods, method_colors=method_colors, background=REVERSE_BACKGROUND, reverse_axis=True)
    y_values = list(range(len(methods)))[::-1]
    for axis in (method_axis, forward_stats_axis, reverse_stats_axis):
        axis.set_xlim(0, 1)
        axis.set_ylim(-0.65, len(methods) - 0.35)
        axis.axis("off")
    method_axis.text(0.14, 1.03, "Method", transform=method_axis.transAxes,
                     ha="left", va="bottom", fontsize=12, fontweight="bold", color="#243447")
    for axis, color in (
        (forward_stats_axis, FORWARD),
        (reverse_stats_axis, REVERSE),
    ):
        for x_value, label in ((0.33, "P value"), (0.82, "IVs")):
            axis.text(x_value, 1.03, label, transform=axis.transAxes,
                      ha="center", va="bottom", fontsize=10.5, fontweight="bold", color=color)
    for index, (key, y_value) in enumerate(zip(methods, y_values)):
        if index % 2 == 0:
            method_axis.axhspan(y_value - 0.48, y_value + 0.48, color="#F6F7F8", zorder=0)
        method_axis.plot([0.035, 0.105], [y_value, y_value], color=method_colors[key], linewidth=1.6)
        method_axis.scatter(0.07, y_value, s=48, facecolor=method_colors[key],
                            edgecolor="#26313D", linewidth=0.8, zorder=3)
        method_axis.text(0.14, y_value, labels[key], ha="left", va="center",
                         fontsize=10.5, fontweight="bold", color="#344254")
        for axis, direction_rows, color, background in (
            (forward_stats_axis, forward, FORWARD, FORWARD_BACKGROUND),
            (reverse_stats_axis, reverse, REVERSE, REVERSE_BACKGROUND),
        ):
            if index % 2 == 0:
                axis.axhspan(y_value - 0.48, y_value + 0.48, color=background, zorder=0)
            row = direction_rows.get(key)
            p_value = "NA" if row is None or row.get("pval") is None else f"{row['pval']:.2g}"
            n_iv = "NA" if row is None or row.get("nsnp") is None else str(row["nsnp"])
            axis.text(0.33, y_value, p_value, ha="center", va="center",
                      fontsize=10.5, fontweight="normal", color="#4B5563")
            axis.text(0.82, y_value, n_iv, ha="center", va="center",
                      fontsize=10.5, fontweight="normal", color="#4B5563")
    for axis, title, exposure, outcome, color in (
        (forward_axis, "Forward MR", pair["trait_x"], pair["trait_y"], FORWARD),
        (reverse_axis, "Reverse MR", pair["trait_y"], pair["trait_x"], REVERSE),
    ):
        direction = fill(f"{exposure} → {outcome}", width=30, break_long_words=False, break_on_hyphens=False)
        axis.set_title(f"{title}\n{direction}", color=color, fontsize=11, fontweight="bold", pad=14)
    forward_axis.set_xlabel("MR estimate ($\\hat{\\beta}$)", fontsize=10.5, fontweight="normal")
    reverse_axis.set_xlabel("MR estimate ($\\hat{\\beta}$)", fontsize=10.5, fontweight="normal")
    figure.suptitle(f"{pair['trait_x']} ↔ {pair['trait_y']}", fontsize=16, fontweight="bold", y=0.98)
    _save_publication_figure(figure, plt, path)


def _quadrant_plot(plt: Any, summaries: list[dict[str, Any]], path: Path, *, title: str) -> None:
    from matplotlib.patches import Patch

    max_abs = max(
        1.5,
        max(abs(float(item["forward_evidence_score"])) for item in summaries),
        max(abs(float(item["reverse_evidence_score"])) for item in summaries),
    )
    limit = min(12.0, max_abs * 1.18)
    figure, axis = plt.subplots(figsize=(10.8, 9.0), facecolor="white")
    axis.axvspan(0, limit, ymin=0.5, ymax=1.0, color=CATEGORY_COLORS["Bidirectional"], alpha=0.10)
    axis.axvspan(-limit, 0, ymin=0.5, ymax=1.0, color=CATEGORY_COLORS["Reverse only"], alpha=0.09)
    axis.axvspan(0, limit, ymin=0.0, ymax=0.5, color=CATEGORY_COLORS["Forward only"], alpha=0.09)
    axis.axvspan(-limit, 0, ymin=0.0, ymax=0.5, color=CATEGORY_COLORS["Null"], alpha=0.08)
    axis.axhline(0, color="#334155", linewidth=1.2)
    axis.axvline(0, color="#334155", linewidth=1.2)
    for index, item in enumerate(summaries, start=1):
        x = max(-limit, min(limit, float(item["forward_evidence_score"])))
        y = max(-limit, min(limit, float(item["reverse_evidence_score"])))
        color = CATEGORY_COLORS[item["category"]]
        agreement = float(item["method_agreement"])
        axis.scatter(x, y, s=100 + 90 * agreement, color=color, edgecolor="white", linewidth=1.6, zorder=3)
        axis.annotate(
            item["pair_label"],
            (x, y),
            xytext=(6, 7 if index % 2 else -13),
            textcoords="offset points",
            fontsize=10.5,
            fontweight="bold",
            color="#253244",
        )
    axis.text(limit * 0.95, limit * 0.93, "Bidirectional\nX ↔ Y", ha="right", va="top", fontsize=15, fontweight="bold", color=CATEGORY_COLORS["Bidirectional"])
    axis.text(-limit * 0.95, limit * 0.93, "Reverse only\nY → X", ha="left", va="top", fontsize=15, fontweight="bold", color=CATEGORY_COLORS["Reverse only"])
    axis.text(limit * 0.95, -limit * 0.93, "Forward only\nX → Y", ha="right", va="bottom", fontsize=15, fontweight="bold", color=CATEGORY_COLORS["Forward only"])
    axis.text(-limit * 0.95, -limit * 0.93, "Null\nNo directional evidence", ha="left", va="bottom", fontsize=15, fontweight="bold", color=CATEGORY_COLORS["Null"])
    axis.set_xlim(-limit, limit)
    axis.set_ylim(-limit, limit)
    axis.set_xlabel("Forward MR cross-method evidence margin", fontsize=13, fontweight="bold")
    axis.set_ylabel("Reverse MR cross-method evidence margin", fontsize=13, fontweight="bold")
    axis.set_title(title, fontsize=18, fontweight="bold", pad=18)
    axis.grid(color="#DCE2E9", linewidth=0.6, alpha=0.8)
    axis.legend(
        handles=[Patch(facecolor=color, label=label) for label, color in CATEGORY_COLORS.items()],
        loc="lower center",
        bbox_to_anchor=(0.5, 0.035),
        bbox_transform=figure.transFigure,
        ncol=4,
        frameon=False,
        fontsize=10.5,
    )
    figure.subplots_adjust(bottom=0.17)
    figure.text(
        0.99,
        0.012,
        "Score = median log10(α / adjusted P); zero = evidence threshold",
        ha="right",
        fontsize=10.5,
        fontweight="bold",
        color="#667085",
    )
    _save_publication_figure(figure, plt, path)


def _write_table(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "trait_x", "trait_y", "direction", "exposure", "outcome", "method",
        "source_method", "input_scale", "beta.hat", "se", "pval", "qval",
        "nsnp", "CILevel", "CIIntervals", "source_result_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for row in rows:
            rendered = {field: row.get(field) for field in fields}
            rendered["CILevel"] = row["ci"].get("level")
            rendered["CIIntervals"] = " | ".join(
                f"[{item['lower']:.8g}, {item['upper']:.8g}]" for item in row["ci"]["ranges"]
            )
            writer.writerow(rendered)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    alpha = _float(payload.get("alpha"))
    alpha = 0.05 if alpha is None else alpha
    if not 0 < alpha < 1:
        return _blocked("analysis-bidirectional blocked: alpha must be between 0 and 1.", "invalid_parameters")
    adjust_method = _text(payload.get("p_adjust_method") or "bh").casefold()
    if adjust_method not in {"bh", "none"}:
        return _blocked("analysis-bidirectional blocked: p_adjust_method must be bh or none.", "invalid_parameters")
    pairs, rows, warnings, error = _normalize(dict(payload or {}))
    if error:
        return _blocked(f"analysis-bidirectional blocked: {error}.", "invalid_pair_results")
    scale_issue = input_scale_issue(rows)
    if scale_issue:
        return _blocked(scale_issue, "incompatible_input_scale")
    if rows and rows[0].get("input_scale") == "unknown":
        warnings.append("Legacy results lack input_scale; effect-unit comparability is unverified.")

    _adjust(rows, adjust_method)
    summaries, error = _summaries(pairs, rows, alpha=alpha)
    if error:
        return _blocked(f"analysis-bidirectional blocked: {error}.", "no_common_directional_methods")

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
            f"analysis-bidirectional blocked: matplotlib is unavailable: {_text(exc)}.",
            "plot_dependency_unavailable",
        )
    _configure_plot_style(plt)

    table_path = reports_dir / "bidirectional_estimates.tsv"
    quadrant_path = plots_dir / "bidirectional_evidence_quadrant.png"
    record_path = reports_dir / "bidirectional_result_record.json"
    _write_table(rows, table_path)
    explanation_dir = Path(__file__).resolve().parents[1] / "plot_explanations"
    plot_records: list[dict[str, Any]] = []
    mirrored_paths: list[str] = []
    for pair in pairs:
        pair_rows = [row for row in rows if row["pair_index"] == pair["pair_index"]]
        plot_path = plots_dir / f"bidirectional_mirrored_forest_{pair['pair_index']:02d}_{_slug(pair['trait_x'] + '_' + pair['trait_y'])}.png"
        _mirrored_plot(plt, pair, pair_rows, plot_path)
        mirrored_paths.append(str(plot_path))
        plot_records.append(
            {
                "plot_id": f"bidirectional_mirrored_forest_{pair['pair_index']:02d}",
                "path": str(plot_path),
                "title": f"Bidirectional mirrored forest: {pair['trait_x']} and {pair['trait_y']}",
                "source": "mr_bidirectional_result",
                "explanation_path": str(explanation_dir / "bidirectional_mirrored_forest.md"),
            }
        )
    title = _text(payload.get("title")) or "Bidirectional MR evidence landscape"
    _quadrant_plot(plt, summaries, quadrant_path, title=title)
    plot_records.append(
        {
            "plot_id": "bidirectional_evidence_quadrant",
            "path": str(quadrant_path),
            "title": title,
            "source": "mr_bidirectional_result",
            "explanation_path": str(explanation_dir / "bidirectional_evidence_quadrant.md"),
        }
    )
    category_counts = {
        category: sum(item["category"] == category for item in summaries)
        for category in CATEGORY_COLORS
    }
    summary = (
        f"Bidirectional MR analysis summarized {len(pairs)} trait pair(s) and "
        f"{len(rows)} directional method estimate(s): "
        + ", ".join(f"{key}={value}" for key, value in category_counts.items())
        + "."
    )
    result = {
        "input_scale": rows[0].get("input_scale", "unknown"),
        "method": "mr_bidirectional",
        "pairs": pairs,
        "pair_summaries": summaries,
        "estimates": rows,
        "summary_table_path": str(table_path),
        "mirrored_forest_plot_paths": mirrored_paths,
        "quadrant_plot_path": str(quadrant_path),
        "diagnostics": {
            "pair_count": len(pairs),
            "estimate_count": len(rows),
            "alpha": alpha,
            "p_adjust_method": adjust_method,
            "category_counts": category_counts,
            "warnings": warnings,
        },
        "interpretation": {
            "summary": summary,
            "recommendations": [
                "Interpret quadrant labels as cross-method directional MR evidence, not proof of causal truth.",
                "Inspect each mirrored forest because forward and reverse effects use different instruments and scales.",
            ],
        },
        "plot_manifest": {"plots": plot_records},
        "result_record_path": str(record_path),
    }
    record_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "summary": summary,
        "outputs": {"status": "ok", "mr_bidirectional_result": result},
        "details": {"result_status": "ok", "failure_class": None},
        "artifacts": [
            {"path": str(table_path), "kind": "tsv", "summary": "Bidirectional MR estimates"},
            *[
                {"path": path, "kind": "png", "summary": "Bidirectional mirrored forest"}
                for path in mirrored_paths
            ],
            {"path": str(quadrant_path), "kind": "png", "summary": title},
            {"path": str(record_path), "kind": "json", "summary": "Bidirectional MR result record"},
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate completed bidirectional MR results")
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
