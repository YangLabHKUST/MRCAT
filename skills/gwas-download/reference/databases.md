# Source Download Notes

This file describes download considerations for `gwas-download` across different databases.

---

## 1. OpenGWAS (`opengwas`)

### Purpose
Download complete summary statistics for a study from OpenGWAS.

### Practice Notes
- Prefer the `download_descriptor` already provided in the input.
- If the descriptor is not executable, return blocked/error instead of searching for the study again.
- Some APIs may require a JWT.
- If a protected request is required, request user confirmation first.

### Common Metadata
- `study_id`
- `trait`
- `population`
- `sample_size`
- `ncase`
- `ncontrol`
- `year`
- `build`
- `consortium`

### Suggested Environment Variable
- `OPENGWAS_JWT`

---

## 2. GWAS Catalog (`gwas_catalog`)

### Purpose
Download files from GWAS Catalog summary-statistics locations that have already been confirmed as downloadable.

### Practice Notes
- Do not assume a study is downloadable from accession alone.
- Prefer the `download_descriptor` already confirmed during search.
- If a download link must be re-resolved, base it on known summary-statistics records or FTP paths.
- Validate that the URL exists before downloading.

### Common Metadata
- `accession_id`
- `reported_trait`
- `efo_trait`
- `publication_info`
- `initialSampleSize`
- `replicationSampleSize`

---

## 3. FinnGen (`finngen`)

### Purpose
Download summary-statistics files from FinnGen release and endpoint information.

### Practice Notes
- Prefer the already resolved `download_descriptor`.
- If there is no explicit URL, try constructing one from `release`, `endpoint code`, and `filename`.
- Automatically construct URLs only when the construction rule is stable.

### Common Metadata
- `endpoint_code`
- `release`
- `category`
- `num_cases`
- `num_controls`
- `sex_stratum`
- `filename`

---

## 4. Pan-UKB (`pan_ukb`)

### Purpose
Download GWAS summary statistics from Pan-UKB flat-file storage.

### Practice Notes
- Prefer the `filename` provided in the manifest.
- Download URLs can usually be constructed from stable rules.
- The common URL shape is:
  `https://pan-ukb-us-east-1.s3.amazonaws.com/sumstats_flat_files/{filename}`
- Preserve the original `filename` to avoid naming ambiguity.

### Common Metadata
- `phenotype_code`
- `filename`
- `trait_type`
- `category`
- `sex`
- `n_cases_<POP>`
- `n_controls_<POP>`
- `coding_description`

---

## Common Download Rule

Each study to download should preferably contain:

```json
{
  "trait": "coffee consumption",
  "study_id": "ukb-b-12345",
  "source": "opengwas",
  "downloadable": true,
  "download_descriptor": {
    "source": "opengwas",
    "study_id": "ukb-b-12345",
    "status": "ready",
    "method": "url",
    "requires_auth": false,
    "url": "https://..."
  },
  "requires_user_confirmation": false,
  "ancestry": "european",
  "study_metadata": {
    "any_source_specific_field": "keep it here"
  }
}
```

Notes:

- `download_descriptor` must have a stable status from the `gwas-search` stage.
- `gwas-download` focuses on executing downloads, not redoing complex search.
- `study_metadata` must remain a lightweight object; keep `{}` even when empty.
- If a URL truly needs to be constructed dynamically, do so only from stable manifest / metadata rules.

---

## Error Return Recommendation

If a source download fails, return:

```json
{
  "status": "error",
  "study_id": "ukb-b-12345",
  "source": "opengwas",
  "trait": "coffee consumption",
  "error": {
    "type": "download_error",
    "message": "..."
  }
}
```
