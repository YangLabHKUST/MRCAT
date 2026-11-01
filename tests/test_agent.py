from pathlib import Path
import json
import subprocess
import sys
import pytest
from mrcat.agent import Agent, parse_action
from mrcat.store import Store
from mrcat.execution import CodeExecutor
from mrcat.memory import initial_memory, render_memory

ROOT = Path(__file__).resolve().parents[1]


def decision(route="search", action="run", **values):
    return dict(route=route, action=action, message=None, **({"effective_request": None} | values))


def action(kind, body, **kwargs):
    return dict(type=kind, body=body, **kwargs)


def coding_action(kind, body, **kwargs):
    if kind == 'execute':
        return dict(tool='run', content=body, language=kwargs.get('language', 'python'))
    return dict(tool='finish', body=body, outcome=kwargs.get('outcome', 'complete'))


def native_reply(call, context=None):
    """Fixture model emits the native wire response used in production."""
    from uuid import uuid4
    call = dict(call)
    name = call.pop('tool')
    content = call.pop('message', None)
    if name == 'run':
        call.setdefault('purpose', 'compute')
        call.setdefault('language', 'python')
    if name == 'publish' and 'execution_id' not in call:
        history = (context or {}).get('action_history', [])
        call['execution_id'] = next(json.loads(row['content'])['execution_id'] for row in reversed(history)
                                    if row['role'] == 'tool' and 'execution_id' in json.loads(row['content']))
    return json.dumps(dict(role='assistant', content=content, tool_calls=[dict(id='call_' + uuid4().hex,
        type='function', function=dict(name=name, arguments=json.dumps(call)))]))


def journal_view(context):
    """Test evidence accessor for the native transcript; production sends no duplicate journal."""
    rows = []
    history = context.get('action_history', [])
    for i, message in enumerate(history):
        if message['role'] == 'assistant' and message.get('tool_calls'):
            function = message['tool_calls'][0]['function']
            rows.append(dict(tool=function['name'], arguments=json.loads(function['arguments']),
                             result=json.loads(history[i + 1]['content'])))
        elif message['role'] == 'user':
            rows.append(json.loads(message['content']))
    return rows


class Model:
    def __init__(self, actions=(), decisions=(), plans=(), evaluations=(), finalizations=()):
        self.actions = iter(actions)
        self.decisions = iter(decisions)
        self.plans = iter(plans)
        self.calls = []
        self.evaluations = iter(evaluations)
        self.finalizations = iter(finalizations)

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        context = json.loads(kwargs["user"])
        if kwargs["role"] == "manager":
            value = dict(next(self.decisions, decision()))
            if value['action'] in {'run', 'propose', 'revise'} and value['effective_request'] is None:
                value['effective_request'] = context['latest_request']
            return json.dumps(value)
        if kwargs["role"] == "planner":
            value = next(self.plans, "Inspect the files; compute and check the requested result.")
            if isinstance(value, dict):
                return json.dumps(value)
            if value.startswith(('{', '[', '```')):
                return value
            # Legacy test scenarios specify a prose objective. The fixture emits
            # the new wire protocol; production never converts prose to items.
            return json.dumps({'plan_items': [dict(step_id='work_' + str(len(context.get('completed_items', {}))+1),
                title=value, skill_id=None, reuse_from=[])]})
        if kwargs["role"] == "memory":
            if 'conversation' in context:
                return json.dumps(dict(objective='Continue the requested task',
                    decisions='Preserve the requested inputs.',
                    completed='Earlier execution evidence is saved in checkpoint history.',
                    active='Current script.', blockers='None recorded.',
                    next_steps='Verify the next operation.', references='Saved journal and scripts.'))
            return context["previous_memory"] + ("\nSaved artifact: workspace/result.csv." if "workspace/result.csv" in kwargs["user"] else "") + "\nRecent observations are saved in conversation.json; inspect them before reuse.\n[END_MEMORY]"
        if kwargs["role"] == "evaluate":
            handoff = context.get("handoff", {})
            if handoff:
                default = dict(route="execute" if handoff.get("outcome") == "complete" else "finalize" if handoff.get("body", "").startswith("Question: ") else "replan",
                               reason="Fixture accepts the evidence." if handoff.get("outcome") == "complete" else "Fixture obstacle requires resolution.")
                if default['route'] == 'execute':
                    default['accept_item'] = True
            else:
                default = dict(route="continue", reason="Useful inspection can continue.", message="Use the observations for the next action.")
            return json.dumps(next(self.evaluations, default))
        if kwargs["role"] == "finalize":
            body = context["handoff"]["body"]
            status = 'blocked' if body.startswith('Question: ') else 'completed'
            if status == 'completed' and context.get('result_sources'):
                def scalar_path(value, path=''):
                    if isinstance(value, dict):
                        for key, child in value.items():
                            found = scalar_path(child, path + '/' + key.replace('~', '~0').replace('/', '~1'))
                            if found is not None:
                                return found
                    elif isinstance(value, list):
                        for index, child in enumerate(value):
                            found = scalar_path(child, path + '/' + str(index))
                            if found is not None:
                                return found
                    elif value is not None:
                        return path
                    return None
                body = '\n\n'.join('{{value:' + source['id'] + path + '}}'
                                  for source in context['result_sources']
                                  if (path := scalar_path(source['data'])) is not None)
            return next(self.finalizations, status + "\n" + body.removeprefix('Question: ') + "\n[END_FINAL_SUMMARY]")
        result = next(self.actions)
        if callable(result):
            result = result(context)
        result = result if isinstance(result, dict) else action("final", result)
        # Existing scenarios describe semantic intentions; emit the current
        # role-specific wire protocol, not deprecated MR final/ask/evaluate.
        if kwargs["role"] == "mr" and result.get("type") in {"final", "ask", "evaluate"}:
            body = ("Question: " if result["type"] == "ask" else "") + result["body"]
            result = action("end", body, outcome="complete" if result["type"] == "final" else "blocked")
        if kwargs["role"] == "mr" and 'action_history' in context and 'type' in result:
            if result['type'] == 'execute':
                result = dict(tool='run', content=result['body'], language=result.get('language', 'python'), message=result.get('message', ''))
            elif result['type'] == 'skill':
                result = dict(tool='docs', id=result['body'])
            elif result['type'] == 'end':
                result = dict(tool='finish', outcome=result.get('outcome', 'complete'), body=result['body'])
        return native_reply(result, context) if kwargs.get('tools') else json.dumps(result)


