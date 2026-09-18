#!/usr/bin/env python3
"""Compare two wheels built from the same frozen inputs.

C2 must establish whether the MMCV CUDA wheel is byte-reproducible before C3
commits to an identity contract. `nvcc` has no `/Brepro` equivalent for device
code, so a negative answer is a legitimate result -- but it must be a measured
one, naming the exact source of variance rather than being assumed either way.

The tool is offline and reads only the two wheels it is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path


class WheelComparisonError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# Members whose bytes decide whether the runtime behaves identically. A
# difference here is never cosmetic.
_NATIVE_SUFFIXES = (".pyd", ".dll", ".so")
# Metadata whose content is part of the distribution's identity.
_IDENTITY_MEMBERS = re.compile(r"\.dist-info/(METADATA|WHEEL|entry_points\.txt)$")
# RECORD restates the other members' hashes, so it differs whenever they do and
# is reported through them rather than as an independent finding.
_RECORD_MEMBER = re.compile(r"\.dist-info/RECORD$")
# Absolute build paths embedded in artefacts defeat relocatable reproduction.
_EMBEDDED_PATH = re.compile(
    rb"[A-Za-z]:\\(?:Users|Windows|build|work|actions-runner)[\\\w.-]*"
    rb"|/(?:home|build|tmp|work)/[\w./-]{4,}"
)


@dataclass(frozen=True, slots=True)
class _Member:
    name: str
    sha256: str
    size: int
    date_time: tuple[int, int, int, int, int, int]
    crc: int


def _members(path: Path) -> dict[str, _Member]:
    if not path.is_file():
        raise WheelComparisonError("wheel_missing:" + path.name)
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise WheelComparisonError("wheel_invalid_zip:" + path.name) from exc
    with archive:
        result: dict[str, _Member] = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            data = archive.read(info.filename)
            result[info.filename] = _Member(
                name=info.filename,
                sha256=hashlib.sha256(data).hexdigest(),
                size=len(data),
                date_time=tuple(info.date_time),  # type: ignore[arg-type]
                crc=info.CRC,
            )
        return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_native(name: str) -> bool:
    return name.casefold().endswith(_NATIVE_SUFFIXES)


def _embedded_paths(path: Path, member: str) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        data = archive.read(member)
    found = {match.decode("utf-8", "replace") for match in _EMBEDDED_PATH.findall(data)}
    return sorted(found)


def compare_wheels(left: Path, right: Path) -> dict[str, object]:
    """Classify the difference between two wheels of the same distribution."""
    left_members = _members(left)
    right_members = _members(right)

    left_sha = _sha256_file(left)
    right_sha = _sha256_file(right)

    only_left = sorted(set(left_members) - set(right_members))
    only_right = sorted(set(right_members) - set(left_members))
    shared = sorted(set(left_members) & set(right_members))

    content_differs: list[str] = []
    timestamp_only: list[str] = []
    for name in shared:
        a, b = left_members[name], right_members[name]
        if a.sha256 != b.sha256:
            content_differs.append(name)
        elif a.date_time != b.date_time:
            timestamp_only.append(name)

    # RECORD mirrors the other members, so it is not an independent signal.
    substantive = [
        name for name in content_differs if _RECORD_MEMBER.search(name) is None
    ]
    native_differs = [name for name in substantive if _is_native(name)]
    identity_differs = [
        name for name in substantive if _IDENTITY_MEMBERS.search(name) is not None
    ]
    other_differs = [
        name
        for name in substantive
        if name not in native_differs and name not in identity_differs
    ]

    if left_sha == right_sha:
        verdict = "byte-identical"
    elif only_left or only_right:
        verdict = "divergent-inventory"
    elif substantive:
        verdict = "divergent-content"
    else:
        # Same filenames, same member bytes, different archive bytes: the
        # variance is in the container, not in what gets installed.
        verdict = "semantically-identical"

    variance_sources: list[str] = []
    if only_left or only_right:
        variance_sources.append("member-inventory")
    if native_differs:
        variance_sources.append("native-binary-content")
    if identity_differs:
        variance_sources.append("distribution-metadata")
    if other_differs:
        variance_sources.append("member-content")
    if timestamp_only:
        variance_sources.append("archive-timestamps")
    if (
        left_sha != right_sha
        and not substantive
        and not timestamp_only
        and not (only_left or only_right)
    ):
        variance_sources.append("archive-container")

    embedded: dict[str, list[str]] = {}
    for name in sorted(set(native_differs) | set(substantive)):
        paths = sorted(set(_embedded_paths(left, name)) | set(_embedded_paths(right, name)))
        if paths:
            embedded[name] = paths

    return {
        "schemaVersion": "mavi-wheel-reproducibility-comparison-v1",
        "verdict": verdict,
        "byteIdentical": left_sha == right_sha,
        "left": {"filename": left.name, "sha256": left_sha, "sizeBytes": left.stat().st_size},
        "right": {"filename": right.name, "sha256": right_sha, "sizeBytes": right.stat().st_size},
        "memberCount": {"left": len(left_members), "right": len(right_members)},
        "varianceSources": variance_sources,
        "onlyInLeft": only_left,
        "onlyInRight": only_right,
        "contentDiffers": substantive,
        "nativeContentDiffers": native_differs,
        "metadataDiffers": identity_differs,
        "timestampOnlyDiffers": timestamp_only,
        "embeddedBuildPaths": embedded,
        "note": (
            "A byte-identical or semantically-identical verdict is a build "
            "reproducibility result only. It is not a runtime, hardware or "
            "Production qualification."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require",
        choices=("byte-identical", "semantically-identical"),
        help=(
            "Exit non-zero unless the verdict is at least this strong. "
            "Omit to report without enforcing."
        ),
    )
    args = parser.parse_args()

    try:
        result = compare_wheels(args.left, args.right)
    except WheelComparisonError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True))
        return 2

    if args.output is not None:
        if args.output.exists():
            print(
                json.dumps(
                    {"ok": False, "code": "wheel_comparison_output_exists"},
                    sort_keys=True,
                )
            )
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    print(json.dumps({"ok": True, "comparison": result}, sort_keys=True))

    if args.require is None:
        return 0
    accepted = {
        "byte-identical": {"byte-identical"},
        "semantically-identical": {"byte-identical", "semantically-identical"},
    }[args.require]
    return 0 if result["verdict"] in accepted else 3


if __name__ == "__main__":
    raise SystemExit(main())
