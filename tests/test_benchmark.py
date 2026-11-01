from mrcat.store import Store
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import subprocess
import sys
import threading
import time

import pytest

from mrcat import benchmark
from test_agent import Model, action, decision, verified_value

ROOT = benchmark.ROOT


def prepare(tmp_path, auto_confirm=True):
    directory = tmp_path / "Q01"
    benchmark.write_json(directory / "query.json", dict(query_id="Q01", query="MR test"))
    benchmark.write_json(directory / "settings.json", dict(provider="openai", max_rounds=5,
                          execution_timeout=5, auto_confirm_plan=auto_confirm))
    return directory


def test_parser_and_selection(tmp_path):
    path = tmp_path / "queries.txt"
    path.write_text("Q01: line one\nline two\n\nQ02: other\n")
    cases = benchmark.parse_queries(path)
    assert cases[0]["query"] == "line one\nline two"
    assert benchmark.select_queries(cases, ["q02,Q01"], 1) == cases[:1]
    with pytest.raises(ValueError, match="Unknown query"):
        benchmark.select_queries(cases, ["Q03"])
    for text in ("Q01: a\nQ01: b", "Q01:\n", "outside\nQ01: a", ""):
        path.write_text(text)
        with pytest.raises(ValueError):
            benchmark.parse_queries(path)


