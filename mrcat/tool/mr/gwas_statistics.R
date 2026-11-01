# Shared statistic definitions; selection P values remain source GWAS P values.
mr_numeric <- function(x) suppressWarnings(as.numeric(as.character(x)))

mr_native_statistics <- function(dat, beta_col = "beta", se_col = "se", or_col = "or") {
  read_col <- function(name) if (name %in% names(dat)) mr_numeric(dat[[name]]) else rep(NA_real_, nrow(dat))
  beta <- read_col(beta_col)
  se <- read_col(se_col)
  odds <- read_col(or_col)
  from_or <- !is.finite(beta) & is.finite(odds) & odds > 0
  beta[from_or] <- log(odds[from_or])
  # Canonical SE is the standard error of beta/log(OR), never log(SE).
  list(beta = beta, se = se, from_or = from_or)
}

mr_gwas_z <- function(z = NULL, p = NULL, beta = NULL, se = NULL) {
  # Column-level priority matches format_data; do not mix estimands row by row.
  if (!is.null(z)) return(mr_numeric(z))
  if (!is.null(p) && !is.null(beta)) return(sign(mr_numeric(beta)) * sqrt(qchisq(mr_numeric(p), 1, lower.tail = FALSE)))
  if (!is.null(beta) && !is.null(se)) return(mr_numeric(beta) / mr_numeric(se))
  stop("No signed statistics available to construct Z")
}

mr_gwas_n <- function(dat, override = NULL) {
  populated <- function(name) name %in% names(dat) && any(is.finite(mr_numeric(dat[[name]])))
  if (populated("n")) return(list(value = mr_numeric(dat$n), source = "n"))
  if (populated("n_cases") && populated("n_controls")) {
    return(list(value = mr_numeric(dat$n_cases) + mr_numeric(dat$n_controls), source = "n_cases+n_controls"))
  }
  n <- mr_numeric(override)
  if (length(n) == 1L && is.finite(n) && n > 0) return(list(value = rep(n, nrow(dat)), source = "sample_size_parameter"))
  list(value = rep(NA_real_, nrow(dat)), source = "unavailable")
}

mr_canonical_effects <- function(dat, scale, sample_size = NULL) {
  dat <- data.table::copy(data.table::as.data.table(dat))
  native <- mr_native_statistics(dat)
  populated <- function(key) key %in% names(dat) && any(is.finite(mr_numeric(dat[[key]])))
  get_stat <- function(key) if (populated(key)) mr_numeric(dat[[key]]) else NULL
  p <- get_stat("pval")
  neglog <- get_stat("neglog10_pval")
  if (is.null(p)) p <- rep(NA_real_, nrow(dat))
  from_neglog <- rep(FALSE, nrow(dat))
  if (!is.null(neglog)) {
    from_neglog <- !is.finite(p) & is.finite(neglog) & neglog >= 0
    p[from_neglog] <- 10^(-neglog[from_neglog])
  }
  n <- mr_gwas_n(dat, sample_size)
  n_values <- n$value
  dat[, `:=`(beta_native = native$beta, se_native = native$se, pval = p, n = n_values)]
  if (scale == "standardize") {
    working_z <- mr_gwas_z(get_stat("z"), if (any(is.finite(p))) p else NULL,
                   if (any(is.finite(native$beta))) native$beta else NULL,
                   if (any(is.finite(native$se))) native$se else NULL)
    dat[, `:=`(beta = working_z / sqrt(n_values), se = 1 / sqrt(n_values))]
    if (!any(is.finite(p))) dat[, pval := pchisq(working_z^2, 1, lower.tail = FALSE)]
  } else if (scale == "native") {
    dat[, `:=`(beta = native$beta, se = native$se)]
    if (!any(is.finite(p))) dat[, pval := pchisq((beta / se)^2, 1, lower.tail = FALSE)]
  } else stop("Unsupported canonical input_scale")
  identity_ok <- !is.na(dat$SNP) & nzchar(as.character(dat$SNP)) &
    !is.na(dat$effect_allele) & nzchar(as.character(dat$effect_allele)) &
    !is.na(dat$other_allele) & nzchar(as.character(dat$other_allele))
  usable <- identity_ok & is.finite(dat$pval) & dat$pval >= 0 & dat$pval <= 1 &
    is.finite(dat$beta) & is.finite(dat$se) & dat$se > 0
  if (scale == "standardize") usable <- usable & is.finite(dat$n) & dat$n > 0
  list(data = dat[usable], diagnostics = list(
    input_scale = scale, sample_size_source = n$source,
    canonical_rows = nrow(dat), usable_rows = sum(usable), excluded_rows = sum(!usable),
    native_beta_se_rows = sum(usable & is.finite(native$beta) & is.finite(native$se) & native$se > 0 & !native$from_or),
    or_derived_beta_rows = sum(usable & native$from_or),
    z_n_derived_beta_se_rows = if (scale == "standardize") sum(usable) else 0L,
    neglog10_derived_pval_rows = sum(usable & from_neglog)))
}
