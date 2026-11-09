args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  stop("expected args: input_json output_json execution_dir")
}

suppressPackageStartupMessages({
  library(data.table)
  library(jsonlite)
})

payload <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
output_json <- args[[2]]
execution_dir <- args[[3]]
log_step <- function(..., .error = FALSE) {
  cat("[mr-divw] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
}

dir.create(file.path(execution_dir, "reports"), recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(execution_dir, "plots"), recursive = TRUE, showWarnings = FALSE)

script_file <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
script_dir <- if (length(script_file) > 0) {
  dirname(normalizePath(sub("^--file=", "", script_file[[1]]), winslash = "/", mustWork = TRUE))
} else {
  getwd()
}
workspace_dir <- Sys.getenv("MRCAT_WORKSPACE_DIR", unset = "")
if (!nzchar(workspace_dir)) {
  workspace_dir <- normalizePath(file.path(script_dir, "..", "..", "..", ".."), winslash = "/", mustWork = TRUE)
}
skill_root <- normalizePath(file.path(script_dir, "..", ".."), winslash = "/", mustWork = TRUE)
source(file.path(workspace_dir, "mrcat", "tool", "MRTool", "mr_input_scale.R"))
plot_explanation_path <- function(plot_id) {
  normalizePath(file.path(skill_root, "plot_explanations", paste0(plot_id, ".md")), winslash = "/", mustWork = TRUE)
}
source(file.path(workspace_dir, "mrcat", "tool", "MRTool", "mr_instrument_selection.R"))

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

range_for_log <- function(x) {
  values <- suppressWarnings(as.numeric(x))
  values <- values[is.finite(values)]
  if (length(values) == 0) return("NA")
  paste0("[", format(min(values), digits = 6, scientific = TRUE), ", ", format(max(values), digits = 6, scientific = TRUE), "]")
}

fit_divw_with_plot <- function(path, call_args) {
  plot_args <- call_args
  plot_args$diagnostics <- TRUE
  grDevices::png(path, width = 2100, height = 1500, res = 300)
  on.exit(grDevices::dev.off(), add = TRUE)
  fit <- do.call(mr.divw::mr.divw, plot_args)
  list(fit = fit, path = normalizePath(path, winslash = "/", mustWork = TRUE))
}

write_blocked <- function(selection, min_instruments) {
  nsnp <- selection$nsnp
  threshold <- selection$threshold
  summary_text <- paste0("mr-divw blocked: ", mr_selection_summary(selection, min_instruments), ".")
  log_step("Blocked: ", summary_text, .error = TRUE)
  rendered <- list(
    summary = summary_text,
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
input_scale <- mr_input_scale(payload$input_scale, allowed = c("standardize", "native"))
mrdat <- mr_apply_input_scale(mrdat, input_scale, payload$exposure_type, payload$outcome_type)
scale_excluded_rows <- attr(mrdat, "scale_excluded_rows")
log_step("Loaded upstream MRdat: rows=", nrow(mrdat), ".")
required <- c("b.exp", "b.out", "se.exp", "se.out", "pval.exp")
missing <- setdiff(required, names(mrdat))
if (length(missing) > 0) {
  stop(paste("MRdat missing columns:", paste(missing, collapse = ", ")))
}
numeric_columns <- c("b.exp", "b.out", "se.exp", "se.out", "pval.exp")
mrdat[, (numeric_columns) := lapply(.SD, function(x) suppressWarnings(as.numeric(x))), .SDcols = numeric_columns]

threshold <- suppressWarnings(as.numeric(payload$pvalue_threshold)[1])
if (length(threshold) == 0 || !is.finite(threshold)) threshold <- 5e-8
min_instruments <- suppressWarnings(as.integer(payload$min_instruments)[1])
if (length(min_instruments) == 0 || !is.finite(min_instruments)) min_instruments <- 4L
lambda_value <- suppressWarnings(as.numeric(payload[["lambda"]])[1])

selection <- mr_select_instruments(mrdat, threshold, min_instruments, log_step)
selected <- selection$selected
threshold <- selection$threshold
nsnp <- selection$nsnp
log_step("Selected instrument summary: pval.exp_range=", range_for_log(selected$pval.exp), "; b.exp_range=", range_for_log(selected$b.exp), "; b.out_range=", range_for_log(selected$b.out), "; se.exp_range=", range_for_log(selected$se.exp), "; se.out_range=", range_for_log(selected$se.out), ".")
if (!selection$passed) {
  write_blocked(selection, min_instruments)
}
selection_text <- mr_selection_summary(selection, min_instruments)
recommendations <- mr_selection_recommendations(selection)

log_step("Loading R package: mr.divw.")
suppressPackageStartupMessages(library(mr.divw))

call_args <- list(
  beta.exposure = selected$b.exp,
  beta.outcome = selected$b.out,
  se.exposure = selected$se.exp,
  se.outcome = selected$se.out,
  diagnostics = FALSE,
  over.dispersion = TRUE
)
if (length(lambda_value) > 0 && is.finite(lambda_value)) {
  call_args$lambda <- lambda_value
}
log_step("Fitting method: dIVW; lambda=", ifelse(length(lambda_value) > 0 && is.finite(lambda_value), lambda_value, "default"), ".")
fit_plot <- fit_divw_with_plot(file.path(execution_dir, "plots", "divw_residual_qq.png"), call_args)
fit <- fit_plot$fit

row <- list(
  method = "dIVW",
  Threshold = threshold,
  nsnp = as.integer(nsnp),
  "beta.hat" = num_or_null(fit$beta.hat),
  se = num_or_null(fit$beta.se),
  pval = num_or_null(pchisq(fit$beta.hat^2 / fit$beta.se^2, 1, lower.tail = FALSE)),
  ci = ci_from_se(fit$beta.hat, fit$beta.se)
)
log_step("Completed method: dIVW; beta=", row[["beta.hat"]], "; se=", row$se, "; pval=", row$pval, ".")
log_step("dIVW result JSON: ", jsonlite::toJSON(row, auto_unbox = TRUE, null = "null", digits = NA))

plot_refs <- list(
  list(
    plot_id = "divw_residual_qq",
    path = fit_plot$path,
    title = "dIVW residual QQ plot",
    source = "mr_divw_result",
    explanation_path = plot_explanation_path("divw_residual_qq")
  )
)

summary_text <- paste0(
  "canonicalized/formatted counts: completed upstream and reused; ",
  "estimated MR-APSS parameters: completed upstream for shared MRdat; ",
  "input MRdat: already constructed and LD-clumped upstream, rows=", nrow(mrdat), "; ",
  "method-level pvalue_threshold instrument selection/QC on already-clumped MRdat: ", selection_text, "; ",
  "fitted method: dIVW beta=", row[["beta.hat"]], "; ",
  "artifacts/plots: result_record=1, plots=", length(plot_refs), "."
)

record_path <- file.path(execution_dir, "reports", "mr_divw_result_record.json")
log_step("Writing result record: ", record_path)
selected_path <- mr_save_selected_input(selected, execution_dir)
result <- list(
  input_scale = input_scale,
  scale_excluded_rows = scale_excluded_rows,
  selected_mrdat_path = selected_path,
  method = "mr_divw",
  methods = list(row),
  diagnostics = list(mrdat_rows = nrow(mrdat), pvalue_threshold = threshold, nsnp = nsnp, lambda = num_or_null(lambda_value)),
  interpretation = list(summary = summary_text, recommendations = recommendations),
  plot_manifest = list(plots = plot_refs),
  result_record_path = normalizePath(record_path, winslash = "/", mustWork = FALSE)
)
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)

outputs <- list(status = "ok")
outputs$mr_divw_result <- result
rendered <- list(
  summary = summary_text,
  outputs = outputs,
  details = list(result_status = "ok", failure_class = NULL),
  artifacts = list(list(path = result$result_record_path, kind = "json", summary = "dIVW result record"))
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
log_step("Completed successfully.")
