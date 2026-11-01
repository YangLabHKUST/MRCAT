"""Coding evidence views and structured scientific review contracts."""
import json
from . import memory
from .diagnostics import redact

def _tool(name, description, properties, required):
    return dict(type='function', function=dict(name=name, description=description,
        parameters=dict(type='object', properties=properties, required=required,
                        additionalProperties=False)))


TEXT = dict(type='string')
CODING_TOOLS = [
    _tool('list', 'List a directory without recursive traversal.', dict(path=TEXT), ['path']),
    _tool('read', 'Read a bounded line range from a file.',
          dict(path=TEXT, start=dict(type='integer', minimum=1), end=dict(type='integer', minimum=1)), ['path']),
    _tool('grep', 'Search text in a specific directory or file. Bound the search with path and glob.',
          dict(pattern=TEXT, path=TEXT, glob=TEXT), ['pattern', 'path']),
    _tool('write', 'Save a script or other text in the item work directory.',
          dict(path=TEXT, content=TEXT), ['path', 'content']),
    _tool('edit', 'Replace one exact occurrence in a previously read file.',
          dict(path=TEXT, old=TEXT, new=TEXT), ['path', 'old', 'new']),
    _tool('run', 'Execute a saved script or inline source. Inspection is limited to 30 seconds. '
          'Use repair for dependency recovery, compute for the requested analysis.',
          dict(language=dict(type='string', enum=['python', 'r', 'bash']), path=TEXT, content=TEXT,
               purpose=dict(type='string', enum=['inspect', 'repair', 'compute']),
               timeout=dict(type='integer', minimum=1)), ['language', 'purpose']),
    _tool('publish', 'Publish a JSON object written by a successful execution in this item. '
          'Use the execution_id returned by run and the path of its output file.',
          dict(name=TEXT, path=TEXT, execution_id=TEXT), ['name', 'path', 'execution_id']),
    _tool('docs', 'Read a method resource note or a Skill guide. Verify installation claims in the runtime.',
          dict(id=TEXT), ['id']),
    _tool('finish', 'Submit analysis evidence, a scientific boundary, or a verified technical obstacle. '
          'Successful submission does not mean Review has accepted the item.',
          dict(outcome=dict(type='string', enum=['complete', 'blocked', 'technical_blocked']), body=TEXT),
          ['outcome', 'body']),
]


def coding_calls(message):
    """Validate the whole envelope before any tool can have side effects."""
    if not isinstance(message, dict) or message.get('role') != 'assistant':
        raise ValueError('Expected a native assistant tool call.')
    calls = message.get('tool_calls', [])
    if not isinstance(calls, list) or not calls:
        raise ValueError('Expected native tool calls.')
    ids = set()
    for call in calls:
        if (not isinstance(call, dict) or call.get('type') != 'function'
                or not isinstance(call.get('id'), str) or not call['id']):
            raise ValueError('Native call requires a function and a call ID.')
        if call['id'] in ids:
            raise ValueError('Native tool call IDs must be unique within a turn.')
        ids.add(call['id'])
    return calls


def coding_call(call):
    """Validate one call's arguments; a rejected call still receives a result."""
    function = call.get('function') or {}
    schema = next((t['function']['parameters'] for t in CODING_TOOLS
                   if t['function']['name'] == function.get('name')), None)
    if schema is None:
        raise ValueError('Unknown coding tool.')
    arguments = json.loads(function['arguments'])
    if not isinstance(arguments, dict):
        raise ValueError('Tool arguments must be an object.')
    if set(arguments) - set(schema['properties']) or set(schema['required']) - set(arguments):
        raise ValueError('Missing or unexpected tool arguments.')
    for key, value in arguments.items():
        spec = schema['properties'][key]
        if (spec['type'] == 'string' and not isinstance(value, str) or
                spec['type'] == 'integer' and type(value) is not int):
            raise ValueError(f'Invalid type for {key}.')
        if 'enum' in spec and value not in spec['enum']:
            raise ValueError(f'Invalid value for {key}.')
        if 'minimum' in spec and value < spec['minimum'] or 'maximum' in spec and value > spec['maximum']:
            raise ValueError(f'Out-of-range value for {key}.')
    return dict(tool=function['name'], **arguments)



