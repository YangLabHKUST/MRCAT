---
name: analysis-result-synthesis
description: Summarize completed MR estimates for at least two distinct directed trait
  pairs; does not fit MR.
accepts-milestones: [mr_primary_result, mrapss_result, mr_bwmr_result, mr_divw_result,
  mr_raps_result, mr_mrmix_result, mr_cml_ma_result, mr_robust_result, mr_lasso_result,
  mr_conmix_result, cause_result]
produces-milestone: mr_result_synthesis
reusable-outputs: [summary_table_path, forest_plot_path, result_record_path]
---

# analysis-result-synthesis

Summarize completed MR estimates for at least two distinct directed trait pairs; does not fit MR.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `analysis_result_synthesis` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import analysis_result_synthesis

result = analysis_result_synthesis(
    pair_results=[{'exposure': 'Trait X',
      'outcome': 'Trait Y',
      'result_paths': ['/absolute/path/to/xy_result_record.json']},
     {'exposure': 'Trait Z',
      'outcome': 'Trait Y',
      'result_paths': ['/absolute/path/to/zy_result_record.json']}],
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_result_synthesis"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `pair_results` | list | required | Nested pair records; exact shape below. |
| `title` | string | optional | Optional display title. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

`pair_results` requires at least two distinct directed pairs. Each item has `exposure`, `outcome`, and nonempty `result_paths` of completed inner MR method records. Group all requested methods for a pair together and include the pair once. Do not pass higher-level comparison, mediation or prioritization outputs. Optional `title` is display text.

## Interpretation checks

The inferred design can be many-to-one, one-to-many or a matrix; raw betas are not universally comparable across traits/units.

Use actual inner `result_record_path` files from producers. Keep input_scale consistent (native, standardize and mrmix_standardize are distinct); equal labels alone do not establish comparable phenotype units. Legacy missing scale remains unknown. Never manufacture estimates or metadata to satisfy an input contract.

## Outputs and checks

On success, `result["outputs"]["mr_result_synthesis"]` holds the data described below.

Contains `design`, normalized pairs/estimates, `summary_table_path`, `forest_plot_path`, diagnostics, `plot_manifest` and `result_record_path`.
