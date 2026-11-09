# Final result delivery

MR Finalize keeps its existing completed/blocked response and end marker. The
runtime now also supplies `result_sources`, read from the active task's saved
method records and custom published outputs. Explicitly referenced historical
tasks can be included. It does not scan unrelated sessions or use handoff prose
to create results.

When sources are present, the model selects the relevant source and writes
qualitative interpretation. Numerical delivery uses two references:

- `{{table:r1}}` inserts the saved methods table (or a generic custom-output table).
- `{{value:r1/methods/0/pval}}` inserts that specific saved scalar, without rounding
  or recomputation. Field paths use JSON Pointer escaping.

Source IDs are local to the supplied catalog. Unknown sources, missing fields,
unreadable records, and literal numerical claims are rejected before the summary
is saved. Finalize gets one correction attempt; a persistent failure pauses only
delivery and preserves the computation. Markdown link destinations and numbered
list labels are not statistical claims. Work without structured result sources
retains ordinary textual delivery; it does not gain this numerical guarantee.

Custom `publish_result()` outputs need no registered skill or fixed MR schema.
They remain marked unverified: publication and faithful rendering do not certify
the computation, method assumptions, or surrounding scientific interpretation.
Model selection of the correct source and qualitative conclusions still require
evidence-based review. This is not a general proof of scientific correctness.

For `standardize`, `Z/sqrt(N)` and `1/sqrt(N)` describe the input SNP-trait
associations and their standard errors. The fitted MR slope, its standard error,
and its confidence interval come from the estimator. These input formulas must
not be presented as formulas or units for the final MR slope or its SE. Numerical
fitting, QC, clumping, and existing result records are unchanged.
