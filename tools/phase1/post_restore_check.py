#!/usr/bin/env python3
"""Bind post-restore product verification to the exact Task-17 backup execution."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

STATE_PATH = Path(__file__).with_name("verify_authoritative_state.py")
SPEC = importlib.util.spec_from_file_location("mavi_phase1_state_restore", STATE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("task17_state_import_failed")
state = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = state
SPEC.loader.exec_module(state)


class RestoreCheckError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--acceptance-evidence", type=Path, required=True)
    parser.add_argument("--execution-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise RestoreCheckError("restore_check_output_exists")
        execution_bytes = args.execution_evidence.read_bytes()
        execution = json.loads(execution_bytes)
        if (
            not isinstance(execution, dict)
            or execution.get("schemaVersion") != "mavi-backup-restore-execution-v1"
            or execution.get("result") != "restore-complete"
        ):
            raise RestoreCheckError("restore_execution_evidence_invalid")
        acceptance_sha = sha256_file(args.acceptance_evidence)
        if execution.get("acceptanceEvidenceSha256") != acceptance_sha:
            raise RestoreCheckError("restore_acceptance_execution_mismatch")

        accepted = json.loads(args.acceptance_evidence.read_text(encoding="utf-8"))
        if accepted.get("sourceCommit") != execution.get("sourceCommit"):
            raise RestoreCheckError("restore_source_commit_mismatch")

        checked = state.check_state(
            base_url=args.base_url,
            acceptance_evidence=args.acceptance_evidence,
            expected_application_commit=execution["sourceCommit"],
        )
        result = {
            "schemaVersion": "mavi-post-restore-check-v1",
            "sourceCommit": execution["sourceCommit"],
            "acceptanceEvidenceSha256": acceptance_sha,
            "executionEvidenceSha256": hashlib.sha256(execution_bytes).hexdigest(),
            "backupManifestSha256": execution["backupManifestSha256"],
            "databaseManifestSha256": execution["database"]["manifestSha256"],
            "managedSourceManifestSha256": execution["managedSource"]["manifestSha256"],
            "acceptedEvidenceManifestSha256": execution["acceptedEvidence"]["manifestSha256"],
            "stateCheck": checked,
            "result": {"passed": True, "failureCodes": []},
        }
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (
        OSError,
        json.JSONDecodeError,
        state.e2e.AcceptanceError,
        state.StateCheckError,
        RestoreCheckError,
    ) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps({"ok": True, "sha256": sha256_file(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
