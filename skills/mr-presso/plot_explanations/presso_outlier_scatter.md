# MR-PRESSO outlier scatter

This plot places each selected SNP's exposure effect on the x-axis and outcome
effect on the y-axis. Error bars show 95% intervals. Orange points are SNPs
flagged by MR-PRESSO's outlier test; dark points are not flagged.

The solid dark line is the raw estimate. When MR-PRESSO returns a corrected
estimate, the dashed blue line shows the estimate after removing detected
outliers. A visible slope change indicates sensitivity to those variants.

Do not infer the causal conclusion from this plot alone. Interpret it together
with the complete raw and corrected estimates, global-test P value, outlier
count and identities, distortion-test P value, selected instrument count, and
the prespecified results from other MR methods.
