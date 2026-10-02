"""Per-file source admission rules for the S2c B0 acquisition pilot (Development only).

Pure functions: no network, no filesystem. A receipt records what is known about one
exact source file revision and which admission state the evidence supports. Admission
is never inferred from the hosting provider or a category: it needs the file's own
licence, a named human rights review, a named privacy review, and capture-time
evidence that is not the upload time. See ``README.md``.

A **purpose approval** (owner decision C+) is a separate record that lets one exact public
file revision be acquired for named engineering purposes (training, development, tuning,
selection, benchmarking, reference, regression-challenge). It relies on a reusable,
hash-bound rights/privacy **determination** shared by every file it covers. It never
changes the B0 admission decision or state: a ``REFERENCE_ONLY`` file stays
``REFERENCE_ONLY`` while approved for training. It can never approve the frozen
qualification test, which is restricted to protected footage (``provenance.py``).
"""

from __future__ import annotations

import re
from datetime import date

from attributes.corpus.canonical import (
    DATE_RE,
    CorpusError,
    canonical_json,
    require,
    require_keys,
    require_pseudonym,
    require_token,
    sha256_hex,
)
from attributes.corpus.provenance import PUBLIC, parse_purposes

RECEIPT_SCHEMA = "mavi-s2c-source-admission-receipt-v2"  # v2 adds origin, purpose approval and acquisition bases
PURPOSE_APPROVALS_SCHEMA = "mavi-s2c-source-purpose-approvals-v1"
SUMMARY_SCHEMA = "mavi-s2c-source-acquisition-summary-v1"

STATES = ("DISCOVERED", "RIGHTS_PENDING", "PROVENANCE_PENDING", "ADMITTED_FOR_PILOT", "REFERENCE_ONLY", "REJECTED")
HUMAN_STATES = ("ADMITTED_FOR_PILOT", "REFERENCE_ONLY", "REJECTED")
ROLES = ("operational-candidate", "training-only", "development-reference")
CAPTURE_EVIDENCE_KINDS = ("embedded-container-metadata", "uploader-statement", "visible-in-frame", "corroborating-source")
CAPTURE_CONFIDENCE = ("high", "medium", "low", "unknown")
VIDEO_MIME = ("video/webm", "video/ogg", "video/mpeg", "video/mp4")
# Commons labels every Ogg container ``application/ogg`` whatever it holds (Theora video, or
# Vorbis/Opus audio only). The container MIME alone is therefore not evidence either way; the
# content classification is Commons' own ``mediatype``. Only this one container MIME gets that
# treatment, and only with an Ogg file extension and a real frame size.
OGG_CONTAINER_MIME = "application/ogg"
_OGG_EXTENSIONS = (".ogv", ".ogg")

# Machine pre-classification of the file's own licence code, never a legal determination:
# an admitted item also needs a named rights review. Anything unlisted stays RIGHTS_PENDING.
OPEN_LICENCES = {
    "cc0": (False,), "pd": (False,), "public-domain": (False,),
    "cc-by-2.0": (False,), "cc-by-2.5": (False,), "cc-by-3.0": (False,), "cc-by-4.0": (False,),
    "cc-by-sa-2.0": (True,), "cc-by-sa-2.5": (True,), "cc-by-sa-3.0": (True,), "cc-by-sa-4.0": (True,),
}

_FILE_TITLE_RE = re.compile(r"^File:[^*?|#<>\[\]{}\n]+\.(?:webm|ogv|ogg|mpg|mpeg|mp4)$", re.IGNORECASE)
_LOCAL_PATH_RE = re.compile(r"(?:^|[\s\"'=(])(?:[A-Za-z]:[\\/]|\\\\|/(?:home|root|Users|tmp|mnt|srv|var|etc)/|~[\\/])")


def normalise_licence(code: object) -> str | None:
    if not isinstance(code, str):
        return None
    value = code.strip().lower().replace(" ", "-")
    return value or None


def licence_class(code: str | None) -> str:
    """OPEN (listed free licence), RESTRICTED (NC/ND), or UNKNOWN."""
    if code is None:
        return "UNKNOWN"
    if code in OPEN_LICENCES:
        return "OPEN"
    if re.search(r"(?:^|-)(?:nc|nd)(?:-|$)", code):
        return "RESTRICTED"
    return "UNKNOWN"


def require_file_title(title: object) -> str:
    """One exact file: no category, wildcard or search pattern can stand for a source."""
    require(isinstance(title, str) and _FILE_TITLE_RE.fullmatch(title) is not None and not title.startswith("File:Category"),
            "source_admission_exact_file_title_required")
    return title


