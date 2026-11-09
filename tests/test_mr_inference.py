"""Intervals must match estimator inference and survive downstream rendering."""
import csv
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.r

ROOT = Path(__file__).resolve().parents[1]
RSCRIPT = os.environ.get("RSCRIPT_BIN", str(Path(sys.executable).with_name("Rscript")))


def run_r(tmp_path, body):
    script = tmp_path / "check.R"
    output = tmp_path / "result.json"
    script.write_text(f'''
    root <- {json.dumps(str(ROOT))}
    source(file.path(root, "mrcat/tool/MRTool/mr_inference.R"))
    load_functions <- function(relative) {{
      env <- new.env(parent=globalenv())
      for (expr in parse(file.path(root, relative))) {{
        if (is.call(expr) && identical(expr[[1]], as.name("<-")) &&
            is.call(expr[[3]]) && identical(expr[[3]][[1]], as.name("function"))) eval(expr,env)
      }}
      env
    }}
    {body}
    jsonlite::write_json(result, {json.dumps(str(output))}, auto_unbox=TRUE,
                         null="null", na="null", digits=NA)
    ''')
    completed = subprocess.run([RSCRIPT, str(script)], capture_output=True, text=True, timeout=90)
    assert completed.returncode == 0, completed.stderr[-6000:]
    return json.loads(output.read_text())


def test_primary_methods_match_actual_package_pvalues(tmp_path):
    result = run_r(tmp_path, '''
    env <- load_functions("skills/mr-primary/scripts/mr_primary/run_mr_primary.R")
    env$log_step <- function(...) NULL
    sys.source(file.path(root,"skills/mr-primary/scripts/mr_primary/fit_primary.R"),env)
    n <- 10; x <- seq(.04,.24,length.out=n); sx <- rep(.005,n); sy <- rep(.04,n)
    y <- .01 + sin(seq_len(n))*.04
    base <- TwoSampleMR::mr_egger_regression(x,y,sx,sy)
    y <- y + (2.1*base$se-base$b)*x
    d <- data.frame(b.exp=x,b.out=y,se.exp=sx,se.out=sy)
    set.seed(217)
    rows <- env$fit_primary(d,5e-6)
    for (row in rows) {
      df <- switch(row$method,"MR-Egger"=n-2,"Weighted mode"=n-1,NULL)
      z <- abs(row$beta.hat/row$se)
      expected_p <- if(is.null(df)) 2*pnorm(-z) else 2*pt(-z,df)
      stopifnot(isTRUE(all.equal(row$pval,expected_p)))
      bounds <- mr_ci_bounds(row$ci)
      stopifnot((bounds[1] > 0 || bounds[2] < 0) == (row$pval < .05))
      critical <- if(is.null(df)) qnorm(.975) else qt(.975,df)
      stopifnot(isTRUE(all.equal(unname(bounds),row$beta.hat+c(-1,1)*critical*row$se)))
    }
    result <- rows
    ''')
    egger = next(row for row in result if row["method"] == "MR-Egger")
    assert egger["pval"] > .05
    assert egger["ci"]["ranges"][0]["lower"] < 0 < egger["ci"]["ranges"][0]["upper"]


@pytest.mark.parametrize("entrypoint", ["mr-primary", "mr-primary-id"])
def test_primary_forest_uses_saved_interval_not_se(tmp_path, entrypoint):
    result = run_r(tmp_path, f'''
    relative <- "skills/{entrypoint}/scripts/{entrypoint.replace('-', '_')}/run_{entrypoint.replace('-', '_')}.R"
    env <- load_functions(relative)
    rows <- list(list(method="MR-Egger",beta.hat=2,se=.1,
                     ci=list(level=.95,ranges=list(list(lower=-1,upper=4)))))
    trace("ggsave",where=asNamespace("ggplot2"),tracer=quote(captured_plot <<- plot),print=FALSE)
    path <- {json.dumps(str(tmp_path / 'forest.png'))}
    if ({json.dumps(entrypoint)} == "mr-primary") env$save_estimates_forest(rows,path) else env$save_estimates_forest(path,rows)
    untrace("ggsave",where=asNamespace("ggplot2"))
    layer <- ggplot2::ggplot_build(captured_plot)$data[[2]]
    result <- list(lower=layer$xmin,upper=layer$xmax)
    ''')
    assert result == {"lower": -1, "upper": 4}


