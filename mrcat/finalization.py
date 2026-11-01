"""Render result values from saved evidence, independently of model prose."""
from collections import Counter
import json
import math
import re
from pathlib import Path

from . import memory
from .results import invalidated_executions


_SLOT = re.compile(r'\{\{value:([^{}\r\n]+)\}\}')
_NUMBER = re.compile(r'(?<![A-Za-z0-9_])[-+−]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])')


def result_sources(agent, state):
    """Read only task-owned records and explicitly reused tasks; never handoffs.

    Packaged methods retain their existing result schema. Custom published
    outputs may have any JSON shape; publication is not scientific approval.
    """
    directory = agent.store.directory(state['session_id']).resolve()
    task = state['active_task']
    works = [task, *memory.referenced_tasks(state['task_history'], task['request'], task['plan'])]
    sources, seen = [], set()

    def read(path):
        path = (directory / path).resolve()
        if not path.is_relative_to(directory) or path.stat().st_size > 2_000_000:
            raise ValueError('Result is outside the session or too large for inline delivery.')
        return path, json.loads(path.read_text())

    def add(path, data, *, pointer='', status='unverified', execution_id=None):
        key = (str(path), pointer)
        if key in seen:
            return
        seen.add(key)
        sources.append(dict(id=f'r{len(sources)+1}', path=str(path.relative_to(directory)),
                            pointer=pointer, status=status, execution_id=execution_id, data=data))

    def unavailable(ref, error):
        # A missing known result must not silently disable numerical validation.
        sources.append(dict(id=f'r{len(sources)+1}', path=str(ref), data=None,
                            status='unavailable', availability=type(error).__name__))

    for work in works:
        invalidated = invalidated_executions(directory, work['task_id'])
        # Direct result records are authoritative; response payloads below are
        # used only when they do not point to a separate record.
        for ref in sorted(set(work.get('artifacts', []))):
            if not Path(ref).name.endswith('result_record.json'):
                continue
            try:
                path, data = read(ref)
                add(path, data)
            except (OSError, ValueError) as exc:
                unavailable(ref, exc)
        for ref in sorted(set(work.get('artifacts', []))):
            if Path(ref).name != 'response.json':
                continue
            try:
                path, response = read(ref)
                outputs = response.get('outputs', {})
                if not isinstance(outputs, dict):
                    continue
                status = outputs.get('status', 'unknown')
                if status in {'blocked', 'failed', 'error'}:
                    continue
                for name, data in outputs.items():
                    if not isinstance(data, dict) or not isinstance(data.get('methods'), list):
                        continue
                    target = data.get('result_record_path')
                    if target:
                        record_path, record = read(target)
                        add(record_path, record, status=status)
                    else:
                        add(path, data, pointer=f'/outputs/{name}', status=status)
            except (OSError, ValueError, AttributeError) as exc:
                unavailable(ref, exc)
        # Custom CodeAct outputs need no method registration or MR-specific schema.
        for path in sorted((directory / 'results' / work['task_id']).glob('*.json')):
            try:
                path, entry = read(path)
                if entry.get('execution_id') in invalidated:
                    continue
                if entry.get('producer', {}).get('tool'):
                    continue  # Packaged results are read from their actual records above.
                add(path, entry['outputs'], pointer='/outputs', status=entry.get('status', 'unverified'),
                    execution_id=entry.get('execution_id'))
            except (OSError, ValueError, KeyError, AttributeError) as exc:
                unavailable(path, exc)
    return sources


def _value(source, segments):
    value = source['data']
    for segment in segments:
        key = segment.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            raise ValueError('Unknown result field: ' + '/'.join(segments))
    return value


def _cell(value):
    text = json.dumps(value, ensure_ascii=False, allow_nan=False) if not isinstance(value, str) else value
    return text.replace('|', '\\|').replace('\n', ' ')


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(value):
    # Tables use six significant digits; scalar slots and source records stay exact.
    return format(value, '.6g') if _finite(value) else '—'


def _ci(value):
    """Format recorded intervals without estimating bounds or dropping extra ranges."""
    if not isinstance(value, dict):
        return value if isinstance(value, str) else '—'
    ranges = value.get('ranges')
    if not isinstance(ranges, list) or not ranges or any(
            not isinstance(interval, dict) or not _finite(interval.get('lower'))
            or not _finite(interval.get('upper')) or interval['lower'] > interval['upper']
            for interval in ranges):
        return '—'
    text = ' ∪ '.join(f"[{_number(interval['lower'])}, {_number(interval['upper'])}]" for interval in ranges)
    level = value.get('level')
    if _finite(level) and 0 < level < 1:
        text += f' ({level * 100:g}%)'
    return text


def _method_table(rows):
    """Keep scientific estimates in the table and recorded settings in short notes."""
    columns = [('method', 'Method'), ('beta.hat', 'Beta'), ('ci', 'CI'),
               ('se', 'SE'), ('pval', 'P value'), ('nsnp', 'SNPs')]
    show_se = any(row.get('se') is not None for row in rows) and any(_ci(row.get('ci')) == '—' for row in rows)
    columns = [(key, label) for key, label in columns if key != 'se' or show_se]
    lines = ['| ' + ' | '.join(label for _, label in columns) + ' |',
             '| ' + ' | '.join('---' for _ in columns) + ' |']
    counts = Counter(row.get('method') for row in rows)
    settings = {}
    for row in rows:
        method = row.get('method', '—')
        label = row.get('display_label') if counts[method] > 1 else None
        values = dict(row, method=label or method)
        values['beta.hat'] = row.get('beta.hat', row.get('beta'))
        values['pval'] = row.get('pval', row.get('pvalue'))
        values['ci'] = _ci(row.get('ci'))
        for key in ('beta.hat', 'se', 'pval'):
            values[key] = _number(values.get(key))
        lines.append('| ' + ' | '.join(_cell(values[key]) if values.get(key) is not None else '—'
                                      for key, _ in columns) + ' |')
        selection, threshold = row.get('selection_threshold'), row.get('Threshold')
        if _finite(selection):
            settings.setdefault(('Instrument selection P threshold', selection), []).append(label or method)
        if _finite(threshold) and (method == 'MR-APSS' or threshold != selection):
            name = 'MR-APSS selection-bias correction threshold' if method == 'MR-APSS' else 'Recorded method threshold'
            settings.setdefault((name, threshold), []).append(label or method)
    for (name, value), methods in settings.items():
        context = '' if name.startswith('MR-APSS ') else f" ({', '.join(dict.fromkeys(methods))})"
        lines += ['', f"{name}{context}: {_cell(value)}."]
    return lines


