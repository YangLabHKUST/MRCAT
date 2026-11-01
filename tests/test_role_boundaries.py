"""Behavioral boundaries between independent role subgraphs and durable memory."""
import json
from mrcat.agent import Agent
from mrcat.execution import CodeExecutor
from mrcat import memory
from test_agent import ROOT, Model, create, decision, action, verified_value


def contexts(model, role):
    return [json.loads(call['user']) for call in model.calls if call['role'] == role]


def test_search_does_not_overwrite_pending_mr_plan_or_user_request(tmp_path):
    store, sid = create(tmp_path)
    model = Model(['CAD candidates delivered.', verified_value(), 'MR answer.'],
                  [decision('mr', 'propose', description='BMI to T2D'), decision('search'), decision('mr', 'confirm')],
                  ['Analyze BMI to T2D.'])
    agent = Agent(ROOT, store, model=model)
    proposed = agent.run(sid, 'Analyze BMI to T2D')
    searched = agent.run(sid, 'First find CAD datasets')
    assert searched['pending'] == proposed['pending']
    assert searched['plan'] == proposed['plan']
    assert searched['memory_request'] == 'Analyze BMI to T2D'
    assert searched['active_task'] is None
    assert contexts(model, 'search')[0]['current_plan'] == ''
    done = agent.run(sid, 'Confirm the BMI plan')
    assert done['task_history'][0]['task_id'] == 'task1'
    assert done['task_history'][0]['request'] == 'Analyze BMI to T2D'
    assert len(contexts(model, 'planner')) == 1
    assert 'Task completed: task1.' in done['task_history'][0]['memory']


def test_search_recovery_changes_approach_without_planner(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('evaluate', 'The remote source is unavailable.'),
                   action('execute', 'print("Use provided local candidate cache")'), 'Cache results delivered.'],
                  evaluations=[dict(route='recover', reason='Use the supplied cache.', message='Read the local cache.')])
    done = Agent(ROOT, store, model=model).run(sid, 'Find candidates from the endpoint or supplied cache')
    assert done['status'] == 'completed'
    assert len(contexts(model, 'evaluate')) == 1
    assert not contexts(model, 'planner')
    assert not any(e['type'] in {'plan_updated', 'recovery_started'} for e in done['events'])
    assert 'Read the local cache.' in json.dumps(contexts(model, 'search')[1])


def test_stale_summary_cannot_restore_delivered_todo(tmp_path):
    store, sid = create(tmp_path)
    base = Model([action('execute', 'print("Found BMI candidates")'), 'BMI candidates delivered.', 'CAD candidates delivered.'])
    def model(**kwargs):
        if kwargs['role'] == 'memory':
            note = memory.initial_search_memory('BMI')
            return memory.replace_section(note, 'Open Questions', 'Next summarize BMI.') + '\n[END_MEMORY]'
        return base(**kwargs)
    agent = Agent(ROOT, store, model=model)
    first = agent.run(sid, 'Find BMI candidates')
    assert 'Next summarize BMI' not in first['role_memory']['search']['memory']
    agent.run(sid, 'Find CAD candidates')
    context = contexts(base, 'search')[-1]
    assert 'BMI' not in context['memory']
    assert context['prior_work'][-1]['status'] == 'completed'
    assert 'memory' not in context['prior_work'][-1]  # Prior goals are a directory, not active instructions.
    assert context['work_request'] == 'Find CAD candidates'


def test_summary_failure_preserves_search_evidence_on_continuation(tmp_path):
    store, sid = create(tmp_path)
    state = store.load(sid)
    work = memory.work_state(state, 'search')
    work.update(request='Find CAD', memory=memory.replace_section(memory.initial_search_memory('Find CAD'),
                 'Evidence Claims', 'Observed study ABC; workspace/candidates.json.'), status='waiting_user')
    store.save(state)
    base = Model([action('execute', 'print("ABC")'), 'ABC is available.'], [decision('search', 'continue')])
    def model(**kwargs):
        if kwargs['role'] == 'memory':
            raise RuntimeError('summary unavailable')
        return base(**kwargs)
    done = Agent(ROOT, store, model=model).run(sid, 'Show ABC')
    note = done['role_memory']['search']['memory']
    assert 'Observed study ABC; workspace/candidates.json.' in note
    assert 'Result delivered to the user' in note
    assert done['role_memory']['search']['status'] == 'completed'


def test_large_output_preserves_header_and_last_lines_in_model_context(tmp_path):
    store, sid = create(tmp_path)
    result = CodeExecutor(ROOT, store.directory(sid)).execute(
        'print("HEADER columns: source, study_id; count=10"); print("x"*80000); print("END diagnostics")',
        'python', 'preview')
    preview = json.loads(memory.message_content(dict(role='observation', content=json.dumps(result)), 6500))
    assert 'HEADER columns: source, study_id; count=10' in preview['stdout']
    assert 'END diagnostics' in preview['stdout']
    assert len(preview['stdout']) < 6500
    assert (store.directory(sid)/result['stdout_path']).stat().st_size > 80000


def test_codeact_calls_named_search_tool_once_and_delivers_frontend_files(tmp_path):
    store, sid = create(tmp_path)
    # Replace only network discovery inside the child process; run the real public tool,
    # writers, subprocess execution, observation and delivery nodes.
    code = '''import importlib, json
from pathlib import Path
from mrcat.tools import gwas_search
module = importlib.import_module("skills.gwas-search.scripts.search_orchestrator")
candidate = dict(source="opengwas", study_id="fixture-cad", trait="Coronary artery disease", ancestry="european", sample_size=10000, downloadable=True, download_descriptor=dict(source="opengwas", study_id="fixture-cad", status="ready", method="url", url="https://example.invalid/cad.tsv"))
def search(**kwargs):
    return dict(candidates=[candidate], raw_results=[], source_timings={}, source_reports=[dict(source="opengwas", status="ok")])
module._search_trait_once = search
result = gwas_search(trait="coronary artery disease", source="opengwas")
assert result["outputs"]["status"] == "ok", result
path = result["outputs"]["gwas_search_results"]["shortlists_path"]
rows = json.loads(Path(path).read_text())["candidates"]
print(json.dumps(dict(count=len(rows), studies=[r["study_id"] for r in rows], shortlist=path)))
'''
    model = Model([action('execute', code), 'Found fixture-cad; the candidate files are available.'])
    done = Agent(ROOT, store, model=model).run(sid, 'Search for CAD datasets')
    cells = [e['details'] for e in done['events'] if e['type'] == 'code_execution']
    assert len(cells) == 1 and cells[0]['returncode'] == 0, cells
    assert 'fixture-cad' in contexts(model, 'search')[-1]['recent_messages'][-1]['content']
    assert any(p.endswith('gwas_search_shortlists.json') for p in cells[0]['generated_files'])
    assert any(p.endswith('gwas_search_shortlists.xlsx') for p in cells[0]['generated_files'])
    assert not contexts(model, 'planner')
    assert done['active_task'] is None and done['status'] == 'completed'
