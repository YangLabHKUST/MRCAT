"""Search migration: real tool boundaries with deterministic provider/HTTP fixtures."""
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from mrcat import tools
from mrcat.search import web, documents, inspection, providers
from mrcat.search.types import SearchResponse, SearchRequest
from mrcat.search.contracts import BRIEF_REQUIRED_HEADINGS, validate_brief_payload
from mrcat.results import result_catalog, read_reference
from test_agent import ROOT, Model, action, create
from mrcat.agent import Agent


class Provider:
    def __init__(self, name, calls, error=None):
        self.name, self.calls, self.error = name, calls, error

    def search(self, request, trace_sink=None):
        self.calls.append((self.name, request))
        if self.error:
            raise self.error
        return SearchResponse('Source reports beta=0.10, CI 0.02–0.18, P=0.01. [C1]',
                              [dict(citation_id='C1', title='Study', url='https://example.org/study')],
                              [request.query], self.name, 'fixture-model', {'total_tokens': 8}, {'answer': 'raw'})


def test_provider_fallback_retains_attempts_citations_and_native_refs(tmp_path, monkeypatch):
    store, sid = create(tmp_path / 'sessions')
    session = store.directory(sid)
    monkeypatch.setenv('MRCAT_SESSION_DIR', str(session))
    monkeypatch.setenv('MRCAT_RESULT_SCOPE', 'search_scope')
    calls = []
    error = providers.WebSearchNoTextError('No synthesis', raw_response={'tool': 'only'}, output_item_types=['tool'], provider='deepseek')
    monkeypatch.setattr(web, 'build_provider_registry', lambda: {
        'deepseek': Provider('deepseek', calls, error), 'openai': Provider('openai', calls)})
    response = tools.web_search(query='BMI to CAD; only FinnGen', context='European population', output_dir=tmp_path / 'out')
    outputs = response['outputs']
    assert [v[0] for v in calls] == ['deepseek', 'openai']
    assert calls[0][1] == calls[1][1]
    assert outputs['provider'] == 'openai' and outputs['usage']['total_tokens'] == 8
    assert outputs['citations'][0]['id'].startswith('search_')
    assert outputs['citations'][0]['citation_id'] == 'C1'
    assert json.loads((tmp_path / 'out/deepseek_error.json').read_text())['raw_response'] == {'tool': 'only'}
    refs = result_catalog(session, 'search_scope')
    assert len(refs) == 1
    stored = next((session / 'results/search_scope').glob('*.json'))
    reference = '$taskref:search_scope/' + stored.stem + '/search_path'
    assert read_reference(session, 'task1', reference) == outputs['search_path']
    assert json.loads(Path(outputs['search_path']).read_text())['answer'] == outputs['answer']
    assert 'status' in json.loads((tmp_path / 'out/response.json').read_text())['outputs']


@pytest.mark.parametrize('provider,fallback,expected', [('deepseek', True, ['deepseek','openai']),
    ('deepseek', False, ['deepseek']), ('openai', True, ['openai']), ('qwen', True, ['qwen'])])
def test_failed_search_does_not_become_empty_evidence(tmp_path, monkeypatch, provider, fallback, expected):
    calls=[]
    monkeypatch.setattr(web, 'build_provider_registry', lambda: {name: Provider(name, calls, RuntimeError('offline')) for name in ['deepseek','openai','qwen']})
    response = tools.web_search(query='Evidence', provider=provider, fallback=fallback, output_dir=tmp_path)
    assert [v[0] for v in calls] == expected
    assert response['outputs']['status'] == 'failed'
    assert 'answer' not in response['outputs']
    assert len(json.loads((tmp_path / 'attempts.json').read_text())) == len(expected)


@pytest.mark.parametrize('provider_type', [providers.OpenAIWebSearchProvider, providers.QwenWebSearchProvider])
def test_hosted_provider_request_citations_and_usage(monkeypatch, provider_type):
    usage=[]; requests=[]
    raw=dict(output=[dict(type='web_search_call', action={'queries':['exact query']}),
        dict(type='message', content=[dict(type='output_text', text='Evidence', annotations=[dict(type='url_citation', title='Paper', url='https://example.org/paper')])])], usage={'input_tokens':7,'output_tokens':3})
    reply=SimpleNamespace(output_text='Evidence', model='fixture', model_dump=lambda:raw)
    def call(**kwargs):
        requests.append(kwargs)
        return reply
    monkeypatch.setattr(providers, 'record_llm_usage', usage.append)
    provider=provider_type(client=SimpleNamespace(responses=SimpleNamespace(create=call)))
    response=provider.search(SearchRequest('exact query','goal',[]))
    assert requests[0]['tools']==[{'type':'web_search'}]
    assert response.queries==['exact query'] and response.citations[0]['url']=='https://example.org/paper'
    assert usage==[raw['usage']]
    reply.output_text=''; raw['output']=[]
    with pytest.raises(providers.WebSearchNoTextError): provider.search(SearchRequest('q','',[]))
    assert len(usage)==2  # Failed synthesis still consumed provider tokens.


