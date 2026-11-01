"""Custom repairs preserve evidence without changing selected-Skill execution."""
import json
from pathlib import Path

from mrcat.agent import Agent
from mrcat.codeact import CodeActNodes
from mrcat.coding_agent import CodingAgentNodes, SYSTEM
from mrcat.coding_protocol import redirected_logs
from test_agent import ROOT, Model, action, create, decision, native_reply, journal_view
from test_dual_executor import search_code, skill_item
from test_plan_items import item


def execution_evidence(context):
    directory = Path(context['session_directory'])
    from mrcat.coding_protocol import observation_view
    return [dict(observation_view(directory, row['result'], output_limit=16000),
                 code=row['arguments'].get('content', ''))
            for row in journal_view(context) if row['tool'] == 'run' and 'returncode' in row.get('result', {})]


def test_mixed_plan_keeps_skill_prompt_and_routes_isolated(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', search_code()),
        action('execute', 'from mrcat.tools import publish_result\npublish_result("checked", {"n": 42})'),
        action('end', 'Checked n=42.', outcome='complete'), action('execute', search_code())],
        [decision('mr', 'propose', execute=True)],
        [{'plan_items': [skill_item('first'), item('custom'), skill_item('last')]}])
    agent = Agent(ROOT, store, model=model)
    done = agent.run(sid, 'Search, check the supplied data, then search the second target')
    calls = [c for c in model.calls if c['role'] == 'mr']
    old_skill_prompt = '\n'.join(agent.prompt(name) for name in ('executor', 'mr', 'mr_tool'))
    assert calls[0]['system'] == calls[-1]['system'] == old_skill_prompt
    assert 'structured_action' not in calls[0] and 'structured_action' not in calls[-1]
    assert calls[1]['system'] == calls[2]['system'] == SYSTEM
    for call in (calls[0], calls[-1]):
        context = json.loads(call['user'])
        assert context['execution_mode'] == 'tool'
        assert 'debug_evidence' not in context and 'item_work_directory' not in context
    reviews = [c for c in model.calls if c['role'] == 'evaluate']
    assert len(reviews) == 1
    assert reviews[0]['system'] == agent.prompt('mr_codeact_review')
    task = done['task_history'][0]
    assert list(task['completed_items']) == ['first', 'custom', 'last']
    assert all(len(task['completed_items'][step]['execution_ids']) == 1 for step in ('first', 'last'))


def test_distinct_redirected_failures_stay_local_and_logs_are_snapshots(tmp_path):
    store, sid = create(tmp_path)
    def failing(index):
        return action('execute', f"from pathlib import Path\nPath('run.log').write_text('actual error {index}')\nraise SystemExit(1)")
    model = Model([*(failing(i) for i in range(3)),
        action('execute', 'from mrcat.tools import publish_result\npublish_result("answer", {"mean": 4})'),
        action('end', 'Complete.', outcome='complete')],
        [decision('mr', 'propose', execute=True)])
    agent = Agent(ROOT, store, model=model)
    done = agent.run(sid, 'Repair the supplied computation')
    contexts = [json.loads(c['user']) for c in model.calls if c['role'] == 'mr']
    evidence = execution_evidence(contexts[3])
    assert [e['redirected_logs'][0]['tail'] for e in evidence] == ['actual error 0', 'actual error 1', 'actual error 2']
    assert contexts[3]['action_history']
    assert execution_evidence(contexts[3])[-1]['returncode'] == 1
    assert sum(c['role'] == 'evaluate' for c in model.calls) == 1
    review = json.loads(next(c['user'] for c in model.calls if c['role'] == 'evaluate'))
    assert 'action_history' not in review and 'failed_execution' not in review
    assert len(review['executions']) == 4
    assert done['status'] == 'completed'


def test_repeated_error_is_executor_feedback_even_when_log_is_rewritten():
    flow = {}
    for _ in range(3):
        flow.update(CodingAgentNodes.track_observation(flow, 'same-error', changed=True, failed=True))
    assert 'Repeated identical' in flow['review_reason']
    flow = {}
    for index in range(3):
        flow.update(CodingAgentNodes.track_observation(flow, str(index), changed=True, failed=True))
    assert flow['review_reason'] == '' and flow['failures'] == 3
    assert CodeActNodes.track_observation(dict(failures=2), 'new', failed=True)['review_reason']


