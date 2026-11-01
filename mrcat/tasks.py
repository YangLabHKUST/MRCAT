"""Task identity, ordered planning guidance and preserved completed results."""
from copy import deepcopy
from .memory import initial_memory, apply_delivery
from .store import now

TERMINAL = {"completed", "failed", "cancelled"}


def archive_task(state, status=None):
    task = state.get("active_task")
    if not task:
        return
    if status:
        task["status"] = status
    apply_delivery(task)
    task["memory"] += f"\nTask {task['status']}: {task['task_id']}.\n"
    task["updated_at"] = now()
    state["task_history"].append(deepcopy(task))
    state["active_task"] = None


def create_task(state, proposal):
    previous = state.get("active_task")
    if previous:
        archive_task(state, previous["status"] if previous["status"] in TERMINAL else "paused")
    number = state["next_task_no"]
    state["next_task_no"] += 1
    task = dict(task_id=f"task{number}", description=proposal["description"],
                request=proposal["request"], status="running", plan=proposal["plan"],
                plan_history=[dict(text=proposal["plan"], reason="Confirmed initial plan", timestamp=now())],
                memory=initial_memory(proposal["request"]), memory_upto=len(state["messages"]),
                context_start=max(0, len(state["messages"])-1), event_start=len(state["events"]), guide=None,
                created_at=now(), updated_at=now(), artifacts=[],
                plan_items=deepcopy(proposal.get('plan_items', [])), completed_items={})
    state["active_task"] = task
    return task


def revise_task(task, plan, reason):
    if task["status"] in TERMINAL:
        raise ValueError("Completed task history is immutable; create a new task to reuse its outputs.")
    task["plan"] = plan['text']
    task['plan_items'] = deepcopy(plan['items'])
    task.setdefault('completed_items', {})
    task.pop('current_item_id', None)
    task.pop('item_execution_ids', None)
    task["plan_history"].append(dict(text=plan['text'], reason=reason, timestamp=now()))
    task["updated_at"] = now()
