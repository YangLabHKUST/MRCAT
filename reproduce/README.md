# Paper data and reproduction

This directory connects the MRCAT manuscript experiments to their inputs,
recorded runs and results. The software and these instructions share one GitHub
repository. Large evidence files belong to one Zenodo record.

**Availability, checked 10 November 2026:** the existing Zenodo deposit is an
unpublished draft. Its reserved DOI is `10.5281/zenodo.24056307`; it is not yet a
public download or a published dataset citation. The inventory below describes
the prepared files, not a publicly available release. No new runs were performed
for this inventory.

## What to download

Once the record is published, download its README and all three ZIP files from
the same record, then extract the ZIP files into one directory outside the Git
checkout. Together they form one evidence package:

```text
mrcat-paper-data/
├── README.md
├── input/
│   ├── inputs.csv
│   ├── 30benchmark/
│   └── reference-analysis/
├── agent-trace/
│   ├── 30benchmark/
│   ├── reference/
│   │   ├── mrapss/
│   │   └── negative-control/
│   ├── risk-factor/
│   └── bidirectional/
└── scores/
```

The download is approximately 14.8 GB; allow additional space for extraction.
[archives.csv](archives.csv) records the byte sizes and MD5 checksums returned
by Zenodo for the current draft. These identify that snapshot and must be updated
if the files change. MD5 is used here for transfer integrity.

The paper evidence package is separate from the LD panels, HapMap3 resources,
LDSC resources and PLINK required to run MRCAT. Prepare those using the single
reference-resource installation described in [Data preparation](../docs/data.md).
Do not use `input.zip` as a replacement for the runtime database.

## Find an experiment

Paths beginning with `input/`, `agent-trace/` or `scores/` below are relative to
the extracted evidence directory. Figure numbers follow manuscript order, rather
than the names of the source PDF files.

