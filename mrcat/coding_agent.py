"""Explicit LangGraph coding executor for custom MR items.

Tool history and budgets live in the checkpointed task. Workspace scripts and
execution observations remain evidence files. Model and tools are separate nodes.
"""
from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

from . import memory
from .codeact import CodeActNodes
from .coding_protocol import (CODING_TOOLS, coding_call, coding_calls, coding_history, coding_turns, failed, redirected_logs,
                              loop_feedback, render_executor_summary)
from .diagnostics import redact
from .execution import runtime_context
from .plan_items import current_item, executor_view
from .results import _publish, result_catalog, work_scope
from .store import write_json

PROVIDER_ENV = "MRCAT_CODING_AGENT_PROVIDER"
DEFAULT_PROVIDER = "deepseek"
OUTPUT_LIMIT = 16000
READ_LIMIT = 12000
GREP_LIMIT = 120
FILE_LIMIT = 2_000_000

SYSTEM = """\
You are a coding agent working inside one MRCAT MR plan item whose skill_id is
null. You own the code, the debugging and the runtime verification; Review owns
the scientific judgement. You are not the final report writer.

You may request multiple native tools in one turn. The host executes them in order
and returns every result before your next turn. Wait for results before choosing
calls that depend on them. Use finish alone, after inspecting the tool results.
Optional prose is commentary, never code to execute. Use write/edit to maintain
scripts, run to execute them, and finish to hand off.

How the workspace behaves:
- context.workdir is your working directory. New files go there. Use paths
  relative to it; you may read anywhere under context.workspace, which is the
  session workspace holding the outputs of earlier items.
- Upstream results are listed in context.upstream_results with saved references.
  Resolve $ref values using mrcat.tools.resolve_ref in a run. Read those files directly; do not search the disk for
  them and do not use files from unrelated sessions.
- Shared reference data (LD scores, PLINK references, HapMap SNP lists) comes
  from mrcat.database.database_resource_ids(). Resolve a resource ID with
  `from mrcat.database import database; database(resource_id)`, which returns a
  validated absolute path. Use those paths instead of guessing directories.
- context.method_docs indexes notes about the shared reference data that sit
  beside the database: what files exist, their structure, and installed
  versions. Read one with docs(id). Installation notes can be stale: a real
  import/load check in context.runtime is authoritative. It contains no workflow;
  the method's usage contract must still be established from the installed
  package. The docs tool also accepts an installed Skill ID to read its guide.
- Read a file before editing it. `edit` replaces one exact occurrence, so quote a
  unique section and change only the defective part.
- `run` executes a saved file when `path` is given, otherwise the inline
  `content`. Large data files (over about 2 MB) cannot be read whole: use
  `read` with `start`/`end` or `grep` to inspect only the region you need.
  The host makes your work directory the current directory of every
  python, r and bash run, so relative paths inside a script resolve there.
  Interpreters come from context.runtime. For a saved script that takes CLI
  arguments, use `run` with bash and invoke the interpreter directly, e.g.
  run(language="bash", purpose="compute", content="<interpreter> script.R arg1 arg2").
  Bash runs under errexit/pipefail.
- A nonzero exit is a real failure. Read stderr, fix the cause, run again.
  Exception: exit 141 is SIGPIPE from a closed pipe (`... | head`). Do not pipe
  potentially large listings through head or sed -n under errexit/pipefail; write
  to a file and read a range instead.
- Every run is saved as executions/<id>/. Its log paths are in the next
  context message and the full text is on disk.

How to work:
- Execute only the current item. A method-requirements investigation is a useful
  completed item: inspect authoritative documentation/package code and the actual
  QC data, then run a script that saves a small evidence-backed JSON result.
  Record source URLs or package version/source locations, required fields and
  effect scales, variant selection and LD rules, extra resources, and whether
  gwas-pair-prepare or an existing prepared pair is compatible (with reasons).
  Print the decisive evidence and include it and the saved reference in the finish
  handoff so Review can assess it. Publish the investigation, then finish complete;
  do not prepare inputs or fit later items. Unresolved requirements remain unknown.
- For preparation/estimation items, build the smallest thing that can run:
  prepare inputs, run the fit, inspect the output. Follow accepted investigation
  results without repeating the investigation unless new evidence contradicts them.
- Shared gwas-pair-prepare defaults to an initial IV P-value ceiling of 5e-5 and
  LD clumping; inspect the actual saved settings, ancestry/build and effect scale.
  Apply the target method's documented final IV selection exactly once (including
  selection already performed by its wrapper), and record the effective threshold
  and SNP count. Further filtering cannot recover discarded variants or undo
  clumping. Incompatible selection/LD/scale requirements need suitable upstream
  preparation, not relaxed checks. Some methods fit the complete prepared set;
  do not impose an additional cutoff on them or overwrite correction thresholds.
- Verify with evidence, not with an exit code: read the produced file, check row
  and column names, compare magnitudes with what the method should give.
- The host supplies your working summary and recent tool turns automatically.
  For earlier evidence, use read/grep on the exact script, result or log paths
  in that summary or context.execution_state; do not browse the session transcript.
- Use `list` to inspect workspace files and `docs` to read a method note on demand.
- Reference resources are available through mrcat.database.database_resource_ids() and database(id) in a run.
- Have the computation write a small JSON object of reusable outputs. Then use
  publish(name, path, execution_id) with its successful run ID. The host verifies
  that the JSON file was produced by that run and has not changed. Python code
  can also import mrcat.tools.publish_result and publish inside the computation.
- Label runs honestly: inspect reads/probes existing state, repair changes a
  diagnosed dependency or implementation, compute executes the requested analysis.
  Inspection runs have a 30-second ceiling; repair runs have a 300-second ceiling.
  Read as much distinct evidence as the task needs. Repeated identical
  observations are not progress: two matching inspection cycles trigger feedback,
  and a third pauses the turn. Use the evidence to test a concrete hypothesis.
- context.executor_memory is the working summary of this plan item, not the MR
  task's scientific memory. The host maintains it from this item's saved turns.
  context.execution_state reports the latest actual run; its evidence overrides
  any claim in the summary. The current request, plan, user updates and Review
  feedback remain authoritative even when the summary describes an earlier plan.
- Preserve useful decisions in your commentary as you work, then act on them.
  A planned command is not an executed command. Finish by submitting evidence or
  a specific obstacle; only MR and Review can accept scientific progress.
- If an import fails, check the actual interpreter and its library paths once.
  Use the package's supported source to install into context.runtime.local_dependencies
  (R install.packages(lib=r_library), Python pip install --target python_target)
  and verify the import and version. Do not repeatedly search unrelated sessions,
  /tmp, the home directory, or the entire filesystem for a missing package.
  A verified network/permission/dependency failure is a technical obstacle;
  include the attempted repair and actual verification outcome when finishing.
- `finish complete` is host-checked: it is refused unless this item already has a
  successful run and a published result. After it succeeds the item goes to
  Review, which may return it for specific scientific evidence.
- When an interface is uncertain, inspect it: read the installed package source,
  read a small input sample, or run a tiny call before the expensive one. Do not
  guess argument names or column mappings.
- Repair one identified cause per turn and rerun the smallest check that proves
  it. Repeated identical failures need a different approach, not another retry.
- Preserve the user's explicit studies, phenotype, ancestry, method, scale and
  thresholds. If an upstream producer is invalid, finish blocked and name it.
- Do not create skill packages, edit installed packages, or write outside your
  work directory. Do not print credentials.
"""

