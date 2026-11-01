# Benchmarking

`mrcat-bench` runs each query in a fresh process and saves its session, execution
records, usage and provenance. It uses the same Agent and Skills as the Web and CLI.

## Queries and data

The distributed query set is [benchmarks/queries.txt](../benchmarks/queries.txt).
It uses `Q01:` headers and preserves multiline query text. Local data paths use
`${MRCAT_BENCH_DATA}`. Set that variable to an absolute directory containing the
required `Qxx/` input files. The runtime replaces only this explicit placeholder;
it saves the resolved query in each case directory. Review both the text and input
files before comparing systems. Data is not bundled.

```bash
export MRCAT_BENCH_DATA=/absolute/path/to/benchmark/data
mrcat-bench --queries benchmarks/queries.txt --only Q01,Q02 --dry-run
mrcat-bench --queries benchmarks/queries.txt --workers 2   --artifact-dir runtime_benchmark --env-file /path/to/settings.env
```

`--dry-run` inspects queries without model calls or output files. `--preflight-only`
checks the worker environments and makes one model connectivity probe, but does
not execute benchmark queries. `--no-auto-confirm-plan` stops at the initial plan.
The default confirms the initial plan only; it does not fabricate clarification
answers or approve later changes of scientific scope.

## Isolation and storage

Linux bubblewrap (`bwrap`), unprivileged user namespaces and the documented R
environment are required. The runner fails if the boundary cannot be established.
It exposes read-only source files, installed software, declared reference resources
and the exact absolute input files named by that query. Query outputs and its local
checkpoint subtree are writable; sibling queries and prior sessions are excluded.
Networking remains shared with the host.

Checkpoints use persistent local storage; see [session storage](architecture.md).
Include the actual SQLite databases when backing up a batch, as session entries
may be symlinks to host-local files.

## Provenance and interpretation

Each new batch writes `provenance.json`, `batch.json`, per-query records and TSV/JSON
summaries. These record source state and hashes, explicit input hashes, resolved
query text, model settings and usage. They do not freeze a remote API, shared data
or transitive software installation. Keep those unchanged for a controlled run.

Use `--require-commit FULL_COMMIT` with a clean dedicated source checkout for a
frozen experiment. The source check rejects tracked changes, untracked files and
ignored executable source files. Keep credentials outside the checkout with
`--env-file`.

This release includes a runner and query set. Historical manuscript results retain
their original source versions; preparing or testing this release does not rerun or
re-score those experiments. A completed process or session status is not a
scientific correctness score. Use a separately specified rubric and inspect actual
artifacts when evaluating analytical validity.
