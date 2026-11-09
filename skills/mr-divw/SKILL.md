---
name: mr-divw
description: "Fit debiased IVW (dIVW) on a prepared MRdat table."
accepts-milestones: [gwas_pair_prepare_result]
produces-milestone: mr_divw_result
reusable-outputs: [result_record_path]
---

# mr-divw

Fit debiased IVW (dIVW) on a prepared MRdat table.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `mr_divw` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import mr_divw

result = mr_divw(
    mrdat_path='/absolute/path/to/MRdat.tsv',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_divw_result"]
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
| `lambda_` | float | optional | Omit to use installed mr.divw package default; explicit finite number overrides it. |
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

On success, `result["outputs"]["mr_divw_result"]` holds the data described below.

The payload contains `methods`, `diagnostics`, `interpretation`, `plot_manifest` and `result_record_path`. Reuse the inner result record for downstream comparison; inspect effective threshold, selected SNP count, scale and warnings. Plot paths are listed in the manifest; do not guess filenames.

## Method Interpretation

Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis.

### Key assumptions

dIVW debiases IVW for noisy SNP-exposure associations under its many-weak-instrument framework. It requires adequate aggregate instrument strength, independent-IV/two-sample conditions and valid IVs or the method's balanced-pleiotropy conditions; directional or correlated pleiotropy is not corrected. Selection-bias protection depends on the selection design and must not be assumed when selection and estimation reuse noisy exposure associations.

### Relevant evidence

Read the actual selection design, strength diagnostics, instrument counts, estimates, uncertainty and warnings. Do not infer an independent selection GWAS or adequate aggregate strength from a relaxed P threshold alone.

### Interpretation

Compare with IVW using comparable scales and instrument sets. A difference is compatible with weak-IV sensitivity, but is not proof of attenuation or permission to prefer the larger estimate. Preserve uncertainty in the debiased fit.

### Limits

A finite or significant result does not verify the selection or pleiotropy assumptions. Do not describe dIVW as a universal correction for invalid IVs, winner's curse or population structure.

- **Original paper:** [Ye et al. 2021](https://doi.org/10.1214/20-AOS2027).
