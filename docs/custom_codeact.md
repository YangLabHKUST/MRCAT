# Custom coding and scientific Review

Every Plan item with `skill_id=null` uses `CodingAgentNodes`. Selected-Skill
items keep the validated Skill call path. There is no alternate Custom CodeAct
implementation or opt-in flag.

The coding loop supports list/read/grep, write/edit, docs, run, publish,
and finish. Each response may contain multiple native function/tool calls. Calls execute in order;
all results are returned before the next model request, paired with their original
call IDs. Use `finish` alone after inspecting the results. History compaction keeps
whole turns together, and interruption settles queued calls without replaying them. Each provider
call ID, original arguments and actual tool result are replayed as assistant/tool
messages. Prose is never parsed as an executable action; the former text-JSON
format-repair call has been removed. Tool and execution nodes
save their results before returning to the model. Files and saved observations
carry state between processes; Python variables do not persist between runs.
DeepSeek coding requests enable thinking and use `tool_choice="auto"`; the API
rejects forced tool choice in thinking mode. A response without native calls
pauses the item rather than executing prose or marking the analysis complete.
The native assistant message retains
`reasoning_content` through checkpoints and tool-result replay, as required by
DeepSeek's thinking tool-call protocol. Older non-thinking turns send an empty
reasoning field; their original saved messages remain unchanged. Review and
memory-summary requests retain their separate structured-decision settings.

Python, R and Bash execute in the item's workspace directory. Runtime cwd and
Bash `errexit`/`pipefail` options are separate from submitted source; archived
source is preserved verbatim.

## Runtime dependencies

The actual interpreter and import/load checks take precedence over inventory
notes. Custom runs prepend item-local R and Python dependency directories while
preserving existing library paths. Install R packages with the explicit local
`lib`, or Python packages with `pip --target`; do not alter the shared environment.
An import failure calls for a supported repair and verification, not repeated
whole-disk searches. Failed installation or unavailable network access must be
reported with the actual error. File tools constrain writes; arbitrary executed
code still runs under the server account and is not a security sandbox.

## Context and memory

The executor receives the current item, plan directory, upstream references,
user constraints, its own working summary and continuous unsummarized tool turns.
The host assembles this context automatically; there is no session-history tool.
For earlier evidence the executor reads specific scripts, results and logs using
the exact paths retained in its summary and latest execution state. Historical
history-tool entries remain in checkpoints but are excluded from model replay
and summary input, so nested query results cannot re-enter the working context.
Its summary belongs to one task/item in `task.coding[step_id].summary`; it does
not write the MR task memory. MR memory projects the task request, accepted plan
items, result references and pending items from host state. Executor handoffs
remain explicitly distinguished from scientific acceptance by Review.

The executor summary records objective, decisions, completed work, active work,
blockers, next steps and references. The latest actual run and its log paths are
projected separately from the journal, so a summary claim cannot overwrite the
recorded execution status. Saved scripts, logs and complete journal entries stay
available. Identical read observations appear in full only at their latest turn
in the model view; earlier copies point to that turn. Saved evidence is unchanged.

The budget counts system instructions, serialized context and tool schemas,
with output and safety reserves. `MRCAT_CONTEXT_TOKENS` defaults to 131072;
`MRCAT_MODEL_CONTEXT_TOKENS` supplies exact model-name overrides. These are
configured capacities, not capacities discovered from the provider. Estimates
are conservative approximations; provider usage records measured consumption.

Summary starts near 85% of the available input budget and aims for 60%. It
summarizes complete older entries while retaining the latest entry. Only a
schema-valid summary that reduces context advances the cursor; this check does
not establish factual correctness. A failed summary retains history; requests
exceeding the hard input budget pause instead of discarding evidence. An older
checkpoint with a compaction cursor adopts its existing task note once as the
executor summary, preserving its old history and cursor for continuation.

SQLite is authoritative. Explicit session export writes MR `memory.md` and
`workspace/outputs/<task>/<item>/executor_memory.md` as readable projections.
Editing either Markdown export does not update the checkpoint.

