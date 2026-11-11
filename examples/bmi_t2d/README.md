# BMI and type 2 diabetes

Follow one research question through literature search, an online-data MR
analysis, a local-file analysis and a follow-up MR-APSS request. This is the
interaction illustrated in Figure 1c. This guide describes how to run it yourself.
The demonstration run is incomplete: the literature, online and local primary-MR
steps finished, but the follow-up MR-APSS step did not complete. No completed
BMI → T2D recording or numerical MR-APSS result is distributed here.

For the included read-only browser example, see the
[Result 4 guide](../result4/README.md).

## Interactive hosted demo

The guided demo uses the current frontend and real agent workers in one session:
literature search and online GWAS analysis, supplied local GWAS analysis, then an
MR-APSS follow-up. Example questions fill the chat input and can be edited before
sending. Visitors can also type their own questions, skip suggestions, and reply
to the agent's proposed plans in their own words. Result tables, code and plots appear as execution
progresses. The previous recording is not played back as a new computation.

To host it from this source checkout, configure the server's model/search
credentials and the usual R/LD-reference dependencies, then run:

```bash
python -m mrcat.web.server --auth demo --host 127.0.0.1 --port 7892 \
  --artifact-dir /path/to/dedicated-demo-sessions \
  --demo-data-dir /path/to/original-bmi-t2d-files \
  --env-file /path/to/private-config.env
```

The data directory must contain the two files identified in `local_inputs.json`;
their full SHA-256 checksums are verified at startup. Selecting the local suggestion
adds a removable dataset selection beside the chat input. Sending copies the files
into the visitor's session and populates the existing Study setup fields. No upload
or visitor API key is required. Text and selected data use the existing session/reply
and Study setup APIs, respectively; the user's edited message is preserved.

Publish only this dedicated service through the desired tunnel. Signed,
HTTP-only visitor cookies keep session stores separate and allow continuation
in the same browser for seven days. To publish an existing session for every
visitor, stop any work on that session and move its complete directory into
`<artifact-dir>/public/`. Public sessions appear first in the session list and
use the current frontend and session APIs. They are read only; New chat creates
an independent visitor session. No snapshot export or per-visitor copy is needed.
Reload the page after adding or removing a public example.

Suggestions are optional; ordinary typed
questions and follow-ups are accepted without matching template text or a fixed
sequence. Dataset selections are limited to the supplied examples; uploads,
forks and provider changes are unavailable. It admits one running agent turn at
a time, up to 40 turns per UTC day (`MRCAT_DEMO_DAILY_TURNS`) and 16 user messages
per visitor session. `MRCAT_DEMO_PROVIDER` defaults to `deepseek`. The server pays
for model/search calls; its environment file must remain private. Keep this
artifact directory across restarts to preserve cookies, sessions and allowances.
The demo polls the existing snapshot API for progress, so temporary Cloudflare
Quick Tunnels can be used for previews despite their lack of SSE support. Use a
named tunnel and a fixed hostname for a permanent public link.

The interface is verified with synthetic transport fixtures, not by pretending
that the historical incomplete MR-APSS run succeeded. An actual visitor run can
still fail on external services or scientific prerequisites; those failures
remain visible in the normal conversation and execution notebook.

## Run the workflow yourself

First complete the [installation](../../README.md#install) and
[reference-data setup](../../docs/data.md). Actual analysis requires a configured
model, the relevant R dependencies and access to the chosen data sources. Search
results and model-generated wording may change. Record study IDs and settings
before comparing numerical results.

### Workspace controls

| Area | How to use it |
| --- | --- |
| Sidebar | Start or reopen a session, select a provider in Settings, or open Examples. |
| Study setup | Supply exposure/outcome files and study metadata for local data. |
| Conversation | Ask a question, review the proposed plan and confirm before analysis. |
| Execution Notebook | Inspect code, outputs, tables and plots; expand Files for saved artifacts. |
| Reports and downloads | Open the report and download result files. |

Completed execution does not establish causality. Interpret estimates with the
study design, ancestry, assumptions and diagnostics.

### Literature inquiry

Ask:

> Does BMI causally affect type 2 diabetes? What does the MR literature say?

Read the cited evidence. Literature findings describe previous studies; they are
not results computed in this session.

### Task 1: start with online data

Ask:

> Run MR for BMI and type 2 diabetes using online GWAS data. Show the results and plots.

The hosted demo sends this as a regular chat request. The agent searches for
online GWAS candidates and selects suitable studies before analysis. This
suggestion does not attach files or preselect study IDs.

Inspect the proposed datasets and plan, then confirm. Keep the selected study IDs,
source links, selection thresholds and LD reference with your results.

### Task 2: start with local files

This is an alternative input route. It is not a compulsory repeat of Task 1.
Use **Study setup** to attach the exposure and outcome files and identify their
traits. If entering paths, use paths accessible to the server running MRCAT.

> Use these two local GWAS files to run MR for BMI and type 2 diabetes.

The hosted demo supplies the two local files automatically. In your own installation,
attach the files through **Study setup** before sending this request.
The accompanying data inventory records the files used in the
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

> Now use MR-APSS on the same local data and compare the results.

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
