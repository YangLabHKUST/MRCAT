"""Plan ownership, exception recovery and evidence boundaries; no remote model calls."""
import json
import pytest
from mrcat.agent import Agent, parse_action
from mrcat.graph import build_graph
from test_agent import ROOT, Model, create, decision, action


def roles(model, role):
    return [json.loads(c['user']) for c in model.calls if c['role'] == role]


@pytest.mark.parametrize('role', ['search'])
def test_new_request_owns_work_without_planner(tmp_path, role):
    store, sid = create(tmp_path)
    model = Model(['Old work done.', action('execute', 'print("new work")'), 'New work done.'],
                  [decision(role), decision(role)])
    agent = Agent(ROOT, store, model=model)
    agent.run(sid, 'Read saved BMI candidates only; do not search again.')
    done = agent.run(sid, 'Search other databases for CAD.')
    context = roles(model, role)[1]
    assert context['current_plan'] == ''
    assert context['work_request'] == 'Search other databases for CAD.'
    assert 'BMI' not in context['memory']
    assert 'BMI' in context['prior_work'][-1]['request']
    assert roles(model, 'manager')[-1]['role_work'][role]['status'] == 'completed'
    assert not roles(model, 'planner')
    assert not any(e['type'] == 'plan_updated' for e in done['events'])
    assert len([e for e in done['events'] if e['type'] == 'code_execution']) == 1


def test_search_clarification_continues_work_across_instances(tmp_path):
    store, sid = create(tmp_path)
    first = Model([action('ask', 'Which file?')], plans=['Inspect the supplied file.'])
    waiting = Agent(ROOT, store, model=first).run(sid, 'Inspect file')
    second = Model(['Inspected.'], [decision('search', 'continue')])
    done = Agent(ROOT, store, model=second).run(sid, 'Use file A')
    assert not roles(second, 'planner')
    assert done['plan'] == waiting['plan'] and done['pending'] is None


def test_small_error_is_repaired_without_evaluation_or_replanning(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', 'raise ValueError("bad input")'),
                   action('execute', 'print("corrected")'), 'Repaired.'])
    Agent(ROOT, store, model=model).run(sid, 'Check input')
    assert not roles(model, 'planner')
    assert not roles(model, 'evaluate')


def test_structured_action_accepts_message_after_action_and_literal_tags():
    parsed = parse_action(json.dumps(dict(type='execute', body='print("<replan>literal</replan>")',
                                         message='Proceed.')))
    assert parsed['kind'] == 'execute' and parsed['message'] == 'Proceed.'
    assert '<replan>' in parsed['body']


@pytest.mark.parametrize('raw', [
    '<replan>new approach</replan><message>search now</message>',
    '{"type":"replan","body":"new plan"}',
    '{"type":"final","body":"done","plan":"new plan"}',
    '{"type":"final","body":"done","memory":"claimed success"}',
    '{"type":[],"body":"bad"}',
    '{"type":"execute","body":"print(42)","language":[]}',
    '[{"type":"execute","body":"print(42)"}]',
    '{"type":"execute","body":"print(42)"} trailing text',
])
def test_invalid_or_deprecated_actions_are_not_executed(raw):
    with pytest.raises(ValueError):
        parse_action(raw)


def test_recovery_applies_only_planner_text_and_preserves_task_identity(tmp_path):
    store, sid = create(tmp_path)
    review = dict(route='replan', reason='Remote endpoint unavailable; reuse the verified workspace/cache.json.')
    model = Model([action('execute', 'import json; from pathlib import Path; Path("cache.json").write_text(json.dumps(dict(value=42)))'),
                   action('evaluate', 'Endpoint remains unavailable.'),
                   action('execute', 'import json\nfrom pathlib import Path\nfrom mrcat.tools import publish_result\npublish_result("cache", {"cached": json.loads(Path("cache.json").read_text())})'), 'Done with cached data.'],
                  [decision('mr', 'propose', execute=True)], ['Use endpoint.', 'Use the verified cache.'], [review])
    graph_nodes = dict(build_graph(Agent(ROOT, store, model=model)).get_subgraphs())['mr'].get_graph().nodes
    assert 'evaluate' in graph_nodes and 'recover' in graph_nodes and 'replan' not in graph_nodes
    done = Agent(ROOT, store, model=model).run(sid, 'Run with endpoint or supplied cache')
    task = done['task_history'][0]
    assert task['task_id'] == 'task1' and len(task['plan_history']) == 2
    assert task['plan_items'][0]['title'] == 'Use the verified cache.'
    assert any(p.endswith('/cache.json') for p in task['artifacts'])
    assert 'workspace/cache.json' in roles(model, 'planner')[-1]['recovery']['reason']
    types = [e['type'] for e in done['events']]
    requested = types.index('executor_handoff')
    approved = types.index('evaluation', requested)
    started = types.index('recovery_started')
    applied = max(i for i,t in enumerate(types) if t == 'plan_updated')
    assert requested < approved < started < applied


