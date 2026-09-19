#!/usr/bin/env python3
"""Compare two wheels built from the same frozen inputs.

C2 must establish whether the MMCV CUDA wheel is reproducible before C3 commits
to an identity contract. A negative answer is a legitimate result -- but it must
be a measured one, naming the exact source of variance rather than being assumed
either way.

Empirically, on the frozen R1 Windows toolchain, two builds of the same MMCV
commit are *not* byte-identical: MSVC stamps a build timestamp into every object
and into the linked image, and the linker mints a fresh PDB GUID on every link.
That is metadata, not machine code -- but "that is only metadata" is a claim,
and a gate may not rest on a claim. So the native members are handed to
`native_binary_metadata`, which zeroes exactly the documented metadata fields
and compares what is left. An equivalence verdict is therefore a proof that
every differing byte lay inside a named field, not a decision to overlook the
difference.

Nothing is whitelisted by filename. `mmcv/_ext.cp312-win_amd64.pyd` gets the
same structural treatment as any other native member, and a native member that
will not parse is a refusal rather than a pass.

The tool is offline and reads only the two wheels it is given.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from native_binary_metadata import (  # noqa: E402
    ACCEPTABLE_CLASSIFICATIONS,
    compare_native_payloads,
    embedded_build_paths,
)


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
# The scan itself lives in `native_binary_metadata` because the object-tree
# comparator needs the same answer, and because the first version of it read
# `https://github.com/...` as a drive letter followed by a separator and
# reported every documentation URL in MMCV as a build path.


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
    # Native members are kept in memory so the structural comparison can run.
    # Only native members: `_ext.cp312-win_amd64.pyd` is 27 MB and the pure
    # Python members are already decided by their hashes.
    native_payloads: dict[str, bytes]
    record: bytes | None


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
        native_payloads: dict[str, bytes] = {}
        record: bytes | None = None
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
            if _is_native(info.filename):
                native_payloads[info.filename] = data
            if _RECORD_MEMBER.search(info.filename) is not None:
                record = data
        return _Archive(
            members=members,
            order=tuple(order),
            comment=archive.comment or b"",
            native_payloads=native_payloads,
            record=record,
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
            matches = embedded_build_paths(data)
            if matches:
                found[info.filename] = matches
    return found


def _record_consistency(archive: _Archive) -> dict[str, object]:
    """Check RECORD against the members it lists, inside one wheel.

    RECORD restating a member's hash means it differs whenever that member
    does. That is a consequence, not an independent defect -- but only when
    RECORD actually agrees with the wheel it ships in. A RECORD that disagrees
    installs something other than what it describes, so the two questions are
    separated here rather than collapsed into "RECORD differs".
    """
    if archive.record is None:
        return {"present": False, "consistent": None, "disagreements": []}
    disagreements: list[str] = []
    try:
        text = archive.record.decode("utf-8")
    except UnicodeDecodeError:
        return {"present": True, "consistent": False, "disagreements": ["record_not_utf8"]}
    # RECORD is CSV, not three fields split on the last two commas: a member
    # whose path contains a comma is quoted, and splitting by hand would report
    # a malformed row for a wheel that is perfectly well formed.
    listed: set[str] = set()
    for row in csv.reader(io.StringIO(text)):
        if not row or not any(field.strip() for field in row):
            continue
        if len(row) != 3:
            disagreements.append(f"record_row_malformed:{','.join(row)[:80]}")
            continue
        name, digest, size = row
        listed.add(name)
        member = archive.members.get(name)
        if member is None:
            # RECORD lists itself and the .dist-info dir with empty fields.
            if digest == "" and size == "":
                continue
            disagreements.append(f"record_member_missing:{name}")
            continue
        if digest == "" and size == "":
            continue
        if not digest.startswith("sha256="):
            disagreements.append(f"record_hash_algorithm_unsupported:{name}")
            continue
        expected = base64.urlsafe_b64encode(
            bytes.fromhex(member.sha256)
        ).rstrip(b"=").decode()
        if digest[len("sha256=") :] != expected:
            disagreements.append(f"record_hash_mismatch:{name}")
        if size != str(member.size):
            disagreements.append(f"record_size_mismatch:{name}")
    # A member the wheel ships and RECORD does not describe is installed
    # without a hash to check it against.
    for name in sorted(set(archive.members) - listed):
        if _RECORD_MEMBER.search(name) is not None:
            continue
        disagreements.append(f"record_member_unlisted:{name}")
    return {
        "present": True,
        "consistent": not disagreements,
        "disagreements": sorted(disagreements)[:32],
    }


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

    # Every native member that differs is analysed structurally. Nothing is
    # excused by name: a member is either proved to differ only in documented
    # metadata fields, or it counts against the verdict.
    native_analysis: dict[str, object] = {}
    native_normalized: list[str] = []
    native_unresolved: list[str] = []
    for name in native_differs:
        analysis = compare_native_payloads(
            left_archive.native_payloads[name],
            right_archive.native_payloads[name],
        )
        native_analysis[name] = analysis
        if analysis["classification"] in ACCEPTABLE_CLASSIFICATIONS:
            native_normalized.append(name)
        else:
            native_unresolved.append(name)

    left_record = _record_consistency(left_archive)
    right_record = _record_consistency(right_archive)
    record_inconsistent = (
        left_record["consistent"] is False or right_record["consistent"] is False
    )
    # RECORD is itself an installed file. It is excused only when a normalized
    # native member explains why it differs; a RECORD that differs on its own,
    # with every other member byte-equal, differs for a reason this tool has not
    # accounted for and must not be waved through as container noise.
    record_unexplained = bool(record_differs) and not native_normalized

    order_differs = left_archive.order != right_archive.order and not (
        only_left or only_right
    )
    comment_differs = left_archive.comment != right_archive.comment

    variance_sources: list[str] = []
    if only_left or only_right:
        variance_sources.append("member-inventory")
    if native_unresolved:
        variance_sources.append("native-binary-content")
    if native_normalized:
        variance_sources.append("native-build-metadata")
    if identity_differs:
        variance_sources.append("distribution-metadata")
    if other_differs:
        variance_sources.append("member-content")
    if record_differs:
        variance_sources.append("record-metadata")
    if record_inconsistent:
        variance_sources.append("record-inconsistent")
    if record_unexplained:
        variance_sources.append("record-unexplained")
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

    # Differences that no structural analysis accounts for. A RECORD row that
    # disagrees with the member it describes counts here: it changes what an
    # installer produces. A RECORD that merely differs *between* the two wheels
    # while agreeing with each does not -- it is restating the native metadata
    # difference one line further down.
    unresolved_members = (
        list(only_left)
        + list(only_right)
        + other_differs
        + identity_differs
        + native_unresolved
    )
    installed_differs = bool(
        unresolved_members
        or record_inconsistent
        or record_unexplained
        or permission_differs
    )

    if left_sha == right_sha:
        verdict = "byte-identical"
    elif only_left or only_right:
        verdict = "divergent-inventory"
    elif installed_differs:
        verdict = "divergent-content"
    elif native_normalized:
        # Every differing native byte was proved to lie inside a documented
        # build-metadata field. This is weaker than `semantically-identical`,
        # which requires the installed members to be byte-equal, and it is
        # named differently so no reader can mistake one for the other.
        verdict = "semantically-identical-after-native-normalization"
    else:
        # Same members, same bytes, same modes: the variance is in the
        # container, not in what gets installed.
        verdict = "semantically-identical"

    if (
        left_sha != right_sha
        and not installed_differs
        and not native_normalized
        and not record_differs
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
        "nativeContentDiffers": native_unresolved,
        "nativeMetadataNormalized": native_normalized,
        "nativeAnalysis": native_analysis,
        "recordConsistency": {"left": left_record, "right": right_record},
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
            "A byte-identical, semantically-identical or "
            "semantically-identical-after-native-normalization verdict is a "
            "Development build reproducibility result only. It is not a "
            "runtime, hardware or Production qualification, and Development "
            "evidence never satisfies a Production gate. "
            "`semantically-identical-after-native-normalization` means every "
            "differing byte in every native member was proved to lie inside a "
            "documented build-metadata field named in `nativeAnalysis`; it "
            "does not mean the wheels are interchangeable by hash. Absolute "
            "build paths present identically in both wheels still defeat "
            "relocatable reproduction."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require",
        choices=(
            "byte-identical",
            "semantically-identical",
            "semantically-identical-after-native-normalization",
        ),
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
        "semantically-identical-after-native-normalization": {
            "byte-identical",
            "semantically-identical",
            "semantically-identical-after-native-normalization",
        },
    }[args.require]
    return 0 if result["verdict"] in accepted else 3


if __name__ == "__main__":
    raise SystemExit(main())
