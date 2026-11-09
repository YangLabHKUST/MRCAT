# Replication assessment of genetically predicted hexadecanedioate levels and coronary artery disease using a FinnGen outcome

*A two-sample Mendelian randomization report*

## Abstract

In this two-sample Mendelian randomization replication assessment, genetically predicted hexadecanedioate levels showed inverse but null-inclusive associations with coronary artery disease in the original GWAS Catalog outcome (IVW beta -0.00878; 95% CI -0.02049 to 0.00294) and with major coronary heart disease events in FinnGen (IVW beta -0.00856; 95% CI -0.02787 to 0.01074). All six compared method estimates were inverse, but the original nominally significant weighted-median result did not statistically replicate. The FinnGen primary IVW was heterogeneous and materially influenced by one MR-PRESSO outlier. The evidence does not establish a causal protective effect of hexadecanedioate on coronary artery disease.

## Background and objective

Hexadecanedioate is a dicarboxylic acid metabolite for which prior Mendelian randomization studies have reported inverse associations with coronary phenotypes, although the endpoint definitions differ. One study reported a protective role for higher hexadecanedioate in unstable angina pectoris, and another reported an inverse association with coronary heart disease risk. The purpose of the present report is to assess whether previously saved two-sample Mendelian randomization estimates for hexadecanedioate levels on coronary artery disease replicate when the outcome is replaced by a FinnGen major coronary heart disease event endpoint, while preserving the same exposure and analysis methods. [1,2]


## Design, data sources, and quality control

This was a two-sample Mendelian randomization study using the same exposure GWAS, GCST90243839 (hexadecanedioate levels; 6,887 European ancestry individuals; source metadata NCBI36). The original outcome was GCST90132314 (coronary artery disease; 1,165,690 European ancestry individuals; GRCh37). The replication outcome was finngen_R12_I9_CHD (major coronary heart disease event; 500,348 Finnish individuals, 56,650 cases and 443,698 controls; GRCh38). Genetic variants associated with hexadecanedioate levels were used as instruments, so this analysis estimates a genetic-instrument-based relation rather than an experimental intervention.

**Per-study QC inputs and retained variant counts**

| Study | Recorded build | Input variants | Retained variants | Excluded variants | Principal filters |
| --- | --- | --- | --- | --- | --- |
| Exposure GCST90243839 | NCBI36, recorded as unknown | 2,545,171 | 1,026,635 | 1,518,536 | Ambiguous alleles 391,175; MHC 10,448; HapMap reference 1,009,261; allele mismatch 38; MAF below 0.05 107,558; chi-square outliers 56 |
| Original outcome GCST90132314 | GRCh37 | 20,073,070 | 1,096,194 | 18,976,876 | Ambiguous alleles 2,837,114; duplicates 16,051,563; sample-size outliers 3,075; chi-square outliers 3 |
| FinnGen outcome finngen_R12_I9_CHD | GRCh38 | 21,327,062 | 1,056,297 | 20,270,765 | Ambiguous alleles 3,034,718; MHC 50,133; duplicates 832,839; HapMap reference 16,214,000; allele mismatch 37; MAF below 0.05 139,025; chi-square outliers 13 |

After QC, the original pair harmonized 1,020,665 variant rows and LD clumping retained 31 independent instruments; the FinnGen pair harmonized 988,118 variant rows and also retained 31 clumped variants. Clumping used an OpenGWAS API EUR reference and LD score regression used European LD scores. The FinnGen outcome is Finnish ancestry, while the pair-preparation ancestry field was recorded as unknown; this EUR-reference mismatch is a limitation. LDSC genetic correlation estimates were 0.107 for the original pair and 0.196 for the FinnGen pair. Primary MR and BWMR selected instruments at p<=5e-06, yielding 10 SNPs; MR-APSS used all 31 clumped variants with selection-bias correction threshold 5e-05.


## Instrumental variable assumptions and analysis methods

The core instrumental-variable assumptions are relevance, independence, and exclusion restriction. In this design, the selected variants should associate with hexadecanedioate levels, be independent of confounders of the metabolite-coronary disease relation, and affect coronary outcomes only through the exposure. These assumptions cannot be fully verified from summary data.

Primary analyses were IVW, MR-Egger, weighted median, and weighted mode. IVW assumes valid instruments or balanced pleiotropy; MR-Egger permits directional pleiotropy under the InSIDE assumption; weighted median requires valid instruments to contribute a majority of total weight; and weighted mode assumes the largest weighted ratio cluster represents valid instruments. MR-APSS models genome-wide background polygenicity, pleiotropy, and sample structure through C/Omega. BWMR propagates SNP-exposure uncertainty and models small centered horizontal pleiotropy with adaptive weighting.

FinnGen sensitivity analyses included Cochran Q, the MR-Egger intercept, leave-one-out, and MR-PRESSO. Steiger direction was unavailable because the exposure type was not specified as quantitative or binary, and Steiger filtering was not requested. Estimates are on the recorded standardize input scale; outcome coefficients use source beta values and no odds ratios were derived.


## Results

