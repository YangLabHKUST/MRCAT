"""Real R tests for directionality, metadata safeguards and opt-in refitting."""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.r

from mrcat import tools

ROOT = Path(__file__).resolve().parents[1]
RSCRIPT = os.environ.get("RSCRIPT_BIN", str(Path(sys.executable).with_name("Rscript")))
HELPER = ROOT / "skills/analysis-sensitivity/scripts/mr_sensitivity/steiger.R"


def run_r(tmp_path, body):
    output = tmp_path / "result.json"
    setup = f'''
    source({json.dumps(str(ROOT / "mrcat/tool/MRTool/mr_inference.R"))})
    source({json.dumps(str(HELPER))})
    library(data.table)
    d <- data.table(SNP=paste0("rs", 1:8), b.exp=seq(.08,.15,.01),
                    b.out=seq(.08,.15,.01)*.3, se.exp=.01, se.out=.01,
                    pval.exp=1e-12, N.exp=10000, N.out=10000,
                    input_scale="standardize")
    meta <- list(exposure=list(type="quantitative"), outcome=list(type="quantitative"))
    execute <- function(filter=FALSE) {{
      dat <- data.frame(SNP=d$SNP, beta.exposure=d$b.exp, beta.outcome=d$b.out,
                        se.exposure=d$se.exp, se.outcome=d$se.out,
                        exposure="X", outcome="Y", id.exposure="X", id.outcome="Y", mr_keep=TRUE)
      run_steiger(d, meta, filter, dat, {json.dumps(str(tmp_path))}, 1234L)
    }}
    dir.create({json.dumps(str(tmp_path / 'reports'))}, showWarnings=FALSE)
    '''
    script = tmp_path / "check.R"
    script.write_text(setup + body + f'''
    jsonlite::write_json(result, {json.dumps(str(output))}, auto_unbox=TRUE,
                         null="null", na="null", digits=NA)
    ''')
    completed = subprocess.run([RSCRIPT, str(script)], capture_output=True, text=True, timeout=90)
    assert completed.returncode == 0, completed.stderr[-6000:]
    return json.loads(output.read_text())


@pytest.mark.parametrize("multiplier, interpretation", [
    (.3, "supports_exposure_to_outcome"),
    (2, "supports_outcome_to_exposure"),
    (1.001, "inconclusive"),
    (1, "inconclusive"),
])
def test_direction_and_pvalue_match_independent_fisher_calculation(tmp_path, multiplier, interpretation):
    response = run_r(tmp_path, f"d$b.out <- d$b.exp * {multiplier}\nresult <- execute()")
    result = response["result"]
    assert result["status"] == "ok"
    assert result["interpretation"] == interpretation
    r2x = sum((b / .01) ** 2 / (9998 + (b / .01) ** 2) for b in [.08 + .01*i for i in range(8)])
    r2y = sum((b * multiplier / .01) ** 2 / (9998 + (b * multiplier / .01) ** 2)
              for b in [.08 + .01*i for i in range(8)])
    z = (math.atanh(math.sqrt(r2x)) - math.atanh(math.sqrt(r2y))) / math.sqrt(2 / 9997)
    assert result["r2_exposure"] == pytest.approx(r2x)
    assert result["r2_outcome"] == pytest.approx(r2y)
    assert result["steiger_pval"] == pytest.approx(math.erfc(abs(z) / math.sqrt(2)), rel=1e-10, abs=1e-14)
    assert result["filtering"]["status"] == "not_requested"
    assert not (tmp_path / "reports/sensitivity_steiger_filtered_mrdat.tsv").exists()


@pytest.mark.parametrize("change, reason", [
    ("meta <- NULL", "specify type"),
    ('meta$outcome$type <- "unknown"', "specify type"),
    ("d$N.out <- NULL", "sample_size"),
    ("d$N.out[2] <- NA", "sample_size"),
    ("d$N.exp <- 3", "exceed 3"),
    ("d$se.exp[2] <- 0", "SE must be positive"),
    ("d$SNP[2] <- d$SNP[1]", "unique"),
    ("d$b.exp <- 100", "Summed SNP R-squared"),
    ('meta$outcome <- list(type="binary")', "beta_scale"),
])
def test_unavailable_is_explicit_and_never_filters_incomplete_data(tmp_path, change, reason):
    response = run_r(tmp_path, change + "\nresult <- execute(TRUE)")
    result = response["result"]
    assert result["status"] == "unavailable"
    assert reason in result["reason"]
    assert result["filtering"]["status"] == "blocked"
    assert "correct_causal_direction" not in result
    assert not list((tmp_path / "reports").iterdir())


BINARY_SETUP = '''
d$b.out.native <- seq(.05,.12,.01)
d$eaf.out <- seq(.2,.55,.05)
meta$outcome <- list(type="binary", beta_scale="log_odds", eaf_column="eaf.out",
                     ncase=2000, ncontrol=8000, prevalence=.08)
'''


def test_binary_uses_native_log_odds_and_explicit_population_prevalence(tmp_path):
    result = run_r(tmp_path, BINARY_SETUP + '''
    d$b.out <- d$b.out * 100
    result <- execute()
    expected <- TwoSampleMR::get_r_from_lor(d$b.out.native, d$eaf.out, 2000, 8000, .08)
    stopifnot(isTRUE(all.equal(result$result$r2_outcome, sum(expected^2))))
    stopifnot(result$result$outcome$correlation_method == "get_r_from_lor")
    ''')["result"]
    assert result["status"] == "ok"
    assert result["outcome"]["prevalence"] == .08


