"""Exercise durable state across instances, exports, node failure and execution."""
import json

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from mrcat.agent import Agent
from mrcat.codeact import CodeActNodes
from mrcat.execution import CodeExecutor
from mrcat.graph import build_graph, recover_execution
from mrcat.fork import fork_session
from mrcat.store import Store
from test_agent import ROOT, Model, action, create, decision


def test_session_and_memory_survive_missing_exports(tmp_path):
    store, sid = create(tmp_path)
    Agent(ROOT, store, model=Model(['Remember this answer.'])).run(sid, 'Explain')
    directory = store.directory(sid)
    with SqliteSaver.from_conn_string(str(directory / 'graph.sqlite')) as saver:
        checkpoint = build_graph(Agent(ROOT, store), saver).get_state(
            {'configurable': {'thread_id': sid}})
        assert checkpoint.values['session']['messages'] == store.load(sid)['messages']
        assert checkpoint.values['session']['role_memory']['search']
    for name in ('session.json', 'memory.md', 'conversation.json'):
        assert not (directory / name).exists()
    restored = Store(tmp_path)
    assert restored.list()[0]['session_id'] == sid
    model = Model(['Second answer.'], [decision('search', 'continue')])
    done = Agent(ROOT, restored, model=model).run(sid, 'Follow up')
    assert [m['content'] for m in done['messages'] if m['role'] == 'user'] == ['Explain', 'Follow up']
    restored.export(done)
    assert (directory / 'memory.md').exists()
    assert not (directory / 'session.json').exists()


def test_export_is_not_an_input_or_recovery_source(tmp_path):
    store, sid = create(tmp_path)
    state = store.load(sid)
    export = dict(state, question='CORRUPTED EXPORT', messages=[])
    (store.directory(sid) / 'session.json').write_text(json.dumps(export))
    assert Store(tmp_path).load(sid)['question'] == state['question']
    (store.directory(sid) / 'graph.sqlite').unlink()
    with pytest.raises(ValueError, match='checkpoint is missing'):
        Store(tmp_path).load(sid)


def test_fork_reads_checkpoint_even_without_exports(tmp_path):
    store, sid = create(tmp_path / 'original')
    assert not (store.directory(sid) / 'session.json').exists()
    copied = fork_session(store.directory(sid), tmp_path / 'copies')
    restored = Store(tmp_path / 'copies').load(copied)
    assert restored['question'] == store.load(sid)['question']
    assert restored['persistence'] == 'langgraph'


def test_legacy_session_import_is_explicit_and_preserves_source(tmp_path):
    store, sid = create(tmp_path / 'original')
    state = store.load(sid)
    state.pop('persistence')
    state['active_task'] = dict(task_id='task1', status='paused', memory='Saved work',
                               plan_items=[dict(step_id='fit', skill_id=None)])
    directory = store.directory(sid)
    journal = directory / 'workspace/outputs/task1/fit/.coding_agent/journal.json'
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps(dict(step=1, entries=[dict(tool='read')])))
    (directory / 'graph.sqlite').unlink()
    source = json.dumps(state)
    (directory / 'session.json').write_text(source)
    assert store.load(sid) == state
    with pytest.raises(ValueError, match='Legacy sessions are read-only'):
        store.save(state)
    copied = fork_session(directory, tmp_path / 'copies')
    imported = Store(tmp_path / 'copies')
    assert imported.has_checkpoint(copied)
    assert imported.load(copied)['active_task']['coding']['fit']['step'] == 1
    assert (directory / 'session.json').read_text() == source
    assert not (directory / 'graph.sqlite').exists()


def test_failed_node_cannot_mutate_committed_memory(tmp_path):
    store, sid = create(tmp_path)
    before = store.load(sid)
    nodes = CodeActNodes(Agent(ROOT, store))
    def fail(flow, state):
        state['question'] = 'UNCOMMITTED'
        store.save(state)
        raise RuntimeError('crash before returning')
    with pytest.raises(RuntimeError, match='crash'):
        nodes.wrap(fail)({'sid': sid, 'session': before})
    assert before['question'] != 'UNCOMMITTED'
    assert Store(tmp_path).load(sid)['question'] == before['question']


def test_external_job_update_preserves_pending_confirmation(tmp_path):
    store, sid = create(tmp_path)
    first = Agent(ROOT, store, model=Model(decisions=[decision('mr', 'propose')]))
    first.run(sid, 'Plan')
    state = store.load(sid)
    pending = state['pending']
    state['job'] = {'status': 'completed', 'job_id': 'old'}
    store.save(state)
    assert Store(tmp_path).load(sid)['pending'] == pending
    model = Model([action('end', 'Question: A required input is missing.', outcome='blocked')], [decision('mr', 'confirm')])
    done = Agent(ROOT, Store(tmp_path), model=model).run(sid, 'Confirm')
    assert (done.get('active_task') or done['task_history'][0])['task_id'] == 'task1'
    assert not any(c['role'] == 'planner' for c in model.calls)


