import pytest
import json
import os
from pathlib import Path
import shlex
import sys

from mrcat.execution import CodeExecutor, execution_environment, runtime_context

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.r
def test_shell_python_uses_server_environment_with_hostile_path(tmp_path, monkeypatch):
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    for name in ('python', 'python3', 'Rscript'):
        executable = foreign / name
        executable.write_text('#!/bin/sh\nprintf wrong-environment\nexit 91\n')
        executable.chmod(0o755)
    monkeypatch.setenv('PATH', str(foreign) + os.pathsep + os.environ['PATH'])
    monkeypatch.delenv('RSCRIPT_BIN', raising=False)
    executor = CodeExecutor(ROOT, tmp_path / 'session')
    result = executor.execute("python -c 'import sys,openpyxl; print(sys.executable); print(openpyxl.__version__)'", 'bash', 'python')
    assert result['returncode'] == 0, result
    assert result['stdout'].splitlines()[0] == sys.executable
    r = executor.execute("Rscript -e 'cat(R.home())'", 'bash', 'r')
    assert r['returncode'] == 0, r
    assert Path(r['stdout']).resolve().is_relative_to(Path(sys.prefix).resolve())
    assert runtime_context()['python_executable'] == sys.executable
    assert runtime_context()['rscript_executable'] == str(Path(sys.executable).parent / 'Rscript')


def test_explicit_rscript_override_is_honored(tmp_path, monkeypatch):
    script = tmp_path / 'custom-Rscript'
    script.write_text('#!/bin/sh\nprintf explicit-r\n')
    script.chmod(0o755)
    monkeypatch.setenv('RSCRIPT_BIN', str(script))
    assert runtime_context()['rscript_executable'] == str(script)
    result = CodeExecutor(ROOT, tmp_path / 'session').execute('ignored', 'r', 'override')
    assert result['returncode'] == 0 and result['stdout'] == 'explicit-r'


def test_missing_local_r_does_not_fall_back_to_system(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'bin' / 'python'))
    monkeypatch.delenv('RSCRIPT_BIN', raising=False)
    assert runtime_context()['rscript_executable'] is None
    result = CodeExecutor(ROOT, tmp_path / 'session').execute('cat(42)', 'r', 'missing')
    assert result['status'] == 'launch_error'


def test_search_cli_imports_from_shell_without_environment_repair(tmp_path):
    entrypoint = ROOT / 'skills/gwas-search/scripts/run_search.py'
    result = CodeExecutor(ROOT, tmp_path).execute(f'python {shlex.quote(str(entrypoint))} --help', 'bash', 'help')
    assert result['returncode'] == 0, result
    assert '--trait' in result['stdout']


def test_search_artifacts_use_existing_execution_directory(tmp_path):
    scripts = ROOT / 'skills/gwas-search/scripts'
    code = f'''
from importlib import import_module
search_output = import_module("skills.gwas-search.scripts.search_output")
write_shortlists_artifact = search_output.write_shortlists_artifact
write_raw_artifact = search_output.write_raw_artifact
write_shortlists_artifact([], target={{"value": "BMI"}}, diagnostics={{}})
write_raw_artifact({{"raw_results": []}})
'''
    result = CodeExecutor(ROOT, tmp_path).execute(code, 'python', 'search')
    assert result['returncode'] == 0, result
    output = tmp_path / 'workspace/outputs/search'
    assert json.loads((output / 'gwas_search_shortlists.json').read_text())['candidates'] == []
    assert (output / 'gwas_search_shortlists.xlsx').exists()
    assert 'workspace/outputs/search/gwas_search_raw.json' in result['generated_files']
