#!/usr/bin/env python3
"""Execute and finalize Task-17 offline backup/restore qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


class BackupRestoreError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def safe_tree_manifest(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        raise BackupRestoreError("backup_store_root_missing")
    root = root.resolve(strict=True)
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise BackupRestoreError("backup_store_link_forbidden")
        if not path.is_file():
            continue
        resolved = path.resolve(strict=True)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise BackupRestoreError("backup_store_path_escape") from exc
        files.append({
            "relativePath": relative,
            "sizeBytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return {
        "schemaVersion": "mavi-backup-store-manifest-v1",
        "files": files,
    }


def write_manifest(path: Path, value: dict[str, Any]) -> str:
    path.write_bytes(canonical_bytes(value))
    return sha256_file(path)


def ensure_clean_directory(path: Path) -> None:
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise BackupRestoreError("restore_target_not_clean")
    else:
        path.mkdir(parents=True)


def run_checked(args: list[str]) -> str:
    completed = subprocess.run(args, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise BackupRestoreError("backup_restore_command_failed:" + Path(args[0]).name)
    return completed.stdout.strip() or completed.stderr.strip()


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.backup_dir.exists():
        if not args.backup_dir.is_dir() or any(args.backup_dir.iterdir()):
            raise BackupRestoreError("backup_destination_not_clean")
    else:
        args.backup_dir.mkdir(parents=True)

    ensure_clean_directory(args.restore_media_root)
    ensure_clean_directory(args.restore_evidence_root)

    database_dir = args.backup_dir / "database"
    media_dir = args.backup_dir / "managed-source"
    evidence_dir = args.backup_dir / "accepted-evidence"
    database_dir.mkdir()
    database_dump = database_dir / "postgres.dump"

    pg_dump_version = run_checked([args.pg_dump, "--version"])
    pg_restore_version = run_checked([args.pg_restore, "--version"])
    run_checked([
        args.pg_dump,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(database_dump),
        f"service={args.source_pg_service}",
    ])
    if not database_dump.is_file() or database_dump.stat().st_size == 0:
        raise BackupRestoreError("database_backup_empty")

    shutil.copytree(args.source_media_root, media_dir, dirs_exist_ok=False, symlinks=False)
    shutil.copytree(args.source_evidence_root, evidence_dir, dirs_exist_ok=False, symlinks=False)

    database_manifest = {
        "schemaVersion": "mavi-backup-database-manifest-v1",
        "files": [{
            "relativePath": "postgres.dump",
            "sizeBytes": database_dump.stat().st_size,
            "sha256": sha256_file(database_dump),
        }],
    }
    database_manifest_sha = write_manifest(database_dir / "manifest.json", database_manifest)
    media_manifest = safe_tree_manifest(media_dir)
    media_manifest_sha = write_manifest(media_dir / "manifest.json", media_manifest)
    evidence_manifest = safe_tree_manifest(evidence_dir)
    evidence_manifest_sha = write_manifest(evidence_dir / "manifest.json", evidence_manifest)

    backup_manifest = {
        "schemaVersion": "mavi-backup-set-v1",
        "sourceCommit": args.source_commit,
        "databaseManifestSha256": database_manifest_sha,
        "managedSourceManifestSha256": media_manifest_sha,
        "acceptedEvidenceManifestSha256": evidence_manifest_sha,
        "pgDumpVersion": pg_dump_version,
        "pgRestoreVersion": pg_restore_version,
    }
    backup_manifest_sha = write_manifest(args.backup_dir / "backup-manifest.json", backup_manifest)

    run_checked([
        args.pg_restore,
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        f"service={args.restore_pg_service}",
        str(database_dump),
    ])

    shutil.copytree(media_dir, args.restore_media_root, dirs_exist_ok=True, symlinks=False)
    shutil.copytree(evidence_dir, args.restore_evidence_root, dirs_exist_ok=True, symlinks=False)
    # Backup package metadata belongs only to the backup set, not restored stores.
    for restored in (
        args.restore_media_root / "manifest.json",
        args.restore_evidence_root / "manifest.json",
    ):
        restored.unlink()

    if safe_tree_manifest(args.restore_media_root)["files"] != media_manifest["files"]:
        raise BackupRestoreError("managed_source_restore_integrity_failed")
    if safe_tree_manifest(args.restore_evidence_root)["files"] != evidence_manifest["files"]:
        raise BackupRestoreError("accepted_evidence_restore_integrity_failed")

    return {
        "schemaVersion": "mavi-backup-restore-execution-v1",
        "sourceCommit": args.source_commit,
        "database": {"included": True, "manifestSha256": database_manifest_sha},
        "managedSource": {"included": True, "manifestSha256": media_manifest_sha},
        "acceptedEvidence": {"included": True, "manifestSha256": evidence_manifest_sha},
        "backupManifestSha256": backup_manifest_sha,
        "cleanRestoreTarget": True,
        "result": "restore-complete",
    }


def finalize(execution_path: Path, post_restore_path: Path) -> dict[str, Any]:
    execution_bytes = execution_path.read_bytes()
    post_bytes = post_restore_path.read_bytes()
    execution = json.loads(execution_bytes)
    post = json.loads(post_bytes)
    if execution.get("schemaVersion") != "mavi-backup-restore-execution-v1":
        raise BackupRestoreError("backup_restore_execution_invalid")
    if execution.get("result") != "restore-complete":
        raise BackupRestoreError("backup_restore_execution_not_complete")
    if post.get("schemaVersion") != "mavi-post-restore-check-v1":
        raise BackupRestoreError("post_restore_check_invalid")
    if post.get("result", {}).get("passed") is not True:
        raise BackupRestoreError("post_restore_check_not_passed")
    if post.get("sourceCommit") != execution.get("sourceCommit"):
        raise BackupRestoreError("post_restore_source_commit_mismatch")

    return {
        "schemaVersion": "mavi-backup-restore-evidence-v1",
        "sourceCommit": execution["sourceCommit"],
        "database": execution["database"],
        "managedSource": execution["managedSource"],
        "acceptedEvidence": execution["acceptedEvidence"],
        "backupManifestSha256": execution["backupManifestSha256"],
        "cleanRestoreTarget": execution["cleanRestoreTarget"],
        "postRestoreCheckSha256": hashlib.sha256(post_bytes).hexdigest(),
        "result": {"passed": True, "failureCodes": []},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    execute_parser = sub.add_parser("execute")
    execute_parser.add_argument("--source-commit", required=True)
    execute_parser.add_argument("--source-pg-service", required=True)
    execute_parser.add_argument("--restore-pg-service", required=True)
    execute_parser.add_argument("--source-media-root", type=Path, required=True)
    execute_parser.add_argument("--source-evidence-root", type=Path, required=True)
    execute_parser.add_argument("--restore-media-root", type=Path, required=True)
    execute_parser.add_argument("--restore-evidence-root", type=Path, required=True)
    execute_parser.add_argument("--backup-dir", type=Path, required=True)
    execute_parser.add_argument("--pg-dump", default="pg_dump")
    execute_parser.add_argument("--pg-restore", default="pg_restore")
    execute_parser.add_argument("--output", type=Path, required=True)

    finalize_parser = sub.add_parser("finalize")
    finalize_parser.add_argument("--execution", type=Path, required=True)
    finalize_parser.add_argument("--post-restore-check", type=Path, required=True)
    finalize_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise BackupRestoreError("backup_restore_output_exists")
        if args.command == "execute":
            value = execute(args)
        else:
            value = finalize(args.execution, args.post_restore_check)
        args.output.write_bytes(canonical_bytes(value))
    except (BackupRestoreError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps({"ok": True, "sha256": sha256_file(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
