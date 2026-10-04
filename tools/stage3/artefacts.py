"""Shared rules for every Stage 3 S3.2 measurement artefact (plan §5).

One canonical form, the same bytes the T1 .NET exporter writes:
UTF-8 without a byte-order mark, object members sorted at every depth, no
insignificant whitespace (and no trailing newline), non-ASCII characters written
as themselves, round-trip number formatting, no NaN or infinity. An artefact's
identity is the SHA-256 of those bytes. Nothing here generates a timestamp.

Other S3.2 rules live here too, so the five tools cannot drift apart: write-once
output, strict JSON reading (duplicate keys refused), schema validation against
``contracts/schemas``, the git binding of pre-registered files, the measurement
export loader (T1's ``vehicle-subclass-measurement-export-v1``), and the human
label vocabulary.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from functools import cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts" / "schemas"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Human label vocabulary (plan §5). These are review decisions, not ObjectSubclass values.
LABEL_VOCABULARY = "mavi-vehicle-subclass-labels-v1"
CLASSES = ("car", "truck", "bus", "motorcycle")
UNKNOWN = "unknown"
LABELS = (*CLASSES, UNKNOWN)
UNKNOWN_REASONS = ("occluded", "too-small", "ambiguous-type", "mixed-track", "not-a-vehicle", "other")
NOTE_MAX = 200
REASON_MAX = 200

# MAVI's outcome on a Track: a v1 value, or the vote abstained.
UNDETERMINED = "undetermined"
OUTCOMES = (*CLASSES, UNDETERMINED)

REQUIREMENTS_GIT_PATH = "docs/qualification/stage3/s3-2-subclass-requirements.json"
LABELING_GUIDE_GIT_PATH = "docs/qualification/stage3/s3-2-labeling-guide.md"
# The S3.2 pre-registration (PR #156, first on main at d520db1034b4eb63ddd077f5e4df3b8d0f4e33d9; register G1/G2):
# the only requirements and labelling-guide bytes T3 and T4 accept, at that commit or any later ancestor of HEAD
# carrying the same bytes. A later revision is a new governed pre-registration (fresh sample, packs and labels,
# plan §13) and changes these identities explicitly in a reviewed commit.
REGISTERED_REQUIREMENTS_SHA256 = "ca28702f82c6845298a2cf348d7b057024923c7a0a0f4fd496097bf1b7272d75"
REGISTERED_LABELING_GUIDE_SHA256 = "c5f8be38be9977ea05692e1e9d45d4ca7ea9b200629316f6375640778a251fc5"
REGISTERED_SHA256 = {REQUIREMENTS_GIT_PATH: REGISTERED_REQUIREMENTS_SHA256,
                     LABELING_GUIDE_GIT_PATH: REGISTERED_LABELING_GUIDE_SHA256}
EXPORT_FILE_NAME = "subclass-measurement-export.json"
SCOPE = (
    "This measurement is Track-conditional. It evaluates subclass classification given that "
    "MAVI produced the Track. It is not an end-to-end detection or tracking accuracy measurement. "
    "Development/evaluation evidence; not frozen qualification."
)


class S32Error(ValueError):
    """A refusal. The message starts with a stable code (``code`` or ``code:detail``)."""

    @property
    def code(self) -> str:
        return str(self).split(":", 1)[0]


def require(condition: object, code: str) -> None:
    if not condition:
        raise S32Error(code)


# Canonical bytes


def canonical_json(document: object) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def document_sha256(document: object) -> str:
    return sha256_hex(canonical_json(document))


def h(*parts: str) -> str:
    """The plan's ``h(a‖b‖…)``: SHA-256 hex of the UTF-8 parts joined by a line feed."""
    return sha256_hex("\n".join(parts).encode("utf-8"))


