# Adapted from local MRbenchmarking/Rfuncs/mr_lasso.R.

ci_normal <- function(type, mean, se, alpha) {
  x <- 1 - alpha / 2
  if (type == "l") return(mean - qnorm(x) * se)
  if (type == "u") return(mean + qnorm(x) * se)
  NA_real_
}

ci_t <- function(type, mean, se, df, alpha) {
  x <- 1 - alpha / 2
  if (type == "l") return(mean - qt(x, df = df) * se)
  if (type == "u") return(mean + qt(x, df = df) * se)
  NA_real_
}

mr_lasso <- function(snps, Bx, By, Bxse, Byse, distribution = "normal", alpha = 0.05,
                     lambda = c(seq(from = 0.01, to = 2, by = 0.01), seq(from = 2.2, to = 10, by = 0.2))) {
  if (!requireNamespace("glmnet", quietly = TRUE)) {
    stop("MR-Lasso requires the glmnet R package")
  }
  nsnps <- length(Bx)
  if (!(distribution %in% c("normal", "t-dist"))) {
    stop("distribution must be one of: normal, t-dist")
  }

  orientation <- ifelse(Bx < 0, -1, 1)
  Bx <- Bx * orientation
  By <- By * orientation

  S <- diag(Byse^-2)
  b <- S^(1 / 2) %*% Bx
  Pb <- b %*% solve(t(b) %*% b, t(b))
  xlas <- (diag(nsnps) - Pb) %*% S^(1 / 2)
  ylas <- (diag(nsnps) - Pb) %*% S^(1 / 2) %*% By

  if (length(lambda) != 0) {
    las_fit <- glmnet::glmnet(xlas, ylas, intercept = FALSE, lambda = lambda)
    las_mod <- list(fit = las_fit$beta[, 1], lambda = lambda)
  } else {
    las_fit <- glmnet::glmnet(xlas, ylas, intercept = FALSE)
    lamseq <- sort(las_fit$lambda)
    lamlen <- length(lamseq)
    rse <- sapply(seq_len(lamlen), function(j) {
      av <- which(las_fit$beta[, (lamlen - j + 1)] == 0)
      if (length(av) <= 1) {
        return(c(NA_real_, length(av)))
      }
      mod <- lm(S[av, av]^(1 / 2) %*% By[av] ~ S[av, av]^(1 / 2) %*% Bx[av] - 1)
      c(sqrt(t(mod$residuals) %*% (mod$residuals) / (mod$df.residual)), length(av))
    })
    rse_inc <- rse[1, 2:lamlen] - rse[1, 1:(lamlen - 1)]
    het <- which(rse[1, 2:lamlen] > 1 & rse_inc > (qchisq(0.95, 1) / rse[2, 2:lamlen]))
    if (length(het) == 0) {
      lam_pos <- lamlen
    } else {
      lam_pos <- min(het)
    }
    num_valid <- rse[2, ]
    estimable_lam_pos <- which(num_valid > 1 & is.finite(rse[1, ]))
    if (length(estimable_lam_pos) == 0) {
      stop("MR-Lasso heterogeneity path contains fewer than two valid instruments")
    }
    min_lam_pos <- min(estimable_lam_pos)
    if (lam_pos < min_lam_pos) lam_pos <- min_lam_pos
    las_mod <- list(fit = las_fit$beta[, (lamlen - lam_pos + 1)], lambda = lamseq[lam_pos])
  }

  a <- las_mod$fit
  e <- By - a
  est <- solve(t(Bx) %*% S %*% Bx, t(Bx) %*% S %*% e)
  valid <- which(a == 0)
  if (length(valid) > 1) {
    post_mod <- summary(lm(By[valid] ~ Bx[valid] - 1, weights = Byse[valid]^-2))
    post_est <- post_mod$coef[, 1]
    post_se <- post_mod$coef[, 2] / min(post_mod$sigma, 1)
  } else {
    post_est <- NA_real_
    post_se <- NA_real_
  }

  if (distribution == "normal") {
    ciLower <- ci_normal("l", post_est, post_se, alpha)
    ciUpper <- ci_normal("u", post_est, post_se, alpha)
    pvalue <- 2 * pnorm(-abs(post_est / post_se))
  } else {
    ciLower <- ci_t("l", post_est, post_se, length(valid) - 1, alpha)
    ciUpper <- ci_t("u", post_est, post_se, length(valid) - 1, alpha)
    pvalue <- 2 * pt(-abs(post_est / post_se), df = length(valid) - 1)
  }

  list(
    Estimate = as.numeric(post_est),
    StdError = as.numeric(post_se),
    CILower = as.numeric(ciLower),
    CIUpper = as.numeric(ciUpper),
    Alpha = alpha,
    Pvalue = as.numeric(pvalue),
    SNPs = nsnps,
    RegEstimate = as.numeric(est),
    RegIntercept = as.numeric(a),
    Valid = length(valid),
    ValidSNPs = as.character(snps[valid]),
    Lambda = las_mod$lambda
  )
}