def test_explicit_sample_sizes_and_direction_only_filter(tmp_path):
    result = run_r(tmp_path, '''
    d$N.exp <- d$N.out <- NULL
    d$study_n <- rep(10000, nrow(d))
    meta$exposure$sample_size <- "study_n"
    meta$outcome$sample_size <- 10000
    d$b.out <- .999*d$b.exp
    result <- execute(TRUE)
    snps <- data.table::fread(result$reports$steiger_snps)
    stopifnot(all(snps$steiger_pval > .05))
    ''')["result"]
    assert result["status"] == "ok"
    assert result["interpretation"] == "inconclusive"
    assert result["filtering"]["nsnp_retained"] == 8
    assert result["exposure"]["sample_size"] == "study_n"


@pytest.mark.parametrize("change, reason", [
    ("meta$outcome$prevalence <- NULL", "population prevalence"),
    ("meta$outcome$ncase <- NULL", "ncase"),
    ("meta$outcome$eaf_column <- NULL", "eaf_column"),
    ("d$b.out.native <- NULL", "native log-odds"),
    ("d$eaf.out[1] <- 1.2", "invalid binary"),
    ("meta$outcome$prevalence <- 0", "invalid binary"),
])
def test_binary_never_guesses_missing_metadata(tmp_path, change, reason):
    result = run_r(tmp_path, BINARY_SETUP + change + "\nresult <- execute()")["result"]
    assert result["status"] == "unavailable"
    assert reason in result["reason"]


@pytest.mark.parametrize("retained", [0, 2, 6, 8])
def test_filtering_preserves_subset_scale_and_refits_only_when_sufficient(tmp_path, retained):
    response = run_r(tmp_path, f'''
    d$b.out <- 2*d$b.exp
    if ({retained} > 0) d$b.out[seq_len({retained})] <- .3*d$b.exp[seq_len({retained})] + seq_len({retained})^2*.0001
    d$input_scale <- "native"
    original <- copy(d)
    result <- execute(TRUE)
    stopifnot(identical(d, original))
    for (row in result$result$filtering$estimates) {{
      df <- switch(row$method,"MR Egger"=row$nsnp-2,"Weighted mode"=row$nsnp-1,NULL)
      critical <- if(is.null(df)) qnorm(.975) else qt(.975,df)
      stopifnot(isTRUE(all.equal(row$lo_ci,row$b-critical*row$se)),
                isTRUE(all.equal(row$up_ci,row$b+critical*row$se)))
    }}
    ''')
    filtering = response["result"]["filtering"]
    assert filtering["nsnp_retained"] == retained
    assert filtering["nsnp_removed"] == 8 - retained
    assert filtering["input_scale"] == "native"
    with Path(filtering["selected_mrdat_path"]).open() as handle:
        subset = list(csv.DictReader(handle, delimiter="\t"))
    assert [row["SNP"] for row in subset] == [f"rs{i+1}" for i in range(retained)]
    if retained < 4:
        assert filtering["status"] == "blocked"
        assert "Fewer than four" in filtering["reason"]
    else:
        assert filtering["status"] == "ok"
        assert len(filtering["estimates"]) == 4
        ivw = next(row for row in filtering["estimates"] if row["method"] == "Inverse variance weighted")
        xs, ys = [float(r["b.exp"]) for r in subset], [float(r["b.out"]) for r in subset]
        assert ivw["b"] == pytest.approx(sum(x*y for x, y in zip(xs, ys)) / sum(x*x for x in xs))


@pytest.mark.parametrize("with_metadata, filter_requested", [(False, False), (False, True), (True, True)])
def test_public_tool_real_primary_to_sensitivity_and_artifacts(tmp_path, monkeypatch, with_metadata, filter_requested):
    monkeypatch.setenv("RSCRIPT_BIN", RSCRIPT)
    source = tmp_path / "MRdat.tsv"
    with source.open("w") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["SNP", "b.exp", "b.out", "se.exp", "se.out", "pval.exp", "N.exp", "N.out"])
        for i in range(12):
            bx = .1 + (i % 7) * .013
            writer.writerow([f"rs{i+1}", bx, .35*bx + ((i % 5)-2)*.002, .01, .01, 1e-12, 10000, 10000])
    primary = tools.mr_primary(mrdat_path=source, output_dir=tmp_path / "primary")
    assert primary["outputs"]["status"] == "ok", primary
    record = primary["outputs"]["mr_primary_result"]
    selected = Path(record["selected_mrdat_path"])
    digest = hashlib.sha256(selected.read_bytes()).hexdigest()
    metadata = {side: {"type": "quantitative"} for side in ("exposure", "outcome")} if with_metadata else None
    response = tools.analysis_sensitivity(primary_result_record_path=record["result_record_path"],
        steiger_metadata=metadata, steiger_filter=filter_requested, nb_distribution=100,
        detailed_plot_max_instruments=1, output_dir=tmp_path / "sensitivity")
    assert response["outputs"]["status"] == "ok", response
    result = response["outputs"]["mr_sensitivity_result"]
    assert result["steiger"]["status"] == ("ok" if with_metadata else "unavailable")
    expected_filter_status = "ok" if with_metadata else "blocked" if filter_requested else "not_requested"
    assert result["steiger"]["filtering"]["status"] == expected_filter_status
    assert result["heterogeneity"] and result["pleiotropy"] and result["mr_presso"]
    assert all(Path(artifact["path"]).is_file() for artifact in response["artifacts"])
    assert hashlib.sha256(selected.read_bytes()).hexdigest() == digest
    assert json.loads(Path(result["result_record_path"]).read_text()) == result
    if with_metadata:
        assert 0 < result["steiger"]["steiger_pval"] < 1e-10
