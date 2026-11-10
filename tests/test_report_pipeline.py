"""End-to-end report parity using actual MRCAT saved results and graph routing."""
from copy import deepcopy
import json
from pathlib import Path
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from mrcat.agent import Agent
from mrcat.state.store import Store, write_json
from mrcat.report.scientific import report_spec_example
from mrcat.web.server import create_app

ROOT = Path(__file__).resolve().parents[1]


def seed(tmp_path, store=None):
    store = store or Store(tmp_path / 'sessions')
    state = store.create('Study exposure and outcome', 'openai')
    sid = state['session_id']
    directory = store.directory(sid)
    plot = directory / 'workspace' / 'forest.png'
    Image.new('RGB', (120, 80), 'white').save(plot)
    outputs = {'mr_primary_result': {'methods': [{'method': 'IVW', 'beta.hat': 0.2, 'se': 0.1, 'pval': 0.04}],
                'input_scale': 'standardize', 'plot_manifest': {'plots': [{'plot_id':'forest','title':'MR estimates','path':str(plot)}]}}}
    write_json(directory / 'workspace/response.json', {'details': {'input_scale': 'standardize', 'pval_threshold': 5e-8}})
    write_json(directory / 'results/task1/fit.json', dict(outputs=outputs,status='ok',execution_id='cell1',producer={'tool':'mr_primary', 'arguments': {'pval_threshold': 5e-8}, 'response_path': str(directory / 'workspace/response.json')}))
    write_json(directory / 'results/task1/qc.json', dict(outputs={'qc': {'rows': 100, 'source':'fixture'}},status='ok',execution_id='cell0'))
    items = [dict(step_id='qc', title='Prepare study', skill_id='gwas-qc', reuse_from=[]),
             dict(step_id='fit', title='Estimate MR', skill_id='mr-primary', reuse_from=[])]
    task = dict(task_id='task1', request='Study exposure and outcome', status='completed', memory='',
                artifacts=[str(plot.relative_to(directory))], plan_items=items, plan='Prepare then estimate',
                completed_items={
                    'qc':dict(item=items[0],outputs={'qc':dict(ref='$ref:qc/qc',execution_id='cell0')},execution_ids=['cell0'],summary='QC completed'),
                    'fit':dict(item=items[1],outputs={'mr_primary_result':dict(ref='$ref:fit/mr_primary_result',execution_id='cell1')},execution_ids=['cell1'],summary='Fit completed')})
    state['task_history'] = [task]
    store.save(state)
    return store, sid


class ReportModel:
    def __init__(self, *, judgements=None, fail_judge=False, numbers=None, literature=False):
        self.calls = []
        self.judgements = iter(judgements or [0])
        self.fail_judge = fail_judge
        self.numbers = iter(numbers or [])
        self.literature = literature

    def __call__(self, **kwargs):
        role = kwargs['role']; self.calls.append(kwargs)
        ctx = json.loads(kwargs['user'])
        if role == 'manager':
            continuing = ctx['latest_request'] == 'Continue report'
            return json.dumps(dict(route='report',action='continue' if continuing else 'run',message=None,
                                   effective_request=None if continuing else ctx['latest_request']))
        if role == 'report_selection':
            return json.dumps(dict(selected_step_refs=['task1/fit'],selection_reason='Report the saved MR result.'))
        if role == 'literature_claims':
            return json.dumps(dict(claims=[dict(claim_id='LC1',claim='Research background',claim_type='background',search_queries=['exposure outcome'])] if self.literature else []))
        if role == 'literature_verify':
            return json.dumps(dict(evaluations=[dict(reference_id='PMID:123',claim_ids=['LC1'],support_grade='background_support',reasoning='Background only.',citation_wording='Prior observational context.')]))
        if role == 'report_writer':
            ids = [x['figure_id'] for x in ctx['Figure Catalog']]
            spec = report_spec_example(ids, reference_ids=ctx['Allowed Reference IDs'])
            spec['abstract'] = 'The estimate was ' + next(self.numbers, '0.2') + '; interpretation remains limited.'
            return json.dumps(spec)
        if role == 'report_judge':
            if self.fail_judge:
                raise RuntimeError('Synthetic Judge outage')
            count = next(self.judgements, 0)
            return json.dumps(dict(decision='revise' if count else 'accept', issues=[
                dict(location='Discussion',problem=f'Unsupported claim {i}',required_change='Use the original evidence.') for i in range(count)]))
        raise AssertionError('Unexpected model role: ' + role)


