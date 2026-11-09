---
name: mr-bwmr
description: >-
  Fit Bayesian weighted MR on harmonized, LD-independent MRdat, with native or
  Z/sqrt(N)-standardized effects; default minimum is four selected instruments. Models
  instrument uncertainty and pleiotropic outliers but does not model an instrument LD
  matrix or perform cis selection or colocalization. Gene-expression data require a
  compatible instrument set and justified method choice; BWMR is not an automatic
  follow-up for every MR analysis.
accepts-milestones: [gwas_pair_prepare_result]
produces-milestone: mr_bwmr_result
reusable-outputs: [result_record_path]
---

# mr-bwmr

Fit Bayesian weighted MR (BWMR) on a prepared MRdat table.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `mr_bwmr` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import mr_bwmr

result = mr_bwmr(
    mrdat_path='/absolute/path/to/MRdat.tsv',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_bwmr_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `mrdat_path` | path | required | Prepared harmonized, LD-clumped MRdat TSV. |
| `input_scale` | string | "standardize" | Allowed: standardize, native. Effect representation; keep explicit user choice. |
| `pvalue_threshold` | float | 5e-8 | Exposure P-value selection threshold; do not relax silently. |
| `min_instruments` | int | 4 | Minimum selected instruments. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Use the verified `mrdat_path` returned by pair preparation. Required base columns: `SNP`, `b.exp`, `b.out`, `se.exp`, `se.out`, `pval.exp`; retain all extra provenance columns. Do not pass raw GWAS or study IDs. Reuse the prepared pair rather than harmonizing or clumping again.

`standardize` (default) recalculates beta=Z/sqrt(N), SE=1/sqrt(N) when all Z.exp/Z.out/N.exp/N.out columns exist. Legacy tables without them retain existing b/se values: reuse only verified standardized pair tables, never relabel raw/native values. `native` uses `b.exp.native`, `se.exp.native`, `b.out.native`, `se.out.native`; it must not silently fall back to standardized values.

The tool applies pvalue_threshold exactly once and never relaxes it. If too few valid instruments remain, report insufficiency. Decide whether another dataset or a justified user-compatible threshold is appropriate; do not automatically increase the cutoff. Report the threshold and selected SNP count.

## Input scale and reuse checks

State actual input_scale separately from phenotype effect units. Generic
standardize uses Z/sqrt(N) and 1/sqrt(N); it is not automatically phenotype-SD
or log-odds. Do not label it as OR merely because the outcome is binary. Preserve
an explicitly requested scale; if this method cannot support it, report the
conflict rather than switching silently. Use the recorded selected_mrdat_path
for downstream SNP analyses. A scale change requires rerunning affected fits
and derived summaries, not relabeling old results. Reuse compatible preparation;
rebuild it only when required native/provenance fields are absent. Missing N or
native fields cannot justify inventing values or row-wise scale fallback.

## Outputs and checks

On success, `result["outputs"]["mr_bwmr_result"]` holds the data described below.

The payload contains `methods`, `diagnostics`, `interpretation`, `plot_manifest` and `result_record_path`. Reuse the inner result record for downstream comparison; inspect effective threshold, selected SNP count, scale and warnings. Plot paths are listed in the manifest; do not guess filenames.

BWMR also returns `weights_path`; its plot manifest contains `bwmr_weighted_fit`.

## Method Interpretation

Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis.

### Key assumptions

BWMR propagates SNP-exposure uncertainty and models small, centered horizontal-pleiotropic effects with adaptive weighting for outliers. Its causal interpretation remains conditional on that pleiotropy model and approximately LD-independent prepared instruments; systematic directional or correlated pleiotropy is not generally resolved by downweighting.

### Relevant evidence

Use fitted estimates and intervals, instrument selection/strength, convergence/warnings and posterior weights when supplied. Compare with IVW and available pleiotropy/influence diagnostics. Near-one weights show little extreme downweighting, not that every SNP is valid or that pleiotropy is absent.

### Interpretation

Compare magnitudes and uncertainty before attributing a BWMR-IVW difference to exposure uncertainty or influential variants. A similar estimate with a wider null-inclusive interval can reflect uncertainty propagation rather than contradictory evidence. Weights alone cannot establish the biological source of a difference.

### Limits

BWMR does not itself resolve sample overlap, population mismatch, reverse causation or colocalization failure. State how any observed directional-pleiotropy signal bears on its centered-pleiotropy model without claiming that a diagnostic from another estimator directly tests all BWMR assumptions.

- **Original method reference:** [Zhao et al. 2020](https://doi.org/10.1093/bioinformatics/btz749).
