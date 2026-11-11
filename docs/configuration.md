# Configuration

[Back to the quick start](../README.md#quick-start)

MRCAT reads local model settings from `.env`. For the web console, keys are
configured by the person running the server, not entered by visitors in the
browser. A provider must have working credentials before it can run a new analysis.
Viewing the included read-only recording does not require credentials.

## Choose a provider

Copy `.env.example` to `.env` once, then edit the existing entries for your
chosen provider. Do not overwrite an existing settings file or append duplicate
values. The template defaults to DeepSeek to match the README example and the
web menu.

| Provider | `LLM_PROVIDER` | API key | Model | Endpoint | Web menu |
| --- | --- | --- | --- | --- | --- |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | `DEEPSEEK_MODEL` | `DEEPSEEK_BASE_URL` | Yes |
| OpenAI | `openai` | `OPENAI_API_KEY` | `OPENAI_MODEL` | `OPENAI_BASE_URL` | Yes |
| Qwen | `qwen` | `QWEN_API_KEY` | `QWEN_MODEL` | `QWEN_BASE_URL` | Yes |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | `ANTHROPIC_MODEL` | `ANTHROPIC_BASE_URL` | CLI only |
| GLM | `glm` | `GLM_API_KEY` | `GLM_MODEL` | `GLM_BASE_URL` | CLI only |
| Grok | `grok` | `GROK_API_KEY` | `GROK_MODEL` | `GROK_BASE_URL` | CLI only |
| OpenAI-compatible endpoint | `custom` | `CUSTOM_API_KEY` | `CUSTOM_MODEL` | `CUSTOM_BASE_URL` | CLI only |

The key comes from your provider account. The model value is the API model ID
available to that account, not its display name. An endpoint is an API base URL,
not a chat website. The template supplies example endpoints and model IDs;
check availability with your provider when configuring a new model.

### DeepSeek

Edit these entries in `.env`:

```dotenv
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

Get a key from the [provider platform](https://platform.deepseek.com/) and check
its [API guide](https://api-docs.deepseek.com/) for model and endpoint details.
Replace the key placeholder; leave other providers' keys blank if unused.
Select **deepseek** in the web menu before starting a new chat.

### OpenAI or Qwen

For OpenAI, set `LLM_PROVIDER=openai`, fill `OPENAI_API_KEY`, set `OPENAI_MODEL`
to an API model available to your account, and use the appropriate
`OPENAI_BASE_URL`. Select **openai** in the web menu.

For Qwen, set `LLM_PROVIDER=qwen` and fill `QWEN_API_KEY`, `QWEN_MODEL` and
`QWEN_BASE_URL` for your account's region and endpoint. Select **qwen** in the
web menu. Model access and endpoints can differ across accounts and regions.

After editing `.env`, stop the web server with Ctrl+C, restart it and create a
new chat. The chosen provider is saved with a session; changing the menu is
not a migration of an existing conversation.

### CLI and custom endpoints

The CLI supports all providers in the table. For example, after configuring
Anthropic in `.env`:

```bash
mrcat --provider anthropic --question "Explain the assumptions of two-sample MR. Do not run an analysis."
```

For a custom OpenAI-compatible endpoint, configure:

```dotenv
LLM_PROVIDER=custom
CUSTOM_API_KEY=your_api_key_here
CUSTOM_BASE_URL=https://your-api-host.example/v1
CUSTOM_MODEL=your_model_id
```

All three values above are placeholders. Replace them with the endpoint's actual
credentials, API URL and model ID, then use `mrcat --provider custom`.
Do not select a different provider in the web menu and expect it to use these values.

## OpenGWAS

OpenGWAS credentials are separate from model credentials. To use its API for
study searches, authenticated downloads or online LD clumping:

1. Sign in to the [OpenGWAS account page](https://api.opengwas.io/profile/).
2. Generate a JWT and set `OPENGWAS_JWT=your_opengwas_token_here` in your
   existing `.env`. Paste only the token, without a `Bearer ` prefix.
3. Restart MRCAT after adding or replacing the token.

MRCAT loads this variable from `.env` and passes its environment to Python
and R execution processes. You do not need a separate `.Renviron` entry for
R code launched by MRCAT. If you already set `OPENGWAS_JWT` in the shell, update
or unset that value too: exported variables take priority over `.env`.

Without this token, the OpenGWAS search source reports that authentication is
required; model access alone does not enable it. Local GWAS inputs may still
need the token when using online LD clumping. To avoid OpenGWAS requests for
clumping, supply a local PLINK executable (`plink_bin`) and a compatible LD
reference panel prefix (`bfile`). Viewing the included recording requires no
token.

The [OpenGWAS API documentation](https://api.opengwas.io/api/) currently specifies
a 14-day token lifetime. For `401 Unauthorized`, check for a missing, expired or
invalid token; generate a replacement, update `.env` and restart MRCAT. For
`429 Too Many Requests`, wait for the allowance to reset as indicated by the
response; generating a new token does not reset the allowance. Keep the token
private and out of Git.

## Model limits

The template includes the following capacities:

| Setting | Template value | Meaning |
| --- | ---: | --- |
| `MRCAT_CONTEXT_TOKENS` | `131072` | Configured total context capacity, including input and output. |
| `MRCAT_MAX_OUTPUT_TOKENS` | `32768` | Initial output-token budget. |
| `MRCAT_MAX_RETRY_OUTPUT_TOKENS` | `65536` | Cap for a retry after a truncated response. |
| `MRCAT_MODEL_CONTEXT_TOKENS` | `{}` | Optional JSON mapping of model IDs to context capacities. |

These are explicit settings, not limits discovered from the provider. Check your
endpoint's documented limits and adjust these values before running it. Neither
output budget should exceed what the endpoint accepts. If an endpoint allows at
most 8,192 output tokens, for example, reduce both output settings to 8,192 or
less; the template's larger numbers are not appropriate for that endpoint.

Leave role-specific model overrides blank for a single-model setup.
`MANAGER_MODEL` and `REPORTER_MODEL` can override their respective roles for
advanced use; overridden models must be available through the configured provider.
The `*_OFFICIAL_*` entries are optional profiles used by search tests and are
not required for the quick start. Configure search-service credentials separately
if a selected search backend requires them; model connectivity alone does not
verify every external data service.

## Accessing a remote server

`mrcat-web` listens on `127.0.0.1` by default. If you run it on a remote server,
that address refers to the server; entering it in your laptop's browser does
not connect to the server.

Start MRCAT on the server, then run this command in a terminal on your own computer:

```bash
ssh -N -L 17869:127.0.0.1:17869 USER@SERVER
```

Replace `USER@SERVER` with your SSH login and server address. Keep both MRCAT
and the SSH connection running, then open `http://127.0.0.1:17869` in your
computer's browser. The SSH connection forwards that local port to MRCAT on
the server. If local port 17869 is already in use, choose another local port,
for example `-L 17870:127.0.0.1:17869`, and open `http://127.0.0.1:17870`.

For an existing shared deployment, use its web address instead. See the
[deployment guide](multi_user.md) to set up shared access.

## Where settings and outputs live

Run commands from the repository root for the quick start. By default, the
entry points read `.env` and `config.yaml` from the current directory.
`MRCAT_CONFIG_DIR` chooses another settings directory. `--env-file` chooses an
explicit environment file. Exported shell variables take priority over that
file, followed by the settings directory's `.env`.

Sessions are stored under `runtime_artifacts/` in the current directory.
Choose another location with:

```bash
mrcat-web --port 17869 --artifact-dir /absolute/path/to/sessions
```

Checkpoint state owns workflow progress; JSON/Markdown and trace files are
readable projections. Read [checkpoint storage](checkpoint_storage.md) before
moving or backing up sessions that refer to host-local files.

`MRCAT_DATABASE_DIR` points directly to the reference database directory. When
using the standalone downloader, export this variable in the shell or pass
`--database-dir`: the downloader does not read `.env`.

```bash
export MRCAT_DATABASE_DIR=/absolute/path/to/database
python scripts/download_database.py --from-dir /path/to/database-bundles
mrcat-web --port 17869
```

Keep `.env`, API keys, private sessions and raw input data out of Git. The
repository distributes only the blank credential template `.env.example`.
For shared access, use [the deployment guide](multi_user.md). Web ownership
checks separate session access; model-generated code still runs under the
operator's OS account and is not an OS sandbox.

## Command-line use

Start a conversation or send a single request:

```bash
mrcat --provider deepseek
mrcat --provider deepseek --question "Find GWAS studies of systolic blood pressure and coronary artery disease."
```

Resume using the session ID printed by the CLI:

```bash
mrcat --session session_ID
```

`python main.py` and `python -m mrcat.web.server` use the same implementation as
the installed entry points. New sessions use `session_` IDs. Existing `bridge_`
IDs remain supported and use the same access checks.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| GitHub reports “Repository not found” | The repository is currently private. Authenticate with an account that has access; the clone URL alone does not grant access. |
| `mrcat-web` is not found | Activate `conda activate mrcat`. The environment recipe installs the package; if needed, run `python -m pip install -e .` from the repository root. |
| An API key is reported as missing | Check the exact provider-specific key name, selected provider and working directory. Restart after editing `.env`. |
| The model returns HTTP 401/403 or “model not found” | Check the provider key, account access, API endpoint and model ID. A model name in the template does not grant access to it. |
| The endpoint rejects `max_tokens` or the context size | Adjust the model capacity settings above to the limits of the actual endpoint. |
| New `.env` settings appear to have no effect | Check exported shell variables, `--env-file` and `MRCAT_CONFIG_DIR`; they can select or override settings. Restart and use a new chat. |
| Model requests fail behind a proxy | Verify the proxy first. `MRCAT_DISABLE_PROXY=1` removes inherited proxy variables for the MRCAT process when direct access is intended. |
| The page opens but MR analysis reports missing dependencies | Run `Rscript scripts/install_r_dependencies.R --check` and `python scripts/download_database.py --check`. Read [data preparation](data.md); the database's public download is not yet available. |
| The recorded example has no reply box | It is intentionally read only. Select **New Chat** for an analysis using your configured model. |

A simple conversational reply checks the selected model connection. It does not
verify R packages, GWAS services or reference data. Confirm those prerequisites
before a scientific run.
