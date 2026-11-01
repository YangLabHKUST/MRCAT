# Harmonized Effect Landscape

This plot shows the joint exposure and outcome effect geometry after pair-level harmonization, with clumped instruments overlaid.

## What Is Shown

- The x-axis is the harmonized exposure effect, `b.exp`.
- The y-axis is the harmonized outcome effect, `b.out`.
- The heat-colored background shows the density of harmonized SNPs from the pair-level `Mdat`.
- Overlaid points are the clumped `MRdat` instruments.
- Green instruments have exposure and outcome effects in the same direction.
- Red instruments have exposure and outcome effects in opposite directions.
- Gray instruments are near zero in one or both effect dimensions.
- The horizontal and vertical zero lines divide effect directions.

## How To Read It

The dense background describes the broad shared genetic-effect architecture of the two traits after harmonization. The highlighted instruments show which parts of that architecture are used by downstream MR methods.

If instruments are spread around both sides of the outcome axis, downstream estimates may be sensitive to heterogeneity or pleiotropy. If most instruments sit along a clear slope, that can suggest a coherent exposure-outcome effect pattern, but it still needs formal MR estimation and sensitivity checks.

## Warning Signs

- A few isolated instruments far from the main cloud can dominate MR estimates.
- A strong split between same-direction and opposite-direction instruments may indicate heterogeneity, bidirectional biology, or pleiotropic pathways.
- A dense background shifted away from zero can reflect shared genetic architecture, sample overlap, or broad confounding structure.
- Very few highlighted instruments means limited power and less stable sensitivity analysis.

## Use In The Pipeline

This plot is a pair-preparation QC view. It helps interpret the geometry of harmonized effects and selected instruments before MR methods are run. It is not a causal estimate and should be interpreted together with MR estimates, heterogeneity diagnostics, outlier tests, and method-specific plots.