def report_run(tmp_path, model):
    store, sid = seed(tmp_path)
    before = deepcopy(store.load(sid)['task_history'])
    result = Agent(ROOT, store, model=model).run(sid, 'Write a scientific report')
    return store, sid, before, result


def checkpoint(store, sid):
    return store.load(sid)['report_state']


def test_report_selects_qc_embeds_figures_and_publishes_only_reviewed_report(tmp_path):
    model = ReportModel()
    store, sid, before, result = report_run(tmp_path, model)
    assert result['status'] == 'completed', result['events'][-1]
    data = checkpoint(store,sid)
    assert data['result']['review']['status'] == 'accepted'
    writer = json.loads(next(c['user'] for c in model.calls if c['role'] == 'report_writer'))
    judge = json.loads(next(c['user'] for c in model.calls if c['role'] == 'report_judge'))
    assert 'pval_threshold' in json.dumps(writer['Original Analysis Evidence'])
    assert 'standardize' in json.dumps(judge['Original Analysis Evidence'])
    assert data['progress']['llm_calls'][-1]['status'] == 'validated'
    assert set(data['report_selection']['selected_step_refs']) == {'task1/qc','task1/fit'}
    assert result['task_history'] == before and result['active_task'] is None
    html = next(store.directory(sid).glob('workspace/reports/*/scientific_report.html')).read_text()
    assert 'data:image/png;base64,' in html and '0.2' in html
    assert 'Draft — automated review' not in html
    client = TestClient(create_app(repo_root=ROOT, artifact_dir=store.base))
    snapshot = client.get(f'/api/sessions/{sid}').json()
    assert snapshot['final_report']['summary'].endswith('/final_summary.md')
    assert 'data:image/png;base64,' in snapshot['final_report']['html']
    assert all(name in [c['role'] for c in model.calls] for name in ['report_selection','report_writer','report_judge'])


def test_failed_judge_resumes_only_judge_without_rewriting_analysis_or_draft(tmp_path):
    model = ReportModel(fail_judge=True)
    store,sid,before,result = report_run(tmp_path,model)
    assert result['status'] == 'paused'
    assert checkpoint(store,sid)['next_stage'] == 'judge'
    assert not list(store.directory(sid).glob('workspace/reports/*/scientific_report.html'))
    draft = next(store.directory(sid).glob('workspace/reports/*/scientific_report_draft.html'))
    assert 'Draft — automated review has not passed' in draft.read_text()
    counts = Counter(c['role'] for c in model.calls)
    model.fail_judge = False
    result = Agent(ROOT,store,model=model).run(sid,'Continue report')
    assert result['status'] == 'completed', checkpoint(store,sid).get('error')
    after = Counter(c['role'] for c in model.calls)
    assert after['report_judge'] == counts['report_judge'] + 1
    assert after['report_writer'] == counts['report_writer']
    assert after['report_selection'] == counts['report_selection']
    assert result['task_history'] == before


