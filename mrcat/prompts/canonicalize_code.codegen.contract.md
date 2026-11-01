Build Python code to canonicalize one GWAS summary-statistics side.

## Required Output

The generated `transform(input_path, output_path, context)` function must write a tab-separated file with these columns in this exact order:

`SNP, CHR, BP, effect_allele, other_allele, beta, or, se, z, pval, neglog10_pval, freq_qc, info, n, n_cases, n_controls`

Always write this header as the first output line. Fill unavailable optional fields with empty strings.

## Mapping Decision Process

Reason about the file as a coherent format. Do not map each column independently from aliases alone.

1. Inspect `source`, `mapping_notes`, `study_metadata`, `physical_format`,
   `header_fields`, `sample_rows`, `vcf_metadata`, and `vcf_format_fields`
   together.
2. Identify a documented format or software signature only when the source/context and the joint set of fields support it. A filename or one familiar-looking column is not enough.
3. Select one coherent association namespace: the same trait/sample, ancestry scope, effect estimate, allele pair, frequency namespace, and quality namespace.
4. Map fields using the evidence hierarchy below, then check sample values for compatibility with the selected meanings.
5. If a required mapping is not fully established but one coherent executable
   mapping remains, use the deterministic soft-assumption rules below and
   disclose the risk. Return `status: "blocked"` only when no executable
   mapping can satisfy the hard-block boundary below.

Use mapping evidence in this order, from strongest to weakest:

1. Explicit user `mapping_notes`, column descriptions, VCF header definitions,
   source notes, or `study_metadata` for this file.
2. A documented standard/source/software convention whose complete signature matches the context and header.
3. Explicit header semantics such as `effect_allele`, `OR(A1)`, or `EAF_A1`.
4. Generic aliases such as `A1`, `Allele1`, `ALT`, `A1FREQ`, or `Freq1`.

Higher-priority evidence overrides lower-priority naming conventions. Sample values may confirm type/range compatibility, but values, allele frequency, or minor-allele status must never be used to infer effect direction. If equally strong evidence conflicts but a coherent allele pair and signed statistic remain available, apply the deterministic fallback below and record the conflict as a soft assumption.

## Effect-Direction Decision and Soft Fallback

Before generating code, determine which source allele the signed statistic
refers to.

Treat the mapping as resolved when direction is established by:

1. explicit header semantics;
2. explicit source or study metadata; or
3. a documented format convention whose complete signature matches.

When those sources do not establish direction but the file still contains one
coherent allele pair and a signed statistic, continue with exactly one
deterministic fallback:

1. paired `A1`/`A2` or `Allele1`/`Allele2`: use the first allele as effect;
2. paired `REF`/`ALT`: use ALT as effect;
3. another clearly paired first/second allele namespace: use the first allele.

In this fallback case, return `status: "ok"` and include an `assumptions` entry
with `kind: "effect_allele_direction"`, the selected mapping, its limited
basis, and the risk that the signed effect could be reversed. The generated
code must implement the disclosed mapping consistently; it must not silently
flip values. Generic allele labels, allele frequencies, minor-allele status,
REF/ALT order, filenames, and sample values are fallback selectors rather than
evidence that upgrades the direction to resolved.

Block with `failure_class: "missing_required_allele_pair"` only when two
compatible alleles cannot be formed for any association row in the study.
Directional uncertainty alone is a recorded risk, not a hard block.

## Hard-Block Boundary

Return a structured blocked response only when execution cannot produce a
valid canonical table, including:

- the input is absent, unreadable, or its container cannot be handled safely;
- variant identity cannot be represented as an rsID or coordinate plus two
  alleles;
- no usable compatible allele pair exists anywhere in the study;
- no signed association statistic (`beta`, `or`, or signed `z`) exists;
- no compatible uncertainty/significance field exists;
- no numeric sample-size value exists in a row-level column, case/control
  columns, or side-level context;
- the input cannot be represented as one row-preserving canonical variant
  table at all; or
- equally plausible namespaces would mix traits, samples, ancestry scopes, or
  association tests and no single coherent namespace can be selected.

Every blocked response must name a specific `failure_class` and include
`missing_requirements` describing what information or artifact is required.
Do not use a hard block merely because ancestry provenance, effect direction,
or sample-size semantics would benefit from further confirmation when a
coherent executable mapping exists; record those items in `assumptions`.

## Input and Output Integrity