def test_identical_real_tracebacks_pause_without_scientific_review(tmp_path):
    store, sid = create(tmp_path)
    code = "from pathlib import Path\nPath('run.log').write_text('same diagnostic')\nraise ValueError('same failure')"
    model = Model([action('execute', code) for _ in range(3)],
                  [decision('mr', 'propose', execute=True)])
    done = Agent(ROOT, store, model=model, max_rounds=3).run(sid, 'Repair the calculation')
    cells = [e['details'] for e in done['events'] if e['type'] == 'code_execution']
    assert len(cells) == 3 and len({c['source_path'] for c in cells}) == 3
    assert not any(c['role'] == 'evaluate' for c in model.calls)
    assert done['status'] == 'paused'


def test_log_preview_is_bounded_redacted_and_workspace_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv('TEST_API_KEY', 'private-test-value')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'run.log').write_text('x' * 20000 + '\nAPI_KEY=private-test-value\nactual error')
    external = tmp_path / 'outside.log'
    external.write_text('DO NOT READ')
    (workspace / 'link.log').symlink_to(external)
    result = dict(generated_files=['workspace/run.log', 'outside.log', 'workspace/link.log'])
    logs = redirected_logs(tmp_path, result)
    assert len(logs) == 1 and logs[0]['truncated']
    assert len(logs[0]['tail']) < 4100
    assert 'private-test-value' not in logs[0]['tail']
    assert logs[0]['tail'].endswith('actual error')


def test_custom_shell_pipeline_propagates_failure_and_stops_before_publication(tmp_path):
    store, sid = create(tmp_path)
    failed_code = "python -c 'raise ValueError(\"fit failed\")' 2>&1 | tee run.log\necho invalid > should_not_exist.txt"
    model = Model([action('execute', failed_code, language='bash'),
                   action('execute', 'from mrcat.tools import publish_result\npublish_result("answer", {"n": 8})'),
                   action('end', 'Repaired.', outcome='complete')],
                  [decision('mr', 'propose', execute=True)])
    done = Agent(ROOT, store, model=model).run(sid, 'Repair the custom computation')
    cells = [e['details'] for e in done['events'] if e['type'] == 'code_execution']
    assert cells[0]['returncode'] != 0
    assert 'ValueError: fit failed' in cells[0]['stdout']
    assert cells[0]['code'] == failed_code
    assert (store.directory(sid) / cells[0]['source_path']).read_text() == failed_code
    assert not (store.directory(sid) / 'workspace/should_not_exist.txt').exists()
    repair = [json.loads(c['user']) for c in model.calls if c['role'] == 'mr'][1]
    assert execution_evidence(repair)[-1]['returncode'] != 0
    assert execution_evidence(repair)[-1]['code'] == failed_code
    assert 'ValueError: fit failed' in execution_evidence(repair)[0]['redirected_logs'][0]['tail']
    assert done['status'] == 'completed'


def test_custom_paths_are_runnable_from_workspace_without_mutating_records(tmp_path):
    store, sid = create(tmp_path)
    def read_saved_evidence(context):
        result = execution_evidence(context)[-1]
        paths = [result[key] for key in ('source_path', 'stdout_path', 'stderr_path')]
        paths += result['generated_files']
        assert all(Path(p).is_absolute() for p in paths)
        assert result['redirected_logs'][0]['path'] in paths
        assert 'failed_execution' not in context
        return action('execute', 'from pathlib import Path\n' +
            f'paths = {paths!r}\nassert all(Path(p).is_file() for p in paths)\n' +
            f'assert "actual failure" in Path({result["stderr_path"]!r}).read_text()\n' +
            'from mrcat.tools import publish_result\npublish_result("paths_checked", {"valid": True})')
    model = Model([action('execute', 'from pathlib import Path\nPath("run.log").write_text("diagnostic")\nraise ValueError("actual failure")'),
                   read_saved_evidence, action('end', 'Verified saved evidence.', outcome='complete')],
                  [decision('mr', 'propose', execute=True)])
    done = Agent(ROOT, store, model=model).run(sid, 'Read the failed operation and repair it')
    first = next(e['details'] for e in done['events'] if e['type'] == 'code_execution')
    saved = json.loads((store.directory(sid) / 'executions' / first['execution_id'] / 'observation.json').read_text())
    assert saved['source_path'].startswith('executions/')
    assert len(saved['generated_files']) == 1
    assert saved['generated_files'][0].endswith('/run.log')
    assert saved['generated_files'][0].startswith('workspace/')
    assert done['status'] == 'completed'



