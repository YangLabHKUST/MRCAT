args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) stop("expected args: input_json output_json execution_dir")

suppressPackageStartupMessages({
  library(data.table)
  library(jsonlite)
  library(TwoSampleMR)
  library(ggplot2)
  library(MRPRESSO)
})

payload <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
output_json <- args[[2]]
execution_dir <- args[[3]]
log_step <- function(..., .error = FALSE) {
  cat("[analysis-sensitivity] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
}
dir.create(file.path(execution_dir, "reports"), recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(execution_dir, "plots"), recursive = TRUE, showWarnings = FALSE)

script_file <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
script_dir <- if (length(script_file) > 0) {
  dirname(normalizePath(sub("^--file=", "", script_file[[1]]), winslash = "/", mustWork = TRUE))
} else {
  getwd()
}
skill_root <- normalizePath(file.path(script_dir, "..", ".."), winslash = "/", mustWork = TRUE)
source(file.path(script_dir, "steiger.R"))
workspace_dir <- normalizePath(file.path(skill_root, "..", ".."), mustWork = TRUE)
source(file.path(workspace_dir, "mrcat", "tool", "mr", "mr_presso_results.R"))
plot_explanation_path <- function(plot_id) {
  normalizePath(file.path(skill_root, "plot_explanations", paste0(plot_id, ".md")), winslash = "/", mustWork = TRUE)
}
normalize_path <- function(path) normalizePath(path, winslash = "/", mustWork = FALSE)

num_or_null <- function(x) {
  if (is.null(x) || length(x) == 0) return(NULL)
  value <- suppressWarnings(as.numeric(x)[1])
  if (!is.finite(value)) return(NULL)
  value
}

first_finite <- function(x) {
  values <- suppressWarnings(as.numeric(x))
  values <- values[is.finite(values)]
  if (length(values) == 0) return(NULL)
  values[[1]]
}

detect_flag <- function(value, threshold = 0.05) {
  !is.null(value) && is.finite(value) && value < threshold
}

save_first_plot <- function(plot_obj, path, width = 7, height = 5) {
  if (is.list(plot_obj) && length(plot_obj) > 0 && !inherits(plot_obj, "ggplot")) plot_obj <- plot_obj[[1]]
  ggplot2::ggsave(path, plot_obj, width = width, height = height, dpi = 300, limitsize = FALSE)
  normalize_path(path)
}

build_twosamplemr_dat <- function(selected) {
  data.frame(
    SNP = as.character(selected$SNP),
    beta.exposure = as.numeric(selected$b.exp),
    beta.outcome = as.numeric(selected$b.out),
    se.exposure = as.numeric(selected$se.exp),
    se.outcome = as.numeric(selected$se.out),
    exposure = "exposure",
    outcome = "outcome",
    id.exposure = "exposure",
    id.outcome = "outcome",
    mr_keep = TRUE,
    stringsAsFactors = FALSE
  )
}

write_failure <- function(failure_class, message) {
  rendered <- list(
    summary = paste0("analysis-sensitivity blocked: ", message),
    outputs = list(status = "blocked", failure_class = failure_class),
    details = list(failure_class = failure_class, message = message),
    artifacts = list()
  )
  jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
  quit(save = "no", status = 0)
}

primary_record_path <- normalizePath(payload$primary_result_record_path, winslash = "/", mustWork = TRUE)
primary <- jsonlite::fromJSON(primary_record_path, simplifyVector = FALSE)
if (!identical(primary$method, "mr_primary")) write_failure("invalid_primary_result", "primary result method must be mr_primary.")
selected_path <- primary$selected_mrdat_path
if (is.null(selected_path) || !file.exists(selected_path)) write_failure("missing_selected_mrdat", "primary result selected_mrdat_path does not exist.")

input_scale <- primary$input_scale
if (is.null(input_scale)) write_failure("missing_input_scale", "Primary result lacks scale provenance; rerun primary MR before sensitivity analysis.")
selected <- data.table::fread(selected_path)
if (!("input_scale" %in% names(selected)) || any(is.na(selected$input_scale) | selected$input_scale != input_scale)) write_failure("input_scale_mismatch", "Selected SNP table and primary result have inconsistent input_scale.")
required <- c("SNP", "b.exp", "b.out", "se.exp", "se.out", "pval.exp")
missing <- setdiff(required, names(selected))
if (length(missing) > 0) write_failure("invalid_selected_mrdat", paste("selected MRdat missing columns:", paste(missing, collapse = ", ")))
numeric_columns <- c("b.exp", "b.out", "se.exp", "se.out", "pval.exp")
selected[, (numeric_columns) := lapply(.SD, function(x) suppressWarnings(as.numeric(x))), .SDcols = numeric_columns]
if (nrow(selected) < 4) write_failure("insufficient_instruments", "at least four selected instruments are required.")

nb_distribution <- suppressWarnings(as.integer(payload$nb_distribution)[1])
if (length(nb_distribution) == 0 || !is.finite(nb_distribution) || nb_distribution < 1) nb_distribution <- 1000L
signif_threshold <- suppressWarnings(as.numeric(payload$signif_threshold)[1])
if (length(signif_threshold) == 0 || !is.finite(signif_threshold) || signif_threshold <= 0 || signif_threshold >= 1) signif_threshold <- 0.05
seed <- suppressWarnings(as.integer(payload$seed)[1])
if (length(seed) == 0 || !is.finite(seed)) seed <- 1234L
steiger_filter <- payload$steiger_filter
if (is.null(steiger_filter)) steiger_filter <- FALSE
if (!is.logical(steiger_filter) || length(steiger_filter) != 1 || is.na(steiger_filter)) {
  write_failure("invalid_steiger_filter", "steiger_filter must be a boolean.")
}
detailed_plot_max_instruments <- suppressWarnings(as.integer(payload$detailed_plot_max_instruments)[1])
if (length(detailed_plot_max_instruments) == 0 || !is.finite(detailed_plot_max_instruments) || detailed_plot_max_instruments < 1) {
  detailed_plot_max_instruments <- 100L
}

dat <- build_twosamplemr_dat(selected)
log_step("Running standard sensitivity diagnostics on instruments=", nrow(dat), ".")
heterogeneity_df <- tryCatch(TwoSampleMR::mr_heterogeneity(dat), error = function(e) write_failure("heterogeneity_failed", conditionMessage(e)))
pleiotropy_df <- tryCatch(TwoSampleMR::mr_pleiotropy_test(dat), error = function(e) write_failure("pleiotropy_failed", conditionMessage(e)))
leave_one_out_df <- tryCatch(TwoSampleMR::mr_leaveoneout(dat), error = function(e) write_failure("leave_one_out_failed", conditionMessage(e)))
single_snp_df <- tryCatch(TwoSampleMR::mr_singlesnp(dat), error = function(e) write_failure("single_snp_failed", conditionMessage(e)))
steiger <- run_steiger(selected, payload$steiger_metadata, steiger_filter, dat, execution_dir, seed)
log_step("Steiger status=", steiger$result$status,
         if (!is.null(steiger$result$reason)) paste0("; ", steiger$result$reason) else "",
         "; filtering=", steiger$result$filtering$status, ".")

heterogeneity <- lapply(seq_len(nrow(heterogeneity_df)), function(index) {
  row <- heterogeneity_df[index, , drop = FALSE]
  q_pval <- num_or_null(row$Q_pval)
  list(
    method = as.character(row$method[[1]]),
    q = num_or_null(row$Q),
    df = num_or_null(row$Q_df),
    pval = q_pval,
    detected = detect_flag(q_pval)
  )
})

egger_intercept <- first_finite(pleiotropy_df$egger_intercept)
egger_se <- first_finite(pleiotropy_df$se)
egger_pval <- first_finite(pleiotropy_df$pval)
pleiotropy <- list(
  intercept = num_or_null(egger_intercept),
  se = num_or_null(egger_se),
  pval = num_or_null(egger_pval),
  detected = detect_flag(egger_pval)
)

all_row <- leave_one_out_df[as.character(leave_one_out_df$SNP) == "All", , drop = FALSE]
all_beta <- if (nrow(all_row) > 0) first_finite(all_row$b) else NULL
if (is.null(all_beta)) {
  for (row in primary$methods) {
    if (identical(as.character(row$method), "IVW")) {
      all_beta <- num_or_null(row[["beta.hat"]])
      break
    }
  }
}
loo_rows <- leave_one_out_df[as.character(leave_one_out_df$SNP) != "All", , drop = FALSE]
pct_change <- rep(NA_real_, nrow(loo_rows))
if (!is.null(all_beta) && is.finite(all_beta) && all_beta != 0 && nrow(loo_rows) > 0) {
  pct_change <- abs((as.numeric(loo_rows$b) - all_beta) / all_beta) * 100
}
finite_change <- which(is.finite(pct_change))
max_index <- if (length(finite_change) > 0) finite_change[[which.max(pct_change[finite_change])]] else NULL
most_influential_snp <- if (!is.null(max_index)) as.character(loo_rows$SNP[[max_index]]) else NULL
max_abs_change <- if (!is.null(max_index)) pct_change[[max_index]] else NULL
direction_reversed <- FALSE
if (!is.null(all_beta) && is.finite(all_beta) && all_beta != 0 && nrow(loo_rows) > 0) {
  loo_beta <- suppressWarnings(as.numeric(loo_rows$b))
  direction_reversed <- any(is.finite(loo_beta) & sign(loo_beta) != 0 & sign(loo_beta) != sign(all_beta))
}
leave_one_out <- list(
  most_influential_snp = most_influential_snp,
  max_abs_change_percent = num_or_null(max_abs_change),
  influential_count = as.integer(sum(is.finite(pct_change) & pct_change > 20)),
  direction_reversed = direction_reversed
)

selected_df <- as.data.frame(selected)
selected_labels <- as.character(selected_df$SNP)
rownames(selected_df) <- make.unique(selected_labels)
mr_presso_check_input(selected_df)
nb_used <- mr_presso_simulations(nrow(selected_df), nb_distribution, signif_threshold)
log_step("Running MR-PRESSO: requested simulations=", nb_distribution, "; NbDistribution=", nb_used, "; SignifThreshold=", signif_threshold, "; seed=", seed, ".")
presso_fit <- tryCatch(
  MRPRESSO::mr_presso(
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
  ),
  error = function(e) write_failure("mr_presso_failed", conditionMessage(e))
)

presso_raw_path <- normalize_path(file.path(execution_dir, "reports", "sensitivity_mr_presso_raw.rds"))
saveRDS(presso_fit, presso_raw_path)
presso <- tryCatch(mr_presso_extract(presso_fit, selected_df, signif_threshold),
                   error = function(e) write_failure("mr_presso_result_invalid", conditionMessage(e)))
main_df <- presso_fit[["Main MR results"]]
raw_beta <- num_or_null(main_df[["Causal Estimate"]][main_df[["MR Analysis"]] == "Raw"])
corrected_beta <- num_or_null(main_df[["Causal Estimate"]][main_df[["MR Analysis"]] == "Outlier-corrected"])
outlier_snps <- presso$outlier_snps
global_pval <- presso$global_pval
global_rss <- presso$global_rss
distortion_pval <- presso$distortion_pval
mr_presso <- list(
  global_pval = global_pval,
  global_rss = global_rss,
  detected = presso$global_detected,
  outlier_status = presso$outlier_status,
  outlier_count = presso$outlier_count,
  outlier_snps = as.list(outlier_snps),
  raw_beta = raw_beta,
  corrected_beta = corrected_beta,
  distortion_pval = distortion_pval,
  distortion_detected = presso$distortion_detected,
  nb_distribution_requested = nb_distribution,
  nb_distribution_used = nb_used,
  raw_result_path = presso_raw_path
)

reports <- list(
  heterogeneity = normalize_path(file.path(execution_dir, "reports", "sensitivity_heterogeneity.tsv")),
  pleiotropy = normalize_path(file.path(execution_dir, "reports", "sensitivity_pleiotropy.tsv")),
  leave_one_out = normalize_path(file.path(execution_dir, "reports", "sensitivity_leave_one_out.tsv")),
  single_snp = normalize_path(file.path(execution_dir, "reports", "sensitivity_single_snp.tsv")),
  mr_presso = normalize_path(file.path(execution_dir, "reports", "sensitivity_mr_presso.tsv"))
)
data.table::fwrite(heterogeneity_df, reports$heterogeneity, sep = "\t", quote = FALSE, na = "NA")
data.table::fwrite(pleiotropy_df, reports$pleiotropy, sep = "\t", quote = FALSE, na = "NA")
data.table::fwrite(leave_one_out_df, reports$leave_one_out, sep = "\t", quote = FALSE, na = "NA")
data.table::fwrite(single_snp_df, reports$single_snp, sep = "\t", quote = FALSE, na = "NA")
report_value <- function(value) if (is.null(value) || length(value) == 0) NA_character_ else as.character(value[[1]])
presso_report <- data.table::data.table(
  metric = c("global_rss", "global_pval", "outlier_status", "outlier_count", "outlier_snps", "raw_beta", "corrected_beta", "distortion_pval", "nb_distribution_used"),
  value = c(
    report_value(global_rss),
    report_value(global_pval),
    presso$outlier_status,
    report_value(presso$outlier_count),
    paste(outlier_snps, collapse = ","),
    report_value(raw_beta),
    report_value(corrected_beta),
    report_value(distortion_pval),
    as.character(nb_used)
  )
)
data.table::fwrite(presso_report, reports$mr_presso, sep = "\t", quote = FALSE, na = "NA")
reports <- c(reports, steiger$reports)

plots <- list()
skipped_plots <- list()
if (nrow(selected) <= detailed_plot_max_instruments) {
  single_plot <- save_first_plot(
    TwoSampleMR::mr_forest_plot(single_snp_df),
    file.path(execution_dir, "plots", "sensitivity_single_snp_forest.png"),
    height = max(5, 1.5 + 0.18 * nrow(single_snp_df))
  )
  plots <- append(plots, list(
    list(plot_id = "sensitivity_single_snp_forest", path = single_plot, title = "Single-SNP forest plot", source = "mr_sensitivity_result", explanation_path = plot_explanation_path("sensitivity_single_snp_forest"))
  ))
} else {
  skipped_plots <- append(skipped_plots, list(
    list(
      plot_id = "sensitivity_single_snp_forest",
      reason = "instrument_count_exceeds_limit",
      instrument_count = nrow(selected),
      limit = detailed_plot_max_instruments
    )
  ))
}
funnel_plot <- save_first_plot(
  TwoSampleMR::mr_funnel_plot(single_snp_df),
  file.path(execution_dir, "plots", "sensitivity_funnel.png")
)
plots <- append(plots, list(
  list(plot_id = "sensitivity_funnel", path = funnel_plot, title = "Funnel plot", source = "mr_sensitivity_result", explanation_path = plot_explanation_path("sensitivity_funnel"))
))
if (nrow(selected) <= detailed_plot_max_instruments) {
  loo_plot <- save_first_plot(
    TwoSampleMR::mr_leaveoneout_plot(leave_one_out_df),
    file.path(execution_dir, "plots", "sensitivity_leave_one_out.png"),
    width = 9,
    height = max(5, 1.5 + 0.18 * nrow(leave_one_out_df))
  )
  plots <- append(plots, list(
    list(plot_id = "sensitivity_leave_one_out", path = loo_plot, title = "Leave-one-out plot", source = "mr_sensitivity_result", explanation_path = plot_explanation_path("sensitivity_leave_one_out"))
  ))
} else {
  skipped_plots <- append(skipped_plots, list(
    list(
      plot_id = "sensitivity_leave_one_out",
      reason = "instrument_count_exceeds_limit",
      instrument_count = nrow(selected),
      limit = detailed_plot_max_instruments
    )
  ))
  log_step(
    "Skipping detailed Single-SNP forest and leave-one-out plots: instruments=", nrow(selected),
    " exceeds limit=", detailed_plot_max_instruments, ". Full numeric reports were preserved."
  )
}

is_outlier <- seq_len(nrow(selected_df)) %in% presso$outlier_indices
presso_plot_path <- file.path(execution_dir, "plots", "sensitivity_presso_outlier.png")
png(presso_plot_path, width = 2100, height = 1500, res = 300)
x <- selected_df$b.exp
y <- selected_df$b.out
plot(x, y, type = "n", xlab = "SNP-exposure effect", ylab = "SNP-outcome effect", main = "MR-PRESSO outlier plot")
abline(h = 0, v = 0, col = "grey85")
points(x, y, pch = 19, col = ifelse(is_outlier, "#D55E00", "#333333"))
if (!is.null(raw_beta) && is.finite(raw_beta)) abline(a = 0, b = raw_beta, col = "#333333", lwd = 2)
if (!is.null(corrected_beta) && is.finite(corrected_beta)) abline(a = 0, b = corrected_beta, col = "#0072B2", lwd = 2, lty = 2)
legend("topleft", legend = c("Instrument", "Outlier", "Raw estimate", "Corrected estimate"), pch = c(19, 19, NA, NA), lty = c(NA, NA, 1, 2), col = c("#333333", "#D55E00", "#333333", "#0072B2"), bty = "n")
dev.off()
presso_plot <- normalize_path(presso_plot_path)

plots <- append(plots, list(
  list(plot_id = "sensitivity_presso_outlier", path = presso_plot, title = "MR-PRESSO outlier plot", source = "mr_sensitivity_result", explanation_path = plot_explanation_path("sensitivity_presso_outlier"))
))

summary_text <- paste0(
  "analysis-sensitivity completed: instruments=", nrow(selected),
  "; heterogeneity_tests=", length(heterogeneity),
  "; egger_intercept_p=", ifelse(is.null(egger_pval), "NA", egger_pval),
  "; mr_presso_outlier_status=", presso$outlier_status,
  "; mr_presso_outliers=", report_value(presso$outlier_count),
  "; mr_presso_simulations_requested=", nb_distribution,
  "; mr_presso_simulations_used=", nb_used,
  "; steiger=", steiger$result$status,
  "; steiger_filtering=", steiger$result$filtering$status,
  "; detailed_plots_skipped=", length(skipped_plots), "."
)
record_path <- file.path(execution_dir, "reports", "mr_sensitivity_result_record.json")
result <- list(
  method = "mr_sensitivity",
  input_scale = input_scale,
  selected_mrdat_path = selected_path,
  primary_result_record_path = primary_record_path,
  heterogeneity = heterogeneity,
  pleiotropy = pleiotropy,
  leave_one_out = leave_one_out,
  mr_presso = mr_presso,
  steiger = steiger$result,
  reports = reports,
  plot_manifest = list(plots = plots, skipped = skipped_plots),
  result_record_path = normalize_path(record_path)
)
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)

rendered <- list(
  summary = summary_text,
  outputs = list(status = "ok", mr_sensitivity_result = result),
  details = list(result_status = "ok", failure_class = NULL),
  artifacts = c(
    list(list(path = result$result_record_path, kind = "json", summary = "MR sensitivity result record"),
         list(path = presso_raw_path, kind = "rds", summary = "Unmodified MR-PRESSO package result")),
    lapply(names(reports), function(name) list(path = reports[[name]], kind = "tsv", summary = paste(name, "sensitivity report"))),
    lapply(plots, function(plot) list(path = plot$path, kind = "png", summary = plot$title))
  )
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
log_step("Completed successfully.")
