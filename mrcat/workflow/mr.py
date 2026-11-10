"""MR advances plan items; each item owns a bounded CodeAct execution loop."""
import json
from langgraph.graph import START, END, StateGraph
from uuid import uuid4
from mrcat.workflow.flow import Flow
from mrcat.state.store import write_json
from mrcat.workflow.review import evidence_context
from mrcat.workflow.finalization import result_sources, render_summary
from mrcat.runtime.diagnostics import exception_details
from mrcat.state import memory
from mrcat.workflow import tasks
from mrcat.runtime.codeact import CodeActNodes
from mrcat.runtime.coding_protocol import review_context
from mrcat.workflow.plan_items import current_item, complete_item


def parse_final_summary(raw):
    """A short status line plus Markdown avoids embedding a report inside JSON."""
    text = raw.strip()
    status, separator, body = text.partition('\n')
    marker = '[END_FINAL_SUMMARY]'
    if status.strip() not in {'completed', 'blocked'} or not separator or not body.rstrip().endswith(marker):
        raise ValueError('Return completed or blocked on the first line, then Markdown, ending with [END_FINAL_SUMMARY].')
    summary = body.rstrip()[:-len(marker)].strip()
    if not summary:
        raise ValueError('A final summary must include the result or the unresolved obstacle.')
    return status.strip(), summary


