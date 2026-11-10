"""One intake decision per user turn; no per-code-action manager calls."""
import json
from mrcat.state.memory import excerpt, recent_messages, task_brief, task_catalog

ACTIONS_BY_ROUTE = {
    "respond": ("respond",),
    "search": ("run", "continue"),
    "mr": ("propose", "revise", "confirm", "continue", "cancel"),
    "report": ("run", "continue"),
}


def validate_state(decision, state):
    """Reject unavailable MR actions before entering a workflow node."""
    if decision['route'] != 'mr':
        return
    from mrcat.workflow.tasks import TERMINAL
    task = state.get('active_task')
    pending = state.get('pending') or {}
    proposal = pending.get('kind') == 'plan_confirmation'
    unfinished = task is not None and task['status'] not in TERMINAL
    action = decision['action']
    if action == 'confirm':
        if not proposal:
            raise ValueError('There is no pending plan to confirm. Use continue for an unfinished active task, '
                             'or propose to reuse historical work in a new task.')
        if pending.get('task_id') and (not unfinished or task['task_id'] != pending['task_id']):
            raise ValueError('The pending plan does not belong to an unfinished active task.')
    elif action == 'continue':
        if not unfinished:
            raise ValueError('There is no unfinished MR task to continue. Use propose to reuse historical '
                             'work in a new task, with the complete effective_request.')
        if proposal:
            raise ValueError('Confirm or revise the pending plan before continuing.')
    elif action == 'revise' and not (unfinished or proposal):
        raise ValueError('There is no active task or proposed plan to revise. Use propose for new work.')


def context(state, request):
    task = state.get("active_task")
    pending = state.get("pending")
    proposal = pending and pending.get("kind") == "plan_confirmation"
    return dict(latest_request=request,
                active_task=task_brief(task),
                current_plan="" if proposal else (task or {}).get("plan", ""),
                task_memory=excerpt(task["memory"], 1800) if task else "",
                pending=pending,
                role_work={role: dict(status=work.get("status", "unknown"), request=work.get("request", ""),
                                     summary=excerpt(work.get("memory", ""), 350))
                            for role, work in state["role_memory"].items()},
                task_history=task_catalog(state["task_history"]),
                recent_messages=recent_messages(state["messages"], limit=2500, count=4))


def parse_decision(raw):
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        decision = json.loads(text)
    except ValueError as exc:
        raise ValueError("Return one valid JSON object with separate route and action fields.") from exc
    if not isinstance(decision, dict):
        raise ValueError("Return one JSON object with separate route and action fields.")
    route, action = decision.get("route"), decision.get("action")
    if not isinstance(route, str) or route not in ACTIONS_BY_ROUTE:
        raise ValueError(
            f"Invalid route {route!r}. Allowed routes: {', '.join(ACTIONS_BY_ROUTE)}. "
            "route and action are separate fields; never combine them with '/'. "
            'For plan confirmation use route="mr", action="confirm". '
            "Preserve the user's intent and return the complete corrected JSON object."
        )
    if not isinstance(action, str) or action not in ACTIONS_BY_ROUTE[route]:
        raise ValueError(
            f"Invalid action {action!r} for route {route!r}. "
            f"Allowed actions for this route: {', '.join(ACTIONS_BY_ROUTE[route])}. "
            "Return the complete corrected JSON object without changing the user's intent."
        )
    message = decision.get("message")
    if decision["route"] == "respond":
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Manager respond requires a nonempty message.")
    elif "message" not in decision or message is not None:
        raise ValueError("Manager workflow routes require message=null; only Planner writes plans.")
    if not isinstance(decision.get("execute", False), bool):
        raise ValueError("Manager execute must be a boolean.")
    if "effective_request" not in decision:
        raise ValueError("Manager must include effective_request: complete updated request or null.")
    request = decision["effective_request"]
    if request is not None and (not isinstance(request, str) or not request.strip()):
        raise ValueError("effective_request must be nonempty text or null.")
    if action in {"respond", "confirm", "cancel"} and request is not None:
        raise ValueError("Respond, confirm and cancel must preserve the request: effective_request=null.")
    if action in {"run", "propose", "revise"} and request is None:
        raise ValueError("New or revised work requires the complete effective_request.")
    return decision
