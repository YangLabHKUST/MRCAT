"""Two execution modes share one code runner; tool success needs no model handoff."""
import importlib
import json
from pathlib import Path

import pytest

from mrcat.agent import Agent
from mrcat import tools
from mrcat.skills import SkillRegistry
from test_agent import ROOT, Model, action, create, decision
from test_plan_items import item


def skill_item(name='search'):
    return item(name, title='Search the exact requested target', skill_id='gwas-search')


def search_code(*, blocked=False, no_output=False):
    # Replace only the external search service, while exercising real public
    # tool registration, subprocess execution, persistence and advancement.
    payload = {'status': 'blocked', 'gwas_search_results': {}} if blocked else {
        'status': 'ok', 'gwas_search_results': {'shortlists_path': 'PLACEHOLDER'}}
    return '''import importlib
from pathlib import Path
from mrcat.tools import gwas_search
backend = importlib.import_module('skills.gwas-search.scripts.run_search')
p = Path.cwd() / 'shortlists.json'
p.write_text('{"candidates": []}')
outputs = ''' + repr(payload) + '''
if outputs['status'] == 'ok':
    outputs['gwas_search_results']['shortlists_path'] = str(p)
backend.run = lambda payload: {'summary': 'Real fixture result', 'outputs': outputs,
    'details': {'failure_class': 'no_data' if outputs['status'] == 'blocked' else None}}
''' + ("print('exit zero without calling the tool')" if no_output else "print(gwas_search(trait='fixture')['summary'])")


def test_all_guides_have_a_callable_interface():
    registry = SkillRegistry(ROOT / 'skills')
    assert len(registry.list_bundles()) == 26
    for skill in registry.list_bundles():
        assert callable(getattr(tools, skill.id.replace('-', '_'))), skill.id


def test_successful_tools_use_one_executor_call_each_and_zero_reviews(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', search_code()), action('execute', search_code())],
                  [decision('mr', 'propose', execute=True)],
                  [{'plan_items': [skill_item('first'), skill_item('second')]}])
    done = Agent(ROOT, store, model=model).run(sid, 'Search two targets')
    assert done['status'] == 'completed'
    assert [c['role'] for c in model.calls].count('mr') == 2
    assert not any(c['role'] == 'evaluate' for c in model.calls)
    assert list(done['task_history'][0]['completed_items']) == ['first', 'second']
    assert len(list((store.directory(sid) / 'results/task1').glob('*.json'))) == 2
    contexts = [json.loads(c['user']) for c in model.calls if c['role'] == 'mr']
    assert all(c['execution_mode'] == 'tool' for c in contexts)
    assert all('skill_catalog' not in c for c in contexts)


def test_blocked_tool_can_finalize_without_downstream_execution(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', search_code(blocked=True))],
                  [decision('mr', 'propose', execute=True)],
                  [{'plan_items': [skill_item('first'), skill_item('never_run')]}],
                  [dict(route='finalize', reason='No requested data; stop without substitution.')],
                  ['blocked\nNo requested data are available. No analysis was run.\n[END_FINAL_SUMMARY]'])
    done = Agent(ROOT, store, model=model).run(sid, 'Search unavailable data')
    assert done['status'] == 'waiting_user'
    assert done['active_task']['completed_items'] == {}
    assert sum(c['role'] == 'mr' for c in model.calls) == 1
    assert sum(c['role'] == 'evaluate' for c in model.calls) == 1
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 1


def test_missing_input_is_reviewed_with_the_current_skill_guide(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', "from mrcat.tools import gwas_search\ngwas_search(trait='$ref:missing/trait')")],
                  decisions=[decision('mr', 'propose', execute=True)],
                  plans=[{'plan_items': [skill_item()]}],
                  evaluations=[dict(route='finalize', reason='Required input is unavailable.')],
                  finalizations=['blocked\nSupply the missing input.\n[END_FINAL_SUMMARY]'])
    waiting = Agent(ROOT, store, model=model).run(sid, 'Search from supplied input')
    assert waiting['status'] == 'waiting_user'
    assert sum(c['role'] == 'mr' for c in model.calls) == 1
    context = json.loads(next(c['user'] for c in model.calls if c['role'] == 'evaluate'))
    assert context['current_item']['skill_id'] == 'gwas-search'
    assert context['skill_requirements'][0]['skill'] == 'gwas-search'
    assert 'Unresolved result reference' in context['handoff']['body']


