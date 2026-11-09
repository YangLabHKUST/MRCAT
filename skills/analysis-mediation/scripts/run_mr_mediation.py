from __future__ import annotations

from mrcat.tool.MRTool.input_scale import input_scale_issue

import argparse
import csv
import json
import math
import os
import re
from pathlib import Path
from typing import Any


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _load_input(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    candidate = Path(value)
    if candidate.is_file():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(value)


def _execution_dir() -> Path:
    path = Path(
        os.getenv("MRCAT_EXECUTION_DIR")
        or Path.cwd() / "tmp_mr_mediation"
    ).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _blocked(summary: str, failure_class: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "outputs": {
            "status": "blocked",
            "failure_class": failure_class,
        },
        "details": {
            "result_status": "blocked",
            "failure_class": failure_class,
        },
    }


def _load_result_record(
    raw_path: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    path_text = _compact_text(raw_path)
    if not path_text:
        return None, "result record path is empty"
    path = Path(path_text).expanduser()
    if not path.is_file():
        return None, f"result record does not exist: {path_text}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"result record is not readable JSON: {path_text}: {exc}"
    if not isinstance(payload, dict):
        return None, f"result record must contain an object: {path_text}"
    methods = payload.get("methods")
    if not isinstance(methods, list) or not methods:
        return None, f"result record has no methods: {path_text}"
    if any(isinstance(row, dict) and _compact_text(row.get("method")).casefold() == "cause" for row in methods):
        return None, "CAUSE posterior intervals do not supply sampling SEs for delta-method mediation"
    return payload, None


def _load_result_records(
    raw_paths: Any,
    *,
    label: str,
) -> tuple[list[dict[str, Any]] | None, list[str], str | None]:
    if not isinstance(raw_paths, list) or not raw_paths:
        return None, [], f"{label} must be a non-empty list"
    records: list[dict[str, Any]] = []
    paths: list[str] = []
    seen: set[str] = set()
    for raw_path in raw_paths:
        path_text = _compact_text(raw_path)
        if not path_text:
            return None, paths, f"{label} contains an empty path"
        if path_text in seen:
            return None, paths, f"{label} repeats result record {path_text}"
        seen.add(path_text)
        record, error = _load_result_record(path_text)
        if error:
            return None, paths, error
        assert record is not None
        records.append(record)
        paths.append(path_text)
    return records, paths, None


def _method_index(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for raw_row in list(record.get("methods") or []):
        if not isinstance(raw_row, dict):
            continue
        method = _compact_text(raw_row.get("method"))
        beta = _float(raw_row.get("beta.hat"))
        if beta is None:
            beta = _float(raw_row.get("beta"))
        if not method or beta is None:
            continue
        key = method.casefold()
        if key in indexed:
            continue
        indexed[key] = {
            "method": method,
            "beta": beta,
            "input_scale": record.get("input_scale") or "unknown",
            "se": _float(raw_row.get("se")),
            "ci": raw_row.get("ci") if isinstance(raw_row.get("ci"), dict) else {"level": None, "ranges": []},
            "nsnp": raw_row.get("nsnp"),
            "source_row": dict(raw_row),
        }
    return indexed


def _combined_method_index(
    records: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], str | None]:
    combined: dict[str, dict[str, Any]] = {}
    for record in records:
        for method_key, row in _method_index(record).items():
            if method_key in combined:
                return {}, (
                    "duplicate method name across result records: "
                    f"{row['method']}"
                )
            combined[method_key] = row
    return combined, None


def _normal_pvalue(beta: float, se: float | None) -> float | None:
    if se is None or se <= 0:
        return None
    return math.erfc(abs(beta / se) / math.sqrt(2.0))


def _interval(
    estimate: float,
    se: float | None,
) -> dict[str, Any]:
    ranges: list[dict[str, float]] = []
    if se is not None and se > 0:
        margin = 1.959963984540054 * se
        ranges.append(
            {
                "lower": estimate - margin,
                "upper": estimate + margin,
            }
        )
    return {"level": 0.95, "ranges": ranges}


def _path_row(
    *,
    mediator: str,
    total: dict[str, Any],
    x_to_m: dict[str, Any],
    m_to_y: dict[str, Any],
) -> dict[str, Any]:
    beta_total = float(total["beta"])
    beta_x_to_m = float(x_to_m["beta"])
    beta_m_to_y = float(m_to_y["beta"])
    indirect = beta_x_to_m * beta_m_to_y
    se_x_to_m = x_to_m.get("se")
    se_m_to_y = m_to_y.get("se")
    indirect_se = None
    if (
        isinstance(se_x_to_m, float)
        and se_x_to_m > 0
        and isinstance(se_m_to_y, float)
        and se_m_to_y > 0
    ):
        indirect_se = math.sqrt(
            (beta_m_to_y * se_x_to_m) ** 2
            + (beta_x_to_m * se_m_to_y) ** 2
        )

    proportion = indirect / beta_total if beta_total != 0 else None
    proportion_se = None
    total_se = total.get("se")
    if (
        proportion is not None
        and indirect_se is not None
        and isinstance(total_se, float)
        and total_se > 0
    ):
        proportion_se = math.sqrt(
            (indirect_se / beta_total) ** 2
            + ((indirect * total_se) / (beta_total**2)) ** 2
        )

    return {
        "mediator": mediator,
        "method": str(total["method"]),
        "input_scale": total["input_scale"],
        "beta_x_to_m": beta_x_to_m,
        "se_x_to_m": se_x_to_m,
        "x_to_m_ci": x_to_m["ci"],
        "beta_m_to_y": beta_m_to_y,
        "se_m_to_y": se_m_to_y,
        "m_to_y_ci": m_to_y["ci"],
        "total_effect": beta_total,
        "total_effect_se": total_se,
        "total_effect_ci": total["ci"],
        "indirect_effect": indirect,
        "indirect_se": indirect_se,
        "indirect_pval": _normal_pvalue(indirect, indirect_se),
        "indirect_ci": _interval(indirect, indirect_se),
        "mediation_proportion": proportion,
        "proportion_se": proportion_se,
        "proportion_ci": (
            _interval(proportion, proportion_se)
            if proportion is not None
            else {"level": 0.95, "ranges": []}
        ),
        "nsnp_x_to_m": x_to_m.get("nsnp"),
        "nsnp_m_to_y": m_to_y.get("nsnp"),
        "nsnp_total": total.get("nsnp"),
    }


def _write_table(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "mediator",
        "method",
        "input_scale",
        "beta_x_to_m",
        "se_x_to_m",
        "x_to_m_ci",
        "beta_m_to_y",
        "se_m_to_y",
        "m_to_y_ci",
        "total_effect",
        "total_effect_se",
        "total_effect_ci",
        "indirect_effect",
        "indirect_se",
        "indirect_pval",
        "indirect_ci",
        "mediation_proportion",
        "proportion_se",
        "proportion_ci",
        "nsnp_x_to_m",
        "nsnp_m_to_y",
        "nsnp_total",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(
            {key: json.dumps(value) if isinstance(value, dict) else value for key, value in row.items()}
            for row in rows
        )


def _plot_interval(
    axis: Any,
    *,
    estimate: float | None,
    interval: dict[str, Any],
    y_value: float,
    color: str,
    marker: str,
) -> None:
    if estimate is None:
        return
    for raw_range in list(interval.get("ranges") or []):
        if not isinstance(raw_range, dict):
            continue
        lower = _float(raw_range.get("lower"))
        upper = _float(raw_range.get("upper"))
        if lower is None or upper is None:
            continue
        axis.plot(
            [min(lower, upper), max(lower, upper)],
            [y_value, y_value],
            color=color,
            linewidth=2.6,
            solid_capstyle="round",
            zorder=2,
        )
    axis.scatter(
        estimate,
        y_value,
        s=72,
        marker=marker,
        color=color,
        edgecolor="white",
        linewidth=1.2,
        zorder=3,
    )


def _interval_bounds(
    interval: dict[str, Any],
) -> tuple[float, float] | None:
    for raw_range in list(interval.get("ranges") or []):
        if not isinstance(raw_range, dict):
            continue
        lower = _float(raw_range.get("lower"))
        upper = _float(raw_range.get("upper"))
        if lower is not None and upper is not None:
            return min(lower, upper), max(lower, upper)
    return None


def _format_number(value: float | None) -> str:
    if value is None:
        return "NA"
    absolute = abs(value)
    if absolute != 0 and (absolute < 0.01 or absolute >= 100):
        return f"{value:.2g}"
    return f"{value:.2f}"


def _format_estimate(
    estimate: float | None,
    interval: dict[str, Any],
    *,
    percent: bool = False,
) -> str:
    if estimate is None:
        return "NA"
    scale = 100.0 if percent else 1.0
    estimate_text = _format_number(estimate * scale)
    suffix = "%" if percent else ""
    ranges = [
        (_float(item.get("lower")), _float(item.get("upper")))
        for item in interval.get("ranges", [])
    ]
    ranges = [(lower, upper) for lower, upper in ranges if lower is not None and upper is not None]
    if not ranges:
        return f"{estimate_text}{suffix}"
    intervals = " ∪ ".join(
        f"({_format_number(lower * scale)}, {_format_number(upper * scale)})"
        for lower, upper in ranges
    )
    return f"{estimate_text}{suffix} {intervals}"


def _filename_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")
    return (slug or "mediator")[:80]


def _configure_plot_style(plt: Any) -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "Liberation Sans", "sans-serif"],
            "font.weight": "bold",
            "font.size": 12,
            "axes.titlesize": 14,
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
    figure.savefig(path, dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _generate_forest_plot(
    rows: list[dict[str, Any]],
    path: Path,
) -> str | None:
    matplotlib_config_dir = path.parent.parent / ".matplotlib"
    cache_dir = path.parent.parent / ".cache"
    matplotlib_config_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_config_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
        from matplotlib.ticker import PercentFormatter  # type: ignore
    except Exception as exc:
        return f"matplotlib is unavailable: {_compact_text(exc)}"

    _configure_plot_style(plt)

    palette = [
        "#0F4D92",
        "#42949E",
        "#7C6CCF",
        "#D9544D",
        "#5B7FCA",
        "#B89BD9",
        "#767676",
        "#272727",
    ]
    if not rows:
        return "no mediation estimates are available for plotting"
    mediator = str(rows[0]["mediator"])
    if any(str(row["mediator"]) != mediator for row in rows):
        return "each mediation plot must contain exactly one mediator"
    method_colors = {
        str(row["method"]): palette[index % len(palette)]
        for index, row in enumerate(rows)
    }
    y_values = list(range(len(rows)))[::-1]

    height = max(4.6, min(12.0, 0.72 * len(rows) + 3.1))
    figure = plt.figure(figsize=(17.0, height), facecolor="white")
    grid = figure.add_gridspec(
        nrows=1,
        ncols=7,
        width_ratios=[1.9, 1.4, 1.3, 1.9, 1.4, 1.65, 1.55],
        wspace=0.12,
    )
    axes = [figure.add_subplot(grid[0, index]) for index in range(7)]
    (
        x_to_m_text_axis,
        x_to_m_axis,
        method_axis,
        m_to_y_text_axis,
        m_to_y_axis,
        proportion_text_axis,
        proportion_axis,
    ) = axes

    for index, (y_value, row) in enumerate(zip(y_values, rows)):
        if index % 2:
            for axis in axes:
                axis.axhspan(
                    y_value - 0.48,
                    y_value + 0.48,
                    color="#F5F7F8",
                    zorder=0,
                )
        method_axis.text(
            0.5,
            y_value,
            str(row["method"]),
            ha="center",
            va="center",
            fontsize=12,
            fontweight="bold",
            color="#252A2E",
        )

    for y_value, row in zip(y_values, rows):
        method = str(row["method"])
        color = method_colors[method]
        _plot_interval(
            x_to_m_axis,
            estimate=_float(row.get("beta_x_to_m")),
            interval=row["x_to_m_ci"],
            y_value=y_value,
            color=color,
            marker="o",
        )
        _plot_interval(
            m_to_y_axis,
            estimate=_float(row.get("beta_m_to_y")),
            interval=row["m_to_y_ci"],
            y_value=y_value,
            color=color,
            marker="o",
        )
        x_to_m_text_axis.text(
            0.02,
            y_value,
            _format_estimate(
                _float(row.get("beta_x_to_m")),
                row["x_to_m_ci"],
            ),
            transform=x_to_m_text_axis.get_yaxis_transform(),
            ha="left",
            va="center",
            fontsize=10.5,
            fontweight="bold",
            color="#30353A",
        )
        m_to_y_text_axis.text(
            0.02,
            y_value,
            _format_estimate(
                _float(row.get("beta_m_to_y")),
                row["m_to_y_ci"],
            ),
            transform=m_to_y_text_axis.get_yaxis_transform(),
            ha="left",
            va="center",
            fontsize=10.5,
            fontweight="bold",
            color="#30353A",
        )
        proportion = _float(row.get("mediation_proportion"))
        proportion_interval = dict(row.get("proportion_ci") or {})
        proportion_text_axis.text(
            0.02,
            y_value,
            _format_estimate(
                proportion,
                proportion_interval,
                percent=True,
            ),
            transform=proportion_text_axis.get_yaxis_transform(),
            ha="left",
            va="center",
            fontsize=10.5,
            fontweight="bold",
            color="#30353A",
        )
        if proportion is not None:
            proportion_axis.barh(
                y_value,
                proportion,
                height=0.40,
                color=color,
                alpha=0.9,
                zorder=2,
            )
            bounds = _interval_bounds(proportion_interval)
            if bounds is not None:
                lower, upper = bounds
                proportion_axis.errorbar(
                    proportion,
                    y_value,
                    xerr=[
                        [max(0.0, proportion - lower)],
                        [max(0.0, upper - proportion)],
                    ],
                    fmt="none",
                    ecolor="#7A7F83",
                    elinewidth=1.4,
                    capsize=3.5,
                    zorder=3,
                )

    for axis in (x_to_m_axis, m_to_y_axis, proportion_axis):
        axis.axvline(0.0, color="#444444", linewidth=1.4, linestyle="--")
        axis.grid(axis="x", color="#D8DDE3", linewidth=0.75)
        axis.set_axisbelow(True)
        axis.set_yticks([])
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_visible(False)
        axis.spines["bottom"].set_color("#90969A")
        axis.tick_params(axis="x", labelsize=10.5, colors="#4F5559", width=1.1, length=5)

    for axis in (
        x_to_m_text_axis,
        method_axis,
        m_to_y_text_axis,
        proportion_text_axis,
    ):
        axis.set_xlim(0.0, 1.0)
        axis.set_xticks([])
        axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_visible(False)

    y_min = -0.58
    y_max = max(0.58, float(len(rows) - 1) + 0.58)
    for axis in axes:
        axis.set_ylim(y_min, y_max)

    x_to_m_text_axis.set_title(
        f"Exposure →\n{mediator}\n$\\hat{{\\beta}}$ (reported CI)",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=13,
    )
    method_axis.set_title(
        "Method",
        fontsize=13,
        fontweight="bold",
        pad=27,
    )
    m_to_y_text_axis.set_title(
        f"{mediator}\n→ outcome\n$\\hat{{\\beta}}$ (reported CI)",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=13,
    )
    proportion_text_axis.set_title(
        "Mediation proportion\nEstimate (95% CI)",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=13,
    )
    x_to_m_axis.set_xlabel("Effect estimate", fontsize=11.5, fontweight="bold")
    m_to_y_axis.set_xlabel("Effect estimate", fontsize=11.5, fontweight="bold")
    proportion_axis.set_xlabel("Mediated", fontsize=11.5, fontweight="bold")
    proportion_axis.xaxis.set_major_formatter(PercentFormatter(xmax=1.0))

    figure.suptitle(
        f"Two-step MR mediation via {mediator}",
        fontsize=18,
        fontweight="bold",
        y=0.985,
    )
    figure.text(
        0.5,
        0.012,
        "Mediation-proportion confidence intervals use the delta method; component covariances are assumed zero.",
        ha="center",
        fontsize=10.5,
        fontweight="bold",
        color="#5B6165",
    )
    figure.subplots_adjust(left=0.035, right=0.985, top=0.76, bottom=0.13)
    _save_publication_figure(figure, plt, path)
    return None


def run(payload: dict[str, Any]) -> dict[str, Any]:
    raw = dict(payload or {})
    total_records, total_paths, error = _load_result_records(
        raw.get("total_effect_results"),
        label="total_effect_results",
    )
    if error:
        return _blocked(
            f"analysis-mediation blocked: {error}.",
            "invalid_total_effect_result",
        )
    assert total_records is not None
    total_methods, method_error = _combined_method_index(total_records)
    if method_error:
        return _blocked(
            f"analysis-mediation blocked: {method_error}.",
            "duplicate_method",
        )
    if not total_methods:
        return _blocked(
            "analysis-mediation blocked: total-effect result has no finite method estimates.",
            "missing_total_effect_estimate",
        )

    raw_paths = raw.get("indirect_paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        return _blocked(
            "analysis-mediation blocked: indirect_paths is required.",
            "missing_indirect_paths",
        )

    rows: list[dict[str, Any]] = []
    source_paths: list[dict[str, str]] = []
    seen_mediators: set[str] = set()
    for index, raw_path in enumerate(raw_paths):
        if not isinstance(raw_path, dict):
            return _blocked(
                "analysis-mediation blocked: every indirect_paths item must be an object.",
                "invalid_indirect_path",
            )
        if set(raw_path) != {
            "name",
            "x_to_m_results",
            "m_to_y_results",
        }:
            return _blocked(
                "analysis-mediation blocked: every indirect path must contain exactly "
                "name, x_to_m_results, and m_to_y_results.",
                "invalid_indirect_path",
            )
        mediator = _compact_text(raw_path.get("name"))
        if not mediator:
            return _blocked(
                f"analysis-mediation blocked: indirect_paths[{index}].name is required.",
                "invalid_indirect_path",
            )
        mediator_key = mediator.casefold()
        if mediator_key in seen_mediators:
            return _blocked(
                f"analysis-mediation blocked: duplicate mediator {mediator}.",
                "duplicate_mediator",
            )
        seen_mediators.add(mediator_key)

        x_to_m_records, x_paths, x_error = _load_result_records(
            raw_path.get("x_to_m_results"),
            label=f"{mediator}.x_to_m_results",
        )
        m_to_y_records, y_paths, y_error = _load_result_records(
            raw_path.get("m_to_y_results"),
            label=f"{mediator}.m_to_y_results",
        )
        if x_error or y_error:
            return _blocked(
                "analysis-mediation blocked: "
                + "; ".join(
                    value
                    for value in (x_error, y_error)
                    if value
                )
                + ".",
                "invalid_indirect_result",
            )
        assert x_to_m_records is not None
        assert m_to_y_records is not None
        x_to_m_methods, x_method_error = _combined_method_index(
            x_to_m_records
        )
        m_to_y_methods, y_method_error = _combined_method_index(
            m_to_y_records
        )
        if x_method_error or y_method_error:
            return _blocked(
                "analysis-mediation blocked: "
                + "; ".join(
                    value
                    for value in (x_method_error, y_method_error)
                    if value
                )
                + ".",
                "duplicate_method",
            )
        common = (
            set(total_methods)
            .intersection(x_to_m_methods)
            .intersection(m_to_y_methods)
        )
        if not common:
            return _blocked(
                "analysis-mediation blocked: no common method is available across "
                f"the total, X -> {mediator}, and {mediator} -> Y results.",
                "no_common_method",
            )
        for method_key in sorted(common):
            path_inputs = [total_methods[method_key], x_to_m_methods[method_key], m_to_y_methods[method_key]]
            scale_issue = input_scale_issue(path_inputs, require_known=True)
            if scale_issue:
                return _blocked(scale_issue, "incompatible_input_scale")
            if path_inputs[0]["input_scale"] == "mrmix_standardize":
                return _blocked("MRMix-specific scales require explicit trait-unit reconciliation before mediation.", "incompatible_input_scale")
            rows.append(
                _path_row(
                    mediator=mediator,
                    total=total_methods[method_key],
                    x_to_m=x_to_m_methods[method_key],
                    m_to_y=m_to_y_methods[method_key],
                )
            )
        source_paths.append(
            {
                "mediator": mediator,
                "x_to_m_results": x_paths,
                "m_to_y_results": y_paths,
            }
        )

    scale_issue = input_scale_issue(rows, require_known=True)
    if scale_issue:
        return _blocked(scale_issue, "incompatible_input_scale")
    execution_dir = _execution_dir()
    reports_dir = execution_dir / "reports"
    plots_dir = execution_dir / "plots"
    reports_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)
    table_path = reports_dir / "mr_mediation_paths.tsv"
    record_path = reports_dir / "mr_mediation_result_record.json"
    _write_table(rows, table_path)

    explanation_path = (
        Path(__file__).resolve().parents[1]
        / "plot_explanations"
        / "mr_mediation_forest.md"
    )
    rows_by_mediator: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_mediator.setdefault(str(row["mediator"]), []).append(row)
    plot_paths: list[str] = []
    plot_records: list[dict[str, Any]] = []
    for index, (mediator, mediator_rows) in enumerate(
        rows_by_mediator.items(),
        start=1,
    ):
        plot_path = plots_dir / (
            f"mr_mediation_{index:02d}_{_filename_slug(mediator)}.png"
        )
        plot_error = _generate_forest_plot(mediator_rows, plot_path)
        if plot_error:
            return _blocked(
                f"analysis-mediation blocked: {plot_error}.",
                "plot_dependency_unavailable",
            )
        plot_paths.append(str(plot_path))
        plot_records.append(
            {
                "plot_id": (
                    f"mr_mediation_{index:02d}_{_filename_slug(mediator)}"
                ),
                "path": str(plot_path),
                "title": f"Two-step MR mediation via {mediator}",
                "source": "mr_mediation_result",
                "explanation_path": str(explanation_path),
            }
        )

    method_rows = [
        {
            "method": f"{row['method']} [{row['mediator']} indirect]",
            "Threshold": None,
            "nsnp": None,
            "beta.hat": row["indirect_effect"],
            "se": row["indirect_se"],
            "pval": row["indirect_pval"],
            "ci": row["indirect_ci"],
        }
        for row in rows
    ]
    result = {
        "method": "mr_mediation",
        "input_scale": rows[0]["input_scale"],
        "methods": method_rows,
        "mediation_paths": rows,
        "mediation_table_path": str(table_path),
        "forest_plot_paths": plot_paths,
        "diagnostics": {
            "mediator_count": len(seen_mediators),
            "estimate_count": len(rows),
            "total_effect_results": total_paths,
            "indirect_result_paths": source_paths,
            "assumptions": [
                "product_of_coefficients",
                "delta_method",
                "component_estimate_covariances_assumed_zero",
            ],
        },
        "interpretation": {
            "summary": (
                "Computed separate two-step MR mediation estimates for "
                f"{len(seen_mediators)} mediator(s)."
            ),
            "recommendations": [
                (
                    "Do not sum mediator-specific indirect effects or interpret "
                    "them as jointly adjusted when mediators are correlated."
                )
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
        "summary": (
            "analysis-mediation completed: calculated "
            f"{len(rows)} mediator-method estimate(s)."
        ),
        "outputs": {
            "status": "ok",
            "mr_mediation_result": result,
        },
        "details": {
            "result_status": "ok",
            "failure_class": None,
        },
        "artifacts": [
            {
                "path": str(table_path),
                "kind": "tsv",
                "summary": "Two-step MR mediation estimates",
            },
            *[
                {
                    "path": plot_record["path"],
                    "kind": "png",
                    "summary": plot_record["title"],
                }
                for plot_record in plot_records
            ],
            {
                "path": str(record_path),
                "kind": "json",
                "summary": "MR mediation result record",
            },
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate completed pair MR results for mediation."
    )
    parser.add_argument("--input-json")
    parser.add_argument("--out")
    args = parser.parse_args()
    result = run(_load_input(args.input_json))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
