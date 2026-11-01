# Sensitivity Single-SNP Forest Plot

## What This Plot Is For

This plot checks whether Wald ratio estimates from individual SNP instruments point in a consistent direction, and compares those single-SNP results with all-SNP IVW and MR-Egger summary estimates.

## What Is In The Plot

- The x-axis is the MR effect beta, the estimated effect of exposure on outcome.
- Each y-axis row is one SNP, with additional summary rows such as `All - IVW` and `All - MR Egger`.
- Thin black points and horizontal lines are individual SNP Wald ratio estimates; the point is that SNP's beta and the line is `b +/- 1.96 * se`.
- Thick red points and horizontal lines are all-SNP summary estimates, usually including `All - IVW` and `All - MR Egger`; the red point is the method beta and the red line is `b +/- 1.96 * se`.
- The vertical dashed line is beta = 0. Points to the right indicate positive estimates, and points to the left indicate negative estimates.

## How To Read It

First check whether most black single-SNP points are on the same side of 0; more agreement means more consistent direction. Then look for black points far from the others or with very long intervals, because those SNPs may be unstable or inconsistent with the main trend. Finally check whether the red `All - IVW` and `All - MR Egger` estimates agree with the direction of most black points. If the red summary estimates conflict with most single-SNP estimates, heterogeneity and outlier SNPs need close inspection.

## Do Not Interpret From This Plot Alone

This plot emphasizes the direction and stability of single-SNP and all-SNP estimates. Final interpretation should also use beta, standard error, p value, number of SNPs, heterogeneity tests, MR-Egger intercept, funnel plot, and leave-one-out results.
