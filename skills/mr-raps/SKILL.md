---
name: mr-raps
description: "Fit robust adjusted profile-score MR (RAPS) on a prepared MRdat table."
accepts-milestones: [gwas_pair_prepare_result]
produces-milestone: mr_raps_result
reusable-outputs: [result_record_path]
---

# mr-raps

Fit robust adjusted profile-score MR (RAPS) on a prepared MRdat table.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `mr_raps` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import mr_raps

result = mr_raps(
    mrdat_path='/absolute/path/to/MRdat.tsv',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_raps_result"]
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
| `diagnostics` | bool | true | Request RAPS diagnostic plots. |
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

On success, `result["outputs"]["mr_raps_result"]` holds the data described below.

The payload contains `methods`, `diagnostics`, `interpretation`, `plot_manifest` and `result_record_path`. Reuse the inner result record for downstream comparison; inspect effective threshold, selected SNP count, scale and warnings. Plot paths are listed in the manifest; do not guess filenames.

## Method Interpretation

Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis.

### Key assumptions

RAPS accounts for exposure-association uncertainty with many weak independent IVs. Its random-effects pleiotropy model is centered and independent of instrument strength; robust loss limits occasional large outliers. Systematic directional or correlated pleiotropy is not generally covered.

### Relevant evidence

Inspect actual strength/selection, fitted estimates and intervals, convergence/warnings, and residual or pleiotropy diagnostics when supplied. Discuss threshold stability only if multiple thresholds were actually fitted; one run cannot establish it.

### Interpretation

Compare RAPS with IVW on comparable instruments and scales. Differences can be compatible with weak-IV sensitivity or residual weighting, but do not identify the cause by themselves. State which observed threat RAPS addresses and what uncertainty remains.

### Limits

Robust fitting or a significant result does not establish the pleiotropy model or exclude overlap/population bias. Do not select the larger or more significant estimate as the answer.

- **Original paper:** [Zhao et al. 2020](https://doi.org/10.1214/19-AOS1866).
