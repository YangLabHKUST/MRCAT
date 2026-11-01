# Preserve the author package's decisions and Monte Carlo P-value bounds.
mr_presso_simulations <- function(nsnp, requested, alpha) {
  if (length(nsnp) != 1L || !is.finite(nsnp) || nsnp < 4 ||
      length(requested) != 1L || !is.finite(requested) || requested < 1 ||
      length(alpha) != 1L || !is.finite(alpha) || alpha <= 0 || alpha >= 1) {
    stop("Invalid MR-PRESSO instrument count, simulation count or significance threshold.")
  }
  # Bonferroni-adjusted Monte Carlo resolution is nsnp / NbDistribution.
  used <- max(requested, ceiling(nsnp / alpha) + 1)
  if (used > .Machine$integer.max) stop("Required MR-PRESSO simulation count exceeds the supported integer range.")
  as.integer(used)
}

mr_presso_check_input <- function(dat) {
  fields <- c("b.exp", "b.out", "se.exp", "se.out")
  if (!all(fields %in% names(dat)) ||
      any(!vapply(dat[fields], function(x) all(is.finite(x)), logical(1))) ||
      any(dat$se.exp <= 0 | dat$se.out <= 0)) {
    stop("MR-PRESSO requires finite effects and positive SEs on every input row; do not silently drop rows before mapping outlier indices.")
  }
}

mr_presso_pvalue <- function(value) {
  if (is.null(value) || length(value) == 0L) return(NULL)
  if (length(value) != 1L) stop("Expected a scalar MR-PRESSO P value.")
  if (is.na(value)) return(NULL)
  text <- trimws(as.character(value))
  if (text %in% c("", "NA", "NaN")) return(NULL)
  number <- suppressWarnings(as.numeric(sub("^(<=|>=|<|>)\\s*", "", text)))
  if (!is.finite(number) || number < 0 || number > 1) {
    stop(paste("Invalid MR-PRESSO P value:", text))
  }
  if (grepl("^[<>]", text)) text else number
}

mr_presso_detected <- function(value, alpha) {
  value <- mr_presso_pvalue(value)
  if (is.null(value)) return(NULL)
  if (is.numeric(value)) return(value < alpha)
  bound <- as.numeric(sub("^(<=|>=|<|>)\\s*", "", value))
  if (startsWith(value, "<=")) return(if (bound < alpha) TRUE else NULL)
  if (startsWith(value, "<")) return(if (bound <= alpha) TRUE else NULL)
  if (bound >= alpha) return(FALSE)
  NULL
}

mr_presso_extract <- function(fit, selected_df, alpha) {
  mr_presso_check_input(selected_df)
  tests <- fit[["MR-PRESSO results"]]
  if (!is.list(tests) || is.null(tests[["Global Test"]])) {
    stop("MR-PRESSO returned no global test.")
  }
  global <- tests[["Global Test"]]
  outlier <- tests[["Outlier Test"]]
  distortion <- tests[["Distortion Test"]]
  indices <- integer()
  status <- "not_tested"
  if (!is.null(outlier)) {
    raw_indices <- distortion[["Outliers Indices"]]
    if (is.null(raw_indices)) {
      stop("MR-PRESSO returned an outlier test without Outliers Indices; cannot reconstruct decisions from formatted P values.")
    }
    if (identical(raw_indices, "No significant outliers")) {
      status <- "none"
    } else if (identical(raw_indices, "All SNPs considered as outliers")) {
      indices <- seq_len(nrow(selected_df))
      status <- "all"
    } else {
      if (!is.numeric(raw_indices) || !length(raw_indices) ||
          any(!is.finite(raw_indices)) || any(raw_indices != floor(raw_indices)) ||
          any(raw_indices < 1 | raw_indices > nrow(selected_df)) ||
          anyDuplicated(raw_indices)) {
        stop("MR-PRESSO returned invalid Outliers Indices.")
      }
      indices <- as.integer(raw_indices)
      status <- "detected"
    }
    if (!is.data.frame(outlier) || nrow(outlier) != nrow(selected_df) ||
        !identical(rownames(outlier), rownames(selected_df)) ||
        !("Pvalue" %in% names(outlier))) {
      stop("MR-PRESSO outlier table does not match the fitted input rows.")
    }
  }
  main <- fit[["Main MR results"]]
  corrected <- if (is.data.frame(main) && "MR Analysis" %in% names(main)) {
    main[main[["MR Analysis"]] == "Outlier-corrected", "Causal Estimate"]
  } else numeric()
  if (any(is.finite(corrected)) && !(status == "detected")) {
    stop("MR-PRESSO corrected estimate contradicts the returned outlier indices.")
  }
  labels <- if ("SNP" %in% names(selected_df)) as.character(selected_df$SNP) else rownames(selected_df)
  snps <- labels[indices]
  list(
    global_pval = mr_presso_pvalue(global[["Pvalue"]]),
    global_rss = global[["RSSobs"]],
    global_detected = mr_presso_detected(global[["Pvalue"]], alpha),
    outlier_status = status,
    outlier_indices = indices,
    outlier_snps = snps,
    outlier_count = if (status == "not_tested") NULL else length(indices),
    outlier_rows = lapply(seq_along(indices), function(i) {
      list(snp = snps[[i]], pval = mr_presso_pvalue(outlier$Pvalue[[indices[[i]]]]))
    }),
    distortion_pval = mr_presso_pvalue(distortion[["Pvalue"]]),
    distortion_detected = mr_presso_detected(distortion[["Pvalue"]], alpha),
    distortion_coefficient = distortion[["Distortion Coefficient"]]
  )
}
