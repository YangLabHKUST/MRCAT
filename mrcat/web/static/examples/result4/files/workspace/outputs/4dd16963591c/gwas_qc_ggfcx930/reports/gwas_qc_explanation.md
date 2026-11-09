## Input and output

- Raw file: `/recorded-session/cache/gwas-download/gwas_catalog/GCST90132314/88763fd2db35d60c/GCST90132314_buildGRCh37.tsv`
- Canonical file: `/recorded-session/workspace/outputs/4dd16963591c/gwas_qc_ggfcx930/canonical/study.canonical.tsv.gz`
- Physical format: raw `table`; canonical output written as tab-separated text by `csv.writer`.
- Rows read: `20,073,070`
- Rows written: `20,073,070`
- Validation outcome: execution exit code `0`; `validation_warnings` empty; code-generation attempt status `sample_ok`.

## Column mapping

| Raw field/expression | Canonical field | Operation | Evidence |
| --- | --- | --- | --- |
| `p_value` cleaned | `pval` | Direct copy after missing-token cleanup | Final code assigns cleaned `p_value` to canonical `pval` output index |
| `chromosome` cleaned | `CHR` | Direct copy after cleanup | Final code assigns cleaned `chromosome` to canonical `CHR` output index |
| `base_pair_location` cleaned | `BP` | Direct copy after cleanup | Final code assigns cleaned `base_pair_location` to canonical `BP` output index |
| `effect_allele` cleaned | `effect_allele` | Direct copy if both alleles pass `_usable_allele`; otherwise empty | Final code validates allele strings and writes cleaned `effect_allele` |
| `other_allele` cleaned | `other_allele` | Direct copy if both alleles pass `_usable_allele`; otherwise empty | Final code validates allele strings and writes cleaned `other_allele` |
| `effect_allele_frequency` cleaned | `freq_qc` | Direct copy after cleanup | Final code assigns cleaned `effect_allele_frequency` to canonical `freq_qc` |
| `odds_ratio` cleaned | `or` | Direct copy after cleanup | Final code assigns cleaned `odds_ratio` to canonical `or` |
| `beta` cleaned | `beta` | Direct copy after cleanup | Final code assigns cleaned `beta` to canonical `beta` |
| `standard_error` cleaned | `se` | Direct copy after cleanup | Final code assigns cleaned `standard_error` to canonical `se` |
| `cases` cleaned | `n_cases` | Direct copy after cleanup | Final code assigns cleaned `cases` to canonical `n_cases` |
| `n` cleaned | `n` | Direct copy after cleanup | Final code assigns cleaned `n` to canonical `n` |

## Additional processing

- Missing-token normalization: performed. The final code treats empty strings, `.`, `NA`, `N/A`, `NULL`, `NaN`, and `nan` as missing and writes them as empty strings.
- Packed-field parsing: not performed by the final code. The `markername` field was not parsed; separate `chromosome` and `base_pair_location` fields were used.
- rsID extraction: not performed by the final code. `SNP` was written as an empty string.
- Empty canonical fields written: `SNP`, `z`, `neglog10_pval`, `info`, and `n_controls` were written empty. If either raw allele failed the nucleotide-only `_usable_allele` check, `effect_allele` and `other_allele` were both written empty for that row.
- Row skips: the final code skipped rows where all cells were missing and otherwise preserved one output row per raw variant row.
- Not performed by the final code: no parsing of `markername`, no allele swapping, no frequency flipping, no statistic derivation, no liftover, no deduplication, no reordering, and no mapping of unused fields such as `freqse`, `minfreq`, `maxfreq`, `direction`, `hetisq`, `hetchisq`, `hetdf`, `hetpval`, `effective_cases`, or `meta_analysis`.

## Genome build

- `genome_build`: `grch37`
- `genome_build_reason`: `Study metadata explicitly states genome_assembly GRCh37 and file notes state base_pair_location is according to GRCh37; coordinate_check matched 365 sampled positions to GRCh37 versus 1 to GRCh38.`

## Variant identity and HM3 mapping

The final transform wrote `SNP` as an empty string and did not extract rsIDs from `markername`.

Recorded coordinate-to-rsID/HM3 mapping result:

- `raw_rsid_retained`: `0`
- `hm3_rsid_mapped`: `1,184,393`
- `unmapped_rows`: `18,888,677`
- `rows`: `20,073,070`
- `genome_build`: `grch37`
- `enabled`: `true`

Recorded `snp_id_counts`:

- `rsid`: `1,184,393`
- `coordinate`: `0`
- `other`: `0`
- `missing`: `18,888,677`
- `snp_id_type`: `rsid`

## Direction and assumptions

- Effect allele: final code used source `effect_allele`.
- Other allele: final code used source `other_allele`.
- Signed statistic: final code used `beta` as canonical `beta` and `odds_ratio` as canonical `or`.
- Basis: source metadata/file notes explicitly state that `effect_allele` is “the allele to which the beta and odds ratio correspond” and `other_allele` is the “non-effect” allele. This was also recorded in the execution mapping reason as a documented GWAS Catalog pre-GWAS-SSF file with explicit `effect_allele`, `other_allele`, `beta`, and `odds_ratio` fields.
- No soft fallback or direction assumption is recorded in the supplied execution evidence.

## Execution notes

- Final execution exit code: `0`.
- Final execution stderr tail: empty.
- `validation_warnings`: empty.
- Execution summary stdout preview printed the canonical header and preview rows, followed by `{"result": {"rows_written": 20073070}}`.
- The final generated code opened the output path with `open(output_path, 'w')`, not `gzip.open`; the supplied canonical path ends in `.tsv.gz`.

## Audit boundary

This explanation describes what the executed code did; it does not independently validate biological correctness or create new downstream inputs.
