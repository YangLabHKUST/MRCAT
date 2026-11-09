---
name: gwas-pair-prepare
description: >-
  Joint harmonization, genome-wide LDSC background estimation and LD clumping from two
  formatted summary-association studies. Always estimates C/Omega with the configured
  European LD-score reference; use only when both inputs support that background model.
  Not a standalone harmonization/clumping tool for cis-only, sparse gene-level or
  preselected-instrument inputs. Those analyses still need compatible pair preparation,
  implemented with custom code when this combined tool is unsuitable. Internally
  constructs beta=Z/sqrt(N) and SE=1/sqrt(N) from formatted Z/N; compatible inputs
  need no separate standardization step. Different required Z/N definitions or
  transformations need targeted upstream work. Unless the user specifies otherwise,
  use OpenGWAS API clumping first; after API failure, retry with a verified
  compatible local PLINK reference and report the reference change.
accepts-milestones: [gwas_qc_result]
produces-milestone: gwas_pair_prepare_result
reusable-outputs: [mrdat_path, c_path, omega_path, exposure_label, outcome_label,
  ancestry]
---

# gwas-pair-prepare

Harmonize two formatted studies, estimate background parameters and LD-clump instruments for one directed pair.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `gwas_pair_prepare` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import gwas_pair_prepare

result = gwas_pair_prepare(
    formatted_exposure_path='/absolute/path/to/exposure_formatted.tsv',
    formatted_outcome_path='/absolute/path/to/outcome_formatted.tsv',
    # Set the API population from supported ancestry evidence.
    pop='EUR',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["gwas_pair_prepare_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `formatted_exposure_path` | path | required | Verified formatted exposure study TSV. |
| `formatted_outcome_path` | path | required | Verified formatted outcome study TSV. |
| `exposure_label` | string | optional | Exposure display label. |
| `outcome_label` | string | optional | Outcome display label. |
| `ancestry` | string | optional | Known population or explicit user constraint; omit unknown. |
| `M` | float | optional | Positive compatible LDSC reference SNP count; normally omitted. |
| `h2_fix_intercept` | bool | false | Fix LDSC heritability intercept when justified. |
| `iv_threshold` | float | 5e-5 | Exposure P-value ceiling for reusable instruments. |
| `clump_r2` | float | 0.001 | LD correlation ceiling. |
| `clump_kb` | int | 10000 | LD clumping window in kb. |
| `clump_p` | float | 0.999 | Secondary-variant P-value ceiling. |
| `bfile` | string | optional | Local PLINK reference prefix; see reference rules below. |
| `plink_bin` | path | optional | Local PLINK executable. |
| `pop` | string | optional | Allowed: EUR, AFR, EAS, SAS, AMR. API clumping population; set from reference evidence. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Both paths must be the `formatted_path` from distinct study QC results (or verified equivalent formatted tables), never raw GWAS, canonical tables, study IDs or previously clumped MRdat. Labels are optional. Preserve ancestry provenance; do not assign European ancestry merely to use a European LD panel.

Preserve explicit user or Plan choices of local/API clumping and reference panel. Otherwise use OpenGWAS API clumping first, with population supported by ancestry evidence and without bfile. If the API call fails and user constraints allow a reference change, retry using a local PLINK reference only after verifying population/build compatibility, readable .bed/.bim/.fam files and a usable PLINK executable. An installed EUR panel or matching build alone does not establish compatibility. Record the API failure, the local reference actually used, effective settings and retained SNP count; disclose the switch in the final report because it can change the instrument set and estimates. If no compatible fallback is available, report the blocker. Ordinary resource selection belongs within this execution; add a separate investigation only when reference applicability changes the scientific plan.

Choose LD reference: `bfile` selects local PLINK (prefix without .bed/.bim/.fam, or registered resource ID); omit `pop` and preserve explicit `plink_bin`. IDs include `plink.eur.grch37`, `plink.eur.grch38`, `plink.afr.grch38`, `plink.eas.grch38`, `plink.sas.grch38`. Without `bfile`, set API `pop` to `EUR`, `AFR`, `EAS`, `SAS`, or `AMR` from supported ancestry evidence. If using EUR for unknown/mixed ancestry, explicitly record it as an execution-reference assumption. The example EUR is illustrative, not a study-ancestry assertion.

The Python entrypoint resolves `ldsc.eur` and PLINK resources. LDSC remains European regardless of clumping population; disclose mismatches. On API failure the tool returns the error; it does not choose a local reference. You may explicitly retry with a compatible bfile after inspecting reference metadata and preserving user constraints. Reuse preparation for the same directed pair and compatible settings; native columns survive so scale changes alone do not require re-preparation.

## Effect scale and extra preparation

The tool constructs b.exp/b.out=Z/sqrt(N) and se.exp/se.out=1/sqrt(N)
from each formatted study's Z/N. Downstream estimators can select the standardized
scale from this prepared pair; native effect columns are also retained. For a
request matching this formula and the recorded Z/N definitions, use the QC
formatted outputs directly instead of creating a custom standardization item.
Preserve the requested scale and instrument-selection settings in the plan.

If the requested Z source, N definition or formula differs from the available
contract, establish that difference and prepare only the affected input. Do not
silently replace source selection P values while converting effect scales. If the
user requests a separate full standardized GWAS file, this prepared pair is not
that deliverable; plan a compatible export/conversion only if needed.

## Preparation and reference checks

Prepare each directed pair once from the correct two study outputs. Preserve
separate exposure/outcome identities even when a study is reused in other pairs.
MRdat, C and Omega consumed together must come from the same preparation and
settings; never mix pairs or substitute identity matrices for missing artifacts.
Outcome native beta flips with the harmonized outcome Z; its SE does not.

Preserve explicit local/API choices. In API mode, unambiguous European/Finnish,
African, East Asian, South Asian and Admixed American/Latino ancestry may map to
EUR, AFR, EAS, SAS and AMR respectively. This selects a reference; it never
rewrites the reported ancestry. If using the existing EUR-reference fallback
for unknown/mixed ancestry, record why it is unresolved and the mismatch risk
as `[RISK][SOFT_ASSUMPTION]` before execution. Preserve an explicit pop on a
reference mismatch and disclose it, unless doing so violates a user constraint.
Do not silently switch reference panels after an API failure. A local reference
must have documented compatible population/build and real readable resources.
The LDSC EUR reference remains separate from the clumping reference.

The reusable-pair iv_threshold is not necessarily the final estimator's cutoff;
preserve each explicit requested threshold. Smaller r2 and larger clump_kb mean
stricter LD pruning. M requires a documented compatible LD-score reference;
fixing the heritability intercept imposes an assumption, not a generic repair.
Missing inputs/references, failed harmonization and no usable overlap are
execution obstacles. A disclosed reference assumption is not evidence that
selection passed or that populations are equivalent.

## Outputs and checks

On success, `result["outputs"]["gwas_pair_prepare_result"]` holds the data described below.

`mrdat_path`, `c_path`, `omega_path` feed MR-APSS; `mrdat_path` also feeds other local MR estimators. Keep all three from the same preparation. Read actual thresholds, SNP counts, LD reference and warnings; do not interpret successful preparation as a causal finding.

