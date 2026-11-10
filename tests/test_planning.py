"""Planner metadata, explicit reuse evidence and ordered contracts; no remote models."""
import json
from pathlib import Path
import pytest
from mrcat.agent import Agent
from mrcat.skills import SkillRegistry
from mrcat.workflow.planning import planning_history, result_index
from mrcat.workflow.plan_items import parse_plan
from test_agent import ROOT, Model, create, decision, action


def context(model):
    return json.loads(next(c['user'] for c in model.calls if c['role'] == 'planner'))


def save_response(directory, relative, payload):
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return relative


def test_new_plan_receives_frontmatter_not_all_guides(tmp_path):
    store, sid = create(tmp_path)
    plan = '1. Use gwas-qc for each raw study.\n2. Use gwas-pair-prepare on the two QC results.\n3. Use mr-cml-ma on the prepared MRdat.'
    model = Model(decisions=[decision('mr', 'propose')], plans=[plan])
    agent = Agent(ROOT, store, model=model)
    state = agent.run(sid, 'Run cML-MA using a remote exposure and a local outcome')
    sent = context(model)
    options = {s['skill_id']: s for s in sent['skill_options']}
    assert len(options) == len(agent.skills.list_bundles()) == 26
    assert options['mr-cml-ma']['accepts'] == ['gwas_pair_prepare_result']
    assert options['gwas-pair-prepare']['produces'] == 'gwas_pair_prepare_result'
    assert 'canonical_path' in options['gwas-qc']['reusable_outputs']
    assert options['mr-cause']['accepts'] == ['gwas_qc_result']
    assert all('instruction_body' not in item for item in options.values())
    assert '## Use in Python' not in json.dumps(sent)
    assert '"step_id":"search_xxx_exposure"' in sent['few_shot']
    assert state['pending']['plan_items'][0]['title'] == plan
    assert state['plan'] == state['pending']['plan']
    assert state['active_task'] is None
    assert (store.directory(sid) / 'plan.md').read_text() == state['plan']
    assert len(model.calls) == 2  # Manager + Planner, no guide/model prefetch loop.


def test_actual_result_paths_and_status_reach_reuse_planner(tmp_path):
    store, sid = create(tmp_path)
    directory = store.directory(sid)
    pair = directory / 'workspace/pair/MRdat.tsv'
    pair.parent.mkdir(parents=True); pair.write_text('SNP\tb.exp\nrs1\t0.1\n')
    ref = save_response(directory, 'workspace/pair/response.json', dict(outputs=dict(
        status='ok', gwas_pair_prepare_result=dict(mrdat_path=str(pair),
        c_path=str(pair.parent/'missing_C.tsv'), exposure_label='X', outcome_label='Y'))))
    blocked = save_response(directory, 'workspace/blocked/response.json', dict(outputs=dict(status='blocked')))
    state = store.load(sid)
    state['task_history'] = [dict(task_id='task_old', request='Analyze X to Y', description='X to Y',
                                  status='paused', artifacts=[ref, blocked], memory='UNVERIFIED_OLD_SUMMARY')]
    store.save(state)
    plan = f'1. Use mr-cml-ma, reusing task_old gwas_pair_prepare_result.mrdat_path from {ref} for X → Y.'
    model = Model(decisions=[decision('mr', 'propose')], plans=[plan])
    done = Agent(ROOT, store, model=model).run(sid, 'Add cML-MA to task_old X to Y')
    sent = context(model)
    history = sent['available_results']['task_history'][0]
    prepared, failed = history['results']
    output = prepared['outputs'][0]
    assert prepared['reported_status'] == 'ok' and failed['reported_status'] == 'blocked'
    assert output['fields']['mrdat_path'] == str(pair)
    assert output['referenced_files_exist'] == dict(c_path=False, mrdat_path=True)
    assert output['compatible_producers'] == ['gwas-pair-prepare']
    assert 'UNVERIFIED_OLD_SUMMARY' not in json.dumps(sent)
    assert 'Reuse and recovery item guidance' in sent['few_shot']
    assert done['pending']['plan_items'][0]['title'] == plan and done['task_history'] == state['task_history']


