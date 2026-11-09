"""Exercise storage placement, offline WAL recovery and Web responsiveness."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import httpx
import pytest

from mrcat import checkpoints
from mrcat.agent import Agent
from mrcat.fork import fork_session
from mrcat.store import Store
from mrcat.web.server import create_app
from test_agent import ROOT, Model


@pytest.fixture
def storage(tmp_path, monkeypatch):
    network = tmp_path / 'network'
    network.mkdir()
    local = tmp_path / 'local'
    monkeypatch.setenv('MRCAT_CHECKPOINT_DIR', str(local))
    monkeypatch.setattr(checkpoints, 'network_path',
                        lambda p: Path(p).resolve().is_relative_to(network))
    return network, local


def test_local_checkpoint_survives_restart_and_fork(storage):
    network, local = storage
    store = Store(network)
    sid = store.create('Remember this', 'openai')['session_id']
    entry = store.directory(sid) / 'graph.sqlite'
    assert entry.is_symlink() and entry.resolve().is_relative_to(local)
    Agent(ROOT, store, model=Model(['Saved answer.'])).run(sid, 'Remember this')
    original = Store(network).load(sid)
    assert json.loads(original['messages'][-1]['content'])['body'] == 'Saved answer.'
    copied = fork_session(store.directory(sid), network / 'copies')
    other = Store(network / 'copies')
    assert other.load(copied)['messages'] == original['messages']
    assert other.checkpoint_path(copied) != store.checkpoint_path(sid)
    assert not list(network.rglob('graph.sqlite-wal'))
    assert not list(network.rglob('graph.sqlite-shm'))
    entry.resolve().unlink()
    with pytest.raises(FileNotFoundError, match='target is missing'):
        store.load(sid)
    with pytest.raises(FileNotFoundError, match='target is missing'):
        store.save(original)


def old_checkpoint(network, monkeypatch):
    # Build a pre-migration DB with a real uncheckpointed committed WAL page.
    with monkeypatch.context() as patch:
        patch.delenv('MRCAT_CHECKPOINT_DIR')
        patch.setattr(checkpoints, 'network_path', lambda p: False)
        store = Store(network)
        sid = store.create('Keep committed state', 'openai')['session_id']
    entry = store.directory(sid) / 'graph.sqlite'
    subprocess.run([sys.executable, '-c', '''
import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA wal_autocheckpoint=0')
conn.execute('CREATE TABLE wal_evidence (value TEXT)')
conn.execute("INSERT INTO wal_evidence VALUES ('committed before shutdown')")
conn.commit()
os._exit(0)
''', str(entry)], check=True)
    assert Path(str(entry) + '-wal').stat().st_size > 0
    return store, sid, entry


def hashes(entry):
    return {suffix: hashlib.sha256(Path(str(entry) + suffix).read_bytes()).hexdigest()
            for suffix in checkpoints.SIDECARS if Path(str(entry) + suffix).exists()}


def test_migration_preserves_wal_and_source_backup(storage, monkeypatch):
    network, local = storage
    store, sid, entry = old_checkpoint(network, monkeypatch)
    before = hashes(entry)
    with pytest.raises(ValueError, match='network filesystem'):
        store.load(sid)
    result = checkpoints.migrate(entry.parent)
    assert hashes(Path(result['backup']) / 'graph.sqlite') == before
    assert entry.is_symlink()
    with sqlite3.connect(store.checkpoint_path(sid)) as conn:
        assert conn.execute('SELECT value FROM wal_evidence').fetchone()[0] == 'committed before shutdown'
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert store.load(sid)['question'] == 'Keep committed state'
    assert not Path(str(entry) + '-wal').exists()
    assert checkpoints.migrate(entry.parent)['migrated'] is False
    copied = fork_session(entry.parent, network / 'copies')
    assert not list((network / 'copies' / copied).glob('.checkpoint-backup-*'))


def test_frozen_snapshot_never_modifies_original(storage, monkeypatch):
    network, local = storage
    store, sid, entry = old_checkpoint(network / 'frozen', monkeypatch)
    before = hashes(entry)
    view = network / 'view'
    view.mkdir()
    alias = view / sid
    alias.symlink_to(entry.parent, target_is_directory=True)
    with pytest.raises(ValueError, match='Linked sessions'):
        checkpoints.migrate(alias)
    checkpoints.migrate(alias, readonly=True)
    assert not entry.is_symlink() and hashes(entry) == before
    reader = Store(view)
    state = reader.load(sid)
    assert state['question'] == 'Keep committed state'
    with pytest.raises(PermissionError, match='read-only'):
        reader.save(state)
    with pytest.raises(PermissionError, match='read-only'):
        reader.clear_live_events(sid)
    with pytest.raises(PermissionError, match='read-only'):
        Agent(ROOT, reader, model=Model(['No write'])).run(sid, 'Change')
    copied = fork_session(alias, view)
    assert reader.load(copied)['question'] == state['question']
    assert hashes(entry) == before
    entry.touch()
    with pytest.raises(ValueError, match='Frozen checkpoint changed'):
        reader.load(sid)


def test_migration_refuses_live_connections(tmp_path):
    store = Store(tmp_path / 'source')
    sid = store.create('Test', 'openai')['session_id']
    entry = store.directory(sid) / 'graph.sqlite'
    conn = sqlite3.connect(entry)
    try:
        with pytest.raises(ValueError, match='active PIDs'):
            checkpoints.migrate(entry.parent, root=tmp_path / 'local')
    finally:
        conn.close()


def test_network_destination_is_rejected(storage):
    network, _ = storage
    with pytest.raises(ValueError, match='local filesystem'):
        checkpoints.local_target(network / 'session', root=network / 'databases')


def test_concurrent_local_readers_and_writer(storage):
    network, _ = storage
    store = Store(network)
    state = store.create('Concurrent', 'openai')
    sid = state['session_id']
    state['job'] = dict(job_id='worker', status='running')
    store.save(state)
    def write():
        for i in range(12):
            store.publish_live_event(state, dict(id=str(i), timestamp=str(i), content=str(i)))
    def read():
        for _ in range(12):
            loaded = Store(network).load(sid)
            assert loaded['question'] == 'Concurrent'
            store.preview(loaded)
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(write)] + [pool.submit(read) for _ in range(4)]
        for future in futures:
            future.result(timeout=15)
    assert len(store.preview(store.load(sid))['events']) == 12


@pytest.mark.parametrize('endpoint', ['events', 'manual'])
def test_blocked_database_does_not_block_homepage(tmp_path, monkeypatch, endpoint):
    app = create_app(repo_root=ROOT, artifact_dir=tmp_path)
    sid = app.state.service.store.create('Blocked read', 'openai')['session_id'] if endpoint == 'events' else None
    entered, release = threading.Event(), threading.Event()
    def blocked(*args):
        entered.set()
        release.wait(3)
        raise FileNotFoundError('Deliberately blocked fixture')
    monkeypatch.setattr(app.state.service.store, 'load' if endpoint == 'events' else 'create', blocked)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            start = time.monotonic()
            request = (client.get(f'/api/sessions/{sid}/events') if endpoint == 'events'
                       else client.post('/api/manual-sessions', data={'analysis_request': 'test'}))
            pending = asyncio.create_task(request)
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                response = await asyncio.wait_for(client.get('/'), timeout=1)
                assert response.status_code == 200
                assert time.monotonic() - start < 1.5
                assert not pending.done()
            finally:
                release.set()
                await pending
    asyncio.run(exercise())


def test_session_list_reads_metadata_without_scanning_artifacts(tmp_path, monkeypatch):
    app = create_app(repo_root=ROOT, artifact_dir=tmp_path)
    service = app.state.service
    state = service.store.create('List metadata', 'openai')
    sid = state['session_id']
    expected = service.snapshot(sid)['state']
    def no_snapshot(*args):
        raise AssertionError('Session listing must not build full snapshots')
    monkeypatch.setattr(service, 'snapshot', no_snapshot)
    monkeypatch.setattr(service, 'files', no_snapshot)
    assert service.sessions() == [expected]
