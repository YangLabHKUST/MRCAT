---
name: gwas-download
description: "Download one selected remote GWAS study or one user-supplied raw-file URL; preserve metadata and reuse the download cache."
accepts-milestones: [gwas_selection_result]
produces-milestone: gwas_download_result
reusable-outputs: [downloaded_study]
---

# gwas-download

Download one selected remote GWAS study or one user-supplied raw-file URL; preserve metadata and reuse the download cache.

## Use in Python

Shared calling conventions: [runtime reference](../runtime-reference.md); also supplied in the Executor instructions.

Use `gwas_download` from `mrcat.tools` in the active `mrcat` environment.

```python
from mrcat.tools import gwas_download

result = gwas_download(
    download_url='https://example.org/study.tsv.gz',
    label='User-provided study',
)
print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["gwas_download_result"]
    print(result.get("artifacts", []))
else:
    print(result.get("details", {}))
```

## Parameters

| Parameter | Type | Required / default | Meaning |
| --- | --- | --- | --- |
| `selected_study` | object | optional | Complete selected candidate; exclusive with download_url. |
| `download_url` | string | optional | User-provided raw HTTP(S) URL; exclusive with selected_study. |
| `label` | string | optional | Known study/trait display label. |
| `sample_size` | integer | optional | Documented positive study N; omit unknown. |
| `ancestry` | string | optional | Known population or explicit user constraint; omit unknown. |
| `study_metadata` | object | optional | Complete structured source/file metadata; preserve unknowns. |
| `output_dir` | path | optional | Fresh output directory; created automatically when omitted. |

## Choosing inputs

Choose exactly one mode: `selected_study` is one complete candidate object that you selected from a search shortlist; or `download_url` is the user's HTTP(S) raw-data URL. The example URL is a placeholder and must be replaced. Never pass a shortlist, study-ID string or landing page as the selected object.

Selected-study mode needs `source`, `study_id`, and an executable `download_descriptor`; preserve the whole candidate. Direct-URL metadata (`label`, `sample_size`, `ancestry`, `study_metadata`) is optional; omit unknown facts. Local files need no download. Reuse one download per study. Use `output_dir` to choose the download destination. The function handles metadata and file transport.

## Provenance checks

Downloading implements an already justified selection, not a new study choice.
Do not replace a failed selected study with a related dataset. Preserve normalized
study facts and nulls in downloaded_study, plus complete study_metadata and
source/file notes. GWAS Catalog README/meta/notes can define assembly or allele
semantics; retain that evidence on cache hits as well as new downloads. Pass the
whole returned object to QC. Download success proves transport, not phenotype
compatibility, allele orientation or readiness for causal interpretation.

## Outputs and checks

On success, `result["outputs"]["gwas_download_result"]` holds the data described below.

`downloaded_study` holds `raw_path`, file size, labels, source/ID, ancestry, sample-size facts and `study_metadata`. Pass this entire object to QC. Keep cache-hit metadata and GWAS Catalog file notes; a downloaded file alone is not analysis-ready.

