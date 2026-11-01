# Two-step MR mediation pathway plot

Each plot represents one mediator, with one aligned row per MR method. The left
forest panel shows the exposure-to-mediator estimate, the middle forest panel
shows the mediator-to-outcome estimate, and the right panel shows the
corresponding mediation proportion. Numeric estimates and 95% confidence
intervals are printed beside their graphical summaries. Color identifies the
MR method consistently across all panels in that mediator's plot.

The component-effect panels use their own causal-effect scales. The mediation
proportion is calculated as the product-of-coefficients indirect effect divided
by the total exposure-to-outcome effect. Its confidence interval uses the delta
method. Product-of-coefficients indirect effects remain available in the TSV
table and structured result record.

Uncertainty assumes zero covariance among component estimates. Interpret each
mediator separately; do not sum correlated mediator-specific indirect effects
or treat them as jointly adjusted.
