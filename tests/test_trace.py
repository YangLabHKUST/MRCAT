"""Trace evidence, reconstruction, continuation and isolation from agent behavior."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path

import pytest

from mrcat import trace
from mrcat.agent import Agent
from mrcat.runtime.execution import CodeExecutor
from mrcat.state.store import Store
from test_agent import ROOT, Model


@pytest.fixture(autouse=True)
def local_checkpoints(tmp_path, monkeypatch):
    monkeypatch.setenv('MRCAT_CHECKPOINT_DIR', str(tmp_path / 'checkpoints'))


def rows(directory):
    records = [json.loads(line) for line in (directory / 'trace.jsonl').read_text().splitlines()]
    assert [r['seq'] for r in records] == list(range(1, len(records) + 1))
    assert len({r['event_id'] for r in records}) == len(records)
    assert all(r['session_id'] == directory.name for r in records)
    return records


def responding(text='Answer'):
    return Model(decisions=[dict(route='respond', action='respond', message=text, effective_request=None)])


def run_answer(tmp_path):
    store = Store(tmp_path / 'sessions')
    state = store.create('Question', 'deepseek')
    sid = state['session_id']
    model = responding()
    done = Agent(ROOT, store, model=model).run(sid, 'Question')
    return store, sid, done, model


def test_new_turn_records_inputs_responses_and_final_without_extra_calls(tmp_path):
    store, sid, done, model = run_answer(tmp_path)
    records = rows(store.directory(sid))
    assert len(model.calls) == 1
    assert done['status'] == 'completed'
    assert done['messages'][-1]['content'] == 'Answer'
    assert {r['capture_mode'] for r in records} == {'live'}
    kinds = [r['type'] for r in records]
    assert {'trace_metadata', 'session_created', 'turn_start', 'message', 'user_message',
            'llm_start', 'llm_end', 'final', 'turn_end'} <= set(kinds)
    start = next(r for r in records if r['type'] == 'llm_start')
    end = next(r for r in records if r['type'] == 'llm_end')
    assert start['data']['system'] == model.calls[0]['system']
    assert start['data']['user'] == model.calls[0]['user']
    assert end['parent_id'] == start['event_id']
    assert end['data']['status'] == 'returned'
    assert json.loads(end['data']['response'])['message'] == 'Answer'


def test_execution_records_full_logs_and_failed_and_successful_receipts(tmp_path):
    store = Store(tmp_path / 'sessions')
    state = store.create('Compute', 'deepseek')
    directory = store.directory(state['session_id'])
    executor = CodeExecutor(ROOT, directory, poll_interval=.01)
    code = "print('x' * 20001)\nraise ValueError('test failure')\n"
    failed = executor.execute(code, 'python', 'failure')
    assert failed['returncode'] != 0
    executor.execute("print('repaired')", 'python', 'success')
    records = rows(directory)
    starts = [r for r in records if r['type'] == 'execution_start']
    ends = [r for r in records if r['type'] == 'execution_end']
    assert len(starts) == len(ends) == 2
    assert starts[0]['data']['code'] == code
    assert ends[0]['data']['stdout'] == 'x' * 20001 + '\n'
    assert ends[0]['data']['stdout'] != failed['stdout']
    assert 'test failure' in ends[0]['data']['stderr']
    assert ends[1]['data']['observation']['returncode'] == 0


def test_model_error_is_retained_and_raised_unchanged(tmp_path):
    store = Store(tmp_path / 'sessions')
    state = store.create('Fail', 'deepseek')
    def fail(**kwargs):
        raise ValueError('deliberate test failure')
    agent = Agent(ROOT, store, model=fail)
    with pytest.raises(ValueError, match='deliberate test failure'):
        agent.run(state['session_id'], 'Fail')
    records = rows(store.directory(state['session_id']))
    end = next(r for r in records if r['type'] == 'llm_end')
    assert end['data']['status'] == 'error'
    assert end['data']['error']['type'] == 'ValueError'
    assert records[-1]['type'] == 'turn_end'
    assert records[-1]['data']['exception_type'] == 'ValueError'


def test_backfill_is_read_only_complete_and_idempotent(tmp_path):
    store, sid, done, model = run_answer(tmp_path)
    directory = store.directory(sid)
    executor = CodeExecutor(ROOT, directory, poll_interval=.01)
    executor.execute("print('historical stdout')", 'python', 'old_code')
    report = directory / 'workspace/outputs/task1/final_summary.md'
    report.parent.mkdir(parents=True)
    report.write_text('Final report evidence.')
    (directory / 'trace.jsonl').unlink()
    before = {str(p): sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*')
              if p.is_file() and p.name != '.trace.lock'}
    assert trace.backfill(directory)['created']
    records = rows(directory)
    assert {r['capture_mode'] for r in records} == {'reconstructed'}
    assert any(r['type'] == 'report' and r['data']['text'] == report.read_text() for r in records)
    assert any(r['type'] == 'execution_end' and r['data']['stdout'] == 'historical stdout\n' for r in records)
    assert any(r['type'] == 'llm_end' for r in records)
    assert len([r for r in records if r['type'] == 'message']) == len(done['messages'])
    assert all(r['timestamp'] is None for r in records if r['type'] in {'llm_start', 'llm_end', 'message'})
    for path, digest in before.items():
        assert sha256(Path(path).read_bytes()).hexdigest() == digest
    original = (directory / 'trace.jsonl').read_bytes()
    assert not trace.backfill(directory)['created']
    assert (directory / 'trace.jsonl').read_bytes() == original
    assert len(model.calls) == 1


def test_old_session_continues_with_history_then_live_events(tmp_path):
    store, sid, done, _ = run_answer(tmp_path)
    directory = store.directory(sid)
    (directory / 'trace.jsonl').unlink()
    Agent(ROOT, store, model=responding('Second answer')).run(sid, 'Continue')
    records = rows(directory)
    first_live = next(i for i, row in enumerate(records) if row['capture_mode'] == 'live')
    assert all(row['capture_mode'] == 'reconstructed' for row in records[:first_live])
    assert all(row['capture_mode'] == 'live' for row in records[first_live:])
    assert records[first_live]['type'] == 'turn_start'
    assert any(r['type'] == 'final' and r['data']['content'] == 'Second answer' for r in records)


def test_concurrent_writers_and_partial_tail_recovery(tmp_path):
    store = Store(tmp_path / 'sessions')
    directory = store.directory(store.create('Concurrent', 'deepseek')['session_id'])
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda n: trace.emit(directory, 'probe', {'n': n}, event_id=f'probe:{n}'), range(60)))
    assert len([r for r in rows(directory) if r['type'] == 'probe']) == 60
    with (directory / 'trace.jsonl').open('ab') as handle:
        handle.write(b'{"incomplete":')
    trace.emit(directory, 'probe', {'n': 60}, event_id='probe:60')
    records = rows(directory)
    assert records[-2]['type'] == 'trace_repaired'
    assert records[-1]['event_id'] == 'probe:60'
    trace.emit(directory, 'probe', {'n': 60}, event_id='probe:60')
    assert rows(directory) == records


def test_trace_failure_does_not_change_agent_result(tmp_path, monkeypatch, caplog):
    store = Store(tmp_path / 'sessions')
    sid = store.create('Question', 'deepseek')['session_id']
    def broken(*args, **kwargs):
        raise OSError('trace device unavailable')
    monkeypatch.setattr(trace, '_append', broken)
    model = responding()
    done = Agent(ROOT, store, model=model).run(sid, 'Question')
    assert done['status'] == 'completed' and done['messages'][-1]['content'] == 'Answer'
    assert len(model.calls) == 1
    assert 'workflow continues' in caplog.text


def test_redaction_preserves_noncredential_urls_and_numerical_results(tmp_path, monkeypatch):
    monkeypatch.setenv('TEST_API_KEY', 'sk-' + 'a' * 30)
    store = Store(tmp_path / 'sessions')
    directory = store.directory(store.create('Question', 'deepseek')['session_id'])
    trace.emit(directory, 'probe', dict(text='sk-' + 'a' * 30, beta=.0123,
               url='https://example.org/data?study=123', api_key='another credential'))
    data = rows(directory)[-1]['data']
    assert data['text'] == data['api_key'] == '[REDACTED]'
    assert data['beta'] == .0123
    assert data['url'] == 'https://example.org/data?study=123'


def test_backfill_refuses_running_session_and_linked_view(tmp_path):
    store = Store(tmp_path / 'sessions')
    state = store.create('Question', 'deepseek')
    directory = store.directory(state['session_id'])
    (directory / 'trace.jsonl').unlink()
    state['status'] = 'running'
    store.save(state)
    with pytest.raises(ValueError, match='running'):
        trace.backfill(directory)
    view = tmp_path / 'view'
    view.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match='Linked'):
        trace.backfill(view)
    assert not (directory / 'trace.jsonl').exists()


def test_native_tools_results_artifacts_and_reconstruction_keep_call_links(tmp_path):
    from test_agent import decision
    from test_coding_graph import CodingModel
    store = Store(tmp_path / 'sessions')
    sid = store.create('Compute', 'deepseek')['session_id']
    model = CodingModel([
        dict(tool='write', path='analysis.py', content='import json\nfrom pathlib import Path\nPath("result.json").write_text(json.dumps({"value": 42}))'),
        dict(tool='run', path='analysis.py', language='python'),
        dict(tool='publish', name='answer', path='result.json'),
        dict(tool='finish', outcome='complete', body='Verified 42.'),
    ], decisions=[decision('mr', 'propose')])
    done = Agent(ROOT, store, model=model, auto_confirm_plan=True).run(sid, 'Compute')
    assert done['status'] == 'completed'
    directory = store.directory(sid)
    original = rows(directory)
    calls = [r for r in original if r['type'] == 'tool_start']
    results = [r for r in original if r['type'] == 'tool_result']
    assert len(calls) == len(results) == 4
    assert {r['parent_id'] for r in results} == {r['event_id'] for r in calls}
    assert any(r['type'] == 'result_registered' for r in original)
    assert any(r['type'] == 'report' for r in original)
    assert any(r['type'] == 'llm_usage_summary' for r in original)
    assert len([r for r in original if r['type'] == 'llm_start']) == len(model.calls)
    artifact = directory / 'workspace/outputs/test/skill/generated_code/attempt.prompt.txt'
    artifact.parent.mkdir(parents=True)
    artifact.write_text('Original saved Skill prompt')
    (directory / 'trace.jsonl').unlink()
    trace.backfill(directory)
    reconstructed = rows(directory)
    assert len([r for r in reconstructed if r['type'] == 'tool_result']) == 4
    assert any(r['type'] == 'saved_artifact' and r['data']['text'] == artifact.read_text() for r in reconstructed)
    assert any(r['type'] == 'llm_usage_summary' for r in reconstructed)
