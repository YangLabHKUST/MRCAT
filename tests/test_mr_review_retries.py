"""Review controls repeated item repair while preserving progress and stop budgets."""
import json

import pytest

from mrcat.agent import Agent
from test_agent import ROOT, Model, action, create, decision, verified_value
from test_dual_executor import search_code, skill_item


def retry():
    return dict(route='execute', accept_item=False,
                reason='The saved partial output progressed; resume the current operation.')


def progress_code(offset):
    return ('from pathlib import Path\n'
            'p = Path("download.part")\n'
            f'assert (p.stat().st_size if p.exists() else 0) == {offset}\n'
            'with p.open("ab") as stream: stream.write(b"x")\n'
            f'print("Retained {offset + 1} bytes", flush=True)\n'
            'raise TimeoutError("Transfer interrupted; resume the partial output")')


def evaluations(model):
    return [json.loads(c['user']) for c in model.calls if c['role'] == 'evaluate']


def test_skill_retries_past_third_review_preserve_progress_and_completed_items(tmp_path):
    store, sid = create(tmp_path)
    model = Model(
        [action('execute', search_code()),
         *[action('execute', progress_code(i)) for i in range(3)],
         action('execute', 'from pathlib import Path\nassert Path("download.part").read_bytes() == b"xxx"\n' + search_code())],
        [decision('mr', 'propose', execute=True)],
        [{'plan_items': [skill_item('first'), skill_item('second')]}],
        [retry() for _ in range(3)])
    done = Agent(ROOT, store, model=model).run(sid, 'Process two supplied targets')
    assert done['status'] == 'completed'
    task = done['task_history'][0]
    assert len(task['completed_items']['first']['execution_ids']) == 1
    assert len(task['completed_items']['second']['execution_ids']) == 4
    assert len(evaluations(model)) == 3
    for i, context in enumerate(evaluations(model)):
        assert f'Retained {i + 1} bytes' in context['executions'][-1]['observation']['stdout']
        assert 'first' in context['completed_items']
    assert sum(c['role'] == 'planner' for c in model.calls) == 1
    assert not any(e['type'] == 'interrupted' for e in done['events'])


def test_custom_review_can_request_more_than_three_revisions(tmp_path):
    store, sid = create(tmp_path)
    model = Model(
        [*[action('end', 'Additional scientific validation is needed.', outcome='blocked') for _ in range(3)],
         verified_value(), 'Validated.'],
        [decision('mr', 'propose', execute=True)],
        evaluations=[*[retry() for _ in range(3)],
                     dict(route='execute', accept_item=True, reason='Published evidence satisfies the request.')])
    done = Agent(ROOT, store, model=model).run(sid, 'Validate the supplied value')
    assert done['status'] == 'completed'
    assert len(evaluations(model)) == 4
    assert all('review_limit' not in context and 'reviews_used' not in context
               for context in evaluations(model))


@pytest.mark.parametrize('route', ['replan', 'finalize'])
def test_review_can_change_route_after_repeated_repairs(tmp_path, route):
    store, sid = create(tmp_path)
    actions = [action('execute', 'raise ValueError("Unresolved input")') for _ in range(4)]
    plans = [{'plan_items': [skill_item()]}]
    if route == 'replan':
        plans.append({'plan_items': [skill_item('replacement')]})
        actions.append(action('execute', search_code()))
    model = Model(actions, [decision('mr', 'propose', execute=True)], plans,
                  [*[retry() for _ in range(3)], dict(route=route, reason='Current evidence requires a different resolution.')],
                  [] if route == 'replan' else ['blocked\nA required input is missing.\n[END_FINAL_SUMMARY]'])
    done = Agent(ROOT, store, model=model).run(sid, 'Process the supplied target')
    assert done['status'] == ('completed' if route == 'replan' else 'waiting_user')
    assert len(evaluations(model)) == 4
    assert sum(c['role'] == 'planner' for c in model.calls) == (2 if route == 'replan' else 1)


def test_repeated_reviews_do_not_reset_overall_action_budget(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', progress_code(i)) for i in range(4)],
                  [decision('mr', 'propose', execute=True)],
                  [{'plan_items': [skill_item()]}], [retry() for _ in range(4)])
    done = Agent(ROOT, store, model=model, max_rounds=4).run(sid, 'Process the supplied target')
    assert done['status'] == 'paused'
    assert len(evaluations(model)) == 4
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 4
    assert 'action budget reached' in next(e['content'] for e in reversed(done['events']) if e['type'] == 'interrupted')
    assert done['active_task']['completed_items'] == {}


def test_continue_saved_pending_review_preserves_evidence_without_repair_counter(tmp_path):
    store, sid = create(tmp_path)
    first = Model([action('execute', progress_code(0))],
                  [decision('mr', 'propose', execute=True)],
                  [{'plan_items': [skill_item()]}], [retry()])
    paused = Agent(ROOT, store, model=first, max_rounds=1).run(sid, 'Process the supplied target')
    task = paused['active_task']
    # Reproduce an existing checkpoint stopped by the removed review-count rule.
    task['item_reviews'] = 3
    task['review_pending'] = dict(handoff=dict(outcome='blocked', body='Transfer timed out with partial bytes retained.'),
                                  request=task['request'], plan=task['plan'])
    store.save(paused)
    old_events = paused['events'][:]
    old_executions = task['item_execution_ids'][:]
    second = Model([action('execute', 'from pathlib import Path\nassert Path("download.part").read_bytes() == b"x"\n' + search_code())],
                   [decision('mr', 'continue')], evaluations=[retry()])
    done = Agent(ROOT, store, model=second).run(sid, 'Continue this task')
    assert done['status'] == 'completed'
    assert done['events'][:len(old_events)] == old_events
    assert evaluations(second)[0]['handoff'] == task['review_pending']['handoff']
    completed = done['task_history'][0]
    assert completed['task_id'] == task['task_id']
    assert completed['completed_items']['search']['execution_ids'][:-1] == old_executions
    assert not any(c['role'] == 'planner' for c in second.calls)