def test_execution_receipt_prevents_duplicate_effect(tmp_path):
    executor = CodeExecutor(ROOT, tmp_path)
    code = "from pathlib import Path\np=Path('count'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"
    result = executor.execute(code, 'python', 'once')
    assert result['returncode'] == 0
    assert executor.execute(code, 'python', 'once') == result
    assert (tmp_path / 'workspace/count').read_text() == '1'
    with pytest.raises(ValueError, match='different source'):
        executor.execute('print(99)', 'python', 'once')
    (tmp_path / 'executions/once/observation.json').unlink()
    with pytest.raises(RuntimeError, match='already started'):
        executor.execute(code, 'python', 'once')


def test_subgraph_checkpoint_retains_completed_tool_before_crash(tmp_path):
    store, sid = create(tmp_path)
    def crash(context):
        raise RuntimeError('model interrupted after execution')
    model = Model([action('execute', 'print(42)'), crash])
    with pytest.raises(RuntimeError, match='model interrupted'):
        Agent(ROOT, store, model=model).run(sid, 'Compute')
    state = Store(tmp_path).load(sid)
    observations = [m for m in state['messages'] if m['role'] == 'observation']
    assert any(json.loads(m['content']).get('stdout', '').strip() == '42' for m in observations)


def test_crash_after_process_completion_recovers_receipt_without_rerun(tmp_path, monkeypatch):
    store, sid = create(tmp_path)
    original = CodeActNodes.observe
    def interrupted(self, flow, state):
        raise KeyboardInterrupt('worker stopped before observe')
    monkeypatch.setattr(CodeActNodes, 'observe', interrupted)
    source = "from pathlib import Path\np=Path('count'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\nprint(42)"
    with pytest.raises(KeyboardInterrupt):
        Agent(ROOT, store, model=Model([action('execute', source)])).run(sid, 'Compute once')
    # Worker lifecycle writes must not lose the receipt awaiting observation.
    state = Store(tmp_path).load(sid)
    state['status'] = 'stopped'
    store.save(state)
    assert state['pending_execution']['action']['execution_id']
    monkeypatch.setattr(CodeActNodes, 'observe', original)
    model = Model(['The saved result is 42.'], [decision('search', 'continue')])
    done = Agent(ROOT, Store(tmp_path), model=model).run(sid, 'Continue')
    assert (store.directory(sid) / 'workspace/count').read_text() == '1'
    assert 'pending_execution' not in done
    assert any(e['type'] == 'execution_recovered' for e in done['events'])
    assert any(m['role'] == 'observation' and json.loads(m['content']).get('stdout', '').strip() == '42'
               for m in done['messages'])


def test_recovery_cannot_attach_an_old_execution_to_a_new_task(tmp_path):
    store, sid = create(tmp_path)
    state = store.load(sid)
    state['active_task'] = dict(task_id='task2', current_item_id='fit', status='running', memory='')
    expected_task = dict(state['active_task'])
    state['pending_execution'] = dict(role='mr', task_id='task1', step_id='fit',
                                     action=dict(kind='execute', execution_id='old'))
    receipt = store.directory(sid) / 'executions/old/observation.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps(dict(execution_id='old', returncode=0)))
    recovered = recover_execution(Agent(ROOT, store), sid, state)
    assert recovered['active_task'] == expected_task
    assert recovered['messages'] == []
    assert 'pending_execution' not in recovered
    assert recovered['events'][-1]['type'] == 'execution_recovery_skipped'


def test_live_events_use_sqlite_without_becoming_recovery_state(tmp_path):
    store, sid = create(tmp_path)
    state = store.load(sid)
    state['job'] = dict(job_id='worker1', status='running')
    store.save(state)
    nodes = CodeActNodes(Agent(ROOT, store))
    def stream_then_crash(flow, private):
        private['question'] = 'NOT COMMITTED'
        store.event(private, 'code_execution', 'Live stdout', stdout='working')
        view = Store(tmp_path).preview(Store(tmp_path).load(sid))
        assert view['events'][-1]['content'] == 'Live stdout'
        assert view['question'] != 'NOT COMMITTED'
        raise RuntimeError('Interrupted before checkpoint')
    with pytest.raises(RuntimeError):
        nodes.wrap(stream_then_crash)({'sid': sid, 'session': state})
    assert Store(tmp_path).load(sid)['events'] == []
    store.clear_live_events(sid)
    assert store.preview(store.load(sid))['events'] == []
    assert not list(store.directory(sid).glob('*.json'))


def test_history_tool_reads_checkpoint_without_exports(tmp_path, monkeypatch):
    from mrcat.tools import session_history
    store, sid = create(tmp_path)
    state = store.load(sid)
    state['messages'] = [dict(role='user', content=f'Message {i}') for i in range(5)]
    store.save(state)
    monkeypatch.setenv('MRCAT_SESSION_DIR', str(store.directory(sid)))
    page = session_history(start=1, limit=2)
    assert [row['content'] for row in page['messages']] == ['Message 1', 'Message 2']
    assert page['next_start'] == 3 and page['has_more']
    assert not (store.directory(sid) / 'conversation.json').exists()
