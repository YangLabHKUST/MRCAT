args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  stop("expected args: input_json output_json execution_dir")
}

suppressPackageStartupMessages({
  library(data.table)
  library(jsonlite)
  library(MendelianRandomization)
})

payload <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
output_json <- args[[2]]
execution_dir <- args[[3]]
log_step <- function(..., .error = FALSE) {
  cat("[mr-conmix] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
}

dir.create(file.path(execution_dir, "reports"), recursive = TRUE, showWarnings = FALSE)

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
source(file.path(workspace_dir, "mrcat", "tool", "MRTool", "mr_instrument_selection.R"))
source(file.path(workspace_dir, "mrcat", "tool", "MRTool", "mr_input_scale.R"))

num_or_null <- function(x) {
  value <- suppressWarnings(as.numeric(x)[1])
  if (length(value) == 0 || !is.finite(value)) return(NULL)
  value
}

ci_from_ranges <- function(lower, upper, level) {
  lower_values <- suppressWarnings(as.numeric(lower))
  upper_values <- suppressWarnings(as.numeric(upper))
  count <- min(length(lower_values), length(upper_values))
  ranges <- list()
  if (count > 0) {
    for (index in seq_len(count)) {
      lower_value <- lower_values[[index]]
      upper_value <- upper_values[[index]]
      if (!is.finite(lower_value) || !is.finite(upper_value)) next
      if (lower_value > upper_value) {
        swap <- lower_value
        lower_value <- upper_value
        upper_value <- swap
      }
      ranges[[length(ranges) + 1]] <- list(lower = lower_value, upper = upper_value)
    }
  }
  list(level = level, ranges = ranges)
}

int_param <- function(x, default) {
  value <- suppressWarnings(as.integer(x)[1])
  if (length(value) == 0 || !is.finite(value)) return(default)
  value
}

range_for_log <- function(x) {
  values <- suppressWarnings(as.numeric(x))
  values <- values[is.finite(values)]
  if (length(values) == 0) return("NA")
  paste0("[", format(min(values), digits = 6, scientific = TRUE), ", ", format(max(values), digits = 6, scientific = TRUE), "]")
}

number_param <- function(x, default) {
  value <- suppressWarnings(as.numeric(x)[1])
  if (length(value) == 0 || !is.finite(value)) return(default)
  value
}

write_blocked <- function(selection, min_instruments) {
  nsnp <- selection$nsnp
  threshold <- selection$threshold
  summary_text <- paste0("mr-conmix blocked: ", mr_selection_summary(selection, min_instruments), ".")
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
ci_min <- number_param(payload$ci_min, if (input_scale == "standardize") -1.5 else NA_real_)
ci_max <- number_param(payload$ci_max, if (input_scale == "standardize") 1.5 else NA_real_)
ci_step <- number_param(payload$ci_step, if (input_scale == "standardize") 0.01 else NA_real_)
alpha <- number_param(payload$alpha, 0.05)
psi <- number_param(payload$psi, 0)

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

# A native effect can be far outside a fixed standardized grid.
ratios <- selected$b.out / selected$b.exp
ratio_se <- abs(selected$se.out / selected$b.exp)
if (!is.finite(ci_min)) ci_min <- min(ratios - 2 * ratio_se)
if (!is.finite(ci_max)) ci_max <- max(ratios + 2 * ratio_se)
if (!is.finite(ci_min) || !is.finite(ci_max) || ci_min >= ci_max) stop("MR-ConMix requires a non-degenerate CI grid; supply ci_min and ci_max")
if (!is.finite(ci_step)) ci_step <- (ci_max - ci_min) / 10000
if (ci_step <= 0 || ci_step >= ci_max - ci_min || psi < 0 || alpha <= 0 || alpha >= 1) stop("Invalid MR-ConMix grid, psi, or alpha")

log_step("Fitting method: MR-ConMix; CIMin=", ci_min, "; CIMax=", ci_max, "; CIStep=", ci_step, "; alpha=", alpha, "; psi=", psi, ".")
mr_input <- MendelianRandomization::mr_input(
  bx = selected$b.exp,
  bxse = selected$se.exp,
  by = selected$b.out,
  byse = selected$se.out,
  snps = selected$SNP
)
fit <- MendelianRandomization::mr_conmix(
  object = mr_input,
  psi = psi,
  CIMin = ci_min,
  CIMax = ci_max,
  CIStep = ci_step,
  alpha = alpha
)

row <- list(
  method = "MR-ConMix",
  Threshold = threshold,
  nsnp = as.integer(nsnp),
  "beta.hat" = num_or_null(fit@Estimate),
  se = NULL,
  pval = num_or_null(fit@Pvalue),
  ci = ci_from_ranges(fit@CILower, fit@CIUpper, 1 - alpha),
  CIMin = num_or_null(fit@CIMin),
  CIMax = num_or_null(fit@CIMax),
  CIStep = num_or_null(fit@CIStep),
  Psi = num_or_null(fit@Psi),
  Valid = as.integer(length(fit@Valid))
)
log_step("Completed method: MR-ConMix; beta=", row[["beta.hat"]], "; pval=", row$pval, "; CI ranges=", length(row$ci$ranges), ".")
log_step("MR-ConMix result JSON: ", jsonlite::toJSON(row, auto_unbox = TRUE, null = "null", digits = NA))

plot_refs <- list()

summary_text <- paste0(
  "Parameters used: pvalue_threshold=", threshold,
  ", min_instruments=", min_instruments,
  ", ci_min=", row$CIMin,
  ", ci_max=", row$CIMax,
  ", ci_step=", row$CIStep,
  ", alpha=", alpha,
  ", psi_input=", psi,
  ", psi_effective=", row$Psi, ". ",
  "canonicalized/formatted counts: completed upstream and reused; ",
  "estimated MR-APSS parameters: completed upstream for shared MRdat; ",
  "input MRdat: already constructed and LD-clumped upstream, rows=", nrow(mrdat), "; ",
  "method-level pvalue_threshold instrument selection/QC on already-clumped MRdat: ", selection_text, "; ",
  "fitted method: MR-ConMix beta=", row[["beta.hat"]], "; ",
  "artifacts/plots: result_record=1, plots=", length(plot_refs), "."
)

record_path <- file.path(execution_dir, "reports", "mr_conmix_result_record.json")
log_step("Writing result record: ", record_path)
selected_path <- mr_save_selected_input(selected, execution_dir)
result <- list(
  input_scale = input_scale,
  scale_excluded_rows = scale_excluded_rows,
  selected_mrdat_path = selected_path,
  method = "mr_conmix",
  methods = list(row),
  diagnostics = list(
    mrdat_rows = nrow(mrdat),
    pvalue_threshold = threshold,
    nsnp = nsnp,
    ci_min = ci_min,
    ci_max = ci_max,
    ci_step = ci_step,
    alpha = alpha,
    psi = psi
  ),
  interpretation = list(summary = summary_text, recommendations = recommendations),
  plot_manifest = list(plots = plot_refs),
  result_record_path = normalizePath(record_path, winslash = "/", mustWork = FALSE)
)
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)

outputs <- list(status = "ok")
outputs$mr_conmix_result <- result
rendered <- list(
  summary = summary_text,
  outputs = outputs,
  details = list(result_status = "ok", failure_class = NULL),
  artifacts = list(list(path = result$result_record_path, kind = "json", summary = "MR-ConMix result record"))
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
log_step("Completed successfully.")
