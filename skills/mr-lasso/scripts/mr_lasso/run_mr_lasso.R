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
  cat("[mr-lasso] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
}

dir.create(file.path(execution_dir, "reports"), recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(execution_dir, "plots"), recursive = TRUE, showWarnings = FALSE)

script_file <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
script_dir <- if (length(script_file) > 0) {
  dirname(normalizePath(sub("^--file=", "", script_file[[1]]), winslash = "/", mustWork = TRUE))
} else {
  getwd()
}
source(file.path(script_dir, "mr_lasso_helper.R"))
workspace_dir <- Sys.getenv("MRCAT_WORKSPACE_DIR", unset = "")
if (!nzchar(workspace_dir)) {
  workspace_dir <- normalizePath(file.path(script_dir, "..", "..", "..", ".."), winslash = "/", mustWork = TRUE)
}
skill_root <- normalizePath(file.path(script_dir, "..", ".."), winslash = "/", mustWork = TRUE)
source(file.path(workspace_dir, "mrcat", "tool", "mr", "mr_input_scale.R"))
plot_explanation_path <- function(plot_id) {
  normalizePath(file.path(skill_root, "plot_explanations", paste0(plot_id, ".md")), winslash = "/", mustWork = TRUE)
}
source(file.path(workspace_dir, "mrcat", "tool", "mr", "mr_instrument_selection.R"))

num_or_null <- function(x) {
  value <- suppressWarnings(as.numeric(x)[1])
  if (length(value) == 0 || !is.finite(value)) return(NULL)
  value
}

