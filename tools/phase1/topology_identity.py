#!/usr/bin/env python3
"""Stable topology identities for Task-17 production acceptance."""

from __future__ import annotations

import hashlib
import platform
import subprocess
from pathlib import Path


class TopologyIdentityError(ValueError):
    pass


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _run_text(arguments: list[str]) -> str:
    completed = subprocess.run(arguments, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise TopologyIdentityError("topology_identity_command_failed:" + arguments[0])
    return completed.stdout.strip()


def host_identity_sha256() -> str:
    system = platform.system()
    hostname = platform.node().strip().lower()
    if not hostname:
        raise TopologyIdentityError("topology_hostname_missing")

    if system == "Linux":
        try:
            machine_id = Path("/etc/machine-id").read_text(encoding="utf-8").strip().lower()
        except OSError as exc:
            raise TopologyIdentityError("topology_linux_machine_id_missing") from exc
        if not machine_id:
            raise TopologyIdentityError("topology_linux_machine_id_missing")
        return _sha256_text(f"linux|{hostname}|{machine_id}")

    if system == "Windows":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            ) as key:
                machine_guid = str(
                    winreg.QueryValueEx(key, "MachineGuid")[0]
                ).strip().lower()
        except (OSError, ImportError) as exc:
            raise TopologyIdentityError(
                "topology_windows_machine_guid_missing"
            ) from exc
        if not machine_guid:
            raise TopologyIdentityError("topology_windows_machine_guid_missing")
        return _sha256_text(f"windows|{hostname}|{machine_guid}")

    raise TopologyIdentityError("topology_unsupported_host:" + system)


def storage_root_identity_sha256(path: Path) -> str:
    try:
        canonical = str(path.resolve(strict=True))
    except OSError as exc:
        raise TopologyIdentityError("topology_storage_root_missing") from exc
    system = platform.system()
    if system == "Windows":
        canonical = canonical.lower()
        family = "windows"
    else:
        family = "posix"
    return _sha256_text(f"mavi-storage-root-v1|{family}|{canonical.rstrip('/\\')}")


def database_identity(psql: str, service: str) -> str:
    sql = (
        "select current_database() || '|' || "
        "coalesce(inet_server_addr()::text, 'local-socket') || '|' || "
        "coalesce(inet_server_port()::text, 'local');"
    )
    completed = subprocess.run(
        [psql, f"service={service}", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", sql],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise TopologyIdentityError("topology_database_identity_failed")
    value = completed.stdout.strip()
    if not value or value.count("|") != 2:
        raise TopologyIdentityError("topology_database_identity_invalid")
    return value