- Determine compression/container and logical format separately. Open gzip-compatible text such as `.gz`, `.bgz`, `.bgzip`, or `.vcf.gz` with `gzip.open(..., "rt", encoding="utf-8", newline="")`; open plain text with `open(..., "r", encoding="utf-8", newline="")`. If the available Python standard library cannot safely read the actual container, block.
- Use `input_delimiter` for ordinary tables. For `whitespace`, use whitespace splitting or `pandas.read_csv(..., sep=r"\s+")`. Do not infer a delimiter from a `.tsv` suffix. Always write tab-separated output.
- Parse line endings safely with the `csv` module or remove both CR and LF with `rstrip("\r\n")`; never leave `\r` attached to the last header or value.
- Treat conventional missing tokens such as an empty field, `.`, `NA`, `N/A`, `NULL`, `NaN`, or `nan` as unavailable and write an empty string. Do not treat a valid numeric zero as missing.
- Preserve one output row for every raw variant row and preserve row order. Do not filter, deduplicate, harmonize, clump, QC, or reorder rows. If the input mixes variant association rows with covariate, aggregate, or incompatible test rows and a valid row-preserving variant transform cannot be defined, block rather than silently dropping rows.
- A row-level value may be unavailable even when the study-level mapping is
  executable. When an individual row contains symbolic or non-nucleotide
  allele values such as `D`, `I`, `R`, `<DEL>`, or `<INS>`, preserve that
  output row and write empty `effect_allele` and `other_allele` fields for the
  row. Never infer nucleotide alleles from symbolic values, and do not block
  the whole study solely because such rows exist. The untouched raw input
  remains the source of those original symbolic values; downstream formatting
  determines whether the row is analysis-ready.
- Use only values present in source fields or explicit context. Do not derive OR from beta, beta or z from p-values, p-values from log-p values, total N from case/control counts, or any other statistic.
- Do not flip alleles, frequencies, or signed statistics. Do not liftover coordinates, change the coordinate basis, or otherwise change the source genome-build representation.

## Variant Identity and Alleles

- Write only rsID-like identifiers to `SNP`. If an ID field contains a delimited list, extract one valid `rs\d+` token in source order. Do not write a composite list or coordinate ID to `SNP`.
- Parse packed coordinate identifiers such as `chr:pos`, `chr:pos:ref:alt`, or equivalent source-documented layouts into `CHR`, `BP`, and alleles when the layout is unambiguous. Otherwise use explicit chromosome and position fields.
- If no rsID exists, write `CHR`, `BP`, and both alleles so the caller can perform deterministic local HM3 rsID mapping.
- Each usable allele may be a single base or a non-empty nucleotide sequence composed of A/C/G/T. Accept insertion/deletion pairs such as `REF=A, ALT=AT` or `REF=CT, ALT=C`. Preserve each usable source allele string; do not trim, normalize, complement, or swap alleles. Handle symbolic non-nucleotide values with the row-level missing-value rule above.
- `effect_allele` is the allele to which the selected signed association statistic refers. Prefer explicit semantics or a matching documented convention; otherwise apply and disclose the deterministic soft fallback above. Select `other_allele` from the same coherent allele pair.
- `EAF_A1` or `effect_allele_frequency_A1` is valid header evidence that A1 is the effect allele when paired A1/A2 fields and a signed statistic are present and no stronger evidence contradicts it. Generic names such as `A1FREQ`, `Freq1`, or `frq_A1` identify a frequency namespace but are not sufficient by themselves to establish statistic direction.

## Documented Format Conventions

Apply these conventions only when the context and joint header signature identify the corresponding format. They are format evidence, not universal alias rules.

### GWAS Catalog GWAS-SSF

- Use explicit `effect_allele` and `other_allele` fields. Do not replace them using `ref_allele` or ALT/REF assumptions.
- Map `beta`, `odds_ratio`, `standard_error`, `p_value`, `neg_log_10_p_value`, and `effect_allele_frequency` by their declared meanings.
- Keep original and harmonized (`hm_*`) fields within one coherent namespace; do not combine an original effect/allele field with a harmonized counterpart.
- The canonical schema has no hazard-ratio field. If `hazard_ratio` is the only association effect, block; do not map it to `or` or `beta`.
- A GWAS Catalog study ID alone does not prove that an older or nonstandard downloaded file follows GWAS-SSF. Use the actual header and file notes.

### OpenGWAS GWAS-VCF

- For a documented OpenGWAS/GWAS-VCF association sample, the effect estimate is relative to ALT: map ALT to `effect_allele` and REF to `other_allele`.
- Read association fields from the selected FORMAT/sample namespace: `ES` is the signed effect estimate, `SE` is its standard error, `LP` is `-log10(p)`, `AF` is ALT/effect-allele frequency, `SS` is sample size, `EZ` is signed z-score, `SI` is numeric imputation accuracy, and `NC` is case count.
- Do not substitute a general VCF INFO annotation `AF` for the association sample's FORMAT `AF`.
- If a VCF contains multiple trait/sample columns, select the one explicitly matching the study/trait metadata. If it cannot be selected safely, block. Generic non-GWAS VCF files do not inherit these association conventions.
- If one VCF record contains multiple ALT alleles or multiple association values and one effect allele cannot be selected without expanding or duplicating the raw row, block rather than choosing the first ALT/value.