Primary MR estimates are summarized for both branches. All estimates from the four primary methods were inverse, but only the original weighted-median estimate had a confidence interval entirely below the null.

**Primary MR estimates in the original and FinnGen branches**

| Branch | Method | SNPs | Beta | SE | 95% CI | P value |
| --- | --- | --- | --- | --- | --- | --- |
| Original GWAS Catalog | IVW | 10 | -0.008775 | 0.005977 | -0.020490 to 0.002939 | 0.142 |
| Original GWAS Catalog | MR-Egger | 10 | -0.039396 | 0.025349 | -0.097852 to 0.019059 | 0.159 |
| Original GWAS Catalog | Weighted median | 10 | -0.013130 | 0.006209 | -0.025299 to -0.000962 | 0.034 |
| Original GWAS Catalog | Weighted mode | 10 | -0.017527 | 0.018944 | -0.060382 to 0.025328 | 0.379 |
| FinnGen | IVW | 10 | -0.008562 | 0.009850 | -0.027868 to 0.010745 | 0.385 |
| FinnGen | MR-Egger | 10 | -0.041663 | 0.044084 | -0.143320 to 0.059994 | 0.372 |
| FinnGen | Weighted median | 10 | -0.003745 | 0.009178 | -0.021734 to 0.014244 | 0.683 |
| FinnGen | Weighted mode | 10 | -0.004861 | 0.027567 | -0.067222 to 0.057499 | 0.864 |

**Figure 1.** Primary MR scatter plots for the original GWAS Catalog outcome and FinnGen outcome branches.

**Interpretation.** The SNP clouds show broadly inverse fitted relationships, but many SNP-outcome effects are close to zero. The FinnGen branch has a similarly inverse IVW and MR-Egger appearance with wider SNP-outcome uncertainty, consistent with its larger standard errors.

In the FinnGen branch, Cochran Q indicated heterogeneity: IVW Q was 19.57 with 9 degrees of freedom and p=0.021, and MR-Egger Q was 18.21 with 8 degrees of freedom and p=0.020. The MR-Egger intercept was 0.00228 with standard error 0.00295 and p=0.463, so directional pleiotropy was not detected by that test; however, this test has limited power with 10 instruments. Leave-one-out identified rs11045885 as the most influential variant, with a maximum absolute change of 94.18%, an influential_count of 5, and no direction reversal. MR-PRESSO detected global heterogeneity with p=0.018 and one outlier, rs11045885. After outlier correction, the FinnGen primary IVW estimate changed from -0.008562 to -0.000498, with distortion p=0.016. Steiger direction was unavailable because the exposure type was not specified.

**Figure 2.** Leave-one-out and MR-PRESSO outlier evidence for the FinnGen primary IVW analysis.

**Interpretation.** Together these plots show that the FinnGen primary IVW estimate depends materially on rs11045885. The MR-PRESSO correction moves the point estimate from -0.008562 toward -0.000498, supporting caution in interpreting a simple inverse causal effect.

**MR-APSS and BWMR estimates by branch**

| Method | Branch | SNPs | Beta | SE | 95% CI | P value |
| --- | --- | --- | --- | --- | --- | --- |
| MR-APSS | Original | 31 | -0.014855 | 0.009974 | -0.034405 to 0.004694 | 0.136 |
| MR-APSS | FinnGen | 31 | -0.021588 | 0.014778 | -0.050552 to 0.007376 | 0.144 |
| BWMR | Original | 10 | -0.009017 | 0.006216 | -0.021200 to 0.003166 | 0.147 |
| BWMR | FinnGen | 10 | -0.008845 | 0.010234 | -0.028904 to 0.011215 | 0.387 |

MR-APSS used all 31 clumped variants at threshold 5e-05. Its estimates were inverse and null-inclusive in both branches. MR-APSS IVstrength was 0.02895 in the original branch and 0.02871 in the FinnGen branch; this is total modeled IV signal, not per-SNP F. The model estimated pi0 at approximately 0.31 and nvalid at approximately 9.6 in both branches; these are model-based quantities, not validated biological classifications. BWMR used the same 10 instruments as primary MR. The approximate per-SNP F statistics for BWMR ranged from 20.89 to 79.83, with none below 10. Posterior BWMR weights were close to one, with minima near 0.9996 to 0.9998, indicating little extreme downweighting rather than proving that all instruments are valid.

**Figure 3.** MR-APSS result plots for the original GWAS Catalog and FinnGen outcome branches.

**Interpretation.** Both MR-APSS fits use the same 31 clumped variants and estimate inverse slopes with null-inclusive uncertainty. The FinnGen slope is more strongly inverse but also wider, so the two branches are compatible rather than contradictory.

**Figure 4.** BWMR weighted causal fit plots for the original GWAS Catalog and FinnGen outcome branches.

**Interpretation.** Both BWMR fits show inverse causal slopes with near-one posterior weights and confidence intervals that include the null. This indicates that exposure-uncertainty-aware weighting did not produce a strong protective effect estimate in either branch.