def test_planner_failure_during_recovery_preserves_old_plan_and_pauses(tmp_path):
    store, sid = create(tmp_path)
    base = Model([action('evaluate', 'Blocked.')], [decision('mr', 'propose', execute=True)],
                 ['Original plan.'], [dict(route='replan', reason='Needs another source; replan using the authorized cache.')])
    planner_calls = 0
    def model(**kwargs):
        nonlocal planner_calls
        if kwargs['role'] == 'planner':
            planner_calls += 1
            if planner_calls == 2:
                raise RuntimeError('Planner offline')
        return base(**kwargs)
    done = Agent(ROOT, store, model=model).run(sid, 'Run now')
    assert done['status'] == 'paused' and done['active_task']['task_id'] == 'task1'
    assert done['active_task']['plan_items'][0]['title'] == 'Original plan.' and not done['task_history']
    assert len(done['active_task']['plan_history']) == 1
    failed = next(i for i,e in enumerate(done['events']) if e['type'] == 'recovery_failed')
    assert not any(e['type'] == 'plan_updated' for e in done['events'][failed:])
    # Pausing below the context threshold preserves the journal without another summary.
    assert not roles(base, 'memory')
    from mrcat.memory import control_facts
    assert any(e['type'] == 'recovery_failed' for e in control_facts(done, 'mr'))


def test_rejected_executor_claim_is_excluded_from_memory_facts(tmp_path):
    store, sid = create(tmp_path)
    base = Model(['Done.'], plans=['Original plan.'])
    replies = iter(['{"type":"replan","body":"UNEXECUTED_CLAIM: supplementary search completed"}',
                    json.dumps(action('final', 'Stopped with a limitation.'))])
    def model(**kwargs):
        if kwargs['role'] == 'search':
            return next(replies)
        return base(**kwargs)
    done = Agent(ROOT, store, model=model).run(sid, 'Find CAD data')
    context = roles(base, 'memory')[-1]
    assert 'UNEXECUTED_CLAIM' not in json.dumps(context)
    assert all(m['role'] != 'assistant' for m in context['observations'])
    assert done['plan'] == ''
    assert any('action_rejected' in m['content'] for m in context['observations'])
    assert 'UNEXECUTED_CLAIM' in json.dumps(store.load(sid)['messages'])


def test_repeated_observations_trigger_evaluate_but_not_automatic_replan(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', 'print("same source lines")')] * 3 + ['Answer.'])
    Agent(ROOT, store, model=model).run(sid, 'Inspect')
    assert len(roles(model, 'evaluate')) == 1
    assert 'identical observations' in roles(model, 'evaluate')[0]['trigger']
    assert not roles(model, 'planner')


def test_progress_without_files_can_continue(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', f'print({i} ** 2)') for i in range(6)] + ['Computed.'])
    done = Agent(ROOT, store, model=model).run(sid, 'Calculate six values')
    assert done['status'] == 'completed'
    assert len(roles(model, 'evaluate')) == 1
    assert 'can be useful progress' in roles(model, 'evaluate')[0]['trigger']
    assert not roles(model, 'planner')


def test_blocked_finalization_never_completes_task(tmp_path):
    status = 'waiting_user'
    store, sid = create(tmp_path)
    model = Model([action('evaluate', 'Need a decision.')], [decision('mr', 'propose', execute=True)],
                  evaluations=[dict(route='finalize', reason='Blocked: no authorized input.')],
                  finalizations=['blocked\nPlease supply data.\n[END_FINAL_SUMMARY]'])
    done = Agent(ROOT, store, model=model).run(sid, 'Run now')
    assert done['status'] == status and done['active_task']['status'] == status
    assert not done['task_history'] and not any(e['type'] == 'final' for e in done['events'])


def test_recovery_attempts_are_bounded_without_false_completion(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('evaluate', 'Still blocked.')] * 4)
    done = Agent(ROOT, store, model=model).run(sid, 'Inspect')
    assert len(roles(model, 'evaluate')) == 3 and done['status'] == 'paused'
    assert not any(e['type'] == 'final' for e in done['events'])


def test_three_code_failures_enter_evaluate(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', f'raise ValueError("failure {i}")') for i in range(3)],
                  evaluations=[dict(route='stop', reason='No further supported repair.', message='Input unavailable.')])
    done = Agent(ROOT, store, model=model).run(sid, 'Inspect')
    assert len(roles(model, 'evaluate')) == 1 and done['status'] == 'paused'
    assert 'Three consecutive execution failures' in roles(model, 'evaluate')[0]['trigger']
