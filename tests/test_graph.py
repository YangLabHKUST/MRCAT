import json
from pathlib import Path
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.state import CompiledStateGraph
from mrcat.agent import Agent
from mrcat.workflow.graph import build_graph
from mrcat.state import memory
from test_agent import ROOT, Model, create, decision, action, verified_value


def test_real_graph_and_cross_instance_plan_resume(tmp_path):
    store, sid = create(tmp_path)
    first = Agent(ROOT, store, model=Model(decisions=[decision('mr', 'propose')]))
    assert isinstance(build_graph(first), CompiledStateGraph)
    nodes = set(build_graph(first).get_graph().nodes)
    assert {'manager', 'search', 'mr', 'report', 'wait'} <= nodes
    assert not {'planner', 'task', 'execute', 'observe'} & nodes
    subgraphs = dict(build_graph(first).get_subgraphs())
    assert set(subgraphs) == {'search', 'mr', 'report'}
    for role, subgraph in subgraphs.items():
        child_nodes = set(subgraph.get_graph().nodes)
        if role == 'report':
            assert {'evidence', 'literature', 'writer', 'validate', 'judge', 'revise', 'export', 'deliver'} <= child_nodes
            assert not {'executor', 'evaluate', 'execute', 'planner'} & child_nodes
            continue
        assert {'executor', 'evaluate'} <= child_nodes
        if role == 'mr':
            inner = dict(subgraph.get_subgraphs())['executor']
            assert {'model', 'execute', 'observe', 'handoff'} <= set(inner.get_graph().nodes)
            assert 'evaluate' not in inner.get_graph().nodes
            assert not {'execute', 'observe'} & child_nodes
        else:
            assert {'execute', 'observe'} <= child_nodes
        assert ('planner' in child_nodes) == (role == 'mr')
        assert ('recover' in child_nodes) == (role == 'mr')
    first.run(sid, 'Plan the analysis')
    with SqliteSaver.from_conn_string(str(store.directory(sid) / 'graph.sqlite')) as saver:
        snapshot = build_graph(first, saver).get_state({'configurable': {'thread_id': sid}})
        assert snapshot.next == ('wait',)
    model = Model([verified_value(), 'Analysis completed.'], [decision('mr', 'confirm')])
    done = Agent(ROOT, store, model=model).run(sid, 'Confirm')
    assert done['task_history'][0]['task_id'] == 'task1'
    assert not any(c['role'] == 'planner' for c in model.calls)
    assert [m['content'] for m in done['messages'] if m['role'] == 'user'] == ['Plan the analysis', 'Confirm']


def test_long_outputs_do_not_cause_memory_on_every_round(tmp_path):
    store, sid = create(tmp_path)
    actions = [action("execute", f'print("{i}" * 18000)') for i in range(8)] + ["Done."]
    model = Model(actions)
    done = Agent(ROOT, store, model=model).run(sid, 'Inspect long output')
    calls = [c['role'] for c in model.calls]
    assert calls.count('search') == 9 and calls.count('memory') == 1
    assert done['status'] == 'completed'
    assert len(done['messages'][2]['content']) > 10000


def test_observation_keeps_error_and_paths_and_more_of_latest_output():
    result = dict(execution_id='x', status='exited', returncode=1,
        stdout='HEADER\n' + 'x' * 14000, stderr='FileNotFoundError: important/path/result.json',
        source_path='executions/x/code.py', stdout_path='executions/x/stdout.log', stderr_path='executions/x/stderr.log')
    message = dict(role='observation', content=json.dumps(result))
    rendered = memory.recent_messages([message])[0]['content']
    decoded = json.loads(rendered)
    assert decoded['returncode'] == 1 and 'FileNotFoundError' in decoded['stderr']
    assert decoded['stdout_path'] == result['stdout_path']
    assert 2500 < len(decoded['stdout']) < 6500
    assert len(rendered) <= 6500


def test_incomplete_memory_does_not_replace_facts_and_answer_is_already_visible(tmp_path):
    store, sid = create(tmp_path)
    state = store.load(sid)
    work = memory.work_state(state, 'search')
    work['memory'] = memory.initial_memory('Preserve this verified task')
    original = work['memory']
    store.save(state)
    base = Model([action('execute', 'print(42)'), 'The answer is 42.'])
    def model(**kwargs):
        if kwargs['role'] == 'memory':
            assert any(e['type']=='final' and e['content']=='The answer is 42.' for e in store.load(sid)['events'])
            return '### Confirmed Facts\nThe result is in the directory that'
        return base(**kwargs)
    done = Agent(ROOT, store, model=model).run(sid, 'Inspect')
    assert done['status'] == 'completed'
    work = done['role_memory']['search']
    assert work['history'][-1]['memory'] == original
    assert '### Research Goal\nInspect' in work['memory']
    assert 'Result delivered to the user' in work['memory']
    assert work['delivery']['content'] == 'The answer is 42.'
    assert 'No pending work for this delivered request.' in work['memory']
    assert any(e['type']=='memory_warning' for e in done['events'])


def test_no_summary_for_simple_answer(tmp_path):
    store, sid = create(tmp_path)
    model = Model(['Here is an explanation.'])
    Agent(ROOT, store, model=model).run(sid, 'Explain')
    assert [c['role'] for c in model.calls] == ['manager', 'search']
