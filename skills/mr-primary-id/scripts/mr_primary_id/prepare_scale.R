# Preserve native harmonized data and diagnose conversion before SNP selection.
id_sample_sizes <- function(dat, side, payload) {
  column <- function(prefix) {
    key <- paste0(prefix, ".", side)
    if (key %in% names(dat)) mr_numeric(dat[[key]]) else rep(NA_real_, nrow(dat))
  }
  sizes <- data.frame(n = column("samplesize"), n_cases = column("ncase"), n_controls = column("ncontrol"))
  mr_gwas_n(sizes, payload[[paste0(side, "_sample_size")]])
}

resolve_id_sample_sizes <- function(dat, payload, lookup) {
  result <- list(data = dat, metadata = NULL, resolved = list(), error = NULL)
  needed <- list()
  for (side in c("exposure", "outcome")) {
    n <- id_sample_sizes(dat, side, payload)$value
    id <- payload[[paste0(side, "_gwas_id")]]
    if (any(!is.finite(n) | n <= 0) && is.null(payload[[paste0(side, "_sample_size")]]) &&
        length(id) == 1L && !is.na(id) && nzchar(id)) needed[[side]] <- id
  }
  if (!length(needed)) return(result)
  metadata <- tryCatch(lookup(unique(unlist(needed))), error = function(e) e)
  if (inherits(metadata, "error")) {
    result$error <- conditionMessage(metadata)
    return(result)
  }
  result$metadata <- metadata
  if (!is.data.frame(metadata) || !"id" %in% names(metadata)) {
    result$error <- "Study metadata lacks an explicit study ID column."
    return(result)
  }
  for (side in names(needed)) {
    matched <- which(!is.na(metadata$id) & as.character(metadata$id) == needed[[side]])
    if (length(matched) != 1L) next
    row <- metadata[matched, , drop = FALSE]
    value <- function(key) if (key %in% names(row)) mr_numeric(row[[key]]) else NA_real_
    n <- value("sample_size")
    source <- "sample_size"
    if (!is.finite(n) || n <= 0) {
      counts <- c(value("ncase"), value("ncontrol"))
      n <- if (all(is.finite(counts) & counts > 0)) sum(counts) else NA_real_
      source <- "ncase+ncontrol"
    }
    if (!is.finite(n) || n <= 0) next
    existing <- id_sample_sizes(dat, side, payload)$value
    missing <- !is.finite(existing) | existing <= 0
    existing[missing] <- n
    result$data[[paste0("samplesize.", side)]] <- existing
    result$resolved[[side]] <- list(study_id = needed[[side]], sample_size = n,
                                   source = source, filled_rows = sum(missing))
  }
  result
}

prepare_id_scale <- function(dat, input_scale, payload) {
  diagnostics <- list()
  fail <- function(side, reason, rows) list(
    data = dat, diagnostics = diagnostics,
    error = list(side = side, reason = reason, invalid_rows = sum(rows),
                 example_snps = head(as.character(dat$SNP[rows]), 5L)))
  for (side in c("exposure", "outcome")) {
    b_key <- paste0("beta.", side)
    se_key <- paste0("se.", side)
    dat[[paste0("beta_native.", side)]] <- dat[[b_key]]
    dat[[paste0("se_native.", side)]] <- dat[[se_key]]
    if (input_scale == "standardize") {
      n <- id_sample_sizes(dat, side, payload)
      diagnostics[[side]] <- list(sample_size_source = n$source)
      bad_n <- !is.finite(n$value) | n$value <= 0
      if (any(bad_n)) return(fail(side, "missing_or_invalid_sample_size", bad_n))
      z <- mr_gwas_z(p = dat[[paste0("pval.", side)]], beta = dat[[b_key]], se = dat[[se_key]])
      if (any(!is.finite(z))) return(fail(side, "invalid_signed_statistic", !is.finite(z)))
      dat[[b_key]] <- z / sqrt(n$value)
      dat[[se_key]] <- 1 / sqrt(n$value)
    }
    invalid <- !is.finite(dat[[b_key]]) | !is.finite(dat[[se_key]]) | dat[[se_key]] <= 0
    if (any(invalid)) return(fail(side, "invalid_effect_or_uncertainty", invalid))
  }
  list(data = dat, diagnostics = diagnostics, error = NULL)
}
