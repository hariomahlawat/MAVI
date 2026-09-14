#!/usr/bin/env python3
"""Reproducible identity for the exact Task-17 Python virtual environment."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


class EnvironmentFingerprintError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(python: Path) -> dict[str, str]:
    if not python.is_file():
        raise EnvironmentFingerprintError("worker_python_missing")

    script = r'''
import base64, hashlib, importlib.metadata as md, json, pathlib, sys, sysconfig

def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

prefix = pathlib.Path(sys.prefix).resolve()
cfg = prefix / "pyvenv.cfg"
if not cfg.is_file():
    raise SystemExit(3)

recorded = set()
records = []
for dist in md.distributions():
    name = (dist.metadata.get("Name") or "").strip().lower()
    version = str(dist.version)
    files = []
    for item in sorted((dist.files or []), key=lambda p: str(p)):
        target = pathlib.Path(dist.locate_file(item)).resolve()
        logical = str(item).replace("\\", "/")
        if not target.is_file():
            raise SystemExit(4)
        actual_sha = file_sha256(target)
        actual_size = target.stat().st_size
        if item.hash is not None:
            if item.hash.mode != "sha256":
                raise SystemExit(5)
            expected = item.hash.value.rstrip("=")
            actual_b64 = base64.urlsafe_b64encode(
                bytes.fromhex(actual_sha)
            ).decode("ascii").rstrip("=")
            if actual_b64 != expected:
                raise SystemExit(6)
        if item.size is not None and actual_size != item.size:
            raise SystemExit(7)
        recorded.add(str(target))
        files.append({
            "path": logical,
            "sizeBytes": actual_size,
            "sha256": actual_sha,
        })
    records.append({"name": name, "version": version, "files": files})
records.sort(key=lambda x: (x["name"], x["version"]))

site_roots = []
for key in ("purelib", "platlib"):
    raw = sysconfig.get_paths().get(key)
    if raw:
        root = pathlib.Path(raw).resolve()
        if root.exists() and str(root) not in {str(item) for item in site_roots}:
            site_roots.append(root)

site_files = []
for root in sorted(site_roots, key=lambda p: str(p)):
    for target in sorted(root.rglob("*"), key=lambda p: str(p)):
        if not target.is_file():
            continue
        resolved = target.resolve()
        relative = resolved.relative_to(root).as_posix()
        site_files.append({
            "root": str(root),
            "path": relative,
            "sizeBytes": resolved.stat().st_size,
            "sha256": file_sha256(resolved),
            "recorded": str(resolved) in recorded,
        })

print(json.dumps({
    "venvRoot": str(prefix),
    "pyvenvCfgSha256": file_sha256(cfg),
    "resolvedPython": str(pathlib.Path(sys.executable).resolve()),
    "distributions": records,
    "sitePackagesFiles": site_files,
}, sort_keys=True, separators=(",", ":")))
'''
    completed = subprocess.run(
        [str(python), "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        codes = {
            3: "worker_pyvenv_cfg_missing",
            4: "worker_distribution_file_missing",
            5: "worker_distribution_record_hash_unsupported",
            6: "worker_distribution_record_hash_mismatch",
            7: "worker_distribution_record_size_mismatch",
        }
        raise EnvironmentFingerprintError(
            codes.get(completed.returncode, "worker_environment_introspection_failed")
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise EnvironmentFingerprintError("worker_environment_introspection_invalid") from exc

    resolved_python = Path(value["resolvedPython"])
    if not resolved_python.is_file():
        raise EnvironmentFingerprintError("worker_resolved_python_missing")
    value["resolvedPythonSha256"] = sha256_file(resolved_python)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "workerEnvironmentSha256": hashlib.sha256(canonical).hexdigest(),
        "workerVenvRootSha256": hashlib.sha256(value["venvRoot"].encode("utf-8")).hexdigest(),
        "workerResolvedPythonSha256": value["resolvedPythonSha256"],
    }
