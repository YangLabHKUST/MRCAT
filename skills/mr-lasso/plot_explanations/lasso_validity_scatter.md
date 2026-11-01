# MR-Lasso Valid SNP Scatter Plot

## What This Plot Is For

This plot shows which SNPs MR-Lasso retains as valid SNPs, which SNPs are penalized as inconsistent with the main trend, and which group the final MR-Lasso beta estimate line mainly follows.

## What Is In The Plot

- The x-axis is each SNP's exposure effect `b.exp`; the y-axis is the same SNP's outcome effect `b.out`.
- Each filled circle is one SNP. Point size is fixed and does not represent weight or significance.
- Green points `#009E73` are valid SNPs retained by MR-Lasso.
- Orange points `#D55E00` are penalized SNPs, usually inconsistent with the main linear trend.
- Light gray error bars (`grey75`) show `b.exp +/- 1.96 * se.exp` horizontally and `b.out +/- 1.96 * se.out` vertically.
- Very light gray crosshair lines (`grey85`) mark `b.exp = 0` and `b.out = 0`.
- The blue solid line `#0072B2` is the MR-Lasso estimate, with intercept 0 and slope equal to the MR-Lasso beta.

## How To Read It

First check whether green valid SNPs form a clear linear trend, then check whether orange penalized SNPs sit far from the green main group. More numerous or more distant orange points suggest that ordinary MR estimates may be affected by outlying or invalid instruments. Then read the blue line direction: upward to the right indicates positive beta, and downward to the right indicates negative beta. Longer error bars mean less precise exposure or outcome effect estimates for that SNP.

## Do Not Interpret From This Plot Alone

This plot shows MR-Lasso SNP selection and the beta estimate line. Final interpretation should also use beta, standard error, p value, number of SNPs, valid SNP count, lambda selection, and other sensitivity results.
