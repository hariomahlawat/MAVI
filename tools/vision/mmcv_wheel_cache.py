#!/usr/bin/env python3
"""Content-addressed reuse of Task 10's own MMCV wheel (qualification tooling).

Task 10 compiles MMCV from an immutable source commit against the installed
PyTorch. The compiled wheel may be reused only by a later Task 10 job whose
build inputs are identical. This tool defines that identity, records a wheel's
provenance after a build, and verifies a restored wheel before it is installed.

* ``identity``  -- compute this job's build identity and its cache key.
* ``record``    -- after a build, write provenance binding the wheel to the identity.
* ``verify``    -- check a restored wheel against this job's identity.

``verify`` exits 0 when the wheel is verified. It exits 3 when the entry is
unverifiable, meaning provenance is absent, unreadable, or of an unknown
schema; the job then rebuilds. It exits 2 on an integrity violation, meaning
provenance for a different identity, a changed wheel, a wrong distribution or
tag, or a RECORD that disagrees with the wheel's members; the job then fails
and never falls back to a rebuild.

Byte reproducibility of the MMCV wheel is Task 12's proof, not this tool's;
see docs/qualification/stage2-s1/2026-10-01-task10-harness-separation-and-mmcv-wheel-reuse.md.
"""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import json
import os
import platform
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_wheel_reproducibility import (  # noqa: E402
    WheelComparisonError,
    _read_archive,
    _record_consistency,
)

IDENTITY_SCHEMA = "mavi-task10-mmcv-wheel-identity-v1"
PROVENANCE_SCHEMA = "mavi-task10-mmcv-wheel-provenance-v1"
PROVENANCE_NAME = "provenance.json"
EXPECTED_DISTRIBUTION = ("mmcv", "2.1.0")
EXIT_VERIFIED, EXIT_INTEGRITY, EXIT_UNVERIFIABLE = 0, 2, 3


class IntegrityError(Exception):
    """The restored entry claims an identity or bytes it does not have."""


class Unverifiable(Exception):
    """The restored entry cannot be checked at all."""


def canonical(document: Any) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_line(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (completed.stdout or "") + (completed.stderr or "")
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def toolchain_identity() -> dict[str, Any]:
    """The compiler, SDK and C++ runtime that a build on this runner would use."""
    if platform.system() == "Windows":
        return {
            "msvcToolsVersion": os.environ.get("VCToolsVersion"),
            "windowsSdkVersion": os.environ.get("WindowsSDKVersion"),
            "vsCmdVersion": os.environ.get("VSCMD_VER"),
            "cl": _first_line(["cl"]),
        }
    return {
        "cxx": _first_line([os.environ.get("CXX", "c++"), "--version"]),
        "libc": list(platform.libc_ver()),
    }


def torch_identity() -> dict[str, Any]:
    import torch  # noqa: PLC0415 - identity is computed after the pinned PyTorch is installed

    return {
        "version": torch.__version__,
        "gitVersion": torch.version.git_version,
        "configSha256": sha256_bytes(torch.__config__.show().encode("utf-8")),
        "cxx11Abi": bool(getattr(torch._C, "_GLIBCXX_USE_CXX11_ABI", False)),
    }


def environment_identity(mmcv_commit: str, recipe: str) -> dict[str, Any]:
    import numpy  # noqa: PLC0415

    return {
        "schema": IDENTITY_SCHEMA,
        "mmcvSourceCommit": mmcv_commit,
        "buildRecipe": recipe,
        "toolSha256": sha256_file(Path(__file__)),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "build": list(platform.python_build()),
            "compiler": platform.python_compiler(),
            "soabi": sysconfig.get_config_var("SOABI") or sysconfig.get_config_var("EXT_SUFFIX"),
            "cacheTag": sys.implementation.cache_tag,
        },
        "torch": torch_identity(),
        "numpy": numpy.__version__,
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "sysconfigPlatform": sysconfig.get_platform(),
            "runnerImage": os.environ.get("ImageOS"),
        },
        "toolchain": toolchain_identity(),
    }


def identity_key(identity: dict[str, Any]) -> str:
    return sha256_bytes(canonical(identity))


def expected_wheel_tag(identity: dict[str, Any]) -> str:
    version = identity["python"]["version"].split(".")
    python_tag = f"cp{version[0]}{version[1]}"
    platform_tag = identity["platform"]["sysconfigPlatform"].replace("-", "_").replace(".", "_")
    return f"{python_tag}-{python_tag}-{platform_tag}"


def _single_wheel(directory: Path) -> Path:
    wheels = sorted(directory.glob("*.whl"))
    if len(wheels) != 1:
        raise Unverifiable(f"expected exactly one wheel in {directory.name}, found {len(wheels)}")
    return wheels[0]


