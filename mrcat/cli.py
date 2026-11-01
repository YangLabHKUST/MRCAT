"""Interactive CLI sharing the persistent agent used by the web console."""
import argparse
import os
from pathlib import Path

from .agent import Agent
from .config.env import load_repo_dotenv, disable_proxy_from_env_if_requested
from .store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=Path("runtime_artifacts"))
    parser.add_argument("--session")
    parser.add_argument("--provider")
    parser.add_argument("--question")
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.environ.setdefault("MRCAT_CONFIG_DIR", str(Path.cwd()))
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    load_repo_dotenv(repo_root=root)
    disable_proxy_from_env_if_requested()
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    store = Store(args.artifact_dir)
    sid = args.session
    request = args.question if args.question is not None else input("mrcat> ")
    while request.strip():
        if sid is None:
            sid = store.create(request, os.getenv("LLM_PROVIDER", "anthropic"))["session_id"]
        os.environ["LLM_PROVIDER"] = store.load(sid)["provider"]
        (store.directory(sid) / "STOP").unlink(missing_ok=True)
        state = Agent(root, store).run(sid, request)
        print(state["events"][-1]["content"])
        print("Session:", sid)
        if args.question is not None:
            break
        request = input("mrcat> ")
