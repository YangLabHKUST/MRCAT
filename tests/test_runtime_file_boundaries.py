"""Anonymous fixtures for data-file selection and R output directory boundaries."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from test_agent import ROOT


@pytest.mark.parametrize('name', ['md5sum.txt', 'MD5SUMS.txt', 'checksum.txt.gz',
                                  'sha256sum.txt', 'readme.txt', 'metadata.tsv'])
def test_catalog_sidecars_are_not_summary_statistics(name):
    catalog = importlib.import_module('skills.gwas-search.scripts.search_gwas_catalog')
    assert not catalog.GWASCatalogSearcher._is_root_data_file_url('https://example.org/xxx/' + name)
    assert catalog.GWASCatalogSearcher._is_root_data_file_url('https://example.org/xxx/xxx.tsv.gz')


@pytest.mark.parametrize('kind', ['shared', 'cause', 'primary_id'])
def test_r_runners_use_execution_directory_and_absolute_script(tmp_path, monkeypatch, kind):
    execution = tmp_path / 'execution'
    monkeypatch.setenv('MRCAT_EXECUTION_DIR', str(execution))
    monkeypatch.chdir(tmp_path)
    Path('xxx.tsv').write_text('xxx\n')

    def run(command, **kwargs):
        assert Path(kwargs['cwd']) == execution
        assert Path(command[1]).is_absolute() and Path(command[1]).is_file()
        payload = json.loads(Path(command[2]).read_text())
        for key, value in payload.items():
            if key.endswith('_path'):
                assert Path(value).is_absolute()
        Path(command[3]).write_text(json.dumps({'outputs': {'status': 'ok'}}))
        return SimpleNamespace(returncode=0)

    if kind == 'shared':
        module = importlib.import_module('mrcat.tool.mr.mr_method_runner')
        spec = importlib.import_module('skills.mr-robust.scripts.run_mr_robust').SPEC
        monkeypatch.setattr(module, 'run_streaming', run)
        result = module.run_r_method({'mrdat_path': 'xxx.tsv'}, spec)
    else:
        module = importlib.import_module('skills.mr-cause.scripts.run_cause' if kind == 'cause'
                                         else 'skills.mr-primary-id.scripts.run_mr_primary_id')
        monkeypatch.setattr(module, 'run_streaming', run)
        result = module.run({'canonical_exposure_path': 'xxx.tsv', 'canonical_outcome_path': 'xxx.tsv'}
                            if kind == 'cause' else {'exposure_gwas_id': 'xxx', 'outcome_gwas_id': 'xxx'})
    assert result['outputs']['status'] == 'ok'


@pytest.mark.r
def test_robust_plot_cleanup_does_not_open_a_default_device(tmp_path):
    source = ROOT / 'skills/mr-robust/scripts/mr_robust/run_mr_robust.R'
    code = f'''
expressions <- parse({str(source)!r})
for (expr in expressions) {{
  if (is.call(expr) && identical(expr[[1]], as.name("<-")) &&
      identical(expr[[2]], as.name("save_robust_plot"))) eval(expr)
}}
plot.xxx <- function(x, ...) {{ plot.new(); plot.window(c(0,1),c(0,1)); points(.5,.5) }}
save_robust_plot("xxx.png", structure(list(), class="xxx"))
stopifnot(dev.cur() == 1L, file.exists("xxx.png"), !file.exists("Rplots.pdf"))
plot.xxx <- function(x, ...) stop("xxx plotting error")
try(save_robust_plot("xxx_error.png", structure(list(), class="xxx")), silent=TRUE)
stopifnot(dev.cur() == 1L, !file.exists("Rplots.pdf"))
'''
    result = subprocess.run([str(Path(sys.executable).with_name('Rscript')), '--vanilla', '-e', code],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
