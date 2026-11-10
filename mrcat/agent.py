"""Manager-led roles and MR item modes over one shared code execution engine."""
from pathlib import Path
from uuid import uuid4
import json
import os

from mrcat.state.store import write_json
from mrcat.runtime.execution import runtime_context
from mrcat.state.results import result_catalog, work_scope
from .skills import SkillRegistry
from mrcat.workflow import manager, tasks
from mrcat.state import memory

from mrcat.runtime.actions import parse_action


class Agent:
    def __init__(self, repo_root, store, *, model=None, max_rounds=None, execution_timeout=3600,
                 auto_confirm_plan=False):
        self.root = Path(repo_root).resolve()
        self.store = store
        self.skills = SkillRegistry(self.root / "skills")
        self.model = model or self._model
        self.max_rounds = int(max_rounds if max_rounds is not None else os.getenv("MRCAT_MAX_ROUNDS", "300"))
        if self.max_rounds < 1:
            raise ValueError("MRCAT_MAX_ROUNDS must be positive.")
        self.execution_timeout = execution_timeout
        self.auto_confirm_plan = auto_confirm_plan

    def context_budget(self, role):
        from .config.loader import load_repo_config
        from .model.llm_gateway import current_model
        from mrcat.model.context import ContextBudget
        config = load_repo_config(repo_root=self.root).config
        model = (config.llm.models.for_role('reporter') if role in {
            'report_selection', 'literature_claims', 'literature_verify', 'report_writer', 'report_judge'
        } else current_model(config))
        return ContextBudget.configured(model)

    def _model(self, *, role, system, user, structured_action=False, tools=None):
        from mrcat.config.loader import load_repo_config
        from mrcat.model.llm_gateway import call_text, OutputTruncatedError
        output_limit = int(os.getenv("MRCAT_MAX_OUTPUT_TOKENS", "32768"))
        retry_limit = int(os.getenv("MRCAT_MAX_RETRY_OUTPUT_TOKENS", "65536"))
        if output_limit <= 0 or retry_limit <= 0:
            raise ValueError("MRCAT output token budgets must be positive integers.")
        config = load_repo_config(repo_root=self.root).config
        options = {}
        if structured_action:
            from mrcat.model.llm_gateway import current_provider
            if current_provider(config) in {"deepseek", "openai", "anthropic"}:
                from mrcat.runtime.coding_protocol import REVIEW_TOOL, SUMMARY_TOOL, action_messages
                tool = {'evaluate': REVIEW_TOOL, 'memory': SUMMARY_TOOL}[role]
                options.update(action_tool=tool, thinking=False)
                system = f"Submit exactly one {role} decision through {tool['function']['name']}.\n" + system
                options["request_messages"] = action_messages(system, user)
        if tools:
            from mrcat.runtime.coding_protocol import action_messages
            from .model.llm_gateway import current_provider
            options.update(tools=tools, request_messages=action_messages(system, user),
                           thinking=current_provider(config) == 'deepseek')
        if role in {'report_selection', 'literature_claims', 'literature_verify', 'report_writer', 'report_judge'}:
            options.update(model=config.llm.models.for_role('reporter'),
                           temperature=config.llm.temperatures.roles.for_role('reporter'))
        if role in {'literature_claims', 'literature_verify', 'report_judge'}:
            options['thinking'] = False
        try:
            return call_text(system=system, user=user, agent_config=config, max_tokens=output_limit, **options)
        except OutputTruncatedError:
            budget = self.context_budget(role)
            increased_limit = min(output_limit * 2, retry_limit,
                                  budget.window - budget.margin - budget.measure(system, user, options.get('tools') or options.get('action_tool')))
            if increased_limit <= output_limit:
                raise
            return call_text(system=system, user=user, agent_config=config, max_tokens=increased_limit, **options)

    def prompt(self, name):
        return (self.root / "mrcat/prompts" / (name + ".md")).read_text()

    def executor_prompt(self, state, role):
        from mrcat.workflow.plan_items import current_item
        item = current_item(state['active_task']) if role == 'mr' else None
        if item and item['skill_id'] is None:
            from mrcat.runtime.coding_agent import SYSTEM
            return SYSTEM
        text = self.prompt('executor') + '\n' + self.prompt(role)
        if role == 'mr':
            item = current_item(state['active_task'])
            text += '\n' + self.prompt('mr_tool')
        return text

    def _call(self, state, role, system, user, *, structured_action=False, tools=None):
        from mrcat.model.llm_usage import read_llm_total_tokens, read_llm_call_count, read_llm_unreported_calls
        session = self.store.directory(state["session_id"])
        directory = session / "llm" / uuid4().hex
        item = None
        if role == 'mr' and state.get('active_task'):
            from mrcat.workflow.plan_items import current_item
            item = current_item(state['active_task'])
        write_json(directory / "prompt.json", dict(role=role, system=system, user=user, **({"tools": tools} if tools else {})))
        from .trace import llm_started, llm_finished
        llm_started(session, directory)
        budget = self.context_budget(role)
        tool = tools
        if structured_action:
            from mrcat.runtime.coding_protocol import REVIEW_TOOL, SUMMARY_TOOL
            tool = {'evaluate': REVIEW_TOOL, 'memory': SUMMARY_TOOL}[role]
        before = read_llm_total_tokens(session), read_llm_call_count(session), read_llm_unreported_calls(session)
        try:
            budget.check(system, user, tool)
            options = dict(structured_action=True) if structured_action and self.model == self._model else {}
            if tools:
                options["tools"] = tools
            result = self.model(role=role, system=system, user=user, **options)
            (directory / "response.txt").write_text(result)
            return result
        except Exception as exc:
            from mrcat.runtime.diagnostics import exception_details, redact_data
            details = exception_details(exc)
            if getattr(exc, "provider_response", None) is not None:
                response_path = directory / "provider_response.json"
                write_json(response_path, redact_data(exc.provider_response))
                details["provider_response"] = str(response_path.relative_to(session))
            write_json(directory / "error.json", details)
            exc.mrcat_diagnostic = str((directory / "error.json").relative_to(session))
            raise
        finally:
            from mrcat.model.context import tokens
            try:
                sections = json.loads(user)
            except (TypeError, ValueError):
                sections = {}
            section_tokens = {key: tokens(value) for key, value in sections.items()} if isinstance(sections, dict) else {}
            after = read_llm_total_tokens(session), read_llm_call_count(session), read_llm_unreported_calls(session)
            write_json(directory / "usage.json", dict(role=role, input_characters=len(system)+len(user),
                       estimated_input_tokens=budget.measure(system, user, tool),
                       input_token_budget=budget.input_limit, context_tokens=budget.window,
                       context_section_tokens=section_tokens,
                       item_id=item['step_id'] if item else None, skill=item['skill_id'] if item else None,
                       reported_total_tokens=after[0]-before[0] if after[1]>before[1] and after[2]==before[2] else None,
                       provider_calls=after[1]-before[1]))
            llm_finished(session, directory)

    def _event(self, state, kind, content="", **details):
        details.setdefault("agent", state["active_agent"])
        if state["active_agent"] == "mr" and state.get("active_task"):
            details.setdefault("task_id", state["active_task"]["task_id"])
        return self.store.event(state, kind, content, **details)

    def _record(self, state, role, content):
        state["messages"].append(dict(role=role, content=content, agent=state["active_agent"],
                                      task_id=(state.get("active_task") or {}).get("task_id") if state["active_agent"] == "mr" else None))
        self.store.save(state)
        from .trace import message_record
        message_record(self.store.directory(state['session_id']), state)

    def _plan(self, state, request, reason, *, recovery=None, effective_request=None, new_task=False):
        role = state["active_agent"]
        if role != "mr":
            raise ValueError("Only the MR subgraph can generate a Plan.")
        from mrcat.workflow.planning import planning_history
        from mrcat.workflow.plan_items import parse_plan, validate_reuse, recovery_view, completed_results
        work = None if new_task else state.get("active_task")
        if recovery and work:
            work = recovery_view(work, recovery.get('invalidate_steps', []), recovery['reason'],
                                 self.store.directory(state['session_id']))
        pending = state.get("pending")
        effective_request = effective_request or (pending or {}).get("request") or (work or {}).get("request") or request
        current_plan = (pending or {}).get("plan") or (work or {}).get("plan", "")
        planning_state = dict(state, active_task=work) if recovery else state
        available = planning_history(planning_state, self.store.directory(state['session_id']), self.skills,
                                     references=(effective_request, current_plan))
        variant = 'reuse' if state['task_history'] or (work and work.get('artifacts')) or recovery else 'initial'
        context = dict(latest_request=request, effective_request=effective_request, reason=reason, recovery=recovery,
                       skill_options=self.skills.planning_catalog(), available_results=available,
                       study_setup=state.get('study_setup'),
                       few_shot=self.prompt('planner.' + variant + '.fewshot'),
                       current_plan=current_plan, current_items=(pending or work or {}).get('plan_items', []),
                       completed_items=(work or {}).get('completed_items', {}),
                       completed_results=completed_results(work, self.store.directory(state['session_id'])) if work else [],
                       invalidated_items=[dict(step_id=row['step_id'], reason=row['reason'])
                                          for row in (work or {}).get('invalidated_items', [])],
                       task_memory=work["memory"] if work else "",
                       shared_memory={role: memory.excerpt(work["memory"], 350)
                                      for role, work in state["role_memory"].items()},
                       recent_messages=memory.recent_messages(state["messages"], limit=5000, count=4))
        for attempt in range(2):
            raw = self._call(state, "planner", self.prompt("planner"), json.dumps(context, ensure_ascii=False))
            try:
                plan = parse_plan(raw, (work or {}).get('completed_items', {}))
                for item in plan['items']:
                    if item['skill_id'] and not self.skills.get(item['skill_id']):
                        raise ValueError('Unknown skill guide: ' + item['skill_id'])
                validate_reuse(plan['items'], [*state['task_history'],
                    *([planning_state['active_task']] if planning_state.get('active_task') else [])])
                return plan
            except ValueError as exc:
                if attempt:
                    raise
                context['format_error'] = str(exc)
        raise AssertionError('Unreachable planner response state')

    def _publish_plan(self, state, plan, *, draft=False):
        if isinstance(plan, dict):
            plan = plan['text']
        state["plan"] = plan
        (self.store.directory(state["session_id"]) / "plan.md").write_text(plan)
        self._event(state, "plan_updated", plan, draft=draft)

    def needs_compaction(self, state, role):
        work = memory.work_state(state, role)
        if work.get('memory_attempt_upto') == len(state['messages']):
            return False
        context = self.executor_context(state, role)
        return self.context_budget(role).measure(self.executor_prompt(state, role), context) > self.context_budget(role).summary_trigger

    def compact_memory(self, state, role, *, force=False):
        from mrcat.model.context import tokens
        work = memory.work_state(state, role)
        if work.get('memory_attempt_upto') == len(state['messages']):
            return
        while force or self.needs_compaction(state, role):
            start = max(work.get('memory_upto', 0), work['context_start'])
            rows = [(i, m) for i, m in enumerate(state['messages']) if i >= start
                    and m in memory.relevant_messages([m], role=role, task_id=work.get('task_id'))]
            if not rows or (force and not any(m['role'] == 'observation' for _, m in rows)):
                return
            # Retain the recent suffix; only a successfully summarized prefix may leave it.
            context = dict(previous_memory=memory.working_note(work), latest_request=state['request'],
                           effective_request=work.get('request', state['request']),
                           task=memory.task_brief(state.get('active_task')) if role == 'mr' else None,
                           current_plan=work.get('plan', '') if role == 'mr' else '',
                           delivery=work.get('delivery'), execution_facts=work.get('execution_facts', []),
                           control_facts=memory.control_facts(state, role), observations=[])
            prompt = self.prompt('search_memory' if role == 'search' else 'memory')
            summary_budget = self.context_budget('memory')
            remaining = self.context_budget(role).measure(self.executor_prompt(state, role), self.executor_context(state, role))
            upto = start
            for index, message in rows:
                evidence = message['role'] in {'user', 'observation'}
                candidate = dict(context, observations=[*context['observations'], message]) if evidence else context
                if summary_budget.measure(prompt, candidate) > summary_budget.input_limit:
                    break
                context = candidate
                upto = index + 1
                remaining -= tokens(message)
                if not force and evidence and remaining <= self.context_budget(role).summary_target:
                    break
            if not context['observations']:
                if not force:
                    self.context_budget(role).check(self.executor_prompt(state, role), self.executor_context(state, role))
                return
            try:
                note = self._call(state, 'memory', prompt, json.dumps(context, ensure_ascii=False))
                work['memory'] = memory.completed_memory(note, role)
                work['memory_upto'] = upto
                work.pop('memory_attempt_upto', None)
                if not force:
                    self._event(state, 'memory_compacted', 'Summarized earlier evidence.', role=role, through_message=upto)
            except Exception as exc:
                work['memory_attempt_upto'] = len(state['messages'])
                self._event(state, 'memory_warning', f'Memory update unavailable: {type(exc).__name__}; history retained.')
                if not force:
                    self.context_budget(role).check(self.executor_prompt(state, role), self.executor_context(state, role))
                return
            if upto >= len(state['messages']):
                return
            if force:
                # Final delivery needs a working summary, not an extra pass over every historical cell.
                return

    def executor_context(self, state, role):
        from mrcat.workflow.plan_items import executor_view, current_item
        work = memory.work_state(state, role)
        directory = self.store.directory(state["session_id"])
        guide_id = work.get("guide")
        guide = self.skills.get(guide_id) if guide_id else None
        recent = [dict(role=row['role'], content=row['content']) for row in memory.relevant_messages(
            state['messages'], start=max(work['context_start'], work.get('item_context_start', 0), work.get('memory_upto', 0)),
            role=role, task_id=work.get('task_id'))]
        plan = work.get("plan", "") if role == "mr" else ""
        request = work.get("request", state["request"])
        selected = memory.referenced_tasks(state["task_history"], request, plan, state["request"])
        if role == 'mr' and current_item(work):
            source_ids = {ref.split('/')[0] for ref in current_item(work)['reuse_from']}
            selected = [task for task in state['task_history'] if task['task_id'] in source_ids]
        # A report without an explicit task reference defaults to the current/latest MR work.
        current_mr = state.get("active_task") if role == "report" and not selected else None
        if role == "report" and not selected and not current_mr:
            selected = state["task_history"][-1:]
        context = dict(role=role, latest_request=state["request"], runtime=runtime_context(),
                    task={key: work.get(key) for key in ("task_id", "status")} if role == "mr" else None,
                    current_plan=plan, memory=memory.working_note(work),
                    work_request=request, work_status=work.get("status", "running"),
                    prior_work=memory.work_history(work), execution_facts=work.get("execution_facts", []),
                    artifacts=work.get("artifacts", [])[-12:],
                    result_refs=result_catalog(directory, work_scope(work, role),
                        include_scopes=[t["task_id"] for t in selected] +
                            ([current_mr["task_id"]] if current_mr else [])),
                    control_facts=memory.control_facts(state, role),
                    evaluation=work.get('evaluation'),
                    other_role_summaries={name:dict(request=memory.excerpt(w.get("request", ""), 250),
                        status=w.get("status", "unknown"), summary=memory.excerpt(memory.working_note(w), 350),
                        artifacts=w.get("artifacts", [])[-6:])
                        for name,w in state["role_memory"].items() if name!=role},
                    current_mr_summary=dict(task_id=current_mr["task_id"],
                        memory=memory.excerpt(current_mr["memory"],1000),
                        artifacts=current_mr["artifacts"][-10:]) if current_mr else None,
                    saved_tasks=[dict(task_id=t["task_id"], request=t.get("request", ""), status=t["status"],
                                     memory=memory.excerpt(t["memory"],1000), artifacts=t["artifacts"][-10:])
                                 for t in selected],
                    skill_catalog=self.skills.catalog(),
                    active_guide=dict(name=guide.id, path=str(guide.skill_dir/"SKILL.md"),
                                      content=self.skills.read(guide.id)) if guide else None,
                    recent_messages=recent, repo_root=str(self.root), workspace=str(directory/"workspace"),
                    history_access='mrcat.tools.session_history(start=0, limit=50)')
        if role == 'mr' and current_item(work):
            context.update(executor_view(work, directory, state['task_history']))
            from mrcat.workflow.plan_items import item_results
            context['item_results'] = item_results(work, directory)
            context['execution_mode'] = 'tool' if current_item(work)['skill_id'] else 'codeact'
            if current_item(work)['skill_id']:
                # The current tool is chosen; compile its inputs from actual saved results.
                # Do not replay unrelated catalogs, roles or artifact inventories.
                for key in ('skill_catalog', 'other_role_summaries', 'prior_work', 'execution_facts',
                            'artifacts', 'saved_tasks', 'current_mr_summary'):
                    context.pop(key, None)
        return context

    def run(self, sid, request):
        from mrcat.model.llm_usage import llm_usage_scope
        from mrcat.model.llm_gateway import OutputTruncatedError
        from mrcat.model.context import ContextBudgetExceeded
        from .trace import session_trace
        with session_trace(self.store, sid), llm_usage_scope(self.store.directory(sid) / "llm_usage.json"):
            try:
                return self._run(sid, request)
            except (OutputTruncatedError, ContextBudgetExceeded) as exc:
                state = self.store.load(sid)
                state['status'] = 'waiting_user' if state.get('pending') else 'paused'
                if state.get('active_task'):
                    state['active_task']['status'] = 'paused'
                self._event(state, 'error', f'{exc} Saved plan and results are preserved; reply to retry.')
                self.store.save(state)
                return state
            except Exception as exc:
                state = self.store.load(sid)
                state["status"] = "failed"
                if state.get("active_agent")=="mr" and state.get("active_task"):
                    # A failed turn does not terminate the scientific task.
                    state['active_task']['status'] = 'paused'
                self._event(state, "error", f"{type(exc).__name__}: {exc}")
                raise

    def _run(self, sid, request):
        from mrcat.workflow.graph import run_graph
        return run_graph(self, sid, request)

    def _route_mr(self, state, decision, plan=None):
        action = decision["action"]
        pending = state.get("pending")
        task = state.get("active_task")
        if action=="cancel":
            if pending and pending.get("kind")=="plan_confirmation":
                state["pending"] = None
                state["plan"] = task["plan"] if task else ""
                if task:
                    state["memory_request"] = task["request"]
            else:
                tasks.archive_task(state,"cancelled")
                state["pending"] = None
            state["status"]="completed"
            self._event(state,"task_cancelled","Cancelled; saved files are retained.")
            return False
        if action in {"propose","revise"}:
            if action=="revise" and not task and not (pending and pending.get("kind")=="plan_confirmation"):
                raise ValueError("There is no active task or proposed plan to revise.")
            if plan is None:
                raise ValueError("The planner node must supply the proposed plan.")
            if self._stopped(state):
                return False
            proposal = dict(kind="plan_confirmation", request=decision["effective_request"],
                            description=decision.get("description") or (pending or {}).get("description") or (task or {}).get("description") or state["request"],
                            plan=plan['text'], plan_items=plan['items'], task_id=((pending or {}).get("task_id") if pending and pending.get("kind")=="plan_confirmation" else task["task_id"] if task else None) if action=="revise" else None,
                            question="Confirm the plan shown above, or describe the changes you want.")
            state["pending"] = proposal
            state["memory_request"] = proposal["request"]
            auto_confirm = (self.auto_confirm_plan and action == "propose"
                            and not task and not state["task_history"])
            execute = decision.get("execute", False) or auto_confirm
            self._publish_plan(state,plan,draft=not execute)
            if not execute:
                state["status"]="waiting_user"
                self._event(state,"question",proposal["question"])
                return False
            if auto_confirm:
                self._event(state, "plan_auto_confirmed", "Initial plan approved by benchmark execution policy.")
            action="confirm"
        if action=="confirm":
            pending=state.get("pending")
            if not pending or pending.get("kind")!="plan_confirmation":
                raise ValueError("There is no pending plan to confirm.")
            if pending.get("task_id"):
                if not task or task["task_id"]!=pending["task_id"]:
                    raise ValueError("The plan belongs to another task.")
                tasks.revise_task(task,dict(text=pending['plan'], items=pending['plan_items']),state["request"])
                task["request"]=pending["request"]
                task["description"]=pending["description"]
                task["memory"]=memory.replace_section(task["memory"], "Task Description", pending["request"])
                task["status"]="running"
                kind="task_revised"
            else:
                task=tasks.create_task(state,pending)
                kind="task_created"
            state["pending"]=None
            state["memory_request"]=task["request"]
            state["plan"]=task["plan"]
            self._event(state,kind,f"{task['task_id']}: {task['description']}")
            self._publish_plan(state,task["plan"])
            return True
        if action=="continue":
            if not task or task["status"] in tasks.TERMINAL:
                raise ValueError("There is no unfinished MR task to continue.")
            if pending and pending.get("kind")=="plan_confirmation":
                raise ValueError("Confirm or revise the pending plan before continuing.")
            if decision["effective_request"]:
                task["request"] = decision["effective_request"]
                task["memory"] = memory.replace_section(task["memory"], "Task Description", task["request"])
            task["status"]="running"
            state["pending"]=None
            state["memory_request"]=task["request"]
            state["plan"]=task["plan"]
            return True
        raise ValueError(f"Unsupported MR action: {action}")

    def _stopped(self,state):
        if not (self.store.directory(state["session_id"])/"STOP").exists():
            return False
        state["status"]="stopped"
        if state["active_agent"]=="mr" and state.get("active_task"):
            state["active_task"]["status"]="paused"
        self._event(state,"interrupted","Stopped; task, memory and files are preserved.")
        return True
