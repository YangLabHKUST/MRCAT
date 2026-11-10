"""Verify skill streams at the CodeAct and standalone JSON CLI boundaries."""
import json
from pathlib import Path

import pytest

from mrcat.runtime.execution import CodeExecutor

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('cli', [False, True])
def test_search_progress_and_diagnostics_keep_their_channels(tmp_path, cli):
    code = '''import importlib, json, sys
from mrcat import tools
common = importlib.import_module('skills.gwas-search.scripts.common')
orchestrator = importlib.import_module('skills.gwas-search.scripts.search_orchestrator')
def search(**kwargs):
    common.log_step('Search progress fixture')
    common.log_step('Search diagnostic fixture', error=True)
    return dict(candidates=[], raw_results=[], source_timings={},
                source_reports=[dict(source='opengwas', status='empty')])
orchestrator._search_trait_once = search
'''
    if cli:
        code += "sys.argv = ['run_search', '--trait', 'fixture', '--source', 'opengwas']\nimportlib.import_module('skills.gwas-search.scripts.run_search').main()\n"
    else:
        code += "result = tools.gwas_search(trait='fixture', source='opengwas')\nprint('RESULT=' + json.dumps(result))\n"
    result = CodeExecutor(ROOT, tmp_path).execute(code, 'python', 'search')
    assert result['returncode'] == 0, result['stderr']
    assert 'Search diagnostic fixture' in result['stderr']
    assert 'Search diagnostic fixture' not in result['stdout']
    progress_stream = result['stderr'] if cli else result['stdout']
    assert 'Search progress fixture' in progress_stream
    if cli:
        assert isinstance(json.loads(result['stdout'])['outputs'], dict)
    else:
        assert 'Search progress fixture' not in result['stderr']
        assert 'RESULT=' in result['stdout']
    assert list((tmp_path / 'workspace').rglob('gwas_search_shortlists.json'))


@pytest.mark.parametrize('cli', [False, True])
@pytest.mark.parametrize('fail', [False, True])
@pytest.mark.r
def test_r_runner_streams_and_cli_json(tmp_path, cli, fail):
    # Exercise every actual runner logger without loading scientific packages.
    scripts = sorted(p for p in (ROOT / 'skills').rglob('*.R')
                     if 'log_step <- function' in p.read_text())
    paths = ','.join(json.dumps(str(p)) for p in scripts)
    fixture = tmp_path / 'stream_fixture.R'
    ending = 'stop("R failure fixture")' if fail else "writeLines('{\"outputs\":{\"status\":\"ok\"}}', args[[2]])"
    fixture.write_text(f'''args <- commandArgs(trailingOnly = TRUE)
for (path in c({paths})) {{
  expressions <- parse(path)
  for (expr in expressions) {{
    if (is.call(expr) && identical(expr[[1]], as.name("<-")) &&
        identical(expr[[2]], as.name("log_step"))) eval(expr)
  }}
  log_step("R progress fixture")
  log_step("R diagnostic fixture", .error = TRUE)
}}
warning("Third-party warning fixture", immediate. = TRUE)
{ending}
''')
    source = tmp_path / 'input.tsv'
    source.write_text('fixture\n')
    input_json = tmp_path / 'input.json'
    input_json.write_text(json.dumps({'mrdat_path': str(source)}))
    code = f'''import importlib, json, sys
from pathlib import Path
from dataclasses import replace
from mrcat import tools
from mrcat.tool.MRTool import run_method_cli
method = importlib.import_module('skills.mr-bwmr.scripts.run_mr_bwmr')
method.SPEC = replace(method.SPEC, script_path=Path({str(fixture)!r}))
'''
    if cli:
        code += f"sys.argv = ['method', '--input-json', {str(input_json)!r}]\nrun_method_cli(method.SPEC)\n"
    else:
        code += f"result = tools.mr_bwmr(mrdat_path={str(source)!r})\nprint('RESULT=' + json.dumps(result))\n"
    result = CodeExecutor(ROOT, tmp_path / 'session').execute(code, 'python', 'method')
    assert result['returncode'] == 0, result['stderr']
    assert result['stderr'].count('R diagnostic fixture') == len(scripts)
    if not cli:
        assert 'R diagnostic fixture' not in result['stdout'].split('RESULT=', 1)[0]
    assert 'Third-party warning fixture' in result['stderr']
    progress_stream = result['stderr'] if cli else result['stdout'].split('RESULT=', 1)[0]
    assert progress_stream.count('R progress fixture') == len(scripts)
    if cli:
        payload = json.loads(result['stdout'])
    else:
        assert 'R progress fixture' not in result['stderr']
        payload = json.loads(result['stdout'].split('RESULT=', 1)[1])
    assert payload['outputs']['status'] == ('blocked' if fail else 'ok')
    if fail:
        assert 'R failure fixture' in result['stderr']
        assert 'R failure fixture' in payload['details']['stderr_tail']
    else:
        assert 'R failure fixture' not in result['stderr']
