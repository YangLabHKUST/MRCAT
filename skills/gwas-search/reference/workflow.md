# GWAS Search Workflow

`gwas-search` resolves and searches exactly one remote target per invocation.
`SKILL.md` is authoritative.

## Input

Provide exactly one of:

- `trait`
- `study_id`

Optional search constraints are singular `source`, `ancestry`, and
`limit_per_source`. A trait with no `source` uses the default multi-source
strategy. A study ID with no `source` requires one uniquely inferable ID
namespace. Local paths bypass this skill.

Normalize `source` and `ancestry` before trait resolution. With neither
constraint, preserve the default source order. With only `source`, search it
strictly. With only `ancestry`, use its configured source order. With both,
search the explicit source only when it supports that ancestry; otherwise
block. Ancestry never reroutes an explicit study ID.

## Output

Successful scientific completion emits `gwas_search_results` with:

- `target`
- `shortlists_path`
- `search_diagnostics`

The shortlist artifact contains one `candidates` array. Success requires at
least one executable downloadable candidate. An empty array is blocked, emits
no milestone, and retains `search_exhausted=true` plus the shortlist and raw
artifacts for reviewer recovery. Authentication and infrastructure failures
remain blocked.

The skill never selects a study, combines MR roles, or downloads data.
