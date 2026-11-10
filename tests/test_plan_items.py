"""Flat planning guidance, real references and durable progress."""
import json

import pytest

from mrcat.agent import Agent
from mrcat.workflow.plan_items import parse_plan, validate_reuse
from test_agent import ROOT, Model, action, create, decision


def item(name, *, title=None, skill_id=None, reuse_from=None):
    return dict(step_id=name, title=title or name, skill_id=skill_id, reuse_from=reuse_from or [])


def two_items():
    return {'plan_items': [item('prepare', title='Prepare the supplied values'),
                           item('calculate', title='Calculate the mean using prepare results')]}


PREPARE = "from mrcat.tools import publish_result\npublish_result('numbers', {'values': [2, 4, 6]})"


def calculate(context):
    row = next(r for r in context['upstream_results'] if r['source'].endswith('/prepare/numbers'))
    return action('execute', "from mrcat.tools import resolve_ref, publish_result\n"
                  f"v=resolve_ref({row['ref']!r})['values']\n"
                  "publish_result('answer', {'mean': sum(v)/len(v)})")


def test_custom_items_advance_after_review_with_full_plan_and_actual_results(tmp_path):
    store, sid = create(tmp_path)
    plan = two_items()
    model = Model([action('execute', PREPARE), 'Prepared.', calculate, 'Calculated.'],
                  [decision('mr', 'propose', execute=True)], [plan])
    done = Agent(ROOT, store, model=model).run(sid, 'Compute a mean from supplied values')
    assert done['status'] == 'completed'
    task = done['task_history'][0]
    assert list(task['completed_items']) == ['prepare', 'calculate']
    contexts = [json.loads(c['user']) for c in model.calls if c['role'] == 'mr']
    assert [c['current_item']['step_id'] for c in contexts] == ['prepare', 'prepare', 'calculate', 'calculate']
    assert all(len(c['plan_overview']) == 1 for c in contexts)
    assert contexts[2]['upstream_results'][0]['ref'] == '$ref:numbers'
    assert 'item_inputs' not in contexts[2]
    assert contexts[2]['action_history'] == []
    assert contexts[3]['result_refs'][-1]['ref'] == '$ref:answer'
    assert sum(c['role'] == 'evaluate' for c in model.calls) == 2
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 2
    from mrcat.state.results import read_reference
    binding = task['completed_items']['calculate']['outputs']['answer']['ref']
    assert read_reference(store.directory(sid), 'task1', binding)['mean'] == 4.0
    assert '4.0' in task['final_summary']


def test_host_rejects_custom_completion_without_publication(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', 'print("successful exit but no result")'), 'Done.'],
                  [decision('mr', 'propose', execute=True)], [two_items()])
    waiting = Agent(ROOT, store, model=model, max_rounds=2).run(sid, 'Compute a mean')
    assert waiting['status'] == 'paused'
    assert waiting['active_task']['completed_items'] == {}
    assert not any(c['role'] == 'evaluate' for c in model.calls)
    assert waiting['active_task']['coding']['prepare']['entries'][-1]['tool'] == 'finish_rejected'


def test_local_repair_preserves_full_plan_and_completed_results(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', PREPARE), 'Prepared.',
                   action('execute', 'raise ValueError("local coding error")'), calculate, 'Calculated.'],
                  [decision('mr', 'propose', execute=True)], [two_items()])
    done = Agent(ROOT, store, model=model).run(sid, 'Compute a mean')
    assert done['status'] == 'completed'
    contexts = [json.loads(c['user']) for c in model.calls if c['role'] == 'mr']
    from test_custom_codeact import execution_evidence
    assert execution_evidence(contexts[3])[-1]['code'].startswith('raise ValueError')
    assert contexts[3]['upstream_results'][0]['ref'] == '$ref:numbers'
    assert len(contexts[3]['plan_overview']) == 1
    assert len(done['task_history'][0]['completed_items']['prepare']['execution_ids']) == 1


def test_custom_stagnation_pauses_at_budget_without_scientific_review(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', f'print("same candidate pool, formatting {i}")') for i in range(6)],
                  [decision('mr', 'propose', execute=True)], [two_items()],
                  [dict(route='finalize', reason='Repeated reads have no supported next action.')],
                  ['blocked\nNo usable output.\n[END_FINAL_SUMMARY]'])
    waiting = Agent(ROOT, store, model=model, max_rounds=6).run(sid, 'Compute a mean')
    assert waiting['status'] == 'paused'
    assert not any(c['role'] == 'evaluate' for c in model.calls)
    assert sum(e['type'] == 'code_execution' for e in waiting['events']) == 6


