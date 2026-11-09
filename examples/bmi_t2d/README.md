# BMI and type 2 diabetes

Follow one research question through literature search, an online-data MR
analysis, a local-file analysis and a follow-up MR-APSS request. This is the
interaction illustrated in Figure 1c. This guide describes how to run it yourself.
The demonstration run is incomplete: the literature, online and local primary-MR
steps finished, but the follow-up MR-APSS step did not complete. No completed
BMI → T2D recording or numerical MR-APSS result is distributed here.

For the included read-only browser example, see the
[Result 4 guide](../result4/README.md).

## Run the workflow yourself

First complete the [installation](../../README.md#install) and
[reference-data setup](../../docs/data.md). Actual analysis requires a configured
model, the relevant R dependencies and access to the chosen data sources. Search
results and model-generated wording may change. Record study IDs and settings
before comparing numerical results.

### Literature inquiry

Ask:

> Does body mass index causally affect type 2 diabetes? Find and briefly summarize
> the relevant Mendelian randomization literature, with verifiable references and
> limitations. Do not run an MR analysis yet.

Read the cited evidence. Literature findings describe previous studies; they are
not results computed in this session.

### Task 1: start with online data

Ask:

> Run a two-sample MR analysis of BMI on type 2 diabetes using suitable online
> GWAS summary statistics. Identify the studies, ancestry, sample sizes and
> potential sample overlap. Download the selected studies, perform QC,
> harmonization and LD clumping, then run IVW, MR-Egger, weighted median and
> weighted mode. Show the plan before execution and report the effect scale,
> instrument counts, estimates and uncertainty.

Inspect the proposed datasets and plan, then confirm. Keep the selected study IDs,
source links, selection thresholds and LD reference with your results.

### Task 2: start with local files

This is an alternative input route. It is not a compulsory repeat of Task 1.
Use **Study setup** to attach the exposure and outcome files and identify their
traits. If entering paths, use paths accessible to the server running MRCAT.

> I have two local GWAS summary-statistic files: EXPOSURE_FILE for BMI and
> OUTCOME_FILE for type 2 diabetes. Run IVW, MR-Egger, weighted median and weighted
> mode after QC, harmonization and LD clumping. Show the plan before execution.
> Preserve the documented study metadata and explain the effect scale.

Replace `EXPOSURE_FILE` and `OUTCOME_FILE` with the actual inputs and supply their
verified metadata. The accompanying data inventory records the files used in the
saved demonstration. Online and local branches can use different studies;
estimates from different input pairs should not be treated as duplicate fits.

The recorded local inputs are `bmi_mrapss.gz` and `t2d_mrapss.gz`, identified in
[local_inputs.json](local_inputs.json) by SHA-256. They correspond to the BMI and
T2D datasets listed in the upstream
[MR-APSS data-source table](https://github.com/YangLabHKUST/MRAPSS_RealDataAnalysis_reproduce/blob/master/GWAS_26and5_source.csv).
These inputs are not included in the repository, wheel or reference-data set.
A local `bmi_t2d_local_inputs.tar` bundle preserves the exact files, but no public
download is configured. Obtain the inputs from their source or the maintainer,
verify the recorded checksums and select the two `.gz` files in Study setup.

For the recorded local branch, use exposure P ≤ 5e-8, LD r² ≤ 0.001, a 1,000 kb
window and the local European GRCh37 reference. Preserve the per-SNP sample sizes
and use `Z/sqrt(N)`-standardized effects. A different LD panel can retain a
different set of instruments even with the same nominal clumping settings.

### Task 3: add MR-APSS in the same conversation

> Now use MR-APSS to analyze the same local BMI and T2D studies. Reuse the suitable
> QC outputs from Task 2. Prepare the pair for MR-APSS using an exposure P-value
> threshold of 5e-5, retaining the matching C and Omega estimates and documenting
> the LD reference and clumping settings. Explain the result and its limitations.

Confirm the additional plan. The useful continuity is reuse of study-level QC.
The prepared instrument set and background parameters must still satisfy
MR-APSS requirements. Its `Z/sqrt(N)` input representation is not automatically a
log odds ratio; do not exponentiate its slope merely because T2D is binary.

## Inspect the evidence

For each analytical branch, check the study identities, input checksums, QC
outputs, preparation settings, instrument count, effect scale, method estimates
and uncertainty. Interpret method agreement with the diagnostics and remaining
assumptions. A software demonstration does not independently establish causal
truth.

Full GWAS inputs and machine-local checkpoints are not part of the Python wheel.
The completed primary analyses do not establish completion of the MR-APSS step.

## Maintainer export

`export_recording.py` creates a read-only browser projection from a completed,
reviewed session. It never changes the source checkpoints. Pass the private
configuration files with `--env-file` so literal credentials can be removed from
the export. Review the result before committing or publishing it.
