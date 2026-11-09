## Two-sample MR: hexadecanedioate levels → coronary artery disease

The requested two-sample Mendelian randomization analysis was completed using exposure **Hexadecanedioate levels** (GCST90243839) and outcome **Coronary artery disease** (GCST90132314). Estimates are on the `standardize` input scale.

### MR estimates

| Method | Instruments | Beta | SE | CI lower | CI upper | p-value |
|---|---:|---:|---:|---:|---:|---:|
| IVW | 10 | -0.00877503934156128 | 0.0059768865785 | -0.0204895217751021 | 0.00293944309197954 | 0.142060151406819 |
| MR-Egger | 10 | -0.0393964274516033 | 0.0253493444212965 | -0.0978521205118276 | 0.019059265608621 | 0.158757590345491 |
| Weighted median | 10 | -0.0131300643345956 | 0.00620854820629253 | -0.0252985952152097 | -0.000961533453981518 | 0.0344438851315121 |
| Weighted mode | 10 | -0.0175270809988976 | 0.0189442944019554 | -0.0603820522744389 | 0.0253278902766438 | 0.379006247645994 |
| MR-APSS | 31 | -0.0148554543367293 | 0.00997435147238598 | -0.0344051832226058 | 0.00469427454914721 | 0.13639 |
| BWMR | 10 | -0.00901668509042803 | 0.00621574651963823 | -0.0211995482689189 | 0.00316617808806289 | 0.146885753486633 |

All point estimates were negative. IVW, MR-Egger, weighted mode, MR-APSS, and BWMR had confidence intervals spanning the null. The weighted median was nominally significant, but this was not corroborated by the other methods. Overall, the results do **not** provide consistent evidence for a causal effect of hexadecanedioate levels on coronary artery disease risk.

### Sensitivity diagnostics

- MR-Egger intercept p-value: 0.249776799773281; no detected directional pleiotropy.
- IVW heterogeneity p-value: 0.0545001410027869; MR-Egger heterogeneity p-value: 0.0827692499937809.
- MR-PRESSO global p-value: 0.057; no detected global pleiotropy, and outlier status was not tested.
- Steiger diagnostics were unavailable/not requested.

### Effect scale

The input scale is `standardize`: SNP–exposure and SNP–outcome input effects were constructed as Z/sqrt(N) with standard errors 1/sqrt(N), separately for each trait. The reported MR beta is the fitted exposure-to-outcome slope across instruments; its SE and confidence interval are estimator-derived and are **not** themselves Z/sqrt(N) or 1/sqrt(N). No odds ratio is reported because this was not a native log-odds fit.

### Result files

- [Method comparison record](workspace/outputs/9e6d6ea63abf/analysis_method_comparison_tdn4785n/reports/method_comparison_result_record.json)
- [Primary MR record](workspace/outputs/cc5ac7326e22/mr_primary_tizeuu7q/reports/mr_primary_result_record.json)
- [Sensitivity record](workspace/outputs/d5b79e5401bd/analysis_sensitivity_d0xk5hvh/reports/mr_sensitivity_result_record.json)
- [MR-APSS record](workspace/outputs/f2ed685faa65/mr_apss_sqnnzrer/reports/mrapss_result_record.json)
- [BWMR record](workspace/outputs/a4b4ddfdf6f8/mr_bwmr_82v_7hvf/reports/mr_bwmr_result_record.json)
- [Method comparison summary plot](workspace/outputs/9e6d6ea63abf/analysis_method_comparison_tdn4785n/plots/method_comparison_summary.png)