class MRNodes(CodeActNodes):
    def __init__(self, agent):
        super().__init__(agent)
        from mrcat.runtime.coding_agent import CodingAgentNodes
        self.custom = CodingAgentNodes(agent)

    def prepare_executor(self, flow, state):
        task = state['active_task']
        task.pop('review_pending', None)
        task.pop('finalization_pending', None)
        item = current_item(task)
        if item is None:
            return self.ready_to_finalize(flow, state)
        new_item = task.get('current_item_id') != item['step_id']
        if new_item:
            task.update(current_item_id=item['step_id'], item_execution_ids=[],
                        item_run_ids=[],
                        item_context_start=len(state['messages']), guide=item['skill_id'])
            if (task.get('evaluation') or {}).get('accept_item') is True:
                task.pop('evaluation', None)
            self.agent._event(state, 'plan_item_started', item['title'], item_id=item['step_id'])
            if item['skill_id']:
                self.agent._event(state, 'skill_loaded', item['skill_id'])
        return dict(next_node='executor', handoff={}, action={}, review_reason='', failures=0,
                    item_round_start=flow['rounds'],
                    fingerprints=[], unchanged=0, format_errors=0, coding_stop=False)

    def context(self, flow, state):
        if self.agent._stopped(state):
            self.custom.cancel_pending(state, 'Stopped before the tool finished; queued calls were not executed.')
            return dict(next_node=END)
        if flow['rounds'] >= self.agent.max_rounds:
            self.custom.cancel_pending(state, 'Execution action budget reached; queued calls were not executed.')
            return dict(next_node='handoff', handoff=dict(outcome='paused',
                        body='Execution action budget reached; this is not completion.'))
        item = current_item(state['active_task'])
        if not item['skill_id']:
            # Technical recovery belongs to the Custom Executor, not Review.
            if flow.get('coding_stop'):
                self.custom.cancel_pending(state, flow['review_reason'])
                return dict(next_node='handoff', handoff=dict(outcome='paused', body=flow['review_reason']))
            pending = self.custom.dispatch(state)
            if pending:
                return pending | dict(rounds=flow['rounds'] + 1)
            if flow.get('format_errors', 0) >= 2:
                return dict(next_node='handoff', handoff=dict(outcome='paused', body=flow['review_reason']))
            return dict(next_node='compact' if self.custom.needs_compaction(state) else 'model')
        if flow.get('review_reason'):
            outcome = 'paused' if flow.get('format_errors', 0) >= 2 else 'blocked'
            return dict(next_node='handoff', handoff=dict(outcome=outcome, body=flow['review_reason']))
        return dict(next_node='compact' if self.agent.needs_compaction(state, 'mr') else 'model')

    def compact(self, flow, state):
        if current_item(state['active_task'])['skill_id'] is None:
            self.custom.compact(state)
        else:
            self.agent.compact_memory(state, 'mr')
        return {}

    def compact_end(self, flow, state):
        item = current_item(state['active_task'])
        if state['active_task'].get('coding'):
            if flow['ending'] != 'final' and item and item['skill_id'] is None:
                self.custom.compact(state)
            memory.update_mr_task_memory(state['active_task'])
            memory.apply_delivery(state['active_task'])
            return {}
        return super().compact_end(flow, state)

    def role(self, flow, state):
        item = current_item(state['active_task'])
        update = (super().role(flow, state) if item['skill_id'] else
                  self.custom.role(flow, state))
        if item['skill_id'] and update.get('next_node') in {'skill', 'end'}:
            action = update['action']
            if action['kind'] != 'end' or action.get('outcome') != 'blocked':
                return update | dict(next_node='handoff', handoff=dict(outcome='blocked',
                    body='Selected skill was not executed. Generate its documented call in one code cell; '
                         'the host advances from the real tool output, not a guide load or complete claim.'))
        if update.get('next_node') == 'end':
            action = update['action']
            update.update(next_node='handoff', handoff=dict(outcome=action['outcome'], body=action['body']))
        return update

    @staticmethod
    def track_observation(flow, fingerprint, *, changed=False, failed=False):
        return CodeActNodes.track_observation(flow, fingerprint, changed=changed, failed=failed)

    def execute(self, flow, state):
        if current_item(state['active_task'])['skill_id']:
            return super().execute(flow, state)
        return self.custom.execute(flow, state)

    def tools(self, flow, state):
        update = self.custom.tools(flow, state)
        if update.get('next_node') == 'end':
            action = update['action']
            update.update(next_node='handoff',
                          handoff=dict(outcome=action['outcome'], body=action['body']))
        return update

    def observe(self, flow, state):
        task = state['active_task']
        item = current_item(task)
        update = (super().observe(flow, state) if item['skill_id'] else
                  self.custom.observe(flow, state))
        execution_id = flow['action']['execution_id']
        task.setdefault('item_execution_ids', []).append(execution_id)
        item = current_item(task)
        if not item['skill_id']:
            return update | dict(next_node='context')
        directory = self.agent.store.directory(state['session_id'])
        result = json.loads((directory / 'executions' / execution_id / 'observation.json').read_text())
        if result['status'] == 'cancelled':
            return update | dict(next_node='handoff', handoff=dict(outcome='paused', body='Execution was interrupted.'))
        try:
            if result['returncode'] != 0 or result['status'] != 'exited':
                raise ValueError(f"Execution {result['status']}, exit={result['returncode']}: {result['stderr'][-2000:]}")
            expected = item['skill_id'].replace('-', '_')
            refs = [r for r in result.get('result_refs', []) if r.get('tool') == expected]
            if not refs or any(r['status'] != 'ok' for r in refs):
                raise ValueError('Expected tool did not return a successful saved result. ' +
                                 json.dumps(result.get('tool_results', []), ensure_ascii=False))
            if any(r.get('tool') != expected for r in result.get('result_refs', [])):
                raise ValueError('A skill item must publish only its selected tool outputs; do not run later items or duplicate results.')
        except (ValueError, OSError, KeyError) as exc:
            return update | dict(next_node='handoff', handoff=dict(outcome='blocked', body=str(exc)))
        summary = '\n'.join(r.get('summary', '') for r in result.get('tool_results', []))
        return update | dict(next_node='handoff', handoff=dict(outcome='complete',
            body=summary or 'The selected tool returned a successful saved result.'))

    def handoff(self, flow, state):
        handoff = flow['handoff']
        task = state['active_task']
        task['executor_handoff'] = handoff
        if handoff['outcome'] != 'paused':
            task['review_pending'] = dict(handoff=handoff, request=task['request'], plan=task['plan'])
        self.agent._event(state, 'executor_handoff', handoff['body'], outcome=handoff['outcome'])
        return {}

    def after_executor(self, flow, state):
        if state['status'] == 'stopped':
            return dict(next_node=END)
        if flow['handoff']['outcome'] == 'paused':
            return dict(next_node='pause', review_reason=flow['handoff']['body'])
        task = state['active_task']
        if flow['handoff']['outcome'] == 'complete' and current_item(task)['skill_id']:
            try:
                item_id = complete_item(task, self.agent.store.directory(state['session_id']), flow['handoff'])
            except (ValueError, OSError, KeyError) as exc:
                self.agent._record(state, 'observation', 'Item is not complete: ' + str(exc))
                handoff = dict(outcome='blocked', body='Item output checks failed: ' + str(exc))
                task['review_pending'] = dict(handoff=handoff, request=task['request'], plan=task['plan'])
                return dict(next_node='evaluate', handoff=handoff)
            self.agent._event(state, 'plan_item_completed', flow['handoff']['body'], item_id=item_id)
            task.pop('review_pending', None)
            task.pop('evaluation', None)
            return dict(next_node='prepare_executor')
        return dict(next_node='evaluate')

    def ready_to_finalize(self, flow, state):
        task = state['active_task']
        handoff = task.get('executor_handoff') or dict(outcome='complete', body='All plan items have saved outputs.')
        decision = dict(route='finalize', reason='All plan items completed; deliver their saved results.', origin='host')
        task.pop('review_pending', None)
        task['finalization_pending'] = dict(handoff=handoff, review=decision,
                                            request=task['request'], plan=task['plan'])
        return dict(next_node='finalize', handoff=handoff, review=decision)

    def evaluation_context(self, flow, state):
        """Review real execution evidence separately from mutable memory summaries."""
        task = state['active_task']
        directory = self.agent.store.directory(state['session_id'])
        messages = memory.relevant_messages(state['messages'], start=task['context_start'],
                                             role='mr', task_id=task['task_id'])
        return dict(role='mr', task=memory.task_brief(task), latest_request=state['request'],
                    current_item=current_item(task), completed_items=task.get('completed_items', {}),
                    current_plan=task['plan'], initially_confirmed_plan=task['plan_history'][0]['text'],
                    user_updates=[memory.excerpt(m['content'], 2000) for m in messages if m['role'] == 'user'][-6:],
                    handoff=flow['handoff'], previous_review=task.get('evaluation'),
                    session_directory=str(directory), history_access='mrcat.tools.session_history(start=0, limit=50)',
                    **evidence_context(self.agent, state))

    def evaluate(self, flow, state):
        if self.agent._stopped(state):
            return dict(next_node=END)
        task = state['active_task']
        item = current_item(task)
        custom = item is not None and item['skill_id'] is None
        context = review_context(self.agent, state, flow) if custom else self.evaluation_context(flow, state)
        # The gateway owns transport retries. Only a malformed review gets one
        # format-repair attempt here; a service failure never restarts execution.
        for attempt in range(2):
            try:
                raw = self.agent._call(state, 'evaluate', self.agent.prompt('mr_codeact_review' if custom else 'mr_evaluate'),
                                       json.dumps(context, ensure_ascii=False), structured_action=custom)
            except Exception as exc:
                return self.node_failed(state, 'evaluate', exc, 'model_call')
            try:
                review = json.loads(raw)
                fields = {'route', 'reason'}
                if isinstance(review, dict) and review.get('route') == 'execute':
                    fields.add('accept_item')
                if isinstance(review, dict) and review.get('route') == 'replan':
                    fields.update(key for key in ('invalidate_steps', 'accept_item') if key in review)
                if (not isinstance(review, dict)
                        or set(review) != fields
                        or review.get('route') not in {'execute', 'replan', 'finalize'}
                        or not isinstance(review.get('reason'), str) or not review['reason'].strip()):
                    raise ValueError('Review requires route=execute|replan|finalize and reason; execute also requires accept_item=true|false.')
                if review['route'] == 'replan':
                    from mrcat.workflow.plan_items import validate_invalidation
                    validate_invalidation(task, review.get('invalidate_steps', []))
                if 'accept_item' in review:
                    if not isinstance(review['accept_item'], bool):
                        raise ValueError('accept_item must be a boolean.')
                    if review['accept_item']:
                        item = current_item(task)
                        if item is None or item['skill_id'] or flow['handoff']['outcome'] != 'complete':
                            raise ValueError('Only a custom item submitted complete can be accepted. Failed skill items must be retried or replanned.')
                break
            except (ValueError, TypeError) as exc:
                if attempt:
                    return self.node_failed(state, 'evaluate', exc, 'review_format', response=raw)
                context['format_error'] = str(exc)
                context['previous_response'] = memory.excerpt(raw, 3500)
        if self.agent._stopped(state):
            return dict(next_node=END)
        # A routing reason is a judgment, not a new observed fact or permission.
        task = state['active_task']
        task.pop('review_pending', None)
        task['evaluation'] = review
        self.agent._event(state, 'evaluation', review['reason'], route=review['route'])
        update = dict(review=review, review_reason='', format_errors=0,
                      fingerprints=[], unchanged=0, failures=0)
        if review['route'] == 'finalize':
            task['finalization_pending'] = dict(handoff=flow['handoff'], review=review,
                                                request=task['request'], plan=task['plan'])
            return update | dict(next_node='finalize')
        if review.get('accept_item'):
            item_id = complete_item(task, self.agent.store.directory(state['session_id']), flow['handoff'])
            memory.update_mr_task_memory(task)
            self.agent._event(state, 'plan_item_completed', review['reason'], item_id=item_id)
        if review['route'] == 'execute':
            return update | dict(next_node='prepare_executor')
        if not review.get('accept_item') and flow.get('recoveries', 0) >= 3:
            return update | dict(next_node='pause', review_reason=(
                'Repeated plan recovery did not resolve the obstacle; task remains unfinished.'))
        task['replan_pending'] = dict(review=review, request=task['request'], plan=task['plan'])
        self.agent._event(state, 'assistant_message', review['reason'])
        return update | dict(next_node='recover')

    def node_failed(self, state, node, exc, stage, response=None):
        """Technical failures preserve the pending node, never imply scientific rejection."""
        from mrcat.runtime.diagnostics import redact
        directory = self.agent.store.directory(state['session_id'])
        details = exception_details(exc)
        details.update(stage=stage, node=node, model_diagnostic=getattr(exc, 'mrcat_diagnostic', None))
        if response is not None:
            details['response'] = redact(response)[:12000]
        ref = f"evaluations/{state['active_task']['task_id']}/{uuid4().hex}/error.json"
        write_json(directory / ref, details)
        pending_key = 'review_pending' if node == 'evaluate' else 'finalization_pending'
        state['active_task'][pending_key]['error_path'] = ref
        # Reuse the existing frontend error event; its content identifies the stage.
        self.agent._event(state, 'evaluation_failed',
                          f"MR {node} {stage} failed: {details['type']}: {details['message'][:1200]}",
                          stage=stage, diagnostic_path=ref)
        return dict(next_node='pause', review_reason=(
            f'MR {node} could not complete. Analysis outputs are preserved. '
            f'Continue this unchanged task to retry only {node.capitalize()}. Diagnostic: ' + ref))

    def finalize(self, flow, state):
        """Write a grounded delivery; completed and blocked have distinct lifecycle states."""
        if self.agent._stopped(state):
            return dict(next_node=END)
        if flow['review']['route'] != 'finalize':
            raise ValueError('MR finalization requires completed items or an explicit Review finalize decision.')
        task = state['active_task']
        messages = memory.relevant_messages(state['messages'], start=task['context_start'],
                                             role='mr', task_id=task['task_id'])
        sources = result_sources(self.agent, state)
        context = dict(role='mr', task=memory.task_brief(task), latest_request=state['request'],
                       current_item=current_item(task), completed_items=task.get('completed_items', {}),
                       current_plan=task['plan'],
                       user_updates=[memory.excerpt(m['content'], 2000) for m in messages if m['role'] == 'user'][-6:],
                       handoff=flow['handoff'], previous_review=task.get('evaluation'),
                       review=flow['review'], result_sources=sources)
        initial_plan = task['plan_history'][0]['text']
        if initial_plan != task['plan']:
            context['initially_confirmed_plan'] = initial_plan
        for attempt in range(2):
            try:
                raw = self.agent._call(state, 'finalize', self.agent.prompt('mr_finalize'),
                                       json.dumps(context, ensure_ascii=False))
            except Exception as exc:
                return self.node_failed(state, 'finalize', exc, 'model_call')
            try:
                stage = 'summary_format'
                status, summary = parse_final_summary(raw)
                stage = 'summary_evidence'
                if status == 'completed' and current_item(task):
                    raise ValueError('The plan has unfinished items. Report blocked with the missing work or resource.')
                summary = render_summary(summary, sources, status=status)
                break
            except ValueError as exc:
                if attempt:
                    return self.node_failed(state, 'finalize', exc, stage, response=raw)
                context['format_error'] = str(exc)
                context['previous_response'] = memory.excerpt(raw, 3500)
        if self.agent._stopped(state):
            return dict(next_node=END)
        ref = f"workspace/outputs/{task['task_id']}/final_summary.md"
        path = self.agent.store.directory(state['session_id']) / ref
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.md.tmp')
            temporary.write_text(summary + '\n', encoding='utf-8')
            temporary.replace(path)
        except OSError as exc:
            return self.node_failed(state, 'finalize', exc, 'save_summary')
        task.pop('finalization_pending', None)
        task['artifacts'] = list(dict.fromkeys([*task['artifacts'], ref]))
        task['final_summary'] = summary
        self.agent._record(state, 'assistant', summary)
        # A blocked delivery asks for the missing decision/resource and keeps the task open.
        kind = 'final' if status == 'completed' else 'ask'
        return self.deliver({**flow, 'action': dict(kind=kind, body=summary)}, state) | dict(next_node='compact_end')

    def entry(self, flow, state):
        return dict(recovering=False, recoveries=0,
                    next_node='planner' if flow['decision']['action'] in {'propose', 'revise'} else 'task')

    def planner(self, flow, state):
        recovery = flow.get('review') if flow.get('recovering') else None
        reason = recovery['reason'] if recovery else (
            'Revise the current plan' if flow['decision']['action'] == 'revise' else 'Propose a new MR task')
        try:
            plan = self.agent._plan(state, state['request'], reason, recovery=recovery,
                                    effective_request=None if recovery else flow['decision']['effective_request'],
                                    new_task=not recovery and (flow['decision']['action'] == 'propose' or
                                        (state.get('pending') or {}).get('kind') == 'plan_confirmation' and
                                        (state.get('pending') or {}).get('task_id') is None))
        except Exception as exc:
            if not recovery:
                raise
            self.agent._event(state, 'recovery_failed',
                              f'Planner unavailable: {type(exc).__name__}; previous plan retained.')
            self.agent._record(state, 'observation', json.dumps(dict(type='recovery_failed', plan_applied=False)))
            return dict(recovering=False, next_node='pause',
                        review_reason='A replacement plan could not be generated; previous plan and outputs retained.')
        if self.agent._stopped(state):
            return dict(next_node=END)
        if recovery:
            from mrcat.workflow.plan_items import apply_invalidation
            apply_invalidation(state['active_task'], recovery.get('invalidate_steps', []), reason,
                               self.agent.store.directory(state['session_id']))
            tasks.revise_task(memory.work_state(state, 'mr'), plan, reason)
            state['active_task'].pop('replan_pending', None)
            self.agent._publish_plan(state, plan)
            self.agent._record(state, 'observation', json.dumps(dict(type='plan_applied', plan_path='plan.md'), ensure_ascii=False))
            return dict(plan=plan, recovering=False, next_node='prepare_executor')
        return dict(plan=plan, next_node='task')

    def task(self, flow, state):
        old_request = (state.get('active_task') or {}).get('request')
        plan = flow.get('plan') if flow['decision']['action'] in {'propose', 'revise'} else None
        proceed = self.agent._route_mr(state, flow['decision'], plan=plan)
        if not proceed:
            return dict(next_node=END)
        task = state['active_task']
        if not task.get('plan_items') or any('step_id' not in item for item in task['plan_items']) or (old_request and old_request != task['request'] and flow['decision']['action'] == 'continue'):
            task.pop('review_pending', None)
            task.pop('finalization_pending', None)
            return dict(next_node='recover', review=dict(route='replan',
                        reason='Create current-format items for the updated request or prior plan, preserving compatible completed results and reusing their saved outputs.'))
        pending = task.get('replan_pending')
        if (flow['decision']['action'] == 'continue' and pending
                and pending['request'] == task['request'] and pending['plan'] == task['plan']):
            return dict(next_node='recover', review=pending['review'])
        task.pop('replan_pending', None)
        for key, node in (('finalization_pending', 'finalize'), ('review_pending', 'evaluate')):
            pending = task.get(key)
            if (flow['decision']['action'] == 'continue' and pending
                    and pending['request'] == task['request'] and pending['plan'] == task['plan']):
                return dict(next_node=node, handoff=pending['handoff'], review=pending.get('review', {}))
        task.pop('review_pending', None)
        task.pop('finalization_pending', None)
        return dict(next_node='prepare')

    def recover(self, flow, state):
        self.agent._event(state, 'recovery_started', flow['review']['reason'])
        # Planning from an accepted result is progress, not a failed recovery.
        increment = 0 if flow['review'].get('accept_item') else 1
        return dict(recovering=True, recoveries=flow.get('recoveries', 0) + increment, next_node='planner')


