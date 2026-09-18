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
_NATIVE_SUFFIXES = (".pyd", ".dll", ".so", ".dylib", ".exe", ".lib")
# Metadata whose content is part of the distribution's identity.
_IDENTITY_MEMBERS = re.compile(
    r"\.dist-info/(METADATA|WHEEL|entry_points\.txt)$", re.IGNORECASE
)
# RECORD restates the other members' hashes, so when they differ it differs too.
# The converse does not hold: RECORD can disagree with the members it lists, and
# that is an installable defect, so it is reported in its own right.
_RECORD_MEMBER = re.compile(r"\.dist-info/RECORD$", re.IGNORECASE)
# Absolute build paths embedded in artefacts defeat relocatable reproduction.
# Deliberately general: the GitHub Windows runner workspace is `D:\a\<repo>`,
# and an allow-list of familiar roots misses exactly the layouts in scope.
_EMBEDDED_PATH = re.compile(
    rb"[A-Za-z]:[\\/][^\x00-\x1f\"<>|*?]{6,120}"
    rb"|/(?:home|build|tmp|work|opt|usr|root|var|mnt|Users)/[\w./+-]{4,120}"
)


@dataclass(frozen=True, slots=True)
class _Member:
    name: str
    sha256: str
    size: int
    date_time: tuple[int, int, int, int, int, int]
    # The high 16 bits carry the Unix mode: the executable bit on console
    # scripts and the symlink bit both live here and change what gets installed.
    mode: int
    create_system: int
    compress_type: int


@dataclass(frozen=True, slots=True)
class _Archive:
    members: dict[str, _Member]
    order: tuple[str, ...]
    comment: bytes