def canonical_text(data: bytes, code: str) -> bytes:
    """A text asset as UTF-8 without BOM and LF line endings (CRLF and CR become LF)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise S32Error(code) from exc
    text = text.removeprefix("﻿")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


# Strict reading


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise S32Error(f"json_duplicate_key:{key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise S32Error(f"json_non_finite:{value}")


def parse_json(data: bytes, code: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S32Error(code) from exc


def read_bytes(path: Path, code: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise S32Error(f"{code}:{Path(path).name}") from exc


def read_artefact(path: Path, schema: str, code: str) -> tuple[dict[str, Any], bytes, str]:
    """A canonical artefact: (document, exact bytes, SHA-256). Non-canonical bytes are refused."""
    data = read_bytes(path, code)
    document = parse_json(data, code)
    validate(document, schema, code)
    require(canonical_json(document) == data, f"{code}:not_canonical")
    return document, data, sha256_hex(data)


# Schemas


@cache
def _validator(schema: str):
    import jsonschema

    document = json.loads((SCHEMAS / f"{schema}.schema.json").read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(document, format_checker=jsonschema.FormatChecker())


def validate(document: object, schema: str, code: str) -> None:
    error = next(iter(_validator(schema).iter_errors(document)), None)
    if error is not None:
        where = "/".join(str(part) for part in error.absolute_path)
        raise S32Error(f"{code}:schema:{where}")


# Write once


def write_once(path: Path, data: bytes, code: str = "output_exists") -> None:
    """Writes a file that did not exist; a crash leaves no file at ``path``."""
    path = Path(path)
    require(not path.exists(), code)
    require(path.parent.is_dir(), "output_parent_missing")
    temporary = path.parent / f".{path.name}.partial-{uuid.uuid4().hex}"
    try:
        temporary.write_bytes(data)
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise S32Error(code) from exc
        except OSError:
            # No hard links on this volume: exclusive create, then write.
            try:
                with open(path, "xb") as stream:
                    stream.write(data)
            except FileExistsError as exc:
                raise S32Error(code) from exc
    finally:
        temporary.unlink(missing_ok=True)


class OutputDirectory:
    """A new output directory built in a hidden sibling and moved into place only on success."""

    def __init__(self, target: Path, code: str = "output_exists") -> None:
        self.target = Path(target)
        require(not self.target.exists(), code)
        require(self.target.parent.is_dir(), "output_parent_missing")
        self.code = code
        self.staging = self.target.parent / f".{self.target.name}.partial-{uuid.uuid4().hex}"

    def __enter__(self) -> Path:
        self.staging.mkdir()
        return self.staging

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            if self.target.exists():
                shutil.rmtree(self.staging, ignore_errors=True)
                raise S32Error(self.code)
            os.rename(self.staging, self.target)
        else:
            shutil.rmtree(self.staging, ignore_errors=True)
        return False


def write_text_file(directory: Path, relative: str, data: bytes) -> None:
    target = directory / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def safe_relative(path: str, code: str) -> str:
    """A relative, forward-slashed path with no traversal; the only form artefacts store."""
    require(isinstance(path, str) and path and not path.startswith("/") and "\\" not in path and ":" not in path, code)
    require(all(part not in ("", ".", "..") for part in path.split("/")), code)
    return path


# Git binding of pre-registered files


def _git(repository: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(repository), *args], capture_output=True, check=False)


def git_binding(repository: Path, file: Path, commit: str, git_path: str, code: str) -> dict[str, str]:
    """``file`` must be byte-identical to ``git show <commit>:<git_path>`` and ``commit`` an ancestor of HEAD."""
    require(isinstance(commit, str) and COMMIT_RE.fullmatch(commit), f"{code}:commit")
    data = read_bytes(file, code)
    shown = _git(repository, "show", f"{commit}:{git_path}")
    require(shown.returncode == 0, f"{code}:not_in_commit")
    require(shown.stdout == data, f"{code}:differs_from_commit")
    ancestor = _git(repository, "merge-base", "--is-ancestor", commit, "HEAD")
    require(ancestor.returncode == 0, f"{code}:not_ancestor_of_head")
    return {"gitCommit": commit, "gitPath": git_path, "sha256": sha256_hex(data)}


def require_preregistered(binding: dict[str, str], code: str) -> None:
    """A git binding is also the registered S3.2 identity for its path: a caller-selected later commit carrying
    different bytes is refused even though ``git_binding`` accepts it."""
    require(binding["sha256"] == REGISTERED_SHA256.get(binding["gitPath"]), code)


# Measurement exports (T1)


class Export:
    """One T1 export, read from its exact bytes. Evidence paths resolve from its directory."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.directory = self.path.parent
        self.data = read_bytes(self.path, "export_unreadable")
        self.sha256 = sha256_hex(self.data)
        self.document = parse_json(self.data, "export_unreadable")
        # Identity is the SHA-256 of T1's exact bytes; Python never re-canonicalises an export
        # (.NET and Python format some numbers differently, e.g. ``1E-05`` and ``1e-05``).
        validate(self.document, "vehicle-subclass-measurement-export-v1", "export_invalid")
        run = self.document["processingRun"]
        require(run["attestation"]["processingRunId"] == run["processingRunId"], "export_invalid:attestation_run")
        require(run["attestation"]["videoAssetId"] == run["videoAssetId"] == self.document["video"]["videoAssetId"],
                "export_invalid:video")
        require(self.document["profile"]["pipelineProfileSha256"] == run["attestation"]["pipelineProfileSha256"],
                "export_invalid:profile")
        ids = [track["id"] for track in self.document["tracks"]]
        require(len(ids) == len(set(ids)), "export_invalid:duplicate_track")

    @property
    def run_id(self) -> str:
        return self.document["processingRun"]["processingRunId"]

    @property
    def video(self) -> dict[str, Any]:
        return self.document["video"]

    @property
    def attestation(self) -> dict[str, Any]:
        return self.document["processingRun"]["attestation"]

    @property
    def tracks(self) -> list[dict[str, Any]]:
        return self.document["tracks"]

    def track(self, track_id: str) -> dict[str, Any] | None:
        return next((track for track in self.tracks if track["id"] == track_id), None)

    def evidence_bytes(self, observation: dict[str, Any]) -> bytes | None:
        """The observation's evidence bytes when they verify; ``None`` when missing or changed."""
        relative = safe_relative(observation["evidencePath"], "export_invalid:evidence_path")
        try:
            data = (self.directory / relative).read_bytes()
        except OSError:
            return None
        sha = sha256_hex(data)
        if sha != observation["evidenceSha256"] or len(data) != observation["evidenceSizeBytes"]:
            return None
        return data

    def require_evidence(self, observation: dict[str, Any]) -> bytes:
        data = self.evidence_bytes(observation)
        require(data is not None, "export_evidence_mismatch")
        return data


def load_exports(paths: list[Path]) -> dict[str, Export]:
    """Exports keyed by their SHA-256; one per run, and one run per video. Two runs of one video asset or
    of one source (a reprocessing) would count the same scene twice, so they are refused."""
    exports: dict[str, Export] = {}
    runs: set[str] = set()
    videos: set[str] = set()
    sources: set[str] = set()
    for path in paths:
        export = Export(path)
        require(export.sha256 not in exports, "export_duplicate")
        require(export.run_id not in runs, "export_run_duplicate")
        require(export.video["videoAssetId"] not in videos and export.video["sourceSha256"] not in sources,
                "export_video_duplicate")
        exports[export.sha256] = export
        runs.add(export.run_id)
        videos.add(export.video["videoAssetId"])
        sources.add(export.video["sourceSha256"])
    return exports


def text_value(value: object, code: str, maximum: int) -> str:
    require(isinstance(value, str) and value.strip() == value and 0 < len(value) <= maximum, code)
    require("\n" not in value and "\r" not in value, code)
    return value
