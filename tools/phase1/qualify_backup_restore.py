#!/usr/bin/env python3
"""Execute and finalize Task-17 offline backup/restore qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from typing import Any

PHASE1_ROOT = Path(__file__).resolve().parent
if str(PHASE1_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE1_ROOT))

import verify_phase1_evidence as evidence_verifier  # noqa: E402
from policy_identity import PolicyIdentityError, canonical_acceptance_profile  # noqa: E402
from topology_identity import (  # noqa: E402
    TopologyIdentityError,
    storage_root_identity_sha256,
)


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


def pg_scalar(psql: str, service: str, sql: str) -> str:
    completed = subprocess.run(
        [psql, f"service={service}", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", sql],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise BackupRestoreError("backup_restore_psql_failed")
    return completed.stdout.strip()


def fetch_live_storage_topology(base_url: str) -> dict[str, Any]:
    request = Request(
        urljoin(base_url.rstrip("/") + "/", "api/system/storage-topology"),
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise BackupRestoreError("backup_restore_storage_topology_http_failed")
            value = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise BackupRestoreError("backup_restore_storage_topology_unavailable") from exc
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != "mavi-storage-topology-attestation-v1"
        or not isinstance(value.get("databaseIdentity"), str)
        or not isinstance(value.get("managedMediaRootIdentitySha256"), str)
        or not isinstance(value.get("acceptedEvidenceRootIdentitySha256"), str)
        or not isinstance(value.get("maviBuild"), str)
        or not isinstance(value.get("maviCommit"), str)
    ):
        raise BackupRestoreError("backup_restore_storage_topology_invalid")
    return value


def validate_live_storage_topology(
    live: dict[str, Any],
    *,
    source_commit: str,
    expected_mavi_build: str,
    source_database_identity: str,
    source_media_root: Path,
    source_evidence_root: Path,
) -> dict[str, Any]:
    media_identity = storage_root_identity_sha256(source_media_root)
    evidence_identity = storage_root_identity_sha256(source_evidence_root)
    if (
        live.get("maviCommit") != source_commit
        or live.get("maviBuild") != expected_mavi_build
        or live.get("databaseIdentity") != source_database_identity
        or live.get("managedMediaRootIdentitySha256") != media_identity
        or live.get("acceptedEvidenceRootIdentitySha256") != evidence_identity
    ):
        raise BackupRestoreError("backup_restore_live_storage_topology_mismatch")
    return {
        "schemaVersion": "mavi-storage-topology-attestation-v1",
        "maviBuild": expected_mavi_build,
        "maviCommit": source_commit,
        "databaseIdentity": source_database_identity,
        "managedMediaRootIdentitySha256": media_identity,
        "acceptedEvidenceRootIdentitySha256": evidence_identity,
    }


def database_identity(psql: str, service: str) -> str:
    value = pg_scalar(
        psql,
        service,
        "select current_database() || '|' || "
        "coalesce(inet_server_addr()::text, 'local-socket') || '|' || "
        "coalesce(inet_server_port()::text, 'local');",
    )
    if not value or value.count("|") != 2:
        raise BackupRestoreError("backup_restore_database_identity_invalid")
    return value


def assert_database_targets_distinct(source_identity: str, restore_identity: str) -> None:
    if source_identity == restore_identity:
        raise BackupRestoreError("backup_restore_database_targets_not_distinct")


def assert_restore_database_clean(psql: str, service: str) -> None:
    value = pg_scalar(
        psql,
        service,
        "select count(*)::text from information_schema.tables "
        "where table_schema = 'public' and table_type = 'BASE TABLE';",
    )
    try:
        count = int(value)
    except ValueError as exc:
        raise BackupRestoreError("backup_restore_database_cleanliness_invalid") from exc
    if count != 0:
        raise BackupRestoreError("restore_database_not_clean")


def _resolved(path: Path) -> Path:
    return path.resolve(strict=False)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _assert_disjoint_roots(paths: list[Path]) -> None:
    resolved = [_resolved(path) for path in paths]
    for index, first in enumerate(resolved):
        for second in resolved[index + 1:]:
            if first == second:
                raise BackupRestoreError("backup_restore_roots_not_distinct")
            if _is_relative_to(first, second) or _is_relative_to(second, first):
                raise BackupRestoreError("backup_restore_roots_nested")


def execute(args: argparse.Namespace) -> dict[str, Any]:
    acceptance_bytes = args.acceptance_evidence.read_bytes()
    try:
        acceptance = json.loads(acceptance_bytes)
    except json.JSONDecodeError as exc:
        raise BackupRestoreError("backup_restore_acceptance_evidence_invalid") from exc
    if not isinstance(acceptance, dict):
        raise BackupRestoreError("backup_restore_acceptance_evidence_invalid")
    _, acceptance_profile_sha = canonical_acceptance_profile(args.acceptance_profile)
    try:
        evidence_verifier._validate_schema(
            acceptance,
            PHASE1_ROOT / "phase1-acceptance-evidence.schema.json",
        )
        evidence_verifier.verify_acceptance(
            acceptance,
            expected_source_commit=args.source_commit,
            expected_acceptance_profile_sha256=acceptance_profile_sha,
        )
    except evidence_verifier.EvidenceError as exc:
        raise BackupRestoreError(
            "backup_restore_acceptance_evidence_invalid:" + exc.code
        ) from exc
    acceptance_sha = hashlib.sha256(acceptance_bytes).hexdigest()

    source_database_identity = database_identity(args.psql, args.source_pg_service)
    restore_database_identity = database_identity(args.psql, args.restore_pg_service)
    assert_database_targets_distinct(source_database_identity, restore_database_identity)
    live_storage_topology = validate_live_storage_topology(
        fetch_live_storage_topology(args.base_url),
        source_commit=args.source_commit,
        expected_mavi_build=args.expected_mavi_build,
        source_database_identity=source_database_identity,
        source_media_root=args.source_media_root,
        source_evidence_root=args.source_evidence_root,
    )
    assert_restore_database_clean(args.psql, args.restore_pg_service)

    _assert_disjoint_roots([
        args.source_media_root,
        args.source_evidence_root,
        args.restore_media_root,
        args.restore_evidence_root,
        args.backup_dir,
    ])

    source_media_manifest = safe_tree_manifest(args.source_media_root)
    source_evidence_manifest = safe_tree_manifest(args.source_evidence_root)

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
    if media_manifest["files"] != source_media_manifest["files"]:
        raise BackupRestoreError("managed_source_backup_integrity_failed")
    media_manifest_sha = write_manifest(media_dir / "manifest.json", media_manifest)
    evidence_manifest = safe_tree_manifest(evidence_dir)
    if evidence_manifest["files"] != source_evidence_manifest["files"]:
        raise BackupRestoreError("accepted_evidence_backup_integrity_failed")
    evidence_manifest_sha = write_manifest(evidence_dir / "manifest.json", evidence_manifest)

    backup_manifest = {
        "schemaVersion": "mavi-backup-set-v1",
        "sourceCommit": args.source_commit,
        "acceptanceEvidenceSha256": acceptance_sha,
        "acceptanceProfileSha256": acceptance_profile_sha,
        "sourceDatabaseIdentity": source_database_identity,
        "restoreDatabaseIdentity": restore_database_identity,
        "liveStorageTopology": live_storage_topology,
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

    restore_storage_topology = {
        "schemaVersion": "mavi-storage-topology-attestation-v1",
        "maviBuild": args.expected_mavi_build,
        "maviCommit": args.source_commit,
        "databaseIdentity": restore_database_identity,
        "managedMediaRootIdentitySha256": storage_root_identity_sha256(args.restore_media_root),
        "acceptedEvidenceRootIdentitySha256": storage_root_identity_sha256(args.restore_evidence_root),
    }

    return {
        "schemaVersion": "mavi-backup-restore-execution-v1",
        "sourceCommit": args.source_commit,
        "acceptanceEvidenceSha256": acceptance_sha,
        "acceptanceProfileSha256": acceptance_profile_sha,
        "sourceDatabaseIdentity": source_database_identity,
        "restoreDatabaseIdentity": restore_database_identity,
        "liveStorageTopology": live_storage_topology,
        "restoreStorageTopology": restore_storage_topology,
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
    if post.get("executionEvidenceSha256") != hashlib.sha256(execution_bytes).hexdigest():
        raise BackupRestoreError("post_restore_execution_binding_mismatch")
    if post.get("acceptanceEvidenceSha256") != execution.get("acceptanceEvidenceSha256"):
        raise BackupRestoreError("post_restore_acceptance_binding_mismatch")
    if post.get("backupManifestSha256") != execution.get("backupManifestSha256"):
        raise BackupRestoreError("post_restore_backup_binding_mismatch")
    if post.get("databaseManifestSha256") != execution.get("database", {}).get("manifestSha256"):
        raise BackupRestoreError("post_restore_database_binding_mismatch")
    if post.get("managedSourceManifestSha256") != execution.get("managedSource", {}).get("manifestSha256"):
        raise BackupRestoreError("post_restore_source_store_binding_mismatch")
    if post.get("acceptedEvidenceManifestSha256") != execution.get("acceptedEvidence", {}).get("manifestSha256"):
        raise BackupRestoreError("post_restore_evidence_store_binding_mismatch")
    if post.get("restoreStorageTopology") != execution.get("restoreStorageTopology"):
        raise BackupRestoreError("post_restore_topology_binding_mismatch")
    state_check = post.get("stateCheck")
    if (
        not isinstance(state_check, dict)
        or state_check.get("schemaVersion") != "mavi-authoritative-state-check-v1"
        or state_check.get("acceptanceEvidenceSha256") != execution.get("acceptanceEvidenceSha256")
        or state_check.get("expectedApplicationCommit") != execution.get("sourceCommit")
        or state_check.get("observedApplicationCommit") != execution.get("sourceCommit")
        or state_check.get("result", {}).get("passed") is not True
        or state_check.get("result", {}).get("failureCodes") != []
    ):
        raise BackupRestoreError("post_restore_state_check_binding_mismatch")

    return {
        "schemaVersion": "mavi-backup-restore-evidence-v1",
        "sourceCommit": execution["sourceCommit"],
        "acceptanceEvidenceSha256": execution["acceptanceEvidenceSha256"],
        "acceptanceProfileSha256": execution["acceptanceProfileSha256"],
        "executionEvidenceSha256": hashlib.sha256(execution_bytes).hexdigest(),
        "sourceDatabaseIdentity": execution["sourceDatabaseIdentity"],
        "restoreDatabaseIdentity": execution["restoreDatabaseIdentity"],
        "liveStorageTopology": execution["liveStorageTopology"],
        "restoreStorageTopology": execution["restoreStorageTopology"],
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
    execute_parser.add_argument("--expected-mavi-build", required=True)
    execute_parser.add_argument("--base-url", required=True)
    execute_parser.add_argument("--acceptance-evidence", type=Path, required=True)
    execute_parser.add_argument("--acceptance-profile", type=Path, required=True)
    execute_parser.add_argument("--source-pg-service", required=True)
    execute_parser.add_argument("--restore-pg-service", required=True)
    execute_parser.add_argument("--source-media-root", type=Path, required=True)
    execute_parser.add_argument("--source-evidence-root", type=Path, required=True)
    execute_parser.add_argument("--restore-media-root", type=Path, required=True)
    execute_parser.add_argument("--restore-evidence-root", type=Path, required=True)
    execute_parser.add_argument("--backup-dir", type=Path, required=True)
    execute_parser.add_argument("--psql", default="psql")
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
    except (
        BackupRestoreError,
        OSError,
        json.JSONDecodeError,
        PolicyIdentityError,
        TopologyIdentityError,
    ) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps({"ok": True, "sha256": sha256_file(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
