# dIVW Residual QQ Plot

## What This Plot Is For

This plot checks whether dIVW standardized residuals are approximately normal, helping detect outlier SNPs, heavy-tailed residuals, or model-assumption mismatch.

## What Is In The Plot

- Each point represents a quantile of a SNP's dIVW standardized residual.
- The residual core is `beta.outcome - beta_dIVW * beta.exposure`, standardized using outcome/exposure standard errors, tau squared, and the covariance term when sample overlap is present.
- The x-axis is theoretical normal quantiles and the y-axis is sample standardized residual quantiles, following the default base R `qqnorm` structure.
- The reference line comes from base R `qqline`. If residuals are close to normal, points should roughly follow the line.
- This plot does not use color to distinguish SNP classes; the main information is the position of points relative to the reference line.

## How To Read It

First check whether most central points lie close to the reference line; this suggests that the main residual distribution is consistent with model expectations. Then inspect both tails for clear departures. Upward or downward tail bending can indicate heavy tails, outlier SNPs, heterogeneity, or incomplete dIVW model fit. If only a few tail points deviate, use other plots and numeric diagnostics to decide whether they truly affect beta.

## Do Not Interpret From This Plot Alone

The QQ plot only checks the distributional shape of dIVW residuals. Final interpretation should also use beta, standard error, p value, number of SNPs, lambda, tau squared, sample-overlap settings, and other sensitivity analyses.
