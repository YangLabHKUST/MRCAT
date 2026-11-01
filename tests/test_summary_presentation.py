"""Readable Answer tables must retain saved estimates and leave evidence untouched."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from mrcat.finalization import format_saved_summary, render_summary
from mrcat.web.server import create_app


ROOT = Path(__file__).resolve().parents[1]


def method(method='IVW', **updates):
    return dict(method=method, display_label=method, source_result_path='workspace/source.json',
                input_scale='standardize', endpoint='mr_primary', Threshold=5e-5,
                selection_threshold=5e-5, nsnp=31, nvalid=None,
                **{'beta.hat': -.00453795572743985, 'se': .00314786339337296,
                   'pval': .149415619724115,
                   'ci': {'level': .95, 'ranges': [{'lower': -.0107077679784509,
                                                   'upper': .00163185652357116}]}}, **updates)


def old_summary(rows):
    labels = {'method': 'Method', 'beta.hat': 'Beta', 'se': 'SE', 'pval': 'P value',
              'nsnp': 'SNPs', 'Threshold': 'Instrument selection P threshold', 'ci': 'CI'}
    fields = list(rows[0])
    lines = ['| ' + ' | '.join(labels.get(key, key) for key in fields) + ' |',
             '| ' + ' | '.join('---' for key in fields) + ' |']
    lines += ['| ' + ' | '.join(value if isinstance(value, str) else json.dumps(value)
                              for value in row.values()) + ' |' for row in rows]
    return ('Saved explanation.\n\n' + '\n'.join(lines) +
            '\n\n[r1](<workspace/source.json>)\n\nSaved interpretation.\n')


def test_mr_table_hides_metadata_formats_ci_and_preserves_scalar_provenance():
    record = {'methods': [method()]}
    original = deepcopy(record)
    source = dict(id='r1', path='workspace/source.json', data=record)
    result = format_saved_summary(old_summary(record['methods'])) + '\n' + render_summary('{{value:r1/methods/0/pval}}', [source], status='completed')
    assert '| Method | Beta | CI | P value | SNPs |' in result
    assert '[-0.0107078, 0.00163186] (95%)' in result
    assert '-0.00453796' in result and '0.149416' in result
    assert result.endswith('0.149415619724115')
    for field in ['display_label', 'source_result_path', 'input_scale', 'endpoint', 'selection_threshold', 'nvalid']:
        assert field not in result
    assert '"ranges"' not in result
    assert result.count('5e-05') == 1
    assert '[r1](<workspace/source.json>)' in result
    assert record == original


def test_ci_keeps_disconnected_ranges_and_recorded_confidence_level():
    row = method()
    row['ci'] = {'level': .9, 'ranges': [{'lower': -2, 'upper': -1}, {'lower': 1, 'upper': 2}]}
    result = format_saved_summary(old_summary([row]))
    assert '[-2, -1] ∪ [1, 2] (90%)' in result
    assert '[-2, 2]' not in result and '95%' not in result


@pytest.mark.parametrize('ci', [None, {}, {'ranges': []},
                                {'ranges': [{'lower': None, 'upper': 1}]},
                                {'ranges': [{'lower': 2, 'upper': 1}]}])
def test_missing_or_invalid_ci_is_not_reconstructed_from_beta_and_se(ci):
    row = method(); row['ci'] = ci
    result = format_saved_summary(old_summary([row]))
    assert '| -0.00453796 | — |' in result
    assert '95%' not in result


def test_selection_and_mrapss_correction_thresholds_remain_distinct():
    row = method('MR-APSS'); row.update(Threshold=1e-4, selection_threshold=5e-5)
    result = format_saved_summary(old_summary([method(), row]))
    assert 'Instrument selection P threshold (IVW, MR-APSS): 5e-05.' in result
    assert 'MR-APSS selection-bias correction threshold: 0.0001.' in result
    assert 'threshold' not in result.splitlines()[2]


def test_existing_summary_is_idempotent_and_prose_and_links_are_unchanged():
    old = old_summary([method()])
    result = format_saved_summary(old)
    assert result != old
    assert result.startswith('Saved explanation.\n\n')
    assert result.endswith('\n\n[r1](<workspace/source.json>)\n\nSaved interpretation.\n')
    assert format_saved_summary(result) == result
    assert format_saved_summary('```markdown\n' + old + '```') == '```markdown\n' + old + '```'
    assert format_saved_summary('| Field | Saved value |\n| --- | --- |\n| count | 42 |') == '| Field | Saved value |\n| --- | --- |\n| count | 42 |'


def test_custom_method_schema_uses_model_authored_table():
    source = dict(id='r1', path='workspace/custom.json', data={
        'methods': [{'method': 'permutation', 'statistic': 2.5, 'replicates': 199}]})
    result = render_summary('| Method | Statistic |\n| --- | --- |\n'
                            '| permutation | {{value:r1/methods/0/statistic}} |', [source], status='completed')
    assert '| permutation | 2.5 |' in result


def test_repeated_methods_use_one_label_column_and_missing_se_is_omitted():
    first, second = method(), method()
    first.update(display_label='IVW [discovery]', se=None)
    second.update(display_label='IVW [replication]', se=None)
    result = format_saved_summary(old_summary([first, second]))
    assert 'display_label' not in result and '| SE |' not in result
    assert '| IVW [discovery] |' in result and '| IVW [replication] |' in result


def test_se_is_shown_when_ci_is_unavailable():
    row = method(); row['ci'] = None
    result = format_saved_summary(old_summary([row]))
    assert result.splitlines()[2] == '| Method | Beta | CI | SE | P value | SNPs |'
    assert '| -0.00453796 | — | 0.00314786 |' in result


def test_saved_answer_projection_does_not_change_checkpoints_files_or_raw_downloads(tmp_path):
    app = create_app(repo_root=ROOT, artifact_dir=tmp_path)
    service = app.state.service
    state = service.store.create('Display the saved Answer', 'openai')
    sid = state['session_id']
    original = old_summary([method()])
    ref = 'workspace/outputs/task1/final_summary.md'
    task = dict(task_id='task1', status='completed', final_summary=original,
                artifacts=[ref], evaluation={'route': 'finalize'})
    state.update(status='completed', active_agent='mr', task_history=[task])
    state['events'] = [dict(id='final1', type='final', timestamp='1', content=original,
                           details={'agent': 'mr', 'task_id': 'task1'})]
    service.store.save(state)
    path = service.store.directory(sid) / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(original)
    expected = format_saved_summary(original)
    with TestClient(app) as client, patch('mrcat.agent.Agent._call', side_effect=AssertionError('No model call is needed')):
        snapshot = client.get(f'/api/sessions/{sid}').json()
        assert snapshot['mr']['events'][0]['content'] == expected
        assert snapshot['mr']['state']['task_history'][0]['final_summary'] == expected
        assert snapshot['final_report']['markdown'] == expected
        assert 'display_label' not in snapshot['final_report']['html']
        # The raw API remains a faithful download of the original evidence.
        response = client.get(f'/api/sessions/{sid}/artifacts/raw', params={'summary': ref})
        assert response.text == original
        assert path.read_text() == original
        assert service.store.load(sid)['task_history'][0]['final_summary'] == original
        assert service.store.load(sid)['events'][0]['content'] == original
