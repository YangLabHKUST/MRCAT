"""Exercise the real worker mount boundary, not a mocked path filter."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from mrcat import sandbox

ROOT = Path(__file__).resolve().parents[1]


def run(command, env, code, timeout=45):
    result = subprocess.run(command + [sys.executable, "-c", code], env=env,
                            text=True, capture_output=True, timeout=timeout)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_explicit_inputs_only(tmp_path):
    source = tmp_path / "xxx input.tsv"
    source.write_text("xxx")
    assert sandbox.query_inputs(f'Read "{source}"; https://xxx.org/xxx') == [str(source)]
    assert sandbox.query_inputs(f"Read {tmp_path}/missing.tsv.") == [str(tmp_path / "missing.tsv")]
    with pytest.raises(ValueError, match="individual files"):
        sandbox.query_inputs(str(tmp_path))


def test_missing_bwrap_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="no host fallback"):
        sandbox.prepare_worker(ROOT, tmp_path, [])


@pytest.mark.sandbox
def test_worker_boundary_and_cross_language_cells(tmp_path, monkeypatch):
    # The boundary test needs an executable resource, not a real LD panel.
    references = tmp_path / "reference fixtures"
    plink = references / "plink/bin/plink1.9/plink"
    plink.parent.mkdir(parents=True)
    plink.write_text('#!/bin/sh\n[ "$1" = "--version" ] || exit 1\nprintf "PLINK sandbox fixture\\n"\n')
    plink.chmod(0o755)
    monkeypatch.setenv("MRCAT_DATABASE_DIR", str(references))
    directory = tmp_path / "xxx query"
    directory.mkdir()
    allowed = tmp_path / "xxx input.tsv"
    allowed.write_text("0.1\n0.2\n0.3\n")
    hidden = tmp_path / "xxx old result.txt"
    hidden.write_text(os.urandom(32).hex())
    private_project = tmp_path / "unrelated project"
    private_project.mkdir()
    (private_project / "private.txt").write_text("not an input")
    alias = directory / "xxx escape"
    alias.symlink_to(hidden)
    command, env, manifest = sandbox.prepare_worker(ROOT, directory, [str(allowed)])
    sandbox.preflight(command, env)
    forbidden = [str(hidden), str(alias), str(tmp_path / "batch.json"),
                 str(ROOT / "runtime_benchmark"), str(ROOT / "tests"),
                 str(private_project), str(Path.home() / ".claude"),
                 str(Path.home() / ".codex")]
    (tmp_path / "batch.json").write_text("xxx reference answers")
    code = f'''
from pathlib import Path
import json, subprocess, os
from mrcat.execution import CodeExecutor
from mrcat.model.prompt_assembler import PromptAssembler
from mrcat.database import database
prompt = PromptAssembler().build_structured_prompt(role_name='gwas_select', stage='selector', sections={{'xxx': 'xxx'}})
assert prompt.system_prompt
from mrcat.report.agent import ReportAgent
from types import SimpleNamespace
reporter = ReportAgent(SimpleNamespace(root=Path({str(ROOT)!r}), prompt=lambda role: ''), {{}})
assert 'substantive' in reporter.build_structured_prompt(stage='report_judge', sections={{}})['system']
subprocess.run([str(database('plink.binary')), '--version'], check=True)
for name in {forbidden!r}:
    assert not Path(name).exists(), name
    try:
        Path(name).read_bytes()
    except OSError:
        pass
    else:
        raise AssertionError(name)
assert Path({str(allowed)!r}).read_text() == '0.1\\n0.2\\n0.3\\n'
try:
    Path({str(allowed)!r}).write_text('xxx')
except OSError:
    pass
else:
    raise AssertionError('input is writable')
assert Path('/proc/1/root{str(hidden)}').exists() is False
executor = CodeExecutor({str(ROOT)!r}, Path.cwd() / 'xxx session', timeout=30)
cells = [
    ('python', "from pathlib import Path; Path('xxx.txt').write_text('xxx')"),
    ('r', 'stopifnot(readLines("xxx.txt") == "xxx"); '
          + 'stopifnot(!file.exists(' + json.dumps({str(hidden)!r}) + ')); '
          + 'library(TwoSampleMR); library(MRMix); '
          + 'x <- c(0.1, 0.2, 0.3); y <- 0.5*x; '
          + 'fit <- mr_ivw(b_exp=x, b_out=y, se_exp=rep(0.01, 3), se_out=rep(0.02, 3)); '
          + 'stopifnot(abs(fit$b - 0.5) < 1e-8); writeLines("xxx R", "xxx_r.txt")'),
    ('bash', 'test "$(cat xxx_r.txt)" = "xxx R" && test ! -e ' + __import__('shlex').quote({str(hidden)!r})),
]
for i, (language, source) in enumerate(cells):
    observation = executor.execute(source, language, 'xxx_' + str(i))
    assert observation['returncode'] == 0, observation
print('boundary-and-cells-ok')
'''
    assert "boundary-and-cells-ok" in run(command, env, code, timeout=90)
    assert allowed.read_text() == "0.1\n0.2\n0.3\n"
    assert all("execution/reports" not in mount["target"] for mount in manifest["read_only"])


@pytest.mark.sandbox
def test_download_resume_inside_worker(tmp_path):
    # Run the existing real HTTP/CodeExecutor integration entirely inside bwrap.
    shutil.copyfile(ROOT / "tests/test_download_cache.py", tmp_path / "download_test.py")
    command, env, _ = sandbox.prepare_worker(ROOT, tmp_path, [])
    code = f'''
from pathlib import Path
import download_test
download_test.ROOT = Path({str(ROOT)!r})
download_test.test_timeout_resumes_across_cells_and_preserves_cache_identity(Path.cwd())
print('download-resume-ok')
'''
    assert "download-resume-ok" in run(command, env, code, timeout=90)


@pytest.mark.sandbox
def test_robust_method_plots_with_read_only_source(tmp_path):
    command, env, _ = sandbox.prepare_worker(ROOT, tmp_path, [])
    code = f'''
from pathlib import Path
from mrcat.tools import mr_robust
source = Path({str(ROOT / 'skills/mr-robust/scripts/mr_robust')!r})
try:
    (source / 'xxx_write_probe').write_text('xxx')
except OSError:
    pass
else:
    raise AssertionError('Skill source must be read-only')
data = Path.cwd() / 'xxx.tsv'
header = 'SNP\\tb.exp\\tb.out\\tse.exp\\tse.out\\tpval.exp\\tZ.exp\\tZ.out\\tN.exp\\tN.out\\n'
rows = []
for i in range(24):
    bx = .1 + (i % 7) * .013
    by = .35 * bx + ((i % 5) - 2) * .002
    rows.append(f'xxx_{{i}}\\t{{bx}}\\t{{by}}\\t.01\\t.01\\t1e-10\\t{{bx/.01}}\\t{{by/.01}}\\t10000\\t10000\\n')
data.write_text(header + ''.join(rows))
result = mr_robust(mrdat_path=data, output_dir=Path.cwd() / 'xxx_output')
assert result['outputs']['status'] == 'ok', result
record = result['outputs']['mr_robust_result']
plots = record['plot_manifest']['plots']
assert plots and all(Path(p['path']).is_file() and Path(p['path']).is_relative_to(Path.cwd()) for p in plots)
assert not list(Path.cwd().rglob('Rplots.pdf'))
assert not (source / 'Rplots.pdf').exists()
print('robust-read-only-source-ok')
'''
    assert 'robust-read-only-source-ok' in run(command, env, code, timeout=90)
