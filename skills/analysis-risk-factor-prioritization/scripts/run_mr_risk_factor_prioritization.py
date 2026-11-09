from __future__ import annotations

from mrcat.tool.MRTool.input_scale import input_scale_issue

import argparse
import csv
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


AGGREGATE_METHODS = {
    "method_comparison",
    "mr_mediation",
    "mr_result_synthesis",
    "mr_risk_factor_prioritization",
}
POSITIVE = "#B64342"
NEGATIVE = "#0F4D92"
NEUTRAL = "#767676"


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
        or Path.cwd() / "tmp_mr_risk_factor_prioritization"
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
    for raw_interval in list(raw_ci.get("ranges") or []):
        if not isinstance(raw_interval, dict):
            continue
        lower = _float(raw_interval.get("lower"))
        upper = _float(raw_interval.get("upper"))
        if lower is None or upper is None:
            continue
        ranges.append({"lower": min(lower, upper), "upper": max(lower, upper)})
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
    if _text(record.get("method")) in AGGREGATE_METHODS:
        return None, f"aggregate result record is not a method endpoint: {path_text}"
    return record, None


def _method_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _text(value).casefold())


def _normalize(
    payload: dict[str, Any],
) -> tuple[str, list[str], list[dict[str, Any]], list[str], str | None]:
    outcome = _text(payload.get("outcome"))
    if not outcome:
        return "", [], [], [], "outcome is required"
    raw_exposures = payload.get("exposure_results")
    if not isinstance(raw_exposures, list) or len(raw_exposures) < 2:
        return outcome, [], [], [], (
            "exposure_results must contain at least two exposures"
        )

    exposures: list[str] = []
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_exposures: set[str] = set()
    seen_paths: set[str] = set()
    for exposure_index, raw_exposure in enumerate(raw_exposures, start=1):
        if not isinstance(raw_exposure, dict):
            return outcome, [], [], warnings, (
                f"exposure_results[{exposure_index}] must be an object"
            )
        exposure = _text(raw_exposure.get("exposure"))
        if not exposure:
            return outcome, [], [], warnings, (
                f"exposure_results[{exposure_index}].exposure is required"
            )
        exposure_key = exposure.casefold()
        if exposure_key in seen_exposures:
            return outcome, [], [], warnings, f"duplicate exposure: {exposure}"
        seen_exposures.add(exposure_key)
        exposures.append(exposure)
        raw_paths = raw_exposure.get("result_paths")
        if not isinstance(raw_paths, list) or not raw_paths:
            return outcome, [], [], warnings, f"{exposure} requires result_paths"
        row_start = len(rows)
        for raw_path in raw_paths:
            path_text = _text(raw_path)
            if not path_text:
                return outcome, [], [], warnings, (
                    f"{exposure} contains an empty result path"
                )
            if path_text in seen_paths:
                return outcome, [], [], warnings, (
                    f"result record is assigned more than once: {path_text}"
                )
            seen_paths.add(path_text)
            record, error = _load_record(path_text)
            if error:
                return outcome, [], [], warnings, error
            assert record is not None
            endpoint = _text(record.get("method")) or Path(path_text).stem
            for method_index, raw_method in enumerate(record["methods"], start=1):
                if not isinstance(raw_method, dict):
                    continue
                method = _text(raw_method.get("method")) or (
                    f"{endpoint}_{method_index}"
                )
                beta = _float(raw_method.get("beta.hat"))
                if beta is None:
                    beta = _float(raw_method.get("beta"))
                if beta is None:
                    warnings.append(
                        f"Skipped {exposure} {method}: beta is unavailable."
                    )
                    continue
                ci = _ci(raw_method.get("ci"))
                if not ci["ranges"]:
                    return outcome, [], [], warnings, (
                        f"{exposure} {method} has no finite ci.ranges"
                    )
                pvalue = _float(raw_method.get("pval"))
                if pvalue is not None and not 0 <= pvalue <= 1:
                    warnings.append(
                        f"Ignored invalid p-value for {exposure} {method}."
                    )
                    pvalue = None
                rows.append(
                    {
                        "exposure": exposure,
                        "outcome": outcome,
                        "method": method,
                        "endpoint": endpoint,
                        "source_result_path": path_text,
                        "input_scale": record.get("input_scale") or "unknown",
                        "Threshold": _float(raw_method.get("Threshold")),
                        "nsnp": _int(raw_method.get("nsnp")),
                        "beta.hat": beta,
                        "se": _float(raw_method.get("se")),
                        "pval": pvalue,
                        "ci": ci,
                    }
                )
        if len(rows) == row_start:
            return outcome, [], [], warnings, (
                f"{exposure} has no finite method estimates"
            )

    duplicate_labels = Counter(
        (row["exposure"].casefold(), row["method"].casefold()) for row in rows
    )
    for row in rows:
        key = (row["exposure"].casefold(), row["method"].casefold())
        row["method_key"] = (
            f"{row['method']} [{row['endpoint']}]"
            if duplicate_labels[key] > 1
            else row["method"]
        )
    duplicate_keys = Counter(
        (row["exposure"].casefold(), row["method_key"].casefold()) for row in rows
    )
    duplicated = next((key for key, count in duplicate_keys.items() if count > 1), None)
    if duplicated:
        return outcome, [], [], warnings, (
            "duplicate method endpoint for exposure: " + " / ".join(duplicated)
        )
    return outcome, exposures, rows, warnings, None


