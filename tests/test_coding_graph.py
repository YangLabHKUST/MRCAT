"""The explicit coding executor uses checkpoints and real local tool execution."""
import json

import pytest

from mrcat.agent import Agent
from mrcat.coding_agent import CodingAgentNodes
from mrcat.graph import build_graph
from mrcat.store import Store
from test_agent import ROOT, Model, create, decision, native_reply


class CodingModel(Model):
    def __init__(self, calls, **kwargs):
        super().__init__(**kwargs)
        self.tool_calls = iter(calls)

    def __call__(self, **kwargs):
        if kwargs['role'] == 'mr':
            self.calls.append(kwargs)
            return native_reply(next(self.tool_calls), json.loads(kwargs['user']))
        return super().__call__(**kwargs)


def test_coding_loop_publishes_and_returns_to_review(tmp_path):
    store, sid = create(tmp_path)
    model = CodingModel([
        dict(tool='write', path='analysis.py', content='import json\nfrom pathlib import Path\nPath("result.json").write_text(json.dumps({"value": 6 * 7}))'),
        dict(tool='run', path='analysis.py', language='python'),
        dict(tool='publish', name='answer', path='result.json'),
        dict(tool='finish', outcome='complete', body='Verified 42; see published answer.'),
    ], decisions=[decision('mr', 'propose')])
    agent = Agent(ROOT, store, model=model, auto_confirm_plan=True)
    graph = dict(build_graph(agent).get_subgraphs())['mr']
    coding = dict(graph.get_subgraphs())['executor']
    assert {'model', 'tools', 'execute', 'observe', 'handoff'} <= set(coding.get_graph().nodes)
    done = agent.run(sid, 'Calculate 6 * 7 and publish the result')
    assert done['status'] == 'completed'
    task = done['task_history'][0]
    history = next(iter(task['coding'].values()))
    assert [e['tool'] for e in history['entries']] == ['write', 'run', 'publish', 'finish']
    assert [c['role'] for c in model.calls].count('evaluate') == 1
    assert not list(store.directory(sid).rglob('journal.json'))
    assert Store(tmp_path).load(sid)['task_history'][0]['coding'] == task['coding']
    assert task['item_run_ids']


def test_coding_continuation_keeps_workspace_and_history(tmp_path, monkeypatch):
    monkeypatch.setenv('MRCAT_MAX_ROUNDS', '1')
    store, sid = create(tmp_path)
    first = CodingModel([dict(tool='write', path='script.py', content='print(42)')],
                        decisions=[decision('mr', 'propose')])
    paused = Agent(ROOT, store, model=first, auto_confirm_plan=True).run(sid, 'Compute')
    assert paused['status'] == 'paused'
    task_id = paused['active_task']['task_id']
    second = CodingModel([dict(tool='run', path='script.py', language='python')],
                         decisions=[decision('mr', 'continue')])
    resumed = Agent(ROOT, Store(tmp_path), model=second).run(sid, 'Continue')
    task = resumed['active_task']
    assert task['task_id'] == task_id
    history = next(iter(task['coding'].values()))
    assert [e['tool'] for e in history['entries']] == ['write', 'run']
    context = json.loads(next(c['user'] for c in second.calls if c['role'] == 'mr'))
    assert context['action_history']


def test_tool_receipt_blocks_repeated_edit_and_restores_publication(tmp_path):
    store, sid = create(tmp_path)
    nodes = CodingAgentNodes(Agent(ROOT, store))
    state = store.load(sid)
    task = {'task_id': 'task1'}
    workdir = store.directory(sid) / 'workspace'
    script = workdir / 'script.py'
    script.write_text('old')
    call = dict(tool='edit', path='script.py', old='old', new='new')
    first = nodes._host_tool_once(state, task, store.directory(sid), workdir, call, 'edit1')
    assert first['ok']
    assert nodes._host_tool_once(state, task, store.directory(sid), workdir, call, 'edit1') == first
    assert script.read_text() == 'new'
    from mrcat.execution import CodeExecutor
    result = CodeExecutor(ROOT, store.directory(sid), strict_bash=True).execute(
        'from pathlib import Path; Path("result.json").write_text(\'{"value":42}\')',
        'python', 'run1', working_directory=workdir)
    task['item_run_ids'] = ['run1']
    call = dict(tool='publish', name='answer', path='result.json', execution_id='run1')
    result = nodes._host_tool_once(state, task, store.directory(sid), workdir, call, 'publish1')
    assert result['ok']
    task.pop('item_execution_ids')
    nodes._host_tool_once(state, task, store.directory(sid), workdir, call, 'publish1')
    assert result['execution_id'] in task['item_execution_ids']


