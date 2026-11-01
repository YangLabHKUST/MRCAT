"""Native coding contracts, bounded recovery and execution-backed publication."""
import json
from types import SimpleNamespace

import pytest

from mrcat.agent import Agent
from mrcat.coding_agent import CodingAgentNodes
from mrcat.coding_protocol import CODING_TOOLS, coding_call
from mrcat.execution import CodeExecutor
from mrcat.model import llm_gateway as gateway
from test_agent import ROOT, create, decision, native_reply, journal_view
from test_coding_graph import CodingModel


@pytest.mark.parametrize('provider', ['openai', 'deepseek', 'anthropic'])
@pytest.mark.parametrize('sdk', [False, True])
@pytest.mark.parametrize('count', [1, 2])
def test_native_tools_keep_real_ids_and_exact_source(monkeypatch, provider, sdk, count):
    args = dict(language='python', purpose='compute', content='print("quotes\\nvalue")')
    message = json.loads(native_reply(dict(tool='run', **args)))
    history = [dict(role='system', content='system'), dict(role='user', content='task'), message,
               dict(role='tool', tool_call_id=message['tool_calls'][0]['id'], content='actual output')]
    response = (dict(content=[dict(type='tool_use', id='provider-call', name='run', input=args)])
                if provider == 'anthropic' else dict(choices=[dict(message=dict(role='assistant', content=None,
                    tool_calls=[dict(id='provider-call', type='function', function=dict(name='run', arguments=json.dumps(args)))]))]))
    if count == 2:
        from copy import deepcopy
        calls = response['content'] if provider == 'anthropic' else response['choices'][0]['message']['tool_calls']
        calls.append(deepcopy(calls[0]))
        calls[1]['id'] = 'provider-call-2'
    options = dict(system='system', user='task', model='fixture', temperature=0, max_tokens=256,
                   tools=CODING_TOOLS, request_messages=history, thinking=False)
    if sdk:
        requests = []
        def create_response(**kwargs):
            requests.append(kwargs)
            return SimpleNamespace(**response)
        for name in ['_wait_for_rate_limit', '_record_provider_success', '_check_provider_error', '_check_output_complete']:
            monkeypatch.setattr(gateway, name, lambda *a, **k: None)
        monkeypatch.setattr(gateway, 'current_provider', lambda _: provider)
        monkeypatch.setattr(gateway, '_get_api_key', lambda _: 'fixture')
        monkeypatch.setattr(gateway, 'current_retries', lambda _: 0)
        if provider == 'anthropic':
            import anthropic
            monkeypatch.setattr(anthropic, 'Anthropic', lambda **_: SimpleNamespace(messages=SimpleNamespace(create=create_response)))
            monkeypatch.setattr(gateway, '_anthropic_sdk_base_url', lambda _: 'https://example.invalid')
            raw = gateway._call_anthropic_sdk(**options, timeout=1, agent_config=None)
        else:
            import openai
            monkeypatch.setattr(openai, 'OpenAI', lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_response))))
            monkeypatch.setattr(gateway, '_openai_compatible_base_url', lambda _: 'https://example.invalid')
            raw = gateway._call_openai_compatible_sdk(**options, timeout=1, agent_config=None)
        payload = requests[0]
    else:
        payload = json.loads(gateway._build_payload(**options, provider=provider))
        raw = gateway._extract_tool_message(response, CODING_TOOLS, provider=provider)
    decoded = json.loads(raw)
    assert [call['id'] for call in decoded['tool_calls']] == ['provider-call', 'provider-call-2'][:count]
    assert coding_call(decoded['tool_calls'][0]) == dict(tool='run', **args)
    if provider == 'anthropic':
        assert payload['tool_choice'] == dict(type='any')
        assert payload['messages'][-1]['content'][0]['tool_use_id'] == message['tool_calls'][0]['id']
    else:
        assert payload['tools'] == CODING_TOOLS
        assert payload['tool_choice'] == 'required' and 'parallel_tool_calls' not in payload
        assert payload['messages'] == history


def test_tool_content_and_multiple_calls_never_become_code():
    for message in [dict(content='{"tool":"run","content":"print(42)"}'),
                    dict(content=None, tool_calls=json.loads(native_reply(dict(tool='read', path='x')))['tool_calls'] * 2)]:
        with pytest.raises(gateway.ProviderResponseError):
            gateway._extract_tool_message(dict(choices=[dict(message=message)]), CODING_TOOLS)


