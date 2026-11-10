"""Whole native turns execute, checkpoint and replay without dropping calls."""
import json
from copy import deepcopy

import pytest

from mrcat.agent import Agent
from mrcat.runtime.coding_agent import CodingAgentNodes
from mrcat.runtime.coding_protocol import CODING_TOOLS, coding_history, coding_turns, coding_calls
from mrcat.model import llm_gateway as gateway
from mrcat.state.store import Store
from test_agent import ROOT, Model, create, decision, native_reply
from test_context_budget import coding_history as seeded_history


def batch(*calls, context=None):
    messages = [json.loads(native_reply(call, context)) for call in calls]
    return dict(role='assistant', content='Inspect and compute.',
                tool_calls=[m['tool_calls'][0] for m in messages])


class BatchModel(Model):
    def __init__(self, turns, **kwargs):
        super().__init__(**kwargs)
        self.turns = iter(turns)
        self.sent = []

    def __call__(self, **kwargs):
        if kwargs['role'] != 'mr':
            return super().__call__(**kwargs)
        self.calls.append(kwargs)
        message = batch(*next(self.turns), context=json.loads(kwargs['user']))
        self.sent.append(message)
        return json.dumps(message)


def contexts(model):
    return [json.loads(c['user']) for c in model.calls if c['role'] == 'mr']


def journal(state):
    task = state.get('active_task') or state['task_history'][-1]
    return next(iter(task['coding'].values()))


def assert_turn(history, message):
    index = history.index(message)
    outputs = history[index + 1:index + 1 + len(message['tool_calls'])]
    assert [row['role'] for row in outputs] == ['tool'] * len(outputs)
    assert [row['tool_call_id'] for row in outputs] == [call['id'] for call in message['tool_calls']]
    return [json.loads(row['content']) for row in outputs]


@pytest.mark.parametrize('failure', [False, True])
def test_two_runs_finish_before_next_model_request(tmp_path, failure):
    store, sid = create(tmp_path)
    first = 'print("first")' + ('; raise ValueError("probe failed")' if failure else '')
    model = BatchModel([
        [dict(tool='run', content=first), dict(tool='run', content=(
            'from mrcat.tools import publish_result; publish_result("answer", {"value":42}); print("second")'))],
        [dict(tool='finish', outcome='complete', body='Computed 42.')],
    ], decisions=[decision('mr', 'propose')])
    done = Agent(ROOT, store, model=model, auto_confirm_plan=True).run(sid, 'Compute')
    assert done['status'] == 'completed'
    outputs = assert_turn(contexts(model)[1]['action_history'], model.sent[0])
    assert outputs[0]['ok'] is (not failure) and outputs[1]['ok']
    assert outputs[0]['stdout'].strip() == 'first' and outputs[1]['stdout'].strip() == 'second'
    assert outputs[0]['execution_id'] != outputs[1]['execution_id']
    assert len(contexts(model)) == 2
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 2
    assert 'pending_turn' not in journal(done)


def test_invalid_arguments_and_finish_do_not_drop_other_calls(tmp_path):
    store, sid = create(tmp_path)
    model = BatchModel([
        [dict(tool='run', language='wrong', content='print(0)'),
         dict(tool='finish', outcome='complete', body='Premature'),
         dict(tool='write', path='check.py', content='print(42)'),
         dict(tool='read', path='check.py')],
        [dict(tool='run', content='from mrcat.tools import publish_result; publish_result("answer", {"value":42})')],
        [dict(tool='finish', outcome='complete', body='Verified 42')],
    ], decisions=[decision('mr', 'propose')])
    done = Agent(ROOT, store, model=model, auto_confirm_plan=True).run(sid, 'Compute')
    assert done['status'] == 'completed'
    outputs = assert_turn(contexts(model)[1]['action_history'], model.sent[0])
    assert 'Invalid value for language' in outputs[0]['error']
    assert 'finish alone' in outputs[1]['error']
    assert outputs[2]['ok'] and 'print(42)' in outputs[3]['content']
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 1


