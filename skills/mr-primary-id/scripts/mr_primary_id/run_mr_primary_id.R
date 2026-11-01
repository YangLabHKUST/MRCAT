args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  stop("expected args: input_json output_json execution_dir")
}

suppressPackageStartupMessages({
  library(jsonlite)
  library(TwoSampleMR)
  library(ggplot2)
})

payload <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
output_json <- args[[2]]
execution_dir <- args[[3]]
log_step <- function(..., .error = FALSE) {
  cat("[mr-primary-id] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
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
source(file.path(workspace_dir, "mrcat", "tool", "mr", "mr_input_scale.R"))
source(file.path(workspace_dir, "mrcat", "tool", "mr", "gwas_statistics.R"))
source(file.path(workspace_dir, "mrcat", "tool", "mr", "ld_clumping.R"))
source(file.path(script_dir, "prepare_scale.R"))
input_scale <- mr_input_scale(payload$input_scale)
skill_root <- normalizePath(file.path(script_dir, "..", ".."), winslash = "/", mustWork = TRUE)
plot_explanation_path <- function(plot_id) {
  normalizePath(file.path(skill_root, "plot_explanations", paste0(plot_id, ".md")), winslash = "/", mustWork = TRUE)
}

compact <- function(x) {
  if (is.null(x) || length(x) == 0) return("")
  trimws(paste(as.character(x), collapse = " "))
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

int_or_default <- function(x, default) {
  value <- suppressWarnings(as.integer(as.numeric(x)[1]))
  if (length(value) == 0 || !is.finite(value)) return(default)
  value
}

num_or_default <- function(x, default) {
  value <- suppressWarnings(as.numeric(x)[1])
  if (length(value) == 0 || !is.finite(value)) return(default)
  value
}

method_key <- function(method) {
  text <- as.character(method)
  if (grepl("Inverse variance weighted", text, fixed = TRUE)) return("IVW")
  if (grepl("MR Egger", text, fixed = TRUE)) return("MR-Egger")
  if (grepl("Weighted median", text, fixed = TRUE)) return("Weighted median")
  if (grepl("Weighted mode", text, fixed = TRUE)) return("Weighted mode")
  ""
}

save_ggplot <- function(path, plots, width = 7, height = 5) {
  if (!is.list(plots) || length(plots) == 0 || is.null(plots[[1]])) {
    stop(paste("plot generation returned no plot for", basename(path)))
  }
  ggplot2::ggsave(
    filename = path,
    plot = plots[[1]],
    width = width,
    height = height,
    dpi = 300,
    limitsize = FALSE
  )
  normalizePath(path, winslash = "/", mustWork = TRUE)
}

save_estimates_forest <- function(path, rows) {
  method <- vapply(rows, function(row) as.character(row$method), character(1))
  beta <- vapply(rows, function(row) as.numeric(row[["beta.hat"]]), numeric(1))
  se <- vapply(rows, function(row) as.numeric(row$se), numeric(1))
  lower <- beta - 1.96 * se
  upper <- beta + 1.96 * se
  measure <- "Beta"
  null_value <- 0
  plot_data <- data.frame(method = factor(method, levels = rev(method)), estimate = beta, lower = lower, upper = upper)
  plot <- ggplot2::ggplot(plot_data, ggplot2::aes(x = estimate, y = method)) +
    ggplot2::geom_vline(xintercept = null_value, linetype = "dashed", color = "grey55") +
    ggplot2::geom_errorbarh(ggplot2::aes(xmin = lower, xmax = upper), height = 0.18, color = "#4C78A8") +
    ggplot2::geom_point(size = 2.7, color = "#1F4E79") +
    ggplot2::labs(x = paste0(measure, " (95% CI)"), y = NULL, title = "Primary MR estimates") +
    ggplot2::theme_minimal()
  ggplot2::ggsave(path, plot, width = 7, height = 4.5, dpi = 300)
  normalizePath(path, winslash = "/", mustWork = TRUE)
}

write_blocked <- function(failure_class, message, trace, step_summaries) {
  log_step("Blocked: failure_class=", failure_class, "; message=", message, .error = TRUE)
  rendered <- list(
    summary = paste0("mr-primary-id blocked: ", message),
    outputs = list(
      status = "blocked",
      failure_class = failure_class,
      message = message,
      instrument_selection_trace = trace,
      step_summaries = step_summaries
    ),
    details = list(
      result_status = "blocked",
      failure_class = failure_class,
      message = message,
      diagnostics = list(
        route = "opengwas_id",
        source_skill = "mr-primary-id",
        instrument_selection_trace = trace,
        step_summaries = step_summaries
      )
    ),
    artifacts = list()
  )
  jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
  quit(save = "no", status = 0)
}

exposure_id <- compact(payload$exposure_gwas_id)
outcome_id <- compact(payload$outcome_gwas_id)
exposure_label <- compact(payload$exposure_label)
outcome_label <- compact(payload$outcome_label)
if (!nzchar(exposure_label)) exposure_label <- exposure_id
if (!nzchar(outcome_label)) outcome_label <- outcome_id

pvalue_thresholds <- if (is.null(payload$pvalue_threshold)) 5e-8 else unlist(payload$pvalue_threshold, use.names = FALSE)
if (!is.numeric(pvalue_thresholds) || !length(pvalue_thresholds) ||
    any(!is.finite(pvalue_thresholds) | pvalue_thresholds <= 0 | pvalue_thresholds > 1) ||
    is.unsorted(pvalue_thresholds, strictly = TRUE)) {
  stop("pvalue_threshold must be in (0, 1], with a strictly increasing explicit schedule.")
}
clump_r2 <- num_or_default(payload$clump_r2, 0.001)
clump_kb <- int_or_default(payload$clump_kb, 10000L)
min_instruments <- int_or_default(payload$min_instruments, 4L)
harmonise_action <- int_or_default(payload$harmonise_action, 2L)
method_list <- c("mr_ivw", "mr_egger_regression", "mr_weighted_median", "mr_weighted_mode")
required_methods <- c("IVW", "MR-Egger", "Weighted median", "Weighted mode")
log_step("Starting OpenGWAS ID primary analysis: exposure=", exposure_id, "; outcome=", outcome_id, "; thresholds=", paste(pvalue_thresholds, collapse = ","), "; min_instruments=", min_instruments, ".")

trace <- list()
step_summaries <- list(
  list(
    step = "input",
    status = "ok",
    summary = paste0("OpenGWAS IDs ready: exposure=", exposure_id, "; outcome=", outcome_id, ".")
  )
)
selected_dat <- NULL
selected_attempt <- NULL
selected_threshold <- NULL

extract_or_block <- function(call, stage) {
  tryCatch(mrcat_opengwas_call(call), error = function(err) {
    is_502 <- inherits(err, "mrcat_opengwas_502") || grepl("502 Bad Gateway|HTTP[^0-9]*502", conditionMessage(err), ignore.case = TRUE)
    failure <- if (is_502) "opengwas_http_502" else "opengwas_request_failed"
    write_blocked(
      failure,
      paste0(stage, ": ", conditionMessage(err), ". Request failed", if (is_502) " with HTTP 502" else " at the OpenGWAS request", ". No instrument-count inference is possible; keep P-value thresholds unchanged. Local LD clumping cannot replace missing GWAS association data."),
      trace, step_summaries
    )
  })
}

for (attempt_index in seq_along(pvalue_thresholds)) {
  threshold <- pvalue_thresholds[[attempt_index]]
  log_step("Attempt ", attempt_index, ": extracting exposure instruments with p <= ", threshold, "; clump_r2=", clump_r2, "; clump_kb=", clump_kb, ".")
  attempt <- list(
    attempt = as.integer(attempt_index),
    p_threshold = threshold,
    clump_r2 = clump_r2,
    clump_kb = as.integer(clump_kb),
    harmonise_action = as.integer(harmonise_action)
  )

  exposure_dat <- extract_or_block(
    function() TwoSampleMR::extract_instruments(
      outcomes = exposure_id,
      p1 = threshold,
      clump = TRUE,
      r2 = clump_r2,
      kb = clump_kb
    ), "extract_instruments"
  )
  saveRDS(exposure_dat, file.path(execution_dir, "reports", "exposure_native.rds"))
  attempt$n_instruments <- if (is.null(exposure_dat)) 0L else as.integer(nrow(exposure_dat))
  log_step("Attempt ", attempt_index, ": extracted exposure instruments=", attempt$n_instruments, ".")
  if (is.null(exposure_dat) || nrow(exposure_dat) == 0) {
    attempt$action <- "try_next_threshold"
    attempt$reason <- "no_exposure_instruments"
    trace[[length(trace) + 1]] <- attempt
    step_summaries[[length(step_summaries) + 1]] <- list(
      step = paste0("attempt_", attempt_index, "_extract_instruments"),
      status = "blocked",
      summary = paste0("p<=", threshold, " returned no exposure instruments.")
    )
    next
  }

  log_step("Attempt ", attempt_index, ": extracting matching outcome rows.")
  outcome_dat <- extract_or_block(
    function() TwoSampleMR::extract_outcome_data(snps = exposure_dat$SNP, outcomes = outcome_id),
    "extract_outcome_data"
  )
  saveRDS(outcome_dat, file.path(execution_dir, "reports", "outcome_native.rds"))
  attempt$n_outcome_rows <- if (is.null(outcome_dat)) 0L else as.integer(nrow(outcome_dat))
  log_step("Attempt ", attempt_index, ": matched outcome rows=", attempt$n_outcome_rows, ".")
  if (is.null(outcome_dat) || nrow(outcome_dat) == 0) {
    attempt$action <- "try_next_threshold"
    attempt$reason <- "no_outcome_rows"
    trace[[length(trace) + 1]] <- attempt
    step_summaries[[length(step_summaries) + 1]] <- list(
      step = paste0("attempt_", attempt_index, "_extract_outcome"),
      status = "blocked",
      summary = paste0("p<=", threshold, " instruments had no outcome rows.")
    )
    next
  }

  log_step("Attempt ", attempt_index, ": harmonizing alleles with action=", harmonise_action, ".")
  dat <- tryCatch(
    TwoSampleMR::harmonise_data(exposure_dat = exposure_dat, outcome_dat = outcome_dat, action = harmonise_action),
    error = function(e) {
      write_blocked("harmonization_failed", paste0("harmonise_data: ", conditionMessage(e)), trace, step_summaries)
    }
  )
  keep <- if (!is.null(dat) && "mr_keep" %in% names(dat)) dat$mr_keep %in% TRUE else rep(FALSE, if (is.null(dat)) 0 else nrow(dat))
  dat <- if (is.null(dat)) NULL else dat[keep, , drop = FALSE]
  if (!is.null(dat) && nrow(dat)) {
    native_path <- file.path(execution_dir, "reports", "harmonized_native.rds")
    saveRDS(dat, native_path)
    attempt$n_harmonized_before_scale <- nrow(dat)
    if (input_scale == "standardize") {
      sizes <- resolve_id_sample_sizes(dat, payload, function(ids) {
        mrcat_opengwas_call(function() ieugwasr::gwasinfo(ids))
      })
      dat <- sizes$data
      attempt$sample_size_resolution <- sizes$resolved
      attempt$sample_size_metadata_error <- sizes$error
      if (!is.null(sizes$metadata)) {
        metadata_path <- file.path(execution_dir, "reports", "sample_size_metadata.rds")
        saveRDS(sizes$metadata, metadata_path)
        attempt$sample_size_metadata_path <- normalizePath(metadata_path)
      }
    }
    scaled <- prepare_id_scale(dat, input_scale, payload)
    attempt$scale_diagnostics <- scaled$diagnostics
    if (!is.null(scaled$error)) {
      attempt$action <- "repair_scale_inputs"
      attempt$reason <- "scale_input_invalid"
      attempt$scale_error <- scaled$error
      attempt$harmonized_native_path <- normalizePath(native_path)
      trace[[length(trace) + 1]] <- attempt
      write_blocked("scale_input_invalid",
        paste0(scaled$error$side, ": ", scaled$error$reason, "; affected rows=", scaled$error$invalid_rows,
               ". Native harmonized data saved at ", native_path,
               ". Repair the same study's supported scale inputs; do not infer absent instruments or change thresholds/scale."),
        trace, step_summaries)
    }
    dat <- scaled$data
    attempt$scale_excluded_rows <- 0L
  }
  attempt$n_harmonized <- if (is.null(dat)) 0L else as.integer(nrow(dat))
  log_step("Attempt ", attempt_index, ": retained harmonized instruments=", attempt$n_harmonized, "; minimum required=", min_instruments, ".")
  if (is.null(dat) || nrow(dat) < min_instruments) {
    attempt$action <- "try_next_threshold"
    attempt$reason <- paste0("harmonized_instruments_below_min_", min_instruments)
    trace[[length(trace) + 1]] <- attempt
    step_summaries[[length(step_summaries) + 1]] <- list(
      step = paste0("attempt_", attempt_index, "_harmonise"),
      status = "blocked",
      summary = paste0("p<=", threshold, " retained ", attempt$n_harmonized, " harmonized instruments; min=", min_instruments, ".")
    )
    next
  }

  attempt$action <- "continue_to_primary_fit"
  attempt$reason <- "ok"
  trace[[length(trace) + 1]] <- attempt
  step_summaries[[length(step_summaries) + 1]] <- list(
    step = paste0("attempt_", attempt_index, "_ready"),
    status = "ok",
    summary = paste0("p<=", threshold, " retained ", nrow(dat), " harmonized instruments.")
  )
  selected_dat <- dat
  selected_attempt <- attempt_index
  selected_threshold <- threshold
  break
}

if (is.null(selected_dat)) {
  write_blocked(
    "insufficient_instruments",
    paste0("no configured p-value threshold reached min_instruments=", min_instruments, "."),
    trace,
    step_summaries
  )
}

log_step("Fitting primary methods with TwoSampleMR::mr; instruments=", nrow(selected_dat), "; threshold=", selected_threshold, ".")
mr_res <- tryCatch(
  TwoSampleMR::mr(selected_dat, method_list = method_list),
  error = function(e) {
    write_blocked("mr_primary_failed", paste0("TwoSampleMR::mr failed: ", conditionMessage(e)), trace, step_summaries)
  }
)
log_step("Completed primary fit: result rows=", nrow(mr_res), ".")
if (!is.data.frame(mr_res) || nrow(mr_res) == 0) {
  write_blocked("mr_primary_failed", "TwoSampleMR::mr returned no result rows.", trace, step_summaries)
}

rows <- list()
for (required in required_methods) {
  matched <- NULL
  for (i in seq_len(nrow(mr_res))) {
    if (identical(method_key(mr_res$method[[i]]), required)) {
      matched <- mr_res[i, , drop = FALSE]
      break
    }
  }
  if (is.null(matched)) {
    write_blocked("primary_methods_incomplete", paste0("missing primary method: ", required), trace, step_summaries)
  }
  rows[[length(rows) + 1]] <- list(
    method = required,
    Threshold = selected_threshold,
    attempt = as.integer(selected_attempt),
    nsnp = as.integer(matched$nsnp[[1]]),
    "beta.hat" = num_or_null(matched$b[[1]]),
    se = num_or_null(matched$se[[1]]),
    pval = num_or_null(matched$pval[[1]]),
    ci = ci_from_se(matched$b[[1]], matched$se[[1]])
  )
  log_step("Collected method: ", required, "; beta=", rows[[length(rows)]][["beta.hat"]], "; se=", rows[[length(rows)]]$se, "; pval=", rows[[length(rows)]]$pval, ".")
}

step_summaries[[length(step_summaries) + 1]] <- list(
  step = "primary_fit",
  status = "ok",
  summary = paste0("Fitted 4 primary methods using ", nrow(selected_dat), " harmonized instruments at p<=", selected_threshold, ".")
)

selected_mrdat <- data.frame(
  SNP = as.character(selected_dat$SNP),
  input_scale = input_scale,
  b.exp.native = as.numeric(selected_dat$beta_native.exposure),
  b.out.native = as.numeric(selected_dat$beta_native.outcome),
  se.exp.native = as.numeric(selected_dat$se_native.exposure),
  se.out.native = as.numeric(selected_dat$se_native.outcome),
  b.exp = as.numeric(selected_dat$beta.exposure),
  b.out = as.numeric(selected_dat$beta.outcome),
  se.exp = as.numeric(selected_dat$se.exposure),
  se.out = as.numeric(selected_dat$se.outcome),
  pval.exp = as.numeric(selected_dat$pval.exposure),
  stringsAsFactors = FALSE
)
selected_path <- file.path(execution_dir, "reports", "selected_mrdat.tsv")
utils::write.table(selected_mrdat, selected_path, sep = "\t", row.names = FALSE, quote = FALSE, na = "NA")
selected_path <- normalizePath(selected_path, winslash = "/", mustWork = TRUE)

scatter_plot_path <- save_ggplot(
  file.path(execution_dir, "plots", "primary_scatter.png"),
  TwoSampleMR::mr_scatter_plot(mr_res, selected_dat)
)
forest_plot_path <- save_estimates_forest(
  file.path(execution_dir, "plots", "primary_estimates_forest.png"),
  rows
)
plot_refs <- list(
  list(plot_id = "primary_scatter", path = scatter_plot_path, title = "Primary MR scatter plot", source = "mr_primary_result", explanation_path = plot_explanation_path("primary_scatter")),
  list(plot_id = "primary_estimates_forest", path = forest_plot_path, title = "Primary MR estimates forest plot", source = "mr_primary_result", explanation_path = plot_explanation_path("primary_estimates_forest"))
)

summary_text <- paste0(
  "mr-primary-id completed: exposure=", exposure_id,
  "; outcome=", outcome_id,
  "; selected_attempt=", selected_attempt,
  "; p_threshold=", selected_threshold,
  "; clump_r2=", clump_r2,
  "; clump_kb=", clump_kb,
  "; harmonized_snps=", nrow(selected_dat),
  "; methods=IVW, MR-Egger, Weighted median, Weighted mode",
  "; plots=", length(plot_refs), "."
)

record_path <- file.path(execution_dir, "reports", "mr_primary_result_record.json")
log_step("Writing result record: ", record_path)
result <- list(
  method = "mr_primary",
  input_scale = input_scale,
  methods = rows,
  selected_mrdat_path = selected_path,
  diagnostics = list(
    pvalue_threshold = selected_threshold,
    nsnp = as.integer(nrow(selected_dat))
  ),
  interpretation = list(summary = summary_text, recommendations = list()),
  plot_manifest = list(plots = plot_refs),
  result_record_path = normalizePath(record_path, winslash = "/", mustWork = FALSE)
)
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)

rendered <- list(
  summary = summary_text,
  outputs = list(status = "ok", mr_primary_result = result),
  details = list(result_status = "ok", failure_class = NULL),
  artifacts = c(
    list(
      list(path = result$result_record_path, kind = "json", summary = "OpenGWAS ID primary MR result record"),
      list(path = selected_path, kind = "tsv", summary = "selected instruments used by primary MR")
    ),
    lapply(plot_refs, function(plot) list(path = plot$path, kind = "png", summary = plot$title))
  )
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
log_step("Completed successfully.")
