args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  stop("expected args: input_json output_json execution_dir")
}

suppressPackageStartupMessages({
  library(data.table)
  library(jsonlite)
  library(ggplot2)
})

payload <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
output_json <- args[[2]]
execution_dir <- args[[3]]
log_step <- function(..., .error = FALSE) {
  cat("[mr-bwmr] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
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
source(file.path(workspace_dir, "mrcat", "tool", "mr", "mr_input_scale.R"))
plot_explanation_path <- function(plot_id) {
  normalizePath(file.path(skill_root, "plot_explanations", paste0(plot_id, ".md")), winslash = "/", mustWork = TRUE)
}

source(file.path(workspace_dir, "mrcat", "tool", "mr", "mr_instrument_selection.R"))
bwmr_source <- Sys.getenv("MRCAT_BWMR_SOURCE", unset = "")
if (!nzchar(bwmr_source)) bwmr_source <- file.path(.Library, "mrcat-methods", "BWMR_updated.R")
if (!file.exists(bwmr_source)) stop("BWMR source is missing. Run scripts/install_r_dependencies.R or set MRCAT_BWMR_SOURCE.")
source(bwmr_source)

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

int_param <- function(x, default) {
  value <- suppressWarnings(as.integer(x)[1])
  if (length(value) == 0 || !is.finite(value)) return(default)
  value
}

write_blocked <- function(selection, min_instruments) {
  summary_text <- paste0("mr-bwmr blocked: ", mr_selection_summary(selection, min_instruments), ".")
  log_step("Blocked: ", summary_text, .error = TRUE)
  rendered <- list(
    summary = summary_text,
    outputs = list(
      status = "blocked",
      failure_class = "insufficient_instruments",
      nsnp = as.integer(selection$nsnp),
      min_instruments = as.integer(min_instruments),
      Threshold = selection$threshold
    ),
    details = list(
      failure_class = "insufficient_instruments",
      nsnp = as.integer(selection$nsnp),
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
min_instruments <- int_param(payload$min_instruments, 4L)

selection <- mr_select_instruments(mrdat, threshold, min_instruments, log_step)
if (!selection$passed) {
  write_blocked(selection, min_instruments)
}
selected <- selection$selected
threshold <- selection$threshold
nsnp <- selection$nsnp
selection_text <- mr_selection_summary(selection, min_instruments)
recommendations <- mr_selection_recommendations(selection)

log_step("Fitting method: BWMR; nsnp=", nsnp, "; threshold=", threshold, ".")
fit <- tryCatch(
  suppressWarnings(BWMR(
    gammahat = selected$b.exp,
    Gammahat = selected$b.out,
    sigmaX = selected$se.exp,
    sigmaY = selected$se.out
  )),
  error = function(error) stop("BWMR failed: ", conditionMessage(error))
)

beta <- num_or_null(fit$beta)
se <- num_or_null(fit$se_beta)
pval <- num_or_null(fit$P_value)
weights <- suppressWarnings(as.numeric(fit$weights))
if (is.null(beta) || is.null(se) || se <= 0 || is.null(pval)) {
  stop("BWMR returned a non-finite estimate, standard error, or p-value")
}
if (length(weights) != nsnp || any(!is.finite(weights))) {
  stop("BWMR returned invalid posterior weights")
}

row <- list(
  method = "BWMR",
  Threshold = threshold,
  nsnp = as.integer(nsnp),
  "beta.hat" = beta,
  se = se,
  pval = pval,
  ci = ci_from_se(beta, se)
)
log_step("Completed method: BWMR; beta=", beta, "; se=", se, "; pval=", pval, ".")

snp_labels <- if ("SNP" %in% names(selected)) {
  as.character(selected$SNP)
} else {
  paste0("row_", seq_len(nsnp))
}
weights_table <- data.table::data.table(SNP = snp_labels, posterior_weight = weights)
weights_path <- file.path(execution_dir, "reports", "bwmr_weights.tsv")
data.table::fwrite(weights_table, weights_path, sep = "\t")

plot_specs <- list(
  list(
    plot_id = "bwmr_weighted_fit",
    plot = fit$plot4 + ggplot2::labs(title = "BWMR weighted causal fit", color = "Posterior weight"),
    title = "BWMR weighted causal fit",
    width = 7,
    height = 5
  )
)
plot_refs <- lapply(plot_specs, function(spec) {
  path <- file.path(execution_dir, "plots", paste0(spec$plot_id, ".png"))
  ggplot2::ggsave(path, plot = spec$plot, width = spec$width, height = spec$height, dpi = 300)
  list(
    plot_id = spec$plot_id,
    path = normalizePath(path, winslash = "/", mustWork = TRUE),
    title = spec$title,
    source = "mr_bwmr_result",
    explanation_path = plot_explanation_path(spec$plot_id)
  )
})

summary_text <- paste0(
  "canonicalized/formatted counts: completed upstream and reused; ",
  "input MRdat: already constructed and LD-clumped upstream, rows=", nrow(mrdat), "; ",
  "method-level pvalue_threshold instrument selection/QC on already-clumped MRdat: ", selection_text, "; ",
  "fitted method: BWMR beta=", beta, "; ",
  "posterior weights: min=", format(min(weights), digits = 6),
  ", median=", format(stats::median(weights), digits = 6), "; ",
  "artifacts/plots: result_record=1, weights_table=1, plots=", length(plot_refs), "."
)

record_path <- file.path(execution_dir, "reports", "mr_bwmr_result_record.json")
selected_path <- mr_save_selected_input(selected, execution_dir)
result <- list(
  input_scale = input_scale,
  scale_excluded_rows = scale_excluded_rows,
  selected_mrdat_path = selected_path,
  method = "mr_bwmr",
  methods = list(row),
  diagnostics = list(
    mrdat_rows = nrow(mrdat),
    pvalue_threshold = threshold,
    nsnp = nsnp,
    weak_instrument_count = selection$weak_count,
    posterior_weight_min = min(weights),
    posterior_weight_median = stats::median(weights),
    tau = num_or_null(fit$tau),
    sigma = num_or_null(fit$sigma),
    implementation_commit = "c00e8186f12ed25899aaf85b7ac5c98c6d86c24c"
  ),
  interpretation = list(summary = summary_text, recommendations = recommendations),
  plot_manifest = list(plots = plot_refs),
  weights_path = normalizePath(weights_path, winslash = "/", mustWork = TRUE),
  result_record_path = normalizePath(record_path, winslash = "/", mustWork = FALSE)
)
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)

rendered <- list(
  summary = summary_text,
  outputs = list(status = "ok", mr_bwmr_result = result),
  details = list(result_status = "ok", failure_class = NULL),
  artifacts = list(
    list(path = result$result_record_path, kind = "json", summary = "BWMR result record"),
    list(path = result$weights_path, kind = "tsv", summary = "BWMR posterior SNP weights")
  )
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
log_step("Completed successfully.")
