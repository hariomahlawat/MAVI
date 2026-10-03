"""The T9 ingestion map (S3.2 plan T9): ``vehicle-subclass-ingestion-map-v1`` checks.

Every check here runs before T9 makes any API call. The map is the only source of T9's
camera, time-zone and recording-start values; it is committed (or its digest committed)
before the first import and bound to the frozen source pool by ``sourcePoolSha256``.

Zones are validated with Python's ``zoneinfo`` over the declared ``tzdata`` package. MAVI's
own check (``SystemTimeZoneService``) additionally needs a .NET IANA→Windows mapping; a zone
that ``tzdata`` lists but .NET cannot map would still be refused by the API, never accepted
silently.
"""

from __future__ import annotations

import re
import zoneinfo
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import artefacts as a
import release_bridge as rb

SCHEMA = "vehicle-subclass-ingestion-map-v1"
CODE = "ingestion_map_invalid"
CONVENTION_GIT_PATH = "docs/qualification/stage3/s3-2-ingestion-convention.md"
CODE_PREFIX = "S32-"
CODE_MAX = 32
_LOCAL = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_NOT_ZONES = frozenset({"Factory", "localtime", "posixrules"})


def camera_code(source_camera: str) -> str:
    """``S32-`` + the source camera upper-cased, every character outside A–Z, 0–9 and ``-``
    replaced by ``-``, truncated to MAVI's 32-character limit."""
    body = "".join(c if ("A" <= c <= "Z" or "0" <= c <= "9" or c == "-") else "-" for c in source_camera.upper())
    return (CODE_PREFIX + body)[:CODE_MAX]


def valid_zone(zone: object) -> bool:
    if not isinstance(zone, str) or zone in _NOT_ZONES or zone.startswith(("posix/", "right/")):
        return False
    if zone not in zoneinfo.available_timezones():
        return False
    try:
        zoneinfo.ZoneInfo(zone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return False
    return True


def local_time_problem(value: str, zone: str) -> str | None:
    """``malformed``, ``nonexistent`` or ``ambiguous`` in ``zone``; ``None`` when MAVI's import accepts it."""
    if not _LOCAL.fullmatch(value):
        return "malformed"
    try:
        local = datetime.fromisoformat(value)
    except ValueError:
        return "malformed"
    tz = zoneinfo.ZoneInfo(zone)
    first, second = local.replace(tzinfo=tz, fold=0), local.replace(tzinfo=tz, fold=1)
    # A wall time inside a forward gap does not survive a round trip through UTC.
    if first.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != local:
        return "nonexistent"
    if first.utcoffset() != second.utcoffset():
        return "ambiguous"
    return None


def recording_start_utc(value: str, zone: str) -> datetime:
    """The UTC instant MAVI's import derives from a valid ``recordingStartLocal`` in ``zone``."""
    return datetime.fromisoformat(value).replace(tzinfo=zoneinfo.ZoneInfo(zone)).astimezone(timezone.utc)


def committed_blob(repository: Path, commit: str, git_path: str, sha256: str, code: str) -> None:
    """The file at ``git_path`` in ``commit`` hashes to ``sha256`` and ``commit`` is an ancestor of HEAD."""
    a.require(isinstance(commit, str) and a.COMMIT_RE.fullmatch(commit), f"{code}:commit")
    shown = a._git(repository, "show", f"{commit}:{git_path}")
    a.require(shown.returncode == 0, f"{code}:not_in_commit")
    a.require(a.sha256_hex(shown.stdout) == sha256, f"{code}:differs_from_commit")
    ancestor = a._git(repository, "merge-base", "--is-ancestor", commit, "HEAD")
    a.require(ancestor.returncode == 0, f"{code}:not_ancestor_of_head")


def check(document: dict[str, Any], *, pool: dict[str, Any], pool_sha256: str, release: dict[str, Any],
          release_sha256: str, repository: Path) -> dict[str, dict[str, Any]]:
    """Validates the map against the pool and release; returns cameras keyed by ``cameraCode``."""
    a.validate(document, SCHEMA, CODE)
    a.require(document["sourcePoolSha256"] == pool_sha256, f"{CODE}:source_pool")

    cameras: dict[str, dict[str, Any]] = {}
    by_source: dict[str, str] = {}
    for camera in document["cameras"]:
        # Both are copied into the canonical T9 record: the repository's free-text and local-path rules apply.
        rb.free_text(camera["name"], f"{CODE}:camera_name", 128)
        rb.free_text(camera["sourceCamera"], f"{CODE}:source_camera", 200)
        a.require(camera["cameraCode"] not in cameras, f"{CODE}:duplicate_camera_code")
        a.require(camera["sourceCamera"] not in by_source, f"{CODE}:duplicate_source_camera")
        a.require(camera["cameraCode"] == camera_code(camera["sourceCamera"]), f"{CODE}:camera_code")
        a.require(valid_zone(camera["timeZoneId"]), f"{CODE}:time_zone")
        cameras[camera["cameraCode"]] = camera
        by_source[camera["sourceCamera"]] = camera["cameraCode"]

    pool_members = {member["member"]: member for member in pool["members"]}
    a.require(set(by_source) == {member["sourceCamera"] for member in pool["members"]}, f"{CODE}:cameras")
    seen: set[str] = set()
    listed = {entry["path"] for entry in release["files"]} - {entry["path"] for entry in release["excludedMembers"]}
    for entry in document["members"]:
        name = entry["member"]
        a.require(name not in seen, f"{CODE}:duplicate_member")
        seen.add(name)
        a.require(name in pool_members, f"{CODE}:extra_member")
        a.require(entry["cameraCode"] in cameras, f"{CODE}:unknown_camera")
        a.require(entry["cameraCode"] == by_source[pool_members[name]["sourceCamera"]], f"{CODE}:member_camera")
        problem = local_time_problem(entry["recordingStartLocal"], cameras[entry["cameraCode"]]["timeZoneId"])
        a.require(problem is None, f"{CODE}:recording_start_{problem}")
        recording = entry["recordingTime"]
        if recording["source"] == "release-metadata":
            evidence = recording["evidence"]
            a.require(evidence["releaseRecordSha256"] == release_sha256 == pool["releaseRecordSha256"],
                      f"{CODE}:release_evidence")
            a.require(evidence["member"] in listed, f"{CODE}:release_evidence")
        else:
            convention = recording["convention"]
            committed_blob(repository, convention["gitCommit"], convention["gitPath"], convention["sha256"],
                           f"{CODE}:convention")
    a.require(seen == set(pool_members), f"{CODE}:missing_member")
    return cameras
