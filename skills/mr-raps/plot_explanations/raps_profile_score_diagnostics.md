# RAPS Profile Score Diagnostics

## What This Plot Is For

This is a Figure 5(a)-style RAPS diagnostic: a normal Q-Q plot of standardized residuals beside leave-one-out causal estimates plotted against instrument strength. It is generated from the current analysis data rather than copied from the paper. The residuals and leave-one-out estimates are computed by `mr.raps::mr.raps.mle` with over-dispersion enabled and Huber loss, using the same selected instruments as the main RAPS analysis.

## What Is In The Plot

- The left panel compares package-computed standardized residuals with standard-normal quantiles. Points near the dashed diagonal are compatible with the expected residual distribution.
- The right panel shows the package-computed leave-one-out estimate after removing each instrument in turn. Its x-axis is the per-instrument F-statistic, `(beta.exposure / se.exposure)^2`, on a logarithmic scale.
- The horizontal dashed line is the full profile-score diagnostic estimate.
- The red star identifies the SNP with the largest absolute leave-one-out change, `abs(beta_leave_one_out - beta_full)`. The same SNP is marked in both panels so its residual and influence can be compared directly.
- This selection rule always identifies the most influential SNP in the analyzed set. It is not a formal outlier test and does not apply a residual threshold or an outlier-test p-value.

## How To Read It

Read the two panels together:

1. First inspect the overall Q-Q pattern. Residuals following the dashed diagonal are broadly compatible with the model's normal-residual assumption. Systematic curvature, compressed or expanded tails, or isolated points far from the line can indicate under-dispersion, over-dispersion, heavy tails, or residual outliers.
2. The red star in the Q-Q panel is not automatically a residual outlier. It only locates the SNP selected from the leave-one-out analysis. Its vertical departure from the diagonal must still be judged in the context of the other residuals.
3. In the right panel, compare every leave-one-out estimate with the horizontal dashed full-data estimate. A tight cluster around the line indicates stability. A large vertical displacement means that removing that SNP changes the diagnostic estimate materially.
4. Use the F-statistic to distinguish influence from instrument strength. A strong instrument can be influential without having an abnormal residual, while an SNP with an extreme residual can have limited influence after Huber down-weighting.

The red SNP should only be described as a likely outlier when there is supporting evidence in both diagnostics, such as a clearly abnormal standardized residual and a substantial leave-one-out shift. Otherwise, describe it more narrowly as the most influential SNP in this instrument set. Confirm any concern with the numerical RAPS result, other sensitivity analyses, and the SNP's known biological associations.

## Relation To The Main RAPS Result

The main reported estimate still comes from the current recommended `mr.raps()` interface. This diagnostic figure uses the package's original robust adjusted profile-score routine because that is the routine that computes and returns the paper's standardized-residual and leave-one-out diagnostics. The two estimates are usually close, but they are not mathematically identical estimators and should not be presented as interchangeable numerical results.
