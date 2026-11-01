# GWAS Download Workflow

`gwas-download` downloads exactly one remote study per invocation.
`SKILL.md` is authoritative.

## Input

Pass one complete `selected_study` from:

`gwas_selection_result.selected_studies.<role>`

Local paths bypass this skill. The input study must contain an executable
download descriptor and any source-specific metadata required by the
downloader.

## Output

Successful completion emits
`gwas_download_result.downloaded_study` containing:

- `raw_path`
- `file_size`
- `label`
- `study_id`
- `source`
- `ancestry`
- `ancestry_raw`
- `sample_size`
- `n_cases`
- `n_controls`
- `study_metadata`

The normalized study fields snapshot the selected study used for this exact
download. `study_metadata` starts with `selected_study.study_metadata` and may
include file-specific facts discovered by the downloader, such as
`file_notes`; it does not duplicate its normalized sibling fields.
Canonicalization binds the complete `downloaded_study` object instead of
remapping its individual fields.

The skill never searches, selects, pairs, canonicalizes, or passes local files
through unchanged.
