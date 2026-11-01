# MR-Robust Diagnostic Plot

## What This Plot Is For

This plot checks whether residuals from the `robustbase::lmrob` robust regression fit match expectations, whether outlier SNPs remain, and whether residuals vs fitted values show systematic patterns. The current runner calls `plot(fit, which = c(2, 4))`, so the figure contains the second and fourth `lmrob` diagnostic panels.

## What Is In The Plot

- Each point represents one SNP's observation or residual diagnostic value in the robust regression fit.
- In the `Normal Q-Q vs. Residuals` panel, the x-axis is theoretical normal quantiles and the y-axis is model residuals; the gray reference line comes from `qqline`. Points closer to the line indicate residual tails closer to a normal shape.
- In the `Residuals vs. Fitted Values` panel, the x-axis is fitted values and the y-axis is residuals, showing the difference between each SNP's outcome effect and the robust-regression fitted value.
- The horizontal dashed lines in the residuals-vs-fitted panel mark residual = 0 and `+/-2.5 * robust scale`, highlighting large residuals.
- `lmrob` usually labels a small number of points with the largest absolute residuals; those labels identify SNPs that need closer inspection.
- This plot does not use color to encode SNP classes; focus on point positions, reference lines, and labeled residual points.

## How To Read It

Start with the QQ panel. If points roughly follow the gray reference line, residual tails are broadly consistent with model expectations. Strong tail departures suggest heavy tails or outlier SNPs. Then inspect the residuals-vs-fitted panel: points should scatter randomly around residual = 0, without curvature, funnel shape, or one-sided shift across fitted values. Points outside `+/-2.5 * robust scale` or labeled by the plot have large residuals and should be checked even though robust regression reduces outlier influence.

## Do Not Interpret From This Plot Alone

This is a robust-regression residual diagnostic, not a direct causal conclusion. Final interpretation should also use beta, standard error, p value, number of SNPs, robust-regression weights, outlier status, and results from other MR methods.
