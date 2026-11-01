"""Capacity-based history retention, atomic summaries and whole-prompt limits."""
import json
from copy import deepcopy

import pytest

from mrcat.agent import Agent
from mrcat.coding_agent import CodingAgentNodes, SYSTEM
from mrcat.context import ContextBudget, ContextBudgetExceeded
from mrcat.tasks import create_task
from test_agent import ROOT, create


def coding_history(tmp_path, count=70):
    store, sid = create(tmp_path)
    state = store.load(sid)
    item = dict(step_id='fit', title='Repair fit.py', skill_id=None, reuse_from=[])
    task = create_task(state, dict(description='Repair', request='Keep all input rows',
                                  plan='Repair fit.py', plan_items=[item]))
    task.update(current_item_id='fit', item_context_start=0, item_execution_ids=[])
    state['active_agent'] = 'mr'
    journal = CodingAgentNodes._journal(task, item)
    for i in range(count):
        journal['entries'].append(dict(step=i + 1, tool='read', arguments={'path': 'fit.py'},
                                       result={'content': f'CONFIRMED_{i} ' + 'data ' * 320}))
    journal['step'] = count
    return Agent(ROOT, store), state, journal


def test_capacity_retains_more_than_24_complete_turns(tmp_path):
    agent, state, journal = coding_history(tmp_path)
    nodes = CodingAgentNodes(agent)
    task = state['active_task']
    _, workdir = nodes._workdir(state, task, task['plan_items'][0])
    context = nodes._context(state, task, task['plan_items'][0], workdir, journal, 300)
    assert [json.loads(m['content']) for m in context['action_history']] == journal['entries']
    assert len(context['action_history']) == 70
    assert json.loads(context['action_history'][0]['content'])['result']['content'].startswith('CONFIRMED_0')
    assert not nodes.needs_compaction(state)
    assert 'current_plan' not in context and 'completed_results' not in context


def test_summary_commits_prefix_only_after_validation_and_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('MRCAT_CONTEXT_TOKENS', '32000')
    monkeypatch.setenv('MRCAT_MAX_OUTPUT_TOKENS', '2048')
    agent, state, journal = coding_history(tmp_path)
    original = deepcopy(journal['entries'])
    task_note = state['active_task']['memory']
    calls = []
    def summarize(**kwargs):
        data = json.loads(kwargs['user'])
        calls.append(data)
        assert data['conversation']
        assert 'CONFIRMED_69' not in kwargs['user']
        return json.dumps(dict(objective='Keep all input rows', decisions='', active='fit.py', references='Saved journal',
                               completed='Earlier read results remain in saved history.',
                               next_steps='Verify the fit.', blockers='Inspected fit.py.'))
    agent.model = summarize
    nodes = CodingAgentNodes(agent)
    assert nodes.needs_compaction(state)
    nodes.compact(state)
    assert calls and 0 < journal['summary_upto'] < len(original)
    assert journal['entries'] == original
    assert state['active_task']['memory'] == task_note
    assert not nodes.needs_compaction(state)
    agent.store.save(state)
    restored = agent.store.load(state['session_id'])
    assert restored['active_task']['coding'] == state['active_task']['coding']
    assert 'Keep all input rows' in restored['active_task']['memory']


def test_failed_summary_does_not_drop_any_history(tmp_path, monkeypatch):
    monkeypatch.setenv('MRCAT_CONTEXT_TOKENS', '32000')
    monkeypatch.setenv('MRCAT_MAX_OUTPUT_TOKENS', '2048')
    agent, state, journal = coding_history(tmp_path)
    original = deepcopy(journal)
    note = state['active_task']['memory']
    agent.model = lambda **kwargs: '{"incomplete":"summary"}'
    with pytest.raises(ContextBudgetExceeded):
        CodingAgentNodes(agent).compact(state)
    assert journal['entries'] == original['entries']
    assert journal.get('summary_upto', 0) == 0
    assert state['active_task']['memory'] == note


def test_full_prompt_budget_accounts_for_system_and_tools(monkeypatch):
    monkeypatch.setenv('MRCAT_CONTEXT_TOKENS', '8192')
    monkeypatch.setenv('MRCAT_MAX_OUTPUT_TOKENS', '1024')
    monkeypatch.setenv('MRCAT_MODEL_CONTEXT_TOKENS', '{"large": 131072}')
    small = ContextBudget.configured('small')
    assert ContextBudget.configured('large').input_limit > small.input_limit
    text = '数据信息' * 2000
    with pytest.raises(ContextBudgetExceeded):
        small.check(SYSTEM, {'question': 'Compute'}, {'description': text})


