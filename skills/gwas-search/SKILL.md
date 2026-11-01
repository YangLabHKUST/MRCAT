---
name: gwas-search
description: "Find downloadable GWAS candidates for one trait or source-native identifier. Natural-language UKB or UK Biobank means Pan-UKB; only a complete ukb-* ID identifies OpenGWAS. Preserve supplied phenotype/field IDs unchanged. Search only, without selection or download."
accepts-milestones: []
produces-milestone: gwas_search_results
reusable-outputs: [shortlists_path]
---

# gwas-search

Find downloadable GWAS candidates for one trait or exact study ID. Search only; no selection or GWAS data download.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `gwas_search` from `mrcat.tools` in the active `mrcat` environment.

```python
import json
from pathlib import Path
from mrcat.tools import gwas_search

result = gwas_search(
    trait='xxx',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["gwas_search_results"]
    shortlist = json.loads(Path(data["shortlists_path"]).read_text())
    candidates = shortlist["candidates"]
    print("Candidate count:", len(candidates))
    fields = ("source", "study_id", "trait", "sample_size", "ancestry", "downloadable")
    print(json.dumps([{key: row.get(key) for key in fields} for row in candidates[:20]], ensure_ascii=False))
    print("Shortlist:", data["shortlists_path"])
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `trait` | string | optional | Biological target label; required unless study_id supplied. |
| `study_id` | string | optional | Exact source-native ID; alternative or addition to trait. |
| `source` | string | optional | Optional source restriction; see routing below. |
| `ancestry` | string | optional | Known population or explicit user constraint; omit unknown. |
| `limit_per_source` | int | 20 | Per-source candidate cap. |
| `aliases` | list[str] | optional | Equivalent search terms chosen by you; no internal LLM expansion. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Supply `trait`, `study_id`, or both. With an exact ID, preserve the full identifier; `trait` is only semantic context. Omit `source` for the configured multi-source search (currently OpenGWAS, GWAS Catalog, Pan-UKB, FinnGen). Omit `ancestry` unless the user restricts population. No source or ancestry needs to be invented to call this tool.

A supplied record, field or phenotype identifier also belongs in `study_id`,
unchanged. Never manufacture an OpenGWAS prefix from a phenotype number. The
source adapter resolves native identifiers to real candidate keys. If the Plan
conflicts with the user's source or these routing rules, report the conflict
for correction before searching; a generated Plan is not new user authority.

Sources: `opengwas`, `gwas_catalog`, `pan_ukb`, `finngen`. Natural-language UKB means Pan-UKB; a complete `ukb-*` ID belongs to OpenGWAS. Bare `GCST*` belongs to GWAS Catalog; `ebi-*`, `ieu-*`, `bbj-*`, `finn-*`, `eqtl-*`, `prot-*`, `met-*` belong to OpenGWAS; `finngen_*` belongs to FinnGen. Explicit source/ID or ancestry/ID conflicts must be reported, not silently rerouted.

Choose the expanded biological trait yourself. Add aliases only when their meaning is equivalent; ambiguous abbreviations can match unrelated records. The tool searches the supplied terms once and does not call another LLM to expand them or retry with new traits. Inspect diagnostics and decide whether a justified revised query is needed. Reuse successful shortlists.

## Trait resolution and refinement checks

You own trait resolution and refinement in this CodeAct loop; the search tool
has no internal resolver LLM. Preserve the original scientific target separately
from search wording. The current request and explicit corrections outrank prior
memory. Preserve phenotype, subtype, mechanism, anatomy, severity, etiology,
measurement definition, source and population constraints.

- Before the first trait-search call, choose one concise English query and
  supply the established equivalent full names and common unambiguous
  abbreviations as aliases when known. Include distinct full-name alternatives,
  not just an abbreviation of the query. Keep the list concise and non-redundant;
  do not invent terms or add aliases merely to reach a count. Supported variants
  include translation, spelling, singular/plural, noun/adjective, abbreviation
  expansion, hyphenation/spacing and documented biomedical or database-title
  wording. Do not wait for an empty result to include known equivalent names.
- Use the current request and relevant search history when choosing the first
  query and aliases. Terms that retrieved a candidate accepted as a correct
  semantic match are strong lexical evidence; include the shortest useful
  phenotype-preserving variant if a later search missed that same phenotype.
  Ignore unrelated or superseded history and terms rejected for semantic
  mismatch. Download, formatting, QC or analysis failure does not itself
  invalidate previously effective search terminology. Use an empty alias list
  only when neither the current trait nor relevant history supports a useful
  equivalent variant.
- Do not broaden to a parent phenotype, related disease, mechanism, complication,
  treatment or loose proxy; do not switch to a subtype the request did not ask
  for. A retrieved related candidate is discovery evidence, not an approved
  substitute. Do not put source names, study IDs, URLs or filenames into trait
  aliases; use exact-ID mode for a supplied study ID and preserve that identifier.
- Inspect source diagnostics before interpreting an empty shortlist. Metadata
  omissions, truncated output, authentication errors and service failures do not
  establish phenotype absence. Check the named missing fields or source failure.
- When no acceptable candidate is found, another search is allowed within the
  unchanged request if there is a concrete new equivalent term or recoverable
  lookup problem. Explain the gap and what changes; retain tried terms and
  outcomes in memory. Do not repeat exhausted terms without new evidence or
  a specific transient-failure reason. Reuse unaffected successful shortlists.
- If only a changed phenotype, source, fixed ID, population or other confirmed
  condition could permit analysis, do not make that change yourself. Preserve
  the candidates and unresolved difference, then hand off blocked. If a search
  budget or technical limitation ends discovery, report that limitation rather
  than claiming that the requested data do not exist.

Search retrieves candidates; gwas-select determines their scientific suitability.
An empty selection can lead back to search without a new Plan when the next
operation still implements the current Plan and authorized scientific target.

## Outputs and checks

On success, `result["outputs"]["gwas_search_results"]` holds the data described below.

`shortlists_path` points to JSON with `target`, `candidates`, `diagnostics`. The same output directory contains `gwas_search_shortlists.xlsx` and `gwas_search_raw.json`. Keep these filenames for the frontend candidate list. Inspect trait relevance, duplicates and source failures once using compact fields. HTTP 429/auth/service failure is not evidence of no matching studies. If you remove candidates, actually write the filtered deliverable and check its row count before claiming removal.

## Supplemental discovery and handoff

Call the existing search function and extract a compact result in the same cell
as the normal operation. Supplement it only to resolve a named gap in the user's
request or observed results, not to rebuild filtering and export as a routine.
An extra action's message should explain that gap. Deliver once the evidence is
sufficient; no repeated directory listing or full candidate dump is needed.

Formal candidates use `source`, `study_id`, `trait`, `ancestry`, sample-size fields,
`download_descriptor` and `study_metadata` inside the existing `target` /
`candidates` / `diagnostics` envelope. Unknown information may remain null and
source-specific fields may be retained. Do not reduce the saved objects to a
presentation table or treat related phenotypes as interchangeable.

For custom discovery, incomplete records, historical native formats and optional
reuse of the existing XLSX writer, read [Candidate output convention](reference/output-format.md).
This is a handoff convention, not a mandatory saving function or scientific
acceptance gate. The ordinary tool call already produces these files.

## GWAS Catalog recovery

The Catalog adapter uses REST API v2 and combines reported-trait and EFO-trait
searches before deduplicating accessions. Ontology matches are candidates, not
authorization to substitute a phenotype, subtype or variant-analysis type.
If one endpoint fails, usable candidates from the other are retained with
partial source diagnostics. These candidates still require semantic selection;
partial or failed searches cannot establish absence of the requested phenotype.
For a verified accession, reuse gwas_search(study_id=..., source="gwas_catalog")
in exact-ID mode. Custom metadata inspection must use
https://www.ebi.ac.uk/gwas/rest/api/v2/studies/{accession_id}.
Legacy /gwas/rest/api/studies and findBy endpoints may return 410 Gone; that
is an endpoint failure, not evidence that a study or its summary data is absent.
Use the supported endpoint within the current Plan before declaring a source
unavailable. Do not retry a retired URL or silently switch sources.
