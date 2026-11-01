# MR-APSS MRplot

## What This Plot Is For

This plot shows the SNP cloud used in the MR-APSS fit, each SNP's posterior probability of being a valid IV, and whether the MR-APSS beta line with its uncertainty band explains the main cloud.

## What Is In The Plot

- The x-axis is the SNP effect on the exposure, `b.exp`; the y-axis is the same SNP's effect on the outcome, `b.out`. Axis titles include the current exposure and outcome names.
- Each triangle represents one SNP.
- Gray error bars (`gray60`) show effect-estimate uncertainty: horizontally `b.exp +/- se.exp`, vertically `b.out +/- se.out`.
- Point size is `-log10(pval.exp)`; larger points indicate stronger exposure association.
- Point color is the MR-APSS `IV Posterior`, the posterior probability that the SNP is a valid IV. Light blue `#56B1F7` is lower and dark blue `#132B43` is higher; read exact values from the legend.
- The red line is the MR-APSS beta estimate, with intercept 0 and slope `MRres$beta`.
- The translucent red band is the uncertainty range around the estimate line, drawn as `(beta +/- 1.96 * beta.se) * b.exp`.
- The gray dashed horizontal line marks `b.out = 0`.

## How To Read It

First check whether the dark-blue, larger SNPs roughly follow the red estimate line; these SNPs have stronger exposure associations and are more likely to be treated as valid IVs by MR-APSS. Then check the width of the red band: a wider band means greater beta uncertainty. If many points are light-colored and far from the red line, the valid-IV posterior probabilities are low or the SNP cloud is heterogeneous. Also pay attention to SNPs with long error bars because their point estimates are imprecise.

## Do Not Interpret From This Plot Alone

This plot shows the MR-APSS SNP cloud, IV posterior probabilities, and beta estimate line. Final interpretation should also use beta, standard error, p value, number of SNPs, `pi0`, `tau.sq`, `sigma.sq`, selection-bias correction results, and other MR methods.
