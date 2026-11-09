---
name: analysis-replication
description: Compare at least two completed study combinations for the same exposure/outcome
  question; does not rerun studies or pool estimates.
accepts-milestones: [gwas_selection_result, mr_primary_result, mrapss_result, mr_bwmr_result,
  mr_divw_result, mr_raps_result, mr_mrmix_result, mr_cml_ma_result, mr_robust_result,
  mr_lasso_result, mr_conmix_result, cause_result]
produces-milestone: mr_replication_result
reusable-outputs: [summary_table_path, forest_matrix_path, result_record_path]
---

# analysis-replication

Compare at least two completed study combinations for the same exposure/outcome question; does not rerun studies or pool estimates.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `analysis_replication` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import analysis_replication

result = analysis_replication(
    exposure='Trait X',
    outcome='Trait Y',
    analyses=[{'name': 'Analysis A',
      'exposure_study': {'source': 'opengwas', 'study_id': 'ieu-a-2'},
      'outcome_study': {'source': 'opengwas', 'study_id': 'ieu-a-7'},
      'result_paths': ['/absolute/path/to/analysis_a_result_record.json']},
     {'name': 'Analysis B',
      'exposure_study': {'source': 'opengwas', 'study_id': 'ieu-a-2'},
      'outcome_study': {'source': 'opengwas', 'study_id': 'ieu-a-9'},
      'result_paths': ['/absolute/path/to/analysis_b_result_record.json']}],
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_replication_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `exposure` | string | required | Fixed exposure label. |
| `outcome` | string | required | Fixed outcome label. |
| `analyses` | list | required | Study combinations; exact shape below. |
| `title` | string | optional | Optional display title. |
| `alpha` | float | 0.05 | Significance / confidence-interval alpha. |
| `p_adjust_method` | string | "bh" | Multiple-testing adjustment: bh or none. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

`exposure` and `outcome` label one fixed question. `analyses` requires at least two items with unique `name`, `exposure_study`, `outcome_study`, `result_paths`. Each study object needs `source` and `study_id`; retain available metadata, sample size and ancestry. Result paths are completed inner method records, not selection/download/QC outputs. Preserve partial method failures as missing estimates.

## Interpretation checks

Interpret each branch using its contributing methods' assumptions and actual
diagnostics. Compare phenotype definitions, ancestry, scales, instrument lineage
and sample overlap before attributing differences to replication failure. Shared
exposure data or instruments are expected in some replication designs; different
outcome IDs alone neither establish nor refute independent outcome samples.
Unknown overlap limits an independence claim but is not observed overlap or
proof that the estimates disagree. Compare magnitudes and uncertainty, not just
whether P values fall on opposite sides of a threshold.


`alpha` defaults to 0.05; `p_adjust_method` is `bh` (within method across analyses) or `none`. Different IDs do not prove sample independence. Shared effect axes require documented comparable units; this is a descriptive comparison, not meta-analysis or automatic independent replication.

Use actual inner `result_record_path` files from producers. Keep input_scale consistent (native, standardize and mrmix_standardize are distinct); equal labels alone do not establish comparable phenotype units. Legacy missing scale remains unknown. Never manufacture estimates or metadata to satisfy an input contract.

## Outputs and checks

On success, `result["outputs"]["mr_replication_result"]` holds the data described below.

Contains normalized analyses/estimates, `summary_table_path`, forest matrix, coverage/concordance diagnostics, `plot_manifest` and `result_record_path`.

