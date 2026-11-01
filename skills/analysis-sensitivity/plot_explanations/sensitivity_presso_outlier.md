# Sensitivity MR-PRESSO Outlier Plot

## What This Plot Is For

This plot shows where MR-PRESSO-flagged outlier SNPs sit in the SNP cloud and whether the causal-effect estimate line changes noticeably after those outliers are removed or corrected.

## What Is In The Plot

- The x-axis is each SNP's exposure effect `b.exp`; the y-axis is the same SNP's outcome effect `b.out`.
- Each filled circle is one SNP. Point size is fixed and does not represent weight or significance.
- Black points `#333333` are SNPs not flagged as outliers by MR-PRESSO.
- Orange points `#D55E00` are outlier SNPs flagged by MR-PRESSO.
- Light gray error bars (`grey75`) show `b.exp +/- 1.96 * se.exp` horizontally and `b.out +/- 1.96 * se.out` vertically.
- Very light gray crosshair lines (`grey85`) mark `b.exp = 0` and `b.out = 0`.
- The black solid line `#333333` is the raw estimate before outlier correction.
- The blue dashed line `#0072B2` is the outlier-corrected estimate after removing or correcting outliers.

## How To Read It

First check whether orange outliers are clearly separated from the main black SNP cloud. If they are, their outcome-effect and exposure-effect relationship differs from the main trend. Then compare the black solid line and blue dashed line. The closer the lines are, the smaller the outlier impact on beta. Large differences in direction or slope indicate that outliers have a stronger effect on the result. SNPs with long error bars are imprecise, so interpret them with lower certainty.

## Do Not Interpret From This Plot Alone

This plot only shows outlier locations and the graphical difference between raw and corrected estimates. Final interpretation should also use beta, standard error, p value, number of SNPs, global test, outlier test, distortion test, and results from other MR methods.
