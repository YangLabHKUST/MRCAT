# Sensitivity Funnel Plot

## What This Plot Is For

This plot checks whether single-SNP MR estimates are roughly symmetric across precision levels, helping diagnose directional pleiotropy, heterogeneity, or a small number of outlier SNPs.

## What Is In The Plot

- The x-axis is single-SNP beta, the Wald ratio estimate from using each SNP as an individual instrument.
- The y-axis is `1 / SE`. Higher positions indicate smaller standard errors and more precise single-SNP estimates; lower positions indicate greater uncertainty.
- Black points are the single-SNP beta values.
- Colored vertical lines are all-SNP method beta estimates, from summary methods such as `All - IVW` and `All - MR Egger`.
- Line colors follow the `MR Method` legend; each color corresponds to an all-SNP MR method, not an individual SNP.

## How To Read It

First check whether black points are roughly symmetric around the colored method lines. Ideally, high-precision and low-precision SNP estimates should not be strongly shifted to one side. Strong one-sided skew, or low-precision points far from the main cloud, may suggest directional pleiotropy, heterogeneity, or outlier instruments. Then compare whether IVW, MR-Egger, and other colored vertical lines are far apart; large separation means the methods disagree on the overall beta.

## Do Not Interpret From This Plot Alone

The funnel plot is a sensitivity diagnostic, not the primary significance test. Final interpretation should also use beta, standard error, p value, number of SNPs, MR-Egger intercept, heterogeneity tests, single-SNP forest, and leave-one-out results.