def refuse_local_paths(document: object) -> None:
    """Receipts carry public URLs but never local paths, drive letters or home directories."""
    if isinstance(document, str):
        require(_LOCAL_PATH_RE.search(document) is None, "source_receipt_local_path")
    elif isinstance(document, dict):
        for key, value in document.items():
            refuse_local_paths(key)
            refuse_local_paths(value)
    elif isinstance(document, (list, tuple)):
        for value in document:
            refuse_local_paths(value)


def _date_or_none(value: object, code: str) -> date | None:
    if value is None:
        return None
    require(isinstance(value, str) and DATE_RE.fullmatch(value) is not None, code)
    return date.fromisoformat(value)


def capture_interval(decision: dict) -> tuple[date | None, date | None]:
    capture = decision.get("capture") or {}
    start = _date_or_none(capture.get("start"), "source_capture_start")
    end = _date_or_none(capture.get("end"), "source_capture_end")
    if start and end:
        require(start <= end, "source_capture_interval_order")
    return start, end


def freshness(decision: dict) -> str:
    """CAPTURE_AFTER_REFERENCE only when the whole capture interval is after the reference date."""
    reference = _date_or_none(decision.get("freshnessReferenceDate"), "source_freshness_reference")
    start, end = capture_interval(decision)
    if reference is None or start is None or end is None:
        return "UNDETERMINED"
    if start > reference:
        return "CAPTURE_AFTER_REFERENCE"
    if end <= reference:
        return "CAPTURE_NOT_AFTER_REFERENCE"
    return "UNDETERMINED"


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def is_continuous_video(meta: dict) -> bool:
    """Provider metadata describes continuous video: Commons ``mediatype`` VIDEO and either a
    video MIME, or the Ogg container MIME on an Ogg file with a positive frame size."""
    if meta.get("mediaType") != "VIDEO":
        return False
    mime = meta.get("mime")
    if mime in VIDEO_MIME:
        return True
    title = meta.get("fileTitle")
    return (mime == OGG_CONTAINER_MIME and isinstance(title, str) and title.lower().endswith(_OGG_EXTENSIONS)
            and _positive_int(meta.get("width")) and _positive_int(meta.get("height")))


def _file_blockers(meta: dict) -> tuple[list[str], str]:
    """Blockers that follow from the provider metadata alone, and the licence class."""
    blockers: list[str] = []
    lic = licence_class(meta.get("licenceCode"))
    if not is_continuous_video(meta):
        blockers.append("not-continuous-video")
    if not meta.get("originalFileUrl") or not meta.get("fileSha1") or not meta.get("declaredByteSize"):
        blockers.append("original-file-identity-missing")
    if lic == "RESTRICTED":
        blockers.append("licence-restricts-derivatives-or-use")
    elif lic == "UNKNOWN":
        blockers.append("file-licence-unknown")
    if not meta.get("author"):
        blockers.append("author-unknown")
    return blockers, lic