def test_old_task_and_role_do_not_enter_coding_context(tmp_path):
    agent, state, journal = coding_history(tmp_path, count=2)
    state['messages'].append(dict(role='user', task_id='task2', content='OTHER TASK'))
    nodes = CodingAgentNodes(agent)
    task = state['active_task']
    _, workdir = nodes._workdir(state, task, task['plan_items'][0])
    context = nodes._context(state, task, task['plan_items'][0], workdir, journal, 300)
    assert 'OTHER TASK' not in json.dumps(context)


def test_coding_summary_over_old_character_limit_is_accepted_when_it_reduces_context(tmp_path, monkeypatch):
    monkeypatch.setenv('MRCAT_CONTEXT_TOKENS', '32000')
    monkeypatch.setenv('MRCAT_MAX_OUTPUT_TOKENS', '2048')
    agent, state, journal = coding_history(tmp_path)
    original = deepcopy(journal['entries'])
    task_note = state['active_task']['memory']
    calls = []
    def summarize(**kwargs):
        calls.append(kwargs)
        return json.dumps(dict(objective='Keep all input rows', decisions='', active='fit.py', references='Saved journal',
            completed='Verified evidence remains in saved files. ' * 180,
            next_steps='Verify the fit.', blockers='Inspected fit.py.'))
    agent.model = summarize
    nodes = CodingAgentNodes(agent)
    nodes.compact(state)
    assert len(journal['summary']) > 6000
    assert journal['summary_upto'] > 0
    assert journal['entries'] == original
    assert state['active_task']['memory'] == task_note
    assert not nodes.needs_compaction(state)
    count = len(calls)
    nodes.compact(state)
    assert len(calls) == count
    agent.store.save(state)
    restored = agent.store.load(state['session_id'])
    assert restored['active_task']['memory'] == state['active_task']['memory']
    assert restored['active_task']['coding'] == state['active_task']['coding']


def test_nonreducing_summary_does_not_replace_memory_or_advance_history(tmp_path, monkeypatch):
    monkeypatch.setenv('MRCAT_CONTEXT_TOKENS', '32000')
    monkeypatch.setenv('MRCAT_MAX_OUTPUT_TOKENS', '2048')
    agent, state, journal = coding_history(tmp_path, count=2)
    journal['entries'][-1]['result']['content'] = 'large latest evidence ' * 6000
    original = deepcopy(journal['entries'])
    task_note = state['active_task']['memory']
    memory_before = state['active_task']['memory']
    agent.model = lambda **kwargs: json.dumps(dict(objective='Task', decisions='', active='fit.py', references='Saved journal',
        completed='Nonreducing summary content. ' * 300,
        next_steps='Pending', blockers='Read'))
    with pytest.raises(ContextBudgetExceeded):
        CodingAgentNodes(agent).compact(state)
    assert state['active_task']['memory'] == memory_before
    assert journal.get('summary_upto', 0) == 0
    assert journal['entries'] == original
    assert state['active_task']['memory'] == task_note
    assert 'did not reduce context' in state['events'][-1]['content']


def test_token_limited_summary_still_rejects_oversized_output():
    from mrcat.memory import completed_memory, initial_memory
    note = initial_memory('Evidence ' * 3000) + '\n[END_MEMORY]'
    with pytest.raises(ValueError, match='exceeds its budget'):
        completed_memory(note, token_limit=1000)


def test_compaction_skips_history_queries_without_losing_evidence_or_cursor(tmp_path, monkeypatch):
    monkeypatch.setenv('MRCAT_CONTEXT_TOKENS', '32000')
    monkeypatch.setenv('MRCAT_MAX_OUTPUT_TOKENS', '2048')
    agent, state, journal = coding_history(tmp_path)
    retired = dict(step=0, tool='history', result=dict(messages=['NESTED_QUERY' * 10000]))
    journal['entries'].insert(0, retired)
    original = deepcopy(journal['entries'])
    summarized_steps = []
    def summarize(**kwargs):
        data = json.loads(kwargs['user'])
        assert 'NESTED_QUERY' not in kwargs['user']
        assert all(row['tool'] != 'history' for row in data['conversation'])
        assert data['session_directory'] == str(agent.store.directory(state['session_id']))
        assert data['workdir'].endswith('/workspace/outputs/task1/fit')
        summarized_steps.extend(row['step'] for row in data['conversation'])
        return json.dumps(dict(objective='Keep all input rows', decisions='', completed='Read source.',
            active='fit.py', blockers='', next_steps='Verify fit.py.', references=data['workdir'] + '/fit.py'))
    agent.model = summarize
    nodes = CodingAgentNodes(agent)
    nodes.compact(state)
    assert summarized_steps
    assert journal['entries'][journal['summary_upto'] - 1]['step'] == summarized_steps[-1]
    assert journal['entries'] == original
    assert not nodes.needs_compaction(state)