class HTTPResponse:
    def __init__(self, url, status=200, body=b'', headers=None):
        self.url, self.status_code, self.body = url, status, body
        self.headers = headers or {}
        self.encoding='utf-8'
        self.is_redirect=status in {301,302,303,307,308}
        self.is_permanent_redirect=status in {301,308}
        self.closed=False
    def __enter__(self): return self
    def __exit__(self,*args): self.closed=True
    def iter_content(self,chunk_size):
        for i in range(0,len(self.body),chunk_size): yield self.body[i:i+chunk_size]


def fake_http(monkeypatch, responses):
    calls=[]
    class Session:
        def __init__(self): self.headers={}
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def request(self,method,url,**kwargs):
            calls.append((method,url,kwargs))
            return responses[len(calls)-1]
    monkeypatch.setattr(inspection.requests,'Session',Session)
    monkeypatch.setattr(inspection.socket,'getaddrinfo',lambda host,port:[(None,None,None,None,('8.8.8.8' if host!='localhost' else '127.0.0.1',port))])
    return calls


def test_inspection_bounds_ignored_range_and_closes_responses(tmp_path, monkeypatch):
    url='https://example.org/file.tsv.gz'
    response=HTTPResponse(url,body=b'a'*400000)
    calls=fake_http(monkeypatch,[response])
    out=tools.web_open(url=url,operation='range',end=9999999,output_dir=tmp_path)['outputs']
    assert out['bytes_read']==262144 and out['truncated'] is True
    assert calls[0][2]['headers']=={'Range':'bytes=0-262143'} and response.closed
    assert json.loads(Path(out['inspection_path']).read_text())['status_code']==200


@pytest.mark.parametrize('target', ['http://example.org/page','https://localhost/page','https://user:pass@example.org/page'])
def test_invalid_redirect_blocked_before_second_request(monkeypatch,target):
    first=HTTPResponse('https://example.org/page',302,headers={'location':target})
    calls=fake_http(monkeypatch,[first])
    with pytest.raises(ValueError): inspection._request(first.url)
    assert len(calls)==1 and first.closed


def test_official_redirect_cannot_escape_explicit_source(tmp_path, monkeypatch):
    first=HTTPResponse('https://api.opengwas.io/api/gwasinfo',302,headers={'location':'https://www.ebi.ac.uk/gwas/studies'})
    calls=fake_http(monkeypatch,[first])
    with pytest.raises(ValueError,match='outside'):
        tools.http_inspect(url=first.url,source='opengwas',output_dir=tmp_path)
    assert len(calls)==1


def test_http_error_and_truncated_json_are_not_success(tmp_path, monkeypatch):
    fake_http(monkeypatch,[HTTPResponse('https://example.org/a',403,body=b'denied')])
    assert tools.web_open(url='https://example.org/a',output_dir=tmp_path)['outputs']['status']=='failed'
    fake_http(monkeypatch,[HTTPResponse('https://example.org/a',body=b'{"key":1234}')])
    with pytest.raises(ValueError,match='exceeds'):
        tools.web_open(url='https://example.org/a',operation='json',max_bytes=4,output_dir=tmp_path)


def candidate():
    return dict(source='opengwas', study_id='ieu-a-2', ancestry='european', trait='BMI',
                study_metadata={'original':'preserved'},downloadable=None)


def test_native_gwas_probe_preserves_full_objects(tmp_path, monkeypatch):
    sources=inspection._sources(); received=[]
    class Searcher:
        def probe_candidates(self, rows, **kwargs):
            received.append(deepcopy(rows))
            return [dict(r,downloadable=True) for r in rows]
    monkeypatch.setitem(sources.SEARCHERS,'opengwas',Searcher)
    item=candidate()
    out=tools.gwas_probe(candidates=[item],source='opengwas',ancestry='european',study_id='ieu-a-2',output_dir=tmp_path)['outputs']
    assert received==[[item]] and out['candidates'][0]['study_metadata']==item['study_metadata']
    assert item['downloadable'] is None


@pytest.mark.parametrize('kwargs', [dict(source='finngen',ancestry='east_asian'),
    dict(source='opengwas',study_id='ieu-a-7'),dict(source='pan_ukb'),dict(source='opengwas',ancestry='african')])
