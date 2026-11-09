"""Local deterministic frontend fixture; no external model calls."""
from pathlib import Path
import argparse
import json
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_agent import Model, decision, ROOT, action
from mrcat.agent import Agent
from mrcat.web.server import create_app

parser=argparse.ArgumentParser()
parser.add_argument('--port',type=int,default=18769)
args=parser.parse_args()
app=create_app(repo_root=ROOT,artifact_dir=tempfile.mkdtemp(prefix='mrcat-roles-browser-'))
store=app.state.service.store
proposal=store.create('Plan an MR software test','openai')['session_id']
Agent(ROOT,store,model=Model(decisions=[decision('mr','propose',description='Synthetic MR plan')], plans=['1. Use gwas-qc on each supplied raw study.\n2. Use gwas-pair-prepare on the two QC outputs.\n3. Use mr-cml-ma on the prepared MRdat.'])).run(proposal,'Plan an MR software test')
search=store.create('Find synthetic CAD candidates','openai')['session_id']
search_code = '''import json
from pathlib import Path
from openpyxl import Workbook
p = Path("gwas_search_shortlists.json")
payload = dict(target=dict(kind="trait", value="coronary artery disease"), candidates=[dict(source="opengwas", study_id="fixture-cad", trait="Coronary artery disease", sample_size=10000, ancestry="european", downloadable=True), dict(source="pan_ukb", study_id=None, trait="Supplemental coronary atherosclerosis", sample_size=None, ancestry=None, downloadable=None, study_metadata=dict(phenocode="411.4"))], diagnostics={})
p.write_text(json.dumps(payload))
w = Workbook(); w.active.append(["study_id", "trait"]); w.active.append(["fixture-cad", "Coronary artery disease"]); w.save(p.with_suffix(".xlsx"))
print("2 candidates: fixture-cad and an incomplete supplemental record; files saved.")
'''
Agent(ROOT,store,model=Model([action('execute', search_code), 'Found a synthetic CAD candidate and an incomplete supplemental record.'])).run(search,'Find synthetic CAD candidates')
from test_report_pipeline import seed, ReportModel
_, completed = seed(store.base, store=store)
Agent(ROOT, store, model=ReportModel()).run(completed, 'Write a report from saved results')
blocked=store.create('Analyze the confirmed synthetic study A','openai')['session_id']
Agent(ROOT,store,model=Model([action('end', 'The supplied file identifies study B.', outcome='blocked')],
    [decision('mr','propose',execute=True)],
    evaluations=[dict(route='finalize',reason='Blocked: the supplied input differs from confirmed study A.')],
    finalizations=['blocked\nThe analysis is unfinished. Please supply study A or explicitly authorize a change.\n[END_FINAL_SUMMARY]']
)).run(blocked,'Analyze the confirmed synthetic study A')
notebook = store.create('Synthetic Notebook file provenance', 'openai')
notebook.update(status='completed')
directory = store.directory(notebook['session_id'])
for name, content in [('summary.csv', 'name,value\nA,2\n'),
                      ('report.md', '# Report\nSynthetic data only.')]:
    (directory / 'workspace' / name).write_text(content)
    store.event(notebook, 'code_execution', f'Saved workspace/{name}.',
                execution_id=name, language='python', code='print("Synthetic fixture")',
                stdout='Synthetic fixture', stderr='', status='exited', returncode=0,
                agent='search', generated_files=[f'workspace/{name}'])
Path('/tmp/mrcat-browser-roles.json').write_text(json.dumps({'proposal':proposal,'completed':completed,'search':search,'blocked':blocked,'notebook':notebook['session_id'],'store':str(store.base)}))
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')
