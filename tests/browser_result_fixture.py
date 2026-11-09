"""Saved MRCAT artifacts for browser regression; no model or scientific run."""
import base64
import gzip
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mrcat.store import Store

ids = json.loads(Path('/tmp/mrcat-browser-roles.json').read_text())
store = Store(ids['store'])
state = store.create('Synthetic result presentation regression', 'openai')
state.update(status='completed', active_agent='mr')
sid = state['session_id']
root = store.directory(sid)
def save(path, value):
    path = root / 'workspace' / path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.json': path.write_text(json.dumps(value))
    elif path.suffix == '.gz':
        with gzip.open(path, 'wt') as f: f.write(value)
    elif isinstance(value, bytes): path.write_bytes(value)
    else: path.write_text(value)
    return path

table = 'SNP\tb.exp\tb.out\tse.exp\tse.out\nrs1\t0.2\t0.05\t0.01\t0.02\nrs2\t0.3\t0.09\t0.02\t0.03\n'
save('qc/formatted/study.mrapss.tsv.gz', table)
save('pair/intermediate/gwas_pair_mrdat_clumped.tsv.gz', table)
save('pair/intermediate/gwas_pair_mdat.tsv.gz', table)
save('primary/reports/selected_mrdat.tsv', table)
png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1kAAAAASUVORK5CYII=')
save('primary/plots/primary_scatter.png', png)
save('qc/plots/gwas_qc_qq_plot.png', png)
save('replication/plots/replication_forest_matrix.png', png)
# Historical results may contain multiple exports of the same plot.
for folder, name in [('primary', 'primary_scatter'), ('qc', 'gwas_qc_qq_plot'),
                     ('replication', 'replication_forest_matrix')]:
    save(f'{folder}/plots/{name}.svg', '<svg xmlns="http://www.w3.org/2000/svg"/>')
    save(f'{folder}/plots/{name}.pdf', b'%PDF-1.4\n')
    save(f'{folder}/plots/{name}.tiff', b'II')
save('primary/plots/legacy_only.svg', '<svg xmlns="http://www.w3.org/2000/svg"/>')

save('qc/plots/gwas_qc_qq_plot.plot.json', {'version': 1, 'kind': 'qq', 'expected': [0, 1, 2], 'observed': [0, 1.1, 2.1], 'lambda_gc': 1.02})
save('qc/response.json', {'summary': 'canonical_rows=1000, formatted_rows=800', 'outputs': {'status': 'ok', 'gwas_qc_result': {'label': 'Synthetic exposure'}}, 'details': {'result_status': 'ok'}})
save('pair/response.json', {'summary': 'mdat_rows=800, clumped_rows=2, iv_threshold=5e-8', 'outputs': {'status': 'ok', 'gwas_pair_prepare_result': {'exposure_label': 'Synthetic exposure', 'outcome_label': 'Synthetic outcome'}}})
payload = {'input_scale': 'standardize', 'methods': [{'method': 'IVW', 'beta.hat': 0.2, 'se': 0.1, 'pval': 0.04, 'nsnp': 2, 'ci': {'ranges': [{'lower': 0.01, 'upper': 0.39}]}}], 'selected_mrdat_path': str(root / 'workspace/primary/reports/selected_mrdat.tsv'), 'plot_manifest': {'plots': [{'plot_id': 'primary_scatter', 'path': str(root / 'workspace/primary/plots/primary_scatter.png')}]}}
save('primary/response.json', {'summary': 'Synthetic estimates only.', 'outputs': {'status': 'ok', 'mr_primary_result': payload}})
save('primary/reports/mr_primary_result_record.json', payload)
save('replication/response.json', {'outputs': {'mr_replication_result': {
    'analyses': [{'analysis_index': 0, 'name': 'Replication study'}],
    'estimates': [{'analysis_index': 0, 'method': 'IVW', 'beta.hat': 0.2, 'pval': 0.04,
                   'ci': {'level': 0.95, 'ranges': [{'lower': 0.01, 'upper': 0.39}]}}],
    'plot_manifest': {'plots': [{'plot_id': 'replication_forest_matrix',
        'path': str(root / 'workspace/replication/plots/replication_forest_matrix.png')}]}
}}})

save('broken/response.json', '{malformed')
(root / 'workspace/broken/response.json').write_text('{malformed')
paths = [str(p.relative_to(root)) for p in (root / 'workspace').rglob('*') if p.is_file()]
store.event(state, 'code_execution', 'Inspect QC, harmonization and MR results from saved artifacts.', execution_id='result-cell', language='python', code='print("Synthetic presentation fixture")', status='exited', returncode=0, stdout='Synthetic presentation fixture', stderr='A diagnostic message', agent='mr', task_id='task_1', generated_files=paths)
Path('/tmp/mrcat-result-session.json').write_text(json.dumps({'session_id':sid, 'store':ids['store']}))
print(sid)
