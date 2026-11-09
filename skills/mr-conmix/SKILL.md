---
name: mr-conmix
description: "Fit the contamination-mixture MR estimator and profile confidence intervals on prepared MRdat."
accepts-milestones: [gwas_pair_prepare_result]
produces-milestone: mr_conmix_result
reusable-outputs: [result_record_path]
---

# mr-conmix

Fit the contamination-mixture MR estimator and profile confidence intervals on prepared MRdat.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `mr_conmix` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import mr_conmix

result = mr_conmix(
    mrdat_path='/absolute/path/to/MRdat.tsv',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_conmix_result"]
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
| `ci_min` | float | optional | Default -1.5 for standardize; required for native. |
| `ci_max` | float | optional | Default 1.5 for standardize; required for native. |
| `ci_step` | float | optional | Default 0.01 for standardize; required for native. |
| `alpha` | float | 0.05 | Significance / confidence-interval alpha. |
| `psi` | float | 0 | Pleiotropy parameter passed to mr_conmix. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Use the verified `mrdat_path` returned by pair preparation. Required base columns: `SNP`, `b.exp`, `b.out`, `se.exp`, `se.out`, `pval.exp`; retain all extra provenance columns. Do not pass raw GWAS or study IDs. Reuse the prepared pair rather than harmonizing or clumping again.

`standardize` (default) recalculates beta=Z/sqrt(N), SE=1/sqrt(N) when all Z.exp/Z.out/N.exp/N.out columns exist. Legacy tables without them retain existing b/se values: reuse only verified standardized pair tables, never relabel raw/native values. `native` uses `b.exp.native`, `se.exp.native`, `b.out.native`, `se.out.native`; it must not silently fall back to standardized values. With native input, supply an explicit compatible ci_min/ci_max/ci_step grid; the standardize default grid is -1.5 to 1.5 by 0.01. Preserve disjoint confidence intervals.

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

On success, `result["outputs"]["mr_conmix_result"]` holds the data described below.

The payload contains `methods`, `diagnostics`, `interpretation`, `plot_manifest` and `result_record_path`. Reuse the inner result record for downstream comparison; inspect effective threshold, selected SNP count, scale and warnings. Plot paths are listed in the manifest; do not guess filenames.

## Method Interpretation

Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis.

### Key assumptions

The contamination-mixture model relies on the largest compatible ratio cluster representing valid instruments, with invalid ratios represented by its contamination model. Identification and uncertainty depend on that cluster structure and the specified invalid-effect distribution.

### Relevant evidence

Read the actual profile likelihood, fitted point estimate, all returned confidence intervals, instrument set and warnings. A single convenient interval cannot replace disjoint intervals or supported modes.

### Interpretation

A dominant profile mode supports a conditional cluster-based estimate; separated modes indicate multiple statistically plausible relations. Compare with other completed methods and scales without treating each cluster as a known biological mechanism.

### Limits

The largest cluster is not proven valid. Multimodality does not establish distinct causal pathways, and this fit does not generally resolve correlated pleiotropy or sample structure. Preserve all supported intervals rather than selecting by significance.

- **Original paper:** [Burgess et al. 2020](https://doi.org/10.1038/s41467-019-14156-4).
