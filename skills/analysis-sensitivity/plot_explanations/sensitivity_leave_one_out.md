# Sensitivity Leave-One-Out Plot

## What This Plot Is For

This plot checks whether the overall IVW MR beta changes substantially when each SNP is removed one at a time. It answers whether the result is driven mainly by one SNP.

## What Is In The Plot

- The x-axis is the IVW MR effect beta.
- Each y-axis row is one analysis: black rows are IVW after removing the labeled SNP, and the red `All` row is IVW with all SNPs retained.
- Thin black points and horizontal lines are IVW beta estimates after removing one SNP; the line is `b +/- 1.96 * se`.
- The thick red point and horizontal line are the `All - IVW` summary estimate with all SNPs retained; the line is also `b +/- 1.96 * se`.
- The vertical dashed line is beta = 0, used to judge direction and whether intervals cross zero.

## How To Read It

First check whether black points stay close to the red `All` result; if so, no single SNP has a large influence on the overall IVW beta. Then look for a row where the black point moves far away, or where beta changes from positive to negative or negative to positive after removing that SNP. That SNP may have strong influence on the result. Also check interval length: longer intervals mean less precise leave-one-out estimates.

## Do Not Interpret From This Plot Alone

Leave-one-out only checks stability after deleting one SNP at a time; it does not rule out all pleiotropy or weak-instrument problems. Final interpretation should also use beta, standard error, p value, number of SNPs, heterogeneity tests, single-SNP forest plot, and funnel plot.
