"""Local SQLite checkpoint storage and explicit offline migration."""
from contextlib import closing
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import shutil
import sqlite3
from uuid import uuid4

NETWORK_FILESYSTEMS = {'nfs', 'nfs4', 'cifs', 'smb3', '9p', 'ceph', 'lustre',
                       'fuse.sshfs', 'fuse.glusterfs'}
SIDECARS = ('', '-wal', '-shm', '-journal')


@lru_cache(maxsize=1)
def mounts():
    entries = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, right = line.split(' - ', 1)
        mount = left.split()[4]
        for escaped, literal in [('\\040', ' '), ('\\011', '\t'), ('\\012', '\n'), ('\\134', '\\')]:
            mount = mount.replace(escaped, literal)
        entries.append((Path(mount), right.split()[0]))
    return sorted(entries, key=lambda item: len(item[0].parts), reverse=True)


def network_path(path):
    resolved = Path(path).resolve()
    return next(kind in NETWORK_FILESYSTEMS for mount, kind in mounts()
                if resolved.is_relative_to(mount))


def local_target(directory, root=None):
    root = Path(root or os.getenv('MRCAT_CHECKPOINT_DIR') or
                f'/var/tmp/mrcat-{os.getuid()}/checkpoints').resolve()
    if network_path(root):
        raise ValueError(f'Checkpoint storage must be on a local filesystem: {root}')
    identity = sha256(str(Path(directory).resolve()).encode()).hexdigest()[:24]
    return root / identity / 'graph.sqlite'


def checkpoint_path(directory, *, create=False, writable=False):
    """Keep the session entry stable, but always open SQLite on local storage."""
    directory = Path(directory)
    entry = directory / 'graph.sqlite'
    if entry.is_symlink() and not entry.exists():
        # Never replace lost authoritative state with an empty database.
        raise FileNotFoundError(f'Checkpoint target is missing: {entry} -> {entry.resolve()}')
    if entry.exists():
        if network_path(entry):
            target = local_target(directory)
            marker = target.parent / 'readonly.json'
            if marker.exists():
                saved = json.loads(marker.read_text())
                if saved['source'] != str(entry.resolve()) or saved['signature'] != signature(entry):
                    raise ValueError(f'Frozen checkpoint changed; recreate its local snapshot: {entry}')
                if create or writable:
                    raise PermissionError('Frozen checkpoint snapshots are read-only. Fork the session first.')
                if not target.is_file():
                    raise FileNotFoundError(f'Frozen checkpoint snapshot is missing: {target}')
                return target
            raise ValueError(f'Checkpoint is on a network filesystem: {entry}. '
                             'Stop its server and workers, then run '
                             'python -m mrcat.checkpoints migrate --offline SESSION_DIR.')
        return entry.resolve()
    if create and (os.getenv('MRCAT_CHECKPOINT_DIR') or network_path(directory)):
        target = local_target(directory)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Create the target before publishing the link; concurrent readers must
        # never see a dangling checkpoint reference during session creation.
        target.touch(exist_ok=False, mode=0o600)
        directory.mkdir(parents=True, exist_ok=True)
        entry.symlink_to(target)
        return target
    return entry


def checkpoint_users(entry):
    """Best-effort guard; --offline still requires the operator to stop users."""
    paths = {str(entry) + suffix for suffix in SIDECARS}
    users = set()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            for fd in (process / 'fd').iterdir():
                try:
                    if os.readlink(fd) in paths:
                        users.add(int(process.name))
                except FileNotFoundError:
                    pass
        except (FileNotFoundError, ProcessLookupError):
            pass
        except PermissionError:
            # Non-dumpable processes cannot be inspected even for the same UID.
            # This check supplements the explicit offline migration contract.
            continue
    return sorted(users)


def signature(entry):
    return {suffix: [path.stat().st_size, path.stat().st_mtime_ns]
            for suffix in SIDECARS if (path := Path(str(entry) + suffix)).exists()}


def migrate(directory, *, root=None, readonly=False):
    """Migrate a quiescent DB plus WAL; retain an untouched source backup."""
    if Path(directory).is_symlink() and not readonly:
        raise ValueError('Linked sessions must use --read-only; never modify their original checkpoint.')
    directory = Path(directory).resolve(strict=True)
    entry = directory / 'graph.sqlite'
    if entry.is_symlink():
        return dict(session=str(directory), target=str(checkpoint_path(directory)), migrated=False)
    if not entry.is_file():
        raise FileNotFoundError(entry)
    users = checkpoint_users(entry)
    if users:
        raise ValueError(f'Stop checkpoint readers and writers before migration; active PIDs: {users}')
    target = local_target(directory, root)
    target.parent.mkdir(parents=True, exist_ok=False, mode=0o700)
    backup = (target.parent / 'source-backup' if readonly else
              directory / ('.checkpoint-backup-' + uuid4().hex[:12]))
    backup.mkdir(mode=0o700)
    originals = [Path(str(entry) + suffix) for suffix in SIDECARS
                 if Path(str(entry) + suffix).exists()]
    before = signature(entry)
    try:
        for path in originals:
            shutil.copy2(path, backup / path.name)
        # Rebuild shared-memory metadata locally. The WAL contains committed
        # pages that may not yet be present in the main database file.
        for suffix in ('', '-wal', '-journal'):
            source = backup / ('graph.sqlite' + suffix)
            if source.exists():
                shutil.copy2(source, Path(str(target) + suffix))
        with closing(sqlite3.connect(target)) as conn:
            check = conn.execute('PRAGMA integrity_check').fetchall()
            if check != [('ok',)]:
                raise ValueError(f'Checkpoint integrity check failed: {check}')
            if conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] != 0:
                raise ValueError('Local WAL recovery is busy')
        after = signature(entry)
        if before != after or checkpoint_users(entry):
            raise ValueError('Source changed during migration; stop all readers and writers first.')
        if readonly:
            (target.parent / 'readonly.json').write_text(json.dumps(
                dict(source=str(entry), signature=before), indent=2) + '\n')
            return dict(session=str(directory), target=str(target), backup=str(backup), readonly=True)
        link = directory / ('.checkpoint-link-' + uuid4().hex)
        link.symlink_to(target)
        os.replace(link, entry)
        for path in originals:
            if path != entry:
                path.unlink()
    except BaseException:
        # Before publication, the original checkpoint is still authoritative.
        if not entry.is_symlink():
            shutil.rmtree(target.parent)
        raise
    result = dict(session=str(directory), target=str(target), backup=str(backup), migrated=True)
    (backup / 'migration.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['migrate'])
    parser.add_argument('sessions', nargs='+', type=Path)
    parser.add_argument('--checkpoint-dir', type=Path)
    parser.add_argument('--read-only', action='store_true',
                        help='Create a local snapshot for frozen linked sessions without modifying the source.')
    parser.add_argument('--offline', required=True, action='store_true',
                        help='Confirm that all servers and workers using these sessions are stopped.')
    args = parser.parse_args()
    for directory in args.sessions:
        print(json.dumps(migrate(directory, root=args.checkpoint_dir, readonly=args.read_only), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
