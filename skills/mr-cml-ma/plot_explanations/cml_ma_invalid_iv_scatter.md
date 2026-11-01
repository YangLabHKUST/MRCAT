# cML-MA Invalid-IV Scatter Plot

## What This Plot Is For

This plot shows which instruments cML-MA classifies as possible invalid IVs, and whether those invalid IVs deviate from the main trend among selected IVs.

## What Is In The Plot

- The x-axis is each SNP's exposure effect `b.exp`; the y-axis is the same SNP's outcome effect `b.out`.
- Each filled circle is one SNP. Point size is fixed and does not represent weight or significance.
- Black points `#333333` are selected IVs that the model treats as usable for estimating the main effect.
- Blue points `#0072B2` are invalid IVs selected by the BIC model used by cML-MA.
- Light gray error bars (`grey75`) show `b.exp +/- 1.96 * se.exp` horizontally and `b.out +/- 1.96 * se.out` vertically.
- Very light gray crosshair lines (`grey85`) mark `b.exp = 0` and `b.out = 0`.
- The orange solid line `#D55E00` is the MA-BIC estimate, with intercept 0 and slope equal to the method beta.

## How To Read It

First check whether blue invalid IVs cluster at the edge of the cloud or clearly deviate from the black selected-IV main group. If so, they are more likely to violate valid-IV assumptions. Then check whether the orange estimate line primarily follows the black-point main group rather than being pulled by blue points. Longer error bars mean the SNP's exposure or outcome effect estimate is less precise.

## Do Not Interpret From This Plot Alone

This plot helps explain invalid-IV locations and the MA-BIC beta line. Final interpretation should also use beta, standard error, p value, number of SNPs, invalid-IV count, model-selection output, and other sensitivity analyses.
