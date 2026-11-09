"""Export a completed Result 4 session without running agents or editing checkpoints."""
import argparse
from contextlib import closing
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from urllib.parse import quote, unquote

from dotenv import dotenv_values
from openpyxl import load_workbook

from mrcat.store import Store
from mrcat.web.service import Service

EXAMPLE_ID = "example-result4"
ASSET_ROOT = "/static/examples/result4"
TEXT = {".json", ".md", ".txt", ".log", ".py", ".r", ".tsv", ".csv", ".svg", ".html"}
BINARY = {".png", ".jpg", ".jpeg", ".pdf", ".tiff", ".xlsx"}


def sanitizer(session, env_files):
    values = list(os.environ.items())
    for path in env_files:
        values.extend(dotenv_values(path).items())
    secrets = {v for k, v in values if v and len(v) >= 12 and re.search("KEY|TOKEN|SECRET|PASSWORD", k.upper())}

    def scrub(text):
        for value in sorted(secrets, key=len, reverse=True):
            text = text.replace(value, "[REDACTED]")
        text = text.replace(str(session), "/recorded-session")
        text = re.sub(r"https://[^\s\"'<>]*\.oci\.customer-oci\.com/p/[^\s\"'<>]+", "[REDACTED_DOWNLOAD_URL]", text)
        text = re.sub(r"(?i)([?&](?:token|access_token|api_key|signature|x-amz-signature)=)[^&\s\"'<>]+", r"\1REDACTED", text)
        text = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1REDACTED", text)
        text = re.sub(r"/(?:import/home\d*|home)/[^/\s\"'<>]+/", "/local/", text)
        return text
    return scrub, secrets


def allowed(path, size):
    parts = path.parts
    if any(p.startswith(".") or "audit" in p.lower() or p == "__pycache__" for p in parts):
        return False
    if "draft" in path.name.lower() or size > 4_000_000:
        return False
    return path.suffix.lower() in TEXT | BINARY or path.name.endswith((".tsv.gz", ".csv.gz"))


def preview_table(path):
    def table(name, rows):
        rows = iter(rows)
        headers = list(next(rows, []))
        data = []
        for row in rows:
            data.append(list(row))
            if len(data) > 100:
                break
        return dict(name=name, headers=headers, rows=data[:100], truncated=len(data) > 100)

    if path.suffix == ".xlsx":
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            sheets = [table(s.title, s.iter_rows(values_only=True)) for s in book]
        finally:
            book.close()
    else:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as stream:
            sheets = [table(path.name, csv.reader(stream, delimiter="\t" if ".tsv" in path.name else ","))]
    first = sheets[0]
    return dict(columns=first["headers"], rows=first["rows"], sheets=sheets,
                truncated=any(s["truncated"] for s in sheets))


