fit_primary <- function(selected, threshold) {
  rows <- list()
  nsnp <- nrow(selected)
  fitters <- list(
    IVW = TwoSampleMR::mr_ivw,
    "MR-Egger" = TwoSampleMR::mr_egger_regression,
    "Weighted median" = TwoSampleMR::mr_weighted_median,
    "Weighted mode" = TwoSampleMR::mr_weighted_mode
  )

  for (method in names(fitters)) {
    log_step("Fitting method: ", method, ".")
    fit <- try(
      fitters[[method]](selected$b.exp, selected$b.out, selected$se.exp, selected$se.out),
      silent = TRUE
    )
    if (!inherits(fit, "try-error") && !is.null(fit)) {
      rows[[length(rows) + 1]] <- list(
        method = method,
        Threshold = threshold,
        nsnp = as.integer(nsnp),
        "beta.hat" = num_or_null(fit$b),
        se = num_or_null(fit$se),
        pval = num_or_null(fit$pval),
        ci = mr_primary_ci(fit$b, fit$se, method, fit$nsnp)
      )
      log_step(
        "Completed method: ", method,
        "; beta=", num_or_null(fit$b),
        "; se=", num_or_null(fit$se),
        "; pval=", num_or_null(fit$pval), "."
      )
    } else {
      log_step("Method failed: ", method, "; error=", paste(as.character(fit), collapse = " "), ".", .error = TRUE)
    }
  }

  if (length(rows) == 0) {
    stop("no primary method returned a result")
  }
  rows
}