def _read_archive(path: Path) -> _Archive:
    if not path.is_file():
        raise WheelComparisonError("wheel_missing:" + path.name)
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise WheelComparisonError("wheel_invalid_zip:" + path.name) from exc
    with archive:
        members: dict[str, _Member] = {}
        order: list[str] = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            if info.filename in members:
                # Installers disagree on which copy of a duplicated entry wins,
                # so such a wheel installs different bytes depending on the
                # installer. That is a defect in the artefact, not a difference
                # between two artefacts.
                raise WheelComparisonError(
                    f"wheel_duplicate_member:{path.name}:{info.filename}"
                )
            try:
                # Read by ZipInfo, never by name: name lookup resolves through
                # the last entry with that name.
                data = archive.read(info)
            except (
                OSError,
                zipfile.BadZipFile,
                RuntimeError,
                NotImplementedError,
            ) as exc:
                raise WheelComparisonError(
                    f"wheel_member_unreadable:{path.name}:{info.filename}"
                ) from exc
            members[info.filename] = _Member(
                name=info.filename,
                sha256=hashlib.sha256(data).hexdigest(),
                size=len(data),
                date_time=tuple(info.date_time),  # type: ignore[arg-type]
                mode=(info.external_attr >> 16) & 0xFFFF,
                create_system=info.create_system,
                compress_type=info.compress_type,
            )
            order.append(info.filename)
        return _Archive(
            members=members,
            order=tuple(order),
            comment=archive.comment or b"",
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_native(name: str) -> bool:
    return name.casefold().endswith(_NATIVE_SUFFIXES)


def _embedded_paths(path: Path) -> dict[str, list[str]]:
    """Scan every member for absolute build paths.

    This is a property of one wheel, not of a difference between two. Two
    builds run from the same directory embed the same path and come out
    byte-identical, so scanning only differing members reports nothing exactly
    when the non-relocatability exists.
    """
    found: dict[str, list[str]] = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            try:
                data = archive.read(info)
            except (
                OSError,
                zipfile.BadZipFile,
                RuntimeError,
                NotImplementedError,
            ) as exc:
                raise WheelComparisonError(
                    f"wheel_member_unreadable:{path.name}:{info.filename}"
                ) from exc
            matches = {
                match.decode("utf-8", "replace").rstrip("\x00")
                for match in _EMBEDDED_PATH.findall(data)
            }
            if matches:
                found[info.filename] = sorted(matches)
    return found


def compare_wheels(left: Path, right: Path) -> dict[str, object]:
    """Classify the difference between two wheels of the same distribution."""
    left_archive = _read_archive(left)
    right_archive = _read_archive(right)
    left_members = left_archive.members
    right_members = right_archive.members

    left_sha = _sha256_file(left)
    right_sha = _sha256_file(right)

    only_left = sorted(set(left_members) - set(right_members))
    only_right = sorted(set(right_members) - set(left_members))
    shared = sorted(set(left_members) & set(right_members))

    content_differs: list[str] = []
    permission_differs: list[str] = []
    timestamp_only: list[str] = []
    compression_differs: list[str] = []
    for name in shared:
        a, b = left_members[name], right_members[name]
        if a.sha256 != b.sha256:
            content_differs.append(name)
            continue
        # Same bytes: anything below changes the container or how the member is
        # installed, not the member itself.
        if a.mode != b.mode or a.create_system != b.create_system:
            permission_differs.append(name)
        if a.compress_type != b.compress_type:
            compression_differs.append(name)
        if a.date_time != b.date_time:
            timestamp_only.append(name)

    record_differs = [
        name for name in content_differs if _RECORD_MEMBER.search(name) is not None
    ]
    # RECORD is reported in its own right, but not classified alongside the
    # members it restates, so one real difference is not double-counted.
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

    order_differs = left_archive.order != right_archive.order and not (
        only_left or only_right
    )
    comment_differs = left_archive.comment != right_archive.comment

    variance_sources: list[str] = []
    if only_left or only_right:
        variance_sources.append("member-inventory")
    if native_differs:
        variance_sources.append("native-binary-content")
    if identity_differs:
        variance_sources.append("distribution-metadata")
    if other_differs:
        variance_sources.append("member-content")
    if record_differs:
        variance_sources.append("record-metadata")
    if permission_differs:
        variance_sources.append("member-permissions")
    if compression_differs:
        variance_sources.append("compression-method")
    if order_differs:
        variance_sources.append("entry-order")
    if comment_differs:
        variance_sources.append("archive-comment")
    if timestamp_only:
        variance_sources.append("archive-timestamps")

    # A RECORD that disagrees with the members it lists, or permissions that
    # differ, change what an installer produces. Neither is container noise.
    installed_differs = bool(
        only_left or only_right or substantive or record_differs or permission_differs
    )

    if left_sha == right_sha:
        verdict = "byte-identical"
    elif only_left or only_right:
        verdict = "divergent-inventory"
    elif installed_differs:
        verdict = "divergent-content"
    else:
        # Same members, same bytes, same modes: the variance is in the
        # container, not in what gets installed.
        verdict = "semantically-identical"

    if (
        left_sha != right_sha
        and not installed_differs
        and not timestamp_only
        and not compression_differs
        and not order_differs
        and not comment_differs
    ):
        # Nothing this tool inspects accounts for the difference, so say so
        # rather than implying the variance was understood and dismissed.
        variance_sources.append("archive-container-unexplained")

    left_paths = _embedded_paths(left)
    right_paths = _embedded_paths(right)
    shared_paths = {
        name: paths
        for name, paths in left_paths.items()
        if right_paths.get(name) == paths
    }

    return {
        "schemaVersion": "mavi-wheel-reproducibility-comparison-v2",
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
        "recordDiffers": record_differs,
        "permissionDiffers": permission_differs,
        "compressionDiffers": compression_differs,
        "entryOrderDiffers": order_differs,
        "archiveCommentDiffers": comment_differs,
        "timestampOnlyDiffers": timestamp_only,
        "embeddedBuildPaths": {
            "left": left_paths,
            "right": right_paths,
            "identicalInBoth": shared_paths,
        },
        "note": (
            "A byte-identical or semantically-identical verdict is a build "
            "reproducibility result only. It is not a runtime, hardware or "
            "Production qualification. Absolute build paths present identically "
            "in both wheels still defeat relocatable reproduction."
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
    except (RuntimeError, NotImplementedError, OSError) as exc:
        print(
            json.dumps(
                {"ok": False, "code": "wheel_comparison_failed", "detail": str(exc)[:200]},
                sort_keys=True,
            )
        )
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