ci_from_bounds <- function(lower, upper, level) {
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

int_param <- function(x, default) {
  value <- suppressWarnings(as.integer(x)[1])
  if (length(value) == 0 || !is.finite(value)) return(default)
  value
}

compact <- function(x) {
  if (is.null(x) || length(x) == 0) return("")
  trimws(paste(as.character(x), collapse = " "))
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

save_lasso_scatter <- function(path, selected, fit) {
  valid <- as.character(selected$SNP) %in% as.character(fit$ValidSNPs)
  beta <- suppressWarnings(as.numeric(fit$Estimate)[1])
  save_plot(path, function() {
    x <- selected$b.exp
    y <- selected$b.out
    xlim <- range(c(x, x - 1.96 * selected$se.exp, x + 1.96 * selected$se.exp), finite = TRUE)
    ylim <- range(c(y, y - 1.96 * selected$se.out, y + 1.96 * selected$se.out), finite = TRUE)
    plot(x, y, type = "n", xlab = "SNP-exposure effect", ylab = "SNP-outcome effect", main = "MR-Lasso validity scatter", xlim = xlim, ylim = ylim)
    abline(h = 0, v = 0, col = "grey85")
    arrows(x - 1.96 * selected$se.exp, y, x + 1.96 * selected$se.exp, y, length = 0, col = "grey75")
    arrows(x, y - 1.96 * selected$se.out, x, y + 1.96 * selected$se.out, length = 0, col = "grey75")
    points(x, y, pch = 19, col = ifelse(valid, "#009E73", "#D55E00"))
    if (is.finite(beta)) abline(a = 0, b = beta, col = "#0072B2", lwd = 2)
    legend("topleft", legend = c("Valid SNP", "Penalized SNP", "MR-Lasso estimate"), pch = c(19, 19, NA), lty = c(NA, NA, 1), col = c("#009E73", "#D55E00", "#0072B2"), bty = "n")
  })
}

lambda_param <- function(x) {
  if (is.null(x) || length(x) == 0) return(NULL)
  values <- suppressWarnings(as.numeric(unlist(x)))
  values <- values[is.finite(values)]
  if (length(values) == 0) return(NULL)
  values
}

write_blocked <- function(selection, min_instruments) {
  nsnp <- selection$nsnp
  threshold <- selection$threshold
  summary_text <- paste0("mr-lasso blocked: ", mr_selection_summary(selection, min_instruments), ".")
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
required <- c("SNP", "b.exp", "b.out", "se.exp", "se.out", "pval.exp")
missing <- setdiff(required, names(mrdat))
if (length(missing) > 0) {
  stop(paste("MRdat missing columns:", paste(missing, collapse = ", ")))
}

numeric_columns <- c("b.exp", "b.out", "se.exp", "se.out", "pval.exp")
mrdat[, (numeric_columns) := lapply(.SD, function(x) suppressWarnings(as.numeric(x))), .SDcols = numeric_columns]

threshold <- suppressWarnings(as.numeric(payload$pvalue_threshold)[1])
if (length(threshold) == 0 || !is.finite(threshold)) threshold <- 5e-8
min_instruments <- int_param(payload$min_instruments, 4L)
distribution <- compact(payload$distribution)
if (!nzchar(distribution)) distribution <- "normal"
alpha <- suppressWarnings(as.numeric(payload$alpha)[1])
if (length(alpha) == 0 || !is.finite(alpha)) alpha <- 0.05
lambda_values <- lambda_param(payload[["lambda"]])

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

log_step("Fitting method: MR-Lasso; distribution=", distribution, "; alpha=", alpha, "; lambda=", ifelse(is.null(lambda_values), "auto", paste(lambda_values, collapse = ",")), ".")
fit <- mr_lasso(
  snps = selected$SNP,
  Bx = selected$b.exp,
  By = selected$b.out,
  Bxse = selected$se.exp,
  Byse = selected$se.out,
  distribution = distribution,
  alpha = alpha,
  lambda = lambda_values
)

row <- list(
  method = "MR-Lasso",
  Threshold = threshold,
  nsnp = as.integer(nsnp),
  "beta.hat" = num_or_null(fit$Estimate),
  se = num_or_null(fit$StdError),
  pval = num_or_null(fit$Pvalue),
  ci = ci_from_bounds(fit$CILower, fit$CIUpper, 1 - alpha),
  Valid = num_or_null(fit$Valid),
  Lambda = num_or_null(fit$Lambda)
)
log_step("Completed method: MR-Lasso; beta=", row[["beta.hat"]], "; se=", row$se, "; pval=", row$pval, ".")
log_step("MR-Lasso result JSON: ", jsonlite::toJSON(row, auto_unbox = TRUE, null = "null", digits = NA))

lasso_plot_path <- save_lasso_scatter(file.path(execution_dir, "plots", "lasso_validity_scatter.png"), selected, fit)
plot_refs <- list(
  list(
    plot_id = "lasso_validity_scatter",
    path = lasso_plot_path,
    title = "MR-Lasso validity scatter",
    source = "mr_lasso_result",
    explanation_path = plot_explanation_path("lasso_validity_scatter")
  )
)

summary_text <- paste0(
  "canonicalized/formatted counts: completed upstream and reused; ",
  "estimated MR-APSS parameters: completed upstream for shared MRdat; ",
  "input MRdat: already constructed and LD-clumped upstream, rows=", nrow(mrdat), "; ",
  "method-level pvalue_threshold instrument selection/QC on already-clumped MRdat: ", selection_text, "; ",
  "fitted method: MR-Lasso beta=", row[["beta.hat"]], "; ",
  "artifacts/plots: result_record=1, plots=", length(plot_refs), "."
)

record_path <- file.path(execution_dir, "reports", "mr_lasso_result_record.json")
log_step("Writing result record: ", record_path)
selected_path <- mr_save_selected_input(selected, execution_dir)
result <- list(
  input_scale = input_scale,
  scale_excluded_rows = scale_excluded_rows,
  selected_mrdat_path = selected_path,
  method = "mr_lasso",
  methods = list(row),
  diagnostics = list(
    mrdat_rows = nrow(mrdat),
    pvalue_threshold = threshold,
    nsnp = nsnp,
    distribution = distribution,
    alpha = alpha,
    lambda_mode = ifelse(is.null(lambda_values), "auto", "provided")
  ),
  interpretation = list(summary = summary_text, recommendations = recommendations),
  plot_manifest = list(plots = plot_refs),
  result_record_path = normalizePath(record_path, winslash = "/", mustWork = FALSE)
)
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)

outputs <- list(status = "ok")
outputs$mr_lasso_result <- result
rendered <- list(
  summary = summary_text,
  outputs = outputs,
  details = list(result_status = "ok", failure_class = NULL),
  artifacts = list(list(path = result$result_record_path, kind = "json", summary = "MR-Lasso result record"))
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
log_step("Completed successfully.")
