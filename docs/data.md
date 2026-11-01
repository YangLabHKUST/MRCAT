# Data and reference resources

GWAS datasets and reference panels are not included in this repository. Prepare
only the resources needed by the chosen method. Missing resources are reported as
an analysis boundary; the runtime does not silently substitute a population or build.

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
