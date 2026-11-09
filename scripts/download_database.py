#!/usr/bin/env python3
"""Install checksum-pinned reference bundles without importing MRCAT or .env."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile


DEFAULT_MANIFEST = Path(__file__).with_name("database_manifest.json")


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def destination(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name or not relative.parts:
        raise ValueError(f"Unsafe reference path: {name}")
    target = root.joinpath(*relative.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Reference path escapes database directory: {name}")
    return target


def matches(path, record):
    return (path.is_file() and path.stat().st_size == record["size_bytes"]
            and digest(path) == record["sha256"])


def problems(root, bundle):
    failures = []
    for record in bundle["files"]:
        path = destination(root, record["path"])
        if not matches(path, record):
            failures.append(record["path"] + ": missing or checksum mismatch")
        elif record.get("executable") and not os.access(path, os.X_OK):
            failures.append(record["path"] + ": not executable")
    return failures


def install_archive(archive, root, bundle):
    """Stage and verify the entire bundle before replacing any installed file."""
    if not matches(archive, bundle["archive"]):
        raise ValueError(f"Archive checksum or size mismatch: {archive.name}")
    with tempfile.TemporaryDirectory(prefix=".mrcat-stage-", dir=root) as tmp:
        staging = Path(tmp)
        if bundle["archive"]["format"] == "zip":
            reader = zipfile.ZipFile(archive)
        else:
            reader = tarfile.open(archive, "r:*")
        with reader:
            for record in bundle["files"]:
                target = destination(staging, record["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                member = record.get("member", record["path"])
                if isinstance(reader, zipfile.ZipFile):
                    info = reader.getinfo(member)
                    if info.file_size != record["size_bytes"]:
                        raise ValueError(f"Unexpected archive member size: {member}")
                    source = reader.open(info)
                else:
                    info = reader.getmember(member)
                    if not info.isfile() or info.size != record["size_bytes"]:
                        raise ValueError(f"Invalid archive member: {member}")
                    source = reader.extractfile(info)
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, 4 * 1024 * 1024)
                if not matches(target, record):
                    raise ValueError(f"Extracted file checksum mismatch: {record['path']}")
                target.chmod(0o755 if record.get("executable") else 0o644)
        for record in bundle["files"]:
            target = destination(root, record["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(destination(staging, record["path"]), target)


def source_url(bundle, base_url):
    url = bundle["archive"].get("url")
    if not url and base_url:
        url = base_url.rstrip("/") + "/" + urllib.parse.quote(bundle["archive"]["name"])
    if not url:
        raise ValueError(
            "Reference bundles have not been published. Use --from-dir for local "
            "prepared bundles, or --base-url after publication. See docs/data.md."
        )
    if urllib.parse.urlsplit(url).scheme not in {"https", "http"}:
        raise ValueError("Download URLs must use HTTPS or HTTP.")
    return url


def fetch(url, archive, record):
    """Use a temporary file; never accept an incomplete or changed download."""
    total = 0
    with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as output:
        for block in iter(lambda: response.read(4 * 1024 * 1024), b""):
            total += len(block)
            if total > record["size_bytes"]:
                raise ValueError("Download exceeds the pinned archive size.")
            output.write(block)
    if not matches(archive, record):
        raise ValueError("Downloaded archive failed SHA-256/size verification.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--database-dir", type=Path,
                        default=Path(os.environ.get("MRCAT_DATABASE_DIR", "database")))
    parser.add_argument("--list", action="store_true", help="List bundles without downloading.")
    parser.add_argument("--check", action="store_true", help="Verify installed files without writing.")
    parser.add_argument("--from-dir", type=Path, help="Install prepared local archives without network access.")
    parser.add_argument("--base-url", help="Published release or object-store directory URL.")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text())
    if manifest["schema_version"] != 1:
        raise ValueError("Unsupported reference manifest version.")
    bundles = manifest["bundles"]
    if args.list:
        for name, bundle in bundles.items():
            size = sum(item["size_bytes"] for item in bundle["files"])
            print(f"{name}: {size / 1e6:.1f} MB installed; {bundle['description']}")
        return 0
    root = args.database_dir.expanduser().resolve()
    pending = []
    for name, bundle in bundles.items():
        failures = problems(root, bundle)
        print(f"{name}: {'needs preparation' if failures else 'verified'}", flush=True)
        if failures:
            pending.append(name)
            if args.check:
                for failure in failures:
                    print(f"  {failure}")
    if args.check:
        return 1 if pending else 0
    # Resolve every missing source before making changes (including unpublished bundles).
    sources = {}
    for name in pending:
        bundle = bundles[name]
        required_platform = bundle.get("platform")
        actual_platform = f"{platform.system().lower()}-{platform.machine().lower()}"
        if required_platform and required_platform != actual_platform:
            raise ValueError(f"{name} requires {required_platform}; this system is {actual_platform}.")
        if args.from_dir:
            path = destination(args.from_dir.expanduser().resolve(), bundle["archive"]["name"])
            if not path.is_file():
                raise ValueError(f"Missing local archive: {path}")
            sources[name] = path
        else:
            sources[name] = source_url(bundle, args.base_url or manifest.get("release_base_url"))
    if pending:
        root.mkdir(parents=True, exist_ok=True)
    for name in pending:
        bundle = bundles[name]
        source = sources[name]
        if isinstance(source, Path):
            install_archive(source, root, bundle)
        else:
            print(f"Downloading {name} ({bundle['archive']['size_bytes'] / 1e6:.1f} MB)...", flush=True)
            with tempfile.TemporaryDirectory(prefix=".mrcat-download-", dir=root) as tmp:
                archive = Path(tmp) / "archive"
                fetch(source, archive, bundle["archive"])
                install_archive(archive, root, bundle)
        print(f"{name}: installed and verified", flush=True)
    print(f"Complete reference database ready: {root}")
    print("For runs from another directory, export MRCAT_DATABASE_DIR to this absolute path.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"Database preparation failed: {exc}", file=sys.stderr)
        sys.exit(1)
