"""Read-only planning evidence from existing tasks and tool response files.

This index does not select inputs, compile bindings or declare scientific success.
Custom code artifacts remain visible even without a standard tool response.
"""
import json
from pathlib import Path
from . import memory
from .plan_items import reusable_results


def result_index(work, directory, skills):
    directory = Path(directory).resolve()
    artifacts = list(dict.fromkeys(work.get('artifacts', [])))
    responses = [ref for ref in artifacts if Path(ref).name == 'response.json']
    results = []
    for ref in responses[-16:]:
        path = (directory / ref).resolve()
        entry = dict(response_path=ref)
        results.append(entry)
        if not path.is_relative_to(directory):
            entry['availability'] = 'outside_session; not inspected'
            continue
        try:
            if path.stat().st_size > 256_000:
                entry['availability'] = 'large response; inspect on demand'
                continue
            data = json.loads(path.read_text())
            outputs = data.get('outputs') if isinstance(data, dict) else None
            if not isinstance(outputs, dict):
                entry['availability'] = 'unrecognized response; inspect on demand'
                continue
            entry.update(availability='response exists', reported_status=outputs.get('status'), outputs=[])
            for name, payload in outputs.items():
                if name == 'status' or not isinstance(payload, dict):
                    continue
                producers = [s for s in skills.list_bundles() if s.produces == name]
                keys = set(key for s in producers for key in s.reusable_outputs)
                keys.update(('label', 'exposure_label', 'outcome_label', 'ancestry', 'input_scale', 'study_id', 'source'))
                fields = {key: (memory.excerpt(json.dumps(payload[key], ensure_ascii=False), 1200)
                                if isinstance(payload[key], (dict, list)) else payload[key])
                          for key in sorted(keys) if key in payload}
                files = {}
                for key, value in fields.items():
                    if key.endswith('_path') and isinstance(value, str) and value:
                        candidate = Path(value)
                        candidate = candidate if candidate.is_absolute() else directory / candidate
                        files[key] = candidate.is_file()
                entry['outputs'].append(dict(output=name, compatible_producers=[s.id for s in producers],
                                              fields=fields, referenced_files_exist=files))
        except (OSError, ValueError, TypeError):
            entry['availability'] = 'missing or unreadable response'
    return dict(results=results, omitted_response_count=max(0, len(responses)-16),
                artifact_refs=artifacts[-24:], artifact_count=len(artifacts))


def planning_history(state, directory, skills, *, references=()):
    selected = {t['task_id'] for t in memory.referenced_tasks(state['task_history'], *references)}
    reference_text = "\n".join(str(value or "") for value in references)

    def work_view(work, *, expanded=False):
        refs = work.get('artifacts', [])
        expanded = expanded or any(ref and ref in reference_text for ref in refs)
        index = result_index(work, directory, skills) if expanded else dict(
            artifact_refs=refs[-8:], artifact_count=len(refs), detail='Read referenced artifacts when executing.')
        return dict(request=memory.excerpt(work.get('request', ''), 350), status=work.get('status', ''), **index)

    def task_view(task, *, expanded=False):
        return dict(task_id=task['task_id'], reusable_results=reusable_results(task), **work_view(task, expanded=expanded))

    return dict(
        active_task=task_view(state['active_task'], expanded=True) if state.get('active_task') else None,
        task_history=[task_view(task, expanded=task['task_id'] in selected) for task in state['task_history']],
        role_results={name: dict(**work_view(work), history=[work_view(old) for old in work.get('history', [])])
                      for name, work in state.get('role_memory', {}).items()
                      if work.get('artifacts') or work.get('history')},
        history_access='mrcat.tools.session_history(start=0, limit=50)',
        evidence_note='History is a compact directory. Only explicitly referenced tasks/artifacts and the active task '
                      'have expanded result records. Missing detail is not a missing result. Name the source task and '
                      'saved artifact in the text Plan; executor reads it when needed. Reported status and file existence '
                      'do not establish scientific approval. Match study, direction, population and method compatibility.')
