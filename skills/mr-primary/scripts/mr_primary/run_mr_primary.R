args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) stop("expected args: input_json output_json execution_dir")

suppressPackageStartupMessages({
  library(data.table)
  library(jsonlite)
  library(TwoSampleMR)
  library(ggplot2)
})

payload <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
output_json <- args[[2]]
execution_dir <- args[[3]]
log_step <- function(..., .error = FALSE) {
  cat("[mr-primary] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
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
source(file.path(workspace_dir, "mrcat", "tool", "MRTool", "mr_inference.R"))

num_or_null <- function(x) {
  value <- suppressWarnings(as.numeric(x)[1])
  if (length(value) == 0 || !is.finite(value)) return(NULL)
  value
}

normalize_path <- function(path) normalizePath(path, winslash = "/", mustWork = FALSE)

write_blocked <- function(selection, min_instruments) {
  summary_text <- paste0("mr-primary blocked: ", mr_selection_summary(selection, min_instruments), ".")
  rendered <- list(
    summary = summary_text,
    outputs = list(
      status = "blocked",
      failure_class = "insufficient_instruments",
      nsnp = as.integer(selection$nsnp),
      min_instruments = as.integer(min_instruments),
      Threshold = selection$threshold
    ),
    details = list(failure_class = "insufficient_instruments"),
    artifacts = list()
  )
  jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
  quit(save = "no", status = 0)
}

write_failure <- function(message) {
  rendered <- list(
    summary = paste0("mr-primary blocked: ", message),
    outputs = list(status = "blocked", failure_class = "mr_primary_failed"),
    details = list(failure_class = "mr_primary_failed", message = message),
    artifacts = list()
  )
  jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
  quit(save = "no", status = 0)
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

save_scatter <- function(selected, rows, path) {
  dat <- build_twosamplemr_dat(selected)
  method_names <- vapply(
    rows,
    function(row) as.character(row$method),
    character(1)
  )
  method_names[method_names == "MR-Egger"] <- "MR Egger"

  mr_results <- data.frame(
    id.exposure = "exposure",
    id.outcome = "outcome",
    method = method_names,
    b = vapply(rows, function(row) as.numeric(row[["beta.hat"]]), numeric(1)),
    stringsAsFactors = FALSE
  )
  threshold <- as.numeric(rows[[1]]$Threshold)

  plot <- suppressMessages(
    TwoSampleMR::mr_scatter_plot(mr_results, dat)[[1]] +
      ggplot2::scale_colour_manual(
        values = c(
          "IVW" = "#0072B2",
          "MR Egger" = "#D55E00",
          "Weighted median" = "#009E73",
          "Weighted mode" = "#7A5195"
        )
      )
  ) +
    ggplot2::labs(
      x = "SNP effect on exposure",
      y = "SNP effect on outcome",
      colour = NULL,
      caption = paste0(
        "n = ", nrow(selected),
        " instruments; selection P \u2264 ",
        format(threshold, scientific = TRUE, trim = TRUE)
      )
    ) +
    ggplot2::guides(colour = ggplot2::guide_legend(nrow = 1, byrow = TRUE)) +
    ggplot2::theme_classic(base_size = 10, base_family = "sans") +
    ggplot2::theme(
      legend.position = "top",
      legend.justification = "left",
      legend.text = ggplot2::element_text(size = 8.5),
      axis.title = ggplot2::element_text(size = 10),
      axis.text = ggplot2::element_text(size = 9, colour = "#333333"),
      plot.caption = ggplot2::element_text(size = 8, colour = "#666666", hjust = 0),
      plot.margin = ggplot2::margin(8, 10, 8, 8)
    )
  ggplot2::ggsave(path, plot, width = 7, height = 5, dpi = 300, bg = "white")
  normalize_path(path)
}

save_estimates_forest <- function(rows, path) {
  method <- vapply(rows, function(row) as.character(row$method), character(1))
  beta <- vapply(rows, function(row) as.numeric(row[["beta.hat"]]), numeric(1))
  bounds <- t(vapply(rows, function(row) mr_ci_bounds(row$ci), numeric(2)))
  lower <- bounds[, "lower"]
  upper <- bounds[, "upper"]
  null_value <- 0
  plot_data <- data.frame(method = factor(method, levels = rev(method)), estimate = beta, lower = lower, upper = upper)
  plot <- ggplot2::ggplot(plot_data, ggplot2::aes(x = estimate, y = method)) +
    ggplot2::geom_vline(xintercept = null_value, linetype = "dashed", color = "grey55") +
    ggplot2::geom_errorbarh(ggplot2::aes(xmin = lower, xmax = upper), height = 0.18, color = "#4C78A8") +
    ggplot2::geom_point(size = 2.7, color = "#1F4E79") +
    ggplot2::labs(x = expression(hat(beta)~"(95% CI)"), y = NULL, title = "Primary MR estimates") +
    ggplot2::theme_minimal()
  ggplot2::ggsave(path, plot, width = 7, height = 4.5, dpi = 300)
  normalize_path(path)
}

source(file.path(script_dir, "fit_primary.R"))

log_step("Reading upstream harmonized and clumped MRdat: ", payload$mrdat_path)
mrdat <- data.table::fread(payload$mrdat_path)
input_scale <- mr_input_scale(payload$input_scale, allowed = c("standardize", "native"))
mrdat <- mr_apply_input_scale(mrdat, input_scale, payload$exposure_type, payload$outcome_type)
scale_excluded_rows <- attr(mrdat, "scale_excluded_rows")
required <- c("SNP", "b.exp", "b.out", "se.exp", "se.out", "pval.exp")
missing <- setdiff(required, names(mrdat))
if (length(missing) > 0) stop(paste("MRdat missing columns:", paste(missing, collapse = ", ")))
numeric_columns <- c("b.exp", "b.out", "se.exp", "se.out", "pval.exp")
mrdat[, (numeric_columns) := lapply(.SD, function(x) suppressWarnings(as.numeric(x))), .SDcols = numeric_columns]

threshold <- suppressWarnings(as.numeric(payload$pvalue_threshold)[1])
if (length(threshold) == 0 || !is.finite(threshold)) threshold <- 5e-8
min_instruments <- suppressWarnings(as.integer(payload$min_instruments)[1])
if (length(min_instruments) == 0 || !is.finite(min_instruments)) min_instruments <- 4L

selection <- mr_select_instruments(mrdat, threshold, min_instruments, log_step)
if (!selection$passed) write_blocked(selection, min_instruments)
selected <- selection$selected
threshold <- selection$threshold
nsnp <- selection$nsnp

selected_path <- file.path(execution_dir, "reports", "selected_mrdat.tsv")
data.table::fwrite(selected, selected_path, sep = "\t", quote = FALSE, na = "NA")
selected_path <- normalize_path(selected_path)

rows <- tryCatch(
  fit_primary(selected, threshold),
  error = function(e) write_failure(paste0("primary MR fitting failed: ", conditionMessage(e)))
)

scatter_path <- save_scatter(selected, rows, file.path(execution_dir, "plots", "primary_scatter.png"))
forest_path <- save_estimates_forest(rows, file.path(execution_dir, "plots", "primary_estimates_forest.png"))
plots <- list(
  list(plot_id = "primary_scatter", path = scatter_path, title = "Primary MR scatter plot", source = "mr_primary_result", explanation_path = plot_explanation_path("primary_scatter")),
  list(plot_id = "primary_estimates_forest", path = forest_path, title = "Primary MR estimates forest plot", source = "mr_primary_result", explanation_path = plot_explanation_path("primary_estimates_forest"))
)

summary_text <- paste0(
  "mr-primary completed: pvalue_threshold=", threshold,
  "; instruments=", nsnp,
  "; methods=IVW, MR-Egger, Weighted median, Weighted mode; plots=2."
)
record_path <- file.path(execution_dir, "reports", "mr_primary_result_record.json")
result <- list(
  input_scale = input_scale,
  scale_excluded_rows = scale_excluded_rows,
  method = "mr_primary",
  methods = rows,
  selected_mrdat_path = selected_path,
  diagnostics = list(pvalue_threshold = threshold, nsnp = as.integer(nsnp)),
  interpretation = list(summary = summary_text, recommendations = mr_selection_recommendations(selection)),
  plot_manifest = list(plots = plots),
  result_record_path = normalize_path(record_path)
)
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)

rendered <- list(
  summary = summary_text,
  outputs = list(status = "ok", mr_primary_result = result),
  details = list(result_status = "ok", failure_class = NULL),
  artifacts = c(
    list(
      list(path = result$result_record_path, kind = "json", summary = "primary MR result record"),
      list(path = selected_path, kind = "tsv", summary = "selected instruments used by primary MR")
    ),
    lapply(plots, function(plot) list(path = plot$path, kind = "png", summary = plot$title))
  )
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
log_step("Completed successfully.")