def _add_bh_qvalues(rows: list[dict[str, Any]]) -> None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("pval") is not None:
            groups[row["method_key"].casefold()].append(row)
        row["qval"] = None
    for group in groups.values():
        ordered = sorted(group, key=lambda row: float(row["pval"]))
        count = len(ordered)
        adjusted = [min(1.0, float(row["pval"]) * count / rank) for rank, row in enumerate(ordered, 1)]
        for index in range(count - 2, -1, -1):
            adjusted[index] = min(adjusted[index], adjusted[index + 1])
        for row, qvalue in zip(ordered, adjusted):
            row["qval"] = qvalue


def _direction(beta: float) -> str:
    if beta > 0:
        return "positive"
    if beta < 0:
        return "negative"
    return "null"


def _method_order(rows: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for row in rows:
        key = row["method_key"]
        if key.casefold() not in seen:
            seen.add(key.casefold())
            result.append(key)
    return result


def _matches_primary(row: dict[str, Any], primary_method: str) -> bool:
    target = _method_token(primary_method)
    return bool(target) and target in {
        _method_token(row["method"]),
        _method_token(row["method_key"]),
        _method_token(row["endpoint"]),
    }


def _rank_exposures(
    exposures: list[str],
    rows: list[dict[str, Any]],
    primary_method: str,
) -> tuple[list[str], str | None]:
    if not primary_method:
        return list(exposures), None
    matched = [row for row in rows if _matches_primary(row, primary_method)]
    if not matched:
        return [], f"primary_method was not found: {primary_method}"
    original = {exposure.casefold(): index for index, exposure in enumerate(exposures)}
    scores: dict[str, tuple[float, float, int]] = {}
    for exposure in exposures:
        candidates = [
            row for row in matched if row["exposure"].casefold() == exposure.casefold()
        ]
        score = min(
            (
                float(row["qval"]) if row.get("qval") is not None else math.inf,
                float(row["pval"]) if row.get("pval") is not None else math.inf,
                original[exposure.casefold()],
            )
            for row in candidates
        ) if candidates else (math.inf, math.inf, original[exposure.casefold()])
        scores[exposure.casefold()] = score
    return sorted(exposures, key=lambda exposure: scores[exposure.casefold()]), None


def _finalize_rows(
    rows: list[dict[str, Any]], exposures: list[str], methods: list[str]
) -> list[dict[str, Any]]:
    exposure_rank = {value.casefold(): index + 1 for index, value in enumerate(exposures)}
    method_rank = {value.casefold(): index for index, value in enumerate(methods)}
    for row in rows:
        row["direction"] = _direction(row["beta.hat"])
        row["ci_excludes_zero"] = all(
            interval["upper"] < 0 or interval["lower"] > 0
            for interval in row["ci"]["ranges"]
        )
        row["priority_rank"] = exposure_rank[row["exposure"].casefold()]
    return sorted(
        rows,
        key=lambda row: (
            exposure_rank[row["exposure"].casefold()],
            method_rank[row["method_key"].casefold()],
        ),
    )


def _ci_text(ci: dict[str, Any]) -> str:
    return " | ".join(
        f"[{interval['lower']:.4g}, {interval['upper']:.4g}]"
        for interval in ci["ranges"]
    )


def _pvalue_text(pvalue: float | None) -> str:
    return "NA" if pvalue is None else f"{pvalue:.3g}"


def _write_table(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "priority_rank",
        "exposure",
        "outcome",
        "method",
        "method_key",
        "endpoint",
        "input_scale", "beta.hat",
        "se",
        "CILevel",
        "CIIntervals",
        "pval",
        "qval",
        "direction",
        "ci_excludes_zero",
        "nsnp",
        "Threshold",
        "source_result_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for row in rows:
            output = {field: row.get(field) for field in fields}
            output["CILevel"] = row["ci"].get("level")
            output["CIIntervals"] = _ci_text(row["ci"])
            writer.writerow(output)


def _configure_plot_style(plt: Any) -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "Liberation Sans", "sans-serif"],
            "font.weight": "normal",
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": 12,
            "axes.titlesize": 15,
            "axes.labelsize": 13,
            "axes.labelweight": "bold",
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "legend.fontsize": 10.5,
            "legend.frameon": False,
            "axes.linewidth": 1.2,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
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
    outcome: str,
) -> None:
    from matplotlib.lines import Line2D

    height = max(6.8, 0.29 * len(rows) + 2.9)
    figure = plt.figure(figsize=(12.0, height), facecolor="white")
    grid = figure.add_gridspec(
        1,
        4,
        width_ratios=[1.8, 1.3, 4.1, 1.95],
        wspace=0.035,
    )
    exposure_axis = figure.add_subplot(grid[0, 0])
    method_axis = figure.add_subplot(grid[0, 1])
    forest_axis = figure.add_subplot(grid[0, 2])
    table_axis = figure.add_subplot(grid[0, 3])
    axes = [exposure_axis, method_axis, forest_axis, table_axis]
    y_values = list(range(len(rows)))[::-1]
    pvalue_x = 0.12
    ivs_x = 0.88

    groups: list[tuple[str, int, int]] = []
    start = 0
    while start < len(rows):
        exposure = rows[start]["exposure"]
        end = start
        while end + 1 < len(rows) and rows[end + 1]["exposure"] == exposure:
            end += 1
        groups.append((exposure, start, end))
        start = end + 1

    for group_index, (exposure, start, end) in enumerate(groups):
        group_y = y_values[start : end + 1]
        lower, upper = min(group_y) - 0.5, max(group_y) + 0.5
        if group_index % 2:
            for axis in axes:
                axis.axhspan(lower, upper, color="#F3F5F7", zorder=0)
        exposure_axis.text(
            0.98,
            (min(group_y) + max(group_y)) / 2,
            exposure,
            ha="right",
            va="center",
            fontsize=10.6,
            fontweight="bold",
            color="#272727",
        )

    for y_value, row in zip(y_values, rows):
        color = (
            POSITIVE
            if row["beta.hat"] > 0
            else NEGATIVE
            if row["beta.hat"] < 0
            else NEUTRAL
        )
        for interval in row["ci"]["ranges"]:
            forest_axis.plot(
                [interval["lower"], interval["upper"]],
                [y_value, y_value],
                color=color,
                linewidth=2.4,
                solid_capstyle="round",
                zorder=3,
            )
        corrected = row.get("qval") is not None and row["qval"] < 0.05
        forest_axis.scatter(
            row["beta.hat"],
            y_value,
            s=82,
            facecolor=color if corrected else "white",
            edgecolor=color,
            linewidth=2.0,
            zorder=4,
        )
        method_axis.text(
            0.5,
            y_value,
            row["method_key"],
            ha="center",
            va="center",
            fontsize=9.8,
            color="#272727",
        )
        table_axis.text(
            pvalue_x,
            y_value,
            _pvalue_text(row.get("pval")),
            ha="left",
            va="center",
            fontsize=9.8,
            fontweight="semibold",
            color="#272727",
        )
        table_axis.text(
            ivs_x,
            y_value,
            "NA" if row.get("nsnp") is None else str(row["nsnp"]),
            ha="right",
            va="center",
            fontsize=9.8,
            fontweight="semibold",
            color="#272727",
        )

    for y_value in y_values:
        for axis in (method_axis, forest_axis, table_axis):
            axis.axhline(y_value - 0.5, color="#E4E8EC", linewidth=0.55, zorder=1)

    forest_axis.axvline(0, color="#272727", linestyle="--", linewidth=1.25, zorder=2)
    forest_axis.margins(x=0.06)
    forest_axis.grid(axis="x", color="#D8DDE3", linewidth=0.75, zorder=1)
    forest_axis.set_xlabel(
        f"Reported causal-effect estimate (β)\nOutcome: {outcome}",
        labelpad=8,
    )

    exposure_axis.set_title("Exposure", loc="right", fontsize=11, fontweight="bold", pad=11)
    method_axis.set_title("MR method", loc="center", fontsize=11, fontweight="bold", pad=11)
    table_axis.text(
        pvalue_x,
        1.015,
        "P value",
        transform=table_axis.transAxes,
        ha="left",
        va="bottom",
        fontsize=11,
        fontweight="bold",
    )
    table_axis.text(
        ivs_x,
        1.015,
        "IVs",
        transform=table_axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=11,
        fontweight="bold",
    )
    for axis in axes:
        axis.set_ylim(-0.5, len(rows) - 0.5)
        axis.set_yticks([])
        axis.tick_params(axis="y", left=False, labelleft=False)
    for axis in (exposure_axis, method_axis, table_axis):
        axis.set_xlim(0, 1)
        axis.set_xticks([])
        axis.tick_params(axis="x", bottom=False, labelbottom=False)
        for spine in axis.spines.values():
            spine.set_visible(False)

    legend_handles = [
        Line2D([0], [0], marker="o", linestyle="", markerfacecolor=POSITIVE, markeredgecolor=POSITIVE, markersize=7.5, label="Positive β"),
        Line2D([0], [0], marker="o", linestyle="", markerfacecolor=NEGATIVE, markeredgecolor=NEGATIVE, markersize=7.5, label="Negative β"),
        Line2D([0], [0], marker="o", linestyle="", markerfacecolor="#555555", markeredgecolor="#555555", markersize=7.5, label="Filled: within-method BH q < 0.05"),
        Line2D([0], [0], marker="o", linestyle="", markerfacecolor="white", markeredgecolor="#555555", markeredgewidth=1.8, markersize=7.5, label="Open: BH q ≥ 0.05 or unavailable"),
    ]
    figure.suptitle(title, fontsize=16, fontweight="bold", y=0.985)
    figure.legend(
        handles=legend_handles,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.075),
        ncol=4,
        fontsize=7.6,
        handletextpad=0.45,
        columnspacing=0.9,
        labelspacing=0.5,
    )
    figure.subplots_adjust(left=0.025, right=0.99, top=0.94, bottom=0.18)
    _save_publication_figure(figure, plt, path)


