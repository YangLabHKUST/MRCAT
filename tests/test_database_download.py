"""Reference provisioning must preserve integrity and stay within its manifest."""
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import threading

import pytest


spec = importlib.util.spec_from_file_location(
    "download_database", Path(__file__).resolve().parents[1] / "scripts/download_database.py")
download = importlib.util.module_from_spec(spec)
spec.loader.exec_module(download)


@pytest.fixture
def reference(tmp_path):
    payload = b"reference data\n"
    archives = tmp_path / "archives"
    archives.mkdir()
    archive = archives / "core.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        for name, data in [("hapmap3/list", payload), (".env", b"not a reference\n")]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            output.addfile(info, io.BytesIO(data))
    bundle = dict(description="test reference", archive=dict(
        name=archive.name, format="tar.gz", url=None,
        size_bytes=archive.stat().st_size, sha256=download.digest(archive)),
        files=[dict(path="hapmap3/list", size_bytes=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest())])
    manifest = tmp_path / "manifest.json"
    data = dict(schema_version=1, release_base_url=None,
                bundles={"core": bundle})
    manifest.write_text(json.dumps(data))
    return manifest, data, archives, tmp_path / "installed"


def options(reference):
    manifest, _, _, root = reference
    return ["--manifest", str(manifest), "--database-dir", str(root)]


def test_http_install_checks_files_and_reuses_verified_data(reference):
    _, _, archives, root = reference
    server = ThreadingHTTPServer(("127.0.0.1", 0),
                                partial(SimpleHTTPRequestHandler, directory=str(archives)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert download.main(options(reference) + [
            "--base-url", f"http://127.0.0.1:{server.server_port}"]) == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert (root / "hapmap3/list").read_bytes() == b"reference data\n"
    assert not (root / ".env").exists()
    # No URL is available now: the second invocation must rely on verified files.
    assert download.main(options(reference)) == 0
    assert download.main(options(reference) + ["--check"]) == 0
    assert not list(root.glob(".mrcat-*"))


def test_check_and_unpublished_source_do_not_create_directories(reference):
    root = reference[3]
    assert download.main(options(reference) + ["--check"]) == 1
    assert not root.exists()
    with pytest.raises(ValueError, match="not been published"):
        download.main(options(reference))
    assert not root.exists()


def test_corrupt_archive_preserves_existing_reference(reference):
    _, _, archives, root = reference
    target = root / "hapmap3/list"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing installation")
    (archives / "core.tar.gz").write_bytes(b"truncated")
    with pytest.raises(ValueError, match="checksum"):
        download.main(options(reference) + ["--from-dir", str(archives)])
    assert target.read_bytes() == b"existing installation"


def test_extracted_file_is_checked_before_install(reference):
    manifest, data, archives, root = reference
    data["bundles"]["core"]["files"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Extracted file checksum"):
        download.main(options(reference) + ["--from-dir", str(archives)])
    assert not (root / "hapmap3/list").exists()
    assert not list(root.glob(".mrcat-*"))


@pytest.mark.parametrize("path", ["../escape", "/absolute", "a/../../escape", "a\\..\\escape"])
def test_manifest_cannot_escape_database(reference, path):
    manifest, data, archives, root = reference
    data["bundles"]["core"]["files"][0]["path"] = path
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Unsafe reference path"):
        download.main(options(reference) + ["--from-dir", str(archives)])
    assert not root.exists()


def test_existing_symlink_cannot_redirect_installation(reference, tmp_path):
    _, _, archives, root = reference
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    (root / "hapmap3").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes database"):
        download.main(options(reference) + ["--from-dir", str(archives)])
    assert list(outside.iterdir()) == []


def test_tar_symlink_is_not_installed(reference):
    manifest, data, archives, root = reference
    archive = archives / "core.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        info = tarfile.TarInfo("hapmap3/list")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        output.addfile(info)
    data["bundles"]["core"]["archive"].update(
        size_bytes=archive.stat().st_size, sha256=download.digest(archive))
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Invalid archive member"):
        download.main(options(reference) + ["--from-dir", str(archives)])
    assert not (root / "hapmap3/list").exists()


def test_executable_permission_is_restored(reference):
    manifest, data, archives, root = reference
    data["bundles"]["core"]["files"][0]["executable"] = True
    manifest.write_text(json.dumps(data))
    assert download.main(options(reference) + ["--from-dir", str(archives)]) == 0
    path = root / "hapmap3/list"
    assert os.access(path, os.X_OK)
    path.chmod(0o644)
    assert download.main(options(reference) + ["--check"]) == 1


def test_complete_install_checks_and_repairs_every_panel(reference):
    manifest, data, archives, root = reference
    extra = json.loads(json.dumps(data["bundles"]["core"]))
    extra["files"][0].update(path="plink/EAS/panel.bim", member="hapmap3/list")
    data["bundles"]["eas-grch38"] = extra
    manifest.write_text(json.dumps(data))
    assert download.main(options(reference) + ["--from-dir", str(archives)]) == 0
    assert (root / "plink/EAS/panel.bim").read_bytes() == b"reference data\n"
    (root / "plink/EAS/panel.bim").unlink()
    assert download.main(options(reference) + ["--check"]) == 1
    assert download.main(options(reference) + ["--from-dir", str(archives)]) == 0
    assert download.main(options(reference) + ["--check"]) == 0
    assert (root / "plink/EAS/panel.bim").read_bytes() == b"reference data\n"


def test_manifest_covers_every_registered_reference():
    from mrcat.database import database_resource_ids

    manifest = json.loads(download.DEFAULT_MANIFEST.read_text())
    included = {resource for bundle in manifest["bundles"].values()
                for resource in bundle["resources"]}
    assert included == set(database_resource_ids())
