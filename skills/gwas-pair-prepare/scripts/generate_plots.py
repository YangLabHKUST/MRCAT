from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


MAX_BACKGROUND_POINTS = 200000
MAX_INSTRUMENT_POINTS = 50000
SAMPLE_MOD = 6
GENOME_WIDE_NEGLOG = -math.log10(5e-8)
RETIRE_PLOT_IDS = [
    "gwas_pair_retention_bar",
    "gwas_pair_instrument_pvalue_histogram",
    "gwas_pair_beta_scatter",
]


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("expected args: input_json output_json")
    request = _read_json(Path(sys.argv[1]))
    output_path = Path(sys.argv[2])
    result = generate(request)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def generate(request: dict[str, Any]) -> dict[str, Any]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
    except Exception as exc:
        return {
            "status": "ok",
            "plots": [],
            "retired_plot_ids": RETIRE_PLOT_IDS,
            "diagnostics": {"warnings": [f"matplotlib unavailable: {exc}"]},
        }

    configure_plot_style(plt)
    payload = request.get("milestone_payload") if isinstance(request.get("milestone_payload"), dict) else {}
    execution_dir = Path(str(request.get("execution_dir") or "")).resolve()
    plots_dir = execution_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    explanation_dir = Path(__file__).resolve().parents[1] / "plot_explanations"
    diagnostics: dict[str, Any] = {"warnings": [], "counts": {}}
    plots: list[dict[str, Any]] = []

    mdat_path = payload_path(payload.get("mdat_path"))
    mrdat_path = payload_path(payload.get("mrdat_path"))
    c_path = payload_path(payload.get("c_path"))
    omega_path = payload_path(payload.get("omega_path"))
    ldsc_report = safe_json(payload_path(payload.get("ldsc_result_path")))

    background_points = collect_effect_points(mdat_path, limit=MAX_BACKGROUND_POINTS, stable=True)
    instrument_points = collect_effect_points(mrdat_path, limit=MAX_INSTRUMENT_POINTS, stable=False)
    if background_points or instrument_points:
        landscape_path = plots_dir / "gwas_pair_effect_landscape.png"
        save_effect_landscape(plt, background_points, instrument_points, landscape_path)
        plots.append(plot_record("gwas_pair_effect_landscape", landscape_path, "Harmonized effect landscape", explanation_dir))
    else:
        diagnostics["warnings"].append("skipped effect landscape: no finite b.exp/b.out values")

    strength_points = collect_strength_points(mrdat_path)
    if strength_points:
        strength_path = plots_dir / "gwas_pair_strength_outcome_plot.png"
        save_strength_outcome_plot(plt, strength_points, strength_path)
        plots.append(
            plot_record(
                "gwas_pair_strength_outcome_plot",
                strength_path,
                "Instrument strength vs outcome association",
                explanation_dir,
            )
        )
    else:
        diagnostics["warnings"].append("skipped strength/outcome plot: no finite MRdat p-values")

    c_matrix = read_vector_matrix(c_path)
    omega_matrix = read_vector_matrix(omega_path)
    if c_matrix or omega_matrix or ldsc_report:
        heatmap_path = plots_dir / "gwas_pair_ldsc_heatmap.png"
        save_ldsc_heatmap(plt, c_matrix, omega_matrix, ldsc_report, heatmap_path)
        plots.append(plot_record("gwas_pair_ldsc_heatmap", heatmap_path, "LDSC background parameter heatmap", explanation_dir))
    else:
        diagnostics["warnings"].append("skipped LDSC heatmap: no C/Omega/LDSC report values")

    diagnostics["counts"] = {
        "background_effect_points": len(background_points),
        "instrument_effect_points": len(instrument_points),
        "strength_points": len(strength_points),
        "has_c_matrix": bool(c_matrix),
        "has_omega_matrix": bool(omega_matrix),
        "ldsc_rg": ldsc_report.get("rg") if isinstance(ldsc_report, dict) else None,
    }
    return {
        "status": "ok",
        "plots": plots,
        "retired_plot_ids": RETIRE_PLOT_IDS,
        "diagnostics": diagnostics,
    }


