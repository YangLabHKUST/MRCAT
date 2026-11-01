"""Native Search artifacts served by the real frontend; no remote model calls."""
import argparse
import json
from pathlib import Path
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_agent import ROOT, Model, action
from test_search_capabilities import brief, design
from mrcat.agent import Agent
from mrcat.web.server import create_app

parser=argparse.ArgumentParser()
parser.add_argument('--port',type=int,default=18771)
args=parser.parse_args()
app=create_app(repo_root=ROOT,artifact_dir=tempfile.mkdtemp(prefix='mrcat-search-documents-'))
store=app.state.service.store
scan=design()
scan['scan_design']['exposure_list'].append(dict(trait='LDL cholesterol',aliases=['LDL-C']))
scan['scan_design']['outcome_list'].append(dict(trait='Stroke',aliases=['cerebrovascular stroke']))
answer='''# Search Findings
## 1. Primary Mendelian Randomization Evidence
- Fixture study reports beta=0.10, CI 0.02–0.18, P=0.01 [C1].
## 2. Supporting Genetic and Contextual Evidence
- Observational evidence provides context [C2].
## 3. GWAS Data Resources
- [FinnGen](https://www.finngen.fi/) is an available resource.
## 4. Limitations and Evidence Gaps
- Sample overlap was not reported.
## 5. Recommended MR Analysis Plan
Review the candidate design before planning an analysis.
'''
code='''from mrcat import tools
from mrcat.search import documents, web
from mrcat.search.types import SearchResponse
import json
def fixture(**kwargs):
    return kwargs['validator'](%r if 'pipeline_queries' in kwargs['example'] else %r)
documents.call_validated_json=fixture
class Provider:
    def search(self, request, trace_sink=None):
        citations=[dict(citation_id='C'+str(i),title='Source '+str(i),url='https://example.org/study/'+str(i)) for i in range(1,8)]
        citations.append(dict(citation_id='C8', title='<img src=x onerror=alert(1)>',url='javascript:alert(1)'))
        return SearchResponse(%r,citations,[request.query],'openai','fixture',{},dict(answer='saved raw response'))
web.build_provider_registry=lambda:dict(openai=Provider())
print(json.dumps(tools.web_search(query='BMI and LDL cholesterol to CAD and Stroke',provider='openai',output_dir='outputs/web')))
evidence=[dict(answer="Synthetic fixture evidence", citations=[dict(id="search_fixture_c1",url="https://example.org/paper")])]
for tool in [tools.research_brief,tools.scan_design]:
    print(json.dumps(tool(request="Only FinnGen European BMI and LDL cholesterol -> CAD and Stroke; cML-MA; p < 5e-8; exclude study X", evidence=evidence,output_dir='outputs/'+tool.__name__)))
''' % (brief(),scan,answer)
sessions=[]
for _ in range(2):
    sid=store.create('Prepare Search evidence, brief and scan design','openai')['session_id']
    done=Agent(ROOT,store,model=Model([action('execute',code),'Review the saved evidence and proposed scan design.'])).run(sid,'Prepare Search evidence, brief and scan design')
    assert done['status']=='completed'
    sessions.append(sid)
Path('/tmp/mrcat-search-documents-browser.json').write_text(json.dumps(dict(session=sessions[0],other=sessions[1],store=str(store.base))))
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')
