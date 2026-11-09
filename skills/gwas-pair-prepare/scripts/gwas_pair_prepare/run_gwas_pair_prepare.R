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
source(file.path(dirname(normalizePath(script_file)), "est_paras.R"))
workspace_dir <- normalizePath(file.path(dirname(script_file), "..", "..", "..", ".."), mustWork = TRUE)
source(file.path(workspace_dir, "mrcat", "tool", "MRTool", "ld_clumping.R"))

payload <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
output_json <- args[[2]]
execution_dir <- args[[3]]
log_step <- function(..., .error = FALSE) {
  cat("[gwas-pair-prepare] ", paste0(...), "\n", sep = "", file = if (.error) stderr() else stdout())
}
format_matrix_for_log <- function(x) {
  if (is.null(x)) return("null")
  mat <- matrix(as.numeric(x), nrow = 2, ncol = 2)
  rows <- apply(mat, 1, function(row) paste(format(row, digits = 16, scientific = TRUE), collapse = ", "))
  paste0("[[", rows[[1]], "], [", rows[[2]], "]]")
}

dir.create(file.path(execution_dir, "intermediate"), recursive = TRUE, showWarnings = FALSE)
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
    if (file.exists(candidate) || dir.exists(candidate)) return(normalizePath(candidate, winslash = "/", mustWork = TRUE))
  }
  text
}

resolve_bfile_prefix <- function(path) {
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
    if (file.exists(candidate) || file.exists(paste0(candidate, ".bed"))) {
      return(normalizePath(candidate, winslash = "/", mustWork = FALSE))
    }
  }
  text
}

resolve_clumping_pop <- function(bfile, pop) {
  if (nzchar(bfile)) return("")
  explicit_pop <- toupper(compact(pop))
  supported <- c("EUR", "AFR", "EAS", "SAS", "AMR")
  if (nzchar(explicit_pop) && !(explicit_pop %in% supported)) {
    stop(
      paste0(
        "unsupported OpenGWAS LD-reference population: ",
        explicit_pop
      )
    )
  }
  if (nzchar(explicit_pop)) return(explicit_pop)
  "EUR"
}

as_bool <- function(x, default = FALSE) {
  text <- tolower(compact(x))
  if (!nzchar(text)) return(default)
  text %in% c("1", "true", "t", "yes", "y", "on")
}

as_optional_number <- function(x, name) {
  if (is.null(x) || length(x) == 0) return(NULL)
  if (is.character(x) && length(x) == 1 && !nzchar(trimws(x))) return(NULL)
  value <- suppressWarnings(as.numeric(x))
  if (length(value) != 1 || is.na(value) || !is.finite(value)) {
    stop(sprintf("%s must be a finite number when provided", name))
  }
  value
}

read_formatted <- function(path) {
  dt <- as.data.frame(data.table::fread(path))
  required <- c("SNP", "A1", "A2", "Z", "N", "chi2", "P")
  missing <- setdiff(required, names(dt))
  if (length(missing) > 0) {
    stop(paste("formatted GWAS table missing columns:", paste(missing, collapse = ", ")))
  }
  dt
}

ldscore_dir <- resolve_path(payload$ldscore_dir)
if (!nzchar(ldscore_dir) || !dir.exists(ldscore_dir)) {
  stop("gwas-pair-prepare requires existing ldscore_dir")
}

log_step("Reading formatted exposure: ", payload$formatted_exposure_path)
dat1 <- read_formatted(payload$formatted_exposure_path)
log_step("Loaded formatted exposure: rows=", nrow(dat1), ".")
log_step("Reading formatted outcome: ", payload$formatted_outcome_path)
dat2 <- read_formatted(payload$formatted_outcome_path)
log_step("Loaded formatted outcome: rows=", nrow(dat2), ".")
M_value <- as_optional_number(payload$M, "M")
h2_fix_intercept <- as_bool(payload$h2_fix_intercept, default = FALSE)

