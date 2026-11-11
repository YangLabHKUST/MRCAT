<div align="center">

# MRCAT

**An AI assistant for Mendelian randomization**

[Quick start](#quick-start) · [Demo](#demo) · [Paper experiments](#paper-experiments)

</div>

MRCAT searches for GWAS studies, prepares exposure and outcome data, runs MR
analyses and diagnostics, and writes reports from the saved results. Review the
plan, inspect code and plots, and ask follow-up questions in one workspace.

[![MRCAT workspace showing a recorded analysis](docs/assets/mrcat-workspace.png)](docs/assets/mrcat-workspace.png)

*The workspace displaying the included read-only analysis example.*

## Demo

- [BMI → T2D live demo](https://wiki-northern-diploma-cumulative.trycloudflare.com/) — try an analysis without your own API key (temporary preview).
- [Completed analysis: hexadecanedioate → CAD](https://result4.mrcat.science/#example-result4) — explore a recorded session with code, plots and a report.

See the [BMI → T2D tutorial](examples/bmi_t2d/README.md) for example questions and data requirements.

## Quick start

<a id="install"></a>

### 1. Install

Requires Linux, Conda and Git. The environment installs Python 3.11 and R.

```bash
git clone https://github.com/77JULIE/MRCAT.git
cd MRCAT
conda env create -f environment.yml
conda activate mrcat
Rscript scripts/install_r_dependencies.R
```

Scientific analysis also requires GWAS inputs and [Reference data](#reference-data).

### 2. Configure a model

Copy the settings template once, or edit your existing `.env`:

```bash
cp .env.example .env
```

For DeepSeek, set these entries in `.env`:

```dotenv
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

Keep `.env` private. See [model configuration](docs/configuration.md#choose-a-provider)
for other providers, model limits and troubleshooting.

### 3. Start and try a question

```bash
mrcat-web --port 7869
```

Open **http://127.0.0.1:7869** on the same machine. Select your provider under
**Settings**, then choose **New Chat**. For remote or shared access, see the
[deployment guide](docs/multi_user.md).

> What information should I prepare for an MR analysis of BMI and type 2 diabetes?

To inspect the included recording without an API key or reference data, choose
**Examples** in the sidebar.

## Reference data

GWAS inputs and reference panels are separate from the software installation.
The prepared reference archives are not yet publicly downloadable; see
[data preparation](docs/data.md) for local installation, requirements and sources.

## Paper experiments

- **Experiment inputs:** [10.5281/zenodo.24056307](https://doi.org/10.5281/zenodo.24056307)
- **Agent run records and benchmark scores:** [10.5281/zenodo.24123092](https://doi.org/10.5281/zenodo.24123092)
