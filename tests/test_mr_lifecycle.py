"""Nested execution, review-only resume, whole-task evidence and final artifacts."""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from mrcat.agent import Agent, parse_action
from mrcat.web.server import create_app
from test_agent import ROOT, Model, action, create, decision, verified_value


def calls(model, role):
    return [json.loads(c['user']) for c in model.calls if c['role'] == role]


def test_mr_many_saved_observations_do_not_review_each_cell(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('skill', 'mr-cml-ma'),
                   *[action('execute', f'from pathlib import Path; Path("observation_{i}.txt").write_text("checked"); print("Useful observation {i}"); from mrcat.tools import publish_result; publish_result("check_{i}", {{"checked": {i}}})') for i in range(7)],
                   action('end', 'The entire supplied Plan is supported by the observations.', outcome='complete')],
                  [decision('mr', 'propose', execute=True)])
    done = Agent(ROOT, store, model=model).run(sid, 'Inspect seven supplied values')
    assert len(calls(model, 'evaluate')) == 1
    context = calls(model, 'evaluate')[0]
    assert len(context['executions']) == 7
    assert 'Useful observation 0' in context['executions'][0]['observation']['stdout']
    assert [g['skill'] for g in context['skill_requirements']] == ['mr-cml-ma']
    assert 'invalid' in context['skill_requirements'][0]['requirements'].lower()
    assert 'candidate_final' not in context
    assert done['status'] == 'completed'
    task = done['task_history'][0]
    path = store.directory(sid) / 'workspace/outputs/task1/final_summary.md'
    assert path.read_text().strip() == task['final_summary']
    assert done['events'][-1]['type'] == 'final'


def test_failed_review_resumes_only_review_and_redacts_diagnostics(tmp_path, monkeypatch):
    store, sid = create(tmp_path)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'private-test-value-123')
    base = Model([action('execute', 'from pathlib import Path; Path("answer.txt").write_text("42")\nfrom mrcat.tools import publish_result\npublish_result("answer", {"value": int(Path("answer.txt").read_text())})'),
                  action('end', 'Saved answer.txt; Plan complete.', outcome='complete')],
                 [decision('mr', 'propose', execute=True)])
    def failed(**kwargs):
        if kwargs['role'] == 'evaluate':
            raise RuntimeError('HTTP 502 upstream; api_key=private-test-value-123')
        return base(**kwargs)
    paused = Agent(ROOT, store, model=failed).run(sid, 'Compute the supplied value')
    assert paused['status'] == 'paused'
    assert not paused['task_history']
    pending = paused['active_task']['review_pending']
    record = json.loads((store.directory(sid)/pending['error_path']).read_text())
    assert record['stage'] == 'model_call' and 'HTTP 502' in record['message']
    assert 'private-test-value-123' not in json.dumps(record)
    assert not (store.directory(sid)/'workspace/outputs/task1/final_summary.md').exists()
    model = Model(decisions=[decision('mr','continue')], evaluations=[dict(route='execute',accept_item=True,reason='Saved evidence accepted.')])
    done = Agent(ROOT, store, model=model).run(sid, 'Continue')
    assert done['status'] == 'completed'
    assert [c['role'] for c in model.calls] == ['manager','evaluate','finalize']
    assert sum(e['type']=='code_execution' for e in done['events']) == 1
    assert 'review_pending' not in done['task_history'][0]


def test_changed_request_does_not_reuse_pending_review(tmp_path):
    store, sid = create(tmp_path)
    base = Model([verified_value(), 'First handoff.'], [decision('mr','propose',execute=True)])
    def failed(**kwargs):
        if kwargs['role']=='evaluate': raise RuntimeError('Service unavailable')
        return base(**kwargs)
    Agent(ROOT,store,model=failed).run(sid,'Original request')
    model = Model([verified_value(43, 'updated'), 'Updated handoff.'],[decision('mr','continue',effective_request='Updated request')])
    done=Agent(ROOT,store,model=model).run(sid,'Here is additional input')
    assert len(calls(model,'mr')) == 2
    assert calls(model,'evaluate')[0]['handoff']['body']=='Updated handoff.'
    assert done['task_history'][0]['request']=='Updated request'


