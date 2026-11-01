"""Effective user requests and compact evidence context without new model rounds."""
import json
from copy import deepcopy

import pytest

from mrcat import manager, memory
from mrcat.agent import Agent
from mrcat.planning import planning_history
from mrcat.skills import SkillRegistry
from test_agent import ROOT, Model, create, decision, action
from test_planning import save_response


def contexts(model, role):
    return [json.loads(call['user']) for call in model.calls if call['role'] == role]


def test_mr_request_revision_commits_only_on_confirmation_and_survives_resume(tmp_path):
    original = 'BMI -> T2D; European ancestry; cML-MA; p < 5e-8; exposure /data/bmi.tsv; exclude study X.'
    revised = original.replace('T2D', 'CAD')
    plan_a = '1. Use mr-cml-ma for the prepared BMI to T2D pair.'
    plan_b = '1. Use mr-cml-ma for the prepared BMI to CAD pair.'
    store, sid = create(tmp_path, original)
    model = Model([action('ask', 'Provide the outcome file.'), action('ask', 'Provide CAD metadata.'),
                   action('ask', 'The CAD metadata is still needed.')],
        decisions=[decision('mr', 'propose', execute=True, effective_request=original),
                   decision('mr', 'revise', effective_request=revised),
                   decision('respond', 'respond') | {'message': 'The new proposal changes the outcome.'},
                   decision('mr', 'confirm'), decision('mr', 'continue')], plans=[plan_a, plan_b])
    agent = Agent(ROOT, store, model=model)
    agent.run(sid, original)
    pending = agent.run(sid, 'Change only the outcome to CAD')
    assert pending['pending']['request'] == revised
    assert pending['active_task']['request'] == original
    assert contexts(model, 'manager')[1]['active_task']['request'] == original
    assert contexts(model, 'planner')[1]['effective_request'] == revised
    assert contexts(model, 'planner')[1]['latest_request'] == 'Change only the outcome to CAD'
    discussed = agent.run(sid, 'What changed?')
    assert discussed['pending'] == pending['pending']
    assert discussed['active_task'] == pending['active_task']
    confirmed = agent.run(sid, 'Confirm')
    assert confirmed['active_task']['request'] == revised
    assert confirmed['active_task']['task_id'] == 'task1'
    resumed = agent.run(sid, 'Continue')
    assert resumed['active_task']['request'] == revised
    assert contexts(model, 'mr')[-1]['work_request'] == revised
    assert contexts(model, 'mr')[-1]['user_updates'][-1] == 'Continue'
    assert len(contexts(model, 'planner')) == 2
    assert len(contexts(model, 'manager')) == 5
    assert not contexts(model, 'memory')
    assert len(resumed['active_task']['plan_history']) == 2


def test_pending_request_merge_is_passed_to_planner_and_new_task(tmp_path):
    original = 'European BMI -> T2D, cML-MA, p < 5e-8, no proxy variants.'
    merged = original.replace('T2D', 'CAD')
    store, sid = create(tmp_path, original)
    model = Model([action('ask', 'Which CAD file?')], decisions=[
        decision('mr', 'propose', effective_request=original),
        decision('mr', 'revise', effective_request=merged), decision('mr', 'confirm')])
    agent = Agent(ROOT, store, model=model)
    agent.run(sid, original)
    agent.run(sid, 'Use CAD instead')
    assert contexts(model, 'manager')[-1]['pending']['request'] == original
    done = agent.run(sid, 'Yes')
    assert done['active_task']['request'] == merged
    assert merged in done['active_task']['memory']
    assert not contexts(model, 'memory')


def test_search_clarification_merges_request_without_planning(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('ask', 'Which population?'), action('ask', 'Which source?'), 'Continued.'],
        decisions=[decision('search', 'run', effective_request='Find CAD GWAS.'),
                   decision('search', 'continue', effective_request='Find CAD GWAS in Europeans.'),
                   decision('search', 'continue')])
    agent = Agent(ROOT, store, model=model)
    agent.run(sid, 'Find CAD GWAS')
    clarified = agent.run(sid, 'Europeans')
    assert clarified['role_memory']['search']['request'] == 'Find CAD GWAS in Europeans.'
    assert clarified['pending']['kind'] == 'clarification'
    resumed = agent.run(sid, 'Continue')
    assert contexts(model, 'search')[-1]['work_request'] == 'Find CAD GWAS in Europeans.'
    assert resumed['active_task'] is None and resumed['plan'] == ''
    assert not contexts(model, 'planner')


@pytest.mark.parametrize('action_name', ['respond', 'confirm', 'cancel'])
def test_non_editing_actions_cannot_rewrite_effective_request(action_name):
    route = 'respond' if action_name == 'respond' else 'mr'
    value = decision(route, action_name, effective_request='Silently changed the study.')
    if route == 'respond': value['message'] = 'Answer'
    with pytest.raises(ValueError, match='preserve the request'):
        manager.parse_decision(json.dumps(value))


