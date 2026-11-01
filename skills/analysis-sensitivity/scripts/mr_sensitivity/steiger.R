# Steiger diagnostics use explicit trait metadata and the original selected SNPs.
# Missing data never become reassuring results or silently remove instruments.
steiger_trait <- function(selected, meta, side) {
  if (!is.list(meta) || !identical(meta$type, "quantitative") && !identical(meta$type, "binary")) {
    stop(paste0(side, ": specify type as quantitative or binary"))
  }
  values <- function(value, label) {
    if (is.character(value) && length(value) == 1 && value %in% names(selected)) {
      value <- selected[[value]]
    }
    value <- suppressWarnings(as.numeric(unlist(value)))
    if (length(value) == 1) value <- rep(value, nrow(selected))
    if (length(value) != nrow(selected) || any(!is.finite(value))) {
      stop(paste0(side, ": missing or invalid ", label, " for selected SNPs"))
    }
    value
  }
  if (identical(meta$type, "quantitative")) {
    n_source <- if (is.null(meta$sample_size)) paste0("N.", side) else meta$sample_size
    n <- values(n_source, "sample_size")
    if (any(n <= 3)) stop(paste0(side, ": sample_size must exceed 3"))
    b <- values(paste0("b.", side), "beta")
    se <- values(paste0("se.", side), "SE")
    if (any(se <= 0)) stop(paste0(side, ": SE must be positive"))
    r <- TwoSampleMR::get_r_from_bsen(b, se, n)
    provenance <- list(type = meta$type, correlation_method = "get_r_from_bsen",
                       sample_size = n_source, beta_column = paste0("b.", side),
                       se_column = paste0("se.", side))
  } else {
    if (!identical(meta$beta_scale, "log_odds")) {
      stop(paste0(side, ": binary traits require explicit beta_scale=log_odds for native beta"))
    }
    if (!is.character(meta$eaf_column) || length(meta$eaf_column) != 1 ||
        !meta$eaf_column %in% names(selected)) {
      stop(paste0(side, ": binary traits require an explicitly identified aligned eaf_column"))
    }
    b <- values(paste0("b.", side, ".native"), "native log-odds beta")
    af <- values(meta$eaf_column, "effect allele frequency")
    cases <- values(meta$ncase, "ncase")
    controls <- values(meta$ncontrol, "ncontrol")
    prevalence <- values(meta$prevalence, "population prevalence")
    if (any(af <= 0 | af >= 1 | prevalence <= 0 | prevalence >= 1 |
            cases <= 0 | controls <= 0)) stop(paste0(side, ": invalid binary trait metadata"))
    r <- TwoSampleMR::get_r_from_lor(b, af, cases, controls, prevalence)
    n <- TwoSampleMR::effective_n(cases, controls)
    if (any(n <= 3)) stop(paste0(side, ": effective sample size must exceed 3"))
    provenance <- list(type = meta$type, correlation_method = "get_r_from_lor",
                       beta_column = paste0("b.", side, ".native"),
                       eaf_column = meta$eaf_column, ncase = meta$ncase,
                       ncontrol = meta$ncontrol, prevalence = meta$prevalence,
                       sample_size_method = "TwoSampleMR::effective_n")
  }
  if (any(!is.finite(r) | abs(r) >= 1)) stop(paste0(side, ": invalid SNP-trait correlations"))
  list(r = abs(r), n = n, provenance = provenance)
}

