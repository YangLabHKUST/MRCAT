# Development

[Back to the README](../README.md)

## Repository layout

```text
mrcat/       Agent, model gateway, state, results, reporting and web console
skills/      Skill guides, Python/R analysis wrappers and plot explanations
scripts/     R dependency installation and reference-data download/verification
examples/    Tutorials, recording exporters and an offline installation check
tests/       Product behavior, method output and browser regressions
docs/        User guides, architecture and the README interface image
```

Full paper experiment inputs, runners and results are maintained separately.
The selected read-only recording is included for inspection. Development audit
scripts and records, private settings, session stores, caches and reference
databases must not be committed or bundled with the source distribution.

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