def test_dry_run_and_refuse_overwrite(tmp_path, capsys):
    source = tmp_path / "queries.txt"
    source.write_text("Q01: keep exactly\n  this text\nQ02: second")
    destination = tmp_path / "new"
    assert benchmark.main(["--queries", str(source), "--only", "Q01", "--batch-dir", str(destination), "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["cases"][0]["query"] == "keep exactly\n  this text"
    assert not destination.exists()
    destination.mkdir()
    with pytest.raises(SystemExit) as exc:
        benchmark.main(["--queries", str(source), "--batch-dir", str(destination)])
    assert exc.value.code == 2


@pytest.mark.parametrize("auto_confirm", [True, False])
def test_plan_confirmation_stops_at_real_question(tmp_path, monkeypatch, auto_confirm):
    from mrcat.agent import Agent
    directory = prepare(tmp_path, auto_confirm)
    model = Model(actions=[action("ask", "What is the sample size?")],
                  decisions=[decision("mr", "propose")])
    monkeypatch.setattr("mrcat.agent.Agent", lambda *a, **k: Agent(*a, model=model, **k))
    monkeypatch.chdir(tmp_path)
    assert benchmark.run_case(directory) == 1
    result = json.loads((directory / "result.json").read_text())
    assert result["status"] == "waiting_user"
    assert result["pending_kind"] == ("clarification" if auto_confirm else "plan_confirmation")
    assert not (directory / "auto_confirmation.json").exists()
    assert len([c for c in model.calls if c["role"] == "manager"]) == 1
    session_path = next(directory.glob("session_*/graph.sqlite")).parent
    session = Store(directory).load(session_path.name)
    user_messages = [m["content"] for m in session["messages"] if m["role"] == "user"]
    assert user_messages == ["MR test"]
    assert session["request"] == "MR test"
    assert sum(e["type"] == "plan_auto_confirmed" for e in session["events"]) == int(auto_confirm)
    assert (Path(result["session_dir"]) / "plan.md").is_file()


@pytest.mark.parametrize("next_action", ["revise", "propose"])
def test_auto_confirmation_does_not_approve_later_plans(tmp_path, next_action):
    from mrcat.agent import Agent
    store = benchmark.Store(tmp_path)
    state = store.create("MR test", "openai")
    first_action = (action("ask", "Which input file should be used?") if next_action == "revise"
                    else action("final", "First analysis completed."))
    model = Model(actions=([verified_value(), first_action] if next_action == "propose" else [first_action]),
                  decisions=[decision("mr", "propose"), decision("mr", next_action)])
    agent = Agent(ROOT, store, model=model, auto_confirm_plan=True)
    agent.run(state["session_id"], "MR test")
    waiting = agent.run(state["session_id"], "Plan the updated analysis")
    assert waiting["status"] == "waiting_user"
    assert waiting["pending"]["kind"] == "plan_confirmation"
    assert sum(e["type"] == "plan_auto_confirmed" for e in waiting["events"]) == 1
    assert [m["content"] for m in waiting["messages"] if m["role"] == "user"] == [
        "MR test", "Plan the updated analysis"]


@pytest.fixture
def local_gateway(monkeypatch):
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    first_calls = []
    probes = []
    service = dict(error=None)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            system = body["messages"][0]["content"]
            if system == 'Connectivity check. Reply only with xxx.':
                probes.append(body)
                reply = (dict(error=dict(message=service['error'])) if service['error'] else
                         dict(choices=[dict(message=dict(content='xxx'))], usage=dict(prompt_tokens=5, completion_tokens=1)))
                payload = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            context = json.loads(body["messages"][1]["content"])
            if "MRCAT Manager" in system:
                with lock:
                    first_calls.append(context["latest_request"])
                    first = len(first_calls) <= 2
                if first:
                    barrier.wait(timeout=15)
                pending = context.get("pending") or {}
                request = context["latest_request"]
                route = "mr" if request.startswith("MR") or pending else "search"
                verb = "confirm" if pending else "propose" if route == "mr" else "run"
                result = dict(route=route, action=verb, message=None,
                              effective_request=request if verb in {"propose", "run"} else None)
                if "failure" in request:
                    result = dict(route="invalid")
            elif "MRCAT MR Planner" in system:
                result = dict(plan_items=[dict(step_id='write', title='Write the requested answer.', skill_id=None, reuse_from=[])])
            elif "MR item Review node" in system or "You review the SCIENTIFIC BOUNDARIES" in system:
                result = dict(route="execute", accept_item=True, reason="The file was created.")
            elif "MR Finalize node" in system:
                result = "completed\n{{value:r1/directory}}\nSaved answer.txt.\n[END_FINAL_SUMMARY]"
            elif "working memory for the current role" in system:
                result = context["previous_memory"] + "\n[END_MEMORY]"
            elif 'coding agent working' in system:
                result = (dict(tool='finish', outcome='complete', body='Saved answer.txt.') if any(m['role'] == 'tool' for m in body['messages']) else
                          dict(tool='run', language='python', content='from pathlib import Path; from mrcat.tools import publish_result; p=Path("answer.txt"); p.write_text(str(Path.cwd())); publish_result("answer", {"directory":p.read_text()})'))
            elif context["recent_messages"] and context["recent_messages"][-1]["role"] == "observation":
                result = action("end", "Saved answer.txt.", outcome="complete") if context["role"] == "mr" else action("final", "Saved answer.txt.")
            else:
                result = action("execute", 'from pathlib import Path; Path("answer.txt").write_text(str(Path.cwd())); print("saved")')
            content = json.dumps(result) if isinstance(result, dict) else result
            message = dict(role="assistant", content=content)
            if body.get('tools') and len(body['tools']) > 1:
                from test_agent import native_reply
                message=json.loads(native_reply(result))
            elif body.get('tools'):
                message = dict(role='assistant', content=None, tool_calls=[dict(id='fixture', type='function', function=dict(
                    name=body['tools'][0]['function']['name'], arguments=content))])
            payload = json.dumps(dict(choices=[dict(message=message)],
                                      usage=dict(prompt_tokens=10, completion_tokens=10))).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for key, value in dict(LLM_BACKEND="http", OPENAI_API_KEY="local-test-not-a-secret",
                           OPENAI_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1",
                           OPENAI_TIMEOUT_SEC="20", OPENAI_RETRY_COUNT="1").items():
        monkeypatch.setenv(key, value)
    yield dict(probes=probes, first_calls=first_calls, service=service)
    server.shutdown()
    thread.join()


@pytest.mark.sandbox
def test_real_parallel_agents_and_invalid_route_isolation(tmp_path, local_gateway):
    source = tmp_path / "queries.txt"
    source.write_text("Q01: MR write answer\nQ02: search write answer\nQ03: failure")
    batch = tmp_path / "batch"
    command = [sys.executable, str(ROOT / "run_agent_benchmark.py"), "--queries", str(source),
               "--batch-dir", str(batch), "--provider", "openai", "--workers", "2"]
    process = subprocess.run(command, cwd=tmp_path, text=True, capture_output=True, timeout=60)
    assert process.returncode == 1, process.stdout + process.stderr
    records = [json.loads(line) for line in (batch / "summary.jsonl").read_text().splitlines()]
    assert [r["status"] for r in records] == ["completed", "completed", "paused"]
    rejected = Store(Path(records[2]["session_dir"]).parent).load(Path(records[2]["session_dir"]).name)
    assert rejected["active_task"] is None and rejected["task_history"] == []
    assert any(e["type"] == "error" and "Routing validation failed" in e["content"] for e in rejected["events"])
    assert not any(e["type"] == "code_execution" for e in rejected["events"])
    for result in records[:2]:
        session = Path(result["session_dir"])
        assert session.parent == batch / result["query_id"]
        workdir = session / ("workspace/outputs/task1/write" if result["query_id"] == "Q01" else "workspace")
        assert (workdir / "answer.txt").read_text() == str(workdir)
        usage = json.loads((session / "llm_usage.json").read_text())
        assert result["llm_call_count"] == usage["llm_call_count"] > 0
        assert result["llm_total_tokens"] == result["llm_call_count"] * 20
    for result in records[:2]:
        state = Store(Path(result["session_dir"]).parent).load(Path(result["session_dir"]).name)
        assert sum(e["type"] == "plan_auto_confirmed" for e in state["events"]) == int(result["query_id"] == "Q01")
        assert sum(m["role"] == "user" for m in state["messages"]) == 1
    assert local_gateway["first_calls"].count("MR write answer") == 1
    assert records[0]["session_id"] != records[1]["session_id"]
    assert len(local_gateway['probes']) == 1
    preflight = json.loads((batch / 'model_preflight.json').read_text())
    assert preflight['status'] == 'passed' and preflight['reported_total_tokens'] == 6


@pytest.mark.sandbox
def test_timeout_cleans_separate_execution_group(tmp_path, monkeypatch):
    monkeypatch.setattr('mrcat.preflight.check_model', lambda *a: None)
    directory = prepare(tmp_path)
    script = directory / "worker.py"
    script.write_text('''import json, subprocess, sys
from pathlib import Path
session = Path.cwd() / "session_fixture"
session.mkdir()
proc = subprocess.Popen([sys.executable, "-c", "import time; from pathlib import Path;\\nwhile True: Path('heartbeat').write_text(str(time.time())); time.sleep(0.05)"], start_new_session=True)
(session / "execution_process.json").write_text(json.dumps({"pid": proc.pid}))
proc.wait()
''')
    original = subprocess.Popen
    def launch(command, **kwargs):
        if "--worker" in command:
            command = command[:command.index("--") + 1] + [sys.executable, str(script)]
        return original(command, **kwargs)
    monkeypatch.setattr(benchmark.subprocess, "Popen", launch)
    records = benchmark.run_batch(tmp_path, [dict(query_id="Q01", query="MR test")], workers=1, query_timeout=1)
    assert records[0]["status"] == "timeout"
    heartbeat = (directory / "heartbeat").read_text()
    time.sleep(0.3)
    assert (directory / "heartbeat").read_text() == heartbeat


def test_interrupted_usage_does_not_lose_timeout_result(tmp_path):
    directory = prepare(tmp_path)
    store = benchmark.Store(directory)
    state = store.create("MR test", "openai")
    (store.directory(state["session_id"]) / "llm_usage.json").write_text('{"llm_total_tokens":')
    result = benchmark.result_record(directory, status="timeout", reason="Query time limit exceeded")
    assert result["status"] == "timeout"
    assert result["llm_total_tokens"] is None
    assert result["session_id"] == state["session_id"]


def test_unreported_usage_is_unknown_not_zero(tmp_path):
    directory = prepare(tmp_path)
    store = benchmark.Store(directory)
    state = store.create('xxx', 'openai')
    benchmark.write_json(store.directory(state['session_id']) / 'llm_usage.json',
                         dict(llm_total_tokens=0, llm_call_count=1, llm_unreported_usage_calls=1))
    assert benchmark.result_record(directory, status='failed')['llm_total_tokens'] is None


@pytest.mark.sandbox
def test_preflight_only_never_starts_an_agent(tmp_path, local_gateway):
    source = tmp_path / 'xxx.txt'
    source.write_text('Q01: xxx')
    batch = tmp_path / 'batch'
    proc = subprocess.run([sys.executable, str(ROOT / 'run_agent_benchmark.py'), '--queries', str(source),
                           '--batch-dir', str(batch), '--provider', 'openai', '--preflight-only'],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(local_gateway['probes']) == 1 and local_gateway['first_calls'] == []
    assert not list(batch.glob('Q*/session_*'))
    assert not list(batch.glob('Q*/result.json'))


@pytest.mark.sandbox
def test_provider_failure_blocks_entire_batch(tmp_path, local_gateway):
    local_gateway['service']['error'] = 'xxx service timeout'
    source = tmp_path / 'xxx.txt'
    source.write_text('Q01: xxx\nQ02: xxx')
    batch = tmp_path / 'batch'
    proc = subprocess.run([sys.executable, str(ROOT / 'run_agent_benchmark.py'), '--queries', str(source),
                           '--batch-dir', str(batch), '--provider', 'openai'],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert 'xxx service timeout' in proc.stderr
    assert len(local_gateway['probes']) == 1 and local_gateway['first_calls'] == []
    assert not list(batch.glob('Q*/session_*'))
    report = json.loads((batch / 'model_preflight.json').read_text())
    assert report['status'] == 'failed' and report['reported_total_tokens'] is None


def test_probe_wall_clock_timeout_stops_process(tmp_path):
    from mrcat.preflight import check_model
    import os
    directory = tmp_path / 'xxx'
    directory.mkdir()
    started = time.monotonic()
    with pytest.raises(ValueError, match='exceeded'):
        check_model([sys.executable, '-c', 'import time; time.sleep(60)'],
                    dict(os.environ), directory, timeout=0.2)
    assert time.monotonic() - started < 5
    assert json.loads((tmp_path / 'model_preflight.json').read_text())['reported_total_tokens'] is None