### FinnGen

- For the documented FinnGen association format, beta is relative to ALT: map `alt` to `effect_allele`, `ref` to `other_allele`, `beta`, `sebeta`, `pval`, `mlogp`, and `af_alt` by their meanings.
- For binary traits, same-namespace `af_alt_controls` may be preferred for frequency QC when no overall `af_alt` is available. `maf`, `maf_cases`, and `maf_controls` are frequency-QC candidates only and do not determine effect direction.
- `rsids` may contain multiple identifiers; extract one valid rsID. Leave `info` empty unless the association file actually contains a numeric imputation/variant-quality field.

### Pan-UKB

- ALT is the effect allele and REF is the other allele for documented Pan-UKB per-phenotype association files.
- For Pan-UKB-style scoped columns, choose one ancestry scope and use it consistently across all scoped columns. Use `pan_ukb_scope` when provided; otherwise infer from `ancestry`. If ancestry is missing or ambiguous, default to EUR when EUR scoped columns exist. Do not mix scopes such as `beta_EUR` with `se_AFR`.
- Keep population-specific, `meta`, and `meta_hq` fields as distinct namespaces. Select matching `beta_*`, `se_*`, `neglog10_pval_*`, frequency, and sample-size fields from one namespace.
- For binary traits, a same-scope control allele frequency may be used for `freq_qc` when no same-scope overall frequency exists.
- `low_confidence`, `low_confidence_*`, and scoped variants such as `low_confidence_EUR` are boolean QC flags, not numeric INFO scores, and must not be mapped to `info`.

### Common Association Software

- SAIGE: in a matching SAIGE single-variant result, `Allele2` is the effect allele, `Allele1` is the other allele, `BETA` and `AF_Allele2` refer to Allele2, and numeric `imputationInfo` may map to `info`.
- REGENIE: in a matching REGENIE single-variant result, `ALLELE1` is the ALT/effect allele, `ALLELE0` is the REF/other allele, and `A1FREQ` refers to ALLELE1. Keep `BETA`, `SE`, `LOG10P`, `INFO`, and `N` in that same result namespace.
- BOLT-LMM: in a matching BOLT-LMM result, `ALLELE1` is the effect allele, `ALLELE0` is the other allele, and `A1FREQ` and `BETA` refer to ALLELE1.
- PLINK association output: A1 is the tested/dosage allele to which BETA or OR refers, but A1 is not universally ALT or the minor allele. Use A1/A2 only when the header and test output identify this convention. Keep the selected statistic, SE, frequency, and test in one namespace. If mixed `TEST` records cannot be represented while preserving every raw variant row, block.
- PLINK `STAT` is test-dependent and is not universally a standard-normal
  z-score. Do not map `STAT` to canonical `z` from its name alone. For PLINK
  linear-regression output, where `STAT` is a t-statistic, leave canonical `z`
  empty when `BETA`, `SE`, and `P` are available; downstream formatting may
  compute the method-specific z representation. Map `STAT` to `z` only when
  explicit source metadata or a complete documented signature defines it as a
  signed standard-normal z-score.
- Neale Lab UK Biobank v3-style output: when the complete signature includes a
  packed `variant=CHR:BP:REF:ALT` field together with `minor_allele`,
  `minor_AF`, `n_complete_samples`, `AC`, `ytx`, `beta`, `se`, `tstat`, and
  `pval`, beta is ALT-oriented; map ALT to `effect_allele` and REF to
  `other_allele`. `minor_allele` and `minor_AF` remain identity/frequency-QC
  fields and do not independently establish direction.

### Provenance-Suffixed Companion Columns

- Treat a provenance suffix such as `_UKB` as a namespace label, not as a file
  format or effect-direction rule. Interpret the semantic stem and the observed
  values: an rsID-like `SNPID_*` field may supply `SNP`, a numeric `INFO_*`
  field may supply `info`, and a valid `MAF_*` field may supply `freq_qc`.
- Use the selected companion suffix consistently when mapping `freq_qc`. If a
  provenance scope such as `_UKB` is established by selected companion fields
  such as `SNPID_UKB` and `INFO_UKB`, and both an unsuffixed frequency field
  such as `MAF` and a matching suffixed field such as `MAF_UKB` exist, map the
  matching suffixed field to `freq_qc`. This matching-suffix preference is
  mandatory unless stronger explicit metadata states that the unsuffixed
  frequency belongs to the selected provenance scope or that the suffixed
  frequency has incompatible semantics.
- Suffixed identifier, quality, and frequency companions do not establish which
  allele a signed statistic refers to. Resolve effect direction from the
  association fields and their documented joint convention, and never replace
  a coherent association namespace merely because a companion column carries
  a source suffix.