READ_TOOLS = {'list', 'read', 'grep', 'docs'}


def observation_key(entry):
    """Match arguments AND observed output; changing data is not a repeat."""
    if entry.get('tool') not in READ_TOOLS:
        return None
    result = entry.get('result') or {}
    if result.get('ok') is None:
        return None
    return json.dumps([entry['tool'], entry.get('arguments', {}), result],
                      ensure_ascii=False, sort_keys=True)


def loop_feedback(entries):
    """Detect one- to five-action cycles across turns, independent of compaction."""
    keys = [observation_key(entry) for entry in entries[-15:]]
    for repeats in (3, 2):
        for width in range(1, 6):
            size = repeats * width
            if len(keys) < size:
                continue
            tail = keys[-size:]
            if all(key is not None for key in tail) and tail == tail[-width:] * repeats:
                action = 'Paused' if repeats == 3 else 'Change approach'
                return dict(coding_stop=repeats == 3, review_reason=(
                    f'{action}: the same {width}-action inspection cycle returned identical observations '
                    f'{repeats} times. Reuse the saved evidence and perform the next concrete verification, '
                    'repair or computation; if a prerequisite is missing, describe that obstacle.'))
    return dict(coding_stop=False, review_reason='')


def render_executor_summary(raw, token_limit):
    """Validate only the summary contract; tool evidence remains authoritative."""
    from .context import tokens
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != set(SUMMARY_FIELDS) or not all(
            isinstance(text, str) for text in value.values()):
        raise ValueError('Executor summary requires the named work-state text fields.')
    if not value['objective'].strip():
        raise ValueError('Executor summary requires a nonempty objective.')
    note = '\n\n'.join(f"### {key.replace('_', ' ').title()}\n{value[key]}" for key in SUMMARY_FIELDS)
    if tokens(note) > token_limit:
        raise ValueError('Executor summary exceeds its token budget.')
    return note


def coding_turns(entries, start=0):
    """Yield journal ranges that cannot split an assistant's calls and results."""
    index = start
    while index < len(entries):
        end = index + 1
        while end < len(entries) and entries[end].get('call_id') and not entries[end].get('assistant'):
            end += 1
        yield end, entries[index:end]
        index = end


def coding_history(entries):
    """Replay one assistant message followed by every result with its real ID."""
    entries = [entry for entry in entries if entry.get('tool') != 'history']
    latest = {}
    for entry in entries:
        key = observation_key(entry)
        if key:
            latest[key] = entry
    messages = []
    for _, turn in coding_turns(entries):
        message = turn[0].get('assistant')
        if message is None:
            # Existing checkpoints are evidence; do not invent past tool calls.
            messages.extend(dict(role='user', content=json.dumps(entry, ensure_ascii=False)) for entry in turn)
            continue
        messages.append(message)
        results = {entry.get('call_id', message['tool_calls'][0]['id']): entry for entry in turn}
        for call in message['tool_calls']:
            entry = results.get(call['id'], {})
            result = entry.get('result') or {}
            key = observation_key(entry)
            if key and latest[key] is not entry:
                result = dict(ok=result.get('ok'), repeated_observation=True,
                              latest_step=latest[key]['step'],
                              note='Identical arguments and observation; the latest matching tool turn below '
                                   'contains the output. The original observation remains in saved history.')
            if result.get('ok') is None:
                result = dict(result, ok=False, error='Tool has no final observation. Inspect saved logs; do not assume success.')
            messages.append(dict(role='tool', tool_call_id=call['id'],
                                 content=json.dumps(result, ensure_ascii=False)))
    return messages


REVIEW_TOOL = dict(type='function', function=dict(
    name='submit_review', description='Submit the scientific review of the current Custom plan item.',
    parameters=dict(type='object', properties=dict(
        route=dict(type='string', enum=['execute', 'replan', 'finalize']),
        reason=dict(type='string'), accept_item=dict(type='boolean', description=(
            'Accept a submitted complete custom item. Required for execute; optional for replan '
            'to save its result before planning the remaining work. Omit for finalize.')),
        invalidate_steps=dict(type='array', items=dict(type='string'))),
        required=['route', 'reason'], additionalProperties=False)))

