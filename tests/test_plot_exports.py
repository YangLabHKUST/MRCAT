"""Static plots produce only PNG; interactive data stays in its own artifacts."""
from pathlib import Path
import runpy

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("skill,script,function", [
    ("analysis-bidirectional", "run_bidirectional.py", "_save_publication_figure"),
    ("analysis-replication", "run_replication.py", "_save_publication_figure"),
    ("analysis-mediation", "run_mr_mediation.py", "_save_publication_figure"),
    ("analysis-result-synthesis", "run_mr_result_synthesis.py", "_save_publication_figure"),
    ("analysis-risk-factor-prioritization", "run_mr_risk_factor_prioritization.py", "_save_publication_figure"),
    ("analysis-method-comparison", "run_method_comparison.py", "save_figure"),
    ("gwas-qc", "generate_plots.py", "save_figure"),
    ("gwas-pair-prepare", "generate_plots.py", "save_figure"),
])
def test_static_export_is_png_only(tmp_path, skill, script, function):
    module = runpy.run_path(str(ROOT / "skills" / skill / "scripts" / script))
    figure, axis = plt.subplots(figsize=(2, 2))
    axis.plot([0, 1], [0, 1])
    axis.set_xlabel(r"$\hat{\beta}$")
    output = tmp_path / "estimate.png"
    try:
        module[function](figure, plt, output)
        assert list(tmp_path.iterdir()) == [output]
        with Image.open(output) as image:
            assert image.format == "PNG"
            image.verify()
    finally:
        plt.close(figure)
