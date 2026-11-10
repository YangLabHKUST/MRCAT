from pathlib import Path
import argparse, fcntl, json, os, signal, sys, traceback
from mrcat.config.env import load_repo_dotenv, disable_proxy_from_env_if_requested
from mrcat.agent import Agent
from mrcat.state.store import Store

class Stopped(BaseException): pass

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--root",required=True);parser.add_argument("--store",required=True);parser.add_argument("--session",required=True);parser.add_argument("--request",required=True)
    args=parser.parse_args();root=Path(args.root);store=Store(args.store);sid=args.session;directory=store.directory(sid)
    load_repo_dotenv(repo_root=root);disable_proxy_from_env_if_requested()
    def stop(signum,frame): raise Stopped()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    # Wait until the parent has persisted the job record.
    with (directory/"job.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);fcntl.flock(lock,fcntl.LOCK_UN)
    terminal="failed"
    try:
        state=Agent(root,store,execution_timeout=int(os.getenv("MRCAT_EXECUTION_TIMEOUT","3600"))).run(sid,json.loads(Path(args.request).read_text())["request"])
        terminal=state["status"]
    except Stopped:
        terminal="stopped";state=store.load(sid);state["status"]=terminal
        if state.get("active_agent")=="mr" and state.get("active_task"):
            state["active_task"]["status"]="paused"
        for event in state["events"]:
            if event["type"]=="code_execution" and event["details"].get("status")=="running": event["details"]["status"]="cancelled"
        store.event(state,"interrupted","Stopped. Reply to continue with the saved plan, conversation and files.")
    except Exception as exc:
        traceback.print_exc();state=store.load(sid);state["status"]="failed"
        message = f"{type(exc).__name__}: {exc}"
        if not state["events"] or state["events"][-1].get("type") != "error" or state["events"][-1].get("content") != message:
            store.event(state, "error", message)
    finally:
        state=store.load(sid)
        if state.get("job"): state["job"]["status"]=terminal
        store.save(state)
if __name__=="__main__":main()
