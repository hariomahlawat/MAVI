#!/usr/bin/env python3
"""Assemble CPU+CUDA variant evidence into one OS offline-install gate package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class AssembleError(ValueError):
    pass


def load(path: Path) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    value = json.loads(data)
    if not isinstance(value, dict):
        raise AssembleError("offline_variant_evidence_invalid")
    return value, hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--os", choices=("windows", "linux"), required=True)
    parser.add_argument("--cpu", type=Path, required=True)
    parser.add_argument("--cuda", type=Path, required=True)
    parser.add_argument("--isolation-method", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise AssembleError("offline_output_exists")
        cpu, cpu_sha = load(args.cpu)
        cuda, cuda_sha = load(args.cuda)
        expected = {
            f"{args.os}-x86_64-cpu": cpu,
            f"{args.os}-x86_64-cuda": cuda,
        }
        commits = {item.get("sourceCommit") for item in expected.values()}
        modes = {item.get("bundleMode") for item in expected.values()}
        targets = {item.get("targetVerifiedManifestSha256") for item in expected.values()}
        profiles = {item.get("acceptanceProfileSha256") for item in expected.values()}
        if len(commits) != 1 or None in commits:
            raise AssembleError("offline_source_commit_mismatch")
        if len(modes) != 1 or None in modes:
            raise AssembleError("offline_bundle_mode_mismatch")
        if len(targets) != 1 or None in targets:
            raise AssembleError("offline_target_manifest_mismatch")
        if len(profiles) != 1 or None in profiles:
            raise AssembleError("offline_acceptance_profile_mismatch")
        for variant, item in expected.items():
            if item.get("schemaVersion") != "mavi-offline-variant-evidence-v1":
                raise AssembleError("offline_variant_schema_invalid")
            if item.get("variant") != variant or item.get("result") != "passed":
                raise AssembleError("offline_variant_not_passed")
        variants = []
        for variant, item in expected.items():
            variants.append({
                "variant": variant,
                "bundleManifestSha256": item["bundleManifestSha256"],
                "releaseLockSha256": item["releaseLockSha256"],
                "expectedHostCompatibility": item["expectedHostCompatibility"],
                "observedHostCompatibility": item["observedHostCompatibility"],
                "installCommand": item["installCommand"],
                "installExitCode": item["installExitCode"],
                "pipCheckPassed": item["pipCheckPassed"],
                "runtimeStarted": item["runtimeStarted"],
                "realInferencePassed": item["realInferencePassed"],
                "workerFlowPassed": item["workerFlowPassed"],
                "actualDevice": item["actualDevice"],
                "outboundNetworkUnavailable": item["outboundNetworkUnavailable"],
                "networkIsolation": item["networkIsolation"],
                "firstRunDownloadObserved": item["firstRunDownloadObserved"],
                "result": item["result"],
            })
        value = {
            "schemaVersion": "mavi-offline-install-evidence-v1",
            "sourceCommit": next(iter(commits)),
            "targetVerifiedManifestSha256": next(iter(targets)),
            "acceptanceProfileSha256": next(iter(profiles)),
            "os": args.os,
            "bundleMode": next(iter(modes)),
            "isolationMethod": args.isolation_method,
            "variants": variants,
            "result": "passed",
        }
        args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    except (AssembleError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
