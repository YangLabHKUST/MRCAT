"""Shared CodeAct nodes; each role owns a separately compiled LangGraph."""
from uuid import uuid4
from copy import deepcopy
import json
import hashlib
from langgraph.graph import StateGraph, START, END
from mrcat.state import memory
from mrcat.workflow import tasks
from mrcat.runtime.execution import CodeExecutor
from mrcat.state.results import work_scope
from mrcat.workflow.flow import Flow


class CodeActNodes:
    strict_bash = False

    def __init__(self, agent):
        self.agent = agent

    def wrap(self, method):
        def node(flow):
            state = deepcopy(flow['session'])
            with self.agent.store.node_state(state):
                if method.__name__ == 'tools' and flow.get('coding_call'):
                    from mrcat.trace import tool_started
                    tool_started(self.agent.store.directory(state['session_id']), state, flow)
                result = method(flow, state)
                if method.__name__ in {'tools', 'observe'}:
                    from mrcat.trace import capture_coding
                    capture_coding(self.agent.store.directory(state['session_id']), state)
                if (result.get('action') or {}).get('kind') == 'execute':
                    state['pending_execution'] = {key: value for key, value in (flow | result).items()
                                                  if key != 'session'}
                    if flow.get('role') == 'mr':
                        state['pending_execution'].update(
                            task_id=state['active_task']['task_id'],
                            step_id=state['active_task']['current_item_id'])
                if method.__name__ == 'observe':
                    state.pop('pending_execution', None)
                call = result.get('coding_call') or {}
                if call.get('tool') in {'write', 'edit', 'publish'}:
                    state['pending_coding_tool'] = dict(
                        call=call, action_id=result['coding_action_id'],
                        task_id=state['active_task']['task_id'],
                        step_id=state['active_task']['current_item_id'])
                if method.__name__ == 'tools':
                    state.pop('pending_coding_tool', None)
            return {**result, 'session': state}
        return node

    def prepare(self, flow, state):
        role = flow['role']
        if role != 'mr':
            memory.begin_role_work(state, role, flow['decision']['action'], flow['decision']['effective_request'])
        else:
            memory.work_state(state, role).pop('delivery', None)
        return {}

    def context(self, flow, state):
        if self.agent._stopped(state):
            target = END
        elif flow.get('format_errors', 0) >= 2:
            target = 'pause'
        elif flow['rounds'] >= self.agent.max_rounds:
            target = 'pause'
        elif flow.get('review_reason'):
            target = 'evaluate'
        elif self.agent.needs_compaction(state, flow['role']):
            target = 'compact'
        else:
            target = 'executor'
        return dict(next_node=target)

    def compact(self, flow, state):
        self.agent.compact_memory(state, flow['role'])
        return {}

    def role(self, flow, state):
        from mrcat.agent import parse_action
        role = flow['role']
        context = self.agent.executor_context(state, role)
        if flow.get('failures', 0) and flow.get('action', {}).get('kind') == 'execute':
            # Repair the failed operation with its full source and real observation,
            # not clipped assistant text or unrelated historical tasks.
            directory = self.agent.store.directory(flow['sid'])
            observation = directory / 'executions' / flow['action']['execution_id'] / 'observation.json'
            context = {key: context[key] for key in (
                'role', 'task', 'work_request', 'latest_request', 'current_plan', 'memory',
                'runtime', 'active_guide', 'skill_catalog', 'evaluation', 'control_facts',
                'repo_root', 'workspace', 'history_access', 'result_refs',
                'current_item', 'completed_results', 'item_results', 'completed_item_ids') if key in context}
            context['failed_execution'] = dict(code=flow['action']['body'],
                language=flow['action']['language'], observation=json.loads(observation.read_text()))
            context['repair_instruction'] = (
                'Repair this operation within the current Plan. Use the actual error and supported inputs; '
                'do not repeat successful earlier work. Read a specific missing fact only when needed. '
                'If repair requires a scientific change, use the role-specific blocked handoff.')
        raw = self.agent._call(state, role, self.agent.executor_prompt(state, role),
                               json.dumps(context, ensure_ascii=False))
        update = dict(rounds=flow['rounds'] + 1)
        for attempt in range(2):
            self.agent._record(state, 'assistant', raw)
            if self.agent._stopped(state):
                return update | dict(next_node=END)
            try:
                if attempt and raw.strip() == 'UNRECOVERABLE':
                    raise ValueError('The intended action could not be recovered without guessing.')
                action = parse_action(raw, role=role)
                break
            except ValueError as exc:
                self.agent._record(state, 'observation', json.dumps(dict(
                    type='action_rejected', reason=str(exc), applied=False)))
                if attempt:
                    return update | dict(next_node='context', format_errors=2,
                        review_reason='Action format repair failed; neither response was executed. Earlier outputs remain available.')
                # One focused transport repair; do not ask the model to solve the
                # scientific task again or replay the full Executor context.
                raw = self.agent._call(state, role, self.agent.prompt('action_repair'),
                    json.dumps(dict(role=role, error=str(exc), previous_response=raw), ensure_ascii=False))
        if action['message']:
            self.agent._event(state, 'assistant_message', action['message'])
        kind = action['kind']
        if kind == 'execute':
            action['execution_id'] = uuid4().hex[:12]
        if kind == 'evaluate':
            self.agent._event(state, 'recovery_requested', action['body'])
        return update | dict(action=action, format_errors=0,
                             review_reason=action['body'] if kind == 'evaluate' else '',
                             next_node='deliver' if kind in {'ask', 'final'} else kind)

    def skill(self, flow, state):
        name = flow['action']['body']
        progress = self.track_observation(flow, 'guide:' + name)
        if not self.agent.skills.get(name):
            self.agent._record(state, 'observation', f'Unknown guide: {name}; you can still write code directly.')
            return progress
        memory.work_state(state, flow['role'])['guide'] = name
        if name not in state['loaded_skills']:
            state['loaded_skills'].append(name)
        self.agent._record(state, 'observation', f'Read {name} in active_guide. Full guide: {self.agent.root / "skills" / name / "SKILL.md"}')
        self.agent._event(state, 'skill_loaded', name)
        return progress

    @staticmethod
    def track_observation(flow, fingerprint, *, changed=False, failed=False):
        """Signals request model evaluation; they never decide scientific progress."""
        seen = [*flow.get('fingerprints', []), fingerprint][-6:]
        failures = flow.get('failures', 0) + 1 if failed else 0
        unchanged = 0 if changed else flow.get('unchanged', 0) + 1
        reason = ''
        if failures >= 3:
            reason = 'Three consecutive execution failures. Assess whether local repair is still appropriate.'
        elif not changed and seen.count(fingerprint) >= 3:
            reason = 'Repeated identical observations. Assess whether these actions still advance the request.'
        elif unchanged >= 6:
            reason = ('Six actions without saved artifact changes. Reads and calculations can be useful progress; '
                      'assess their evidence before deciding whether to continue or change the plan.')
        return dict(fingerprints=seen, failures=failures, unchanged=unchanged, review_reason=reason)

    def evaluate(self, flow, state):
        if self.agent._stopped(state):
            return dict(next_node=END)
        if flow.get('evaluations', 0) >= 3:
            return dict(next_node='pause', review_reason='Repeated recovery attempts did not resolve the obstacle; task paused.')
        context = self.agent.executor_context(state, flow['role'])
        context['trigger'] = flow['review_reason']
        # No tool catalog or guide is needed for a bounded recovery decision.
        context.pop('skill_catalog', None)
        context.pop('active_guide', None)
        try:
            raw = self.agent._call(state, 'evaluate', self.agent.prompt('evaluate'), json.dumps(context, ensure_ascii=False))
            review = json.loads(raw)
            if (not isinstance(review, dict) or review.get('route') not in {'continue', 'recover', 'ask', 'stop'}
                    or not isinstance(review.get('reason'), str) or not review['reason'].strip()
                    or not isinstance(review.get('message', ''), str)
                    or not isinstance(review.get('reusable', ''), str)):
                raise ValueError('Evaluate requires route, reason, optional message and reusable text.')
            if review['route'] == 'ask' and not review.get('message', '').strip():
                raise ValueError('A clarification requires a question.')
        except Exception as exc:
            self.agent._record(state, 'observation', json.dumps(dict(type='evaluation_failed', reason=type(exc).__name__)))
            return dict(next_node='pause', review_reason='Recovery evaluation was unavailable or invalid; task paused.')
        if self.agent._stopped(state):
            return dict(next_node=END)
        self.agent._event(state, 'evaluation', review['reason'], route=review['route'])
        # Store model guidance separately; it is not an observed scientific fact.
        memory.work_state(state, flow['role'])['evaluation'] = review
        update = dict(review=review, evaluations=flow.get('evaluations', 0) + 1,
                      review_reason='', fingerprints=[], unchanged=0, failures=0, format_errors=0)
        route = review['route']
        if route in {'continue', 'recover'}:
            self.agent._event(state, 'assistant_message', review.get('message') or review['reason'])
        if route == 'ask':
            return update | dict(action=dict(kind='ask', body=review['message']), next_node='deliver')
        if route == 'stop':
            return update | dict(review_reason=review.get('message') or review['reason'], next_node='pause')
        return update | dict(next_node='recover' if route == 'recover' and flow['role'] == 'mr' else 'context')

    def execute(self, flow, state):
        action = flow['action']
        execution_id = action['execution_id']
        directory = self.agent.store.directory(flow['sid'])
        event = self.agent._event(state, 'code_execution', action['message'] or f'Run {action["language"]}',
                                 execution_id=execution_id, language=action['language'], code=action['body'],
                                 status='running', stdout='', stderr='')
        def output(stdout, stderr):
            event['details'].update(stdout=stdout, stderr=stderr)
            from mrcat.state.store import now
            event['timestamp'] = now()
            self.agent.store.publish_live_event(state, event)
        executor = CodeExecutor(self.agent.root, directory, timeout=action.get('timeout', self.agent.execution_timeout),
                                strict_bash=self.strict_bash)
        result = executor.execute(action['body'], action['language'], execution_id, on_output=output,
            working_directory=action.get('working_directory'),
            result_scope=work_scope(memory.work_state(state, flow['role']), flow['role']))
        event['details'].update(result)
        # Observation is consumed in a distinct node; full output stays on disk.
        return {}

    def observe(self, flow, state):
        directory = self.agent.store.directory(flow['sid'])
        ref = f'executions/{flow["action"]["execution_id"]}/observation.json'
        result = json.loads((directory / ref).read_text())
        self.agent._record(state, 'observation', json.dumps(result, ensure_ascii=False))
        work = memory.work_state(state, flow['role'])
        work['artifacts'] = list(dict.fromkeys([*work.get('artifacts', []), ref, *result.get('generated_files', [])]))
        memory.record_execution(work, result)
        # Exclude execution IDs, timing and log paths from comparison.
        payload = {key: result.get(key) for key in ('status', 'returncode', 'stdout', 'stderr')}
        tool_results = result.get('tool_results', [])
        payload['tool_results'] = [{key: row.get(key) for key in ('status', 'failure_class', 'summary', 'message')}
                                   for row in tool_results]
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return self.track_observation(flow, fingerprint, changed=bool(result.get('generated_files') or result.get('result_refs')),
                                      failed=result.get('returncode') != 0 or any(
                                          row.get('status') in {'blocked', 'failed', 'error'} for row in tool_results))

    def deliver(self, flow, state):
        action = flow['action']
        if action['kind'] == 'ask':
            state['pending'] = dict(kind='clarification', role=flow['role'], question=action['body'])
        # Publish before memory maintenance, so a finished answer never waits for it.
        self.agent._event(state, 'question' if action['kind'] == 'ask' else 'final', action['body'])
        memory.record_delivery(memory.work_state(state, flow['role']), action['kind'], action['body'])
        return dict(ending=action['kind'])

    def pause(self, flow, state):
        self.agent._event(state, 'interrupted', flow.get('review_reason') or 'Action budget reached. The task is not complete; reply to continue.')
        return dict(ending='pause')

    def compact_end(self, flow, state):
        self.agent.compact_memory(state, flow['role'], force=True)
        memory.apply_delivery(memory.work_state(state, flow['role']))
        return {}

    def finish(self, flow, state):
        ending = flow['ending']
        state['status'] = {'final': 'completed', 'ask': 'waiting_user', 'pause': 'paused'}[ending]
        if flow['role'] == 'mr':
            if ending == 'final':
                tasks.archive_task(state, 'completed')
            else:
                memory.work_state(state, 'mr')['status'] = state['status']
        else:
            memory.work_state(state, flow['role'])['status'] = state['status']
            if ending == 'final' and (state.get('pending') or {}).get('role') == flow['role']:
                state['pending'] = None
        return dict(next_node=END)



