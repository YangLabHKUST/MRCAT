"""Execute source directly; reject ambiguous actions and preserve role boundaries."""
import json
import importlib
from pathlib import Path

import pytest

from mrcat.actions import parse_action
from mrcat import memory
from mrcat.agent import Agent
from test_agent import ROOT, Model, action, create, decision, coding_action, native_reply


@pytest.mark.parametrize('language,body', [('python', 'print("a\\nb", {"x": 1})'), ('r', 'print("quoted value")'), ('bash', "printf '%s\\n' 'hello'")])
def test_unescaped_code_block(language, body):
    parsed = parse_action(f'Check the actual result.\n```{language}\n{body}\n```', role='mr')
    assert parsed == dict(kind='execute', language=language, body=body, message='Check the actual result.')


def test_longer_fence_keeps_literal_markdown_in_code():
    body = 'report = """```python\nprint(42)\n```"""\nprint(report)'
    assert parse_action(f'````python\n{body}\n````', role='mr')['body'] == body


@pytest.mark.parametrize('raw', ['```python\nprint(1)', '```python\n\n```',
    '{"type":"end","outcome":"complete","body":"Done"}\n```python\nprint(1)\n```',
    '```json\n{"type":"end","outcome":"complete","body":"Done"}\n```\n```python\nprint(1)\n```'])
def test_incomplete_or_multiple_actions_never_execute(raw):
    with pytest.raises(ValueError):parse_action(raw, role='mr')


def test_custom_rejected_text_returns_to_native_loop_without_format_repair(tmp_path):
    store,sid=create(tmp_path)
    class RawModel(Model):
        def __call__(self, **kwargs):
            if kwargs['role'] == 'mr':
                self.calls.append(kwargs)
                value = next(self.actions)
                return value if isinstance(value, str) else native_reply(value)
            return super().__call__(**kwargs)
    model=RawModel(['```python\nprint(42)',
        coding_action('execute', 'from pathlib import Path\nPath("answer.txt").write_text("42")\nfrom mrcat.tools import publish_result\npublish_result("answer", {"value": int(Path("answer.txt").read_text())})'),
        coding_action('end', 'Plan complete: answer.txt contains 42.', outcome='complete')],
        [decision('mr','propose',execute=True)])
    result=Agent(ROOT,store,model=model).run(sid,'Write answer.txt with 42.')
    assert result['status']=='completed'
    assert (store.directory(sid)/'workspace/outputs/task1/work_1/answer.txt').read_text()=='42'
    assert sum(e['type']=='code_execution' for e in result['events'])==1
    assert sum(c['role']=='evaluate' for c in model.calls)==1
    assert sum(c['role']=='planner' for c in model.calls)==1


def test_fenced_history_compacts_old_source_and_retains_latest():
    messages=[]
    for i in range(2):
        messages.extend([dict(role='assistant',agent='mr',content=f'Check {i}.\n```python\nprint("CODE_{i}")\n```'),
            dict(role='observation',agent='mr',content=json.dumps(dict(execution_id=str(i),status='exited',returncode=0,
                source_path=f'executions/{i}/code.py',stdout_path=f'executions/{i}/stdout.log',stderr_path=f'executions/{i}/stderr.log',stdout='ok',stderr='')))])
    visible=memory.recent_messages(messages,role='mr')
    assert 'CODE_0' not in visible[0]['content']
    assert 'Check 0' in visible[0]['content']
    assert 'executions/0/code.py' in visible[1]['content']
    assert 'CODE_1' in visible[2]['content']


def test_catalog_merges_ontology_even_when_reported_trait_has_hits(monkeypatch):
    module=importlib.import_module('skills.gwas-search.scripts.search_gwas_catalog')
    searcher=module.GWASCatalogSearcher(); calls=[];cache=[]
    monkeypatch.setattr(searcher,'cached_json_get',lambda *args:(False,None))
    monkeypatch.setattr(searcher,'cached_json_set',lambda *args:cache.append(args))
    def pages(**filters):
        calls.append(filters)
        if 'disease_trait' in filters:return [dict(accession_id='A',full_summary_stats_available=False)]
        return [dict(accession_id='A',full_summary_stats_available=False),dict(accession_id='B',full_summary_stats_available=True)]
    monkeypatch.setattr(searcher,'_study_pages',pages)
    rows=searcher._search_studies('example trait')
    assert [r['accession_id'] for r in rows]==['A','B']
    assert calls==[dict(disease_trait='example trait'),dict(efo_trait='example trait',show_child_traits='false')]
    assert cache[0][-1]==rows


def test_multiple_blocks_are_rejected_before_any_execution():
    raw = ('Prepare the value.\n```python\nx = 40\n```\nSave it.\n'
           '```python\nfrom pathlib import Path\nPath("answer.txt").write_text(str(x + 2))\nprint(x + 2)\n```\nWait for the actual observation.')
    with pytest.raises(ValueError, match='exactly one final executable code block'):
        parse_action(raw, role='mr')


@pytest.mark.parametrize('raw', [
    '```python\nprint(1)\n```\n```bash\necho 2\n```',
    '```python\nprint(1)\n```\n```python\nprint(2)',
    '```python\nprint(1)\n```\n{"type":"end","body":"Done","outcome":"complete"}',
])
def test_ambiguous_or_truncated_reply_is_atomic(raw):
    with pytest.raises(ValueError):
        parse_action(raw, role='mr')


