<div align="center">

# MRCAT

**A reliable AI assistant for Mendelian randomization**

[Quick start](#quick-start) · [Demo](#demo) · [Paper experiments](#paper-experiments)

</div>

MRCAT searches for GWAS studies, prepares exposure and outcome data, runs MR
analyses and diagnostics, and writes reports from the saved results. Review the
plan, inspect code and plots, and ask follow-up questions in one workspace.

[![MRCAT workspace showing a BMI–type 2 diabetes analysis](docs/assets/mrcat-workspace.png)](docs/assets/mrcat-workspace.png)

*The MRCAT workspace showing study setup, an analysis plan and interactive results for BMI and type 2 diabetes.*

## Demo

- [Live demo](https://demo.mrcat.science/) — explore a public example or start your own analysis without an API key.
- [Completed analysis: hexadecanedioate → CAD](https://result4.mrcat.science/#example-result4) — explore a recorded session with code, plots and a report.

See the [BMI → T2D tutorial](examples/bmi_t2d/README.md) for example questions and data requirements.

## Quick start

<a id="install"></a>

### 1. Install

Requires Linux, Conda and Git. The environment installs Python 3.11 and R.

```bash
git clone https://github.com/YangLabHKUST/MRCAT.git
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

### 3. Configure OpenGWAS access

For OpenGWAS study searches, authenticated downloads and online LD clumping,
sign in to the [OpenGWAS account page](https://api.opengwas.io/profile/) and
generate a JWT. Set it in the same `.env` file:

```dotenv
OPENGWAS_JWT=your_opengwas_token_here
```

Paste only the token, without a `Bearer ` prefix. This is separate from your
model API key. Tokens currently expire after 14 days; generate a replacement,
update `.env` and restart MRCAT when needed
([OpenGWAS authentication](https://api.opengwas.io/api/)).

Local GWAS files can still require this token if the analysis uses online LD
clumping. A workflow using local inputs and local PLINK clumping, with no
OpenGWAS requests, does not need it. Viewing the included recording does not
need it either. See [OpenGWAS configuration](docs/configuration.md#opengwas)
for details and troubleshooting.

### 4. Start and try a question

```bash
mrcat-web --port 17869
```

Open **http://127.0.0.1:17869** on the same machine. Select your provider under
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
