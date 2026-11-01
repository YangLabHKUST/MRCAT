"""Compact working memory; full evidence stays in the session transcript and files."""
import json
import re
from uuid import uuid4
from .actions import parse_action

MEMORY_LIMIT = 6000
# Spend context on evidence rather than replayed code and shared guide prose.
# This is a character budget, not a provider token count or a round limit.
RECENT_LIMIT = 14000


def excerpt(text, limit):
    text = str(text)
    if len(text) <= limit:
        return text
    marker = "\n[Excerpt; consult the saved transcript or referenced file.]\n"
    if limit <= len(marker):
        return text[:max(0, limit)]
    available = limit - len(marker)
    return text[:available * 2 // 3] + marker + text[-available // 3:]


def initial_memory(description):
    return (f"### Task Description\n{description}\n\n"
            "### Confirmed Facts\nNone recorded.\n\n"
            "### Pending Questions\nNone recorded.\n\n"
            "### Recent Progress\nNot started.\n")


def message_content(message, limit):
    """Clip output fields, never the envelope carrying errors and evidence paths."""
    raw = message["content"]
    if message["role"] != "observation":
        return excerpt(raw, limit)
    try:
        result = json.loads(raw)
    except (ValueError, TypeError):
        return excerpt(raw, limit)
    if not isinstance(result, dict) or "stdout_path" not in result:
        return excerpt(raw, limit)
    envelope = {key: result[key] for key in ("execution_id", "status", "returncode", "source_path",
                "stdout_path", "stderr_path", "tool_results") if key in result}
    files = result.get("generated_files", [])
    envelope["generated_files"] = files[:8]
    envelope["generated_file_count"] = len(files)
    budget = max(0, limit - len(json.dumps(envelope, ensure_ascii=False)) - 80)
    stderr, stdout = str(result.get("stderr", "")), str(result.get("stdout", ""))
    err_budget = min(len(stderr), max(budget // 2, budget - len(stdout)))
    envelope["stderr"] = excerpt(stderr, err_budget)
    envelope["stdout"] = excerpt(stdout, max(0, budget - len(envelope["stderr"])))
    while len(json.dumps(envelope, ensure_ascii=False)) > limit:
        field = max(("stdout", "stderr"), key=lambda key: len(envelope[key]))
        if not envelope[field]:
            break
        envelope[field] = excerpt(envelope[field], max(0, len(envelope[field]) - 200))
    return json.dumps(envelope, ensure_ascii=False)


def relevant_messages(messages, *, start=0, role=None, task_id=None):
    return [m for m in messages[start:]
            if (not role or m["role"] == "user" or m.get("agent", role) == role)
            and (not task_id or m.get("task_id") in (None, task_id))]


def recent_window(messages, *, start=0, limit=RECENT_LIMIT, count=None, role=None, task_id=None):
    """One indexed, character-budgeted projection for execution and compaction."""
    selected, remaining, observation_seen, assistant_seen = [], limit, False, False
    for index in range(len(messages) - 1, start - 1, -1):
        message = messages[index]
        if role and message['role'] != 'user' and message.get('agent', role) != role:
            continue
        if task_id and message.get('task_id') not in (None, task_id):
            continue
        if (count is not None and len(selected) >= count) or remaining < 1200:
            break
        newest = message["role"] == "observation" and not observation_seen
        # Keep the latest proposed code for repair. Earlier code remains at the
        # source_path in its observation; replaying it is not execution evidence.
        if message['role'] == 'assistant' and assistant_seen:
            try:
                action = parse_action(message['content'], role=message.get('agent'))
            except (ValueError, TypeError):
                action = None
            if isinstance(action, dict) and action.get('kind') == 'execute':
                message = dict(message, content=(action.get('message', '') +
                    '\nEarlier code: see source_path in the following observation.').strip())
        cap = 4000 if newest else 1500 if message['role'] == 'observation' else 2500
        content = message_content(message, min(cap, remaining))
        entry = {"role": message["role"], "content": content}
        selected.append((index, entry))
        remaining -= len(json.dumps(entry, ensure_ascii=False))
        observation_seen |= message["role"] == "observation"
        assistant_seen |= message['role'] == 'assistant'
    return list(reversed(selected))


def recent_messages(messages, **kwargs):
    return [message for _, message in recent_window(messages, **kwargs)]


MEMORY_END = "[END_MEMORY]"


def completed_memory(text, role=None, *, token_limit=None):
    text = text.strip()
    if not text.endswith(MEMORY_END):
        raise ValueError("Memory output is incomplete; previous memory retained.")
    note = text[:-len(MEMORY_END)].strip()
    if token_limit is None:
        oversized = len(note) > MEMORY_LIMIT
    else:
        from .context import tokens
        oversized = tokens(note) > token_limit
    if not note or oversized:
        raise ValueError("Memory output is empty or exceeds its budget; previous memory retained.")
    headings = SEARCH_HEADINGS if role == "search" else TASK_HEADINGS
    for heading in headings:
        if "### " + heading not in note:
            raise ValueError("Memory output is missing a section; previous memory retained.")
    return note


def work_state(state, role):
    if role == "mr" and state.get("active_task"):
        return state["active_task"]
    return state["role_memory"].setdefault(role, {
        "memory": initial_search_memory("") if role == "search" else initial_memory(f"{role.title()} work in this session."),
        "memory_upto": 0, "context_start": len(state["messages"]), "guide": None,
    })


def task_brief(task):
    if not task:
        return None
    return {key: task.get(key) for key in ("task_id", "description", "status", "request")}


def task_catalog(tasks):
    """A small directory, not expanded summaries or result payloads."""
    return [dict(task_id=t["task_id"], request=excerpt(t.get("request") or t.get("description", ""), 350),
                 status=t["status"], artifact_count=len(t.get("artifacts", []))) for t in tasks]


def referenced_tasks(tasks, *texts):
    """Expand explicit task IDs or artifact references; do not guess relevance."""
    text = "\n".join(str(value or "") for value in texts)
    return [t for t in tasks if re.search(r"(?<![A-Za-z0-9_])" + re.escape(t["task_id"]) +
                                         r"(?![A-Za-z0-9_])", text, re.I)
            or any(ref and ref in text for ref in t.get("artifacts", []))]


def work_history(work):
    return [dict(request=excerpt(old.get("request", ""), 300), status=old.get("status", "unknown"),
                 artifacts=old.get("artifacts", [])[-6:]) for old in work.get("history", [])]


def render_memory(state):
    lines = ["# Memory", "", "## User Request", state.get("memory_request", state["question"]), ""]
    for role in ("search", "report"):
        work = state.get("role_memory", {}).get(role)
        if work:
            lines.extend([f"## {role.title()}", work["memory"], ""])
    for task in [*state.get("task_history", []), *([state["active_task"]] if state.get("active_task") else [])]:
        lines.extend([f"## {task['task_id']}", f"Status: {task['status']}", task["memory"], ""])
    return "\n".join(lines)


def control_facts(state, role):
    """Host-recorded plan/recovery events override claims in model summaries."""
    task_id = (state.get("active_task") or {}).get("task_id") if role == "mr" else None
    kinds = {"recovery_requested", "evaluation", "final", "question"}
    if role == "mr":
        kinds.update({"plan_updated", "recovery_started", "recovery_failed", "task_created", "task_revised"})
    start = work_state(state, role).get("event_start", 0)
    selected = [e for e in state["events"][start:] if e["type"] in kinds
                and e.get("details", {}).get("agent") == role
                and (not task_id or e.get("details", {}).get("task_id") == task_id)]
    return [dict(type=e["type"], content="See current_plan." if e["type"] == "plan_updated" else excerpt(e["content"], 500),
                 details=e.get("details", {})) for e in selected[-5:]]


TASK_HEADINGS = ("Task Description", "Confirmed Facts", "Pending Questions", "Recent Progress")
SEARCH_HEADINGS = ("Research Goal", "Question Spec", "User Decisions", "Evidence Claims",
                   "Candidate Datasets", "Open Questions", "Current Summary")


def initial_search_memory(request):
    return "\n\n".join("### " + heading + "\n" + (request if heading == "Research Goal" else "None recorded.")
                        for heading in SEARCH_HEADINGS)


def begin_role_work(state, role, action, effective_request=None):
    """A new request owns its pending work; old summaries are explicitly history."""
    work = work_state(state, role)
    request = effective_request or work.get("request") or state["request"]
    if action == "run":
        history = list(work.get("history", []))
        empty = initial_search_memory("") if role == "search" else initial_memory(f"{role.title()} work in this session.")
        if work.get("request") or work.get("memory") != empty:
            history.append(dict(request=work.get("request", ""), status=work.get("status", "unknown"),
                                memory=excerpt(work["memory"], 1800), artifacts=work.get("artifacts", [])[-10:]))
        work.clear()
        work.update(history=history[-3:], request=request, artifacts=[], guide=None,
                    result_scope=f"{role}_{uuid4().hex[:12]}",
                    memory=initial_search_memory(request) if role == "search" else initial_memory(request))
    elif role == "search" and "### Research Goal" not in work["memory"]:
        # An older session's generic summary remains available as history, never as new instructions.
        work["history"] = [dict(memory=excerpt(work["memory"], 1800), status=work.get("status", "unknown"))]
        work["memory"] = initial_search_memory(work.get("request") or state["request"])
    work["request"] = request
    if effective_request:
        work["memory"] = replace_section(work["memory"], "Research Goal" if role == "search" else "Task Description", request)
    work.pop("plan", None)
    work.pop("delivery", None)
    work.update(status="running", latest_request=state["request"], context_start=len(state["messages"])-1,
                memory_upto=len(state["messages"])-1, event_start=len(state["events"]))
    work.pop("memory_attempt_upto", None)


def replace_section(note, heading, body):
    pattern = r"(### " + re.escape(heading) + r"\n).*?(?=\n### |\Z)"
    return re.sub(pattern, lambda match: match[1] + body.rstrip() + "\n", note, flags=re.S)


def working_note(work):
    """Runtime facts are supplied separately, without repeating the delivery block."""
    return re.sub(r"\n?\[Runtime record\]\n.*?(?=\n### |\Z)", "", work["memory"], flags=re.S).strip()


def record_execution(work, result):
    """Record execution, not a scientific verdict or an inferred tool success."""
    fact = (f"Execution {result['execution_id']}: {result['status']}, return code {result['returncode']}; "
            f"log: {result['stdout_path']}; errors: {result['stderr_path']}.")
    work['execution_facts'] = [*work.get('execution_facts', []), fact][-4:]


def record_delivery(work, kind, answer):
    work['delivery'] = dict(kind=kind, content=excerpt(answer, 1000))
    apply_delivery(work)


def apply_delivery(work):
    """Project host-recorded delivery after summarization, including failed summaries."""
    delivery = work.get('delivery')
    if not delivery:
        return
    search = '### Research Goal' in work['memory']
    progress = 'Current Summary' if search else 'Recent Progress'
    pending = 'Open Questions' if search else 'Pending Questions'
    if delivery['kind'] == 'final':
        body = 'Result delivered to the user (not a scientific validation):\n' + delivery['content']
        work['memory'] = replace_section(work['memory'], pending, 'No pending work for this delivered request.')
    else:
        body = 'Awaiting user input: ' + delivery['content']
        work['memory'] = replace_section(work['memory'], pending, delivery['content'])
    note = working_note(work)
    match = re.search(r"### " + re.escape(progress) + r"\n(.*?)(?=\n### |\Z)", note, re.S)
    findings = match.group(1).strip() if match else ""
    work['memory'] = replace_section(work['memory'], progress,
        findings + '\n\n[Runtime record]\n' + '\n'.join([*work.get('execution_facts', []),
                   'Saved artifact references: ' + ', '.join(work.get('artifacts', [])[-8:]), body]))



def update_mr_task_memory(task):
    """Summarize accepted task progress from host state, not executor prose."""
    completed = task.get('completed_items', {})
    items = task.get('plan_items', [])
    accepted = [f"{item['step_id']}: {item['title']}" for item in items
                if item['step_id'] in completed]
    pending = [f"{item['step_id']}: {item['title']}" for item in items
               if item['step_id'] not in completed]
    # Completed-item records hold the authoritative result references.
    facts = json.dumps(completed, ensure_ascii=False, default=str) if completed else 'No accepted results yet.'
    handoff = task.get('executor_handoff') or {}
    progress = ('Executor handoff (not scientific acceptance): ' + handoff.get('outcome', '') +
                '. ' + excerpt(handoff.get('body', ''), 1200)) if handoff else 'No executor handoff yet.'
    task['memory'] = (
        f"### Task Description\n{task.get('request', '')}\n\n"
        f"### Confirmed Facts\nAccepted plan items:\n" + ('\n'.join(accepted) or 'None.') +
        '\nAccepted result records:\n' + facts +
        '\n\n### Pending Questions\n' + ('\n'.join(pending) or 'No unfinished plan items.') +
        '\n\n### Recent Progress\n' + progress)
