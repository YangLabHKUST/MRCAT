## Replication assessment: hexadecanedioate levels → coronary artery disease

**Setting.** The exposure was preserved as `GCST90243839` (hexadecanedioate levels). The replacement outcome was FinnGen `finngen_R12_I9_CHD` (“Major coronary heart disease event”), compared with the original `GCST90132314` coronary artery disease outcome. The same primary suite, MR-APSS, and BWMR were fitted.

**Answer.** The FinnGen outcome branch did **not** statistically replicate the prior nominal weighted-median finding. All compared point estimates were inverse, every FinnGen confidence interval included the null, and every FinnGen p-value was above the planned alpha of 0.05. The original weighted-median estimate was β -0.0131300643345956 with CI -0.0252985952152097 to -0.000961533453981518 and p 0.0344438851315121; its FinnGen counterpart was β -0.00374490901250325 with CI -0.0217338084604373 to 0.0142439904354308 and p 0.683256704719799.

| Method | Original β (CI lower, CI upper) | Original p | FinnGen β (CI lower, CI upper) | FinnGen p |
|---|---|---|---|---|
| IVW | -0.00877503934156128 (-0.0204895217751021, 0.00293944309197954) | 0.142060151406819 | -0.00856171529298656 (-0.0278679448418377, 0.0107445142558646) | 0.384746843092962 |
| MR-Egger | -0.0393964274516033 (-0.0978521205118276, 0.019059265608621) | 0.158757590345491 | -0.041662752525425 (-0.143319703537776, 0.0599941984869257) | 0.372280395894546 |
| Weighted median | -0.0131300643345956 (-0.0252985952152097, -0.000961533453981518) | 0.0344438851315121 | -0.00374490901250325 (-0.0217338084604373, 0.0142439904354308) | 0.683256704719799 |
| Weighted mode | -0.0175270809988976 (-0.0603820522744389, 0.0253278902766438) | 0.379006247645994 | -0.0048612235424192 (-0.0672216754731057, 0.0574992283882673) | 0.863928472407596 |
| MR-APSS | -0.0148554543367293 (-0.0344051832226058, 0.00469427454914721) | 0.13639 | -0.0215882291121731 (-0.0505523769088152, 0.00737591868446897) | 0.14405 |
| BWMR | -0.00901668509042803 (-0.0211995482689189, 0.00316617808806289) | 0.146885753486633 | -0.00884466048690903 (-0.0289041974811938, 0.0112148765073758) | 0.387475768286607 |

**FinnGen sensitivity diagnostics.** Heterogeneity was detected: IVW heterogeneity p 0.0207877012064813, MR-Egger heterogeneity p 0.0196937421087678. MR-PRESSO global p was 0.018, with 1 detected outlier and distortion p 0.016. MR-Egger intercept p was 0.462698310287103. Steiger filtering was unavailable because the exposure/outcome type specification was missing.

**Scale interpretation.** Inputs were on the `standardize` scale. In this workflow, SNP-trait input effects use Z/sqrt(N) and input standard errors use 1/sqrt(N), separately for exposure and outcome. The reported MR beta is the fitted exposure-to-outcome slope, and its standard error and confidence interval are produced by each estimator across instruments; the fitted MR beta is not itself Z/sqrt(N), and the fitted MR standard error is not 1/sqrt(N). These standardized estimates do not provide a native clinical-unit or odds-ratio interpretation.

**Limitations.** The FinnGen outcome is Finnish, while the retained exposure and EUR clumping/LDSC references are European, so ancestry mismatch limits portability. The FinnGen selection uses a major coronary heart disease event endpoint as a CAD proxy, not the exact original CAD definition. Different outcome study IDs do not by themselves establish fully independent samples or replication.

**Key artifacts.** [Replication result](workspace/outputs/19c8f69c9557/analysis_replication_8ut6uc3c/reports/replication_result_record.json) · [Replication forest plot](workspace/outputs/19c8f69c9557/analysis_replication_8ut6uc3c/plots/replication_forest_matrix.png) · [FinnGen primary MR](workspace/outputs/32e9f140fc83/mr_primary_m8lrhgrn/reports/mr_primary_result_record.json) · [FinnGen sensitivity](workspace/outputs/81bb521130c4/analysis_sensitivity_bae6cb4m/reports/mr_sensitivity_result_record.json) · [FinnGen APSS](workspace/outputs/f557bbed1fec/mr_apss_x2od2x4m/reports/mrapss_result_record.json) · [FinnGen BWMR](workspace/outputs/09f910c44d94/mr_bwmr_q1dkdu92/reports/mr_bwmr_result_record.json)