def verified_value(value=42, name='answer'):
    """Execute and publish a supplied scalar for lifecycle-only test scenarios."""
    return action('execute', 'from mrcat.tools import publish_result\n'
                  f'value = {value!r}\nassert value == {value!r}\n'
                  f'publish_result({name!r}, {{"value": value}})')


def create(tmp_path, question="Calculate a sum"):
    store = Store(tmp_path)
    state = store.create(question, "openai")
    return store, state["session_id"]


def test_unknown_task_error_repair_and_file_state(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', 'raise ValueError("inspect input")'),
                   action('execute', 'from pathlib import Path; Path("sum.txt").write_text("10")'),
                   action('execute', 'from pathlib import Path; assert Path("sum.txt").read_text()=="10"; print("verified 10")'),
                   'The sum is 10.'])
    done = Agent(ROOT, store, model=model).run(sid, "Calculate a sum")
    cells = [e["details"] for e in done["events"] if e["type"] == "code_execution"]
    assert done["status"] == "completed" and cells[0]["returncode"] != 0
    assert cells[2]["stdout"].strip() == "verified 10"
    assert cells[1]["generated_files"] == ["workspace/sum.txt"]
    assert sum(c["role"] == "manager" for c in model.calls) == 1
    assert sum(c["role"] == "planner" for c in model.calls) == 0
    assert "ValueError" in [c for c in model.calls if c["role"] == "search"][1]["user"]
    assert done["active_task"] is None


def test_greeting_does_not_plan_and_mr_proposal_does_not_create_task(tmp_path):
    store, sid = create(tmp_path, "Hello")
    model = Model(decisions=[decision("respond", "respond", message_override="unused")])
    model.decisions = iter([decision("respond", "respond") | {"message": "Hello!"},
                            decision("mr", "propose", description="BMI to T2D")])
    agent = Agent(ROOT, store, model=model)
    greeting = agent.run(sid, "Hello")
    assert [c["role"] for c in model.calls] == ["manager"]
    assert greeting["plan"] == "" and greeting["active_task"] is None
    proposal = agent.run(sid, "Analyze BMI to T2D")
    assert proposal["status"] == "waiting_user" and proposal["active_task"] is None
    assert proposal["pending"]["kind"] == "plan_confirmation"
    assert proposal["next_task_no"] == 1
    assert "## task1" not in render_memory(store.load(sid))