def test_review_format_repair_does_not_reexecute(tmp_path):
    store,sid=create(tmp_path)
    base=Model([verified_value(), 'Ready.'],[decision('mr','propose',execute=True)])
    outputs=iter(['not JSON',json.dumps(dict(route='execute',accept_item=True,reason='Supported.'))])
    contexts=[]
    def model(**kwargs):
        if kwargs['role']=='evaluate':
            contexts.append(json.loads(kwargs['user']))
            return next(outputs)
        return base(**kwargs)
    done=Agent(ROOT,store,model=model).run(sid,'Use the supplied result')
    assert done['status']=='completed' and len(calls(base,'mr'))==2
    assert len(contexts)==2 and contexts[1]['previous_response']=='not JSON'


def test_review_reads_early_tool_records_and_actual_inputs(tmp_path):
    store,sid=create(tmp_path)
    code='''import json
from pathlib import Path
p=Path("qc");p.mkdir()
(p/"response.json").write_text(json.dumps({"outputs":{"status":"ok","gwas_qc_result":{"genome_build":"unknown","ancestry":"mixed"}},"details":{"risk_notes":["Unresolved source scale"]}}))
(p/"gwas_qc_input.json").write_text(json.dumps({"sample_size":12000,"raw_path":"source.tsv"}))
print("QC evidence saved")
from mrcat.tools import publish_result
publish_result("qc", {"path": str((p/"response.json").resolve())})'''
    model=Model([action('skill','gwas-qc'),action('execute',code),
                 *[action('execute',f'print("Later step {i}")') for i in range(4)],'Ready.'],
                [decision('mr','propose',execute=True)])
    Agent(ROOT,store,model=model).run(sid,'Use the supplied QC evidence')
    context=calls(model,'evaluate')[0]
    record=context['tool_records'][0]
    assert 'Unresolved source scale' in record['content']
    assert '12000' in record['inputs']
    assert context['skill_requirements'][0]['skill']=='gwas-qc'
    assert context['execution_count']==5


@pytest.mark.parametrize('kind',['final','ask','evaluate'])
def test_mr_rejects_direct_delivery_and_review_actions(kind):
    with pytest.raises(ValueError,match='MR executor'):
        parse_action(json.dumps(action(kind,'Do something')),role='mr')
    assert parse_action(json.dumps(action('end','Need to change the selected population.',outcome='blocked')),role='mr')['outcome']=='blocked'


def test_summary_projection_and_download_are_task_specific(tmp_path):
    app=create_app(repo_root=ROOT,artifact_dir=tmp_path)
    store=app.state.service.store
    sid=store.create('Analyze supplied results','openai')['session_id']
    answer='## Result\n{{value:r1/value}}\n[Data](workspace/outputs/task1/work_1/answer.txt)\n<script>alert("test")</script>'
    model=Model([action('execute','from pathlib import Path; Path("answer.txt").write_text("42")\nfrom mrcat.tools import publish_result\npublish_result("answer", {"value": int(Path("answer.txt").read_text())})'),'Ready.'],
                [decision('mr','propose',execute=True)],
                evaluations=[dict(route='execute',accept_item=True,reason='Evidence checked.')],
                finalizations=['completed\n'+answer+'\n[END_FINAL_SUMMARY]'])
    Agent(ROOT,store,model=model).run(sid,'Analyze supplied results')
    client=TestClient(app)
    snapshot=client.get(f'/api/sessions/{sid}').json()
    report=snapshot['final_report']
    assert report['summary']=='workspace/outputs/task1/final_summary.md'
    assert '<script>' not in report['html']
    assert '/api/sessions/' in report['html']
    raw=client.get(f'/api/sessions/{sid}/artifacts/raw',params={'summary':report['summary']})
    assert raw.status_code==200 and raw.text.strip()==snapshot['mr']['state']['task_history'][0]['final_summary']
    preview=client.get(f'/api/sessions/{sid}/artifacts/markdown',params={'summary':report['summary']}).json()
    assert preview['html']==report['html']


def test_review_can_execute_replan_or_finalize(tmp_path):
    from mrcat.workflow.mr import mr_graph
    store, sid = create(tmp_path)
    graph = mr_graph(Agent(ROOT, store)).get_graph()
    targets = {e.target for e in graph.edges if e.source == 'evaluate'}
    assert targets == {'prepare_executor', 'recover', 'finalize', 'pause', '__end__'}
    assert not {'executor', 'deliver'} & targets