def test_invalid_arguments_return_to_same_loop_without_format_repair(tmp_path):
    store, sid = create(tmp_path)
    model = CodingModel([dict(tool='run', content='print(42)', language='wrong'),
                         dict(tool='run', content='from mrcat.tools import publish_result; publish_result("answer", {"value":6*7})'),
                         dict(tool='finish', outcome='complete', body='Verified 42')],
                        decisions=[decision('mr', 'propose')])
    done = Agent(ROOT, store, model=model, auto_confirm_plan=True).run(sid, 'Compute')
    calls = [c for c in model.calls if c['role'] == 'mr']
    assert done['status'] == 'completed' and len(calls) == 3
    second = json.loads(calls[1]['user'])
    assert 'Invalid value for language' in second['action_history'][-1]['content']
    assert all(c.get('tools') == CODING_TOOLS for c in calls)
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 1


def test_distinct_reads_can_exceed_the_old_inspection_allowance(tmp_path):
    store, sid = create(tmp_path)
    workspace = store.directory(sid) / 'workspace'
    paths = [workspace / f'input_{i}.txt' for i in range(15)]
    for i, path in enumerate(paths):
        path.write_text(str(i))
    model = CodingModel([
        *[dict(tool='read', path=str(path)) for path in paths],
        dict(tool='run', content='from mrcat.tools import publish_result; publish_result("answer", {"value": 42})'),
        dict(tool='finish', outcome='complete', body='Computed and published 42.'),
    ], decisions=[decision('mr', 'propose')])
    done = Agent(ROOT, store, model=model, auto_confirm_plan=True).run(sid, 'Inspect inputs and compute')
    assert done['status'] == 'completed'
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 1


def test_run_timeout_and_dependency_environment_are_task_local(tmp_path):
    store, sid = create(tmp_path)
    nodes = CodingAgentNodes(Agent(ROOT, store, execution_timeout=3600))
    workdir = store.directory(sid) / 'workspace'
    flow = nodes._run({}, workdir, dict(entries=[]), dict(tool='run', language='python', purpose='inspect',
        content='print(42)', timeout=900), {}, 1, 'check')
    assert flow['action']['timeout'] == 30
    source = 'import os; print(os.environ["R_LIBS"].split(os.pathsep)[0]); print(os.environ["PYTHONPATH"])'
    result = CodeExecutor(ROOT, store.directory(sid), strict_bash=True).execute(source, 'python', 'env')
    assert result['returncode'] == 0
    assert str(workdir / '.deps' / 'R') in result['stdout']
    assert str(workdir / '.deps' / 'python') in result['stdout']


def test_publish_rejects_changed_files_failed_runs_and_other_items(tmp_path):
    store, sid = create(tmp_path)
    nodes = CodingAgentNodes(Agent(ROOT, store))
    directory = store.directory(sid)
    workdir = directory / 'workspace'
    source = 'import json; from pathlib import Path; Path("result.json").write_text(json.dumps({"value":6*7}))'
    execution = CodeExecutor(ROOT, directory, strict_bash=True)
    execution.execute(source, 'python', 'good')
    task = dict(task_id='task1', item_run_ids=['good'])
    call = dict(tool='publish', name='answer', path='result.json', execution_id='good')
    result = nodes._host_tool({}, task, directory, workdir, call)
    record = json.loads((directory / 'results/task1/answer.json').read_text())
    assert result['ok'] and record['outputs']['value'] == 42 and record['execution_id'] == 'good'
    assert record['producer']['source_path'] == 'executions/good/code.py'
    (workdir / 'result.json').write_text('{"value":99}')
    with pytest.raises(ValueError, match='changed'):
        nodes._host_tool({}, task, directory, workdir, dict(call, name='changed'))
    with pytest.raises(ValueError, match='this item'):
        nodes._host_tool({}, dict(task_id='task2'), directory, workdir, call)
    execution.execute(source + '\nraise ValueError("failed fit")', 'python', 'bad')
    task['item_run_ids'].append('bad')
    with pytest.raises(ValueError, match='unsuccessful'):
        nodes._host_tool({}, task, directory, workdir, dict(call, execution_id='bad', name='bad'))


