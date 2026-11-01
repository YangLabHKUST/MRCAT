from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json, os, threading, time
import pytest
from fastapi.testclient import TestClient
from mrcat.web.server import create_app
from test_agent import ROOT, action as action_payload

@pytest.fixture
def gateway(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            system=body['messages'][0]['content']
            if 'MRCAT Manager' in system:
                context=json.loads(body['messages'][1]['content'])
                if context.get('pending',{} ) and context['pending'].get('kind')=='plan_confirmation':
                    route,manager_action='mr','confirm'
                elif context.get('active_task'):
                    route,manager_action='mr','continue'
                elif context['latest_request'].startswith('MR'):
                    route,manager_action='mr','propose'
                else:
                    route,manager_action='search','run'
                result=json.dumps({'route':route,'action':manager_action,'message':None,'effective_request':context['latest_request'] if manager_action in {'run','propose','revise'} else None})
            elif 'working memory for the current role' in system:
                result='### Task Description\nInspect the requested file.\n### Confirmed Facts\nSaved answer is in workspace/answer.txt.\n### Pending Questions\nNone.\n### Recent Progress\nInspect that file before reuse.\n[END_MEMORY]'
                if 'Search.' in system:
                    context=json.loads(body['messages'][1]['content'])
                    result=context['previous_memory']+'\n[END_MEMORY]'
            elif 'MR item Review node' in system or 'You review the SCIENTIFIC BOUNDARIES' in system:
                context=json.loads(body['messages'][1]['content'])
                result=json.dumps(dict(route='execute', accept_item=True, reason='Fixture output is available.'))
            elif 'MR Finalize node' in system:
                result='completed\n{{value:r1/value}}\nVerified the saved answer.\n[END_FINAL_SUMMARY]'
            elif 'MRCAT MR Planner' in system:
                result=json.dumps(dict(plan_items=[dict(step_id='write', title='Inspect input and write the answer.',
                    skill_id=None, reuse_from=[])]))
            else:
                context=json.loads(body['messages'][1]['content'])
                user_messages=[m['content'] for m in context.get('recent_messages', []) if m['role']=='user']
                if 'coding agent working' in system:
                    request=(context['user_updates'] or [context['work_request']])[-1]
                    if 'slow' in request:
                        result=json.dumps(dict(tool='run', content='import time; print("started", flush=True); time.sleep(30)'))
                    elif any(m['role'] == 'tool' and json.loads(m['content']).get('result_refs') for m in body['messages']):
                        result=json.dumps(dict(tool='finish', outcome='complete', body='Verified the saved answer.'))
                    else:
                        result=json.dumps(dict(tool='run', content='from pathlib import Path; from mrcat.tools import publish_result; Path("answer.txt").write_text("42"); publish_result("answer", {"value":int(Path("answer.txt").read_text())})'))
                elif 'slow' in (user_messages[-1] if user_messages else context['latest_request']):
                    result=json.dumps(action_payload('execute', 'import time; print("started", flush=True); time.sleep(30)'))
                elif context['recent_messages'] and context['recent_messages'][-1]['role']=='observation':
                    result=json.dumps(action_payload('end', 'Verified the saved answer.', outcome='complete') if context['role']=='mr' else action_payload('final', 'Verified the saved answer.'))
                else:
                    result=json.dumps(action_payload('execute', 'from pathlib import Path; Path("answer.txt").write_text("42"); print(42)'))
            message={'role':'assistant','content':result}
            if body.get('tools') and len(body['tools']) > 1:
                from test_agent import native_reply
                message=json.loads(native_reply(json.loads(result)))
            elif body.get('tools'):
                message=dict(role='assistant', content=None, tool_calls=[dict(id='fixture', type='function', function=dict(name=body['tools'][0]['function']['name'], arguments=result))])
            payload=json.dumps({'choices':[{'message':message}],'usage':{'prompt_tokens':10,'completion_tokens':10}}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    for key,value in {'LLM_BACKEND':'http','OPENAI_API_KEY':'local-test-not-a-secret','OPENAI_BASE_URL':f'http://127.0.0.1:{server.server_port}/v1','OPENAI_TIMEOUT_SEC':'5','OPENAI_RETRY_COUNT':'1','MRCAT_MAX_ROUNDS':'5'}.items():monkeypatch.setenv(key,value)
    yield
    server.shutdown();thread.join()

def wait(client,sid,predicate,timeout=15):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        snapshot=client.get('/api/sessions/'+sid).json()
        if predicate(snapshot):return snapshot
        time.sleep(.1)
    raise AssertionError(snapshot)

def test_real_worker_restart_and_cancel(tmp_path,gateway):
    app=create_app(repo_root=ROOT,artifact_dir=tmp_path);client=TestClient(app)
    started=client.post('/api/sessions',json={'question':'calculate','provider':'openai'})
    assert started.status_code==200,started.text
    sid=started.json()['session']['session_id']
    done=wait(client,sid,lambda s:s['state']['status']=='completed')
    assert (tmp_path/sid/'workspace/answer.txt').read_text()=='42'
    assert done['latest_job']['status']=='completed'
    usage=json.loads((tmp_path/sid/'llm_usage.json').read_text())
    assert usage['llm_call_count']==4 and usage['llm_total_tokens']==80
    # A new service instance must restore the same durable conversation.
    other=TestClient(create_app(repo_root=ROOT,artifact_dir=tmp_path))
    assert other.get('/api/sessions/'+sid).json()['mr']['events']==done['mr']['events']
    assert other.post(f'/api/sessions/{sid}/reply',json={'reply':'slow task'}).status_code==200
    wait(other,sid,lambda s:any(e['type']=='code_execution' and 'started' in e['details'].get('stdout','') for e in s['mr']['events']))
    assert other.post(f'/api/sessions/{sid}/reply',json={'reply':'conflict'}).status_code==409
    assert other.post(f'/api/sessions/{sid}/stop').status_code==200
    stopped=wait(other,sid,lambda s:s['state']['status']=='stopped' and s['active_job'] is None)
    assert stopped['latest_job']['status']=='stopped'
    assert other.post(f'/api/sessions/{sid}/reply',json={'reply':'continue normally'}).status_code==200
    resumed=wait(other,sid,lambda s:s['state']['status']=='completed')
    assert any(e['type']=='interrupted' for e in resumed['mr']['events'])
    assert len([e for e in resumed['mr']['events'] if e['type']=='plan_updated'])==0

def test_manual_upload_uses_same_agent(tmp_path,gateway):
    client=TestClient(create_app(repo_root=ROOT,artifact_dir=tmp_path))
    response=client.post('/api/manual-sessions',data={'analysis_request':'Inspect uploaded data','exposure_manifest':json.dumps([{'name':'Exposure','file_index':0}]),'outcome_manifest':json.dumps([{'name':'Outcome'}]),'methods':'["mr-bwmr"]','sources':'[]','provider':'openai'},files={'exposure_files':('exposure.csv',b'SNP,beta\nrs1,.1\n','text/csv')})
    assert response.status_code==200,response.text
    sid=response.json()['session']['session_id']
    snapshot=wait(client,sid,lambda s:s['state']['status']=='completed')
    ref=snapshot['state']['study_setup']['exposures'][0]['file_ref']
    assert (tmp_path/sid/ref).read_text().startswith('SNP,beta')
    assert any('exposure.csv' in e['content'] for e in snapshot['mr']['events'] if e['type']=='user_message')


def test_mr_worker_plan_confirmation_stop_and_same_task_resume(tmp_path,gateway):
    client=TestClient(create_app(repo_root=ROOT,artifact_dir=tmp_path))
    response=client.post('/api/sessions',json={'question':'MR analysis','provider':'openai'})
    sid=response.json()['session']['session_id']
    proposed=wait(client,sid,lambda s:s['state']['status']=='waiting_user' and not s['active_job'])
    assert proposed['mr']['state']['active_task'] is None
    assert not any(e['type']=='code_execution' for e in proposed['mr']['events'])
    assert client.post(f'/api/sessions/{sid}/reply',json={'reply':'confirm slow'}).status_code==200
    running=wait(client,sid,lambda s:any(e['type']=='code_execution' and 'started' in e['details'].get('stdout','') for e in s['mr']['events']))
    assert running['mr']['state']['active_task']['task_id']=='task1'
    client.post(f'/api/sessions/{sid}/stop')
    stopped=wait(client,sid,lambda s:s['state']['status']=='stopped' and not s['active_job'])
    assert stopped['mr']['state']['active_task']['status']=='paused'
    client.post(f'/api/sessions/{sid}/reply',json={'reply':'continue normally'})
    done=wait(client,sid,lambda s:s['state']['status']=='completed' and not s['active_job'])
    assert done['mr']['state']['active_task'] is None
    assert done['mr']['state']['task_history'][0]['task_id']=='task1'
    assert len(done['mr']['state']['task_history'])==1
