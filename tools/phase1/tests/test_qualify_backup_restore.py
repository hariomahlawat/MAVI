from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "qualify_backup_restore.py"
SPEC = importlib.util.spec_from_file_location("backup_restore", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)

POST_RESTORE_PATH = Path(__file__).resolve().parents[1] / "post_restore_check.py"
POST_RESTORE_SPEC = importlib.util.spec_from_file_location("post_restore_check_tests", POST_RESTORE_PATH)
assert POST_RESTORE_SPEC and POST_RESTORE_SPEC.loader
post_restore = importlib.util.module_from_spec(POST_RESTORE_SPEC)
sys.modules[POST_RESTORE_SPEC.name] = post_restore
POST_RESTORE_SPEC.loader.exec_module(post_restore)



def test_tree_manifest_rejects_links(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_text("x", encoding="utf-8")
    link = root / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink unavailable")
    with pytest.raises(mod.BackupRestoreError, match="backup_store_link_forbidden"):
        mod.safe_tree_manifest(root)


def _execution_payload():
    return {
        "schemaVersion": "mavi-backup-restore-execution-v1",
        "sourceCommit": "a" * 40,
        "acceptanceEvidenceSha256": "5" * 64,
        "acceptanceProfileSha256": "6" * 64,
        "sourceDatabaseIdentity": "source|127.0.0.1|5432",
        "restoreDatabaseIdentity": "restore|127.0.0.1|5433",
        "liveStorageTopology": {
            "schemaVersion": "mavi-storage-topology-attestation-v1",
            "maviBuild": "build-a",
            "maviCommit": "a" * 40,
            "databaseIdentity": "source|127.0.0.1|5432",
            "managedMediaRootIdentitySha256": "7" * 64,
            "acceptedEvidenceRootIdentitySha256": "8" * 64,
        },
        "restoreStorageTopology": {
            "schemaVersion": "mavi-storage-topology-attestation-v1",
            "maviBuild": "build-a",
            "maviCommit": "a" * 40,
            "databaseIdentity": "restore|127.0.0.1|5433",
            "managedMediaRootIdentitySha256": "9" * 64,
            "acceptedEvidenceRootIdentitySha256": "a" * 64,
        },
        "database": {"included": True, "manifestSha256": "1" * 64},
        "managedSource": {"included": True, "manifestSha256": "2" * 64},
        "acceptedEvidence": {"included": True, "manifestSha256": "3" * 64},
        "backupManifestSha256": "4" * 64,
        "cleanRestoreTarget": True,
        "result": "restore-complete",
    }


def _post_payload(execution_path: Path, execution: dict):
    return {
        "schemaVersion": "mavi-post-restore-check-v1",
        "sourceCommit": execution["sourceCommit"],
        "acceptanceEvidenceSha256": execution["acceptanceEvidenceSha256"],
        "executionEvidenceSha256": mod.hashlib.sha256(execution_path.read_bytes()).hexdigest(),
        "backupManifestSha256": execution["backupManifestSha256"],
        "databaseManifestSha256": execution["database"]["manifestSha256"],
        "managedSourceManifestSha256": execution["managedSource"]["manifestSha256"],
        "acceptedEvidenceManifestSha256": execution["acceptedEvidence"]["manifestSha256"],
        "restoreStorageTopology": execution["restoreStorageTopology"],
        "result": {"passed": True, "failureCodes": []},
    }


def test_finalize_requires_matching_source_commit(tmp_path: Path):
    execution = tmp_path / "execution.json"
    execution_value = _execution_payload()
    execution.write_text(json.dumps(execution_value), encoding="utf-8")
    post = tmp_path / "post.json"
    post_value = _post_payload(execution, execution_value)
    post_value["sourceCommit"] = "b" * 40
    post.write_text(json.dumps(post_value), encoding="utf-8")
    with pytest.raises(mod.BackupRestoreError, match="post_restore_source_commit_mismatch"):
        mod.finalize(execution, post)


def test_finalize_rejects_evidence_spliced_from_other_execution(tmp_path: Path):
    execution = tmp_path / "execution.json"
    execution_value = _execution_payload()
    execution.write_text(json.dumps(execution_value), encoding="utf-8")
    other = tmp_path / "other.json"
    other_value = dict(execution_value)
    other_value["backupManifestSha256"] = "9" * 64
    other.write_text(json.dumps(other_value), encoding="utf-8")
    post = tmp_path / "post.json"
    post.write_text(json.dumps(_post_payload(other, other_value)), encoding="utf-8")
    with pytest.raises(mod.BackupRestoreError, match="post_restore_execution_binding_mismatch"):
        mod.finalize(execution, post)


def test_database_identity_rejects_same_source_and_restore():
    identity = "mavi|127.0.0.1|5432"
    with pytest.raises(mod.BackupRestoreError, match="backup_restore_database_targets_not_distinct"):
        mod.assert_database_targets_distinct(identity, identity)

def test_disjoint_roots_reject_nested_paths(tmp_path: Path):
    source = tmp_path / "source"
    nested = source / "backup"
    with pytest.raises(mod.BackupRestoreError, match="backup_restore_roots_nested"):
        mod._assert_disjoint_roots([source, nested])


def test_source_tree_manifest_rejects_symlink_before_copy(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("secret", encoding="utf-8")
    link = root / "escape"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink unavailable")
    with pytest.raises(mod.BackupRestoreError, match="backup_store_link_forbidden"):
        mod.safe_tree_manifest(root)


def test_live_storage_topology_rejects_other_database_or_roots(tmp_path: Path):
    media = tmp_path / "media"
    evidence = tmp_path / "evidence"
    media.mkdir()
    evidence.mkdir()
    live = {
        "schemaVersion": "mavi-storage-topology-attestation-v1",
        "maviBuild": "build-a",
        "maviCommit": "a" * 40,
        "databaseIdentity": "other|127.0.0.1|5432",
        "managedMediaRootIdentitySha256": mod.storage_root_identity_sha256(media),
        "acceptedEvidenceRootIdentitySha256": mod.storage_root_identity_sha256(evidence),
    }
    with pytest.raises(
        mod.BackupRestoreError,
        match="backup_restore_live_storage_topology_mismatch",
    ):
        mod.validate_live_storage_topology(
            live,
            source_commit="a" * 40,
            expected_mavi_build="build-a",
            source_database_identity="source|127.0.0.1|5432",
            source_media_root=media,
            source_evidence_root=evidence,
        )


def test_live_storage_topology_accepts_exact_sources(tmp_path: Path):
    media = tmp_path / "media"
    evidence = tmp_path / "evidence"
    media.mkdir()
    evidence.mkdir()
    live = {
        "schemaVersion": "mavi-storage-topology-attestation-v1",
        "maviBuild": "build-a",
        "maviCommit": "a" * 40,
        "databaseIdentity": "source|127.0.0.1|5432",
        "managedMediaRootIdentitySha256": mod.storage_root_identity_sha256(media),
        "acceptedEvidenceRootIdentitySha256": mod.storage_root_identity_sha256(evidence),
    }
    result = mod.validate_live_storage_topology(
        live,
        source_commit="a" * 40,
        expected_mavi_build="build-a",
        source_database_identity="source|127.0.0.1|5432",
        source_media_root=media,
        source_evidence_root=evidence,
    )
    assert result == live


def test_finalize_rejects_post_restore_topology_mismatch(tmp_path: Path):
    execution = tmp_path / "execution.json"
    execution_value = _execution_payload()
    execution.write_text(json.dumps(execution_value), encoding="utf-8")
    post = tmp_path / "post.json"
    post_value = _post_payload(execution, execution_value)
    post_value["restoreStorageTopology"] = dict(post_value["restoreStorageTopology"])
    post_value["restoreStorageTopology"]["databaseIdentity"] = "source|127.0.0.1|5432"
    post.write_text(json.dumps(post_value), encoding="utf-8")
    with pytest.raises(mod.BackupRestoreError, match="post_restore_topology_binding_mismatch"):
        mod.finalize(execution, post)


def test_post_restore_topology_accepts_exact_restored_target():
    expected = _execution_payload()["restoreStorageTopology"]
    result = post_restore.validate_restored_storage_topology(
        dict(expected),
        {"restoreStorageTopology": expected},
    )
    assert result == expected


def test_post_restore_topology_rejects_original_database():
    expected = _execution_payload()["restoreStorageTopology"]
    live = dict(expected)
    live["databaseIdentity"] = "source|127.0.0.1|5432"
    with pytest.raises(post_restore.RestoreCheckError, match="restore_storage_topology_mismatch"):
        post_restore.validate_restored_storage_topology(
            live,
            {"restoreStorageTopology": expected},
        )


def test_post_restore_topology_rejects_wrong_storage_root():
    expected = _execution_payload()["restoreStorageTopology"]
    live = dict(expected)
    live["managedMediaRootIdentitySha256"] = "f" * 64
    with pytest.raises(post_restore.RestoreCheckError, match="restore_storage_topology_mismatch"):
        post_restore.validate_restored_storage_topology(
            live,
            {"restoreStorageTopology": expected},
        )
