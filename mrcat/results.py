"""Durable result bindings shared by tools and arbitrary CodeAct code."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re

from uuid import uuid4

from .store import now

_NAME = re.compile(r"[A-Za-z0-9_-]+")


def work_scope(work, role):
    return work.get("task_id") or work.get("result_scope") or role


def _runtime():
    directory = os.environ.get("MRCAT_SESSION_DIR")
    scope = os.environ.get("MRCAT_RESULT_SCOPE")
    if not directory or not scope:
        raise RuntimeError("Result references require a CodeAct session and work scope.")
    return Path(directory), scope


def _scope_directory(directory, scope):
    if not isinstance(scope, str) or not _NAME.fullmatch(scope):
        raise ValueError("Invalid result scope.")
    return Path(directory) / "results" / scope


def _json_value(value):
    # Convert Path objects, not arbitrary strings that might contain identifiers.
    def encode(item):
        if isinstance(item, Path):
            return str(item.expanduser().resolve())
        raise TypeError(f"Not a JSON result value: {type(item).__name__}")
    return json.loads(json.dumps(value, allow_nan=False, default=encode))


def _publish(name, outputs, *, automatic=False, producer=None, status="unverified"):
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("Result IDs must contain only letters, numbers, underscores or hyphens.")
    if not isinstance(outputs, dict):
        raise TypeError("Publish a dictionary of named outputs; keep large data in files.")
    outputs = _json_value(outputs)
    directory, scope = _runtime()
    folder = _scope_directory(directory, scope)
    folder.mkdir(parents=True, exist_ok=True)
    result_id = f"{name}_{uuid4().hex[:12]}" if automatic else name
    entry = dict(outputs=outputs, status=status, created_at=now(),
        execution_id=os.environ.get("MRCAT_EXECUTION_ID"), producer=producer or {})
    temporary = folder / f".{uuid4().hex}.tmp"
    try:
        temporary.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        # Publish a complete record atomically without replacing an existing ID.
        # Hard-link creation avoids blocking filesystem locks on shared storage.
        try:
            os.link(temporary, folder / f"{result_id}.json")
        except FileExistsError:
            raise ValueError(f"Result {result_id!r} already exists; publish a new ID instead of overwriting it.") from None
    finally:
        temporary.unlink(missing_ok=True)
    from .trace import capture_result
    capture_result(directory, folder / f"{result_id}.json")
    return f"$ref:{result_id}"


def publish_result(result_id, outputs):
    """Publish custom named outputs immediately; return their root $ref.

    Registration records data, not scientific validation. Pass Path objects or
    absolute file paths for artifacts. Existing IDs cannot be replaced.
    """
    return _publish(result_id, outputs)


def register_tool_result(name, result, arguments, response_path):
    """Called by the common tool entry point only inside a CodeAct session."""
    if not os.environ.get("MRCAT_SESSION_DIR"):
        return
    outputs = result.get("outputs") or {}
    details = result.get("details") or {}
    return _publish(name, outputs, automatic=True,
        status=outputs.get("status") or details.get("result_status") or "unknown",
        producer=dict(tool=name, arguments=arguments, response_path=str(response_path)))


def resolve_ref(reference):
    """Resolve a local $ref or an explicit same-session $taskref, without an LLM."""
    directory, scope = _runtime()
    return read_reference(directory, scope, reference)


def invalidated_executions(directory, scope):
    path = _scope_directory(directory, scope) / '.invalidated'
    return json.loads(path.read_text()) if path.exists() else {}


def read_reference(directory, scope, reference):
    """Resolve the same saved binding from the host or an executing cell."""
    if not isinstance(reference, str):
        raise TypeError("A result reference must be a string.")
    if reference.startswith("$taskref:"):
        parts = reference[len("$taskref:"):].split("/")
        if len(parts) < 2:
            raise ValueError(f"Invalid result reference: {reference}")
        scope, result_id, *path = parts
    elif reference.startswith("$ref:"):
        result_id, *path = reference[len("$ref:"):].split("/")
    else:
        raise ValueError("Use $ref:<result_id>/<field> or $taskref:<scope>/<result_id>/<field>.")
    if not _NAME.fullmatch(scope) or not _NAME.fullmatch(result_id) or any(not p for p in path):
        raise ValueError(f"Invalid result reference: {reference}")
    try:
        entry = json.loads((_scope_directory(directory, scope) / f"{result_id}.json").read_text())
    except FileNotFoundError:
        raise ValueError(f"Unresolved result reference: {reference}. Use an existing entry in result_refs.") from None
    if entry.get('execution_id') in invalidated_executions(directory, scope):
        raise ValueError(f'Result {reference} was invalidated by Review; use the repaired producer result.')
    if entry["status"] in {"blocked", "failed", "error"}:
        raise ValueError(f"Result {reference} has status {entry['status']}; inspect its response before repair.")
    value = entry["outputs"]
    for segment in path:
        if isinstance(value, dict) and segment in value:
            value = value[segment]
        elif isinstance(value, list) and segment.isdigit() and int(segment) < len(value):
            value = value[int(segment)]
        else:
            raise ValueError(f"Missing output field in reference: {reference}")
    return deepcopy(value)


def resolve_inputs(value):
    """Resolve references recursively in tool arguments, preserving ordinary values."""
    if isinstance(value, str) and value.startswith(("$ref:", "$taskref:")):
        return resolve_ref(value)
    if isinstance(value, dict):
        return {key: resolve_inputs(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [resolve_inputs(item) for item in value]
    return value


def _identity(arguments):
    """Show source identity without replaying complete study metadata or payloads."""
    labels = {}
    def visit(value, prefix=""):
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            label = f"{prefix}.{key}" if prefix else key
            if isinstance(item, dict):
                visit(item, label)
            elif key in {"study_id", "source", "trait", "label"} or key.endswith("_path"):
                if isinstance(item, (str, int, float)):
                    labels[label] = str(item)[:240]
    visit(arguments)
    return dict(list(labels.items())[:8])


def result_catalog(directory, scope, *, include_scopes=(), execution_id=None):
    """Host projection rebuilt from disk, independent of conversational memory."""
    rows = []
    for source_scope in dict.fromkeys([scope, *include_scopes]):
        invalidated = invalidated_executions(directory, source_scope)
        files = _scope_directory(directory, source_scope).glob("*.json")
        entries = [(path.stem, json.loads(path.read_text())) for path in files]
        for result_id, entry in sorted(entries, key=lambda item: (item[1]["created_at"], item[0])):
            if entry.get('execution_id') in invalidated:
                continue
            if execution_id is not None and entry.get("execution_id") != execution_id:
                continue
            ref = (f"$ref:{result_id}" if source_scope == scope
                   else f"$taskref:{source_scope}/{result_id}")
            producer = entry.get("producer", {})
            rows.append(dict(ref=ref, fields=list(entry["outputs"]), status=entry["status"],
                tool=producer.get("tool", "custom_code"),
                input_identity=_identity(producer.get("arguments", {})),
                response_path=producer.get("response_path")))
    return rows
