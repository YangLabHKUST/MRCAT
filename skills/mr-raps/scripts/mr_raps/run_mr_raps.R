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
  cat("[mr-raps] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
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

bool_value <- function(x, default = FALSE) {
  text <- tolower(trimws(paste(as.character(x), collapse = " ")))
  if (!nzchar(text) || identical(text, "null")) return(default)
  text %in% c("1", "true", "t", "yes", "y", "on")
}

save_raps_fit_and_plot <- function(path, raps_df, diagnostics_flag) {
  if (diagnostics_flag) {
    grDevices::png(path, width = 2100, height = 1500, res = 300)
    on.exit(grDevices::dev.off(), add = TRUE)
    fit <- suppressWarnings(mr.raps::mr.raps(raps_df, diagnostics = TRUE))
    return(list(fit = fit, path = normalizePath(path, winslash = "/", mustWork = TRUE)))
  }
  fit <- suppressWarnings(mr.raps::mr.raps(raps_df, diagnostics = FALSE))
  grDevices::png(path, width = 2100, height = 1500, res = 300)
  on.exit(grDevices::dev.off(), add = TRUE)
  plot(fit)
  list(fit = fit, path = normalizePath(path, winslash = "/", mustWork = TRUE))
}

save_profile_score_diagnostics <- function(path, selected) {
  b_exp <- selected$b.exp
  b_out <- selected$b.out
  se_exp <- selected$se.exp
  se_out <- selected$se.out

  grDevices::pdf(NULL)
  diagnostic_fit <- NULL
  tryCatch(
    invisible(utils::capture.output(
      diagnostic_fit <- suppressWarnings(mr.raps::mr.raps.mle(
        b_exp,
        b_out,
        se_exp,
        se_out,
        over.dispersion = TRUE,
        loss.function = "huber",
        diagnostics = TRUE,
        suppress.warning = TRUE
      ))
    )),
    finally = grDevices::dev.off()
  )

  standardized_residual <- suppressWarnings(as.numeric(diagnostic_fit$std.resid))
  leave_one_out <- suppressWarnings(as.numeric(diagnostic_fit$beta.hat.loo))
  if (length(standardized_residual) != nrow(selected) || length(leave_one_out) != nrow(selected)) {
    stop("mr.raps.mle diagnostics did not return one residual and leave-one-out estimate per instrument")
  }

  snp_labels <- if ("SNP" %in% names(selected)) {
    as.character(selected$SNP)
  } else {
    paste0("SNP ", seq_len(nrow(selected)))
  }
  f_statistic <- (b_exp / se_exp)^2
  influence <- abs(leave_one_out - diagnostic_fit$beta.hat)
  influential_index <- if (any(is.finite(influence))) {
    which.max(replace(influence, !is.finite(influence), -Inf))
  } else {
    which.max(abs(standardized_residual))
  }

  qq_order <- order(standardized_residual)
  qq_data <- data.frame(
    instrument_index = qq_order,
    theoretical_quantile = stats::qnorm(stats::ppoints(length(qq_order))),
    standardized_residual = standardized_residual[qq_order],
    SNP = snp_labels[qq_order]
  )
  loo_data <- data.frame(
    instrument_index = seq_len(nrow(selected)),
    f_statistic = f_statistic,
    leave_one_out = leave_one_out,
    SNP = snp_labels
  )
  qq_data <- qq_data[is.finite(qq_data$theoretical_quantile) & is.finite(qq_data$standardized_residual), ]
  loo_data <- loo_data[is.finite(loo_data$f_statistic) & loo_data$f_statistic > 0 & is.finite(loo_data$leave_one_out), ]

  point_color <- "#8CCBD0"
  highlight_color <- "#D95F59"
  qq_plot <- ggplot2::ggplot(
    qq_data,
    ggplot2::aes(x = theoretical_quantile, y = standardized_residual)
  ) +
    ggplot2::geom_abline(intercept = 0, slope = 1, linetype = "dashed", color = "#555555", linewidth = 0.55) +
    ggplot2::geom_point(color = point_color, alpha = 0.82, size = 2.4) +
    ggplot2::geom_point(
      data = qq_data[qq_data$instrument_index == influential_index, ],
      color = highlight_color,
      shape = 8,
      size = 3.2
    ) +
    ggrepel::geom_text_repel(
      data = qq_data[qq_data$instrument_index == influential_index, ],
      ggplot2::aes(label = SNP),
      color = highlight_color,
      size = 3.6,
      min.segment.length = 0,
      seed = 17,
      show.legend = FALSE
    ) +
    ggplot2::labs(
      x = "Quantile of standard normal",
      y = "Standardized residual"
    ) +
    ggplot2::theme_bw(base_size = 14) +
    ggplot2::theme(
      panel.border = ggplot2::element_rect(color = "#444444", fill = NA, linewidth = 0.7),
      panel.grid.minor = ggplot2::element_blank(),
      axis.title = ggplot2::element_text(color = "#222222"),
      axis.text = ggplot2::element_text(color = "#333333")
    )

  loo_plot <- ggplot2::ggplot(
    loo_data,
    ggplot2::aes(x = f_statistic, y = leave_one_out)
  ) +
    ggplot2::geom_hline(
      yintercept = diagnostic_fit$beta.hat,
      linetype = "dashed",
      color = "#555555",
      linewidth = 0.55
    ) +
    ggplot2::geom_point(color = point_color, alpha = 0.82, size = 2.4) +
    ggplot2::geom_point(
      data = loo_data[loo_data$instrument_index == influential_index, ],
      color = highlight_color,
      shape = 8,
      size = 3.2
    ) +
    ggrepel::geom_text_repel(
      data = loo_data[loo_data$instrument_index == influential_index, ],
      ggplot2::aes(label = SNP),
      color = highlight_color,
      size = 3.6,
      min.segment.length = 0,
      seed = 17,
      show.legend = FALSE
    ) +
    ggplot2::scale_x_log10(breaks = c(2, 5, 10, 20, 50, 100, 200, 500, 1000)) +
    ggplot2::labs(
      x = "Instrument strength (F-statistic)",
      y = "Leave-one-out estimate"
    ) +
    ggplot2::theme_bw(base_size = 14) +
    ggplot2::theme(
      panel.border = ggplot2::element_rect(color = "#444444", fill = NA, linewidth = 0.7),
      panel.grid.minor = ggplot2::element_blank(),
      axis.title = ggplot2::element_text(color = "#222222"),
      axis.text = ggplot2::element_text(color = "#333333")
    )

  grDevices::png(path, width = 2400, height = 1100, res = 250)
  tryCatch(
    gridExtra::grid.arrange(qq_plot, loo_plot, ncol = 2),
    finally = grDevices::dev.off()
  )
  normalizePath(path, winslash = "/", mustWork = TRUE)
}

write_blocked <- function(selection, min_instruments) {
  nsnp <- selection$nsnp
  threshold <- selection$threshold
  summary_text <- paste0("mr-raps blocked: ", mr_selection_summary(selection, min_instruments), ".")
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
diagnostics_requested <- bool_value(payload$diagnostics, default = TRUE)

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
diagnostics_flag <- diagnostics_requested && nsnp >= 8L
diagnostics_skip_reason <- NULL
if (diagnostics_requested && !diagnostics_flag) {
  diagnostics_skip_reason <- paste0(
    "Residual-normality and profile-score diagnostics were skipped because ",
    nsnp,
    " instruments are below the minimum of 8 required by nortest::ad.test()."
  )
  recommendations <- c(recommendations, diagnostics_skip_reason)
  log_step(diagnostics_skip_reason)
}

log_step("Loading R package: mr.raps.")
suppressPackageStartupMessages(library(mr.raps))

raps_df <- data.frame(
  beta.exposure = selected$b.exp,
  beta.outcome = selected$b.out,
  se.exposure = selected$se.exp,
  se.outcome = selected$se.out
)
log_step("Fitting method: RAPS; diagnostics=", diagnostics_flag, ".")
fit_plot <- save_raps_fit_and_plot(file.path(execution_dir, "plots", "raps_diagnostics.png"), raps_df, diagnostics_flag)
fit <- fit_plot$fit

row <- list(
  method = "RAPS",
  Threshold = threshold,
  nsnp = as.integer(nsnp),
  "beta.hat" = num_or_null(fit$beta.hat),
  se = num_or_null(fit$beta.se),
  pval = num_or_null(pchisq(fit$beta.hat^2 / fit$beta.se^2, 1, lower.tail = FALSE)),
  ci = ci_from_se(fit$beta.hat, fit$beta.se)
)
log_step("Completed method: RAPS; beta=", row[["beta.hat"]], "; se=", row$se, "; pval=", row$pval, ".")
log_step("RAPS result JSON: ", jsonlite::toJSON(row, auto_unbox = TRUE, null = "null", digits = NA))

plot_refs <- list(
  list(
    plot_id = "raps_diagnostics",
    path = fit_plot$path,
    title = "RAPS residual diagnostics",
    source = "mr_raps_result",
    explanation_path = plot_explanation_path("raps_diagnostics")
  )
)
if (diagnostics_flag) {
  log_step("Generating paper-style profile score diagnostics with package-computed residuals and leave-one-out estimates.")
  profile_score_path <- save_profile_score_diagnostics(
    file.path(execution_dir, "plots", "raps_profile_score_diagnostics.png"),
    selected
  )
  plot_refs[[length(plot_refs) + 1L]] <- list(
    plot_id = "raps_profile_score_diagnostics",
    path = profile_score_path,
    title = "RAPS paper-style profile score diagnostics",
    source = "mr_raps_result",
    explanation_path = plot_explanation_path("raps_profile_score_diagnostics")
  )
}

summary_text <- paste0(
  "canonicalized/formatted counts: completed upstream and reused; ",
  "estimated MR-APSS parameters: completed upstream for shared MRdat; ",
  "input MRdat: already constructed and LD-clumped upstream, rows=", nrow(mrdat), "; ",
  "method-level pvalue_threshold instrument selection/QC on already-clumped MRdat: ", selection_text, "; ",
  "diagnostics requested=", diagnostics_requested,
  ", diagnostics executed=", diagnostics_flag,
  if (!is.null(diagnostics_skip_reason)) paste0(", diagnostics note=", diagnostics_skip_reason, "; ") else "; ",
  "fitted method: RAPS beta=", row[["beta.hat"]], "; ",
  "artifacts/plots: result_record=1, plots=", length(plot_refs), "."
)

record_path <- file.path(execution_dir, "reports", "mr_raps_result_record.json")
log_step("Writing result record: ", record_path)
selected_path <- mr_save_selected_input(selected, execution_dir)
result <- list(
  input_scale = input_scale,
  scale_excluded_rows = scale_excluded_rows,
  selected_mrdat_path = selected_path,
  method = "mr_raps",
  methods = list(row),
  diagnostics = list(
    mrdat_rows = nrow(mrdat),
    pvalue_threshold = threshold,
    nsnp = nsnp,
    diagnostics_requested = diagnostics_requested,
    diagnostics = diagnostics_flag,
    diagnostics_skip_reason = diagnostics_skip_reason
  ),
  interpretation = list(summary = summary_text, recommendations = recommendations),
  plot_manifest = list(plots = plot_refs),
  result_record_path = normalizePath(record_path, winslash = "/", mustWork = FALSE)
)
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)

outputs <- list(status = "ok")
outputs$mr_raps_result <- result
rendered <- list(
  summary = summary_text,
  outputs = outputs,
  details = list(result_status = "ok", failure_class = NULL),
  artifacts = list(list(path = result$result_record_path, kind = "json", summary = "RAPS result record"))
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
log_step("Completed successfully.")
