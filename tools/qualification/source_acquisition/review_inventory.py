"""B0 review inventory: metadata-only triage of described candidates (Development only).

Builds one review inventory from explicitly supplied, verified recorded-discovery evidence
bundles. It is local only: it opens no socket, reads each bundle's bytes once, verifies them
against the bundle's checksum, its manifest and an operator-supplied archive SHA-256 pin, and
never writes inside a bundle. Output goes to a new directory that must not exist.

This is triage, not B0 review. Every candidate is DESCRIBED; none is REVIEWED, ADMISSIBLE or
FROZEN_QUALIFICATION here, and every review field is null. Triage uses retained Commons
metadata and titles only. Title rules describe what a title says; they never establish a
visual property, a location or a capture date.

Inputs that carry judgement are explicit and hashed into the output:
- the provisional freshness reference (recorded as PROVISIONAL, never as a decision);
- an optional title-judgements file (``mavi-s2c-b0-title-judgements-v1``) of regex rules,
  each with a closed-vocabulary code and a reason.

The output is deterministic: identical bundles, inputs and code give identical bytes.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
import tarfile
from datetime import date
from pathlib import Path

from attributes.corpus.canonical import canonical_json, sha256_hex

from . import admission, commons
from .acquire import StoreError, assert_controlled_store
from .recorded_discovery import _verify_archive

INVENTORY_SCHEMA = "mavi-s2c-b0-review-inventory-v2"
JUDGEMENTS_SCHEMA = "mavi-s2c-b0-title-judgements-v1"
PROPOSALS_SCHEMA = "mavi-s2c-b0-proposed-metadata-decisions-v1"
TEMPLATE_SCHEMA = "mavi-s2c-source-admission-decisions-v1"

# Generic, corpus-independent title rules. Corpus-specific judgements come from the judgements file.
GENERIC_TITLE_RULES = (
    ("TITLE_TIMELAPSE", r"time-?lapse", "title states a time-lapse; not continuous real-time video for tracking"),
    ("TITLE_ARCHIVAL_YEAR", r"\((1[89]\d\d)\)|\b(19[0-7]\d)\b", "title names a year before 1980; archival footage"),
)
JUDGEMENT_CODES = frozenset({
    "TITLE_TIMELAPSE", "TITLE_ARCHIVAL_YEAR", "TITLE_EVENT_SERIES", "TITLE_BILLBOARD", "TITLE_STRUCTURE",
    "TITLE_TREE_WORK", "TITLE_FEATURE_FILM", "TITLE_NEWSREEL", "TITLE_NOT_A_SCENE",
})
# Title codes that, together with an objective freshness exclusion, make a file clearly unsuitable.
EXCLUDING_CODES = frozenset({"TITLE_TIMELAPSE", "TITLE_ARCHIVAL_YEAR", "TITLE_FEATURE_FILM", "TITLE_NEWSREEL", "TITLE_TREE_WORK"})
INDIA_HINT = re.compile(r"India|Kolkata|Howrah|Bombay|Narmada|TGSRTC|Holi|Iftar", re.I)
STREET_HINT = re.compile(r"street|traffic|Holi|Iftar|TGSRTC|bus|road|freeway|cars|avtocesta|allee|cityscape|Alfama|Sintra|Moscow|Boston", re.I)
PRIMARY_ORDER = ("CLEARLY_UNSUITABLE", "NON_OPERATIONAL_REFERENCE_ONLY",
                 "LIKELY_UNSUITABLE_TITLE_NEEDS_VISUAL_CONFIRMATION", "PLAUSIBLE_NEEDS_VISUAL_REVIEW")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _date(text: object) -> date | None:
    if not isinstance(text, str):
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def read_bundle(evidence_dir: Path, name: str, expected_archive_sha256: str) -> dict:
    """Read a bundle's bytes once and verify them: checksum file, operator pin and every manifest member."""
    if not _SHA256.match(expected_archive_sha256 or ""):
        raise StoreError(f"{name}: the expected archive SHA-256 must be 64 lower-case hex digits")
    evidence_dir = Path(evidence_dir)
    archive_bytes = (evidence_dir / f"{name}.tar.gz").read_bytes()
    manifest_bytes = (evidence_dir / "MANIFEST.json").read_bytes()
    recorded = (evidence_dir / f"{name}.tar.gz.sha256").read_text(encoding="ascii").split()[0]
    actual = sha256_hex(archive_bytes)
    if actual != recorded:
        raise StoreError(f"{name}: archive SHA-256 differs from the bundle's checksum file")
    if actual != expected_archive_sha256:
        raise StoreError(f"{name}: archive SHA-256 differs from the supplied pin")
    _verify_archive(archive_bytes, manifest_bytes, name)
    members, prefix = {}, name + "/"
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            members[member.name[len(prefix):]] = tar.extractfile(member).read()
    for required in ("config/run-config.json", "capture/scopes.jsonl"):
        if required not in members:
            raise StoreError(f"{name}: bundle has no {required}")
    manifest = json.loads(manifest_bytes)
    return {"name": name, "archiveSha256": actual, "manifestSha256": sha256_hex(manifest_bytes), "run": manifest["run"],
            "runConfigSha256": sha256_hex(members["config/run-config.json"]), "members": members}