## Budgets, recovery and completion

`MRCAT_MAX_ROUNDS` defaults to 300 actions per user turn and applies to Search,
selected-Skill execution and custom coding. Continuation renews the allowance.
Inspection runs are capped at 30 seconds, dependency repair runs at 300 seconds,
and compute runs at the configured execution timeout.

There is no cumulative inspection-count limit. For read/list/grep/docs,
the host compares tool arguments and returned observations across turns. Two
identical cycles of one to five actions produce feedback after the tool history;
a third pauses with all work preserved. Different arguments, changed results or
an intervening edit/run break that cycle. Continuation preserves the journal and
feedback while allowing another approach. This detects exact read cycles, not
all forms of semantic repetition or all nonproductive executions.

Three identical execution failures also pause without invoking scientific Review.
These are resource guards, not measures of scientific progress. The model supplies
each run's purpose; this classification is not an independent assessment. Budget
exhaustion, transport failures and `technical_blocked` pause without asking Review
to debug code.

`publish(name, path, execution_id)` loads a small JSON object produced by a
successful run in the current item. Its recorded SHA-256 must still match; the
publication points to that execution's source and observation. It does not accept
model-authored numerical values as tool arguments. Python scripts may instead
call `mrcat.tools.publish_result` during execution. Completion requires a
publication linked to a successful run, and the latest run must also have
succeeded. A process exit or publication alone does not establish scientific
validity.
Review then checks inputs, assumptions, scope and support for conclusions.
`blocked` hands off a scientific obstacle or essential missing information.
Execution checks alone do not establish scientific validity.

Session state, coding journals and summary cursors are checkpointed in
`graph.sqlite`. Source, logs, result files and action receipts remain separate
artifacts. Stable operation IDs prevent replay of a completed operation during
recovery; a newly requested operation is not automatically deduplicated.

## Validation

`tests/test_native_coding.py` covers native provider transports, rejected calls,
distinct inspections, local dependency settings and execution-backed publication.
`tests/test_coding_graph.py` covers local tool execution, interrupted receipt
recovery, 300 actions, pause, and continuation. `tests/test_context_budget.py`
covers continuous history, summary thresholds, failed summaries and whole-request
budgets. `tests/test_executor_memory.py` covers memory ownership, cycle detection,
model-view deduplication, exports and continuation. `tests/test_custom_codeact.py` covers execution evidence and Review.

The October 19 continuity experiment under
`runtime_artifacts/codeact_continuity_validation_20261019` describes the previous
implementation. The current real-model validation is under
`runtime_artifacts/runtime_refactor_validation`; it uses synthetic data and is
engineering validation, not a GWAS benchmark score.


## Investigation before method-specific planning

When no compatible Skill or accepted investigation establishes a requested
method's input requirements, Planner ends the initial acquisition/QC checklist
with a custom investigation. The executor checks authoritative method sources and
actual data and publishes the findings through the existing run/publication path.
Review receives the current published payloads; Planner receives completed
result payloads through the existing reference resolver. These are compact views
of saved evidence, not new scientific schemas. Review accepts evidence appropriate
to that item; it does not require a fit yet.
`route=replan, accept_item=true` saves the completed item and its references before
calling Planner. This transition does not consume the failed-recovery budget;
ordinary action limits and unsuccessful-recovery limits still apply. A pending
replan is checkpointed, so a Planner failure can resume without repeating the
investigation or mistaking its completion for completion of the whole analysis.

Planner then chooses compatible shared pair preparation or method-specific
preparation from QC. Shared preparation defaults to a 5e-5 initial IV ceiling,
not a universal estimator cutoff. Final selection follows the target method,
including selection performed by its wrapper; actual thresholds, LD and scale
must be checked. Filtering cannot undo upstream SNP loss. Accepted investigations
are reusable evidence, not completed MR estimates. Known compatible Skills keep
their direct workflows. No plan-item fields or method-name routing table are added.
