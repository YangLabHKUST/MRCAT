"""Check package decisions, bounded P values and both real MR-PRESSO entrypoints."""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.r

from mrcat import tools

ROOT = Path(__file__).resolve().parents[1]
RSCRIPT = os.environ.get("RSCRIPT_BIN", str(Path(sys.executable).with_name("Rscript")))
HELPER = ROOT / "mrcat/tool/MRTool/mr_presso_results.R"


def run_r(tmp_path, body):
    script = tmp_path / "verify.R"
    output = tmp_path / "verified.json"
    script.write_text(f"source({json.dumps(str(HELPER))})\n" + body + f"""
    jsonlite::write_json(result, {json.dumps(str(output))}, auto_unbox=TRUE,
                         null="null", na="null", digits=NA)
    """)
    completed = subprocess.run([RSCRIPT, str(script)], capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr[-6000:]
    return json.loads(output.read_text())


FIXTURE = """
d <- data.frame(SNP=paste0("rs", 1:74), b.exp=.1, b.out=.03, se.exp=.01, se.out=.01)
rownames(d) <- d$SNP
ot <- data.frame(Pvalue=rep("1", 74), row.names=rownames(d))
ot$Pvalue[c(2,5)] <- "<0.074"
fit <- list(
  `Main MR results`=data.frame(`MR Analysis`=c("Raw","Outlier-corrected"),
                              `Causal Estimate`=c(.4,.3), check.names=FALSE),
  `MR-PRESSO results`=list(
    `Global Test`=list(RSSobs=99, Pvalue="<0.001"),
    `Outlier Test`=ot,
    `Distortion Test`=list(`Outliers Indices`=c(2,5), Pvalue="<0.001",
                           `Distortion Coefficient`=25)))
"""


def test_formatted_upper_bounds_do_not_override_package_outlier_indices(tmp_path):
    result = run_r(tmp_path, FIXTURE + "\nresult <- mr_presso_extract(fit, d, .05)")
    assert result["outlier_indices"] == [2, 5]
    assert result["outlier_snps"] == ["rs2", "rs5"]
    assert result["outlier_count"] == 2
    assert result["outlier_status"] == "detected"
    assert result["global_pval"] == "<0.001"
    assert result["global_detected"] is True
    assert result["distortion_pval"] == "<0.001"
    assert result["outlier_rows"] == [
        {"snp": "rs2", "pval": "<0.074"}, {"snp": "rs5", "pval": "<0.074"}
    ]


@pytest.mark.parametrize("status, replacement, count", [
    ("none", 'fit[["MR-PRESSO results"]][["Distortion Test"]][["Outliers Indices"]] <- "No significant outliers"', 0),
    ("all", 'fit[["MR-PRESSO results"]][["Distortion Test"]][["Outliers Indices"]] <- "All SNPs considered as outliers"', 74),
    ("not_tested", 'fit[["MR-PRESSO results"]][c("Outlier Test","Distortion Test")] <- NULL', None),
])
def test_absent_test_is_distinct_from_no_outliers(tmp_path, status, replacement, count):
    result = run_r(tmp_path, FIXTURE + """
    fit[["Main MR results"]][["Causal Estimate"]][2] <- NA_real_
    fit[["MR-PRESSO results"]][["Distortion Test"]][["Pvalue"]] <- NA_real_
    """ + replacement + "\nresult <- mr_presso_extract(fit, d, .05)")
    assert result["outlier_status"] == status
    assert result["outlier_count"] == count
    assert result["distortion_pval"] is None
    assert result["distortion_detected"] is None


@pytest.mark.parametrize("change, message", [
    ('fit[["MR-PRESSO results"]][["Distortion Test"]] <- NULL', "without Outliers Indices"),
    ('fit[["MR-PRESSO results"]][["Distortion Test"]][["Outliers Indices"]] <- c(2,75)', "invalid Outliers Indices"),
    ('rownames(fit[["MR-PRESSO results"]][["Outlier Test"]]) <- rev(rownames(d))', "does not match"),
    ('d$b.out[1] <- NA_real_', "do not silently drop rows"),
    ('fit[["MR-PRESSO results"]][["Distortion Test"]][["Outliers Indices"]] <- "No significant outliers"', "contradicts"),
])
def test_ambiguous_or_inconsistent_result_cannot_be_reported_as_zero(tmp_path, change, message):
    result = run_r(tmp_path, FIXTURE + change + """
    result <- tryCatch({mr_presso_extract(fit, d, .05); "unexpected success"},
                       error=function(e) conditionMessage(e))
    """)
    assert message in result


def test_pvalue_bounds_and_simulation_resolution(tmp_path):
    result = run_r(tmp_path, """
    vals <- list("<0.001", "<0.074", "<0.05", "<=0.05", ">=0.05", .01, .05, NA)
    result <- list(
      flags=lapply(vals, mr_presso_detected, alpha=.05),
      simulations=mapply(mr_presso_simulations, c(74,722,12,12),
                         c(1000,1000,100,10000), MoreArgs=list(alpha=.05)))
    """)
    assert result["flags"] == [True, None, True, None, False, True, False, None]
    assert result["simulations"] == [1481, 14441, 241, 10000]


@pytest.mark.parametrize("entrypoint", ["mr_presso", "analysis_sensitivity", "analysis_sensitivity_timeout"])
def test_public_tools_match_unmodified_package_result(tmp_path, monkeypatch, entrypoint):
    monkeypatch.setenv("RSCRIPT_BIN", RSCRIPT)
    source = tmp_path / "MRdat.tsv"
    with source.open("w") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["SNP", "b.exp", "b.out", "se.exp", "se.out", "pval.exp", "N.exp", "N.out"])
        for i in range(12):
            bx = .1 + (i % 7) * .013
            by = .35*bx + ((i % 5)-2)*.002 + (.12 if i == 11 else 0)
            writer.writerow([f"rs{i+1}", bx, by, .01, .01, 1e-12, 10000, 10000])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if entrypoint == "mr_presso":
        response = tools.mr_presso(mrdat_path=source, nb_distribution=100,
                                   output_dir=tmp_path / entrypoint)
        assert response["outputs"]["status"] == "ok", response
        record = response["outputs"]["mr_presso_result"]
        actual = record["mr_presso"]
        raw_path = record["diagnostics"]["raw_result_path"]
        count, snps = actual["outlier_test"]["count"], actual["outlier_test"]["snps"]
        global_p, distortion_p = actual["global_test"]["pval"], actual["distortion_test"]["pval"]
        raw_beta = actual["raw_estimate"]["beta.hat"]
        corrected_beta = actual["corrected_estimate"]["beta.hat"]
        simulations = record["diagnostics"]["nb_distribution_used"]
    else:
        primary = tools.mr_primary(mrdat_path=source, output_dir=tmp_path / "primary")
        assert primary["outputs"]["status"] == "ok", primary
        response = tools.analysis_sensitivity(
            primary_result_record_path=primary["outputs"]["mr_primary_result"]["result_record_path"],
            mr_presso_timeout_seconds=0.001 if entrypoint.endswith("_timeout") else 300,
            nb_distribution=100, detailed_plot_max_instruments=1, output_dir=tmp_path / entrypoint)
        assert response["outputs"]["status"] == "ok", response
        record = response["outputs"]["mr_sensitivity_result"]
        actual = record["mr_presso"]
        if entrypoint.endswith("_timeout"):
            assert actual["status"] == "unavailable"
            assert "time limit" in actual["reason"]
            assert actual["nb_distribution_used"] == 241
            assert actual["outlier_status"] == "not_tested"
            for key in ("global_pval", "global_rss", "detected", "outlier_count", "raw_beta",
                        "corrected_beta", "distortion_pval", "distortion_detected", "raw_result_path"):
                assert actual[key] is None
            assert record["heterogeneity"]
            assert record["pleiotropy"]["pval"] is not None
            assert record["leave_one_out"]["most_influential_snp"]
            assert record["steiger"]["status"] == "unavailable"
            for name in ("heterogeneity", "pleiotropy", "single_snp", "leave_one_out"):
                assert Path(record["reports"][name]).is_file()
            assert "mr_presso" not in record["reports"]
            assert {p["plot_id"] for p in record["plot_manifest"]["plots"]} == {"sensitivity_funnel"}
            assert all(Path(a["path"]).is_file() for a in response["artifacts"])
            assert "mr_presso_status=unavailable" in response["summary"]
            assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
            return
        assert actual["status"] == "ok"
        raw_path = actual["raw_result_path"]
        count, snps = actual["outlier_count"], actual["outlier_snps"]
        global_p, distortion_p = actual["global_pval"], actual["distortion_pval"]
        raw_beta, corrected_beta = actual["raw_beta"], actual["corrected_beta"]
        simulations = actual["nb_distribution_used"]
    assert response["outputs"]["status"] == "ok", response
    assert simulations == 241
    assert count > 0
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    assert any(a["path"] == raw_path for a in response["artifacts"])
    native = run_r(tmp_path, f"""
    fit <- readRDS({json.dumps(raw_path)})
    tests <- fit[["MR-PRESSO results"]]
    indices <- tests[["Distortion Test"]][["Outliers Indices"]]
    main <- fit[["Main MR results"]]
    if ({json.dumps(entrypoint)} == "analysis_sensitivity") {{
      single <- read.delim(file.path(dirname({json.dumps(raw_path)}),"sensitivity_single_snp.tsv"))
      egger <- single[single$SNP=="All - MR Egger",]
      stopifnot(nrow(egger)==1,
                isTRUE(all.equal(egger$lo_ci,egger$b-qt(.975,10)*egger$se)),
                isTRUE(all.equal(egger$up_ci,egger$b+qt(.975,10)*egger$se)))
    }}
    result <- list(snps=as.list(paste0("rs", indices)), count=length(indices),
                   global=tests[["Global Test"]]$Pvalue,
                   distortion=tests[["Distortion Test"]]$Pvalue,
                   beta=main[["Causal Estimate"]],p=main[["P-value"]],
                   raw_ci=main[["Causal Estimate"]][1]+c(-1,1)*qt(.975,11)*main$Sd[1],
                   corrected_ci=main[["Causal Estimate"]][2]+c(-1,1)*qt(.975,11-length(indices))*main$Sd[2])
    """)
    assert count == native["count"]
    assert snps == native["snps"]
    for actual_p, expected_p in [(global_p, native["global"]), (distortion_p, native["distortion"])]:
        if isinstance(expected_p, str) and expected_p.startswith("<"):
            assert actual_p == expected_p
        else:
            assert actual_p == pytest.approx(float(expected_p), abs=5e-5)
    assert [raw_beta, corrected_beta] == pytest.approx(native["beta"], abs=5e-5)
    if entrypoint == "mr_presso":
        for key in ("raw", "corrected"):
            estimate = actual[f"{key}_estimate"]
            bounds = estimate["ci"]["ranges"][0]
            assert [bounds["lower"], bounds["upper"]] == pytest.approx(native[f"{key}_ci"])
        assert record["methods"][0]["nsnp"] == 12 - count
        assert record["methods"][0]["pval"] == pytest.approx(native["p"][1])
