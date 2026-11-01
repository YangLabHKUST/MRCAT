"""Executor state is separate from scientific memory and survives recovery."""
import json
from copy import deepcopy

import pytest

from mrcat.agent import Agent
from mrcat.coding_agent import CodingAgentNodes
from mrcat.coding_protocol import action_messages, coding_history, loop_feedback
from mrcat.memory import update_mr_task_memory
from mrcat.store import Store
from test_agent import ROOT, create, decision, native_reply
from test_coding_graph import CodingModel
from test_context_budget import coding_history as seeded_history


def read_entry(step, path, content='unchanged'):
    call = dict(tool='read', path=path)
    return dict(step=step, tool='read', arguments=call,
                assistant=json.loads(native_reply(call)), result=dict(ok=True, content=content))


@pytest.mark.parametrize('width', [1, 2, 5])
def test_repeat_guard_compares_observations_across_turns(width):
    entries = [read_entry(i + 1, f'{i % width}.py') for i in range(3 * width)]
    original = deepcopy(entries)
    assert loop_feedback(entries[:width]) == dict(coding_stop=False, review_reason='')
    feedback = loop_feedback(entries[:2 * width])
    assert not feedback['coding_stop'] and 'Change approach' in feedback['review_reason']
    assert loop_feedback(entries)['coding_stop']
    entries[-1]['result']['content'] = 'file changed'
    assert not loop_feedback(entries)['coding_stop']
    assert not loop_feedback([*original, dict(tool='edit')])['review_reason']
    assert len(entries) == len(original)


def test_dedup_keeps_native_pairs_and_latest_full_observation_without_changing_journal():
    entries = [read_entry(1, 'a.py', 'before'), read_entry(2, 'a.py', 'after'),
               read_entry(3, 'a.py', 'after')]
    original = deepcopy(entries)
    history = coding_history(entries)
    outputs = [json.loads(row['content']) for row in history if row['role'] == 'tool']
    assert outputs[0]['content'] == 'before'
    assert outputs[1]['repeated_observation'] and outputs[1]['latest_step'] == 3
    assert outputs[2]['content'] == 'after'
    for assistant, observation in zip(history[::2], history[1::2]):
        assert assistant['tool_calls'][0]['id'] == observation['tool_call_id']
    request = action_messages('system', json.dumps(dict(action_history=history, execution_feedback='Change approach')))
    assert request[2:-1] == history and 'Change approach' in request[-1]['content']
    assert 'execution_feedback' not in request[1]['content']
    assert entries == original


def test_summary_claim_cannot_replace_latest_actual_run(tmp_path):
    agent, state, journal = seeded_history(tmp_path, count=0)
    journal.update(summary='The computation succeeded.', summary_upto=1, step=1)
    journal['entries'] = [dict(step=1, tool='run', arguments=dict(path='fit.py', purpose='compute', language='python'),
        result=dict(ok=False, execution_id='failed1', status='exited', returncode=1,
                    stderr_path='executions/failed1/stderr.log'))]
    nodes = CodingAgentNodes(agent)
    task = state['active_task']
    item = task['plan_items'][0]
    _, workdir = nodes._workdir(state, task, item)
    context = nodes._context(state, task, item, workdir, journal, 300)
    assert context['execution_state']['last_run']['returncode'] == 1
    assert context['execution_state']['last_run']['script'] == 'fit.py'
    assert context['executor_memory'] == journal['summary']
    assert 'memory' not in context and context['action_history'] == []


def test_export_is_readable_but_checkpoint_remains_authoritative(tmp_path):
    agent, state, journal = seeded_history(tmp_path, count=2)
    journal['summary'] = 'Executor-only debugging detail'
    task = state['active_task']
    update_mr_task_memory(task)
    mr_note = task['memory']
    agent.store.save(state)
    agent.store.export(state)
    directory = agent.store.directory(state['session_id'])
    exported = directory / 'workspace/outputs' / task['task_id'] / 'fit/executor_memory.md'
    assert exported.read_text() == journal['summary']
    assert journal['summary'] not in (directory / 'memory.md').read_text()
    exported.write_text('Tampered executor export')
    (directory / 'memory.md').write_text('Tampered MR export')
    restored = Store(tmp_path).load(state['session_id'])['active_task']
    assert restored['memory'] == mr_note
    assert restored['coding']['fit'] == journal


def test_mr_memory_distinguishes_unaccepted_claims_from_result_records():
    task = dict(request='Compute 42', plan_items=[dict(step_id='fit', title='Fit')],
                completed_items={}, executor_handoff=dict(outcome='complete', body='Claimed success'))
    update_mr_task_memory(task)
    assert 'No accepted results yet.' in task['memory']
    assert 'not scientific acceptance' in task['memory']
    task['completed_items']['fit'] = dict(outputs={'answer': {'ref': '$ref:answer', 'execution_id': 'run1'}})
    update_mr_task_memory(task)
    assert '$ref:answer' in task['memory'] and 'No unfinished plan items.' in task['memory']


