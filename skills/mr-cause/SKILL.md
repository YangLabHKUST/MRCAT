---
name: mr-cause
description: >-
  Fit CAUSE causal and sharing models from two genome-wide canonical studies, including
  its own harmonization and LD clumping. Needs the broad variant universe for nuisance
  estimation, not cis-only, sparse gene-level or previously selected MR instruments.
  Consumes neither formatted MRdat nor C/Omega. Does not perform gene/tissue selection
  or regional colocalization; a custom implementation cannot compensate for missing
  genome-wide evidence. Internally supports input_scale="standardize" using
  beta=Z/sqrt(N) and SE=1/sqrt(N) from canonical statistics and documented N;
  compatible inputs need no separate standardization step. Different required
  Z/N definitions or transformations need targeted upstream work. Unless the user
  specifies otherwise, use OpenGWAS API clumping first; after API failure, retry
  with a verified compatible local PLINK reference and report the reference change.
accepts-milestones: [gwas_qc_result]
produces-milestone: cause_result
reusable-outputs: [result_record_path]
---

# mr-cause

Fit CAUSE causal and sharing models from two genome-wide canonical studies, with its own harmonization and clumping.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `mr_cause` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import mr_cause

result = mr_cause(
    canonical_exposure_path='/absolute/path/to/exposure_canonical.tsv',
    canonical_outcome_path='/absolute/path/to/outcome_canonical.tsv',
    # Set the API population from supported ancestry evidence.
    pop='EUR',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["cause_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `canonical_exposure_path` | path | required | Genome-wide canonical exposure table. |
| `canonical_outcome_path` | path | required | Genome-wide canonical outcome table. |
| `exposure_label` | string | optional | Exposure display label. |
| `outcome_label` | string | optional | Outcome display label. |
| `ancestry` | string | optional | Known population or explicit user constraint; omit unknown. |
| `input_scale` | string | "standardize" | Allowed: standardize, native. Effect representation; keep explicit user choice. |
| `exposure_sample_size` | float | optional | Documented positive exposure N fallback when canonical sample-size fields are unavailable. |
| `outcome_sample_size` | float | optional | Documented positive outcome N fallback when canonical sample-size fields are unavailable. |
| `pval_thresh` | float | 0.001 | CAUSE instrument selection P-value ceiling. |
| `r2_thresh` | float | 0.01 | CAUSE LD clumping r-squared ceiling. |
| `clump_kb` | int | 10000 | LD clumping window in kb. |
| `param_variant_sample_size` | int | 1000000 | Maximum variants sampled for nuisance estimation. |
| `seed` | int | 1 | Random seed. |
| `bfile` | path | optional | Local PLINK reference prefix; see reference rules below. |
| `plink_bin` | path | optional | Local PLINK executable. |
| `pop` | string | optional | Allowed: EUR, AFR, EAS, SAS, AMR. API clumping population; set from reference evidence. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Use `canonical_path` from each study's QC result, not formatted or clumped MRdat. Preserve the genome-wide variant universe and allele/scale provenance. Required column names are SNP, effect_allele, other_allele, beta, or, se, z, pval, neglog10_pval, n (unused alternate statistics may be missing values); the tool performs CAUSE-specific formatting, harmonization and QC. Standardization requires positive sample-size information; sample-size fallback parameters must be documented.

Preserve explicit user or Plan choices of local/API clumping and reference panel. Otherwise use OpenGWAS API clumping first, with population supported by ancestry evidence and without bfile. If the API call fails and user constraints allow a reference change, retry with a local panel only after verifying population/build compatibility, readable .bed/.bim/.fam files and a usable PLINK executable. Installation alone does not establish compatibility. With `bfile`, pass an actual PLINK prefix and a usable `plink_bin` (resource IDs are not resolved here as they are in pair preparation). Unknown ancestry/build is unresolved compatibility, not evidence for EUR; any permitted EUR assumption must be explicitly justified and reported. Record the API failure, actual local reference, effective settings and retained SNP count, and disclose the switch in the final report because it can change the instrument set and estimates. If no compatible fallback is available, report the blocker. API failure does not switch panels automatically; the executor must explicitly retry with the verified local reference. CAUSE uses its own clumping; it does not consume C/Omega.

## Effect scale and extra preparation

For input_scale="standardize", the tool constructs beta=Z/sqrt(N) and
SE=1/sqrt(N) internally. It uses populated canonical Z first, otherwise signed
P-derived Z when available, otherwise beta/SE. N comes from canonical n, otherwise
n_cases+n_controls, otherwise a documented sample-size parameter. A sample-size
parameter does not override populated canonical n. Check these source and
sample-size rules against the request; native beta/SE and P-derived Z are not
interchangeable by assumption.

When the rules match, pass canonical QC outputs directly and retain the requested
scale in the fit item. A canonical table without a populated z column does not
by itself require custom code if the documented fallback satisfies the request.
Add targeted upstream investigation/conversion only for incompatible required
Z/N definitions, an unsupported transformation, or a separate standardized-file
deliverable not already provided. Preserve source selection P values and the
broad variant universe; missing evidence cannot be repaired by inventing N or Z.

## CAUSE execution checks

Use two full canonical studies, not a primary estimator's selected SNP set or
formatted/clumped MRdat. The method owns its formatting, harmonization and LD
clumping. Apply task-wide thresholds and windows unless explicitly excluded:
for example P < 5e-8 means pval_thresh=5e-8, and 1 Mb means clump_kb=1000.
Do not omit a user parameter merely because the Plan item does not repeat it.

Preserve local/API reference choices, actual population/build and unresolved
reference risks. EUR as an execution assumption does not establish European
study ancestry. Missing canonical inputs, no usable merged variants or a fitting
failure remain obstacles; do not replace CAUSE with another estimator.
param_variant_sample_size and seed govern nuisance-parameter sampling, not a
new dataset or relaxed instrument threshold. The retained backend can force a
fit after nuisance non-convergence; report that explicitly, not as convergence.

Distinguish official sharing/causal/ELPD diagnostic plots from a paper-style
illustration. A plotting threshold or illustrated IVW slope does not change the
actual CAUSE fitting threshold or supply its causal evidence. Preserve source
units and use the model-comparison definitions below when interpreting results.

## Outputs and checks

On success, `result["outputs"]["cause_result"]` holds the data described below.

The payload contains `methods`, `diagnostics`, `interpretation`, `plot_manifest` and `result_record_path`. Reuse the inner result record for downstream comparison; inspect effective threshold, selected SNP count, scale and warnings. Plot paths are listed in the manifest; do not guess filenames.

## Method Interpretation

Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis.

### Key assumptions

CAUSE compares genome-wide causal and sharing models, allowing a shared factor to affect a subset of variants as well as uncorrelated pleiotropy. Distinguishing a causal effect from sharing depends on these model/distributional assumptions, appropriate genome-wide inputs and nuisance/error-correlation estimation.

### Relevant evidence

Read causal-versus-sharing predictive comparison, posterior effect/interval, convergence and nuisance-fit warnings, and LD/input provenance. Do not apply per-SNP F > 10 to reject genome-wide CAUSE input or substitute a primary estimator's selected instrument set.

### Interpretation

beta.hat is the causal-model gamma posterior median and ci its 95% posterior credible interval. pval is the one-sided causal-versus-sharing ELPD test, not a Wald test of beta=0. For the sharing-versus-causal row, negative delta_elpd favors the causal model. A nonzero gamma alone is insufficient; assess whether the causal model improves on sharing and whether diagnostics support the fit.

### Limits

Model preference does not establish biological causality or that a shared factor has been identified. Report nonconverged/forced nuisance fits as numerically unstable. se is null; posterior intervals cannot be converted to frequentist SEs or used in SE-based delta-method mediation. Agreement with other methods remains conditional on their different assumptions.