def test_grip_real_fit_uses_t_intervals_for_both_estimates(tmp_path):
    result = run_r(tmp_path, '''
    set.seed(217)
    n <- 12; x <- seq(.04,.26,length.out=n); sx <- rep(.005,n); sy <- rep(.04,n)
    y <- rnorm(n,0,.04)
    base <- TwoSampleMR::mr_grip(x,y,sx,sy,parameters=list())
    y <- y + (2.1*base$se-base$b)*x
    fit <- TwoSampleMR::mr_grip(x,y,sx,sy,parameters=list())
    directory <- tempfile(); dir.create(directory)
    data_path <- file.path(directory,"input.tsv")
    data.table::fwrite(data.frame(SNP=paste0("rs",seq_len(n)),b.exp=x,b.out=y,
                                se.exp=sx,se.out=sy,pval.exp=1e-12),data_path,sep="\t")
    input <- file.path(directory,"input.json"); output <- file.path(directory,"output.json")
    jsonlite::write_json(list(mrdat_path=data_path),input,auto_unbox=TRUE,digits=NA)
    logs <- system2(file.path(R.home("bin"),"Rscript"),
                    c(file.path(root,"skills/mr-grip/scripts/mr_grip/run_mr_grip.R"),input,output,directory),
                    stdout=TRUE,stderr=TRUE)
    if (!is.null(attr(logs,"status"))) stop(paste(logs,collapse="\n"))
    saved <- jsonlite::read_json(output)$outputs$mr_grip_result$methods
    stopifnot(isTRUE(all.equal(saved[[1]]$beta.hat,fit$b)),
              isTRUE(all.equal(saved[[1]]$se,fit$se)),
              isTRUE(all.equal(saved[[1]]$pval,fit$pval)))
    ordinary <- saved[[1]]$ci
    adjusted <- saved[[2]]$ci
    stopifnot(fit$pval>.05,fit$pval.adj>.05,
              ordinary$ranges[[1]]$lower<0,adjusted$ranges[[1]]$lower<0)
    result <- list(ordinary=ordinary,adjusted=adjusted)
    ''')
    assert result["ordinary"]["ranges"][0]["upper"] > 0
    assert result["adjusted"]["ranges"][0]["upper"] > 0


def test_presso_ci_uses_actual_retained_instruments(tmp_path):
    result = run_r(tmp_path, '''
    env <- load_functions("skills/mr-presso/scripts/mr_presso/run_mr_presso.R")
    main <- data.frame(Exposure="x",Analysis=c("Raw","Outlier-corrected"),
                       Estimate=.21,Sd=.1,Tstat=2.1,Pvalue=c(2*pt(-2.1,9),2*pt(-2.1,7)))
    raw <- env$estimate_at(main,1L,"raw",10L)
    corrected <- env$estimate_at(main,2L,"outlier_corrected",8L)
    stopifnot(raw$pval>.05,corrected$pval>.05,
              raw$ci$ranges[[1]]$lower<0,corrected$ci$ranges[[1]]$lower<raw$ci$ranges[[1]]$lower)
    result <- list(raw=raw,corrected=corrected)
    ''')
    assert result["corrected"]["ci"]["ranges"][0]["upper"] > result["raw"]["ci"]["ranges"][0]["upper"]


def test_single_snp_forest_preserves_egger_summary_bounds(tmp_path):
    result = run_r(tmp_path, '''
    env <- load_functions("skills/analysis-sensitivity/scripts/mr_sensitivity/run_mr_sensitivity.R")
    d <- data.frame(SNP=c("rs1","rs2","All - MR Egger"),b=c(.1,.2,.21),
                    se=c(.01,.01,.1),lo_ci=c(.08,.18,-.02),up_ci=c(.12,.22,.44))
    plot <- env$single_snp_forest(d)
    row <- plot$data[as.character(plot$data$SNP)=="All - MR Egger",]
    result <- list(lower=row$lo_ci,upper=row$up_ci)
    ''')
    assert result == {"lower": -.02, "upper": .44}


