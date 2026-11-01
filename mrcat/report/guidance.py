"""Load interpretation rules owned by the Skills represented in report evidence."""
from pathlib import Path
import re


def _strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)
    elif isinstance(value, str):
        yield value


def skill_interpretation_guidance(root, selected_steps, available_steps=()):
    selected_steps = list(selected_steps)
    producers = {}
    for step in [*available_steps, *selected_steps]:
        if step.get('status') != 'completed':
            continue
        for record in step.get('outputs', {}).values():
            if isinstance(record, dict) and record.get('result_record_path'):
                producers.setdefault(record['result_record_path'], []).append(step)

    # Aggregations can embed producer records without selecting their steps
    # separately. Follow actual record paths, never infer methods from filenames.
    pending = selected_steps.copy()
    seen, skill_ids = set(), set()
    while pending:
        step = pending.pop()
        if id(step) in seen or step.get('status') != 'completed':
            continue
        seen.add(id(step))
        skill_ids.add(step.get('skill_id'))
        for value in _strings(step.get('outputs', {})):
            pending.extend(producers.get(value, []))

    root = Path(root)
    guidance = []
    for path in sorted((root / 'skills').glob('*/SKILL.md')):
        if path.parent.name not in skill_ids:
            continue
        sections = []
        for match in re.finditer(r'(?ms)^## ([^\n]+)\n(.*?)(?=^## |\Z)', path.read_text(encoding='utf-8')):
            title, body = match.groups()
            if 'interpret' in title.lower() and title.lower() != 'interpretation by the agent':
                sections.append(f'## {title}\n{body.strip()}')
        if sections:
            guidance.append(dict(skill_id=path.parent.name, source=str(path.relative_to(root)),
                                 content='\n\n'.join(sections)))
    return guidance
