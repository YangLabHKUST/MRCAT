"""Browser caches must observe other processes without owning workflow state."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
from unittest.mock import patch

from mrcat.store import Store
from mrcat.web.server import create_app
from mrcat.web.service import Service
from test_agent import ROOT


def create_service(tmp_path):
    service = Service(ROOT, tmp_path)
    state = service.store.create('Inspect cached state', 'openai')
    return service, state['session_id']


def test_idle_readers_share_work_and_rebuild_after_restart(tmp_path):
    service, sid = create_service(tmp_path)
    with patch.object(service.store, 'load', wraps=service.store.load) as load, \
         patch.object(service, 'files', wraps=service.files) as files:
        with ThreadPoolExecutor(max_workers=6) as pool:
            snapshots = list(pool.map(lambda _: service.snapshot(sid), range(18)))
        assert load.call_count == files.call_count == 1
        assert all(item is snapshots[0] for item in snapshots)
        assert service.sessions()[0]['session_id'] == sid
        assert load.call_count == 1
    service.views.close()
    restored = Service(ROOT, tmp_path)
    assert restored.snapshot(sid) == snapshots[0]
    restored.views.close()


def test_external_checkpoint_and_wal_events_invalidate_separately(tmp_path):
    service, sid = create_service(tmp_path)
    writer = Store(tmp_path)
    state = writer.load(sid)
    state['job'] = dict(job_id='worker', status='running', pid=os.getpid())
    state['status'] = 'running'
    writer.save(state)
    generation, first, _ = service.snapshot_payload(sid)
    event = dict(id='stdout', type='code_execution', timestamp='1', content='',
                 details={'status': 'running', 'stdout': 'first'})
    with patch.object(service.store, 'load', wraps=service.store.load) as load, \
         patch.object(service, 'files', wraps=service.files) as files:
        writer.publish_live_event(state, event)
        next_generation, live, _ = service.snapshot_payload(sid)
        assert next_generation == generation
        assert live['mr']['events'][-1]['details']['stdout'] == 'first'
        event['timestamp'] = '2'; event['details']['stdout'] = 'first\nsecond'
        writer.publish_live_event(state, event)
        assert service.snapshot(sid)['mr']['events'][-1]['details']['stdout'].endswith('second')
        assert live['mr']['events'][-1]['details']['stdout'] == 'first'
        assert load.call_count == files.call_count == 0
        # Save a terminal state and clear the transient queue. Events must not
        # disappear or duplicate, and newly produced artifacts must be visible.
        state['events'].append(event)
        state['job']['status'] = 'completed'; state['status'] = 'completed'
        (writer.directory(sid) / 'workspace/result.txt').write_text('42')
        writer.save(state)
        done = service.snapshot(sid)
        assert done['state']['status'] == 'completed' and done['active_job'] is None
        assert len(done['mr']['events']) == 1
        assert 'workspace/result.txt' in done['mr']['manifest']['runs'][sid]['artifacts']['files']
        assert load.call_count == files.call_count == 1
    service.views.close()


def test_dead_worker_is_detected_without_database_change(tmp_path):
    service, sid = create_service(tmp_path)
    state = service.store.load(sid)
    state['job'] = dict(job_id='worker', status='running', pid=123456789)
    state['status'] = 'running'
    service.store.save(state)
    with patch('mrcat.web.service.os.kill'):
        assert service.snapshot(sid)['active_job']
    with patch('mrcat.web.service.os.kill', side_effect=ProcessLookupError):
        recovered = service.snapshot(sid)
    assert recovered['state']['status'] == 'paused'
    assert recovered['active_job'] is None
    assert Store(tmp_path).load(sid)['job']['status'] == 'interrupted'
    service.views.close()


def test_command_acknowledgements_do_not_build_snapshots(tmp_path):
    service, sid = create_service(tmp_path)
    with patch.object(service, 'snapshot', side_effect=AssertionError('full snapshot')), \
         patch.object(service, 'files', side_effect=AssertionError('directory scan')), \
         patch('mrcat.web.service.subprocess.Popen') as process:
        process.return_value.pid = 123456789
        accepted = service.reply(sid, 'Continue')
        assert accepted['session']['active_job']['status'] == 'running'
        assert 'mr' not in accepted['session']
        with patch('mrcat.web.service.os.killpg'):
            assert service.stop(sid)['session']['session_id'] == sid
    service.views.close()


def test_stream_sends_deltas_and_reconnect_sends_full_state(tmp_path):
    app = create_app(repo_root=ROOT, artifact_dir=tmp_path)
    service = app.state.service
    state = service.store.create('Stream', 'openai'); sid = state['session_id']
    state['job'] = dict(job_id='worker', status='running', pid=os.getpid())
    state['status'] = 'running'; service.store.save(state)
    endpoint = next(route.endpoint for route in app.routes
                    if getattr(route, 'path', '') == '/api/sessions/{sid}/events')
    class Request:
        async def is_disconnected(self): return False
    async def scenario():
        response = await endpoint(sid, Request())
        stream = response.body_iterator
        assert (await anext(stream)).startswith('event: snapshot\n')
        assert (await anext(stream)).startswith(': heartbeat')
        event = dict(id='one', type='assistant_message', content='Progress', timestamp='1', details={})
        Store(tmp_path).publish_live_event(state, event)
        delta = await anext(stream)
        assert delta.startswith('event: events\n')
        assert json.loads(delta.split('data: ', 1)[1]) == [event]
        await stream.aclose()
        other = await endpoint(sid, Request())
        full = await anext(other.body_iterator)
        assert full.startswith('event: snapshot\n')
        assert json.loads(full.split('data: ', 1)[1])['mr']['events'] == [event]
        await other.body_iterator.aclose()
    asyncio.run(scenario())
    service.views.close()


def test_pending_session_write_is_visible_before_next_checkpoint(tmp_path):
    from langgraph.checkpoint.sqlite import SqliteSaver
    from copy import deepcopy
    service, sid = create_service(tmp_path)
    initial = service.snapshot(sid)
    with SqliteSaver.from_conn_string(str(service.store.checkpoint_path(sid))) as saver:
        saved = saver.get_tuple({'configurable': {'thread_id': sid}})
        state = deepcopy(saved.checkpoint['channel_values']['session'])
        state['status'] = 'paused'
        state['pending'] = {'question': 'Preserved pending write'}
        saver.put_writes(saved.config, [('session', state)], 'finished-node')
    assert service.snapshot(sid)['mr']['state']['pending'] == state['pending']
    assert initial['mr']['state']['pending'] is None
    service.views.close()


def test_evicted_stream_view_cannot_reuse_old_generation(tmp_path):
    service, sid = create_service(tmp_path)
    old_generation = service.snapshot_payload(sid)[0]
    service.views.close()
    state = service.store.load(sid)
    state['status'] = 'paused'
    service.store.save(state)
    generation, snapshot, _ = service.snapshot_payload(sid)
    assert generation != old_generation
    assert snapshot['state']['status'] == 'paused'
    service.views.close()