def test_budget_settles_every_queued_call_without_executing_it(tmp_path):
    store, sid = create(tmp_path)
    model = BatchModel([[dict(tool='write', path='one', content='1'),
                         dict(tool='write', path='two', content='2')]],
                       decisions=[decision('mr', 'propose')])
    paused = Agent(ROOT, store, model=model, auto_confirm_plan=True, max_rounds=1).run(sid, 'Compute')
    assert paused['status'] == 'paused'
    entries = journal(paused)['entries']
    outputs = assert_turn(coding_history(entries), model.sent[0])
    assert outputs[0]['ok'] and outputs[1]['executed'] is False
    assert 'budget' in outputs[1]['error']
    assert not list((store.directory(sid) / 'workspace').rglob('two'))
    assert 'pending_turn' not in journal(paused)


@pytest.mark.parametrize('interrupt_at', ['host_receipt', 'run_receipt', 'run_before_start'])
def test_interrupted_batch_recovers_results_without_replaying_or_running_siblings(tmp_path, monkeypatch, interrupt_at):
    store, sid = create(tmp_path)
    original_host = CodingAgentNodes._host_tool_once
    original_observe = CodingAgentNodes.observe
    from mrcat.runtime.codeact import CodeActNodes
    original_execute = CodeActNodes.execute
    def host(self, state, task, directory, workdir, call, action_id):
        result = original_host(self, state, task, directory, workdir, call, action_id)
        raise KeyboardInterrupt('after host receipt')
    def observe(self, flow, state):
        raise KeyboardInterrupt('after run receipt')
    def execute(self, flow, state):
        raise KeyboardInterrupt('before process start')
    if interrupt_at == 'host_receipt':
        monkeypatch.setattr(CodingAgentNodes, '_host_tool_once', host)
        first = dict(tool='write', path='counter', content='1')
    else:
        if interrupt_at == 'run_receipt':
            monkeypatch.setattr(CodingAgentNodes, 'observe', observe)
        else:
            monkeypatch.setattr(CodeActNodes, 'execute', execute)
        first = dict(tool='run', content='from pathlib import Path; p=Path("counter"); p.write_text(str(int(p.read_text())+1) if p.exists() else "1")')
    model = BatchModel([[first, dict(tool='write', path='queued', content='must not run')]],
                       decisions=[decision('mr', 'propose')])
    with pytest.raises(KeyboardInterrupt):
        Agent(ROOT, store, model=model, auto_confirm_plan=True).run(sid, 'Compute')
    saved = Store(tmp_path).load(sid)
    assert 'pending_turn' in journal(saved)
    monkeypatch.setattr(CodingAgentNodes, '_host_tool_once', original_host)
    monkeypatch.setattr(CodingAgentNodes, 'observe', original_observe)
    monkeypatch.setattr(CodeActNodes, 'execute', original_execute)
    resumed_model = BatchModel([[dict(tool='run', content='from mrcat.tools import publish_result; publish_result("answer", {"value":42})')],
                                [dict(tool='finish', outcome='complete', body='Computed 42.')]],
                               decisions=[decision('mr', 'continue')])
    done = Agent(ROOT, Store(tmp_path), model=resumed_model).run(sid, 'Continue with a fresh computation')
    assert done['status'] == 'completed'
    outputs = assert_turn(contexts(resumed_model)[0]['action_history'], model.sent[0])
    assert outputs[0]['ok'] is (interrupt_at != 'run_before_start')
    assert outputs[1]['executed'] is False
    assert not list((store.directory(sid) / 'workspace').rglob('queued'))
    counters = list((store.directory(sid) / 'workspace').rglob('counter'))
    assert [p.read_text() for p in counters] == ([] if interrupt_at == 'run_before_start' else ['1'])
    assert 'pending_turn' not in journal(done)


