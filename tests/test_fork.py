import hashlib
import fcntl
import sqlite3

import pytest
from fastapi.testclient import TestClient

from mrcat.agent import Agent
from mrcat.fork import fork_session
from mrcat.results import read_reference
from mrcat.store import Store
from mrcat.web.server import create_app
from test_agent import ROOT, Model, action, decision, verified_value


def digests(directory):
    # Readers may create SQLite sidecars without changing authoritative content.
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()
            and not (p.parent == directory and p.name in {
                'graph.sqlite-wal', 'graph.sqlite-shm', 'graph.sqlite-journal'})}


def test_copy_reuses_results_and_writes_only_to_copy(tmp_path):
    original = Store(tmp_path / 'benchmark')
    state = original.create('Compute', 'openai')
    sid = state['session_id']
    source = original.directory(sid)
    code = """from pathlib import Path
from mrcat.results import publish_result
path = Path('value.txt').resolve()
path.write_text('original')
publish_result('saved', {'path': str(path)})
"""
    Agent(ROOT, original, model=Model([action('execute', code), 'Saved.'])).run(sid, 'Compute')
    (source / 'workspace/blob.gz').write_bytes(b'\x00\xffbinary')
    alias_store = tmp_path / 'view'
    alias_store.mkdir()
    alias = alias_store / sid
    alias.symlink_to(source, target_is_directory=True)
    before = digests(source)
    copied = fork_session(alias, alias_store)
    destination = alias_store / copied
    assert not destination.is_symlink()
    assert (destination / 'graph.sqlite').exists()
    assert (destination / 'graph.sqlite').read_bytes() != (source / 'graph.sqlite').read_bytes()
    assert (destination / 'workspace/blob.gz').read_bytes() == b'\x00\xffbinary'
    assert (destination / 'workspace/blob.gz').stat().st_ino != (source / 'workspace/blob.gz').stat().st_ino
    state = Store(alias_store).load(copied)
    assert state['messages']
    assert state['events'][-1]['details']['source_session_id'] == sid
    scope = state['role_memory']['search']['result_scope']
    value = read_reference(destination, scope, '$ref:saved/path')
    assert value == str(destination / 'workspace/value.txt')
    model = Model([action('execute', f"from pathlib import Path; Path({value!r}).write_text('continued')"), 'Updated.'])
    Agent(ROOT, Store(alias_store), model=model).run(copied, 'Continue with the saved result')
    assert (destination / 'workspace/value.txt').read_text() == 'continued'
    assert digests(source) == before


def test_waiting_plan_can_be_confirmed_in_copy(tmp_path):
    original = Store(tmp_path / 'original')
    sid = original.create('Analyze', 'openai')['session_id']
    state = Agent(ROOT, original, model=Model(decisions=[decision('mr', 'propose')])).run(sid, 'Plan')
    before = digests(original.directory(sid))
    copied = fork_session(original.directory(sid), tmp_path / 'copies')
    store = Store(tmp_path / 'copies')
    assert store.load(copied)['pending'] == state['pending']
    model = Model([verified_value(), 'Completed.'], [decision('mr', 'confirm')])
    done = Agent(ROOT, store, model=model).run(copied, 'Confirm')
    assert done['task_history'][0]['task_id'] == 'task1'
    assert not any(c['role'] == 'planner' for c in model.calls)
    assert digests(original.directory(sid)) == before


def test_web_linked_sources_are_read_only_and_can_be_copied(tmp_path):
    original = Store(tmp_path / 'original')
    state = original.create('Original', 'openai')
    source = original.directory(state['session_id'])
    state['job'] = dict(status='running', pid=99999999)
    original.save(state)
    view = tmp_path / 'view'
    view.mkdir()
    (view / state['session_id']).symlink_to(source, target_is_directory=True)
    client = TestClient(create_app(repo_root=ROOT, artifact_dir=view))
    url = '/api/sessions/' + state['session_id']
    before = digests(source)
    assert client.get(url).status_code == 200
    assert client.get('/api/sessions').status_code == 200
    assert client.post(url + '/mr/reply', json={'reply': 'Continue'}).status_code == 403
    assert client.post(url + '/stop').status_code == 403
    assert client.post(url + '/study-setup', data={'analysis_request': 'Change'}).status_code == 403
    assert client.post(url + '/fork').status_code == 400
    assert digests(source) == before
    state['job'] = None
    original.save(state)
    before = digests(source)
    response = client.post(url + '/fork')
    assert response.status_code == 200
    copied = response.json()['session']['session_id']
    assert copied != state['session_id']
    assert client.get('/api/sessions/' + copied).status_code == 200
    assert digests(source) == before


