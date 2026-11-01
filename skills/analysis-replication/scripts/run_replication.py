from __future__ import annotations

from mrcat.tool.mr.input_scale import input_scale_issue

import argparse
import csv
import json
import math
import os
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Any


AGGREGATE_METHODS = {
    "method_comparison",
    "mr_bidirectional",
    "mr_mediation",
    "mr_replication",
    "mr_result_synthesis",
    "mr_risk_factor_prioritization",
}
POSITIVE = "#B64342"
NEGATIVE = "#0F4D92"
MISSING = "#A8A8A8"
METHOD_PRIORITY = {
    "ivw": 0,
    "mr-apss": 1,
    "bwmr": 2,
    "mr-egger": 3,
    "weighted median": 4,
    "weighted mode": 5,
}


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
        or Path.cwd() / "tmp_analysis_replication"
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
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": 12,
            "axes.titlesize": 15,
            "axes.labelsize": 12,
            "axes.labelweight": "bold",
            "axes.titleweight": "bold",
            "xtick.labelsize": 10.5,
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


def _study(raw: Any, *, field: str) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict):
        return None, f"{field} must be a selected study object"
    source = _text(raw.get("source"))
    study_id = _text(raw.get("study_id") or raw.get("id"))
    if not source or not study_id:
        return None, f"{field} requires source and study_id"
    metadata = raw.get("study_metadata") if isinstance(raw.get("study_metadata"), dict) else {}
    return {
        "source": source,
        "study_id": study_id,
        "trait": _text(raw.get("trait")),
        "sample_size": _integer(raw.get("sample_size")),
        "ncase": _integer(raw.get("ncase")),
        "ncontrol": _integer(raw.get("ncontrol")),
        "ancestry": _text(raw.get("ancestry") or raw.get("ancestry_raw")),
        "study_metadata": dict(metadata),
    }, None


