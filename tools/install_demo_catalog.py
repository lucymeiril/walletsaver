#!/usr/bin/env python3
"""Install once or preserve an existing demo; catalog updates use admin review."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import zlib

REQUIRED_FILES = ("admin.sqlite", "public_snapshot.sqlite", "opinet.sqlite")
FILES = REQUIRED_FILES + ("external_hotdeals.sqlite",)
MARKER = ".demo-catalog-installed.json"
LOCK = ".demo-catalog-install.lock"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected a regular file: {path.name}")


def stored_path(source: Path, name: str, spec: dict) -> Path:
    return source / spec.get("archive_file", name)


def copy_database(source: Path, name: str, spec: dict, output) -> None:
    """Stream only a fixed raw SQLite or its fixed .gz; bound restored size."""
    opener = gzip.open if "archive_file" in spec else open
    written = 0
    with opener(stored_path(source, name, spec), "rb") as origin:
        while chunk := origin.read(1024 * 1024):
            written += len(chunk)
            if written > spec["bytes"]:
                raise ValueError(f"Restored byte count exceeds manifest: {name}")
            output.write(chunk)
    if written != spec["bytes"]:
        raise ValueError(f"Restored byte count mismatch: {name}")


def validate_database(path: Path, name: str, spec: dict) -> None:
    if path.stat().st_size != spec["bytes"] or digest(path) != spec["sha256"]:
        raise ValueError(f"Restored hash/size mismatch: {name}")
    # immutable + read-only: inspection cannot initialize or journal SQLite.
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(spec["required_tables"]).issubset(tables):
            raise ValueError(f"Required tables missing: {name}")
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError(f"SQLite integrity check failed: {name}")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError(f"Foreign key check failed: {name}")
        for table, expected in spec["counts"].items():
            if table not in tables or not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
                raise ValueError(f"Invalid table count contract: {name}")
            quoted = '"' + table.replace('"', '""') + '"'
            if connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0] != expected:
                raise ValueError(f"Table count mismatch: {name}/{table}")
    finally:
        connection.close()


def validate_source(source: Path) -> tuple[dict, str]:
    manifest_path = source / "manifest.json"
    regular_file(manifest_path)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValueError("Demo manifest must be an object")
    if manifest.get("schema_version") != 1 or isinstance(manifest.get("schema_version"), bool):
        raise ValueError("Unsupported demo manifest schema")
    revision = manifest.get("catalog_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("Invalid catalog revision")
    if (not isinstance(manifest.get("files"), dict) or not set(REQUIRED_FILES).issubset(manifest["files"])
            or not set(manifest["files"]).issubset(FILES)):
        raise ValueError("Manifest must describe admin/public/fuel and only the optional external hotdeal snapshot")
    # Validate every stored digest before any temporary restoration or target write.
    for name in manifest["files"]:
        spec = manifest["files"][name]
        if not isinstance(spec, dict):
            raise ValueError(f"Invalid manifest file contract: {name}")
        for prefix in ("", "archive_") if any(k.startswith("archive_") for k in spec) else ("",):
            sha = spec.get(prefix + "sha256")
            size = spec.get(prefix + "bytes")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError(f"Invalid manifest hash: {name}")
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                raise ValueError(f"Invalid manifest byte count: {name}")
        if any(k.startswith("archive_") for k in spec) and spec.get("archive_file") != name + ".gz":
            raise ValueError(f"Only the fixed {name}.gz archive is allowed")
        path = stored_path(source, name, spec)
        regular_file(path)
        if any(Path(str(source / name) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise ValueError(f"Shipped database must be closed/checkpointed: {name}")
        prefix = "archive_" if "archive_file" in spec else ""
        if path.stat().st_size != spec[prefix + "bytes"] or digest(path) != spec[prefix + "sha256"]:
            raise ValueError(f"Source hash/size mismatch: {name}")
        required = spec.get("required_tables")
        counts = spec.get("counts")
        if not isinstance(required, list) or not required or any(not isinstance(t, str) or not t for t in required):
            raise ValueError(f"Missing required table contract: {name}")
        if not isinstance(counts, dict) or not set(required).issubset(counts):
            raise ValueError(f"Missing required table counts: {name}")
    for name in manifest["files"]:
        spec = manifest["files"][name]
        if "archive_file" in spec:
            # Temporary, fixed-name restoration is inspected with a read-only VFS;
            # no generic archive extraction or source SQLite mutation is possible.
            with tempfile.TemporaryDirectory(prefix="walletsaver-demo-validate-") as directory:
                restored = Path(directory) / name
                with restored.open("xb") as output:
                    copy_database(source, name, spec, output)
                validate_database(restored, name, spec)
        else:
            validate_database(source / name, name, spec)
    return manifest, hashlib.sha256(manifest_bytes).hexdigest()


def install(source: Path, target: Path) -> str:
    if source.is_symlink() or target.is_symlink():
        raise ValueError("Source and target directories must not be symlinks")
    source = source.resolve(strict=True)
    target = target.resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("Source and writable target must be separate directories")
    manifest, manifest_sha = validate_source(source)
    if target.exists() and not target.is_dir():
        raise ValueError("Demo target must be a directory")
    target.mkdir(parents=True, exist_ok=True)
    marker = target / MARKER
    if marker.exists() or marker.is_symlink():
        regular_file(marker)
        receipt = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            raise ValueError("Invalid installed catalog receipt")
        installed_files = receipt.get("source_files")
        revision = receipt.get("catalog_revision")
        if (receipt.get("schema_version") != 1 or isinstance(receipt.get("schema_version"), bool)
                or not isinstance(revision, int) or isinstance(revision, bool) or revision < 1
                or not isinstance(receipt.get("source_manifest_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", receipt["source_manifest_sha256"])
                or not isinstance(installed_files, dict)
                or not set(REQUIRED_FILES).issubset(installed_files)
                or not set(installed_files).issubset(FILES)
                or any(not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha)
                       for sha in installed_files.values())):
            raise ValueError("Invalid installed catalog provenance")
        for name in installed_files:
            regular_file(target / name)
        # User/admin changes, WALs and new private stores are deliberately untouched.
        # The receipt describes the FIRST installation, not the current package
        # or subsequent reviewed admin updates. A valid new shipped source must
        # never turn normal startup into an implicit catalog replacement.
        expected = {name: manifest["files"][name]["sha256"] for name in manifest["files"]}
        if receipt["source_manifest_sha256"] != manifest_sha or installed_files != expected:
            return ("Existing demo preserved (no files copied); shipped source differs from the initial installation. "
                    "To update catalog data, use the authenticated admin review/apply/publish workflow")
        return "Existing demo preserved (no files copied)"
    if any(target.iterdir()):
        raise ValueError("Refusing a nonempty target without a completed demo installation")
    lock = target / LOCK
    created: list[Path] = []
    # A competing installer cannot overwrite anything, including a partial first copy.
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        if any(path != lock for path in target.iterdir()):
            raise ValueError("Target changed during first installation")
        for name in manifest["files"]:
            destination = target / name
            with destination.open("xb") as output:
                created.append(destination)
                copy_database(source, name, manifest["files"][name], output)
                output.flush()
                os.fsync(output.fileno())
            if digest(destination) != manifest["files"][name]["sha256"]:
                raise ValueError(f"Copied hash mismatch: {name}")
        # Detect a source mutation during the copy before certifying the installation.
        if digest(source / "manifest.json") != manifest_sha or any(digest(stored_path(source, n, manifest["files"][n])) != manifest["files"][n].get("archive_sha256", manifest["files"][n]["sha256"]) for n in manifest["files"]):
            raise ValueError("Source changed during installation")
        with marker.open("x", encoding="utf-8") as output:
            created.append(marker)
            json.dump({"schema_version": 1, "catalog_revision": manifest["catalog_revision"],
                       "source_manifest_sha256": manifest_sha,
                       "source_files": {name: manifest["files"][name]["sha256"] for name in manifest["files"]}}, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    finally:
        lock.unlink(missing_ok=True)
    return "Sanitized catalog/fuel and any declared external-hotdeal snapshots installed; private account stores are not shipped"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--check-only", action="store_true", help="Validate shipped files without installing (gzip validation uses temporary files)")
    args = parser.parse_args()
    try:
        if args.check_only:
            validate_source(args.source.resolve(strict=True))
            print("Shipped catalog manifest, hashes, schema, counts and foreign keys verified")
        else:
            if args.target is None:
                parser.error("--target is required unless --check-only")
            print(install(args.source, args.target))
        return 0
    except (OSError, EOFError, zlib.error, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        print(f"Demo catalog installation refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