log_step("Estimating pair-level background parameters and harmonizing exposure/outcome; ldscore_dir=", ldscore_dir, "; h2_fix_intercept=", h2_fix_intercept, ".")
paras <- mrcat_est_paras(
  dat1 = dat1,
  dat2 = dat2,
  trait1.name = compact(payload$exposure_label),
  trait2.name = compact(payload$outcome_label),
  LDSC = TRUE,
  h2.fix.intercept = h2_fix_intercept,
  ldscore.dir = ldscore_dir,
  M = M_value
)
log_step("Completed harmonization and LDSC estimation: harmonized rows=", nrow(paras$dat), ".")
harmonized_unique_snps <- if ("SNP" %in% names(paras$dat)) length(unique(as.character(paras$dat$SNP))) else NA_integer_
harmonized_duplicate_snps <- if (is.na(harmonized_unique_snps)) NA_integer_ else nrow(paras$dat) - harmonized_unique_snps
log_step(
  "Exposure-outcome harmonization evidence: formatted_exposure_rows=", nrow(dat1),
  "; formatted_outcome_rows=", nrow(dat2),
  "; harmonized_rows=", nrow(paras$dat),
  "; dropped_vs_exposure=", max(nrow(dat1) - nrow(paras$dat), 0),
  "; dropped_vs_outcome=", max(nrow(dat2) - nrow(paras$dat), 0),
  "; dropped_vs_smaller_input=", max(min(nrow(dat1), nrow(dat2)) - nrow(paras$dat), 0),
  "; harmonized_unique_snps=", harmonized_unique_snps,
  "; harmonized_duplicate_snps=", harmonized_duplicate_snps,
  "; columns=", paste(names(paras$dat), collapse = ","),
  "."
)

mdat_path <- file.path(execution_dir, "intermediate", "gwas_pair_mdat.tsv.gz")
log_step("Writing harmonized Mdat: ", mdat_path)
data.table::fwrite(paras$dat, mdat_path, sep = "\t", quote = FALSE, na = "NA", compress = "gzip")

c_path <- file.path(execution_dir, "intermediate", "gwas_pair_C.tsv")
omega_path <- file.path(execution_dir, "intermediate", "gwas_pair_Omega.tsv")
data.table::fwrite(as.data.frame(matrix(as.vector(paras$C), nrow = 1)), c_path, sep = "\t", quote = FALSE, col.names = FALSE)
data.table::fwrite(as.data.frame(matrix(as.vector(paras$Omega), nrow = 1)), omega_path, sep = "\t", quote = FALSE, col.names = FALSE)
log_step("Estimated Background Parameters: C=", format_matrix_for_log(paras$C), "; Omega=", format_matrix_for_log(paras$Omega), ".")
log_step("Writing Estimated Background Parameters: C=", c_path, "; Omega=", omega_path, ".")

ldsc_result_path <- file.path(execution_dir, "reports", "gwas_pair_ldsc_result.json")
ldsc_report <- list(
  n_mdat = nrow(paras$dat),
  has_C = !is.null(paras$C),
  has_Omega = !is.null(paras$Omega),
  ldscore_dir = ldscore_dir,
  rg = if (!is.null(paras$ldsc_res) && !is.null(paras$ldsc_res$rg)) paras$ldsc_res$rg else NULL
)
jsonlite::write_json(ldsc_report, ldsc_result_path, auto_unbox = TRUE, pretty = TRUE, null = "null", digits = NA)

iv_threshold <- suppressWarnings(as.numeric(payload$iv_threshold))
if (!is.finite(iv_threshold)) iv_threshold <- 5e-5
clump_r2 <- suppressWarnings(as.numeric(payload$clump_r2))
if (!is.finite(clump_r2)) clump_r2 <- 0.001
clump_kb <- suppressWarnings(as.numeric(payload$clump_kb))
if (!is.finite(clump_kb)) clump_kb <- 10000
clump_p <- suppressWarnings(as.numeric(payload$clump_p))
if (!is.finite(clump_p)) clump_p <- 0.999
bfile <- resolve_bfile_prefix(payload$bfile)
plink_bin <- resolve_path(payload$plink_bin)
clump_mode <- if (nzchar(bfile)) "local_plink" else "api"
pair_ancestry <- compact(payload$ancestry)
pop <- resolve_clumping_pop(bfile, payload$pop)

