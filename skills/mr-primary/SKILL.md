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

Confidence intervals use the same reference distribution as each method's
P value: normal for IVW and weighted median, t with K-2 degrees of freedom for
MR-Egger, and t with K-1 degrees of freedom for weighted mode, where K is the
number of fitted instruments. Plots preserve these saved intervals.

Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis.

### Key assumptions

- **IVW:** valid instruments, or balanced pleiotropy uncorrelated with instrument strength; exposure-association measurement error must be sufficiently small for the fitted model.
- **MR-Egger:** InSIDE (instrument strength independent of direct effects) allows directional pleiotropy. Unadjusted regression also relies on sufficiently small exposure-association measurement error (NOME); ordinary per-SNP F statistics do not establish NOME or InSIDE.
- **Weighted median:** a majority of the total instrument weight must come from valid IVs, not merely a majority of SNPs.
- **Weighted mode:** under zero-modal pleiotropy, the largest weighted ratio cluster represents valid IVs; the valid group need not be an absolute majority.

### Relevant evidence

Use the actual selected instruments, strength information, method-specific estimates and intervals, IVW/Egger Q, Egger intercept and influence diagnostics when supplied. These do not directly verify InSIDE, the valid-weight majority or the valid modal cluster. Missing assessments remain unknown.

### Interpretation

Use IVW as a reference and compare magnitude, uncertainty and diagnostic sensitivity across these complementary estimators. A nonzero Egger intercept challenges an IVW-only interpretation but does not itself invalidate the Egger slope: that slope remains conditional on InSIDE and measurement-error assumptions. A null intercept does not prove absence of pleiotropy. Compare slopes and intervals before treating differences as disagreement; a wide interval containing the null is not evidence against a more precise compatible estimate. Median/mode agreement provides conditional robustness, not proof of their validity conditions.

### Limits

Do not turn heterogeneity, an intercept signal or an influential SNP alone into an automatic overall causal or inconclusive verdict. Explain which estimator and part of the claim are affected, then weigh the remaining estimates and uncertainty. The four fits share data and are not independent confirmations. Preserve unresolved assumptions in the final causal interpretation.

- **Original papers:** [IVW, Burgess et al. 2013](https://doi.org/10.1002/gepi.21758); [MR-Egger, Bowden et al. 2015](https://doi.org/10.1093/ije/dyv080); [weighted median, Bowden et al. 2016](https://doi.org/10.1002/gepi.21965); [weighted mode, Hartwig et al. 2017](https://doi.org/10.1093/ije/dyx102).
