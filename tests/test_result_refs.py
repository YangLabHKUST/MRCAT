"""Result binding survives process boundaries without constraining CodeAct."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from mrcat.state import results
from mrcat import tools
from mrcat.agent import Agent
from mrcat.runtime.execution import CodeExecutor
from mrcat.state.store import Store
from test_agent import Model, action, create, decision

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('MRCAT_SESSION_DIR', str(tmp_path))
    monkeypatch.setenv('MRCAT_RESULT_SCOPE', 'task1')
    monkeypatch.setenv('MRCAT_EXECUTION_ID', 'cell1')
    monkeypatch.setenv('MRCAT_EXECUTION_DIR', str(tmp_path/'workspace/outputs/cell1'))
    return tmp_path


def test_custom_values_paths_and_missing_refs(runtime, monkeypatch):
    ref = tools.publish_result('custom_1', {'estimate': 0.25, 'rows': [{'value': 2}],
                                          'result_path': runtime/'result.tsv'})
    assert ref == '$ref:custom_1'
    assert tools.resolve_ref(ref+'/rows/0/value') == 2
    assert tools.resolve_ref(ref+'/result_path') == str(runtime/'result.tsv')
    with pytest.raises(ValueError, match='already exists'):
        tools.publish_result('custom_1', {'estimate': 99})
    assert tools.resolve_ref(ref+'/estimate') == 0.25
    for invalid in ['$ref:missing/value', ref+'/absent', ref+'/rows/99', '$ref:../value', ref+'/']:
        with pytest.raises(ValueError):
            tools.resolve_ref(invalid)
    copy = tools.resolve_ref(ref)
    copy['rows'][0]['value'] = 99
    assert tools.resolve_ref(ref+'/rows/0/value') == 2
    monkeypatch.setenv('MRCAT_RESULT_SCOPE', 'task2')
    with pytest.raises(ValueError, match='Unresolved'):
        tools.resolve_ref(ref)
    tools.publish_result('custom_1', {'estimate': 9})
    assert tools.resolve_ref(ref+'/estimate') == 9
    assert tools.resolve_ref('$taskref:task1/custom_1/estimate') == 0.25
    monkeypatch.setenv('MRCAT_SESSION_DIR', str(runtime/'other_session'))
    with pytest.raises(ValueError, match='Unresolved'):
        tools.resolve_ref('$taskref:task1/custom_1/estimate')


def test_common_tool_entry_resolves_nested_inputs_and_publishes(runtime, monkeypatch):
    received = []
    def run(payload):
        received.append(payload)
        return {'outputs': {'status': 'ok', 'gwas_download_result': {
            'downloaded_study': {'study_id': payload['selected_study']['study_id'],
                                'local_path': str(runtime/'raw.tsv')}}}, 'summary': 'saved'}
    class Module:
        pass
    module = Module(); module.run = run
    monkeypatch.setattr(tools, '_load', lambda *args: module)
    tools.publish_result('selection', {'candidates': [{'study_id': 'study-A'}]})
    first = tools.gwas_download(selected_study='$ref:selection/candidates/0')
    second = tools.gwas_download(selected_study={'study_id': '$ref:selection/candidates/0/study_id'})
    assert received[0] == received[1] == {'selected_study': {'study_id': 'study-A'}}
    assert first == second and 'ref' not in first
    catalog = [row for row in results.result_catalog(runtime, 'task1') if row['tool'] == 'gwas_download']
    assert len(catalog) == 2 and catalog[0]['ref'] != catalog[1]['ref']
    for row in catalog:
        assert tools.resolve_ref(row['ref']+'/gwas_download_result') == first['outputs']['gwas_download_result']
        assert row['input_identity'] == {'selected_study.study_id': 'study-A'}
        assert Path(row['response_path']).is_file()
    with pytest.raises(ValueError, match='Unresolved'):
        tools.gwas_download(selected_study='$ref:absent/value')
    assert len(received) == 2  # No backend call with an unresolved binding.


def test_blocked_tool_is_visible_but_not_reusable(runtime):
    tools._invoke(lambda _: {'outputs': {'status': 'blocked'}, 'details': {'failure_class': 'missing_N'}},
                  {'output_dir': None}, 'example')
    row = results.result_catalog(runtime, 'task1')[0]
    assert row['status'] == 'blocked'
    assert json.loads(Path(row['response_path']).read_text())['details']['failure_class'] == 'missing_N'
    with pytest.raises(ValueError, match='status blocked'):
        tools.resolve_ref(row['ref'])


def test_cross_cell_restart_and_late_failure(tmp_path):
    first = CodeExecutor(ROOT, tmp_path).execute(
        'from mrcat.tools import publish_result\n'
        'publish_result("custom_1", {"estimate": 42})\n'
        'raise RuntimeError("later operation failed")', 'python', 'first', result_scope='task1')
    assert first['returncode'] != 0
    assert first['result_refs'][0]['ref'] == '$ref:custom_1'
    # A new executor/process reads the durable table, without Python variables.
    second = CodeExecutor(ROOT, tmp_path).execute(
        'from mrcat.tools import resolve_ref\nprint(resolve_ref("$ref:custom_1/estimate"))',
        'python', 'second', result_scope='task1')
    assert second['returncode'] == 0 and second['stdout'].strip() == '42'
    assert second['result_refs'] == []
    third = CodeExecutor(ROOT, tmp_path).execute(
        'from mrcat.tools import resolve_ref\nprint(resolve_ref("$ref:custom_1/estimate"))',
        'python', 'third', result_scope='task2')
    assert third['returncode'] != 0 and 'Unresolved result reference' in third['stderr']


def test_concurrent_processes_do_not_drop_or_overwrite_results(runtime):
    code = ('from mrcat.state.results import register_tool_result\n'
            'register_tool_result("tool", {"outputs":{"status":"ok","value":42}}, {}, "response.json")')
    processes = [subprocess.Popen([sys.executable, '-c', code], cwd=ROOT,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(8)]
    try:
        output = [p.communicate(timeout=20) for p in processes]
        assert all(p.returncode == 0 for p in processes), output
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill()
            p.wait()
    assert len(results.result_catalog(runtime, 'task1')) == 8
    for row in results.result_catalog(runtime, 'task1'):
        assert tools.resolve_ref(row['ref']+'/value') == 42


def test_result_refs_remain_in_focused_repair_and_after_memory_loss(tmp_path):
    store, sid = create(tmp_path)
    model = Model([
        action('execute', 'from mrcat.tools import publish_result\npublish_result("partial", {"x":42})\nraise ValueError("later")'),
        action('execute', 'from mrcat.tools import resolve_ref, publish_result\nvalue = resolve_ref("$ref:partial/x")\nassert value == 42\npublish_result("verified", {"x":value})\nprint("reused")'),
        action('end', 'Reused published result.', outcome='complete')],
        [decision('mr', 'propose', execute=True)])
    done = Agent(ROOT, store, model=model).run(sid, 'Compute and reuse the result.')
    contexts = [json.loads(c['user']) for c in model.calls if c['role'] == 'mr']
    from test_custom_codeact import execution_evidence
    assert execution_evidence(contexts[1])[-1]['returncode'] != 0
    assert contexts[1]['result_refs'][0]['ref'] == '$ref:partial'
    assert done['status'] == 'completed'
    # Discard conversational context and reopen the store/agent.
    from mrcat.state import memory
    state = store.load(sid)
    task = state.get('active_task') or state['task_history'][-1]
    state['active_task'] = task
    state['messages'] = []
    task['memory'] = 'Summary omitted the earlier result.'
    task['memory_upto'] = 0; task['context_start'] = 0
    store.save(state)
    restored = Agent(ROOT, Store(tmp_path), model=model).executor_context(state, 'mr')
    assert restored['result_refs'][0]['ref'] == '$ref:partial'
    assert restored['result_refs'][0]['status'] == 'unverified'
    assert sum(c['role']=='evaluate' for c in model.calls) == 1


def test_new_search_scope_isolated_and_continuation_preserves_it(tmp_path):
    from mrcat.state import memory
    state = Store(tmp_path).create('Search', 'openai')
    memory.begin_role_work(state, 'search', 'run', 'first search')
    first = memory.work_state(state, 'search')['result_scope']
    memory.begin_role_work(state, 'search', 'continue', 'continue')
    assert memory.work_state(state, 'search')['result_scope'] == first
    memory.begin_role_work(state, 'search', 'run', 'different search')
    assert memory.work_state(state, 'search')['result_scope'] != first


def test_shell_code_can_publish_and_resolve_without_a_skill(tmp_path):
    code = """python - <<'PYCODE'
