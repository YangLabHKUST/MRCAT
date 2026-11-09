# MRCAT

MRCAT is a skill-guided agent for Mendelian randomization (MR). It finds GWAS
studies, prepares exposure/outcome data, runs MR methods and diagnostics, and
writes reports grounded in saved results. Conversations can reuse saved evidence.

## Install

Linux and Python 3.11 or newer are required. From the repository root:

```bash
conda env create -f environment.yml
conda activate mrcat
Rscript scripts/install_r_dependencies.R
cp .env.example .env
```

Set your provider, model and API key in `.env`. R libraries and GWAS/reference
resources are separate dependencies; see [data preparation](docs/data.md).
The environment file is an installation recipe, not a complete dependency lock.
The installer reports missing R packages and retrieves the pinned BWMR helper
under its upstream terms. Check an existing installation without modifying it:

```bash
Rscript scripts/install_r_dependencies.R --check
```

If Python and the analysis dependencies are already available:

```bash
python -m pip install .
```

The distribution includes Skills, prompts, Python/R wrappers and Web assets.
Python installation alone does not install R libraries or reference data.

## Reference data

MRCAT provides one complete reference-data set: HapMap3/MHC lists, European
LDSC files, the European GRCh37 panel, EUR/AFR/EAS/SAS GRCh38 panels and the
PLINK executable. It downloads about 2.92 GB and installs about 12.86 GB.
GWAS study inputs are separate.

**The reference data are prepared locally and have not been published.**
Before publication, install the maintainer-provided local archives with:

```bash
python scripts/download_database.py --from-dir /path/to/database-bundles
```

After publication, one command will download, verify and install the complete set:

```bash
python scripts/download_database.py
```

Existing verified files are reused. Use `python scripts/download_database.py
--check` to verify the complete installation without changing files.
Non-European PLINK panels do not change the workflow's European LDSC background
reference. See [data preparation](docs/data.md) for sources, platform restrictions
and storage requirements.

## Start

```bash
mrcat-web --port 7869
```

Open `http://127.0.0.1:7869`, choose your configured provider and ask a research
question. Review and confirm the proposed plan. The console provides conversation,
execution cells, tables, interactive figures, reports and downloads. It supports
study setup with local files, stopping a turn and continuing in an independent copy.

```bash
mrcat --question "Find GWAS studies of systolic blood pressure and coronary artery disease."
mrcat --session session_ID
```

`python main.py` and `python -m mrcat.web.server` use the same implementation.
New sessions use `session_` IDs. Existing `bridge_` IDs and directories remain
valid; both use `/api/sessions` and the same access checks.

For a shared console, follow [Cloudflare Access setup](docs/multi_user.md).
Authenticated users have separate session stores. Model-generated code still
runs under the operator's OS account; web ownership checks are not an OS sandbox.

## Configuration and outputs

Command-line entry points read `.env` and `config.yaml` from the current directory.
`MRCAT_CONFIG_DIR` chooses another settings directory. `--env-file` selects an
explicit environment file. Exported variables take priority, followed by the
explicit file, then the settings directory's `.env`.

Sessions default to `runtime_artifacts/` in the current directory; use
`--artifact-dir /path/to/sessions` for another location. Checkpoints own workflow
state; generated JSON/Markdown and trace files are readable projections.
See [checkpoint storage](docs/checkpoint_storage.md) before backing up sessions
whose SQLite entries link to host-local storage.

`MRCAT_DATABASE_DIR` points directly to your reference database directory.
It does not change the installed code location. Never distribute private `.env`
files, API keys or user sessions.

Supported providers are `anthropic`, `openai`, `deepseek`, `qwen`, `glm`, `grok`
and `custom`. The Web selector currently exposes deepseek, openai and qwen; the
CLI supports the full list. Configure provider-specific `*_API_KEY`, `*_MODEL`
and, if required, `*_BASE_URL`. The `custom` provider uses an OpenAI-compatible
endpoint. `REPORTER_MODEL` optionally overrides the report model.

Match `MRCAT_CONTEXT_TOKENS`, `MRCAT_MAX_OUTPUT_TOKENS` and
`MRCAT_MAX_RETRY_OUTPUT_TOKENS` to the served model. These are explicit capacities,
not values discovered from the provider. `MRCAT_DISABLE_PROXY=1` removes inherited
proxy variables for this process.

