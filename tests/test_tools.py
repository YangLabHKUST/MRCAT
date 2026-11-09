"""Exercise the public Python tool interface, artifacts and scientific choices."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from mrcat import tools
from mrcat.agent import Agent
from mrcat.store import Store

ROOT = Path(__file__).resolve().parents[1]


def forbid_model(*args, **kwargs):
    raise AssertionError("A deterministic tool must not call an internal LLM")


@pytest.mark.parametrize("count", [0, 1])
def test_search_terms_are_agent_owned_and_artifacts_remain_compatible(tmp_path, monkeypatch, count):
    from mrcat.model import llm_gateway
    monkeypatch.setattr(llm_gateway, "call_text", forbid_model)
    monkeypatch.setattr(llm_gateway, "call_validated_json", forbid_model)
    orchestrator = importlib.import_module("skills.gwas-search.scripts.search_orchestrator")
    calls = []
    candidate = {"source": "opengwas", "study_id": "example-cad", "trait": "Coronary artery disease",
                 "ancestry": "european", "sample_size": 10000, "downloadable": True,
                 "download_descriptor": {"source": "opengwas", "study_id": "example-cad", "status": "ready", "method": "url", "url": "https://example.invalid/cad.tsv"}}
    def search(**kwargs):
        calls.append(kwargs)
        return dict(candidates=[candidate] if count else [], raw_results=[], source_timings={},
                    source_reports=[dict(source="opengwas", status="ok" if count else "empty")])
    monkeypatch.setattr(orchestrator, "_search_trait_once", search)
    from fastapi.testclient import TestClient
    from mrcat.web.server import create_app
    app = create_app(repo_root=ROOT, artifact_dir=tmp_path / "sessions")
    service = app.state.service
    sid = service.store.create("CAD search", "openai")["session_id"]
    session_dir = service.store.directory(sid)
    cell_dir = session_dir / "workspace/outputs/cell"
    monkeypatch.setenv("MRCAT_EXECUTION_DIR", str(cell_dir))
    response = tools.gwas_search(trait="coronary artery disease", source="opengwas", aliases=["coronary heart disease"])
    assert len(calls) == 1  # Empty results do not start a hidden refinement loop.
    assert calls[0]["query"] == "coronary artery disease"
    assert calls[0]["aliases"] == ["coronary heart disease"]
    saved = next(cell_dir.glob("*/gwas_search_shortlists.json"))
    assert len(json.loads(saved.read_text())["candidates"]) == count
    assert saved.with_suffix(".xlsx").is_file()
    assert (saved.parent / "gwas_search_raw.json").is_file()
    assert json.loads((saved.parent / "response.json").read_text()) == response
    assert os.environ["MRCAT_EXECUTION_DIR"] == str(cell_dir)
    client = TestClient(app)
    snapshot = client.get(f"/api/sessions/{sid}").json()
    relative = str(saved.relative_to(session_dir))
    files = snapshot["mr"]["manifest"]["runs"][sid]["artifacts"]["files"]
    assert relative in files
    raw = client.get(f"/api/sessions/{sid}/artifacts/raw", params={"summary": relative})
    assert len(raw.json()["candidates"]) == count
    workbook = client.get(f"/api/sessions/{sid}/artifacts/spreadsheet",
                          params={"summary": str(saved.with_suffix(".xlsx").relative_to(session_dir))})
    assert workbook.status_code == 200 and workbook.json()["sheets"]


def test_search_and_download_helpers_do_not_collide():
    search = importlib.import_module("skills.gwas-search.scripts.run_search")
    download = importlib.import_module("skills.gwas-download.scripts.run_download")
    assert search.write_json.__module__ == "skills.gwas-search.scripts.common"
    assert download.resolve_output_dir.__module__ == "skills.gwas-download.scripts.common"


def test_repeated_calls_preserve_outputs_and_restore_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("MRCAT_EXECUTION_DIR", str(tmp_path))
    method = importlib.import_module("skills.mr-divw.scripts.run_mr_divw")
    received = []
    def run(payload):
        received.append(payload)
        Path(os.environ["MRCAT_EXECUTION_DIR"], "estimate.tsv").write_text("beta\n0.2\n")
        return {"outputs": {"status": "ok"}, "summary": "fixture"}
    monkeypatch.setattr(method, "run", run)
    for _ in range(2):
        tools.mr_divw(mrdat_path=tmp_path / "pair.tsv", lambda_=2.0)
    assert len(list(tmp_path.glob("*/estimate.tsv"))) == 2
    assert received[0]["lambda"] == 2.0 and received[0]["mrdat_path"] == str(tmp_path / "pair.tsv")
    monkeypatch.setattr(method, "run", lambda payload: (_ for _ in ()).throw(ValueError("fixture failure")))
    with pytest.raises(ValueError, match="fixture failure"):
        tools.mr_divw(mrdat_path="missing.tsv")
    assert os.environ["MRCAT_EXECUTION_DIR"] == str(tmp_path)


@pytest.mark.r
def test_instrument_selection_never_relaxes_requested_threshold(tmp_path):
    script = ROOT / "mrcat/tool/MRTool/mr_instrument_selection.R"
    code = f'''source({str(script)!r})
d <- data.frame(SNP=paste0("rs",1:6), pval.exp=c(1e-9,1e-9,rep(1e-6,4)),
                b.exp=0.1,b.out=0.03,se.exp=0.01,se.out=0.01)
s <- mr_select_instruments(d,5e-8,4,function(...) NULL)
stopifnot(!s$passed,s$nsnp==2,s$threshold==5e-8,!s$relaxed,length(s$attempts)==1)
t <- mr_select_instruments(d,1e-6,4,function(...) NULL)
stopifnot(t$passed,t$nsnp==6,t$threshold==1e-6,!t$relaxed)
'''
    result = subprocess.run([str(Path(sys.executable).parent / "Rscript"), "-e", code],
                            cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stderr


def test_active_guide_reaches_model_without_middle_truncation(tmp_path):
    store=Store(tmp_path)
    state=store.create("Use CAUSE", "openai")
    state["active_agent"]="mr"
    from mrcat import memory
    memory.work_state(state,"mr")["guide"]="mr-cause"
    agent=Agent(ROOT,store)
    assert agent.executor_context(state,"mr")["active_guide"]["content"] == (ROOT/"skills/mr-cause/SKILL.md").read_text()


@pytest.mark.r
def test_real_primary_method_and_comparison_keep_artifacts(tmp_path, monkeypatch):
    from mrcat.model import llm_gateway
    monkeypatch.setattr(llm_gateway,"call_text",forbid_model)
    monkeypatch.setenv("RSCRIPT_BIN",str(Path(sys.executable).parent/"Rscript"))
    monkeypatch.setenv("MRCAT_WORKSPACE_DIR",str(ROOT))
    data=tmp_path/"MRdat.tsv"
    header="SNP\tb.exp\tb.out\tse.exp\tse.out\tpval.exp\tZ.exp\tZ.out\tN.exp\tN.out\n"
    rows=[]
    for i in range(24):
        bx=0.1+(i%7)*0.013
        by=0.35*bx+((i%5)-2)*0.002
        rows.append(f"rs{i+1}\t{bx}\t{by}\t0.01\t0.01\t1e-10\t{bx/0.01}\t{by/0.01}\t10000\t10000\n")
    data.write_text(header+"".join(rows))
    result=tools.mr_primary(mrdat_path=data,output_dir=tmp_path/"primary")
    assert result["outputs"]["status"]=="ok",result
    record=Path(result["outputs"]["mr_primary_result"]["result_record_path"])
    assert record.is_file()
    comparison=tools.analysis_method_comparison(method_result_paths=[record],output_dir=tmp_path/"comparison")
    assert comparison["outputs"]["status"]=="ok",comparison
    payload=comparison["outputs"]["method_comparison_result"]
    assert Path(payload["comparison_table_path"]).is_file()
    assert len(payload["methods"])>=2
    assert all(Path(plot["path"]).is_file() for plot in payload["plot_manifest"]["plots"])
    assert "reports" not in payload  # Interpretation is owned by the agent.


def test_documented_supplement_export_keeps_unknowns_and_native_provenance(tmp_path, monkeypatch):
    """Exercise the documented export with incomplete real-world candidate shapes."""
    import re
    from fastapi.testclient import TestClient
    from mrcat.web.server import create_app
    app = create_app(repo_root=ROOT, artifact_dir=tmp_path / 'sessions')
    store = app.state.service.store
    sid = store.create('Supplement CAD discovery', 'openai')['session_id']
    output = store.directory(sid) / 'workspace/outputs/cad_supplement'
    reference = (ROOT / 'skills/gwas-search/reference/output-format.md').read_text()
    code = re.search(r'```python\n(.*?)\n```', reference, re.S)[1]
    code = code.replace('/absolute/path/to/session/workspace/outputs/cad_supplement', str(output))
    candidates = [dict(source='pan_ukb', study_id=None, trait='Coronary atherosclerosis',
                       sample_size=None, ancestry=None, downloadable=None,
                       download_descriptor=None,
                       study_metadata=dict(phenocode='411.4', aws_path='unverified-source-path'),
                       supplemental_note='Population-specific metadata unresolved.')]
    exec(compile(code, 'documented-supplement-example', 'exec'),
         dict(candidates=candidates, target=dict(kind='trait', value='CAD'), diagnostics={}))
    saved = output / 'gwas_search_shortlists.json'
    assert json.loads(saved.read_text())['candidates'] == candidates
    assert saved.with_suffix('.xlsx').is_file()
    from openpyxl import load_workbook
    workbook_file = load_workbook(saved.with_suffix('.xlsx'))
    sheet = workbook_file.active
    values = dict(zip([cell.value for cell in sheet[1]], [cell.value for cell in sheet[2]]))
    assert values['Downloadable'] == 'Unknown'
    assert values['Download Status'] == 'unknown'
    workbook_file.close()
    client = TestClient(app)
    relative = str(saved.relative_to(store.directory(sid)))
    response = client.get(f'/api/sessions/{sid}/artifacts/raw', params={'summary': relative})
    assert response.json()['candidates'][0]['study_id'] is None
    workbook = client.get(f'/api/sessions/{sid}/artifacts/spreadsheet',
                          params={'summary': relative.replace('.json', '.xlsx')})
    assert workbook.status_code == 200
    assert 'Coronary atherosclerosis' in workbook.text