def configure_plot_style(plt: Any) -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#222222",
            "axes.labelcolor": "#222222",
            "axes.titleweight": "bold",
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.labelsize": 11,
            "xtick.color": "#4b5563",
            "ytick.color": "#4b5563",
            "savefig.facecolor": "white",
            "savefig.bbox": "tight",
        }
    )


def save_effect_landscape(plt: Any, background: list[dict[str, Any]], instruments: list[dict[str, Any]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.6, 6.4))
    if background:
        xs = [item["b_exp"] for item in background]
        ys = [item["b_out"] for item in background]
        extent = effect_extent(background, instruments)
        hb = ax.hexbin(
            xs,
            ys,
            gridsize=64,
            bins="log",
            mincnt=1,
            cmap="magma",
            linewidths=0,
            extent=extent,
        )
        cbar = fig.colorbar(hb, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label("Harmonized SNP density")
        ax.set_xlim(extent[0], extent[1])
        ax.set_ylim(extent[2], extent[3])
    if instruments:
        same = [item for item in instruments if direction(item) == "same"]
        opposite = [item for item in instruments if direction(item) == "opposite"]
        neutral = [item for item in instruments if direction(item) == "near_zero"]
        scatter_group(ax, same, "#2A9D8F", "Clumped instruments: same direction")
        scatter_group(ax, opposite, "#D1495B", "Clumped instruments: opposite direction")
        scatter_group(ax, neutral, "#6B7280", "Clumped instruments: near zero")
    ax.axhline(0, color="#111827", linewidth=0.8)
    ax.axvline(0, color="#111827", linewidth=0.8)
    ax.set_xlabel("Exposure effect, b.exp")
    ax.set_ylabel("Outcome effect, b.out")
    ax.set_title("Harmonized genetic-effect landscape")
    if instruments:
        ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.13), fontsize=9)
    style_axis(ax)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    save_figure(fig, plt, path)


def save_strength_outcome_plot(plt: Any, points: list[dict[str, Any]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.0, 6.0))
    groups = {
        "same direction": ("#2A9D8F", [item for item in points if direction(item) == "same"]),
        "opposite direction": ("#D1495B", [item for item in points if direction(item) == "opposite"]),
        "near zero": ("#6B7280", [item for item in points if direction(item) == "near_zero"]),
    }
    for label, (color, rows) in groups.items():
        if not rows:
            continue
        sizes = [point_size(item) for item in rows]
        ax.scatter(
            [item["neglogp_exp"] for item in rows],
            [item["neglogp_out"] for item in rows],
            s=sizes,
            alpha=0.78,
            color=color,
            edgecolors="white",
            linewidths=0.35,
            label=label,
        )
    thresholds = sorted({item["threshold"] for item in points if item.get("threshold") is not None})
    iv_threshold = thresholds[0] if thresholds else 5e-5
    if iv_threshold > 0:
        ax.axvline(-math.log10(iv_threshold), color="#111827", linewidth=0.9, linestyle="--", label=f"IV threshold ({iv_threshold:g})")
    ax.axhline(GENOME_WIDE_NEGLOG, color="#E31A1C", linewidth=0.9, linestyle=":", label="Outcome p = 5e-8")
    for index, item in enumerate(sorted(points, key=lambda row: (-row["neglogp_exp"], -row["neglogp_out"]))[:10]):
        ax.annotate(
            item["snp"],
            xy=(item["neglogp_exp"], item["neglogp_out"]),
            xytext=(5, 4 + (index % 4) * 3),
            textcoords="offset points",
            fontsize=7.5,
            color="#111827",
            arrowprops={"arrowstyle": "-", "linewidth": 0.35, "color": "#374151"},
        )
    ax.set_xlabel("Instrument strength: -log10(pval.exp)")
    ax.set_ylabel("Outcome association: -log10(pval.out)")
    ax.set_title("Instrument strength vs outcome association")
    ax.legend(frameon=False, loc="upper right", fontsize=9)
    style_axis(ax)
    fig.tight_layout()
    save_figure(fig, plt, path)


