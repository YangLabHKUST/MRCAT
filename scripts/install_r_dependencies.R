# Run after activating mrcat. --check loads packages without installing anything.
args <- commandArgs(trailingOnly = TRUE)
if (length(setdiff(args, "--check"))) stop("Usage: Rscript scripts/install_r_dependencies.R [--check]")
check_only <- "--check" %in% args
lib <- .Library
if (!dir.exists(lib)) stop("R library does not exist: ", lib)
# Do not silently satisfy requirements from a user's unrelated R installation.
.libPaths(lib, include.site = FALSE)
options(repos = c(MRCIEU = "https://mrcieu.r-universe.dev", CRAN = "https://cloud.r-project.org"),
        timeout = 600)
cran <- c("data.table", "jsonlite", "ggplot2", "glmnet", "robustbase", "remotes", "MendelianRandomization")
# Commits match the working development environment; transitive dependencies
# are resolved by the upstream repositories rather than claimed to be locked.
github <- c(
  TwoSampleMR = "MRCIEU/TwoSampleMR@5121e4ecd08a7331b72ff0cdaa33d96d18ae069b",
  MRAPSS = "YangLabHKUST/MR-APSS@ef6afd2b4dd4923722cb74c4a5fd20dd41ed0510",
  MRcML = "xue-hr/MRcML@58a3481976093175cbb82a5e6bf06c10e3c576f2",
  mr.raps = "qingyuanzhao/mr.raps@dd79b5bd74d10b699503cdd226d70c726f11c796",
  MRPRESSO = "rondolab/MR-PRESSO@3e3c92d7eda6dce0d1d66077373ec0f7ff4f7e87",
  MRMix = "gqi/MRMix@56afdb2bc96760842405396f5d3f02e60e305039",
  cause = "jean997/cause@6257e6c66e6c1518c8750d1e4d2b4d6e42644fa5",
  mr.divw = "tye27/mr.divw"
)
loadable <- function(pkg) {
  tryCatch(requireNamespace(pkg, quietly = TRUE), error = function(e) FALSE)
}
if (!check_only) {
  missing <- cran[!vapply(cran, loadable, logical(1))]
  if (length(missing)) install.packages(missing, lib = lib)
  if (!loadable("remotes")) stop("Install the remotes package before continuing.")
  for (pkg in names(github)) {
    if (!loadable(pkg)) {
      remotes::install_github(github[[pkg]], lib = lib, upgrade = "never",
                              dependencies = NA, build_vignettes = FALSE)
    }
  }
}
required <- c(cran, names(github))
bwmr_source <- Sys.getenv("MRCAT_BWMR_SOURCE", unset = "")
if (!nzchar(bwmr_source)) bwmr_source <- file.path(lib, "mrcat-methods", "BWMR_updated.R")
bwmr_md5 <- "b4a773429b9992838e4498e219f2eae5"
if (!check_only && !file.exists(bwmr_source)) {
  dir.create(dirname(bwmr_source), recursive = TRUE, showWarnings = FALSE)
  temporary <- tempfile(tmpdir = dirname(bwmr_source))
  download.file("https://raw.githubusercontent.com/jiazhao97/BWMR/c00e8186f12ed25899aaf85b7ac5c98c6d86c24c/updates/BWMR_updated.R",
                temporary, mode = "wb")
  if (unname(tools::md5sum(temporary)) != bwmr_md5) {
    unlink(temporary)
    stop("Downloaded BWMR source does not match the pinned version.")
  }
  if (!file.rename(temporary, bwmr_source)) stop("Cannot save BWMR source: ", bwmr_source)
}
if (!file.exists(bwmr_source) || unname(tools::md5sum(bwmr_source)) != bwmr_md5) {
  stop("Missing or changed BWMR source. Run the installer or point MRCAT_BWMR_SOURCE to the pinned upstream file.")
}
cat("BWMR source:", bwmr_source, "\n")
ready <- vapply(required, loadable, logical(1))
for (pkg in required) {
  cat(pkg, if (ready[[pkg]]) as.character(packageVersion(pkg)) else "MISSING OR UNLOADABLE", "\n")
}
cat("R home:", R.home(), "\nLibrary:", lib, "\n")
if (!all(ready)) stop("Unavailable R packages: ", paste(required[!ready], collapse = ", "))