def test_compaction_preserves_whole_multi_call_turns(tmp_path, monkeypatch):
    monkeypatch.setenv('MRCAT_CONTEXT_TOKENS', '32000')
    monkeypatch.setenv('MRCAT_MAX_OUTPUT_TOKENS', '2048')
    agent, state, saved = seeded_history(tmp_path, count=0)
    for i in range(40):
        message = batch(dict(tool='read', path=f'{i}-a'), dict(tool='read', path=f'{i}-b'))
        for j, call in enumerate(message['tool_calls']):
            saved['entries'].append(dict(step=2*i+j+1, tool='read', call_id=call['id'],
                **({'assistant': message} if j == 0 else {}),
                arguments=dict(path=f'{i}-{j}'), result=dict(ok=True, content='data ' * 320)))
    saved['step'] = 80
    original = deepcopy(saved['entries'])
    requests = []
    def summarize(**kwargs):
        context = json.loads(kwargs['user']); requests.append(context)
        turns = list(coding_turns(context['conversation']))
        assert all(len(turn) == 2 for _, turn in turns)
        return json.dumps(dict(objective='Compute', decisions='', completed='Read files', active='',
                               blockers='', next_steps='Compute', references='Saved files'))
    agent.model = summarize
    nodes = CodingAgentNodes(agent)
    assert nodes.needs_compaction(state)
    nodes.compact(state)
    assert requests and 0 < saved['summary_upto'] <= 78
    assert saved['summary_upto'] % 2 == 0
    assert saved['entries'] == original
    history = coding_history(saved['entries'][saved['summary_upto']:])
    assert_turn(history, original[saved['summary_upto']]['assistant'])
    assert not nodes.needs_compaction(state)


def test_duplicate_ids_reject_whole_envelope_before_dispatch():
    message = batch(dict(tool='read', path='a'), dict(tool='read', path='b'))
    message['tool_calls'][1]['id'] = message['tool_calls'][0]['id']
    with pytest.raises(ValueError, match='unique'):
        coding_calls(message)
    with pytest.raises(gateway.ProviderResponseError, match='duplicate'):
        gateway._extract_tool_message(dict(choices=[dict(message=message)]),
                                      CODING_TOOLS)


@pytest.mark.parametrize('provider', ['openai', 'deepseek', 'anthropic'])
def test_multi_call_history_reaches_provider_as_one_complete_turn(provider):
    message = batch(dict(tool='read', path='a'), dict(tool='read', path='b'))
    results = [dict(role='tool', tool_call_id=call['id'], content='{"ok":true}') for call in message['tool_calls']]
    history = [dict(role='system', content='system'), dict(role='user', content='task'), message, *results]
    payload = json.loads(gateway._build_payload(system='system', user='task', provider=provider,
        model='fixture', temperature=0, max_tokens=256, thinking=False, tools=CODING_TOOLS, request_messages=history))
    if provider == 'anthropic':
        assert len(payload['messages']) == 3
        assistant, user = payload['messages'][-2:]
        assert assistant['role'] == 'assistant' and user['role'] == 'user'
        calls = [b for b in assistant['content'] if b['type'] == 'tool_use']
        assert [b['id'] for b in calls] == [b['tool_use_id'] for b in user['content']]
        assert len(user['content']) == 2
    else:
        assert payload['messages'] == history


def test_repeated_invalid_arguments_remain_bounded_across_model_turns(tmp_path):
    store, sid = create(tmp_path)
    model = BatchModel([[dict(tool='run', language='wrong', content='print(0)')]] * 2,
                       decisions=[decision('mr', 'propose')])
    paused = Agent(ROOT, store, model=model, auto_confirm_plan=True).run(sid, 'Compute')
    assert paused['status'] == 'paused'
    assert len(contexts(model)) == 2
    assert len(journal(paused)['entries']) == 2
    assert not any(e['type'] == 'code_execution' for e in paused['events'])
