args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  stop("expected args: input_json output_json execution_dir")
}

suppressPackageStartupMessages({
  library(data.table)
  library(jsonlite)
  library(cause)
  library(MRAPSS)
})

payload <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
output_json <- args[[2]]
execution_dir <- args[[3]]
log_step <- function(..., .error = FALSE) {
  cat("[mr-cause] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
}

dir.create(file.path(execution_dir, "intermediate"), recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(execution_dir, "reports"), recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(execution_dir, "plots"), recursive = TRUE, showWarnings = FALSE)

script_file <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
script_dir <- if (length(script_file) > 0) {
  dirname(normalizePath(sub("^--file=", "", script_file[[1]]), winslash = "/", mustWork = TRUE))
} else {
  getwd()
}
workspace_dir <- normalizePath(file.path(script_dir, "..", "..", "..", ".."), mustWork = TRUE)
source(file.path(workspace_dir, "mrcat", "tool", "mr", "mr_input_scale.R"))
source(file.path(workspace_dir, "mrcat", "tool", "mr", "gwas_statistics.R"))
source(file.path(workspace_dir, "mrcat", "tool", "mr", "ld_clumping.R"))
input_scale <- mr_input_scale(payload$input_scale)
skill_root <- normalizePath(file.path(script_dir, "..", ".."), winslash = "/", mustWork = TRUE)
plot_explanation_path <- function(plot_id) {
  normalizePath(file.path(skill_root, "plot_explanations", paste0(plot_id, ".md")), winslash = "/", mustWork = TRUE)
}

compact <- function(x) {
  if (is.null(x) || length(x) == 0) return("")
  trimws(paste(as.character(x), collapse = " "))
}

resolve_path <- function(path) {
  text <- compact(path)
  if (!nzchar(text)) return("")
  candidates <- c(text)
  if (!grepl("^/", text)) {
    workspace <- Sys.getenv("MRCAT_WORKSPACE_DIR", unset = "")
    skill_dir <- Sys.getenv("MRCAT_SKILL_DIR", unset = "")
    if (nzchar(workspace)) candidates <- c(candidates, file.path(workspace, text))
    if (nzchar(skill_dir)) candidates <- c(candidates, file.path(skill_dir, text))
  }
  for (candidate in candidates) {
    if (file.exists(candidate) || dir.exists(candidate)) return(normalizePath(candidate, winslash = "/", mustWork = TRUE))
  }
  text
}

resolve_bfile_prefix <- function(path) {
  text <- compact(path)
  if (!nzchar(text)) return("")
  candidates <- c(text)
  if (!grepl("^/", text)) {
    workspace <- Sys.getenv("MRCAT_WORKSPACE_DIR", unset = "")
    skill_dir <- Sys.getenv("MRCAT_SKILL_DIR", unset = "")
    if (nzchar(workspace)) candidates <- c(candidates, file.path(workspace, text))
    if (nzchar(skill_dir)) candidates <- c(candidates, file.path(skill_dir, text))
  }
  for (candidate in candidates) {
    if (file.exists(candidate) || file.exists(paste0(candidate, ".bed"))) {
      return(normalizePath(candidate, winslash = "/", mustWork = FALSE))
    }
  }
  text
}

resolve_clumping_pop <- function(bfile, pop) {
  if (nzchar(bfile)) return("")
  explicit_pop <- toupper(compact(pop))
  supported <- c("EUR", "AFR", "EAS", "SAS", "AMR")
  if (nzchar(explicit_pop) && !(explicit_pop %in% supported)) {
    stop(
      paste0(
        "unsupported OpenGWAS LD-reference population: ",
        explicit_pop
      )
    )
  }
  if (nzchar(explicit_pop)) return(explicit_pop)
  "EUR"
}

num_or_null <- function(x) {
  value <- suppressWarnings(as.numeric(x)[1])
  if (length(value) == 0 || !is.finite(value)) return(NULL)
  value
}

ci_from_bounds <- function(lower, upper, level = 0.95) {
  lower_value <- num_or_null(lower)
  upper_value <- num_or_null(upper)
  ranges <- list()
  if (!is.null(lower_value) && !is.null(upper_value)) {
    if (lower_value > upper_value) {
      swap <- lower_value
      lower_value <- upper_value
      upper_value <- swap
    }
    ranges <- list(list(lower = lower_value, upper = upper_value))
  }
  list(level = level, ranges = ranges)
}

range_for_log <- function(x) {
  values <- suppressWarnings(as.numeric(x))
  values <- values[is.finite(values)]
  if (length(values) == 0) return("NA")
  paste0("[", format(min(values), digits = 6, scientific = TRUE), ", ", format(max(values), digits = 6, scientific = TRUE), "]")
}

save_plot <- function(path, draw, width = 2100, height = 1500, res = 300) {
  grDevices::png(path, width = width, height = height, res = res)
  on.exit(grDevices::dev.off(), add = TRUE)
  draw()
  normalizePath(path, winslash = "/", mustWork = TRUE)
}

save_plot_object <- function(path, plot_obj, width = 2400, height = 1800, res = 300) {
  save_plot(
    path,
    function() {
      if (inherits(plot_obj, "grob") || inherits(plot_obj, "gTree") || inherits(plot_obj, "gtable")) {
        grid::grid.draw(plot_obj)
      } else {
        print(plot_obj)
      }
    },
    width = width,
    height = height,
    res = res
  )
}

build_paper_style_plot <- function(cause_fit, exposure_label, outcome_label,
                                   display_pval_thresh = 5e-6,
                                   genome_wide_pval = 5e-8) {
  dat <- as.data.frame(cause_fit$data)
  dat$pval1 <- 2 * stats::pnorm(-abs(dat$beta_hat_1 / dat$seb1))
  dat$genome_wide <- dat$pval1 < genome_wide_pval
  dat <- dat[
    is.finite(dat$beta_hat_1) &
      is.finite(dat$seb1) &
      is.finite(dat$beta_hat_2) &
      is.finite(dat$seb2) &
      is.finite(dat$delta_elpd) &
      is.finite(dat$pval1) &
      dat$pval1 < display_pval_thresh,
    ,
    drop = FALSE
  ]
  if (nrow(dat) == 0) {
    stop("CAUSE paper-style plot has no variants at the display threshold.")
  }

  max_delta_elpd <- max(abs(dat$delta_elpd))
  if (!is.finite(max_delta_elpd) || max_delta_elpd == 0) max_delta_elpd <- 1

  ivw_dat <- dat[
    dat$genome_wide & is.finite(dat$seb2) & dat$seb2 > 0,
    ,
    drop = FALSE
  ]
  ivw_slope <- NA_real_
  if (nrow(ivw_dat) > 0) {
    weights <- 1 / (ivw_dat$seb2^2)
    denominator <- sum(weights * ivw_dat$beta_hat_1^2)
    if (is.finite(denominator) && denominator > 0) {
      ivw_slope <- sum(weights * ivw_dat$beta_hat_1 * ivw_dat$beta_hat_2) / denominator
    }
  }

  plot_obj <- ggplot2::ggplot(
    dat,
    ggplot2::aes(x = beta_hat_1, y = beta_hat_2)
  ) +
    ggplot2::geom_vline(xintercept = 0, linewidth = 0.35) +
    ggplot2::geom_hline(yintercept = 0, linewidth = 0.35) +
    ggplot2::geom_segment(
      ggplot2::aes(
        x = beta_hat_1 - 1.96 * seb1,
        xend = beta_hat_1 + 1.96 * seb1,
        y = beta_hat_2,
        yend = beta_hat_2
      ),
      color = "grey78",
      linewidth = 0.35
    ) +
    ggplot2::geom_segment(
      ggplot2::aes(
        x = beta_hat_1,
        xend = beta_hat_1,
        y = beta_hat_2 - 1.96 * seb2,
        yend = beta_hat_2 + 1.96 * seb2
      ),
      color = "grey78",
      linewidth = 0.35
    ) +
    ggplot2::geom_point(
      ggplot2::aes(
        color = delta_elpd,
        size = -log10(pval1),
        shape = genome_wide
      ),
      alpha = 0.95
    ) +
    ggplot2::scale_shape_manual(
      values = c("FALSE" = 16, "TRUE" = 17),
      guide = "none"
    ) +
    ggplot2::scale_color_gradient2(
      low = "#62C900",
      mid = "grey74",
      high = "#9C27D8",
      midpoint = 0,
      limits = c(-max_delta_elpd, max_delta_elpd),
      name = "Contribution\nto test statistic"
    ) +
    ggplot2::scale_size_continuous(
      name = paste0("-log10(", exposure_label, " P value)")
    ) +
    ggplot2::labs(
      title = paste0(exposure_label, " and ", outcome_label, " Effect Sizes"),
      x = paste0("Association with ", exposure_label),
      y = paste0("Association with ", outcome_label)
    ) +
    ggplot2::theme_bw(base_size = 11)

  if (is.finite(ivw_slope)) {
    plot_obj <- plot_obj + ggplot2::geom_abline(
      slope = ivw_slope,
      intercept = 0,
      linetype = "dashed",
      linewidth = 0.45
    )
  }
  plot_obj
}

write_blocked <- function(summary, failure_class, nsnp = NULL, min_instruments = NULL) {
  log_step("Blocked: failure_class=", failure_class, "; summary=", summary, .error = TRUE)
  outputs <- list(status = "blocked", failure_class = failure_class)
  details <- list(failure_class = failure_class)
  if (!is.null(nsnp)) {
    outputs$nsnp <- as.integer(nsnp)
    details$nsnp <- as.integer(nsnp)
  }
  if (!is.null(min_instruments)) {
    outputs$min_instruments <- as.integer(min_instruments)
    details$min_instruments <- as.integer(min_instruments)
  }
  rendered <- list(summary = summary, outputs = outputs, details = details, artifacts = list())
  jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
  quit(save = "no", status = 0)
}

read_canonical <- function(path, side) {
  required <- c(
    "SNP", "effect_allele", "other_allele",
    "beta", "or", "se", "z", "pval", "neglog10_pval", "n"
  )
  available <- names(data.table::fread(path, nrows = 0, showProgress = FALSE))
  missing <- setdiff(required, available)
  if (length(missing) > 0) {
    stop(paste(side, "canonical table missing columns:", paste(missing, collapse = ", ")))
  }
  optional <- intersect(c("n_cases", "n_controls"), available)
  dt <- data.table::fread(path, select = c(required, optional))
  mr_canonical_effects(dt, input_scale, payload[[paste0(side, "_sample_size")]])
}

format_for_cause <- function(dt) {
  format_args <- list(
    X = dt,
    snp = "SNP",
    beta_hat = "beta",
    se = "se",
    A1 = "effect_allele",
    A2 = "other_allele",
    p_value = "pval",
    compute_pval = TRUE
  )
  if ("n" %in% names(dt) && any(is.finite(dt$n))) {
    format_args$sample_size <- "n"
  }
  do.call(cause::gwas_format, format_args)
}

extract_cause_estimate <- function(cause_fit, threshold, nsnp) {
  elpd <- as.data.frame(cause_fit$elpd)
  if (nrow(elpd) > 0 && all(c("model1", "model2") %in% names(elpd))) {
    elpd <- unique(elpd[elpd$model1 == "sharing" & elpd$model2 == "causal", , drop = FALSE])
  }
  delta_elpd <- if ("delta_elpd" %in% names(elpd)) num_or_null(elpd$delta_elpd[1]) else NULL
  delta_elpd_se <- if ("se_delta_elpd" %in% names(elpd)) num_or_null(elpd$se_delta_elpd[1]) else NULL

  cause_summary <- summary(cause_fit, ci_size = 0.95)
  pval <- num_or_null(cause_summary$p[1])
  if (is.null(pval) || pval < 0 || pval > 1) {
    stop("CAUSE summary returned an invalid causal-versus-sharing model comparison p-value.")
  }

  quants <- cause_summary$quants
  if (!is.list(quants) || length(quants) < 2) {
    stop("CAUSE summary is missing causal posterior quantiles.")
  }
  causal_quants <- as.data.frame(quants[[2]])
  if (nrow(causal_quants) < 3 || !"gamma" %in% names(causal_quants)) {
    stop("CAUSE causal posterior summary is missing gamma quantiles.")
  }
  beta_hat <- num_or_null(causal_quants[1, "gamma"])
  lower <- num_or_null(causal_quants[2, "gamma"])
  upper <- num_or_null(causal_quants[3, "gamma"])
  if (is.null(beta_hat) || is.null(lower) || is.null(upper)) {
    stop("CAUSE causal posterior summary returned non-finite gamma estimates.")
  }
  bounds <- sort(c(lower, upper))
  lower <- bounds[[1]]
  upper <- bounds[[2]]
  se <- (upper - lower) / (2 * 1.96)
  if (!is.finite(se) || se <= 0) {
    stop("CAUSE causal posterior credible interval produced an invalid compatibility standard error.")
  }
  if (is.null(delta_elpd) || is.null(delta_elpd_se) || delta_elpd_se <= 0) {
    stop("CAUSE ELPD comparison returned invalid delta_elpd or se_delta_elpd values.")
  }

  list(
    method = "CAUSE",
    Threshold = threshold,
    nsnp = as.integer(nsnp),
    "beta.hat" = beta_hat,
    se = num_or_null(se),
    pval = pval,
    ci = ci_from_bounds(lower, upper),
    delta_elpd = delta_elpd,
    delta_elpd_se = delta_elpd_se
  )
}

pval_thresh <- suppressWarnings(as.numeric(payload$pval_thresh)[1])
if (length(pval_thresh) == 0 || !is.finite(pval_thresh)) pval_thresh <- 0.001
r2_thresh <- suppressWarnings(as.numeric(payload$r2_thresh)[1])
if (length(r2_thresh) == 0 || !is.finite(r2_thresh)) r2_thresh <- 0.01
clump_kb <- suppressWarnings(as.integer(payload$clump_kb)[1])
if (length(clump_kb) == 0 || !is.finite(clump_kb)) clump_kb <- 10000L
param_variant_sample_size <- suppressWarnings(as.integer(payload$param_variant_sample_size)[1])
if (length(param_variant_sample_size) == 0 || !is.finite(param_variant_sample_size)) param_variant_sample_size <- 1000000L
seed <- suppressWarnings(as.integer(payload$seed)[1])
if (length(seed) == 0 || !is.finite(seed)) seed <- 1L
if (seed < 0L) stop("seed must be a non-negative integer.")

log_step("Reading canonical exposure: ", payload$canonical_exposure_path)
exposure_read <- read_canonical(payload$canonical_exposure_path, "exposure")
exposure_canonical <- exposure_read$data
exposure_effect_diagnostics <- exposure_read$diagnostics
exposure_canonical_rows <- exposure_effect_diagnostics$canonical_rows
log_step(
  "Loaded canonical exposure: rows=", exposure_canonical_rows,
  "; usable rows=", exposure_effect_diagnostics$usable_rows,
  "; native beta/se rows=", exposure_effect_diagnostics$native_beta_se_rows,
  "; OR-derived beta rows=", exposure_effect_diagnostics$or_derived_beta_rows,
  "; z/n-derived beta/se rows=", exposure_effect_diagnostics$z_n_derived_beta_se_rows,
  "; -log10(p)-derived p-value rows=", exposure_effect_diagnostics$neglog10_derived_pval_rows,
  "; excluded rows=", exposure_effect_diagnostics$excluded_rows, "."
)
if (nrow(exposure_canonical) < 1) {
  write_blocked(
    "mr-cause blocked: exposure canonical study has no rows with usable identity, significance, and beta/se, OR/se, effect statistics in the requested input_scale.",
    "missing_effect_statistics"
  )
}
log_step("Formatting exposure with cause::gwas_format.")
exposure <- format_for_cause(exposure_canonical)
rm(exposure_canonical)
gc()
log_step("CAUSE-formatted exposure rows=", nrow(exposure), ".")

log_step("Reading canonical outcome: ", payload$canonical_outcome_path)
outcome_read <- read_canonical(payload$canonical_outcome_path, "outcome")
outcome_canonical <- outcome_read$data
outcome_effect_diagnostics <- outcome_read$diagnostics
outcome_canonical_rows <- outcome_effect_diagnostics$canonical_rows
log_step(
  "Loaded canonical outcome: rows=", outcome_canonical_rows,
  "; usable rows=", outcome_effect_diagnostics$usable_rows,
  "; native beta/se rows=", outcome_effect_diagnostics$native_beta_se_rows,
  "; OR-derived beta rows=", outcome_effect_diagnostics$or_derived_beta_rows,
  "; z/n-derived beta/se rows=", outcome_effect_diagnostics$z_n_derived_beta_se_rows,
  "; -log10(p)-derived p-value rows=", outcome_effect_diagnostics$neglog10_derived_pval_rows,
  "; excluded rows=", outcome_effect_diagnostics$excluded_rows, "."
)
if (nrow(outcome_canonical) < 1) {
  write_blocked(
    "mr-cause blocked: outcome canonical study has no rows with usable identity, significance, and beta/se, OR/se, effect statistics in the requested input_scale.",
    "missing_effect_statistics"
  )
}
log_step("Formatting outcome with cause::gwas_format.")
outcome <- format_for_cause(outcome_canonical)
rm(outcome_canonical)
gc()
log_step("CAUSE-formatted outcome rows=", nrow(outcome), ".")

log_step("Merging exposure and outcome GWAS with cause::gwas_merge.")
merged <- cause::gwas_merge(
  exposure,
  outcome,
  X1_formatted = TRUE,
  X2_formatted = TRUE
)
log_step("Completed GWAS merge: rows=", nrow(merged), ".")
merged_path <- file.path(execution_dir, "intermediate", "cause_merged.tsv.gz")
data.table::fwrite(merged, merged_path, sep = "\t", na = "NA", compress = "gzip")
log_step("CAUSE merged GWAS summary: exposure_b_range=", range_for_log(merged$beta_hat_1), "; outcome_b_range=", range_for_log(merged$beta_hat_2), "; exposure_se_range=", range_for_log(merged$seb1), "; outcome_se_range=", range_for_log(merged$seb2), ".")

clump_input <- data.table::as.data.table(merged)
clump_input[, pval.exp := if ("p1" %in% names(clump_input)) {
  as.numeric(p1)
} else {
  2 * stats::pnorm(-abs(beta_hat_1 / seb1))
}]

bfile <- resolve_bfile_prefix(payload$bfile)
plink_bin <- resolve_path(payload$plink_bin)
clump_mode <- if (nzchar(bfile)) "local_plink" else "api"
pop <- resolve_clumping_pop(bfile, payload$pop)
clump_args <- list(
  dat = clump_input,
  IV.Threshold = pval_thresh,
  SNP_col = "snp",
  pval_col = "pval.exp",
  clump_kb = clump_kb,
  clump_r2 = r2_thresh
)
if (identical(clump_mode, "local_plink")) {
  clump_args$bfile <- bfile
  if (nzchar(plink_bin)) clump_args$plink_bin <- plink_bin
} else {
  clump_args$pop <- pop
}
log_step(
  "Clumping instruments: clump_mode=", clump_mode,
  "; pval_thresh=", pval_thresh,
  "; r2_thresh=", r2_thresh,
  "; clump_kb=", clump_kb,
  "; pop=", ifelse(nzchar(pop) && identical(clump_mode, "api"), pop, "null"),
  "; bfile=", ifelse(nzchar(bfile), bfile, "null"),
  "; plink_bin=", ifelse(nzchar(bfile) && nzchar(plink_bin), plink_bin, "null"),
  "."
)
clump_result <- mrcat_clump(clump_args, payload$api_clumping_fallback,
    record_path = file.path(execution_dir, "reports", "ld_clumping_reference.json"))
clumped <- clump_result$data
clumping_reference <- clump_result$reference
clump_mode <- clumping_reference$mode
if (identical(clump_mode, "local_plink")) {
  bfile <- clumping_reference$bfile
  plink_bin <- clumping_reference$plink_bin
}
log_step(mrcat_ld_reference_summary(clumping_reference))
log_step("Completed clumping: retained rows=", nrow(clumped), ".")
log_step("CAUSE clumped summary: pval.exp_range=", range_for_log(clumped$pval.exp), "; b.exp_range=", range_for_log(clumped$beta_hat_1), "; b.out_range=", range_for_log(clumped$beta_hat_2), ".")

clumped_path <- file.path(execution_dir, "intermediate", "cause_clumped.tsv.gz")
log_step("Writing clumped variants: ", clumped_path)
data.table::fwrite(clumped, clumped_path, sep = "\t", quote = FALSE, na = "NA", compress = "gzip")

top_vars <- intersect(
  as.character(merged$snp),
  as.character(as.data.table(clumped)[pval.exp <= pval_thresh]$snp)
)
nsnp <- length(top_vars)
log_step("Selected CAUSE top variants: rows=", nsnp, ".")
if (nsnp < 1) {
  write_blocked("mr-cause blocked: no clumped variants passed pval_thresh.", "insufficient_instruments", nsnp = nsnp, min_instruments = 1)
}

set.seed(seed)
varlist <- sample(as.character(merged$snp), size = min(nrow(merged), param_variant_sample_size), replace = FALSE)
log_step("Estimating CAUSE parameters: sampled variants=", length(varlist), ".")
params <- cause::est_cause_params(merged, varlist)
params_path <- file.path(execution_dir, "intermediate", "cause_params.rds")
saveRDS(list(input_scale = input_scale, variants = varlist, params = params), params_path)
log_step("Estimated CAUSE parameters object: class=", paste(class(params), collapse = ","), "; fields=", paste(names(params), collapse = ","), ".")
params_converged <- isTRUE(params$converged)
force_nonconverged_params <- !params_converged
if (force_nonconverged_params) {
  log_step(
    "CAUSE parameter estimates did not converge; continuing with force=TRUE as in the MRbenchmarking CAUSE protocol. ",
    "The result must be interpreted with this numerical-fit warning."
  )
}
log_step("Fitting method: CAUSE; force=", force_nonconverged_params, ".")
cause_fit <- cause::cause(
  X = merged,
  variants = top_vars,
  param_ests = params,
  pval_thresh = pval_thresh,
  force = force_nonconverged_params
)
row <- extract_cause_estimate(cause_fit, pval_thresh, nsnp)
log_step("Completed method: CAUSE; beta=", row[["beta.hat"]], "; se=", row$se, "; pval=", row$pval, "; delta_elpd=", row$delta_elpd, "; delta_elpd_se=", row$delta_elpd_se, ".")
log_step("CAUSE result JSON: ", jsonlite::toJSON(row, auto_unbox = TRUE, null = "null", digits = NA))

official_data_plots <- plot(
  cause_fit,
  type = "data",
  intern = TRUE,
  pval_thresh = 5e-6
)
if (!is.list(official_data_plots) || length(official_data_plots) < 3) {
  stop("CAUSE plot.cause did not return the expected three data diagnostic panels.")
}

exposure_label <- compact(payload$exposure_label)
if (!nzchar(exposure_label)) exposure_label <- "Exposure"
outcome_label <- compact(payload$outcome_label)
if (!nzchar(outcome_label)) outcome_label <- "Outcome"

sharing_diagnostic_path <- save_plot_object(
  file.path(execution_dir, "plots", "cause_data_diagnostics_sharing.png"),
  official_data_plots[[1]],
  width = 2400,
  height = 1800
)
causal_diagnostic_path <- save_plot_object(
  file.path(execution_dir, "plots", "cause_data_diagnostics_causal.png"),
  official_data_plots[[2]],
  width = 2400,
  height = 1800
)
elpd_diagnostic_path <- save_plot_object(
  file.path(execution_dir, "plots", "cause_data_diagnostics_elpd.png"),
  official_data_plots[[3]],
  width = 2400,
  height = 1800
)
paper_style_plot <- build_paper_style_plot(
  cause_fit,
  exposure_label = exposure_label,
  outcome_label = outcome_label
)
paper_style_plot_path <- save_plot_object(
  file.path(execution_dir, "plots", "cause_paper_style.png"),
  paper_style_plot,
  width = 2400,
  height = 1800
)

plot_refs <- list(
  list(
    plot_id = "cause_data_diagnostics_sharing",
    path = sharing_diagnostic_path,
    title = "CAUSE sharing-model diagnostic",
    source = "cause_result",
    explanation_path = plot_explanation_path("cause_data_diagnostics_sharing")
  ),
  list(
    plot_id = "cause_data_diagnostics_causal",
    path = causal_diagnostic_path,
    title = "CAUSE causal-model diagnostic",
    source = "cause_result",
    explanation_path = plot_explanation_path("cause_data_diagnostics_causal")
  ),
  list(
    plot_id = "cause_data_diagnostics_elpd",
    path = elpd_diagnostic_path,
    title = "CAUSE ELPD contribution diagnostic",
    source = "cause_result",
    explanation_path = plot_explanation_path("cause_data_diagnostics_elpd")
  ),
  list(
    plot_id = "cause_paper_style",
    path = paper_style_plot_path,
    title = "CAUSE paper-style variant evidence",
    source = "cause_result",
    explanation_path = plot_explanation_path("cause_paper_style")
  )
)

summary_text <- paste0(
  "Parameters used: pval_thresh=", pval_thresh,
  ", r2_thresh=", r2_thresh,
  ", clump_kb=", clump_kb,
  ", param_variant_sample_size=", param_variant_sample_size,
  ", clump_mode=", clump_mode,
  ", pop=", ifelse(nzchar(pop) && identical(clump_mode, "api"), pop, "null"),
  ", bfile=", ifelse(nzchar(bfile), bfile, "null"),
  ", plink_bin=", ifelse(nzchar(bfile) && nzchar(plink_bin), plink_bin, "null"),
  ", seed=", seed,
  ", parameter_estimates_converged=", params_converged,
  ", force=", force_nonconverged_params, ". ",
  "canonical/CAUSE-formatted counts: canonical exposure rows=", exposure_canonical_rows,
  ", canonical outcome rows=", outcome_canonical_rows,
  ", exposure native beta/se rows=", exposure_effect_diagnostics$native_beta_se_rows,
  ", exposure OR-derived beta rows=", exposure_effect_diagnostics$or_derived_beta_rows,
  ", exposure z/n-derived beta/se rows=", exposure_effect_diagnostics$z_n_derived_beta_se_rows,
  ", exposure -log10(p)-derived p-value rows=", exposure_effect_diagnostics$neglog10_derived_pval_rows,
  ", exposure excluded rows=", exposure_effect_diagnostics$excluded_rows,
  ", outcome native beta/se rows=", outcome_effect_diagnostics$native_beta_se_rows,
  ", outcome OR-derived beta rows=", outcome_effect_diagnostics$or_derived_beta_rows,
  ", outcome z/n-derived beta/se rows=", outcome_effect_diagnostics$z_n_derived_beta_se_rows,
  ", outcome -log10(p)-derived p-value rows=", outcome_effect_diagnostics$neglog10_derived_pval_rows,
  ", outcome excluded rows=", outcome_effect_diagnostics$excluded_rows,
  ", CAUSE-formatted exposure rows=", nrow(exposure),
  ", CAUSE-formatted outcome rows=", nrow(outcome), "; ",
  "estimated MR-APSS parameters: not required for CAUSE branch; ",
  "LD clumping count: cause_clumped_rows=", nrow(clumped), "; ",
  "filtered instruments: nsnp=", nsnp, " at p<=", pval_thresh, "; ",
  "fitted method: CAUSE beta=", row[["beta.hat"]],
  ", 95% credible interval=[", row$ci$ranges[[1]]$lower, ", ", row$ci$ranges[[1]]$upper, "]",
  ", model-comparison pval=", row$pval,
  ", delta_elpd=", row$delta_elpd,
  ", se_delta_elpd=", row$delta_elpd_se, "; ",
  "artifacts/plots: result_record=1, clumped_table=1, plots=", length(plot_refs), "."
)

record_path <- file.path(execution_dir, "reports", "cause_result_record.json")
log_step("Writing result record: ", record_path)
result <- list(
  method = "cause",
  input_scale = input_scale,
  nuisance_params_path = normalizePath(params_path, winslash = "/", mustWork = TRUE),
  prepared_gwas_path = normalizePath(merged_path, winslash = "/", mustWork = TRUE),
  exposure_sample_size_source = exposure_effect_diagnostics$sample_size_source,
  outcome_sample_size_source = outcome_effect_diagnostics$sample_size_source,
  methods = list(row),
  diagnostics = list(
    clumping_reference = clumping_reference,
    canonical_exposure_rows = exposure_canonical_rows,
    canonical_outcome_rows = outcome_canonical_rows,
    exposure_native_beta_se_rows = exposure_effect_diagnostics$native_beta_se_rows,
    exposure_or_derived_beta_rows = exposure_effect_diagnostics$or_derived_beta_rows,
    exposure_z_n_derived_beta_se_rows = exposure_effect_diagnostics$z_n_derived_beta_se_rows,
    exposure_neglog10_derived_pval_rows = exposure_effect_diagnostics$neglog10_derived_pval_rows,
    exposure_excluded_rows = exposure_effect_diagnostics$excluded_rows,
    outcome_native_beta_se_rows = outcome_effect_diagnostics$native_beta_se_rows,
    outcome_or_derived_beta_rows = outcome_effect_diagnostics$or_derived_beta_rows,
    outcome_z_n_derived_beta_se_rows = outcome_effect_diagnostics$z_n_derived_beta_se_rows,
    outcome_neglog10_derived_pval_rows = outcome_effect_diagnostics$neglog10_derived_pval_rows,
    outcome_excluded_rows = outcome_effect_diagnostics$excluded_rows,
    cause_formatted_exposure_rows = nrow(exposure),
    cause_formatted_outcome_rows = nrow(outcome),
    merged_rows = nrow(merged),
    clumped_rows = nrow(clumped),
    nsnp = nsnp,
    pval_thresh = pval_thresh,
    r2_thresh = r2_thresh,
    clump_kb = clump_kb,
    param_variant_sample_size = param_variant_sample_size,
    seed = seed,
    parameter_estimates_converged = params_converged,
    force_nonconverged_params = force_nonconverged_params,
    clump_mode = clump_mode,
    pop = if (nzchar(pop) && identical(clump_mode, "api")) pop else NULL,
    bfile = if (nzchar(bfile)) bfile else NULL,
    plink_bin = if (nzchar(bfile) && nzchar(plink_bin)) plink_bin else NULL,
    clumped_path = normalizePath(clumped_path, winslash = "/", mustWork = FALSE)
  ),
  interpretation = list(
    summary = summary_text,
    recommendations = if (force_nonconverged_params) {
      list(
        "CAUSE nuisance-parameter estimation did not converge; the fit was continued with force=TRUE, matching the MRbenchmarking protocol. Treat this result as numerically unstable and verify it in sensitivity analyses."
      )
    } else {
      list()
    }
  ),
  plot_manifest = list(plots = plot_refs),
  result_record_path = normalizePath(record_path, winslash = "/", mustWork = FALSE)
)
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)

outputs <- list(status = "ok")
outputs$cause_result <- result
rendered <- list(
  summary = summary_text,
  outputs = outputs,
  details = list(result_status = "ok", failure_class = NULL,
                 reference_usage = mrcat_ld_reference_summary(clumping_reference)),
  artifacts = list(
    list(path = result$result_record_path, kind = "json", summary = "CAUSE result record"),
    list(path = result$prepared_gwas_path, kind = "tsv", summary = "CAUSE merged GWAS in the fitted input scale"),
    list(path = result$nuisance_params_path, kind = "rds", summary = "CAUSE nuisance parameters, scale, and sampled variants"),
    list(path = normalizePath(clumped_path, winslash = "/", mustWork = FALSE), kind = "tsv", summary = "CAUSE clumped variants")
  )
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
log_step("Completed successfully.")
