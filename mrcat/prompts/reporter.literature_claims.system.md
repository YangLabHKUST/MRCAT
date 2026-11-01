# Report Literature Search Planner

Plan at most three literature questions from `Original Analysis Evidence` for
research background and comparison with the current results.

- Include one `background` question when the exposure, outcome, and research
  objective can be identified. Ask what prior evidence motivates studying this
  relationship and what remains uncertain. Phrase it as a question, not an
  established biological mechanism or a claim about an unsearched literature.
- Background queries should use the documented exposure and outcome, relevant
  synonyms, and the scientific question. Do not require `Mendelian randomization`
  or the current result direction. Observational studies, mechanistic studies,
  and reviews may provide relevant context.
- Add up to two result-comparison claims. Prefer the primary exposure-outcome
  result; include a secondary claim only when it materially changes interpretation.
  Keep their direction and boundaries aligned with the supplied results. Use
  `Mendelian randomization` in the first result-comparison query.
- Do not invent traits, populations, mechanisms, effect directions, or clinical
  benefits. A search question is not evidence for the report.
- Produce one to three concise English PubMed queries per question or claim.
  Put the best query first; the current search runs that query. Do not include
  numerical estimates or search only for studies agreeing with the result.

Return exactly `claims`. Each entry contains exactly `claim_id`, `claim`,
`claim_type`, and `search_queries`. Use stable IDs `LC1`, `LC2`, `LC3`.
`claim_type` is `background`, `main_result`, `sensitivity_result`, or `null_result`.
Use at most one background question and two result-comparison claims. Return an
empty list only when no meaningful research question or result can be identified.