run_steiger <- function(selected, metadata, filter_requested, dat, execution_dir, seed) {
  reports <- list()
  filtering <- list(requested = filter_requested, status = if (filter_requested) "blocked" else "not_requested")
  unavailable <- function(reason) {
    list(result = list(status = "unavailable", reason = reason,
                       nsnp = nrow(selected), filtering = filtering), reports = reports)
  }
  prepared <- tryCatch({
    if (anyDuplicated(selected$SNP)) stop("Steiger requires unique selected SNP identifiers")
    x <- steiger_trait(selected, metadata$exposure, "exp")
    y <- steiger_trait(selected, metadata$outcome, "out")
    if (sum(x$r^2) >= 1 || sum(y$r^2) >= 1) stop("Summed SNP R-squared must be below 1; check LD and input metadata")
    list(x = x, y = y)
  }, error = function(e) conditionMessage(e))
  if (is.character(prepared)) return(unavailable(prepared))
  x <- prepared$x
  y <- prepared$y
  computed <- tryCatch({
    d <- dat
    d$r.exposure <- x$r
    d$r.outcome <- y$r
    d$rsq.exposure <- x$r^2
    d$rsq.outcome <- y$r^2
    d$samplesize.exposure <- d$effective_n.exposure <- x$n
    d$samplesize.outcome <- d$effective_n.outcome <- y$n
    # All correlations are supplied; no automatic quantitative-trait fallback.
    d$pval.exposure <- d$pval.outcome <- NA_real_
    overall <- TwoSampleMR::directionality_test(d)
    per_snp <- TwoSampleMR::steiger_filtering(d)
    if (nrow(overall) != 1 || !is.finite(overall$steiger_pval) ||
        any(!is.finite(per_snp$steiger_pval))) stop("Steiger returned non-finite test results")
    list(overall = overall, per_snp = per_snp)
  }, error = function(e) conditionMessage(e))
  if (is.character(computed)) return(unavailable(computed))
  overall <- computed$overall
  per_snp <- computed$per_snp
  save_table <- function(table, name) {
    path <- file.path(execution_dir, "reports", paste0("sensitivity_steiger_", name, ".tsv"))
    data.table::fwrite(table, path, sep = "\t", quote = FALSE, na = "NA")
    normalizePath(path, winslash = "/", mustWork = TRUE)
  }
  reports$steiger_summary <- save_table(overall, "summary")
  snps <- data.frame(SNP = selected$SNP, r2_exposure = x$r^2, r2_outcome = y$r^2,
                     effective_n_exposure = x$n, effective_n_outcome = y$n,
                     steiger_dir = per_snp$steiger_dir, steiger_pval = per_snp$steiger_pval)
  reports$steiger_snps <- save_table(snps, "snps")
  keep <- per_snp$steiger_dir
  if (filter_requested) {
    filtered <- data.table::copy(selected[which(keep), ])
    reports$steiger_filtered_mrdat <- save_table(filtered, "filtered_mrdat")
    filtering <- list(requested = TRUE, status = "blocked", rule = "r2_exposure > r2_outcome",
                      nsnp_before = nrow(selected), nsnp_retained = sum(keep),
                      nsnp_removed = sum(!keep), removed_snps = as.list(selected$SNP[!keep]),
                      selected_mrdat_path = reports$steiger_filtered_mrdat,
                      input_scale = as.character(selected$input_scale[[1]]))
    if (sum(keep) < 4) {
      filtering$reason <- "Fewer than four SNPs remain; the four-method primary refit was not run"
    } else {
      set.seed(seed)
      methods <- c("mr_ivw", "mr_egger_regression", "mr_weighted_median", "mr_weighted_mode")
      fits <- tryCatch(TwoSampleMR::mr(dat[keep, , drop = FALSE], method_list = methods),
                       error = function(e) conditionMessage(e))
      if (is.character(fits)) {
        filtering$reason <- fits
      } else {
        fits$lo_ci <- fits$b - stats::qnorm(0.975) * fits$se
        fits$up_ci <- fits$b + stats::qnorm(0.975) * fits$se
        reports$steiger_filtered_mr <- save_table(fits, "filtered_mr")
        filtering$estimates_path <- reports$steiger_filtered_mr
        filtering$estimates <- lapply(seq_len(nrow(fits)), function(i) as.list(fits[i, ]))
        valid <- is.finite(fits$b) & is.finite(fits$se) & fits$se > 0 & is.finite(fits$pval)
        filtering$status <- if (nrow(fits) == length(methods) && all(valid)) "ok" else "partial"
        if (filtering$status == "partial") filtering$reason <- "Some requested estimators did not return finite estimates"
      }
    }
  }
  p <- overall$steiger_pval[[1]]
  forward <- overall$correct_causal_direction[[1]]
  interpretation <- if (p >= 0.05) "inconclusive" else if (forward) "supports_exposure_to_outcome" else "supports_outcome_to_exposure"
  list(result = list(status = "ok", nsnp = nrow(selected),
                     r2_exposure = overall$snp_r2.exposure[[1]],
                     r2_outcome = overall$snp_r2.outcome[[1]],
                     correct_causal_direction = forward, steiger_pval = p,
                     interpretation = interpretation, alpha = 0.05,
                     forward_snp_count = sum(keep), reverse_or_equal_snp_count = sum(!keep),
                     exposure = x$provenance, outcome = y$provenance,
                     sample_size_aggregation = "Mean per-SNP effective N for the overall test",
                     filtering = filtering), reports = reports)
}