def test_gwas_probe_rejects_constraint_changes_before_network(tmp_path, monkeypatch, kwargs):
    monkeypatch.setattr(inspection.requests,'Session',lambda:pytest.fail('Unexpected network access'))
    with pytest.raises(ValueError): tools.gwas_probe(candidates=[candidate()], output_dir=tmp_path, **kwargs)


def external_candidate():
    return dict(source='published_gwas',study_id='observed-accession',data_kind='gwas_summary_statistics',
                study_metadata={'provenance_url':'https://example.org/study','sample_size':1234},
                download_url='https://example.org/data.tsv.gz',ancestry=None)


def test_external_probe_keeps_metadata_and_rejects_non_gwas(tmp_path,monkeypatch):
    item=external_candidate()
    fake_http(monkeypatch,[HTTPResponse(item['download_url'],headers={'content-type':'application/gzip'})])
    out=tools.web_probe(candidate=item,output_dir=tmp_path)['outputs']['candidate']
    assert out['downloadable'] is True and out['ancestry'] is None
    assert out['study_metadata']==item['study_metadata'] and out['download_descriptor']['url']==item['download_url']
    item['data_kind']='eqtl'
    with pytest.raises(ValueError,match='data_kind'): tools.web_probe(candidate=item,output_dir=tmp_path)


def test_html_login_is_not_downloadable(tmp_path,monkeypatch):
    item=external_candidate()
    fake_http(monkeypatch,[HTTPResponse(item['download_url'],headers={'content-type':'text/html'})])
    out=tools.web_probe(candidate=item,output_dir=tmp_path)['outputs']
    assert out['status']=='failed' and 'candidate' not in out


def brief():
    return dict(markdown='# Search Brief\n\n'+'\n\n'.join('## '+h+'\nNot reported' for h in BRIEF_REQUIRED_HEADINGS),
                pipeline_queries=['Use FinnGen European BMI -> CAD with cML-MA; p < 5e-8.'])


def design():
    return dict(markdown='# Proposed design\nBMI to CAD',scan_design=dict(exposure_list=[dict(trait='BMI',aliases=[])],
        outcome_list=[dict(trait='CAD',aliases=['coronary artery disease'])],rationale='Supplied evidence',citations=['search_fixture_c1']))


def test_brief_and_scan_use_evidence_and_keep_constraints(tmp_path,monkeypatch):
    requests=[]
    def call(**kwargs):
        requests.append(kwargs)
        output=brief() if 'pipeline_queries' in kwargs['example'] else design()
        kwargs['trace_sink']('llm_prompt',{'user':kwargs['user']})
        return kwargs['validator'](output)
    monkeypatch.setattr(documents,'call_validated_json',call)
    evidence={'answer':'beta=0.10, CI 0.02–0.18, P=0.01; source says significant',
              'citations':[dict(id='search_fixture_c1',url='https://example.org/paper')]}
    evidence_path=tmp_path/'search.json'; evidence_path.write_text(json.dumps(evidence))
    request='Only FinnGen; European; BMI -> CAD; cML-MA; p < 5e-8; exclude study X.'
    for function in [tools.research_brief,tools.scan_design]:
        out=function(request=request,evidence=[str(evidence_path)],output_dir=tmp_path/function.__name__)['outputs']
        assert Path(out['markdown_path']).read_text()==out['markdown']
        assert json.loads(Path(out['artifact_path']).read_text())['request']==request
        actual=json.loads(requests[-1]['user'])
        assert actual['evidence'][0]['content']==evidence and actual['request']==request
        assert (Path(out['artifact_path']).parent/'trace.jsonl').exists()
    assert 'PHENOME_SCAN' in out['pipeline_queries'][0] and request in out['pipeline_queries'][0]
    assert 'method=baseline' not in out['pipeline_queries'][0]
    assert len(requests)==2


def test_scan_unknown_citation_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(documents,'call_validated_json',lambda **kwargs:kwargs['validator'](design()))
    with pytest.raises(ValueError,match='unknown sources'):
        tools.scan_design(request='BMI -> CAD',evidence=[],output_dir=tmp_path)
    assert not (tmp_path/'scan_design.json').exists()


def test_brief_requires_legacy_sections():
    with pytest.raises(ValueError,match='heading'): validate_brief_payload(dict(markdown='# Empty',pipeline_queries=[]))
    bad=brief(); bad['markdown']+='\n## Pipeline Queries\nShould be structured'
    with pytest.raises(ValueError,match='must not include'): validate_brief_payload(bad)


