"""Copy an idle session into an independent store without modifying its source."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import argparse
import fcntl
import json
import os
import re
import shutil
import stat
import tempfile

from mrcat.state.store import Store, now


TEXT_SUFFIXES = {'.json', '.jsonl', '.md', '.txt', '.log', '.py', '.r', '.sh',
                 '.csv', '.tsv', '.html', '.svg', '.yaml', '.yml'}
TRANSIENT = {'graph.sqlite', 'graph.sqlite-wal', 'graph.sqlite-shm',
             'graph.sqlite-journal', 'session.json', 'conversation.json', 'memory.md',
             'report_checkpoint.json', 'job.lock', 'STOP', 'execution_process.json',
             'trace.jsonl', '.trace.lock'}
CHECKPOINT_FILES = {'graph.sqlite', 'graph.sqlite-wal', 'graph.sqlite-shm',
                    'graph.sqlite-journal'}


@contextmanager
def source_lock(source):
    """Use an existing web lock, but never create a file in the source."""
    path = source / 'job.lock'
    if not path.exists():
        yield
        return
    with path.open('rb') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Session is busy. Stop or finish its current turn first.') from exc
        yield


def inventory(source):
    result = {}
    for path in sorted(source.rglob('*')):
        if path.relative_to(source).parts[0].startswith('.checkpoint-backup-'):
            continue
        checkpoint = path.parent == source and path.name in CHECKPOINT_FILES
        try:
            info = path.lstat()
        except FileNotFoundError:
            if checkpoint and path.name != 'graph.sqlite':
                continue
            raise
        if checkpoint and path.name == 'graph.sqlite' and path.is_symlink():
            Store(source.parent).checkpoint_path(source.name)
            continue
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError(f'Cannot copy linked or special files inside a session: {path}')
        # Readers create/remove SQLite sidecars. Check session content separately;
        # physical checkpoint files are neither copied nor a change signal.
        if checkpoint:
            continue
        result[str(path.relative_to(source))] = (info.st_mode, info.st_size, info.st_mtime_ns, info.st_ino)
    return result


def copy_file(source, target, remap):
    """Remap readable artifacts; copy binary datasets without shared inodes."""
    if source.suffix.lower() in TEXT_SUFFIXES:
        with source.open('r', encoding='utf-8', errors='surrogateescape', newline='') as src:
            with target.open('w', encoding='utf-8', errors='surrogateescape', newline='') as dst:
                for line in src:
                    dst.write(remap(line))
        shutil.copystat(source, target)
    else:
        shutil.copy2(source, target)
    target.chmod(target.stat().st_mode | stat.S_IWUSR)


def fork_session(source, destination):
    """Return a new session ID; source must be idle and destination independent."""
    alias = Path(os.path.abspath(source))
    source = alias.resolve(strict=True)
    destination = Path(destination).resolve()
    if destination == source or destination.is_relative_to(source):
        raise ValueError('The destination must be outside the source session.')
    with source_lock(source):
        before = inventory(source)
        original_state = Store(source.parent).load(source.name)
        state = deepcopy(original_state)
        if state.get('persistence') != 'langgraph':
            if (source / 'report_checkpoint.json').exists():
                state['report_state'] = json.loads((source / 'report_checkpoint.json').read_text())
            tasks = [*state.get('task_history', []), *([state['active_task']] if state.get('active_task') else [])]
            for task in tasks:
                for item in task.get('plan_items', []):
                    journal = source / 'workspace' / 'outputs' / task['task_id'] / item['step_id'] / '.coding_agent' / 'journal.json'
                    if not journal.resolve().is_relative_to(source):
                        raise ValueError('Legacy coding history must remain inside its session.')
                    if journal.exists():
                        task.setdefault('coding', {})[item['step_id']] = json.loads(journal.read_text())
        if state.get('version') != 2:
            raise ValueError('Only version 2 sessions can be copied.')
        if (state.get('status') == 'running' or (state.get('job') or {}).get('status') == 'running'
                or (source / 'execution_process.json').exists()):
            raise ValueError('Session is running. Stop or finish its current turn first.')
        store = Store(destination)
        sid = 'session_' + uuid4().hex[:16]
        target = store.directory(sid)
        roots = {str(source), str(alias)}
        # Match the session root as a path, never a similarly named sibling.
        pattern = re.compile('(?:' + '|'.join(re.escape(p) for p in sorted(roots, key=len, reverse=True))
                             + r')(?=/|[\s\x22\x27<>),;\]}]|$)')
        def remap(text):
            return pattern.sub(lambda match: str(target), text)
        with tempfile.TemporaryDirectory(prefix='.fork-', dir=destination) as temporary:
            staging = Path(temporary) / sid
            staging.mkdir()
            for relative, info in before.items():
                path = Path(relative)
                if len(path.parts) == 1 and (path.name in TRANSIENT):
                    continue
                out = staging / path
                if stat.S_ISDIR(info[0]):
                    out.mkdir(parents=True, exist_ok=True)
                else:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    copy_file(source / path, out, remap)
            if (inventory(source) != before
                    or Store(source.parent).load(source.name) != original_state):
                raise ValueError('The source changed during copying. Retry after it is idle.')
            old_sid = state['session_id']
            source_updated_at = state['updated_at']
            state = json.loads(remap(json.dumps(state, ensure_ascii=False)))
            state.update(session_id=sid, persistence='langgraph', job=None, created_at=now(), updated_at=now())
            # Business state includes pending input. Start fresh graph control on
            # the next user turn instead of replaying the parent's checkpoint.
            state['events'].append(dict(id=uuid4().hex, type='session_fork',
                content='Created an independent copy. Further messages and outputs belong to this session.',
                timestamp=now(), details=dict(source_session_id=old_sid, source_directory=str(source),
                    source_updated_at=source_updated_at,
                    inherited_message_count=len(state['messages']))))
            Store(temporary).save(state)
            staging.rename(target)
    return sid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Existing session directory containing graph.sqlite')
    parser.add_argument('--artifact-dir', type=Path, default=Path('runtime_artifacts'))
    args = parser.parse_args()
    try:
        sid = fork_session(args.source, args.artifact_dir)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Copy failed: {exc}\n')
    print(json.dumps(dict(session_id=sid, directory=str(args.artifact_dir.resolve() / sid)), indent=2))


if __name__ == '__main__':
    main()
