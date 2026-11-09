"""Export a reviewed, completed example for the existing read-only Web viewer.

The source checkpoint remains private and authoritative. This export contains
only browser projections and selected small artifacts, never a runnable session.
"""
import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path

import markdown
from dotenv import dotenv_values
from mrcat.web.service import Service


def export(root, run_path, destination, env_files):
    run = json.loads(run_path.read_text())
    service = Service(root, run["store"])
    state = service.store.load(run["session_id"])
    if state["status"] != "completed" or (state.get("job") or {}).get("status") == "running":
        raise ValueError("Export only after the example has completed and been reviewed.")
    if len(run["stages"]) != 4:
        raise ValueError("Record literature, online MR, local MR and MR-APSS stages.")
    private_values = dict(os.environ)
    for path in env_files:
        # Preserve different values of the same key across supplied files.
        private_values.update({f"{path}:{key}": value for key, value in dotenv_values(path).items()})
    secrets = [value for key, value in private_values.items()
               if value and len(value) >= 12 and re.search("KEY|TOKEN|SECRET|PASSWORD", key.upper())]
    session = service.store.directory(run["session_id"])
    replacements = {str(session): ".", str(root): "/path/to/mrcat"}

    def scrub(text):
        for secret in secrets:
            text = text.replace(secret, "[REDACTED]")
        for source, target in replacements.items():
            text = text.replace(source, target)
        # OpenGWAS downloads include temporary Oracle pre-authenticated URLs.
        text = re.sub(r"(https://[^/\s\"']+\.oci\.customer-oci\.com/p/)[^/\s\"']+(/n/)",
                      r"\1[REDACTED]\2", text)
        # Keep filenames and study identity; remove machine-specific home paths.
        text = re.sub(r"/(?:import/home4|home)/[^/\s\"']+/jyxProject/", "/path/to/projects/", text)
        return text

    def write_json(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(scrub(json.dumps(data, ensure_ascii=False, indent=2)) + "\n")

    destination.mkdir(parents=True, exist_ok=True)
    files = {}
    selected = []
    allowed = {".json", ".tsv", ".csv", ".md", ".txt", ".log", ".py", ".R", ".png", ".pdf"}
    for item in service.files(run["session_id"]):
        relative = item["path"]
        source = session / relative
        if source.suffix not in allowed or source.stat().st_size > 4_000_000:
            continue
        if any(part.startswith(".") or part == "__pycache__" for part in Path(relative).parts):
            continue
        target = destination / "files" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix in {".png", ".pdf"}:
            target.write_bytes(source.read_bytes())
        else:
            target.write_text(scrub(source.read_text()))
        files[relative] = {"path": "files/" + relative,
                           "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                           "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
        selected.append(item)
        if source.suffix in {".tsv", ".csv"}:
            with target.open(newline="") as stream:
                reader = csv.reader(stream, delimiter="\t" if source.suffix == ".tsv" else ",")
                headers = next(reader, [])
                rows = []
                for row in reader:
                    rows.append(row)
                    if len(rows) > 100:
                        break
            table = dict(name=source.name, headers=headers, rows=rows[:100], truncated=len(rows) > 100)
            preview = "files/" + relative + ".preview.json"
            write_json(destination / preview, dict(columns=headers, rows=rows[:100], sheets=[table], truncated=table["truncated"]))
            files[relative]["preview"] = preview
    snapshot = service.project(state, selected, None)
    snapshot["active_job"] = snapshot["latest_job"] = None
    snapshot["pending_question"] = ""
    snapshot["state"]["study_setup"] = {}
    for event in snapshot["mr"]["events"]:
        details = event.get("details", {})
        if "generated_files" in details:
            details["generated_files"] = [p for p in details["generated_files"] if p in files]
        for key in ("source_path", "stdout_path", "stderr_path"):
            if details.get(key) not in files:
                details.pop(key, None)
    # The public alias is not a live server-side session ID.
    encoded = json.dumps(snapshot, ensure_ascii=False).replace(run["session_id"], "example-bmi-t2d")
    snapshot = json.loads(scrub(encoded))
    for image in snapshot["images"]:
        image["url"] = "/static/examples/bmi-t2d/" + files[image["summary"]]["path"]
    write_json(destination / "recording.json", dict(
        snapshot=snapshot, files=files, stages=run["stages"],
        provenance={**{k: run[k] for k in ("source_commit", "model", "provider", "recorded_at")},
                    "source_note": "source_commit is the base commit; source_hashes.json records the working tree at run start.",
                    "export_note": "Machine paths, configured credentials and temporary download access tokens are redacted."},
    ))
    write_json(destination / "prompts.json", [dict(title=s["title"], question=s["question"]) for s in run["stages"]])
    write_json(destination / "source_hashes.json", json.loads((run_path.parent / "source_hashes.json").read_text()))
    write_json(destination / "environment.json", json.loads((run_path.parent / "environment.json").read_text()))
    guide = (root / "examples/bmi_t2d/README.md").read_text()
    guide = guide.split("## Maintainer export")[0]
    guide = guide.replace("../../README.md#install", "#installation")
    guide = guide.replace("../../docs/data.md", "#reference-data-setup")
    guide = guide.replace("http://127.0.0.1:7869/#example-bmi-t2d", "/#example-bmi-t2d")
    installation = (root / "README.md").read_text().split("## Install\n", 1)[1].split("## Start\n", 1)[0]
    guide += "\n## Installation\n" + installation
    guide += "\n## Reference-data setup\n" + (root / "docs/data.md").read_text().split("\n", 1)[1]
    for name in ("local_inputs.json", "expected_results.json"):
        source = root / "examples/bmi_t2d" / name
        if source.exists():
            write_json(destination / name, json.loads(source.read_text()))
    guide += ("\n## Recorded inputs and outputs\n\n[Local input inventory](local_inputs.json) · "
              "[Expected results](expected_results.json) · [Recorded prompts](prompts.json) · "
              "[Source file hashes](source_hashes.json) · [Recorded environment](environment.json)\n")
    (destination / "tutorial.md").write_text(guide)
    html = markdown.markdown(guide, extensions=["tables", "fenced_code", "toc"])
    (destination / "tutorial.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>BMI and T2D · MRCAT tutorial</title><style>'
        'body{max-width:900px;margin:40px auto;padding:0 24px;font:17px/1.65 system-ui;color:#17212f}'
        'a{color:#1868a8}pre{padding:16px;background:#eef3f8;overflow:auto}'
        'code{overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}'
        'td,th{padding:8px;border-bottom:1px solid #d8e1ea;text-align:left}'
        'blockquote{margin-left:0;padding-left:20px;border-left:3px solid #1868a8}'
        '</style><nav><a href="/#example-bmi-t2d">← View the recorded example</a> · '
        '<a href="tutorial.md" download>Download tutorial</a></nav><main>' + html + '</main></html>')
    print(f"Exported {len(files)} reviewed artifacts to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, action="append", default=[])
    args = parser.parse_args()
    export(Path(__file__).resolve().parents[2], args.run, args.destination, args.env_file)
