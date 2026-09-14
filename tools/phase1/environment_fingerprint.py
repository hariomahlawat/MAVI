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
import hashlib, importlib.metadata as md, json, pathlib, sys
prefix = pathlib.Path(sys.prefix).resolve()
cfg = prefix / "pyvenv.cfg"
if not cfg.is_file():
    raise SystemExit(3)
records = []
for dist in md.distributions():
    name = (dist.metadata.get("Name") or "").strip().lower()
    version = str(dist.version)
    record_hash = None
    record = next((p for p in (dist.files or []) if str(p).endswith(".dist-info/RECORD")), None)
    if record is not None:
        target = pathlib.Path(dist.locate_file(record))
        if target.is_file():
            record_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    records.append({"name": name, "version": version, "recordSha256": record_hash})
records.sort(key=lambda x: (x["name"], x["version"], x["recordSha256"] or ""))
print(json.dumps({
    "venvRoot": str(prefix),
    "pyvenvCfgSha256": hashlib.sha256(cfg.read_bytes()).hexdigest(),
    "resolvedPython": str(pathlib.Path(sys.executable).resolve()),
    "distributions": records,
}, sort_keys=True, separators=(",", ":")))
'''
    completed = subprocess.run(
        [str(python), "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise EnvironmentFingerprintError("worker_environment_introspection_failed")
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
