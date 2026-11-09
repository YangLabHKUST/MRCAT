"""Run from outside the checkout after installing the built wheel, without an API key."""
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import mrcat
from mrcat.agent import Agent
from mrcat.skills import SkillRegistry
from mrcat.store import Store
from mrcat.web.server import create_app


def main():
    root = Path(mrcat.__file__).resolve().parents[1]
    assert root != Path(__file__).resolve().parents[1], "Install the wheel in an independent environment first"
    for module in ("benchmark", "preflight", "sandbox", "provenance"):
        assert importlib.util.find_spec(f"mrcat.{module}") is None, module
    registry = SkillRegistry(root / "skills")
    assert len(registry.list_bundles()) == 26
    for skill in registry.list_bundles():
        assert skill.instruction_body
        for script in (skill.skill_dir / "scripts").glob("*.py"):
            importlib.import_module(".".join(script.relative_to(root).with_suffix("").parts))
    assert (root / "mrcat/tool/MRTool/mr_input_scale.R").is_file()
    for command in ("mrcat", "mrcat-web"):
        process = subprocess.run([str(Path(sys.executable).parent / command), "--help"], capture_output=True, text=True)
        assert process.returncode == 0, process.stderr
    with TemporaryDirectory(prefix="mrcat-installed-") as temporary:
        store = Store(temporary)
        state = store.create("Check the installation", "openai")
        sid = state["session_id"]
        model = lambda **kwargs: json.dumps(dict(route="respond", action="respond", message="Installed agent responded.", effective_request=None))
        done = Agent(root, store, model=model).run(sid, "Check the installation")
        assert done["status"] == "completed"
        with TestClient(create_app(artifact_dir=temporary)) as client:
            assert client.get("/").status_code == 200
            assert client.get("/static/app.js").status_code == 200
            assert client.get("/static/vendor/plotly-gl2d-3.1.0.min.js").status_code == 200
            assert len(client.get("/api/methods").json()["methods"]) == 12
            assert client.get(f"/api/sessions/{sid}").json()["session_id"] == sid
    print("PASS: installed wheel, 26 Skills, wrapper imports, prompts, R helpers, Web assets, checkpoint and CLI entries")


if __name__ == "__main__":
    main()
