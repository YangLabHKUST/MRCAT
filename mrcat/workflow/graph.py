"""Manager routes user turns to independent Search, MR and Report subgraphs.

Only the root wait node resumes automatically. Interrupted code is never replayed.
Checkpoints retain both session memory and control state. Files are projections
and execution evidence, never a second source of mutable workflow state.
"""
import json
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, interrupt
from mrcat.workflow import manager
from mrcat.workflow.flow import Flow
from mrcat.runtime.codeact import CodeActNodes, role_graph


class ManagerNodes(CodeActNodes):
    def intake(self, flow, state):
        if state.get('version') != 2:
            raise ValueError('Upgrade this saved session before continuing.')
        state.update(status='running', active_agent='manager', request=flow['request'])
        self.agent._record(state, 'user', flow['request'])
        self.agent._event(state, 'user_message', flow['request'])
        return dict(rounds=0, manager_attempts=0, manager_error='', action={}, handoff={},
                    review_reason='', review={}, evaluations=0, failures=0, format_errors=0,
                    unchanged=0, fingerprints=[], ending="", plan="",
                    next_node=END if self.agent._stopped(state) else 'manager')


    def manager(self, flow, state):
        context = manager.context(state, flow['request'])
        if flow['manager_error']:
            context['format_error'] = flow['manager_error']
        raw = self.agent._call(state, 'manager', self.agent.prompt('manager'), json.dumps(context, ensure_ascii=False))
        attempts = flow['manager_attempts'] + 1
        try:
            decision = manager.parse_decision(raw)
            manager.validate_state(decision, state)
        except (ValueError, TypeError) as exc:
            if attempts >= 2:
                state['status'] = 'waiting_user' if state.get('pending') else 'paused'
                message = ('Manager could not produce a valid routing decision after one correction attempt. '
                           'No workflow action was applied. Your plan and saved results are preserved. '
                           'Please retry your last request.')
                self.agent._event(state, 'error', f'Routing validation failed: {exc}')
                self.agent._record(state, 'assistant', message)
                self.agent._event(state, 'assistant_message', message)
                return dict(manager_attempts=attempts, manager_error=str(exc),
                            next_node='wait' if state.get('pending') else END)
            return dict(manager_attempts=attempts, manager_error=str(exc), next_node='manager')
        if self.agent._stopped(state):
            return dict(next_node=END)
        self.agent._event(state, 'manager_route', '',
                          route=decision['route'], action=decision['action'])
        role = decision['route']
        target = role
        if role != 'respond':
            state['active_agent'] = role
        return dict(decision=decision, role=role, next_node=target, manager_attempts=attempts)


    def respond(self, flow, state):
        answer = flow['decision'].get('message', '')
        self.agent._record(state, 'assistant', answer)
        state['status'] = 'waiting_user' if state.get('pending') else 'completed'
        self.agent._event(state, 'final', answer)
        return dict(next_node='wait' if state.get('pending') else END)


    def wait(self, flow, state):
        # No writes or model calls before interrupt: this node restarts on resume.
        request = interrupt(state.get('pending') or {'question': 'Reply to continue.'})
        return dict(request=str(request))


    def after_role(self, flow, state):
        return dict(next_node='wait' if state['status'] == 'waiting_user' else END)


def build_graph(agent, checkpointer=None):
    nodes = ManagerNodes(agent)
    graph = StateGraph(Flow)
    # External lifecycle updates finish the previous control path. A subsequent
    # user turn enters intake with the saved pending question and task intact.
    graph.add_node('persist', lambda flow: {})
    graph.add_edge('persist', END)
    for name in ('intake', 'manager', 'respond', 'after_role', 'wait'):
        graph.add_node(name, nodes.wrap(getattr(nodes, name)))
    for role in ('search', 'mr', 'report'):
        graph.add_node(role, role_graph(agent, role))
        graph.add_edge(role, 'after_role')
    def route(flow):
        return flow['next_node']
    graph.add_edge(START, 'intake')
    graph.add_conditional_edges('intake', route, ['manager', END])
    graph.add_conditional_edges('manager', route, ['manager', 'respond', 'search', 'mr', 'report', 'wait', END])
    graph.add_conditional_edges('respond', route, ['wait', END])
    graph.add_conditional_edges('after_role', route, ['wait', END])
    graph.add_edge('wait', 'intake')
    return graph.compile(checkpointer=checkpointer, name='mrcat')


