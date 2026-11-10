"""One-time import of early MRCAT sessions; original transcripts remain intact."""
import argparse
from pathlib import Path
from mrcat.state.store import Store, write_json, now
from mrcat.state.memory import initial_memory


def upgrade(store, sid):
    state = store.load(sid)
    if state.get("version")==2:
        return False
    if (state.get("job") or {}).get("status")=="running":
        raise ValueError("Stop the active job before upgrading its session.")
    directory = store.directory(sid)
    backup = directory / "session.before_roles.json"
    if not backup.exists():
        write_json(backup, state)
    requests = [m["content"] for m in state["messages"] if m["role"]=="user"]
    latest = requests[-1] if requests else state["question"]
    state.update(version=2, persistence='langgraph', request=latest, memory_request=latest, active_agent="manager", active_task=None,
                 task_history=[], next_task_no=1, pending=None, role_memory={},
                 loaded_skills=list(state.get("loaded_skills", {})))
    executions = [e for e in state["events"] if e["type"]=="code_execution"]
    if executions:
        refs = [e["details"]["stdout_path"] for e in executions if e["details"].get("stdout_path")]
        task = dict(task_id="task1", description=latest, request=latest,
                    status=state["status"] if state["status"] in {"completed","failed","cancelled"} else "paused",
                    plan=state["plan"], plan_history=[dict(text=state["plan"], reason="Imported existing text plan; prior confirmation was not recorded", timestamp=now())],
                    memory=initial_memory(latest).replace("Not started.", "Imported prior execution; inspect saved logs before treating results as verified.\n"+"\n".join(refs[-3:])),
                    context_start=len(state["messages"]), memory_upto=len(state["messages"]), guide=None,
                    created_at=state["created_at"], updated_at=now(), artifacts=refs)
        if task["status"] in {"completed","failed","cancelled"}:
            state["task_history"].append(task)
        else:
            state["active_task"]=task
        state["next_task_no"]=2
        state["active_agent"]="mr"
    store.event(state,"session_upgraded","Imported existing conversation and files; task memory is now separate from the transcript.",agent="manager")
    return True


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--artifact-dir",type=Path,default=Path("runtime_artifacts"))
    args=parser.parse_args()
    store=Store(args.artifact_dir)
    for state in store.list():
        if upgrade(store,state["session_id"]):
            print("Upgraded",state["session_id"])

if __name__=="__main__":
    main()