def test_cause_keeps_posterior_interval_without_fabricating_se(tmp_path):
    result = run_r(tmp_path, '''
    env <- load_functions("skills/mr-cause/scripts/cause/run_cause.R")
    summary.audit_cause <- function(object,...) list(p=.42,quants=list(NULL,data.frame(gamma=c(.1,-.01,.5))))
    fit <- structure(list(elpd=data.frame(model1="sharing",model2="causal",delta_elpd=.1,se_delta_elpd=.2)),class="audit_cause")
    result <- env$extract_cause_estimate(fit,.001,10)
    ''')
    assert result["se"] is None
    assert result["beta.hat"] == .1
    assert result["pval"] == .42
    assert result["ci"]["ranges"] == [{"lower": -.01, "upper": .5}]


@pytest.fixture
def mediation():
    path = ROOT / "skills/analysis-mediation/scripts/run_mr_mediation.py"
    spec = importlib.util.spec_from_file_location("mediation_inference_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mediation_preserves_source_intervals_in_record_table_and_plot(tmp_path, monkeypatch, mediation):
    interval = {"level": .9, "ranges": [{"lower": -3., "upper": -2.}, {"lower": 1., "upper": 4.}]}
    source = {"input_scale": "native", "methods": [{"method": "MR-ConMix", "beta.hat": 2., "se": None, "ci": interval}]}
    indexed = mediation._method_index(source)["mr-conmix"]
    row = mediation._path_row(mediator="M", total=indexed, x_to_m=indexed, m_to_y=indexed)
    assert row["x_to_m_ci"] == row["m_to_y_ci"] == row["total_effect_ci"] == interval
    assert row["indirect_se"] is None
    assert row["indirect_ci"]["ranges"] == []
    table = tmp_path / "paths.tsv"
    mediation._write_table([row], table)
    with table.open() as handle:
        saved = next(csv.DictReader(handle, delimiter="\t"))
    assert json.loads(saved["x_to_m_ci"]) == interval
    captured = []
    original = mediation._plot_interval

    def capture(*args, **kwargs):
        captured.append(kwargs["interval"])
        return original(*args, **kwargs)

    def save(figure, plt, path):
        figure.savefig(path, dpi=50)
        plt.close(figure)

    monkeypatch.setattr(mediation, "_plot_interval", capture)
    monkeypatch.setattr(mediation, "_save_publication_figure", save)
    assert mediation._generate_forest_plot([row], tmp_path / "mediation.png") is None
    assert captured[:2] == [interval, interval]
    assert "∪" in mediation._format_estimate(2., interval)


@pytest.mark.parametrize("legacy_se", [None, .130102])
def test_mediation_rejects_cause_even_with_legacy_compatibility_se(tmp_path, mediation, legacy_se):
    source = tmp_path / "cause.json"
    source.write_text(json.dumps({"input_scale": "standardize", "methods": [
        {"method": "CAUSE", "beta.hat": .1, "se": legacy_se,
         "ci": {"level": .95, "ranges": [{"lower": -.01, "upper": .5}]}}
    ]}))
    result = mediation.run({"total_effect_results": [str(source)]})
    assert result["outputs"]["status"] == "blocked"
    assert "CAUSE posterior intervals" in result["summary"]


def test_mediation_derived_delta_p_and_ci_remain_consistent(mediation):
    source = {"input_scale": "native", "methods": [{"method": "IVW", "beta.hat": .3, "se": .1}]}
    indexed = mediation._method_index(source)["ivw"]
    row = mediation._path_row(mediator="M", total=indexed, x_to_m=indexed, m_to_y=indexed)
    assert row["indirect_pval"] == pytest.approx(math.erfc(abs(row["indirect_effect"] / row["indirect_se"]) / math.sqrt(2)))
