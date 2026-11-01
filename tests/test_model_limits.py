"""Reject truncated model output before parsing or executing any fragment."""
import json
import sys
from types import SimpleNamespace

import pytest

from mrcat.model import llm_gateway as gateway
from mrcat.agent import Agent
from test_agent import ROOT, Model, action, create, decision, verified_value


@pytest.fixture(autouse=True)
def isolated_gateway(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'deepseek')
    monkeypatch.setenv('LLM_BACKEND', 'http')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key-only')
    monkeypatch.setenv('DEEPSEEK_RETRY_COUNT', '1')
    monkeypatch.delenv('MRCAT_MAX_OUTPUT_TOKENS', raising=False)
    monkeypatch.delenv('MRCAT_MAX_RETRY_OUTPUT_TOKENS', raising=False)
    monkeypatch.setattr(gateway, '_check_provider_circuit', lambda *a: None)
    monkeypatch.setattr(gateway, '_wait_for_rate_limit', lambda *a: None)


def response(text='', reason='length'):
    return {'choices': [{'message': {'content': text}, 'finish_reason': reason}],
            'usage': {'prompt_tokens': 5, 'completion_tokens': 10}}


def http_responses(monkeypatch, bodies):
    bodies = iter(bodies)
    calls = []

    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps(next(bodies)).encode()

    def urlopen(request, **kwargs):
        calls.append(json.loads(request.data))
        return Reply()

    monkeypatch.setattr(gateway.urllib.request, 'urlopen', urlopen)
    return calls


@pytest.mark.parametrize('body', [response(), response('Partial plan or code'),
    {'stop_reason': 'max_tokens', 'content': [{'type': 'text', 'text': 'Partial'}]},
    {'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'}, 'output_text': 'Partial'}])
def test_http_truncation_is_not_empty_text_retry_or_provider_failure(monkeypatch, body):
    calls = http_responses(monkeypatch, [body])
    failures = []
    monkeypatch.setattr(gateway, '_record_provider_failure', lambda *a: failures.append(True))
    with pytest.raises(gateway.OutputTruncatedError, match='partial output was discarded'):
        gateway.call_text('system', 'user', max_tokens=32768)
    assert len(calls) == 1 and failures == []


@pytest.mark.parametrize('provider', ['deepseek', 'anthropic'])
def test_explicit_provider_error_is_not_retried_as_empty_text(monkeypatch, provider):
    monkeypatch.setenv('LLM_PROVIDER', provider)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key-only')
    calls = http_responses(monkeypatch, [{'error': {'message': 'xxx service timeout'}}])
    failures = []
    monkeypatch.setattr(gateway, '_record_provider_failure', lambda *a: failures.append(True))
    with pytest.raises(gateway.ProviderResponseError, match='xxx service timeout'):
        gateway.call_text('xxx', 'xxx')
    assert len(calls) == 1 and failures == [True]


def test_empty_completion_can_still_retry(monkeypatch):
    calls = http_responses(monkeypatch, [{'choices': []}, response('xxx', 'stop')])
    assert gateway.call_text('xxx', 'xxx') == 'xxx'
    assert len(calls) == 2


