"""Run arbitrary Python, R or Bash. Return observations, never scientific verdicts."""
from pathlib import Path
import hashlib, json, os, platform, shutil, signal, subprocess, sys, time
from mrcat.state.store import write_json
from mrcat.state.results import result_catalog

def execution_environment():
    """Use the server's interpreter environment, including for shell children."""
    env = dict(os.environ)
    bindir = str(Path(sys.executable).parent)
    env["PATH"] = os.pathsep.join(dict.fromkeys([bindir, *env.get("PATH", "").split(os.pathsep)]))
    # An absent local R must fail explicitly, never select an unrelated system R.
    env["RSCRIPT_BIN"] = env.get("RSCRIPT_BIN") or str(Path(bindir) / "Rscript")
    return env


def runtime_context(*, workdir=None):
    """Small, factual environment description; do not expose inherited secrets."""
    env = execution_environment()
    context = dict(environment=Path(sys.prefix).name, prefix=sys.prefix,
                python_executable=sys.executable, python_version=platform.python_version(),
                rscript_executable=shutil.which(env["RSCRIPT_BIN"], path=env["PATH"]),
                shell="/bin/bash", shell_path_prefix=str(Path(sys.executable).parent))
    if workdir is not None:
        context['local_dependencies'] = dict(r_library=str(Path(workdir) / '.deps' / 'R'),
                                             python_target=str(Path(workdir) / '.deps' / 'python'))
    return context


