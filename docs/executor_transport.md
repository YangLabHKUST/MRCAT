# Executable reply contract

A Search or selected-Skill Executor reply contains one final Python, R or Bash fenced code block, or one
role-appropriate control action. A single code block can contain multiple steps,
tool calls and custom code. Use a longer outer fence when the source contains
literal Markdown fences.

The runtime rejects multiple code blocks before running any of them. It does not
concatenate drafts and replacements or assume the last block is sufficient.
One focused format-repair call receives only the rejected reply, the parsing
error and the role. The repair must preserve required setup, inputs and intended
operations. If the intended version is ambiguous, it returns `UNRECOVERABLE`.
An invalid repair or this marker pauses the work, preserves prior outputs and
does not invoke Evaluate or change the Plan. The saved model replies and
`action_rejected` observations retain the diagnostics.

For OpenAI-compatible Chat Completions responses, both SDK and HTTP transports
use only the first choice's `message.content`. Other choices are alternatives,
not subsequent program fragments. Truncation is checked for the same selected
choice. An empty selected choice is not replaced by a different candidate.
`reasoning_content` is not executable input. Thinking configuration is unchanged.

This contract prevents the observed two-block draft/replacement failure. It does
not prove that operations inside a single block are nonduplicative or
scientifically correct. It does not introduce persistent Python variables across
cells; saved results and `$ref` continue to provide cross-cell reuse.

Regression coverage is in `tests/test_action_transport.py` and
`tests/test_model_limits.py`. The archived QC reply is retained as a parser
fixture, with its opaque result ID anonymized. Tests never run that QC call.

Custom items use the coding tool protocol described in `custom_codeact.md`.
The `run` tool passes the exact submitted source to the same CodeExecutor.
Selected-Skill items advance on the saved tool output; custom items use
the native `finish` tool after successful execution and execution-linked publication, then enter Review.
Review's `execute`/`accept_item` determines repair versus advancement; `replan`
and `finalize` remain separate outcomes.

Failed Skill items return to Review after each attempt. The host honors its
repair decision without a fixed per-item review-count cutoff. Review must use
execution evidence to distinguish progress (such as a resumable download) from
an exhausted repair. The overall action budget, plan-recovery budget, explicit
stops and technical Review failures still bound execution.