def derive_state(meta: dict, decision: dict | None) -> tuple[str, list[str]]:
    """Effective admission state and the blockers that stop a stronger state.

    ``meta`` is parsed provider metadata for one exact file revision; ``decision`` the
    human review for that same revision, or None. A human request is honoured only when
    every rule holds; otherwise the effective state is the pending state that names the gap.
    """
    blockers, lic = _file_blockers(meta)

    if decision is None:
        if "not-continuous-video" in blockers or "licence-restricts-derivatives-or-use" in blockers:
            return "REJECTED", blockers
        if lic != "OPEN" or "author-unknown" in blockers:
            return "RIGHTS_PENDING", blockers
        if not meta.get("declaredCaptureDate"):
            return "PROVENANCE_PENDING", blockers + ["capture-date-undeclared"]
        return "DISCOVERED", blockers

    require(decision.get("fileTitle") == meta.get("fileTitle"), "source_decision_title_mismatch")
    requested = decision.get("state")
    require(requested in HUMAN_STATES, "source_decision_state")
    reason = decision.get("reason")
    if requested == "REJECTED":
        require(isinstance(reason, str) and reason.strip() != "", "source_rejection_reason_required")
        return "REJECTED", blockers
    if requested == "REFERENCE_ONLY":
        require(isinstance(reason, str) and reason.strip() != "", "source_reference_reason_required")
        require(decision.get("intendedRole") == "development-reference", "source_reference_role")
        return "REFERENCE_ONLY", blockers

    # ADMITTED_FOR_PILOT: the review must be bound to exactly this file revision.
    if decision.get("pageRevisionId") != meta.get("pageRevisionId") or decision.get("fileSha1") != meta.get("fileSha1"):
        blockers.append("reviewed-revision-differs-from-current")
    rights = decision.get("rightsReview") or {}
    if not (rights.get("reviewedBy") and rights.get("determination") == "PERMITTED_FOR_PILOT_ACQUISITION" and rights.get("evidence")):
        blockers.append("human-rights-review-missing")
    privacy = decision.get("privacyReview") or {}
    if not (privacy.get("reviewedBy") and privacy.get("basis")):
        blockers.append("human-privacy-review-missing")
    if not decision.get("reviewedBy"):
        blockers.append("reviewer-missing")
    capture = decision.get("capture") or {}
    start, end = capture_interval(decision)
    kinds = capture.get("evidenceKinds") or []
    if start is None or end is None:
        blockers.append("capture-date-missing")
    if not kinds or any(k not in CAPTURE_EVIDENCE_KINDS for k in kinds) or not capture.get("evidence"):
        blockers.append("capture-evidence-missing-or-upload-derived")
    if capture.get("confidence") not in ("high", "medium"):
        blockers.append("capture-confidence-insufficient")
    role = decision.get("intendedRole")
    if role not in ("operational-candidate", "training-only"):
        blockers.append("intended-role-invalid-for-admission")
    if role == "operational-candidate" and freshness(decision) != "CAPTURE_AFTER_REFERENCE":
        blockers.append("freshness-not-established")
    try:
        require_pseudonym(decision.get("siteId"), "site")
        require_pseudonym(decision.get("viewpointId"), "viewpoint")
    except CorpusError:
        blockers.append("site-or-viewpoint-pseudonym-missing")

    rights_gaps = {"file-licence-unknown", "licence-restricts-derivatives-or-use", "author-unknown", "human-rights-review-missing", "human-privacy-review-missing"}
    if "not-continuous-video" in blockers:
        return "REJECTED", blockers
    if any(b in rights_gaps for b in blockers):
        return "RIGHTS_PENDING", blockers
    if blockers:
        return "PROVENANCE_PENDING", blockers
    return "ADMITTED_FOR_PILOT", blockers


def _determination(value: object, code: str) -> dict:
    """A reusable rights/privacy determination: one review covering every file that names it.

    It bounds the purposes and licence codes it covers, records the rights review, the
    privacy review and, for share-alike or unrecognised licences, R-5's ruling."""
    require(isinstance(value, dict), code)
    require_keys(value, code, ("determinationId", "reviewedOn", "purposes", "licenceCodes", "rights", "privacy", "r5Ruling"))
    require_token(value["determinationId"], f"{code}:id")
    require(_date_or_none(value["reviewedOn"], f"{code}:date") is not None, f"{code}:date")
    parse_purposes(value["purposes"], code, PUBLIC)
    codes = value["licenceCodes"]
    require(isinstance(codes, list) and codes and codes == sorted(set(codes)) and all(normalise_licence(c) == c for c in codes), f"{code}:licence_codes")
    require(isinstance(value["rights"], dict) and isinstance(value["privacy"], dict), f"{code}:reviews")
    require(value["r5Ruling"] is None or isinstance(value["r5Ruling"], dict), f"{code}:r5")
    return value


