# Development

[Back to the README](../README.md)

## Repository layout

```text
mrcat/                 Python application and public entry points
  workflow/            Routing, planning, review and task transitions
  runtime/             Code execution, action transport and diagnostics
  state/               Session storage, memory and published results
  model/               Model clients and context budgets
  config/              Configuration loading
  search/              GWAS and literature search
  report/              Evidence selection, report writing and export
  web/                 HTTP API and browser interface
  tool/                Shared Python and R method implementations
  prompts/             Agent instructions
skills/                Method guides and executable method wrappers
scripts/               Dependency and reference-data installation
examples/              Tutorials, exporters and offline installation checks
tests/                 Product, method and browser regressions
docs/                  User and architecture documentation
```

Full paper experiment inputs, runners and results are maintained separately.
The selected read-only recording is included for inspection. Development audit
scripts and records, private settings, session stores, caches and reference
databases must not be committed or bundled with the source distribution.

## Source of truth and publication

Use this development checkout for code changes, tests and service launches.
Do not maintain a second editable upload checkout. Runtime sessions and reference
resources remain outside the tracked source tree; restarting a service must keep
its existing artifact and database paths.

The GitHub `main` branch has a separate public release history. Publish a reviewed
source tree as a child of the current GitHub `main`; do not force-push the private
development history or merge it into the public repository. The `github` remote
points to `https://github.com/77JULIE/MRCAT.git`.

After committing the intended changes and passing the checks below, publish from
this checkout with a clean working tree:

```bash
set -e
test -z "$(git status --porcelain)"
git fetch github main
mrcat_source_commit=$(git rev-parse HEAD)
mrcat_release_commit=$(git commit-tree "${mrcat_source_commit}^{tree}" \
  -p refs/remotes/github/main -m "Publish MRCAT source ${mrcat_source_commit}")
git update-ref refs/mrcat/published "$mrcat_release_commit"
git push github "${mrcat_release_commit}:refs/heads/main"
```

This sends the committed source files while retaining the existing public
history. It needs no second working directory and does not publish ignored
settings, sessions or reference data. A concurrent remote update causes the
normal push to fail; fetch and review that update before preparing another
release.

## Install and test

With the documented Python environment active, run from the repository root:

```bash
python -m pip install -e ".[dev]"
ruff check mrcat skills tests
python -m pytest -m "not r" -q
python -m pytest -m r -q
node tests/test_result_formatters.cjs
python -m build
```

R tests require the documented R libraries and method dependencies. Browser
scenarios in `tests/browser_*.cjs` use Playwright and their corresponding fixture
servers or the exported static site. Software tests do not establish scientific
accuracy for every live-model analysis.

Checkpoint tests need a local temporary filesystem. If the default temporary
directory is on NFS, prefix the test commands with `TMPDIR=/var/tmp`.

The distribution includes Skills, prompts, Python/R wrappers and web assets.
Installing a wheel does not install R libraries or reference data. Source
installation files include `environment.yml`, the reference-data installer and
its manifest. The dependency recipe is not a complete lock of all dependencies.

The R installer retrieves the pinned BWMR helper under its upstream terms;
that implementation is not redistributed in the MRCAT source. Check an existing
installation without changing it:

```bash
Rscript scripts/install_r_dependencies.R --check
```

## Calling a tool from Python

Tools are documented in their owning Skills. For a prepared pair and the
appropriate R environment:

```python
from pathlib import Path
from mrcat.tools import mr_primary

result = mr_primary(
    mrdat_path=Path("prepared_pair.tsv"),
    output_dir=Path("outputs/primary"),
)
print(result["summary"])
```

`prepared_pair.tsv` must satisfy the [mr-primary contract](../skills/mr-primary/SKILL.md).
This snippet does not supply example data or perform upstream preparation.

## README screenshot

`docs/assets/mrcat-workspace.png` is a browser screenshot of the included,
sanitized Result 4 recording in the frontend published with commit `87f7c82`.
It shows a recorded analysis, not a newly executed workflow. Capture updates
from the reviewed example only; never use private user sessions or credential
screens. Keep the read-only status visible and do not alter scientific results
for presentation. The original large GWAS files are not needed to view it.
