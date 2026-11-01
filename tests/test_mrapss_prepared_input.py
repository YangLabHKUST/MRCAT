import sys
"""Verify the fit-only MR-APSS contract against the installed author package."""

import csv
import json
import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.r

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/mr-apss/scripts/mrapss/run_mrapss.R"
RSCRIPT = os.environ.get("RSCRIPT_BIN", str(Path(sys.executable).parent / "Rscript"))


def run_r(args):
    return subprocess.run(
        [RSCRIPT, *map(str, args)], capture_output=True, text=True, timeout=180
    )


@pytest.fixture(scope="module")
def prepared_pair(tmp_path_factory):
    directory = tmp_path_factory.mktemp("mrapss_author_example")
    # Offline author-provided clumped data; no GWAS download or LD API calls.
    code = f"""
    suppressPackageStartupMessages({{
      library(MRAPSS); library(data.table); library(jsonlite)
    }})
    data(MRdat); data(C); data(Omega)
    setwd({json.dumps(str(directory))})
    fwrite(as.data.table(C), "C.tsv", sep="\\t", col.names=FALSE)
    fwrite(as.data.table(Omega), "Omega.tsv", sep="\\t", col.names=FALSE)
    for (scenario in c("adjusted", "unchanged")) {{
      dat <- MRdat
      if (scenario == "unchanged") dat$Threshold <- 5e-5
      fwrite(dat, paste0(scenario, ".tsv"), sep="\\t")
      # Read the exact serialized input used by the wrapper.
      dat <- as.data.frame(fread(paste0(scenario, ".tsv")))
      fit <- MRAPSS(dat, C=C, Omega=Omega, Cor.SelectionBias=TRUE)
      write_json(list(beta=fit$beta, se=fit$beta.se,
                      pvalue=as.numeric(fit$pvalue), Threshold=fit$Threshold,
                      nsnp=nrow(fit$MRdat)),
                 paste0(scenario, ".json"), auto_unbox=TRUE, digits=NA)
    }}
    """
    result = run_r(["-e", code])
    assert result.returncode == 0, result.stderr[-4000:]
    return directory


def run_wrapper(tmp_path, prepared_pair, data_path, **extra):
    payload = {
        "mrdat_path": str(data_path),
        "c_path": str(prepared_pair / "C.tsv"),
        "omega_path": str(prepared_pair / "Omega.tsv"),
        **extra,
    }
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps(payload))
    completed = run_r([SCRIPT, input_path, output_path, tmp_path])
    return completed, output_path


@pytest.mark.parametrize("scenario", ["adjusted", "unchanged"])
def test_preserves_prepared_threshold_and_matches_direct_fit(
    tmp_path, prepared_pair, scenario
):
    source_path = prepared_pair / f"{scenario}.tsv"
    reference = json.loads((prepared_pair / f"{scenario}.json").read_text())
    completed, output_path = run_wrapper(tmp_path, prepared_pair, source_path)
    assert completed.returncode == 0, completed.stderr[-4000:]
    result = json.loads(output_path.read_text())
    assert result["outputs"]["status"] == "ok"
    record = result["outputs"]["mrapss_result"]
    fitted = record["methods"][0]
    assert fitted["Threshold"] == pytest.approx(reference["Threshold"], rel=1e-12)
    assert fitted["beta.hat"] == pytest.approx(reference["beta"], rel=1e-8)
    assert fitted["se"] == pytest.approx(reference["se"], rel=1e-8)
    assert fitted["pval"] == pytest.approx(reference["pvalue"], rel=1e-8, abs=0)
    assert fitted["nsnp"] == reference["nsnp"]
    assert record["diagnostics"]["selection_bias_threshold"] == fitted["Threshold"]
    assert "pvalue_threshold" not in record["diagnostics"]
    assert "MRdat_selection_bias_threshold=" in result["summary"]

    with source_path.open() as handle:
        source = list(csv.DictReader(handle, delimiter="\t"))
    with Path(record["selected_mrdat_path"]).open() as handle:
        selected = list(csv.DictReader(handle, delimiter="\t"))
    assert [r["SNP"] for r in selected] == [r["SNP"] for r in source]
    assert [float(r["Threshold"]) for r in selected] == [
        float(r["Threshold"]) for r in source
    ]
    if scenario == "adjusted":
        assert fitted["Threshold"] != 5e-5
        # A correction threshold must not become a second SNP-selection cutoff.
        assert any(float(r["pval.exp"]) > fitted["Threshold"] for r in selected)


@pytest.mark.parametrize("invalid", ["mixed", "missing", "NA", "0", "29.716"])
def test_invalid_correction_threshold_is_not_repaired_or_filtered(
    tmp_path, prepared_pair, invalid
):
    with (prepared_pair / "adjusted.tsv").open() as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = reader.fieldnames
        rows = list(reader)
    if invalid == "missing":
        fields = [field for field in fields if field != "Threshold"]
        for row in rows:
            row.pop("Threshold")
    else:
        rows[0]["Threshold"] = "5e-5" if invalid == "mixed" else invalid
    path = tmp_path / "invalid.tsv"
    with path.open("w") as handle:
        writer = csv.DictWriter(handle, fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    completed, output_path = run_wrapper(tmp_path, prepared_pair, path)
    assert completed.returncode != 0
    assert "Threshold" in completed.stderr
    assert not output_path.exists()
    assert not (tmp_path / "reports/mrapss_result_record.json").exists()


@pytest.mark.parametrize("threshold", [5e-5, 1e-6])
def test_fit_rejects_reselection_even_when_nominal_threshold_is_default(
    tmp_path, prepared_pair, threshold
):
    completed, output_path = run_wrapper(
        tmp_path, prepared_pair, prepared_pair / "adjusted.tsv",
        pvalue_threshold=threshold,
    )
    assert completed.returncode != 0
    assert "Set iv_threshold in gwas-pair-prepare" in completed.stderr
    assert not output_path.exists()


def test_public_fit_interface_does_not_accept_a_selection_threshold():
    from mrcat.tools import mr_apss

    with pytest.raises(TypeError, match="pvalue_threshold"):
        mr_apss(
            mrdat_path="unused", c_path="unused", omega_path="unused",
            pvalue_threshold=5e-5,
        )