def parse_purpose_approvals(document: object) -> list[dict]:
    """Validate a purpose-approvals document and resolve each approval against its determination.

    Per file, an approval binds only the exact revision and SHA-1, the purposes, the
    determination it relies on and the file's B0 decision (``null`` if it has none). The
    document's ``approvedBy``/``approvedOn`` sign the whole batch. A malformed document is
    refused whole."""
    code = "source_approvals_invalid"
    require(isinstance(document, dict), code)
    require_keys(document, code, ("schemaVersion", "approvedBy", "approvedOn", "determinations", "approvals"))
    require(document["schemaVersion"] == PURPOSE_APPROVALS_SCHEMA, f"{code}:schema")
    refuse_local_paths(document)
    require(isinstance(document["approvedBy"], str) and document["approvedBy"].strip() != "", f"{code}:approver")
    require(_date_or_none(document["approvedOn"], f"{code}:date") is not None, f"{code}:date")
    determinations: dict[str, dict] = {}
    require(isinstance(document["determinations"], list) and document["determinations"], f"{code}:determinations")
    for value in document["determinations"]:
        d = _determination(value, f"{code}:determination")
        require(d["determinationId"] not in determinations, f"{code}:determination_duplicate")
        determinations[d["determinationId"]] = d
    require(isinstance(document["approvals"], list) and document["approvals"], f"{code}:approvals")
    resolved, titles = [], set()
    for approval in document["approvals"]:
        acode = f"{code}:approval"
        require(isinstance(approval, dict), acode)
        require_keys(approval, acode, ("fileTitle", "pageRevisionId", "fileSha1", "purposes", "determinationId", "b0Decision"), ("b0RejectionReview",))
        title = require_file_title(approval["fileTitle"])
        require(title not in titles, f"{acode}:duplicate_file")
        titles.add(title)
        parse_purposes(approval["purposes"], acode, PUBLIC)
        require(approval["determinationId"] in determinations, f"{acode}:determination_unknown")
        require(approval["b0Decision"] is None or approval["b0Decision"] in HUMAN_STATES, f"{acode}:b0_decision")
        resolved.append({**approval, "approvedBy": document["approvedBy"], "approvedOn": document["approvedOn"],
                         "determination": determinations[approval["determinationId"]]})
    return resolved


def purpose_approval_blockers(meta: dict, approval: dict, decision: dict | None = None) -> list[str]:
    """What stops a resolved purpose approval (``parse_purpose_approvals``) from authorising
    acquisition of this exact file revision.

    Refused outright: a public approval for ``frozen-qualification``; an approval whose
    declared ``b0Decision`` differs from a supplied B0 decision. Otherwise each gap is a
    named blocker. The file must be continuous video, with its original identity, a named
    author and a licence that is not NC/ND; the approval must bind the re-fetched revision
    and SHA-1; and the determination must cover its purposes and the file's licence code,
    with a rights review (``PERMITTED_FOR_ENGINEERING_USE``), a privacy review and, for
    share-alike or unrecognised licences, R-5's ``PERMITTED`` ruling. A file with no licence
    code is never covered.

    A file whose B0 decision is ``REJECTED`` (declared or supplied) also needs a named
    per-file ``b0RejectionReview`` stating that the rejection was not on rights or privacy
    grounds (ADR-015 §2): such a rejection is never bypassed by a new purpose, and leaving
    out the decisions file does not avoid the check. The B0 decision is read, never changed."""
    require(isinstance(approval, dict), "source_approval_invalid")
    require(approval.get("fileTitle") == meta.get("fileTitle"), "source_approval_title_mismatch")
    refuse_local_paths(approval)
    purposes = parse_purposes(approval.get("purposes"), "source_approval", PUBLIC)
    determination = approval.get("determination")
    require(isinstance(determination, dict), "source_approval_unresolved")
    declared = approval.get("b0Decision")
    if decision is not None:
        require(decision.get("state") == declared, "source_approval_b0_decision_mismatch")
    blockers, lic = _file_blockers(meta)
    if approval.get("pageRevisionId") != meta.get("pageRevisionId") or approval.get("fileSha1") != meta.get("fileSha1"):
        blockers.append("approved-revision-differs-from-current")
    if not approval.get("approvedBy") or not approval.get("approvedOn"):
        blockers.append("approver-missing")
    if not set(purposes) <= set(determination.get("purposes") or []):
        blockers.append("purpose-not-covered-by-determination")
    licence = meta.get("licenceCode")
    if licence is None:
        blockers.append("file-licence-missing")
    elif licence not in (determination.get("licenceCodes") or []):
        blockers.append("licence-not-covered-by-determination")
    rights = determination.get("rights") or {}
    if not (rights.get("reviewedBy") and rights.get("determination") == "PERMITTED_FOR_ENGINEERING_USE" and rights.get("evidence")):
        blockers.append("rights-determination-missing")
    privacy = determination.get("privacy") or {}
    if not (privacy.get("reviewedBy") and privacy.get("basis")):
        blockers.append("privacy-determination-missing")
    if declared == "REJECTED":
        rejection = approval.get("b0RejectionReview") or {}
        if rejection.get("rightsOrPrivacyRejection") is not False:
            blockers.append("b0-rights-or-privacy-rejection" if rejection.get("rightsOrPrivacyRejection") is True else "b0-rejection-review-missing")
        elif not (rejection.get("reviewedBy") and rejection.get("basis")):
            blockers.append("b0-rejection-review-missing")
    share_alike = bool(OPEN_LICENCES.get(licence or "", (False,))[0])
    if share_alike or lic == "UNKNOWN":
        r5 = determination.get("r5Ruling") or {}
        if r5.get("ruledBy") and r5.get("ruling") == "PERMITTED" and r5.get("reference"):
            if licence is not None and "file-licence-unknown" in blockers:
                blockers.remove("file-licence-unknown")  # R-5 has interpreted this licence code
        else:
            blockers.append("r5-ruling-missing")
    return sorted(set(blockers))