def test_report_shares_selected_task_memory_without_replacing_results(tmp_path):
    store, sid = seed(tmp_path)
    state = store.load(sid)
    memory = 'The strict threshold retained three instruments; Review relaxed it before the successful fit.'
    state['task_history'][0]['memory'] = memory
    unrelated = deepcopy(state['task_history'][0])
    unrelated.update(task_id='task2', memory='Unrelated investigation context.')
    for name in ['fit', 'qc']:
        source = store.directory(sid) / f'results/task1/{name}.json'
        write_json(store.directory(sid) / f'results/task2/{name}.json', json.loads(source.read_text()))
    state['task_history'].append(unrelated)
    store.save(state)
    before = deepcopy(state['task_history'])
    model = ReportModel()
    result = Agent(ROOT, store, model=model).run(sid, 'Write a scientific report')
    assert result['status'] == 'completed'
    for role in ['report_writer', 'report_judge']:
        context = json.loads(next(c['user'] for c in model.calls if c['role'] == role))
        assert context['Task Memory'] == [dict(task_id='task1', memory=memory)]
        assert 'task_memories' not in context['Original Analysis Evidence']
        estimates = context['Original Analysis Evidence']['mr_evidence']['task_results']
        assert estimates[0]['structured_outputs']['mr_primary_result']['methods'][0]['beta.hat'] == 0.2
    assert result['task_history'] == before


def test_changed_task_memory_restarts_report_instead_of_resuming_stale_judge(tmp_path):
    model = ReportModel(fail_judge=True)
    store, sid, _, result = report_run(tmp_path, model)
    assert result['status'] == 'paused'
    previous_run = checkpoint(store, sid)['run_id']
    state = store.load(sid)
    state['task_history'][0]['memory'] = 'Review adjusted the instrument threshold after insufficient instruments.'
    store.save(state)
    model.fail_judge = False
    result = Agent(ROOT, store, model=model).run(sid, 'Continue report')
    assert result['status'] == 'completed'
    assert checkpoint(store, sid)['run_id'] != previous_run
    assert Counter(c['role'] for c in model.calls)['report_writer'] == 2
    judge = json.loads([c['user'] for c in model.calls if c['role'] == 'report_judge'][-1])
    assert judge['Task Memory'][0]['memory'] == state['task_history'][0]['memory']


@pytest.mark.parametrize('judgements,status,rewrites', [([2,0],'accepted_after_revision',1),
    ([2,2],'last_valid_draft_retained',1),([4,3,2,1],'needs_review',3)])
def test_revision_policy_matches_old_report(tmp_path,judgements,status,rewrites):
    model = ReportModel(judgements=judgements)
    store,sid,_,result = report_run(tmp_path,model)
    assert result['status'] == 'completed', checkpoint(store,sid).get('error')
    review = checkpoint(store,sid)['result']['review']
    assert review['status'] == status and review['revision_attempts'] == rewrites
    assert bool(list(store.directory(sid).glob('workspace/reports/*/scientific_report.html'))) == status.startswith('accepted')


def test_rounded_numbers_reach_judge_without_automatic_rewrite(tmp_path):
    store, sid = seed(tmp_path)
    path = store.directory(sid) / 'results/task1/fit.json'
    saved = json.loads(path.read_text())
    saved['outputs']['mr_primary_result']['methods'][0]['beta.hat'] = 0.063773669925266
    write_json(path, saved)
    model = ReportModel(numbers=['0.064'])
    result = Agent(ROOT, store, model=model).run(sid, 'Write a scientific report')
    data = checkpoint(store, sid)
    assert result['status'] == 'completed'
    assert data['result']['review']['status'] == 'accepted'
    assert sum(c['role'] == 'report_writer' for c in model.calls) == 1
    assert sum(c['role'] == 'report_judge' for c in model.calls) == 1
    judge = json.loads(next(c['user'] for c in model.calls if c['role'] == 'report_judge'))
    assert '0.063773669925266' in json.dumps(judge['Original Analysis Evidence'])
    assert '0.064' in data['draft']['abstract']
    assert data['progress']['writer_rewrite_count'] == 0


