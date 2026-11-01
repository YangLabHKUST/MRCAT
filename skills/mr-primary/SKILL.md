---
name: mr-primary
description: >-
  Fit the fixed IVW, MR-Egger, weighted-median and weighted-mode suite on harmonized,
  LD-independent MRdat; default minimum is four selected instruments. Supports native or
  Z/sqrt(N)-standardized effects. Does not select a cis region, model correlated
  instruments, perform colocalization, or provide a single-SNP Wald-ratio branch. Use
  custom estimation when the required estimator or instrument structure is outside this
  suite.
accepts-milestones: [gwas_pair_prepare_result]
produces-milestone: mr_primary_result
reusable-outputs: [result_record_path]
---

# mr-primary

Fit IVW, MR-Egger, weighted median and weighted mode on a prepared MRdat table.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `mr_primary` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import mr_primary

result = mr_primary(
    mrdat_path='/absolute/path/to/MRdat.tsv',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_primary_result"]
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

On success, `result["outputs"]["mr_primary_result"]` holds the data described below.

The payload contains `methods`, `diagnostics`, `interpretation`, `plot_manifest` and `result_record_path`. Reuse the inner result record for downstream comparison; inspect effective threshold, selected SNP count, scale and warnings. Plot paths are listed in the manifest; do not guess filenames.

`selected_mrdat_path` and `input_scale` are required for sensitivity reuse. Primary plots are scatter and estimates forest; invoke analysis-sensitivity only when those diagnostics are needed.

## Method Interpretation
Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis. Present these four estimates as complementary sensitivity analyses rather than four independent confirmations of causality.

- **IVW:** the efficient primary estimate when all IVs are valid, or pleiotropic effects are balanced. Prefer it when heterogeneity and directional-pleiotropy diagnostics are reassuring; otherwise do not rely on it alone.
- **MR-Egger:** allows directional pleiotropy under the InSIDE assumption, but is less precise. A materially different Egger slope or non-null intercept weakens an IVW-only claim.
- **Weighted median:** is consistent when at least half of the total IV weight comes from valid instruments. Treat agreement with IVW as assumption-robust support, not as an independent replication.
- **Weighted mode:** targets the largest cluster of similar SNP ratio estimates under the zero-modal-pleiotropy assumption. A discrepant mode estimate indicates cluster sensitivity that must be reported.
- **Recommendation:** use IVW as a reference, then emphasize a directionally consistent result that survives a method with a different failure mode. Significant disagreement, heterogeneity, a non-null Egger intercept, or influential SNPs means describe the result as inconclusive rather than causal.
- **Original papers:** [IVW, Burgess et al. 2013](https://doi.org/10.1002/gepi.21758); [MR-Egger, Bowden et al. 2015](https://doi.org/10.1093/ije/dyv080); [weighted median, Bowden et al. 2016](https://doi.org/10.1002/gepi.21965); [weighted mode, Hartwig et al. 2017](https://doi.org/10.1093/ije/dyx102).
