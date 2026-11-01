# Shared tool calling conventions

Use functions from `mrcat.tools` in the active `mrcat` environment. Agent cells
already have the package available; terminal users should start Python from the
MRCAT repository. Pass documented keyword arguments, omit unused options and
replace example paths/IDs with verified inputs. File arguments accept strings
or `Path` objects; nested records are ordinary dictionaries/lists.

Tools manage Python/R interchange and save `response.json` in a fresh directory
under the cell outputs (`./outputs` in a terminal). Optional `output_dir` selects
a fresh destination. Python/R variables do not survive Agent cells: retain
artifact paths and reload only the needed saved data in a later cell.

Results are dictionaries: inspect `summary`, `outputs.status`, the skill-specific
output record and `artifacts`. On failure inspect `details` and the referenced
stderr before deciding on repair. Process success is not scientific validity.
Check the required contents and counts in the calling cell; reuse verified data
and resolved questions. Reopen files only for a specific missing fact or error.

## Numerical precision

Save machine-readable R results with `digits = NA` in every
`jsonlite::write_json()` and `jsonlite::toJSON()` call, including result records,
response envelopes and reference calculations. Preserve numeric values until
the display layer; round only figure labels or human-readable tables.