- Keep companion values from one coherent provenance scope. Do not combine
  fields with different suffixes or scopes unless the source explicitly
  documents them as the same association record.

## User Mapping Notes

`mapping_notes` is reserved for explicit user-provided explanations about this file, not an upstream agent's inferred mapping. An absent value means the user supplied no extra explanation; it does not weaken the evidence from file metadata or a complete documented format signature. Apply the evidence hierarchy above. Record your own mapping decisions and assumptions in the generated response and QC report, without attributing them to the user. If a supplied explanation conflicts with source evidence, disclose the conflict and apply the existing conflict and validation rules.

## Canonical Column Semantics

| Canonical field | Mapping requirement |
| --- | --- |
| `SNP` | One rsID-like identifier only. Identifier fields such as `SNPID` may carry a provenance suffix such as `_UKB`; use the value only when it is rsID-like. |
| `CHR`, `BP` | Source chromosome and base-pair location, without build conversion. |
| `effect_allele`, `other_allele` | One coherent allele pair from the selected association namespace, with resolved direction or a disclosed soft fallback. |
| `beta` | Signed additive/log-effect estimate only; never an odds ratio or hazard ratio. |
| `or` | Odds ratio only; do not convert it to beta. |
| `se` | Standard error of the selected effect estimate only; never a p-value, z-score, or confidence bound. |
| `z` | Signed z-score only; never chi-square or an unsigned statistic. |
| `pval` | Ordinary p-values in `[0, 1]` only. Do not place `LP`, `LOGP`, `LOG10P`, or other `-log10(p)` values here. |
| `neglog10_pval` | Non-negative `-log10(p)` values only. Do not convert ordinary p-values. |
| `freq_qc` | A compatible allele frequency, effect-allele frequency, minor-allele frequency, or control frequency used only for frequency QC. A semantic frequency field such as `MAF` may carry a provenance suffix such as `_UKB`. Prefer the selected scope/namespace. Do not flip it or use its values to infer direction. |
| `info` | A numeric imputation or variant-quality score where larger means higher quality and the value is directly usable as a quality threshold, such as `INFO`, a provenance-suffixed `INFO_*`, `imputation_info`, `imputation_quality`, `R2`, or `RSQ`. Boolean inclusion/exclusion flags are not INFO. |
| `n` | Row-level total/per-variant sample size only. If N exists only as side metadata, leave row-level sample-size columns empty; downstream formatting uses the side-level value. |
| `n_cases`, `n_controls` | Row-level case and control counts respectively; do not exchange them or derive total N. |

## Consistency Checks Before Returning Code

Confirm that:

- the study contains usable variant identity as an rsID or an unambiguous
  coordinate plus both alleles;
- usable effect and other alleles belong to the selected statistic's
  namespace; row-level symbolic allele records follow the missing-value rule
  and do not invalidate otherwise usable study rows;
- one signed statistic among `beta`, `or`, or `z` is available;
- at least one compatible uncertainty/significance field among `se`, `pval`, `neglog10_pval`, or `z` is available;
- sample size is available as row-level `n`, both row-level case/control counts, or side-level context;
- ordinary p-values are compatible with `[0, 1]`, `-log10(p)` is non-negative, and frequency values are compatible with frequency semantics;
- scoped or suffixed fields have not been mixed across ancestry, trait, sample, imputation panel, original/harmonized representation, or analysis test.
- when both unsuffixed and provenance-suffixed frequency candidates exist,
  `freq_qc` matches the selected companion suffix unless stronger explicit
  metadata documents the exception.

If a numeric column conventionally named `N`, `NMISS`, `SS`, `samplesize`, or
equivalent is the only executable sample-size mapping but its provenance is not
fully documented, map it and add a `sample_size_semantics` soft assumption.
Block only when no usable sample-size value exists at all.

If a required item crosses the hard-block boundary, return a structured
blocked response. Otherwise generate one coherent transform and disclose every
unresolved decision in `assumptions`.

## JSON Response Shape

For code:

```json
{
  "status": "ok",
  "code": "def transform(input_path, output_path, context):\n    ...",
  "reason": "short explanation of the identified format and mapping namespace",
  "assumptions": [
    {
      "kind": "effect_allele_direction or sample_size_semantics",
      "decision": "the mapping used by the generated code",
      "basis": "why this is the best executable mapping",
      "risk": "what could change if the assumption is wrong"
    }
  ]
}
```

For blocked:

```json
{
  "status": "blocked",
  "failure_class": "missing_required_...",
  "missing_requirements": [
    {"field": "allele_pair", "message": "why no executable allele pair can be formed"}
  ],
  "reason": "short explanation"
}
```