def test_plan_revision_confirmation_and_same_task_resume(tmp_path):
    store, sid = create(tmp_path, "Analyze BMI")
    model = Model([action('ask', 'Which supplied file should I use?'),
                   action('execute', 'from pathlib import Path; Path("result.txt").write_text("checked")\nfrom mrcat.tools import publish_result\npublish_result("result", {"text": Path("result.txt").read_text()})'),
                   'Analysis completed with stated limitations.'],
                  [decision("mr","propose",description="BMI analysis"),
                   decision("mr","revise",description="BMI analysis using native effects"),
                   decision("respond","respond") | {"message":"IVW combines estimates."},
                   decision("mr","confirm"), decision("mr","continue")],
                  ["Inspect and analyze BMI.", "Use native effects; inspect and analyze BMI."])
    agent = Agent(ROOT, store, model=model)
    agent.run(sid,"Analyze BMI")
    revised = agent.run(sid,"Use native effects")
    assert revised["pending"]["plan_items"][0]["title"].startswith("Use native")
    explained = agent.run(sid,"Explain IVW")
    assert explained["pending"] == revised["pending"] and explained["active_task"] is None
    waiting = agent.run(sid,"Proceed")
    assert waiting["active_task"]["task_id"] == "task1"
    assert waiting["active_task"]["status"] == "waiting_user"
    done = agent.run(sid,"Use file A")
    assert done["active_task"] is None and done["task_history"][0]["task_id"] == "task1"
    assert any(p.endswith("/result.txt") for p in done["task_history"][0]["artifacts"])
    assert sum(c["role"] == "planner" for c in model.calls) == 2
    assert "### Confirmed Facts" in render_memory(store.load(sid))


def test_active_plan_changes_keep_identity_and_history(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('ask', 'Need a data file.'), action('ask', 'Confirm the file metadata.')],
                  [decision("mr","propose",execute=True,description="Analysis"),
                   decision("mr","revise",execute=True,description="Analysis on file B")],
                  ["Inspect file A.", "Inspect file B."])
    agent = Agent(ROOT, store, model=model)
    first = agent.run(sid,"Analyze now using file A")
    changed = agent.run(sid,"Switch to file B and continue")
    assert changed["active_task"]["task_id"] == first["active_task"]["task_id"] == "task1"
    assert len(changed["active_task"]["plan_history"]) == 2
    assert changed["next_task_no"] == 2


def test_new_task_preserves_finished_task_history(tmp_path):
    store, sid = create(tmp_path)
    model = Model([verified_value(), 'First analysis done.', verified_value(), 'New analysis done.'],
                  [decision("mr", "propose", execute=True, description="First study"),
                   decision("mr", "propose", execute=True, description="Second study")])
    agent = Agent(ROOT, store, model=model)
    first = agent.run(sid, "Run first study now")
    frozen = first["task_history"][0]
    last = agent.run(sid, "Run second study now")
    assert [t["task_id"] for t in last["task_history"]] == ["task1", "task2"]
    assert last["task_history"][0] == frozen


def test_cancel_proposal_does_not_create_task(tmp_path):
    store, sid = create(tmp_path)
    model = Model(decisions=[decision("mr","propose"), decision("mr","cancel")])
    agent = Agent(ROOT,store,model=model)
    agent.run(sid,"Plan MR")
    done = agent.run(sid,"Cancel")
    assert done["pending"] is None and done["active_task"] is None and not done["task_history"]


def test_no_host_acceptance_gate(tmp_path):
    store, sid = create(tmp_path)
    done = Agent(ROOT,store,model=Model([action('execute', 'raise RuntimeError("unavailable")'),
        'No estimate can be reported.'])).run(sid,"Inspect input")
    assert done["status"] == "completed"
    assert next(e for e in done["events"] if e["type"] == "code_execution")["details"]["returncode"] != 0


def test_budget_pauses_task_without_completing(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', 'print(1)')],[decision("mr","propose",execute=True)])
    done = Agent(ROOT,store,model=model,max_rounds=1).run(sid,"Run now")
    assert done["status"] == "paused" and done["active_task"]["status"] == "paused"
    assert not done["task_history"]


def test_guide_and_evaluation_do_not_replan_by_themselves(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('skill', 'mr-bwmr'),action('evaluate', 'Inspect inputs.'),'Suitable data are needed.'])
    done = Agent(ROOT,store,model=model).run(sid,"Inspect BWMR inputs")
    assert done["loaded_skills"] == ["mr-bwmr"]
    assert sum(c["role"] == "planner" for c in model.calls) == 0
    context = json.loads([c for c in model.calls if c["role"] == "search"][-1]["user"])
    assert context["active_guide"]["name"] == "mr-bwmr"
    assert "loaded_skills" not in context


