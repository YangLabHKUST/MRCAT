---
name: analysis-sensitivity
description: >-
  Run heterogeneity, Egger-intercept, single-SNP, leave-one-out, MR-PRESSO and Steiger
  diagnostics on a completed primary result record and its exact selected MRdat with at
  least four instruments. Steiger needs verified trait metadata; filtering/refitting is
  optional. This is not a generic validator for arbitrary custom MR outputs,
  single-instrument or correlated-instrument fits, and does not perform colocalization.
  Plan applicable custom checks when this suite does not fit.
accepts-milestones: [mr_primary_result]
produces-milestone: mr_sensitivity_result
reusable-outputs: [result_record_path]
---

# analysis-sensitivity

Run heterogeneity, Egger-intercept, single-SNP, leave-one-out, MR-PRESSO and Steiger diagnostics using the exact instruments of a completed primary MR result. Explicitly requested Steiger filtering produces a separate subset and MR refit.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `analysis_sensitivity` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import analysis_sensitivity

result = analysis_sensitivity(
    primary_result_record_path='/absolute/path/to/mr_primary_result_record.json',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_sensitivity_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `primary_result_record_path` | path | required | Inner primary MR result record; not outer response. |
| `nb_distribution` | int | 1000 | Requested minimum MR-PRESSO simulations; increased when needed so instrument count / simulations < signif_threshold. Actual count is recorded. |
| `signif_threshold` | float | 0.05 | MR-PRESSO significance cutoff. |
| `seed` | int | 1234 | Random seed. |
| `detailed_plot_max_instruments` | int | 100 | Detailed-plot limit; statistics still use all selected SNPs. |
| `steiger_metadata` | dict | optional | Verified exposure/outcome types and sample information; schema below. Missing or invalid information makes Steiger unavailable, without suppressing the other diagnostics. |
| `steiger_filter` | bool | false | Retain SNPs with exposure R-squared greater than outcome R-squared, save the subset, and refit the four primary estimators. Does not overwrite the primary result. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Pass the `result_record_path` from `mr-primary` or `mr-primary-id`, not the outer response. That record must retain `selected_mrdat_path`, `input_scale`, and a matching selected-SNP table with at least four instruments. Reuse these exact instruments and scale; do not reclump, reselect or substitute another MRdat. `detailed_plot_max_instruments` limits detailed plot display, not statistical input. Only the explicitly requested Steiger refit uses a subset; the existing diagnostics and overall Steiger test remain on the original instrument set.

## Steiger input requirements

Supply `steiger_metadata={"exposure": {...}, "outcome": {...}}` from verified
study information. Never infer quantitative type from missing disease metadata,
or infer log-odds units from `input_scale="native"` or a binary outcome label.

- **Quantitative trait:** `{"type": "quantitative"}` uses `N.exp` / `N.out`
  in the selected table. An explicit `sample_size` can supply a verified number
  or name a per-SNP sample-size column. Correlations use
  `TwoSampleMR::get_r_from_bsen(beta, SE, N)` on the saved working effects.
- **Binary trait:** requires `type="binary"`, `beta_scale="log_odds"`,
  `eaf_column`, `ncase`, `ncontrol`, and `prevalence`. Native log-odds effects
  must exist as `b.exp.native` / `b.out.native`. `eaf_column` must identify
  observed effect-allele frequencies aligned to those effects, not an unverified
  MAF or population-frequency field. Counts and population prevalence can be
  verified numbers or names of columns in the selected table. Correlations use
  `get_r_from_lor`; tests use `TwoSampleMR::effective_n(ncase, ncontrol)`.
  Do not substitute the study case fraction for population prevalence.
- Every selected SNP must have valid inputs for both traits. There is no
  default prevalence, row-wise fallback or silent complete-case subset.
  Missing information produces `steiger.status="unavailable"` with a reason;
  requested filtering is then `blocked`. Report the gap instead of inventing
  metadata. A historical primary record may need regeneration to retain missing
  columns; never modify its saved selected table in place.

For example, only when both traits are verified quantitative and the saved table
contains their sample sizes:

```python
result = analysis_sensitivity(
    primary_result_record_path='/absolute/path/to/mr_primary_result_record.json',
    steiger_metadata={
        'exposure': {'type': 'quantitative'},
        'outcome': {'type': 'quantitative'},
    },
    steiger_filter=True,  # Enable only when the analysis calls for filtering.
)
```

The overall test compares summed SNP R-squared using mean per-SNP effective
sample sizes, following TwoSampleMR. It assumes the selected instruments are
approximately independent. Summed R-squared at or above one is rejected.

## Outputs and checks

On success, `result["outputs"]["mr_sensitivity_result"]` holds the data described below.

Contains diagnostics, plot manifest and a reusable `result_record_path`. Heterogeneity, Egger intercept, single-SNP/leave-one-out and MR-PRESSO outputs concern the same primary instrument set; distinguish unavailable diagnostics from reassuring negative tests.

MR-PRESSO outliers come from the package's `Outliers Indices`, mapped to the
exact fitted rows. `mr_presso.outlier_status` distinguishes `not_tested`,
`none`, `detected` and `all`; a test that was not run has a null outlier count.
P values retain bounds such as `<0.001` as strings; never remove the inequality
or interpret a bound as an exact P value. The unmodified package result is
saved at `mr_presso.raw_result_path`. Requested and actual simulation counts
are recorded. The automatic increase meets the minimum Monte Carlo resolution
for the chosen cutoff; it does not establish stability for borderline results.

`steiger` contains status, both total R-squared values,
`correct_causal_direction`, `steiger_pval`, interpretation, input provenance,
and `filtering`. `reports.steiger_summary` and `reports.steiger_snps` point to
the overall and per-SNP tables. Successful filtering additionally saves
`steiger_filtered_mrdat` and `steiger_filtered_mr` reports, with retained/removed
counts and removed SNP IDs in `steiger.filtering`. The refit uses IVW, MR-Egger,
weighted median and weighted mode with the original working effects and scale;
it does not rerun all sensitivity diagnostics. Fewer than four retained SNPs
blocks that refit but preserves the subset and the original diagnostics.
Check nested status even when the overall tool status is `ok`.

## Interpreting Steiger results

- `correct_causal_direction=true` means the instruments explain more variance
  in the exposure. With `steiger_pval < 0.05`, describe this as support for the
  proposed exposure-to-outcome direction under Steiger's assumptions.
- `correct_causal_direction=false` with `steiger_pval < 0.05` supports the
  opposite orientation and challenges the proposed direction. It does not
  establish reverse causality; assess reverse MR and the study context.
- `steiger_pval >= 0.05` is inconclusive about direction, regardless of the
  boolean flag. `unavailable` means not evaluated, never passed.
- The P-value tests a difference in explained variance, not whether the MR
  causal effect is nonzero. A favorable direction does not establish causality
  or exclude horizontal pleiotropy, confounding or measurement bias.
- Per-SNP `steiger_dir` is a comparison of R-squared. Filtering retains TRUE
  values without imposing an additional P-value cutoff; it does not mean each
  retained SNP has statistically established direction. Report before/after
  SNP counts, beta, SE/CI and P-value; do not prefer the filtered estimate merely
  because it is more significant. A direction reversal or large effect change
  indicates sensitivity to instrument selection.
- Differential measurement error, winner's curse, sample overlap, LD and
  uncertain case-control prevalence can affect this assessment. Binary-trait
  liability-scale R-squared is an approximation; inspect its metadata carefully.

References: [TwoSampleMR Steiger test](https://mrcieu.github.io/TwoSampleMR/reference/mr_steiger.html),
[Steiger filtering](https://mrcieu.github.io/TwoSampleMR/reference/steiger_filtering.html),
[Hemani et al. 2017](https://doi.org/10.1371/journal.pgen.1007081).

## Interpretation by the agent

The tool computes statistics and plots only; it does not call another model to interpret them. Read the actual method results, diagnostics and warnings, then explain them in the user's language. Write a Markdown report when requested. Preserve inconclusive results and failed methods; do not select the most significant estimator as the answer.

## Scientific interpretation checks

A diagnostic finding is specific to the fitted relation. A nonzero Egger
intercept challenges an IVW-only interpretation; it does not by itself invalidate
the Egger slope, whose interpretation remains conditional on InSIDE and
measurement-error assumptions. Neither Q nor the intercept directly tests those
identifying conditions. Explain effect/interval and influence changes together;
heterogeneity alone does not determine the overall causal verdict.

Single-SNP forest plots retain normal Wald intervals for individual variants
and IVW, and use t(K-2) intervals for the all-SNP MR-Egger row. Steiger-filtered
refits use the same method-specific interval rules as mr-primary.


Integrate primary estimates with each available diagnostic; missing or excerpted
evidence remains unknown. Do not recalculate or invent missing results merely
to make a reassuring report. These are checks of one selected instrument set,
not independent causal confirmations.

- Report IVW and MR-Egger Cochran-Q separately. Heterogeneity indicates model
  strain, not its biological cause.
- The MR-Egger intercept probes directional pleiotropy under its assumptions.
  A non-significant intercept does not prove absence, especially with few IVs.
- Single-SNP and leave-one-out results reveal influential variants; a direction
  reversal or material magnitude change makes the conclusion variant-dependent.
- For MR-PRESSO report global test, outlier identities/count, raw and corrected
  estimates and distortion test when available. Do not select the corrected
  result because it is more significant or call outliers proven pleiotropic.
  SNP-specific outlier testing requires `OUTLIERtest=TRUE` and the MR-PRESSO
  global P value below `signif_threshold`, not a significant causal-effect P
  value. Report that global P value together with `mr_presso.outlier_status`.
  When `not_tested` follows a global P value that does not meet the cutoff,
  explain: "The MR-PRESSO global test was not significant (P=...), so
  SNP-specific outlier testing was not triggered and no outlier-corrected
  estimate was produced." Insert the recorded P value; this is not a failed
  MR-PRESSO run. Report another reason only when supported by the evidence.
  `none` means SNP-specific testing ran without significant outliers;
  `not_tested` and a null count do not mean zero outliers after testing. Use
  the structured status over generic package warnings, task-memory shorthand,
  empty SNP lists, or unmarked plots. A non-significant global test does not
  establish absence of pleiotropy.
  The global test concerns horizontal pleiotropy; the distortion test concerns
  the change in the estimate after outlier removal. A significant global test
  does not establish significant distortion. A null distortion result means
  unavailable, not a negative test.
- Detailed-plot limits skip rendering only. Numeric single-SNP and leave-one-out
  reports remain evidence; a skipped plot is not a missing or negative test.
- Calibrate the conclusion to sample/instrument limitations and actual findings.
  Recommend at most two configured mr-* skills only when their documented
  capabilities address an observed gap; do not recommend primary MR again or
  invent a configured method. No further method is a valid recommendation.
  Advice does not add work to the confirmed Plan or promise proof of causality.
