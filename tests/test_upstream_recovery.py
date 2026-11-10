"""Reopen invalid producers without rerunning valid branches or reusing stale fits."""
import json

import pytest

from mrcat.agent import Agent
from mrcat.workflow.plan_items import apply_invalidation, validate_invalidation
from mrcat.workflow.finalization import result_sources
from mrcat.state.store import write_json
from mrcat.state.results import read_reference, result_catalog
from test_agent import ROOT, Model, action, create, decision
from test_plan_items import item


def publish(name, value):
    return action('execute', 'from mrcat.tools import publish_result\n'
                  f'publish_result({name!r}, {{"value": {value}}})')


def scenario(tmp_path, *, planner_fails=False):
    store, sid = create(tmp_path)
    initial = {'plan_items': [item('source_xxx'), item('other_xxx'),
                              item('derived_xxx'), item('consumer_xxx')]}
    revised = {'plan_items': [item('source_xxx', title='Correct the source file for the SAME study'),
                              item('derived_xxx'), item('consumer_xxx')]}
    review = dict(route='replan', invalidate_steps=['source_xxx', 'derived_xxx'],
                  reason='Wrong source content invalidates its derived result; preserve other_xxx.')
    base = Model([publish('old_xxx', -1), 'Saved source.',
                  publish('other_xxx', 2), 'Saved valid branch.',
                  publish('old_derived_xxx', -2), 'Saved derived value.',
                  action('evaluate', 'The source is not the requested data.'),
                  publish('new_xxx', 3), 'Source corrected.',
                  publish('new_derived_xxx', 6), 'Derived value corrected.',
                  publish('answer_xxx', 8), 'Computed.'],
                 [decision('mr', 'propose', execute=True)], [initial, revised],
                 [*[dict(route='execute', accept_item=True, reason='Fixture accepts saved output.')]*3, review])

    def model(**kwargs):
        if planner_fails and kwargs['role'] == 'planner' and json.loads(kwargs['user']).get('recovery'):
            raise RuntimeError('Planner unavailable')
        return base(**kwargs)

    done = Agent(ROOT, store, model=model).run(sid, 'Compute from supplied xxx inputs')
    return store, sid, base, done


def test_replan_reopens_bad_producer_and_consumer_preserving_valid_branch(tmp_path):
    store, sid, model, done = scenario(tmp_path)
    assert done['status'] == 'completed'
    task = done['task_history'][0]
    assert len(task['completed_items']['other_xxx']['execution_ids']) == 1
    assert [row['step_id'] for row in task['invalidated_items']] == ['source_xxx', 'derived_xxx']
    directory = store.directory(sid)
    for name in ('old_xxx', 'old_derived_xxx'):
        # Preserve raw evidence while disallowing both local and historical reuse.
        assert (directory / 'results/task1' / (name + '.json')).exists()
        for ref in ('$ref:' + name, '$taskref:task1/' + name):
            with pytest.raises(ValueError, match='invalidated'):
                read_reference(directory, 'task1', ref)
    assert {row['ref'] for row in result_catalog(directory, 'task1')} == {
        '$ref:other_xxx', '$ref:new_xxx', '$ref:new_derived_xxx', '$ref:answer_xxx'}
    planner = json.loads([c for c in model.calls if c['role'] == 'planner'][-1]['user'])
    assert set(planner['completed_items']) == {'other_xxx'}
    assert [r['source'] for r in planner['available_results']['active_task']['reusable_results']] == [
        'task1/other_xxx/other_xxx']
    final = json.loads(next(c['user'] for c in model.calls if c['role'] == 'finalize'))
    assert sorted(source['data']['value'] for source in final['result_sources']) == [2, 3, 6, 8]
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 6


def test_failed_replanning_does_not_partially_revoke_results(tmp_path):
    store, sid, model, done = scenario(tmp_path, planner_fails=True)
    assert done['status'] == 'paused'
    task = done['active_task']
    assert set(task['completed_items']) == {'source_xxx', 'other_xxx', 'derived_xxx'}
    assert 'invalidated_items' not in task
    assert len(task['plan_history']) == 1
    assert not (store.directory(sid) / 'results/task1/.invalidated').exists()


def test_invalidated_tool_artifacts_remain_on_disk_but_leave_delivery(tmp_path):
    store, sid = create(tmp_path)
    directory = store.directory(sid)
    state = store.load(sid)
    bad = 'workspace/outputs/xxx_bad/xxx_result_record.json'
    good = 'workspace/outputs/xxx_good/xxx_result_record.json'
    for ref in (bad, good):
        write_json(directory / ref, {'value': 1})
    write_json(directory / 'executions/xxx_bad/observation.json', {'generated_files': [bad]})
    state['active_task'] = dict(task_id='task1', request='xxx', plan='xxx', artifacts=[bad, good],
                               completed_items={'xxx_bad': {'execution_ids': ['xxx_bad'], 'outputs': {}}})
    apply_invalidation(state['active_task'], ['xxx_bad'], 'Wrong source data', directory)
    assert (directory / bad).is_file()
    assert state['active_task']['artifacts'] == [good]
    sources = result_sources(Agent(ROOT, store, model=Model([])), state)
    assert [source['path'] for source in sources] == [good]


@pytest.mark.parametrize('steps', ['xxx', [None], ['xxx', 'xxx'], ['unfinished_xxx']])
def test_invalidation_requires_exact_distinct_completed_ids(steps):
    with pytest.raises(ValueError, match='completed step IDs'):
        validate_invalidation({'completed_items': {'xxx': {}}}, steps)