def _normalize(payload: dict[str, Any]) -> tuple[
    str, str, list[dict[str, Any]], list[dict[str, Any]], list[str], str | None
]:
    exposure = _text(payload.get("exposure"))
    outcome = _text(payload.get("outcome"))
    if not exposure or not outcome or exposure.casefold() == outcome.casefold():
        return "", "", [], [], [], "exposure and outcome must be distinct non-empty labels"
    raw_analyses = payload.get("analyses")
    if not isinstance(raw_analyses, list) or len(raw_analyses) < 2:
        return exposure, outcome, [], [], [], "analyses must contain at least two completed study combinations"
    analyses: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_names: set[str] = set()
    seen_pairs: set[tuple[str, str, str, str]] = set()
    seen_paths: set[str] = set()
    for analysis_index, raw_analysis in enumerate(raw_analyses, start=1):
        if not isinstance(raw_analysis, dict):
            return exposure, outcome, [], [], warnings, f"analyses[{analysis_index}] must be an object"
        name = _text(raw_analysis.get("name"))
        if not name:
            return exposure, outcome, [], [], warnings, f"analyses[{analysis_index}].name is required"
        name_key = name.casefold()
        if name_key in seen_names:
            return exposure, outcome, [], [], warnings, f"duplicate analysis name: {name}"
        seen_names.add(name_key)
        exposure_study, error = _study(raw_analysis.get("exposure_study"), field=f"analyses[{analysis_index}].exposure_study")
        if error:
            return exposure, outcome, [], [], warnings, error
        outcome_study, error = _study(raw_analysis.get("outcome_study"), field=f"analyses[{analysis_index}].outcome_study")
        if error:
            return exposure, outcome, [], [], warnings, error
        assert exposure_study is not None and outcome_study is not None
        study_pair = (
            exposure_study["source"].casefold(),
            exposure_study["study_id"].casefold(),
            outcome_study["source"].casefold(),
            outcome_study["study_id"].casefold(),
        )
        if study_pair in seen_pairs:
            return exposure, outcome, [], [], warnings, f"duplicate selected study combination: {name}"
        seen_pairs.add(study_pair)
        raw_paths = raw_analysis.get("result_paths")
        if not isinstance(raw_paths, list) or not raw_paths:
            return exposure, outcome, [], [], warnings, f"analyses[{analysis_index}].result_paths is required"
        analysis_paths: list[str] = []
        seen_methods: set[str] = set()
        analysis_row_start = len(rows)
        for raw_path in raw_paths:
            path_text = _text(raw_path)
            if not path_text:
                return exposure, outcome, [], [], warnings, f"analyses[{analysis_index}] contains an empty result path"
            if path_text in seen_paths:
                return exposure, outcome, [], [], warnings, f"result record is assigned more than once: {path_text}"
            seen_paths.add(path_text)
            record, error = _load_record(path_text)
            if error:
                return exposure, outcome, [], [], warnings, error
            assert record is not None
            analysis_paths.append(path_text)
            source_method = _text(record.get("method")) or Path(path_text).stem
            for method_index, raw_method in enumerate(record["methods"], start=1):
                if not isinstance(raw_method, dict):
                    continue
                method = _text(raw_method.get("method")) or f"{source_method}_{method_index}"
                method_key = method.casefold()
                if method_key in seen_methods:
                    return exposure, outcome, [], [], warnings, f"{name} has duplicate method: {method}"
                beta = _float(raw_method.get("beta.hat"))
                if beta is None:
                    beta = _float(raw_method.get("beta"))
                if beta is None:
                    warnings.append(f"Skipped {name} {method}: beta is unavailable.")
                    continue
                interval = _ci(raw_method.get("ci"))
                if not interval["ranges"]:
                    return exposure, outcome, [], [], warnings, f"{name} {method} has no finite ci.ranges"
                seen_methods.add(method_key)
                rows.append(
                    {
                        "analysis_index": analysis_index,
                        "analysis_name": name,
                        "exposure": exposure,
                        "outcome": outcome,
                        "exposure_study": exposure_study,
                        "outcome_study": outcome_study,
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
        if len(rows) == analysis_row_start:
            return exposure, outcome, [], [], warnings, f"{name} has no usable estimates"
        analyses.append(
            {
                "analysis_index": analysis_index,
                "name": name,
                "exposure_study": exposure_study,
                "outcome_study": outcome_study,
                "result_paths": analysis_paths,
            }
        )
    return exposure, outcome, analyses, rows, warnings, None


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
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["pval"] is not None:
            grouped[row["method_key"]].append(row)
    for method_rows in grouped.values():
        values = [float(row["pval"]) for row in method_rows]
        adjusted = _bh(values) if method == "bh" else values
        for row, qvalue in zip(method_rows, adjusted):
            row["qval"] = qvalue
    for row in rows:
        row.setdefault("qval", None)


def _sample_text(study: dict[str, Any]) -> str:
    sample_size = study.get("sample_size")
    if sample_size is not None:
        return f"N={sample_size:,}"
    ncase = study.get("ncase")
    ncontrol = study.get("ncontrol")
    if ncase is not None or ncontrol is not None:
        return f"cases={ncase or 'NA'} · controls={ncontrol or 'NA'}"
    metadata = study.get("study_metadata") if isinstance(study.get("study_metadata"), dict) else {}
    fallback = _text(metadata.get("initialSampleSize"))
    return f"N={fallback}" if fallback else "N=NA"


def _source_label(value: Any) -> str:
    source = _text(value)
    labels = {
        "opengwas": "OpenGWAS",
        "gwas catalog": "GWAS Catalog",
        "pan-ukb": "Pan-UKB",
        "panukb": "Pan-UKB",
        "finngen": "FinnGen",
    }
    return labels.get(source.casefold(), source or "Source unavailable")


def _ancestry_text(study: dict[str, Any]) -> str:
    ancestry = _text(study.get("ancestry"))
    if not ancestry:
        return "Ancestry unavailable"
    if ancestry.casefold() in {"unknown", "na", "n/a"}:
        return "Ancestry unknown"
    if "ancestry" in ancestry.casefold():
        return ancestry
    return f"{ancestry[0].upper() + ancestry[1:]} ancestry"


def _study_title(study: dict[str, Any], role: str) -> str:
    trait = _text(study.get("trait")) or role
    return f"{role}: {trait} ({study['study_id']})"


def _wrapped_study_title(study: dict[str, Any], role: str) -> str:
    return textwrap.fill(
        _study_title(study, role),
        width=34,
        break_long_words=False,
        break_on_hyphens=False,
    )


def _study_metadata_line(study: dict[str, Any]) -> str:
    return f"{_source_label(study.get('source'))} · {_sample_text(study)} · {_ancestry_text(study)}"


def _study_fingerprint(study: dict[str, Any]) -> tuple[str, str]:
    return (
        _text(study.get("source")).casefold(),
        _text(study.get("study_id")).casefold(),
    )


def _shared_study_sides(analyses: list[dict[str, Any]]) -> tuple[bool, bool]:
    exposure_keys = {_study_fingerprint(item["exposure_study"]) for item in analyses}
    outcome_keys = {_study_fingerprint(item["outcome_study"]) for item in analyses}
    return len(exposure_keys) == 1, len(outcome_keys) == 1


def _analysis_display_name(analysis: dict[str, Any]) -> str:
    name = _text(analysis.get("name"))
    if len(name) <= 32:
        return name
    return f"Analysis {analysis['analysis_index']}"


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


def _forest_matrix(
    plt: Any,
    analyses: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    path: Path,
) -> None:
    from matplotlib.gridspec import GridSpec
    from matplotlib.ticker import MaxNLocator

    labels = {
        key: next(row["method"] for row in rows if row["method_key"] == key)
        for key in {row["method_key"] for row in rows}
    }
    methods = sorted(
        labels,
        key=lambda key: (
            METHOD_PRIORITY.get(labels[key].casefold(), len(METHOD_PRIORITY)),
            labels[key].casefold(),
        ),
    )
    lookup = {(row["analysis_index"], row["method_key"]): row for row in rows}
    shared_exposure, shared_outcome = _shared_study_sides(analyses)
    common_side = "exposure" if shared_exposure else "outcome" if shared_outcome else None
    height = max(6.2, 0.64 * len(methods) + (2.2 if common_side else 3.8))
    width = max(10.5, 2.9 * len(analyses) + 2.0)
    figure = plt.figure(figsize=(width, height), facecolor="white")
    header_ratio = 1.25 if common_side else 2.1
    grid = GridSpec(
        2,
        len(analyses) + 1,
        left=0.035,
        right=0.985,
        bottom=0.13,
        top=0.96,
        width_ratios=[1.25] + [3.0] * len(analyses),
        height_ratios=[header_ratio, max(3.6, 0.7 * len(methods))],
        wspace=0.12,
        hspace=0.02,
        figure=figure,
    )

    method_header_axis = figure.add_subplot(grid[0, 0])
    method_header_axis.axis("off")
    method_header_axis.text(
        0.0, 0.02, "METHOD", fontsize=11, fontweight="bold", color="#111111",
        ha="left", va="bottom",
    )

    y_values = list(range(len(methods)))[::-1]
    method_axis = figure.add_subplot(grid[1, 0])
    method_axis.set_xlim(0, 1)
    method_axis.set_ylim(-0.5, len(methods) - 0.5)
    method_axis.axis("off")
    for row_index, (method_key, y_value) in enumerate(zip(methods, y_values)):
        if row_index % 2 == 0:
            method_axis.axhspan(y_value - 0.48, y_value + 0.48, color="#F2F6F8", zorder=0)
        method_axis.text(
            0.0, y_value, labels[method_key], fontsize=10.5, fontweight="bold",
            color="#111111", ha="left", va="center",
        )

    study_axes: list[Any] = []
    for analysis in analyses:
        column = int(analysis["analysis_index"])
        header_axis = figure.add_subplot(grid[0, column])
        header_axis.axis("off")
        header_axis.text(
            0.5, 0.92, _analysis_display_name(analysis), fontsize=12, fontweight="bold",
            color="#111111", ha="center", va="top",
        )
        if common_side == "exposure":
            study = analysis["outcome_study"]
            header_axis.text(
                0.5, 0.55, _wrapped_study_title(study, "Outcome"), fontsize=9.2,
                fontweight="bold", color="#111111", ha="center", va="center",
            )
            header_axis.text(
                0.5, 0.16, _study_metadata_line(study), fontsize=7.2,
                fontweight="normal", color="#111111", ha="center", va="center",
            )
        elif common_side == "outcome":
            study = analysis["exposure_study"]
            header_axis.text(
                0.5, 0.55, _wrapped_study_title(study, "Exposure"), fontsize=9.2,
                fontweight="bold", color="#111111", ha="center", va="center",
            )
            header_axis.text(
                0.5, 0.16, _study_metadata_line(study), fontsize=7.2,
                fontweight="normal", color="#111111", ha="center", va="center",
            )
        else:
            exposure_study = analysis["exposure_study"]
            outcome_study = analysis["outcome_study"]
            header_axis.text(
                0.5, 0.69, _wrapped_study_title(exposure_study, "Exposure"), fontsize=8.8,
                fontweight="bold", color="#111111", ha="center", va="center",
            )
            header_axis.text(
                0.5, 0.49, _study_metadata_line(exposure_study), fontsize=6.8,
                fontweight="normal", color="#111111", ha="center", va="center",
            )
            header_axis.text(
                0.5, 0.27, _wrapped_study_title(outcome_study, "Outcome"), fontsize=8.8,
                fontweight="bold", color="#111111", ha="center", va="center",
            )
            header_axis.text(
                0.5, 0.07, _study_metadata_line(outcome_study), fontsize=6.8,
                fontweight="normal", color="#111111", ha="center", va="center",
            )

        axis = figure.add_subplot(
            grid[1, column],
            sharey=study_axes[0] if study_axes else method_axis,
        )
        study_axes.append(axis)
        analysis_rows = [
            row for row in rows if row["analysis_index"] == analysis["analysis_index"]
        ]
        low, high = _axis_limits(analysis_rows)
        for row_index, (method_key, y_value) in enumerate(zip(methods, y_values)):
            if row_index % 2 == 0:
                axis.axhspan(y_value - 0.48, y_value + 0.48, color="#F2F6F8", zorder=0)
            row = lookup.get((analysis["analysis_index"], method_key))
            if row is None:
                axis.scatter(
                    (low + high) / 2, y_value, marker="x", s=48,
                    color=MISSING, linewidth=1.6, zorder=3,
                )
                continue
            color = POSITIVE if row["beta.hat"] >= 0 else NEGATIVE
            for interval in row["ci"]["ranges"]:
                axis.plot(
                    [interval["lower"], interval["upper"]], [y_value, y_value],
                    color=color, linewidth=2.4, solid_capstyle="round", zorder=2,
                )
                axis.vlines(
                    [interval["lower"], interval["upper"]],
                    y_value - 0.08, y_value + 0.08,
                    color=color, linewidth=1.3, zorder=2,
                )
            axis.scatter(
                row["beta.hat"], y_value, s=72,
                facecolor=color, edgecolor=color,
                linewidth=1.9, zorder=3,
            )
        axis.axvline(0, color="#111111", linewidth=1.25, linestyle="--")
        axis.set_xlim(low, high)
        axis.xaxis.set_major_locator(MaxNLocator(nbins=5))
        axis.set_ylim(-0.5, len(methods) - 0.5)
        axis.set_yticks([])
        axis.grid(axis="x", color="#DCE2E9", linewidth=0.65)
        for spine in ("top", "right", "left"):
            axis.spines[spine].set_visible(False)
        axis.tick_params(axis="x", labelsize=9.0, width=1.0, length=4, colors="#111111")
        for tick_label in axis.get_xticklabels():
            tick_label.set_fontweight("bold")
            tick_label.set_color("#111111")

    figure.text(
        0.59, 0.055,
        "MR estimate (β)",
        fontsize=10.5, fontweight="bold", color="#111111", ha="center", va="bottom",
    )
    _save_publication_figure(figure, plt, path)


def _write_table(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "analysis_name", "exposure", "outcome", "exposure_source", "exposure_study_id",
        "exposure_sample_size", "exposure_ncase", "exposure_ncontrol", "exposure_ancestry",
        "outcome_source", "outcome_study_id", "outcome_sample_size", "outcome_ncase",
        "outcome_ncontrol", "outcome_ancestry", "method", "source_method",
        "input_scale", "beta.hat", "se", "pval", "qval", "nsnp", "CILevel", "CIIntervals",
        "source_result_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for row in rows:
            exp = row["exposure_study"]
            out = row["outcome_study"]
            rendered = {field: row.get(field) for field in fields}
            for prefix, study in (("exposure", exp), ("outcome", out)):
                rendered[f"{prefix}_source"] = study.get("source")
                rendered[f"{prefix}_study_id"] = study.get("study_id")
                rendered[f"{prefix}_sample_size"] = study.get("sample_size")
                rendered[f"{prefix}_ncase"] = study.get("ncase")
                rendered[f"{prefix}_ncontrol"] = study.get("ncontrol")
                rendered[f"{prefix}_ancestry"] = study.get("ancestry")
            rendered["CILevel"] = row["ci"].get("level")
            rendered["CIIntervals"] = " | ".join(
                f"[{item['lower']:.8g}, {item['upper']:.8g}]" for item in row["ci"]["ranges"]
            )
            writer.writerow(rendered)


def _method_diagnostics(analyses: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    for method_key in sorted({row["method_key"] for row in rows}):
        method_rows = [row for row in rows if row["method_key"] == method_key]
        label = method_rows[0]["method"]
        positive = sum(row["beta.hat"] > 0 for row in method_rows)
        negative = sum(row["beta.hat"] < 0 for row in method_rows)
        majority = max(positive, negative)
        diagnostics[label] = {
            "coverage": len(method_rows),
            "analysis_count": len(analyses),
            "directional_concordance": majority / len(method_rows),
            "positive_count": positive,
            "negative_count": negative,
        }
    return diagnostics


def run(payload: dict[str, Any]) -> dict[str, Any]:
    alpha = _float(payload.get("alpha"))
    alpha = 0.05 if alpha is None else alpha
    if not 0 < alpha < 1:
        return _blocked("analysis-replication blocked: alpha must be between 0 and 1.", "invalid_parameters")
    adjust_method = _text(payload.get("p_adjust_method") or "bh").casefold()
    if adjust_method not in {"bh", "none"}:
        return _blocked("analysis-replication blocked: p_adjust_method must be bh or none.", "invalid_parameters")
    exposure, outcome, analyses, rows, warnings, error = _normalize(dict(payload or {}))
    if error:
        return _blocked(f"analysis-replication blocked: {error}.", "invalid_analyses")
    scale_issue = input_scale_issue(rows)
    if scale_issue:
        return _blocked(scale_issue, "incompatible_input_scale")
    if rows and rows[0].get("input_scale") == "unknown":
        warnings.append("Legacy results lack input_scale; effect-unit comparability is unverified.")

    _adjust(rows, adjust_method)
    method_diagnostics = _method_diagnostics(analyses, rows)
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
            f"analysis-replication blocked: matplotlib is unavailable: {_text(exc)}.",
            "plot_dependency_unavailable",
        )
    _configure_plot_style(plt)

    table_path = reports_dir / "replication_estimates.tsv"
    plot_path = plots_dir / "replication_forest_matrix.png"
    record_path = reports_dir / "replication_result_record.json"
    _write_table(rows, table_path)
    title = _text(payload.get("title")) or f"Replication landscape · {exposure} → {outcome}"
    _forest_matrix(plt, analyses, rows, plot_path)
    explanation_path = Path(__file__).resolve().parents[1] / "plot_explanations" / "replication_forest_matrix.md"
    plot_record = {
        "plot_id": "replication_forest_matrix",
        "path": str(plot_path),
        "title": title,
        "source": "mr_replication_result",
        "explanation_path": str(explanation_path),
    }
    complete_methods = sum(values["coverage"] == len(analyses) for values in method_diagnostics.values())
    summary = (
        f"Replication analysis summarized {len(analyses)} selected study combination(s), "
        f"{len(rows)} method estimate(s), and {len(method_diagnostics)} method(s) for "
        f"{exposure} to {outcome}; {complete_methods} method(s) covered every analysis."
    )
    result = {
        "input_scale": rows[0].get("input_scale", "unknown"),
        "method": "mr_replication",
        "exposure": exposure,
        "outcome": outcome,
        "analyses": analyses,
        "estimates": rows,
        "summary_table_path": str(table_path),
        "forest_matrix_path": str(plot_path),
        "diagnostics": {
            "analysis_count": len(analyses),
            "estimate_count": len(rows),
            "method_count": len(method_diagnostics),
            "alpha": alpha,
            "p_adjust_method": adjust_method,
            "method_coverage": method_diagnostics,
            "warnings": warnings,
        },
        "interpretation": {
            "summary": summary,
            "recommendations": [
                "Interpret agreement across selected study combinations using direction, uncertainty, effect-scale compatibility, and method coverage together.",
                "Different study IDs do not by themselves establish non-overlapping samples or independent replication.",
            ],
        },
        "plot_manifest": {"plots": [plot_record]},
        "result_record_path": str(record_path),
    }
    record_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "summary": summary,
        "outputs": {"status": "ok", "mr_replication_result": result},
        "details": {"result_status": "ok", "failure_class": None},
        "artifacts": [
            {"path": str(table_path), "kind": "tsv", "summary": "Replication MR estimates and study provenance"},
            {"path": str(plot_path), "kind": "png", "summary": title},
            {"path": str(record_path), "kind": "json", "summary": "Replication MR result record"},
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate repeated MR analyses across selected studies")
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
