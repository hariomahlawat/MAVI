#!/usr/bin/env python3
"""Compute the exact intended verified model-manifest bytes/hash without promoting them."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class TargetManifestError(ValueError):
    pass


def canonical_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build_target_manifest(candidate: dict[str, Any], qualification_id: str) -> bytes:
    if candidate.get("verificationStatus") != "unverified":
        raise TargetManifestError("target_manifest_candidate_not_unverified")
    if candidate.get("qualificationId") is not None:
        raise TargetManifestError("target_manifest_candidate_qualification_unexpected")
    if not qualification_id or qualification_id != qualification_id.strip():
        raise TargetManifestError("target_manifest_qualification_id_invalid")
    target = dict(candidate)
    target["verificationStatus"] = "verified"
    target["qualificationId"] = qualification_id
    return canonical_json(target)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--qualification-id", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        candidate = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(candidate, dict):
            raise TargetManifestError("target_manifest_json_invalid")
        payload = build_target_manifest(candidate, args.qualification_id)
        digest = sha256_bytes(payload)
        if args.output:
            output = Path(args.output)
            if output.exists():
                raise TargetManifestError("target_manifest_output_exists")
            output.write_bytes(payload)
    except (OSError, json.JSONDecodeError, TargetManifestError) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "targetVerifiedManifestSha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
