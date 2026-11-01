# Third-party components

The root LICENSE applies to original MRCAT code. It does not replace the licenses
or terms of third-party software and data.

| Component | Location or installation | Source and retained notice |
| --- | --- | --- |
| Plotly.js gl2d 3.1.0 | `mrcat/web/static/vendor/` | `plotly-LICENSE.txt` in the same directory |
| Lucide icons | `mrcat/web/static/icons/` | `LUCIDE_LICENSE.txt` |
| Tabler icons | `mrcat/web/static/icons/` | `TABLER_LICENSE.txt` |
| BWMR updated implementation | Retrieved by the R installer, not bundled | [jiazhao97/BWMR, commit c00e8186f12ed25899aaf85b7ac5c98c6d86c24c](https://github.com/jiazhao97/BWMR/blob/c00e8186f12ed25899aaf85b7ac5c98c6d86c24c/updates/BWMR_updated.R) |
| Specialist MR packages | Installed separately into R | Upstream references in `scripts/install_r_dependencies.R` |

The inspected BWMR commit contains no standalone LICENSE or License field in its
DESCRIPTION. Its source is therefore obtained separately rather than assigned the
MRCAT license. Review the upstream terms for your intended use or redistribution.
GWAS datasets and reference panels are also obtained separately under their
original providers' terms. Method citations and interpretation notes are retained
in the relevant Skill guides.
