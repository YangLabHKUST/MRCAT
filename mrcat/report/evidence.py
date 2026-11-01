"""Read report evidence from completed MRCAT items and durable result bindings."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json

from ..results import read_reference, invalidated_executions
from .guidance import skill_interpretation_guidance
from .policy import (ReportNotApplicable, add_required_report_evidence,
                     _catalog_plot_metadata, _collect_session_report_figures)


def session_evidence(state, directory):
    directory = Path(directory)
    tasks = {t['task_id']: t for t in state.get('task_history', [])}
    if state.get('active_task'):
        tasks[state['active_task']['task_id']] = state['active_task']
    rows = []
    for task in tasks.values():
        invalid = invalidated_executions(directory, task['task_id'])
        steps = []
        for step_id, completed in task.get('completed_items', {}).items():
            if any(execution in invalid for execution in completed.get('execution_ids', [])):
                continue
            item = completed['item']
            outputs, sources, errors = {}, [], []
            for name, binding in completed.get('outputs', {}).items():
                try:
                    outputs[name] = read_reference(directory, task['task_id'], binding['ref'])
                    sources.append(result_source(directory, task['task_id'], name, binding))
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    errors.append(str(exc))
            # A revoked, missing or failed binding cannot become report evidence.
            if errors or not outputs:
                continue
            steps.append(dict(step_ref=f"{task['task_id']}/{step_id}", step_id=step_id,
                skill_id=item.get('skill_id'), title=item['title'], status='completed',
                is_mr=not item.get('skill_id') or item['skill_id'].startswith(('mr-', 'analysis-')),
                reuse_from=item.get('reuse_from', []), result_names=sorted(outputs),
                runtime_summary=completed.get('summary', ''), outputs=outputs, sources=sources,
                figures=_catalog_plot_metadata(outputs)))
        if steps:
            rows.append(dict(task_id=task['task_id'], status=task['status'],
                             user_goal=task['request'], steps=steps))
    return rows


def result_source(directory, scope, name, binding):
    # read_reference has already checked the reference and invalidation status.
    reference = binding['ref']
    if reference.startswith('$taskref:'):
        scope, result_id, *_ = reference[len('$taskref:'):].split('/')
    else:
        result_id = reference[len('$ref:'):].split('/')[0]
    entry = json.loads((directory / 'results' / scope / f'{result_id}.json').read_text())
    producer = deepcopy(entry.get('producer', {}))
    source = dict(name=name, ref=reference, execution_id=entry.get('execution_id'), producer=producer)
    response_path = producer.get('response_path')
    if response_path:
        try:
            response = json.loads(Path(response_path).read_text())
            source['diagnostics'] = response.get('details', {})
        except (OSError, ValueError):
            source['diagnostics_unavailable'] = True
    return source


def evidence_catalog(rows, state):
    return dict(session_id=state['session_id'], current_question=state['request'], tasks=[
        dict(task_id=t['task_id'], status=t['status'], user_goal=t['user_goal'],
             steps=[{k: v for k, v in step.items() if k not in {'outputs', 'sources'}} for step in t['steps']])
        for t in rows])


def fingerprint(rows, root, request):
    # Match the old continuation policy: evidence or writing-policy changes restart.
    files = {}
    def visit(value):
        if isinstance(value, dict):
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
        elif isinstance(value, str) and value.startswith('/'):
            path = Path(value)
            try:
                stat = path.stat()
                files[value] = [stat.st_size, stat.st_mtime_ns]
            except OSError:
                files[value] = None
    visit(rows)
    prompts = {p.name: p.read_text() for p in (Path(root) / 'mrcat/prompts').glob('report*.md')}
    prompts['report.md'] = (Path(root) / 'mrcat/prompts/report.md').read_text()
    steps = [step for task in rows for step in task['steps']]
    guidance = skill_interpretation_guidance(root, steps)
    return hashlib.sha256(json.dumps([rows, files, prompts, guidance, request], sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def select_evidence(reporter, state, data, execution):
    rows = data['available_evidence']
    catalog = evidence_catalog(rows, state)
    selection = execution.call('evidence_selection', reporter.select_session_report_evidence, catalog=catalog)
    selected = set(selection['selected_step_refs'])
    by_ref = {step['step_ref']: step for task in rows for step in task['steps']}
    added_qc = set()
    conflicts = []
    while True:
        previous = set(selected)
        selection['selected_step_refs'] = sorted(selected)
        selection = add_required_report_evidence(catalog=catalog, selection=selection)
        added_qc.update(selection['required_step_refs_added'])
        selected.update(selection['selected_step_refs'])
        for ref in list(selected):
            for source in by_ref[ref]['reuse_from']:
                upstream = '/'.join(source.split('/')[:2])
                if upstream in by_ref:
                    selected.add(upstream)
                else:
                    conflict = dict(step_id=ref, source=source, issue='Reused evidence is missing or invalidated.')
                    if conflict not in conflicts:
                        conflicts.append(conflict)
        if selected == previous:
            break
    selection['selected_step_refs'] = sorted(selected)
    selection['required_step_refs_added'] = sorted(added_qc)
    selection['available_step_refs'] = sorted(by_ref)
    data['report_selection'] = selection
    tasks, scientific, workflow, goals = [], [], [], []
    for task in rows:
        steps = [s for s in task['steps'] if s['step_ref'] in selected]
        if not steps:
            continue
        goals.append(dict(task_id=task['task_id'], user_goal=task['user_goal']))
        projected = dict(task_id=task['task_id'], plan={'items': []}, step_outputs={})
        for step in steps:
            projected['plan']['items'].append(dict(item_id=step['step_id'], skill_id=step['skill_id']))
            projected['step_outputs'][step['step_id']] = deepcopy(step['outputs'])
            scientific.append(dict(step_id=step['step_ref'], task_id=task['task_id'],
                task_status=task['status'], skill_id=step['skill_id'] or 'custom', status=step['status'],
                runtime_summary=step['runtime_summary'], structured_outputs=step['outputs'], sources=step['sources']))
            workflow.append(dict(step_id=step['step_ref'], skill_id=step['skill_id'], title=step['title'], status=step['status']))
        tasks.append(projected)
    if not tasks:
        raise ReportNotApplicable('No saved MR results are available for the requested report.')
    figures, assets = _collect_session_report_figures(tasks)
    data.update(figure_catalog=figures, figure_assets={key: str(path) for key, path in assets.items()},
        report_context=dict(task_contract=dict(user_question=state['request'], selected_task_goals=goals),
            workflow_completion=workflow,
            selected_studies={row['step_id']: row['structured_outputs'] for row in scientific
                              if row['skill_id'] in {'gwas-select', 'gwas-download', 'gwas-qc'}},
            step_evidence=scientific,
            mr_evidence=dict(applies=True, task_results=[row for row in scientific
                if row['skill_id'].startswith(('mr-', 'analysis-')) or row['skill_id']=='custom']),
            evidence_conflicts=conflicts,
            skill_interpretation_guidance=skill_interpretation_guidance(
                reporter.agent.root, [by_ref[ref] for ref in sorted(selected)], by_ref.values())))
