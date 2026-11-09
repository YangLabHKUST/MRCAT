args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) stop("expected args: input_json output_json execution_dir")

suppressPackageStartupMessages({
  library(data.table)
  library(jsonlite)
  library(TwoSampleMR)
})

payload <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
output_json <- args[[2]]
execution_dir <- args[[3]]
log_step <- function(..., .error = FALSE) {
  cat("[mr-grip] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
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
  workspace_dir <- normalizePath(file.path(script_dir, "..", "..", "..", ".."), winslash = "/", mustWork = FALSE)
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
  summary_text <- paste0("mr-grip blocked: ", mr_selection_summary(selection, min_instruments), ".")
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
    summary = paste0("mr-grip blocked: ", message),
    outputs = list(status = "blocked", failure_class = "mr_grip_failed"),
    details = list(failure_class = "mr_grip_failed", message = message),
    artifacts = list()
  )
  jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
  quit(save = "no", status = 0)
}

log_step("Reading upstream harmonized and clumped MRdat: ", payload$mrdat_path)
mrdat <- data.table::fread(payload$mrdat_path)
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

fit <- try(
  TwoSampleMR::mr_grip(
    selected$b.exp,
    selected$b.out,
    selected$se.exp,
    selected$se.out,
    parameters = list()
  ),
  silent = TRUE
)
if (inherits(fit, "try-error") || is.null(fit)) {
  write_failure(paste0("MR-GRIP fitting failed: ", paste(as.character(fit), collapse = " ")))
}

rows <- list(
  list(
    method = "MR-GRIP",
    Threshold = threshold,
    nsnp = as.integer(nsnp),
    "beta.hat" = num_or_null(fit$b),
    se = num_or_null(fit$se),
    pval = num_or_null(fit$pval),
    ci = mr_ci_from_se(fit$b, fit$se, df = nsnp - 2)
  ),
  list(
    method = "MR-GRIP weak-instrument adjusted",
    Threshold = threshold,
    nsnp = as.integer(nsnp),
    "beta.hat" = num_or_null(fit$b.adj),
    se = num_or_null(fit$se.adj),
    pval = num_or_null(fit$pval.adj),
    ci = mr_ci_from_se(fit$b.adj, fit$se.adj, df = nsnp - 2)
  )
)

summary_text <- paste0(
  "mr-grip completed: pvalue_threshold=", threshold,
  "; instruments=", nsnp,
  "; methods=MR-GRIP, MR-GRIP weak-instrument adjusted."
)
record_path <- file.path(execution_dir, "reports", "mr_grip_result_record.json")
result <- list(
  method = "mr_grip",
  methods = rows,
  selected_mrdat_path = selected_path,
  diagnostics = list(pvalue_threshold = threshold, nsnp = as.integer(nsnp)),
  interpretation = list(summary = summary_text, recommendations = mr_selection_recommendations(selection)),
  plot_manifest = list(plots = list()),
  result_record_path = normalize_path(record_path)
)
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)

rendered <- list(
  summary = summary_text,
  outputs = list(status = "ok", mr_grip_result = result),
  details = list(result_status = "ok", failure_class = NULL),
  artifacts = list(
    list(path = result$result_record_path, kind = "json", summary = "MR-GRIP result record"),
    list(path = selected_path, kind = "tsv", summary = "selected instruments used by MR-GRIP")
  )
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
log_step("Completed successfully.")
