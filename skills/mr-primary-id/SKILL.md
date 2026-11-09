---
name: mr-primary-id
description: >-
  Quick fixed IVW, MR-Egger, weighted-median and weighted-mode suite from two OpenGWAS
  study IDs; retrieves associations, clumps and harmonizes internally. Requires
  network/authentication; default minimum is four instruments. Supports native or
  Z/sqrt(N)-standardized effects. Does not consume local files or enforce a
  gene/tissue/cis-region design, and has no single-SNP Wald-ratio or colocalization
  branch. An eQTL ID alone does not establish applicability.
accepts-milestones: [gwas_selection_result]
produces-milestone: mr_primary_result
reusable-outputs: [result_record_path]
---

# mr-primary-id

Run IVW, MR-Egger, weighted median and weighted mode directly from two OpenGWAS study IDs. Requires network access and OpenGWAS authentication.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `mr_primary_id` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import mr_primary_id

result = mr_primary_id(
    exposure_gwas_id='xxx_exposure',
    outcome_gwas_id='xxx_outcome',
    pvalue_threshold=5e-8,
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_primary_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `exposure_gwas_id` | string | required | Complete exposure OpenGWAS ID. |
| `outcome_gwas_id` | string | required | Complete outcome OpenGWAS ID. |
| `exposure_label` | string | optional | Exposure display label. |
| `outcome_label` | string | optional | Outcome display label. |
| `input_scale` | string | "standardize" | Allowed: standardize, native. Effect representation; keep explicit user choice. |
| `exposure_sample_size` | float | optional | Documented positive exposure N override. |
| `outcome_sample_size` | float | optional | Documented positive outcome N override. |
| `pvalue_threshold` | float or list[float] | 5e-8 | Exact cutoff, or an explicitly chosen increasing schedule. No implicit relaxation. |
| `clump_r2` | float | 0.001 | LD correlation ceiling. |
| `clump_kb` | int | 10000 | LD clumping window in kb. |
| `min_instruments` | int | 4 | Minimum selected instruments. |
| `harmonise_action` | int | 2 | TwoSampleMR harmonization action. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Both inputs are complete OpenGWAS IDs. The example IDs are illustrative; replace them with the selected studies. This route retrieves instruments/outcome associations and harmonizes them, rather than consuming local MRdat. Standardized effects require positive N from metadata or documented `exposure_sample_size`/`outcome_sample_size` overrides. Retain available source-unit documentation for the final report.

The tool attempts only the supplied cutoff or explicit schedule. A scalar is
never expanded into a schedule. A supplied list must be strictly increasing;
the tool stops at the first eligible set and never continues based on MR
significance. If there are too few instruments, decide the next action using
the user's requirements and returned evidence. API/authentication errors are
not zero instruments.

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

On success, `result["outputs"]["mr_primary_result"]` holds the data described below.

The payload contains `methods`, `diagnostics`, `interpretation`, `plot_manifest` and `result_record_path`. Reuse the inner result record for downstream comparison; inspect effective threshold, selected SNP count, scale and warnings. Plot paths are listed in the manifest; do not guess filenames.

`selected_mrdat_path` and `input_scale` are required for sensitivity reuse. Primary plots are scatter and estimates forest; invoke analysis-sensitivity only when those diagnostics are needed.

## Method Interpretation

Confidence intervals match the method's P-value distribution: normal for IVW
and weighted median, t(K-2) for MR-Egger, and t(K-1) for weighted mode, where K
is the number of fitted instruments. Forest plots use the saved intervals.

Explain findings in the user's language. Describe the fitted input representation and supported units once in the final report; missing source units alone do not require extra analysis.

### Key assumptions

This route fits the same four estimators as mr-primary. IVW requires valid IVs or balanced pleiotropy uncorrelated with instrument strength and sufficiently small exposure measurement error. MR-Egger permits directional pleiotropy under InSIDE and sufficiently small measurement error (NOME). Weighted median requires a majority of total IV weight to be valid; weighted mode requires a valid largest weighted ratio cluster under zero-modal pleiotropy.

### Relevant evidence

Read selected IVs, strength, estimates, intervals and available Q, intercept and influence diagnostics. These do not establish InSIDE, NOME, the valid-weight majority or the modal-cluster condition. Do not invent absent diagnostics or infer them from study IDs.

### Interpretation

A nonzero Egger intercept can challenge IVW without invalidating the Egger slope under its own assumptions. A null intercept does not establish validity. Compare effect magnitudes and intervals, not significance alone; imprecise compatible estimates are not contradictory. Explain which observed diagnostic affects which estimate.

### Limits

These are complementary estimates from shared data, not four independent confirmations. Neither agreement nor any single diagnostic determines the causal verdict. State remaining assumptions and the resulting degree of support without prescribing the expected direction.

- **Original papers:** [IVW, Burgess et al. 2013](https://doi.org/10.1002/gepi.21758); [MR-Egger, Bowden et al. 2015](https://doi.org/10.1093/ije/dyv080); [weighted median, Bowden et al. 2016](https://doi.org/10.1002/gepi.21965); [weighted mode, Hartwig et al. 2017](https://doi.org/10.1093/ije/dyx102).

## Scale failure recovery

`scale_input_invalid` means the API returned instruments but their effect scale
cannot be prepared with the supplied inputs. Inspect the side, invalid-row count
and reason in the selection trace. Native exposure/outcome and harmonized RDS
files are retained under reports for repair. Obtain missing N only from supported
metadata for the same study (preserving total versus case/control semantics),
then supply the existing exposure_sample_size/outcome_sample_size arguments.
The tool first attempts one batch metadata lookup through the existing OpenGWAS
client for missing sample sizes on both sides. It matches exact study IDs, fills
only missing row values and saves the metadata and resolution trace. Existing
sample sizes and explicit overrides are retained. Check this trace before
repeating a failed metadata request; never guess endpoints or invent N. A failed
lookup still blocks scale preparation and is not an instrument-count result.
Do not reinterpret this as absent instruments, relax the P-value threshold or
switch input_scale to native to hide the error. A harmonization exception is
reported separately as harmonization_failed.

## Instrument-count recovery after valid scale preparation

The tool evaluates a scalar threshold once. If it reports too few eligible
instruments, inspect the selection trace and distinguish user-fixed parameters
from defaults. When the user left the threshold unspecified, choose and record
a bounded threshold schedule before rerunning, justify it by instrument strength
and the requested method, and pass that explicit list as `pvalue_threshold` in
one tool call. The tool stops at the first eligible set. Keep the method's
minimum instrument requirement; do not reduce it to force a result. Preserve
the study IDs, phenotype and population. Do not use MR direction or significance
to choose a threshold or continue the schedule after a valid fit. Report the
actual threshold and any weak-instrument limitations. If the user explicitly
fixed a required value, ask before changing it. A generic confirmation alone
does not turn tool defaults into fixed scientific requirements.
