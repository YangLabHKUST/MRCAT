"""Verify checkpoint persistence across real benchmark sandbox lifetimes."""
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from mrcat import checkpoints, sandbox
from mrcat.store import Store

ROOT = Path(__file__).resolve().parents[1]


def run(command, env, code):
    result = subprocess.run(command + [sys.executable, '-c', code], env=env,
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.sandbox
def test_checkpoint_survives_worker_exit_and_restart_without_sibling_access(tmp_path, monkeypatch):
    monkeypatch.setenv('MRCAT_CHECKPOINT_DIR', str(tmp_path / 'local-checkpoints'))
    workers = []
    for query in ('Q01', 'Q02'):
        directory = tmp_path / 'batch' / query
        directory.mkdir(parents=True)
        command, env, manifest = sandbox.prepare_worker(ROOT, directory, [])
        sandbox.preflight(command, env)
        assert not list(directory.iterdir())
        assert not list(Path(manifest['checkpoint_dir']).iterdir())
        workers.append((directory, command, env, manifest))
    for index, (directory, command, env, manifest) in enumerate(workers):
        other = workers[1 - index][3]['checkpoint_dir']
        run(command, env, f'''
import os, sqlite3
from pathlib import Path
from mrcat.store import Store
assert not Path({other!r}).exists()
store = Store(Path.cwd())
state = store.create({directory.name!r}, 'openai')
state['status'] = 'waiting_user'
state['pending'] = {{'kind': 'clarification', 'question': 'Which sample size?'}}
store.save(state)
sid = state['session_id']
(Path.cwd() / 'sid.txt').write_text(sid)
db = store.checkpoint_path(sid)
assert db.is_relative_to(Path(os.environ['MRCAT_CHECKPOINT_DIR']))
# Preserve a committed WAL transaction even when the worker exits without closing it.
conn = sqlite3.connect(db)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA wal_autocheckpoint=0')
conn.execute('CREATE TABLE persistence_probe (value TEXT)')
conn.execute("INSERT INTO persistence_probe VALUES ('committed')")
conn.commit()
assert Path(str(db) + '-wal').stat().st_size > 0
os._exit(0)
''')
    for directory, command, env, manifest in workers:
        sid = (directory / 'sid.txt').read_text()
        store = Store(directory)
        entry = directory / sid / 'graph.sqlite'
        assert entry.is_symlink() and entry.is_file()
        assert entry.resolve().is_relative_to(Path(manifest['checkpoint_dir']))
        state = store.load(sid)
        assert state['question'] == directory.name
        assert state['pending']['question'] == 'Which sample size?'
        with sqlite3.connect(entry.resolve()) as conn:
            assert conn.execute('SELECT value FROM persistence_probe').fetchone() == ('committed',)
            assert conn.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        run(command, env, f'''
from pathlib import Path
from mrcat.store import Store
store = Store(Path.cwd())
state = store.load({sid!r})
assert state['status'] == 'waiting_user'
assert state['pending']['question'] == 'Which sample size?'
state['memory_request'] = 'State saved after restart'
store.save(state)
''')
        assert store.load(sid)['memory_request'] == 'State saved after restart'


@pytest.mark.sandbox
def test_preflight_rejects_read_only_checkpoint_mount(tmp_path, monkeypatch):
    monkeypatch.setenv('MRCAT_CHECKPOINT_DIR', str(tmp_path / 'local-checkpoints'))
    directory = tmp_path / 'Q01'
    directory.mkdir()
    command, env, manifest = sandbox.prepare_worker(ROOT, directory, [])
    target = command.index(manifest['checkpoint_dir'])
    assert command[target - 1] == '--bind'
    command[target - 1] = '--ro-bind'
    with pytest.raises(ValueError, match='Read-only file system'):
        sandbox.preflight(command, env)
    assert not list(directory.iterdir())


@pytest.mark.sandbox
def test_worker_rejects_network_checkpoint_root(tmp_path, monkeypatch):
    local = tmp_path / 'network-checkpoints'
    monkeypatch.setenv('MRCAT_CHECKPOINT_DIR', str(local))
    monkeypatch.setattr(checkpoints, 'network_path', lambda path: Path(path) == local)
    with pytest.raises(ValueError, match='local filesystem'):
        sandbox.prepare_worker(ROOT, tmp_path, [])
    assert not local.exists()
