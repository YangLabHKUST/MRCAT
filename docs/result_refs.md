# CodeAct result references

Results are saved immediately in `<session>/results/<scope>/<id>.json`, independently
of model memory and Python cell processes. Each complete record is published by
atomic hard-link creation; publication never replaces an existing record and needs
no blocking file lock. Tool call IDs include a random suffix. Each MR task or Search/Report work item owns its own namespace.

Named functions in `mrcat.tools` automatically register the `outputs` object of
returned tool responses. Existing return values and `response.json` files remain
unchanged. Actual producer IDs, status, source identity, and available root fields
appear in each execution observation and in `result_refs` on every executor turn,
including local error repair. IDs identify calls, not Plan steps. Registration
makes no LLM calls.

## Ordered MR items

Planner returns four-field items: step_id, title, skill_id, reuse_from. It never
declares input bindings or mandatory output fields. Runtime records each completed
step's actual publications. `completed_results` maps task/step/output sources to
real references and compact payloads. `current_plan` contains the full checklist;
`current_item` identifies the only step Executor should execute.

Historical reuse_from entries select task_id/step_id/output_name sources from the
actual planning directory. Executor translates these to the supplied $taskref
references. Current-task consumers use actual $ref values from completed_results.
Step IDs identify operations; result IDs identify saved publications. Large data
remain in files. References survive restart and recovery without repeating the
producer. For example:

```python
from mrcat.tools import gwas_qc

# Use an actual ID supplied in result_refs.
qc = gwas_qc(
    downloaded_study="$ref:gwas_download_1/gwas_download_result/downloaded_study"
)
```

The common tool entry point resolves references recursively in dictionaries and
lists before invoking a tool. Missing producers/fields and blocked/failed/error
results raise an execution error; they never fall back to another producer.
Tool failures remain recorded with their response path for diagnosis.

## Unregistered methods

No skill registration is needed. Use variables within a cell, and publish only
outputs needed by subsequent cells. Publication accepts JSON-compatible values
and converts `Path` objects to absolute paths; strings are not guessed to be paths.
Large tables and arrays belong in files. Use distinct files for revised results.

```python
from pathlib import Path
from mrcat.tools import publish_result, resolve_ref

# Run any suitable custom Python code or R/Bash subprocess here.
output = Path.cwd() / "custom_estimates.tsv"
output.write_text("estimate\n0.25\n")
publish_result("custom_analysis_1", {
    "estimate": 0.25,
    "result_path": output.resolve(),
})
```

A later cell, including after a restart:

```python
from mrcat.tools import resolve_ref

estimate = resolve_ref("$ref:custom_analysis_1/estimate")
path = resolve_ref("$ref:custom_analysis_1/result_path")
```

R/Bash code may invoke the same Python helpers; Python may also orchestrate R/Bash
subprocesses and publish their results. Custom registration is labeled
`unverified`: it records outputs, not scientific validation. Duplicate IDs raise
an error instead of replacing prior bindings. Published results survive an error
in a later operation in the same cell; unpublished work does not become a result.
To repair a custom publication, publish a new meaningful ID. The reviewed step
records its actual publications; the next consumer chooses the corrected result
from those references and the saved evidence. No Planner output schema is involved.

Local `$ref:<id>/<field>/...` resolves only within the current work namespace.
Explicit same-session historical reuse uses
`$taskref:<scope>/<id>/<field>/...`. Fields may address dictionaries or list indices.
This is result lookup, not permission to change study, phenotype or method.
Artifact files remain ordinary files: the registry does not prevent arbitrary
code from deleting or modifying them, and does not certify their contents.

The shell working directory is already `<session>/workspace`. Use returned
absolute file paths or `Path.cwd() / "outputs"`; adding another `workspace/` is
incorrect. Session-relative paths in Markdown reports are display links.
Existing historical response files are not auto-imported or guessed into this
registry. Reuse requires an explicit, verified source.
