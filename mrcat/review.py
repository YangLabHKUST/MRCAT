"""Read task evidence and relevant guide requirements, without running analysis."""
import json
import re
from pathlib import Path
from . import memory
from .results import invalidated_executions


def compact(value, depth=0):
    if depth > 5:
        return '[Nested content omitted; inspect the source if required.]'
    if isinstance(value, dict):
        return {k: compact(v, depth+1) for k, v in value.items()}
    if isinstance(value, list):
        return [compact(v, depth+1) for v in value[:8]] + ([f'[{len(value)-8} more entries]'] if len(value)>8 else [])
    if isinstance(value, str):
        return memory.excerpt(value, 900)
    return value


def evidence_context(agent, state):
    task = state['active_task']
    directory = agent.store.directory(state['session_id'])
    events = [e for e in state['events'][task.get('event_start', 0):]
              if e.get('details', {}).get('task_id') == task['task_id']]
    executions = [e['details'] for e in events if e['type'] == 'code_execution']
    invalidated = invalidated_executions(directory, task['task_id'])
    # Cover early input/QC operations as well as the final method. Do not silently
    # hide omitted evidence or interpret file presence as scientific approval.
    per_call = max(600, min(2400, 22000 // max(1, len(executions))))
    rows = []
    for details in executions:
        tool_call = any(Path(ref).name == 'response.json' for ref in details.get('generated_files', []))
        # Tool records below contain numerical/metadata evidence. Avoid duplicating
        # their long printed JSON and generated-file inventories in every trace.
        observed = {key: details.get(key) for key in ('execution_id', 'status', 'returncode',
                    'stdout_path', 'stderr_path', 'source_path', 'result_refs')}
        observed['stdout'] = memory.excerpt(details.get('stdout', ''), 650 if tool_call else per_call)
        observed['stderr'] = memory.excerpt(details.get('stderr', ''), 450 if tool_call else 900)
        if details.get('execution_id') in invalidated:
            observed['invalidated_reason'] = invalidated[details['execution_id']]
        rows.append(dict(code=memory.excerpt(details.get('code', ''), 800 if tool_call else 1200), observation=observed))
    guides = list(dict.fromkeys([e['content'] for e in events if e['type'] == 'skill_loaded']))
    if task.get('guide') and task['guide'] not in guides:
        guides.append(task['guide'])
    requirements = []
    for name in guides:
        skill = agent.skills.get(name)
        if not skill:
            continue
        # Existing Markdown is the source of truth; no second scientific schema.
        sections = re.split(r'(?m)^## ', skill.instruction_body)
        relevant = [s for s in sections[1:] if any(w in s.split('\n', 1)[0].lower()
                    for w in ('input', 'check', 'interpret', 'reference', 'read and decide', 'preserve', 'recovery'))]
        text = re.sub(r'```.*?```', '', '\n\n'.join(relevant), flags=re.S)
        requirements.append(dict(skill=name, path=str(skill.skill_dir/'SKILL.md'),
                                 requirements=memory.excerpt(text, 6000)))
    works = [task, *memory.referenced_tasks(state['task_history'], task['request'], task['plan'])]
    records = []
    seen = set()
    for work in works:
        for ref in work.get('artifacts', []):
            if Path(ref).name != 'response.json' or ref in seen:
                continue
            seen.add(ref)
            path = (directory/ref).resolve()
            record = dict(task_id=work['task_id'], path=ref)
            records.append(record)
            if not path.is_relative_to(directory.resolve()):
                record['availability'] = 'Outside this session; not read.'
                continue
            try:
                if path.stat().st_size > 256000:
                    record['availability'] = 'Large response; request a targeted inspection if needed.'
                    continue
                data = json.loads(path.read_text())
                # Keep status, method outputs and warnings; the artifact directory
                # and full presentation text remain in the saved response.
                if isinstance(data, dict):
                    data = {key: value for key, value in data.items() if key != 'artifacts'}
                    if isinstance(data.get('summary'), str):
                        data['summary'] = memory.excerpt(data['summary'], 400)
                record['content'] = memory.excerpt(json.dumps(compact(data), ensure_ascii=False), 2800)
                inputs = []
                for source in sorted(path.parent.glob('*_input.json'))[:4]:
                    if source.resolve().is_relative_to(directory.resolve()) and source.stat().st_size <= 32000:
                        inputs.append(dict(path=str(source.relative_to(directory)), content=compact(json.loads(source.read_text()))))
                record['inputs'] = memory.excerpt(json.dumps(inputs, ensure_ascii=False), 1200)
            except (OSError, ValueError) as exc:
                record['availability'] = f'Unreadable response: {type(exc).__name__}'
    return dict(executions=rows, execution_count=len(executions), skill_requirements=requirements,
                tool_records=records, artifacts=task.get('artifacts', [])[-16:],
                artifact_count=len(task.get('artifacts', [])), artifact_index=str(directory/'results'),
                evidence_limits='Excerpts are not complete files. Missing evidence requires targeted inspection; tool status and filenames do not prove scientific validity.')
