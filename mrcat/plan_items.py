"""Ordered planning guidance and associations with actual saved results."""
from copy import deepcopy
import json
from pathlib import Path
import re

from .results import read_reference

_ID = re.compile(r'[a-z][a-z0-9_]*')
FIELDS = ('step_id', 'title', 'skill_id', 'reuse_from')


def validate_invalidation(task, steps):
    if (not isinstance(steps, list) or any(not isinstance(step, str) for step in steps)
            or len(set(steps)) != len(steps)
            or any(step not in task.get('completed_items', {}) for step in steps)):
        raise ValueError('invalidate_steps must list distinct completed step IDs from this task.')


def recovery_view(task, steps, reason, directory):
    """Preview reopening invalid producers without mutating the running task."""
    validate_invalidation(task, steps)
    revised = deepcopy(task)
    for step in steps:
        completed = revised['completed_items'].pop(step)
        artifacts = set()
        for execution_id in completed.get('execution_ids', []):
            path = Path(directory) / 'executions' / execution_id / 'observation.json'
            if path.exists():
                artifacts.update(json.loads(path.read_text()).get('generated_files', []))
            artifacts.update(ref for ref in revised.get('artifacts', []) if execution_id in Path(ref).parts)
        revised['artifacts'] = [ref for ref in revised.get('artifacts', []) if ref not in artifacts]
        revised.setdefault('invalidated_items', []).append(dict(
            step_id=step, completed=completed, reason=reason, artifacts=sorted(artifacts)))
    return revised


def apply_invalidation(task, steps, reason, directory):
    """Retain files and publications, but revoke their active bindings and reuse."""
    if not steps:
        return
    from .results import invalidated_executions
    from .store import write_json
    revised = recovery_view(task, steps, reason, directory)
    executions = invalidated_executions(directory, task['task_id'])
    for step in steps:
        for execution_id in task['completed_items'][step].get('execution_ids', []):
            executions[execution_id] = reason
    write_json(Path(directory) / 'results' / task['task_id'] / '.invalidated', executions)
    for key in ('completed_items', 'invalidated_items', 'artifacts'):
        task[key] = revised[key]


def parse_plan(raw, completed=None):
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {'plan_items'} or not isinstance(data['plan_items'], list) or not data['plan_items']:
        raise ValueError('Return {"plan_items": [...]} with a nonempty ordered list.')
    completed = completed or {}
    seen = set()
    for item in data['plan_items']:
        if not isinstance(item, dict) or set(item) != set(FIELDS):
            raise ValueError('Each item needs only step_id, title, skill_id, reuse_from.')
        name = item['step_id']
        if not isinstance(name, str) or not _ID.fullmatch(name) or name in seen:
            raise ValueError('Step IDs must be unique lowercase snake_case identifiers.')
        if not isinstance(item['title'], str) or not item['title'].strip():
            raise ValueError('Each item needs a concrete title describing its intent.')
        if item['skill_id'] is not None and (not isinstance(item['skill_id'], str) or not item['skill_id'].strip()):
            raise ValueError('skill_id must name a skill or be null for custom code.')
        reuse = item['reuse_from']
        if not isinstance(reuse, list) or any(not isinstance(ref, str) or len(ref.split('/')) != 3
                or any(not part for part in ref.split('/')) for ref in reuse):
            raise ValueError('reuse_from must list task_id/step_id/output_name sources.')
        if len(set(reuse)) != len(reuse):
            raise ValueError('reuse_from must not contain duplicate sources.')
        if name in completed and item != completed[name].get('item'):
            raise ValueError('Completed items are immutable; use a new step_id for changed work: ' + name)
        seen.add(name)
    text = '\n'.join(f"{i}. [{item['step_id']}] {item['title']}" +
                     (f" (Reuse: {', '.join(item['reuse_from'])})" if item['reuse_from'] else '')
                     for i, item in enumerate(data['plan_items'], 1))
    return dict(text=text, items=data['plan_items'])


def current_item(task):
    return next((item for item in task.get('plan_items', [])
                 if item['step_id'] not in task.get('completed_items', {})), None)


def item_publications(task, directory):
    ids = set(task.get('item_execution_ids', []))
    rows = []
    for path in (Path(directory) / 'results' / task['task_id']).glob('*.json'):
        entry = json.loads(path.read_text())
        if entry.get('execution_id') in ids:
            rows.append((path.stem, entry))
    return sorted(rows, key=lambda row: row[1]['created_at'])


def complete_item(task, directory, handoff):
    """Record actual publications after tool success or custom Review acceptance."""
    item = current_item(task)
    bindings = {}
    for result_id, entry in item_publications(task, directory):
        if entry['status'] not in {'ok', 'unverified'}:
            continue
        if entry.get('producer', {}).get('tool'):
            for output in entry['outputs']:
                if output != 'status':
                    bindings[output] = dict(ref=f'$ref:{result_id}/{output}', execution_id=entry['execution_id'])
        else:
            bindings[result_id] = dict(ref=f'$ref:{result_id}', execution_id=entry['execution_id'])
    task['completed_items'][item['step_id']] = dict(item=deepcopy(item), outputs=bindings,
        execution_ids=list(task.get('item_execution_ids', [])), summary=handoff['body'])
    task.pop('current_item_id', None)
    task.pop('item_execution_ids', None)
    return item['step_id']


def reusable_results(task):
    """Flat lineage directory; output names come from execution, never Planner."""
    rows = []
    for step_id, completed in task.get('completed_items', {}).items():
        for name, binding in completed['outputs'].items():
            rows.append(dict(source=f"{task['task_id']}/{step_id}/{name}",
                             ref=f"$taskref:{task['task_id']}/" + binding['ref'].removeprefix('$ref:')))
    return rows


def validate_reuse(items, tasks):
    available = {row['source'] for task in tasks for row in reusable_results(task)}
    for item in items:
        for ref in item['reuse_from']:
            if ref not in available:
                raise ValueError('Reuse source is not a completed saved result: ' + ref)


def completed_results(task, directory, history=(), *, selected=()):
    """Resolve saved completed outputs for planning and execution alike."""
    from .review import compact
    rows = []
    for source in [task, *history]:
        for row in reusable_results(source):
            if source['task_id'] != task['task_id'] and row['source'] not in selected:
                continue
            ref = row['ref']
            if source['task_id'] == task['task_id']:
                ref = '$ref:' + ref.split('/', 1)[1]
            try:
                outputs = compact(read_reference(directory, task['task_id'], ref))
                rows.append(dict(source=row['source'], ref=ref, outputs=outputs))
            except (OSError, ValueError) as exc:
                rows.append(dict(source=row['source'], ref=ref, error=str(exc)))
    return rows


def executor_view(task, directory, history):
    """Full brief plan, current step, and actual results available for compilation."""
    item = current_item(task)
    rows = completed_results(task, directory, history, selected=set(item['reuse_from']) if item else set())
    return dict(current_plan=task['plan_items'], current_item=item,
                completed_item_ids=list(task.get('completed_items', {})), completed_results=rows,
                invalidated_items=[dict(step_id=row['step_id'], reason=row['reason'])
                                   for row in task.get('invalidated_items', [])])


def item_results(task, directory):
    from .review import compact
    return [dict(ref='$ref:' + result_id, status=entry['status'], outputs=compact(entry['outputs']))
            for result_id, entry in item_publications(task, directory)][-8:]