def test_interrupted_publication_is_recovered_before_continuation(tmp_path, monkeypatch):
    store, sid = create(tmp_path)
    original = CodingAgentNodes._host_tool_once
    def publish_then_stop(self, state, task, directory, workdir, call, action_id):
        result = original(self, state, task, directory, workdir, call, action_id)
        if call['tool'] == 'publish':
            raise KeyboardInterrupt('stop after publication before checkpoint')
        return result
    monkeypatch.setattr(CodingAgentNodes, '_host_tool_once', publish_then_stop)
    first = CodingModel([
        dict(tool='run', content='import json; from pathlib import Path; Path("result.json").write_text(json.dumps({"value":42}))', language='python'),
        dict(tool='publish', name='answer', path='result.json'),
    ], decisions=[decision('mr', 'propose')])
    with pytest.raises(KeyboardInterrupt):
        Agent(ROOT, store, model=first, auto_confirm_plan=True).run(sid, 'Compute')
    result_path = next((store.directory(sid) / 'results/task1').glob('*.json'))
    before = result_path.read_bytes()
    monkeypatch.setattr(CodingAgentNodes, '_host_tool_once', original)
    second = CodingModel([dict(tool='finish', outcome='complete', body='Verified saved answer.')],
                         decisions=[decision('mr', 'continue')])
    done = Agent(ROOT, Store(tmp_path), model=second).run(sid, 'Continue')
    assert done['status'] == 'completed'
    assert result_path.read_bytes() == before
    assert any(e['type'] == 'coding_tool_recovered' for e in done['events'])
    assert 'pending_coding_tool' not in done
    journal = next(iter(done['task_history'][0]['coding'].values()))
    assert [e['tool'] for e in journal['entries']] == ['run', 'publish', 'finish']


def test_300_action_budget_and_restart_keep_all_edits_and_publish(tmp_path, monkeypatch):
    """Real filesystem tools cross the former 16/24/60 limits and a process boundary."""
    monkeypatch.delenv('MRCAT_MAX_ROUNDS', raising=False)
    store, sid = create(tmp_path)
    first = CodingModel([
        dict(tool='write', path='counter.py', content='import json\nfrom pathlib import Path\nvalue = 0\nprint(value)\nPath("result.json").write_text(json.dumps({"value":value}))\n'),
        *[dict(tool='edit', path='counter.py', old=f'value = {i}\n', new=f'value = {i+1}\n')
          for i in range(299)],
    ], decisions=[decision('mr', 'propose')])
    paused = Agent(ROOT, store, model=first, auto_confirm_plan=True).run(sid, 'Calculate and verify the counter.')
    assert paused['status'] == 'paused'
    task = paused['active_task']
    journal = next(iter(task['coding'].values()))
    assert journal['step'] == 300 and len(journal['entries']) == 300
    assert journal['entries'][1]['arguments']['old'] == 'value = 0\n'
    task_id = task['task_id']
    second = CodingModel([
        *[dict(tool='edit', path='counter.py', old=f'value = {i}\n', new=f'value = {i+1}\n')
          for i in range(299, 305)],
        dict(tool='run', path='counter.py', language='python'),
        dict(tool='publish', name='counter', path='result.json'),
        dict(tool='finish', outcome='complete', body='Verified 305 in the saved run and publication.'),
    ], decisions=[decision('mr', 'continue')])
    done = Agent(ROOT, Store(tmp_path), model=second).run(sid, 'Continue the same task.')
    assert done['status'] == 'completed'
    task = done['task_history'][0]
    assert task['task_id'] == task_id
    history = next(iter(task['coding'].values()))
    assert len(history['entries']) == 309
    context = json.loads(next(c['user'] for c in second.calls if c['role'] == 'mr'))
    assert len(context['action_history']) == 600
    run = next(e['details'] for e in done['events'] if e['type'] == 'code_execution')
    assert run['stdout'].strip() == '305'
    assert len(list((store.directory(sid) / 'results' / task_id).glob('counter.json'))) == 1


def test_rejected_handoff_returns_to_tools_before_review_acceptance(tmp_path):
    from mrcat.coding_protocol import action_messages

    store, sid = create(tmp_path)
    reason = 'Verify the saved value against the independent calculation before resubmitting.'
    model = CodingModel([
        dict(tool='run', content=(
            'from pathlib import Path; from mrcat.tools import publish_result; '
            'Path("answer.txt").write_text("42"); publish_result("answer", {"value": 42})')),
        dict(tool='finish', outcome='complete', body='Saved 42.'),
        dict(tool='run', content=(
            'from pathlib import Path; assert int(Path("answer.txt").read_text()) == 6 * 7; '
            'print("Independent verification passed")')),
        dict(tool='finish', outcome='complete', body='Verified saved 42 against 6 * 7.'),
    ], decisions=[decision('mr', 'propose')], evaluations=[
        dict(route='execute', accept_item=False, reason=reason),
        dict(route='execute', accept_item=True, reason='Independent check passed.'),
    ])
    done = Agent(ROOT, store, model=model, auto_confirm_plan=True).run(sid, 'Compute and verify')
    assert done['status'] == 'completed'
    calls = [call for call in model.calls if call['role'] == 'mr']
    assert len(calls) == 4
    resumed = calls[2]
    context = json.loads(resumed['user'])
    assert context['evaluation']['accept_item'] is False
    history = context['action_history']
    finish_result = json.loads(history[-1]['content'])
    assert finish_result['ok'] is True
    assert 'does not mean scientific acceptance' in finish_result['body']
    messages = action_messages(resumed['system'], resumed['user'])
    assert messages[2:2 + len(history)] == history
    assert messages[-1]['role'] == 'user' and reason in messages[-1]['content']
    assert 'Review has not accepted' in messages[-1]['content']
    assert 'evaluation' not in json.loads(messages[1]['content'])
    task = done['task_history'][0]
    entries = next(iter(task['coding'].values()))['entries']
    assert [entry['tool'] for entry in entries] == ['run', 'finish', 'run', 'finish']
    assert all(entry['result'].get('returncode') == 0 for entry in entries if entry['tool'] == 'run')
    assert [call['role'] for call in model.calls].count('planner') == 1
    assert [call['role'] for call in model.calls].count('evaluate') == 2
