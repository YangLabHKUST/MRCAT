from pathlib import Path
from contextlib import asynccontextmanager
import argparse, asyncio, csv, gzip, json, mimetypes, os, re
from .rendering import render_markdown
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from .service import Service, BusyError
from .study_methods import study_method_catalog
from .study_sources import study_source_catalog

def create_app(*,repo_root=None,artifact_dir=None):
    root=Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
    service=Service(root,artifact_dir or Path.cwd()/"runtime_artifacts")
    @asynccontextmanager
    async def lifespan(app):
        # Load Markdown extensions once, rather than on the first session GET.
        await asyncio.to_thread(render_markdown, '', lambda path: path)
        try: yield
        finally: await asyncio.to_thread(service.views.close)
    app=FastAPI(title="MRCAT", lifespan=lifespan);app.state.service=service
    static=root/"mrcat/web/static";app.mount("/static",StaticFiles(directory=static),name="static")
    @app.exception_handler(BusyError)
    async def busy(request,exc): return JSONResponse({"detail":str(exc)},status_code=409)
    @app.exception_handler(FileNotFoundError)
    async def missing(request,exc): return JSONResponse({"detail":str(exc)},status_code=404)
    @app.exception_handler(ValueError)
    async def invalid(request,exc): return JSONResponse({"detail":str(exc)},status_code=400)
    @app.exception_handler(PermissionError)
    async def forbidden(request,exc): return JSONResponse({"detail":str(exc)},status_code=403)
    @app.get("/")
    @app.get("/index.html")
    def index(): return FileResponse(static/"index.html")
    @app.get("/api/methods")
    def methods(): return {"methods":study_method_catalog(root/"skills"),"sources":study_source_catalog()}
    @app.get("/api/sessions")
    def sessions(): return {"sessions":service.sessions()}
    @app.post("/api/sessions")
    async def start(request:Request):
        body=await request.json()
        return await asyncio.to_thread(service.start,str(body.get("question","")),str(body.get("provider","anthropic")))
    @app.get("/api/sessions/{sid}")
    def snapshot(sid:str):
        return Response(service.snapshot_payload(sid)[2], media_type="application/json")
    @app.post("/api/sessions/{sid}/fork")
    async def fork(sid:str): return await asyncio.to_thread(service.fork, sid)
    @app.post("/api/sessions/{sid}/reply")
    async def reply(sid:str,request:Request):
        body=await request.json();return await asyncio.to_thread(service.reply,sid,body.get("reply",""))
    @app.post("/api/sessions/{sid}/stop")
    def stop(sid:str): return service.stop(sid)
    async def setup(request,sid=None):
        form=await request.form()
        if sid is None:
            state=await asyncio.to_thread(service.store.create,str(form.get("analysis_request","")),str(form.get("provider","anthropic")));sid=state["session_id"]
        return await asyncio.to_thread(service.study_setup,sid,exposure_manifest=str(form.get("exposure_manifest","[]")),outcome_manifest=str(form.get("outcome_manifest","[]")),analysis_request=str(form.get("analysis_request","")),methods=str(form.get("methods","[]")),sources=str(form.get("sources","[]")),exposure_files=form.getlist("exposure_files"),outcome_files=form.getlist("outcome_files"))
    @app.post("/api/manual-sessions")
    async def manual(request:Request): return await setup(request)
    @app.post("/api/sessions/{sid}/study-setup")
    async def study(sid:str,request:Request): return await setup(request,sid)
    # Existing UI buttons become ordinary user requests to the same agent.
    actions={"brief":"Prepare a source-grounded research brief for this task.","scan-design":"Propose an analysis design for this task.","double-check":"Review the actual evidence and outputs for this task. Explain problems and uncertainty.","scientific-report":"Write a scientific report grounded in the actual outputs. Save Markdown and any requested formats under workspace.","plots/generate":"Generate the requested plots from existing results.","handoff":"Perform the requested analysis.","data-search/select":"Use the following selected datasets for the analysis.","scan-design/select":"Use the following selected analysis design."}
    def action_handler(instruction):
        async def handle(sid:str,request:Request):
            raw=await request.body();body=json.loads(raw) if raw else {}
            return await asyncio.to_thread(service.reply,sid,instruction+"\n"+json.dumps(body,ensure_ascii=False))
        return handle
    for path,instruction in actions.items(): app.add_api_route("/api/sessions/{sid}/"+path,action_handler(instruction),methods=["POST"])
    @app.get("/api/sessions/{sid}/artifacts/raw")
    def raw(sid:str,summary:str,phase:str="mr",run_id:str|None=None):
        path=service.artifact(sid,summary)
        # Untrusted generated HTML must not execute in the application's origin.
        headers={"X-Content-Type-Options":"nosniff","Content-Security-Policy":"sandbox"}
        media=mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path,media_type=media,headers=headers)
    @app.get("/api/sessions/{sid}/artifacts/markdown")
    def md(sid:str,summary:str,phase:str="mr",run_id:str|None=None):
        path=service.artifact(sid,summary);text=path.read_text()
        html=render_markdown(text, lambda path: service.url(sid, path))
        return {"markdown":text,"html":html,"summary":summary}
    @app.get("/api/sessions/{sid}/artifacts/spreadsheet")
    def sheet(sid:str,summary:str,phase:str="mr",run_id:str|None=None,max_rows:int=100,sheet:str|None=None):
        path=service.artifact(sid,summary);limit=max(1,min(max_rows,500))
        from itertools import islice
        def preview(name, iterator):
            rows = [list(row) for row in islice(iterator, limit + 2)]
            return {"name": name, "headers": rows[0] if rows else [],
                    "rows": rows[1:limit + 1], "truncated": len(rows) > limit + 1}
        if path.suffix.lower() == ".xlsx":
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True, data_only=True)
            try:
                names = [sheet] if sheet and sheet in wb.sheetnames else wb.sheetnames
                sheets = [preview(name, wb[name].iter_rows(values_only=True)) for name in names]
            finally:
                wb.close()
        else:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", encoding="utf-8", errors="replace") as f:
                sample = f.read(4096); f.seek(0)
                delimiter = "\t" if "\t" in sample.partition("\n")[0] else ","
                sheets = [preview(path.name, csv.reader(f, delimiter=delimiter))]
        first = sheets[0] if sheets else {"headers": [], "rows": [], "truncated": False}
        return {"columns": first["headers"], "rows": first["rows"], "sheets": sheets,
                "summary": summary, "truncated": any(item["truncated"] for item in sheets)}
    @app.get("/api/sessions/{sid}/events")
    async def events(sid:str,request:Request):
        initial = await asyncio.to_thread(service.snapshot_payload, sid)
        async def stream():
            previous_generation, previous, payload = initial
            yield "event: snapshot\ndata: " + payload + "\n\n"
            while not await request.is_disconnected():
                await asyncio.sleep(0.5)
                generation, snapshot, payload = await asyncio.to_thread(service.snapshot_payload, sid)
                if snapshot is previous:
                    yield ": heartbeat\n\n"
                elif generation != previous_generation:
                    yield "event: snapshot\ndata: " + payload + "\n\n"
                else:
                    # Live stdout/progress replaces existing event IDs. The
                    # durable task state has not changed, so send only changes.
                    old = {event['id']: event for event in previous['mr']['events']}
                    changed = [event for event in snapshot['mr']['events']
                               if old.get(event['id']) != event]
                    if changed:
                        yield "event: events\ndata: " + json.dumps(changed, ensure_ascii=False) + "\n\n"
                    else:
                        yield ": heartbeat\n\n"
                previous_generation, previous = generation, snapshot
        return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache", "X-Accel-Buffering":"no"})
    return app

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--host",default="127.0.0.1");parser.add_argument("--port",type=int,default=7869);parser.add_argument("--artifact-dir",default="runtime_artifacts");parser.add_argument("--env-file",type=Path)
    args=parser.parse_args();root=Path(__file__).resolve().parents[2]
    os.environ.setdefault("MRCAT_CONFIG_DIR", str(Path.cwd()))
    from mrcat.config.env import load_repo_dotenv,disable_proxy_from_env_if_requested
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    load_repo_dotenv(repo_root=root)
    disable_proxy_from_env_if_requested()
    import uvicorn
    uvicorn.run(create_app(repo_root=root,artifact_dir=Path(args.artifact_dir).resolve()),host=args.host,port=args.port)
if __name__=="__main__":main()
