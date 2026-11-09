# Data and reference resources

GWAS datasets and reference panels are not included in this repository. Install
the complete reference set below; each method uses the resources it needs.
Missing resources are reported as
an analysis boundary; the runtime does not silently substitute a population or build.

## Prepare reference data

There is one complete reference-data set, containing HapMap3/MHC, European
LDSC, European GRCh37 and EUR/AFR/EAS/SAS GRCh38 PLINK panels, plus PLINK.
The installer always prepares every component. It handles the underlying
archives automatically; users do not select panels or installation profiles.
Exact files, sizes, SHA-256 checksums and source notes are recorded in
[database_manifest.json](../scripts/database_manifest.json).
The script uses only the Python standard library and does not read `.env`,
call a language model, or run an analysis.

**Publication status:** the MRCAT data archives have not been uploaded. Their
release URL is deliberately unset. Network installation becomes available after
publication and setting the manifest's `release_base_url`. The pinned PLINK
archive already has an official upstream URL.

After publication:

```bash
python scripts/download_database.py
```

Before publication, or for an offline installation, obtain the prepared archive
directory from the maintainer and run:

```bash
python scripts/download_database.py --from-dir /path/to/database-bundles
```

To verify the entire installation without downloading or changing files:

```bash
python scripts/download_database.py --check
```

For storage outside the checkout, export `MRCAT_DATABASE_DIR` before installing
and starting MRCAT. The script also accepts `--database-dir`; setting the path
only inside `.env` does not configure this standalone installer.

```bash
export MRCAT_DATABASE_DIR=/absolute/path/to/database
python scripts/download_database.py --from-dir /path/to/database-bundles
```

The complete set downloads about 2.92 GB and installs about 12.86 GB. Allow at
least 16 GB of free space for a fresh installation, plus space for GWAS inputs
and outputs. Existing verified files are reused. A damaged or different
component is reinstalled from the pinned snapshot after verification. Unlisted
files are left alone. Interrupted downloads restart on the next invocation.
Temporary downloads and staging directories are removed on normal completion
or handled errors. `--list` displays the contents without changing files.

The included PLINK executable requires **Linux x86_64**. The installer rejects
installation of that executable on other platforms. R dependencies remain a
separate installation step.

## Which resources are needed?

| Resource | Needed for | Preparation |
| --- | --- | --- |
| HapMap3 SNP list and MHC SNP list | `gwas-qc` formatting | `core` |
| European LDSC scores, chromosome counts and SNP list | `gwas-pair-prepare` background estimation; QC coordinate mapping and reference-based plots | `core` |
| European GRCh37 PLINK `.bed/.bim/.fam` | Local GRCh37 clumping and GRCh37 coordinate checks | `eur-grch37` |
| PLINK executable | Local LD clumping | `plink-linux-x86_64` |
| European GRCh38 PLINK `.bed/.bim/.fam` | GRCh38 coordinate-to-rsID mapping or GRCh38 local clumping | `eur-grch38` |
| African GRCh38 PLINK `.bed/.bim/.fam` | Compatible African-population local clumping | `afr-grch38` |
| East Asian GRCh38 PLINK `.bed/.bim/.fam` | Compatible East-Asian-population local clumping | `eas-grch38` |
| South Asian GRCh38 PLINK `.bed/.bim/.fam` | Compatible South-Asian-population local clumping | `sas-grch38` |
| Pan-UKB LD scores | Not selected by the current standard pair-preparation wrapper | Not included; outside the registered reference resources |

The installer prepares all listed components regardless of the next analysis.
Literature search alone needs none of them; individual analyses use the
resources appropriate to their studies. GRCh38 coordinate mapping currently resolves a complete registered
PLINK prefix, even though the mapper reads its `.bim` file; provide all three
files to satisfy that resource contract.

The current `gwas-pair-prepare` wrapper always resolves the **European LDSC**
resource. Adding an AFR/EAS/SAS PLINK panel changes the clumping reference only;
it does not make the LDSC background population-specific. Check compatibility
with the studies before running that workflow.

### GRCh38 panel snapshots

Each bundle contains the complete `.bed`, `.bim` and `.fam` set. File hashes,
sample counts and variant counts are recorded in the manifest. Installed sizes
are decimal GB:

| Bundle | Samples | Variants | Download size | Installed size |
| --- | ---: | ---: | ---: | ---: |
| `eur-grch38` | 633 | 11,417,608 | 455 MB | 2.15 GB |
| `afr-grch38` | 893 | 20,914,656 | 1,231 MB | 5.30 GB |
| `eas-grch38` | 585 | 10,097,576 | 377 MB | 1.78 GB |
| `sas-grch38` | 601 | 12,021,508 | 471 MB | 2.17 GB |

All seven bundles together download about **2.92 GB** and install about
**12.86 GB**. Each archive is under 2 GiB, so no split-file reassembly is needed.
Allow at least **16 GB**
of free space for a fresh installation, plus space for study data and analysis
outputs. Updating an existing complete installation can require extra staging
space while the old files are still present. This set covers every registered
reference resource; it does not imply that panels for every population or
genome build exist. No AMR PLINK panel is present in this snapshot.

