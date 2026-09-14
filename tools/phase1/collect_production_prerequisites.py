#!/usr/bin/env python3
"""Capture Task-17 production prerequisite identities from the real host/service."""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


class PrerequisiteObservationError(ValueError):
    pass


def run_text(arguments: list[str]) -> str:
    completed = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise PrerequisiteObservationError(
            "prerequisite_command_failed:" + arguments[0]
        )
    return completed.stdout.strip()


def windows_values() -> dict[str, str]:
    if platform.system() != "Windows":
        raise PrerequisiteObservationError("prerequisite_windows_host_required")

    iis_reg = run_text([
        "reg.exe",
        "query",
        r"HKLM\SOFTWARE\Microsoft\InetStp",
        "/v",
        "VersionString",
    ])
    iis_match = re.search(
        r"VersionString\s+REG_SZ\s+(.+)$",
        iis_reg,
        re.MULTILINE,
    )
    if iis_match is None:
        raise PrerequisiteObservationError("prerequisite_iis_version_unavailable")

    windows_reg = run_text([
        "reg.exe",
        "query",
        r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion",
    ])
    def registry_value(name: str) -> str:
        match = re.search(
            rf"^{re.escape(name)}\s+REG_\w+\s+(.+)$",
            windows_reg,
            re.MULTILINE,
        )
        if match is None:
            raise PrerequisiteObservationError(
                "prerequisite_windows_version_unavailable:" + name
            )
        return match.group(1).strip()

    runtimes = run_text(["dotnet", "--list-runtimes"]).splitlines()
    aspnet = []
    for line in runtimes:
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "Microsoft.AspNetCore.App":
            aspnet.append(parts[1])
    if not aspnet:
        raise PrerequisiteObservationError("prerequisite_dotnet_runtime_unavailable")

    def version_key(value: str) -> tuple[int, ...]:
        numbers = re.findall(r"\d+", value)
        return tuple(int(item) for item in numbers)

    return {
        "windowsProductName": registry_value("ProductName"),
        "windowsVersion": registry_value("DisplayVersion"),
        "windowsBuild": registry_value("CurrentBuildNumber"),
        "architecture": platform.machine(),
        "iisVersion": iis_match.group(1).strip(),
        "dotnetRuntimeVersion": max(aspnet, key=version_key),
    }


def database_values(psql: str, pg_service: str) -> dict[str, str]:
    def scalar(sql: str) -> str:
        value = run_text([
            psql,
            f"service={pg_service}",
            "-X",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ])
        if not value:
            raise PrerequisiteObservationError(
                "prerequisite_database_value_missing"
            )
        return value

    return {
        "postgresVersion": scalar("show server_version;"),
        "pgvectorVersion": scalar(
            "select extversion from pg_extension where extname = 'vector';"
        ),
    }


def linux_values() -> dict[str, str]:
    if platform.system() != "Linux":
        raise PrerequisiteObservationError("prerequisite_linux_host_required")

    os_release: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(
            encoding="utf-8"
        ).splitlines():
            if "=" not in line:
                continue
            key, raw = line.split("=", 1)
            os_release[key] = raw.strip().strip('"')
    except OSError as exc:
        raise PrerequisiteObservationError(
            "prerequisite_linux_release_unavailable"
        ) from exc

    driver_lines = [
        item.strip()
        for item in run_text([
            "nvidia-smi",
            "--query-gpu=driver_version",
            "--format=csv,noheader",
        ]).splitlines()
        if item.strip()
    ]
    if not driver_lines or len(set(driver_lines)) != 1:
        raise PrerequisiteObservationError(
            "prerequisite_nvidia_driver_ambiguous"
        )

    cuda = run_text([
        sys.executable,
        "-c",
        "import torch; print(torch.version.cuda or '')",
    ])
    if not cuda:
        raise PrerequisiteObservationError(
            "prerequisite_cuda_runtime_unavailable"
        )

    return {
        "distribution": os_release.get("ID", ""),
        "release": os_release.get("VERSION_ID", ""),
        "architecture": platform.machine(),
        "pythonVersion": platform.python_version(),
        "pythonImplementation": platform.python_implementation(),
        "nvidiaDriverVersion": driver_lines[0],
        "cudaRuntimeVersion": cuda,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--role",
        choices=(
            "windows-operational-plane",
            "database",
            "linux-vision-worker",
        ),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--psql", default="psql")
    parser.add_argument("--pg-service")
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise PrerequisiteObservationError(
                "prerequisite_observation_output_exists"
            )
        if args.role == "windows-operational-plane":
            values = windows_values()
        elif args.role == "database":
            if not args.pg_service:
                raise PrerequisiteObservationError(
                    "prerequisite_pg_service_required"
                )
            values = database_values(args.psql, args.pg_service)
        else:
            values = linux_values()

        if any(not isinstance(value, str) or not value for value in values.values()):
            raise PrerequisiteObservationError(
                "prerequisite_observation_value_missing"
            )
        payload = {
            "schemaVersion": "mavi-production-prerequisite-observation-v1",
            "role": args.role,
            "capturedAtUtc": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "values": values,
        }
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, PrerequisiteObservationError) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps({"ok": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
