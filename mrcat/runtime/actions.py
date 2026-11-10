"""Executor action transport, independent of task state and model calls."""
import json
import re

def parse_action(raw, role=None):
    """Extract executable source; prose is commentary, never execution evidence."""
    text = raw.strip()
    blocks, prose = [], []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = re.fullmatch(r"[ \t]*(`{3,}|~{3,})([A-Za-z]*)[ \t]*", lines[index])
        if not match:
            prose.append(lines[index])
            index += 1
            continue
        fence, language = match.groups()
        end = next((i for i in range(index + 1, len(lines)) if lines[i].strip() == fence), None)
        if end is None:
            raise ValueError("Unclosed code fence; return complete source before execution.")
        blocks.append((language.lower(), "\n".join(lines[index + 1:end])))
        index = end + 1
    if blocks and any(language in {"python", "r", "bash"} for language, _ in blocks):
        if len(blocks) != 1:
            raise ValueError("Return exactly one final executable code block. No code was executed. "
                             "Do not submit both a draft and its replacement.")
        if not blocks[0][1].strip():
            raise ValueError("Executable source must not be empty.")
        # Do not execute a reply that also requests a control transition.
        for line in prose:
            if line.lstrip().startswith(("{", "[")):
                raise ValueError("Keep control objects separate from executable source.")
        action = dict(type="execute", language=blocks[0][0],
                      body=blocks[0][1], message="\n".join(prose).strip())
    else:
        if len(blocks) == 1 and blocks[0][0] == "json" and not "\n".join(prose).strip():
            text = blocks[0][1].strip()
        try:
            action = json.loads(text)
        except ValueError as exc:
            raise ValueError("Return python/r/bash source blocks, or one control JSON object. "
                             "Do not simulate observations or wrap source in an output record.") from exc
    if not isinstance(action, dict) or set(action) - {"type", "body", "message", "language", "outcome"}:
        raise ValueError('Use type, body, message, language and end outcome; executor cannot write Plan or memory.')
    if not isinstance(action.get("type"), str) or action["type"] not in {"execute", "skill", "evaluate", "ask", "final", "end"}:
        raise ValueError('Choose an action allowed by your role: MR uses execute, skill or end. Only Planner may replace a Plan.')
    if not isinstance(action.get("body"), str) or not action["body"].strip():
        raise ValueError('Action body must be nonempty text.')
    if not isinstance(action.get("message", ""), str):
        raise ValueError('Action message must be text.')
    if not isinstance(action.get("language", "python"), str) or action.get("language", "python") not in {"python", "r", "bash"}:
        raise ValueError('Execution language must be python, r or bash.')
    if role == "mr" and action["type"] not in {"execute", "skill", "end"}:
        raise ValueError("MR executor uses execute, skill or end; end hands control to Evaluate, not a user-facing answer.")
    if action["type"] == "end":
        if role != "mr" or not isinstance(action.get("outcome"), str) or action["outcome"] not in {"complete", "blocked"}:
            raise ValueError("MR end requires outcome=complete or blocked and a concise evidence handoff in body.")
    elif "outcome" in action:
        raise ValueError("Only end accepts outcome.")
    result = dict(kind=action["type"], body=action["body"].strip(),
                  message=action.get("message", ""), language=action.get("language", "python"))
    if action["type"] == "end":
        result["outcome"] = action["outcome"]
    return result
