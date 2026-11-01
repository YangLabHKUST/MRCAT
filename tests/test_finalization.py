"""Final delivery must preserve method-bound values and custom result shapes."""
import json
from pathlib import Path

import pytest

from mrcat.agent import Agent
from mrcat.finalization import render_summary, result_sources
from test_agent import ROOT, Model, action, create, decision, verified_value


def source():
    return dict(id='r1', path='workspace/fit/result_record.json', status='ok', data={
        'input_scale': 'standardize', 'methods': [
            {'method': 'IVW', 'beta.hat': .151, 'se': .0277, 'pval': 4.9448e-8, 'nsnp': 121},
            {'method': 'MRMix', 'beta.hat': .2, 'se': .0367, 'pval': 5.005e-8, 'nsnp': 121}]})


def test_model_authored_table_preserves_method_binding():
    summary = ('| Method | P value |\n| --- | --- |\n'
               '| IVW | {{value:r1/methods/0/pval}} |\n'
               '| MRMix | {{value:r1/methods/1/pval}} |')
    rendered = render_summary(summary, [source()], status='completed')
    assert '| IVW | 4.9448e-08 |' in rendered
    assert '| MRMix | 5.005e-08 |' in rendered
    assert '{{' not in rendered


@pytest.mark.parametrize('formula', ['1/sqrt(N)', '1/√N', r'\(1/\sqrt{N}\)'])
def test_documented_input_formula_is_not_a_fitted_numerical_claim(formula):
    summary = f'Input SNP standard errors use {formula}; MR SE comes from the estimator.\n{{{{value:r1/methods/0/pval}}}}'
    assert formula in render_summary(summary, [source()], status='completed')


@pytest.mark.parametrize('text', [
    'IVW p=0.6459. {{value:r1/methods/0/pval}}',  # Q13-style unsupported value.
    'IVW p=5.005e-8. {{value:r1/methods/0/pval}}',  # Existing value from the wrong method is still rejected.
    '`SE=0.0277`. {{value:r1/methods/0/pval}}',  # Code formatting must not bypass provenance.
    '[p=0.6459](workspace/result.json) {{value:r1/methods/0/pval}}',
    '共有121个工具变量。{{value:r1/methods/0/pval}}',
    '该方法的p值为0.6459。{{value:r1/methods/0/pval}}',
])
def test_numerical_prose_requires_a_source_even_if_number_exists(text):
    with pytest.raises(ValueError, match='numerical claims'):
        render_summary(text, [source()], status='completed')


@pytest.mark.parametrize('text', ['{{value:r2/methods/0/pval}}', '{{value:r1/methods/8/pval}}',
                               '{{value:r1/methods/0/missing}}', '{{value:r1/methods}}'])
def test_invalid_reference_does_not_substitute_another_value(text):
    with pytest.raises(ValueError):
        render_summary(text, [source()], status='completed')


def test_custom_result_does_not_require_mr_schema():
    custom = dict(id='r1', path='results/task1/custom.json', data={
        'estimator': 'custom permutation statistic', 'observed/statistic': 2.5,
        'null_interval': [-.4, .5], 'replicates': 199})
    answer = render_summary('{{value:r1/estimator}}: {{value:r1/observed~1statistic}}.', [custom], status='completed')
    assert answer == 'custom permutation statistic: 2.5.'


def test_recorded_study_id_and_space_in_field_path_are_supported():
    record = dict(id='r1', path='results/selection.json', data={'selected_studies': {
        'grip strength': {'study_id': 'ukb-b-10215', 'trait': 'Hand grip strength (right)'}}})
    answer = render_summary('Study ukb-b-10215: {{value:r1/selected_studies/grip strength/trait}}.',
                            [record], status='completed')
    assert answer == 'Study ukb-b-10215: Hand grip strength (right).'
    with pytest.raises(ValueError, match='numerical claims'):
        render_summary('Study ukb-b-99999: {{value:r1/selected_studies/grip strength/trait}}', [record], status='completed')


def test_boolean_result_is_a_valid_saved_scalar():
    record = dict(id='r1', path='result.json', data={'passed': True})
    assert render_summary('Passed: {{value:r1/passed}}', [record], status='completed') == 'Passed: true'


