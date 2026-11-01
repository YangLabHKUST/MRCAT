"""Record benchmark sources and inputs without copying credentials or datasets."""
from dataclasses import asdict
import hashlib
from importlib.metadata import distributions
import os
from pathlib import Path
import platform
import subprocess
import sys
from urllib.parse import urlsplit

from .sandbox import code_files, query_inputs


def file_record(path):
    path = Path(path)
    if not path.is_file():
        return dict(path=str(path), missing=True)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=digest.hexdigest())


def source_version(root, expected_commit=None):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
    try:
        commit = git("rev-parse", "HEAD")
        changes = git("status", "--porcelain", "--untracked-files=all")
        tags = git("tag", "--points-at", "HEAD").splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        if expected_commit:
            raise ValueError("A frozen benchmark requires a Git checkout") from exc
        return dict(commit=None, status="unavailable")
    if expected_commit and (commit != expected_commit or changes):
        raise ValueError("Frozen benchmark requires the expected full commit and a clean checkout")
    # Ignored Python/R files can still be mounted in a worker. Check these too.
    if expected_commit:
        tracked = set(git("ls-files").splitlines())
        extra = [str(p.relative_to(root)) for p in code_files(root)
                 if str(p.relative_to(root)) not in tracked]
        if extra:
            raise ValueError("Untracked executable sources in frozen checkout: " + ", ".join(extra))
    return dict(commit=commit, tags=tags, dirty=bool(changes), changes=changes.splitlines())


def capture(root, query_path, cases, config, version):
    sources = []
    for path in code_files(root):
        row = file_record(path)
        row["path"] = str(path.relative_to(root))
        sources.append(row)
    inputs = sorted({p for case in cases for p in query_inputs(case["query"])})
    gateway = config.llm.gateway
    return dict(
        system="MRCAT", implementation_package="mrcat", source=version,
        source_files=sources, query_file=file_record(query_path),
        input_files=[file_record(p) for p in inputs],
        model_config=dict(provider=gateway.provider, backend=gateway.backend,
                          endpoint_host=urlsplit(gateway.base_url).hostname,
                          timeout_sec=gateway.timeout_sec, retry_count=gateway.retry_count,
                          models=asdict(config.llm.models),
                          temperatures=asdict(config.llm.temperatures),
                          ),
        output_budget_overrides={k: v for k, v in os.environ.items() if k.startswith("MRCAT_MAX_")},
        runtime=dict(python=sys.executable, python_version=platform.python_version(),
                     platform=platform.platform(), rscript=os.environ.get("RSCRIPT_BIN"),
                     python_packages=sorted({(d.metadata["Name"], d.version)
                                             for d in distributions() if d.metadata["Name"]})),
    )