def test_refuse_running_nested_and_linked_artifacts(tmp_path):
    original = Store(tmp_path / 'original')
    state = original.create('Original', 'openai')
    source = original.directory(state['session_id'])
    state['status'] = 'running'
    original.save(state)
    with pytest.raises(ValueError, match='running'):
        fork_session(source, tmp_path / 'copies')
    state['status'] = 'completed'
    original.save(state)
    with pytest.raises(ValueError, match='outside'):
        fork_session(source, source / 'copies')
    (source / 'workspace/link').symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(ValueError, match='linked'):
        fork_session(source, tmp_path / 'copies')
    assert not (tmp_path / 'copies').exists()


def test_failed_copy_is_not_published(tmp_path, monkeypatch):
    from mrcat import fork
    original = Store(tmp_path / 'original')
    source = original.directory(original.create('Original', 'openai')['session_id'])
    (source / 'workspace/data.txt').write_text('original')
    copy_file = fork.copy_file
    def mutate(src, dst, remap):
        copy_file(src, dst, remap)
        (source / 'workspace/data.txt').write_text('changed')
    monkeypatch.setattr(fork, 'copy_file', mutate)
    with pytest.raises(ValueError, match='changed'):
        fork_session(source, tmp_path / 'copies')
    assert list((tmp_path / 'copies').iterdir()) == []


def test_copy_respects_existing_web_lock_without_modifying_source(tmp_path):
    original = Store(tmp_path / 'original')
    source = original.directory(original.create('Original', 'openai')['session_id'])
    lock = source / 'job.lock'
    lock.touch()
    before = digests(source)
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='busy'):
            fork_session(source, tmp_path / 'copies')
    copied = fork_session(source, tmp_path / 'copies')
    assert not (tmp_path / 'copies' / copied / 'job.lock').exists()
    assert digests(source) == before


def test_copy_allows_checkpoint_reader_during_copy(tmp_path, monkeypatch):
    from mrcat import fork
    original = Store(tmp_path / 'original')
    state = original.create('Original', 'openai')
    source = original.directory(state['session_id'])
    (source / 'workspace/data.txt').write_text('original')
    copy_file = fork.copy_file
    readers = []

    def read_during_copy(src, dst, remap):
        copy_file(src, dst, remap)
        checkpoint = original.checkpoint_path(state['session_id'])
        reader = sqlite3.connect(checkpoint)
        reader.execute('SELECT checkpoint_id FROM checkpoints LIMIT 1').fetchone()
        readers.append(reader)
        assert checkpoint.with_name('graph.sqlite-shm').exists()

    monkeypatch.setattr(fork, 'copy_file', read_during_copy)
    before = digests(source)
    try:
        copied = fork_session(source, tmp_path / 'copies')
        assert Store(tmp_path / 'copies').load(copied)['question'] == 'Original'
    finally:
        for reader in readers:
            reader.close()
    assert digests(source) == before


def test_copy_rejects_checkpoint_state_change_during_copy(tmp_path, monkeypatch):
    from mrcat import fork
    original = Store(tmp_path / 'original')
    state = original.create('Original', 'openai')
    source = original.directory(state['session_id'])
    (source / 'workspace/data.txt').write_text('original')
    copy_file = fork.copy_file

    def change_state_during_copy(src, dst, remap):
        copy_file(src, dst, remap)
        state['question'] = 'Changed while copying'
        original.save(state)

    monkeypatch.setattr(fork, 'copy_file', change_state_during_copy)
    with pytest.raises(ValueError, match='source changed'):
        fork_session(source, tmp_path / 'copies')
    assert list((tmp_path / 'copies').iterdir()) == []
