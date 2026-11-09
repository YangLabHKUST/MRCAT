---
name: analysis-risk-factor-prioritization
description: Summarize at least two exposures against one outcome from completed MR
  estimates, with within-method BH adjustment.
accepts-milestones: [mr_primary_result, mrapss_result, mr_bwmr_result, mr_divw_result,
  mr_raps_result, mr_mrmix_result, mr_cml_ma_result, mr_robust_result, mr_lasso_result,
  mr_conmix_result, cause_result]
produces-milestone: mr_risk_factor_prioritization_result
reusable-outputs: [summary_table_path, forest_plot_path, method_matrix_path, result_record_path]
---

# analysis-risk-factor-prioritization

Summarize at least two exposures against one outcome from completed MR estimates, with within-method BH adjustment.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `analysis_risk_factor_prioritization` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import analysis_risk_factor_prioritization

result = analysis_risk_factor_prioritization(
    outcome='Trait Y',
    exposure_results=[{'exposure': 'Trait X',
      'result_paths': ['/absolute/path/to/xy_result_record.json']},
     {'exposure': 'Trait Z',
      'result_paths': ['/absolute/path/to/zy_result_record.json']}],
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_risk_factor_prioritization_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `outcome` | string | required | Fixed outcome label. |
| `exposure_results` | list | required | Exposure labels and result paths; shape below. |
| `primary_method` | string | optional | Explicit user-selected ordering method. |
| `title` | string | optional | Optional display title. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

`outcome` is one label; `exposure_results` contains at least two unique `exposure` labels with nonempty `result_paths` lists of completed inner MR method records. Retain the user's display labels and all completed requested methods. Missing methods stay missing. `primary_method` optionally chooses an explicitly requested ordering method; otherwise exposure order is preserved. Optional `title` affects display.

## Interpretation checks

A causal interpretation of a prioritized exposure remains conditional on its
own contributing methods' assumptions and relevant diagnostics. Prioritization
does not test those assumptions or adjust causal effects for the other exposures.
Explain whether ranking differences reflect scale, precision, coverage or actual
method sensitivity. Missing diagnostic evidence is unassessed, not reassuring.


Do not treat absolute beta as a universal risk score across differently scaled exposures.
BH q-values are adjusted within each method across the submitted exposures.
Preserve missing method cells and coverage differences; a ranking or a small
P value does not establish causality or an independent effect of each risk factor.

Use actual inner `result_record_path` files from producers. Keep input_scale consistent (native, standardize and mrmix_standardize are distinct); equal labels alone do not establish comparable phenotype units. Legacy missing scale remains unknown. Never manufacture estimates or metadata to satisfy an input contract.

## Outputs and checks

On success, `result["outputs"]["mr_risk_factor_prioritization_result"]` holds the data described below.

Contains long-form `summary_table_path`, forest figure, method matrix, BH q-values, coverage diagnostics, `plot_manifest` and `result_record_path`.

