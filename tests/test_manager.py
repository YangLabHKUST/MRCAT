"""Routing must not author a second plan or overwrite task memory."""
import json

import pytest

from mrcat.agent import Agent
from mrcat.memory import render_memory
from mrcat.manager import parse_decision
from test_agent import ROOT, Model, create, decision, verified_value


@pytest.mark.parametrize('route,action', [('search', 'run'), ('report', 'run'),
    ('mr', 'propose'), ('mr', 'revise'), ('mr', 'confirm'), ('mr', 'continue'), ('mr', 'cancel')])
def test_workflow_message_must_be_null(route, action):
    value = decision(route, action, effective_request='Requested work' if action in {'run','propose','revise'} else None)
    assert parse_decision(json.dumps(value)) == value
    for message in ('', '1. Manager invents an alternative plan.'):
        with pytest.raises(ValueError, match='message=null'):
            parse_decision(json.dumps(value | {'message': message}))


@pytest.mark.parametrize('message', [None, '', '   ', 42])
def test_respond_requires_an_actual_answer(message):
    with pytest.raises(ValueError, match='nonempty message'):
        parse_decision(json.dumps(decision('respond', 'respond') | {'message': message}))


def test_only_planner_plan_is_presented_and_confirmed(tmp_path):
    store, sid = create(tmp_path, 'Analyze the supplied files')
    wrong = '1. Switch to another outcome.\n2. Run a different method.'
    plan = '1. Use gwas-pair-prepare on the supplied QC files.\n2. Use mr-cml-ma on the prepared MRdat.'
    model = Model([verified_value(), 'Synthetic value available.'], decisions=[
        decision('mr', 'propose') | {'message': wrong},
        decision('mr', 'propose', description='Analyze the supplied files'),
        decision('mr', 'confirm')], plans=[plan])
    agent = Agent(ROOT, store, model=model)
    proposed = agent.run(sid, 'Analyze the supplied files')
    assert proposed['pending']['plan_items'][0]['title'] == plan
    assert proposed['pending']['plan'] == proposed['plan']
    assert proposed['pending']['question'] == 'Confirm the plan shown above, or describe the changes you want.'
    assert [e['content'] for e in proposed['events'] if e['type'] == 'plan_updated'] == [proposed['plan']]
    assert wrong not in json.dumps(proposed['events'])
    assert not any(e['type'] == 'assistant_message' for e in proposed['events'])
    assert [c['role'] for c in model.calls] == ['manager', 'manager', 'planner']
    assert 'message=null' in json.loads(model.calls[1]['user'])['format_error']
    completed = agent.run(sid, 'Confirm')
    assert completed['task_history'][0]['plan'] == proposed['plan']
    assert sum(c['role'] == 'planner' for c in model.calls) == 1


def test_discussion_preserves_proposal_and_memory_without_replanning(tmp_path):
    store, sid = create(tmp_path, 'Plan the analysis')
    explanation = 'The displayed plan uses your supplied files.'
    model = Model(decisions=[decision('mr', 'propose'),
        decision('respond', 'respond') | {'message': explanation}])
    agent = Agent(ROOT, store, model=model)
    before = agent.run(sid, 'Plan the analysis')
    memory_before = render_memory(store.load(sid))
    after = agent.run(sid, 'Why are these files used?')
    assert after['pending'] == before['pending']
    assert after['plan'] == before['plan']
    assert after['active_task'] is None and after['task_history'] == []
    assert after['status'] == 'waiting_user'
    assert render_memory(store.load(sid)) == memory_before
    assert [c['role'] for c in model.calls] == ['manager', 'planner', 'manager']
    assert after['events'][-1]['type'] == 'final'
    assert after['events'][-1]['content'] == explanation


@pytest.mark.parametrize('route', ['mr/confirm', 'unknown', None, [], {}])
def test_invalid_route_reports_field_and_legal_values(route):
    with pytest.raises(ValueError, match='Invalid route') as error:
        parse_decision(json.dumps(decision(route, 'confirm')))
    assert 'Allowed routes: respond, search, mr, report' in str(error.value)
    assert 'route="mr", action="confirm"' in str(error.value)


@pytest.mark.parametrize('action', ['run', 'mr/confirm', None, [], {}])
def test_invalid_action_reports_allowed_values_for_route(action):
    with pytest.raises(ValueError, match="Invalid action") as error:
        parse_decision(json.dumps(decision('mr', action)))
    assert 'propose, revise, confirm, continue, cancel' in str(error.value)


def test_bad_confirmation_is_corrected_before_any_execution(tmp_path):
    store, sid = create(tmp_path)
    model = Model([verified_value(), 'Completed.'], decisions=[decision('mr', 'propose'),
        decision('mr/confirm', 'confirm'), decision('mr', 'confirm')])
    agent = Agent(ROOT, store, model=model)
    before = agent.run(sid, 'Plan the analysis')
    done = agent.run(sid, 'yes')
    calls = [c for c in model.calls if c['role'] == 'manager']
    assert 'Invalid route' in json.loads(calls[-1]['user'])['format_error']
    assert done['task_history'][0]['plan'] == before['plan']
    assert [e['details']['route'] for e in done['events'] if e['type'] == 'manager_route'] == ['mr', 'mr']