SUMMARY_FIELDS = ('objective', 'decisions', 'completed', 'active', 'blockers', 'next_steps', 'references')

SUMMARY_TOOL = dict(type='function', function=dict(
    name='submit_summary', description='Summarize older coding evidence for continued work, without performing new actions.',
    parameters=dict(type='object', properties={key: dict(type='string') for key in SUMMARY_FIELDS},
                    required=list(SUMMARY_FIELDS), additionalProperties=False)))

def failed(result):
    return (result.get('status') != 'exited' or result.get('returncode') != 0 or
            any(row.get('status') in {'blocked', 'failed', 'error'}
                for row in result.get('tool_results', [])))

def tail(path, limit=6000):
    """Read bounded bytes, including for large redirected logs."""
    with path.open('rb') as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - limit))
        value = stream.read(limit).decode('utf-8', errors='replace')
    return redact(value), size > limit

def redirected_logs(directory, result):
    workspace = (directory / 'workspace').resolve()
    logs = []
    for ref in reversed(result.get('generated_files', [])):
        path = (directory / ref).resolve()
        if not path.is_relative_to(workspace) or not (
                path.suffix.lower() in {'.log', '.err', '.out'} or
                path.name.lower() in {'stderr.txt', 'stdout.txt'}):
            continue
        try:
            if not path.is_file():
                continue
            content, truncated = tail(path, 4000)
        except OSError:
            continue
        logs.append(dict(path=ref, tail=content, truncated=truncated))
        if len(logs) == 3:
            break
    return logs

def observation_view(directory, result, *, output_limit=4000):
    """Translate framework-owned paths at the model boundary, never saved data."""
    compact = dict(result)

    def absolute(value):
        return str((directory / value).resolve())

    for key in ('source_path', 'stdout_path', 'stderr_path'):
        if compact.get(key):
            compact[key] = absolute(compact[key])
    compact['generated_files'] = [absolute(p) for p in result.get('generated_files', [])]
    for key in ('tool_results', 'redirected_logs'):
        compact[key] = [dict(row, path=absolute(row['path'])) if row.get('path') else dict(row)
                        for row in result.get(key, [])]
    for key in ('stdout', 'stderr'):
        compact[key] = memory.excerpt(redact(result.get(key, '')), output_limit)
    return compact

def review_context(agent, state, flow):
    """Scientific review uses original instructions and saved evidence, not summaries."""
    from .review import evidence_context
    from .plan_items import current_item, item_results
    task = state['active_task']
    return dict(
        current_item=current_item(task), current_plan=task['plan'],
        current_results=item_results(task, agent.store.directory(state['session_id'])),
        work_request=task['request'], completed_items=task.get('completed_items', {}),
        user_updates=[m['content'] for m in memory.relevant_messages(
            state['messages'], start=task['context_start'], role='mr', task_id=task['task_id'])
            if m['role'] == 'user'],
        handoff=flow['handoff'], previous_review=task.get('evaluation'),
        initially_confirmed_plan=task['plan_history'][0]['text'],
        session_directory=str(agent.store.directory(state['session_id'])),
        history_access='mrcat.tools.session_history(start=0, limit=50)',
        **evidence_context(agent, state))


def action_messages(system, user):
    """Use the exact bounded conversation saved with this model request."""
    context = json.loads(user)
    history = context.pop('action_history', [])
    feedback = context.pop('execution_feedback', '')
    review = context.get('evaluation') or {}
    needs_revision = review.get('route') == 'execute' and review.get('accept_item') is False
    if needs_revision:
        context.pop('evaluation')
    messages = [dict(role='system', content=system),
                dict(role='user', content=json.dumps(context, ensure_ascii=False)), *history]
    if feedback:
        messages.append(dict(role='user', content='Current execution feedback: ' + feedback))
    if needs_revision:
        messages.append(dict(role='user', content=(
            'Review has not accepted this item. The previous finish submitted a handoff only. '
            'Continue from the existing files and evidence; address the unresolved issues below '
            'with native tools, then submit a new finish. Do not repeat unaffected work or treat '
            'the Review judgment as observed evidence.\nCurrent Review: '
            + json.dumps(review, ensure_ascii=False))))
    return messages