def test_whole_result_table_slot_is_rejected():
    with pytest.raises(ValueError, match='Unresolved'):
        render_summary('{{table:r1}}', [source()], status='completed')


def test_blocked_response_need_not_display_partial_estimates():
    assert render_summary('The original endpoint is unavailable.', [source()], status='blocked')
    with pytest.raises(ValueError, match='source-bound'):
        render_summary('The analysis is complete.', [source()], status='completed')


def test_finalize_repairs_only_delivery_using_real_saved_record(tmp_path):
    store, sid = create(tmp_path)
    code = ('import json\nfrom pathlib import Path\n'
            'Path("fit_result_record.json").write_text(' + repr(json.dumps(source()['data'])) + ')\nfrom mrcat.tools import publish_result\npublish_result("fit", json.loads(Path("fit_result_record.json").read_text()))')
    model = Model([action('execute', code), 'Result is ready; invented p=0.6459.'],
                  [decision('mr', 'propose', execute=True)], finalizations=[
                      'completed\nIVW p=0.6459.\n[END_FINAL_SUMMARY]',
                      'completed\n{{value:r1/methods/0/pval}}\nThe estimates are positive.\n[END_FINAL_SUMMARY]'])
    done = Agent(ROOT, store, model=model).run(sid, 'Report the saved estimates')
    assert done['status'] == 'completed'
    assert sum(c['role'] == 'finalize' for c in model.calls) == 2
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 1
    final = done['task_history'][0]['final_summary']
    assert '0.6459' not in final and '4.9448e-08' in final


def test_custom_published_result_reaches_finalize_without_a_skill(tmp_path):
    store, sid = create(tmp_path)
    code = ('from mrcat.tools import publish_result\n'
            'values = [2, 4, 6]\n'
            'publish_result("custom", {"estimator":"arithmetic mean", "mean":sum(values)/len(values)})')
    model = Model([action('execute', code), 'Custom computation is ready.'],
                  [decision('mr', 'propose', execute=True)], finalizations=[
                      'completed\nMean: {{value:r1/mean}}\n[END_FINAL_SUMMARY]'])
    done = Agent(ROOT, store, model=model).run(sid, 'Compute the arithmetic mean')
    final = done['task_history'][0]['final_summary']
    assert 'Mean: 4.0' in final
    review = json.loads(next(c for c in model.calls if c['role'] == 'evaluate')['user'])
    execution = next(e['details'] for e in done['events'] if e['type'] == 'code_execution')
    assert execution['result_refs']
    assert review['executions'][0]['observation']['result_refs'] == execution['result_refs']
    context = json.loads(next(c for c in model.calls if c['role'] == 'finalize')['user'])
    assert context['result_sources'][0]['status'] == 'unverified'
    assert context['result_sources'][0]['execution_id']
    assert context['current_plan'] and context['review']['route'] == 'finalize'
    assert context['completed_items'] and context['handoff']['outcome'] == 'complete'
    assert not {'executions', 'tool_records', 'skill_requirements', 'initially_confirmed_plan'} & context.keys()


def test_records_are_task_scoped_not_discovered_by_scanning_workspace(tmp_path):
    store, sid = create(tmp_path)
    folder = store.directory(sid)
    (folder/'workspace/unrelated_result_record.json').write_text(json.dumps(source()['data']))
    state = store.load(sid)
    state['active_task'] = dict(task_id='task1', request='Current request', plan='Current plan', artifacts=[])
    assert result_sources(Agent(ROOT, store), state) == []


def test_missing_known_result_cannot_disable_provenance_checks(tmp_path):
    store, sid = create(tmp_path)
    state = store.load(sid)
    state['active_task'] = dict(task_id='task1', request='Current request', plan='Current plan',
                               artifacts=['workspace/missing_result_record.json'])
    sources = result_sources(Agent(ROOT, store), state)
    assert sources[0]['status'] == 'unavailable'
    with pytest.raises(ValueError, match='numerical claims'):
        render_summary('The p-value is 0.6459.', sources, status='completed')
    with pytest.raises(ValueError, match='unavailable'):
        render_summary('{{value:r1/value}}', sources, status='completed')
    assert render_summary('The saved result is missing.', sources, status='blocked')
