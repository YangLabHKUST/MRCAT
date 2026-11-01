"""Filesystem allowlist for an entire benchmark worker and its descendants."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

from .checkpoints import local_target


def query_inputs(query):
    """Keep explicit absolute file paths; never expose their parent directory."""
    pattern = r'''["'`](/[^"'`\n]+)["'`]|(?<![\w:/])(/[^\s<>"'`]+)'''
    paths = []
    for match in re.finditer(pattern, query):
        value = (match.group(1) or match.group(2)).rstrip(",;:.)]")
        path = Path(value)
        if path.is_dir():
            raise ValueError(f"Sandbox inputs must be individual files, not directories: {value}")
        if value not in paths:
            paths.append(value)
    return paths


def code_files(root):
    """Expose executable source and guides, not fixtures, build outputs or runs."""
    root = Path(root)
    files = [root / "config.yaml"]
    package = root / "mrcat"
    files.extend(package.rglob("*.py"))
    files.extend(package.rglob("*.R"))
    files.extend((package / "prompts").glob("*.md"))
    files.extend((root / "skills").glob("*.py"))
    files.extend((root / "skills").glob("*.md"))
    for skill in (root / "skills").glob("*/SKILL.md"):
        files.append(skill)
        files.extend(skill.parent.glob("*.py"))
        for suffix in ("*.py", "*.R"):
            files.extend((skill.parent / "scripts").rglob(suffix))
        for directory in ("reference", "plot_explanations"):
            files.extend((skill.parent / directory).rglob("*.md"))
    return sorted(set(path for path in files if path.is_file()))


def reference_files(root):
    # Reuse the tool's resource catalog, without mounting the whole database tree.
    from mrcat.database import _DATABASE
    files = []
    for resource in _DATABASE.values():
        data_root = Path(os.getenv("MRCAT_DATABASE_DIR") or Path(root) / "database").expanduser().resolve()
        path = data_root / Path(resource.relative_path).relative_to("database")
        if resource.kind == "file":
            files.append(path)
        elif resource.kind == "directory":
            files.extend(path / member for member in resource.required_members)
        else:
            files.extend(Path(str(path) + suffix) for suffix in resource.required_members)
    return [path for path in files if path.is_file()]


def worker_environment(root, directory, rscript, r_libraries):
    prefixes = ("LLM_", "ANTHROPIC_", "OPENAI_", "DEEPSEEK_", "QWEN_", "GLM_",
                "GROK_", "CUSTOM_", "OPENGWAS_", "MRCAT_MAX_")
    names = {"REPORTER_MODEL", "IEU_ACCESS_TOKEN", "TZ", "LANG",
             "MRCAT_CONFIG_DIR", "MRCAT_DATABASE_DIR", "MRCAT_BWMR_SOURCE",
             "LC_ALL", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
             "http_proxy", "https_proxy", "all_proxy", "no_proxy",
             "MRCAT_BENCHMARK_DISABLE_PROXY"}
    env = {key: value for key, value in os.environ.items()
           if key in names or key.startswith(prefixes)}
    env.update(HOME="/home/agent", TMPDIR="/tmp", XDG_CACHE_HOME="/home/agent/.cache",
               PATH=os.pathsep.join([str(Path(sys.executable).parent), "/usr/bin", "/bin"]),
               PYTHONPATH=str(root), PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
               PYTHONUNBUFFERED="1", MPLBACKEND="Agg", R_LIBS_USER=os.pathsep.join(r_libraries),
               R_ENVIRON_USER="/dev/null", R_PROFILE_USER="/dev/null", RSCRIPT_BIN=rscript,
               MRCAT_WORKSPACE_DIR=str(root), MRCAT_ROOT=str(root),
               MRCAT_BENCHMARK_SANDBOX="bwrap", MRCAT_BENCHMARK_QUERY_DIR=str(directory))
    return env


def prepare_worker(root, directory, inputs):
    """Return launch prefix/environment/manifest. No unsandboxed fallback exists."""
    root, directory = Path(root).resolve(), Path(directory).resolve()
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise ValueError("bwrap is required for benchmark isolation; no host fallback is allowed")
    rscript = os.environ.get("RSCRIPT_BIN") or str(Path(sys.executable).parent / "Rscript")
    rscript = shutil.which(rscript)
    if not rscript:
        raise ValueError("Rscript must exist in RSCRIPT_BIN or the active Python environment")
    result = subprocess.run([rscript, "--vanilla", "-e", 'cat(R.home(), .libPaths(), sep="\\n")'],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError("Unable to discover R libraries for the benchmark sandbox")
    locations = result.stdout.splitlines()
    if not locations or not Path(locations[0]).is_dir():
        raise ValueError("Unable to discover R.home() for the benchmark sandbox")
    r_home = Path(locations[0])
    libraries = [line for line in locations[1:] if Path(line).is_dir()]
    mounts = {}

    def read_only(path, target=None):
        path = Path(path)
        destination = str(target or path)
        mounts[destination] = dict(source=str(path.resolve()), target=destination, mode="ro")

    for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
        if Path(path).exists():
            read_only(path)
    for path in ("/etc/ssl/certs", "/etc/alternatives", "/etc/hosts", "/etc/resolv.conf", "/etc/nsswitch.conf",
                 "/etc/passwd", "/etc/group", "/etc/localtime", "/etc/gai.conf"):
        if Path(path).exists():
            read_only(path)
    # Rscript launches helpers under R.home() and may belong to a different
    # Conda environment than Python. Include that environment's shared libraries
    # and executables, preserving lexical paths embedded in its launch scripts.
    runtimes = {Path(sys.prefix), r_home, *(Path(path) for path in libraries)}
    for executable in (Path(rscript), Path(rscript).resolve()):
        prefix = executable.parent.parent
        if (prefix / "conda-meta").is_dir():
            runtimes.add(prefix)
    for path in runtimes:
        read_only(path)
        read_only(path.resolve())
    read_only(rscript)
    for path in code_files(root) + reference_files(root):
        read_only(path)
    config = Path(os.getenv("MRCAT_CONFIG_DIR") or root) / "config.yaml"
    if config.is_file():
        read_only(config)
    missing = []
    for value in inputs:
        path = Path(value)
        if path.is_file():
            read_only(path)
        else:
            missing.append(value)

    # Persist SQLite on host-local storage, exposing only this query's subtree.
    checkpoint_dir = local_target(directory).parent / "sessions"
    checkpoint_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    command = [bwrap, "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
               "--die-with-parent", "--new-session", "--cap-drop", "ALL",
               "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
               "--tmpfs", "/home/agent"]
    for mount in sorted(mounts.values(), key=lambda item: (len(Path(item["target"]).parts), item["target"])):
        command.extend(["--ro-bind", mount["source"], mount["target"]])
    command.extend(["--bind", str(directory), str(directory),
                    "--bind", str(checkpoint_dir), str(checkpoint_dir), "--remount-ro", "/",
                    "--chdir", str(directory), "--"])
    env = worker_environment(root, directory, rscript, libraries)
    env["MRCAT_CHECKPOINT_DIR"] = str(checkpoint_dir)
    manifest = dict(mode="bwrap", network="shared-host", read_only=list(mounts.values()),
                    writable=[str(directory), str(checkpoint_dir), "/tmp", "/home/agent"],
                    checkpoint_dir=str(checkpoint_dir), missing_inputs=missing,
                    environment_keys=sorted(env), command_prefix=command)
    return command, env, manifest


def preflight(command, env):
    """Fail before model calls if the OS cannot establish the boundary."""
    code = """
import os, subprocess
from tempfile import TemporaryDirectory
from mrcat.store import Store

# Exercise the real checkpoint path before starting model calls or query sessions.
with TemporaryDirectory(dir=os.environ['MRCAT_CHECKPOINT_DIR']) as local:
    os.environ['MRCAT_CHECKPOINT_DIR'] = local
    with TemporaryDirectory(dir=os.environ['MRCAT_BENCHMARK_QUERY_DIR']) as artifacts:
        store = Store(artifacts)
        state = store.create('Checkpoint preflight', os.environ.get('LLM_PROVIDER', 'anthropic'))
        assert store.load(state['session_id'])['question'] == 'Checkpoint preflight'
subprocess.run([os.environ['RSCRIPT_BIN'], '--vanilla', '-e',
                'library(utils); library(stats)'], check=True)
print('sandbox-ok')
"""
    result = subprocess.run(command + [sys.executable, "-c", code],
                            env=env, capture_output=True, text=True, timeout=30)
    if result.returncode or result.stdout.strip() != "sandbox-ok":
        raise ValueError("Benchmark sandbox preflight failed; no host fallback: " + result.stderr[-2000:])
