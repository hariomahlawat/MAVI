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

PHASE1_ROOT = Path(__file__).resolve().parent
if str(PHASE1_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE1_ROOT))

from production_acceptance_context import (
    AcceptanceContextError,
    load_context as load_acceptance_context,
)
from topology_identity import (  # noqa: E402
    TopologyIdentityError,
    database_identity,
    host_identity_sha256,
)


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

    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\InetStp",
        ) as key:
            iis_version = str(
                winreg.QueryValueEx(key, "VersionString")[0]
            ).strip()
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        ) as key:
            product_name = str(
                winreg.QueryValueEx(key, "ProductName")[0]
            ).strip()
            display_version = str(
                winreg.QueryValueEx(key, "DisplayVersion")[0]
            ).strip()
            build_number = str(
                winreg.QueryValueEx(key, "CurrentBuildNumber")[0]
            ).strip()
    except (OSError, ImportError) as exc:
        raise PrerequisiteObservationError(
            "prerequisite_windows_registry_unavailable"
        ) from exc

    runtimes = run_text(["dotnet", "--list-runtimes"]).splitlines()
    aspnet = []
    for line in runtimes:
        parts = line.split()
        if (
            len(parts) >= 2
            and parts[0] == "Microsoft.AspNetCore.App"
            and parts[1].startswith("10.")
        ):
            aspnet.append(parts[1])
    if not aspnet:
        raise PrerequisiteObservationError("prerequisite_dotnet10_runtime_unavailable")

    def version_key(value: str) -> tuple[int, ...]:
        numbers = re.findall(r"\d+", value)
        return tuple(int(item) for item in numbers)

    return {
        "windowsProductName": product_name,
        "windowsVersion": display_version,
        "windowsBuild": build_number,
        "architecture": platform.machine(),
        "iisVersion": iis_version,
        "dotnetRuntimeVersion": max(aspnet, key=version_key),
    }

def windows_vision_values(*, require_cuda: bool) -> dict[str, str]:
    if platform.system() != "Windows":
        raise PrerequisiteObservationError("prerequisite_windows_host_required")

    values = {
        "architecture": platform.machine(),
        "pythonVersion": platform.python_version(),
        "pythonImplementation": platform.python_implementation(),
    }
    if not require_cuda:
        return values

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
    values["nvidiaDriverVersion"] = driver_lines[0]
    values["cudaRuntimeVersion"] = cuda
    return values


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
    parser.add_argument("--acceptance-context", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--mavi-build", required=True)
    parser.add_argument(
        "--role",
        choices=(
            "windows-operational-plane",
            "database",
            "windows-cuda-vision-worker",
            "windows-cpu-vision-worker",
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
        context, context_sha = load_acceptance_context(
            args.acceptance_context,
            schema_path=PHASE1_ROOT / "production-acceptance-context.schema.json",
            expected_source_commit=args.source_commit,
            expected_mavi_build=args.mavi_build,
        )
        if args.role == "windows-operational-plane":
            values = windows_values()
            topology_identity = host_identity_sha256()
        elif args.role == "database":
            if not args.pg_service:
                raise PrerequisiteObservationError(
                    "prerequisite_pg_service_required"
                )
            values = database_values(args.psql, args.pg_service)
            topology_identity = database_identity(args.psql, args.pg_service)
        elif args.role == "windows-cuda-vision-worker":
            values = windows_vision_values(require_cuda=True)
            topology_identity = host_identity_sha256()
        elif args.role == "windows-cpu-vision-worker":
            values = windows_vision_values(require_cuda=False)
            topology_identity = host_identity_sha256()
        else:
            values = linux_values()
            topology_identity = host_identity_sha256()

        if any(not isinstance(value, str) or not value for value in values.values()):
            raise PrerequisiteObservationError(
                "prerequisite_observation_value_missing"
            )
        payload = {
            "schemaVersion": "mavi-production-prerequisite-observation-v1",
            "acceptanceExecutionId": context["acceptanceExecutionId"],
            "acceptanceContextSha256": context_sha,
            "role": args.role,
            "capturedAtUtc": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "topologyIdentity": topology_identity,
            "values": values,
        }
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (
        OSError,
        PrerequisiteObservationError,
        TopologyIdentityError,
        AcceptanceContextError,
    ) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps({"ok": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