def role_graph(agent, role):
    if role == 'report':
        from mrcat.report.graph import report_graph
        return report_graph(agent)
    if role == 'mr':
        from mrcat.workflow.mr import mr_graph
        return mr_graph(agent)
    nodes = CodeActNodes(agent)
    graph = StateGraph(Flow)
    for name in ('prepare', 'context', 'compact', 'skill', 'evaluate', 'execute',
                 'observe', 'deliver', 'pause', 'compact_end', 'finish'):
        graph.add_node(name, nodes.wrap(getattr(nodes, name)))
    graph.add_node('executor', nodes.wrap(nodes.role))
    def route(flow):
        return flow['next_node']
    graph.add_edge(START, 'prepare')
    graph.add_edge('prepare', 'context')
    graph.add_conditional_edges('context', route, ['executor', 'compact', 'evaluate', 'pause', END])
    graph.add_edge('compact', 'executor')
    graph.add_conditional_edges('executor', route, ['execute', 'skill', 'evaluate', 'deliver', 'context', END])
    graph.add_edge('execute', 'observe')
    graph.add_edge('observe', 'context')
    graph.add_edge('skill', 'context')
    graph.add_conditional_edges('evaluate', route,
                                ['context', 'deliver', 'pause', END])
    graph.add_edge('deliver', 'compact_end')
    graph.add_edge('pause', 'compact_end')
    graph.add_edge('compact_end', 'finish')
    graph.add_edge('finish', END)
    return graph.compile(name=role)