def test_recovery_reuses_completed_item_without_reexecuting_producer(tmp_path):
    store, sid = create(tmp_path)
    repaired = {'plan_items': [two_items()['plan_items'][1]]}
    model = Model([action('execute', PREPARE), 'Prepared.', action('evaluate', 'Implementation needs a revised approach.'),
                   calculate, 'Calculated.'],
                  [decision('mr', 'propose', execute=True)], [two_items(), repaired],
                  [dict(route='execute', accept_item=True, reason='Prepared values are verified.'),
                   dict(route='replan', reason='Repair only calculate; reuse prepare.')])
    done = Agent(ROOT, store, model=model).run(sid, 'Compute a mean')
    assert done['status'] == 'completed'
    assert len(done['task_history'][0]['completed_items']['prepare']['execution_ids']) == 1
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 2


def test_completed_item_cannot_be_rewritten_and_planner_cannot_declare_outputs():
    plan = two_items()
    completed = {'prepare': dict(item=plan['plan_items'][0], outputs={})}
    plan['plan_items'][0] = item('prepare', title='Use different inputs')
    with pytest.raises(ValueError, match='immutable'):
        parse_plan(json.dumps(plan), completed)
    plan = two_items()
    plan['plan_items'][0]['outputs'] = {'numbers': ['values']}
    with pytest.raises(ValueError, match='only step_id'):
        parse_plan(json.dumps(plan))


def test_new_agent_resumes_consumer_with_saved_producer_reference(tmp_path):
    store, sid = create(tmp_path)
    first = Model([action('execute', PREPARE), 'Prepared.', action('ask', 'The required service is unavailable.')],
                  [decision('mr', 'propose', execute=True)], [two_items()])
    waiting = Agent(ROOT, store, model=first).run(sid, 'Compute a mean')
    assert list(waiting['active_task']['completed_items']) == ['prepare']
    second = Model([calculate, 'Calculated.'], [decision('mr', 'continue')])
    done = Agent(ROOT, store, model=second).run(sid, 'Continue')
    assert done['status'] == 'completed'
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 2
    assert not any(c['role'] == 'planner' for c in second.calls)


@pytest.mark.parametrize('finish_first', [True, False])
def test_historical_reuse_selects_exact_task_and_provides_actual_reference(tmp_path, finish_first):
    store, sid = create(tmp_path)
    actions = [action('execute', PREPARE), 'Prepared.']
    steps = [item('prepare')]
    if not finish_first:
        actions.append(action('ask', 'A separate later operation needs input.'))
        steps.append(item('later'))
    first = Model(actions, [decision('mr', 'propose', execute=True)], [{'plan_items': steps}])
    Agent(ROOT, store, model=first).run(sid, 'Prepare values')
    plan = {'plan_items': [item('calculate', title='Reuse task1 values to compute their mean',
                                    reuse_from=['task1/prepare/numbers'])]}
    second = Model([calculate, 'Calculated.'], [decision('mr', 'propose', execute=True)], [plan])
    done = Agent(ROOT, store, model=second).run(sid, 'Use the previous values to compute their mean')
    assert done['status'] == 'completed'
    context = json.loads(next(c['user'] for c in second.calls if c['role'] == 'mr'))
    assert context['upstream_results'][0]['ref'] == '$taskref:task1/numbers'
    assert any(r['ref'] == '$taskref:task1/numbers' for r in context['result_refs'])
    planner = json.loads(next(c['user'] for c in second.calls if c['role'] == 'planner'))
    source = (planner['available_results']['task_history'][0] if finish_first
              else planner['available_results']['active_task'])
    assert source['reusable_results'][0]['source'] == 'task1/prepare/numbers'
    with pytest.raises(ValueError, match='not a completed saved result'):
        validate_reuse([item('wrong', reuse_from=['task1/other/numbers'])], done['task_history'])


def test_prior_plan_is_replanned_once_without_rerunning_completed_producer(tmp_path):
    store, sid = create(tmp_path)
    first = Model([action('execute', PREPARE), 'Prepared.', action('ask', 'Service unavailable.')],
                  [decision('mr', 'propose', execute=True)], [two_items()])
    Agent(ROOT, store, model=first).run(sid, 'Compute a mean')
    saved = store.load(sid)
    task = saved['active_task']
    task['plan_items'] = [dict(id='calculate', goal='Compute mean', skill=None, inputs={}, outputs={}, completion='Compute mean')]
    task['completed_items']['prepare']['contract'] = task['completed_items']['prepare'].pop('item')
    task['review_pending'] = dict(request=task['request'], plan=task['plan'],
                                  handoff=dict(outcome='blocked', body='Old-format pending review'))
    store.save(saved)
    second = Model([calculate, 'Calculated.'], [decision('mr', 'continue')],
                   [{'plan_items': [item('calculate', title='Use the completed prepare results to compute the mean')]}])
    done = Agent(ROOT, store, model=second).run(sid, 'Continue')
    assert done['status'] == 'completed'
    assert sum(c['role'] == 'planner' for c in second.calls) == 1
    assert len(done['task_history'][0]['completed_items']['prepare']['execution_ids']) == 1
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 2