def load_judgements(path: Path | None) -> tuple[list[dict], str | None]:
    """Validated title-judgement rules and the SHA-256 of the file's bytes (None when absent)."""
    if path is None:
        return [], None
    raw = Path(path).read_bytes()
    document = json.loads(raw)
    if not isinstance(document, dict) or document.get("schema") != JUDGEMENTS_SCHEMA or not isinstance(document.get("rules"), list):
        raise StoreError(f"title judgements must be a {JUDGEMENTS_SCHEMA} document with a rules list")
    rules = []
    for rule in document["rules"]:
        if not isinstance(rule, dict) or set(rule) != {"code", "titlePattern", "reason"}:
            raise StoreError("each title judgement has exactly code, titlePattern and reason")
        if rule["code"] not in JUDGEMENT_CODES or not isinstance(rule["reason"], str) or not rule["reason"].strip():
            raise StoreError(f"title judgement {rule.get('code')!r} has an unknown code or an empty reason")
        try:
            re.compile(rule["titlePattern"])
        except (re.error, TypeError) as exc:
            raise StoreError(f"title judgement pattern does not compile: {rule.get('titlePattern')!r}") from exc
        rules.append(dict(rule))
    return rules, sha256_hex(raw)


def _historical_states(members: dict) -> dict:
    states = {}
    for path in sorted(members):
        if path.startswith("store/discovery/") and path.endswith(".json") and not path.split("/")[-1].startswith("decisions-template"):
            for item in json.loads(members[path]).get("items", []):
                states.setdefault(item["fileTitle"], {"state": item.get("admissionState"), "blockers": sorted(item.get("blockers") or []),
                                                      "discoveryReportSha256": path.split("/")[-1][:-5]})
    return states


def _scopes(members: dict) -> dict:
    scope_of = {}
    for line in members["capture/scopes.jsonl"].splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("event") == "scope":
            for title in record.get("describedTitles") or []:
                scope_of.setdefault(title, record["scope"])
    return scope_of


def _stem(title: str) -> str:
    t = re.sub(r"\.(webm|ogv|ogg|mpg|mpeg|mp4)$", "", title[5:], flags=re.I)
    t = re.sub(r"[-_ ]?\d+x\d+$", "", t)
    return re.sub(r"\s+\d+$", "", t).lower()


