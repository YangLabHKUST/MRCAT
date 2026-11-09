# Match effect intervals to the reference distribution used by the estimator.
mr_ci_from_se <- function(beta, se, df = NULL, level = 0.95) {
  beta <- suppressWarnings(as.numeric(beta)[1])
  se <- suppressWarnings(as.numeric(se)[1])
  valid <- length(beta) == 1L && is.finite(beta) &&
    length(se) == 1L && is.finite(se) && se > 0
  if (!is.null(df)) valid <- valid && length(df) == 1L && is.finite(df) && df > 0
  ranges <- list()
  if (valid) {
    critical <- if (is.null(df)) stats::qnorm((1 + level) / 2) else stats::qt((1 + level) / 2, df)
    ranges <- list(list(lower = beta - critical * se, upper = beta + critical * se))
  }
  list(level = level, ranges = ranges)
}

mr_primary_ci <- function(beta, se, method, nsnp) {
  key <- gsub("[^a-z]", "", tolower(method))
  df <- switch(key, mregger = nsnp - 2, weightedmode = nsnp - 1, NULL)
  mr_ci_from_se(beta, se, df)
}

mr_ci_bounds <- function(ci) {
  if (!length(ci$ranges)) return(c(lower = NA_real_, upper = NA_real_))
  c(lower = ci$ranges[[1]]$lower, upper = ci$ranges[[1]]$upper)
}