def test_frontmatter_is_lightweight_and_guide_is_loaded_only_for_selected_skill(tmp_path):
    skills = tmp_path/'skills'; guide = skills/'example'; guide.mkdir(parents=True)
    (guide/'SKILL.md').write_text('---\nname: example\ndescription: Example operation.\naccepts-milestones: [prepared]\nproduces-milestone: result\nreusable-outputs: [result_path]\n---\nPRIVATE_GUIDE_BODY\n')
    registry = SkillRegistry(skills)
    assert 'PRIVATE_GUIDE_BODY' not in json.dumps(registry.planning_catalog())
    assert 'PRIVATE_GUIDE_BODY' not in registry.catalog()
    assert 'PRIVATE_GUIDE_BODY' in registry.read('example')
    store, sid = create(tmp_path/'sessions')
    model = Model([action('skill', 'mr-cml-ma'), 'Inspected the selected guide.'])
    Agent(ROOT, store, model=model).run(sid, 'Explain this tool')
    contexts = [json.loads(c['user']) for c in model.calls if c['role']=='search']
    assert contexts[0]['active_guide'] is None
    assert contexts[1]['active_guide']['name'] == 'mr-cml-ma'
    assert '## Choosing inputs' in contexts[1]['active_guide']['content']
    assert '## Use in Python' not in contexts[1]['skill_catalog']


def test_result_index_includes_custom_artifacts_and_unreadable_responses(tmp_path):
    registry=SkillRegistry(ROOT/'skills')
    bad=save_response(tmp_path,'workspace/bad/response.json', [])
    work=dict(artifacts=['workspace/custom.tsv', 'workspace/missing/response.json', bad])
    before=json.dumps(work)
    result=result_index(work,tmp_path,registry)
    assert result['artifact_refs'][0]=='workspace/custom.tsv'
    assert [x['availability'] for x in result['results']]==[
        'missing or unreadable response', 'unrecognized response; inspect on demand']
    assert json.dumps(work)==before


def test_recovery_planning_receives_current_task_evidence_and_text_examples(tmp_path):
    store, sid=create(tmp_path)
    model=Model([action('execute', 'from pathlib import Path; Path("cache.tsv").write_text("verified cache")'),
                 action('evaluate','Endpoint unavailable.'), action('execute', 'from pathlib import Path; from mrcat.tools import publish_result; publish_result("cache", {"text":Path("cache.tsv").read_text()})'), 'Done.'],
                [decision('mr','propose',execute=True)],
                ['1. Use the authorized endpoint.', '1. Reuse the current task cache with the requested skill.'],
                [dict(route='replan',reason='Endpoint unavailable; reuse the supplied cache.')])
    done=Agent(ROOT,store,model=model).run(sid,'Run with endpoint or supplied cache')
    sent=[json.loads(c['user']) for c in model.calls if c['role']=='planner'][-1]
    assert 'skill_options' in sent
    assert sent['available_results']['active_task']['task_id']=='task1'
    assert any(p.endswith('/cache.tsv') for p in sent['available_results']['active_task']['artifact_refs'])
    assert 'Reuse and recovery item guidance' in sent['few_shot']
    assert all(isinstance(p['text'],str) for p in done['task_history'][0]['plan_history'])
    assert 'execution_queue' not in done['task_history'][0]


@pytest.mark.parametrize('bad', ['{"plan_items": []}', '["Use mr-cml-ma"]', '```json\n{}\n```', 'steps:\n  - skill: mr-cml-ma', ''])
def test_invalid_plan_contract_is_rejected(bad):
    with pytest.raises(ValueError): parse_plan(bad)


def test_planner_retries_format_only_then_publishes_plain_text(tmp_path):
    store,sid=create(tmp_path)
    plan='1. Use mr-bwmr with the supplied MRdat.'
    model=Model(decisions=[decision('mr','propose')], plans=['{"plan_items": []}',plan])
    done=Agent(ROOT,store,model=model).run(sid,'Run BWMR with the prepared pair')
    calls=[json.loads(c['user']) for c in model.calls if c['role']=='planner']
    assert len(calls)==2 and 'format_error' in calls[1]
    assert done['pending']['plan_items'][0]['title']==plan
    assert [e['content'] for e in done['events'] if e['type']=='plan_updated']==[done['plan']]


def test_prior_search_results_remain_visible_beside_current_search(tmp_path):
    store,sid=create(tmp_path)
    directory=store.directory(sid)
    first=save_response(directory,'workspace/bmi/response.json',dict(outputs=dict(status='ok',
         gwas_search_results=dict(shortlists_path=str(directory/'workspace/bmi/gwas_search_shortlists.json')))))
    second=save_response(directory,'workspace/cad/response.json',dict(outputs=dict(status='ok',
         gwas_search_results=dict(shortlists_path=str(directory/'workspace/cad/gwas_search_shortlists.json')))))
    state=store.load(sid)
    state['role_memory']['search']=dict(request='Find CAD',status='completed',artifacts=[second],
        history=[dict(request='Find BMI',status='completed',artifacts=[first])])
    available=planning_history(state,directory,SkillRegistry(ROOT/'skills'))['role_results']['search']
    assert available['artifact_refs']==[second] and 'results' not in available
    assert available['history'][0]['artifact_refs']==[first]
    assert available['history'][0]['request']=='Find BMI'
