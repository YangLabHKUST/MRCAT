---
name: analysis-method-comparison
description: Compare completed method estimates for one directed pair. Creates figures
  and numerical summaries; the calling agent interprets the evidence. Does not refit
  MR.
accepts-milestones: [mr_primary_result, mrapss_result, mr_bwmr_result, mr_divw_result,
  mr_raps_result, mr_mrmix_result, mr_cml_ma_result, mr_robust_result, mr_lasso_result,
  mr_conmix_result, cause_result, gwas_pair_prepare_result]
produces-milestone: method_comparison_result
reusable-outputs: [comparison_table_path, result_record_path]
---

# analysis-method-comparison

Compare completed method estimates for one directed pair. Creates figures and numerical summaries; the calling agent interprets the evidence. Does not refit MR.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `analysis_method_comparison` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import analysis_method_comparison

result = analysis_method_comparison(
    method_result_paths=['/absolute/path/to/mr_primary_result_record.json',
     '/absolute/path/to/mrapss_result_record.json'],
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["method_comparison_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `method_result_paths` | list | required | Completed inner method result-record paths. |
| `exposure_label` | string | optional | Exposure display label. |
| `outcome_label` | string | optional | Outcome display label. |
| `max_snp_points` | int | 5000 | Maximum plotted SNP points. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

`method_result_paths` contains existing inner result-record paths with `methods`, finite estimates and `ci` objects (`level`, `ranges`); at least two usable method estimates are needed. Do not supply prior comparison reports. SNP plots use the actual selected_mrdat_path saved by the methods; labels and `max_snp_points` affect presentation only. Include the user's requested methods, with missing/failed methods disclosed, rather than inventing replacements.

Use actual inner `result_record_path` files from producers. Keep input_scale consistent (native, standardize and mrmix_standardize are distinct); equal labels alone do not establish comparable phenotype units. Legacy missing scale remains unknown. Never manufacture estimates or metadata to satisfy an input contract.

## Outputs and checks

On success, `result["outputs"]["method_comparison_result"]` holds the data described below.

Contains `comparison_table_path`, `result_record_path`, `plot_manifest`, numerical summaries and diagnostic warnings. It does not generate a model interpretation or a Markdown report. Explain the evidence yourself using participating methods' interpretation guidance. Do not use method agreement as independent causal replication.

## Interpretation by the agent

The tool computes statistics and plots only; it does not call another model to interpret them. Read the actual method results, diagnostics and warnings, then explain them in the user's language. Write a Markdown report when requested. Preserve inconclusive results and failed methods; do not select the most significant estimator as the answer.

## Scientific interpretation checks

Use actual normalized estimates, producer diagnostics and participating skills.
Interpret only methods present in the evidence, by assumptions and failure modes,
not by counting significant p-values. Do not recompute or invent missing evidence.

Use each participating method's own `Method Interpretation` for its identifying
assumptions, relevant evidence and limits. Connect those conditions to the actual
run before judging support. A diagnostic affecting IVW does not automatically
invalidate a method designed to accommodate that violation. If method guidance
or an assessment is absent, disclose the material gap rather than inventing a
validity verdict. Keep method-specific assumptions in their owning Skills.

Start with the reference direction, interval, instrument set and diagnostics.
Explain which observed threat each additional method addresses. Compare actual
thresholds, SNP lineage/counts, input_scale and phenotype units before magnitudes.
Z/sqrt(N) is not automatically SD or log odds. Do not pool native, generic
standardize and MRMix-specific estimates; equal labels alone do not establish
identical QC, instruments or units. Different method p-values may test different
nulls and cannot be ranked as interchangeable evidence.

Cochran-Q identifies model strain, not its biological source. An Egger-intercept
negative test is limited by power. Leave-one-out direction/magnitude instability
means variant dependence. MR-PRESSO correction does not prove removed variants
are biologically pleiotropic. Missing diagnostics and untested thresholds remain
unknown, not reassuring. Preserve failed methods and every disjoint interval.

Use robust_support only for comparable, concordant methods addressing distinct
plausible threats with reassuring relevant diagnostics. Otherwise distinguish
qualified_support, inconclusive, simple_causal_model_challenged,
multiple_mechanism_signal (supported separated modes/intervals), and
insufficient_evidence. State the decisive evidence; classifications are bounded
interpretation, not runtime routes or proof/disproof of causality. Recommendations
do not authorize additional methods or change the confirmed Plan.
