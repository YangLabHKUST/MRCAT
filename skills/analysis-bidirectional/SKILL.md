---
name: analysis-bidirectional
description: Summarize completed forward and reverse MR results for one or more trait
  pairs; does not fit MR.
accepts-milestones: [mr_primary_result, mrapss_result, mr_bwmr_result, mr_divw_result,
  mr_raps_result, mr_mrmix_result, mr_cml_ma_result, mr_robust_result, mr_lasso_result,
  mr_conmix_result, cause_result]
produces-milestone: mr_bidirectional_result
reusable-outputs: [summary_table_path, quadrant_plot_path, result_record_path]
---

# analysis-bidirectional

Summarize completed forward and reverse MR results for one or more trait pairs; does not fit MR.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `analysis_bidirectional` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import analysis_bidirectional

result = analysis_bidirectional(
    pair_results=[{'trait_x': 'Trait X',
      'trait_y': 'Trait Y',
      'forward_result_paths': ['/absolute/path/to/xy_result_record.json'],
      'reverse_result_paths': ['/absolute/path/to/yx_result_record.json']}],
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_bidirectional_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `pair_results` | list | required | Nested pair records; exact shape below. |
| `title` | string | optional | Optional display title. |
| `alpha` | float | 0.05 | Significance / confidence-interval alpha. |
| `p_adjust_method` | string | "bh" | Multiple-testing adjustment: bh or none. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

`pair_results` is a nonempty list. Each item requires `trait_x`, `trait_y`, `forward_result_paths` (X to Y) and `reverse_result_paths` (Y to X). Both path lists contain completed inner method records; at least one method must occur in both directions. Labels must differ; unordered pairs and result paths must not be duplicated. Optional `title` is display text. `p_adjust_method` is `bh` or `none`.

Forward/reverse estimates use different instruments and units: keep independent effect axes; never negate a forward beta to fabricate a reverse estimate. Evidence quadrants summarize directional evidence, not causal truth.

Use actual inner `result_record_path` files from producers. Keep input_scale consistent (native, standardize and mrmix_standardize are distinct); equal labels alone do not establish comparable phenotype units. Legacy missing scale remains unknown. Never manufacture estimates or metadata to satisfy an input contract.

## Interpretation checks

Align exact method names and retain all completed requested endpoints. Consensus
uses methods with finite p-values in both directions; never use the minimum
p-value or count methods as independent studies. BH correction is separate for
forward and reverse estimates across the submitted batch. Quadrant coordinates
are median evidence margins log10(alpha/q), not effect sizes. Forward-only,
reverse-only, bidirectional and null describe directional evidence, not causal
truth. Use replication analysis for repeated study combinations of one direction.

## Outputs and checks

On success, `result["outputs"]["mr_bidirectional_result"]` holds the data described below.

Contains `summary_table_path`, `mirrored_forest_plot_paths`, `quadrant_plot_path`, pair summaries, diagnostics, `plot_manifest` and `result_record_path`.
