---
source-config:
  remote-priority: true
  ancestry-aliases:
    european: [european, europe, eur]
    african: [african, africa, afr]
    east_asian: [east asian, eas]
    admixed_american: [admixed american, american admixed, amr]
    central_south_asian: [central south asian, south asian, csa, sas]
    middle_eastern: [middle eastern, greater middle eastern, mid, mea]
    multi_ancestry: [multi ancestry, mixed ancestry, trans ethnic, multi]
    finnish: [finnish, finland, finn, finngen, fin]
    japanese: [japanese, japan, biobank japan, bbj]
    taiwanese: [taiwanese, taiwan, taiwan biobank, twb]
    central_asian: [central asian, central asia]
  ancestry-routes:
    european: [opengwas, gwas_catalog, pan_ukb, finngen]
    african: [pan_ukb, opengwas, gwas_catalog]
    east_asian: [pan_ukb, opengwas, gwas_catalog]
    admixed_american: [pan_ukb, opengwas, gwas_catalog]
    central_south_asian: [pan_ukb, opengwas, gwas_catalog]
    middle_eastern: [pan_ukb, opengwas, gwas_catalog]
    multi_ancestry: [pan_ukb, opengwas, gwas_catalog]
    finnish: [finngen, opengwas, gwas_catalog]
    japanese: [opengwas, gwas_catalog]
    taiwanese: [gwas_catalog, opengwas]
    central_asian: [gwas_catalog, opengwas]
  sources:
    opengwas:
      metadata_endpoint: "https://api.opengwas.io/api/gwasinfo"
      files_endpoint: "https://api.opengwas.io/api/gwasinfo/files"
      auth_env: "OPENGWAS_JWT"
      requires_auth_for_search: true
    gwas_catalog:
      metadata_endpoint: "https://www.ebi.ac.uk/gwas/rest/api/v2/studies"
      summary_statistics_base: "https://ftp.ebi.ac.uk/pub/databases/gwas/summary_statistics"
      summary_statistics_patterns:
        - "{base}/{range_dir}/{study_id}/{study_id}_buildGRCh38.tsv.gz"
        - "{base}/{range_dir}/{study_id}/{study_id}_buildGRCh37.tsv.gz"
        - "{base}/{range_dir}/{study_id}/{study_id}.tsv.gz"
    pan_ukb:
      metadata_endpoint: "https://pan-ukb-us-east-1.s3.amazonaws.com/sumstats_release/phenotype_manifest.tsv.bgz"
      flat_files_base: "https://pan-ukb-us-east-1.s3.amazonaws.com/sumstats_flat_files"
    finngen:
      default_release: "R12"
      metadata_endpoint: "https://storage.googleapis.com/finngen-public-data-r12/summary_stats/finngen_R12_manifest.tsv"
      releases:
        R12:
          mode: "manifest"
          manifest_url: "https://storage.googleapis.com/finngen-public-data-r12/summary_stats/finngen_R12_manifest.tsv"
        R10:
          mode: "api"
          metadata_endpoint: "https://r10.finngen.fi/api/phenos"
          autocomplete_endpoint: "https://r10.finngen.fi/api/autocomplete"
          pheno_endpoint_template: "https://r10.finngen.fi/api/pheno/{pheno}"
          descriptor_url_template: "https://storage.googleapis.com/finngen-public-data-r10/summary_stats/finngen_{release}_{endpoint}.gz"
---

# Database Notes For `gwas-search`

This file provides supplemental source-specific search notes for the GWAS search skill.

## OpenGWAS

- Prefer metadata / index APIs for search.
- Mark a study as downloadable only when it can be resolved to complete summary statistics or a clear download location.
- In the formal milestone, keep only `population`, compact publication timing fields, download fallback fields, and `sample_size` / `ncase` / `ncontrol`.

## GWAS Catalog

- A trait hit alone is not enough; summary statistics availability must be confirmed.
- Extract only scalar publication date/year fields; do not include the full publication blob in the formal milestone.
- Compress ancestry / cohort descriptions into `population` when they help selection.
- Preserve official `initialSampleSize` and `replicationSampleSize`; normalized `sample_size` should come only from initial/discovery sample size.

## FinnGen

- Search the official R12 manifest by default; explicit `finngen_R10_*` IDs still use the R10 API.
- The release in a study ID is a strict routing condition; do not silently fall back across releases.
- Preserve `release`, `endpoint`, `endpoint_code`, `num_cases`, `num_controls`, and download fallback fields.
- If the source does not provide independent publication timing, do not synthesize extra `publication_*` fields.

## Pan-UKB

- Prefer searching the phenotype manifest TSV.
- Preserve `filename`, `trait_type`, `phenocode`, and compact `population` context fields.
- Do not include `category` or large manifest row contents in the formal milestone.

## Common Output Rule

Each formal result should use this shape:

```json
{
  "trait": "natural language trait name",
  "study_id": "source-native study identifier",
  "source": "opengwas|gwas_catalog|finngen|pan_ukb",
  "downloadable": true,
  "download_descriptor": {
    "source": "opengwas",
    "study_id": "source-native study identifier",
    "status": "ready",
    "method": "url",
    "requires_auth": false,
    "url": "https://..."
  },
  "downloadability_reason": "confirmed_url|resolved_url|requires_auth|no_summary_stats|probe_failed|unresolved",
  "requires_user_confirmation": false,
  "sample_size": 123456,
  "n_cases": null,
  "n_controls": null,
  "study_metadata": {
    "population": "European",
    "publication_year": 2021
  }
}
```

Full raw metadata, matched information, and download probe results should be written to raw artifacts, not to the formal milestone.

The sorted shortlist in the formal milestone is itself the downstream selection input; do not mirror any extra "best candidate" fields.

## Error Handling

If a source errors, return this structure:

```json
{
  "source": "gwas_catalog",
  "status": "error|empty|auth_required",
  "n_results": 0,
  "message": "...",
  "metadata_endpoint": "https://..."
}
```