def test_cancel_revision_restores_confirmed_request(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('ask', 'Need metadata.')], decisions=[
        decision('mr', 'propose', execute=True, effective_request='Analyze BMI to T2D.'),
        decision('mr', 'revise', effective_request='Analyze BMI to CAD.'), decision('mr', 'cancel')])
    agent = Agent(ROOT, store, model=model)
    original = agent.run(sid, 'Analyze BMI to T2D now')
    agent.run(sid, 'Change to CAD')
    cancelled = agent.run(sid, 'Cancel the revision')
    assert cancelled['active_task'] == original['active_task']
    assert cancelled['memory_request'] == 'Analyze BMI to T2D.'
    assert cancelled['plan'] == original['plan']


def test_executor_plan_once_and_unrelated_history_is_not_expanded(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('ask', 'Need data.')], [decision('mr', 'propose', execute=True)],
                  ['1. Use mr-cml-ma with the task2 prepared pair.'])
    agent = Agent(ROOT, store, model=model)
    agent.run(sid, 'Use task2 prepared data for cML-MA')
    state = store.load(sid)
    state['task_history'] = [dict(task_id=f'task{n}', request=f'Study {n}', description=f'Study {n}',
        status='completed', memory=f'History {n} findings', artifacts=[f'workspace/task{n}/response.json']) for n in [2, 20]]
    state['role_memory']['search'] = dict(request='Old search', memory='EARLIER_SEARCH_FINDINGS ' * 200, artifacts=[], status='completed')
    state['active_task']['plan_items'][0]['reuse_from'] = ['task2/prepare/gwas_pair_prepare_result']
    before = deepcopy(state)
    sent = agent.executor_context(state, 'mr')
    assert sent['current_item'] == state['active_task']['plan_items'][0]
    assert sent['current_plan'] == [sent['current_item']]
    assert [t['task_id'] for t in sent['saved_tasks']] == ['task2']
    assert len(sent['other_role_summaries']['search']['summary']) <= 350
    assert state['role_memory']['search']['memory'] not in json.dumps(sent)
    assert 'history_access' in sent and state == before


def test_planner_expands_explicit_old_task_and_keeps_other_results_discoverable(tmp_path):
    store, sid = create(tmp_path)
    state = store.load(sid); directory = store.directory(sid)
    for n in [1, 2, 20]:
        ref = save_response(directory, f'workspace/task{n}/response.json', dict(outputs=dict(status='ok',
            gwas_pair_prepare_result=dict(mrdat_path=f'workspace/task{n}/MRdat.tsv'))))
        state['task_history'].append(dict(task_id=f'task{n}', request=f'Exposure {n} -> CAD', status='completed', artifacts=[ref]))
    before = deepcopy(state)
    history = planning_history(state, directory, SkillRegistry(ROOT/'skills'), references=('Use task2.',))['task_history']
    assert [t['task_id'] for t in history] == ['task1', 'task2', 'task20']
    assert 'results' in history[1] and 'results' not in history[0] and 'results' not in history[2]
    assert history[0]['artifact_refs'] == ['workspace/task1/response.json']
    assert history[1]['results'][0]['outputs'][0]['fields']['mrdat_path'] == 'workspace/task2/MRdat.tsv'
    assert state == before


def test_delivery_keeps_resolved_findings_and_runtime_record_is_idempotent():
    work = dict(memory=memory.replace_section(memory.initial_memory('Analyze file'), 'Recent Progress',
        'Read the file: delimiter is tab; resolved the parsing error. Reuse workspace/prepared.tsv.'),
        execution_facts=['Execution x: exited, return code 0.'], artifacts=['workspace/prepared.tsv'])
    memory.record_delivery(work, 'ask', 'Supply the outcome metadata.')
    note = work['memory']
    memory.apply_delivery(work)
    assert work['memory'] == note
    assert 'delimiter is tab' in memory.working_note(work)
    assert '[Runtime record]' not in memory.working_note(work)
    memory.record_delivery(work, 'final', 'Delivered the prepared input.')
    assert 'delimiter is tab' in work['memory']
    assert 'Supply the outcome metadata.' not in work['memory']
    assert work['memory'].count('[Runtime record]') == 1


def test_one_code_cell_does_not_add_a_memory_or_planning_round(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', 'print("count=3; input already read")'), 'Found 3 records.'])
    Agent(ROOT, store, model=model).run(sid, 'Count the supplied records')
    assert [c['role'] for c in model.calls] == ['manager', 'search', 'search', 'memory']
    assert contexts(model, 'memory')[0]['effective_request'] == 'Count the supplied records'
    assert 'count=3' in contexts(model, 'search')[-1]['recent_messages'][-1]['content']