def record_provenance(directory: Path, identity: dict[str, Any], build: dict[str, Any]) -> dict[str, Any]:
    wheel = _single_wheel(directory)
    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "identity": identity,
        "identitySha256": identity_key(identity),
        "wheel": {"name": wheel.name, "sha256": sha256_file(wheel), "size": wheel.stat().st_size},
        "build": build,
    }
    (directory / PROVENANCE_NAME).write_bytes(canonical(provenance) + b"\n")
    return provenance


def _wheel_metadata(path: Path) -> tuple[str, str, list[str]]:
    import zipfile  # noqa: PLC0415

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata = [n for n in names if n.endswith(".dist-info/METADATA")]
        wheel_files = [n for n in names if n.endswith(".dist-info/WHEEL")]
        if len(metadata) != 1 or len(wheel_files) != 1:
            raise IntegrityError("wheel_dist_info_not_unique")
        meta = email.parser.Parser().parsestr(archive.read(metadata[0]).decode("utf-8"))
        tags = email.parser.Parser().parsestr(archive.read(wheel_files[0]).decode("utf-8")).get_all("Tag") or []
    return meta.get("Name", ""), meta.get("Version", ""), tags


def verify(directory: Path, identity: dict[str, Any], expected_sha256: str | None = None) -> dict[str, Any]:
    """Verify a restored or handed-over entry; raise ``Unverifiable`` or ``IntegrityError``."""
    provenance_path = directory / PROVENANCE_NAME
    if not provenance_path.is_file():
        raise Unverifiable("provenance_missing")
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Unverifiable("provenance_unreadable") from exc
    if not isinstance(provenance, dict) or provenance.get("schema") != PROVENANCE_SCHEMA:
        raise Unverifiable("provenance_schema_unknown")
    wheel = _single_wheel(directory)

    # From here the entry claims to be verifiable; every disagreement is an integrity violation.
    if provenance.get("identity") != identity:
        raise IntegrityError("identity_mismatch")
    if provenance.get("identitySha256") != identity_key(identity):
        raise IntegrityError("identity_hash_mismatch")
    recorded = provenance.get("wheel") or {}
    if recorded.get("name") != wheel.name:
        raise IntegrityError("wheel_name_mismatch")
    actual_sha256 = sha256_file(wheel)
    if recorded.get("sha256") != actual_sha256 or recorded.get("size") != wheel.stat().st_size:
        raise IntegrityError("wheel_hash_mismatch")
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise IntegrityError("wheel_not_the_expected_artifact")
    name, version, tags = _wheel_metadata(wheel)
    if (name.lower(), version) != EXPECTED_DISTRIBUTION:
        raise IntegrityError(f"wheel_distribution_unexpected:{name}=={version}")
    if tags != [expected_wheel_tag(identity)]:
        raise IntegrityError(f"wheel_tag_unexpected:{tags}")
    try:
        record = _record_consistency(_read_archive(wheel))
    except WheelComparisonError as exc:
        raise IntegrityError(f"wheel_unreadable:{exc}") from exc
    if not record["present"] or not record["consistent"]:
        raise IntegrityError(f"wheel_record_inconsistent:{record.get('disagreements')}")
    return provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    ident = sub.add_parser("identity")
    ident.add_argument("--mmcv-commit", required=True)
    ident.add_argument("--recipe", required=True)
    ident.add_argument("--out", required=True, type=Path)
    rec = sub.add_parser("record")
    rec.add_argument("--dir", required=True, type=Path)
    rec.add_argument("--identity", required=True, type=Path)
    ver = sub.add_parser("verify")
    ver.add_argument("--dir", required=True, type=Path)
    ver.add_argument("--identity", required=True, type=Path)
    ver.add_argument("--expected-sha256")
    args = parser.parse_args(argv)

    if args.command == "identity":
        identity = environment_identity(args.mmcv_commit, args.recipe)
        args.out.write_bytes(canonical(identity) + b"\n")
        print(identity_key(identity))
        return 0
    identity = json.loads(args.identity.read_text(encoding="utf-8"))
    if args.command == "record":
        build = {
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "workflow": os.environ.get("GITHUB_WORKFLOW"),
            "event": os.environ.get("GITHUB_EVENT_NAME"),
            "ref": os.environ.get("GITHUB_REF"),
            "sourceSha": os.environ.get("MAVI_EXPECTED_SOURCE_SHA"),
            "runnerImageVersion": os.environ.get("ImageVersion"),
        }
        provenance = record_provenance(args.dir, identity, build)
        print(json.dumps(provenance["wheel"], sort_keys=True))
        return 0
    try:
        provenance = verify(args.dir, identity, args.expected_sha256)
    except Unverifiable as exc:
        print(f"mmcv-wheel-unverifiable: {exc}", file=sys.stderr)
        return EXIT_UNVERIFIABLE
    except IntegrityError as exc:
        print(f"mmcv-wheel-integrity-violation: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    print("mmcv-wheel-verified", json.dumps({"wheel": provenance["wheel"], "build": provenance["build"]}, sort_keys=True))
    return EXIT_VERIFIED


if __name__ == "__main__":
    raise SystemExit(main())
