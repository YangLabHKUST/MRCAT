"""Checkpoint-owned sessions, live event delivery, and explicit exports."""
from contextlib import contextmanager, closing
from contextvars import ContextVar
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
import json, os, re, sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from .checkpoints import checkpoint_path

_active_state = ContextVar("mrcat_session_state", default=None)

def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)

class Store:
    def __init__(self, base):
        self.base = Path(base).resolve()
        self.base.mkdir(parents=True, exist_ok=True)
    def directory(self, sid):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
            raise ValueError("Invalid session identifier")
        return self.base / sid
    def checkpoint_path(self, sid, *, create=False, writable=False):
        return checkpoint_path(self.directory(sid), create=create, writable=writable)

    def create(self, question, provider):
        if not question.strip():
            raise ValueError("A request is required")
        sid = "session_" + uuid4().hex[:16]
        directory = self.directory(sid)
        (directory / "workspace").mkdir(parents=True)
        state = dict(version=2, persistence='langgraph', session_id=sid, question=question, request=question, memory_request=question, provider=provider,
                     status="created", active_agent="manager", created_at=now(), updated_at=now(),
                     plan="", messages=[], loaded_skills=[], events=[], study_setup={}, job=None,
                     active_task=None, task_history=[], next_task_no=1, pending=None, role_memory={})
        self.save(state)
        from .trace import initialize
        initialize(directory, state)
        return state
    def load(self, sid):
        active = _active_state.get()
        if active is not None and active[0] is self and active[1]['session_id'] == sid:
            return active[1]
        path = self.checkpoint_path(sid)
        if path.exists():
            with SqliteSaver.from_conn_string(str(path)) as saver:
                # A running subgraph can be ahead of its parent. Read the newest
                # committed session across namespaces, including pending writes
                # from a completed node whose superstep has not been committed.
                # Sort the small primary-key index, not all historical blobs.
                # Keep subgraph and pending-write recovery semantics unchanged.
                saver.setup()
                rows = saver.conn.execute(
                    'SELECT checkpoint_ns, checkpoint_id FROM checkpoints '
                    'WHERE thread_id=? ORDER BY checkpoint_id DESC', (sid,))
                for namespace, checkpoint_id in rows:
                    saved = saver.get_tuple({'configurable': {
                        'thread_id': sid, 'checkpoint_ns': namespace,
                        'checkpoint_id': checkpoint_id}})
                    writes = [value for _, channel, value in saved.pending_writes or []
                              if channel == 'session']
                    state = writes[-1] if writes else saved.checkpoint['channel_values'].get('session')
                    if state is not None:
                        return state
        raise FileNotFoundError(f"Session checkpoint is missing or contains no session state: {path}")

    def has_checkpoint(self, sid):
        path = self.checkpoint_path(sid)
        if not path.exists():
            return False
        with SqliteSaver.from_conn_string(str(path)) as saver:
            saved = saver.get_tuple({'configurable': {'thread_id': sid}})
            return bool(saved and 'session' in saved.checkpoint['channel_values'])

    @contextmanager
    def node_state(self, state):
        """Nodes mutate a private copy and return it to LangGraph atomically."""
        token = _active_state.set((self, state))
        try:
            yield
        finally:
            state['updated_at'] = now()
            _active_state.reset(token)

    def save(self, state):
        if state.get('persistence') != 'langgraph':
            raise ValueError('Only current LangGraph sessions can be saved.')
        state["updated_at"] = now()
        active = _active_state.get()
        if active is None or active[0] is not self or active[1] is not state:
            # Creation and idle worker/UI updates use the same graph schema.
            # They start a fresh control path; pending business input is retained.
            from .agent import Agent
            from .graph import build_graph
            directory = self.directory(state['session_id'])
            directory.mkdir(parents=True, exist_ok=True)
            with SqliteSaver.from_conn_string(str(self.checkpoint_path(state['session_id'], create=True))) as saver:
                graph = build_graph(Agent(Path(__file__).resolve().parents[1], self), saver)
                graph.update_state({'configurable': {'thread_id': state['session_id']}},
                                   {'sid': state['session_id'], 'session': state}, as_node='persist')
            self.clear_live_events(state['session_id'])

    def export(self, state):
        """Export readable history on demand; never export a second state store."""
        directory = self.directory(state["session_id"])
        write_json(directory / "conversation.json", state['messages'])
        if state.get("version") == 2:
            from .memory import render_memory
            temporary = directory / ("memory." + uuid4().hex + ".tmp")
            temporary.write_text(render_memory(state), encoding="utf-8")
            os.replace(temporary, directory / "memory.md")
            for task in [*state.get('task_history', []), *([state['active_task']] if state.get('active_task') else [])]:
                for item_id, journal in task.get('coding', {}).items():
                    target = (directory / 'workspace' / 'outputs' / task['task_id'] /
                              item_id / 'executor_memory.md').resolve()
                    if not target.is_relative_to((directory / 'workspace').resolve()):
                        raise ValueError('Executor memory export must stay in the session workspace.')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name('executor_memory.' + uuid4().hex + '.tmp')
                    temporary.write_text(journal.get('summary') or 'No executor compaction yet; see the saved tool history.\n',
                                         encoding='utf-8')
                    os.replace(temporary, target)

    def preview(self, state):
        """Overlay in-flight events only; workflow state always comes from checkpoints."""
        job = state.get('job') or {}
        if job.get('status') != 'running' or not job.get('job_id'):
            return state
        path = self.checkpoint_path(state['session_id'])
        if not path.exists():
            return state
        with closing(sqlite3.connect(path)) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='live_events'").fetchone():
                return state
            rows = conn.execute("SELECT payload FROM live_events WHERE job_id=? ORDER BY rowid",
                                (job['job_id'],)).fetchall()
        events = {event['id']: event for event in state['events']}
        for (payload,) in rows:
            event = json.loads(payload)
            if event['id'] not in events or event['timestamp'] > events[event['id']]['timestamp']:
                events[event['id']] = event
        return dict(state, events=list(events.values()))

    def publish_live_event(self, state, event):
        """A transient UI queue in the same database, not a recoverable session copy."""
        job_id = (state.get('job') or {}).get('job_id')
        if not job_id:
            return
        with closing(sqlite3.connect(self.checkpoint_path(state['session_id'], writable=True))) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS live_events "
                         "(id TEXT PRIMARY KEY, job_id TEXT NOT NULL, payload TEXT NOT NULL)")
            conn.execute("INSERT OR REPLACE INTO live_events VALUES (?, ?, ?)",
                         (event['id'], job_id, json.dumps(event, ensure_ascii=False)))

    def clear_live_events(self, sid):
        with closing(sqlite3.connect(self.checkpoint_path(sid, writable=True))) as conn, conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='live_events'").fetchone():
                conn.execute("DELETE FROM live_events")
    def event(self, state, kind, content="", **details):
        event = dict(id=uuid4().hex, type=kind, content=content, timestamp=now(), details=details)
        state["events"].append(event)
        self.publish_live_event(state, event)
        self.save(state)
        if kind != 'code_execution':
            from .trace import emit
            emit(self.directory(state['session_id']), kind, event, event_id='event:' + event['id'])
        return event
    def list(self):
        rows = []
        for path in self.base.iterdir():
            if not path.is_dir() or path.name.startswith('.'):
                continue
            try: rows.append(self.load(path.name))
            except (OSError, ValueError): continue
        return sorted(rows, key=lambda row: row["updated_at"], reverse=True)
