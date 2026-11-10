"""Anonymous, bounded BMI/T2D example using the regular session service."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import fcntl
import json
import os
import secrets
import shutil
import threading
import time

import jwt
from fastapi import HTTPException

from mrcat.state.store import Store, write_json
from .service import BusyError, Service

COOKIE = "mrcat_demo_visitor"


class DemoVisitors:
    def __init__(self, root, artifact_dir, data_dir):
        self.root = Path(root)
        self.base = Path(artifact_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        self.data_dir = Path(data_dir).resolve()
        self.catalog = json.loads((self.root / "mrcat/web/static/bmi-demo.json").read_text())
        inventory = json.loads((self.root / "examples/bmi_t2d/local_inputs.json").read_text())
        for item in inventory:
            path = self.data_dir / item["filename"]
            if not path.is_file() or path.stat().st_size != item["size_bytes"]:
                raise ValueError(f"Missing or incorrect demo input: {item['filename']}")
            digest = sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != item["sha256"]:
                raise ValueError(f"Demo input checksum mismatch: {item['filename']}")
        self.inventory = inventory
        self.online_cache = []
        cache_root = os.getenv("MRCAT_DEMO_ONLINE_CACHE")
        if cache_root:
            for study_id in ("ieu-b-40", "ebi-a-GCST006867"):
                markers = list((Path(cache_root) / "opengwas" / study_id).glob("*/.gwas-download-complete.json"))
                if len(markers) != 1:
                    raise ValueError(f"Expected one completed download cache for {study_id}")
                marker = json.loads(markers[0].read_text())
                source = markers[0].parent / f"{study_id}.tsv.gz"
                if marker.get("study_id") != study_id or not source.is_file() or source.stat().st_size != marker.get("file_size"):
                    raise ValueError(f"Incomplete download cache for {study_id}")
                digest = sha256()
                with source.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                self.online_cache.append((source, {
                    "source": "opengwas", "study_id": study_id,
                    "source_page": f"https://opengwas.io/datasets/{study_id}",
                    "file_ref": f"workspace/inputs/online/{study_id}.tsv.gz",
                    "file_size": source.stat().st_size, "sha256": digest.hexdigest(),
                    "study_metadata": marker.get("study_metadata", {}),
                    "note": "Previously downloaded GWAS summary statistics, before QC, harmonization or instrument selection. Verify study metadata against the online source.",
                }))
        key_path = self.base / ".visitor-key"
        try:
            with key_path.open("x") as output:
                os.chmod(key_path, 0o600)
                output.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        self.key = key_path.read_text().strip()
        self.services = {}
        self.lock = threading.RLock()

    def visitor(self, request):
        token = request.cookies.get(COOKIE)
        try:
            claims = jwt.decode(token or "", self.key, algorithms=["HS256"],
                                audience="mrcat-bmi-demo", options={"require": ["sub", "exp", "aud"]})
            subject = claims["sub"]
            if not isinstance(subject, str) or len(subject) != 32 or any(c not in "0123456789abcdef" for c in subject):
                raise jwt.InvalidTokenError("Invalid visitor")
        except jwt.PyJWTError:
            if request.method not in {"GET", "HEAD"}:
                raise HTTPException(401, "Open the demo page before starting an analysis.")
            subject = secrets.token_hex(16)
            token = jwt.encode({"sub": subject, "aud": "mrcat-bmi-demo", "exp": int(time.time()) + 7 * 86400},
                               self.key, algorithm="HS256")
        with self.lock:
            if subject not in self.services:
                self.services[subject] = DemoService(self, self.base / "visitors" / subject)
            return self.services[subject], token

    @contextmanager
    def turn(self, service, sid=None):
        # Serialize admission across processes and retain the quota across restarts.
        with self.lock, (self.base / ".admission.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ledger_path = self.base / ".admission.json"
            ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
            today = datetime.now(timezone.utc).date().isoformat()
            if ledger.get("date") != today:
                ledger.update(date=today, turns=0)
            active = ledger.get("active")
            if active:
                store = Store(active["store"])
                saved = store.load(active["sid"])
                job = saved.get("job") or {}
                if job.get("status") == "running":
                    try:
                        os.kill(job["pid"], 0)
                    except ProcessLookupError:
                        pass
                    else:
                        raise BusyError("The demo is running an analysis. Please try again when it finishes.")
            if ledger.get("turns", 0) >= int(os.getenv("MRCAT_DEMO_DAILY_TURNS", "40")):
                raise HTTPException(429, "Today's demo allowance has been used. Please return tomorrow.")
            if sid:
                saved = service.store.load(sid)
                count = sum(e["type"] == "user_message" for e in saved["events"])
                if count >= 16:
                    raise HTTPException(429, "This example has reached its interaction allowance.")
            result = {}
            yield result
            ledger["turns"] = ledger.get("turns", 0) + 1
            ledger["active"] = {"store": str(service.store.base), "sid": result["sid"]}
            write_json(ledger_path, ledger)

    def close(self):
        with self.lock:
            for service in self.services.values():
                service.views.close()


class DemoService(Service):
    def __init__(self, visitors, directory):
        super().__init__(visitors.root, directory)
        self.visitors = visitors

    def start(self, question, provider):
        return self.submit(None, question)

    def reply(self, sid, request):
        return self.submit(sid, request)

    def submit(self, sid, request, *, dataset=None):
        if not isinstance(request, str) or not request.strip():
            raise ValueError("A message is required")
        with self.visitors.turn(self, sid) as admission:
            if sid is None:
                if any(self.store.base.glob("session_*")):
                    raise ValueError("Continue your existing conversation from the Sessions list.")
                saved = self.store.create(request, os.getenv("MRCAT_DEMO_PROVIDER", "deepseek"))
                sid = saved["session_id"]
            else:
                saved = self.reconcile(self.store.load(sid))
                if (saved.get("job") or {}).get("status") == "running":
                    raise BusyError("A task is running. Stop it before sending a new request.")
            if dataset == "online":
                self.attach_online_inputs(saved, request)
            elif dataset == "local":
                self.attach_inputs(saved, request)
            result = super().reply(sid, request)
            admission["sid"] = sid
            return result

    def attach_online_inputs(self, saved, request):
        directory = self.store.directory(saved["session_id"])
        datasets = {
            "ieu-b-40": {"name": "BMI (OpenGWAS ieu-b-40)"},
            "ebi-a-GCST006867": {"name": "Type 2 diabetes (OpenGWAS ebi-a-GCST006867)"},
        }
        for source, item in self.visitors.online_cache:
            target = directory / item["file_ref"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            datasets[item["study_id"]]["file_ref"] = item["file_ref"]
        request = (
            request
            + " Use the two studies in this study setup. Verify their metadata and suitability online; "
            "report any problem before changing datasets. "
        )
        if self.visitors.online_cache:
            write_json(directory / "workspace/inputs/online_gwas_sources.json",
                       [item for _, item in self.visitors.online_cache])
            request += (
                "The supplied file_ref paths are session-relative, previously downloaded GWAS inputs before QC. "
                "Reuse these files; their provenance and checksums are in workspace/inputs/online_gwas_sources.json."
            )
        else:
            request += "Download these studies after verification; no cached files are attached."
        saved["study_setup"] = {
            "exposures": [datasets["ieu-b-40"]],
            "outcomes": [datasets["ebi-a-GCST006867"]],
            "analysis_request": request,
            "methods": [], "sources": ["opengwas"],
        }
        self.store.save(saved)

    def attach_inputs(self, saved, request):
        directory = self.store.directory(saved["session_id"]) / "workspace/inputs"
        directory.mkdir(parents=True, exist_ok=True)
        for item in self.visitors.inventory:
            # Private copies: analysis code cannot modify another visitor's inputs.
            shutil.copyfile(self.visitors.data_dir / item["filename"], directory / item["filename"])
        saved["study_setup"] = {
            "exposures": [{"name": "BMI", "file_ref": "workspace/inputs/bmi_mrapss.gz"}],
            "outcomes": [{"name": "Type 2 diabetes", "file_ref": "workspace/inputs/t2d_mrapss.gz"}],
            "analysis_request": request,
            "methods": [], "sources": [],
        }
        self.store.save(saved)

    def fork(self, sid):
        raise PermissionError("Copying sessions is not available in the public demo.")

    def study_setup(self, sid, *, exposure_manifest, outcome_manifest, analysis_request,
                    methods, sources="[]", exposure_files=None, outcome_files=None):
        if exposure_files or outcome_files:
            raise PermissionError("File uploads are not available in the public demo.")
        selected = dict(exposures=json.loads(exposure_manifest), outcomes=json.loads(outcome_manifest),
                        methods=json.loads(methods), sources=json.loads(sources))
        for step in self.visitors.catalog["steps"]:
            if step.get("setup") == selected:
                return self.submit(sid, analysis_request, dataset=step["id"])
        raise ValueError("Choose one of the supplied example datasets.")