from mrcat.tools import publish_result
publish_result('custom_bash', {'value': 6 * 7})
PYCODE
"""
    first = CodeExecutor(ROOT, tmp_path).execute(code, 'bash', 'shell')
    second = CodeExecutor(ROOT, tmp_path).execute(
        'from mrcat.tools import resolve_ref\nprint(resolve_ref("$ref:custom_bash/value"))', 'python', 'read')
    assert first['returncode'] == second['returncode'] == 0
    assert second['stdout'].strip() == '42'


def test_simultaneous_custom_publish_has_exactly_one_winner(runtime):
    code = ('import sys\nfrom mrcat.tools import publish_result\n'
            'publish_result("same_id", {"value": int(sys.argv[1])})')
    processes = [subprocess.Popen([sys.executable, '-c', code, str(i)], cwd=ROOT,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for i in range(6)]
    try:
        outputs = [p.communicate(timeout=20) for p in processes]
        winners = [i for i, p in enumerate(processes) if p.returncode == 0]
        assert len(winners) == 1, outputs
        assert tools.resolve_ref('$ref:same_id/value') == winners[0]
        assert all('already exists' in outputs[i][1] for i in range(6) if i != winners[0])
        assert len(results.result_catalog(runtime, 'task1')) == 1
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill()
            p.wait()


def test_scalar_publication_counts_as_saved_progress(tmp_path):
    store, sid = create(tmp_path)
    actions = [action('execute', 'from mrcat.tools import publish_result\n'
                      f'publish_result("value_{i}", {{"value": {i}}})') for i in range(7)]
    model = Model([*actions, action('end', 'Published the requested values.', outcome='complete')],
                  [decision('mr', 'propose', execute=True)])
    done = Agent(ROOT, store, model=model).run(sid, 'Compute seven successive values and save each for later reuse.')
    assert done['status'] == 'completed'
    assert sum(c['role'] == 'evaluate' for c in model.calls) == 1
    assert sum(c['role'] == 'planner' for c in model.calls) == 1
    observations = [e['details'] for e in done['events'] if e['type'] == 'code_execution']
    assert len(observations) == 7
    assert all(not r['generated_files'] and len(r['result_refs']) == 1 for r in observations)
