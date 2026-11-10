"""Browser projection and background jobs; no scientific workflow scheduling."""
from pathlib import Path
from contextlib import contextmanager
from uuid import uuid4
import fcntl, json, os, signal, subprocess, sys, threading
from urllib.parse import quote
from mrcat.state.store import Store, now, write_json
from mrcat.workflow.finalization import format_saved_summary
from .rendering import render_markdown
from .cache import ViewCache

class BusyError(RuntimeError): pass

class Service:
    def __init__(self, repo_root, artifact_dir):
        self.root=Path(repo_root).resolve(); self.store=Store(artifact_dir)
        self.views = ViewCache(self)
    @contextmanager
    def locked(self,sid):
        self.require_local(sid)
        path=self.store.directory(sid)/"job.lock"
        with path.open("a") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(lock,fcntl.LOCK_UN)
    def require_local(self, sid):
        if self.store.directory(sid).resolve().parent != self.store.base:
            raise PermissionError('Linked sessions are read-only. Use Continue in a copy before making changes.')
    def fork(self, sid):
        from mrcat.fork import fork_session
        copied = fork_session(self.store.directory(sid), self.store.base)
        return {"session": self.snapshot(copied)}
    def reconcile(self,state):
        if self.store.directory(state['session_id']).resolve().parent != self.store.base:
            return state
        job=state.get("job")
        if job and job["status"]=="running":
            try: os.kill(job["pid"],0)
            except ProcessLookupError:
                job["status"]="interrupted"; state["status"]="paused"
                self.store.event(state,"interrupted","Worker ended unexpectedly. Reply to continue from saved context.")
        return state
    def start(self,question,provider):
        state=self.store.create(question,provider)
        return self.reply(state["session_id"],question)
    def reply(self,sid,request):
        if not str(request).strip(): raise ValueError("A message is required")
        with self.locked(sid):
            state=self.reconcile(self.store.load(sid))
            if (state.get("job") or {}).get("status")=="running": raise BusyError("A task is running. Stop it before sending a new request.")
            directory=self.store.directory(sid);(directory/"STOP").unlink(missing_ok=True)
            job_id=uuid4().hex
            request_path=directory/"jobs"/(job_id+".json")
            write_json(request_path,dict(request=request))
            env=dict(os.environ,PYTHONPATH=str(self.root)+os.pathsep+os.environ.get("PYTHONPATH",""),LLM_PROVIDER=state["provider"])
            log=directory/"jobs"/(job_id+".log")
            with log.open("w") as output:
                proc=subprocess.Popen([sys.executable,"-m","mrcat.web.worker","--root",str(self.root),"--store",str(self.store.base),"--session",sid,"--request",str(request_path)],cwd=self.root,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            state["job"]=dict(job_id=job_id,pid=proc.pid,status="running",action="agent_turn",created_at=now(),log_path=str(log.relative_to(directory)))
            state["status"]="running";self.store.save(state)
            # Reap direct children to avoid zombie PIDs masquerading as live jobs.
            threading.Thread(target=proc.wait,daemon=True).start()
        return self.accepted(state)
    def stop(self,sid):
        with self.locked(sid):
            state=self.store.load(sid);directory=self.store.directory(sid)
            (directory/"STOP").touch()
            child=directory/"execution_process.json"
            if child.exists():
                try: os.killpg(json.loads(child.read_text())["pid"],signal.SIGTERM)
                except (ProcessLookupError,ValueError,OSError): pass
            job=state.get("job") or {}
            if job.get("status")=="running":
                try: os.killpg(job["pid"],signal.SIGTERM)
                except ProcessLookupError: pass
            # Worker writes the terminal event in its signal handler.
        return self.accepted(state)
    def accepted(self, state):
        # Acknowledgement uses the state already checked by the command. It does
        # not reload checkpoints, walk artifacts, or render historical reports.
        job = state.get("job")
        return {"session": dict(session_id=state['session_id'], state=self.session_state(state),
                               active_job=job if job and job['status']=='running' else None,
                               latest_job=job)}

    def files(self,sid):
        base=self.store.directory(sid); resolved=base.resolve(); items=[]
        for folder in (base/"workspace",base/"executions"):
            if not folder.resolve().is_relative_to(resolved): continue
            # One traversal, no repeated resolve/stat of every ancestor on NFS.
            for parent, directories, filenames in os.walk(folder, followlinks=False):
                directories.sort()
                for name in sorted(filenames):
                    if name.startswith('.'): continue
                    path=Path(parent)/name
                    if path.is_symlink() and (not path.resolve().is_relative_to(resolved) or not path.is_file()):
                        continue
                    relative=str(path.relative_to(base))
                    items.append(dict(path=relative,summary=name,kind="image" if path.suffix.lower() in {".png",".jpg",".jpeg",".svg",".webp"} else "file"))
        return sorted(items, key=lambda item: item['path'])

    def snapshot(self,sid):
        return self.views.get(sid).snapshot()[1]

    def snapshot_payload(self,sid):
        return self.views.get(sid).snapshot()

    def project(self,state,files,report):
        sid=state['session_id'];job=state.get("job")
        running=bool(job and job["status"]=="running")
        session=self.session_state(state)
        events=[dict(event,content=format_saved_summary(event["content"]))
                if event["type"] in {"final", "question"} and event.get("details",{}).get("agent")=="mr"
                else event for event in state["events"]]
        def task_view(task):
            return dict(task,final_summary=format_saved_summary(task["final_summary"])) if task and task.get("final_summary") else task
        question=(state.get("pending") or {}).get("question", "") if state["status"]=="waiting_user" else ""
        images=[dict(summary=f["path"],title=f["summary"],url=self.url(sid,f["path"]),source="execution") for f in files if f["kind"]=="image"]
        mr_state=dict(session_id=sid,run_id=sid,status=state["status"],events=events,pending=state.get("pending"),active_task=task_view(state.get("active_task")),task_history=[task_view(task) for task in state.get("task_history",[])])
        return dict(session_id=sid,state=session,active_job=job if running else None,latest_job=job,mr=dict(session_id=sid,run_id=sid,state=mr_state,events=events,manifest={"artifacts":{sid:{"files":files}},"runs":{sid:{"artifacts":{"files":[f["path"] for f in files]}}}}),search={"session_id":None,"state":None,"events":[]},images=images,pending_question=question,brief=None,data_search=None,scan_design=None,final_report=report,double_check=None,trace_files={})
    def final_report(self, sid, state):
        # Report artifacts already expose status; use the existing response shape.
        work = state.get("role_memory", {}).get("report", {})
        run = work.get("report_run_id")
        if run:
            base = f"workspace/reports/{run}"
            for name in ("final_summary", "report_draft"):
                ref = f"{base}/{name}.md"
                try:
                    text = self.artifact(sid, ref).read_text(encoding="utf-8")
                    page = "scientific_report" if name == "final_summary" else "scientific_report_draft"
                    html = self.artifact(sid, f"{base}/{page}.html").read_text(encoding="utf-8")
                    if name == "report_draft":
                        text = "**Draft — automated review has not passed.**\n\n" + text
                    return dict(summary=ref, markdown=text, html=html)
                except (OSError, PermissionError):
                    continue
        active = state.get("active_task")
        candidates = ([active] if active else []) + list(reversed(state.get("task_history", [])))
        for task in candidates:
            if task.get("status") != "completed" and not (
                    task.get("final_summary") and (task.get("evaluation") or {}).get("route") == "finalize"):
                continue
            ref = next((p for p in task.get("artifacts", []) if p.endswith("/final_summary.md")), None)
            if ref:
                try:
                    text = self.artifact(sid, ref).read_text(encoding="utf-8")
                except (OSError, PermissionError):
                    continue
                text = format_saved_summary(text)
                return dict(summary=ref, markdown=text, html=render_markdown(text, lambda path: self.url(sid,path)))
        return None

    @staticmethod
    def session_state(state):
        sid=state['session_id'];job=state.get('job')
        running=bool(job and job['status']=='running')
        return dict(session_id=sid,question=state["question"],provider=state["provider"],status=state.get("active_agent","manager")+"_running" if running else state["status"],active_agent=state.get("active_agent","manager"),mr_session_id=sid,mr_run_id=sid,search_session_id=None,study_setup=state["study_setup"],created_at=state["created_at"],updated_at=state["updated_at"])
    def sessions(self, *, local_only=False):
        rows = []
        for path in self.store.base.iterdir():
            if not path.is_dir() or path.name.startswith('.'): continue
            if local_only and path.is_symlink(): continue
            try: rows.append(self.views.get(path.name).summary())
            except (OSError, ValueError): continue
        return sorted(rows, key=lambda row: row['updated_at'], reverse=True)
    def url(self,sid,path):
        return f"/api/sessions/{sid}/artifacts/raw?phase=mr&summary={quote(path)}"
    def artifact(self,sid,summary):
        base=self.store.directory(sid).resolve();path=(base/summary).resolve()
        try: relative=path.relative_to(base)
        except ValueError: raise PermissionError("Artifact is outside this session")
        # API exposes deliverables and code observations, not prompts or job configuration.
        if (not relative.parts or relative.parts[0] not in {"workspace","executions"} and str(relative) not in {"plan.md","memory.md"}): raise PermissionError("Not a public artifact")
        if str(relative) == 'memory.md':
            self.store.export(self.store.load(sid))
        if not path.is_file(): raise FileNotFoundError(summary)
        return path
    def study_setup(self,sid,*,exposure_manifest,outcome_manifest,analysis_request,methods,sources="[]",exposure_files=None,outcome_files=None):
        with self.locked(sid):
            state=self.reconcile(self.store.load(sid))
            if (state.get("job") or {}).get("status")=="running": raise BusyError("Stop the current task before updating study setup")
            directory=self.store.directory(sid);setup={"analysis_request":analysis_request,"methods":json.loads(methods),"sources":json.loads(sources)}
            for side,manifest,uploads in [("exposures",exposure_manifest,exposure_files or []),("outcomes",outcome_manifest,outcome_files or [])]:
                rows=json.loads(manifest)
                if not isinstance(rows,list): raise ValueError("Dataset manifest must be a list")
                for row in rows:
                    if "file_index" in row:
                        index=row.pop("file_index")
                        if not isinstance(index,int) or index<0 or index>=len(uploads): raise ValueError("Invalid uploaded file index")
                        upload=uploads[index];name=Path(upload.filename or "dataset").name
                        path=directory/"workspace"/"inputs"/(uuid4().hex[:8]+"_"+name)
                        path.parent.mkdir(parents=True,exist_ok=True)
                        with path.open("wb") as out:
                            while chunk:=upload.file.read(1024*1024): out.write(chunk)
                        row["file_ref"]=str(path.relative_to(directory))
                    elif row.get("file_ref"):
                        self.artifact(sid,row["file_ref"])
                setup[side]=rows
            state["study_setup"]=setup;self.store.save(state)
        request="User study setup (resolve file_ref relative to the session directory):\n"+json.dumps(setup,ensure_ascii=False,indent=2)
        return self.reply(sid,request)
