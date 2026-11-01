"""Parallel benchmark workers isolated by bubblewrap filesystem allowlists."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import traceback
from uuid import uuid4

from .store import Store, now, write_json

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ("query_id", "status", "duration_s", "llm_call_count", "llm_total_tokens",
           "llm_unreported_usage_calls", "pending_kind", "session_id", "session_dir", "stop_reason")


def parse_queries(path):
    """Keep multiline query text; reject ambiguous IDs instead of overwriting cases."""
    cases = []
    current = None
    lines = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^\s*(Q\d{2,})\s*:\s*(.*)$", line)
        if match:
            if current:
                cases.append(dict(query_id=current, query="\n".join(lines).strip()))
            current, first = match.groups()
            lines = [first]
        elif current:
            lines.append(line)
        elif line.strip():
            raise ValueError("Query text must start with a Q01: header")
    if current:
        cases.append(dict(query_id=current, query="\n".join(lines).strip()))
    ids = [case["query_id"] for case in cases]
    if not cases or len(ids) != len(set(ids)) or any(not c["query"] for c in cases):
        raise ValueError("Queries must have unique IDs and nonempty text")
    return cases


def select_queries(cases, only, limit=None):
    wanted = {part.strip().upper() for value in only for part in value.split(",") if part.strip()}
    unknown = wanted - {case["query_id"] for case in cases}
    if unknown:
        raise ValueError("Unknown query IDs: " + ", ".join(sorted(unknown)))
    selected = [case for case in cases if not wanted or case["query_id"] in wanted]
    return selected[:limit] if limit is not None else selected


def result_record(query_dir, *, status=None, reason="", duration=0):
    sessions = sorted(p for p in Path(query_dir).glob("session_*") if p.is_dir())
    session = sessions[0] if sessions else None
    try:
        state = Store(query_dir).load(session.name) if session else {}
    except FileNotFoundError:
        # A worker can time out after creating its directory but before its
        # initial checkpoint. Preserve the batch's timeout result.
        state = {}
    usage_path = session / "llm_usage.json" if session else None
    try:
        usage = json.loads(usage_path.read_text()) if usage_path and usage_path.exists() else {}
    except (OSError, ValueError):
        # An interrupted usage writer can leave a partial file; unknown is not zero.
        usage = {key: None for key in ("llm_call_count", "llm_total_tokens", "llm_unreported_usage_calls")}
    pending = state.get("pending") or {}
    case = json.loads((Path(query_dir) / "query.json").read_text())
    latest = next((e["content"] for e in reversed(state.get("events", []))
                   if e["type"] in {"final", "question", "error", "interrupted"}), "")
    tasks = state.get("task_history", []) + ([state["active_task"]] if state.get("active_task") else [])
    return dict(query_id=case["query_id"], status=status or state.get("status", "failed"),
                duration_s=round(duration, 3), session_id=state.get("session_id"),
                session_dir=str(session) if session else None,
                llm_call_count=usage.get("llm_call_count", 0),
                llm_total_tokens=None if usage.get("llm_unreported_usage_calls") else usage.get("llm_total_tokens", 0),
                llm_unreported_usage_calls=usage.get("llm_unreported_usage_calls", 0),
                pending_kind=pending.get("kind"), stop_reason=reason or pending.get("question") or latest,
                task_statuses=[dict(task_id=t["task_id"], status=t["status"])
                               for t in tasks])


def run_case(query_dir):
    """One fresh process, Store and Agent per query; never fabricate clarification replies."""
    from .agent import Agent
    query_dir = Path(query_dir).resolve()
    case = json.loads((query_dir / "query.json").read_text())
    settings = json.loads((query_dir / "settings.json").read_text())
    started = time.monotonic()
    try:
        os.chdir(query_dir)
        os.environ["LLM_PROVIDER"] = settings["provider"]
        store = Store(query_dir)
        state = store.create(case["query"], settings["provider"])
        agent = Agent(ROOT, store, max_rounds=settings["max_rounds"],
                      execution_timeout=settings["execution_timeout"],
                      auto_confirm_plan=settings["auto_confirm_plan"])
        agent.run(state["session_id"], case["query"])
        result = result_record(query_dir, duration=time.monotonic() - started)
    except Exception as exc:
        traceback.print_exc()
        result = result_record(query_dir, status="failed", reason=f"{type(exc).__name__}: {exc}",
                               duration=time.monotonic() - started)
    write_json(query_dir / "result.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "completed" else 1


def write_summaries(batch_dir, cases):
    records = []
    for case in cases:
        path = batch_dir / case["query_id"] / "result.json"
        records.append(json.loads(path.read_text()) if path.exists() else
                       dict(query_id=case["query_id"], status="pending"))
    temporary = batch_dir / "summary.jsonl.tmp"
    temporary.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    temporary.replace(batch_dir / "summary.jsonl")
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=COLUMNS, delimiter="\t", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    temporary = batch_dir / "summary.tsv.tmp"
    temporary.write_text(stream.getvalue(), encoding="utf-8")
    temporary.replace(batch_dir / "summary.tsv")
    return records


def stop_worker(process):
    """Terminate bwrap; its private PID namespace kills all worker descendants."""
    # execution_process.json contains namespace-local PIDs. Never signal those
    # numbers on the host: they can identify unrelated host processes.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_batch(batch_dir, cases, *, workers, query_timeout, preflight_only=False):
    from .sandbox import prepare_worker, preflight, query_inputs
    from .preflight import check_model
    queued = iter(cases)
    active = {}
    exhausted = False
    launches = {}
    # Check every filesystem view before starting any model calls.
    for case in cases:
        directory = batch_dir / case["query_id"]
        command, env, manifest = prepare_worker(ROOT, directory, query_inputs(case["query"]))
        write_json(directory / "sandbox.json", manifest)
        preflight(command, env)
        launches[case["query_id"]] = (command, env)
    write_summaries(batch_dir, cases)
    print("Checking model API inside bwrap (up to 60 seconds)...", flush=True)
    first = cases[0]["query_id"]
    check_model(*launches[first], batch_dir / first)
    if preflight_only:
        return write_summaries(batch_dir, cases)
    try:
        while active or not exhausted:
            while len(active) < workers and not exhausted:
                case = next(queued, None)
                if case is None:
                    exhausted = True
                    break
                directory = batch_dir / case["query_id"]
                prefix, env = launches[case["query_id"]]
                log = (directory / "run.log").open("w")
                try:
                    proc = subprocess.Popen(prefix + [sys.executable, "-m", "mrcat.benchmark", "--worker", str(directory)],
                                            cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT,
                                            start_new_session=True)
                finally:
                    log.close()
                active[proc] = (directory, time.monotonic())
                print(f"{case['query_id']}: started -> {directory}", flush=True)
            for proc, (directory, started) in list(active.items()):
                elapsed = time.monotonic() - started
                timed_out = query_timeout > 0 and elapsed >= query_timeout and proc.poll() is None
                if timed_out:
                    stop_worker(proc)
                if proc.poll() is None:
                    continue
                if timed_out or not (directory / "result.json").exists():
                    # A worker may die before saving a result. Preserve its session evidence.
                    if not timed_out:
                        stop_worker(proc)
                    result = result_record(directory, status="timeout" if timed_out else "failed",
                                           reason="Query time limit exceeded" if timed_out else f"Worker exited with code {proc.returncode}; see run.log",
                                           duration=elapsed)
                    write_json(directory / "result.json", result)
                result = json.loads((directory / "result.json").read_text())
                print(f"{directory.name}: {result['status']}; calls={result['llm_call_count']}; tokens={result['llm_total_tokens']}", flush=True)
                del active[proc]
                write_summaries(batch_dir, cases)
            if active:
                time.sleep(0.1)
    finally:
        for proc, (directory, started) in active.items():
            stop_worker(proc)
            if not (directory / "result.json").exists():
                write_json(directory / "result.json", result_record(directory, status="interrupted",
                           reason="Batch runner interrupted", duration=time.monotonic() - started))
        write_summaries(batch_dir, cases)
    return write_summaries(batch_dir, cases)


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be at least 1")
    return number


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "--worker":
        return run_case(argv[1])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True, help="Q01: query file")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--artifact-dir", type=Path, default=Path("runtime_benchmark"), help="Root for a new timestamped batch directory")
    target.add_argument("--batch-dir", type=Path, help="Exact NEW batch directory; query directories are Q01, Q02, etc.")
    parser.add_argument("--batch-suffix", default="", help="Label for an automatically named batch")
    parser.add_argument("--only", action="append", default=[], help="Query IDs, e.g. Q01,Q03; repeatable")
    parser.add_argument("--limit", type=positive)
    parser.add_argument("--workers", type=positive, default=5)
    parser.add_argument("--provider", choices=("anthropic", "openai", "deepseek", "qwen", "glm", "grok", "custom"))
    parser.add_argument("--env-file", type=Path, help="Optional model settings; exported environment variables take priority")
    parser.add_argument("--max-rounds", type=positive, default=int(os.getenv("MRCAT_MAX_ROUNDS", "300")), help="Agent action budget per turn")
    parser.add_argument("--execution-timeout", type=positive, default=3600, help="Seconds per code cell")
    parser.add_argument("--query-timeout", type=positive, default=0, help="Seconds per query including planning; default: no query time limit")
    parser.add_argument("--no-auto-confirm-plan", action="store_true", help="Stop at the initial MR Plan instead of confirming it")
    parser.add_argument("--dry-run", action="store_true", help="Show queries and destinations; create no files and make no model calls")
    parser.add_argument("--preflight-only", action="store_true", help="Check all sandboxes and make one model probe; do not run queries")
    parser.add_argument("--require-commit", help="Require this full Git commit and a clean source checkout")
    args = parser.parse_args(argv)
    try:
        query_path = args.queries.resolve()
        cases = select_queries(parse_queries(query_path), args.only, args.limit)
        for case in cases:
            if "${MRCAT_BENCH_DATA}" in case["query"]:
                data_root = os.getenv("MRCAT_BENCH_DATA")
                if not data_root or not Path(data_root).is_absolute():
                    raise ValueError("Set MRCAT_BENCH_DATA to the absolute benchmark data directory")
                case["query"] = case["query"].replace("${MRCAT_BENCH_DATA}", str(Path(data_root).resolve()))
        if args.batch_suffix and not re.fullmatch(r"[A-Za-z0-9_-]+", args.batch_suffix):
            raise ValueError("Batch suffix must use letters, digits, underscores or hyphens")
        if args.batch_dir and args.batch_suffix:
            raise ValueError("Use --batch-suffix only with --artifact-dir")
        label = query_path.stem
        name = f"mrcat_{label}_{time.strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:6]}"
        if args.batch_suffix:
            name += "_" + args.batch_suffix
        batch_dir = (args.batch_dir or args.artifact_dir / name).resolve()
        if batch_dir.exists():
            raise ValueError(f"Batch directory already exists; choose a new directory: {batch_dir}")
        if args.env_file and not args.env_file.is_file():
            raise ValueError(f"Environment file does not exist: {args.env_file}")
        from .provenance import source_version, capture
        os.environ.setdefault("MRCAT_CONFIG_DIR", str(Path.cwd()))
        version = source_version(ROOT, args.require_commit)
        if args.dry_run:
            from .sandbox import query_inputs
            print(json.dumps(dict(queries=str(query_path), batch_dir=str(batch_dir), workers=args.workers,
                                  isolation="bwrap", network="shared-host",
                                  auto_confirm_plan=not args.no_auto_confirm_plan,
                                  cases=[dict(**case, query_dir=str(batch_dir / case['query_id']),
                                              input_files=query_inputs(case['query'])) for case in cases]), ensure_ascii=False, indent=2))
            return 0
        from mrcat.config.env import load_repo_dotenv, disable_proxy_from_env_if_requested
        from mrcat.config.loader import load_repo_config
        from dotenv import load_dotenv
        if args.env_file:
            load_dotenv(args.env_file, override=False)
        load_repo_dotenv(repo_root=ROOT)
        disable_proxy_from_env_if_requested()
        if args.provider:
            os.environ["LLM_PROVIDER"] = args.provider
        config = load_repo_config(repo_root=ROOT).config
        settings = dict(provider=config.llm.gateway.provider, model=config.llm.models.default,
                        isolation="bwrap", network="shared-host",
                        max_rounds=args.max_rounds, execution_timeout=args.execution_timeout,
                        query_timeout=args.query_timeout, auto_confirm_plan=not args.no_auto_confirm_plan)
        print("Recording source version and input checksums...", flush=True)
        provenance = capture(ROOT, query_path, cases, config, version)
        batch_dir.mkdir(parents=True, exist_ok=False)
        write_json(batch_dir / "provenance.json", provenance)
        write_json(batch_dir / "batch.json", dict(created_at=now(), queries=str(query_path),
                   repo_root=str(ROOT), python=sys.executable, workers=args.workers, settings=settings, cases=cases))
        for case in cases:
            write_json(batch_dir / case["query_id"] / "query.json", case)
            write_json(batch_dir / case["query_id"] / "settings.json", settings)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"Batch: {batch_dir}\nQueries: {len(cases)}; workers: {args.workers}", flush=True)
    try:
        records = run_batch(batch_dir, cases, workers=args.workers, query_timeout=args.query_timeout,
                            preflight_only=args.preflight_only)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Benchmark startup failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; partial sessions and summaries are saved.", flush=True)
        return 130
    print(f"Summary: {batch_dir / 'summary.tsv'}", flush=True)
    if args.preflight_only:
        print("Preflight passed; no benchmark queries were started.", flush=True)
        return 0
    return 0 if all(r["status"] == "completed" for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