The four sample sets exactly match the corresponding super-populations in the
[official PLINK GRCh38 sample metadata](https://www.cog-genomics.org/plink/2.0/resources).
Their `.bed` headers and dimensions agree with the `.bim` and `.fam` files.
These checks establish sample membership and file consistency. The original
conversion/filtering commands and a full genotype comparison with the upstream
callset have not been recovered, so these are explicitly identified as local
panel snapshots rather than byte-identical upstream distributions. Keep that
provenance limitation with any later publication; do not infer a MAF filter or
unrelated-sample subset from the filenames. Installing a panel does not change
the genome build or ancestry of a study.

The reference set omits duplicate `EUR.*` aliases, old chromosome-6 LDSC files,
copies of the original archives, PLINK toy data and `prettify`, and local method
notes. These files are not required by the registered resource contracts. The local
database is preserved; omission from a bundle does not delete local files.

## Sources and publication readiness

- The two HapMap3/MHC RDA files match the files in the pinned
  [MR-APSS source](https://github.com/YangLabHKUST/MR-APSS/tree/ef6afd2b4dd4923722cb74c4a5fd20dd41ed0510/data)
  byte for byte.
- The LDSC bundle preserves the existing `eur_w_ld_chr` files, including the
  chromosome-6 version with HLA removed. All 45 required score/count/SNP-list
  files are byte-identical to the
  [Original european LDscores archive](https://doi.org/10.5281/zenodo.14993076)
  (CC BY 4.0). The historical Broad download URL returned HTTP 404 during
  preparation; the verified Zenodo archive provides a working source for these
  same files. Do not substitute a different LDSC panel based on its name alone.
- The GRCh37 panel preserves the existing `data_maf0.01_rs_ref` files. The
  [upstream gwasglue tutorial](https://github.com/MRCIEU/gwasglue/blob/master/vignettes/mr.Rmd)
  names this reference archive. All three files are byte-identical to the
  [upstream archive](http://fileserve.mrcieu.ac.uk/ld/data_maf0.01_rs_ref.tgz)
  (archive SHA-256:
  `8c6086487fefff16dfba1635d5e7be33f3407209f695fcd80944f246a4c742ec`).
  The upstream HTTPS endpoint currently has a certificate hostname mismatch;
  the comparison used the documented HTTP endpoint and recorded the hashes.
  The prepared manifest pins both archive and installed-file hashes; it never
  disables TLS certificate verification.
- PLINK 1.9.0-b.7.11 (19 Aug 2025) comes from the pinned
  [official archive](https://s3.amazonaws.com/plink1-assets/plink_linux_x86_64_20250819.zip).
  Its binary matches the local installation; the installer also retains its
  upstream `LICENSE`.

Keep upstream attribution and applicable data terms with any published bundle.
The MRCAT code license does not replace those terms. The GRCh38 bundles are now
prepared for local installation with the provenance limitation described above;
their processing history still needs clarification before describing them as
fully reproducible upstream-derived references. No publication is performed by
the download script. After publication, a maintainer can set `release_base_url` or a
user can supply `--base-url` for the directory containing the exact pinned
archives; their checksums remain mandatory.

## Local GWAS files

Study setup accepts exposure and outcome files with their metadata. Provide the
phenotype definition, source/study identifier, ancestry, sample size and genome
build when known. Binary-trait directionality tests additionally require explicit
case/control and population-prevalence information. Unknown metadata must remain
unknown. See each Skill's input contract before running an analysis.

The usual local workflow is `gwas-qc` for each study, then `gwas-pair-prepare` for
the directed exposure–outcome pair, then an appropriate estimator. The pair's
preparation settings and the estimator's selection rule are distinct. Reversing
the direction requires suitable reverse-direction preparation.

## Reference directory

Place resources under `database/` in a source checkout, or set
`MRCAT_DATABASE_DIR=/absolute/path/to/database` for another location. The override
points directly at the database directory. It does not change code or configuration.
The resource resolver verifies the files required by each registered resource.

| Resource ID | Path inside the database directory |
| --- | --- |
| `hapmap3.snplist_rdata` | `hapmap3/w_hm3.snplist.rda` |
| `hapmap3.mhc_rdata` | `hapmap3/MHC.SNPs.rda` |
| `ldsc.eur` | `ldsc/eur_w_ld_chr/` |
| `plink.binary` | `plink/bin/plink1.9/plink` |
| `plink.eur.grch37` | `plink/EUR/data_maf0.01_rs_ref` |
| `plink.eur.grch38` | `plink/EUR/EUR_phase3_hg38_autosomes` |
| `plink.afr.grch38` | `plink/AFR/AFR_phase3_hg38_autosomes` |
| `plink.eas.grch38` | `plink/EAS/EAS_phase3_hg38_autosomes` |
| `plink.sas.grch38` | `plink/SAS/SAS_phase3_hg38_autosomes` |

PLINK prefixes require matching `.bed`, `.bim` and `.fam` files. The LDSC resource
requires `w_hm3.snplist`, chromosome 1–22 `.l2.ldscore.gz` files and corresponding
`.l2.M_5_50` files. PLINK must be executable. Obtain data from its original source
and verify population, assembly, variant identifiers and release metadata before use.
Record local checksums with the experiment; the directory name alone is not provenance.

```python
from mrcat.database import database, database_resource_ids

print(database_resource_ids())
print(database("ldsc.eur"))  # raises a specific error if incomplete
```

Optional method notes live under `database/docs/`. They describe a local
installation and must be checked against the actual installed package. They do
not supply missing scientific assumptions.

## R dependencies

Use `Rscript scripts/install_r_dependencies.R --check` to check the documented
R environment without installing packages. The installer uses the active R
installation's library and records selected upstream commits in the script.
Transitive dependencies are not fully locked.

The BWMR implementation is retrieved separately from its recorded upstream commit
into the active R library's `mrcat-methods/` directory; it is not redistributed
with MRCAT. `MRCAT_BWMR_SOURCE` can point to that same upstream source for an
existing installation. The installer verifies its checksum. The numerical
implementation is unchanged; only two local attribution comments were present in
the earlier bundled copy.
