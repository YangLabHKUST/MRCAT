"""SNP targets must correspond to the author's unchanged, native MR-APSS plot."""
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image
import pytest

pytestmark = pytest.mark.r
ROOT = Path(__file__).resolve().parents[1]
RSCRIPT = os.environ.get("RSCRIPT_BIN", str(Path(sys.executable).with_name("Rscript")))


def test_native_png_and_snp_coordinates(tmp_path):
    helper = ROOT / "skills/mr-apss/scripts/mrapss/export_mrapss_plot.R"
    code = f'''
    source({json.dumps(str(helper))})
    setwd({json.dumps(str(tmp_path))})
    fit <- list(MRdat=data.frame(SNP=paste0("rs", 101:106),
      b.exp=c(-.08,-.03,.02,.055,.08,.12), b.out=c(-.04,.015,.005,.025,.02,.065),
      se.exp=rep(.007,6), se.out=rep(.006,6), pval.exp=c(1e-8,1e-7,1e-9,1e-11,1e-9,1e-10)),
      post=list(Pi=c(.9,.2,.8,.95,.7,.97)), beta=.4, beta.se=.08)
    plot <- MRAPSS::MRplot(fit, exposure="Synthetic exposure", outcome="Synthetic outcome")
    ggplot2::ggsave("original.png", plot=plot, width=7, height=5, dpi=300)
    export_mrapss_plot(plot, fit, "interactive.png")
    # Keep scales and layout, but hide points to identify their exact painted pixels.
    plot$layers <- lapply(plot$layers, function(layer) {{
      if (inherits(layer$geom, "GeomPoint")) {{
        layer$aes_params$alpha <- 0
      }}
      layer
    }})
    ggplot2::ggsave("without_points.png", plot=plot, width=7, height=5, dpi=300)
    '''
    result = subprocess.run([RSCRIPT, "-e", code], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    original = np.asarray(Image.open(tmp_path / "original.png").convert("RGB"))
    interactive = np.asarray(Image.open(tmp_path / "interactive.png").convert("RGB"))
    np.testing.assert_array_equal(original, interactive)
    without_points = np.asarray(Image.open(tmp_path / "without_points.png").convert("RGB"))
    data = json.loads((tmp_path / "interactive.plot.json").read_text())
    assert (data["width"], data["height"]) == (2100, 1500)
    assert [p["snp"] for p in data["points"]] == [f"rs{i}" for i in range(101, 107)]
    assert [p["posterior"] for p in data["points"]] == pytest.approx([.9, .2, .8, .95, .7, .97])
    assert [p["b_exp"] for p in data["points"]] == pytest.approx([-.08, -.03, .02, .055, .08, .12])
    for point in data["points"]:
        x, y = round(point["x"] * data["width"]), round(point["y"] * data["height"])
        assert point["x_low"] < point["x"] < point["x_high"]
        assert point["y_low"] < point["y"] < point["y_high"]
        assert 0 < x < data["width"] and 0 < y < data["height"]
        # A real point must have painted pixels at the exported click target.
        patch = interactive[y-3:y+4, x-3:x+4]
        assert np.any(patch != without_points[y-3:y+4, x-3:x+4]), point