The replication summary compared 12 estimates across two branches and six methods. Directional concordance was 1.0: all point estimates were inverse. However, every FinnGen confidence interval included the null, and the original weighted-median nominal finding of p=0.034 was not reproduced. The FinnGen weighted-median estimate was -0.003745 with p=0.683. Therefore, the branches are directionally consistent but the previous nominally significant weighted-median result did not statistically replicate. Different outcome definitions and cohorts also prevent treating this comparison as fully independent replication.

**Figure 5.** Forest matrix comparing all six method estimates between the original GWAS Catalog and FinnGen outcome branches.

**Interpretation.** The forest matrix shows directional consistency alongside wider intervals in the FinnGen branch. The original weighted median was the only interval entirely below the null, and its FinnGen counterpart remained inverse but included the null, so the evidence does not support statistical replication of that finding.


## Discussion

These results provide, at most, weak evidence for an inverse association. The original and FinnGen primary IVW estimates were both null-inclusive, and the only nominally significant estimator in the original branch did not persist. MR-APSS and BWMR remained inverse but null-inclusive. The FinnGen primary IVW model was heterogeneous and sensitive to one MR-PRESSO outlier, so the simple IVW estimate should be interpreted with particular caution. The directionally inverse pattern could be compatible with a small protective effect, but it does not establish one.

Material limitations include the small exposure GWAS of 6,887 individuals and only 10 instruments in the primary and BWMR analyses, although the recorded per-SNP F statistics for BWMR did not flag instruments below 10. No power assessment was supplied. The exposure source was NCBI36 but recorded as unknown after QC, while the two outcome builds were GRCh37 and GRCh38; allele harmonization was performed after QC, but the supplied records do not document a formal liftOver. The FinnGen endpoint is a major coronary heart disease event rather than an exact coronary artery disease definition, and its Finnish ancestry was paired with an EUR LD reference under a pair-ancestry field recorded as unknown. Steiger direction was not assessed. Sensitivity records for the original branch were not supplied for this report, so equivalent original-branch diagnostics could not be compared. Unknown sample overlap further limits independence claims.

The results are specific to the European ancestry exposure cohort and the European or Finnish outcome cohorts used here, and may not generalize to other populations. The recorded QC counts, selection thresholds, instrument counts, and analysis branches are reported to support reproducibility.

### Literature evidence and comparison

A prior MR study reported that higher hexadecanedioate levels had a protective role in unstable angina pectoris, which is directionally consistent with the inverse estimates reported here but does not directly address coronary artery disease overall. A separate MR study reported a significant inverse association between hexadecanedioate and coronary heart disease risk, with an odds ratio of 0.82 and 95% CI 0.72 to 0.93. That published result is not directly comparable to the present estimates because it used a different outcome definition and did not report using FinnGen, and the current report presents beta estimates without odds-ratio conversion. Nevertheless, it highlights that published evidence for this metabolite remains mixed relative to the null FinnGen-based result. [1,2]


## Conclusion

**Conclusion.** In this replication assessment, genetically predicted hexadecanedioate levels showed inverse but null-inclusive associations with coronary artery disease in the original analysis and with major coronary heart disease events in FinnGen. The prior nominally significant weighted-median estimate did not replicate, and the FinnGen primary estimate was heterogeneous and sensitive to one outlier. The current evidence does not establish a causal protective effect of hexadecanedioate on coronary artery disease. Mendelian randomization supports causal hypothesis testing but does not by itself prove causality.


## Reporting information

**Software and preregistration.** Analyses were orchestrated using MRCAT 0.1.0 with Python 3.11.15; R 4.5.3; R packages: MRAPSS 0.0.0.9000, MRMix 0.1.0, MRPRESSO 1.0, MRcML 0.0.0.9000, MendelianRandomization 0.10.0, TwoSampleMR 0.7.6, cause 1.2.0.335, data.table 1.18.6.1, ggplot2 4.0.3, glmnet 5.0, jsonlite 2.0.0, mr.divw 0.1.0, mr.raps 0.4.3, robustbase 0.99.7. Preregistration information was not supplied for this analysis.

**Funding.** Funding information for this analysis was not supplied. The role of any funder was not supplied.

**Data and code availability.** GWAS identifiers and analysis provenance are reported in this document. Public data and code availability were not otherwise specified.

**Conflicts of interest.** Conflict-of-interest information was not supplied.


## References

1. Peng, Mengling; Fu, Yu; Qin, Cong; Shi, Lei; Zhang, Meiwei; Zhou, Shanshan. (2024). A stratified study of human blood metabolites and coronary artery diseases-A Mendelian randomization study.. Nutrition, metabolism, and cardiovascular diseases : NMCD. [doi:10.1016/j.numecd.2024.09.024](https://doi.org/10.1016/j.numecd.2024.09.024)
2. Meng, Xiao-Yan; Zhu, Yong-Qing; Zhang, Ying-Jie; Sun, Wei; Li, Shu-Ang. (2025). Causal relationships between serum metabolites and coronary heart disease risk: a mendelian randomization study.. Frontiers in genetics. [doi:10.3389/fgene.2025.1440364](https://doi.org/10.3389/fgene.2025.1440364)