def test_judge_feedback_triggers_numeric_revision(tmp_path):
    model = ReportModel(numbers=['1234567', '0.2'], judgements=[1, 0])
    store,sid,_,result = report_run(tmp_path,model)
    data = checkpoint(store, sid)
    assert result['status'] == 'completed'
    roles = [c['role'] for c in model.calls if c['role'] in {'report_writer', 'report_judge'}]
    assert roles == ['report_writer', 'report_judge', 'report_writer', 'report_judge']
    assert data['result']['review']['status'] == 'accepted_after_revision'
    assert data['progress']['writer_rewrite_count'] == 1
    assert '0.2' in data['draft']['abstract']


def test_changed_saved_evidence_restarts_instead_of_resuming_stale_judge(tmp_path):
    model=ReportModel(fail_judge=True)
    store,sid,_,_=report_run(tmp_path,model)
    path=store.directory(sid)/'results/task1/fit.json'
    data=json.loads(path.read_text());data['outputs']['mr_primary_result']['methods'][0]['pval']=0.05
    write_json(path,data)
    model.fail_judge=False
    result=Agent(ROOT,store,model=model).run(sid,'Continue report')
    assert result['status']=='completed'
    assert sum(c['role']=='report_selection' for c in model.calls)==2


def test_revoked_result_is_not_available_for_report(tmp_path):
    store,sid=seed(tmp_path)
    write_json(store.directory(sid)/'results/task1/.invalidated',{'cell1':'Superseded fit'})
    model=ReportModel()
    result=Agent(ROOT,store,model=model).run(sid,'Write a scientific report')
    assert result['status']=='paused'
    assert not any(c['role']=='report_writer' for c in model.calls)


def test_judge_rejects_numeric_revision_without_progress(tmp_path):
    model = ReportModel(judgements=[1, 1], numbers=['0.2', '987654'])
    store, sid, _, result = report_run(tmp_path, model)
    data = checkpoint(store, sid)
    assert result['status'] == 'completed'
    assert data['result']['review']['status'] == 'last_valid_draft_retained'
    assert data['revision_attempts'] == 1
    assert data['revision_history'][0]['reason'] == 'no_progress'
    assert '0.2' in data['draft']['abstract'] and '987654' not in data['draft']['abstract']
    assert sum(c['role'] == 'report_judge' for c in model.calls) == 2


def test_stop_after_export_continues_delivery_without_model_stages(tmp_path, monkeypatch):
    from mrcat.report.stages import ReportStages
    store, sid = seed(tmp_path)
    model = ReportModel()
    export = ReportStages.export
    stop = store.directory(sid) / 'STOP'
    def stop_after_export(self, **kwargs):
        result = export(self, **kwargs)
        stop.touch()
        return result
    monkeypatch.setattr(ReportStages, 'export', stop_after_export)
    paused = Agent(ROOT, store, model=model).run(sid, 'Write a scientific report')
    assert paused['status'] == 'stopped'
    assert checkpoint(store, sid)['next_stage'] == 'deliver'
    before = Counter(c['role'] for c in model.calls)
    stop.unlink()
    done = Agent(ROOT, store, model=model).run(sid, 'Continue report')
    assert done['status'] == 'completed'
    after = Counter(c['role'] for c in model.calls)
    assert after['report_writer'] == before['report_writer']
    assert after['report_judge'] == before['report_judge']
    assert checkpoint(store, sid)['status'] == 'delivered'


def test_custom_result_selection_adds_cross_task_lineage_and_qc(tmp_path):
    from mrcat.report.evidence import session_evidence, select_evidence
    from mrcat.report.agent import ReportAgent
    from mrcat.report.execution import ReportExecution
    store, sid = seed(tmp_path)
    state = store.load(sid)
    item = dict(step_id='synthesis', title='Compare results', skill_id=None,
                reuse_from=['task1/fit/mr_primary_result'])
    write_json(store.directory(sid) / 'results/task2/comparison.json',
               dict(outputs={'estimate': 0.2}, status='unverified', execution_id='custom1'))
    state['task_history'].append(dict(task_id='task2', request='Compare saved results', status='completed', memory='',
        completed_items={'synthesis': dict(item=item, summary='Compared', execution_ids=['custom1'],
            outputs={'comparison': dict(ref='$ref:comparison', execution_id='custom1')})}))
    model = ReportModel()
    native = Agent(ROOT, store, model=model)
    reporter = ReportAgent(native, state)
    reporter.select_session_report_evidence = lambda **kwargs: dict(
        selected_step_refs=['task2/synthesis'], selection_reason='Compare the saved MR result.')
    state['active_agent'] = 'report'
    data = dict(run_id='lineage', available_evidence=session_evidence(state, store.directory(sid)))
    select_evidence(reporter, state, data, ReportExecution(native, state, data))
    assert set(data['report_selection']['selected_step_refs']) == {'task1/qc','task1/fit','task2/synthesis'}
    assert data['report_selection']['required_step_refs_added'] == ['task1/qc']
    assert any(row['skill_id']=='custom' for row in data['report_context']['mr_evidence']['task_results'])