| Manuscript experiment | Inputs and recorded evidence | What remains separate |
| --- | --- | --- |
| Fig. 1: architecture and illustrative BMI–T2D workflow | Current software and [BMI–T2D tutorial](../examples/bmi_t2d/README.md). | The illustration is not a completed benchmark replay. The historical tutorial's MR-APSS follow-up was incomplete. |
| Fig. 2: 30-query benchmark | `input/30benchmark/`; `agent-trace/30benchmark/runs.csv`; per-agent query directories; `scores/summary.csv`, `gate_scores.csv`, `gate_evidence.csv`; `agent-trace/30benchmark/usage/`. | Online GWAS caches, a portable four-agent runner and the final composite-figure plotting code are not supplied by these archives. |
| Fig. 3: expert-curated comparisons | `input/reference-analysis/`; `agent-trace/reference/mrapss/` including `reference-data/`; `agent-trace/reference/negative-control/` including `results/method_results.csv` and `results/negative_control_interpretations.csv`. | A portable comparison runner and final figure assembly are not supplied. Negative-control Q01–Q06 are independent of benchmark Q01–Q30. |
| Fig. 4: hexadecanedioate–CAD reporting case | Dataset identifiers are in [gwas_sources.csv](gwas_sources.csv). The [recorded example](https://result4.mrcat.science/#example-result4) is also backed by `mrcat/web/static/examples/result4/recording.json` in the software repository. | The three ZIP files have no dedicated reporting-case directory. The full report is Supplementary Data 1; a permanent archive copy of this case and its rerun procedure still need to be added. |
| Fig. 5: RA risk-factor assessment | `agent-trace/risk-factor/MRCAT/`; `agent-trace/risk-factor/results/`, including the GWAS source, analysis-setting and estimate CSV files. | Original online GWAS download caches and portable rerun/figure-assembly commands are not supplied. |
| Fig. 6: bidirectional T2D–CAD analysis | `agent-trace/bidirectional/MRCAT/`; `agent-trace/bidirectional/results/`, including the GWAS source, analysis-setting and estimate CSV files. | Original online GWAS download caches and portable rerun/figure-assembly commands are not supplied. |

For the supplementary material:

- **Benchmark tables and heatmap:** complete queries are in [queries.csv](queries.csv).
  Scores, the G1–G9/B1 rubric, 952 recorded decisions and 104 execution-completion
  entries are under `scores/`. The heatmap source is
  `scores/query_level_gate_scores.csv` (120 system–query rows). Its finished
  rendering is not in the ZIP files. Agent compatibility, tool inventories and
  environment descriptions remain in the manuscript's supplementary tables;
  the archives do not provide complete execution environments.
- **Expert-comparison tables:** original GWAS access routes are in
  [gwas_sources.csv](gwas_sources.csv). Negative-control numerical results,
  interpretations and the Claude Code Q02 sign-correction results are under
  `agent-trace/reference/negative-control/results/`. Failed runs remain in the
  per-agent directories and must not be counted as successful analyses.
- **Reporting-case tables:** dataset identities, processing counts and estimates
  are in the manuscript's reporting-case supplementary tables and Supplementary
  Data 1. This portion has not yet been integrated into the Zenodo package.
- **Downstream tables and plots:** source metadata, settings and estimates are
  in each downstream `results/` directory. [supplementary_figures.csv](supplementary_figures.csv)
  maps all 39 RA and bidirectional supplementary PNGs to byte-identical saved
  files in `agent-trace.zip`, with SHA-256 hashes. It also records the missing
  benchmark heatmap rendering. These are saved plots, not portable plotting
  programs. The Skill catalogue is documented in [Skills](../docs/skills.md).

## Use the queries and inputs

[queries.csv](queries.csv) contains the manuscript's 30 benchmark requests,
one MR-APSS request and six negative-control requests. `query_original` preserves
the manuscript wording after removing TeX formatting. `query_package_paths`
changes only the local input paths to their locations in the evidence package.
For a new run, replace those relative `input/...` paths with absolute paths to
your extracted files, then submit the request through the configured MRCAT
interface. Follow [Configuration](../docs/configuration.md) and the
[tutorial](../examples/bmi_t2d/README.md) to set up a session.

[inputs.csv](inputs.csv) maps 33 query–file assignments to 29 retained input
files. Some queries share the same file, and compressed originals replace
redundant expanded copies. In particular, the MR-APSS BMI input is stored in the
negative-control directory, and negative-control Q03 reuses benchmark files.
Use the mapping instead of assuming every case has its own copies.

[gwas_sources.csv](gwas_sources.csv) lists the original access routes for the
reference comparisons and study identifiers for the reporting and downstream
cases. URLs were transcribed from the manuscript, not retested as downloads.
A blank URL means that the table identifies a resource and study rather than
a direct file URL. Online benchmark requests retain their source constraints
in `queries.csv`; inspect the selected run for the actual chosen studies.
Keep the recorded genome build, ancestry and resource release when retrieving
data. Original providers' access and reuse terms still apply.

## Inspect results or rerun analyses

To inspect the paper's recorded results, start with the relevant result CSV,
then follow its evidence paths into the traces. The package-relative indexes
are intended for navigation. Text inside original traces can still contain
historical machine paths; these are not runnable instructions on another host.

For a new analysis, install MRCAT, configure the provider and data credentials
privately, prepare the reference resources, and submit the mapped query. Record
the exact software commit, environment, model/provider, input identifiers and
settings with the new results. Keep new outputs outside the historical evidence
directory. New agent runs can differ because models, services and data change.

The selected historical benchmark versions are recorded per run in
`agent-trace/30benchmark/runs.csv`. A blank version field is unknown provenance;
the current GitHub commit must not be substituted for it. These archives are
recorded evidence, not resumable LangGraph checkpoints or a validated one-command
reproduction of all paper figures. Independent scoring/review code is not part
of this distribution; the recorded decisions and rubric document the evaluation.

## Release status

The following work remains before describing this as a complete reproduction
release:

1. Integrate the reporting-case materials into the permanent evidence archive.
2. Provide and validate portable experiment/figure commands where indicated
   above, with the correct historical software and environment provenance.
3. Review archive contents for embedded credentials and excluded review code,
   and confirm redistribution terms for reused inputs. The filename inspection
   found no `.env` or audit-named entries, but this alone does not establish that
   all trace contents are safe to publish.
4. Confirm Zenodo creators and licensing. The draft currently has no creators
   and its `cc-zero` setting has not been approved as the license for this mixed
   collection of original and third-party materials.
5. Publish the existing record, verify unauthenticated downloads, and update
   this guide and the manuscript with the published record URL and citation.

The inventory was checked against the active `MRCATPaper_V2` manuscript on
10 November 2026. Execution-completion values and heatmap values match the
corresponding supplementary tables; archive-relative paths differ from the
manuscript's original paths. Downstream estimate values and negative-control
interpretations also match Supplementary Data 2 after accounting for relocated
evidence paths and the split between the two downstream directories.
