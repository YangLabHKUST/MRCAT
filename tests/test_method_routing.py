"""Evidence survives accepted-item replanning and interrupted planning.

Synthetic fixtures exercise routing and reference reuse, not scientific validity
or a live model's ability to classify arbitrary methods.
"""
import json

import pytest

from mrcat.agent import Agent
from mrcat.workflow.mr import MRNodes
from test_agent import ROOT, Model, action, create, decision, verified_value
from test_plan_items import item


def contexts(model, role):
    return [json.loads(c['user']) for c in model.calls if c['role'] == role]


def accepted_replan():
    return dict(route='replan', accept_item=True, invalidate_steps=[],
                reason='Requirements and actual inputs verified; plan preparation and fitting.')


def investigation():
    return item('inspect_method_requirements', title='Verify method requirements against QC data and publish evidence')


def investigate(shared):
    evidence = dict(shared_preparation_compatible=shared, final_iv_threshold=5e-8,
                    source='Synthetic method specification', requires_ld_matrix=not shared)
    return action('execute', 'from mrcat.tools import publish_result\n'
                  f'evidence = {evidence!r}\nprint(evidence)\n'
                  'publish_result("requirements", evidence)')


def prepare_shared():
    # Only the external preparation backend is stubbed; exercise the registered
    # tool, its publication, result binding and automatic item completion.
    return action('execute', r'''import importlib
from pathlib import Path
from mrcat.tools import gwas_pair_prepare
backend = importlib.import_module('skills.gwas-pair-prepare.scripts.run_gwas_pair_prepare')
p = Path.cwd() / 'MRdat.tsv'
p.write_text('SNP\tpval.exp\nrs1\t1e-9\nrs2\t1e-6\n')
def fixture(payload):
    assert payload['iv_threshold'] == 5e-5
    return {'summary': 'Synthetic prepared pair', 'outputs': {'status': 'ok',
        'gwas_pair_prepare_result': {'mrdat_path': str(p), 'iv_threshold': payload['iv_threshold']}}}
backend.run = fixture
print(gwas_pair_prepare(formatted_exposure_path='fixture_exposure.tsv',
                        formatted_outcome_path='fixture_outcome.tsv')['summary'])
''')


def fit(context):
    requirement = next(r for r in context['upstream_results'] if r['source'].endswith('/requirements'))
    prepared = next(r for r in context['upstream_results'] if '/prepare_inputs/' in r['source'])
    return action('execute', 'from mrcat.tools import resolve_ref, publish_result\n'
                  f'requirements = resolve_ref({requirement["ref"]!r})\n'
                  f'prepared = resolve_ref({prepared["ref"]!r})\n'
                  'if requirements["shared_preparation_compatible"]:\n'
                  '    import csv\n'
                  '    with open(prepared["mrdat_path"]) as stream:\n'
                  '        selected = [row["SNP"] for row in csv.DictReader(stream, delimiter="\\t")\n'
                  '                    if float(row["pval.exp"]) <= requirements["final_iv_threshold"]]\n'
                  '    assert selected == ["rs1"]\n'
                  'else:\n'
                  '    assert prepared["ld_matrix"] == [[1, 0.3], [0.3, 1]]\n'
                  '    selected = prepared["variants"]\n'
                  'publish_result("fit", {"selected": selected, "threshold": requirements["final_iv_threshold"]})')


@pytest.mark.parametrize('shared', [True, False])
def test_investigation_replans_and_results_reach_both_preparation_routes(tmp_path, shared):
    store, sid = create(tmp_path)
    inspect = investigation()
    prepare = item('prepare_inputs', skill_id='gwas-pair-prepare' if shared else None)
    plans = [{'plan_items': [inspect]}, {'plan_items': [inspect, prepare, item('fit_method')]}]
    prep_actions = [prepare_shared()] if shared else [action('execute',
        'from mrcat.tools import publish_result\n'
        'publish_result("method_inputs", {"variants": ["rs1", "rs2"], "ld_matrix": [[1, .3], [.3, 1]]})'),
        'Prepared the correlated candidate inputs.']
    model = Model([investigate(shared), 'Requirements verified and published.', *prep_actions,
                   fit, 'Synthetic fit checked.'],
                  [decision('mr', 'propose', execute=True)], plans, [accepted_replan()])
    done = Agent(ROOT, store, model=model).run(sid, 'Run the synthetic method on supplied QC inputs')
    assert done['status'] == 'completed'
    task = done['task_history'][0]
    assert list(task['completed_items']) == ['inspect_method_requirements', 'prepare_inputs', 'fit_method']
    assert len(task['completed_items']['inspect_method_requirements']['execution_ids']) == 1
    replanning = contexts(model, 'planner')[1]
    assert 'requirements' in replanning['completed_items']['inspect_method_requirements']['outputs']
    assert replanning['recovery']['accept_item'] is True
    assert replanning['completed_results'][0]['outputs']['shared_preparation_compatible'] is shared
    assert contexts(model, 'evaluate')[0]['current_results'][0]['outputs']['shared_preparation_compatible'] is shared
    assert 'replan_pending' not in task
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 3
    assert len(contexts(model, 'evaluate')) == (2 if shared else 3)