if (identical(clump_mode, "local_plink")) {
  log_step(
    "Clumping instruments: clump_mode=local_plink; IV.Threshold=", iv_threshold,
    "; clump_r2=", clump_r2,
    "; clump_kb=", clump_kb,
    "; pop=null",
    "; bfile=", ifelse(nzchar(bfile), bfile, "null"),
    "; plink_bin=", ifelse(nzchar(plink_bin), plink_bin, "null"),
    "."
  )
} else {
  log_step(
    "Clumping instruments: clump_mode=api; using OpenGWAS API reference; IV.Threshold=", iv_threshold,
    "; clump_r2=", clump_r2,
    "; clump_kb=", clump_kb,
    "; pop=", pop,
    if (nzchar(plink_bin)) paste0("; ignored_plink_bin_without_bfile=", plink_bin) else "",
    "."
  )
}

clump_result <- mrcat_clump(
  list(
    dat = paras$dat,
    IV.Threshold = iv_threshold,
    SNP_col = "SNP",
    pval_col = "pval.exp",
    clump_kb = clump_kb,
    clump_r2 = clump_r2,
    clump_p = clump_p,
    pop = if (identical(clump_mode, "api")) pop else NULL,
    bfile = if (nzchar(bfile)) bfile else NULL,
    plink_bin = if (nzchar(bfile) && nzchar(plink_bin)) plink_bin else NULL
  ), fallback = payload$api_clumping_fallback,
  record_path = file.path(execution_dir, "reports", "ld_clumping_reference.json")
)
clumped <- clump_result$data
clumping_reference <- clump_result$reference
clump_mode <- clumping_reference$mode
if (identical(clump_mode, "local_plink")) {
  bfile <- clumping_reference$bfile
  plink_bin <- clumping_reference$plink_bin
}
log_step(mrcat_ld_reference_summary(clumping_reference))
log_step("Completed clumping: retained rows=", nrow(clumped), ".")
log_step(
  "Shared MRdat construction used IV.Threshold=", iv_threshold,
  "; this threshold was used only to construct the shared MRdat."
)
adjusted_threshold_values <- if ("Threshold" %in% names(clumped)) suppressWarnings(as.numeric(clumped$Threshold)) else numeric()
adjusted_thresholds <- sort(unique(adjusted_threshold_values[is.finite(adjusted_threshold_values)]))
adjusted_threshold <- if (length(adjusted_thresholds) == 1) adjusted_thresholds[[1]] else NULL
threshold_text <- ifelse(is.null(adjusted_threshold), "null", adjusted_threshold)
pair_ancestry_text <- ifelse(nzchar(pair_ancestry), pair_ancestry, "unknown")
log_step(
  "MRdat$Threshold for downstream selection-bias correction=", threshold_text,
  "; this is not a clump threshold and is ignored by methods that do not consume it."
)
preview_cols <- intersect(c("SNP", "pval.exp", "Threshold"), names(clumped))
if (length(preview_cols) > 0) {
  preview <- utils::head(as.data.frame(clumped)[, preview_cols, drop = FALSE], 5)
  preview_text <- paste(utils::capture.output(print(preview)), collapse = " | ")
  log_step("Head of clumped MRdat columns [", paste(preview_cols, collapse = ","), "]: ", preview_text)
}

mrdat_path <- file.path(execution_dir, "intermediate", "gwas_pair_mrdat_clumped.tsv.gz")
log_step("Writing clumped MRdat: ", mrdat_path)
data.table::fwrite(clumped, mrdat_path, sep = "\t", quote = FALSE, na = "NA", compress = "gzip")
ldsc_rg <- if (!is.null(paras$ldsc_res) && !is.null(paras$ldsc_res$rg)) paras$ldsc_res$rg else NULL

