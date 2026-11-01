"""Append-only application traces and read-only reconstruction of saved sessions.

Checkpoints remain authoritative. This module never invokes a model or tool.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import argparse
import fcntl
import json
import logging
import os
import re
import sqlite3
import tempfile

SCHEMA_VERSION = 1
_INDEX = {}
_TURN = ContextVar('mrcat_trace_turn', default=None)
_LOG = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=str, separators=(',', ':'))


def _redact(value):
    """Keep evidence text, removing credentials rather than arbitrary URL queries."""
    secrets = [v for k, v in os.environ.items() if len(v) >= 6 and
               any(word in k.upper() for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))]
    def clean(item):
        if isinstance(item, dict):
            return {key: ('[REDACTED]' if isinstance(val, str) and re.fullmatch(
                r'(?i)(api[_-]?key|access[_-]?token|authorization|password|secret|opengwas_jwt)', str(key))
                else clean(val)) for key, val in item.items()}
        if isinstance(item, (tuple, list)):
            return [clean(val) for val in item]
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, '[REDACTED]')
            item = re.sub(r'(?i)(bearer\s+)[^\s\"\x27,}]+', r'\1[REDACTED]', item)
            item = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED]', item)
            item = re.sub(r'\bsk-[A-Za-z0-9_-]{20,}', '[REDACTED]', item)
        return item
    return clean(value)


def _record(directory, kind, data, *, event_id, timestamp=None, capture_mode='live',
            source=None, parent_id=None):
    return dict(schema_version=SCHEMA_VERSION, session_id=Path(directory).name,
                event_id=event_id, type=kind, timestamp=timestamp,
                capture_mode=capture_mode, parent_id=parent_id,
                source=source, data=_redact(data))


def _header(directory, state, mode):
    return _record(directory, 'trace_metadata', dict(
        question=state.get('question'), provider=state.get('provider'),
        created_at=state.get('created_at'), generated_at=now(),
        capture_boundary='application calls, saved messages, workflow events, tools and artifacts',
        limitations=['SDK-internal attempts are not captured separately',
                     'Skill-internal calls appear only through their saved artifacts and aggregate usage',
                     'Unrecorded historical responses cannot be recovered',
                     'Reconstructed sequence is a presentation order; unknown event times remain null'],
        credentials='Credential values are redacted; source hashes describe original files'),
        event_id='trace:metadata', timestamp=state.get('created_at'), capture_mode=mode)


@contextmanager
def _lock(directory):
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError('Linked sessions are read-only; export from their original directory.')
    with (directory / '.trace.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _index(path, handle):
    """Index once per process; refresh if another process appended records."""
    size = os.fstat(handle.fileno()).st_size
    signature = (os.fstat(handle.fileno()).st_ino, size)
    cached = _INDEX.get(str(path))
    if cached and cached[0] == signature:
        return cached[1], cached[2], 0
    handle.seek(0)
    ids, sequence, valid = set(), 0, 0
    while line := handle.readline():
        if not line.endswith(b'\n'):
            # A killed writer may leave only its last record incomplete.
            handle.truncate(valid)
            return ids, sequence, size - valid
        row = json.loads(line)
        if row['seq'] != sequence + 1 or row['event_id'] in ids:
            raise ValueError(f'Invalid trace sequence or duplicate event ID: {path}')
        sequence = row['seq']
        ids.add(row['event_id'])
        valid = handle.tell()
    return ids, sequence, 0


def _append(directory, row):
    directory = Path(directory)
    path = directory / 'trace.jsonl'
    # Session creation/run establishes the header. Standalone tool use is unchanged.
    if not path.exists():
        return
    with _lock(directory), path.open('r+b') as handle:
        ids, sequence, discarded = _index(path, handle)
        rows = []
        if discarded:
            rows.append(_record(directory, 'trace_repaired', dict(discarded_tail_bytes=discarded),
                                event_id='trace:repair:' + uuid4().hex, timestamp=now()))
        if row['event_id'] not in ids:
            rows.append(row)
        if not rows:
            return
        handle.seek(0, os.SEEK_END)
        for item in rows:
            sequence += 1
            item = dict(item, seq=sequence)
            handle.write((_json(item) + '\n').encode('utf-8'))
            ids.add(item['event_id'])
        handle.flush()
        os.fsync(handle.fileno())
        info = os.fstat(handle.fileno())
        _INDEX[str(path)] = ((info.st_ino, info.st_size), ids, sequence)


def emit(directory, kind, data, *, event_id=None, parent_id=None, source=None):
    """Observability must not change the outcome of a model/tool operation."""
    try:
        _append(directory, _record(directory, kind, data,
            event_id=event_id or uuid4().hex, timestamp=now(),
            parent_id=parent_id or _TURN.get(), source=source))
    except Exception as exc:
        _LOG.warning('Trace write failed for %s (%s); workflow continues', directory, type(exc).__name__)


def _file(directory, path):
    path = Path(path)
    if not path.resolve().is_relative_to(Path(directory).resolve()):
        raise ValueError(f'Trace source must stay inside the session: {path}')
    raw = path.read_bytes()
    source = dict(path=str(path.relative_to(directory)), sha256=sha256(raw).hexdigest(),
                  mtime_utc=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())
    return raw.decode('utf-8', errors='replace'), source


def _optional(directory, path, *, json_data=False):
    if not Path(path).is_file():
        return None, None
    text, source = _file(directory, path)
    return (json.loads(text) if json_data else text), source


def llm_started(directory, call_dir):
    try:
        prompt, source = _optional(directory, Path(call_dir) / 'prompt.json', json_data=True)
        emit(directory, 'llm_start', prompt, event_id='llm:' + Path(call_dir).name, source=source)
    except Exception as exc:
        _LOG.warning('Trace LLM capture failed (%s)', type(exc).__name__)


def message_record(directory, state):
    try:
        message = state['messages'][-1]
        identity = 'message:' + str(len(state['messages']) - 1) + ':' + sha256(_json(message).encode()).hexdigest()[:16]
        emit(directory, 'message', message, event_id=identity)
    except Exception as exc:
        _LOG.warning('Trace message capture failed (%s)', type(exc).__name__)


def capture_result(directory, path):
    try:
        binding, source = _optional(directory, path, json_data=True)
        response, response_source = None, None
        response_path = (binding.get('producer') or {}).get('response_path')
        if response_path and Path(response_path).resolve().is_relative_to(Path(directory).resolve()):
            response, response_source = _optional(directory, Path(response_path), json_data=True)
        emit(directory, 'result_registered', dict(binding=binding, response=response),
             event_id='result:' + source['path'], parent_id='execution:' + str(binding.get('execution_id')),
             source=[source, response_source] if response_source else source)
    except Exception as exc:
        _LOG.warning('Trace result capture failed (%s)', type(exc).__name__)


def llm_finished(directory, call_dir):
    """Save exactly what the application persisted, including failed calls."""
    try:
        data, sources = {}, []
        for key, name, structured in [('response', 'response.txt', False), ('error', 'error.json', True),
                                      ('usage', 'usage.json', True), ('provider_response', 'provider_response.json', True)]:
            data[key], source = _optional(directory, Path(call_dir) / name, json_data=structured)
            if source:
                sources.append(source)
        data['status'] = 'error' if data['error'] else 'returned' if data['response'] is not None else 'incomplete'
        emit(directory, 'llm_end', data, event_id='llm:' + Path(call_dir).name + ':end',
             parent_id='llm:' + Path(call_dir).name, source=sources)
    except Exception as exc:
        _LOG.warning('Trace LLM capture failed (%s)', type(exc).__name__)


def execution_finished(directory, execution_id, result):
    try:
        data = dict(observation=result)
        sources = []
        for key in ('stdout', 'stderr'):
            data[key], source = _optional(directory, Path(directory) / 'executions' / execution_id / (key + '.log'))
            if source:
                sources.append(source)
        _, source = _optional(directory, Path(directory) / 'executions' / execution_id / 'observation.json')
        if source:
            sources.append(source)
        emit(directory, 'execution_end', data, event_id='execution:' + execution_id + ':end',
             parent_id='execution:' + execution_id, source=sources)
        capture_artifacts(directory, result.get('generated_files', []))
    except Exception as exc:
        _LOG.warning('Trace execution capture failed (%s)', type(exc).__name__)


def coding_records(state):
    tasks = [*state.get('task_history', []), *([state['active_task']] if state.get('active_task') else [])]
    for task in tasks:
        for item, journal in task.get('coding', {}).items():
            for index, entry in enumerate(journal.get('entries', [])):
                identity = f"coding:{task['task_id']}:{item}:{index}:" + sha256(_json(entry).encode()).hexdigest()[:16]
                yield identity, dict(task_id=task['task_id'], item_id=item, entry=entry)


def tool_started(directory, state, flow):
    try:
        task = state.get('active_task') or {}
        journal = task.get('coding', {}).get(task.get('current_item_id'), {})
        pending = journal.get('pending_turn') or {}
        calls = pending.get('message', {}).get('tool_calls', [])
        index = pending.get('index', 0)
        call_id = calls[index]['id'] if index < len(calls) else flow.get('coding_action_id')
        emit(directory, 'tool_start', dict(call=flow['coding_call'], call_id=call_id),
             event_id='tool:' + str(call_id))
    except Exception as exc:
        _LOG.warning('Trace tool capture failed (%s)', type(exc).__name__)


def capture_coding(directory, state):
    try:
        for identity, data in coding_records(state):
            if data['entry'].get('result', {}).get('ok') is None:
                continue
            emit(directory, 'tool_result', data, event_id=identity,
                 parent_id='tool:' + data['entry']['call_id'] if data['entry'].get('call_id') else None)
    except Exception as exc:
        _LOG.warning('Trace tool capture failed (%s)', type(exc).__name__)


def report_records(directory):
    directory = Path(directory)
    paths = set((directory / 'workspace' / 'outputs').glob('*/final_summary.md'))
    paths.update((directory / 'workspace' / 'reports').glob('*/final_summary.md'))
    for path in sorted(paths):
        text, source = _file(directory, path)
        yield 'report:' + source['path'] + ':' + source['sha256'], dict(text=text), source


def artifact_records(directory, candidates=None):
    """Include saved Skill prompts/code and interpretation evidence, not GWAS data."""
    directory = Path(directory)
    if candidates is None:
        paths = list((directory / 'workspace' / 'outputs').glob('*/*/generated_code/*'))
        paths += list((directory / 'workspace' / 'outputs').glob('*/*/reports/*'))
    else:
        paths = [directory / ref for ref in candidates]
    for path in sorted(set(paths)):
        if not path.is_file():
            continue
        if not (path.parent.name == 'generated_code' and path.suffix in {'.py', '.txt', '.json'}
                or path.name in {'gwas_qc_report.json', 'gwas_qc_explanation.md'}):
            continue
        text, source = _file(directory, path)
        yield 'artifact:' + source['path'] + ':' + source['sha256'], dict(text=text), source


def capture_artifacts(directory, candidates=None):
    try:
        for identity, data, source in artifact_records(directory, candidates):
            emit(directory, 'saved_artifact', data, event_id=identity, source=source)
    except Exception as exc:
        _LOG.warning('Trace artifact capture failed (%s)', type(exc).__name__)


def _snapshots(directory):
    """Read SQLite without setup/migrations or any checkpoint writes."""
    directory = Path(directory)
    entry = directory / 'graph.sqlite'
    if entry.exists():
        from langgraph.checkpoint.sqlite import SqliteSaver
        path = entry.resolve()
        wal = Path(str(path) + '-wal')
        uri = path.as_uri() + '?mode=ro' + ('' if wal.exists() and wal.stat().st_size else '&immutable=1')
        with sqlite3.connect(uri, uri=True) as conn:
            saver = SqliteSaver(conn)
            saver.is_setup = True
            snapshots = sorted(saver.list(None), key=lambda saved: saved.checkpoint['ts'])
            for saved in snapshots:
                origin = dict(path='graph.sqlite', checkpoint_id=saved.checkpoint['id'],
                              checkpoint_ns=saved.config['configurable'].get('checkpoint_ns', ''),
                              checkpoint_ts=saved.checkpoint['ts'])
                state = saved.checkpoint['channel_values'].get('session')
                if state:
                    yield state, origin
                for _, channel, value in saved.pending_writes or []:
                    if channel == 'session' and value:
                        yield value, dict(origin, pending_write=True)
    elif (directory / 'session.json').exists():
        state, source = _optional(directory, directory / 'session.json', json_data=True)
        yield state, source
    else:
        raise FileNotFoundError(f'No saved session at {directory}')


def _historical(directory, snapshots):
    records, messages, events, coding = [], set(), {}, set()
    def add(kind, data, identity, source, timestamp=None, parent=None):
        origin = source if isinstance(source, list) else [source]
        anchors = [s.get('checkpoint_ts') or s.get('mtime_utc') for s in origin if s]
        order = timestamp or next((a for a in anchors if a), '')
        row = _record(directory, kind, data, event_id=identity, timestamp=timestamp,
                      capture_mode='reconstructed', source=source, parent_id=parent)
        records.append((order, len(records), row))
    for state, source in snapshots:
        for index, message in enumerate(state.get('messages', [])):
            identity = 'message:' + str(index) + ':' + sha256(_json(message).encode()).hexdigest()[:16]
            if identity not in messages:
                messages.add(identity)
                add('message', message, identity, dict(source, field=f'messages[{index}]'))
        for event in state.get('events', []):
            # A receipt supersedes the mutable progress card, but never drop
            # an old execution event whose execution files are missing.
            execution_id = event.get('details', {}).get('execution_id')
            if event['type'] != 'code_execution' or not execution_id or not (directory / 'executions' / execution_id).exists():
                identity = event.get('id') or sha256(_json(event).encode()).hexdigest()
                events[identity] = (event, source)
        for identity, data in coding_records(state):
            if identity not in coding:
                coding.add(identity)
                call_id = data['entry'].get('call_id')
                if call_id:
                    start_id = 'tool:' + call_id
                    if start_id not in coding:
                        coding.add(start_id)
                        add('tool_start', dict(call=data['entry'].get('arguments'), call_id=call_id), start_id, source)
                if data['entry'].get('result', {}).get('ok') is not None:
                    add('tool_result', data, identity, source, parent='tool:' + call_id if call_id else None)
    for identity, (event, source) in events.items():
        add(event['type'], event, 'event:' + identity, source, timestamp=event.get('timestamp'))
    for call_dir in sorted((directory / 'llm').glob('*')):
        prompt, source = _optional(directory, call_dir / 'prompt.json', json_data=True)
        if source:
            add('llm_start', prompt, 'llm:' + call_dir.name, source)
        data, sources = {}, []
        for key, name, structured in [('response', 'response.txt', False), ('error', 'error.json', True),
                                      ('usage', 'usage.json', True), ('provider_response', 'provider_response.json', True)]:
            data[key], source = _optional(directory, call_dir / name, json_data=structured)
            if source:
                sources.append(source)
        data['status'] = 'error' if data['error'] else 'returned' if data['response'] is not None else 'incomplete'
        # The request precedes its result even when copied files have equal mtimes.
        if sources:
            add('llm_end', data, 'llm:' + call_dir.name + ':end', sources, parent='llm:' + call_dir.name)
    for execution in sorted((directory / 'executions').glob('*')):
        sources = sorted(execution.glob('code.*'))
        if sources:
            code, source = _file(directory, sources[0])
            add('execution_start', dict(execution_id=execution.name, code=code, language=sources[0].suffix),
                'execution:' + execution.name, source)
        observation, source = _optional(directory, execution / 'observation.json', json_data=True)
        data, sources = dict(observation=observation), [source] if source else []
        for key in ('stdout', 'stderr'):
            data[key], source = _optional(directory, execution / (key + '.log'))
            if source:
                sources.append(source)
        if sources:
            add('execution_end' if observation else 'execution_incomplete', data,
                'execution:' + execution.name + ':end', sources, parent='execution:' + execution.name)
    for path in sorted((directory / 'results').glob('*/*.json')):
        data, source = _optional(directory, path, json_data=True)
        response_path = (data.get('producer') or {}).get('response_path')
        response, response_source = None, None
        if response_path:
            candidate = Path(response_path)
            if candidate.resolve().is_relative_to(directory.resolve()):
                response, response_source = _optional(directory, candidate, json_data=True)
        add('result_registered', dict(binding=data, response=response), 'result:' + source['path'],
            [source, response_source] if response_source else source,
            timestamp=data.get('created_at'), parent='execution:' + str(data.get('execution_id')))
    for identity, data, source in report_records(directory):
        add('report', data, identity, source)
    for identity, data, source in artifact_records(directory):
        add('saved_artifact', data, identity, source)
    usage, source = _optional(directory, directory / 'llm_usage.json', json_data=True)
    if source:
        add('llm_usage_summary', usage, 'reconstruction:llm_usage', source)
    last = snapshots[-1][0]
    add('session_snapshot', dict(status=last.get('status'), updated_at=last.get('updated_at')),
        'reconstruction:session_snapshot', snapshots[-1][1])
    ordered = [row for _, _, row in sorted(records, key=lambda item: (item[0], item[1]))]
    by_id = {row['event_id']: row for row in ordered}
    output, seen = [], set()
    def visit(row):
        if row['event_id'] in seen:
            return
        parent = by_id.get(row['parent_id'])
        if parent:
            visit(parent)
        seen.add(row['event_id'])
        output.append(row)
    for row in ordered:
        visit(row)
    return output


def _write_new(directory, records):
    path = directory / 'trace.jsonl'
    fd, temporary = tempfile.mkstemp(prefix='.trace-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            for seq, row in enumerate(records, 1):
                handle.write(_json(dict(row, seq=seq)) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    _INDEX.pop(str(path), None)


def backfill(directory, *, allow_running=False, initial_state=None):
    """Create a missing trace; an existing trace is never replaced or reordered."""
    directory = Path(directory).absolute()
    with _lock(directory):
        path = directory / 'trace.jsonl'
        if path.exists():
            return dict(session=str(directory), trace=str(path), created=False)
        snapshots = list(_snapshots(directory)) if initial_state is None else [(initial_state, {})]
        if not snapshots:
            raise ValueError(f'No session states found in {directory}')
        state = snapshots[-1][0]
        if not allow_running and (state.get('status') == 'running' or
                (state.get('job') or {}).get('status') == 'running' or
                (directory / 'execution_process.json').exists()):
            raise ValueError('Session is running; finish or stop it before exporting.')
        mode = 'live' if initial_state is not None else 'reconstructed'
        rows = [_header(directory, state, mode)]
        if initial_state is not None:
            rows.append(_record(directory, 'session_created', initial_state,
                                event_id='session:created', timestamp=state.get('created_at')))
        else:
            rows.extend(_historical(directory, snapshots))
        _write_new(directory, rows)
        return dict(session=str(directory), trace=str(path), created=True, events=len(rows))


def initialize(directory, state):
    try:
        backfill(directory, initial_state=state)
    except Exception as exc:
        _LOG.warning('Trace initialization failed for %s (%s)', directory, type(exc).__name__)


@contextmanager
def session_trace(store, sid):
    directory = store.directory(sid)
    active = False
    try:
        # A linked/frozen view must never create files in its original session.
        if not directory.is_symlink():
            backfill(directory, allow_running=True)
            active = True
    except Exception as exc:
        _LOG.warning('Trace initialization failed for %s (%s)', directory, type(exc).__name__)
    turn = 'turn:' + uuid4().hex
    token = _TURN.set(turn)
    if active:
        emit(directory, 'turn_start', {}, event_id=turn)
    failure = None
    try:
        yield
    except BaseException as exc:
        failure = type(exc).__name__
        raise
    finally:
        if active:
            try:
                state = store.load(sid)
                capture_coding(directory, state)
                for identity, data, source in report_records(directory):
                    emit(directory, 'report', data, event_id=identity, source=source)
                capture_artifacts(directory)
                usage, source = _optional(directory, directory / 'llm_usage.json', json_data=True)
                if source:
                    emit(directory, 'llm_usage_summary', usage, event_id=turn + ':usage', source=source)
                emit(directory, 'turn_end', dict(status=state.get('status'), exception_type=failure),
                     event_id=turn + ':end', parent_id=turn)
            except Exception as exc:
                _LOG.warning('Trace finalization failed (%s)', type(exc).__name__)
        _TURN.reset(token)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sessions', nargs='+', type=Path, help='Session directories containing graph.sqlite')
    args = parser.parse_args()
    for directory in args.sessions:
        try:
            print(json.dumps(backfill(directory), ensure_ascii=False), flush=True)
        except Exception as exc:
            parser.exit(1, f'Trace export failed for {directory}: {exc}\n')


if __name__ == '__main__':
    main()