def test_five_file_loop_pauses_then_continues_to_real_execution_and_review(tmp_path):
    store, sid = create(tmp_path)
    paths = [store.directory(sid) / 'workspace' / f'source_{i}.py' for i in range(5)]
    for i, path in enumerate(paths):
        path.write_text(f'value = {i}')
    first = CodingModel([dict(tool='read', path=str(path)) for path in paths * 3],
                        decisions=[decision('mr', 'propose')])
    paused = Agent(ROOT, store, model=first, auto_confirm_plan=True).run(sid, 'Compute and publish 42')
    assert paused['status'] == 'paused'
    task = paused['active_task']
    journal = next(iter(task['coding'].values()))
    saved_entries = deepcopy(journal['entries'])
    assert len(saved_entries) == 15 and '3 times' in task['executor_handoff']['body']
    calls = [json.loads(call['user']) for call in first.calls if call['role'] == 'mr']
    assert 'Change approach' in calls[10]['execution_feedback']
    assert not any(call['role'] == 'evaluate' for call in first.calls)
    second = CodingModel([
        dict(tool='run', content='from mrcat.tools import publish_result; publish_result("answer", {"value": 6 * 7})'),
        dict(tool='finish', outcome='complete', body='Executed and published 42.'),
    ], decisions=[decision('mr', 'continue')])
    done = Agent(ROOT, Store(tmp_path), model=second).run(sid, 'Use the inspected evidence and compute now')
    assert done['status'] == 'completed'
    completed = done['task_history'][0]
    resumed = next(iter(completed['coding'].values()))
    assert resumed['entries'][:15] == saved_entries
    assert [row['tool'] for row in resumed['entries'][15:]] == ['run', 'finish']
    assert completed['completed_items'] and '$ref:' in completed['memory']
    assert any(call['role'] == 'evaluate' for call in second.calls)
    assert not any(call['role'] == 'memory' for call in second.calls)


@pytest.mark.parametrize('native', [False, True])
def test_resume_uses_saved_logs_without_replaying_history_queries(tmp_path, native):
    store, sid = create(tmp_path)
    first = CodingModel([dict(tool='run', content=(
        'import json; from pathlib import Path; Path("result.json").write_text(json.dumps(dict(value=42))); '
        'print("Verified answer: 42")'))], decisions=[decision('mr', 'propose')])
    paused = Agent(ROOT, store, model=first, max_rounds=1, auto_confirm_plan=True).run(sid, 'Compute 42')
    assert paused['status'] == 'paused'
    task = paused['active_task']
    journal = next(iter(task['coding'].values()))
    run = journal['entries'][0]['result']
    log_path = str(store.directory(sid) / run['stdout_path'])
    journal.update(summary=f'Computed 42; verify {log_path} and publish result.json.', summary_upto=1)
    for step in range(2, 64):
        call = dict(tool='history', start=step * 2, limit=50)
        entry = dict(step=step, tool='history', arguments=call,
                     result=dict(ok=True, messages=['NESTED_QUERY'], has_more=True))
        if native:
            entry['assistant'] = json.loads(native_reply(call))
        journal['entries'].append(entry)
    journal['step'] = 63
    saved_entries = deepcopy(journal['entries'])
    store.save(paused)
    second = CodingModel([
        dict(tool='read', path=log_path),
        dict(tool='publish', name='answer', path='result.json', execution_id=run['execution_id']),
        dict(tool='finish', outcome='complete', body='Verified the saved output and published 42.'),
    ], decisions=[decision('mr', 'continue')])
    done = Agent(ROOT, Store(tmp_path), model=second).run(sid, 'Verify the saved output and finish')
    assert done['status'] == 'completed'
    calls = [call for call in second.calls if call['role'] == 'mr']
    context = json.loads(calls[0]['user'])
    assert 'history_access' not in context
    assert context['action_history'] == []
    assert log_path in context['executor_memory']
    assert context['execution_state']['last_run']['execution_id'] == run['execution_id']
    assert all('history' not in {tool['function']['name'] for tool in call['tools']} for call in calls)
    assert all('NESTED_QUERY' not in call['user'] for call in second.calls)
    completed = done['task_history'][0]
    restored = next(iter(completed['coding'].values()))
    assert restored['entries'][:len(saved_entries)] == saved_entries
    assert [entry['tool'] for entry in restored['entries'][len(saved_entries):]] == ['read', 'publish', 'finish']
    assert 'Verified answer: 42' in restored['entries'][len(saved_entries)]['result']['content']
    result = json.loads((store.directory(sid) / 'results/task1/answer.json').read_text())
    assert result['outputs']['value'] == 42
    assert result['execution_id'] == run['execution_id']
