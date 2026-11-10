args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  stop("expected args: input_json output_json execution_dir")
}

suppressPackageStartupMessages({
  library(data.table)
  library(jsonlite)
})

payload <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
if ("pvalue_threshold" %in% names(payload)) {
  stop("mr-apss fits prepared instruments without reselection. Set iv_threshold in gwas-pair-prepare and pass its matching MRdat/C/Omega.")
}
output_json <- args[[2]]
execution_dir <- args[[3]]
log_step <- function(..., .error = FALSE) {
  cat("[mr-apss] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
}

dir.create(file.path(execution_dir, "reports"), recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(execution_dir, "plots"), recursive = TRUE, showWarnings = FALSE)

script_file <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
script_dir <- if (length(script_file) > 0) {
  dirname(normalizePath(sub("^--file=", "", script_file[[1]]), winslash = "/", mustWork = TRUE))
} else {
  getwd()
}
workspace_dir <- normalizePath(file.path(script_dir, "..", "..", "..", ".."), mustWork = TRUE)
skill_root <- normalizePath(file.path(script_dir, "..", ".."), winslash = "/", mustWork = TRUE)
source(file.path(workspace_dir, "mrcat", "tool", "MRTool", "mr_input_scale.R"))
plot_explanation_path <- function(plot_id) {
  normalizePath(file.path(skill_root, "plot_explanations", paste0(plot_id, ".md")), winslash = "/", mustWork = TRUE)
}

compact <- function(x) {
  if (is.null(x) || length(x) == 0) return("")
  trimws(paste(as.character(x), collapse = " "))
}

label_or <- function(x, default) {
  text <- compact(x)
  if (nzchar(text)) return(text)
  default
}

num_or_null <- function(x) {
  value <- suppressWarnings(as.numeric(x)[1])
  if (length(value) == 0 || !is.finite(value)) return(NULL)
  value
}

ci_from_se <- function(beta, se) {
  beta_value <- num_or_null(beta)
  se_value <- num_or_null(se)
  ranges <- list()
  if (!is.null(beta_value) && !is.null(se_value) && se_value > 0) {
    ranges <- list(list(
      lower = beta_value - 1.96 * se_value,
      upper = beta_value + 1.96 * se_value
    ))
  }
  list(level = 0.95, ranges = ranges)
}

fmt_num <- function(x) {
  value <- num_or_null(x)
  if (is.null(value)) return("NA")
  format(value, digits = 6, scientific = TRUE, trim = TRUE)
}

format_matrix_for_log <- function(x) {
  if (is.null(x)) return("null")
  mat <- matrix(as.numeric(x), nrow = 2, ncol = 2)
  rows <- apply(mat, 1, function(row) paste(format(row, digits = 16, scientific = TRUE), collapse = ", "))
  paste0("[[", rows[[1]], "], [", rows[[2]], "]]")
}

range_for_log <- function(x) {
  values <- suppressWarnings(as.numeric(x))
  values <- values[is.finite(values)]
  if (length(values) == 0) return("NA")
  paste0("[", format(min(values), digits = 6, scientific = TRUE), ", ", format(max(values), digits = 6, scientific = TRUE), "]")
}

read_matrix2 <- function(path, default) {
  text <- compact(path)
  if (!nzchar(text) || !file.exists(text)) return(default)
  values <- suppressWarnings(as.numeric(unlist(data.table::fread(text, header = FALSE))))
  values <- values[is.finite(values)]
  if (length(values) < 4) return(default)
  matrix(values[1:4], nrow = 2, ncol = 2)
}

method_row <- function(method, threshold, nsnp, beta, se, pval, extra = list()) {
  c(
    list(
      method = method,
      Threshold = threshold,
      nsnp = as.integer(nsnp),
      "beta.hat" = num_or_null(beta),
      se = num_or_null(se),
      pval = num_or_null(pval),
      ci = ci_from_se(beta, se)
    ),
    extra
  )
}

write_blocked <- function(nsnp, min_instruments, threshold) {
  log_step("Blocked: prepared instruments=", nsnp, "; minimum required=", min_instruments, "; MRdat_selection_bias_threshold=", threshold, ".", .error = TRUE)
  rendered <- list(
    summary = paste0("mr-apss blocked: prepared MRdat instruments=", nsnp, " below min_instruments=", min_instruments, "."),
    outputs = list(
      status = "blocked",
      failure_class = "insufficient_instruments",
      nsnp = as.integer(nsnp),
      min_instruments = as.integer(min_instruments),
      Threshold = threshold
    ),
    details = list(
      failure_class = "insufficient_instruments",
      nsnp = as.integer(nsnp),
      min_instruments = as.integer(min_instruments)
    ),
    artifacts = list()
  )
  jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
  quit(save = "no", status = 0)
}

log_step("Reading upstream harmonized and clumped MRdat: ", payload$mrdat_path)
mrdat <- data.table::fread(payload$mrdat_path)
input_scale <- mr_input_scale(payload$input_scale, allowed = c("standardize"))
mrdat <- mr_apply_input_scale(mrdat, input_scale, payload$exposure_type, payload$outcome_type)
scale_excluded_rows <- attr(mrdat, "scale_excluded_rows")
log_step("Loaded upstream MRdat: rows=", nrow(mrdat), ".")
required <- c("b.exp", "b.out", "se.exp", "se.out", "pval.exp", "Threshold")
missing <- setdiff(required, names(mrdat))
if (length(missing) > 0) {
  stop(paste("MRdat missing columns:", paste(missing, collapse = ", ")))
}

numeric_columns <- c("b.exp", "b.out", "se.exp", "se.out", "pval.exp", "Threshold")
mrdat[, (numeric_columns) := lapply(.SD, function(x) suppressWarnings(as.numeric(x))), .SDcols = numeric_columns]

log_step("Reading LDSC matrices: C=", payload$c_path, "; Omega=", payload$omega_path, ".")
C_matrix <- read_matrix2(payload$c_path, diag(2))
Omega_matrix <- read_matrix2(payload$omega_path, matrix(0, 2, 2))
log_step("Loaded Estimated Background Parameters: C=", format_matrix_for_log(C_matrix), "; Omega=", format_matrix_for_log(Omega_matrix), ".")
min_instruments <- 4L
exposure_label <- label_or(payload$exposure_label, "exposure")
outcome_label <- label_or(payload$outcome_label, "outcome")
if (nrow(mrdat) == 0) {
  write_blocked(0L, min_instruments, NULL)
}
correction_threshold <- unique(mrdat$Threshold)
if (length(correction_threshold) != 1L || !is.finite(correction_threshold) ||
    correction_threshold <= 0 || correction_threshold > 1) {
  stop("Prepared MRdat must contain one finite Threshold in (0, 1] on every row. Regenerate gwas-pair-prepare; do not replace it with the nominal IV threshold.")
}
valid_rows <- is.finite(mrdat$b.exp) & is.finite(mrdat$b.out) &
  is.finite(mrdat$se.exp) & mrdat$se.exp > 0 &
  is.finite(mrdat$se.out) & mrdat$se.out > 0 &
  is.finite(mrdat$pval.exp) & mrdat$pval.exp >= 0 & mrdat$pval.exp <= 1
if (!all(valid_rows)) {
  stop("Prepared MRdat contains invalid effect statistics or P values. Regenerate gwas-pair-prepare instead of silently changing the prepared instrument set.")
}
selected <- mrdat
log_step("Prepared fit input: rows=", nrow(selected), "; MRdat_selection_bias_threshold=", correction_threshold, "; reused upstream instruments without reselection; minimum required=", min_instruments, ".")
log_step("MR-APSS fit input summary: pval.exp_range=", range_for_log(selected$pval.exp), "; b.exp_range=", range_for_log(selected$b.exp), "; b.out_range=", range_for_log(selected$b.out), "; se.exp_range=", range_for_log(selected$se.exp), "; se.out_range=", range_for_log(selected$se.out), ".")

if (nrow(selected) < min_instruments) {
  write_blocked(nrow(selected), min_instruments, correction_threshold)
}

log_step("Loading R package: MRAPSS.")
suppressPackageStartupMessages(library(MRAPSS))
log_step("Fitting method: MR-APSS; exposure=", exposure_label, "; outcome=", outcome_label, ".")
fit <- try(
  MRAPSS::MRAPSS(
    as.data.frame(selected),
    exposure = exposure_label,
    outcome = outcome_label,
    C = C_matrix,
    Omega = Omega_matrix,
    Cor.SelectionBias = TRUE
  ),
  silent = TRUE
)
if (inherits(fit, "try-error") || is.null(fit)) {
  stop(paste("MRAPSS::MRAPSS failed:", compact(fit)))
}
log_step("Completed method: MR-APSS; beta=", fit$beta, "; se=", fit$beta.se, "; pval=", fit$pvalue, "; fitted instruments=", nrow(fit$MRdat), ".")
log_step("MR-APSS fitted parameters: pi0=", fit$pi0, "; nvalid=", nrow(fit$MRdat) * fit$pi0, "; sigma.sq=", fit$sigma.sq, "; tau.sq=", fit$tau.sq, "; IVstrength=", fit$IVsignal.sum, ".")

plot_path <- file.path(execution_dir, "plots", "mrapss_mrplot.png")
log_step("Rendering MR-APSS plot: ", plot_path)
mrplot <- MRAPSS::MRplot(fit, exposure = exposure_label, outcome = outcome_label)
source(file.path(script_dir, "export_mrapss_plot.R"))
plot_data_path <- export_mrapss_plot(mrplot, fit, plot_path)
plot_path_norm <- normalizePath(plot_path, winslash = "/", mustWork = FALSE)

row <- method_row(
  "MR-APSS",
  correction_threshold,
  nrow(fit$MRdat),
  fit$beta,
  fit$beta.se,
  fit$pvalue,
  list(
    pi0 = num_or_null(fit$pi0),
    nvalid = num_or_null(nrow(fit$MRdat) * fit$pi0),
    sigma.sq = num_or_null(fit$sigma.sq),
    tau.sq = num_or_null(fit$tau.sq),
    IVstrength = num_or_null(fit$IVsignal.sum),
    threshold_source = "upstream MRdat$Threshold from gwas-pair-prepare"
  )
)
rows <- list(row)
log_step("MR-APSS result JSON: ", jsonlite::toJSON(row, auto_unbox = TRUE, null = "null", digits = NA))

summary_text <- paste0(
  "Parameters used: MRdat_selection_bias_threshold=", fmt_num(correction_threshold),
  ", Cor.SelectionBias=TRUE, min_instruments=", min_instruments, ". ",
  "canonicalized/formatted counts: completed upstream and reused; ",
  "estimated MR-APSS parameters: reused C/Omega from gwas-pair-prepare; ",
  "input MRdat: already constructed and LD-clumped upstream, rows=", nrow(mrdat), "; ",
  "fit input instruments=", nrow(selected), "; ",
  "MR-APSS selection-bias correction threshold=", fmt_num(correction_threshold), "; ",
  "fitted method: MR-APSS beta=", fmt_num(fit$beta),
  ", se=", fmt_num(fit$beta.se),
  ", pval=", fmt_num(fit$pvalue),
  ", nsnp=", nrow(fit$MRdat),
  ", nvalid=", fmt_num(nrow(fit$MRdat) * fit$pi0),
  ", pi0=", fmt_num(fit$pi0),
  ", sigma.sq=", fmt_num(fit$sigma.sq),
  ", tau.sq=", fmt_num(fit$tau.sq),
  ", IVstrength=", fmt_num(fit$IVsignal.sum),
  "; artifacts/plots: result_record=1, mrapss_mrplot=1."
)

record_path <- file.path(execution_dir, "reports", "mrapss_result_record.json")
log_step("Writing result record: ", record_path)
plot_ref <- list(
  plot_id = "mrapss_mrplot",
  path = plot_path_norm,
  title = "MR-APSS Result Plot",
  source = "mrapss_result",
  explanation_path = plot_explanation_path("mrapss_mrplot")
)
selected_path <- mr_save_selected_input(selected, execution_dir)
result <- list(
  input_scale = input_scale,
  scale_excluded_rows = scale_excluded_rows,
  selected_mrdat_path = selected_path,
  method = "mrapss",
  methods = rows,
  diagnostics = list(
    mrdat_rows = nrow(mrdat),
    fit_input_rows = nrow(selected),
    selection_bias_threshold = correction_threshold,
    threshold_source = "upstream MRdat$Threshold from gwas-pair-prepare",
    exposure_label = exposure_label,
    outcome_label = outcome_label,
    c_path = normalizePath(payload$c_path, winslash = "/", mustWork = FALSE),
    omega_path = normalizePath(payload$omega_path, winslash = "/", mustWork = FALSE),
    result_plot_path = plot_path_norm
  ),
  interpretation = list(
    summary = summary_text,
    recommendations = list()
  ),
  plot_manifest = list(
    plots = list(plot_ref),
    standard_bundle = list(
      expected_plot_ids = list("mrapss_mrplot"),
      generated_plot_ids = list("mrapss_mrplot"),
      missing_plot_ids = list(),
      degraded = FALSE
    )
  ),
  result_record_path = normalizePath(record_path, winslash = "/", mustWork = FALSE)
)
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)

outputs <- list(status = "ok")
outputs$mrapss_result <- result
rendered <- list(
  summary = summary_text,
  outputs = outputs,
  details = list(result_status = "ok", failure_class = NULL),
  artifacts = list(
    list(path = result$result_record_path, kind = "json", summary = "MR-APSS result record"),
    list(path = plot_path_norm, kind = "png", summary = "MR-APSS result plot"),
    list(path = normalizePath(plot_data_path, winslash = "/"), kind = "json", summary = "MR-APSS SNP interaction data")
  )
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
log_step("Completed successfully.")
