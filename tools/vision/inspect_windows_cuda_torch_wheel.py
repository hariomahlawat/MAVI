#!/usr/bin/env python3
"""Inspect a Windows PyTorch CUDA wheel before C2 lock freeze.

The tool is offline: it reads one local wheel, verifies the expected binary
identity, checks Windows dependency-marker assumptions, inventories CUDA DLLs,
and emits a deterministic JSON observation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from email.parser import Parser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version


class TorchWheelInspectionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_REQUIRED_CUDA_DLL_PATTERNS = (
    r"^torch/lib/cudart64_12\.dll$",
    r"^torch/lib/cublas64_12\.dll$",
    r"^torch/lib/cublasLt64_12\.dll$",
    r"^torch/lib/cudnn.*64_9\.dll$",
    r"^torch/lib/cufft64_11\.dll$",
    r"^torch/lib/curand64_10\.dll$",
    r"^torch/lib/cusolver64_11\.dll$",
    r"^torch/lib/cusparse64_12\.dll$",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_wheel(
    path: Path,
    *,
    expected_version: str = "2.6.0+cu124",
) -> dict[str, object]:
    if not path.is_file():
        raise TorchWheelInspectionError("torch_wheel_missing")
    if path.suffix.casefold() != ".whl":
        raise TorchWheelInspectionError("torch_wheel_extension_invalid")

    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise TorchWheelInspectionError("torch_wheel_invalid_zip") from exc

    with archive:
        names = sorted(archive.namelist())
        metadata_paths = [
            name
            for name in names
            if name.endswith(".dist-info/METADATA")
            and "/torch-" in ("/" + name)
        ]
        if len(metadata_paths) != 1:
            raise TorchWheelInspectionError(
                "torch_wheel_metadata_ambiguous"
            )
        metadata = Parser().parsestr(
            archive.read(metadata_paths[0]).decode("utf-8")
        )

        if metadata.get("Name", "").casefold() != "torch":
            raise TorchWheelInspectionError(
                "torch_wheel_name_mismatch"
            )
        version = metadata.get("Version", "")
        if Version(version) != Version(expected_version):
            raise TorchWheelInspectionError(
                "torch_wheel_version_mismatch"
            )

        requirements = [
            Requirement(value)
            for value in metadata.get_all("Requires-Dist", [])
        ]
        suspicious: list[str] = []
        for requirement in requirements:
            name = requirement.name.casefold()
            if name.startswith("nvidia-") or name == "triton":
                marker = str(requirement.marker or "")
                if "linux" not in marker.casefold():
                    suspicious.append(str(requirement))
        if suspicious:
            raise TorchWheelInspectionError(
                "torch_wheel_windows_cuda_dependency_marker_invalid"
            )

        dlls = sorted(
            name
            for name in names
            if name.casefold().startswith("torch/lib/")
            and name.casefold().endswith(".dll")
        )
        missing_patterns = [
            pattern
            for pattern in _REQUIRED_CUDA_DLL_PATTERNS
            if not any(re.fullmatch(pattern, name) for name in dlls)
        ]
        if missing_patterns:
            raise TorchWheelInspectionError(
                "torch_wheel_cuda_dll_inventory_incomplete"
            )

        dll_hashes = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in dlls
        }

    return {
        "schemaVersion": "mavi-windows-cuda-torch-wheel-inspection-v1",
        "wheel": {
            "filename": path.name,
            "sha256": _sha256(path),
            "version": version,
        },
        "dependencyMetadata": {
            "requiresDist": sorted(str(item) for item in requirements),
            "suspiciousWindowsCudaDependencies": [],
        },
        "cudaDlls": [
            {
                "path": name,
                "sha256": dll_hashes[name],
            }
            for name in dlls
        ],
        "result": "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument(
        "--expected-version",
        default="2.6.0+cu124",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        value = inspect_wheel(
            args.wheel,
            expected_version=args.expected_version,
        )
    except TorchWheelInspectionError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True))
        return 2

    if args.output is not None:
        if args.output.exists():
            print(
                json.dumps(
                    {"ok": False, "code": "torch_wheel_inspection_output_exists"},
                    sort_keys=True,
                )
            )
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps({"ok": True, "inspection": value}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
