"""Exercise download recovery across real CodeAct subprocesses."""
import hashlib
import importlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread

import pytest

from mrcat.execution import CodeExecutor
from mrcat.results import read_reference

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("legacy_session", [False, True])
def test_download_cache_without_codeact_session(tmp_path, monkeypatch, legacy_session):
    download = importlib.import_module("skills.gwas-download.scripts.run_download")
    monkeypatch.delenv("MRCAT_SESSION_DIR", raising=False)
    output = tmp_path / "xxx"
    if legacy_session:
        session = tmp_path / "sessions" / "xxx"
        monkeypatch.setenv("MRCAT_EXECUTION_DIR", str(session / "runs/xxx/skills/xxx"))
        expected = session / "cache/gwas-download"
    else:
        monkeypatch.delenv("MRCAT_EXECUTION_DIR", raising=False)
        expected = output
    assert download._download_cache_root(output) == expected


def test_timeout_resumes_across_cells_and_preserves_cache_identity(tmp_path):
    content = b"xxx\t0123456789\n" * 300_000
    partial_size = 2 * 1024 * 1024
    release = Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            range_header = self.headers.get("Range")
            requests.append((self.path, range_header, self.headers.get("If-Range")))
            first = len(requests) == 1
            offset = int(range_header.removeprefix("bytes=").removesuffix("-")) if range_header else 0
            self.send_response(206 if range_header else 200)
            self.send_header("Content-Length", str(len(content) - offset))
            self.send_header("ETag", '"xxx"')
            if range_header:
                self.send_header("Content-Range", f"bytes {offset}-{len(content)-1}/{len(content)}")
            self.end_headers()
            try:
                if first:
                    self.wfile.write(content[:partial_size])
                    self.wfile.flush()
                    release.wait(20)
                else:
                    self.wfile.write(content[offset:])
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = tmp_path / "xxx session"
    executor = CodeExecutor(ROOT, session, timeout=5)
    url = f"http://127.0.0.1:{server.server_port}/xxx.tsv"

    def cell(url, output_dir=None):
        output_arg = f", output_dir={str(output_dir)!r}" if output_dir is not None else ""
        return (
            "from mrcat.tools import gwas_download\n"
            f"result = gwas_download(download_url={url!r}{output_arg})\n"
            "assert result['outputs']['status'] == 'ok', result\n"
        )

    def raw_path(observation, active_session=session):
        assert observation["status"] == "exited" and observation["returncode"] == 0, observation
        ref = observation["result_refs"][0]["ref"]
        study = read_reference(active_session, "standalone", ref + "/gwas_download_result/downloaded_study")
        return Path(study["raw_path"])

    try:
        first = executor.execute(cell(url), "python", "xxx_first")
        assert first["status"] == "timeout", first
        release.set()
        partials = list((session / "cache/gwas-download").rglob("*.part"))
        assert len(partials) == 1
        partial = partials[0]
        offset = partial.stat().st_size
        # A killed process may leave some received bytes in an unflushed buffer.
        assert 0 < offset <= partial_size
        assert not list((session / "cache").rglob(".gwas-download-complete.json"))

        # Even an output directory ending in downloads must not relocate the cache.
        executor.timeout = 20
        second = executor.execute(cell(url, session / "workspace/outputs/xxx_retry/downloads"), "python", "xxx_second")
        downloaded = raw_path(second)
        assert downloaded == Path(str(partial).removesuffix(".part"))
        assert requests[1] == ("/xxx.tsv", f"bytes={offset}-", '"xxx"')
        assert hashlib.sha256(downloaded.read_bytes()).digest() == hashlib.sha256(content).digest()
        assert not partial.exists()
        marker = json.loads((downloaded.parent / ".gwas-download-complete.json").read_text())
        assert marker["file_size"] == len(content)

        third = executor.execute(cell(url), "python", "xxx_cached")
        assert raw_path(third) == downloaded
        assert len(requests) == 2  # A new cell reuses the complete download.

        changed = executor.execute(cell(url + "?xxx=2"), "python", "xxx_other_url")
        assert raw_path(changed) != downloaded
        assert requests[-1][1] is None
        assert len(requests) == 3

        other_session = tmp_path / "xxx other session"
        other = CodeExecutor(ROOT, other_session, timeout=20).execute(cell(url), "python", "xxx_separate")
        assert raw_path(other, other_session).is_relative_to(other_session / "cache")
        assert requests[-1][1] is None
        assert len(requests) == 4  # Separate sessions do not share raw data.
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
