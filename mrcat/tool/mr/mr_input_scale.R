# Apply a scale once, before IV selection. Cached pair tables retain both scales.
mr_input_scale <- function(value = NULL, allowed = c("standardize", "native"), default = "standardize") {
  scale <- if (is.null(value)) default else as.character(value)
  if (length(scale) != 1L || is.na(scale) || !(scale %in% allowed)) {
    stop(paste0("Unsupported input_scale; expected ", paste(allowed, collapse = " or ")))
  }
  scale
}

mr_apply_input_scale <- function(dat, scale, exposure_type = NULL, outcome_type = NULL) {
  scale <- mr_input_scale(scale, allowed = c("standardize", "native", "mrmix_standardize"))
  dat <- data.table::copy(data.table::as.data.table(dat))
  fields <- c("b.exp", "se.exp", "b.out", "se.out")
  native_fields <- c("b.exp.native", "se.exp.native", "b.out.native", "se.out.native")
  if (scale == "standardize") {
    # Prefer explicit Z/N. Old pair tables already store this working scale.
    if (all(c("Z.exp", "Z.out", "N.exp", "N.out") %in% names(dat))) {
      for (side in c("exp", "out")) {
        n <- as.numeric(dat[[paste0("N.", side)]])
        z <- as.numeric(dat[[paste0("Z.", side)]])
        n[!is.finite(n) | n <= 0] <- NA_real_
        data.table::set(dat, j = paste0("b.", side), value = z / sqrt(n))
        data.table::set(dat, j = paste0("se.", side), value = 1 / sqrt(n))
      }
    } else if ("input_scale" %in% names(dat) && any(dat$input_scale != "standardize", na.rm = TRUE)) {
      stop("Cannot standardize a previously selected table without Z and N; reuse the pair table")
    }
  } else {
    missing <- setdiff(native_fields, names(dat))
    if (length(missing)) stop("Native statistics unavailable; regenerate QC and pair preparation once")
    for (i in seq_along(fields)) data.table::set(dat, j = fields[i], value = as.numeric(dat[[native_fields[i]]]))
    if (scale == "mrmix_standardize") {
      for (side in c("exp", "out")) {
        type <- if (side == "exp") exposure_type else outcome_type
        if (length(type) != 1L || !(type %in% c("continuous", "binary"))) stop("MRMix requires explicit exposure_type and outcome_type (continuous or binary)")
        b <- dat[[paste0("b.", side)]]
        se <- dat[[paste0("se.", side)]]
        if (type == "continuous") {
          key <- paste0("N.", side)
          if (!(key %in% names(dat))) stop("MRMix continuous standardization requires explicit N")
          n <- as.numeric(dat[[key]])
          multiplier <- 1 / (se * sqrt(n))
          multiplier[!is.finite(n) | n <= 0 | !is.finite(se) | se <= 0] <- NA_real_
        } else {
          key <- paste0("freq.", side)
          if (!(key %in% names(dat))) stop("MRMix binary standardization requires observed allele frequency")
          freq <- as.numeric(dat[[key]])
          multiplier <- sqrt(2 * freq * (1 - freq))
          multiplier[!is.finite(freq) | freq <= 0 | freq >= 1] <- NA_real_
        }
        data.table::set(dat, j = paste0("b.", side), value = b * multiplier)
        data.table::set(dat, j = paste0("se.", side), value = se * multiplier)
      }
    }
  }
  if (!all(fields %in% names(dat))) stop("Missing effect statistics for requested input_scale")
  valid <- Reduce(`&`, lapply(fields, function(key) is.finite(as.numeric(dat[[key]])))) & dat$se.exp > 0 & dat$se.out > 0
  cat("[input-scale] ", scale, ": ", sum(valid), "/", nrow(dat), " rows have usable effects; no scale fallback\n", sep = "")
  dat[, input_scale := scale]
  data.table::setattr(dat, "scale_excluded_rows", sum(!valid))
  dat
}

mr_save_selected_input <- function(dat, execution_dir) {
  path <- file.path(execution_dir, "reports", "selected_mrdat.tsv")
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  data.table::fwrite(dat, path, sep = "\t", na = "NA")
  normalizePath(path, winslash = "/", mustWork = TRUE)
}
