"""Scale interpretation must not replace numeric processing checks."""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.r

from mrcat import tools

ROOT = Path(__file__).resolve().parents[1]
RSCRIPT = os.environ.get('RSCRIPT_BIN', str(Path(sys.executable).with_name("Rscript")))


@pytest.mark.parametrize('scale', ['standardize', 'native'])
def test_primary_preserves_fitted_representation_without_unit_label(tmp_path, scale):
    data = tmp_path / 'pair.tsv'
    fields = ['SNP', 'b.exp', 'b.out', 'se.exp', 'se.out', 'pval.exp',
              'Z.exp', 'Z.out', 'N.exp', 'N.out',
              'b.exp.native', 'b.out.native', 'se.exp.native', 'se.out.native']
    with data.open('w') as handle:
        writer = csv.writer(handle, delimiter='\t'); writer.writerow(fields)
        for i in range(24):
            bx = .1 + (i % 7) * .013
            by = .35 * bx + ((i % 5) - 2) * .002
            writer.writerow([f'rs{i+1}', bx, by, .01, .01, 1e-10,
                             bx/.01, by/.01, 10000, 10000,
                             bx*2, by*3, .02, .03])
    result = tools.mr_primary(mrdat_path=data, input_scale=scale, output_dir=tmp_path/'fit')
    assert result['outputs']['status'] == 'ok', result
    record = result['outputs']['mr_primary_result']
    assert record['input_scale'] == scale
    assert 'effect_scale' not in record
    rows = list(csv.DictReader(Path(record['selected_mrdat_path']).open(), delimiter='\t'))
    assert len(rows) == 24
    assert float(rows[0]['b.exp']) == pytest.approx(.1 if scale == 'standardize' else .2)
    assert float(rows[0]['se.out']) == pytest.approx(.01 if scale == 'standardize' else .03)
    ivw = next(row for row in record['methods'] if row['method'] == 'IVW')
    xs = [float(row['b.exp']) for row in rows]
    ys = [float(row['b.out']) for row in rows]
    # The R result writer rounds JSON numbers to four decimal places.
    assert ivw['beta.hat'] == pytest.approx(sum(x*y for x,y in zip(xs,ys))/sum(x*x for x in xs), abs=5.1e-5)


def test_missing_native_statistics_still_fail():
    script = ROOT / 'mrcat/tool/MRTool/mr_input_scale.R'
    code = f'''source({json.dumps(str(script))})
    dat <- data.table::data.table(b.exp=1,b.out=2,se.exp=.1,se.out=.2)
    err <- tryCatch(mr_apply_input_scale(dat, "native"), error=function(e) conditionMessage(e))
    stopifnot(is.character(err), grepl("Native statistics unavailable", err))
    '''
    result = subprocess.run([RSCRIPT, '-e', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('scales', [('standardize', 'standardize'), ('native', 'native'), ('standardize', 'native')])
def test_replication_units_are_not_a_gate_but_mixed_inputs_are(tmp_path, scales):
    analyses = []
    for i, scale in enumerate(scales):
        record = tmp_path / f'method{i}.json'
        # A historical label does not control new outputs or warnings.
        record.write_text(json.dumps(dict(method='mr_primary', input_scale=scale, effect_scale='unknown',
            methods=[{'method':'IVW','beta.hat':.2,'se':.05,'pval':.001,'nsnp':24,
                      'ci':{'level':.95,'ranges':[{'lower':.102,'upper':.298}]}}])))
        analyses.append(dict(name=f'Study {i}', result_paths=[str(record)],
            exposure_study=dict(source='fixture',study_id='exposure',trait='Exposure'),
            outcome_study=dict(source='fixture',study_id=f'outcome{i}',trait='Outcome')))
    result = tools.analysis_replication(exposure='Exposure', outcome='Outcome', analyses=analyses,
                                        output_dir=tmp_path/'replication')
    if scales[0] != scales[1]:
        assert result['outputs']['status'] == 'blocked'
        assert result['outputs']['failure_class'] == 'incompatible_input_scale'
    else:
        assert result['outputs']['status'] == 'ok', result
        record = result['outputs']['mr_replication_result']
        assert all('effect_scale' not in row for row in record['estimates'])
        assert 'unresolved' not in json.dumps(record).lower()
        assert 'scale_compatible' not in json.dumps(record)
