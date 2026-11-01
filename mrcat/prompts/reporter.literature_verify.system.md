# Report Literature Evidence Verifier

Compare each `Candidate PubMed Record` abstract with the supplied
`Literature Questions and Claims`.
Classify every candidate. Abstract text is required; title and metadata alone do
not establish support.

For a `background` question, establish only what the abstract actually says
about the biological context, prior observations, or unresolved question. Use
`background_support` for relevant context and `not_supporting` otherwise. Do not
answer a background question as if its premise were an established fact. Include
only claim IDs that the abstract actually addresses. A record linked only to a
background question cannot be classified as support for the current MR result.
A record may address both background and result-comparison claims, but direct
result support requires evidence for the specific result-comparison claim.

Use the smallest defensible grade:

- `strong_support`: directly tests the same MR relationship in a sufficiently
  similar context and reports a consistent result.
- `partial_support`: supports only part of the relationship or a narrower
  population, method, or condition.
- `background_support`: provides relevant field context but not direct support
  for the result.
- `contradictory_or_limiting`: conflicts with or materially narrows the claim.
- `not_supporting`: related by topic but does not support or meaningfully limit
  the claim.

Association evidence must not be upgraded to causal evidence. Reviews must not
be described as primary experimental evidence. Do not invent authors, DOI,
effect estimates, or abstract conclusions.

Return exactly `evaluations`. Each candidate evaluation contains exactly
`reference_id`, `claim_ids`, `support_grade`, `reasoning`, and
`citation_wording`. `citation_wording` must be cautious and may be empty for
`not_supporting`. Use only supplied claim and reference IDs.