def format_saved_summary(summary):
    """Read-only presentation of saved MRCAT MR tables; never rewrite evidence.

    Only the generated Method/Beta table is changed. Prose, links, code blocks,
    custom tables and already formatted summaries remain as saved.
    """
    if not summary or '| Method |' not in summary:
        return summary
    labels = {'Method': 'method', 'Beta': 'beta.hat', 'SE': 'se', 'P value': 'pval',
              'SNPs': 'nsnp', 'CI': 'ci', 'Instrument selection P threshold': 'Threshold'}
    technical = {'display_label', 'source_result_path', 'endpoint', 'input_scale',
                 'Instrument selection P threshold', 'selection_threshold'}

    def cells(line):
        return [cell.strip().replace('\\|', '|') for cell in re.split(r'(?<!\\)\|', line.strip()[1:-1])]

    def value(cell):
        if cell in {'—', 'null'}:
            return None
        try:
            return json.loads(cell)
        except ValueError:
            return cell

    lines, result, index, fence = summary.splitlines(keepends=True), [], 0, None
    while index < len(lines):
        line = lines[index]
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            kind = marker[1][0]
            fence = None if fence == kind else fence or kind
        if not fence and line.strip().startswith('| Method |') and index + 1 < len(lines):
            headers = cells(line)
            if 'Beta' in headers and all(re.fullmatch(r':?-+:?', cell) for cell in cells(lines[index + 1])):
                end, rows = index + 2, []
                while end < len(lines) and lines[end].strip().startswith('|') and lines[end].strip().endswith('|'):
                    parts = cells(lines[end])
                    if len(parts) != len(headers):
                        rows = []
                        break
                    rows.append({labels.get(key, key): value(cell) for key, cell in zip(headers, parts)})
                    end += 1
                if rows and (technical.intersection(headers) or any(isinstance(row.get('ci'), dict) for row in rows)):
                    result.append('\n'.join(_method_table(rows)) + ('\n' if lines[end - 1].endswith('\n') else ''))
                    index = end
                    continue
        result.append(line)
        index += 1
    return ''.join(result)


def render_summary(summary, sources, *, status):
    """Resolve source-bound slots; reject hand-written numbers before saving.

    This preserves numerical provenance, not the scientific validity of a fit
    or the meaning of the surrounding prose. Unknown references never fall back
    to a handoff, another method, or a previous task.
    """
    index = {source['id']: source for source in sources}
    matches = list(_SLOT.finditer(summary))
    prose = _SLOT.sub('', summary)
    if '{{' in prose or '}}' in prose:
        raise ValueError('Unresolved final result placeholder.')
    if sources:
        # Link destinations are identifiers, not statistical claims. Link labels
        # and inline code remain checked. Numbered-list ordinals are layout only.
        prose = re.sub(r'(!?\[[^\]]*\])\([^\n]*?\)', r'\1', prose)
        prose = re.sub(r'(?m)^\s*\d+[.)]\s+', '', prose)
        # The documented input-SE formula is explanatory notation, not a
        # fitted numerical claim; accept its plain-text and LaTeX spellings.
        prose = re.sub(r'(?<![\w.])1\s*/\s*(?:sqrt\(N\)|√N|\\sqrt\{N\})', '', prose)
        # Recorded alphanumeric identifiers are labels, not fitted numbers.
        # Do not exempt arbitrary code spans or unknown IDs from validation.
        def identifiers(value):
            if isinstance(value, dict):
                for child in value.values():
                    yield from identifiers(child)
            elif isinstance(value, list):
                for child in value:
                    yield from identifiers(child)
            elif isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', value) and any(c.isdigit() for c in value):
                yield value
        for label in sorted(set(identifiers([source['data'] for source in sources])), key=len, reverse=True):
            prose = re.sub(r'(?<![\w.-])' + re.escape(label) + r'(?![\w.-])', '', prose)
        numbers = _NUMBER.findall(prose)
        if numbers:
            raise ValueError('Use {{value:source/field}} for numerical claims; unsupported literal(s): '
                             + ', '.join(numbers[:8]))
        if status == 'completed' and not matches:
            raise ValueError('Include a source-bound result value for a completed numerical analysis.')

    def replace(match):
        reference = match.group(1)
        result_id, *segments = reference.split('/')
        if result_id not in index:
            raise ValueError('Unknown final result source: ' + result_id)
        source = index[result_id]
        if source.get('status') in {'unavailable', 'blocked', 'failed', 'error'}:
            raise ValueError('Result source is unavailable or failed: ' + result_id)
        value = _value(source, segments)
        if isinstance(value, (dict, list)) or value is None:
            raise ValueError('A value slot must reference a non-null scalar result field.')
        return _cell(value)

    rendered = _SLOT.sub(replace, summary)
    return rendered