def test_failed_planner_resumes_replan_without_repeating_investigation_or_finalizing(tmp_path):
    store, sid = create(tmp_path)
    base = Model([investigate(True), 'Requirements verified.'],
                 [decision('mr', 'propose', execute=True)],
                 [{'plan_items': [investigation()]}], [accepted_replan()])

    def unavailable(**kwargs):
        if kwargs['role'] == 'planner' and json.loads(kwargs['user']).get('recovery'):
            raise RuntimeError('Planner unavailable')
        return base(**kwargs)

    paused = Agent(ROOT, store, model=unavailable).run(sid, 'Run the synthetic method')
    assert paused['status'] == 'paused'
    assert 'inspect_method_requirements' in paused['active_task']['completed_items']
    assert paused['active_task']['replan_pending']['review']['accept_item']
    assert not contexts(base, 'finalize')
    model = Model([verified_value(), 'Fit checked.'], [decision('mr', 'continue')],
                  [{'plan_items': [item('fit_method')]}])
    done = Agent(ROOT, store, model=model).run(sid, 'Continue')
    assert done['status'] == 'completed'
    assert len(contexts(model, 'planner')) == 1
    assert len(contexts(model, 'evaluate')) == 1
    assert all(c['current_item']['step_id'] == 'fit_method' for c in contexts(model, 'mr'))
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 2
    assert 'replan_pending' not in done['task_history'][0]


@pytest.mark.parametrize('accept', [True, 'true'])
def test_replan_cannot_accept_blocked_work_or_nonboolean_acceptance(tmp_path, accept):
    store, sid = create(tmp_path)
    review = accepted_replan() | {'accept_item': accept}
    model = Model([action('end', 'Official requirements are unresolved.', outcome='blocked')],
                  [decision('mr', 'propose', execute=True)],
                  [{'plan_items': [investigation()]}], [review, review])
    done = Agent(ROOT, store, model=model).run(sid, 'Investigate the unknown method')
    assert done['status'] == 'paused'
    assert done['active_task']['completed_items'] == {}
    assert len(contexts(model, 'planner')) == 1
    assert any(e['type'] == 'evaluation_failed' for e in done['events'])


def test_accepted_replans_do_not_consume_failed_recovery_budget(tmp_path):
    store, sid = create(tmp_path)
    actions, plans = [], []
    for i in range(4):
        plans.append({'plan_items': [item(f'investigate_{i}')]})
        actions.extend([verified_value(i, f'evidence_{i}'), 'Evidence published.'])
    plans.append({'plan_items': [item('fit_method')]})
    actions.extend([verified_value(), 'Fit checked.'])
    model = Model(actions, [decision('mr', 'propose', execute=True)], plans,
                  [accepted_replan() for _ in range(4)])
    done = Agent(ROOT, store, model=model).run(sid, 'Investigate four independent synthetic methods')
    assert done['status'] == 'completed'
    assert len(contexts(model, 'planner')) == 5
    assert len(done['task_history'][0]['completed_items']) == 5


def test_accepted_replan_preserves_existing_failed_recovery_count(tmp_path):
    store, sid = create(tmp_path)
    nodes = MRNodes(Agent(ROOT, store, model=Model()))
    state = store.load(sid)
    update = nodes.recover(dict(review=accepted_replan(), recoveries=2), state)
    assert update['recoveries'] == 2
    update = nodes.recover(dict(review=dict(route='replan', reason='Still blocked.'), recoveries=2), state)
    assert update['recoveries'] == 3
