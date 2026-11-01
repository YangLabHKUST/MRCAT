mr_format_number <- function(x, digits = 6) {
  value <- suppressWarnings(as.numeric(x)[1])
  if (length(value) == 0 || !is.finite(value)) return("NA")
  format(value, digits = digits, scientific = TRUE, trim = TRUE)
}

mr_valid_instrument_mask <- function(mrdat) {
  is.finite(mrdat$pval.exp) &
    is.finite(mrdat$b.exp) &
    is.finite(mrdat$b.out) &
    is.finite(mrdat$se.exp) &
    is.finite(mrdat$se.out) &
    mrdat$b.exp != 0 &
    mrdat$se.exp > 0 &
    mrdat$se.out > 0
}

mr_attempts_text <- function(attempts) {
  paste(
    vapply(
      attempts,
      function(item) paste0("p<=", mr_format_number(item$threshold), " retained ", item$nsnp),
      character(1)
    ),
    collapse = " -> "
  )
}

mr_strength_text <- function(selection) {
  if (selection$nsnp == 0 || length(selection$f_values) == 0) {
    return("approximate per-SNP F=(b.exp/se.exp)^2 unavailable because no candidate instruments were retained")
  }
  values <- selection$f_values[is.finite(selection$f_values)]
  if (length(values) == 0) {
    return("approximate per-SNP F=(b.exp/se.exp)^2 unavailable because exposure standard errors were invalid")
  }
  paste0(
    "approximate per-SNP F=(b.exp/se.exp)^2: min=", mr_format_number(min(values)),
    ", median=", mr_format_number(stats::median(values)),
    ", mean=", mr_format_number(mean(values)),
    ", max=", mr_format_number(max(values)),
    ", F<10=", sum(values < 10), "/", length(values)
  )
}

mr_selection_summary <- function(selection, min_instruments) {
  path_text <- mr_attempts_text(selection$attempts)
  if (!isTRUE(selection$passed)) {
    return(paste0(
      "method-level pvalue_threshold path on already-clumped MRdat: ", path_text,
      "; no attempted threshold reached min_instruments=", min_instruments,
      ". Analysis blocked; use a stronger or larger exposure GWAS dataset"
    ))
  }

  selection_note <- if (isTRUE(selection$relaxed)) {
    paste0(
      "method-level pvalue_threshold relaxed from p<=", mr_format_number(selection$initial_threshold),
      " to p<=", mr_format_number(selection$threshold),
      "; this result uses an exploratory instrument-selection threshold"
    )
  } else {
    paste0("selected at the requested method-level pvalue_threshold p<=", mr_format_number(selection$initial_threshold))
  }
  if (selection$weak_count > 0) {
    selection_note <- paste0(
      selection_note, "; ", selection$weak_count, "/", selection$nsnp,
      " instruments have F<10, indicating weak-instrument bias risk"
    )
  } else {
    selection_note <- paste0(selection_note, "; no selected instruments have F<10")
  }

  paste0(
    "method-level pvalue_threshold path on already-clumped MRdat: ", path_text,
    "; selected p<=", mr_format_number(selection$threshold),
    " with nsnp=", selection$nsnp,
    " (min_instruments=", min_instruments, "); ",
    mr_strength_text(selection), "; selection note: ", selection_note
  )
}

mr_selection_recommendations <- function(selection) {
  recommendations <- list()
  if (isTRUE(selection$relaxed)) {
    recommendations <- c(
      recommendations,
      paste0(
        "The method-level instrument pvalue_threshold was relaxed from p<=",
        mr_format_number(selection$initial_threshold), " to p<=",
        mr_format_number(selection$threshold),
        ". Report this exploratory selection and assess instrument strength and sensitivity diagnostics when interpreting the estimate."
      )
    )
  }
  if (selection$weak_count > 0) {
    recommendations <- c(
      recommendations,
      paste0(
        selection$weak_count, " of ", selection$nsnp,
        " selected instruments have approximate F<10. Interpret the estimate cautiously because of weak-instrument bias risk."
      )
    )
  }
  recommendations
}

mr_select_instruments <- function(mrdat, initial_threshold, min_instruments, log_step) {
  threshold <- suppressWarnings(as.numeric(initial_threshold)[1])
  if (length(threshold) == 0 || !is.finite(threshold) || threshold <= 0 || threshold > 1) {
    stop("pvalue_threshold must be a finite number in (0, 1].")
  }
  valid_mask <- mr_valid_instrument_mask(mrdat)
  selected_indices <- which(valid_mask & mrdat$pval.exp <= threshold)
  selected <- mrdat[selected_indices, ]
  selected_threshold <- threshold
  nsnp <- nrow(selected)
  passed <- nsnp >= min_instruments
  attempts <- list(list(threshold = threshold, nsnp = as.integer(nsnp)))
  log_step("Instrument selection: pval.exp <= ", mr_format_number(threshold),
           "; valid instruments=", nsnp, "; minimum required=", min_instruments,
           "; action=", if (passed) "selected" else "blocked", ".")

  f_values <- suppressWarnings((as.numeric(selected$b.exp) / as.numeric(selected$se.exp))^2)
  labels <- if ("SNP" %in% names(selected)) {
    as.character(selected$SNP)
  } else {
    paste0("row_", selected_indices)
  }
  weak_count <- sum(is.finite(f_values) & f_values < 10)
  selection <- list(
    selected = selected,
    threshold = selected_threshold,
    initial_threshold = threshold,
    nsnp = as.integer(nrow(selected)),
    passed = passed,
    relaxed = FALSE,
    attempts = attempts,
    f_values = f_values,
    weak_count = as.integer(weak_count)
  )

  if (passed) {
    for (index in seq_along(f_values)) {
      log_step(
        "Instrument strength: SNP=", labels[[index]],
        "; F=", mr_format_number(f_values[[index]]),
        "; pval.exp=", mr_format_number(selected$pval.exp[[index]]), "."
      )
    }
    log_step("Instrument strength summary: ", mr_strength_text(selection), ".")
    if (selection$relaxed || selection$weak_count > 0) {
      log_step("Instrument selection note: ", sub("^.*; selection note: ", "", mr_selection_summary(selection, min_instruments)), ".")
    }
  }
  selection
}
