"""Native action transport is opt-in for Custom; existing model requests remain identical."""
import json
from types import SimpleNamespace

from mrcat.model import llm_gateway as gateway
from mrcat.agent import Agent
# Arbitrary tool schema for gateway transport tests, independent of the agent loop.
ACTION_TOOL = dict(type='function', function=dict(name='submit_action', description='Test transport',
    parameters=dict(type='object', properties=dict(type=dict(type='string'), body=dict(type='string')))))
import pytest
from test_agent import ROOT, Model, create


def test_shell_options_are_custom_only_and_do_not_rewrite_source(tmp_path):
    from mrcat.execution import CodeExecutor
    from mrcat.codeact import CodeActNodes
    from mrcat.coding_agent import CodingAgentNodes
    source = 'false | cat\necho reached'
    for nodes, expected in [(CodeActNodes, 0), (CodingAgentNodes, 1)]:
        directory = tmp_path / nodes.__name__
        result = CodeExecutor(ROOT, directory, strict_bash=nodes.strict_bash).execute(source, 'bash', 'probe')
        assert result['returncode'] == expected
        assert ('reached' in result['stdout']) == (expected == 0)
        assert (directory / result['source_path']).read_text() == source


def test_http_native_action_only_changes_explicitly_opted_in_payload():
    args = dict(provider='deepseek', system='Return JSON.', user='Compute.',
                model='fixture', temperature=0, max_tokens=128)
    before = json.loads(gateway._build_payload(**args))
    after = json.loads(gateway._build_payload(**args, action_tool=ACTION_TOOL))
    assert 'tools' not in before
    assert after.pop('tools') == [ACTION_TOOL]
    assert after.pop('tool_choice')['function']['name'] == 'submit_action'
    assert after == before


