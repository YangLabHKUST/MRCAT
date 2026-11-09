# Canonicalization Explanation

## Input and output
- Raw file: `finngen_R12_I9_CHD.gz`
- Canonical file: `study.canonical.tsv.gz`
- Physical format: `table`; input was gzip-compressed text opened as `gzip.open(..., 'rt')`; output was gzip-compressed tab-separated text.
- Rows read: `21,327,062`
- Rows written: `21,327,062`
- Validation outcome: no validation warnings recorded (`validation_warnings: []`); final execution exit code `0`.
- Side sample size: `500,348`

## Column mapping
| Raw field/expression | Canonical field | Operation | Evidence |
| --- | --- | --- | --- |
| `#chrom` (leading `#` stripped to `chrom`) | `CHR` | Direct string copy after missing-token normalization. | Source header `#chrom`; final code strips `#` and reads `idx['chrom']`; sample rows contain chromosome values. |
| `pos` | `BP` | Direct string copy after missing-token normalization. | Source header `pos`; sample rows contain positions. |
| `rsids` | `SNP` | Extract first `rs\d+` token with regex; write empty if none is present. | Source header `rsids`; final code `_extract_rsid`; execution records `snp_id_type: rsid` and `raw_rsid_retained: 20,603,728`. |
| `alt` | `effect_allele` | Copy `alt` when both `ref` and `alt` are nucleotide sequences; otherwise write empty. | Final code `effect_allele = alt`; codegen-prompt FinnGen convention: ALT is the effect allele for documented FinnGen association files; execution summary `mapping_reason`. |
| `ref` | `other_allele` | Copy `ref` when both `ref` and `alt` are nucleotide sequences; otherwise write empty. | Final code `other_allele = ref`; same FinnGen convention and execution summary evidence. |
| `beta` | `beta` | Direct string copy after missing-token normalization. | Source header `beta`; final code `_norm_field(_cell(row, i_beta))`; FinnGen convention maps `beta` directly as signed effect estimate. |
| `sebeta` | `se` | Direct string copy after missing-token normalization. | Source header `sebeta`; final code maps `sebeta` to canonical `se`; FinnGen convention treats `sebeta` as standard error of beta. |
| `pval` | `pval` | Direct string copy after missing-token normalization. | Source header `pval`; sample values are ordinary p-values between 0 and 1. |
| `mlogp` | `neglog10_pval` | Direct string copy after missing-token normalization. | Source header `mlogp`; sample values are non-negative; codegen-prompt interprets `mlogp` as `-log10(p)`. |
| `af_alt` | `freq_qc` | Direct string copy after missing-token normalization. | Source header `af_alt`; final code and execution summary record `freq_qc_source: af_alt`. |

No source fields were mapped to canonical `or`, `z`, `info`, `n`, `n_cases`, or `n_controls`; those columns were written as empty strings.

## Additional processing
- Extracted rsIDs: yes, from `rsids` using the regex `rs\d+` and writing the first valid match.
- Parsed packed fields: not performed by the final code; it used explicit `#chrom`, `pos`, `ref`, and `alt` fields.
- Normalized missing tokens: yes, `_norm_field` treated empty, `.`, `NA`, `N/A`, `NULL`, `NaN`, and `nan` as missing and wrote empty strings.
- Wrote empty canonical fields: yes, `or`, `z`, `info`, `n`, `n_cases`, and `n_controls` were written empty because no corresponding row-level source fields existed; only study-level sample size was provided.
- Other explicit transformations: the code validated `ref` and `alt` as nucleotide sequences; if either was non-nucleotide, it preserved the row but wrote empty `effect_allele` and `other_allele`.
- The source fields `nearest_genes`, `af_alt_cases`, and `af_alt_controls` were present but not mapped to canonical fields by the final code.
- The code contains a skip for all-empty rows, but recorded `rows_read == rows_written == 21,327,062`, so no raw data rows were dropped.

## Genome build
- Recorded `genome_build`: `grch38`
- Recorded `genome_build_reason`: `The coordinate_check sampled 1000 variants and found 316 GRCh38 matches versus 1 GRCh37 match, indicating GRCh38 coordinates.`

## Variant identity and HM3 mapping
Recorded coordinate-to-rsid/HM3 mapping summary:
- `raw_rsid_retained`: `20,603,728`
- `hm3_rsid_mapped`: `0`
- `unmapped_rows`: `723,334`
- `rows`: `21,327,062`
- `genome_build`: `grch38`
- `enabled`: `true`

Recorded `snp_id_counts`:
- `rsid`: `20,603,728`
- `coordinate`: `0`
- `other`: `0`
- `missing`: `723,334`

No HM3 rsID mapping occurred; the `723,334` rows without an rsID were written with empty `SNP`.

## Direction and assumptions
- Effect allele used by the final code: `alt`
- Other allele used by the final code: `ref`
- Signed statistic used by the final code: `beta` from source column `beta`
- Standard error used: `se` from source column `sebeta`
- `pval` came from `pval`; `neglog10_pval` came from `mlogp`; `freq_qc` came from `af_alt`
- Basis: matching documented FinnGen format convention in the code-generation prompt, and the recorded execution summary `mapping_reason`: `FinnGen R12 association file with documented ALT-oriented beta: alt maps to effect_allele, ref to other_allele, beta/sebeta/pval/mlogp/af_alt map directly, and row-level sample-size columns are left empty because only study-level counts are provided.`
- `mapping_notes` was `null`, so no user-supplied mapping note was used.
- The code did not flip alleles or signed statistics; `beta` values were copied as-is into the ALT-oriented effect-allele namespace.
- No soft-assumption block was recorded in the evidence; direction was treated as resolved by the matching FinnGen convention.

## Execution notes
- Final execution exit code: `0`
- `stderr_tail`: empty
- `stdout_tail` printed a canonical preview, including one row at `BP 14872` with an empty `SNP`, consistent with the recorded missing-rsID rows.
- Final stdout JSON summary:
  `{"result": {"rows_written": 21327062, "side_sample_size": 500348, "effect_allele_source": "alt", "other_allele_source": "ref", "freq_qc_source": "af_alt"}}`
- No validation warnings were recorded.

## Audit boundary
This explanation describes what the executed code did; it does not independently validate biological correctness or create new downstream inputs.
