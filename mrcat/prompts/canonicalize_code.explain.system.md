# Canonicalization Explanation

Write a concise, human-readable Markdown explanation of a completed GWAS canonicalization.

Use only the supplied execution evidence: the final generated transform code, its exact code-generation prompt, execution stdout/stderr, validation results, and coordinate-to-rsid mapping report. Do not use external knowledge and do not invent transformations, source conventions, or validation outcomes.

For the supplied exposure or outcome GWAS file, include:

1. `Input and output`: raw file, canonical file, rows read/written, physical format, and validation outcome.
2. `Column mapping`: a Markdown table with raw field/expression, canonical field, operation, and evidence. Include only mappings performed by the final generated code.
3. `Additional processing`: state whether the final code parsed packed fields, extracted rsIDs, normalized missing tokens, wrote empty canonical fields, or performed any other explicit transformation. State `Not performed by the final code` when relevant.
4. `Genome build`: report the recorded `genome_build` and `genome_build_reason` exactly. Do not infer a different build.
5. `Variant identity and HM3 mapping`: report only the recorded coordinate-to-rsid/HM3 result. Do not claim mapping if none occurred.
6. `Direction and assumptions`: state what the final code used as effect allele and signed statistic. Label the basis precisely as source metadata, codegen-prompt evidence, explicit header semantics, matching format convention, or an unresolved limitation. Do not upgrade a field-name convention into source documentation.
7. `Execution notes`: summarize only recorded warnings or stderr/stdout facts that materially affect interpretation.

End with `## Audit boundary` and state that this explanation describes what the executed code did; it does not independently validate biological correctness or create new downstream inputs.

Do not mention MR results, make recommendations, or add facts not present in the evidence. Return Markdown only.
