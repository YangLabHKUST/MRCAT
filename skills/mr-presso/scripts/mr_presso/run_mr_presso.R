args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) stop("expected args: input_json output_json execution_dir")

suppressPackageStartupMessages({
  library(data.table)
  library(jsonlite)
})

payload <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
output_json <- args[[2]]
execution_dir <- args[[3]]
log_step <- function(..., .error = FALSE) {
  cat("[mr-presso] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
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
source(file.path(workspace_dir, "mrcat", "tool", "MRTool", "mr_presso_results.R"))
source(file.path(workspace_dir, "mrcat", "tool", "MRTool", "mr_inference.R"))
plot_explanation_path <- function(plot_id) {
  normalizePath(file.path(skill_root, "plot_explanations", paste0(plot_id, ".md")), winslash = "/", mustWork = TRUE)
}
normalize_path <- function(path) normalizePath(path, winslash = "/", mustWork = FALSE)
source(file.path(workspace_dir, "mrcat", "tool", "MRTool", "mr_instrument_selection.R"))

num_or_null <- function(x) {
  if (is.null(x) || length(x) == 0) return(NULL)
  value <- suppressWarnings(as.numeric(x)[1])
  if (!is.finite(value)) return(NULL)
  value
}

int_param <- function(x, default) {
  value <- suppressWarnings(as.integer(x)[1])
  if (length(value) == 0 || !is.finite(value)) return(default)
  value
}

clean_name <- function(value) gsub("[^a-z0-9]+", "", tolower(as.character(value)))

find_column <- function(df, candidates, fallback_index = NULL) {
  if (is.null(df) || ncol(df) == 0) return(NULL)
  names_clean <- clean_name(names(df))
  for (candidate in candidates) {
    hit <- which(names_clean == clean_name(candidate))
    if (length(hit) > 0) return(names(df)[[hit[[1]]]])
  }
  if (!is.null(fallback_index) && ncol(df) >= fallback_index) return(names(df)[[fallback_index]])
  NULL
}

as_frame <- function(value) {
  if (is.null(value)) return(data.frame())
  tryCatch(as.data.frame(value), error = function(e) data.frame())
}

range_for_log <- function(x) {
  values <- suppressWarnings(as.numeric(x))
  values <- values[is.finite(values)]
  if (length(values) == 0) return("NA")
  paste0("[", format(min(values), digits = 6, scientific = TRUE), ", ", format(max(values), digits = 6, scientific = TRUE), "]")
}

write_blocked <- function(selection, min_instruments) {
  summary_text <- paste0("mr-presso blocked: ", mr_selection_summary(selection, min_instruments), ".")
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

estimate_at <- function(main_df, row_index, estimate_type, fitted_nsnp) {
  if (nrow(main_df) < row_index) return(NULL)
  estimate_col <- find_column(main_df, c("causalestimate", "estimate", "beta", "b"), 3)
  se_col <- find_column(main_df, c("sd", "se", "stderr", "standarderror"), 4)
  pval_col <- find_column(main_df, c("pvalue", "pval", "p"), 6)
  if (is.null(estimate_col) || is.null(se_col) || is.null(pval_col)) return(NULL)
  beta <- num_or_null(main_df[[estimate_col]][[row_index]])
  se <- num_or_null(main_df[[se_col]][[row_index]])
  pval <- num_or_null(main_df[[pval_col]][[row_index]])
  if (is.null(beta) || is.null(se) || se <= 0 || is.null(pval)) return(NULL)
  list(
    estimate_type = estimate_type,
    "beta.hat" = beta,
    se = se,
    pval = pval,
    ci = mr_ci_from_se(beta, se, df = fitted_nsnp - 1)
  )
}

save_plot <- function(path, selected_df, outlier_indices, raw_estimate, corrected_estimate) {
  grDevices::png(path, width = 2100, height = 1500, res = 300)
  on.exit(grDevices::dev.off(), add = TRUE)
  x <- selected_df$b.exp
  y <- selected_df$b.out
  xlim <- range(c(x, x - 1.96 * selected_df$se.exp, x + 1.96 * selected_df$se.exp), finite = TRUE)
  ylim <- range(c(y, y - 1.96 * selected_df$se.out, y + 1.96 * selected_df$se.out), finite = TRUE)
  is_outlier <- seq_len(nrow(selected_df)) %in% outlier_indices
  plot(
    x, y,
    type = "n",
    xlab = "SNP-exposure effect",
    ylab = "SNP-outcome effect",
    main = "MR-PRESSO outlier scatter",
    xlim = xlim,
    ylim = ylim
  )
  abline(h = 0, v = 0, col = "grey85")
  arrows(x - 1.96 * selected_df$se.exp, y, x + 1.96 * selected_df$se.exp, y, length = 0, col = "grey75")
  arrows(x, y - 1.96 * selected_df$se.out, x, y + 1.96 * selected_df$se.out, length = 0, col = "grey75")
  points(x, y, pch = 19, col = ifelse(is_outlier, "#D55E00", "#333333"))
  if (!is.null(raw_estimate)) abline(a = 0, b = raw_estimate[["beta.hat"]], col = "#333333", lwd = 2)
  if (!is.null(corrected_estimate)) abline(a = 0, b = corrected_estimate[["beta.hat"]], col = "#0072B2", lwd = 2, lty = 2)
  legend(
    "topleft",
    legend = c("Instrument", "Outlier", "Raw estimate", "Outlier-corrected estimate"),
    pch = c(19, 19, NA, NA),
    lty = c(NA, NA, 1, 2),
    col = c("#333333", "#D55E00", "#333333", "#0072B2"),
    bty = "n"
  )
  normalize_path(path)
}

log_step("Reading upstream harmonized and clumped MRdat: ", payload$mrdat_path)
mrdat <- data.table::fread(payload$mrdat_path)
input_scale <- mr_input_scale(payload$input_scale, allowed = c("standardize", "native"))
mrdat <- mr_apply_input_scale(mrdat, input_scale, payload$exposure_type, payload$outcome_type)
scale_excluded_rows <- attr(mrdat, "scale_excluded_rows")
log_step("Loaded upstream MRdat: rows=", nrow(mrdat), ".")
required <- c("b.exp", "b.out", "se.exp", "se.out", "pval.exp")
missing <- setdiff(required, names(mrdat))
if (length(missing) > 0) stop(paste("MRdat missing columns:", paste(missing, collapse = ", ")))

numeric_columns <- c("b.exp", "b.out", "se.exp", "se.out", "pval.exp")
mrdat[, (numeric_columns) := lapply(.SD, function(x) suppressWarnings(as.numeric(x))), .SDcols = numeric_columns]

threshold <- suppressWarnings(as.numeric(payload$pvalue_threshold)[1])
if (length(threshold) == 0 || !is.finite(threshold) || threshold <= 0 || threshold > 1) threshold <- 5e-8
min_instruments <- int_param(payload$min_instruments, 4L)
if (min_instruments < 4L) min_instruments <- 4L
nb_distribution <- int_param(payload$nb_distribution, 1000L)
if (nb_distribution < 1L) nb_distribution <- 1000L
signif_threshold <- suppressWarnings(as.numeric(payload$signif_threshold)[1])
if (length(signif_threshold) == 0 || !is.finite(signif_threshold) || signif_threshold <= 0 || signif_threshold >= 1) signif_threshold <- 0.05
seed <- int_param(payload$seed, 1234L)

selection <- mr_select_instruments(mrdat, threshold, min_instruments, log_step)
selected <- selection$selected
threshold <- selection$threshold
nsnp <- selection$nsnp
if (!selection$passed) write_blocked(selection, min_instruments)
selection_text <- mr_selection_summary(selection, min_instruments)
recommendations <- mr_selection_recommendations(selection)
log_step(
  "Selected instrument summary: pval.exp_range=", range_for_log(selected$pval.exp),
  "; b.exp_range=", range_for_log(selected$b.exp),
  "; b.out_range=", range_for_log(selected$b.out), "."
)

log_step("Loading R package: MRPRESSO.")
suppressPackageStartupMessages(library(MRPRESSO))

nb_used <- mr_presso_simulations(nsnp, nb_distribution, signif_threshold)
selected_df <- as.data.frame(selected)
selected_labels <- if ("SNP" %in% names(selected_df)) as.character(selected_df$SNP) else paste0("row_", seq_len(nrow(selected_df)))
rownames(selected_df) <- make.unique(selected_labels)
mr_presso_check_input(selected_df)
log_step("Fitting method: MR-PRESSO; requested simulations=", nb_distribution, "; NbDistribution=", nb_used, "; SignifThreshold=", signif_threshold, "; seed=", seed, ".")
fit <- MRPRESSO::mr_presso(
  BetaOutcome = "b.out",
  BetaExposure = "b.exp",
  SdOutcome = "se.out",
  SdExposure = "se.exp",
  OUTLIERtest = TRUE,
  DISTORTIONtest = TRUE,
  data = selected_df,
  NbDistribution = nb_used,
  SignifThreshold = signif_threshold,
  seed = seed
)

presso_raw_path <- normalize_path(file.path(execution_dir, "reports", "mr_presso_raw.rds"))
saveRDS(fit, presso_raw_path)
presso <- mr_presso_extract(fit, selected_df, signif_threshold)
main_df <- as_frame(fit[["Main MR results"]])
if (nrow(main_df) == 0) main_df <- as_frame(fit[[1]])
if (nrow(main_df) == 0) stop("MRPRESSO::mr_presso returned no main MR rows")

raw_estimate <- estimate_at(main_df, 1L, "raw", nsnp)
corrected_nsnp <- nsnp - length(presso$outlier_indices)
corrected_estimate <- estimate_at(main_df, 2L, "outlier_corrected", corrected_nsnp)
if (is.null(raw_estimate) && is.null(corrected_estimate)) stop("MRPRESSO::mr_presso returned no finite estimate")
selected_estimate <- if (!is.null(corrected_estimate)) corrected_estimate else raw_estimate

global_pval <- presso$global_pval
global_rss <- presso$global_rss
distortion_pval <- presso$distortion_pval
distortion_coefficient <- num_or_null(presso$distortion_coefficient)

method_row <- c(
  list(
    method = "MR-PRESSO",
    Threshold = threshold,
    nsnp = as.integer(if (!is.null(corrected_estimate)) corrected_nsnp else nsnp)
  ),
  selected_estimate,
  list(selected_row = if (!is.null(corrected_estimate)) 2L else 1L)
)

mr_presso <- list(
  selected_estimate_type = selected_estimate$estimate_type,
  raw_estimate = raw_estimate,
  corrected_estimate = corrected_estimate,
  global_test = list(
    rss = global_rss,
    pval = global_pval,
    detected = presso$global_detected
  ),
  outlier_test = list(
    status = presso$outlier_status,
    count = presso$outlier_count,
    snps = as.list(presso$outlier_snps),
    rows = presso$outlier_rows
  ),
  distortion_test = list(
    coefficient = distortion_coefficient,
    pval = distortion_pval,
    detected = presso$distortion_detected
  )
)

if (isTRUE(mr_presso$global_test$detected)) {
  recommendations <- c(recommendations, "The MR-PRESSO global test detected model misfit compatible with horizontal pleiotropy; inspect the outlier and distortion results.")
}
if (isTRUE(mr_presso$outlier_test$count > 0)) {
  recommendations <- c(recommendations, paste0("MR-PRESSO flagged ", mr_presso$outlier_test$count, " outlier instrument(s). Compare the prespecified raw and corrected estimates without selecting by significance."))
}

plot_path <- save_plot(
  file.path(execution_dir, "plots", "presso_outlier_scatter.png"),
  selected_df,
  presso$outlier_indices,
  raw_estimate,
  corrected_estimate
)
plot_refs <- list(list(
  plot_id = "presso_outlier_scatter",
  path = plot_path,
  title = "MR-PRESSO outlier scatter",
  source = "mr_presso_result",
  explanation_path = plot_explanation_path("presso_outlier_scatter")
))

summary_text <- paste0(
  "canonicalized/formatted counts: completed upstream and reused; ",
  "input MRdat: already constructed and LD-clumped upstream, rows=", nrow(mrdat), "; ",
  "method-level pvalue_threshold instrument selection/QC on already-clumped MRdat: ", selection_text, "; ",
  "fitted method: MR-PRESSO estimate_type=", selected_estimate$estimate_type,
  ", beta=", selected_estimate[["beta.hat"]],
  ", se=", selected_estimate$se,
  ", pval=", selected_estimate$pval,
  ", global_pval=", if (is.null(global_pval)) "NA" else global_pval,
  ", outlier_status=", presso$outlier_status,
  ", outliers=", if (is.null(presso$outlier_count)) "NA" else presso$outlier_count,
  ", simulations_requested=", nb_distribution, ", simulations_used=", nb_used, "; ",
  "artifacts/plots: result_record=1, plots=1."
)
log_step("Completed method: ", summary_text)

record_path <- file.path(execution_dir, "reports", "mr_presso_result_record.json")
selected_path <- mr_save_selected_input(selected, execution_dir)
result <- list(
  input_scale = input_scale,
  scale_excluded_rows = scale_excluded_rows,
  selected_mrdat_path = selected_path,
  method = "mr_presso",
  methods = list(method_row),
  mr_presso = mr_presso,
  diagnostics = list(
    mrdat_rows = nrow(mrdat),
    pvalue_threshold = threshold,
    nsnp = nsnp,
    selected_snps = as.list(rownames(selected_df)),
    nb_distribution = nb_distribution,
    nb_distribution_used = nb_used,
    raw_result_path = presso_raw_path,
    signif_threshold = signif_threshold,
    seed = seed
  ),
  interpretation = list(summary = summary_text, recommendations = recommendations),
  plot_manifest = list(plots = plot_refs),
  result_record_path = normalize_path(record_path)
)
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)

rendered <- list(
  summary = summary_text,
  outputs = list(status = "ok", mr_presso_result = result),
  details = list(result_status = "ok", failure_class = NULL),
  artifacts = list(
    list(path = result$result_record_path, kind = "json", summary = "MR-PRESSO result record"),
    list(path = presso_raw_path, kind = "rds", summary = "Unmodified MR-PRESSO package result")
  )
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
log_step("Completed successfully.")
