from __future__ import annotations

import csv
import gzip
import hashlib
import heapq
import json
import math
import sys
from pathlib import Path
from typing import Any

from mrcat.database import database


MAX_VALUES = 200000
MAX_SAMPLE = 120000
SAMPLE_MOD = 400
TOP_N = 5000
Y_CAP = 300.0
GENOME_WIDE_NEGLOG = -math.log10(5e-8)
RETIRE_PLOT_IDS = [
    "mrapss_format_qq_plot",
    "mrapss_format_post_format_manhattan",
    "mrapss_format_signal_retention_curve",
    "mrapss_format_retention_bar",
    "mrapss_format_pvalue_histogram",
    "mrapss_format_zscore_histogram",
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
    report_path = payload_path(payload.get("report_path"))
    report = _read_json(report_path) if valid_file(report_path) else {}
    canonical_payload = report.get("canonical") if isinstance(report.get("canonical"), dict) else {}
    repo_root = Path(str(request.get("repo_root") or Path.cwd())).resolve()
    execution_dir = Path(str(request.get("execution_dir") or "")).resolve()
    plots_dir = execution_dir / "plots"
    reports_dir = execution_dir / "reports"
    plots_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    explanation_dir = Path(__file__).resolve().parents[1] / "plot_explanations"
    diagnostics: dict[str, Any] = {"warnings": [], "counts": {}}
    plots: list[dict[str, Any]] = []

    formatted_paths = {"study": payload_path(payload.get("formatted_path"))}
    canonical_paths = {"study": payload_path(canonical_payload.get("canonical_path"))}

    qq_data = {side: collect_qq_data(path) for side, path in formatted_paths.items()}
    if any(item["p_values"] for item in qq_data.values()):
        qq_path = plots_dir / "gwas_qc_qq_plot.png"
        save_qq_plot(plt, qq_data, qq_path)
        study_qq = qq_data["study"]
        write_plot_data(qq_path, {
            "kind": "qq", "expected": study_qq["expected"], "observed": study_qq["observed"],
            "lambda_gc": study_qq["lambda_gc"],
            "note": (
                f"The same first {len(study_qq['p_values']):,} valid P values used by the saved QQ figure "
                f"(limit {MAX_VALUES:,}). Observed -log10(P) is capped at {Y_CAP:g}. "
                "Quantiles are not SNP identifiers; lambda GC describes this subset."
            ),
        })
        plots.append(plot_record("gwas_qc_qq_plot", qq_path, "GWAS QC QQ plot", explanation_dir))
    else:
        diagnostics["warnings"].append("skipped QQ plot: no finite formatted P values")

    manhattan_candidates = {side: collect_manhattan_candidates(path) for side, path in formatted_paths.items()}
    wanted_rsids = {
        str(item.get("snp") or "").strip().lower()
        for candidates in manhattan_candidates.values()
        for item in candidates
        if str(item.get("snp") or "").strip()
    }
    coords = map_rsids_to_coordinates(wanted_rsids, repo_root=repo_root)
    manhattan_points = {
        side: points_with_coordinates(candidates, coords)
        for side, candidates in manhattan_candidates.items()
    }
    if any(manhattan_points.values()):
        manhattan_path = plots_dir / "gwas_qc_post_format_manhattan.png"
        save_post_format_manhattan(plt, manhattan_points, manhattan_path)
        study_points = manhattan_points["study"]
        labels, ticks = manhattan_axis(study_points)
        write_plot_data(manhattan_path, {
            "kind": "manhattan", "points": study_points, "colors": CHR_PALETTE,
            "chromosomes": [{"label": label, "x": x} for label, x in zip(labels, ticks)],
            "highlighted": [item["snp"] for item in manhattan_highlights(study_points)],
            "significance": GENOME_WIDE_NEGLOG,
            "note": (
                f"{len(study_points):,} of {len(manhattan_candidates['study']):,} candidate SNPs mapped to "
                f"the ldsc.eur reference. Same top {TOP_N:,} plus deterministic 1/{SAMPLE_MOD} background "
                f"sample (up to {MAX_SAMPLE:,}) as the saved plot, de-duplicated by SNP. "
                "Search covers plotted SNPs only. Coordinates are reference positions. "
                f"Red line: P = 5e-8; triangles: top 30 signals. -log10(P) capped at {Y_CAP:g}; "
                "P = 0 is kept as recorded, not reconstructed."
            ),
        })
        plots.append(
            plot_record(
                "gwas_qc_post_format_manhattan",
                manhattan_path,
                "GWAS QC post-format Manhattan plot",
                explanation_dir,
            )
        )
    else:
        diagnostics["warnings"].append("skipped post-format Manhattan plot: no formatted SNPs could be mapped to coordinates")

    signal_curves = {
        side: collect_signal_curve(canonical_paths.get(side), formatted_paths.get(side))
        for side in ("study",)
    }
    if any(item.get("points") for item in signal_curves.values()):
        signal_path = plots_dir / "gwas_qc_signal_retention_curve.png"
        save_signal_curve(plt, signal_curves, signal_path)
        curve = signal_curves["study"]
        write_plot_data(signal_path, {
            "kind": "retention", **curve, "significance": GENOME_WIDE_NEGLOG,
            "note": (
                "Each cutoff shows how many canonical GWAS rows remain after formatting. "
                "Fraction = retained / raw at the same cutoff."
                if curve["mode"] == "retention_fraction" else
                "Canonical GWAS is unavailable or lacks usable fields: showing formatted SNP counts, "
                "not a retention fraction."
            ) + " Exploring the plot does not change QC thresholds or rerun analysis.",
        })
        plots.append(
            plot_record(
                "gwas_qc_signal_retention_curve",
                signal_path,
                "GWAS QC signal retention curve",
                explanation_dir,
            )
        )
    else:
        diagnostics["warnings"].append("skipped signal-retention curve: no formatted or canonical P values")

    diagnostics["counts"] = {
        "qq_p_values": {side: len(item["p_values"]) for side, item in qq_data.items()},
        "qq_lambda_gc": {side: item.get("lambda_gc") for side, item in qq_data.items()},
        "manhattan_candidates": {side: len(items) for side, items in manhattan_candidates.items()},
        "manhattan_mapped_points": {side: len(items) for side, items in manhattan_points.items()},
        "reference_requested_rsids": len(wanted_rsids),
        "reference_mapped_rsids": len(coords),
        "signal_curve_modes": {side: item.get("mode") for side, item in signal_curves.items()},
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


def save_qq_plot(plt: Any, qq_data: dict[str, dict[str, Any]], path: Path) -> None:
    sides = [side for side, item in qq_data.items() if item.get("p_values")]
    fig, axes = plt.subplots(
        1,
        len(sides),
        figsize=(6.2 * len(sides), 5.2),
        sharex=False,
        sharey=False,
        squeeze=False,
    )
    colors = ["#2F6B9A", "#C65D2E"]
    for index, (ax, side) in enumerate(zip(axes.flatten(), sides)):
        p_values = qq_data.get(side, {}).get("p_values") or []
        ordered = sorted(p for p in p_values if p >= 0)
        n = len(ordered)
        observed = [neglog10(p) or 0.0 for p in ordered]
        expected = [-math.log10((index + 0.5) / n) for index in range(n)]
        observed.reverse()
        expected.reverse()
        qq_data[side].update({"expected": expected, "observed": observed})
        x_limit = max(max(expected), 1.0) * 1.05
        y_limit = max(max(observed), x_limit, 1.0) * 1.05
        ax.scatter(expected, observed, s=5, alpha=0.45, color=colors[index % len(colors)], linewidths=0)
        ax.plot([0, x_limit], [0, x_limit], color="#111827", linewidth=1.0, linestyle="--", label="Null expectation")
        lambda_gc = qq_data.get(side, {}).get("lambda_gc")
        subtitle = "GWAS QQ"
        if isinstance(lambda_gc, float) and math.isfinite(lambda_gc):
            subtitle += f"  lambda GC={lambda_gc:.3f}"
        ax.set_title(subtitle)
        ax.set_xlabel("Expected -log10(P)")
        ax.set_ylabel("Observed -log10(P)")
        ax.set_xlim(0, x_limit)
        ax.set_ylim(0, y_limit)
        style_axis(ax)
    fig.suptitle("Formatted GWAS association calibration", x=0.02, ha="left", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    save_figure(fig, plt, path)


def save_post_format_manhattan(plt: Any, data_by_side: dict[str, list[dict[str, Any]]], path: Path) -> None:
    sides = [side for side, points in data_by_side.items() if points]
    fig, axes = plt.subplots(len(sides), 1, figsize=(13.5, 4.4 * len(sides)), squeeze=False)
    for ax, side in zip(axes.flatten(), sides):
        points = data_by_side[side]
        add_manhattan_positions(points)
        axis_labels, tick_positions = manhattan_axis(points)
        for chrom_label in axis_labels:
            chrom_points = [item for item in points if item["chr_label"] == chrom_label]
            ax.scatter(
                [item["x"] for item in chrom_points],
                [item["neglogp"] for item in chrom_points],
                s=4,
                alpha=0.72,
                color=CHR_PALETTE.get(chrom_label, "#6b7280"),
                linewidths=0,
                marker="s",
            )
        highlight = manhattan_highlights(points)
        if highlight:
            ax.scatter(
                [item["x"] for item in highlight],
                [item["neglogp"] for item in highlight],
                s=42,
                marker="^",
                color="#D82435",
                edgecolors="#111827",
                linewidths=0.35,
                label="Top significant variants",
                zorder=4,
            )
            for index, item in enumerate(select_label_points(highlight, max_labels=10, min_bp_distance=5000000)):
                ax.annotate(
                    item["snp"],
                    xy=(item["x"], item["neglogp"]),
                    xytext=(4, 5 + (index % 3) * 3),
                    textcoords="offset points",
                    fontsize=7.5,
                    color="#111827",
                    arrowprops={"arrowstyle": "-", "linewidth": 0.35, "color": "#374151"},
                    zorder=5,
                )
        ax.axhline(GENOME_WIDE_NEGLOG, color="#E31A1C", linewidth=0.9, label="p = 5e-8")
        y_max = max([item["neglogp"] for item in points] + [GENOME_WIDE_NEGLOG])
        ax.set_ylim(0, max(GENOME_WIDE_NEGLOG * 1.08, y_max * 1.12))
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(axis_labels)
        ax.set_title("Formatted GWAS SNP signal")
        ax.set_xlabel("Chromosome")
        ax.set_ylabel("-log10(P)")
        style_axis(ax)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, frameon=False, loc="upper right")
    fig.suptitle("Post-format Manhattan plot", x=0.02, ha="left", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    save_figure(fig, plt, path)


def save_signal_curve(plt: Any, curves: dict[str, dict[str, Any]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    colors = ["#2F6B9A", "#C65D2E"]
    fraction_modes = [item.get("mode") == "retention_fraction" for item in curves.values() if item.get("points")]
    use_fraction = any(fraction_modes)
    for index, (side, curve) in enumerate(curves.items()):
        points = curves.get(side, {}).get("points") or []
        if not points:
            continue
        xs = [item["threshold"] for item in points]
        ys = [item["value"] for item in points]
        label = "Retained fraction" if curve.get("mode") == "retention_fraction" else "Retained count"
        ax.plot(xs, ys, marker="o", markersize=4.5, linewidth=2.0, color=colors[index % len(colors)], label=label)
    ax.axvline(GENOME_WIDE_NEGLOG, color="#E31A1C", linewidth=0.9, linestyle="--", label="p = 5e-8")
    ax.set_xlabel("Association strength cutoff: -log10(P) >= x")
    ax.set_ylabel("Retained fraction" if use_fraction else "Formatted SNP count")
    ax.set_title("Signal retained after GWAS QC formatting")
    if use_fraction:
        max_fraction = max(
            [item["value"] for curve in curves.values() for item in (curve.get("points") or [])],
            default=1.0,
        )
        ax.set_ylim(-0.01, min(1.04, max(0.2, max_fraction * 1.25)))
    else:
        ax.set_yscale("log")
    ax.legend(frameon=False)
    style_axis(ax)
    fig.tight_layout()
    save_figure(fig, plt, path)


def collect_qq_data(path: Path | None) -> dict[str, Any]:
    p_values: list[float] = []
    chi2_values: list[float] = []
    if not valid_file(path):
        return {"p_values": p_values, "lambda_gc": None}
    with open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = set(reader.fieldnames or [])
        if "P" not in fields:
            return {"p_values": p_values, "lambda_gc": None}
        for row in reader:
            if len(p_values) >= MAX_VALUES:
                break
            pval = to_float(row.get("P"))
            if pval is None or pval < 0 or pval > 1:
                continue
            p_values.append(pval)
            chi2 = to_float(row.get("chi2"))
            if chi2 is None:
                z_value = to_float(row.get("Z"))
                chi2 = z_value * z_value if z_value is not None else None
            if chi2 is not None and chi2 >= 0:
                chi2_values.append(chi2)
    lambda_gc = None
    if chi2_values:
        lambda_gc = median(chi2_values) / 0.454936423119572
    return {"p_values": p_values, "lambda_gc": lambda_gc}


def collect_manhattan_candidates(path: Path | None) -> list[dict[str, Any]]:
    if not valid_file(path):
        return []
    top_heap: list[tuple[float, int, dict[str, Any]]] = []
    sample: list[dict[str, Any]] = []
    row_index = 0
    with open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = set(reader.fieldnames or [])
        if not {"SNP", "P"}.issubset(fields):
            return []
        for row in reader:
            row_index += 1
            snp = clean_text(row.get("SNP"))
            neglogp = neglog10(to_float(row.get("P")))
            if not snp or neglogp is None:
                continue
            record = {"snp": snp, "p": clean_text(row.get("P")), "neglogp": neglogp}
            item = (neglogp, row_index, record)
            if len(top_heap) < TOP_N:
                heapq.heappush(top_heap, item)
            elif item[0] > top_heap[0][0]:
                heapq.heapreplace(top_heap, item)
            if len(sample) < MAX_SAMPLE and stable_sample(snp):
                sample.append(record)
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for record in [item[2] for item in top_heap] + sample:
        key = str(record.get("snp") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        candidates.append(record)
    return candidates


def points_with_coordinates(candidates: list[dict[str, Any]], coords: dict[str, tuple[int, int]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for item in candidates:
        coord = coords.get(str(item.get("snp") or "").lower())
        if coord is None:
            continue
        points.append({**item, "chr": coord[0], "bp": coord[1]})
    return points


def collect_signal_curve(canonical_path: Path | None, formatted_path: Path | None) -> dict[str, Any]:
    thresholds = [0, 1, 2, 3, 4, 5, 6, GENOME_WIDE_NEGLOG, 8, 10, 12, 20, 50]
    formatted_snps = collect_snp_set(formatted_path)
    if valid_file(canonical_path) and formatted_snps:
        totals = [0 for _ in thresholds]
        retained = [0 for _ in thresholds]
        with open_text(canonical_path) as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            fields = set(reader.fieldnames or [])
            if "SNP" not in fields or not ({"pval", "neglog10_pval"} & fields):
                return formatted_signal_counts(formatted_path, thresholds)
            for row in reader:
                snp = clean_text(row.get("SNP")).lower()
                neglogp = canonical_neglog(row)
                if neglogp is None:
                    continue
                is_retained = bool(snp and snp in formatted_snps)
                for index, threshold in enumerate(thresholds):
                    if neglogp >= threshold:
                        totals[index] += 1
                        if is_retained:
                            retained[index] += 1
        points = [
            {"threshold": threshold, "value": retained[index] / totals[index], "n_raw": totals[index], "n_retained": retained[index]}
            for index, threshold in enumerate(thresholds)
            if totals[index] > 0
        ]
        return {"mode": "retention_fraction", "points": points}
    return formatted_signal_counts(formatted_path, thresholds)


def formatted_signal_counts(path: Path | None, thresholds: list[float]) -> dict[str, Any]:
    counts = [0 for _ in thresholds]
    if not valid_file(path):
        return {"mode": "formatted_count", "points": []}
    with open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if "P" not in set(reader.fieldnames or []):
            return {"mode": "formatted_count", "points": []}
        for row in reader:
            neglogp = neglog10(to_float(row.get("P")))
            if neglogp is None:
                continue
            for index, threshold in enumerate(thresholds):
                if neglogp >= threshold:
                    counts[index] += 1
    points = [
        {"threshold": threshold, "value": count, "n_retained": count}
        for threshold, count in zip(thresholds, counts)
        if count > 0
    ]
    return {"mode": "formatted_count", "points": points}


def collect_snp_set(path: Path | None) -> set[str]:
    snps: set[str] = set()
    if not valid_file(path):
        return snps
    with open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if "SNP" not in set(reader.fieldnames or []):
            return snps
        for row in reader:
            snp = clean_text(row.get("SNP")).lower()
            if snp:
                snps.add(snp)
    return snps


def map_rsids_to_coordinates(rsids: set[str], *, repo_root: Path) -> dict[str, tuple[int, int]]:
    wanted = {rsid.lower() for rsid in rsids if rsid}
    if not wanted:
        return {}
    ldscore_dir = database("ldsc.eur", workspace_dir=repo_root)
    mapped: dict[str, tuple[int, int]] = {}
    for chrom in range(1, 23):
        path = ldscore_dir / f"{chrom}.l2.ldscore.gz"
        if not path.exists():
            continue
        with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                rsid = clean_text(row.get("SNP")).lower()
                if rsid not in wanted or rsid in mapped:
                    continue
                bp = to_int(row.get("BP"))
                if bp is not None:
                    mapped[rsid] = (chrom, bp)
        if len(mapped) >= len(wanted):
            break
    return mapped


CHR_PALETTE = {
    "1": "#24476F",
    "2": "#CF1B2A",
    "3": "#FFD33F",
    "4": "#0F8B4C",
    "5": "#11A85C",
    "6": "#58C7CF",
    "7": "#8B1232",
    "8": "#5C96BD",
    "9": "#351A36",
    "10": "#9A6A2F",
    "11": "#685082",
    "12": "#DB3B7B",
    "13": "#D8D94A",
    "14": "#66505F",
    "15": "#76C568",
    "16": "#1E3B63",
    "17": "#D31823",
    "18": "#FFCF33",
    "19": "#008D61",
    "20": "#2F759A",
    "21": "#6F6F6F",
    "22": "#B58A2A",
}


def add_manhattan_positions(points: list[dict[str, Any]]) -> None:
    chroms = sorted({int(item["chr"]) for item in points})
    offsets: dict[int, int] = {}
    cursor = 0
    for chrom in chroms:
        chrom_rows = [item for item in points if int(item["chr"]) == chrom]
        max_bp = max(int(item["bp"]) for item in chrom_rows)
        offsets[chrom] = cursor
        cursor += max_bp + 5000000
    for item in points:
        chrom = int(item["chr"])
        item["x"] = offsets[chrom] + int(item["bp"])
        item["chr_label"] = str(chrom)


def manhattan_axis(points: list[dict[str, Any]]) -> tuple[list[str], list[float]]:
    labels: list[str] = []
    ticks: list[float] = []
    for chrom in sorted({int(item["chr"]) for item in points}):
        rows = [item for item in points if int(item["chr"]) == chrom]
        labels.append(str(chrom))
        ticks.append((min(item["x"] for item in rows) + max(item["x"] for item in rows)) / 2)
    return labels, ticks


def select_label_points(points: list[dict[str, Any]], *, max_labels: int, min_bp_distance: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in points:
        too_close = any(
            int(item["chr"]) == int(existing["chr"]) and abs(int(item["bp"]) - int(existing["bp"])) < min_bp_distance
            for existing in selected
        )
        if too_close:
            continue
        selected.append(item)
        if len(selected) >= max_labels:
            break
    return selected


def manhattan_highlights(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    significant = [item for item in points if item["neglogp"] >= GENOME_WIDE_NEGLOG]
    return sorted(significant, key=lambda item: (-item["neglogp"], item["chr"], item["bp"]))[:30]


def canonical_neglog(row: dict[str, Any]) -> float | None:
    direct = to_float(row.get("neglog10_pval"))
    if direct is not None and direct > 0:
        return min(direct, Y_CAP)
    return neglog10(to_float(row.get("pval")))


def neglog10(value: float | None) -> float | None:
    if value is None or value < 0:
        return None
    if value == 0:
        return Y_CAP
    return min(-math.log10(value), Y_CAP)


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


def write_plot_data(image_path: Path, payload: dict[str, Any]) -> None:
    """Publish the exact rendered data beside the PNG using the existing artifact API."""
    path = image_path.with_suffix(".plot.json")
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"version": 1, **payload}, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def plot_record(plot_id: str, path: Path, title: str, explanation_dir: Path) -> dict[str, Any]:
    return {
        "plot_id": plot_id,
        "path": str(path),
        "title": title,
        "source": "gwas-qc",
        "explanation_path": str(explanation_dir / f"{plot_id}.md"),
    }


def payload_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    return Path(text).expanduser().resolve() if text else None


def valid_file(path: Path | None) -> bool:
    return path is not None and path.exists() and path.is_file()


def stable_sample(value: Any) -> bool:
    digest = hashlib.md5(str(value).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % SAMPLE_MOD == 0


def median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def clean_text(value: Any) -> str:
    return str(value or "").strip().replace("\r", " ").replace("\n", " ").replace("\t", " ")


def to_int(value: Any) -> int | None:
    try:
        parsed = int(float(str(value or "").strip()))
    except ValueError:
        return None
    return parsed if parsed > 0 else None


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