def test_review_execute_retries_tool_without_planner_or_replaying_prior_item(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', search_code()),
                   action('execute', 'raise ValueError("incorrect path")'),
                   action('execute', search_code()),
                   action('execute', search_code())],
                  [decision('mr', 'propose', execute=True)],
                  [{'plan_items': [skill_item('first'), skill_item('second'), skill_item('third')]}],
                  [dict(route='execute', accept_item=False, reason='Fix the current path only.')])
    done = Agent(ROOT, store, model=model).run(sid, 'Search two targets')
    assert done['status'] == 'completed'
    assert sum(c['role'] == 'planner' for c in model.calls) == 1
    task = done['task_history'][0]
    assert len(task['completed_items']['first']['execution_ids']) == 1
    assert len(task['completed_items']['second']['execution_ids']) == 2
    assert len(task['completed_items']['third']['execution_ids']) == 1
    contexts = [json.loads(c['user']) for c in model.calls if c['role'] == 'mr']
    assert contexts[2]['evaluation']['reason'] == 'Fix the current path only.'
    assert contexts[3]['evaluation'] is None


def test_zero_exit_without_tool_output_is_reviewed_not_completed(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', search_code(no_output=True))],
        [decision('mr', 'propose', execute=True)], [{'plan_items': [skill_item()]}],
        [dict(route='finalize', reason='The declared tool has not run.')],
        ['blocked\nNo usable tool output was produced.\n[END_FINAL_SUMMARY]'])
    done = Agent(ROOT, store, model=model).run(sid, 'Search')
    assert done['active_task']['completed_items'] == {}
    assert done['status'] == 'waiting_user'


def test_failed_tool_can_replan_to_custom_without_replaying_completed_item(tmp_path):
    store, sid = create(tmp_path)
    replacement = item('custom_repair', title='Process the saved shortlist from first')
    def code(context):
        ref = context['upstream_results'][0]['ref'] + '/shortlists_path'
        return action('execute', "from pathlib import Path\nfrom mrcat.tools import resolve_ref, publish_result\n"
                      f"publish_result('answer', {{'content': Path(resolve_ref({ref!r})).read_text()}})")
    model = Model([action('execute', search_code()), action('execute', 'raise ValueError("unsupported operation")'),
                   code, 'The custom operation is checked.'],
                  [decision('mr', 'propose', execute=True)],
                  [{'plan_items': [skill_item('first'), skill_item('second')]}, {'plan_items': [replacement]}],
                  [dict(route='replan', reason='Replace the unsupported step with custom processing of the saved shortlist.')])
    done = Agent(ROOT, store, model=model).run(sid, 'Search then process the result')
    assert done['status'] == 'completed'
    task = done['task_history'][0]
    assert list(task['completed_items']) == ['first', 'custom_repair']
    assert len(task['completed_items']['first']['execution_ids']) == 1
    assert sum(c['role'] == 'planner' for c in model.calls) == 2
    contexts = [json.loads(c['user']) for c in model.calls if c['role'] == 'mr']
    assert [c.get('execution_mode', 'coding') for c in contexts] == ['tool', 'tool', 'coding', 'coding']
    assert contexts[2]['upstream_results'][0]['ref'].startswith('$ref:')


def test_custom_loop_is_reviewed_before_following_skill(tmp_path):
    store, sid = create(tmp_path)
    custom = item('custom', title='Compute the requested search target')
    consumer = skill_item('consume')
    model = Model([action('execute', 'raise ValueError("inspect input")'),
                   action('execute', "from mrcat.tools import publish_result\npublish_result('answer', {'trait': 'fixture'})"),
                   action('end', 'The custom operation is checked.', outcome='complete'),
                   action('execute', search_code().replace("trait='fixture'", "trait='$ref:answer/trait'"))],
                  [decision('mr', 'propose', execute=True)], [{'plan_items': [custom, consumer]}])
    done = Agent(ROOT, store, model=model).run(sid, 'Custom computation then search')
    assert done['status'] == 'completed'
    assert sum(c['role'] == 'evaluate' for c in model.calls) == 1
    events = [e['type'] for e in done['events']]
    assert events.index('evaluation') < events.index('plan_item_completed')
    task = done['task_history'][0]
    assert len(task['completed_items']['custom']['execution_ids']) == 2
    assert len(task['completed_items']['consume']['execution_ids']) == 1


