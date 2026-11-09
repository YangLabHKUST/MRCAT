---
name: mr-mrmix
description: "Fit the MRMix mixture model on a prepared MRdat table."
accepts-milestones: [gwas_pair_prepare_result]
produces-milestone: mr_mrmix_result
reusable-outputs: [result_record_path]
---

# mr-mrmix

Fit the MRMix mixture model on a prepared MRdat table.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `mr_mrmix` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import mr_mrmix

result = mr_mrmix(
    mrdat_path='/absolute/path/to/MRdat.tsv',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_mrmix_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `mrdat_path` | path | required | Prepared harmonized, LD-clumped MRdat TSV. |
| `input_scale` | string | "standardize" | Allowed: standardize, native, mrmix_standardize. Effect representation; keep explicit user choice. |
| `pvalue_threshold` | float | 5e-8 | Exposure P-value selection threshold; do not relax silently. |
| `min_instruments` | int | 4 | Minimum selected instruments. |
| `exposure_type` | string | optional | Allowed: continuous, binary. continuous or binary; required for mrmix_standardize. |
| `outcome_type` | string | optional | Allowed: continuous, binary. continuous or binary; required for mrmix_standardize. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Use the verified `mrdat_path` returned by pair preparation. Required base columns: `SNP`, `b.exp`, `b.out`, `se.exp`, `se.out`, `pval.exp`; retain all extra provenance columns. Do not pass raw GWAS or study IDs. Reuse the prepared pair rather than harmonizing or clumping again.

`standardize` (default) recalculates beta=Z/sqrt(N), SE=1/sqrt(N) when all Z.exp/Z.out/N.exp/N.out columns exist. Legacy tables without them retain existing b/se values: reuse only verified standardized pair tables, never relabel raw/native values. `native` uses `b.exp.native`, `se.exp.native`, `b.out.native`, `se.out.native`; it must not silently fall back to standardized values. `mrmix_standardize` additionally requires exposure_type/outcome_type and positive N for continuous traits and observed frequencies for binary traits; preserve its distinct units.

The tool applies pvalue_threshold exactly once and never relaxes it. If too few valid instruments remain, report insufficiency. Decide whether another dataset or a justified user-compatible threshold is appropriate; do not automatically increase the cutoff. Report the threshold and selected SNP count.

## Scale checks

For mrmix_standardize, require documented continuous/binary types; do not infer
them from trait names. Continuous scaling uses beta/(SE*sqrt(N)), SE=1/sqrt(N).
Binary scaling uses beta*sqrt(2*f*(1-f)) and SE*sqrt(2*f*(1-f)) with observed
frequency, never a QC-imputed 0.5. These assume the corresponding linear/logistic
association model. Keep this scale distinct from generic standardize and native.
Inspect recorded theta-grid bounds/spacing and profile stability: native input
uses a ratio/SE-derived grid; other scales retain the upstream grid. A scale or
grid change is not evidence of a different biological mechanism.

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

On success, `result["outputs"]["mr_mrmix_result"]` holds the data described below.

The payload contains `methods`, `diagnostics`, `interpretation`, `plot_manifest` and `result_record_path`. Reuse the inner result record for downstream comparison; inspect effective threshold, selected SNP count, scale and warnings. Plot paths are listed in the manifest; do not guess filenames.

## Method Interpretation

Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis.

### Key assumptions

MRMix uses a mixture model of exposure/outcome effects to identify a valid-instrument component under a zero-modal-pleiotropy condition. Its interpretation depends on an identifiable valid component and the mixture assumptions; fitting several components does not guarantee that the valid component was recovered.

### Relevant evidence

Use instrument count, the actual profile/solution stability, estimates, intervals, scale and numerical warnings. A sparse instrument set or unstable profile affects identification; do not manufacture a stability assessment when absent.

### Interpretation

Compare the mixture estimate with IVW and other completed methods using comparable units. Discordance can reflect mixture/variant sensitivity but does not identify which method or biological explanation is correct.

### Limits

A stable solution does not establish the validity condition or exclude weak-IV, correlated-pleiotropy or population-structure problems. Retain unstable or ambiguous fits and avoid selecting a preferred direction or P value.

- **Original paper:** [Qi and Chatterjee 2019](https://doi.org/10.1038/s41467-019-09432-2).
