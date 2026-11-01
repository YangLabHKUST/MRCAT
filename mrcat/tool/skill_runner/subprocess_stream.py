from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Sequence
from typing import Any


LineCallback = Callable[[str], None]


def run_streaming(
    command: Sequence[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    on_stdout_line: LineCallback | None = None,
    on_stderr_line: LineCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess while forwarding complete output lines to callbacks."""
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    def consume(stream: Any, parts: list[str], callback: LineCallback | None) -> None:
        try:
            for line in iter(stream.readline, ""):
                parts.append(line)
                if callback is not None:
                    callback(line.rstrip("\r\n"))
        finally:
            stream.close()

    stdout_thread = threading.Thread(target=consume, args=(process.stdout, stdout_parts, on_stdout_line), daemon=True)
    stderr_thread = threading.Thread(target=consume, args=(process.stderr, stderr_parts, on_stderr_line), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        stdout_thread.join()
        stderr_thread.join()
        raise subprocess.TimeoutExpired(
            exc.cmd,
            exc.timeout,
            output="".join(stdout_parts),
            stderr="".join(stderr_parts),
        ) from exc
    stdout_thread.join()
    stderr_thread.join()
    return subprocess.CompletedProcess(
        args=list(command),
        returncode=returncode,
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
    )
