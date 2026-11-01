"""Native Report subgraph with durable stage continuation and reviewed delivery."""
from uuid import uuid4
import json

from langgraph.graph import StateGraph, START, END
from ..flow import Flow
from ..codeact import CodeActNodes
from .. import memory
from .agent import ReportAgent
from .execution import ReportExecution
from .evidence import session_evidence, fingerprint
from .stages import ReportStages, after_judge, after_revision
from . import policy

STAGES = ('evidence', 'literature', 'writer', 'validate', 'save_draft', 'judge', 'revise', 'export')
NEXT = dict(evidence='literature', literature='writer', writer='validate', validate='save_draft',
            save_draft='judge', export='deliver')


class ReportNodes(CodeActNodes):
    def __init__(self, agent):
        self.agent = agent

    def load(self, flow, state):
        directory = self.agent.store.directory(flow['sid'])
        data = state.setdefault('report_state', {})
        return state, directory, data

    def prepare(self, flow, state):
        state, directory, previous = self.load(flow, state)
        memory.begin_role_work(state, 'report', flow['decision']['action'], flow['decision']['effective_request'])
        work = memory.work_state(state, 'report')
        request = work['request']
        rows = session_evidence(state, self.agent.store.directory(flow['sid']))
        stamp = fingerprint(rows, self.agent.root, request)
        resume = (flow['decision']['action'] == 'continue'
                  and previous.get('fingerprint') == stamp
                  and previous.get('next_stage') in (*STAGES, 'deliver')
                  and previous.get('status') in {'running', 'paused', 'failed', 'complete'})
        if resume:
            data = previous
            data.pop('judge_failure', None)
            data.pop('error', None)
            data['status'] = 'running'
            # Stage diagnostics are execution evidence. They may include an
            # interrupted attempt that never committed a graph state update.
            # Routing still comes exclusively from the checkpoint's next_stage.
            progress_path = directory / 'workspace' / 'reports' / data['run_id'] / 'report_execution.json'
            if progress_path.exists():
                data['progress'] = json.loads(progress_path.read_text())
            if data.get('progress'):
                data['progress'].update(status='running', resumed=True)
                for row in [*data['progress'].get('stages', []), *data['progress'].get('llm_calls', [])]:
                    if row['status'] == 'running':
                        row['status'] = 'interrupted'
        else:
            data = dict(run_id=uuid4().hex[:12], fingerprint=stamp, request=request,
                        available_evidence=rows, next_stage='evidence', status='running')
        state['report_state'] = data
        work['report_run_id'] = data['run_id']
        self.agent.store.save(state)
        self.agent._event(state, 'report_started', 'Continue report' if resume else 'Generate report',
                          run_id=data['run_id'], resumed=resume)
        return dict(next_node=data['next_stage'])

    def stage(self, name):
        def execute(flow, state):
            state, directory, data = self.load(flow, state)
            if self.agent._stopped(state):
                data['status'] = 'paused'
                return dict(next_node=END)
            execution = ReportExecution(self.agent, state, data)
            reporter = ReportAgent(self.agent, state, execution=execution)
            stages = ReportStages(reporter, execution.files)
            # Only the report request belongs to this evidence bundle; continuation
            # wording must not replace the question presented to the selector.
            report_state = dict(state, request=data['request'], run_id=data['run_id'])
            try:
                result = execution.call(name, getattr(stages, name), state=report_state,
                                        data=data, execution=execution)
                if name == 'export':
                    report = result['report_result']
                    data['result'] = dict(summary=report.final_summary, artifacts=report.artifacts,
                                          review=report.review)
                    execution.publish(report.artifacts)
                    data['status'] = 'complete'
                next_stage = after_judge(data) if name == 'judge' else after_revision(data) if name == 'revise' else NEXT[name]
                data['next_stage'] = next_stage
                self.agent.store.save(state)
                if self.agent._stopped(state):
                    data['status'] = 'paused'
                    return dict(next_node=END)
                return dict(next_node=next_stage)
            except Exception as exc:
                data.update(status='failed', next_stage=name, error=policy._error_summary(exc))
                # Save an explicitly unreviewed draft even when Judge is unavailable.
                if name == 'judge' and data.get('draft'):
                    failed = dict(data, judge_failure=policy._judge_failure('review', exc), final_judgement=None)
                    try:
                        result = policy.export_report(data=failed, artifact_store=execution.files,
                                                      state=report_state, execution=execution)
                        execution.publish(result.artifacts)
                    except Exception as export_error:
                        data['draft_export_error'] = f'{type(export_error).__name__}: {export_error}'
                body = (f'Report {name} could not complete: {policy._error_summary(exc)}. '
                        'Saved analysis results and any validated draft are preserved. '
                        'Continue this report to retry the pending stage.')
                self.agent._record(state, 'assistant', body)
                self.agent._event(state, 'report_failed', body, stage=name,
                                  checkpoint='graph.sqlite', run_id=data['run_id'])
                state['status'] = 'paused'
                memory.work_state(state, 'report')['status'] = 'paused'
                self.agent.store.save(state)
                return dict(next_node=END)
        return execute

    def deliver(self, flow, state):
        state, directory, data = self.load(flow, state)
        if self.agent._stopped(state):
            data['status'] = 'paused'
            return dict(next_node=END)
        result = data['result']
        accepted = result['review']['status'] in {'accepted', 'accepted_after_revision'}
        html = next(p for p in result['artifacts'] if p.endswith('.html'))
        md = next(p for p in result['artifacts'] if p.endswith('.md'))
        label = 'Reviewed report' if accepted else 'Draft — review has not passed'
        body = f'{label}\n\n[Open report]({html}) · [Markdown]({md})\n\n' + data['draft']['abstract']
        self.agent._record(state, 'assistant', body)
        self.agent._event(state, 'final', body)
        work = memory.work_state(state, 'report')
        memory.record_delivery(work, 'final', body)
        memory.apply_delivery(work)
        work['status'] = state['status'] = 'completed'
        if (state.get('pending') or {}).get('role') == 'report':
            state['pending'] = None
        self.agent.store.save(state)
        data['status'] = 'delivered'
        return dict(next_node=END)


def report_graph(agent):
    nodes = ReportNodes(agent)
    graph = StateGraph(Flow)
    graph.add_node('prepare', nodes.wrap(nodes.prepare))
    for name in STAGES:
        graph.add_node(name, nodes.wrap(nodes.stage(name)))
    graph.add_node('deliver', nodes.wrap(nodes.deliver))
    graph.add_edge(START, 'prepare')
    for name in ('prepare', *STAGES):
        graph.add_conditional_edges(name, lambda flow: flow['next_node'], [*STAGES, 'deliver', END])
    graph.add_edge('deliver', END)
    return graph.compile(name='report')
