# GWAS QC QQ Plot

This plot checks whether the formatted GWAS p-value distribution looks statistically plausible after `MRAPSS::format_data()`.

## What Is Shown

- The panel represents the single GWAS processed by this `gwas-qc` step.
- The x-axis is the expected `-log10(P)` distribution under the null hypothesis.
- The y-axis is the observed `-log10(P)` distribution after GWAS QC formatting.
- The dashed diagonal line is the null expectation.
- `lambda GC` is the genomic-control inflation factor estimated from the median chi-square statistic when `chi2` or `Z` is available.

## How To Read It

Points close to the diagonal suggest that most SNPs behave like null associations, which is expected for a GWAS-wide background. A strong upward tail at the right side suggests real trait-associated loci that may later provide instruments or explain downstream sensitivity patterns.

## Warning Signs

- A broad upward shift across the entire curve can indicate population structure, cryptic relatedness, sample overlap, batch effects, or other inflation.
- A curve that is almost perfectly flat with no upper tail may indicate weak GWAS signal or missing p-value information.
- Sharp discontinuities or steps can indicate rounded p-values, heavily filtered inputs, or source-data formatting artifacts.
- Very large `lambda GC` should be interpreted with trait architecture and sample size in mind. Polygenic traits can have elevated lambda even when the study is well controlled.

## Use In The Pipeline

Use this as upstream formatted-GWAS QC before pair preparation and MR fitting. It does not estimate a causal effect and does not by itself prove that instruments are valid. It should be read together with the post-format Manhattan plot, the signal-retention curve, instrument counts, MR effect estimates, and sensitivity analyses.