def build_inventory(bundles: list[dict], provisional_reference: date, judgements: list[dict],
                    judgements_sha256: str | None, code: dict) -> dict:
    """The inventory document. Pure: no I/O beyond the supplied bundle contents."""
    by_page: dict[int, dict] = {}
    unparseable = []
    for index, bundle in enumerate(bundles):
        historical, scope_of = _historical_states(bundle["members"]), _scopes(bundle["members"])
        for path in sorted(p for p in bundle["members"] if p.startswith("store/evidence/") and p.endswith(".json")):
            blob = bundle["members"][path]
            try:
                meta = commons.parse_file_metadata(json.loads(blob.decode("utf-8")))
            except (ValueError, KeyError, TypeError, UnicodeDecodeError, AttributeError) as exc:
                unparseable.append({"bundle": bundle["name"], "member": path, "memberSha256": sha256_hex(blob),
                                    "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                continue
            provenance = {"bundle": bundle["name"], "archiveSha256": bundle["archiveSha256"], "run": bundle["run"],
                          "runConfigSha256": bundle["runConfigSha256"], "scope": scope_of.get(meta["fileTitle"]),
                          "metadataMember": path, "metadataMemberSha256": sha256_hex(blob),
                          "pageRevisionId": meta["pageRevisionId"], "fileSha1": meta["fileSha1"],
                          "historicalAutomaticState": historical.get(meta["fileTitle"])}
            if meta["pageId"] in by_page:  # the same Commons page described again: one candidate, every provenance kept
                by_page[meta["pageId"]]["provenance"].append(provenance)
                continue
            state, blockers = admission.derive_state(meta, None)
            by_page[meta["pageId"]] = {"order": (index, meta["fileTitle"], meta["pageId"]), "meta": meta, "provenance": [provenance],
                                       "current": {"state": state, "blockers": sorted(blockers)}}

    entries = sorted(by_page.values(), key=lambda e: e["order"])
    uploaders, stems, sha1s, titles = {}, {}, {}, {}
    for e in entries:
        m = e["meta"]
        uploaders.setdefault(m["uploader"] or "unknown", []).append(m["pageId"])
        stems.setdefault(_stem(m["fileTitle"]), []).append(m["pageId"])
        sha1s.setdefault(m["fileSha1"], []).append(m["pageId"])
        titles.setdefault(m["fileTitle"], []).append(m["pageId"])
    rules = [{"code": c, "titlePattern": p, "reason": r, "source": "generic"} for c, p, r in GENERIC_TITLE_RULES]
    rules += [dict(j, source="judgements-file") for j in judgements]
    compiled = [(re.compile(r["titlePattern"], re.I), r) for r in rules]

    candidates, excluded_uploads = [], []
    for e in entries:
        m, flags, reasons = e["meta"], set(), []
        uploaded, declared = _date(m["fileUploadTimestampUtc"]), _date(m["declaredCaptureDate"])
        duration = float(m["durationSeconds"]) if m["durationSeconds"] else 0.0
        if uploaded is None:
            flags.add("UPLOAD_TIME_MISSING")
        elif uploaded <= provisional_reference:
            flags.add("NOT_FRESH_UNDER_PROVISIONAL_REFERENCE")
            excluded_uploads.append(uploaded)
            reasons.append(f"uploaded {uploaded} on or before the provisional reference {provisional_reference}; capture cannot be later than upload")
        if not m["declaredCaptureDate"]:
            flags.add("CAPTURE_DATE_UNDECLARED")
        elif declared is None:
            flags.add("CAPTURE_DATE_NOT_ISO")
        elif uploaded and declared > uploaded:
            flags.add("CAPTURE_DATE_AFTER_UPLOAD")
        licence_class = admission.licence_class(m["licenceCode"])
        share_alike = bool(admission.OPEN_LICENCES.get(m["licenceCode"] or "", (False,))[0]) or bool(re.search(r"-sa-", m["licenceCode"] or ""))
        if licence_class != "OPEN":
            flags.add("LICENCE_NOT_RECOGNISED_R5")
        if share_alike:
            flags.add("SHARE_ALIKE_R5")
        if not INDIA_HINT.search(m["fileTitle"]):
            flags.add("NO_INDIA_HINT_IN_TITLE")
        if STREET_HINT.search(m["fileTitle"]):
            flags.add("STREET_OR_TRAFFIC_HINT_IN_TITLE")
        if isinstance(m["width"], int) and isinstance(m["height"], int) and m["height"] > m["width"]:
            flags.add("DECLARED_PORTRAIT_FRAME")
        if not m["durationSeconds"]:
            flags.add("DURATION_MISSING")
        elif duration < 15:
            flags.add("DECLARED_SHORTER_THAN_15S")
        if len(e["provenance"]) > 1:
            flags.add("DESCRIBED_IN_MULTIPLE_BUNDLES")
            if len({(p["pageRevisionId"], p["fileSha1"]) for p in e["provenance"]}) > 1:
                flags.add("REVISION_DIFFERS_BETWEEN_BUNDLES")
        if len(uploaders[m["uploader"] or "unknown"]) > 1:
            flags.add("SAME_UPLOADER_CLUSTER")
        if len(stems[_stem(m["fileTitle"])]) > 1:
            flags.add("NEAR_DUPLICATE_TITLE")
        if len(sha1s[m["fileSha1"]]) > 1:
            flags.add("IDENTICAL_FILE_BYTES")
        if len(titles[m["fileTitle"]]) > 1:
            flags.add("TITLE_SHARED_BY_PAGE_IDS")
        title_codes = []
        for pattern, rule in compiled:
            if pattern.search(m["fileTitle"]) and rule["code"] not in title_codes:
                title_codes.append(rule["code"])
                flags.add(rule["code"])
                reasons.append(rule["reason"])
        if e["current"]["state"] == "REJECTED":
            primary = "CLEARLY_UNSUITABLE"
            reasons.append("the helper rejects it automatically: " + ",".join(e["current"]["blockers"]))
        elif "NOT_FRESH_UNDER_PROVISIONAL_REFERENCE" in flags and EXCLUDING_CODES & set(title_codes):
            primary = "CLEARLY_UNSUITABLE"
        elif "NOT_FRESH_UNDER_PROVISIONAL_REFERENCE" in flags:
            primary = "NON_OPERATIONAL_REFERENCE_ONLY"
            reasons.append("cannot be an operational candidate under the provisional reference; training-only or reference at most, subject to review")
        elif title_codes:
            primary = "LIKELY_UNSUITABLE_TITLE_NEEDS_VISUAL_CONFIRMATION"
        elif "STREET_OR_TRAFFIC_HINT_IN_TITLE" in flags:
            primary = "PLAUSIBLE_NEEDS_VISUAL_REVIEW"
            reasons.append("fresh-possible upload and a street/traffic title; subject, viewpoint and people/vehicle visibility are unobserved")
        else:
            primary = "LIKELY_UNSUITABLE_TITLE_NEEDS_VISUAL_CONFIRMATION"
            reasons.append("title does not indicate a street or traffic scene")
        candidates.append({
            "pageId": m["pageId"], "title": m["fileTitle"], "pageRevisionId": m["pageRevisionId"], "fileSha1": m["fileSha1"],
            "provenance": e["provenance"],
            "licenceCode": m["licenceCode"], "licenceClass": licence_class, "shareAlike": share_alike,
            "author": m["author"], "uploader": m["uploader"], "uploadedUtc": m["fileUploadTimestampUtc"],
            "declaredCaptureDate": m["declaredCaptureDate"], "mime": m["mime"], "mediaType": m["mediaType"],
            "width": m["width"], "height": m["height"], "durationSeconds": m["durationSeconds"],
            "currentAutomaticState": e["current"],
            "triage": {"primary": primary, "flags": sorted(flags), "reasons": reasons,
                       "basis": "retained Commons metadata and title only; no frame viewed"},
            "status": {"DESCRIBED": True, "REVIEWED": False, "ADMISSIBLE": None, "FROZEN_QUALIFICATION": False},
        })

    def seconds(selector) -> str:
        return f"{sum(float(c['durationSeconds'] or 0) for c in candidates if selector(c)):.1f}"

    fresh = [c for c in candidates if "NOT_FRESH_UNDER_PROVISIONAL_REFERENCE" not in c["triage"]["flags"]]
    unmatched = [r["titlePattern"] for r in judgements if not any(re.search(r["titlePattern"], c["title"], re.I) for c in candidates)]
    summary = {
        "candidates": len(candidates),
        "unparseableEvidence": len(unparseable),
        "byPrimary": {k: sum(1 for c in candidates if c["triage"]["primary"] == k) for k in PRIMARY_ORDER},
        "shareAlikeR5": sum(1 for c in candidates if c["shareAlike"]),
        "licenceNotRecognisedR5": sum(1 for c in candidates if c["licenceClass"] != "OPEN"),
        "captureDateUncertain": sum(1 for c in candidates if {"CAPTURE_DATE_UNDECLARED", "CAPTURE_DATE_NOT_ISO", "CAPTURE_DATE_AFTER_UPLOAD"} & set(c["triage"]["flags"])),
        "historicalStateDiffersFromCurrent": sum(1 for c in candidates for p in c["provenance"][:1]
                                                 if p["historicalAutomaticState"] and p["historicalAutomaticState"]["state"] != c["currentAutomaticState"]["state"]),
        "freshPossibleCandidates": len(fresh),
        "upperBoundSeconds": {
            "freshPossibleAllSubjects": seconds(lambda c: c in fresh),
            "plausibleNeedsVisualReview": seconds(lambda c: c["triage"]["primary"] == "PLAUSIBLE_NEEDS_VISUAL_REVIEW"),
        },
        # Every file uploaded on or before this date is excluded for any reference on or after it, so the
        # fresh-possible set and its upper bound hold for every reference date from here to the provisional one.
        "freshnessBoundValidForReferenceOnOrAfter": str(max(excluded_uploads)) if excluded_uploads else None,
        "uploaderClusters": {u: sorted(ids) for u, ids in sorted(uploaders.items()) if len(ids) > 1},
        "nearDuplicateTitleClusters": {s: sorted(ids) for s, ids in sorted(stems.items()) if len(ids) > 1},
        "unmatchedJudgementPatterns": unmatched,
    }
    return {
        "schema": INVENTORY_SCHEMA,
        "purpose": "metadata-only triage of described candidates; NOT B0 review, admission or qualification",
        "sources": [{"bundle": b["name"], "archiveSha256": b["archiveSha256"], "manifestSha256": b["manifestSha256"],
                     "run": b["run"], "runConfigSha256": b["runConfigSha256"]} for b in bundles],
        "code": code,
        "provisionalFreshnessReference": {"date": str(provisional_reference), "status": "PROVISIONAL, NOT DECIDED"},
        "titleRules": rules,
        "titleJudgementsSha256": judgements_sha256,
        "statusVocabulary": {"DESCRIBED": "metadata retained by a recorded discovery run",
                             "REVIEWED": "a named B0 reviewer has recorded a decision",
                             "ADMISSIBLE": "admitted under every B0 rule (set only after review)",
                             "FROZEN_QUALIFICATION": "part of a sealed frozen qualification partition (never set by B0)"},
        "summary": summary,
        "unparseableEvidence": unparseable,
        "candidates": candidates,
    }


def proposals_and_worksheet(inventory: dict) -> tuple[dict, list[list]]:
    """Stage-1 proposed metadata decisions (unconfirmed; reviewedBy null) and the stage-2 visual worksheet rows."""
    proposals, rows = [], []
    for c in inventory["candidates"]:
        primary = c["triage"]["primary"]
        base = {"fileTitle": c["title"], "pageRevisionId": c["pageRevisionId"], "fileSha1": c["fileSha1"],
                "reviewedBy": None, "confirmation": "PROPOSED_UNCONFIRMED", "triage": primary,
                "reasonBasis": c["triage"]["reasons"]}
        if primary == "CLEARLY_UNSUITABLE":
            proposals.append(dict(base, state="REJECTED", intendedRole=None,
                                  reason="; ".join(c["triage"]["reasons"])))
        elif primary == "NON_OPERATIONAL_REFERENCE_ONLY":
            note = " Reference use of a share-alike or unrecognised licence needs R-5 first." if {"SHARE_ALIKE_R5", "LICENCE_NOT_RECOGNISED_R5"} & set(c["triage"]["flags"]) else ""
            proposals.append(dict(base, state="REFERENCE_ONLY", intendedRole="development-reference",
                                  reason="; ".join(c["triage"]["reasons"]) + note))
        else:
            rows.append([c["pageId"], c["title"], primary, c["licenceCode"], c["shareAlike"], c["uploader"], c["durationSeconds"],
                         "", "", "", "", "", "", "", "", "", "", ""])
    return {"schema": PROPOSALS_SCHEMA, "sources": inventory["sources"],
            "note": "Proposals from metadata only. Not B0 review: a named reviewer must confirm, change or reject each one and sign it.",
            "decisions": proposals}, rows


WORKSHEET_HEADER = ["pageId", "title", "triage", "licence", "shareAlike", "uploader", "declaredDurationS",
                    "sceneType", "pedestriansPresent", "vehiclesPresent", "usableContinuousSeconds", "viewpoint", "siteContext",
                    "apparentCaptureType", "realTimeNotTimelapseOrEdited", "attributeCoverage", "visiblePrivacyConcern",
                    "ownerOrR5Question"]


def _source_revision() -> dict:
    qualification = Path(__file__).resolve().parent.parent
    try:
        commit = subprocess.run(["git", "-C", str(qualification), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(qualification), "status", "--porcelain"], capture_output=True, text=True, timeout=30, check=True).stdout.strip() != ""
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "localChanges": None}
    return {"commit": commit or None, "localChanges": dirty}


def code_identity() -> dict:
    package = Path(__file__).resolve().parent
    return {"repository": _source_revision(),
            "moduleSha256": {p.name: sha256_hex(p.read_bytes()) for p in sorted(package.glob("*.py"))}}


def write_outputs(out: Path, inventory: dict) -> dict:
    """Write every output into a new directory; refuse an existing one. Returns {file: sha256}."""
    out = Path(out)
    assert_controlled_store(out.parent)
    out.mkdir(exist_ok=False)
    proposals, rows = proposals_and_worksheet(inventory)
    files = {"inventory.json": canonical_json(inventory),
             "proposed-metadata-decisions.json": canonical_json(proposals)}
    template = {"schemaVersion": TEMPLATE_SCHEMA, "sources": inventory["sources"],
                "note": "Unreviewed template: every review field is null. Complete only for files actually reviewed.",
                "decisions": [{"fileTitle": c["title"], "pageRevisionId": c["pageRevisionId"], "fileSha1": c["fileSha1"],
                               "state": None, "intendedRole": None, "siteId": None, "viewpointId": None, "reviewedBy": None,
                               "reason": None, "freshnessReferenceDate": None,
                               "capture": {"start": None, "end": None, "confidence": "unknown", "evidenceKinds": [], "evidence": None},
                               "rightsReview": {"reviewedBy": None, "determination": None, "evidence": None},
                               "privacyReview": {"reviewedBy": None, "basis": None}} for c in inventory["candidates"]]}
    files["decisions-template.json"] = (json.dumps(template, indent=2, sort_keys=True) + "\n").encode("utf-8")
    for name, header, body in (
        ("inventory.csv", ["run", "scope", "pageId", "title", "licence", "shareAlike", "uploader", "uploaded", "declaredCapture", "mime",
                           "resolution", "durationS", "historicalState", "currentState", "triage", "flags"],
         [[c["provenance"][0]["run"], c["provenance"][0]["scope"], c["pageId"], c["title"][5:], c["licenceCode"], c["shareAlike"],
           c["uploader"], (c["uploadedUtc"] or "")[:10], c["declaredCaptureDate"], c["mime"], f"{c['width']}x{c['height']}",
           c["durationSeconds"], (c["provenance"][0]["historicalAutomaticState"] or {}).get("state"),
           c["currentAutomaticState"]["state"], c["triage"]["primary"], ";".join(c["triage"]["flags"])] for c in inventory["candidates"]]),
        ("visual-review-worksheet.csv", WORKSHEET_HEADER, rows)):
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(body)
        files[name] = buffer.getvalue().encode("utf-8")
    hashes = {}
    for name in sorted(files):
        with open(out / name, "xb") as handle:
            handle.write(files[name])
        hashes[name] = sha256_hex(files[name])
    with open(out / "SHA256SUMS", "xb") as handle:
        handle.write("".join(f"{h}  {n}\n" for n, h in hashes.items()).encode("ascii"))
    return hashes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="review_inventory", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle", nargs=3, action="append", required=True, metavar=("EVIDENCE_DIR", "NAME", "ARCHIVE_SHA256"),
                        help="a verified evidence bundle and the archive SHA-256 it must have; repeat in a fixed order")
    parser.add_argument("--provisional-reference", required=True, help="provisional freshness reference date (YYYY-MM-DD); recorded as provisional")
    parser.add_argument("--title-judgements", type=Path, help=f"optional {JUDGEMENTS_SCHEMA} file")
    parser.add_argument("--out", required=True, type=Path, help="new output directory (must not exist; outside Git)")
    args = parser.parse_args(argv)
    try:
        reference = date.fromisoformat(args.provisional_reference)
        bundles = [read_bundle(Path(d), n, h) for d, n, h in args.bundle]
        judgements, judgements_sha = load_judgements(args.title_judgements)
        inventory = build_inventory(bundles, reference, judgements, judgements_sha, code_identity())
        hashes = write_outputs(args.out, inventory)
    except (StoreError, OSError, ValueError, KeyError, tarfile.TarError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"out": args.out.name, "hashes": hashes, "summary": inventory["summary"]}, indent=2, sort_keys=True))
    return 0
