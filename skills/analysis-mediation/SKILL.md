---
name: analysis-mediation
description: Compute separate two-step mediation estimates from completed X-to-Y,
  X-to-M and M-to-Y MR results.
accepts-milestones: [mr_primary_result, mrapss_result, mr_bwmr_result, mr_divw_result,
  mr_raps_result, mr_mrmix_result, mr_cml_ma_result, mr_robust_result, mr_lasso_result,
  mr_conmix_result, cause_result]
produces-milestone: mr_mediation_result
reusable-outputs: [mediation_table_path, forest_plot_paths, result_record_path]
---

# analysis-mediation

Compute separate two-step mediation estimates from completed X-to-Y, X-to-M and M-to-Y MR results.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `analysis_mediation` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import analysis_mediation

result = analysis_mediation(
    total_effect_results=['/absolute/path/to/xy_result_record.json'],
    indirect_paths=[{'name': 'Mediator',
      'x_to_m_results': ['/absolute/path/to/xm_result_record.json'],
      'm_to_y_results': ['/absolute/path/to/my_result_record.json']}],
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_mediation_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `total_effect_results` | list | required | X-to-Y inner MR result-record paths. |
| `indirect_paths` | list | required | Mediator paths; exact shape below. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

`total_effect_results` is a nonempty list of completed X-to-Y inner method records. Each `indirect_paths` item contains exactly `name`, `x_to_m_results`, `m_to_y_results`; each path list must contain real completed records. Mediator names must be unique and each path must share a method across all three legs. Documented, compatible input scales and mediator units are required; MRMix-specific scales are not accepted.

## Interpretation checks

Indirect beta is the product of the two component estimates. Delta-method uncertainty assumes zero component covariance. Proportion mediated needs a nonzero total effect. Treat mediators separately; do not sum correlated indirect effects or claim joint adjustment.

Use actual inner `result_record_path` files from producers. Keep input_scale consistent (native, standardize and mrmix_standardize are distinct); equal labels alone do not establish comparable phenotype units. Legacy missing scale remains unknown. Never manufacture estimates or metadata to satisfy an input contract.

## Outputs and checks

On success, `result["outputs"]["mr_mediation_result"]` holds the data described below.

Contains `mediation_paths`, `mediation_table_path`, `forest_plot_paths`, diagnostics, `plot_manifest` and `result_record_path`.