def save_ldsc_heatmap(plt: Any, c_matrix: list[list[float]] | None, omega_matrix: list[list[float]] | None, report: dict[str, Any], path: Path) -> None:
    matrices = [("C", c_matrix), ("Omega", omega_matrix)]
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 4.2), gridspec_kw={"width_ratios": [1, 1, 0.85]})
    for ax, (title, matrix) in zip(axes[:2], matrices):
        if not matrix:
            ax.text(0.5, 0.5, f"{title} unavailable", ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            continue
        finite_values = [abs(value) for row in matrix for value in row if math.isfinite(value)]
        vmax = max(finite_values) if finite_values else 1.0
        vmax = vmax if vmax > 0 else 1.0
        image = ax.imshow(matrix, cmap="RdBu_r", vmin=-vmax, vmax=vmax)
        ax.set_xticks([0, 1])
        ax.set_yticks([0, 1])
        ax.set_xticklabels(["exposure", "outcome"], rotation=25, ha="right")
        ax.set_yticklabels(["exposure", "outcome"])
        ax.set_title(title)
        for y, row in enumerate(matrix):
            for x, value in enumerate(row):
                ax.text(x, y, format_cell(value), ha="center", va="center", color="#111827", fontsize=8.5)
        for spine in ax.spines.values():
            spine.set_visible(False)
        fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    info_ax = axes[2]
    info_ax.set_axis_off()
    rg = to_float(report.get("rg")) if isinstance(report, dict) else None
    n_mdat = report.get("n_mdat") if isinstance(report, dict) else None
    info_lines = [
        "LDSC summary",
        "",
        f"rg: {rg:.4g}" if rg is not None else "rg: unavailable",
        f"harmonized SNPs: {n_mdat}" if n_mdat is not None else "harmonized SNPs: unavailable",
        f"C matrix: {'available' if c_matrix else 'missing'}",
        f"Omega matrix: {'available' if omega_matrix else 'missing'}",
    ]
    info_ax.text(0, 0.92, "\n".join(info_lines), va="top", ha="left", fontsize=11, color="#111827")
    fig.suptitle("Pair-level LDSC/background parameter structure", x=0.02, ha="left", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    save_figure(fig, plt, path)


def collect_effect_points(path: Path | None, *, limit: int, stable: bool) -> list[dict[str, Any]]:
    if not valid_file(path):
        return []
    points: list[dict[str, Any]] = []
    with open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = set(reader.fieldnames or [])
        if not {"b.exp", "b.out"}.issubset(fields):
            return []
        for row in reader:
            if len(points) >= limit:
                break
            snp = clean_text(row.get("SNP"))
            if stable and not stable_sample(snp or len(points)):
                continue
            b_exp = to_float(row.get("b.exp"))
            b_out = to_float(row.get("b.out"))
            if b_exp is None or b_out is None:
                continue
            points.append(
                {
                    "snp": snp,
                    "b_exp": b_exp,
                    "b_out": b_out,
                    "se_exp": to_float(row.get("se.exp")),
                    "se_out": to_float(row.get("se.out")),
                    "pval_exp": to_float(row.get("pval.exp")),
                    "pval_out": to_float(row.get("pval.out")),
                }
            )
    return points


def collect_strength_points(path: Path | None) -> list[dict[str, Any]]:
    if not valid_file(path):
        return []
    points: list[dict[str, Any]] = []
    with open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = set(reader.fieldnames or [])
        required = {"SNP", "b.exp", "b.out", "pval.exp", "pval.out"}
        if not required.issubset(fields):
            return []
        for row in reader:
            if len(points) >= MAX_INSTRUMENT_POINTS:
                break
            p_exp = to_float(row.get("pval.exp"))
            p_out = to_float(row.get("pval.out"))
            b_exp = to_float(row.get("b.exp"))
            b_out = to_float(row.get("b.out"))
            if p_exp is None or p_out is None or b_exp is None or b_out is None:
                continue
            neg_exp = neglog10(p_exp)
            neg_out = neglog10(p_out)
            if neg_exp is None or neg_out is None:
                continue
            points.append(
                {
                    "snp": clean_text(row.get("SNP")),
                    "b_exp": b_exp,
                    "b_out": b_out,
                    "se_exp": to_float(row.get("se.exp")),
                    "se_out": to_float(row.get("se.out")),
                    "pval_exp": p_exp,
                    "pval_out": p_out,
                    "neglogp_exp": neg_exp,
                    "neglogp_out": neg_out,
                    "threshold": to_float(row.get("Threshold")),
                }
            )
    return points


def scatter_group(ax: Any, rows: list[dict[str, Any]], color: str, label: str) -> None:
    if not rows:
        return
    ax.scatter(
        [item["b_exp"] for item in rows],
        [item["b_out"] for item in rows],
        s=28,
        alpha=0.88,
        color=color,
        edgecolors="white",
        linewidths=0.45,
        label=label,
        zorder=4,
    )


def effect_extent(background: list[dict[str, Any]], instruments: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    xs = [item["b_exp"] for item in background]
    ys = [item["b_out"] for item in background]
    x_low, x_high = percentile(xs, 1), percentile(xs, 99)
    y_low, y_high = percentile(ys, 1), percentile(ys, 99)
    if instruments:
        x_low = min(x_low, min(item["b_exp"] for item in instruments))
        x_high = max(x_high, max(item["b_exp"] for item in instruments))
        y_low = min(y_low, min(item["b_out"] for item in instruments))
        y_high = max(y_high, max(item["b_out"] for item in instruments))
    x_pad = max((x_high - x_low) * 0.15, 1e-6)
    y_pad = max((y_high - y_low) * 0.15, 1e-6)
    return (x_low - x_pad, x_high + x_pad, y_low - y_pad, y_high + y_pad)


def format_cell(value: float) -> str:
    if abs(value) < 0.001 and value != 0:
        return f"{value:.2e}"
    return f"{value:.3g}"


def direction(item: dict[str, Any]) -> str:
    product = float(item.get("b_exp") or 0.0) * float(item.get("b_out") or 0.0)
    if abs(product) < 1e-18:
        return "near_zero"
    return "same" if product > 0 else "opposite"


def point_size(item: dict[str, Any]) -> float:
    se_out = item.get("se_out")
    z_out = abs(float(item.get("b_out") or 0.0) / se_out) if isinstance(se_out, float) and se_out > 0 else item.get("neglogp_out", 1.0)
    return max(20.0, min(120.0, 18.0 + float(z_out) * 8.0))


def read_vector_matrix(path: Path | None) -> list[list[float]] | None:
    if not valid_file(path):
        return None
    rows: list[list[float]] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for row in reader:
            values = [to_float(item) for item in row]
            values = [item for item in values if item is not None]
            if values:
                rows.append(values)
    flat = [value for row in rows for value in row]
    if len(flat) >= 4:
        return [[flat[0], flat[2]], [flat[1], flat[3]]]
    if len(rows) >= 2 and all(len(row) >= 2 for row in rows[:2]):
        return [[rows[0][0], rows[0][1]], [rows[1][0], rows[1][1]]]
    return None


def style_axis(ax: Any) -> None:
    ax.grid(color="#e5e7eb", linewidth=0.6, alpha=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#222222")
    ax.spines["bottom"].set_color("#222222")


def save_figure(fig: Any, plt: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=220)
    plt.close(fig)


def plot_record(plot_id: str, path: Path, title: str, explanation_dir: Path) -> dict[str, Any]:
    return {
        "plot_id": plot_id,
        "path": str(path),
        "title": title,
        "source": "gwas-pair-prepare qc",
        "explanation_path": str(explanation_dir / f"{plot_id}.md"),
    }


def payload_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    return Path(text).expanduser().resolve() if text else None


def valid_file(path: Path | None) -> bool:
    return path is not None and path.exists() and path.is_file()


def safe_json(path: Path | None) -> dict[str, Any]:
    if not valid_file(path):
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def stable_sample(value: Any) -> bool:
    digest = hashlib.md5(str(value).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % SAMPLE_MOD == 0


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * pct / 100))
    return ordered[max(0, min(index, len(ordered) - 1))]


def neglog10(value: float | None) -> float | None:
    if value is None or value < 0:
        return None
    if value == 0:
        return 300.0
    return min(-math.log10(value), 300.0)


def clean_text(value: Any) -> str:
    return str(value or "").strip().replace("\r", " ").replace("\n", " ").replace("\t", " ")


def to_float(value: Any) -> float | None:
    try:
        parsed = float(str(value or "").strip())
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def open_text(path: Path):
    with path.open("rb") as handle:
        magic = handle.read(2)
    if magic == b"\x1f\x8b":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="")
    return path.open("r", encoding="utf-8", errors="replace", newline="")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload must be an object: {path}")
    return payload


if __name__ == "__main__":
    main()
