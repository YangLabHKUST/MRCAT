# LDSC Background Parameter Heatmap

This plot summarizes the pair-level LDSC and background-parameter structure estimated during pair preparation.

## What Is Shown

- The `C` heatmap shows the estimated covariance-like background parameter matrix.
- The `Omega` heatmap shows the corresponding error or residual covariance structure.
- Rows and columns correspond to exposure and outcome.
- Cell colors show the sign and magnitude of each matrix entry.
- Cell labels show the numeric values.
- The side panel reports LDSC genetic correlation `rg`, the number of harmonized SNPs when available, and whether the matrix artifacts were present.

## How To Read It

The off-diagonal entries describe cross-trait structure. A nonzero off-diagonal pattern can indicate shared polygenic architecture, correlated errors, sample overlap, or other background coupling between exposure and outcome summary statistics.

The LDSC `rg` provides a genome-wide genetic-correlation summary. Positive values suggest shared alleles tend to move both traits in the same direction; negative values suggest opposite directions. Values near zero suggest little genome-wide genetic correlation, although local loci can still matter.

## Warning Signs

- Large off-diagonal values can signal strong shared background structure that downstream methods may need to account for.
- Missing `C` or `Omega` means the pair-preparation artifacts are incomplete or were not written.
- A large `rg` does not prove causality; it can arise from shared biology, pleiotropy, sample overlap, or confounding.
- Very small harmonized SNP counts can make background estimates less stable.

## Use In The Pipeline

This plot explains the shared pair-level statistical context. It is especially
useful when downstream methods differ in how they account for background
structure. Interpret it with the effect landscape, instrument strength plot,
and downstream method estimates.