def test_continuous_history_preserves_reads_and_later_verification(tmp_path):
    store, sid = create(tmp_path)
    observed = []
    def inspect(context):
        evidence = execution_evidence(context)
        observed.append(len(evidence))
        assert evidence[0]['code']
        assert 'failed_execution' not in context
        return action('execute', 'from pathlib import Path\nprint(Path("fit.py").read_text())')
    code = 'from pathlib import Path\nPath("fit.py").write_text("print(8 / 0) # bad divisor")\nexec(Path("fit.py").read_text())'
    repair = ('from pathlib import Path\nimport subprocess, sys\n'
              'p=Path("fit.py")\np.write_text(p.read_text().replace("8 / 0", "8 / 2"))\n'
              'result=subprocess.run([sys.executable,str(p)],check=True,capture_output=True,text=True)\n'
              'assert float(result.stdout)==4\nfrom mrcat.tools import publish_result\n'
              'publish_result("verified", {"value":float(result.stdout)})')
    def complete(context):
        assert execution_evidence(context)[-3]['code'].startswith('raise ValueError')
        assert len(execution_evidence(context)) == 9
        assert 'failed_execution' not in context
        assert execution_evidence(context)[-1]['returncode'] == 0
        return action('end', 'Saved verified result 4.', outcome='complete')
    model = Model([action('execute', code), *([inspect] * 5),
                   action('execute', 'raise ValueError("verification still fails")'), inspect,
                   action('execute', repair), complete], [decision('mr', 'propose', execute=True)])
    done = Agent(ROOT, store, model=model).run(sid, 'Run and repair the supplied calculation')
    assert done['status'] == 'completed'
    assert observed == [1, 2, 3, 4, 5, 7]
    assert sum(c['role'] == 'evaluate' for c in model.calls) == 1
    review = json.loads(next(c['user'] for c in model.calls if c['role'] == 'evaluate'))
    assert 'failed_execution' not in review and 'debug_evidence' not in review
    assert review['handoff']['outcome'] == 'complete'
    assert len(review['executions']) == 9


def test_explicit_technical_blockage_pauses_without_scientific_review(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', 'raise ValueError("unresolved")'),
                   action('execute', 'print("inspection succeeded")'),
                   action('end', 'Cannot repair without the missing technical fact.', outcome='technical_blocked')],
                  [decision('mr', 'propose', execute=True)])
    done = Agent(ROOT, store, model=model).run(sid, 'Repair the operation')
    assert done['status'] == 'paused'
    assert not any(c['role'] == 'evaluate' for c in model.calls)
    assert done['active_task']['completed_items'] == {}


def test_scientific_boundary_still_reaches_review_without_code_prescription(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('end', 'Required ancestry-matched reference is unavailable; a different population would change the assumptions.', outcome='blocked')],
                  [decision('mr', 'propose', execute=True)],
                  evaluations=[dict(route='finalize', reason='A scientifically compatible reference is required.')],
                  finalizations=['blocked\nA compatible reference is required.\n[END_FINAL_SUMMARY]'])
    done = Agent(ROOT, store, model=model).run(sid, 'Use the explicitly requested ancestry')
    assert done['status'] == 'waiting_user'
    assert sum(c['role'] == 'evaluate' for c in model.calls) == 1


def test_coding_transport_rejects_unknown_tool_and_preserves_shared_parser():
    import pytest
    from mrcat.actions import parse_action
    from mrcat.coding_protocol import coding_call
    with pytest.raises(ValueError):
        coding_call({'type':'execute','body':'print(1)'})
    assert parse_action('```python\nprint(1)\n```', role='mr')['body'] == 'print(1)'
    assert coding_call(json.loads(native_reply(dict(tool='finish', outcome='technical_blocked', body='Missing runtime')))['tool_calls'][0])['outcome'] == 'technical_blocked'