@pytest.mark.parametrize('data_source, requested_id, candidate_id', [
    ('opengwas', 'fixed-id', 'fixed-id'),
    ('pan_ukb', '21001', 'continuous-21001-both_sexes-irnt.tsv.bgz'),
    ('pan_ukb', '21002', 'continuous-21002-both_sexes-irnt.tsv.bgz'),
])
def test_selector_materializes_real_candidates_and_receives_request(
    tmp_path, monkeypatch, data_source, requested_id, candidate_id,
):
    runner = importlib.import_module('skills.gwas-select.scripts.run_select')
    selector = importlib.import_module('skills.gwas-select.scripts.llm_selector')
    candidate = dict(source=data_source, study_id=candidate_id, trait='Exact endpoint',
        ancestry='European', downloadable=True, sample_size=10000,
        download_descriptor=dict(status='ready', method='url', url='https://example.invalid/data'),
        study_metadata={'effect_allele': 'ALT', 'phenocode': requested_id})
    source = tmp_path / 'shortlist.json'
    source.write_text(json.dumps(dict(target=dict(kind='study_id', value=requested_id, source=data_source),
                                     candidates=[candidate], diagnostics={})))
    calls = []
    def select(**kwargs):
        calls.append(kwargs)
        return selector.validate_selection(dict(selected_studies={'target': {'source': data_source, 'study_id': candidate_id}},
            selection_reason='Exact fixed endpoint'), candidates_by_target=kwargs['candidates_by_target'])
    monkeypatch.setattr(runner, 'select_shortlists', select)
    result = tools.gwas_select(shortlists={'target': source}, request='Keep the exact fixed ID', output_dir=tmp_path / 'out')
    assert len(calls) == 1 and 'Keep the exact fixed ID' in calls[0]['current_plan_item']
    assert calls[0]['target_specs']['target']['value'] == requested_id
    selected = result['outputs']['gwas_selection_result']['selected_studies']['target']
    assert selected['study_id'] == candidate_id
    assert selected['study_metadata'] == candidate['study_metadata']
    assert selected['download_descriptor'] == candidate['download_descriptor']
    assert (tmp_path / 'out/response.json').is_file()
    with pytest.raises(selector.LLMSelectionError, match='not in its candidate pool'):
        selector.validate_selection(dict(selected_studies={'target': {'source': data_source, 'study_id': 'invented-id'}}, selection_reason='Wrong'),
            candidates_by_target={'target': [candidate]})


def test_qc_success_without_optional_ancestry_advances_once(tmp_path):
    """Q26 regression: the tool's valid output need not fill reusable metadata."""
    store, sid = create(tmp_path)
    qc = item('qc_exposure', title='QC the supplied exposure', skill_id='gwas-qc')
    code = '''import importlib
from pathlib import Path
from mrcat.tools import gwas_qc
backend = importlib.import_module('skills.gwas-qc.scripts.run_gwas_qc')
payload = {'genome_build': 'grch37', 'genome_build_reason': 'Known fixture coordinates'}
for key in ['canonical_path', 'formatted_path', 'report_path', 'explanation_path']:
    path = Path.cwd() / (key + '.txt')
    path.write_text('fixture artifact')
    payload[key] = str(path)
backend.run = lambda _: {'summary': 'QC succeeded; ancestry unavailable',
    'outputs': {'status': 'ok', 'gwas_qc_result': payload}}
print(gwas_qc(raw_path='fixture.tsv')['summary'])'''
    model = Model([action('execute', code)], [decision('mr', 'propose', execute=True)],
                  [{'plan_items': [qc]}], finalizations=['completed\nQC completed; ancestry is unknown.\n[END_FINAL_SUMMARY]'])
    done = Agent(ROOT, store, model=model).run(sid, 'QC the supplied exposure')
    assert done['status'] == 'completed'
    assert sum(c['role'] == 'mr' for c in model.calls) == 1
    assert not any(c['role'] == 'evaluate' for c in model.calls)
    completed = done['task_history'][0]['completed_items']['qc_exposure']
    assert completed['outputs']['gwas_qc_result']['ref'].startswith('$ref:gwas_qc_')
    result = json.loads(next((store.directory(sid) / 'results/task1').glob('*.json')).read_text())
    assert 'ancestry' not in result['outputs']['gwas_qc_result']
