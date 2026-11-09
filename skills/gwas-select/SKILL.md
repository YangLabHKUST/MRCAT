---
name: gwas-select
description: >-
  Select one executable study per target from saved shortlists, checking phenotype,
  source, ancestry and reuse constraints while preserving fixed identifiers. Produces
  selected study metadata, not an analysis-ready instrument set. Selecting an eQTL study
  does not establish tissue relevance, cis/trans scope, instrument validity or
  compatibility with downstream MR methods; those decisions remain part of the analysis.
accepts-milestones: [gwas_search_results]
produces-milestone: gwas_selection_result
reusable-outputs: [selected_studies, selection_reason]
---

# gwas-select

Call the complete selection tool once for all distinct targets in the current
analysis branch. It loads the shortlists, calls its internal selector LLM,
validates candidate identities, preserves full selected objects and returns the
study set. The Executor must not implement its own candidate selection.

## Use in Python

```python
from mrcat.tools import gwas_select

result = gwas_select(shortlists={
    "exposure": "/absolute/path/to/exposure_shortlists.json",
    "outcome": "/absolute/path/to/outcome_shortlists.json",
})
print(result["summary"])
if result["outputs"]["status"] != "ok":
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `shortlists` | dict | required | Stable target keys mapped to actual `shortlists_path` values from search outputs. Include every distinct remote target once. |
| `ancestry` | string | optional | Explicit population constraint; omit when unspecified. |
| `request` | string | optional | Full selection request for standalone use. In an MR task the actual task request is supplied internally. |
| `current_plan_item` | string | optional | Standalone branch/reselection requirements. The runtime supplies the current MR item internally. |
| `memory_md` | string | optional | Standalone prior decisions. The runtime supplies current-task memory internally. |
| `output_dir` | path | optional | Fresh output directory; automatically created when omitted. |

## Inputs and selection rules

Use the actual search result references supplied by the runtime. Pass each saved shortlist path, not its
candidate table, a study ID, or a reconstructed result. Keep the same target keys
in all downstream references. A local raw file bypasses search/select/download.
Do not read candidate files first to choose on behalf of the tool. The tool
receives the current request and confirmed item itself; do not replace them
with an inferred scope or a claimed user authorization.

The internal selector preserves fixed IDs, requested endpoint, source and
population. Related, broader, laterality or treatment phenotypes are not an
authorized replacement. Rank trait and measurement-definition fidelity before
sample size, metadata completeness or source consistency. Among scientifically
suitable candidates satisfying hard constraints, prefer the reported trait
matching the user's full trait over a shortened or synonymous label. Format is
an eligibility check, not a ranking preference;
do not prefer a convenient VCF or API over a closer eligible trait match.
The selection reason must compare the closest alternative using actual metadata.
Independent replication requires cohort evidence when
requested. Unknown evidence remains unknown. The full internal rules are in
`mrcat/prompts/gwas_select.selector.system.md`.

## Outputs and checks

On success, `outputs.gwas_selection_result` contains `selected_studies` (one
complete candidate per input target key) and `selection_reason`. Candidate
objects retain `download_descriptor`, `study_metadata`, study ID, actual trait,
ancestry and sample sizes. Tools automatically save and register this output;
never publish a second hand-built selection record.

For downloading, pass `selected_studies[target]` directly to `gwas_download`.
For the explicitly requested quick OpenGWAS route, pass the selected study IDs
to `mr_primary_id`. Reuse selected studies across directed pairs.

Empty candidate pools or null selections return `outputs.status=blocked`, a
failure_class, diagnostics and selection reason. Preserve partial selections
in details. No downstream analysis is authorized by a blocked selection.
Review decides whether the specific obstacle supports retry, replan, or a final
boundary explanation. A failed lookup is not evidence that a phenotype cannot
exist. Do not silently substitute a dataset or generate numerical MR results to
complete a boundary query.