@pytest.mark.parametrize("language,code,expected",[("python","print(7)","7"),("bash","printf shell-ok","shell-ok"),("r","cat(6*7)","42")])
def test_languages(tmp_path,language,code,expected):
    result = CodeExecutor(ROOT,tmp_path).execute(code,language,"cell")
    assert result["returncode"] == 0, result
    assert result["stdout"].strip() == expected


def test_timeout_reaps_child_group(tmp_path):
    code = "import subprocess,time; from pathlib import Path; p=subprocess.Popen(['sleep','20']); Path('child.pid').write_text(str(p.pid)); time.sleep(20)"
    result = CodeExecutor(ROOT,tmp_path,timeout=.3).execute(code,"python","slow")
    assert result["status"] == "timeout" and result["returncode"] != 0
    assert not (tmp_path/"execution_process.json").exists()


def test_stop_prevents_even_manager_call(tmp_path):
    store, sid = create(tmp_path)
    (store.directory(sid)/"STOP").touch()
    model = Model()
    done = Agent(ROOT,store,model=model).run(sid,"Do not run")
    assert done["status"] == "stopped" and not model.calls


def test_direct_tool_result_is_an_observation(tmp_path):
    code = """
import json, os, runpy
from pathlib import Path
implementation = Path(os.environ['MRCAT_ROOT']) / 'skills/mr-bwmr/scripts/run_mr_bwmr.py'
method = runpy.run_path(str(implementation))
print(json.dumps(method['run']({'mrdat_path': 'missing.tsv', 'extra': 'kept'})))
"""
    store,sid = create(tmp_path)
    done = Agent(ROOT,store,model=Model([action('execute', code), 'Missing data; no conclusion.'])).run(sid,"Inspect")
    cell = next(e["details"] for e in done["events"] if e["type"] == "code_execution")
    assert json.loads(cell["stdout"])["outputs"]["status"] == "blocked"
    assert done["status"] == "completed"


def test_every_documented_tool_example_binds():
    import ast
    import inspect
    import re
    from mrcat import tools
    for guide in sorted((ROOT / "skills").glob("*/SKILL.md")):
        if guide.parent.name == "gwas-select":
            continue
        text = guide.read_text()
        example = re.search(r"```python\n(.*?)\n```", text, re.S)[1]
        tree = ast.parse(example)
        name = guide.parent.name.replace("-", "_")
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == name)
        function = getattr(tools, name)
        inspect.signature(function).bind(**{k.arg: ast.literal_eval(k.value) for k in call.keywords})
        documented = set(re.findall(r"^\| `([^`]+)` \|", text, re.M))
        assert documented == set(inspect.signature(function).parameters), guide.parent.name


def test_schema_docs_only():
    guides = list((ROOT/"skills").glob("*/SKILL.md"))
    assert len(guides) == 26
    assert not list((ROOT/"skills").rglob("input_schema.yaml"))
    assert not list((ROOT/"skills").rglob("validate_submit.py"))
    assert not (ROOT/"mrcat/capabilities.py").exists()


def test_plain_text_final_has_no_output_schema(tmp_path):
    store,sid = create(tmp_path)
    done = Agent(ROOT,store,model=Model(['Ordinary answer.'])).run(sid,"Explain")
    assert done["events"][-1]["content"] == 'Ordinary answer.'


def test_incomplete_code_is_not_silently_finalized():
    with pytest.raises(ValueError):
        parse_action('<execute language="python">print(1)')


def test_context_stays_bounded_and_full_history_remains_on_disk(tmp_path):
    store,sid = create(tmp_path)
    state = store.load(sid)
    state['role_memory']['search'] = dict(memory=initial_memory('Inspect files'),memory_upto=100,context_start=0,guide='mr-bwmr')
    state['messages'] = [dict(role='observation',content='x'*20000) for _ in range(100)]
    state['loaded_skills'] = [p.parent.name for p in (ROOT/'skills').glob('*/SKILL.md')]
    store.save(state)
    model = Model(['Done.'])
    agent = Agent(ROOT,store,model=model)
    context = agent.executor_context(state,'search')
    assert len(json.dumps(context,ensure_ascii=False)) < 26000
    assert context['active_guide']['content'] == (ROOT/'skills/mr-bwmr/SKILL.md').read_text()
    assert len(context['recent_messages']) <= 8
    done = agent.run(sid,'Continue inspection')
    assert len(done['messages']) > 100
    store.export(store.load(sid))
    assert len((store.directory(sid)/'conversation.json').read_text()) > 2000000
    assert all(len(c['user']) < 30000 for c in model.calls)


