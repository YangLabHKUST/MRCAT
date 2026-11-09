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

Raw and outlier-corrected slope confidence intervals use the corresponding
regression's t distribution. For the single-exposure fit, degrees of freedom
are K-1, using the instruments actually retained in that fit. The selected
method row reports that fitted instrument count. Global and distortion tests
retain their separate Monte Carlo P values.

Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis.

### Key assumptions

MR-PRESSO identifies residual outliers relative to an IVW-style relation, relying on a sufficiently large valid-instrument majority and InSIDE for its outlier-correction setting. It targets outlier-driven pleiotropy rather than general correlated or pervasive directional pleiotropy.

### Relevant evidence

Read the global test, outlier-test status and identities/count, raw and corrected estimates with their fitted instrument counts, and distortion test separately. A missing or untriggered test is not a negative result. Preserve simulation resolution and warnings.

### Interpretation

The global test probes residual misfit compatible with horizontal pleiotropy; the distortion test assesses the estimate change after removal. A significant global test does not establish significant distortion. Compare raw/corrected magnitudes and intervals, including a material observed change even if the distortion test is non-significant.

SNP-specific outlier testing requires `OUTLIERtest=TRUE` and the MR-PRESSO
global P value below `signif_threshold`, not a significant causal-effect P value.
Report the global P value and outlier-test status together. When `not_tested`
results from a global P value that does not meet this cutoff, explain:
"The MR-PRESSO global test was not significant (P=...), so SNP-specific outlier
testing was not triggered and no outlier-corrected estimate was produced."
Insert the recorded P value. This is a completed global test, not a failed
MR-PRESSO run. If another reason is recorded, report that reason instead.

`none` means SNP-specific testing ran without significant outliers;
`not_tested` does not. A null outlier count is unavailable, not zero. Preserve
this distinction over generic package warnings such as "No outlier were
identified", task-memory shorthand, empty SNP lists, or unmarked plots. Do not
describe an untriggered test as having tested and cleared every SNP.

### Limits

Outliers are not proven biologically pleiotropic, and correction does not verify the remaining IVs or InSIDE. A non-significant global test cannot establish absence of pleiotropy. Do not choose a corrected estimate merely because it is more significant.

- **Original paper:** [Verbanck et al. 2018](https://doi.org/10.1038/s41588-018-0099-7).
