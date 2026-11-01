---
name: mr-presso
description: "Run MR-PRESSO global, outlier and distortion tests and raw/corrected estimates on prepared MRdat."
accepts-milestones: [gwas_pair_prepare_result]
produces-milestone: mr_presso_result
reusable-outputs: [result_record_path]
---

# mr-presso

Run MR-PRESSO global, outlier and distortion tests and raw/corrected estimates on prepared MRdat.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `mr_presso` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import mr_presso

result = mr_presso(
    mrdat_path='/absolute/path/to/MRdat.tsv',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_presso_result"]
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
| `nb_distribution` | int | 1000 | Requested minimum simulations; increased when needed so instrument count / simulations < signif_threshold. Actual count is recorded. |
| `signif_threshold` | float | 0.05 | MR-PRESSO significance cutoff. |
| `seed` | int | 1234 | Random seed. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Use the verified `mrdat_path` returned by pair preparation. Required base columns: `SNP`, `b.exp`, `b.out`, `se.exp`, `se.out`, `pval.exp`; retain all extra provenance columns. Do not pass raw GWAS or study IDs. Reuse the prepared pair rather than harmonizing or clumping again.

`standardize` (default) recalculates beta=Z/sqrt(N), SE=1/sqrt(N) when all Z.exp/Z.out/N.exp/N.out columns exist. Legacy tables without them retain existing b/se values: reuse only verified standardized pair tables, never relabel raw/native values. `native` uses `b.exp.native`, `se.exp.native`, `b.out.native`, `se.out.native`; it must not silently fall back to standardized values. Simulation count must resolve the Bonferroni-adjusted outlier cutoff, not merely exceed the instrument count; report raw and corrected results separately.

Outlier identities are read from the package's `Outliers Indices` and mapped
to the exact fitted rows. `mr_presso.outlier_test.status` distinguishes
`not_tested`, `none`, `detected` and `all`; a test that was not run has a null
count. Diagnostic P values retain bounds such as `<0.001` as strings, not
exact numbers. The unmodified package result is saved at
`diagnostics.raw_result_path`. Requested and actual simulation counts are
recorded; meeting the minimum resolution does not establish stability for
borderline results. A missing distortion test is unavailable, not negative.

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

On success, `result["outputs"]["mr_presso_result"]` holds the data described below.

The payload contains `methods`, `diagnostics`, `interpretation`, `plot_manifest` and `result_record_path`. Reuse the inner result record for downstream comparison; inspect effective threshold, selected SNP count, scale and warnings. Plot paths are listed in the manifest; do not guess filenames.

## Method Interpretation
Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis.

- **Use when:** a small number of horizontally pleiotropic outlier SNPs may
  distort an IVW-style estimate. MR-PRESSO tests global heterogeneity, detects
  outliers, and compares raw with outlier-corrected estimates.
- **Interpret:** report whether the method row is raw or outlier-corrected, then
  report both estimates when available, the global-test P value, outlier count
  and identities, and distortion-test P value.
- **Guardrail:** a significant global test indicates model misfit compatible
  with horizontal pleiotropy; it does not identify a biological mechanism. A
  non-significant test does not prove that balanced or correlated pleiotropy is
  absent, especially with few instruments or too few simulations.
- **Comparison:** use MR-PRESSO alongside prespecified estimators. Do not select
  the corrected result post hoc merely because its P value is more favorable.
- **Original paper:** [Verbanck et al. 2018](https://doi.org/10.1038/s41588-018-0099-7).
