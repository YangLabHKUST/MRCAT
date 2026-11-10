"""Report artifacts and stage diagnostics use the native session workspace."""
from pathlib import Path
from time import perf_counter

from mrcat.state.store import write_json, now


class ReportFiles:
    def __init__(self, directory, run_id):
        self.directory = Path(directory)
        self.base = self.directory / 'workspace' / 'reports' / run_id
        self.base.mkdir(parents=True, exist_ok=True)

    def write_json(self, *, name, payload, **kwargs):
        path = self.base / (name + '.json')
        write_json(path, payload)
        return str(path.relative_to(self.directory))

    def write_text(self, *, name, content, suffix, **kwargs):
        path = self.base / (name + suffix)
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(path)
        return str(path.relative_to(self.directory))


class ReportExecution:
    def __init__(self, agent, state, data):
        self.agent, self.state, self.data = agent, state, data
        self.files = ReportFiles(agent.store.directory(state['session_id']), data['run_id'])
        self.progress = data.setdefault('progress', dict(status='running', stages=[], llm_calls=[], json_repair_count=0, writer_rewrite_count=0))
        self.progress_ref = str((self.files.base / 'report_execution.json').relative_to(self.files.directory))
        self.flush()

    def flush(self):
        self.files.write_json(name='report_execution', payload=self.progress)

    def publish(self, paths):
        work = self.state['role_memory']['report']
        work['artifacts'] = list(dict.fromkeys([*work.get('artifacts', []), *paths, self.progress_ref]))
        self.agent.store.save(self.state)

    def call(self, stage, function, **kwargs):
        if any(row['stage'] == stage and row['status'] == 'running' for row in self.progress['stages']):
            return function(**kwargs)
        row = dict(stage=stage, attempt=1 + sum(r['stage'] == stage for r in self.progress['stages']),
                   started_at=now(), status='running')
        if stage == 'writer_revision':
            self.progress['writer_rewrite_count'] += 1
        self.progress['stages'].append(row)
        self.flush()
        self.agent._event(self.state, 'report_stage', stage, stage=stage, status='running', run_id=self.data['run_id'])
        started = perf_counter()
        try:
            result = function(**kwargs)
            row['status'] = 'completed'
            return result
        except Exception as exc:
            from .policy import _error_summary
            row.update(status='failed', error=_error_summary(exc))
            self.progress['status'] = 'failed'
            raise
        finally:
            if row['status'] == 'running':
                row['status'] = 'interrupted'
                self.progress['status'] = 'paused'
            row.update(duration_seconds=round(perf_counter()-started, 3), finished_at=now())
            self.flush()
            self.agent._event(self.state, 'report_stage', stage, run_id=self.data['run_id'], **row)