result <- list(
  clumping_reference = clumping_reference,
  working_scale = "standardize",
  native_usable_rows = sum(is.finite(clumped$b.exp.native) & is.finite(clumped$b.out.native) & is.finite(clumped$se.exp.native) & is.finite(clumped$se.out.native) & clumped$se.exp.native > 0 & clumped$se.out.native > 0),
  mdat_path = normalizePath(mdat_path, winslash = "/", mustWork = FALSE),
  mrdat_path = normalizePath(mrdat_path, winslash = "/", mustWork = FALSE),
  c_path = normalizePath(c_path, winslash = "/", mustWork = FALSE),
  omega_path = normalizePath(omega_path, winslash = "/", mustWork = FALSE),
  ldsc_result_path = normalizePath(ldsc_result_path, winslash = "/", mustWork = FALSE),
  exposure_label = compact(payload$exposure_label),
  outcome_label = compact(payload$outcome_label),
  ancestry = pair_ancestry
)

record_path <- file.path(execution_dir, "reports", "gwas_pair_prepare_record.json")
jsonlite::write_json(result, record_path, auto_unbox = TRUE, pretty = TRUE, null = "null", digits = NA)
result$result_record_path <- normalizePath(record_path, winslash = "/", mustWork = FALSE)

clumping_reference_summary <- if (identical(clump_mode, "local_plink")) {
  paste0(
    "LD clumping used the local PLINK reference bfile=", bfile,
    " with plink_bin=", ifelse(nzchar(plink_bin), plink_bin, "null"),
    "; pop was not the active clumping-reference selector."
  )
} else {
  paste0(
    "LD clumping used the OpenGWAS API population reference pop=", pop,
    " because no local bfile was supplied; bfile and plink_bin were not used."
  )
}
reference_usage_summary <- paste0(
  mrcat_ld_reference_summary(clumping_reference), " ",
  "Reference usage: pair_ancestry=", pair_ancestry_text, ". ",
  clumping_reference_summary, " ",
  "LDSC background estimation independently used ldscore_dir=", ldscore_dir, ". ",
  "Final interpretation must compare both the clumping population/reference ",
  "and LDSC reference with pair_ancestry and report any mismatch as a limitation."
)

rendered <- list(
  summary = paste0(
    "Parameters used: pair_ancestry=", pair_ancestry_text,
    ", ldscore_dir=", ldscore_dir,
    ", M=", ifelse(is.null(M_value), "null", M_value),
    ", h2_fix_intercept=", h2_fix_intercept,
    ", iv_threshold=", iv_threshold,
    ", clump_r2=", clump_r2,
    ", clump_kb=", clump_kb,
    ", clump_p=", clump_p,
    ", clump_mode=", clump_mode,
    ", pop=", ifelse(identical(clump_mode, "api"), pop, "null"),
    ", bfile=", ifelse(identical(clump_mode, "local_plink"), bfile, "null"),
    ", plink_bin=", ifelse(identical(clump_mode, "local_plink") && nzchar(plink_bin), plink_bin, "null"),
    ", MRdat_selection_bias_threshold=", threshold_text,
    ". ", reference_usage_summary, " ",
    "gwas-pair-prepare completed: mdat_rows=", nrow(paras$dat),
    ", clumped_rows=", nrow(clumped),
    ", LDSC rg=", ifelse(is.null(ldsc_rg), "null", ldsc_rg),
    "; C=", result$c_path,
    "; Omega=", result$omega_path,
    "."
  ),
  outputs = list(status = "ok", gwas_pair_prepare_result = result),
  details = list(result_status = "ok", failure_class = NULL,
                 reference_usage = mrcat_ld_reference_summary(clumping_reference)),
  artifacts = list(
    list(path = result$mdat_path, kind = "tsv", summary = "Harmonized pair-level Mdat"),
    list(path = result$mrdat_path, kind = "tsv", summary = "Shared clumped MRdat"),
    list(path = result$c_path, kind = "tsv", summary = "Pair-level C background matrix"),
    list(path = result$omega_path, kind = "tsv", summary = "Pair-level Omega background matrix"),
    list(path = result$ldsc_result_path, kind = "json", summary = "Pair-level LDSC result")
  )
)
jsonlite::write_json(rendered, output_json, auto_unbox = TRUE, pretty = TRUE, null = "null", digits = NA)
log_step("Completed successfully.")