class CodeExecutor:
    def __init__(self, repo_root, session_dir, *, timeout=3600, poll_interval=0.1, strict_bash=False):
        self.repo_root = Path(repo_root).resolve()
        self.session_dir = Path(session_dir).resolve()
        self.workspace = self.session_dir / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.strict_bash = strict_bash
    def execute(self, code, language, execution_id, on_output=None, *, result_scope="standalone", working_directory=None):
        cwd = Path(working_directory or self.workspace).resolve()
        if not cwd.is_relative_to(self.workspace.resolve()) or not cwd.is_dir():
            raise ValueError("Execution working directory must be an existing directory inside this workspace.")
        env = execution_environment()
        if self.strict_bash:
            libraries = runtime_context(workdir=cwd)['local_dependencies']
            Path(libraries['r_library']).mkdir(parents=True, exist_ok=True)
            env['R_LIBS'] = libraries['r_library'] + os.pathsep + env.get('R_LIBS', '')
            env['PYTHONPATH'] = libraries['python_target'] + os.pathsep + env.get('PYTHONPATH', '')
        suffix, command = {"python": ("py", [sys.executable, "-u"]), "r": ("R", [env["RSCRIPT_BIN"]]), "bash": ("sh", ["/bin/bash"])}[language]
        if language == "bash" and self.strict_bash:
            command += ["-e", "-o", "pipefail"]
        directory = self.session_dir / "executions" / execution_id
        source = directory / f"code.{suffix}"
        if directory.exists():
            observation = directory / 'observation.json'
            if not source.is_file() or source.read_text(encoding='utf-8') != code:
                raise ValueError('Execution ID already belongs to different source code.')
            if observation.is_file():
                result = json.loads(observation.read_text())
                if result['language'] != language:
                    raise ValueError('Execution ID already belongs to another language.')
                if result.get('working_directory', str(self.workspace)) != str(cwd):
                    raise ValueError('Execution ID already belongs to another working directory.')
                return result
            raise RuntimeError('Execution already started without a final observation. '
                               'Inspect its logs before requesting a new execution ID.')
        # Claim the ID before launching any external process.
        directory.mkdir(parents=True)
        source.write_text(code, encoding="utf-8")
        from mrcat.trace import emit, execution_finished
        emit(self.session_dir, 'execution_start', dict(execution_id=execution_id, language=language,
            code=code, working_directory=str(cwd), result_scope=result_scope),
            event_id='execution:' + execution_id,
            source={'path': str(source.relative_to(self.session_dir))})
        stdout = directory / "stdout.log"; stderr = directory / "stderr.log"
        env.update(PYTHONPATH=str(self.repo_root) + os.pathsep + env.get("PYTHONPATH", ""), MRCAT_ROOT=str(self.repo_root), MRCAT_WORKSPACE_DIR=str(self.repo_root), MRCAT_WORKSPACE=str(self.workspace), MRCAT_EXECUTION_DIR=str(self.workspace / "outputs" / execution_id), PYTHONUNBUFFERED="1", MPLBACKEND="Agg")
        env.update(MRCAT_SESSION_DIR=str(self.session_dir), MRCAT_RESULT_SCOPE=result_scope,
                   MRCAT_EXECUTION_ID=execution_id)
        Path(env["MRCAT_EXECUTION_DIR"]).mkdir(parents=True, exist_ok=True)
        before_files = self._files()
        started = time.monotonic(); status = "exited"; proc = None
        with stdout.open("w") as out, stderr.open("w") as err:
            try:
                proc = subprocess.Popen(command + [str(source)], cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
                write_json(self.session_dir / "execution_process.json", {"pid": proc.pid})
                sizes = None
                while proc.poll() is None:
                    current = (stdout.stat().st_size, stderr.stat().st_size)
                    if on_output and current != sizes:
                        on_output(self._preview(stdout), self._preview(stderr)); sizes = current
                    if (self.session_dir / "STOP").exists(): status = "cancelled"; break
                    if time.monotonic() - started >= self.timeout: status = "timeout"; break
                    time.sleep(self.poll_interval)
            except OSError as exc:
                err.write(str(exc)); status = "launch_error"
            finally:
                if proc:
                    # Clean the entire process group, including background children.
                    try: os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError: pass
                    try: proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait()
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                (self.session_dir / "execution_process.json").unlink(missing_ok=True)
        result = dict(execution_id=execution_id, language=language, status=status, returncode=proc.returncode if proc else None, stdout=self._preview(stdout), stderr=self._preview(stderr), source_path=str(source.relative_to(self.session_dir)), stdout_path=str(stdout.relative_to(self.session_dir)), stderr_path=str(stderr.relative_to(self.session_dir)), duration_seconds=round(time.monotonic()-started,3))
        result["working_directory"] = str(cwd)
        result["generated_files"] = [path for path, stamp in self._files().items() if before_files.get(path) != stamp]
        # Snapshot small JSON outputs for later publication without trusting model-authored values.
        if self.strict_bash:
            result['artifact_hashes'] = {}
            for ref in result['generated_files']:
                path = self.session_dir / ref
                if path.suffix == '.json' and path.stat().st_size <= 2_000_000:
                    result['artifact_hashes'][ref] = hashlib.sha256(path.read_bytes()).hexdigest()
        # Tool failures can occur in a successful Python process. Expose their
        # saved status to the Executor without making a routing decision.
        tool_results = []
        for ref in result["generated_files"]:
            path = (self.session_dir / ref).resolve()
            if path.name != "response.json" or not path.is_relative_to(self.workspace):
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
                data = json.loads(path.read_text())
                outputs = data.get("outputs") or {}
                details = data.get("details") or {}
                tool_results.append(dict(path=ref, status=outputs.get("status") or details.get("result_status"),
                    failure_class=details.get("failure_class") or outputs.get("failure_class"),
                    summary=str(data.get("summary") or "")[:1200],
                    message=str(details.get("message") or outputs.get("message") or "")[:1200]))
            except (OSError, ValueError, AttributeError):
                continue
        if tool_results:
            result["tool_results"] = tool_results
        result["result_refs"] = result_catalog(self.session_dir, result_scope, execution_id=execution_id)
        write_json(directory / "observation.json", result)
        execution_finished(self.session_dir, execution_id, result)
        return result
    def _files(self):
        result = {}
        for path in self.workspace.rglob("*"):
            try:
                if path.is_file() and path.resolve().is_relative_to(self.workspace):
                    stat = path.stat()
                    result[str(path.relative_to(self.session_dir))] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
        return result

    @staticmethod
    def _preview(path, limit=16000):
        with Path(path).open("rb") as handle:
            size = Path(path).stat().st_size
            if size <= limit:
                return handle.read().decode("utf-8", errors="replace")
            marker = b"\n[Output excerpted; full output is in the saved log.]\n"
            budget = limit - len(marker)
            head = handle.read(budget * 2 // 3)
            handle.seek(-budget // 3, 2)
            return (head + marker + handle.read()).decode("utf-8", errors="replace")