def test_provider_failure_preserves_open_task_without_review(tmp_path):
    from test_agent import Model
    store, sid = create(tmp_path)
    base = Model(decisions=[decision('mr', 'propose')])
    def model(**kwargs):
        if kwargs.get('tools'):
            raise gateway.ProviderResponseError('Provider returned no native call')
        return base(**kwargs)
    done = Agent(ROOT, store, model=model, auto_confirm_plan=True).run(sid, 'Compute')
    assert done['status'] == 'paused' and done['active_task']
    assert not done['task_history']
    assert not any(c['role'] == 'evaluate' for c in base.calls)
    assert 'no native call' in done['active_task']['executor_handoff']['body']


@pytest.mark.parametrize('provider', ['openai', 'anthropic'])
@pytest.mark.parametrize('case,expected', [('none', 'received 0'), ('multiple', 'duplicate tool call ID'),
    ('unknown', 'unadvertised tool'), ('missing_id', 'no valid ID')])
def test_invalid_native_response_retains_evidence(provider, case, expected):
    call = (dict(type='tool_use', id='real-id', name='read', input={'path': 'x'})
            if provider == 'anthropic' else
            dict(type='function', id='real-id', function=dict(name='read', arguments='{"path":"x"}')))
    if case == 'missing_id':
        call.pop('id')
    if case == 'unknown':
        (call if provider == 'anthropic' else call['function'])['name'] = 'invented_tool'
    calls = [] if case == 'none' else [call] * (2 if case == 'multiple' else 1)
    response = (dict(content=calls, stop_reason='tool_use') if provider == 'anthropic' else
                dict(choices=[dict(message=dict(content='', tool_calls=calls), finish_reason='tool_calls')]))
    with pytest.raises(gateway.ProviderResponseError, match=expected) as error:
        gateway._extract_tool_message(response, CODING_TOOLS, provider=provider)
    assert error.value.provider_response == response


def test_model_failure_saves_redacted_provider_response(tmp_path, monkeypatch):
    store, sid = create(tmp_path)
    secret = 'fixture-private-credential'
    monkeypatch.setenv('FIXTURE_API_KEY', secret)
    response = dict(model='fixture', choices=[dict(message=dict(content='Echo '+secret), finish_reason='stop')],
                    metadata={'api_key': 'credential-not-in-environment'})
    def model(**kwargs):
        return gateway._extract_tool_message(response, CODING_TOOLS)
    agent = Agent(ROOT, store, model=model)
    with pytest.raises(gateway.ProviderResponseError, match='received 0'):
        agent._call(store.load(sid), 'mr', 'Native tool test', '{}', tools=CODING_TOOLS)
    directory = next((store.directory(sid) / 'llm').iterdir())
    saved = json.loads((directory / 'provider_response.json').read_text())
    assert saved['choices'][0]['message']['content'] == 'Echo [REDACTED]'
    assert saved['metadata']['api_key'] == '[REDACTED]'
    error = json.loads((directory / 'error.json').read_text())
    assert error['provider_response'].endswith('/provider_response.json')
    assert secret not in (directory / 'error.json').read_text()
    assert not (directory / 'response.txt').exists()


def test_retired_history_call_is_rejected_by_native_transport():
    message = json.loads(native_reply(dict(tool='history', start=0, limit=50)))
    with pytest.raises(gateway.ProviderResponseError, match='unadvertised tool'):
        gateway._extract_tool_message(dict(choices=[dict(message=message)]), CODING_TOOLS)
    with pytest.raises(ValueError, match='Unknown coding tool'):
        coding_call(message['tool_calls'][0])


@pytest.mark.parametrize('review', [None,
    dict(route='execute', accept_item=True, reason='Accepted.'),
    dict(route='replan', accept_item=False, reason='Change the plan.'),
])
def test_non_rejected_review_does_not_instruct_same_item_repair(review):
    from mrcat.coding_protocol import action_messages

    assistant = json.loads(native_reply(dict(tool='read', path='input.txt')))
    history = [assistant, dict(role='tool', tool_call_id=assistant['tool_calls'][0]['id'],
                              content='{"ok": true, "content": "42"}')]
    context = dict(evaluation=review, action_history=history, execution_feedback='Preserve saved files.')
    messages = action_messages('system', json.dumps(context))
    assert messages[2:-1] == history
    assert json.loads(messages[1]['content'])['evaluation'] == review
    assert messages[-1]['content'] == 'Current execution feedback: Preserve saved files.'