def executor_graph(nodes):
    """Inner CodeAct loop: no Planner, Evaluate or user-facing final answer."""
    graph = StateGraph(Flow)
    for name in ('context', 'compact', 'skill', 'execute', 'observe', 'handoff'):
        graph.add_node(name, nodes.wrap(getattr(nodes, name)))
    graph.add_node('model', nodes.wrap(nodes.role))
    graph.add_node('tools', nodes.wrap(nodes.tools))
    graph.add_conditional_edges('tools', lambda flow: flow['next_node'],
                                ['execute', 'context', 'handoff'])
    graph.add_edge(START, 'context')
    route = lambda flow: flow['next_node']
    graph.add_conditional_edges('context', route, ['model', 'tools', 'compact', 'handoff', END])
    graph.add_edge('compact', 'model')
    graph.add_conditional_edges('model', route, ['execute', 'skill', 'context', 'handoff', END]
                                + ['tools'])
    graph.add_edge('skill', 'context')
    graph.add_edge('execute', 'observe')
    graph.add_conditional_edges('observe', route, ['context', 'handoff'])
    graph.add_edge('handoff', END)
    return graph.compile(name='mr_executor')


def mr_graph(agent):
    nodes = MRNodes(agent)
    graph = StateGraph(Flow)
    for name in ('entry', 'planner', 'task', 'prepare', 'prepare_executor', 'after_executor',
                 'evaluate', 'recover', 'finalize', 'pause', 'compact_end', 'finish'):
        graph.add_node(name, nodes.wrap(getattr(nodes, name)))
    graph.add_node('executor', executor_graph(nodes))
    route = lambda flow: flow['next_node']
    graph.add_edge(START, 'entry')
    graph.add_conditional_edges('entry', route, ['planner', 'task'])
    graph.add_conditional_edges('planner', route, ['task', 'prepare_executor', 'pause', END])
    graph.add_conditional_edges('task', route, ['prepare', 'evaluate', 'finalize', 'recover', END])
    graph.add_edge('prepare', 'prepare_executor')
    graph.add_conditional_edges('prepare_executor', route, ['executor', 'evaluate', 'finalize'])
    graph.add_edge('executor', 'after_executor')
    graph.add_conditional_edges('after_executor', route, ['prepare_executor', 'evaluate', 'pause', END])
    graph.add_conditional_edges('evaluate', route, ['prepare_executor', 'recover', 'finalize', 'pause', END])
    graph.add_edge('recover', 'planner')
    graph.add_conditional_edges('finalize', route, ['compact_end', 'pause', END])
    graph.add_edge('pause', 'compact_end')
    graph.add_edge('compact_end', 'finish')
    graph.add_edge('finish', END)
    return graph.compile(name='mr')