def _approval_summary(meta: dict, approval: dict | None, decision: dict | None) -> dict | None:
    if approval is None:
        return None
    blockers = purpose_approval_blockers(meta, approval, decision)
    return {"approvalSha256": sha256_hex(canonical_json(approval)), "determinationId": approval["determination"]["determinationId"],
            "determinationSha256": sha256_hex(canonical_json(approval["determination"])), "purposes": list(approval["purposes"]),
            "approvedBy": approval.get("approvedBy"), "approvedOn": approval.get("approvedOn"), "b0Decision": approval.get("b0Decision"),
            "status": "BLOCKED" if blockers else "APPROVED", "blockers": blockers}


def acquisition_bases(state: str, approval_summary: dict | None) -> list[str]:
    """Why the bytes may be retained: B0 pilot admission, an approved purpose, or both."""
    bases = ["ADMITTED_FOR_PILOT"] if state == "ADMITTED_FOR_PILOT" else []
    if approval_summary is not None and approval_summary["status"] == "APPROVED":
        bases.append("PURPOSE_APPROVAL")
    return bases


def build_receipt(meta: dict, decision: dict | None, metadata_evidence_sha256: str, acquisition: dict | None, approval: dict | None = None) -> dict:
    state, blockers = derive_state(meta, decision)
    approval_summary = _approval_summary(meta, approval, decision)
    d = decision or {}
    capture = d.get("capture") or {}
    receipt = {
        "schemaVersion": RECEIPT_SCHEMA,
        "provider": meta["provider"],
        "sourceType": "public-web-video",
        "sourceOrigin": PUBLIC,
        "fileTitle": meta["fileTitle"],
        "pageId": meta["pageId"],
        "pageRevisionId": meta["pageRevisionId"],
        "canonicalPageUrl": meta["canonicalPageUrl"],
        "originalFileUrl": meta["originalFileUrl"],
        "uploader": meta["uploader"],
        "author": meta["author"],
        "attribution": meta["attribution"],
        "licenceCode": meta["licenceCode"],
        "licenceShortName": meta["licenceShortName"],
        "licenceUrl": meta["licenceUrl"],
        "licenceClass": licence_class(meta["licenceCode"]),
        "shareAlike": bool(OPEN_LICENCES.get(meta["licenceCode"] or "", (False,))[0]),
        "licenceScope": "file description page licence (extmetadata), not the site text licence",
        "metadataEvidenceSha256": metadata_evidence_sha256,
        "publishedAtUtc": meta["fileUploadTimestampUtc"],
        "declaredCaptureDate": meta["declaredCaptureDate"],
        "capture": {"start": capture.get("start"), "end": capture.get("end"), "confidence": capture.get("confidence", "unknown"),
                    "evidenceKinds": sorted(capture.get("evidenceKinds") or []), "evidence": capture.get("evidence")},
        "freshnessReferenceDate": d.get("freshnessReferenceDate"),
        "freshness": freshness(d),
        "declaredMedia": {"mime": meta["mime"], "mediaType": meta["mediaType"], "byteSize": meta["declaredByteSize"],
                          "sha1": meta["fileSha1"], "width": meta["width"], "height": meta["height"],
                          "durationSeconds": meta["durationSeconds"],
                          "frameRate": None, "timeBase": None, "discontinuities": None,
                          "streamPropertiesSource": "measured at MAVI ingestion (VideoAsset), not declared here"},
        "siteId": d.get("siteId"),
        "viewpointId": d.get("viewpointId"),
        "intendedRole": d.get("intendedRole"),
        "requestedState": d.get("state"),
        "admissionState": state,
        "blockers": sorted(blockers),
        "reviewedBy": d.get("reviewedBy"),
        "rightsReview": d.get("rightsReview"),
        "privacyReview": d.get("privacyReview"),
        "reason": d.get("reason"),
        "purposeApproval": approval_summary,
        "acquisitionBases": acquisition_bases(state, approval_summary),
        "acquisition": acquisition,
    }
    refuse_local_paths(receipt)
    return receipt


def receipt_sha256(receipt: dict) -> str:
    return sha256_hex(canonical_json(receipt))
