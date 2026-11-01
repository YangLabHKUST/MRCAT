# Instrument Strength vs Outcome Association

This plot compares how strongly each clumped instrument is associated with the exposure and with the outcome.

## What Is Shown

- The x-axis is exposure instrument strength: `-log10(pval.exp)`.
- The y-axis is outcome association strength: `-log10(pval.out)`.
- Each point is one clumped `MRdat` instrument.
- Point color shows whether `b.exp` and `b.out` have the same direction, opposite directions, or are near zero.
- Point size increases with approximate outcome evidence when `se.out` is available.
- The vertical dashed line marks the instrument-selection threshold recorded in `MRdat$Threshold`, or `5e-5` if no threshold is recorded.
- The horizontal dotted red line marks outcome genome-wide significance, `p = 5e-8`.
- The strongest exposure instruments are labeled by rsID.

## How To Read It

Good MR instruments should be strong for the exposure, so points farther to the right are usually more informative. Points high on the y-axis also associate strongly with the outcome. That can be consistent with a causal pathway, but it can also reflect horizontal pleiotropy, shared biology, or correlated traits.

Direction coloring helps show whether exposure and outcome effects broadly agree. A clean directional pattern can be reassuring, while mixed directions may signal heterogeneity.

## Warning Signs

- Many instruments above the outcome genome-wide line may need careful pleiotropy checks.
- A small number of very strong outcome-associated instruments can dominate estimates.
- Instruments just above the vertical selection threshold may be weak and can reduce robustness.
- Opposite-direction clusters can indicate heterogeneous mechanisms or invalid instruments.

## Use In The Pipeline

Use this plot to inspect selected instruments before fitting MR methods. It does not determine whether an instrument is valid on its own. Final interpretation should use the MR effect estimates, standard errors, p values, number of SNPs, sensitivity methods, and outlier diagnostics.