def _preview(text, limit=OUTPUT_LIMIT):
    text = redact(text or '')
    if len(text) <= limit:
        return text
    marker = '\n[excerpt: middle omitted; read the saved log for the full output]\n'
    budget = limit - len(marker)
    return text[:budget * 2 // 3] + marker + text[-budget // 3:]




def _agent_provider():
    """Provider for the coding agent's own model calls.

    MRCAT_CODING_AGENT_PROVIDER wins. Otherwise this returns the process
    default; the test harness sets it explicitly.
    """
    explicit = os.environ.get(PROVIDER_ENV, '').strip().lower()
    if explicit:
        return explicit
    default = os.environ.get('LLM_PROVIDER', '').strip().lower()
    return default or DEFAULT_PROVIDER


class _provider_scope:
    """Route only this module's model calls through its provider.

    The gateway reads LLM_PROVIDER before config.yaml, and every MRCAT role
    shares one process, so the override exists only for the duration of one
    coding-agent call and is restored under a lock.
    """

    _lock = threading.Lock()

    def __enter__(self):
        _provider_scope._lock.acquire()
        self._previous = os.environ.get('LLM_PROVIDER')
        os.environ['LLM_PROVIDER'] = _agent_provider()
        return self

    def __exit__(self, *exc):
        if self._previous is None:
            os.environ.pop('LLM_PROVIDER', None)
        else:
            os.environ['LLM_PROVIDER'] = self._previous
        _provider_scope._lock.release()
        return False


class CodingAgentNodes(CodeActNodes):
    """Custom-item executor backed by a persistent, tool-using coding loop."""

    strict_bash = True

    # ---- paths, journal ----------------------------------------------------

    def _workdir(self, state, task, item):
        directory = self.agent.store.directory(state['session_id'])
        workdir = directory / 'workspace' / 'outputs' / task['task_id'] / item['step_id']
        workdir.mkdir(parents=True, exist_ok=True)
        return directory, workdir

    @staticmethod
    def _journal(task, item):
        journal = task.setdefault('coding', {}).setdefault(item['step_id'], dict(step=0, entries=[]))
        if 'summary' not in journal:
            # Adopt the only available summary from an older checkpoint once.
            # Keep the original task note intact; never discard compacted evidence.
            journal['summary'] = task.get('memory', '') if journal.get('summary_upto', 0) else ''
        return journal

    @staticmethod
    def _inside(root, path):
        root = Path(root).resolve()
        path = Path(path).resolve()
        return path == root or path.is_relative_to(root)

    def _readable(self, session, workdir, value):
        """Reads resolve against the work directory, then the session; writes never do."""
        if value and Path(value).is_absolute():
            candidate = Path(value)
        else:
            candidate = (workdir / value) if value else workdir
            if not candidate.exists():
                alternate = (session / value) if value else session
                if alternate.exists():
                    candidate = alternate
        candidate = candidate.resolve()
        # Absolute reads are unrestricted: the work happens under the same user
        # account and shared reference data (database/, /tmp) is legitimately
        # outside the session. Only writes are confined to the work directory.
        if Path(value).is_absolute() if value else False:
            return candidate
        if self._inside(workdir, candidate) or self._inside(session, candidate):
            return candidate
        raise ValueError(f'Path is outside the session: {value}')

    def _writable(self, workdir, value):
        if not value:
            raise ValueError('A relative path inside the work directory is required')
        candidate = (workdir / value).resolve()
        if not self._inside(workdir, candidate):
            raise ValueError(f'Writes stay inside the item work directory: {value}')
        return candidate

    # ---- the node ----------------------------------------------------------

    def role(self, flow, state):
        task = state['active_task']
        item = current_item(task)
        directory, workdir = self._workdir(state, task, item)
        journal = self._journal(task, item)
        budget = self.agent.max_rounds - flow['rounds']
        update = dict(rounds=flow['rounds'] + 1, review_reason='')

        try:
            with _provider_scope():
                context = self._context(state, task, item, workdir, journal, budget)
                feedback = flow.get('review_reason') or loop_feedback(journal['entries'])['review_reason']
                if feedback:
                    context['execution_feedback'] = feedback
                raw = self.agent._call(state, 'mr', SYSTEM, json.dumps(context, ensure_ascii=False), tools=CODING_TOOLS)
        except (RuntimeError, ValueError) as exc:
            reason = f'Coding model request failed: {type(exc).__name__}: {redact(str(exc))}'
            self.agent._record(state, 'observation', json.dumps(dict(type='coding_model_failed',
                error=reason, diagnostic=getattr(exc, 'mrcat_diagnostic', None))))
            return update | dict(next_node='context', coding_stop=True, review_reason=reason)
        self.agent._record(state, 'assistant', raw)
        try:
            message = json.loads(raw)
            calls = coding_calls(message)
        except (ValueError, KeyError, TypeError) as exc:
            journal['step'] += 1
            self._append(journal, dict(step=journal['step'], tool='invalid_call',
                                      result=dict(ok=False, error=str(exc))))
            return update | dict(next_node='context', format_errors=flow.get('format_errors', 0) + 1,
                                 review_reason='Native tool envelope was rejected; no action was executed.')
        journal['pending_turn'] = dict(message=message, index=0, start=len(journal['entries']),
                                       action_ids=[uuid4().hex for _ in calls])
        if message.get('content'):
            self.agent._event(state, 'assistant_message', message['content'])
        return update | self.dispatch(state)

    def dispatch(self, state):
        """Dispatch the next saved call; the model runs only after the entire turn."""
        task = state['active_task']
        journal = self._journal(task, current_item(task))
        pending = journal.get('pending_turn')
        if not pending:
            return None
        calls = pending['message']['tool_calls']
        if pending['index'] == len(calls):
            journal.pop('pending_turn')
            return None
        try:
            call = coding_call(calls[pending['index']])
            if call['tool'] == 'finish' and len(calls) != 1:
                raise ValueError('Use finish alone in a new turn after inspecting all tool results.')
        except (ValueError, KeyError, TypeError) as exc:
            call = dict(tool='invalid_call', error=str(exc))
        return dict(coding_call=call, coding_action_id=pending['action_ids'][pending['index']], next_node='tools')

    def cancel_pending(self, state, reason):
        """Settle interrupted calls without replaying code or filesystem effects."""
        tasks = [*state.get('task_history', []), *([state['active_task']] if state.get('active_task') else [])]
        for task in tasks:
            for journal in task.get('coding', {}).values():
                journal.pop('pending_call', None)
                pending = journal.get('pending_turn')
                if not pending:
                    continue
                calls = pending['message']['tool_calls']
                ids = {call['id'] for call in calls}
                for entry in journal['entries'][pending['start']:]:
                    if entry.get('call_id') in ids and (entry.get('result') or {}).get('ok') is None:
                        entry['result'] = dict(entry.get('result') or {}, ok=False, error=reason,
                                               interrupted=True)
                while pending['index'] < len(calls):
                    call = calls[pending['index']]
                    journal['step'] += 1
                    self._append(journal, dict(step=journal['step'], tool=call['function']['name'],
                        result=dict(ok=False, error=reason, executed=False)))
                journal.pop('pending_turn', None)

    def tools(self, flow, state):
        task = state['active_task']
        item = current_item(task)
        directory, workdir = self._workdir(state, task, item)
        journal = self._journal(task, item)
        call = flow['coding_call']
        update = dict(coding_call={}, coding_stop=False, review_reason='', format_errors=0)
        journal['step'] += 1
        step = journal['step']

        if call['tool'] == 'invalid_call':
            self._append(journal, dict(step=step, tool='invalid_call', result=dict(ok=False, error=call['error'])))
            return update | dict(next_node='context', format_errors=flow.get('format_errors', 0) + 1,
                                 review_reason='Native tool arguments were rejected; no action was executed.')
        if call['tool'] == 'finish':
            try:
                return self._finish(state, task, item, directory, workdir, journal, call, update, step)
            except ValueError as exc:
                result = dict(ok=False, error=f'{type(exc).__name__}: {exc}')
                self._append(journal, dict(step=step, tool='finish', arguments=self._brief(call), result=result))
                self.agent._record(state, 'observation', json.dumps(
                    dict(type='coding_agent_tool', tool='finish', result=result), ensure_ascii=False))
                return update | dict(action=dict(kind='context', body='', language='python', message=''),
                                     next_node='context')
        if call['tool'] == 'run':
            try:
                return self._run(task, workdir, journal, call, update, step, flow['coding_action_id'])
            except (OSError, ValueError) as exc:
                result = dict(ok=False, error=f'{type(exc).__name__}: {exc}')
                self._append(journal, dict(step=step, tool='run', arguments=self._brief(call), result=result))
                self.agent._record(state, 'observation', json.dumps(
                    dict(type='coding_agent_tool', tool='run', result=result), ensure_ascii=False))
                return update | dict(action=dict(kind='context', body='', language='python', message=''),
                                     next_node='context')

        try:
            result = self._host_tool_once(state, task, directory, workdir, call, flow['coding_action_id'])
        except (OSError, ValueError) as exc:
            result = dict(ok=False, error=f'{type(exc).__name__}: {exc}')
        self._append(journal, dict(step=step, tool=call['tool'], arguments=self._brief(call), result=result))
        self.agent._record(state, 'observation', json.dumps(
            dict(type='coding_agent_tool', tool=call['tool'], result=result), ensure_ascii=False))
        return update | loop_feedback(journal['entries']) | dict(
            action=dict(kind='context', body='', language='python', message=''), next_node='context')

    @staticmethod
    def _brief(call):
        return dict(call)

    def _host_tool_once(self, state, task, directory, workdir, call, action_id):
        """Receipts guard filesystem/publication effects across node replay."""
        if call['tool'] not in {'write', 'edit', 'publish'}:
            return self._host_tool(state, task, directory, workdir, call)
        receipt = workdir / '.coding_agent' / 'actions' / action_id
        result_path = receipt / 'result.json'
        if receipt.exists():
            if json.loads((receipt / 'request.json').read_text()) != call:
                raise ValueError('Tool action ID already belongs to a different request.')
            if result_path.exists():
                result = json.loads(result_path.read_text())
                if call['tool'] == 'publish' and result.get('ok'):
                    ids = task.setdefault('item_execution_ids', [])
                    if result['execution_id'] not in ids:
                        ids.append(result['execution_id'])
                return result
            raise ValueError('This tool action may already have been applied. Inspect its files '
                             'before issuing a new action; automatic replay is blocked.')
        receipt.mkdir(parents=True)
        write_json(receipt / 'request.json', call)
        try:
            result = self._host_tool(state, task, directory, workdir, call, action_id=action_id)
        except (OSError, ValueError) as exc:
            result = dict(ok=False, error=f'{type(exc).__name__}: {exc}')
        write_json(result_path, result)
        return result

    def recover_tool(self, state):
        """Reconcile a saved host-tool receipt without applying the tool again."""
        pending = state.get('pending_coding_tool')
        if not pending:
            return
        tasks = [*state.get('task_history', []), *([state['active_task']] if state.get('active_task') else [])]
        task = next((task for task in tasks if task['task_id'] == pending['task_id']), None)
        item = next((item for item in task.get('plan_items', []) if item['step_id'] == pending['step_id']), None) if task else None
        if item is None:
            raise ValueError('Pending coding tool has no saved task item.')
        directory, workdir = self._workdir(state, task, item)
        receipt = workdir / '.coding_agent' / 'actions' / pending['action_id']
        call = pending['call']
        if receipt.exists():
            if (receipt / 'result.json').exists():
                result = self._host_tool_once(state, task, directory, workdir, call, pending['action_id'])
            else:
                result = dict(ok=False, error='Tool execution was interrupted; inspect the affected files '
                              'before retrying. The tool has not been replayed.')
            journal = self._journal(task, item)
            journal['step'] += 1
            self._append(journal, dict(step=journal['step'], tool=call['tool'],
                                     arguments=self._brief(call), result=result))
            self.agent._record(state, 'observation', json.dumps(
                dict(type='coding_agent_tool', tool=call['tool'], result=result), ensure_ascii=False))
            self.agent._event(state, 'coding_tool_recovered', 'Recovered a tool receipt without replay.',
                              action_id=pending['action_id'], tool=call['tool'])
        state.pop('pending_coding_tool')

    def _append(self, journal, entry):
        pending = journal.get('pending_turn')
        if pending:
            index = pending['index']
            entry['call_id'] = pending['message']['tool_calls'][index]['id']
            if index == 0:
                entry['assistant'] = pending['message']
            pending['index'] += 1
            if pending['index'] == len(pending['message']['tool_calls']) and entry['result'].get('ok') is not None:
                journal.pop('pending_turn')
        elif journal.get('pending_call'):
            entry['assistant'] = journal.pop('pending_call')
        journal['entries'].append(entry)

    def _context(self, state, task, item, workdir, journal, budget):
        from .resource_docs import resource_docs
        directory = self.agent.store.directory(state['session_id'])
        # One representation of each fact: current item, compact plan directory,
        # selected upstream references, working summary, then continuous tool turns.
        upstream = executor_view(task, directory, state['task_history'])['completed_results']
        return dict(
            current_item=item,
            plan_overview=[dict(step_id=row['step_id'], title=row['title'],
                                completed=row['step_id'] in task.get('completed_items', {}))
                           for row in task['plan_items'] if row['step_id'] != item['step_id']],
            upstream_results=[{k: row[k] for k in ('source', 'ref', 'error') if k in row} for row in upstream],
            result_refs=result_catalog(directory, work_scope(task, 'mr'),
                include_scopes=list({ref.split('/')[0] for ref in item['reuse_from']})),
            method_docs=resource_docs(self.agent.root),
            work_request=task.get('request'),
            user_updates=[row['content'] for row in state['messages'][task['context_start']:]
                          if row['role'] == 'user' and row.get('task_id') in (None, task['task_id'])
                          and row['content'] != task.get('request')],
            executor_memory=journal['summary'],
            execution_state=self._execution_state(journal),
            evaluation=task.get('evaluation'),
            runtime=runtime_context(workdir=workdir),
            workdir=str(workdir), session_directory=str(directory),
            workspace=str(directory / 'workspace'),
            action_history=coding_history(journal['entries'][journal.get('summary_upto', 0):]),
            step=journal['step'], remaining_actions=budget,
            finish_requirements='finish complete needs a published result linked to a successful run in this item.',
        )

    @staticmethod
    def _execution_state(journal):
        # This is a host projection, not a model-authored claim of completion.
        entry = next((row for row in reversed(journal['entries'])
                      if row.get('tool') == 'run' and (row.get('result') or {}).get('execution_id')), None)
        if entry is None:
            return dict(last_run=None)
        arguments, result = entry.get('arguments', {}), entry['result']
        return dict(last_run=dict(step=entry['step'],
            language=arguments.get('language'), purpose=arguments.get('purpose'),
            script=arguments.get('path') or arguments.get('saved_source'),
            **{key: result.get(key) for key in ('execution_id', 'status', 'returncode',
                                               'source_path', 'stdout_path', 'stderr_path')}))

    def needs_compaction(self, state):
        task = state['active_task']
        item = current_item(task)
        _, workdir = self._workdir(state, task, item)
        journal = self._journal(task, item)
        if journal.get('summary_attempt_step') == journal['step']:
            return False
        with _provider_scope():
            budget = self.agent.context_budget('mr')
        return budget.measure(SYSTEM, self._context(state, task, item, workdir, journal, self.agent.max_rounds), CODING_TOOLS) > budget.summary_trigger

    def compact(self, state):
        from .context import tokens
        task = state['active_task']
        item = current_item(task)
        directory, workdir = self._workdir(state, task, item)
        journal = self._journal(task, item)
        with _provider_scope():
            budget = self.agent.context_budget('mr')
        while self.needs_compaction(state):
            context = self._context(state, task, item, workdir, journal, self.agent.max_rounds)
            before_tokens = budget.measure(SYSTEM, context, CODING_TOOLS)
            remaining = before_tokens
            start = journal.get('summary_upto', 0)
            prefix = []
            # Keep at least the latest complete tool turn for immediate repair.
            prompt = self.agent.prompt('mr_codeact_memory')
            summary = dict(previous_summary=journal['summary'], work_request=task['request'],
                           current_item=item, workdir=str(workdir), session_directory=str(directory),
                           conversation=prefix)
            upto = start
            turns = list(coding_turns(journal['entries'], start))
            for end, turn in turns[:-1]:
                turn = [entry for entry in turn if entry.get('tool') != 'history']
                if not turn:
                    continue
                candidate = dict(summary, conversation=[*prefix, *turn])
                if self.agent.context_budget('memory').measure(prompt, candidate) > self.agent.context_budget('memory').summary_target:
                    break
                prefix.extend(turn)
                upto = end
                remaining -= tokens(coding_history(turn))
                if remaining <= budget.summary_target:
                    break
            if not prefix:
                budget.check(SYSTEM, context, CODING_TOOLS)
                return
            try:
                raw = self.agent._call(state, 'memory', prompt, json.dumps(summary, ensure_ascii=False), structured_action=True)
                note = render_executor_summary(raw, budget.summary_target)
                candidate = self._context(state, task, item, workdir,
                                          dict(journal, summary=note, summary_upto=upto), self.agent.max_rounds)
                if budget.measure(SYSTEM, candidate, CODING_TOOLS) >= before_tokens:
                    raise ValueError('Coding summary did not reduce context; previous memory retained.')
                journal['summary'] = note
                journal['summary_upto'] = upto
                journal.pop('summary_attempt_step', None)
                self.agent._event(state, 'memory_compacted', 'Summarized earlier coding turns.',
                                  through_step=journal['entries'][journal['summary_upto'] - 1]['step'])
            except Exception as exc:
                journal['summary_attempt_step'] = journal['step']
                self.agent._event(state, 'memory_warning', f'Coding summary unavailable: {type(exc).__name__}: {redact(str(exc))}; history retained.')
                budget.check(SYSTEM, context, CODING_TOOLS)
                return

    # ---- host-side tools ---------------------------------------------------

    def _host_tool(self, state, task, directory, workdir, call, *, action_id=None):
        tool = call['tool']
        if tool == 'list':
            path = self._readable(directory, workdir, call.get('path') or '.')
            if not path.exists():
                raise ValueError(f'No such path: {call.get("path")}')
            rows = []
            for child in sorted(path.iterdir()) if path.is_dir() else [path]:
                try:
                    suffix = '/' if child.is_dir() else ''
                    size = '' if child.is_dir() else child.stat().st_size
                    base = workdir if self._inside(workdir, child) else directory if self._inside(directory, child) else path.parent
                    rows.append(f'{child.relative_to(base)}{suffix}\t{size}')
                except OSError:
                    continue
            return dict(ok=True, entries=rows[:200])
        if tool == 'read':
            path = self._readable(directory, workdir, call.get('path'))
            if path.is_dir():
                return dict(ok=False, error=f'{call.get("path")} is a directory; use list for directories.')
            if not path.is_file():
                raise ValueError(f'Not a file: {call.get("path")}')
            start = int(call.get('start', 1))
            end = int(call.get('end', start + 199))
            if start < 1 or end < start:
                raise ValueError('read requires 1 <= start <= end')
            rows, size, truncated = [], 0, False
            with path.open(errors='replace') as stream:
                for number, line in enumerate(stream, 1):
                    if number < start:
                        continue
                    if number > end or size + len(line) > READ_LIMIT:
                        truncated = True
                        if not rows:
                            rows.append(f'{number:5d}\t{line[:READ_LIMIT]}')
                        break
                    rows.append(f'{number:5d}\t{line.rstrip()}')
                    size += len(line)
            return dict(ok=True, path=call['path'], start=start, content='\n'.join(rows), truncated=truncated)
        if tool == 'grep':
            root = self._readable(directory, workdir, call['path'])
            command = ['rg', '-n', '-i', '--max-count', str(GREP_LIMIT), '--max-filesize', str(FILE_LIMIT),
                       '--glob', call.get('glob') or '*', '--glob', '!.coding_agent/**',
                       '--glob', '!*.bak', '--', call['pattern'], str(root)]
            with tempfile.TemporaryFile() as output:
                try:
                    result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, timeout=15)
                except subprocess.TimeoutExpired:
                    return dict(ok=False, error='Search exceeded 15 seconds. Narrow the path or glob.')
                output.seek(0)
                text = output.read(READ_LIMIT + 1).decode(errors='replace')
            if result.returncode not in {0, 1}:
                raise ValueError(_preview(result.stderr.decode(errors='replace'), 2000))
            return dict(ok=True, matches=text[:READ_LIMIT].splitlines()[:GREP_LIMIT],
                        truncated=len(text) > READ_LIMIT or len(text.splitlines()) > GREP_LIMIT)
        if tool == 'write':
            path = self._writable(workdir, call.get('path'))
            content = call.get('content')
            if not isinstance(content, str):
                raise ValueError('write requires text content')
            path.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if path.is_file():
                shutil.copyfile(path, path.with_name(path.name + '.bak'))
                backup = path.name + '.bak'
            path.write_text(content, encoding='utf-8')
            return dict(ok=True, path=call.get('path'), lines=content.count('\n') + 1, backup=backup)
        if tool == 'edit':
            path = self._writable(workdir, call.get('path'))
            old, new = call.get('old'), call.get('new')
            if not path.is_file():
                raise ValueError(f'Not a file: {call.get("path")}. Use write for a new file.')
            if not isinstance(old, str) or not old:
                raise ValueError('edit requires the exact existing text in `old`')
            if not isinstance(new, str):
                raise ValueError('edit requires the replacement text in `new`')
            text = path.read_text()
            found = text.count(old)
            if found != 1:
                raise ValueError(f'`old` must occur exactly once; found {found}. Read the file and quote a unique section.')
            shutil.copyfile(path, path.with_name(path.name + '.bak'))
            path.write_text(text.replace(old, new, 1), encoding='utf-8')
            return dict(ok=True, path=call.get('path'), replaced=1, backup=path.name + '.bak')
        if tool == 'docs':
            skill = self.agent.skills.get(str(call.get('id') or ''))
            if skill:
                task['guide'] = skill.id
                if skill.id not in state['loaded_skills']:
                    state['loaded_skills'].append(skill.id)
                self.agent._event(state, 'skill_loaded', skill.id)
                return dict(ok=True, id=skill.id, content=self.agent.skills.read(skill.id))
            from mrcat.resource_docs import read_resource_doc, ResourceDocError
            try:
                content = read_resource_doc(str(call.get('id') or ''))
            except ResourceDocError as exc:
                raise ValueError(str(exc)) from None
            return dict(ok=True, id=call.get('id'), content=_preview(content, 24000))
        if tool == 'publish':
            name, execution_id = call['name'], call['execution_id']
            if execution_id not in task.get('item_run_ids', []):
                raise ValueError('Publication must reference a run from this item.')
            observation = json.loads((directory / 'executions' / execution_id / 'observation.json').read_text())
            if failed(observation):
                raise ValueError('Cannot publish outputs from an unsuccessful run.')
            path = self._writable(workdir, call['path'])
            ref_path = str(path.relative_to(directory))
            digest = observation.get('artifact_hashes', {}).get(ref_path)
            if not digest or not path.is_file() or path.stat().st_size > FILE_LIMIT:
                raise ValueError('Publish a small JSON file produced by the referenced run.')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('The output changed after execution. Rerun the computation before publishing.')
            outputs = json.loads(raw)
            if not isinstance(outputs, dict) or not outputs:
                raise ValueError('The result file must contain a nonempty JSON object.')
            previous = {key: os.environ.get(key) for key in
                        ('MRCAT_SESSION_DIR', 'MRCAT_RESULT_SCOPE', 'MRCAT_EXECUTION_ID')}
            os.environ.update(MRCAT_SESSION_DIR=str(directory), MRCAT_RESULT_SCOPE=task['task_id'],
                              MRCAT_EXECUTION_ID=execution_id)
            try:
                ref = _publish(name, outputs, producer=dict(output_path=ref_path,
                    source_path=observation['source_path'], observation_path=f'executions/{execution_id}/observation.json'))
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            task.setdefault('item_execution_ids', []).append(execution_id)
            return dict(ok=True, ref=ref, name=name, execution_id=execution_id)
        raise ValueError(f'Unknown tool: {tool}')

    # ---- run ---------------------------------------------------------------

    def _run(self, task, workdir, journal, call, update, step, action_id):
        language = call.get('language') or 'python'
        if language not in {'python', 'r', 'bash'}:
            raise ValueError('run language must be python, r or bash')
        if bool(call.get('path')) == bool(call.get('content')):
            raise ValueError('run requires exactly one of path or content')
        ceiling = min(self.agent.execution_timeout, {'inspect': 30, 'repair': 300,
                      'compute': self.agent.execution_timeout}[call['purpose']])
        timeout = min(call.get('timeout', ceiling), ceiling)
        path = call.get('path')
        if path:
            source = self._writable(workdir, path)
            if not source.is_file():
                raise ValueError(f'Script not found: {path}. Write it first.')
            code = source.read_text()
            executed = str(path)
        else:
            code = call.get('content')
            if not isinstance(code, str) or not code.strip():
                raise ValueError('run requires a saved script `path` or inline `content`')
            suffix = {'python': 'py', 'r': 'R', 'bash': 'sh'}[language]
            source = workdir / '.coding_agent' / f'step_{step:03d}.{suffix}'
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(code, encoding='utf-8')
            executed = str(source.relative_to(workdir))
        action = dict(kind='execute', language=language, body=code, working_directory=str(workdir),
                      execution_id=action_id, timeout=timeout, purpose=call['purpose'], message=f'Run {executed}')
        task.setdefault('item_run_ids', []).append(action['execution_id'])
        self._append(journal, dict(step=step, tool='run',
                                   arguments=dict(call, saved_source=executed),
                                   result=dict(ok=None, execution_id=action['execution_id'])))
        return update | dict(action=action, next_node='execute')

    def _observe_execution(self, flow, state):
        directory = self.agent.store.directory(flow['sid'])
        ref = f'executions/{flow["action"]["execution_id"]}/observation.json'
        result = json.loads((directory / ref).read_text())
        logs = redirected_logs(directory, result)
        # Snapshot now: subsequent attempts may overwrite the same log file.
        write_json((directory / ref).with_name('custom_diagnostics.json'), logs)
        self.agent._record(state, 'observation', json.dumps(result, ensure_ascii=False))
        work = memory.work_state(state, 'mr')
        work['artifacts'] = list(dict.fromkeys([*work.get('artifacts', []), ref, *result.get('generated_files', [])]))
        memory.record_execution(work, result)
        payload = {key: result.get(key) for key in ('status', 'returncode', 'stdout', 'stderr')}
        payload['tool_results'] = [{key: row.get(key) for key in ('status', 'failure_class', 'summary', 'message')}
                                   for row in result.get('tool_results', [])]
        payload['log_tails'] = [log['tail'] for log in logs]
        # Tracebacks embed the fresh execution directory even for identical code.
        observed = json.dumps(payload, sort_keys=True).replace(
            str(directory / 'executions' / result['execution_id']), '<execution>')
        fingerprint = hashlib.sha256(observed.encode()).hexdigest()
        update = self.track_observation(flow, fingerprint, failed=failed(result))
        if not failed(result) and flow['action'].get('purpose') in {'repair', 'compute'}:
            update.update(review_reason='', coding_stop=False)
        return update

    @staticmethod
    def track_observation(flow, fingerprint, *, changed=False, failed=False):
        # File creation says nothing about progress. Only repeated failures are stopped here.
        seen = [*flow.get('fingerprints', []), fingerprint][-6:]
        repeated = failed and seen.count(fingerprint) >= 3
        return dict(fingerprints=seen, failures=flow.get('failures', 0) + 1 if failed else 0,
                    coding_stop=repeated or flow.get('coding_stop', False),
                    review_reason='Repeated identical execution failures; saved evidence needs a different repair.'
                    if repeated else flow.get('review_reason', ''))

    def observe(self, flow, state):
        """Record the run in the coding-agent journal, then follow the normal path."""
        update = self._observe_execution(flow, state)
        task = state['active_task']
        item = current_item(task)
        directory, workdir = self._workdir(state, task, item)
        execution_id = flow['action']['execution_id']
        try:
            result = json.loads((directory / 'executions' / execution_id / 'observation.json').read_text())
        except (OSError, ValueError):
            return update | dict(next_node='context')
        journal = self._journal(task, item)
        entry = next((row for row in reversed(journal['entries'])
                      if row.get('tool') == 'run'
                      and isinstance(row.get('result'), dict)
                      and row['result'].get('execution_id') == execution_id), None)
        if entry is not None:
            entry['result'] = dict(
                ok=(result.get('status') == 'exited'
                    and result.get('returncode') in {0, 141}),
                execution_id=execution_id,
                status=result.get('status'), returncode=result.get('returncode'),
                note='exit 141 is SIGPIPE from a closed pipe, not a computation failure'
                     if result.get('returncode') == 141 else None,
                stdout=_preview(result.get('stdout')), stderr=_preview(result.get('stderr')),
                source_path=result.get('source_path'), stdout_path=result.get('stdout_path'),
                stderr_path=result.get('stderr_path'),
                redirected_logs=json.loads((directory / 'executions' / execution_id / 'custom_diagnostics.json').read_text()),
                tool_results=result.get('tool_results', []),
                generated_files=result.get('generated_files', [])[:20],
                result_refs=[row.get('ref') for row in result.get('result_refs', [])][:20])
        return update | dict(next_node='context')

    # ---- finish ------------------------------------------------------------

    def _finish(self, state, task, item, directory, workdir, journal, call, update, step):
        outcome = call.get('outcome')
        body = str(call.get('body') or '').strip()
        if outcome not in {'complete', 'blocked', 'technical_blocked'}:
            raise ValueError('finish requires outcome complete, blocked or technical_blocked')
        if not body:
            raise ValueError('finish requires a body describing the result or the obstacle')
        if outcome == 'complete':
            problem = self._completion_problem(task, directory)
            if problem:
                self._append(journal, dict(step=step, tool='finish_rejected', result=dict(ok=False, error=problem)))
                self.agent._record(state, 'observation', json.dumps(
                    dict(type='completion_rejected', reason=problem, applied=False)))
                return update | dict(next_node='context')
        outcome = 'paused' if outcome == 'technical_blocked' else outcome
        self._append(journal, dict(step=step, tool='finish', result=dict(ok=True, outcome=outcome,
            body='Handoff submitted; successful submission does not mean scientific acceptance. ' + body[:600])))
        return update | dict(next_node='end', action=dict(
            kind='end', outcome=outcome, body=body, language='python', message=''))

    def _completion_problem(self, task, directory):
        """Completion needs real work in this item, not only a claim."""
        runs = task.get('item_run_ids', [])
        if not runs:
            return 'Nothing has been run for this item yet. Build the computation and run it before finishing.'
        try:
            last = json.loads((Path(directory) / 'executions' / runs[-1] / 'observation.json').read_text())
        except (OSError, ValueError):
            return 'The last run has no readable final observation. Inspect its logs before continuing.'
        if failed(last):
            return 'The last run failed. Repair and verify the computation before finishing.'
        if not self._publications(task, directory):
            return ('No result from a successful run has been published for this item. '
                    'Verify the computed output and publish it before finishing.')
        return ''

    @staticmethod
    def _publications(task, directory):
        ids = set(task.get('item_run_ids', []))
        names = []
        for path in (Path(directory) / 'results' / task['task_id']).glob('*.json'):
            try:
                entry = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if entry.get('execution_id') in ids and entry.get('status') not in {'failed', 'error', 'blocked'}:
                try:
                    observation = json.loads((Path(directory) / 'executions' / entry['execution_id'] / 'observation.json').read_text())
                except (OSError, ValueError):
                    continue
                if not failed(observation):
                    names.append(path.stem)
        return names
