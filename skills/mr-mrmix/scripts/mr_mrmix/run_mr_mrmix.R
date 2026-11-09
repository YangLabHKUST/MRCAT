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
  cat("[mr-mrmix] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
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

save_plot <- function(path, draw) {
  grDevices::png(path, width = 2100, height = 1500, res = 300)
  on.exit(grDevices::dev.off(), add = TRUE)
  draw()
  normalizePath(path, winslash = "/", mustWork = TRUE)
}

save_mrmix_profile <- function(path, fit) {
  profile <- as.data.frame(fit$profile_mat)
  if (nrow(profile) == 0 || ncol(profile) < 2) stop("MRMix profile plot has no profile_mat values")
  x_col <- if ("theta" %in% names(profile)) "theta" else names(profile)[[1]]
  y_col <- if ("pi0" %in% names(profile)) "pi0" else names(profile)[[2]]
  x <- suppressWarnings(as.numeric(profile[[x_col]]))
  y <- suppressWarnings(as.numeric(profile[[y_col]]))
  keep <- is.finite(x) & is.finite(y)
  if (!any(keep)) stop("MRMix profile plot has no finite profile values")
  estimate <- suppressWarnings(as.numeric(fit$theta)[1])
  save_plot(path, function() {
    plot(x[keep], y[keep], type = "l", lwd = 2, col = "#333333", xlab = "Causal effect theta", ylab = "Estimated valid-IV proportion pi0", main = "MRMix profile")
    if (is.finite(estimate)) abline(v = estimate, col = "#D55E00", lwd = 2)
    legend("topright", legend = c("Profile", "Estimate"), lty = c(1, 1), lwd = c(2, 2), col = c("#333333", "#D55E00"), bty = "n")
  })
}

write_blocked <- function(selection, min_instruments) {
  nsnp <- selection$nsnp
  threshold <- selection$threshold
  summary_text <- paste0("mr-mrmix blocked: ", mr_selection_summary(selection, min_instruments), ".")
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
input_scale <- mr_input_scale(payload$input_scale, allowed = c("standardize", "native", "mrmix_standardize"))
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

log_step("Loading R package: MRMix.")
suppressPackageStartupMessages(library(MRMix))

log_step("Fitting method: MRMix.")
theta_grid <- seq(-1, 1, by = 0.01)
if (input_scale == "native") {
  ratios <- selected$b.out / selected$b.exp
  ratio_se <- abs(selected$se.out / selected$b.exp)
  theta_grid <- seq(min(ratios - 2 * ratio_se), max(ratios + 2 * ratio_se), length.out = 201)
}
fit <- MRMix::MRMix(selected$b.exp, selected$b.out, selected$se.exp, selected$se.out, theta_temp_vec = theta_grid, profile = TRUE)
row <- list(
  method = "MRMix",
  Threshold = threshold,
  nsnp = as.integer(nsnp),
  "beta.hat" = num_or_null(fit$theta),
  se = num_or_null(fit$SE_theta),
  pval = num_or_null(fit$pvalue_theta),
  ci = ci_from_se(fit$theta, fit$SE_theta)
)
log_step("Completed method: MRMix; beta=", row[["beta.hat"]], "; se=", row$se, "; pval=", row$pval, ".")
log_step("MRMix result JSON: ", jsonlite::toJSON(row, auto_unbox = TRUE, null = "null", digits = NA))

mrmix_plot_path <- save_mrmix_profile(file.path(execution_dir, "plots", "mrmix_profile.png"), fit)
plot_refs <- list(
  list(
    plot_id = "mrmix_profile",
    path = mrmix_plot_path,
    title = "MRMix profile",
    source = "mr_mrmix_result",
    explanation_path = plot_explanation_path("mrmix_profile")
  )
)

summary_text <- paste0(
  "canonicalized/formatted counts: completed upstream and reused; ",
  "estimated MR-APSS parameters: completed upstream for shared MRdat; ",
  "input MRdat: already constructed and LD-clumped upstream, rows=", nrow(mrdat), "; ",
  "method-level pvalue_threshold instrument selection/QC on already-clumped MRdat: ", selection_text, "; ",
  "fitted method: MRMix beta=", row[["beta.hat"]], "; ",
  "artifacts/plots: result_record=1, plots=", length(plot_refs), "."
)

record_path <- file.path(execution_dir, "reports", "mr_mrmix_result_record.json")
log_step("Writing result record: ", record_path)
selected_path <- mr_save_selected_input(selected, execution_dir)
result <- list(
  input_scale = input_scale,
  scale_parameters = if (input_scale == "mrmix_standardize") list(exposure_type = payload$exposure_type, outcome_type = payload$outcome_type) else NULL,
  theta_grid = list(min = min(theta_grid), max = max(theta_grid), step = theta_grid[2] - theta_grid[1]),
  scale_excluded_rows = scale_excluded_rows,
  selected_mrdat_path = selected_path,
  method = "mr_mrmix",
  methods = list(row),
  diagnostics = list(mrdat_rows = nrow(mrdat), pvalue_threshold = threshold, nsnp = nsnp),
  interpretation = list(summary = summary_text, recommendations = recommendations),
  plot_manifest = list(plots = plot_refs),
  result_record_path = normalizePath(record_path, winslash = "/", mustWork = FALSE)
)
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)

outputs <- list(status = "ok")
outputs$mr_mrmix_result <- result
rendered <- list(
  summary = summary_text,
  outputs = outputs,
  details = list(result_status = "ok", failure_class = NULL),
  artifacts = list(list(path = result$result_record_path, kind = "json", summary = "MRMix result record"))
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
log_step("Completed successfully.")
