"""Controlled-store acquisition for the B0 pilot: receipts, evidence and original files.

Store layout (outside every Git worktree):

    <store>/evidence/<sha256>.json      canonical provider metadata responses
    <store>/receipts/<sha256>.json      canonical admission receipts
    <store>/media/commons/<pageId>/<sha1>/<safe file name>
    <store>/source-acquisition-summary.json

Only ADMITTED_FOR_PILOT items are downloaded. Nothing here partitions, annotates,
creates ground truth, reads candidate output, or writes an F1 record.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from attributes.corpus.canonical import canonical_json, sha256_hex

from . import commons
from .admission import SUMMARY_SCHEMA, build_receipt, require_file_title
from .transport import Transport, TransportError, file_digests

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class StoreError(Exception):
    pass


def git_worktree_ancestor(path: Path) -> Path | None:
    current = path.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def assert_controlled_store(store: Path) -> Path:
    resolved = Path(store).expanduser().resolve()
    worktree = git_worktree_ancestor(resolved)
    if worktree is not None:
        raise StoreError(f"controlled store is inside the Git worktree {worktree}; refusing")
    return resolved


def safe_media_name(title: str) -> str:
    name = require_file_title(title)[len("File:"):]
    safe = _SAFE_NAME_RE.sub("_", name).strip("._")
    if not safe or safe in (".", "..") or len(safe) > 180:
        raise StoreError("unsafe media file name")
    return safe


def _retain(directory: Path, document: object) -> str:
    blob = canonical_json(document)
    identity = sha256_hex(blob)
    path = directory / f"{identity}.json"
    directory.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != blob:
            raise StoreError(f"retained record {identity} differs on disk")
    else:
        with open(path, "xb") as out:
            out.write(blob)
    return identity


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_decisions(path: Path) -> list[dict]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schemaVersion") != "mavi-s2c-source-admission-decisions-v1":
        raise StoreError("decisions file must be mavi-s2c-source-admission-decisions-v1")
    decisions = document.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise StoreError("decisions must be a non-empty list")
    titles = [require_file_title(d.get("fileTitle")) for d in decisions]
    if len(titles) != len(set(titles)):
        raise StoreError("each file may be decided once")
    return decisions


def discover(store: Path, titles: list[str], transport: Transport) -> dict:
    """Metadata-only discovery: automatic pending states and a decisions template.

    Nothing is admitted or downloaded. Each template entry names one exact file revision
    and must be completed by named human reviewers before ``acquire`` will fetch bytes.
    """
    root = assert_controlled_store(store)
    items, template = [], []
    for title in sorted(set(titles)):
        try:
            meta, raw = commons.fetch_file_metadata(transport, title)
        except (TransportError, ValueError) as exc:
            items.append({"fileTitle": title, "admissionState": None, "blockers": [], "error": str(exc)})
            continue
        evidence_sha = _retain(root / "evidence", json.loads(raw.decode("utf-8")))
        receipt = build_receipt(meta, None, evidence_sha, None)
        items.append({"fileTitle": title, "admissionState": receipt["admissionState"], "blockers": receipt["blockers"],
                      "licenceCode": receipt["licenceCode"], "declaredCaptureDate": receipt["declaredCaptureDate"],
                      "publishedAtUtc": receipt["publishedAtUtc"], "metadataEvidenceSha256": evidence_sha, "error": None})
        template.append({"fileTitle": title, "pageRevisionId": meta["pageRevisionId"], "fileSha1": meta["fileSha1"],
                         "state": None, "intendedRole": None, "siteId": None, "viewpointId": None, "reviewedBy": None,
                         "reason": None, "freshnessReferenceDate": None,
                         "capture": {"start": None, "end": None, "confidence": "unknown", "evidenceKinds": [], "evidence": None},
                         "rightsReview": {"reviewedBy": None, "determination": None, "evidence": None},
                         "privacyReview": {"reviewedBy": None, "basis": None}})
    report = {"schemaVersion": "mavi-s2c-source-discovery-report-v1", "provider": commons.PROVIDER, "items": items}
    report_sha = _retain(root / "discovery", report)
    decisions = {"schemaVersion": "mavi-s2c-source-admission-decisions-v1", "discoveryReportSha256": report_sha, "decisions": template}
    out = root / "discovery" / f"decisions-template-{report_sha[:16]}.json"
    if not out.exists():
        out.write_text(json.dumps(decisions, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return {"discoveryReportSha256": report_sha, "decisionsTemplate": out.name, "items": items}


def acquire(store: Path, decisions: list[dict], transport: Transport) -> dict:
    """Process every decision; returns the summary (also written to the store)."""
    root = assert_controlled_store(store)
    rows = []
    for decision in sorted(decisions, key=lambda d: d["fileTitle"]):
        title = decision["fileTitle"]
        row = {"fileTitle": title, "receiptSha256": None, "admissionState": None, "acquisitionStatus": None, "error": None}
        try:
            meta, raw = commons.fetch_file_metadata(transport, title)
            evidence_sha = _retain(root / "evidence", json.loads(raw.decode("utf-8")))
            preview = build_receipt(meta, decision, evidence_sha, None)
            acquisition = None
            if preview["admissionState"] == "ADMITTED_FOR_PILOT":
                acquisition = _acquire_file(root, meta, transport)
            receipt = build_receipt(meta, decision, evidence_sha, acquisition)
            row.update(receiptSha256=_retain(root / "receipts", receipt), admissionState=receipt["admissionState"],
                       acquisitionStatus=None if acquisition is None else acquisition["status"])
        except (TransportError, StoreError, ValueError) as exc:
            row.update(acquisitionStatus="FAILED", error=str(exc))
        rows.append(row)
    summary = {"schemaVersion": SUMMARY_SCHEMA, "provider": commons.PROVIDER, "items": rows,
               "counts": {s: sum(1 for r in rows if r["admissionState"] == s) for s in sorted({r["admissionState"] for r in rows if r["admissionState"]})},
               "failed": sum(1 for r in rows if r["acquisitionStatus"] == "FAILED")}
    blob = canonical_json(summary)
    target = root / "source-acquisition-summary.json"
    partial = target.with_name(target.name + ".partial")
    partial.write_bytes(blob)
    partial.replace(target)
    return summary


def _acquire_file(root: Path, meta: dict, transport: Transport) -> dict:
    relative = Path("media") / "commons" / str(meta["pageId"]) / meta["fileSha1"] / safe_media_name(meta["fileTitle"])
    target = root / relative
    if root not in target.resolve().parents:
        raise StoreError("media path escapes the controlled store")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        digests = file_digests(target)
        if digests["sha1"] != meta["fileSha1"] or digests["byteSize"] != meta["declaredByteSize"]:
            raise StoreError("existing media differs from the declared file; left untouched")
        status = "ALREADY_PRESENT_VERIFIED"
    else:
        digests = transport.download(meta["originalFileUrl"], target, meta["declaredByteSize"], meta["fileSha1"])
        status = "ACQUIRED"
    return {"status": status, "acquiredAtUtc": _utc_now(), "storeRelativePath": relative.as_posix(),
            "byteSize": digests["byteSize"], "sha1": digests["sha1"], "sha256": digests["sha256"]}


def verify(store: Path) -> list[str]:
    """Offline re-verification of every acquired file against its receipt; returns problems."""
    root = assert_controlled_store(store)
    problems = []
    for path in sorted((root / "receipts").glob("*.json")):
        blob = path.read_bytes()
        if sha256_hex(blob) != path.stem:
            problems.append(f"{path.name}: receipt identity mismatch")
            continue
        receipt = json.loads(blob)
        acquisition = receipt.get("acquisition")
        if not acquisition:
            continue
        media = root / acquisition["storeRelativePath"]
        if not media.is_file():
            problems.append(f"{receipt['fileTitle']}: media missing")
            continue
        digests = file_digests(media)
        if digests["sha1"] != acquisition["sha1"]:
            problems.append(f"{receipt['fileTitle']}: media SHA-1 differs from receipt/provider identity")
        if digests["sha256"] != acquisition["sha256"] or digests["byteSize"] != acquisition["byteSize"]:
            problems.append(f"{receipt['fileTitle']}: media bytes differ from receipt")
    return problems