def test_focused_document_json_repair_is_bounded_and_audited(tmp_path,monkeypatch):
    from mrcat.model import llm_gateway
    calls=[]
    def model(**kwargs):
        calls.append(kwargs)
        return '{}' if len(calls)==1 else json.dumps(brief())
    monkeypatch.setattr(llm_gateway,'call_text',model)
    tools.research_brief(request='Prepare a brief; only FinnGen',evidence=[],output_dir=tmp_path)
    assert len(calls)==2
    log=(tmp_path/'trace.jsonl').read_text()
    assert 'llm_parse_error' in log and 'llm_prompt' in log


def test_search_tools_execute_in_single_native_loop_and_survive_reload(tmp_path):
    store,sid=create(tmp_path/'sessions')
    code='''from mrcat import tools
from mrcat.search import documents
import json
def fixture(**kwargs):
    return kwargs['validator'](%r)
documents.call_validated_json = fixture
r = tools.research_brief(request="Only FinnGen European BMI -> CAD", evidence=[])
print(json.dumps(r, ensure_ascii=False))
''' % brief()
    model=Model([action('execute',code), 'Brief is saved; review the proposed query.'])
    done=Agent(ROOT,store,model=model).run(sid,'Build a research brief from current evidence')
    assert done['status']=='completed' and done['active_task'] is None
    assert sum(c['role']=='search' for c in model.calls)==2
    assert not any(c['role'] in {'planner','search_decide','data_search_agent'} for c in model.calls)
    cells=[e['details'] for e in done['events'] if e['type']=='code_execution']
    assert len(cells)==1 and cells[0]['returncode']==0, cells
    assert cells[0]['result_refs']
    assert any(p.endswith('/research_brief.json') for p in cells[0]['generated_files'])
    from fastapi.testclient import TestClient
    from mrcat.web.server import create_app
    client=TestClient(create_app(repo_root=ROOT,artifact_dir=store.base))
    path=next(p for p in cells[0]['generated_files'] if p.endswith('/research_brief.json'))
    saved=client.get(f'/api/sessions/{sid}/artifacts/raw',params={'summary':path})
    assert saved.status_code==200 and saved.json()['pipeline_queries']==brief()['pipeline_queries']


def test_deepseek_hosted_search_keeps_citations_and_bounded_uses(monkeypatch):
    calls=[]; usage=[]
    content=[SimpleNamespace(type='server_tool_use',input={'query':'exact study'}),
             SimpleNamespace(type='text',text='Evidence C1',citations=[SimpleNamespace(url='https://example.org/study',title='Study')])]
    message=SimpleNamespace(content=content,model='deepseek-fixture',usage={'input_tokens':5,'output_tokens':2})
    class Stream:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def __iter__(self):return iter([SimpleNamespace(type='content_block_start',content_block=v) for v in content])
        def get_final_message(self):return message
    def stream(**kwargs):
        calls.append(kwargs)
        return Stream()
    monkeypatch.setattr(providers,'record_llm_usage',usage.append)
    provider=providers.DeepSeekWebSearchProvider(client=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    response=provider.search(SearchRequest('Find exact study','',[]))
    assert calls[0]['tools'][0]['max_uses']==3
    assert response.queries==['exact study'] and response.citations[0]['url']=='https://example.org/study'
    assert usage==[message.usage]
    message.content=[]
    with pytest.raises(providers.WebSearchNoTextError):provider.search(SearchRequest('q','',[]))
    assert len(usage)==2


def test_search_tools_import_and_build_documents_in_existing_sandbox(tmp_path):
    from mrcat import sandbox
    import subprocess
    import sys
    command, env, _ = sandbox.prepare_worker(ROOT, tmp_path, [])
    code=f'''
from pathlib import Path
from mrcat import tools
from mrcat.search import documents, inspection, providers
def fixture(**kwargs):
    return kwargs['validator']({brief()!r})
documents.call_validated_json=fixture
out=tools.research_brief(request='Only FinnGen European BMI to CAD', evidence=[], output_dir=Path.cwd()/'brief')['outputs']
assert Path(out['artifact_path']).is_file()
assert inspection._route(dict(source='opengwas', ancestry='european'))['sources']==['opengwas']
assert set(providers.build_provider_registry())=={{'deepseek','openai','qwen'}}
assert not Path({str(ROOT.parent/'MRCAT')!r}).exists()
print('native-search-sandbox-ok')
'''
    completed=subprocess.run(command+[sys.executable,'-c',code],env=env,capture_output=True,text=True,timeout=45)
    assert completed.returncode==0, completed.stdout+completed.stderr
    assert 'native-search-sandbox-ok' in completed.stdout
