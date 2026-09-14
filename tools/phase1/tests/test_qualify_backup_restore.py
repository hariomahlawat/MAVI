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


def test_finalize_requires_matching_source_commit(tmp_path: Path):
    execution = tmp_path / "execution.json"
    execution.write_text(json.dumps({
        "schemaVersion": "mavi-backup-restore-execution-v1",
        "sourceCommit": "a" * 40,
        "database": {"included": True, "manifestSha256": "1" * 64},
        "managedSource": {"included": True, "manifestSha256": "2" * 64},
        "acceptedEvidence": {"included": True, "manifestSha256": "3" * 64},
        "backupManifestSha256": "4" * 64,
        "cleanRestoreTarget": True,
        "result": "restore-complete",
    }), encoding="utf-8")
    post = tmp_path / "post.json"
    post.write_text(json.dumps({
        "schemaVersion": "mavi-post-restore-check-v1",
        "sourceCommit": "b" * 40,
        "result": {"passed": True, "failureCodes": []},
    }), encoding="utf-8")
    with pytest.raises(mod.BackupRestoreError, match="post_restore_source_commit_mismatch"):
        mod.finalize(execution, post)
