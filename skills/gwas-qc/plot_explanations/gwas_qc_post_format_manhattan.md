# GWAS QC Post-Format Manhattan Plot

This plot shows where the formatted SNP signal lies across the genome after the GWAS has passed `MRAPSS::format_data()`.

## What Is Shown

- The panel represents the single GWAS processed by this `gwas-qc` step.
- The x-axis is genomic position grouped by chromosome.
- The y-axis is `-log10(P)` from the formatted GWAS table.
- Each chromosome is drawn in a distinct color.
- The red horizontal line marks the conventional genome-wide threshold, `p = 5e-8`.
- Up to the top 30 genome-wide significant formatted SNPs are highlighted with triangle markers. A small number of the strongest highlighted SNPs are labeled by rsID.

## Coordinate Mapping

Formatted files usually contain rsIDs but not chromosome and base-pair columns. This plot therefore maps the plotted top and sampled rsIDs to coordinates using the local LDSC/HapMap-style reference only when the user requests plot generation. SNPs that cannot be mapped are omitted from this figure.

## How To Read It

Tall peaks indicate genomic regions with strong association signal that survived formatting. These regions may later provide instruments or help explain sensitivity patterns.

## Warning Signs

- No visible peaks can mean weak association signal, strict formatting filters, missing rsID mapping, or unsuitable source data.
- A single extremely dominant region can make the analysis sensitive to that locus.
- Strong signal in regions known for complex LD or immune architecture, such as the MHC, should be interpreted carefully, especially if upstream filtering did not remove it.
- If many expected SNPs are missing, check whether the rsIDs match the local reference build and naming convention.

## Use In The Pipeline

This plot is a formatted-input QC view. It is not an MR estimate and does not show clumped instruments directly. Use it together with the pair-preparation plots to see which broad GWAS signals survive harmonization and instrument selection.
