# GWAS candidate handoff

This is the output convention for a reusable candidate list, not a restriction on
intermediate code or files. Source manifests, exploratory tables and raw search
responses may keep their native structure. Publish the formal list separately so
Search, the frontend and MR do not have to guess what its fields mean.

## Formal output

Keep the filenames `gwas_search_shortlists.json` and
`gwas_search_shortlists.xlsx` for the existing frontend. The JSON envelope is:

```json
{
  "target": {"kind": "trait", "value": "coronary artery disease"},
  "candidates": [
    {
      "source": "pan_ukb",
      "study_id": null,
      "trait": "Coronary atherosclerosis",
      "ancestry": null,
      "sample_size": null,
      "n_cases": null,
      "n_controls": null,
      "downloadable": null,
      "downloadability_reason": "Discovery only; exact study ID and download readiness need verification.",
      "download_url": null,
      "download_descriptor": null,
      "study_metadata": {
        "phenocode": "411.4",
        "raw_record_path": "workspace/supplemental/source_rows.json"
      }
    }
  ],
  "diagnostics": {"notes": "Supplementary discovery; not an approved MR selection."}
}
```

The example illustrates an incomplete discovery, not a ready-to-download study.
Unknown values may remain null; do not discard useful candidates just because
sample size, population or a download descriptor is missing. Additional fields
are allowed. Preserve source-specific information in `study_metadata` and/or a
referenced raw artifact. Do not invent an ID, sample size or downloadability to
make a row look complete.

| Field | Meaning |
| --- | --- |
| source | Actual database, using the tool's canonical source name when known. |
| study_id | Exact source study/file identifier, not an approximate phenotype label. Preserve it as a string when known. |
| trait | Observed trait description. Related phenotypes are not automatically equivalent. |
| ancestry | Documented population of this dataset or effect column; unknown stays null. |
| sample_size / n_cases / n_controls | Source-supported values for the relevant population/cohort, or null. Preserve the count's scope in metadata. |
| downloadable | Evidence-supported availability, or null if unverified. A printed URL alone is not a verified download. |
| download_url / download_descriptor | Preserve existing tool values exactly. Do not manufacture a ready descriptor from an unchecked URL. |
| study_metadata | Source fields, provenance, units, phenotype coding and unresolved details. |

An existing tool candidate is the starting object: copy it in full, then add
supported metadata. A compact display table must not replace that object.
Use source plus exact study ID when comparing identified studies. An unidentified
row cannot be treated as a unique selected study just because its label matches.

## Supplemental results

First state the concrete gap: an explicitly requested study is missing, needed
metadata is absent, or the tool does not support this discovery operation.
Supplement only that gap. Preserve the original tool shortlist and raw evidence;
write an updated formal shortlist in a separate output directory when useful.
Do not rerank, merge or remove candidates without an evidence-based reason.

For a Pan-UKB raw row, `description` can supply `trait`, and `phenocode` should be
preserved in metadata. `phenocode` alone is not always the downloadable study ID:
trait type, coding, sex and modifiers may distinguish datasets. Preserve
`aws_path` as source evidence; populate `download_url` only when its actual value
is an appropriate download URL. Retain the exact source file identity where
available. Never infer the population from the requested population alone.

## Saving files

The standard `gwas_search()` already writes JSON and XLSX. Do not export a second
copy merely to verify that result. For an actual supplemental list, reuse the
existing workbook writer or write the documented format directly. No new saving
API or mandatory validator is required.

This example assumes `candidates`, `target` and `diagnostics` have already been
assembled from observed records. It does not discover, select or validate studies.

```python
import json
from importlib import import_module
from pathlib import Path

output = Path("/absolute/path/to/session/workspace/outputs/cad_supplement")  # Use the supplied workspace path.
output.mkdir(parents=True, exist_ok=True)
shortlist = output / "gwas_search_shortlists.json"
shortlist.write_text(json.dumps({
    "target": target,
    "candidates": candidates,
    "diagnostics": diagnostics,
}, ensure_ascii=False, indent=2), encoding="utf-8")
writer = import_module("skills.gwas-search.scripts.search_output")
writer.write_shortlists_workbook(candidates, shortlist.with_suffix(".xlsx"))
print(json.dumps({"count": len(candidates), "shortlist": str(shortlist)}))
```

## Reading an existing or historical file

1. Establish whether it is the formal envelope or a raw list with native fields.
   Inspect keys and one representative record only if the format is unknown.
2. For native rows, map fields from their actual documented meaning; do not read
   every format using `row.get("study_id")` and interpret nulls as absent studies.
3. If an approved ID is missing from one shortlist, inspect the saved supplemental
   candidates and source evidence for that exact study. A schema mismatch, missing
   metadata or an incomplete search is not evidence that the study cannot exist.
4. If the approved study remains unavailable, preserve that decision and ask about
   a material substitute. Search discovery is not authorization to change an MR task.

The consumer decides which missing information matters for the requested next
operation. Viewing a candidate does not require the same evidence as downloading
or using it in analysis. Report unresolved information instead of rejecting all
incomplete rows or silently guessing.
