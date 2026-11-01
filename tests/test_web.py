from pathlib import Path
from fastapi.testclient import TestClient
from mrcat.web.server import create_app
from mrcat.agent import Agent
from test_agent import Model, ROOT, action, action

def test_projection_and_previews(tmp_path):
    app=create_app(repo_root=ROOT,artifact_dir=tmp_path);service=app.state.service
    state=service.store.create("Calculate", "openai");sid=state["session_id"]
    Agent(ROOT,service.store,model=Model([action('execute', 'from pathlib import Path; Path("data.csv").write_text("x,y\\n1,2\\n")'),action('final', 'Done.')])).run(sid,"Calculate")
    client=TestClient(app)
    assert client.get("/").status_code==200
    assert len(client.get('/api/methods').json()['methods'])==12
    snapshot=client.get('/api/sessions/'+sid).json()
    assert snapshot['state']['status']=='completed'
    assert any(e['type']=='manager_route' and e['details']['route']=='search' for e in snapshot['mr']['events'])
    files=snapshot['mr']['manifest']['runs'][sid]['artifacts']['files'];assert 'workspace/data.csv' in files
    path=service.store.directory(sid)/'workspace/data.csv';path.write_text('x,y\n1,2\n')
    response=client.get(f'/api/sessions/{sid}/artifacts/spreadsheet',params={'summary':'workspace/data.csv'})
    assert response.status_code==200
    assert response.json()['sheets'][0]['headers']==['x','y']
    assert response.json()['sheets'][0]['rows']==[['1','2']]

def test_artifact_paths_are_session_scoped(tmp_path):
    app=create_app(repo_root=ROOT,artifact_dir=tmp_path);service=app.state.service
    sid=service.store.create("Test", "openai")['session_id'];client=TestClient(app)
    for path in ['../../.env','session.json','jobs/request.json','.']:
        assert client.get(f'/api/sessions/{sid}/artifacts/raw',params={'summary':path}).status_code==403
    link=service.store.directory(sid)/'workspace/leak';link.symlink_to(ROOT/'.env.example')
    assert client.get(f'/api/sessions/{sid}/artifacts/raw',params={'summary':'workspace/leak'}).status_code==403
    assert not service.files(sid)


def test_workbook_sheets_and_preview_limit(tmp_path):
    from openpyxl import Workbook
    app = create_app(repo_root=ROOT, artifact_dir=tmp_path)
    service = app.state.service
    sid = service.store.create("Workbook", "openai")["session_id"]
    workbook = Workbook()
    workbook.active.title = "First"
    workbook.active.append(["x", "y"])
    workbook.active.append([1, 2])
    second = workbook.create_sheet("Second")
    second.append(["label"])
    second.append(["a"])
    second.append(["b"])
    workbook.save(service.store.directory(sid) / "workspace/book.xlsx")
    client = TestClient(app)
    response = client.get(f"/api/sessions/{sid}/artifacts/spreadsheet",
                          params={"summary": "workspace/book.xlsx", "max_rows": 1})
    assert response.status_code == 200
    sheets = response.json()["sheets"]
    assert [item["name"] for item in sheets] == ["First", "Second"]
    assert sheets[0]["rows"] == [[1, 2]] and not sheets[0]["truncated"]
    assert sheets[1]["rows"] == [["a"]] and sheets[1]["truncated"]