def export(session, destination, *, env_files=(), site=None):
    session = Path(session).resolve()
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Export to an empty directory; keep reviewed exports explicit.")
    root = Path(__file__).resolve().parents[2]
    sid = session.name
    service = Service(root, session.parent)
    checkpoint = service.store.checkpoint_path(sid)
    # Read a consistent private copy; Store.load may initialize SQLite tables.
    with tempfile.TemporaryDirectory(prefix="mrcat-result4-export-", dir=checkpoint.parent) as temp:
        copied = Path(temp) / sid
        copied.mkdir()
        with closing(sqlite3.connect(checkpoint.as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(copied / "graph.sqlite")) as target:
                source.backup(target)
        state = Store(temp).load(sid)
    if state["status"] != "completed" or (state.get("job") or {}).get("status") == "running":
        raise ValueError("Only a completed, idle session can be published as an example.")
    report = service.final_report(sid, state)
    if not report:
        raise ValueError("The completed session must have a final report.")
    scrub, secrets = sanitizer(session, env_files)
    inventory = service.files(sid)
    selected = [f for f in inventory if allowed(Path(f["path"]), (session / f["path"]).stat().st_size)]
    files = {f["path"]: {"path": "files/" + f["path"]} for f in selected}

    def rewrite(text):
        text = scrub(text)
        # Previously rendered summaries may already contain live-session routes.
        def link(match):
            path = unquote(match[1].replace("&amp;", "&"))
            return ASSET_ROOT + "/" + quote(files[path]["path"], safe="/") if path in files else "#not-in-recording"
        return re.sub(r"/api/sessions/[^/\s]+/artifacts/raw\?[^\s\"'<>]*?summary=([^&\s\"'<>]+)(?:&(?:amp;)?[^\s\"'<>]*)?", link, text)

    def write_json(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rewrite(json.dumps(data, ensure_ascii=False, default=str)), encoding="utf-8")

    for item in selected:
        relative = item["path"]
        source, target = session / relative, destination / files[relative]["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix.lower()
        if suffix in TEXT:
            target.write_text(rewrite(source.read_text()), encoding="utf-8")
        elif suffix == ".gz":
            with source.open("rb") as stream:
                compressed = stream.read(2) == b"\x1f\x8b"
            with (gzip.open(source, "rt") if compressed else source.open()) as stream:
                content = rewrite(stream.read())
            target.write_bytes(gzip.compress(content.encode(), mtime=0))
        elif suffix == ".xlsx":
            book = load_workbook(source)
            for sheet in book:
                for row in sheet:
                    for cell in row:
                        if isinstance(cell.value, str):
                            cell.value = rewrite(cell.value)
                        if cell.hyperlink:
                            cell.hyperlink = rewrite(cell.hyperlink.target or "")
            book.save(target)
            book.close()
        else:
            shutil.copyfile(source, target)
        files[relative]["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        if source.name.endswith((".tsv", ".csv", ".tsv.gz", ".csv.gz", ".xlsx")):
            files[relative]["preview"] = files[relative]["path"] + ".preview.json"
            write_json(destination / files[relative]["preview"], preview_table(target))

    snapshot = service.project(service.store.preview(state), selected, report)
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
    snapshot = json.loads(json.dumps(snapshot, default=str).replace(sid, EXAMPLE_ID))
    for img in snapshot["images"]:
        img["url"] = ASSET_ROOT + "/" + quote(files[img["summary"]]["path"], safe="/")
    events = snapshot["mr"]["events"]
    # Task boundaries come from recorded user messages and task creation events.
    task_starts = [i for i, event in enumerate(events) if event["type"] == "task_created"]
    if len(task_starts) != 2:
        raise ValueError("Expected two completed analysis tasks.")
    boundaries = [0]
    for i, event in enumerate(events):
        if i == task_starts[1]:
            boundaries.append(max(j for j in range(i) if events[j]["type"] == "final") + 1)
        if event["type"] == "report_started":
            boundaries.append(max(j for j in range(i) if events[j]["type"] == "user_message"))
    boundaries.append(len(events))
    if len(boundaries) != 4:
        raise ValueError("Expected original analysis, replication and report stages.")
    titles = ["Original analysis", "FinnGen replication", "Scientific report"]
    description = "Completed session · Read only · No API key needed · Large GWAS files are not included"
    stages = [dict(title="Full session", description=description, start=0, end=len(events))]
    stages += [dict(title=title, description=description, start=a, end=b)
               for title, a, b in zip(titles, boundaries, boundaries[1:])]
    report_path = str(Path(report["summary"]).with_name("scientific_report.html"))
    if report_path not in files:
        raise ValueError("Final report is missing from the export.")
    recording = dict(title="Result 4 · Hexadecanedioate → CAD", snapshot=snapshot,
                     files=files, stages=stages, report_path=report_path,
                     provenance=dict(source_session_id=sid, source_updated_at=state["updated_at"],
                                     source_status=state["status"],
                                     note="Recorded analysis; source session unchanged. Private paths and credentials are redacted. Large GWAS files and report drafts are omitted."))
    write_json(destination / "recording.json", recording)
    for path in destination.rglob("*"):
        if path.is_file():
            raw = path.read_bytes()
            if any(secret.encode() in raw for secret in secrets):
                raise ValueError("Credential scan failed; do not publish this export.")
    service.views.close()
    if site:
        build_site(root, destination, Path(site))
    return dict(files=len(files), events=len(events), stages=len(stages), source_session_id=sid)


def build_site(root, recording, site):
    """Copy current UI assets into a standalone site containing no Python backend."""
    if site.exists() and any(site.iterdir()):
        raise ValueError("Build the static site in an empty directory.")
    static = root / "mrcat/web/static"
    shutil.copytree(static, site / "static", ignore=shutil.ignore_patterns("examples", "__pycache__"))
    shutil.copytree(recording, site / "static/examples/result4")
    html = (static / "index.html").read_text().replace("<body>", '<body data-replay-only="true">')
    (site / "index.html").write_text(html)
    (site / "static/index.html").write_text(html)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, action="append", default=[])
    parser.add_argument("--site", type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.session, args.destination, env_files=args.env_file, site=args.site)))
