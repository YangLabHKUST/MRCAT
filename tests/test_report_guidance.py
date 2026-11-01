"""Report guidance follows selected evidence and remains owned by Skill Markdown."""
from pathlib import Path

from mrcat.report.evidence import fingerprint
from mrcat.report.guidance import skill_interpretation_guidance


ROOT = Path(__file__).resolve().parents[1]


def guide(root, skill_id, content):
    path = root / 'skills' / skill_id / 'SKILL.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def step(skill_id, outputs=None, status='completed'):
    return dict(skill_id=skill_id, status=status, outputs=outputs or {})


def test_guidance_includes_only_interpretation_from_selected_completed_skills(tmp_path):
    guide(tmp_path, 'mr-primary', '# Method\n## Use in Python\nEXECUTION_ONLY\n'
          '## Method Interpretation\nVALID_IV_ASSUMPTION\n'
          '## Outputs and checks\nOUTPUT_ONLY\n')
    guide(tmp_path, 'analysis-sensitivity', '## Interpreting Steiger results\nSTEIGER_LIMIT\n'
          '## Interpretation by the agent\nBOILERPLATE\n'
          '## Scientific interpretation checks\nDIAGNOSTIC_LIMIT\n')
    guide(tmp_path, 'mr-cause', '## Method Interpretation\nUNSELECTED_METHOD\n')
    guide(tmp_path, 'mr-bwmr', '## Method Interpretation\nFAILED_METHOD\n')
    selected = [step('mr-primary'), step('mr-primary'), step('analysis-sensitivity'),
                step(None), step('mr-bwmr', status='failed')]
    actual = skill_interpretation_guidance(tmp_path, selected)
    assert [row['skill_id'] for row in actual] == ['analysis-sensitivity', 'mr-primary']
    assert actual[1]['source'] == 'skills/mr-primary/SKILL.md'
    content = '\n'.join(row['content'] for row in actual)
    assert all(text in content for text in ['VALID_IV_ASSUMPTION', 'STEIGER_LIMIT', 'DIAGNOSTIC_LIMIT'])
    assert not any(text in content for text in ['EXECUTION_ONLY', 'OUTPUT_ONLY', 'BOILERPLATE',
                                              'UNSELECTED_METHOD', 'FAILED_METHOD'])


def test_aggregation_loads_only_its_actual_completed_producer_guidance(tmp_path):
    for name in ['analysis-method-comparison', 'mr-primary', 'mr-cause', 'mr-bwmr']:
        guide(tmp_path, name, f'## Method Interpretation\n{name} assumptions\n')
    primary = step('mr-primary', {'result': {'result_record_path': '/saved/primary.json'}})
    cause = step('mr-cause', {'result': {'result_record_path': '/saved/cause.json'}})
    unrelated = step('mr-bwmr', {'result': {'result_record_path': '/saved/bwmr.json'}})
    comparison = step('analysis-method-comparison', {'result': {
        'diagnostics': {'source_result_paths': ['/saved/primary.json', '/saved/cause.json']}}})
    actual = skill_interpretation_guidance(tmp_path, [comparison],
                                          [comparison, primary, cause, unrelated])
    assert [row['skill_id'] for row in actual] == ['analysis-method-comparison', 'mr-cause', 'mr-primary']
    cause['status'] = 'failed'
    actual = skill_interpretation_guidance(tmp_path, [comparison], [primary, cause, unrelated])
    assert [row['skill_id'] for row in actual] == ['analysis-method-comparison', 'mr-primary']


def test_skill_rule_changes_invalidate_report_continuation(tmp_path):
    prompts = tmp_path / 'mrcat' / 'prompts'
    prompts.mkdir(parents=True)
    (prompts / 'report.md').write_text('Report policy')
    path = guide(tmp_path, 'mr-primary', '## Method Interpretation\nOriginal constraint\n'
                 '## Use in Python\nOriginal calling example\n')
    rows = [{'steps': [step('mr-primary')]}]
    before = fingerprint(rows, tmp_path, 'Write a report')
    path.write_text(path.read_text().replace('Original calling example', 'Updated calling example'))
    assert fingerprint(rows, tmp_path, 'Write a report') == before
    path.write_text(path.read_text().replace('Original constraint', 'Updated scientific constraint'))
    assert fingerprint(rows, tmp_path, 'Write a report') != before


def test_every_registered_estimator_and_analysis_has_skill_owned_guidance():
    names = sorted(path.parent.name for path in (ROOT / 'skills').glob('*/SKILL.md')
                   if path.parent.name.startswith(('mr-', 'analysis-')))
    actual = skill_interpretation_guidance(ROOT, [step(name) for name in names])
    assert [row['skill_id'] for row in actual] == names
    for row in actual:
        assert (ROOT / row['source']).is_file()
        assert row['content']


def test_report_writer_and_judge_share_guidance_without_extra_model_calls(tmp_path):
    from collections import Counter
    import json
    from test_report_pipeline import ReportModel, report_run, checkpoint

    model = ReportModel()
    store, sid, before, result = report_run(tmp_path, model)
    assert result['status'] == 'completed'
    assert result['task_history'] == before
    data = checkpoint(store, sid)
    writer = json.loads(next(c['user'] for c in model.calls if c['role'] == 'report_writer'))
    judge = json.loads(next(c['user'] for c in model.calls if c['role'] == 'report_judge'))
    guidance = writer['Skill Interpretation Guidance']
    assert guidance == judge['Skill Interpretation Guidance']
    assert [row['skill_id'] for row in guidance] == ['mr-primary']
    assert 'InSIDE' in guidance[0]['content']
    assert guidance == data['report_context']['skill_interpretation_guidance']
    assert 'skill_interpretation_guidance' not in writer['Original Analysis Evidence']
    assert 'skill_interpretation_guidance' not in judge['Original Analysis Evidence']
    assert Counter(c['role'] for c in model.calls) == Counter(
        manager=1, report_selection=1, literature_claims=1, report_writer=1, report_judge=1)
