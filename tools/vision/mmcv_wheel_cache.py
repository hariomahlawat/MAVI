#!/usr/bin/env python3
"""Content-addressed reuse of Task 10's own MMCV wheel (qualification tooling).

Task 10 compiles MMCV from an immutable source commit against the installed
PyTorch. The compiled wheel may be reused only by a later Task 10 job whose
build inputs are identical. This tool defines that identity, records a wheel's
provenance after a build, and verifies a restored wheel before it is installed.

* ``identity``  -- compute this job's build identity and its cache key.
* ``record``    -- after a build, write provenance binding the wheel to the identity.
* ``verify``    -- check a restored wheel against this job's identity and, with
                   ``--attest``, that GitHub attests a trusted Task 10 run produced it.

``verify`` exits 0 when the wheel is verified. It exits 3 when the entry is
unverifiable, meaning provenance is absent, unreadable, or of an unknown
schema; the job then rebuilds. It exits 2 on an integrity violation, meaning
provenance for a different identity, a changed wheel, a wrong distribution or
tag, or a RECORD that disagrees with the wheel's members; the job then fails
and never falls back to a rebuild.

Provenance inside a cache entry is written by whoever saved the entry, so on
its own it proves nothing about who built the wheel. ``--attest`` therefore
asks GitHub, not the entry, about the producing run. That run must be a
Task 10 run of this repository, and one of the following:

* a ``push`` or ``workflow_dispatch`` run on the default branch; or
* a run on exactly the head being qualified.

The producer's own uploaded ``mmcv-wheel.json`` must also name this wheel's
SHA-256 and identity. An entry that fails these checks is either unverifiable
or an integrity violation, as for ``verify``.

Byte reproducibility of the MMCV wheel is Task 12's proof, not this tool's;
see docs/qualification/stage2-s1/2026-10-01-task10-harness-separation-and-mmcv-wheel-reuse.md.
"""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import subprocess
import sys
import sysconfig
import urllib.error
import urllib.request
import zipfile
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
TASK10_WORKFLOW_PATH = ".github/workflows/task10-runtime-qualification.yml"
TRUSTED_REF_EVENTS = frozenset({"push", "workflow_dispatch"})
WHEEL_RECORD_NAME = "mmcv-wheel.json"
# Build tools whose version can change the compiled wheel.
BUILD_DISTRIBUTIONS = ("setuptools", "wheel", "ninja", "pip")
# Environment that the MMCV / PyTorch extension build reads. MAX_JOBS only
# changes parallelism, not the output, and is deliberately excluded.
BUILD_ENVIRONMENT = ("CC", "CXX", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "DISTUTILS_USE_SDK", "MSSdk",
                     "TORCH_CUDA_ARCH_LIST", "CUDA_HOME", "FORCE_CUDA")
BUILD_ENVIRONMENT_PREFIXES = ("MMCV_",)


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


def _first_line(command: list[str], *, stderr_first: bool = False) -> str | None:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    streams = [completed.stdout or "", completed.stderr or ""]
    text = "\n".join(reversed(streams) if stderr_first else streams)
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
            # cl prints its version banner to stderr and a usage line to stdout.
            "cl": _first_line(["cl"], stderr_first=True),
        }
    return {
        "cxx": _first_line([os.environ.get("CXX", "c++"), "--version"]),
        "libc": list(platform.libc_ver()),
    }


# Lines of torch.__config__.show() that describe the machine it runs on, not
# how PyTorch was built. Measured on Task 10: two Ubuntu runners with the same
# PyTorch wheel reported different "CPU capability usage" (AVX2 / AVX512).
RUNTIME_CONFIG_MARKERS = ("CPU capability usage",)


def torch_build_config(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not any(m in line for m in RUNTIME_CONFIG_MARKERS))


def torch_identity() -> dict[str, Any]:
    import torch  # noqa: PLC0415 - identity is computed after the pinned PyTorch is installed

    return {
        "version": torch.__version__,
        "gitVersion": torch.version.git_version,
        "configSha256": sha256_bytes(torch_build_config(torch.__config__.show()).encode("utf-8")),
        "cxx11Abi": bool(getattr(torch._C, "_GLIBCXX_USE_CXX11_ABI", False)),
    }


def build_tools_identity() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in BUILD_DISTRIBUTIONS:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def build_environment_identity() -> dict[str, str]:
    return {
        name: value
        for name, value in sorted(os.environ.items())
        if name in BUILD_ENVIRONMENT or name.startswith(BUILD_ENVIRONMENT_PREFIXES)
    }


