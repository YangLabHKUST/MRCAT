# Render the author's plot once and measure its actual panel on the same device.
# Coordinates are fractions of the full PNG, so browser resizing needs no offsets.
export_mrapss_plot <- function(plot, fit, path) {
  width <- 7
  height <- 5
  dpi <- 300
  built <- ggplot2::ggplot_build(plot)
  # Match ggsave's PNG device selection and preserve the native plot appearance.
  device <- if (requireNamespace("ragg", quietly = TRUE)) ragg::agg_png else grDevices::png
  device(path, width = width, height = height, units = "in", res = dpi, bg = "white")
  on.exit(grDevices::dev.off(), add = TRUE)
  grid::grid.newpage()
  grid::grid.draw(ggplot2::ggplot_gtable(built))
  grid::grid.force()
  viewports <- grid::grid.ls(viewports = TRUE, grobs = FALSE, print = FALSE)$name
  panel <- grep("^panel\\.[0-9]+-", viewports, value = TRUE)
  stopifnot(length(panel) == 1L)
  grid::seekViewport(panel[[1]])
  bottom_left <- grid::deviceLoc(grid::unit(0, "npc"), grid::unit(0, "npc"), valueOnly = TRUE)
  top_right <- grid::deviceLoc(grid::unit(1, "npc"), grid::unit(1, "npc"), valueOnly = TRUE)
  bounds <- built$layout$panel_params[[1]]
  x_position <- function(x) (bottom_left$x + (x - bounds$x.range[1]) /
    diff(bounds$x.range) * (top_right$x - bottom_left$x)) / width
  y_position <- function(y) 1 - (bottom_left$y + (y - bounds$y.range[1]) /
    diff(bounds$y.range) * (top_right$y - bottom_left$y)) / height
  data <- fit$MRdat
  stopifnot(length(fit$post$Pi) == nrow(data), "SNP" %in% names(data))
  points <- data.frame(
    snp = as.character(data$SNP), x = x_position(data$b.exp), y = y_position(data$b.out),
    b_exp = data$b.exp, b_out = data$b.out, se_exp = data$se.exp, se_out = data$se.out,
    p_exp = data$pval.exp, posterior = as.numeric(fit$post$Pi),
    x_low = x_position(data$b.exp - data$se.exp), x_high = x_position(data$b.exp + data$se.exp),
    y_low = y_position(data$b.out + data$se.out), y_high = y_position(data$b.out - data$se.out)
  )
  stopifnot(all(is.finite(points$x)), all(is.finite(points$y)))
  sidecar <- sub("\\.png$", ".plot.json", path)
  jsonlite::write_json(list(kind = "mrapss", width = width * dpi, height = height * dpi,
    points = points), sidecar, auto_unbox = TRUE, na = "null", digits = NA)
  sidecar
}
