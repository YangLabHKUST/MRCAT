---
name: mr-cml-ma
description: "Fit constrained maximum-likelihood model averaging (cML-MA) on a prepared MRdat table."
accepts-milestones: [gwas_pair_prepare_result]
produces-milestone: mr_cml_ma_result
reusable-outputs: [result_record_path]
---

# mr-cml-ma

Fit constrained maximum-likelihood model averaging (cML-MA) on a prepared MRdat table.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `mr_cml_ma` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import mr_cml_ma

result = mr_cml_ma(
    mrdat_path='/absolute/path/to/MRdat.tsv',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_cml_ma_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `mrdat_path` | path | required | Prepared harmonized, LD-clumped MRdat TSV. |
| `input_scale` | string | "standardize" | Allowed: standardize, native. Effect representation; keep explicit user choice. |
| `pvalue_threshold` | float | 5e-8 | Exposure P-value selection threshold; do not relax silently. |
| `min_instruments` | int | 4 | Minimum selected instruments. |
| `random_seed` | int | 1 | Random seed. |
| `random_start` | int | 10 | Number of randomized optimization starts. |
| `n_override` | float | optional | Positive documented sample size; otherwise derived from N.exp/N.out. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Use the verified `mrdat_path` returned by pair preparation. Required base columns: `SNP`, `b.exp`, `b.out`, `se.exp`, `se.out`, `pval.exp`; retain all extra provenance columns. Do not pass raw GWAS or study IDs. Reuse the prepared pair rather than harmonizing or clumping again.

`standardize` (default) recalculates beta=Z/sqrt(N), SE=1/sqrt(N) when all Z.exp/Z.out/N.exp/N.out columns exist. Legacy tables without them retain existing b/se values: reuse only verified standardized pair tables, never relabel raw/native values. `native` uses `b.exp.native`, `se.exp.native`, `b.out.native`, `se.out.native`; it must not silently fall back to standardized values. Without n_override, n is the smaller median of positive N.exp and N.out; SE must never be treated as sample size.

The tool applies pvalue_threshold exactly once and never relaxes it. If too few valid instruments remain, report insufficiency. Decide whether another dataset or a justified user-compatible threshold is appropriate; do not automatically increase the cutoff. Report the threshold and selected SNP count.

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

On success, `result["outputs"]["mr_cml_ma_result"]` holds the data described below.

The payload contains `methods`, `diagnostics`, `interpretation`, `plot_manifest` and `result_record_path`. Reuse the inner result record for downstream comparison; inspect effective threshold, selected SNP count, scale and warnings. Plot paths are listed in the manifest; do not guess filenames.

## Method Interpretation
Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis.

- **Use when:** several selected IVs may be invalid. cML-MA uses constrained maximum likelihood and BIC model averaging to estimate an effect while allowing invalid-IV configurations.
- **Interpret:** the BIC-invalid-IV display is a model-based diagnostic, not proof that a highlighted SNP is biologically pleiotropic. Report the estimate with its uncertainty and whether the conclusion agrees with methods based on different assumptions; do not choose it solely because it finds more significant pairs.
- **Interpretation guardrail:** significance under an invalid-IV configuration is not sufficient by itself. Compare with methods that use different invalid-IV or pleiotropy assumptions before making a causal claim.
- **Recommendation:** use it when invalid IVs are credible and there are enough independent instruments; pair it with CAUSE when correlated pleiotropy is plausible.
- **Original paper:** [Xue et al. 2021](https://doi.org/10.1016/j.ajhg.2021.05.014).
