---
name: mr-grip
description: "Fit MR-GRIP and its weak-instrument-adjusted estimate on a prepared MRdat table."
accepts-milestones: [gwas_pair_prepare_result]
produces-milestone: mr_grip_result
reusable-outputs: [result_record_path]
---

# mr-grip

Fit MR-GRIP and its weak-instrument-adjusted estimate on a prepared MRdat table.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `mr_grip` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import mr_grip

result = mr_grip(
    mrdat_path='/absolute/path/to/MRdat.tsv',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_grip_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `mrdat_path` | path | required | Prepared harmonized, LD-clumped MRdat TSV. |
| `pvalue_threshold` | number | 5e-08 | Exposure P-value selection threshold; do not relax silently. |
| `min_instruments` | integer | 4 | Minimum selected instruments. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Use the verified `mrdat_path` returned by pair preparation. Required base columns: `SNP`, `b.exp`, `b.out`, `se.exp`, `se.out`, `pval.exp`; retain all extra provenance columns. Do not pass raw GWAS or study IDs. Reuse the prepared pair rather than harmonizing or clumping again.

This implementation uses the supplied b/se columns directly and has no input_scale switch. Preserve upstream scale evidence; its result record currently omits input_scale, so do not invent it for downstream comparisons.

The tool applies pvalue_threshold exactly once and never relaxes it. If too few valid instruments remain, report insufficiency. Decide whether another dataset or a justified user-compatible threshold is appropriate; do not automatically increase the cutoff. Report the threshold and selected SNP count.

## Outputs and checks

On success, `result["outputs"]["mr_grip_result"]` holds the data described below.

The payload contains `methods`, `diagnostics`, `interpretation`, `plot_manifest` and `result_record_path`. Reuse the inner result record for downstream comparison; inspect effective threshold, selected SNP count, scale and warnings. Plot paths are listed in the manifest; do not guess filenames.

## Method Interpretation

MR-GRIP modifies MR-Egger to make its estimate invariant to allele recoding.
Report the standard and weak-instrument-adjusted estimates separately, with
their uncertainty. Neither estimate guarantees instrument validity. The
adjustment does not replace instrument-strength assessment, and this estimator
does not itself resolve sample overlap or residual population structure.
Interpret agreement or disagreement with other methods through their
assumptions and diagnostics, rather than selecting the most significant result.
Use the supplied effect-scale provenance; an absent input_scale is unknown,
not permission to label the estimate as standardized or log odds.
