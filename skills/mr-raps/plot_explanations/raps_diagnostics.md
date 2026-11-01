# RAPS Diagnostic Plot

## What This Plot Is For

This plot checks whether standardized residuals after RAPS fitting show systematic patterns, heavy tails, or outlier SNPs. The local `mr.raps` `plot(fit)` call draws two diagnostic panels.

## What Is In The Plot

- Each point represents one SNP instrument's diagnostic value in the RAPS fit.
- In the left panel, the x-axis is `Absolute weight` and the y-axis is `Standardized residual`. Higher or lower points have residuals farther from 0.
- The smooth curve in the left panel comes from `geom_smooth(method = "loess")`, helping reveal whether residuals vary systematically with weight.
- The right panel is a half-normal QQ plot of absolute standardized residuals: the x-axis is theoretical half-normal quantile and the y-axis is sample `abs(standardized residual)`.
- The dashed line in the right panel is the 45-degree reference line. Points close to the line indicate residual tails closer to expectation; tail points clearly above the line indicate larger residuals or heavy tails.
- This plot does not use color to distinguish SNP classes; the main information comes from point locations, the loess curve, and the QQ reference line.

## How To Read It

Start with the residual-vs-weight panel. Ideally, points scatter randomly around 0 and the loess curve does not show clear curvature or persistent departure from 0. High-weight SNPs with large residuals may have strong influence on the RAPS fit. Then inspect the QQ panel: central points close to the dashed line are reassuring, while a strongly rising tail or a few points far from the line suggest heavy tails, outlier SNPs, or imperfect model assumptions.

## Do Not Interpret From This Plot Alone

The RAPS diagnostic plot only shows residual shape and outlier clues. Final interpretation should also use beta, standard error, p value, number of SNPs, over-dispersion, loss function, weak-instrument context, and other sensitivity analyses.