def _matrix_plot(
    plt: Any,
    rows: list[dict[str, Any]],
    exposures: list[str],
    methods: list[str],
    path: Path,
    *,
    title: str,
) -> None:
    from matplotlib.lines import Line2D

    figure, axis = plt.subplots(
        figsize=(max(9.0, 1.75 * len(methods) + 3.5), max(4.8, 0.85 * len(exposures) + 2.8))
    )
    lookup = {
        (row["exposure"].casefold(), row["method_key"].casefold()): row
        for row in rows
    }
    for y_value, exposure in enumerate(exposures):
        for x_value, method in enumerate(methods):
            row = lookup.get((exposure.casefold(), method.casefold()))
            if row is None:
                axis.scatter(x_value, y_value, marker="x", s=58, color="#C7C7C7", linewidth=1.4)
                continue
            beta = row["beta.hat"]
            color = POSITIVE if beta > 0 else NEGATIVE if beta < 0 else NEUTRAL
            marker = "^" if beta > 0 else "v" if beta < 0 else "o"
            pvalue = row.get("pval")
            strength = 0.0 if pvalue is None else min(16.0, -math.log10(max(float(pvalue), 1e-300)))
            corrected = row.get("qval") is not None and row["qval"] < 0.05
            axis.scatter(
                x_value,
                y_value,
                marker=marker,
                s=90 + 22 * strength,
                facecolor=color,
                edgecolor="#111111" if corrected else color,
                linewidth=2.0 if corrected else 0.8,
                alpha=0.9,
                zorder=3,
            )
            axis.text(
                x_value,
                y_value + 0.31,
                f"{beta:.3g}",
                ha="center",
                va="center",
                fontsize=9.3,
                fontweight="normal",
                color="#7B848E",
                alpha=0.9,
                zorder=4,
            )
    axis.set_xticks(range(len(methods)))
    axis.set_xticklabels(
        methods,
        rotation=35,
        ha="right",
        rotation_mode="anchor",
        fontsize=11,
        fontweight="bold",
    )
    axis.set_yticks(range(len(exposures)))
    axis.set_yticklabels(exposures, fontsize=11.5, fontweight="bold")
    axis.set_xlim(-0.6, len(methods) - 0.4)
    axis.set_ylim(len(exposures) - 0.45, -0.82)
    axis.set_title(title, fontsize=17, fontweight="bold", pad=22)
    axis.set_xlabel("MR method")
    axis.set_ylabel("Candidate exposure")
    axis.set_xticks([index - 0.5 for index in range(len(methods) + 1)], minor=True)
    axis.set_yticks([index - 0.5 for index in range(len(exposures) + 1)], minor=True)
    axis.grid(which="minor", color="#E8E8E8", linewidth=0.8)
    axis.grid(False, which="major")
    legend = [
        Line2D([0], [0], marker="^", linestyle="", markerfacecolor=POSITIVE, markeredgecolor=POSITIVE, markersize=9, label="Positive beta"),
        Line2D([0], [0], marker="v", linestyle="", markerfacecolor=NEGATIVE, markeredgecolor=NEGATIVE, markersize=9, label="Negative beta"),
        Line2D([0], [0], marker="o", linestyle="", markerfacecolor="white", markeredgecolor="#111111", markeredgewidth=2, markersize=9, label="BH q < 0.05 outline"),
        Line2D([0], [0], marker="x", linestyle="", color="#C7C7C7", markersize=8, label="No completed result"),
    ]
    axis.legend(handles=legend, loc="upper center", bbox_to_anchor=(0.5, -0.25), ncol=4, frameon=False, fontsize=10.5)
    axis.text(
        0.99,
        0.975,
        "Triangle size encodes P value (larger triangle = smaller P)",
        transform=axis.transAxes,
        ha="right",
        va="top",
        fontsize=9.5,
        fontweight="normal",
        color="#555555",
    )
    _save_publication_figure(figure, plt, path)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    outcome, exposures, rows, warnings, error = _normalize(dict(payload or {}))
    if error:
        return _blocked(
            f"analysis-risk-factor-prioritization blocked: {error}.",
            "invalid_exposure_results",
        )
    scale_issue = input_scale_issue(rows)
    if scale_issue:
        return _blocked(scale_issue, "incompatible_input_scale")
    if rows and rows[0].get("input_scale") == "unknown":
        warnings.append("Legacy results lack input_scale; effect-unit comparability is unverified.")

    _add_bh_qvalues(rows)
    primary_method = _text(payload.get("primary_method"))
    ranked_exposures, rank_error = _rank_exposures(exposures, rows, primary_method)
    if rank_error:
        return _blocked(
            f"analysis-risk-factor-prioritization blocked: {rank_error}.",
            "primary_method_not_found",
        )
    methods = _method_order(rows)
    rows = _finalize_rows(rows, ranked_exposures, methods)

    coverage = {
        exposure: [
            method
            for method in methods
            if any(
                row["exposure"].casefold() == exposure.casefold()
                and row["method_key"].casefold() == method.casefold()
                for row in rows
            )
        ]
        for exposure in ranked_exposures
    }
    missing_cells = sum(len(methods) - len(coverage[exposure]) for exposure in ranked_exposures)
    if missing_cells:
        warnings.append(
            f"{missing_cells} exposure-method cell(s) have no completed result and are shown as missing."
        )

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
            "analysis-risk-factor-prioritization blocked: matplotlib is unavailable: "
            + _text(exc),
            "plot_dependency_unavailable",
        )
    _configure_plot_style(plt)

    table_path = reports_dir / "risk_factor_prioritization.tsv"
    forest_path = plots_dir / "risk_factor_forest.png"
    matrix_path = plots_dir / "risk_factor_method_matrix.png"
    record_path = reports_dir / "risk_factor_prioritization_result.json"
    _write_table(rows, table_path)
    title = _text(payload.get("title")) or f"MR risk factors for {outcome}"
    _forest_plot(plt, rows, forest_path, title=title, outcome=outcome)
    _matrix_plot(
        plt,
        rows,
        ranked_exposures,
        methods,
        matrix_path,
        title=f"Cross-method evidence matrix for {outcome}",
    )

    explanation_dir = Path(__file__).resolve().parents[1] / "plot_explanations"
    plot_records = [
        {
            "plot_id": "risk_factor_forest",
            "path": str(forest_path),
            "title": title,
            "source": "mr_risk_factor_prioritization_result",
            "explanation_path": str(explanation_dir / "risk_factor_forest.md"),
        },
        {
            "plot_id": "risk_factor_method_matrix",
            "path": str(matrix_path),
            "title": f"Cross-method evidence matrix for {outcome}",
            "source": "mr_risk_factor_prioritization_result",
            "explanation_path": str(explanation_dir / "risk_factor_method_matrix.md"),
        },
    ]
    significant = sum(
        row.get("qval") is not None and row["qval"] < 0.05 for row in rows
    )
    summary = (
        f"Prioritized {len(ranked_exposures)} exposure(s) for {outcome} from "
        f"{len(rows)} completed estimate(s) across {len(methods)} method label(s); "
        f"{significant} estimate(s) had within-method BH q<0.05."
    )
    result = {
        "input_scale": rows[0].get("input_scale", "unknown"),
        "method": "mr_risk_factor_prioritization",
        "design": "multi_exposure_single_outcome",
        "outcome": outcome,
        "primary_method": primary_method or None,
        "exposures": ranked_exposures,
        "priority_order": ranked_exposures,
        "methods": methods,
        "estimates": rows,
        "summary_table_path": str(table_path),
        "forest_plot_path": str(forest_path),
        "method_matrix_path": str(matrix_path),
        "diagnostics": {
            "exposure_count": len(ranked_exposures),
            "method_count": len(methods),
            "result_record_count": len(
                {row["source_result_path"] for row in rows}
            ),
            "estimate_count": len(rows),
            "within_method_bh_q_lt_0_05_count": significant,
            "missing_exposure_method_cells": missing_cells,
            "method_coverage": coverage,
            "warnings": warnings,
        },
        "interpretation": {
            "summary": summary,
            "recommendations": [
                "Use method agreement and corrected evidence as descriptive prioritization evidence; verify scale comparability and method-specific assumptions before causal interpretation."
            ],
        },
        "plot_manifest": {"plots": plot_records},
        "result_record_path": str(record_path),
    }
    record_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "summary": summary,
        "outputs": {
            "status": "ok",
            "mr_risk_factor_prioritization_result": result,
        },
        "details": {"result_status": "ok", "failure_class": None},
        "artifacts": [
            {"path": str(table_path), "kind": "tsv", "summary": "Risk-factor MR estimates with BH q-values"},
            {"path": str(forest_path), "kind": "png", "summary": title},
            {"path": str(matrix_path), "kind": "png", "summary": f"Cross-method evidence matrix for {outcome}"},
            {"path": str(record_path), "kind": "json", "summary": "Risk-factor prioritization result record"},
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prioritize risk factors from completed MR result records"
    )
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