@pytest.mark.parametrize('provider', ['deepseek', 'anthropic'])
def test_sdk_truncation_does_not_fall_back_to_http(monkeypatch, provider):
    monkeypatch.setenv('LLM_BACKEND', 'sdk')
    monkeypatch.setenv('LLM_PROVIDER', provider)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key-only')
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if provider == 'anthropic':
            return SimpleNamespace(stop_reason='max_tokens', content=[], usage=None)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='length')], usage=None)

    client = SimpleNamespace(messages=SimpleNamespace(create=create),
                             chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    module, constructor = ('anthropic', 'Anthropic') if provider == 'anthropic' else ('openai', 'OpenAI')
    monkeypatch.setitem(sys.modules, module, SimpleNamespace(**{constructor: lambda **kwargs: client}))
    monkeypatch.setattr(gateway, '_call_text_http', lambda **kwargs: pytest.fail('Unexpected HTTP fallback'))
    with pytest.raises(gateway.OutputTruncatedError):
        gateway.call_text('system', 'user', max_tokens=32768)
    assert len(calls) == 1


@pytest.mark.parametrize('role', ['manager', 'planner', 'memory', 'evaluate', 'finalize', 'mr', 'search', 'report'])
def test_every_role_retries_truncation_once_with_larger_budget(monkeypatch, tmp_path, role):
    calls = http_responses(monkeypatch, [response('partial'), response('Complete response', 'stop')])
    store, _ = create(tmp_path)
    text = Agent(ROOT, store)._model(role=role, system='system', user='user')
    assert text == 'Complete response'
    assert [c['max_tokens'] for c in calls] == [32768, 65536]
    assert calls[0]['messages'] == calls[1]['messages']


@pytest.mark.parametrize('initial,cap,expected', [(20000, 30000, [20000, 30000]),
    (20000, 20000, [20000]), (70000, 65536, [70000])])
def test_configured_retry_budget_is_bounded(monkeypatch, tmp_path, initial, cap, expected):
    monkeypatch.setenv('MRCAT_MAX_OUTPUT_TOKENS', str(initial))
    monkeypatch.setenv('MRCAT_MAX_RETRY_OUTPUT_TOKENS', str(cap))
    calls = http_responses(monkeypatch, [response(), response()])
    store, _ = create(tmp_path)
    with pytest.raises(gateway.OutputTruncatedError):
        Agent(ROOT, store)._model(role='planner', system='system', user='user')
    assert [c['max_tokens'] for c in calls] == expected


def test_repeated_truncation_has_only_two_provider_calls(monkeypatch, tmp_path):
    calls = http_responses(monkeypatch, [response(), response('partial')])
    store, _ = create(tmp_path)
    with pytest.raises(gateway.OutputTruncatedError):
        Agent(ROOT, store)._model(role='planner', system='system', user='user')
    assert [c['max_tokens'] for c in calls] == [32768, 65536]


def test_nontruncated_empty_response_keeps_existing_retry(monkeypatch):
    calls = http_responses(monkeypatch, [response('', 'stop'), response('Complete', 'stop')])
    monkeypatch.setattr(gateway.time, 'sleep', lambda *a: None)
    assert gateway.call_text('system', 'user', max_tokens=32768) == 'Complete'
    assert [c['max_tokens'] for c in calls] == [32768, 32768]


def test_executor_truncation_preserves_active_task_and_does_not_execute(monkeypatch, tmp_path):
    store, sid = create(tmp_path)
    model = Model(decisions=[decision('mr', 'propose')])
    Agent(ROOT, store, model=model).run(sid, 'Plan the analysis')
    base = Model(decisions=[decision('mr', 'confirm')])

    def truncated(**kwargs):
        if kwargs['role'] == 'mr':
            raise gateway.OutputTruncatedError('Output truncated')
        return base(**kwargs)

    paused = Agent(ROOT, store, model=truncated).run(sid, 'yes')
    assert paused['status'] == 'paused' and paused['active_task']['status'] == 'paused'
    assert paused['task_history'] == []
    assert not any(e['type'] == 'code_execution' for e in paused['events'])
    task_id = paused['active_task']['task_id']
    resumed = Agent(ROOT, store, model=Model([verified_value(), 'Completed.'], decisions=[decision('mr', 'continue')])).run(sid, 'Continue')
    assert resumed['status'] == 'completed'
    assert resumed['task_history'][0]['task_id'] == task_id


def test_planner_truncation_does_not_publish_partial_plan(tmp_path):
    store, sid = create(tmp_path)
    base = Model(decisions=[decision('mr', 'propose')])

    def truncated(**kwargs):
        if kwargs['role'] == 'planner':
            raise gateway.OutputTruncatedError('Output truncated')
        return base(**kwargs)

    paused = Agent(ROOT, store, model=truncated).run(sid, 'Plan the analysis')
    assert paused['status'] == 'paused'
    assert paused['plan'] == '' and paused['active_task'] is None
    assert not any(e['type'] == 'plan_updated' for e in paused['events'])
    assert list((store.directory(sid) / 'llm').glob('*/error.json'))


def sdk_response(body):
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=c.get('finish_reason'), message=SimpleNamespace(**c['message']))
        for c in body['choices']])


def test_alternative_choices_and_reasoning_never_join_the_program():
    body = response('print("selected")', 'stop')
    body['choices'][0]['message']['reasoning_content'] = 'print("not executable")'
    body['choices'].append(response('print("alternative")', 'stop')['choices'][0])
    assert gateway._extract_openai_compatible_text(body) == 'print("selected")'
    assert gateway._extract_openai_sdk_text(sdk_response(body)) == 'print("selected")'


def test_empty_first_choice_does_not_fall_through_to_another_answer():
    body = response('', 'stop')
    body['choices'].append(response('must not execute', 'stop')['choices'][0])
    body['output_text'] = 'must not use fallback'
    with pytest.raises(RuntimeError, match='first choice'):
        gateway._extract_openai_compatible_text(body)
    sdk = sdk_response(body)
    sdk.output_text = body['output_text']
    assert gateway._extract_openai_sdk_text(sdk) == ''


@pytest.mark.parametrize('first,second,raises', [('stop', 'length', False), ('length', 'stop', True)])
def test_truncation_check_uses_the_same_choice_as_extraction(first, second, raises):
    body = response('first', first)
    body['choices'].append(response('second', second)['choices'][0])
    for value in [body, sdk_response(body)]:
        if raises:
            with pytest.raises(gateway.OutputTruncatedError):
                gateway._check_output_complete(value)
        else:
            gateway._check_output_complete(value)


def test_content_parts_within_one_choice_are_retained():
    body = response([{'type': 'text', 'text': 'first line'}, {'type': 'text', 'text': 'second line'}], 'stop')
    assert gateway._extract_openai_compatible_text(body) == 'first line\nsecond line'
    assert gateway._extract_openai_sdk_text(sdk_response(body)) == 'first line\nsecond line'


@pytest.mark.parametrize('role', ['report_writer', 'report_judge'])
def test_report_uses_reporter_model_and_preserves_options_on_truncation_retry(tmp_path, monkeypatch, role):
    monkeypatch.setenv('REPORTER_MODEL', 'fixture-report-model')
    calls = http_responses(monkeypatch, [response('Partial'), response('Complete', 'stop')])
    store, sid = create(tmp_path)
    assert Agent(ROOT, store)._model(role=role, system='Report stage', user='Evidence') == 'Complete'
    assert [call['model'] for call in calls] == ['fixture-report-model', 'fixture-report-model']
    assert [call['max_tokens'] for call in calls] == [32768, 65536]
    if role == 'report_judge':
        assert all(call.get('thinking') == {'type': 'disabled'} for call in calls)