def test_failed_finalization_retries_only_finalize_across_instances(tmp_path):
    store, sid = create(tmp_path)
    base = Model([action('execute', 'from pathlib import Path; Path("answer.txt").write_text("42")\nfrom mrcat.tools import publish_result\npublish_result("answer", {"value": int(Path("answer.txt").read_text())})'), 'Ready.'],
                 [decision('mr', 'propose', execute=True)])
    def offline(**kwargs):
        if kwargs['role'] == 'finalize':
            raise RuntimeError('Summary service unavailable')
        return base(**kwargs)
    paused = Agent(ROOT, store, model=offline).run(sid, 'Compute the supplied value')
    task = paused['active_task']
    assert paused['status'] == 'paused' and not paused['task_history']
    assert 'review_pending' not in task
    assert task['evaluation']['route'] == 'execute'
    assert task['finalization_pending']['review']['origin'] == 'host'
    assert not (store.directory(sid)/'workspace/outputs/task1/final_summary.md').exists()
    second = Model(decisions=[decision('mr','continue')],
                   finalizations=['completed\n{{value:r1/value}}\n[END_FINAL_SUMMARY]'])
    done = Agent(ROOT, store, model=second).run(sid, 'Continue')
    assert [c['role'] for c in second.calls] == ['manager', 'finalize']
    assert done['status'] == 'completed'
    assert sum(e['type']=='code_execution' for e in done['events']) == 1
    assert 'finalization_pending' not in done['task_history'][0]


def test_changed_request_invalidates_pending_finalization(tmp_path):
    store, sid = create(tmp_path)
    base = Model([verified_value(), 'Old handoff.'], [decision('mr','propose',execute=True)])
    def offline(**kwargs):
        if kwargs['role']=='finalize': raise RuntimeError('Unavailable')
        return base(**kwargs)
    Agent(ROOT,store,model=offline).run(sid,'Old request')
    second=Model([verified_value(43, 'updated'), 'New handoff.'],[decision('mr','continue',effective_request='New request')])
    done=Agent(ROOT,store,model=second).run(sid,'Use the new input')
    assert len(calls(second,'mr')) == 2 and len(calls(second,'evaluate')) == 1
    assert done['task_history'][0]['request']=='New request'
    assert calls(second,'finalize')[0]['handoff']['body']=='New handoff.'


def test_truncated_summary_is_not_published_and_does_not_repeat_review(tmp_path):
    store, sid = create(tmp_path)
    model=Model([verified_value(), 'Ready.'],[decision('mr','propose',execute=True)],
                finalizations=['completed\nThe result is', 'completed\nTruncated again'])
    paused=Agent(ROOT,store,model=model).run(sid,'Compute result')
    assert paused['status']=='paused' and not paused['task_history']
    assert len(calls(model,'evaluate')) == 1
    assert len(calls(model,'finalize')) == 2
    assert not any(e['type']=='final' for e in paused['events'])
    assert 'finalization_pending' in paused['active_task']
    error=next(e for e in paused['events'] if e['type']=='evaluation_failed')
    assert 'finalize summary_format' in error['content']


def test_finalization_can_withhold_success_despite_executor_completion(tmp_path):
    app=create_app(repo_root=ROOT,artifact_dir=tmp_path)
    store=app.state.service.store
    sid=store.create('Analyze study A','openai')['session_id']
    model=Model([verified_value(), 'Done using study B.'],[decision('mr','propose',execute=True)],
                evaluations=[dict(route='finalize',reason='Blocked: B differs from the authorized study A.')],
                finalizations=['blocked\nAnalysis is unfinished. Supply study A; changing to B requires your confirmation.\n[END_FINAL_SUMMARY]'])
    waiting=Agent(ROOT,store,model=model).run(sid,'Analyze study A')
    assert waiting['status']=='waiting_user' and not waiting['task_history']
    assert waiting['pending']['kind']=='clarification'
    task=waiting['active_task']
    assert task['task_id']=='task1' and task['status']=='waiting_user'
    assert not any(e['type']=='final' for e in waiting['events'])
    client=TestClient(app)
    report=client.get(f'/api/sessions/{sid}').json()['final_report']
    assert report['markdown'].strip()==task['final_summary']
    assert 'unfinished' in report['markdown']
    assert '[END_FINAL_SUMMARY]' not in report['markdown']


@pytest.mark.parametrize('route',['continue','recover','ask','stop'])
def test_legacy_mr_review_routes_are_rejected(tmp_path,route):
    store,sid=create(tmp_path)
    model=Model([verified_value(), 'Ready.'],[decision('mr','propose',execute=True)],
                evaluations=[dict(route=route,reason='Legacy route')]*2)
    paused=Agent(ROOT,store,model=model).run(sid,'Compute result')
    assert paused['status']=='paused'
    assert not calls(model,'finalize')
    assert len(calls(model,'mr'))==2