def test_native_coding_uses_tool_result_for_argument_correction(tmp_path):
    from test_coding_graph import CodingModel
    store, sid = create(tmp_path)
    model = CodingModel([
        dict(tool='run', language='python', content='print(42)', extra='invalid'),
        coding_action('execute', 'from mrcat.tools import publish_result; publish_result("answer", {"value":40+2})'),
        coding_action('end', 'Computed 42.', outcome='complete')],
        decisions=[decision('mr', 'propose', execute=True)])
    done = Agent(ROOT, store, model=model).run(sid, 'Compute 42.')
    calls = [c for c in model.calls if c['role'] == 'mr']
    assert done['status'] == 'completed' and len(calls) == 3
    assert 'unexpected tool arguments' in json.loads(calls[1]['user'])['action_history'][-1]['content']
    assert all(c['system'] == calls[0]['system'] for c in calls)
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 1


def test_custom_tool_failure_with_zero_exit_keeps_local_repair_evidence(tmp_path):
    store, sid = create(tmp_path)
    code = ('from pathlib import Path\nimport json\n'
            'Path("response.json").write_text(json.dumps({"outputs":{"status":"blocked"},'
            '"details":{"message":"Missing documented input"}}))\nprint("saved failure")')
    model = Model([action('execute', code), action('execute', 'from mrcat.tools import publish_result\nvalues=[2,4,6]\npublish_result("answer", {"mean": sum(values)/len(values)})'),
                   action('end', 'Operation repaired.', outcome='complete')],
                  [decision('mr', 'propose', execute=True)])
    done = Agent(ROOT, store, model=model).run(sid, 'Process the supplied data.')
    calls = [json.loads(c['user']) for c in model.calls if c['role'] == 'mr']
    repair = calls[1]
    from test_custom_codeact import execution_evidence
    evidence = execution_evidence(repair)
    assert evidence[-1]['code'] == code
    observation = evidence[-1]
    assert observation['returncode'] == 0
    assert observation['tool_results'][0]['status'] == 'blocked'
    assert repair['action_history'] and 'current_item' in repair
    assert evidence[0]['tool_results'][0]['status'] == 'blocked'
    assert sum(c['role'] == 'evaluate' for c in model.calls) == 1
    assert done['status'] == 'completed'


def test_archived_draft_and_replacement_are_rejected():
    raw = (ROOT / 'tests/fixtures/executor_draft_replacement.txt').read_text()
    assert raw.count('result = gwas_qc(') == 2
    with pytest.raises(ValueError, match='exactly one final executable code block'):
        parse_action(raw, role='mr')


def test_native_commentary_is_never_executed(tmp_path):
    from test_agent import native_reply
    store, sid = create(tmp_path)
    base = Model(decisions=[decision('mr', 'propose', execute=True)])
    source = ('from pathlib import Path\np=Path("calls.txt")\np.write_text("called")\n'
              'from mrcat.tools import publish_result\npublish_result("answer", {"count":1})')
    response = json.loads(native_reply(dict(tool='run', content=source)))
    response['content'] = '```python\nraise RuntimeError("unused draft")\n```'
    replies = iter([json.dumps(response), native_reply(dict(tool='finish', outcome='complete', body='Verified once'))])
    def model(**kwargs):
        return next(replies) if kwargs.get('tools') else base(**kwargs)
    done = Agent(ROOT, store, model=model).run(sid, 'Run the operation once.')
    assert done['status'] == 'completed'
    cells = [e['details'] for e in done['events'] if e['type'] == 'code_execution']
    assert len(cells) == 1 and cells[0]['code'] == source


@pytest.mark.parametrize('role', ['search'])
@pytest.mark.parametrize('repair', ['UNRECOVERABLE', '', '```python\nprint(1)\n```\n```python\nprint(2)\n```'])
def test_failed_format_repair_pauses_without_evaluate_and_retains_results(tmp_path, role, repair):
    store, sid = create(tmp_path)
    first = 'from pathlib import Path\nPath("saved.txt").write_text("preserved")'
    bad = '```python\nprint("draft")\n```\n```python\nprint("replacement")\n```'
    raw = iter([json.dumps(coding_action('execute', first)) if role == 'mr' else f'```python\n{first}\n```', bad, repair])
    base = Model(decisions=[decision(role, 'propose' if role == 'mr' else 'run', execute=True)])
    calls = []
    def model(**kwargs):
        if kwargs['role'] == role:
            calls.append(kwargs)
            return next(raw)
        return base(**kwargs)
    done = Agent(ROOT, store, model=model).run(sid, 'Save the result, then inspect it.')
    assert done['status'] == 'paused'
    assert len(calls) == 3  # One successful operation, one rejected reply, one repair.
    assert (store.directory(sid) / ('workspace/outputs/task1/work_1/saved.txt' if role == 'mr' else 'workspace/saved.txt')).read_text() == 'preserved'
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 1
    assert not any(c['role'] in {'evaluate', 'finalize'} for c in base.calls)
    rejected = [json.loads(m['content']) for m in done['messages']
                if m['role'] == 'observation' and '"action_rejected"' in m['content']]
    assert len(rejected) == 2 and all(r['applied'] is False for r in rejected)
    assert not done['task_history']
    if role == 'mr':
        assert done['active_task']['status'] == 'paused'
        assert len(done['active_task']['plan_history']) == 1
        assert 'review_pending' not in done['active_task']


def test_single_block_still_supports_multiple_steps(tmp_path):
    from mrcat.execution import CodeExecutor
    raw = ('```python\nfrom pathlib import Path\nx = 40\n'
           'Path("answer.txt").write_text(str(x + 2))\nprint(x + 2)\n```')
    parsed = parse_action(raw, role='mr')
    result = CodeExecutor(ROOT, tmp_path).execute(parsed['body'], parsed['language'], 'singleblock')
    assert result['returncode'] == 0 and result['stdout'].strip() == '42'
    assert (tmp_path / 'workspace/answer.txt').read_text() == '42'