def run_graph(agent, sid, request):
    path = agent.store.checkpoint_path(sid, writable=True)
    config = {'configurable': {'thread_id': sid}, 'recursion_limit': agent.max_rounds * 10 + 100}
    session = agent.store.load(sid)
    if not agent.store.has_checkpoint(sid):
        raise ValueError('Import this legacy session into a new store before continuing.')
    session.pop('coding_agent', None)
    if session.get('pending_coding_tool'):
        from mrcat.runtime.coding_agent import CodingAgentNodes
        with agent.store.node_state(session):
            CodingAgentNodes(agent).recover_tool(session)
        agent.store.save(session)
    with SqliteSaver.from_conn_string(str(path)) as saver:
        session = recover_execution(agent, sid, session)
        from mrcat.runtime.coding_agent import CodingAgentNodes
        CodingAgentNodes(agent).cancel_pending(session,
            'Previous turn was interrupted. Queued calls were not executed; inspect saved evidence before retrying.')
        agent.store.save(session)
        graph = build_graph(agent, saver)
        saved = graph.get_state(config)
        # Stop/cancel/crash starts a new user turn. Never replay arbitrary code.
        payload = (Command(resume=request, update={'session': session})
                   if saved.next == ('wait',) else dict(sid=sid, request=request, session=session))
        try:
            graph.invoke(payload, config, durability='sync')
        finally:
            agent.store.clear_live_events(sid)
    return agent.store.load(sid)


def recover_execution(agent, sid, session):
    """Consume a finished process receipt when observe never committed.

    This does not rerun code. Incomplete executions remain evidence to inspect,
    and any retry must receive a new execution ID.
    """
    flow = session.get('pending_execution')
    if not flow:
        return session
    action = flow.get('action') or {}
    execution_id = action.get('execution_id')
    role = flow.get('role')
    if action.get('kind') != 'execute' or not execution_id or role not in {'mr', 'search'}:
        return session
    for message in session['messages']:
        if message['role'] != 'observation':
            continue
        try:
            observation = json.loads(message['content'])
        except (ValueError, TypeError):
            continue
        if isinstance(observation, dict) and observation.get('execution_id') == execution_id:
            return session
    receipt = agent.store.directory(sid) / 'executions' / execution_id / 'observation.json'
    if not receipt.exists():
        return session
    result = json.loads(receipt.read_text())
    if role == 'mr':
        from mrcat.workflow.mr import MRNodes
        task = session.get('active_task') or {}
        if (task.get('task_id') != flow.get('task_id')
                or task.get('current_item_id') != flow.get('step_id')):
            session.pop('pending_execution', None)
            agent.store.event(session, 'execution_recovery_skipped',
                              'Saved execution belongs to an inactive task item; its files are retained.',
                              execution_id=execution_id, task_id=flow.get('task_id'))
            return session
        nodes = MRNodes(agent)
    else:
        nodes = CodeActNodes(agent)
    # Treat this receipt exactly like a normal observe node, including result
    # references and tool failures. Do not infer scientific success from exit 0.
    with agent.store.node_state(session):
        existing = next((event for event in session['events']
                         if event['type'] == 'code_execution'
                         and event['details'].get('execution_id') == execution_id), None)
        if existing:
            existing['details'].update(result)
        else:
            agent._event(session, 'code_execution', action.get('message', ''), **result)
        nodes.observe(flow, session)
        session.pop('pending_execution', None)
        agent._event(session, 'execution_recovered', 'Recovered a saved execution observation without rerunning code.',
                     execution_id=execution_id)
    agent.store.save(session)
    return session
