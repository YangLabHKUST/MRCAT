"""Evidence retention and model-call economy without changing scientific routing."""
import json
from copy import deepcopy
import pytest
from mrcat.model.context import ContextBudgetExceeded

from mrcat.state import memory
from mrcat.agent import Agent
from test_agent import ROOT, Model, action, create, decision
from test_custom_codeact import execution_evidence


def observation(index, stdout='n=42', **extra):
    result = dict(execution_id=str(index), status='exited', returncode=0,
        stdout=stdout, stderr='', source_path=f'executions/{index}/code.py',
        stdout_path=f'executions/{index}/stdout.log', stderr_path=f'executions/{index}/stderr.log')
    result.update(extra)
    return dict(role='observation', agent='mr', task_id='task1', content=json.dumps(result))


def state_with(messages):
    return dict(messages=messages, active_task=dict(task_id='task1', context_start=0,
        memory_upto=0, memory=memory.initial_memory('Preserve study and method')), role_memory={})


def test_short_evidence_survives_beyond_old_eight_message_window_without_compaction():
    messages = [observation(i, f'confirmed SNP count={100+i}') for i in range(14)]
    state = state_with(messages)
    before = deepcopy(state)
    visible = memory.recent_messages(messages, role='mr', task_id='task1')
    assert len(visible) == 14
    assert 'count=100' in visible[0]['content'] and 'count=113' in visible[-1]['content']
    assert state == before


def test_old_code_is_referenced_and_latest_code_stays_available():
    messages = []
    for i in range(2):
        messages.extend([dict(role='assistant', agent='mr', content=json.dumps(
            action('execute', f'print("CODE_{i}")', message=f'Check {i}'))), observation(i)])
    original = deepcopy(messages)
    recent = memory.recent_messages(messages, role='mr')
    assert 'CODE_0' not in recent[0]['content']
    assert 'Check 0' in recent[0]['content']
    assert 'executions/0/code.py' in recent[1]['content']
    assert 'CODE_1' in recent[2]['content']
    assert messages == original


def test_tool_block_survives_large_stdout_even_with_zero_exit_code():
    message = observation('qc', 'x' * 20000, tool_results=[dict(
        path='workspace/qc/response.json', status='blocked', failure_class='source_mapping_conflict',
        message='ALT effect allele contradicts minor_allele hint', summary='Mapping failed')])
    projected = json.loads(memory.recent_messages([message])[0]['content'])
    assert projected['returncode'] == 0
    assert projected['tool_results'][0]['failure_class'] == 'source_mapping_conflict'
    assert projected['tool_results'][0]['path'] == 'workspace/qc/response.json'
    assert len(projected['stdout']) < 4000


def test_role_and_task_isolation_in_compaction_and_context():
    other = dict(role='observation', agent='search', task_id='task2', content='UNRELATED ' * 2000)
    state = state_with([observation(0), other, observation(1)])
    evidence = memory.relevant_messages(state['messages'], role='mr', task_id='task1')
    assert len(evidence) == 2
    assert 'UNRELATED' not in json.dumps(memory.recent_messages(state['messages'], role='mr', task_id='task1'))


def test_many_short_mr_cells_do_not_add_periodic_memory_calls(tmp_path):
    store, sid = create(tmp_path)
    model = Model([*[action('execute', f'from pathlib import Path; Path("check_{i}.txt").write_text("checked"); print("checked {i}"); from mrcat.tools import publish_result; publish_result("check_{i}", {{"check": {i}}})') for i in range(8)],
                   action('end', 'All requested checks complete.', outcome='complete')],
                  [decision('mr', 'propose', execute=True)])
    done = Agent(ROOT, store, model=model).run(sid, 'Run the requested checks')
    roles = [call['role'] for call in model.calls]
    assert done['status'] == 'completed'
    assert roles.count('memory') == 0  # MR progress comes from accepted host records at delivery.
    assert roles.count('evaluate') == roles.count('planner') == 1


def test_custom_tool_failure_repair_preserves_debugging_history(tmp_path):
    store, sid = create(tmp_path)
    code = '''import json
from pathlib import Path
Path('response.json').write_text(json.dumps({'outputs': {'status': 'blocked'}, 'details': {'failure_class': 'scale_input_invalid', 'message': 'missing outcome N'}}))'''
    model = Model([*[action('execute', code) for _ in range(2)],
                   action('execute', 'from mrcat.tools import publish_result\npublish_result("repaired", {"n": 100})'),
                   action('end', 'Complete after repair.', outcome='complete')],
                  [decision('mr', 'propose', execute=True)])
    done = Agent(ROOT, store, model=model).run(sid, 'Process the supplied data')
    mr_calls = [json.loads(c['user']) for c in model.calls if c['role'] == 'mr']
    assert 'scale_input_invalid' in json.dumps(execution_evidence(mr_calls[1])[-1])
    assert execution_evidence(mr_calls[2])[-1]['code'] == code
    assert 'failed_execution' not in mr_calls[2]
    assert mr_calls[2]['action_history']
    assert len(execution_evidence(mr_calls[2])) == 2
    assert sum(c['role'] == 'evaluate' for c in model.calls) == 1
    assert done['status'] == 'completed'


def test_failed_summary_does_not_advance_cursor_or_loop_without_new_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("MRCAT_CONTEXT_TOKENS", "16000")
    monkeypatch.setenv("MRCAT_MAX_OUTPUT_TOKENS", "1024")
    store, sid = create(tmp_path)
    state = store.load(sid)
    memory.work_state(state, 'search').update(context_start=0, memory_upto=0)
    state['messages'] = [dict(observation(i, 'evidence ' * 1000), agent='search', task_id=None) for i in range(9)]
    before = state['role_memory']['search']['memory']
    calls = []
    def unavailable(**kwargs):
        calls.append(kwargs)
        raise RuntimeError('summary unavailable')
    agent = Agent(ROOT, store, model=unavailable)
    with pytest.raises(ContextBudgetExceeded):
        agent.compact_memory(state, 'search')
    assert len(calls) == 1
    assert state['role_memory']['search']['memory_upto'] == 0
    assert state['role_memory']['search']['memory'] == before
    assert not agent.needs_compaction(state, 'search')
    assert len(state['messages']) == 9