def test_repeated_invalid_confirmation_preserves_plan_and_can_resume(tmp_path):
    store, sid = create(tmp_path)
    model = Model([verified_value(), 'Completed.'], decisions=[decision('mr', 'propose'),
        decision('mr/confirm', 'confirm'), decision('mr/confirm', 'confirm'), decision('mr', 'confirm')])
    agent = Agent(ROOT, store, model=model)
    before = agent.run(sid, 'Plan the analysis')
    stopped = agent.run(sid, 'yes')
    assert stopped['status'] == 'waiting_user'
    assert stopped['pending'] == before['pending'] and stopped['plan'] == before['plan']
    assert stopped['active_task'] is None and stopped['task_history'] == []
    assert not any(e['type'] == 'code_execution' for e in stopped['events'])
    assert 'Please retry' in stopped['messages'][-1]['content']
    done = Agent(ROOT, store, model=model).run(sid, 'yes')
    assert done['status'] == 'completed'
    assert done['task_history'][0]['plan'] == before['plan']
    assert sum(c['role'] == 'planner' for c in model.calls) == 1


def test_invalid_initial_route_pauses_without_starting_work(tmp_path):
    store, sid = create(tmp_path)
    model = Model(decisions=[decision('search/run', 'run'), decision('search/run', 'run')])
    stopped = Agent(ROOT, store, model=model).run(sid, 'Inspect files')
    assert stopped['status'] == 'paused'
    assert stopped['active_task'] is None and stopped['pending'] is None
    assert [c['role'] for c in model.calls] == ['manager', 'manager']


def paused_task(store, sid):
    from mrcat.tasks import create_task
    state = store.load(sid)
    task = create_task(state, dict(description='Analyze supplied data', request=state['request'],
        plan='Compute the requested value.', plan_items=[dict(step_id='compute',
            title='Compute the requested value.', skill_id=None, reuse_from=[])]))
    task['status'] = state['status'] = 'paused'
    state['plan'] = task['plan']
    store.save(state)
    return state


def test_confirmation_without_pending_plan_corrects_to_resume(tmp_path):
    store, sid = create(tmp_path)
    before = paused_task(store, sid)
    model = Model([verified_value(), 'Completed.'], decisions=[
        decision('mr', 'confirm'), decision('mr', 'continue')])
    done = Agent(ROOT, store, model=model).run(sid, 'I confirm; continue')
    assert 'no pending plan' in json.loads(model.calls[1]['user'])['format_error']
    assert done['status'] == 'completed'
    assert done['task_history'][0]['task_id'] == before['active_task']['task_id']
    assert not any(c['role'] == 'planner' for c in model.calls)


def test_repeated_state_mismatch_preserves_paused_task(tmp_path):
    store, sid = create(tmp_path)
    before = paused_task(store, sid)
    model = Model(decisions=[decision('mr', 'confirm'), decision('mr', 'confirm')])
    stopped = Agent(ROOT, store, model=model).run(sid, 'I confirm')
    assert stopped['status'] == 'paused'
    assert stopped['active_task'] == before['active_task']
    assert stopped['task_history'] == []
    assert [c['role'] for c in model.calls] == ['manager', 'manager']


def test_continuing_archived_task_corrects_to_planner(tmp_path):
    from copy import deepcopy
    from mrcat.tasks import archive_task
    store, sid = create(tmp_path)
    state = paused_task(store, sid)
    archive_task(state, 'failed')
    store.save(state)
    history = deepcopy(state['task_history'])
    model = Model(decisions=[decision('mr', 'continue'), decision('mr', 'propose')])
    proposed = Agent(ROOT, store, model=model).run(sid, 'Continue the previous analysis')
    assert 'no unfinished MR task' in json.loads(model.calls[1]['user'])['format_error']
    assert [c['role'] for c in model.calls] == ['manager', 'manager', 'planner']
    assert proposed['pending']['kind'] == 'plan_confirmation'
    assert proposed['active_task'] is None and proposed['task_history'] == history


def test_failed_turn_preserves_task_for_retry(tmp_path, monkeypatch):
    store, sid = create(tmp_path)
    before = paused_task(store, sid)
    state = store.load(sid)
    state['active_agent'] = 'mr'
    state['active_task']['status'] = 'running'
    store.save(state)
    agent = Agent(ROOT, store, model=Model())
    def fail(*args):
        raise RuntimeError('Transient workflow failure')
    monkeypatch.setattr(agent, '_run', fail)
    with pytest.raises(RuntimeError, match='Transient workflow failure'):
        agent.run(sid, 'Continue')
    after = store.load(sid)
    assert after['status'] == 'failed'
    assert after['active_task'] == before['active_task']
    assert after['task_history'] == []
    assert after['events'][-1]['content'] == 'RuntimeError: Transient workflow failure'
