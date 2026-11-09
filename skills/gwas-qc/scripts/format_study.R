args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  stop("expected args: input_json output_json execution_dir")
}

suppressPackageStartupMessages({
  library(data.table)
  library(jsonlite)
  library(MRAPSS)
})

script_file <- sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[[1]])
script_dir <- dirname(normalizePath(script_file))
workspace_dir <- normalizePath(file.path(script_dir, "..", "..", ".."))
source(file.path(workspace_dir, "mrcat", "tool", "MRTool", "gwas_statistics.R"))
source(file.path(script_dir, "format_data.R"))

input_json <- args[[1]]
output_json <- args[[2]]
execution_dir <- args[[3]]
payload <- jsonlite::fromJSON(input_json, simplifyVector = FALSE)
log_step <- function(..., .error = FALSE) {
  cat("[gwas-qc] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
}

dir.create(file.path(execution_dir, "formatted"), recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(execution_dir, "reports"), recursive = TRUE, showWarnings = FALSE)

compact <- function(x) {
  if (is.null(x) || length(x) == 0) return("")
  trimws(paste(as.character(x), collapse = " "))
}

resolve_path <- function(path) {
  text <- compact(path)
  if (!nzchar(text)) return("")
  candidates <- c(text)
  if (!grepl("^/", text)) {
    workspace <- Sys.getenv("MRCAT_WORKSPACE_DIR", unset = "")
    skill_dir <- Sys.getenv("MRCAT_SKILL_DIR", unset = "")
    if (nzchar(workspace)) candidates <- c(candidates, file.path(workspace, text))
    if (nzchar(skill_dir)) candidates <- c(candidates, file.path(skill_dir, text))
  }
  for (candidate in candidates) {
    if (file.exists(candidate)) return(normalizePath(candidate, winslash = "/", mustWork = TRUE))
  }
  text
}

has_values <- function(dt, col) {
  if (!(col %in% names(dt))) return(FALSE)
  values <- trimws(as.character(dt[[col]]))
  any(!is.na(values) & values != "" & values != "NA")
}

range_for_log <- function(x) {
  values <- suppressWarnings(as.numeric(x))
  values <- values[is.finite(values)]
  if (length(values) == 0) return("NA")
  paste0("[", format(min(values), digits = 6, scientific = TRUE), ", ", format(max(values), digits = 6, scientific = TRUE), "]")
}

number_for_log <- function(x) {
  format(x, digits = 8, scientific = FALSE, trim = TRUE)
}

formatted_n_summary <- function(values) {
  values <- suppressWarnings(as.numeric(values))
  values <- values[is.finite(values)]
  if (length(values) == 0) return("final formatted N is unavailable")
  unique_values <- unique(values)
  if (length(unique_values) == 1) {
    return(paste0("final formatted N is fixed at ", number_for_log(unique_values[[1]]), " for ", length(values), " rows"))
  }
  paste0(
    "final formatted N varies by row: min=", number_for_log(min(values)),
    ", median=", number_for_log(stats::median(values)),
    ", max=", number_for_log(max(values)),
    ", rows=", length(values)
  )
}

remaining_after <- function(messages, marker) {
  matches <- messages[grepl(marker, messages, fixed = TRUE)]
  if (length(matches) == 0) return(NA_real_)
  groups <- regmatches(
    matches[[length(matches)]],
    regexec("remaining\\s+([0-9]+)\\s+SNPs", matches[[length(matches)]], perl = TRUE)
  )[[1]]
  if (length(groups) < 2) return(NA_real_)
  suppressWarnings(as.numeric(groups[[2]]))
}

format_evidence_summary <- function(
  n_input,
  n_final,
  messages,
  had_beta,
  had_or,
  had_z
) {
  stage_markers <- c(
    ambiguous_removed = "Remove ambiguous SNPs",
    mhc_removed = "Remove SNPs in MHC region",
    duplicate_removed = "Remove duplicated SNPs",
    hapmap_reference_removed = "Merge SNPs with the hapmap3 snplist",
    hapmap_allele_mismatch_removed = "Remove SNPs with alleles not matched with the hapmap3 snplist",
    low_maf_removed = "Remove SNPs with MAF less than",
    invalid_pvalue_removed = "Remove SNPs with p-value < 0 or p-value > 1",
    missing_value_removed = "Remove missing values",
    sample_size_outlier_removed = "Remove SNPs with sample size 5 standard deviations away from the mean",
    chi_square_outlier_removed = "Remove SNPs with chi2 > chi2_max"
  )
  parts <- c(paste0("input_rows=", number_for_log(n_input)))
  previous <- as.numeric(n_input)
  for (field_name in names(stage_markers)) {
    retained <- remaining_after(messages, stage_markers[[field_name]])
    if (is.finite(previous) && is.finite(retained) && retained <= previous) {
      parts <- c(
        parts,
        paste0(field_name, "=", number_for_log(previous - retained))
      )
    }
    previous <- retained
  }
  parts <- c(parts, paste0("formatted_rows=", number_for_log(n_final)))

  beta_from_or <- !had_beta && had_or
  input_effect_field <- if (had_beta) {
    "beta"
  } else if (had_or) {
    "or"
  } else if (had_z) {
    "z"
  } else {
    "unresolved"
  }
  formatted_effect_representation <- if (beta_from_or) {
    "log_or"
  } else if (had_beta) {
    "source_beta"
  } else if (had_z) {
    "z"
  } else {
    "unresolved"
  }
  parts <- c(
    parts,
    paste0("input_effect_field=", input_effect_field),
    paste0("beta_from_or=", tolower(as.character(beta_from_or))),
    paste0("formatted_effect_representation=", formatted_effect_representation)
  )
  paste(parts, collapse = ", ")
}

write_blocked <- function(failure_class, message, diagnostics = list()) {
  log_step("Blocked: failure_class=", failure_class, "; message=", message, .error = TRUE)
  rendered <- list(
    summary = paste0("gwas-qc blocked: ", message),
    outputs = list(
      status = "blocked",
      failure_class = failure_class,
      message = message
    ),
    details = list(
      result_status = "blocked",
      failure_class = failure_class,
      diagnostics = diagnostics
    ),
    artifacts = list()
  )
  jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", digits = NA)
  quit(save = "no", status = 0)
}

drop_empty_optional <- function(dt) {
  optional <- c("beta", "or", "se", "z", "pval", "neglog10_pval", "freq_qc", "info", "n", "n_cases", "n_controls")
  for (col in optional) {
    if ((col %in% names(dt)) && !has_values(dt, col)) {
      dt[, (col) := NULL]
    }
  }
  dt
}

load_reference <- function(path, object_name, package_object) {
  resolved_path <- resolve_path(path)
  if (nzchar(resolved_path) && file.exists(resolved_path)) {
    if (!grepl("\\.(rda|RData)$", resolved_path, ignore.case = TRUE)) {
      table <- data.table::fread(resolved_path)
      if (identical(object_name, "MHC.SNPs")) return(as.character(table[[1]]))
      return(as.data.frame(table))
    }
    env <- new.env(parent = emptyenv())
    load(resolved_path, envir = env)
    if (exists(object_name, envir = env)) return(get(object_name, envir = env))
    objects <- ls(env)
    if (length(objects) >= 1) return(get(objects[[1]], envir = env))
  }
  data(list = package_object, package = "MRAPSS", envir = environment())
  get(package_object, envir = environment())
}

run_side <- function(side, input_path, sample_size, snps_merge, snps_remove, min_freq) {
  log_step("Reading ", side, " canonical GWAS: ", input_path)
  dt <- data.table::fread(input_path)
  n_input <- nrow(dt)
  log_step("Loaded ", side, " canonical GWAS: rows=", n_input, "; sample_size=", sample_size, "; min_freq=", min_freq, ".")
  if (!has_values(dt, "SNP")) {
    write_blocked(
      "missing_snp_id",
      paste0(side, " canonical GWAS has no usable SNP/rsid values; provide rsid-bearing GWAS input or add a dedicated rsid annotation skill before MR-APSS formatting."),
      list(
        side = side,
        input_path = normalizePath(input_path, winslash = "/", mustWork = FALSE),
        rows = n_input,
        has_chr_bp = all(c("CHR", "BP") %in% names(dt))
      )
    )
  }
  had_beta <- has_values(dt, "beta")
  had_or <- has_values(dt, "or")
  had_z <- has_values(dt, "z")
  had_n <- has_values(dt, "n")
  had_case_control_n <- has_values(dt, "n_cases") && has_values(dt, "n_controls")
  dt <- drop_empty_optional(dt)
  use_neglog <- !has_values(dt, "pval") && has_values(dt, "neglog10_pval")
  p_col <- if (use_neglog) "neglog10_pval" else "pval"
  b_col <- if ("beta" %in% names(dt)) "beta" else "__missing_beta"
  or_col <- if ("or" %in% names(dt)) "or" else "__missing_or"
  se_col <- if ("se" %in% names(dt)) "se" else "__missing_se"
  freq_col <- if ("freq_qc" %in% names(dt)) "freq_qc" else "__missing_freq_qc"
  n_col <- if ("n" %in% names(dt)) "n" else "__missing_n"
  ncase_col <- if ("n_cases" %in% names(dt)) "n_cases" else "__missing_n_cases"
  ncontrol_col <- if ("n_controls" %in% names(dt)) "n_controls" else "__missing_n_controls"
  z_col <- if ("z" %in% names(dt)) "z" else "__missing_z"
  info_col <- if ("info" %in% names(dt)) "info" else "__missing_info"
  explicit_n <- suppressWarnings(as.numeric(sample_size)[1])
  if (length(explicit_n) == 0 || !is.finite(explicit_n) || explicit_n <= 0) explicit_n <- NULL
  sample_size_source <- "missing"
  sample_size_source_detail <- "no usable canonical n, n_cases/n_controls, or side-level sample_size"
  if ("n" %in% names(dt)) {
    sample_size_source <- "row_level_n"
    sample_size_source_detail <- "canonical n column"
  } else if ("n_cases" %in% names(dt) && "n_controls" %in% names(dt)) {
    sample_size_source <- "row_level_case_control"
    sample_size_source_detail <- "canonical n_cases+n_controls columns"
  } else if (!is.null(explicit_n)) {
    sample_size_source <- "side_level_sample_size"
    sample_size_source_detail <- paste0("side-level sample_size=", number_for_log(explicit_n))
  }
  log_step(
    "Sample size decision for ", side,
    ": source=", sample_size_source,
    "; detail=", sample_size_source_detail,
    "; n_col=", ifelse("n" %in% names(dt), "n", "none"),
    "; n_cases_col=", ifelse("n_cases" %in% names(dt), "n_cases", "none"),
    "; n_controls_col=", ifelse("n_controls" %in% names(dt), "n_controls", "none"),
    "; side_sample_size=", ifelse(is.null(explicit_n), "none", number_for_log(explicit_n)),
    "."
  )

  messages <- character()
  log_step("Formatting ", side, " with MRAPSS::format_data.")
  formatted <- withCallingHandlers(
    mrcat_format_data(
      dat = as.data.frame(dt),
      snps.merge = snps_merge,
      snps.remove = snps_remove,
      snp_col = "SNP",
      b_col = b_col,
      or_col = or_col,
      se_col = se_col,
      freq_col = freq_col,
      A1_col = "effect_allele",
      A2_col = "other_allele",
      p_col = p_col,
      ncase_col = ncase_col,
      ncontrol_col = ncontrol_col,
      n_col = n_col,
      n = explicit_n,
      z_col = z_col,
      info_col = info_col,
      log_pval = use_neglog,
      min_freq = min_freq
    ),
    message = function(m) {
      messages <<- c(messages, conditionMessage(m))
      invokeRestart("muffleMessage")
    }
  )
  log_step("Completed ", side, " formatting: input rows=", n_input, "; retained rows=", nrow(formatted), ".")
  sample_size_summary <- paste0(
    "Sample size used for ", side, ": source=", sample_size_source,
    " (", sample_size_source_detail, "); ",
    formatted_n_summary(formatted$N),
    "."
  )
  log_step(sample_size_summary)
  if (length(messages) > 0) {
    for (format_message in messages) {
      log_step("mrcat_format_data ", side, " message: ", trimws(format_message))
    }
  }
  log_step(
    "Formatting evidence for ", side,
    ": removed_rows=", max(n_input - nrow(formatted), 0),
    "; log_pval=", use_neglog,
    "; beta_from_or=", !had_beta && had_or,
    "; n_from_case_control=", !had_n && had_case_control_n,
    "; formatted_P_range=", range_for_log(formatted$P),
    "; formatted_Z_range=", range_for_log(formatted$Z),
    "; formatted_N_range=", range_for_log(formatted$N),
    "; messages=", ifelse(length(messages) == 0, "none", paste(messages, collapse = " | ")),
    "."
  )

  output_path <- file.path(execution_dir, "formatted", paste0(side, ".mrapss.tsv.gz"))
  log_step("Writing ", side, " formatted GWAS: ", output_path)
  data.table::fwrite(formatted, output_path, sep = "\t", quote = FALSE, na = "NA", compress = "gzip")
  report <- list(
    side = side,
    input_path = normalizePath(input_path, winslash = "/", mustWork = FALSE),
    formatted_path = normalizePath(output_path, winslash = "/", mustWork = FALSE),
    n_input = n_input,
    n_final = nrow(formatted),
    native_usable_rows = sum(is.finite(formatted$beta_native) & is.finite(formatted$se_native) & formatted$se_native > 0),
    n_removed = max(n_input - nrow(formatted), 0),
    log_pval = use_neglog,
    derived_in_format_stage = list(
      beta_from_or = !had_beta && had_or,
      z_from_beta_p_or_beta_se = TRUE,
      n_from_case_control = !had_n && had_case_control_n,
      freq_qc_from_case_control = FALSE
    ),
    sample_size_summary = sample_size_summary,
    messages = messages
  )
  report_path <- file.path(execution_dir, "reports", paste0("mrapss_format_", side, ".json"))
  jsonlite::write_json(report, report_path, auto_unbox = TRUE, pretty = TRUE, null = "null", digits = NA)
  list(
    study = list(
      trait = compact(payload[[paste0(side, "_label")]]),
      formatted_path = normalizePath(output_path, winslash = "/", mustWork = FALSE),
      format_report_path = normalizePath(report_path, winslash = "/", mustWork = FALSE),
      n_input = n_input,
      n_final = nrow(formatted),
      n_removed = max(n_input - nrow(formatted), 0),
      messages = messages
    ),
    evidence_summary = format_evidence_summary(
      n_input,
      nrow(formatted),
      messages,
      had_beta,
      had_or,
      had_z
    )
  )
}

hm3 <- load_reference(payload$hm3_path, "w_hm3.snplist", "w_hm3.snplist")
mhc <- load_reference(payload$mhc_path, "MHC.SNPs", "MHC.SNPs")
min_freq <- suppressWarnings(as.numeric(payload$min_freq)[1])
if (length(min_freq) == 0 || !is.finite(min_freq)) min_freq <- 0.05
log_step("Loaded MR-APSS references; min_freq=", min_freq, ".")

study_run <- run_side("study", payload$canonical_path, payload$sample_size, hm3, mhc, min_freq)
study <- study_run$study
format_report <- list(
  min_freq = min_freq,
  study = study,
  total_input = study$n_input,
  total_final = study$n_final
)
format_report_path <- file.path(execution_dir, "reports", "gwas_qc_format_report.json")
jsonlite::write_json(format_report, format_report_path, auto_unbox = TRUE, pretty = TRUE, null = "null", digits = NA)
if (study$n_final == 0) {
  write_blocked(
    "gwas_qc_format_zero_rows",
    "mrcat_format_data returned zero rows.",
    list(
      n_input = study$n_input,
      n_final = study$n_final,
      format_report_path = normalizePath(format_report_path, winslash = "/", mustWork = FALSE),
      side_report_path = study$format_report_path,
      messages = study$messages
    )
  )
}
result <- list(
  formatted_path = study$formatted_path,
  format_report_path = normalizePath(format_report_path, winslash = "/", mustWork = FALSE),
  label = compact(payload$label),
  ancestry = compact(payload$ancestry),
  n_input = study$n_input,
  n_final = study$n_final,
  n_removed = study$n_removed,
  diagnostics = list(
    min_freq = min_freq,
    formatted_rows = study$n_final,
    input_rows = study$n_input,
    removed_rows = study$n_removed,
    format_report_path = normalizePath(format_report_path, winslash = "/", mustWork = FALSE)
  )
)
rendered <- list(
  summary = paste0(
    "gwas-qc formatting completed: min_freq=", min_freq,
    "; rows input=", study$n_input,
    ", formatted=", study$n_final,
    ", removed=", study$n_removed,
    "; ", study_run$evidence_summary,
    "; report=", normalizePath(format_report_path, winslash = "/", mustWork = FALSE),
    "."
  ),
  outputs = list(status = "ok", gwas_qc_format_result = result),
  details = list(result_status = "ok", failure_class = NULL),
  artifacts = list(
    list(path = study$formatted_path, kind = "tsv", summary = "analysis-ready formatted GWAS"),
    list(path = result$format_report_path, kind = "json", summary = "GWAS format report")
  )
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", digits = NA)
log_step("Completed successfully.")