def environment_identity(mmcv_commit: str, recipe: str) -> dict[str, Any]:
    import numpy  # noqa: PLC0415

    here = Path(__file__).resolve().parent
    return {
        "schema": IDENTITY_SCHEMA,
        "mmcvSourceCommit": mmcv_commit,
        "buildRecipe": recipe,
        "toolSha256": sha256_file(Path(__file__)),
        "verifierSha256": sha256_file(here / "compare_wheel_reproducibility.py"),
        "buildTools": build_tools_identity(),
        "buildEnvironment": build_environment_identity(),
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


def attest(
    provenance: dict[str, Any],
    run: dict[str, Any] | None,
    producer_records: list[dict[str, Any]],
    *,
    expected_head: str,
    repository: str,
    default_branch: str,
    variant: str,
    producer_on_default_branch: bool = False,
) -> dict[str, Any]:
    """Bind a verified entry to a producing run that GitHub, not the entry, describes.

    ``run`` is GitHub's record of the run the provenance names.
    ``producer_records`` are that run's own uploaded ``mmcv-wheel.json``
    records, one per attempt that uploaded its evidence artifact. A rerun
    uploads a second artifact under the same name.

    ``producer_on_default_branch`` says whether GitHub reports the run's head
    commit as contained in the default branch. Without that, a tag named after
    the default branch would also report ``head_branch == default``.

    A producer that is unknown or untrusted makes the entry unverifiable, so
    the job rebuilds; an earlier head of a pull request is the common case. A
    trusted producer whose build records all disagree about the bytes is an
    integrity violation.
    """
    if run is None:
        raise Unverifiable("producer_run_unknown")
    if run.get("path") != TASK10_WORKFLOW_PATH:
        raise Unverifiable(f"producer_not_task10:{run.get('path')}")
    for field in ("repository", "head_repository"):
        if (run.get(field) or {}).get("full_name") != repository:
            raise Unverifiable(f"producer_{field}_untrusted")
    if (
        run.get("event") in TRUSTED_REF_EVENTS
        and run.get("head_branch") == default_branch
        and producer_on_default_branch
    ):
        trust = "default-branch"
    elif run.get("head_sha") == expected_head:
        trust = "same-head"
    else:
        raise Unverifiable(f"producer_not_trusted:{run.get('event')}:{run.get('head_branch')}")
    if not producer_records:
        raise Unverifiable("producer_record_missing")

    reasons = []
    for producer_record in producer_records:
        reason = _producer_disagreement(provenance, run, producer_record, variant)
        if reason is None:
            break
        reasons.append(reason)
    else:
        raise IntegrityError(reasons[0] if len(set(reasons)) == 1 else f"producer_records_disagree:{sorted(set(reasons))}")
    return {
        "trust": trust,
        "runId": run.get("id"),
        "event": run.get("event"),
        "headBranch": run.get("head_branch"),
        "headSha": run.get("head_sha"),
    }


def _producer_disagreement(
    provenance: dict[str, Any], run: dict[str, Any], record: dict[str, Any], variant: str
) -> str | None:
    produced = record.get("provenance") or {}
    if record.get("state") != "build":
        return f"producer_did_not_build:{record.get('state')}"
    if record.get("runtimeVariant") != variant:
        return "producer_variant_mismatch"
    if record.get("headSha") != run.get("head_sha"):
        return "producer_head_mismatch"
    if produced.get("identitySha256") != provenance.get("identitySha256"):
        return "producer_identity_mismatch"
    if (produced.get("wheel") or {}).get("sha256") != (provenance.get("wheel") or {}).get("sha256"):
        return "producer_wheel_mismatch"
    return None


def _api(url: str, token: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    # Unredirected: the artifact download redirects to blob storage, which must
    # not receive the token.
    request.add_unredirected_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def fetch_producer(
    run_id: Any, artifact_name: str, default_branch: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], bool]:
    """Return GitHub's record of ``run_id``, every ``mmcv-wheel.json`` it uploaded, and
    whether its head commit is contained in ``default_branch``."""
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    repository = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    if not str(run_id or "").isdigit():
        return None, [], False
    base = f"{api}/repos/{repository}/actions/runs/{run_id}"
    try:
        run = json.loads(_api(base, token))
        listing = json.loads(_api(f"{base}/artifacts?name={artifact_name}&per_page=100", token))
        records = []
        for artifact in listing.get("artifacts", []):
            if artifact.get("name") != artifact_name or artifact.get("expired"):
                continue
            with zipfile.ZipFile(io.BytesIO(_api(artifact["archive_download_url"], token))) as archive:
                if WHEEL_RECORD_NAME in archive.namelist():
                    records.append(json.loads(archive.read(WHEEL_RECORD_NAME)))
        on_default = False
        head_sha = str(run.get("head_sha") or "")
        if len(head_sha) == 40 and all(c in "0123456789abcdef" for c in head_sha):
            # "behind" or "identical": every commit of head_sha is in the default branch.
            comparison = json.loads(_api(f"{api}/repos/{repository}/compare/{default_branch}...{head_sha}", token))
            on_default = comparison.get("status") in ("behind", "identical")
        return run, records, on_default
    except (urllib.error.URLError, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise Unverifiable(f"producer_unreachable:{exc}") from exc


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
    ver.add_argument("--attest", action="store_true", help="also require a GitHub-attested trusted producer")
    ver.add_argument("--attestation-out", type=Path)
    ver.add_argument("--artifact-name", help="the producer's evidence artifact holding mmcv-wheel.json")
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
        if args.attest:
            default_branch = os.environ["MAVI_DEFAULT_BRANCH"]
            run, records, on_default = fetch_producer(
                (provenance.get("build") or {}).get("runId"), args.artifact_name, default_branch
            )
            attestation = attest(
                provenance,
                run,
                records,
                expected_head=os.environ["MAVI_EXPECTED_SOURCE_SHA"],
                repository=os.environ["GITHUB_REPOSITORY"],
                default_branch=default_branch,
                variant=os.environ["MAVI_RUNTIME_VARIANT"],
                producer_on_default_branch=on_default,
            )
            if args.attestation_out:
                args.attestation_out.write_bytes(canonical(attestation) + b"\n")
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
