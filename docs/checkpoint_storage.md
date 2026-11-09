# Checkpoint storage

LangGraph checkpoints remain the authoritative session and control state. The
browser, workers, live events, and forks use the same checkpoint path resolver.
JSON and Markdown exports do not become a recovery store.

SQLite WAL databases must be on a local filesystem. For a session on NFS, a new
`graph.sqlite` entry is a symlink to local storage under
`/var/tmp/mrcat-<uid>/checkpoints/<session-path-hash>/graph.sqlite`. Set
`MRCAT_CHECKPOINT_DIR` to choose another persistent local directory. This setting
also places new sessions from local artifact directories there. Existing local
checkpoints keep their location. Different session directories have independent
databases, even if their session IDs match.

The symlink preserves existing session paths. SQLite always opens the resolved
local path, so its WAL and shared-memory files stay local too. A missing target
is an error; the application must not silently create an empty replacement.
An existing database on a network filesystem requires explicit offline migration.

## SQLite runtime version

Use SQLite 3.51.3 or newer, as required by `environment.yml`. Check the library
actually loaded by the Python interpreter that starts the server and workers:

```bash
python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

SQLite 3.51.0 and 3.51.1 have a Unix connection open/close deadlock fixed in
[3.51.2](https://www.sqlite.org/releaselog/3_51_2.html). Version
[3.51.3](https://www.sqlite.org/releaselog/3_51_3.html) also fixes a WAL-reset bug.
Moving the database to local disk does not fix a defect in the SQLite library.
After updating the environment, restart the web process so it loads the new
library; preserve checkpoint files and do not automatically restart analysis jobs.

## Offline migration

1. Stop the server and every worker using the selected sessions. Preserve their
   last committed state and execution receipts. Do not migrate a running job.
2. Run the command below in the same environment used to launch the server:

   ```bash
   python -m mrcat.checkpoints migrate --offline /path/to/session
   ```

   The migration also checks visible same-user file descriptors, but this is
   best-effort and does not replace stopping all users, including other hosts.
   It copies the database together with any WAL and rollback journal, recovers
   them locally, checks database integrity, and verifies that the source did not
   change before replacing the session entry with a link. An untouched copy of
   the original database and sidecars remains in `.checkpoint-backup-*` inside
   the session. Never copy only the main SQLite file from a WAL database.
3. Start the server and verify session history, pending work, and HTTP responses.
   A server restart does not automatically rerun stopped analysis jobs.

Use `--read-only` for frozen sessions linked into a browser store. Their original
files and directory links are not modified. The migration makes a local snapshot
and records its source file sizes and modification times. Reads use this snapshot;
write paths reject it and require a fork. A changed source fails validation rather
than silently showing the old snapshot. Use the same `MRCAT_CHECKPOINT_DIR` when
creating and reading these snapshots. To refresh an intentionally changed frozen
source, stop its readers and archive its previous local snapshot directory first.

## Web concurrency

All database operations in async request handlers run in worker threads,
including the first SSE read and manual-session creation. Session lists project
metadata from one state read per session, without scanning artifact directories. A blocked database read
must not block the HTTP event loop. Tests cover a deliberately stalled read while
the homepage responds, concurrent checkpoint readers and live-event writes,
WAL-only committed data, restart, and independent forks.

## Backup and portability

Local storage is host-specific. Backups and moves must include the resolved local
database and its WAL consistently; archiving the artifact directory alone only
archives a symlink. Stop writers and use the SQLite backup API or an offline copy
of the database and WAL. Preserve the source session ID and execution artifacts.
Provision the local directory with the same durability and backup policy as other
application state; verify the host's `/var/tmp` cleanup policy before long-term use.
