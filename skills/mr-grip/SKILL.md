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

Both ordinary and weak-instrument-adjusted estimates use t-based confidence
intervals with K-2 degrees of freedom, matching the package P values. Missing
adjusted uncertainty remains unavailable rather than being inferred from P.

Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis.

### Key assumptions

MR-GRIP modifies MR-Egger to achieve invariance to allele recoding. It relies on VICE (Variance Independent of Covariance Explained), an identifying independence condition on genetic-variance and direct-covariance contributions. VICE is not simply ordinary MR-Egger's InSIDE under a new name. The ordinary fit also relies on sufficiently small exposure measurement error; the adjusted fit targets weak-instrument bias.

### Relevant evidence

Read standard and weak-instrument-adjusted slopes and their own uncertainty, intercept/strength diagnostics and numerical warnings when supplied. Allele-recoding invariance, convergence or an intercept test does not verify VICE. Missing adjusted uncertainty remains unavailable.

### Interpretation

Compare the two fits and other completed methods using their respective identifying conditions. An intercept signal does not by itself invalidate a slope designed to allow directional pleiotropy. Explain actual uncertainty or instability rather than choosing the adjusted or more significant estimate automatically.

### Limits

Adjustment does not guarantee validity or replace strength assessment. This implementation does not itself resolve overlap, residual population structure or arbitrary correlated pleiotropy. Preserve supplied scale provenance; an absent input_scale remains unknown.

- **Original method reference:** [Dudbridge et al.](https://doi.org/10.1371/journal.pgen.1011967).