def test_sdk_native_action_only_changes_explicitly_opted_in_request(monkeypatch):
    import openai
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{}',
            tool_calls=[SimpleNamespace(type='function', function=SimpleNamespace(name='submit_action', arguments='{}'))]))])
    monkeypatch.setattr(openai, 'OpenAI', lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    for name in ['_wait_for_rate_limit', '_record_provider_success', '_check_provider_error', '_check_output_complete']:
        monkeypatch.setattr(gateway, name, lambda *a, **k: None)
    monkeypatch.setattr(gateway, '_get_api_key', lambda _: 'fixture')
    monkeypatch.setattr(gateway, '_openai_compatible_base_url', lambda _: 'https://example.invalid')
    monkeypatch.setattr(gateway, 'current_retries', lambda _: 0)
    args = dict(system='Return JSON.', user='Compute.', model='fixture', temperature=0,
                max_tokens=128, timeout=10, agent_config=None, thinking=None)
    gateway._call_openai_compatible_sdk(**args)
    gateway._call_openai_compatible_sdk(**args, action_tool=ACTION_TOOL)
    assert requests[1].pop('tools') == [ACTION_TOOL]
    assert requests[1].pop('tool_choice')['function']['name'] == 'submit_action'
    assert requests[0] == requests[1]


def test_agent_default_model_does_not_enable_structured_action_for_other_calls(tmp_path, monkeypatch):
    from mrcat.config import loader
    calls = []
    monkeypatch.setattr(loader, 'load_repo_config', lambda **_: SimpleNamespace(config=object()))
    monkeypatch.setattr(gateway, 'current_provider', lambda _: 'deepseek')
    monkeypatch.setattr(gateway, 'call_text', lambda **kwargs: calls.append(kwargs) or '{}')
    store, sid = create(tmp_path)
    agent = Agent(ROOT, store)
    agent._model(role='mr', system='skill', user='{}')
    agent._model(role='evaluate', system='review', user='{}', structured_action=True)
    assert 'action_tool' not in calls[0] and 'thinking' not in calls[0]
    from mrcat.coding_protocol import REVIEW_TOOL
    assert calls[1]['action_tool'] == REVIEW_TOOL and calls[1]['thinking'] is False


@pytest.mark.parametrize('calls', [[], [{'type':'function','function':{'name':'wrong','arguments':'{}'}}],
    [{'type':'function','function':{'name':'submit_action','arguments':'{}'}}] * 2])
def test_native_actions_reject_missing_wrong_or_multiple_calls(calls):
    response = {'choices':[{'message':{'content':'{"type":"execute","body":"print(1)"}', 'tool_calls':calls}}]}
    with pytest.raises(gateway.ProviderResponseError):
        gateway._extract_action_arguments(response, 'submit_action')


def test_native_http_arguments_preserve_code_without_reading_content():
    arguments = json.dumps({'type':'execute','language':'python','body':'print("quoted\\nvalue")'})
    response = {'choices':[{'message':{'content':'untrusted alternative', 'tool_calls':[
        {'type':'function','function':{'name':'submit_action','arguments':arguments}}]}}]}
    assert gateway._extract_action_arguments(response, 'submit_action') == arguments


def test_action_messages_replays_saved_snapshot_without_rereading_files():
    from mrcat.coding_protocol import action_messages
    history = [{'role':'assistant','content':None,'tool_calls':[{'id':'run1','type':'function',
        'function':{'name':'submit_action','arguments':json.dumps(dict(type='execute',
        language='python',body='print(8)',message='Check the result'))}}]},
        {'role':'tool','tool_call_id':'run1','content':json.dumps(dict(stdout='8',returncode=0))},
        {'role':'user','content':'Keep the same inputs'}]
    messages = action_messages('system', json.dumps(dict(work_request='Compute', action_history=history)))
    assert messages[2:] == history
    assert json.loads(messages[1]['content']) == dict(work_request='Compute')


def test_http_replays_supplied_native_messages_without_changing_default():
    messages = [{'role':'system','content':'system'}, {'role':'user','content':'request'},
                {'role':'assistant','content':None,'tool_calls':[{'id':'run1','type':'function',
                 'function':{'name':'submit_action','arguments':'{}'}}]},
                {'role':'tool','tool_call_id':'run1','content':'actual observation'}]
    payload = json.loads(gateway._build_payload(provider='deepseek', system='unused', user='unused',
        model='fixture', temperature=0, max_tokens=128, action_tool=ACTION_TOOL, request_messages=messages))
    assert payload['messages'] == messages


@pytest.mark.parametrize('sdk', [False, True])
def test_anthropic_native_tool_payload_and_response_preserve_history(monkeypatch, sdk):
    history = [{'role':'system','content':'system'}, {'role':'user','content':'request'},
        {'role':'assistant','content':None,'tool_calls':[{'id':'run1','type':'function',
        'function':{'name':'submit_action','arguments':'{"type":"execute","body":"print(8)"}'}}]},
        {'role':'tool','tool_call_id':'run1','content':'actual output 8'},
        {'role':'user','content':'Keep the inputs'}]
    args = dict(system='system', user='request', model='fixture', temperature=0, max_tokens=128)
    response = dict(content=[dict(type='text', text='I will verify the saved result.'),
        dict(type='tool_use', id='new', name='submit_action', input=dict(type='execute', body='print(9)'))])
    if sdk:
        import anthropic
        requests = []
        monkeypatch.setattr(anthropic, 'Anthropic', lambda **_: SimpleNamespace(
            messages=SimpleNamespace(create=lambda **kw: requests.append(kw) or SimpleNamespace(**response))))
        for name in ['_wait_for_rate_limit', '_record_provider_success', '_check_provider_error', '_check_output_complete']:
            monkeypatch.setattr(gateway, name, lambda *a, **k: None)
        monkeypatch.setattr(gateway, '_get_api_key', lambda _: 'fixture')
        monkeypatch.setattr(gateway, '_anthropic_sdk_base_url', lambda _: 'https://example.invalid')
        monkeypatch.setattr(gateway, 'current_retries', lambda _: 0)
        # Default SDK behavior is verified by the existing gateway tests.
        output = gateway._call_anthropic_sdk(**args, timeout=10, agent_config=None, thinking=False,
            action_tool=ACTION_TOOL, request_messages=history)
        assert json.loads(output) == dict(type='execute', body='print(9)')
        payload = requests[0]
    else:
        default = json.loads(gateway._build_payload(**args, provider='anthropic'))
        assert 'tools' not in default
        assert default['messages'] == [dict(role='user', content='request')]
        payload = json.loads(gateway._build_payload(**args, provider='anthropic',
            action_tool=ACTION_TOOL, request_messages=history))
        assert json.loads(gateway._extract_action_arguments(response, 'submit_action', provider='anthropic'))['body'] == 'print(9)'
    assert payload['tools'][0]['input_schema'] == ACTION_TOOL['function']['parameters']
    assert payload['tool_choice'] == dict(type='tool', name='submit_action', disable_parallel_tool_use=True)
    assert payload['messages'][1]['content'][0] == dict(type='tool_use', id='run1', name='submit_action',
        input=dict(type='execute', body='print(8)'))
    assert payload['messages'][2]['content'][0] == dict(type='tool_result', tool_use_id='run1', content='actual output 8')
    assert payload['messages'][3] == dict(role='user', content='Keep the inputs')


@pytest.mark.parametrize('blocks', [[], [dict(type='text', text='{"type":"execute"}')],
    [dict(type='tool_use',name='wrong',input={})],
    [dict(type='tool_use',name='submit_action',input={})] * 2,
    [dict(type='tool_use',name='submit_action',input='{}')]])
def test_anthropic_rejects_text_multiple_or_wrong_tool_responses(blocks):
    with pytest.raises(gateway.ProviderResponseError):
        gateway._extract_action_arguments(dict(content=blocks), 'submit_action', provider='anthropic')


def test_custom_review_uses_native_schema_without_changing_skill_review(tmp_path,monkeypatch):
    from mrcat.config import loader
    from mrcat.coding_protocol import REVIEW_TOOL
    calls=[]
    monkeypatch.setattr(loader,'load_repo_config',lambda **_:SimpleNamespace(config=object()))
    monkeypatch.setattr(gateway,'current_provider',lambda _:'anthropic')
    monkeypatch.setattr(gateway,'call_text',lambda **kwargs:calls.append(kwargs) or '{}')
    store,sid=create(tmp_path);agent=Agent(ROOT,store)
    agent._model(role='evaluate',system='review',user='{}')
    agent._model(role='evaluate',system='review',user='{}',structured_action=True)
    assert 'action_tool' not in calls[0]
    assert calls[1]['action_tool']==REVIEW_TOOL
    assert 'submit_review' in calls[1]['system']


def test_custom_summary_uses_native_schema_without_changing_other_memory(tmp_path,monkeypatch):
    from mrcat.config import loader
    from mrcat.coding_protocol import SUMMARY_TOOL
    calls=[]
    monkeypatch.setattr(loader,'load_repo_config',lambda **_:SimpleNamespace(config=object()))
    monkeypatch.setattr(gateway,'current_provider',lambda _:'anthropic')
    monkeypatch.setattr(gateway,'call_text',lambda **kwargs:calls.append(kwargs) or '{}')
    store,sid=create(tmp_path);agent=Agent(ROOT,store)
    agent._model(role='memory',system='summary',user='{}')
    agent._model(role='memory',system='summary',user='{}',structured_action=True)
    assert 'action_tool' not in calls[0]
    assert calls[1]['action_tool']==SUMMARY_TOOL
