#!/usr/bin/env python3
"""Freeze reviewer decisions and adjudicate the overlap, blind to every prediction (Stage 3, S3.2 plan T5).

Commands::

    freeze --pack <dir> --decisions <draft> --reviewer-name <n> --reviewer-role <r>
           --reviewed-on <YYYY-MM-DD> --out <file>
    adjudicate-prepare --primary <labels> --overlap <labels> --pack <primary-pack-dir> --out <new-dir>
    adjudicate --primary <labels> --overlap <labels> --decisions <file> --adjudicator <n>
               --adjudicated-on <YYYY-MM-DD> --out <file>

None of the commands accepts an export, a measurement result or an attestation:
their only inputs are a verified pack, frozen label files and human decisions, none
of which carries a prediction or confidence. ``reviewedOn``/``adjudicatedOn`` are
declared facts supplied by the operator, never generated.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artefacts as a  # noqa: E402
from build_labeling_pack import PACK_DATA, verify_pack  # noqa: E402

LABELS_SCHEMA = "vehicle-subclass-track-labels-v1"
ADJUDICATION_SCHEMA = "vehicle-subclass-adjudication-v1"
ADJUDICATION_DATA = "adjudication-data.js"


def _date(value: str, code: str) -> str:
    a.require(isinstance(value, str) and a.DATE_RE.fullmatch(value), code)
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise a.S32Error(code) from exc
    return value


def _human(label: object, reason: object, code: str) -> dict[str, str]:
    """A label with its unknown reason: required exactly when the label is ``unknown``."""
    a.require(label in a.LABELS, f"{code}:label")
    if label == a.UNKNOWN:
        a.require(reason is not None, f"{code}:unknown_without_reason")
        a.require(reason in a.UNKNOWN_REASONS, f"{code}:reason")
        return {"label": label, "unknownReason": reason}
    a.require(reason is None, f"{code}:reason_without_unknown")
    return {"label": label}


# freeze


def freeze(pack_dir: Path, draft_path: Path, reviewer_name: str, reviewer_role: str, reviewed_on: str) -> bytes:
    manifest, pack_sha = verify_pack(pack_dir)
    draft = a.parse_json(a.read_bytes(draft_path, "draft_unreadable"), "draft_unreadable")
    a.require(isinstance(draft, dict) and set(draft) == {"packSha256", "reviewerName", "decisions"}, "draft_invalid")
    a.require(draft["packSha256"] == pack_sha, "draft_pack_mismatch")
    name = a.text_value(reviewer_name, "reviewer_invalid", 120)
    role = a.text_value(reviewer_role, "reviewer_invalid", 120)
    a.require(draft["reviewerName"] == name, "draft_reviewer_mismatch")
    reviewed_on = _date(reviewed_on, "reviewed_on_invalid")

    items = {item["itemId"]: item for item in manifest["items"]}
    decisions: dict[str, dict[str, Any]] = {}
    a.require(isinstance(draft["decisions"], list), "draft_invalid")
    for decision in draft["decisions"]:
        a.require(isinstance(decision, dict) and set(decision) <= {"itemId", "label", "unknownReason", "note"}
                  and "itemId" in decision and "label" in decision, "decision_invalid")
        item_id = decision["itemId"]
        a.require(item_id in items, "decision_item_not_in_pack")
        a.require(item_id not in decisions, "decision_duplicate")
        human = _human(decision["label"], decision.get("unknownReason"), "decision_vocabulary")
        if "note" in decision:
            human["note"] = a.text_value(decision["note"], "decision_note_invalid", a.NOTE_MAX)
        item = items[item_id]
        decisions[item_id] = {"itemId": item_id, "processingRunId": item["processingRunId"], "trackId": item["trackId"],
                              "videoSourceSha256": item["videoSourceSha256"], **human}
    a.require(set(decisions) == set(items), "decision_missing")

    document: dict[str, Any] = {
        "schemaVersion": LABELS_SCHEMA,
        "packSha256": pack_sha,
        "viewKind": manifest["viewKind"],
        "labelingGuideSha256": manifest["labelingGuide"]["sha256"],
        "sampleSha256": manifest["sampleSha256"],
        "exportSha256s": manifest["exportSha256s"],
        "reviewer": {"name": name, "role": role},
        "reviewedOn": reviewed_on,
        "vocabulary": a.LABEL_VOCABULARY,
        "decisions": sorted(decisions.values(), key=lambda d: (d["processingRunId"], d["trackId"])),
    }
    if manifest["viewKind"] == "overlap":
        document["parentPackSha256"] = manifest["parentPackSha256"]
    a.validate(document, LABELS_SCHEMA, "labels_invalid")
    return a.canonical_json(document)


# adjudication


def session_id(primary_sha: str, overlap_sha: str) -> str:
    """The adjudication session: one exact frozen primary/overlap pair, nothing else."""
    return a.h("mavi-s32-adjudication-session", primary_sha, overlap_sha)


def read_labels(path: Path, code: str) -> tuple[dict[str, Any], str]:
    document, _, sha = a.read_artefact(path, LABELS_SCHEMA, code)
    return document, sha


def pair_labels(primary_path: Path, overlap_path: Path) -> tuple[dict[str, Any], str, dict[str, Any], str]:
    """Two frozen label files that are a primary and its derived overlap view."""
    primary, primary_sha = read_labels(primary_path, "labels_not_frozen")
    overlap, overlap_sha = read_labels(overlap_path, "labels_not_frozen")
    a.require(primary["viewKind"] == "primary" and overlap["viewKind"] == "overlap"
              and overlap["parentPackSha256"] == primary["packSha256"], "overlap_pack_not_derived")
    a.require(overlap["sampleSha256"] == primary["sampleSha256"], "overlap_pack_not_derived:sample")
    a.require(overlap["labelingGuideSha256"] == primary["labelingGuideSha256"], "labeling_guide_mismatch")
    primary_by_track = {(d["processingRunId"], d["trackId"]): d for d in primary["decisions"]}
    for decision in overlap["decisions"]:
        a.require((decision["processingRunId"], decision["trackId"]) in primary_by_track, "adjudication_coverage_mismatch")
    return primary, primary_sha, overlap, overlap_sha


def _comparison(primary: dict[str, Any], overlap: dict[str, Any]) -> list[dict[str, Any]]:
    """Per overlap Track: both human decisions, and whether they agree well enough to carry."""
    primary_by_track = {(d["processingRunId"], d["trackId"]): d for d in primary["decisions"]}
    rows = []
    for decision in overlap["decisions"]:
        first = primary_by_track[(decision["processingRunId"], decision["trackId"])]
        p = _human(first["label"], first.get("unknownReason"), "labels_invalid")
        o = _human(decision["label"], decision.get("unknownReason"), "labels_invalid")
        rows.append({"primaryItemId": first["itemId"], "processingRunId": decision["processingRunId"],
                     "trackId": decision["trackId"], "primary": p, "overlap": o,
                     "primaryNote": first.get("note"), "overlapNote": decision.get("note"),
                     "carried": p == o})
    return rows


def adjudicate_prepare(primary_path: Path, overlap_path: Path, pack_dir: Path, staging: Path) -> None:
    primary, primary_sha, overlap, overlap_sha = pair_labels(primary_path, overlap_path)
    manifest, pack_sha = verify_pack(pack_dir)
    a.require(pack_sha == primary["packSha256"], "adjudication_pack_mismatch")
    # The adjudicator's copy: the reviewer-visible files of the primary pack only (no manifest,
    # so not even the hidden run/Track mapping), plus both human decisions.
    for entry in manifest["files"]:
        target = staging / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(pack_dir) / entry["path"], target)
    shutil.copyfile(Path(pack_dir) / PACK_DATA, staging / PACK_DATA)
    items = []
    for row in _comparison(primary, overlap):
        entry = {"itemId": row["primaryItemId"], "primary": dict(row["primary"]), "overlap": dict(row["overlap"]),
                 "needsDecision": not row["carried"]}
        for side in ("primary", "overlap"):
            if row[f"{side}Note"]:
                entry[side]["note"] = row[f"{side}Note"]
        items.append(entry)
    payload = {"packSha256": pack_sha, "primaryLabelsSha256": primary_sha, "overlapLabelsSha256": overlap_sha,
               "sessionId": session_id(primary_sha, overlap_sha), "items": sorted(items, key=lambda item: item["itemId"])}
    (staging / ADJUDICATION_DATA).write_bytes(b"window.MAVI_ADJUDICATION = " + a.canonical_json(payload) + b";\n")


def adjudicate(primary_path: Path, overlap_path: Path, decisions_path: Path, adjudicator: str, adjudicated_on: str) -> bytes:
    primary, primary_sha, overlap, overlap_sha = pair_labels(primary_path, overlap_path)
    decisions = a.parse_json(a.read_bytes(decisions_path, "adjudication_decisions_unreadable"), "adjudication_decisions_unreadable")
    a.require(isinstance(decisions, dict)
              and set(decisions) == {"primaryLabelsSha256", "overlapLabelsSha256", "sessionId", "decisions"}
              and isinstance(decisions["decisions"], list), "adjudication_decisions_invalid")
    # Decisions made for another frozen pair (even of the same pack) are never reused.
    a.require(decisions["sessionId"] == session_id(primary_sha, overlap_sha), "adjudication_session_mismatch")
    a.require(decisions["primaryLabelsSha256"] == primary_sha and decisions["overlapLabelsSha256"] == overlap_sha,
              "adjudication_decisions_mismatch")
    name = a.text_value(adjudicator, "adjudicator_invalid", 120)
    adjudicated_on = _date(adjudicated_on, "adjudicated_on_invalid")

    rows = {row["primaryItemId"]: row for row in _comparison(primary, overlap)}
    given: dict[str, dict[str, Any]] = {}
    for decision in decisions["decisions"]:
        a.require(isinstance(decision, dict) and set(decision) <= {"itemId", "adjudicatedLabel", "adjudicatedUnknownReason"}
                  and "itemId" in decision and "adjudicatedLabel" in decision, "adjudication_decisions_invalid")
        item_id = decision["itemId"]
        a.require(item_id in rows, "adjudication_item_unknown")
        a.require(item_id not in given, "adjudication_decision_duplicate")
        a.require(not rows[item_id]["carried"], "adjudication_decision_unexpected")
        given[item_id] = decision

    items = []
    for item_id, row in rows.items():
        if row["carried"]:
            final = dict(row["primary"])
            resolution = "carried"
        else:
            decision = given.get(item_id)
            a.require(decision is not None, "adjudication_decision_missing")
            label = decision["adjudicatedLabel"]
            a.require(label in a.LABELS, "adjudication_label_invalid")
            reason = decision.get("adjudicatedUnknownReason")
            if label == a.UNKNOWN:
                a.require(reason is not None, "adjudication_reason_missing")
                a.require(reason in a.UNKNOWN_REASONS, "adjudication_reason_invalid")
                final = {"label": label, "unknownReason": reason}
            else:
                a.require(reason is None, "adjudication_reason_not_allowed")
                final = {"label": label}
            resolution = "adjudicated"
        item = {"processingRunId": row["processingRunId"], "trackId": row["trackId"],
                "primary": row["primary"], "overlap": row["overlap"],
                "adjudicatedLabel": final["label"], "resolution": resolution}
        if "unknownReason" in final:
            item["adjudicatedUnknownReason"] = final["unknownReason"]
        items.append(item)

    document = {
        "schemaVersion": ADJUDICATION_SCHEMA,
        "primaryLabelsSha256": primary_sha,
        "overlapLabelsSha256": overlap_sha,
        "adjudicator": name,
        "adjudicatedOn": adjudicated_on,
        "vocabulary": a.LABEL_VOCABULARY,
        "items": sorted(items, key=lambda item: (item["processingRunId"], item["trackId"])),
    }
    a.validate(document, ADJUDICATION_SCHEMA, "adjudication_invalid")
    return a.canonical_json(document)


# CLI


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = p.add_subparsers(dest="command", required=True)
    f = commands.add_parser("freeze")
    f.add_argument("--pack", type=Path, required=True)
    f.add_argument("--decisions", type=Path, required=True)
    f.add_argument("--reviewer-name", required=True)
    f.add_argument("--reviewer-role", required=True)
    f.add_argument("--reviewed-on", required=True)
    f.add_argument("--out", type=Path, required=True)
    prepare = commands.add_parser("adjudicate-prepare")
    prepare.add_argument("--primary", type=Path, required=True)
    prepare.add_argument("--overlap", type=Path, required=True)
    prepare.add_argument("--pack", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    adjudication = commands.add_parser("adjudicate")
    adjudication.add_argument("--primary", type=Path, required=True)
    adjudication.add_argument("--overlap", type=Path, required=True)
    adjudication.add_argument("--decisions", type=Path, required=True)
    adjudication.add_argument("--adjudicator", required=True)
    adjudication.add_argument("--adjudicated-on", required=True)
    adjudication.add_argument("--out", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "freeze":
            a.require(not args.out.exists(), "output_exists")
            data = freeze(args.pack, args.decisions, args.reviewer_name, args.reviewer_role, args.reviewed_on)
            a.write_once(args.out, data)
            print(a.sha256_hex(data))
        elif args.command == "adjudicate-prepare":
            with a.OutputDirectory(args.out) as staging:
                adjudicate_prepare(args.primary, args.overlap, args.pack, staging)
            print(args.out)
        else:
            a.require(not args.out.exists(), "output_exists")
            data = adjudicate(args.primary, args.overlap, args.decisions, args.adjudicator, args.adjudicated_on)
            a.write_once(args.out, data)
            print(a.sha256_hex(data))
    except a.S32Error as exc:
        print(f"refused {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