## Skills and use

The [26 built-in Skills](docs/skills.md) include GWAS search, selection, download,
QC and pair preparation; MR estimators; and sensitivity, bidirectional, mediation,
replication and cross-result summaries. Skills and generated code use the same
saved result store. Tool completion is an execution status, not proof of a causal
claim. Confirm phenotype definitions, direction, ancestry, assumptions and scales.

Tools can be called from Python as documented in the owning Skill, for example:

```python
from pathlib import Path
from mrcat.tools import mr_primary
result = mr_primary(mrdat_path=Path("prepared_pair.tsv"), output_dir=Path("outputs/primary"))
print(result["summary"])
```

This requires the prepared input contract and R environment in
[mr-primary](skills/mr-primary/SKILL.md).

## Examples

Start `mrcat-web --port 7869` and select **Result 4 · Hexadecanedioate → CAD**
in the sidebar. The included read-only recording shows the original MR analysis,
FinnGen replication and final scientific report, including failed attempts and
subsequent corrections. Viewing it makes no model calls and requires no API key.
Inspect the plans, code, tables and plots in the Conversation and Execution
Notebook. See the [Result 4 guide](examples/result4/README.md) for provenance and
static-site export. The recording contains selected small outputs, not the
original GWAS files or a resumable session database.

Try the [BMI → T2D interactive demo](https://wiki-northern-diploma-cumulative.trycloudflare.com/)
without signing in or supplying an API key. This is a **temporary preview URL**;
it may change or become unavailable when the preview tunnel restarts.

The guided example stays in one session:

1. Search the literature, then select online GWAS studies and run MR.
2. Load the supplied native local GWAS files and run a separate MR analysis.
3. Follow up with MR-APSS using the same local studies and suitable QC outputs.

Preview each request, send it, then review and confirm the proposed analysis
plan. The server runs the agent and analysis tools to generate results and plots;
this is not a recording. Verified pre-QC downloads can be reused, while QC,
pair preparation, MR fitting and plotting run for the new session. The host
provides the model credentials, data and analysis dependencies. Progress and
errors remain visible; runtime depends on the model, tools and external services.

See the [BMI → T2D guide](examples/bmi_t2d/README.md) for hosting with `--auth demo`,
input provenance and checksums, and the manual tutorial. Full GWAS inputs are
not bundled in Git. The historical tutorial run completed the primary analyses
but not its MR-APSS follow-up; publishing this live interface does not establish
that the entire sequence has been rerun successfully.

For an immediately viewable completed analysis, open the
[public Result 4 recording](https://result4.mrcat.science/#example-result4).

## Offline installation check

```bash
python examples/offline_smoke.py
```

This uses a deterministic local model fixture, makes no external model calls,
and checks conversation persistence. It does not perform MR or reproduce a paper
experiment. Scientific analysis requires the real dependencies and inputs above.

## Repository

```text
mrcat/       Agent, model gateway, state, results, reporting and Web console
skills/      Skill guides, Python/R analysis wrappers and plot explanations
scripts/     R dependency installation and reference-data download/verification
examples/    Small software usage examples
tests/       Product behavior, method output and browser regressions
docs/        Architecture, installation resources and user documentation
```

Full paper experiment inputs, runners and results are maintained separately and
are not bundled with this software. The selected read-only example above is
included for inspection. Development audit scripts and records, private settings,
session stores and reference databases are excluded from the source distribution.

## Development

```bash
python -m pip install -e ".[dev]"
ruff check mrcat skills tests
python -m pytest -m "not r" -q
python -m pytest -m r -q
node tests/test_result_formatters.cjs
python -m build
```

Browser scenarios in `tests/browser_*.cjs` use Playwright and deterministic fixture
servers. R tests require the documented analysis libraries. Software tests do not
establish scientific accuracy for every live-model analysis.

Checkpoint tests need a local temporary filesystem. On a machine with an NFS
temporary directory, prefix the test commands with `TMPDIR=/var/tmp`.

## License and citation

Original code uses [BSD-3-Clause](LICENSE). Third-party code and data retain their
own terms; see [THIRD_PARTY.md](THIRD_PARTY.md). [CITATION.cff](CITATION.cff) contains
software citation metadata. Record the actual software version and configuration
used for an analysis. Authorship metadata currently uses MRCAT contributors and
must be finalized before publication.
