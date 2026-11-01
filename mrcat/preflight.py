"""Bounded model connectivity check using the benchmark worker's environment."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
from urllib.parse import urlsplit

from .store import write_json


def probe(directory):
    from mrcat.config.loader import load_repo_config
    from mrcat.model import llm_gateway as gateway
    from mrcat.model.llm_usage import llm_usage_scope

    directory = Path(directory)
    settings = json.loads((directory / "settings.json").read_text())
    os.environ["LLM_PROVIDER"] = settings["provider"]
    # These bounds apply only to this disposable probe process, not agent calls.
    prefix = settings["provider"].upper()
    os.environ[prefix + "_TIMEOUT_SEC"] = "50"
    os.environ[prefix + "_RETRY_COUNT"] = "1"
    config = load_repo_config(repo_root=Path(__file__).resolve().parents[1]).config
    budget = int(os.getenv("MRCAT_MAX_OUTPUT_TOKENS", "32768"))
    report = dict(status="failed", provider=gateway.current_provider(config),
                  model=gateway.current_model(config), backend=gateway.current_backend(config),
                  endpoint_host=urlsplit(gateway._api_url(config)).hostname,
                  max_tokens=budget, started_at=time.time())
    usage_path = directory / "model_preflight_usage.json"
    started = time.monotonic()
    try:
        with llm_usage_scope(usage_path):
            reply = gateway.call_text(system="Connectivity check. Reply only with xxx.",
                                      user="xxx", agent_config=config, max_tokens=budget)
        if not reply.strip():
            raise RuntimeError("Model returned an empty reply")
        report.update(status="passed", response_characters=len(reply))
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        usage = json.loads(usage_path.read_text()) if usage_path.exists() else {}
        report["usage"] = usage
        report["reported_total_tokens"] = (
            usage.get("llm_total_tokens") if usage.get("llm_call_count")
            and not usage.get("llm_unreported_usage_calls") else None)
        report["duration_s"] = round(time.monotonic() - started, 3)
        write_json(directory / "model_preflight.json", report)
    return 0 if report["status"] == "passed" else 1


def check_model(command, env, directory, *, timeout=60):
    """Use a wall-clock limit even when a server keeps an HTTP connection alive."""
    from .benchmark import stop_worker

    directory = Path(directory)
    report_path = directory / "model_preflight.json"
    started = time.monotonic()
    with (directory / "model_preflight.log").open("w") as log:
        process = subprocess.Popen(command + [sys.executable, "-m", "mrcat.preflight", str(directory)],
                                   env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_worker(process)
            write_json(report_path, dict(status="failed", reported_total_tokens=None,
                       duration_s=round(time.monotonic() - started, 3),
                       error=f"Model preflight exceeded {timeout} seconds; no queries were started"))
        except BaseException:
            stop_worker(process)
            raise
    report = json.loads(report_path.read_text()) if report_path.exists() else dict(
        status="failed", reported_total_tokens=None,
        error=f"Model preflight exited with code {process.returncode}; see model_preflight.log")
    write_json(directory.parent / "model_preflight.json", report)
    if process.returncode != 0 or report["status"] != "passed":
        raise ValueError("Model preflight failed; no queries started: " + report.get("error", "unknown error"))
    print(f"Model preflight passed: {report['model']}; {report['duration_s']}s", flush=True)
    return report


if __name__ == "__main__":
    raise SystemExit(probe(sys.argv[1]))
