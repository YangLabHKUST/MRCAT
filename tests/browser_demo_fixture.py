"""Synthetic transport fixture for the live-demo UI; never calls a model."""
import argparse
import base64
from pathlib import Path
import tempfile

import uvicorn

from test_web_demo import demo_fixture
from mrcat.web.server import create_app
from mrcat.web.service import Service


def reply(self, sid, request):
    saved = self.store.load(sid)
    self.store.event(saved, "user_message", request)
    if request == "Yes, go ahead.":
        saved.update(status="completed", pending=None, active_task=None)
        workspace = self.store.directory(sid) / "workspace"
        (workspace / "synthetic.csv").write_text("method,beta\nSynthetic test,0.2\n")
        (workspace / "synthetic.png").write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII="))
        self.store.event(saved, "code_execution", "Synthetic fixture output; not a scientific result.",
                         execution_id="fixture", language="python", code="print('Synthetic UI fixture')",
                         stdout="Synthetic UI fixture", stderr="", status="exited", returncode=0,
                         agent="mr", generated_files=["workspace/synthetic.csv", "workspace/synthetic.png"])
        self.store.event(saved, "final_answer", "Synthetic fixture complete. [Plot](workspace/synthetic.png)")
    elif not any(word in request.lower() for word in ("run", "analy", "mr-apss")):
        saved.update(status="completed", pending=None)
        self.store.event(saved, "final_answer", "Synthetic literature response for the UI test.")
    else:
        saved.update(status="waiting_user", pending={"kind": "plan_confirmation", "question": "Confirm this synthetic test plan?"})
        self.store.event(saved, "question", "Confirm this synthetic test plan?")
    self.store.save(saved)
    return self.accepted(saved)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18796)
    parser.add_argument("--public-example", action="store_true")
    args = parser.parse_args()
    Service.reply = reply
    app = create_app(**demo_fixture(Path(tempfile.mkdtemp(prefix="mrcat-demo-ui-"))))
    if args.public_example:
        public = app.state.user_services.public
        saved = public.store.create("Synthetic public example", "deepseek")
        reply(public, saved["session_id"], "Yes, go ahead.")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