def test_usage_is_not_fabricated_for_a_mock_model(tmp_path):
    store,sid = create(tmp_path)
    Agent(ROOT,store,model=Model(['Done.'])).run(sid,'Inspect')
    calls = list((store.directory(sid)/'llm').glob('*/usage.json'))
    assert calls and all(json.loads(p.read_text())['reported_total_tokens'] is None for p in calls)


def test_role_context_uses_summaries_not_other_agents_code(tmp_path):
    store,sid = create(tmp_path)
    state = store.load(sid)
    state['role_memory'] = {
        'search': dict(memory='Search found dataset in workspace/study.json.',memory_upto=0,context_start=0,guide=None),
        'report': dict(memory='Write a report.',memory_upto=0,context_start=0,guide=None),
    }
    state['messages'] = [
        dict(role='assistant',agent='search',content='PRIVATE_SEARCH_CODE_NOT_NEEDED_IN_REPORT'),
        dict(role='observation',agent='search',content='HUGE_SEARCH_OUTPUT_NOT_NEEDED_IN_REPORT'),
        dict(role='user',agent='manager',content='Write a report'),
    ]
    context = Agent(ROOT,store).executor_context(state,'report')
    text = json.dumps(context)
    assert 'PRIVATE_SEARCH_CODE' not in text and 'HUGE_SEARCH_OUTPUT' not in text
    assert 'workspace/study.json' in text


def test_memory_service_failure_does_not_discard_final_answer(tmp_path):
    store,sid = create(tmp_path)
    base = Model([action('execute', 'print(42)'), 'Here is the saved result.'])
    def model(**kwargs):
        if kwargs['role']=='memory': raise RuntimeError('temporary summary error')
        return base(**kwargs)
    done = Agent(ROOT,store,model=model).run(sid,'Inspect')
    assert done['status']=='completed' and any(e['type']=='final' and e['content']=='Here is the saved result.' for e in done['events'])
    assert any(e['type']=='memory_warning' for e in done['events'])


def test_revising_a_new_proposal_does_not_overwrite_an_older_active_task(tmp_path):
    store,sid = create(tmp_path)
    model = Model([action('ask', 'Need study A input.'), verified_value(), 'Study B finished.'],[
        decision('mr','propose',execute=True,description='Study A'),
        decision('mr','propose',description='Study B'),
        decision('mr','revise',description='Study B revised'),
        decision('mr','confirm'),
    ],['Plan A.','Plan B.','Plan B revised.'])
    agent = Agent(ROOT,store,model=model)
    agent.run(sid,'Run study A now')
    proposed = agent.run(sid,'Plan a separate study B')
    assert proposed['active_task']['task_id']=='task1' and proposed['pending']['task_id'] is None
    revised = agent.run(sid,'Revise study B inputs')
    assert revised['pending']['task_id'] is None
    done = agent.run(sid,'Confirm study B')
    assert [t['task_id'] for t in done['task_history']]==['task1','task2']
    assert done['task_history'][0]['plan_items'][0]['title']=='Plan A.'
    assert done['task_history'][1]['plan_items'][0]['title']=='Plan B revised.'


def test_provider_response_without_usage_is_unknown_not_zero_cost(tmp_path):
    from mrcat.model.llm_usage import record_llm_usage
    store,sid = create(tmp_path)
    base = Model(['Done.'])
    def model(**kwargs):
        record_llm_usage(None)
        return base(**kwargs)
    Agent(ROOT,store,model=model).run(sid,'Inspect')
    usage=json.loads((store.directory(sid)/'llm_usage.json').read_text())
    assert usage['llm_unreported_usage_calls']==usage['llm_call_count']==2
    calls=[json.loads(p.read_text()) for p in (store.directory(sid)/'llm').glob('*/usage.json')]
    assert all(call['provider_calls']==1 and call['reported_total_tokens'] is None for call in calls)