def test_literature_verification_reaches_writer_and_export(tmp_path, monkeypatch):
    from mrcat.report.literature import PubMedLiteratureClient
    monkeypatch.setattr(PubMedLiteratureClient, 'search', lambda *args, **kwargs: [dict(
        reference_id='PMID:123', pmid='123', title='Research context', abstract='Observed association.',
        authors=[], journal='Example', year='2025', doi='', url='https://pubmed.ncbi.nlm.nih.gov/123/', retracted=False)])
    model = ReportModel(literature=True)
    store, sid, _, result = report_run(tmp_path, model)
    assert result['status'] == 'completed'
    data = checkpoint(store, sid)
    assert data['report_context']['literature_evidence']['studies'][0]['support_grade'] == 'background_support'
    writer = json.loads(next(c['user'] for c in model.calls if c['role']=='report_writer'))
    assert writer['Allowed Reference IDs'] == ['PMID:123']
    html = next(store.directory(sid).glob('workspace/reports/*/scientific_report.html')).read_text()
    assert 'id="ref-1"' in html and 'Research context' in html


def test_interrupt_during_judge_preserves_attempt_diagnostics_and_resumes(tmp_path):
    store, sid = seed(tmp_path)
    model = ReportModel()
    interrupted = False
    def interrupt_once(**kwargs):
        nonlocal interrupted
        if kwargs['role'] == 'report_judge' and not interrupted:
            interrupted = True
            raise KeyboardInterrupt('Synthetic worker interruption')
        return model(**kwargs)
    with pytest.raises(KeyboardInterrupt):
        Agent(ROOT, store, model=interrupt_once).run(sid, 'Write a scientific report')
    before = Counter(c['role'] for c in model.calls)
    done = Agent(ROOT, store, model=model).run(sid, 'Continue report')
    data = checkpoint(store, sid)
    assert done['status'] == 'completed'
    assert Counter(c['role'] for c in model.calls)['report_writer'] == before['report_writer']
    assert any(row['stage'] == 'report_judge' and row['status'] == 'interrupted'
               for row in data['progress']['llm_calls'])
    assert data['progress']['resumed'] is True


def test_report_json_repair_preserves_stage_context_and_stops_after_one_repair():
    from types import SimpleNamespace
    from mrcat.report.client import ReporterRoleClient
    calls = []
    responses = iter(['not JSON', '{"claims": []}'])
    def call(state, role, system, user):
        calls.append(json.loads(user))
        return next(responses)
    client = ReporterRoleClient(SimpleNamespace(_call=call), {})
    prompt = dict(stage='literature_claims', system='Read the evidence.', sections={'Evidence': {'beta': 0.2}})
    assert client.extract_literature_claims(prompt=prompt) == {'claims': []}
    assert len(calls) == 2 and calls[1]['Evidence'] == {'beta': 0.2}
    assert calls[1]['previous_response'] == 'not JSON' and calls[1]['format_error']
    responses = iter(['not JSON', 'still not JSON'])
    calls.clear()
    with pytest.raises(ValueError):
        client.extract_literature_claims(prompt=prompt)
    assert len(calls) == 2
