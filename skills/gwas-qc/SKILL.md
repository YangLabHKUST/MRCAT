---
name: gwas-qc
description: >-
  Convert one raw variant-association study into canonical and formatted tables using
  model-generated mapping and reference-based R formatting. Requires interpretable
  allele/effect statistics and documented sample-size information for formatting.
  Canonicalization preserves raw variants; formatted output applies HM3/MHC and
  allele-frequency filters. Check these filters before using formatted output for a
  gene-region analysis. Does not select a gene, tissue or cis region, harmonize a pair,
  or establish MR applicability. Preserves source effect statistics rather than
  applying the requested MR effect scale. Compatible pair preparation and estimators
  can standardize from these outputs internally; do not add a separate conversion
  unless their statistic/sample-size rules or outputs do not meet the request.
accepts-milestones: [gwas_download_result]
produces-milestone: gwas_qc_result
reusable-outputs: [canonical_path, formatted_path, label, ancestry, sample_size, genome_build,
  genome_build_reason]
---

# gwas-qc

Convert one raw GWAS file to canonical and formatted study tables. Uses model-generated column mapping, local reference resources and R formatting.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `gwas_qc` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import gwas_qc

result = gwas_qc(
    raw_path='/absolute/path/to/raw_gwas.tsv.gz',
    label='Study trait',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["gwas_qc_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `downloaded_study` | object | optional | Complete downloaded-study object; alternative to raw_path. |
| `raw_path` | path | optional | Existing raw study file; alternative to downloaded_study. |
| `label` | string | optional | Known study/trait display label. |
| `sample_size` | integer | optional | Documented positive study N; omit unknown. |
| `source` | string | optional | Optional source restriction; see routing below. |
| `study_metadata` | object | optional | Complete structured source/file metadata; preserve unknowns. |
| `mapping_notes` | string | optional | Optional user-provided file/column explanations only; omit when the user supplied none. |
| `ancestry` | string | optional | Known population or explicit user constraint; omit unknown. |
| `max_attempts` | integer | 3 | Maximum column-mapping/codegen attempts. |
| `sample_rows` | integer | 50 | Preview rows. |
| `sample_timeout_seconds` | integer | 120 | Sample-transform timeout in seconds. |
| `full_timeout_seconds` | integer | 7200 | Full-transform timeout in seconds. |
| `min_freq` | float | 0.05 | Allele-frequency filter. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Choose `downloaded_study` (the complete object from `outputs.gwas_download_result.downloaded_study`) or an existing local `raw_path`. A nonempty downloaded object is authoritative over redundant local fields. Do not pass its JSON filename instead of the object. Keep source metadata intact; do not invent sample sizes or allele definitions.

This raw-file convenience tool still calls the configured model internally for column mapping and genome-build assessment, with up to max_attempts attempts. Account for its latency and inspect its mapping evidence; it is not a simple column rename. The tool maps arbitrary columns to a canonical table, checks sample/full transformations, records source build and mapping risks, maps eligible coordinates to HM3, then formats and filters. HM3/MHC and build references come from the configured database. Unknown build can be retained for studies with rsIDs; coordinate mapping needs build evidence. The complete Neale format is checked against ALT-oriented beta in sample and full-output validation; mapping conflicts feed back to internal code generation. Reuse each study's QC outputs across pairs.

`mapping_notes` is reserved for explanations explicitly supplied by the user about this file. Pass only those explanations, keeping them neutral and preserving their meaning; do not turn them into transformation commands. If the user supplied none, omit the argument. Do not populate it from your own interpretation of headers, sample values, allele frequency, source conventions, or prior model summaries. Preserve source documentation in `study_metadata`; the QC model derives the mapping from the raw file and supplied evidence and records its reasoning in the QC outputs. Never move an agent inference into `study_metadata` to bypass this boundary.

## Effect scale and downstream planning

QC maps source statistics; a successful QC result does not mean beta and SE have
already been standardized. The formatted table supplies Z/N to gwas-pair-prepare,
which constructs beta=Z/sqrt(N) and SE=1/sqrt(N). CAUSE consumes canonical tables
and supports the same scale internally through input_scale="standardize".
When those contracts match the request, pass the QC outputs directly and preserve
the requested scale in the downstream plan items.

Check the recorded Z source and sample-size semantics against explicit user
requirements. Add targeted investigation or conversion only for a real mismatch,
an unresolved prerequisite that changes the analysis, or a separately requested
output file that the existing tools do not provide. Missing N or ambiguous signed
statistics require evidence or a reported boundary, not invented values. Routine
inspection of available fields belongs within execution, not a separate plan item.

## Canonicalization checks and boundaries

Canonicalization still has an internal code-generation LLM. Its complete mapping
contract is loaded from `mrcat/prompts/canonicalize_code.codegen.contract.md`,
with `canonicalize_code.codegen.system.md`; genome-build judgment and explanation
use `genome_build.system.md` and `canonicalize_code.explain.system.md`. These
contracts are already enforced as prompts inside the tool. Use the following
rules when supplying inputs, inspecting its output, or writing custom recovery:

- Interpret the whole format and one coherent trait/sample/ancestry/association
  namespace. Evidence priority is explicit file/user metadata, then a documented
  source/software signature, then explicit header meaning, then generic aliases.
  A filename, one familiar column, minor allele or frequency is not proof of
  effect direction. Do not mix original/harmonized or population-scoped fields.
- Canonicalization preserves one row per raw variant in the original order. It
  must not filter, deduplicate, harmonize, clump, flip signed effects, liftover or
  manufacture statistics. Copy OR and beta to their distinct fields; do not turn
  p-values into signed effects or invent N. Downstream formatting owns its
  documented conversions and QC. Side-level N remains context, not fabricated
  row-level observations; case/control counts remain distinct from total N.
- Use explicit allele semantics or a complete documented format convention.
  If direction alone remains uncertain but a coherent signed statistic and
  allele pair exist, the existing internal contract uses a disclosed fallback:
  A1/A2 or Allele1/Allele2 -> first allele; REF/ALT -> ALT; another clear paired
  namespace -> first allele. Preserve the `effect_allele_direction` assumption
  and possible sign-reversal risk. This is an executable assumption, not proof
  of orientation or scientific acceptance of the downstream causal claim.
- Preserve rows with symbolic alleles (D/I, D/R, <DEL>, <INS>) with empty canonical
  allele fields; let downstream formatting exclude unusable rows. Do not guess
  nucleotide alleles or block an otherwise usable study solely for such rows.
- A sole numeric N-like field with uncertain semantics can use the existing
  disclosed `sample_size_semantics` fallback. No numeric N anywhere is a hard
  missing-input condition; never infer it from SE or unrelated studies.
- Hard blocks include unreadable input, no representable variant identity, no
  usable allele pair, no signed statistic, no compatible uncertainty/significance
  field, no sample-size value, irreconcilably mixed association namespaces, no
  row-preserving transform, or no usable variants after formatting. Preserve
  `failure_class` and structured `missing_requirements`; do not bypass the
  failure by fabricating fields. Inspect sample/full validation before reuse.
- Carry `[RISK][SOFT_ASSUMPTION]`, mapping decisions and unresolved conflicts into
  memory and delivery. Do not upgrade successful QC or a fallback into verified
  science. A stricter explicit user constraint cannot be relaxed by this tool's
  execution fallback; ask when it prevents accepting the result.
- Genome build requires assembly metadata or compatible local coordinate checks;
  source/file names alone are insufficient. Unknown build may retain existing
  rsIDs but cannot authorize coordinate-based rsID mapping. Do not silently
  convert builds or replace reference resources.

Run once per distinct raw study and reuse compatible outputs across pairs.
Neither a filename nor an apparent column layout establishes prior QC. Use the
whole downloaded_study object when available. Keep canonical_path (row-preserved
study data for CAUSE) separate from formatted_path (filtered study data for pair
preparation); neither is an already harmonized/clumped pair. The canonical table
alone has not passed all method-specific QC. Preserve native beta/SE and observed
frequency provenance alongside Z/N; missing native fields need not invalidate
otherwise usable standardized rows.

## Outputs and checks

On success, `result["outputs"]["gwas_qc_result"]` holds the data described below.

`canonical_path` feeds CAUSE; `formatted_path` feeds pair preparation. Also returned: `report_path`, `explanation_path`, `genome_build`, `genome_build_reason`, and known label/ancestry/sample size. Preserve `risk_notes` and `missing_requirements`. Native beta/SE/frequency columns are retained; QC does not assign pair roles or harmonize a pair.
