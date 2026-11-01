# GWAS QC Signal Retention Curve

This plot asks whether GWAS QC formatting preferentially keeps or loses SNPs across different association-strength ranges.

## What Is Shown

- The x-axis is an association-strength cutoff: `-log10(P) >= x`.
- If a canonical GWAS input is available, the y-axis is the fraction of canonical SNPs above that cutoff that remain in the formatted GWAS table.
- If canonical inputs are not available, the y-axis falls back to the number of formatted SNPs above each cutoff.
- The vertical dashed red line marks the conventional genome-wide threshold, `p = 5e-8`.
- The curve represents the single GWAS processed by this step.

## How To Read It

When canonical inputs are available, a high retained fraction across strong-signal cutoffs suggests that formatting preserved most biologically important associations. A lower retained fraction at weak cutoffs can be normal because formatting removes ambiguous alleles, unavailable rsIDs, duplicates, low-frequency variants, MHC variants, or rows missing required fields.

If the curve drops sharply near genome-wide significance, important association signals may have been removed before MR fitting. That can reduce instrument strength or change which loci drive the analysis.

## Warning Signs

- Low retention at strong-signal cutoffs can indicate allele problems, rsID mismatch, reference mismatch, or aggressive filtering.
- Exposure strong-signal loss is especially important because it can reduce usable instruments.
- Outcome strong-signal loss may alter downstream estimates of genetic correlation or pleiotropic structure.
- A fallback count curve is less diagnostic than a true retention fraction because it cannot show what was removed from the canonical input.

## Use In The Pipeline

Use this plot to decide whether formatting preserved the signal needed for pair preparation. It complements the QQ and Manhattan plots by showing not only whether signal exists, but whether it survived the formatting step.
