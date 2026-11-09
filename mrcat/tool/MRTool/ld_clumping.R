# Transport failure is not evidence of an empty instrument set.
mrcat_opengwas_call <- function(call) {
  withCallingHandlers(call(), message = function(condition) {
    if (grepl("Server (code|error): 502|502 Bad Gateway|HTTP[^0-9]*502", conditionMessage(condition), ignore.case = TRUE)) {
      stop(structure(list(message = "OpenGWAS HTTP 502 Bad Gateway", call = NULL),
                     class = c("mrcat_opengwas_502", "error", "condition")))
    }
  })
}

mrcat_clump <- function(args, fallback = NULL, clump = MRAPSS::clump, record_path = NULL) {
  local <- !is.null(args$bfile) && nzchar(args$bfile)
  reference <- list(mode = if (local) "local_plink" else "api",
                    population = if (local) NULL else args$pop,
                    bfile = if (local) args$bfile else NULL,
                    plink_bin = if (local) args$plink_bin else NULL,
                    fallback_reason = NULL)
  result <- tryCatch(
    if (local) do.call(clump, args) else mrcat_opengwas_call(function() do.call(clump, args)),
    error = function(err) {
      if (local || !grepl("Server (code|error): 502|502 Bad Gateway|HTTP[^0-9]*502", conditionMessage(err), ignore.case = TRUE)) stop(err)
      if (is.null(fallback$bfile)) {
        reason <- if (is.null(fallback$unavailable_reason)) "No compatible local LD reference is available." else fallback$unavailable_reason
        stop(paste("OpenGWAS HTTP 502; local clumping fallback unavailable:", reason), call. = FALSE)
      }
      required <- paste0(fallback$bfile, c(".bed", ".bim", ".fam"))
      if (!all(file.exists(required)) || file.access(fallback$plink_bin, 1) != 0) {
        stop("OpenGWAS HTTP 502; local LD reference or PLINK is unavailable.", call. = FALSE)
      }
      local_args <- args
      local_args$pop <- NULL
      local_args$bfile <- fallback$bfile
      local_args$plink_bin <- fallback$plink_bin
      message("[LD fallback] OpenGWAS HTTP 502; switching clumping to ", fallback$resource_id,
              "; population=", fallback$population, "; build=", fallback$genome_build,
              "; bfile=", fallback$bfile, "; analysis thresholds unchanged.")
      value <- do.call(clump, local_args)
      reference <<- c(list(mode = "local_plink", fallback_reason = "OpenGWAS HTTP 502"), fallback)
      value
    }
  )
  if (!is.null(record_path)) {
    jsonlite::write_json(list(reference = reference, summary = mrcat_ld_reference_summary(reference)),
                        record_path, auto_unbox = TRUE, pretty = TRUE, null = "null")
  }
  list(data = result, reference = reference)
}

mrcat_ld_reference_summary <- function(reference) {
  values <- reference[!vapply(reference, is.null, logical(1))]
  paste0("LD reference used: ", paste(paste0(names(values), "=", unlist(values)), collapse = "; "), ".")
}
