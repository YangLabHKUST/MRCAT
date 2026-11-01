---
name: mr-apss
description: >-
  Fit MR-APSS on LD-clumped MRdat with matching C/Omega estimated from compatible
  genome-wide studies. This implementation supports only Z/sqrt(N)-standardized inputs.
  The background model is required, not optional; a sparse single-gene or cis-only
  association table cannot be assumed suitable. Does not perform cis-region selection,
  LD-aware cis-MR or colocalization. Preserve an explicitly requested method and assess
  feasibility rather than substitute another estimator.
accepts-milestones: [gwas_pair_prepare_result]
produces-milestone: mrapss_result
reusable-outputs: [result_record_path]
---

# mr-apss

Fit MR-APSS using prepared MRdat and matching C/Omega background matrices.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `mr_apss` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import mr_apss

result = mr_apss(
    mrdat_path='/absolute/path/to/MRdat.tsv',
    c_path='/absolute/path/to/C.tsv',
    omega_path='/absolute/path/to/Omega.tsv',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mrapss_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `mrdat_path` | path | required | Prepared harmonized, LD-clumped MRdat TSV. |
| `c_path` | path | required | Matching pair-preparation C matrix. |
| `omega_path` | path | required | Matching pair-preparation Omega matrix. |
| `exposure_label` | string | optional | Exposure display label. |
| `outcome_label` | string | optional | Outcome display label. |
| `input_scale` | string | "standardize" | Allowed: standardize. Effect representation; keep explicit user choice. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Use the verified `mrdat_path` returned by pair preparation. Required base columns: `SNP`, `b.exp`, `b.out`, `se.exp`, `se.out`, `pval.exp`, `L2`, `Threshold`; retain all extra provenance columns. Do not pass raw GWAS or study IDs. Reuse the prepared pair rather than harmonizing or clumping again.

MR-APSS fits the complete prepared instrument set without further P-value selection. It preserves `MRdat$Threshold`, the upstream selection-bias correction threshold, which can differ from the nominal `iv_threshold`. Do not overwrite this column or use it to filter SNPs. To change the nominal IV threshold, rerun `gwas_pair_prepare` with the requested `iv_threshold` and pass its matching MRdat/C/Omega. The fit function does not accept `pvalue_threshold`; missing, invalid or inconsistent correction thresholds require fresh preparation, not a guessed default.

MR-APSS supports only `standardize`: explicit Z.exp/Z.out/N.exp/N.out recalculate Z/sqrt(N); legacy pair tables retain their existing standardized b/se. Verify that provenance before reuse. C and Omega must come from the same directed pair and variant preparation.

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

On success, `result["outputs"]["mrapss_result"]` holds the data described below.

The payload contains `methods`, `diagnostics`, `interpretation`, `plot_manifest` and `result_record_path`. Reuse the inner result record for downstream comparison; inspect `methods[].Threshold` and `diagnostics.selection_bias_threshold` as the fitted correction threshold, not the nominal SNP-selection cutoff. Obtain the nominal cutoff from pair preparation. Check the selected SNP count, scale and warnings. Plot paths are listed in the manifest; do not guess filenames.

## Method Interpretation
Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis.

- **Use when:** traits are highly polygenic, moderately associated IVs are informative, or population structure, cryptic relatedness, and sample overlap may bias conventional two-sample MR. MR-APSS uses the prepared `C` and `Omega` background parameters to model sample structure and pleiotropy.
- **Instrument strength:** inclusion of moderately associated or individually weak IVs is an intended feature. The reported `IVstrength` is MR-APSS's total IV signal (`IVsignal.sum`), not a conventional per-SNP F statistic; do not apply the `F > 10` rule or call the fit unreliable from this value alone.
- **Interpret:** the estimate is conditional on this background model. Report the estimate, confidence interval, p-value, `nsnp`, `pi0`/`nvalid`, and `IVstrength`. Compare it with primary MR; discordance can reflect different instrument selection or correction for weak IVs and sample structure, not necessarily an error in either method.
- **Threshold sensitivity:** describe a result as threshold-sensitive only when multiple MR-APSS thresholds were actually tested and produced materially different results. With one threshold, state that threshold robustness was not assessed.
- **Interpretation guardrail:** a result that appears only after loosening the instrument threshold is sensitivity evidence, not automatic confirmation. Report how instrument strength, sample structure, and pleiotropy adjustment change the estimate.
- **Original paper:** [Hu et al. 2022](https://doi.org/10.1073/pnas.2106858119).
