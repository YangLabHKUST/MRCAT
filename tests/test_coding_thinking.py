"""Thinking survives native tool calls, checkpointing and subsequent requests."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from mrcat.agent import Agent
from mrcat.runtime.coding_agent import CodingAgentNodes
from mrcat.runtime.coding_protocol import CODING_TOOLS, coding_history, action_messages
from mrcat.model import llm_gateway as gateway
from test_agent import ROOT, create, native_reply
from test_context_budget import coding_history as seeded_history


@pytest.mark.parametrize('provider,thinking', [('deepseek', True), ('openai', False), ('anthropic', False)])
def test_coding_enables_deepseek_thinking_only(tmp_path, monkeypatch, provider, thinking):
    from mrcat.config import loader
    calls=[]
    monkeypatch.setattr(loader, 'load_repo_config', lambda **_: SimpleNamespace(config=object()))
    monkeypatch.setattr(gateway, 'current_provider', lambda _: provider)
    monkeypatch.setattr(gateway, 'call_text', lambda **kwargs: calls.append(kwargs) or '{}')
    store, _ = create(tmp_path)
    agent=Agent(ROOT,store)
    agent._model(role='mr',system='coding',user='{}',tools=CODING_TOOLS)
    agent._model(role='evaluate',system='review',user='{}',structured_action=True)
    agent._model(role='memory',system='summary',user='{}',structured_action=True)
    assert calls[0]['thinking'] is thinking
    assert calls[1]['thinking'] is False and calls[2]['thinking'] is False


@pytest.mark.parametrize('sdk', [False, True])
def test_deepseek_enables_thinking_and_preserves_reasoning_across_calls(monkeypatch,sdk):
    legacy=json.loads(native_reply(dict(tool='read',path='old')))
    previous=json.loads(native_reply(dict(tool='read',path='current')))
    previous['reasoning_content']='fixture reasoning from the provider'
    history=[dict(role='system',content='system'),dict(role='user',content='task'),legacy,
             dict(role='tool',tool_call_id=legacy['tool_calls'][0]['id'],content='old result'),previous,
             dict(role='tool',tool_call_id=previous['tool_calls'][0]['id'],content='new result')]
    original=deepcopy(history)
    message=json.loads(native_reply(dict(tool='read',path='next')))
    message['tool_calls'].extend(json.loads(native_reply(dict(tool='read',path='another')))['tool_calls'])
    message['reasoning_content']='fixture reasoning for two calls'
    response=dict(choices=[dict(message=message)])
    options=dict(system='system',user='task',model='fixture',temperature=0,max_tokens=256,
                 tools=CODING_TOOLS,request_messages=history,thinking=True)
    if sdk:
        import openai
        requests=[]
        def respond(**kwargs):
            if kwargs.get("tool_choice") != "auto":
                raise RuntimeError("Thinking mode does not support this tool_choice")
            requests.append(kwargs)
            return SimpleNamespace(**response)
        for name in ['_wait_for_rate_limit','_record_provider_success','_check_provider_error','_check_output_complete']:
            monkeypatch.setattr(gateway,name,lambda *a,**k:None)
        monkeypatch.setattr(gateway,'current_provider',lambda _:'deepseek')
        monkeypatch.setattr(gateway,'_get_api_key',lambda _:'fixture')
        monkeypatch.setattr(gateway,'current_retries',lambda _:0)
        monkeypatch.setattr(gateway,'_openai_compatible_base_url',lambda _:'https://example.invalid')
        monkeypatch.setattr(openai,'OpenAI',lambda **_:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=respond))))
        raw=gateway._call_openai_compatible_sdk(**options,timeout=1,agent_config=None)
        payload=requests[0]
        assert payload['extra_body']['thinking']==dict(type='enabled')
    else:
        payload=json.loads(gateway._build_payload(**options,provider='deepseek'))
        assert payload['thinking']==dict(type='enabled')
        raw=gateway._extract_tool_message(response,CODING_TOOLS,provider='deepseek')
    assert payload['tool_choice']=='auto'
    assert payload['tools']==CODING_TOOLS
    assert payload['messages'][2]['reasoning_content']==''
    assert payload['messages'][4]['reasoning_content']==previous['reasoning_content']
    assert json.loads(raw)==message
    assert history==original


def test_reasoning_survives_checkpoint_and_history_projection(tmp_path):
    agent,state,journal=seeded_history(tmp_path,count=0)
    message=json.loads(native_reply(dict(tool='read',path='a')))
    message['tool_calls'].extend(json.loads(native_reply(dict(tool='read',path='b')))['tool_calls'])
    message['reasoning_content']='fixture reasoning retained verbatim'
    journal['pending_turn']=dict(message=message,index=0,start=0,action_ids=['a','b'])
    nodes=CodingAgentNodes(agent)
    for i in range(2):
        nodes._append(journal,dict(step=i+1,tool='read',result=dict(ok=True,content=str(i))))
    journal['step']=2
    agent.store.save(state)
    saved=agent.store.load(state['session_id'])['active_task']['coding']['fit']
    history=coding_history(saved['entries'])
    assert history[0]==message and len(history)==3
    messages=action_messages('system',json.dumps(dict(action_history=history)))
    assert messages[2]['reasoning_content']==message['reasoning_content']
    assert [r['tool_call_id'] for r in messages[3:]]==[c['id'] for c in message['tool_calls']]
