# Session event traces

Each new session automatically saves `trace.jsonl` beside `graph.sqlite`.
Every line is one JSON event. Continuing a conversation appends to the same
file. Checkpoints remain the only workflow state; the agent never uses the
trace to plan, restore state, or decide what to execute.

Events include user and assistant messages, application-level model inputs and
returns (including errors and usage), Plan/Review and memory events, native
coding-tool records, executed code, full saved stdout/stderr, result bindings
and final reports. Saved Skill code-generation prompts/code, QC explanations
and aggregate model usage are also retained. Dataset and binary artifact contents remain in their files.
Credential values are redacted. Source hashes refer to the original bytes.

## Reconstruct an existing conversation

Run from the project directory with its Python environment:

```bash
python -m mrcat.trace /absolute/path/to/session_SESSION
```

Multiple session paths are accepted. For example:

```bash
python -m mrcat.trace runtime_benchmark/BATCH/Q0*/session_*
```

The command reads saved checkpoints, model-call files, executions, registered
results and reports. It writes only `trace.jsonl` and `.trace.lock`; it never
calls a model or reruns an analysis. Finish or stop a session before exporting
it. If a trace already exists, the command leaves it unchanged. Linked views
are read-only; use the original session directory or fork it.

An old conversation without a trace is reconstructed automatically before its
next agent turn. A fork starts a new trace from its inherited evidence rather
than copying a trace with the original session ID.

## Record fields

- `schema_version`: format version, currently 1.
- `session_id`, `seq`, `event_id`, `type`: session, consecutive sequence,
  stable record identity and event kind.
- `timestamp`: observed event time; null when the historical time is unknown.
- `capture_mode`: `live` or `reconstructed`, on each individual record.
- `parent_id`: related turn, model call, execution or native call when known.
- `source`: relative source path and original SHA-256, or checkpoint ID,
  namespace and field. Available checkpoint/file times are included here.
- `data`: original recorded content, with credential values redacted.

Historical order uses recorded event times, first checkpoint appearances, and
file modification times as available. It is a presentation order, not proof of
precise timing. Copying artifacts may change modification times. Known request
and result relationships take precedence over those ordering hints. Repeated
checkpoint copies of the same messages/events are deduplicated; changed
historical message versions are retained.

## Capture boundary and interruptions

The trace observes existing calls through `Agent._call`. Skill-internal calls
are represented by their saved artifacts and aggregate usage; they may lack
separate request/response events. The aggregate call count therefore need not
equal the number of `llm_start` events. It does not intercept SDK
internals and does not change API retry, output limits, prompts, agent routing,
Review decisions or execution behavior. Missing historical thinking fields,
intermediate API attempts and unsaved responses cannot be reconstructed.

Writers lock per session and flush each event. Execution output is captured at
completion rather than once per progress refresh. An interrupted operation can
have a start event without an end event; inspect its saved files. On append,
an incomplete final JSON line left by a killed writer is removed and an
explicit `trace_repaired` event records the discarded byte count. A malformed
complete line is reported, not silently discarded.

Trace write failures produce warnings and do not change the agent's result.
The trace is an evidence projection, not a recovery mechanism. Full raw
provider transcripts and per-SDK-attempt accounting are outside this version.
