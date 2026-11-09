"""Run a minimal persistent conversation without an API key or MR data."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import mrcat
from mrcat.agent import Agent
from mrcat.store import Store

with TemporaryDirectory(prefix="mrcat-example-") as directory:
    store = Store(directory)
    state = store.create("Check my installation", "openai")
    def model(**kwargs):
        return json.dumps(dict(route="respond", action="respond",
                               message="MRCAT is installed and session state is available.",
                               effective_request=None))
    state = Agent(Path(mrcat.__file__).resolve().parents[1], store, model=model).run(
        state["session_id"], "Check my installation")
    assert state["status"] == "completed"
    assert store.load(state["session_id"])["messages"]
    print(state["events"][-1]["content"])
