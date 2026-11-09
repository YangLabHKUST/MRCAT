"""Rebuildable browser views; checkpoints remain the only workflow state.

A read-only SQLite connection observes data_version across WAL commits. Readers
share one view per session. Idle streams neither deserialize state nor walk files.
"""
import json
import os
import sqlite3
import threading
from collections import OrderedDict
from itertools import count

_generations = count(1)


class SessionView:
    def __init__(self, service, sid):
        self.service, self.sid = service, sid
        self.lock = threading.RLock()
        self.conn = None
        self.path = None
        self.identity = None
        self.version = None
        self.checkpoint_key = None
        self.state = None
        self.data = None
        self.payload = None
        self.files = None
        self.report = None
        self.artifacts_dirty = True
        self.generation = 0

    def close(self):
        with self.lock:
            if self.conn is not None:
                self.conn.close()
                self.conn = None
            self.identity = self.version = None

    def refresh(self):
        store = self.service.store
        # Migration requires an offline server. Resolve the session's NFS link
        # once, then keep idle browser checks on the local database filesystem.
        if self.path is None:
            self.path = store.checkpoint_path(self.sid)
        path = self.path
        if path.exists():
            stat = path.stat()
            identity = (str(path), stat.st_dev, stat.st_ino)
            if self.conn is None or identity != self.identity:
                self.close()
                self.conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True,
                                            check_same_thread=False, isolation_level=None,
                                            timeout=1)
                self.identity = identity
                self.state = None
            version = self.conn.execute('PRAGMA data_version').fetchone()[0]
            changed = self.version != version or self.state is None
            if changed:
                # Pending writes may advance a subgraph before its checkpoint.
                latest = self.conn.execute(
                    'SELECT checkpoint_ns, checkpoint_id FROM checkpoints '
                    'WHERE thread_id=? ORDER BY checkpoint_id DESC LIMIT 1',
                    (self.sid,)).fetchone()
                writes = self.conn.execute('SELECT MAX(rowid) FROM writes').fetchone()[0]
                key = (identity, latest, writes)
        else:
            # Frozen legacy sessions are still inspectable; never persist here.
            path = store.directory(self.sid) / 'session.json'
            stat = path.stat()
            version = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
            changed = self.version != version or self.state is None
            key = ('legacy', version)
        if changed:
            if self.state is None or key != self.checkpoint_key:
                self.state = self.service.reconcile(store.load(self.sid))
                self.checkpoint_key = key
                self.artifacts_dirty = True
                self.generation = next(_generations)
            self.version = version
            self.data = self.payload = None
        # A dead worker need not have made a final database write.
        if (self.state.get('job') or {}).get('status') == 'running':
            try: os.kill(self.state['job']['pid'], 0)
            except ProcessLookupError: self.service.reconcile(self.state)
            if self.state['job']['status'] != 'running':
                self.version = None
                self.data = self.payload = None
                self.artifacts_dirty = True
                self.generation = next(_generations)
        return self.state

    def snapshot(self):
        with self.lock:
            state = self.refresh()
            if self.data is None:
                if self.artifacts_dirty:
                    self.files = self.service.files(self.sid)
                    self.report = self.service.final_report(self.sid, state)
                    self.artifacts_dirty = False
                self.data = self.service.project(
                    self.service.store.preview(state), self.files, self.report)
                self.payload = json.dumps(self.data, ensure_ascii=False, default=str)
            return self.generation, self.data, self.payload

    def summary(self):
        with self.lock:
            return self.service.session_state(self.refresh())


class ViewCache:
    def __init__(self, service):
        self.service = service
        self.lock = threading.Lock()
        self.entries = OrderedDict()

    def get(self, sid):
        self.service.store.directory(sid)  # Validate before allocating a reader.
        with self.lock:
            if sid not in self.entries:
                self.entries[sid] = SessionView(self.service, sid)
            self.entries.move_to_end(sid)
            # Bound database handles and historical state retained by the UI.
            if len(self.entries) > 32:
                _, oldest = self.entries.popitem(last=False)
                oldest.close()
            return self.entries[sid]

    def close(self):
        with self.lock:
            for entry in self.entries.values():
                entry.close()
            self.entries.clear()
