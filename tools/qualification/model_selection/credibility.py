"""Candidate credibility and admissibility checks (MSR method v1 revision M1).

Normative text: ``docs/qualification/model-selection/candidate-credibility.md``. This
module enforces the rules marked **[checked]** there, on three documents:

* the **External Evidence Ledger** (``mavi-external-evidence-ledger-v1``), one per
  Model Selection Event. It holds external evidence only: no MAVI measurement or
  MAVI-produced evidence, no licence field and only pre-evaluation dispositions. Each
  candidate's provenance confidence and credibility class are *recomputed* from the
  recorded evidence, and a declared value that disagrees is refused;
* the **frozen ledger** (``<event-id>-evidence-ledger-frozen.json``), the copy whose
  hash the frozen protocol records. From then on the working ledger may only grow:
  evidence and history are append-only and the shortlist and pinned bytes are fixed;
* the **decision summary** (``mavi-model-selection-decision-v1``), a checked
  projection of MSR method §9 written from S2c.4 on. It binds the evaluated bytes to
  the ledger, the evaluated set to the frozen shortlist, recomputes the derived outputs
  (strongest technical, strongest cleared) without reading licence or credibility into
  the ranking, and gates the implementation candidate on clearance and an
  ``established`` class on the decision date.

Standard library only; nothing here reads the network, a model or imagery.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

LEDGER_SCHEMA = "mavi-external-evidence-ledger-v1"
DECISION_SCHEMA = "mavi-model-selection-decision-v1"
METHOD_REVISION = "msr-v1-m1"
UNKNOWN = "UNKNOWN"
REPORTED_LABEL = "reported, not reproduced by MAVI"

ESTABLISHED = "established"
EMERGING = "emerging"
REFERENCE = "reference-only"
EXCLUDED = "excluded-discovery"
MAVI_OWNED = "mavi-owned"
CLASSES = (ESTABLISHED, EMERGING, REFERENCE, EXCLUDED, MAVI_OWNED)
CLASS_RANK = {EXCLUDED: 0, REFERENCE: 1, EMERGING: 2, ESTABLISHED: 3, MAVI_OWNED: 3}
IMPLEMENTABLE_CLASSES = (ESTABLISHED, MAVI_OWNED)

HIGH, MEDIUM, LOW = "High", "Medium", "Low"

CHECKPOINT, METHOD, BASELINE = "checkpoint", "method", "mavi-baseline"
KINDS = (CHECKPOINT, METHOD, BASELINE)

ORIGINAL_PUBLISHERS = ("original-author", "original-organisation")
FRAMEWORK_MAINTAINER = "recognised-framework-maintainer"
PUBLISHERS = (*ORIGINAL_PUBLISHERS, FRAMEWORK_MAINTAINER, "third-party", "unknown")

ESTABLISHED_PUBLICATIONS = ("peer-reviewed", "preprint-established-group", "official-model-documentation")
PUBLICATIONS = (*ESTABLISHED_PUBLICATIONS, "preprint", "none")

FIRST_PARTY = "first-party-claim"
REPETITION = "repetition"
REPRODUCTION = "independent-reproduction"
BENCHMARK = "independent-benchmark"
ADOPTION = "adoption"
SCRUTINY = "public-scrutiny"
EVIDENCE_TYPES = (FIRST_PARTY, REPETITION, REPRODUCTION, BENCHMARK, ADOPTION, SCRUTINY)
INDEPENDENT_TECHNICAL = (REPRODUCTION, BENCHMARK)
INDEPENDENT_TYPES = (REPRODUCTION, BENCHMARK, ADOPTION)
CLAIM_ORIGIN_TYPES = (FIRST_PARTY, REPRODUCTION, BENCHMARK)

AUTHOR, AFFILIATED, INDEPENDENT = "author", "author-affiliated", "independent"
RELATIONS = (AUTHOR, AFFILIATED, INDEPENDENT)
EXACT, METHOD_SCOPE = "exact-checkpoint", "method"
SCOPES = (EXACT, METHOD_SCOPE)
CLAIM_KINDS = ("task-quality", "runtime")

# Pre-evaluation dispositions only (MSR method §4): a ledger cannot record EVALUATED,
# TECHNICALLY_SELECTED or any other bake-off outcome.
DISCOVERED, SHORTLISTED, NOT_SHORTLISTED, REFERENCE_ONLY, DEFERRED = (
    "DISCOVERED", "SHORTLISTED", "NOT_SHORTLISTED", "REFERENCE_ONLY", "DEFERRED",
)
DISPOSITIONS = (DISCOVERED, SHORTLISTED, NOT_SHORTLISTED, REFERENCE_ONLY, DEFERRED)
REASONS_BY_DISPOSITION = {
    DISCOVERED: (),
    SHORTLISTED: (),
    NOT_SHORTLISTED: ("technical", "credibility"),
    REFERENCE_ONLY: ("credibility", "evaluation-permission", "availability"),
    DEFERRED: ("technical", "resources", "availability"),
}
DISPOSITIONS_BY_CLASS = {
    ESTABLISHED: (DISCOVERED, SHORTLISTED, NOT_SHORTLISTED, REFERENCE_ONLY, DEFERRED),
    EMERGING: (DISCOVERED, SHORTLISTED, NOT_SHORTLISTED, REFERENCE_ONLY, DEFERRED),
    REFERENCE: (DISCOVERED, NOT_SHORTLISTED, REFERENCE_ONLY, DEFERRED),
    EXCLUDED: (DISCOVERED, NOT_SHORTLISTED),
    MAVI_OWNED: (DISCOVERED, SHORTLISTED, NOT_SHORTLISTED, DEFERRED),
}
# A credibility reason must be one the evidence supports: emerging and reference-only
# candidates may be held as reference-only (R-CRED's default), an excluded discovery is
# not shortlisted, and an established candidate never takes a credibility reason.
CREDIBILITY_REASON_CLASSES = {NOT_SHORTLISTED: (EXCLUDED,), REFERENCE_ONLY: (REFERENCE, EMERGING)}

# Known events scope their object class and sub-tasks (S2c plan §6); person and vehicle
# evidence cannot be mixed by declaring extra sub-tasks.
EVENT_SCOPES = {
    "person-attributes": ("person", ("T-PC", "T-PO")),
    "vehicle-attributes": ("vehicle", ("T-VC",)),
}

EVENT_STATES = ("TECHNICAL_DECISION_RECORDED", "QUALIFICATION_PENDING", "CLOSED")
IMPLEMENTATION_STATES = ("QUALIFICATION_PENDING", "CLOSED")
OUTCOMES = ("SELECTED_FOR_PACKAGING", "INCUMBENT_RETAINED", "BASELINE_SELECTED", "NO_QUALIFIABLE_CANDIDATE")
LICENCE_STATUSES = ("NOT_ASSESSED", "REVIEW_PENDING", "CLEARED", "CONSTRAINED", "NOT_CLEARED")
CLEARED = "CLEARED"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMMUTABLE_REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
TOKEN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
CANDIDATE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
LOCAL_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
SUBTASK_RE = re.compile(r"^T-[A-Z]{2,4}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# MAVI's own measurements are layer 3 and never external evidence (candidate-credibility.md §2).
# This denylist narrows the risk; the reviewer confirms it (§9). MAVI is matched as a whole
# word so unrelated names (Mavic, MAVIS, primavision) are not refused.
RESERVED_GROUP_RE = re.compile(r"^mavi(?:-|$)")
MAVI_WORD_RE = re.compile(r"(?<![a-z0-9])mavi(?![a-z0-9])", re.IGNORECASE)
MAVI_PATH_RE = re.compile(
    r"^(?:\./)?(?:docs|tools|src|models|config|evidence)[/\\]"
    r"|^evidence-store:"
    r"|(?<![a-z0-9])msr-(?:person|vehicle)-attributes-\d{4}-\d{2}(?![0-9])",
    re.IGNORECASE,
)
# The summary is not scanned for the bare word, because an author may be called Mavi;
# MAVI next to MAVI's own evaluation vocabulary is refused there and in caveats.
EVIDENCE_TEXT_FIELDS = ("source", "locator", "independenceBasis")
MAVI_RESULT_RE = re.compile(
    r"(?<![a-z0-9])mavi(?![a-z0-9]).{0,40}(?:bake-?off|selection partition|tuning partition|frozen test|gates?\b)"
    r"|(?:bake-?off|selection partition).{0,40}(?<![a-z0-9])mavi(?![a-z0-9])",
    re.IGNORECASE,
)

LEDGER_SUFFIX = "-evidence-ledger.json"
FROZEN_SUFFIX = "-evidence-ledger-frozen.json"
SNAPSHOT_SUFFIX = "-evidence-ledger-decided.json"
PROTOCOL_SUFFIX = "-protocol.md"
DECISION_SUFFIX = "-decision.json"
MODEL_SELECTION_DIR = Path("docs/qualification/model-selection")


class CredibilityError(ValueError):
    """A ledger or decision summary violates its contract; the message is a stable code."""


# --------------------------------------------------------------------------- helpers


def canonical_json(document: object) -> bytes:
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("ascii")


def document_sha256(document: object) -> str:
    return hashlib.sha256(canonical_json(document)).hexdigest()


def lf_normalised_sha256(path: Path) -> str:
    """SHA-256 of a text file after CRLF -> LF only (MSR method §10)."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read_json(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CredibilityError(f"json_unreadable:{path.name}") from exc
    if not isinstance(document, dict):
        raise CredibilityError(f"json_not_object:{path.name}")
    return document


def _today() -> date:
    """Latest acceptable date: today in UTC plus one day, so no time zone refuses today."""
    return datetime.now(timezone.utc).date() + timedelta(days=1)


def _fail(code: str, where: str) -> CredibilityError:
    return CredibilityError(f"{code}:{where}")


def _keys(value: object, required: Iterable[str], where: str, optional: Iterable[str] = ()) -> dict:
    if not isinstance(value, dict):
        raise _fail("not_object", where)
    required, optional = set(required), set(optional)
    missing = required - value.keys()
    if missing:
        raise _fail("missing_field", f"{where}.{sorted(missing)[0]}")
    unknown = value.keys() - required - optional
    if unknown:
        raise _fail("unknown_field", f"{where}.{sorted(unknown)[0]}")
    return value


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail("text_required", where)
    return value


def _optional_text(value: object, where: str) -> str | None:
    return None if value is None else _text(value, where)


def _enum(value: object, allowed: Iterable[str], where: str) -> str:
    if value not in tuple(allowed):
        raise _fail("value_not_allowed", where)
    return value  # type: ignore[return-value]


def _match(value: object, pattern: re.Pattern[str], where: str) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise _fail("malformed", where)
    return value


def _sha_or_unknown(value: object, where: str) -> str:
    if value == UNKNOWN:
        return UNKNOWN
    return _match(value, SHA256_RE, where)


def _date(value: object, where: str) -> date:
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise _fail("date_malformed", where)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise _fail("date_malformed", where) from exc
    if parsed > _today():
        raise _fail("date_in_future", where)
    return parsed


def _list(value: object, where: str) -> list:
    if not isinstance(value, list):
        raise _fail("not_list", where)
    return value


def _number(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _fail("number_required", where)
    return float(value)


def _person(name: str) -> str:
    return " ".join(name.split()).casefold()


def _reject_licence_keys(value: object, where: str) -> None:
    """The ledger is licence-blind by construction: no key may even mention a licence."""
    if isinstance(value, dict):
        for key, item in value.items():
            if "licen" in key.lower():
                raise _fail("licence_field_in_ledger", f"{where}.{key}")
            _reject_licence_keys(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_licence_keys(item, f"{where}[{index}]")


_TRACKING_PARAMETER_RE = re.compile(r"^(?:utm_[a-z]+|ref|source|fbclid|gclid)=", re.IGNORECASE)
_ARXIV_RE = re.compile(
    r"^(?:(?:export\.)?arxiv\.org/(?:abs|pdf|html)|huggingface\.co/papers|hf\.co/papers)/"
    r"(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?(?:\.pdf)?$"
)
_OPENREVIEW_RE = re.compile(r"^openreview\.net/(?:forum|pdf|attachment)$")


def _normalised_source(source: str) -> str:
    """One document, however its URL is written.

    Scheme, ``www.``, fragment, case, trailing slashes and tracking parameters are
    ignored; an identifying query (``forum?id=…``) is kept. arXiv abstract, PDF, HTML,
    version and export links collapse to one arXiv id.
    """
    value = source.strip().lower()
    value = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value)
    value = re.sub(r"^www\.", "", value)
    value = value.split("#", 1)[0]
    path, _, query = value.partition("?")
    path = path.rstrip("/")
    arxiv = _ARXIV_RE.match(path)
    if arxiv:
        return f"arxiv:{arxiv.group(1)}"
    kept = sorted(p for p in query.split("&") if p and not _TRACKING_PARAMETER_RE.match(p))
    if _OPENREVIEW_RE.match(path):
        ids = [p for p in kept if p.startswith("id=")]
        notes = [p for p in kept if p.startswith("noteid=")]
        if ids:
            # A note (a review or comment) in a paper's forum is its own document.
            note = f"#{notes[0][len('noteid='):]}" if notes else ""
            return f"openreview:{ids[0][len('id='):]}{note}"
    return path + ("?" + "&".join(kept) if kept else "")


def _integrity_conflict_at(identity: Mapping, as_of: date | None) -> bool:
    conflict = identity.get("integrityConflict")
    return conflict is not None and (as_of is None or date.fromisoformat(conflict["at"]) <= as_of)


# ---------------------------------------------------------------- ledger structure


def _check_identity(entry: dict, where: str) -> None:
    kind = entry["candidateKind"]
    identity = entry["identity"]
    if kind == BASELINE:
        _keys(identity, ("repository", "revision"), where)
        if identity["repository"] != "MAVI":
            raise _fail("baseline_not_mavi", f"{where}.repository")
        if identity["revision"] != UNKNOWN:
            _match(identity["revision"], IMMUTABLE_REVISION_RE, f"{where}.revision")
        return
    _keys(
        identity,
        ("repository", "organisation", "revision", "tag", "files", "publisher", "derivation", "integrityConflict"),
        where,
    )
    _text(identity["repository"], f"{where}.repository")
    _text(identity["organisation"], f"{where}.organisation")
    _text(identity["revision"], f"{where}.revision")
    _optional_text(identity["tag"], f"{where}.tag")
    _enum(identity["publisher"], PUBLISHERS, f"{where}.publisher")
    if identity["integrityConflict"] is not None:
        conflict = _keys(identity["integrityConflict"], ("at", "reason"), f"{where}.integrityConflict")
        _date(conflict["at"], f"{where}.integrityConflict.at")
        _text(conflict["reason"], f"{where}.integrityConflict.reason")
    paths = set()
    for index, item in enumerate(_list(identity["files"], f"{where}.files")):
        _keys(item, ("path", "sha256"), f"{where}.files[{index}]")
        path = _text(item["path"], f"{where}.files[{index}].path")
        if path in paths:
            raise _fail("duplicate_file", f"{where}.files[{index}]")
        paths.add(path)
        _sha_or_unknown(item["sha256"], f"{where}.files[{index}].sha256")
    derivation = identity["derivation"]
    if identity["publisher"] == FRAMEWORK_MAINTAINER and derivation is None:
        raise _fail("derivation_required", f"{where}.derivation")
    if derivation is not None:
        _keys(derivation, ("fromRepository", "fromRevision", "fromSha256", "conversionDocumentedBy"), f"{where}.derivation")
        _text(derivation["fromRepository"], f"{where}.derivation.fromRepository")
        _text(derivation["fromRevision"], f"{where}.derivation.fromRevision")
        _sha_or_unknown(derivation["fromSha256"], f"{where}.derivation.fromSha256")
        _match(derivation["conversionDocumentedBy"], LOCAL_ID_RE, f"{where}.derivation.conversionDocumentedBy")


def _check_evidence(entry: dict, ledger: Mapping, where: str) -> dict[str, dict]:
    authors = set(entry["authors"]["groups"])
    affiliated = set(entry["authors"]["affiliatedGroups"])
    items: dict[str, dict] = {}
    for index, item in enumerate(_list(entry["evidence"], f"{where}.evidence")):
        at = f"{where}.evidence[{index}]"
        _keys(
            item,
            ("evidenceId", "type", "producer", "source", "locator", "retrievedOn", "retrievedSha256", "recordedAt", "summary"),
            at,
            optional=("repeats", "scope", "reproducedArtefact", "independenceBasis", "subTask", "objectClass", "retracted"),
        )
        evidence_id = _match(item["evidenceId"], LOCAL_ID_RE, f"{at}.evidenceId")
        if evidence_id in items:
            raise _fail("duplicate_evidence_id", at)
        kind = _enum(item["type"], EVIDENCE_TYPES, f"{at}.type")
        producer = _keys(item["producer"], ("group", "relation"), f"{at}.producer")
        group = _match(producer["group"], TOKEN_RE, f"{at}.producer.group")
        relation = _enum(producer["relation"], RELATIONS, f"{at}.producer.relation")
        source = _text(item["source"], f"{at}.source")
        _text(item["locator"], f"{at}.locator")
        _text(item["summary"], f"{at}.summary")
        retrieved = _date(item["retrievedOn"], f"{at}.retrievedOn")
        recorded = _date(item["recordedAt"], f"{at}.recordedAt")
        if retrieved > recorded:
            raise _fail("recorded_before_retrieved", at)
        _sha_or_unknown(item["retrievedSha256"], f"{at}.retrievedSha256")
        if RESERVED_GROUP_RE.match(group) or MAVI_PATH_RE.search(source) or any(
            isinstance(item.get(field), str) and MAVI_WORD_RE.search(item[field]) for field in EVIDENCE_TEXT_FIELDS
        ) or MAVI_RESULT_RE.search(item["summary"]):
            raise _fail("mavi_evidence_in_ledger", at)

        if relation == AUTHOR and group not in authors:
            raise _fail("author_group_not_declared", f"{at}.producer")
        if relation == AFFILIATED and group not in affiliated:
            raise _fail("affiliated_group_not_declared", f"{at}.producer")
        if relation == INDEPENDENT and group in authors | affiliated:
            raise _fail("independent_producer_is_author", f"{at}.producer")
        if kind == FIRST_PARTY and relation == INDEPENDENT:
            raise _fail("first_party_claim_not_from_authors", f"{at}.producer")
        if kind == REPETITION:
            if "repeats" not in item:
                raise _fail("repetition_without_origin", at)
        elif "repeats" in item:
            raise _fail("only_repetition_repeats", f"{at}.repeats")
        allowed_extra: set[str] = set()
        if kind in INDEPENDENT_TYPES:
            allowed_extra = {"scope", "independenceBasis", "reproducedArtefact"}
            if relation != INDEPENDENT:
                raise _fail("independent_evidence_not_independent", f"{at}.producer")
            _text(item.get("independenceBasis"), f"{at}.independenceBasis")
            scope = _enum(item.get("scope"), SCOPES, f"{at}.scope")
            if kind == BENCHMARK and scope != METHOD_SCOPE:
                raise _fail("benchmark_scope_is_method", f"{at}.scope")
            if scope == EXACT:
                _check_artefact_matches(entry, item.get("reproducedArtefact"), f"{at}.reproducedArtefact")
            elif "reproducedArtefact" in item:
                raise _fail("artefact_only_for_exact_scope", f"{at}.reproducedArtefact")
        if kind in INDEPENDENT_TECHNICAL:
            allowed_extra |= {"subTask", "objectClass"}
            if item.get("subTask") not in entry["subTasks"]:
                raise _fail("evidence_subtask_outside_candidate", f"{at}.subTask")
            if item.get("objectClass") != ledger["objectClass"]:
                raise _fail("evidence_object_class_mismatch", f"{at}.objectClass")
        for field in ("scope", "reproducedArtefact", "independenceBasis", "subTask", "objectClass"):
            if field in item and field not in allowed_extra:
                raise _fail("field_not_allowed_for_type", f"{at}.{field}")
        if "retracted" in item:
            retracted = _keys(item["retracted"], ("at", "reason"), f"{at}.retracted")
            if _date(retracted["at"], f"{at}.retracted.at") < recorded:
                raise _fail("retracted_before_recorded", f"{at}.retracted")
            _text(retracted["reason"], f"{at}.retracted.reason")
        items[evidence_id] = item

    # Repetitions resolve to an origin in this entry; chains are followed, cycles refused.
    for evidence_id in items:
        _root(items, evidence_id, f"{where}.evidence.{evidence_id}")

    # An independent item must be its own document: not the same page (however the URL
    # is written) nor the same retrieved bytes as any other item, whatever its type.
    for evidence_id, item in items.items():
        if item["type"] not in INDEPENDENT_TYPES:
            continue
        source = _normalised_source(item["source"])
        digest = item["retrievedSha256"]
        for other_id, other in items.items():
            if other_id == evidence_id:
                continue
            if _normalised_source(other["source"]) == source or (digest != UNKNOWN and other["retrievedSha256"] == digest):
                raise _fail("independent_evidence_not_distinct", f"{where}.evidence.{evidence_id}")
    return items


def _root(items: Mapping[str, dict], evidence_id: str, where: str) -> dict:
    seen: set[str] = set()
    current = evidence_id
    while True:
        if current not in items:
            raise _fail("evidence_reference_unresolved", where)
        if current in seen:
            raise _fail("repetition_cycle", where)
        seen.add(current)
        item = items[current]
        if item["type"] != REPETITION:
            return item
        current = item["repeats"]


def _pinned_files(identity: Mapping) -> list[str]:
    """Sorted weight hashes when every file is hashed at an immutable revision, else []."""
    files = identity.get("files") or []
    revision = identity.get("revision", UNKNOWN)
    if not files or not isinstance(revision, str) or not IMMUTABLE_REVISION_RE.match(revision):
        return []
    hashes = [item["sha256"] for item in files]
    if any(value == UNKNOWN for value in hashes):
        return []
    return sorted(hashes)


def _check_artefact_matches(entry: dict, artefact: object, where: str) -> None:
    """Exact scope names every pinned weight file, or the pinned repository and revision."""
    if artefact is None:
        raise _fail("exact_scope_requires_artefact", where)
    if not isinstance(artefact, dict):
        raise _fail("not_object", where)
    identity = entry["identity"]
    if set(artefact) == {"sha256s"}:
        hashes = _list(artefact["sha256s"], f"{where}.sha256s")
        for value in hashes:
            _match(value, SHA256_RE, f"{where}.sha256s")
        if sorted(hashes) != _pinned_files(identity) or not hashes:
            raise _fail("evidence_artefact_mismatch", where)
        return
    _keys(artefact, ("repository", "revision"), where)
    revision = _match(artefact["revision"], IMMUTABLE_REVISION_RE, f"{where}.revision")
    if artefact["repository"] != identity["repository"] or revision != identity["revision"]:
        raise _fail("evidence_artefact_mismatch", where)


def _check_claims(entry: dict, ledger: dict, items: Mapping[str, dict], where: str) -> None:
    claim_ids = set()
    for index, claim in enumerate(_list(entry["claims"], f"{where}.claims")):
        at = f"{where}.claims[{index}]"
        _keys(
            claim,
            ("claimId", "subTask", "objectClass", "kind", "metric", "value", "dataset", "split",
             "originEvidenceId", "supportingEvidenceIds"),
            at,
        )
        claim_id = _match(claim["claimId"], LOCAL_ID_RE, f"{at}.claimId")
        if claim_id in claim_ids:
            raise _fail("duplicate_claim_id", at)
        claim_ids.add(claim_id)
        if claim["subTask"] not in entry["subTasks"]:
            raise _fail("claim_subtask_outside_candidate", f"{at}.subTask")
        if claim["objectClass"] != ledger["objectClass"]:
            raise _fail("claim_object_class_mismatch", f"{at}.objectClass")
        _enum(claim["kind"], CLAIM_KINDS, f"{at}.kind")
        for field in ("metric", "value", "dataset", "split"):
            _text(claim[field], f"{at}.{field}")
        if MAVI_WORD_RE.search(claim["dataset"]) or MAVI_PATH_RE.search(claim["dataset"]):
            raise _fail("mavi_evidence_in_ledger", f"{at}.dataset")
        origin = claim["originEvidenceId"]
        if origin not in items:
            raise _fail("claim_origin_unresolved", f"{at}.originEvidenceId")
        if items[origin]["type"] == REPETITION:
            raise _fail("claim_origin_is_repetition", f"{at}.originEvidenceId")
        if items[origin]["type"] not in CLAIM_ORIGIN_TYPES:
            raise _fail("claim_origin_not_primary", f"{at}.originEvidenceId")
        for supporting in _list(claim["supportingEvidenceIds"], f"{at}.supportingEvidenceIds"):
            if supporting not in items:
                raise _fail("claim_support_unresolved", f"{at}.supportingEvidenceIds")


def _check_structure(entry: dict, ledger: dict, where: str) -> dict[str, dict]:
    _keys(
        entry,
        ("candidateId", "candidateName", "candidateKind", "subTasks", "identity", "authors", "publication",
         "architecture", "evidence", "claims", "popularitySignals", "caveats", "classification",
         "classificationHistory", "disposition"),
        where,
        optional=("methodCode",),
    )
    _match(entry["candidateId"], CANDIDATE_ID_RE, f"{where}.candidateId")
    _text(entry["candidateName"], f"{where}.candidateName")
    kind = _enum(entry["candidateKind"], KINDS, f"{where}.candidateKind")
    subtasks = _list(entry["subTasks"], f"{where}.subTasks")
    if not subtasks or len(set(subtasks)) != len(subtasks) or not set(subtasks) <= set(ledger["subTasks"]):
        raise _fail("candidate_subtasks_invalid", f"{where}.subTasks")
    if kind == METHOD:
        code = _keys(entry.get("methodCode"), ("repository", "revision"), f"{where}.methodCode")
        _text(code["repository"], f"{where}.methodCode.repository")
        _text(code["revision"], f"{where}.methodCode.revision")
    elif "methodCode" in entry:
        raise _fail("method_code_only_for_method", f"{where}.methodCode")
    _check_identity(entry, f"{where}.identity")
    if kind == BASELINE and (entry["evidence"] or entry["claims"]):
        raise _fail("baseline_has_external_evidence", where)

    authors = _keys(entry["authors"], ("names", "groups", "affiliatedGroups"), f"{where}.authors")
    for index, name in enumerate(_list(authors["names"], f"{where}.authors.names")):
        _text(name, f"{where}.authors.names[{index}]")
    for field in ("groups", "affiliatedGroups"):
        for index, group in enumerate(_list(authors[field], f"{where}.authors.{field}")):
            _match(group, TOKEN_RE, f"{where}.authors.{field}[{index}]")
            if kind != BASELINE and RESERVED_GROUP_RE.match(group):
                raise _fail("mavi_evidence_in_ledger", f"{where}.authors.{field}[{index}]")
    if set(authors["groups"]) & set(authors["affiliatedGroups"]):
        raise _fail("author_and_affiliated_groups_overlap", f"{where}.authors")

    publication = _keys(entry["publication"], ("status", "venue", "reference", "basis"), f"{where}.publication")
    status = _enum(publication["status"], PUBLICATIONS, f"{where}.publication.status")
    if status == "none":
        if any(publication[field] is not None for field in ("venue", "reference", "basis")):
            raise _fail("publication_none_has_details", f"{where}.publication")
    else:
        _text(publication["reference"], f"{where}.publication.reference")
        (_text if status == "peer-reviewed" else _optional_text)(publication["venue"], f"{where}.publication.venue")
        (_text if status == "preprint-established-group" else _optional_text)(
            publication["basis"], f"{where}.publication.basis"
        )

    architecture = _keys(entry["architecture"], ("description", "documentedBy"), f"{where}.architecture")
    _text(architecture["description"], f"{where}.architecture.description")
    if architecture["documentedBy"] is not None:
        _match(architecture["documentedBy"], LOCAL_ID_RE, f"{where}.architecture.documentedBy")

    items = _check_evidence(entry, ledger, where)
    for reference in (architecture["documentedBy"], (entry["identity"].get("derivation") or {}).get("conversionDocumentedBy")):
        if reference is not None and reference not in items:
            raise _fail("evidence_reference_unresolved", f"{where}.{reference}")
    _check_claims(entry, ledger, items, where)

    for index, signal in enumerate(_list(entry["popularitySignals"], f"{where}.popularitySignals")):
        at = f"{where}.popularitySignals[{index}]"
        _keys(signal, ("signal", "value", "observedOn", "source"), at)
        _enum(signal["signal"], ("github-stars", "downloads", "citations", "other"), f"{at}.signal")
        _text(signal["value"], f"{at}.value")
        _date(signal["observedOn"], f"{at}.observedOn")
        _text(signal["source"], f"{at}.source")
    for index, caveat in enumerate(_list(entry["caveats"], f"{where}.caveats")):
        if MAVI_RESULT_RE.search(_text(caveat, f"{where}.caveats[{index}]")):
            raise _fail("mavi_evidence_in_ledger", f"{where}.caveats[{index}]")
    return items


# ------------------------------------------------------------ recomputed judgement


def _active(items: Mapping[str, dict], as_of: date | None) -> dict[str, dict]:
    active = {}
    for evidence_id, item in items.items():
        if as_of is not None and date.fromisoformat(item["recordedAt"]) > as_of:
            continue
        retracted = item.get("retracted")
        if retracted is not None and (as_of is None or date.fromisoformat(retracted["at"]) <= as_of):
            continue
        active[evidence_id] = item
    return active


def _is(active: Mapping[str, dict], evidence_id: str | None, types: Iterable[str]) -> bool:
    return evidence_id is not None and evidence_id in active and active[evidence_id]["type"] in tuple(types)


def provenance_confidence(entry: Mapping, items: Mapping[str, dict], as_of: date | None = None) -> str:
    if entry["candidateKind"] == BASELINE:
        return HIGH
    identity = entry["identity"]
    if _integrity_conflict_at(identity, as_of):
        return LOW
    if UNKNOWN in (identity["repository"], identity["organisation"]) or not _pinned_files(identity):
        return LOW
    if identity["publisher"] in ORIGINAL_PUBLISHERS:
        return HIGH
    derivation = identity["derivation"]
    if (
        identity["publisher"] == FRAMEWORK_MAINTAINER
        and derivation is not None
        and derivation["fromRepository"] != UNKNOWN
        and IMMUTABLE_REVISION_RE.match(derivation["fromRevision"])
        and SHA256_RE.match(derivation["fromSha256"])
        and _is(_active(items, as_of), derivation["conversionDocumentedBy"], (FIRST_PARTY, REPRODUCTION, BENCHMARK, ADOPTION))
    ):
        return MEDIUM
    return LOW


def credibility_class(entry: Mapping, items: Mapping[str, dict], as_of: date | None = None) -> str:
    """The class of candidate-credibility.md §3.2, from the evidence active at ``as_of``."""
    if entry["candidateKind"] == BASELINE:
        return MAVI_OWNED
    identity = entry["identity"]
    if (
        _integrity_conflict_at(identity, as_of)
        or identity["repository"] == UNKNOWN
        or identity["publisher"] == "unknown"
        or not entry["authors"]["groups"]
    ):
        return EXCLUDED
    active = _active(items, as_of)
    confidence = provenance_confidence(entry, items, as_of)
    quality_claims = [claim for claim in entry["claims"] if claim["kind"] == "task-quality"]
    traceable = bool(quality_claims) and all(
        _is(active, claim["originEvidenceId"], CLAIM_ORIGIN_TYPES) for claim in entry["claims"]
    )
    documented = _is(active, entry["architecture"]["documentedBy"], (FIRST_PARTY,))
    if confidence == LOW or not documented or not traceable:
        return REFERENCE
    technical = [item for item in active.values() if item["type"] in INDEPENDENT_TECHNICAL]
    if entry["candidateKind"] == CHECKPOINT:
        technical = [item for item in technical if item["scope"] == EXACT]
    groups = {item["producer"]["group"] for item in active.values() if item["type"] in INDEPENDENT_TYPES}
    if (
        confidence == HIGH
        and entry["publication"]["status"] in ESTABLISHED_PUBLICATIONS
        and technical
        and len(groups) >= 2
    ):
        return ESTABLISHED
    return EMERGING


CLASSIFICATION_INPUT_FIELDS = ("candidateKind", "subTasks", "identity", "authors", "publication", "architecture", "claims")


def classification_inputs_sha256(entry: Mapping) -> str:
    """Hash of every non-evidence field the class depends on (candidate-credibility.md §7)."""
    return document_sha256({field: entry[field] for field in CLASSIFICATION_INPUT_FIELDS})


def _check_history(entry: dict, items: Mapping[str, dict], computed: str, where: str) -> None:
    history = _list(entry["classificationHistory"], f"{where}.classificationHistory")
    if not history:
        raise _fail("history_required", f"{where}.classificationHistory")
    previous_to: str | None = None
    previous_at: date | None = None
    pinned: list[str] | None = None
    baseline = entry["candidateKind"] == BASELINE
    inputs = classification_inputs_sha256(entry)
    on_current_inputs = False
    for index, record in enumerate(history):
        at = f"{where}.classificationHistory[{index}]"
        _keys(
            record,
            ("at", "from", "to", "reason", "evidenceIds", "recordedBy", "reviewedBy", "identitySha256",
             "inputsSha256", "checkpointSha256s"),
            at,
        )
        when = _date(record["at"], f"{at}.at")
        if previous_at is not None and when < previous_at:
            raise _fail("history_not_chronological", at)
        if record["from"] != previous_to:
            raise _fail("history_chain_broken", f"{at}.from")
        to = _enum(record["to"], CLASSES, f"{at}.to")
        _text(record["reason"], f"{at}.reason")
        if _person(_text(record["recordedBy"], f"{at}.recordedBy")) == _person(_text(record["reviewedBy"], f"{at}.reviewedBy")):
            raise _fail("history_reviewer_not_independent", at)
        _match(record["identitySha256"], SHA256_RE, f"{at}.identitySha256")
        _match(record["inputsSha256"], SHA256_RE, f"{at}.inputsSha256")
        # Entries on superseded inputs can only precede the entries on the current ones.
        if record["inputsSha256"] == inputs:
            on_current_inputs = True
        elif on_current_inputs:
            raise _fail("history_entry_on_superseded_inputs", at)
        cited = _list(record["evidenceIds"], f"{at}.evidenceIds")
        for evidence_id in cited:
            if evidence_id not in items:
                raise _fail("history_evidence_unresolved", f"{at}.evidenceIds")
            if date.fromisoformat(items[evidence_id]["recordedAt"]) > when:
                raise _fail("history_cites_later_evidence", f"{at}.evidenceIds")
        hashes = _list(record["checkpointSha256s"], f"{at}.checkpointSha256s")
        for value in hashes:
            _match(value, SHA256_RE, f"{at}.checkpointSha256s")
        if hashes != sorted(set(hashes)):
            raise _fail("history_hashes_not_sorted_unique", f"{at}.checkpointSha256s")
        if baseline:
            if to != MAVI_OWNED or hashes:
                raise _fail("baseline_history_invalid", at)
        elif to in (ESTABLISHED, EMERGING) and not hashes:
            raise _fail("history_class_needs_pinned_bytes", at)
        elif to == MAVI_OWNED:
            raise _fail("mavi_owned_only_for_baseline", at)
        if pinned and hashes != pinned:
            raise _fail("checkpoint_changed_under_same_candidate", at)
        if hashes:
            pinned = hashes
        if not baseline and record["inputsSha256"] == inputs:
            # An entry made on today's inputs is recomputed: it may not claim more than the
            # evidence active on its date supports, and a promotion to established must be
            # supported by the evidence it cites. An entry made on earlier inputs (a later
            # correction changed them) cannot be recomputed; it is fixed by the freeze
            # instead, and it can never make a candidate implementable (§8).
            if CLASS_RANK[to] > CLASS_RANK[credibility_class(entry, items, when)]:
                raise _fail("history_overclaims_on_date", at)
            if to == ESTABLISHED:
                cited_items = {evidence_id: items[evidence_id] for evidence_id in cited}
                if credibility_class(entry, cited_items, when) != ESTABLISHED:
                    raise _fail("promotion_not_supported_by_cited_evidence", at)
        previous_to, previous_at = to, when

    last = history[-1]
    if last["to"] != computed:
        raise _fail("class_change_not_recorded", f"{where}.classificationHistory")
    if last["identitySha256"] != document_sha256(entry["identity"]):
        raise _fail("identity_change_not_recorded", f"{where}.classificationHistory")
    if last["inputsSha256"] != inputs:
        raise _fail("classification_input_change_not_recorded", f"{where}.classificationHistory")
    current = [] if baseline else _pinned_files(entry["identity"])
    if last["checkpointSha256s"] != current:
        raise _fail("checkpoint_changed_under_same_candidate", f"{where}.classificationHistory")


def _check_disposition(entry: dict, items: Mapping[str, dict], computed: str, confidence: str, where: str) -> None:
    disposition = _keys(
        entry["disposition"],
        ("status", "reasonClass", "reason", "revisitTrigger", "decidedBy"),
        f"{where}.disposition",
        optional=("reviewedBy", "emergingShortlistBasis"),
    )
    status = _enum(disposition["status"], DISPOSITIONS, f"{where}.disposition.status")
    reason_class = disposition["reasonClass"]
    allowed_reasons = REASONS_BY_DISPOSITION[status]
    if allowed_reasons:
        _enum(reason_class, allowed_reasons, f"{where}.disposition.reasonClass")
    elif reason_class is not None:
        raise _fail("reason_class_not_allowed", f"{where}.disposition.reasonClass")
    if status == DISCOVERED:
        _optional_text(disposition["reason"], f"{where}.disposition.reason")
        _optional_text(disposition["decidedBy"], f"{where}.disposition.decidedBy")
    else:
        _text(disposition["reason"], f"{where}.disposition.reason")
        _text(disposition["decidedBy"], f"{where}.disposition.decidedBy")
    if status in (REFERENCE_ONLY, DEFERRED):
        _text(disposition["revisitTrigger"], f"{where}.disposition.revisitTrigger")
    else:
        _optional_text(disposition["revisitTrigger"], f"{where}.disposition.revisitTrigger")
    _optional_text(disposition.get("reviewedBy"), f"{where}.disposition.reviewedBy")
    # Licence reasoning belongs only to the evaluation-permission carve-out (MSR method §2).
    if "licen" in (disposition["reason"] or "").lower() and reason_class != "evaluation-permission":
        raise _fail("licence_reason_not_allowed", f"{where}.disposition.reason")

    if status not in DISPOSITIONS_BY_CLASS[computed]:
        raise _fail("disposition_not_allowed_for_class", f"{where}.disposition.status")
    if reason_class == "credibility" and computed not in CREDIBILITY_REASON_CLASSES[status]:
        raise _fail("credibility_reason_contradicts_evidence", f"{where}.disposition.reasonClass")
    if computed == EXCLUDED and status == NOT_SHORTLISTED and reason_class != "credibility":
        raise _fail("excluded_discovery_reason_is_credibility", f"{where}.disposition.reasonClass")

    # R-CRED: an emerging candidate is normally held as reference-only. Shortlisting one is
    # an exception that needs a recorded basis and a second reviewer.
    basis = disposition.get("emergingShortlistBasis")
    if status == SHORTLISTED and computed == EMERGING:
        _text(basis, f"{where}.disposition.emergingShortlistBasis")
        reviewer = _text(disposition.get("reviewedBy"), f"{where}.disposition.reviewedBy")
        if _person(reviewer) == _person(disposition["decidedBy"]):
            raise _fail("shortlist_reviewer_not_independent", f"{where}.disposition")
    elif basis is not None and not (status == SHORTLISTED and computed == ESTABLISHED):
        # The basis stays on record when a shortlisted emerging candidate is later promoted.
        raise _fail("shortlist_basis_only_for_emerging", f"{where}.disposition.emergingShortlistBasis")

    if status == SHORTLISTED and entry["candidateKind"] != BASELINE:
        if confidence not in (HIGH, MEDIUM) or not _pinned_files(entry["identity"]):
            raise _fail("shortlist_requires_pinned_provenance", f"{where}.identity")
        if entry["candidateKind"] == METHOD and not IMMUTABLE_REVISION_RE.match(entry["methodCode"]["revision"]):
            raise _fail("shortlist_requires_method_revision", f"{where}.methodCode.revision")
        relied = {claim["originEvidenceId"] for claim in entry["claims"]}
        relied |= {i for i, item in _active(items, None).items() if item["type"] in INDEPENDENT_TYPES}
        for evidence_id in sorted(relied):
            if items[evidence_id]["retrievedSha256"] == UNKNOWN:
                raise _fail("shortlist_requires_snapshotted_evidence", f"{where}.evidence.{evidence_id}")


def validate_ledger(ledger: object) -> dict[str, dict]:
    """Validate a ledger; return ``{candidateId: {class, provenanceConfidence, disposition}}``."""
    _reject_licence_keys(ledger, "ledger")
    _keys(
        ledger,
        ("schema", "eventId", "capabilityId", "objectClass", "subTasks", "methodRevision", "candidates"),
        "ledger",
        optional=("frozenOn",),
    )
    if "frozenOn" in ledger:
        _date(ledger["frozenOn"], "ledger.frozenOn")
    if ledger["schema"] != LEDGER_SCHEMA:
        raise _fail("schema_unsupported", "ledger.schema")
    if ledger["methodRevision"] != METHOD_REVISION:
        raise _fail("method_revision_unsupported", "ledger.methodRevision")
    capability = _match(ledger["capabilityId"], TOKEN_RE, "ledger.capabilityId")
    if not re.fullmatch(rf"msr-{re.escape(capability)}-\d{{4}}-\d{{2}}", str(ledger["eventId"])):
        raise _fail("event_id_mismatch", "ledger.eventId")
    _match(ledger["objectClass"], TOKEN_RE, "ledger.objectClass")
    subtasks = _list(ledger["subTasks"], "ledger.subTasks")
    if not subtasks or len(set(subtasks)) != len(subtasks):
        raise _fail("subtasks_invalid", "ledger.subTasks")
    for index, subtask in enumerate(subtasks):
        _match(subtask, SUBTASK_RE, f"ledger.subTasks[{index}]")
    if capability in EVENT_SCOPES:
        object_class, scoped = EVENT_SCOPES[capability]
        if ledger["objectClass"] != object_class or sorted(subtasks) != sorted(scoped):
            raise _fail("event_scope_mismatch", "ledger")

    summary: dict[str, dict] = {}
    owners: dict[str, list[dict]] = {}
    for index, entry in enumerate(_list(ledger["candidates"], "ledger.candidates")):
        where = f"ledger.candidates[{index}]"
        items = _check_structure(entry, ledger, where)
        candidate_id = entry["candidateId"]
        if candidate_id in summary:
            raise _fail("duplicate_candidate_id", where)
        # One entry per checkpoint. An entry that uses the same bytes differently (a method
        # with its own heads, MSR method §5.1, beside another method or a zero-shot
        # checkpoint entry) may share them only with an identical identity block.
        for sha in _pinned_files(entry["identity"]) if entry["candidateKind"] != BASELINE else ():
            for owner in owners.setdefault(sha, []):
                if not (METHOD in (owner["candidateKind"], entry["candidateKind"]) and owner["identity"] == entry["identity"]):
                    raise _fail("weight_hash_shared_by_two_candidates", where)
            owners[sha].append(entry)
        computed = credibility_class(entry, items)
        confidence = provenance_confidence(entry, items)
        classification = _keys(entry["classification"], ("class", "provenanceConfidence"), f"{where}.classification")
        if classification["class"] != computed:
            raise _fail("declared_class_differs_from_computed", f"{where}.classification.class")
        if classification["provenanceConfidence"] != confidence:
            raise _fail("declared_confidence_differs_from_computed", f"{where}.classification.provenanceConfidence")
        _check_history(entry, items, computed, where)
        _check_disposition(entry, items, computed, confidence, where)
        summary[candidate_id] = {
            "class": computed,
            "provenanceConfidence": confidence,
            "disposition": entry["disposition"]["status"],
        }
    return summary


def _shortlist(ledger: Mapping) -> set[str]:
    return {e["candidateId"] for e in ledger["candidates"] if e["disposition"]["status"] == SHORTLISTED}


FROZEN_APPEND_ONLY = ("evidence", "claims", "classificationHistory", "caveats", "popularitySignals")


def _dates(entry: Mapping) -> list[date]:
    """Every date an entry records."""
    found = [date.fromisoformat(item["recordedAt"]) for item in entry["evidence"]]
    found += [date.fromisoformat(item["retracted"]["at"]) for item in entry["evidence"] if "retracted" in item]
    found += [date.fromisoformat(record["at"]) for record in entry["classificationHistory"]]
    found += [date.fromisoformat(signal["observedOn"]) for signal in entry["popularitySignals"]]
    conflict = entry["identity"].get("integrityConflict")
    if conflict is not None:
        found.append(date.fromisoformat(conflict["at"]))
    return found


def _check_sealed_on(ledger: Mapping, sealed_on: date, code: str) -> None:
    """A sealing date is no earlier than anything the sealed copy records."""
    for entry in ledger["candidates"]:
        if any(value > sealed_on for value in _dates(entry)):
            raise _fail(code, f"ledger.{entry['candidateId']}")


def validate_evolution(older: dict, newer: dict, since: date | None = None) -> None:
    """A sealed ledger copy only grows afterwards (candidate-credibility.md §7).

    ``older`` is the frozen copy (sealed on its ``frozenOn``) or the decision snapshot
    (sealed on the decision date, passed as ``since``). Everything it holds is kept
    unchanged: an evidence item may only gain a ``retracted``, and lists only grow.
    Everything added, including a new candidate, is dated on or after the sealing date,
    so nothing can be backdated before the freeze or the decision. The shortlist is
    fixed, and a shortlisted candidate is fixed apart from its append-only evidence,
    history, caveats and popularity signals and its recomputed classification.
    """
    validate_ledger(older)
    validate_ledger(newer)
    if older["eventId"] != newer["eventId"]:
        raise _fail("evolution_event_mismatch", "ledger.eventId")
    if "frozenOn" not in older:
        raise _fail("frozen_ledger_without_date", "ledger.frozenOn")
    if newer.get("frozenOn", older["frozenOn"]) != older["frozenOn"]:
        raise _fail("frozen_date_changed", "ledger.frozenOn")
    bound = date.fromisoformat(older["frozenOn"]) if since is None else since
    _check_sealed_on(older, bound, "sealed_copy_postdates_its_seal")
    for field in ("capabilityId", "objectClass", "subTasks", "methodRevision"):
        if newer[field] != older[field]:
            raise _fail("frozen_ledger_scope_changed", f"ledger.{field}")
    if _shortlist(older) != _shortlist(newer):
        raise _fail("shortlist_changed_after_freeze", "ledger.candidates")
    before = {entry["candidateId"]: entry for entry in older["candidates"]}
    for later in newer["candidates"]:
        if later["candidateId"] not in before and any(value < bound for value in _dates(later)):
            raise _fail("appended_before_freeze", f"ledger.{later['candidateId']}")
    now = {entry["candidateId"]: entry for entry in newer["candidates"]}
    for entry in older["candidates"]:
        candidate_id = entry["candidateId"]
        where = f"ledger.{candidate_id}"
        later = now.get(candidate_id)
        if later is None:
            raise _fail("frozen_candidate_removed", where)
        for field in FROZEN_APPEND_ONLY:
            if later[field][: len(entry[field])] != entry[field] and field != "evidence":
                raise _fail("frozen_list_rewritten", f"{where}.{field}")
        for record in later["classificationHistory"][len(entry["classificationHistory"]):]:
            if date.fromisoformat(record["at"]) < bound:
                raise _fail("appended_before_freeze", f"{where}.classificationHistory")
        for signal in later["popularitySignals"][len(entry["popularitySignals"]):]:
            if date.fromisoformat(signal["observedOn"]) < bound:
                raise _fail("appended_before_freeze", f"{where}.popularitySignals")
        later_items = {item["evidenceId"]: item for item in later["evidence"]}
        sealed_ids = {item["evidenceId"] for item in entry["evidence"]}
        for item in entry["evidence"]:
            kept = later_items.get(item["evidenceId"])
            if kept is None:
                raise _fail("frozen_evidence_removed", f"{where}.{item['evidenceId']}")
            added_retraction = "retracted" in kept and "retracted" not in item
            if {k: v for k, v in kept.items() if not (k == "retracted" and added_retraction)} != item:
                raise _fail("frozen_evidence_changed", f"{where}.{item['evidenceId']}")
            if added_retraction and date.fromisoformat(kept["retracted"]["at"]) < bound:
                raise _fail("appended_before_freeze", f"{where}.{item['evidenceId']}.retracted")
        for evidence_id, item in later_items.items():
            if evidence_id not in sealed_ids and date.fromisoformat(item["recordedAt"]) < bound:
                raise _fail("appended_before_freeze", f"{where}.{evidence_id}")
        if entry["disposition"]["status"] == SHORTLISTED:
            # Claims are classification inputs: a shortlisted candidate's are fixed too,
            # so an append cannot unsettle a recorded promotion (§8).
            fixed = set(entry) - (set(FROZEN_APPEND_ONLY) - {"claims"}) - {"classification"}
            for field in sorted(fixed):
                if later.get(field) != entry[field]:
                    raise _fail("frozen_shortlisted_field_changed", f"{where}.{field}")


# ------------------------------------------------------------- decision summary


def _maximal(scores: Mapping[str, float]) -> set[str]:
    if not scores:
        return set()
    best = max(scores.values())
    return {candidate for candidate, score in scores.items() if score == best}


def validate_decision(decision: object, ledger: dict, frozen: dict) -> None:
    """Validate a decision summary against its decision snapshot and frozen ledger (§8).

    ``ledger`` is the ledger as it stood at the decision (``<event-id>-evidence-ledger-
    decided.json``); nothing it holds may postdate the decision.
    """
    validate_evolution(frozen, ledger)
    entries = {entry["candidateId"]: entry for entry in ledger["candidates"]}
    _keys(
        decision,
        ("schema", "eventId", "eventState", "outcome", "decidedOn", "ledgerSha256", "frozenLedgerSha256",
         "protocolSha256", "targetProfiles", "evaluated", "licence", "strongestReported",
         "highestTaskQualityEvaluated", "strongestEvaluatedTechnical", "strongestClearedPerProfile", "implementation"),
        "decision",
    )
    if decision["schema"] != DECISION_SCHEMA:
        raise _fail("schema_unsupported", "decision.schema")
    if decision["eventId"] != ledger["eventId"]:
        raise _fail("decision_event_mismatch", "decision.eventId")
    if decision["ledgerSha256"] != document_sha256(ledger):
        raise _fail("decision_ledger_hash_mismatch", "decision.ledgerSha256")
    if decision["frozenLedgerSha256"] != document_sha256(frozen):
        raise _fail("decision_frozen_ledger_hash_mismatch", "decision.frozenLedgerSha256")
    _match(decision["protocolSha256"], SHA256_RE, "decision.protocolSha256")
    state = _enum(decision["eventState"], EVENT_STATES, "decision.eventState")
    decided_on = _date(decision["decidedOn"], "decision.decidedOn")
    _check_sealed_on(ledger, decided_on, "decision_snapshot_postdates_decision")
    profiles = _list(decision["targetProfiles"], "decision.targetProfiles")
    if not profiles or len(set(profiles)) != len(profiles):
        raise _fail("target_profiles_invalid", "decision.targetProfiles")
    for index, profile in enumerate(profiles):
        _match(profile, TOKEN_RE, f"decision.targetProfiles[{index}]")

    # Every candidate shortlisted at freeze is evaluated, and only those are: an
    # inconvenient candidate cannot be dropped between shortlist and ranking.
    evaluated: dict[str, dict] = {}
    for index, row in enumerate(_list(decision["evaluated"], "decision.evaluated")):
        at = f"decision.evaluated[{index}]"
        _keys(
            row,
            ("candidateId", "artefactSha256s", "maviTrainedArtefacts", "maviRevision", "technicalGates",
             "comparativeScore", "taskQualityScore", "measurementSha256"),
            at,
        )
        candidate_id = row["candidateId"]
        if candidate_id in evaluated:
            raise _fail("duplicate_evaluated_candidate", at)
        if candidate_id not in entries:
            raise _fail("evaluated_candidate_not_in_ledger", at)
        _match(row["measurementSha256"], SHA256_RE, f"{at}.measurementSha256")
        _number(row["taskQualityScore"], f"{at}.taskQualityScore")
        gates = _enum(row["technicalGates"], ("passed", "failed"), f"{at}.technicalGates")
        if gates == "passed":
            _number(row["comparativeScore"], f"{at}.comparativeScore")
        elif row["comparativeScore"] is not None:
            raise _fail("failed_gate_has_score", f"{at}.comparativeScore")
        _check_evaluated_artefact(entries[candidate_id], row, at)
        evaluated[candidate_id] = row
    if set(evaluated) != _shortlist(frozen):
        raise _fail("evaluated_set_differs_from_shortlist", "decision.evaluated")

    licence = _keys(decision["licence"], evaluated, "decision.licence")
    for candidate_id in evaluated:
        statuses = _keys(licence[candidate_id], profiles, f"decision.licence.{candidate_id}")
        for profile in profiles:
            _enum(statuses[profile], LICENCE_STATUSES, f"decision.licence.{candidate_id}.{profile}")

    # The strongest reported candidate is a recorded judgement over class R evidence; it
    # must resolve to a ledger claim and carry the "not reproduced" label.
    reported = decision["strongestReported"]
    if reported is None:
        if any(entry["claims"] for entry in entries.values()):
            raise _fail("strongest_reported_required", "decision.strongestReported")
    else:
        _keys(reported, ("candidateId", "claimId", "label"), "decision.strongestReported")
        entry = entries.get(reported["candidateId"])
        if entry is None or reported["claimId"] not in {claim["claimId"] for claim in entry["claims"]}:
            raise _fail("strongest_reported_unresolved", "decision.strongestReported")
        if reported["label"] != REPORTED_LABEL:
            raise _fail("strongest_reported_label", "decision.strongestReported.label")

    # Task quality alone, over every evaluated candidate (gates, runtime and licence ignored).
    quality = {candidate: row["taskQualityScore"] for candidate, row in evaluated.items()}
    highest = decision["highestTaskQualityEvaluated"]
    if quality and highest not in _maximal(quality):
        raise _fail("highest_task_quality_not_maximal", "decision.highestTaskQualityEvaluated")
    if not quality and highest is not None:
        raise _fail("highest_task_quality_without_evaluation", "decision.highestTaskQualityEvaluated")

    # The technical ranking reads recorded scores only: never licence, never credibility.
    technical = {c: row["comparativeScore"] for c, row in evaluated.items() if row["technicalGates"] == "passed"}
    strongest = decision["strongestEvaluatedTechnical"]
    if technical and strongest not in _maximal(technical):
        raise _fail("strongest_technical_not_maximal", "decision.strongestEvaluatedTechnical")
    if not technical and strongest is not None:
        raise _fail("strongest_technical_without_passing_candidate", "decision.strongestEvaluatedTechnical")

    cleared = _keys(decision["strongestClearedPerProfile"], profiles, "decision.strongestClearedPerProfile")
    for profile in profiles:
        eligible = {c: s for c, s in technical.items() if licence[c][profile] == CLEARED}
        named = cleared[profile]
        if eligible and named not in _maximal(eligible):
            raise _fail("strongest_cleared_not_derived", f"decision.strongestClearedPerProfile.{profile}")
        if not eligible and named is not None:
            raise _fail("strongest_cleared_not_derived", f"decision.strongestClearedPerProfile.{profile}")

    implementation = decision["implementation"]
    if implementation is not None:
        _check_implementation(implementation, state, evaluated, licence, profiles, entries)
    outcome = decision["outcome"]
    if state != "CLOSED":
        if outcome is not None:
            raise _fail("outcome_before_closed", "decision.outcome")
        return
    _enum(outcome, OUTCOMES, "decision.outcome")
    components = [] if implementation is None else implementation["components"]
    baseline_only = bool(components) and all(entries[c]["candidateKind"] == BASELINE for c in components)
    if outcome == "SELECTED_FOR_PACKAGING" and (not components or baseline_only):
        raise _fail("outcome_implementation_inconsistent", "decision.outcome")
    if outcome == "BASELINE_SELECTED" and not baseline_only:
        raise _fail("outcome_implementation_inconsistent", "decision.outcome")
    if outcome in ("INCUMBENT_RETAINED", "NO_QUALIFIABLE_CANDIDATE") and components:
        raise _fail("outcome_implementation_inconsistent", "decision.outcome")


def _check_evaluated_artefact(entry: dict, row: dict, where: str) -> None:
    """The evaluated bytes are exactly the ledger identity plus declared MAVI-trained artefacts."""
    artefacts = _list(row["artefactSha256s"], f"{where}.artefactSha256s")
    for value in artefacts:
        _match(value, SHA256_RE, f"{where}.artefactSha256s")
    if artefacts != sorted(set(artefacts)):
        raise _fail("artefacts_not_sorted_unique", f"{where}.artefactSha256s")
    trained = set()
    for index, item in enumerate(_list(row["maviTrainedArtefacts"], f"{where}.maviTrainedArtefacts")):
        at = f"{where}.maviTrainedArtefacts[{index}]"
        _keys(item, ("sha256", "trainingManifestSha256"), at)
        trained.add(_match(item["sha256"], SHA256_RE, f"{at}.sha256"))
        _match(item["trainingManifestSha256"], SHA256_RE, f"{at}.trainingManifestSha256")
    kind = entry["candidateKind"]
    if kind == BASELINE:
        revision = _match(row["maviRevision"], IMMUTABLE_REVISION_RE, f"{where}.maviRevision")
        if entry["identity"]["revision"] not in (UNKNOWN, revision):
            raise _fail("evaluated_artefact_differs_from_ledger", f"{where}.maviRevision")
        if artefacts or trained:
            raise _fail("evaluated_artefact_differs_from_ledger", f"{where}.artefactSha256s")
        return
    if row["maviRevision"] is not None:
        raise _fail("mavi_revision_only_for_baseline", f"{where}.maviRevision")
    if kind == CHECKPOINT and trained:
        raise _fail("checkpoint_has_mavi_trained_artefacts", f"{where}.maviTrainedArtefacts")
    if kind == METHOD and not trained:
        raise _fail("method_without_mavi_trained_artefact", f"{where}.maviTrainedArtefacts")
    if artefacts != sorted(set(_pinned_files(entry["identity"])) | trained):
        raise _fail("evaluated_artefact_differs_from_ledger", f"{where}.artefactSha256s")


def _check_implementation(
    implementation: object,
    state: str,
    evaluated: Mapping[str, dict],
    licence: Mapping[str, Mapping[str, str]],
    profiles: list,
    entries: Mapping[str, dict],
) -> None:
    _keys(implementation, ("components", "decidedBy", "rationale"), "decision.implementation")
    if state not in IMPLEMENTATION_STATES:
        raise _fail("implementation_before_qualification_pending", "decision.implementation")
    _text(implementation["decidedBy"], "decision.implementation.decidedBy")
    _text(implementation["rationale"], "decision.implementation.rationale")
    components = _list(implementation["components"], "decision.implementation.components")
    if not components or len(set(components)) != len(components):
        raise _fail("implementation_components_invalid", "decision.implementation.components")
    for candidate_id in components:
        where = f"decision.implementation.{candidate_id}"
        row = evaluated.get(candidate_id)
        if row is None:
            raise _fail("implementation_not_evaluated", where)
        if row["technicalGates"] != "passed":
            raise _fail("implementation_failed_technical_gate", where)
        if any(licence[candidate_id][profile] != CLEARED for profile in profiles):
            raise _fail("implementation_not_cleared_for_every_profile", where)
        # The snapshot holds nothing after the decision date, so its last history entry is
        # the one in force on that date; that entry is on the current inputs and equals
        # the recomputed class (§7).
        if entries[candidate_id]["classificationHistory"][-1]["to"] not in IMPLEMENTABLE_CLASSES:
            raise _fail("implementation_requires_established", where)


# ------------------------------------------------------------- repository scan


def validate_repository(repo: Path) -> list[str]:
    """Validate every committed ledger, frozen ledger and decision summary; return the paths checked."""
    root = repo / MODEL_SELECTION_DIR
    checked: list[str] = []
    ledgers: dict[Path, dict] = {}

    def relative(path: Path) -> str:
        return path.relative_to(repo).as_posix()

    for path in sorted(root.glob(f"*/msr-*{LEDGER_SUFFIX}")):
        ledger = read_json(path)
        validate_ledger(ledger)
        event = path.name[: -len(LEDGER_SUFFIX)]
        if ledger["eventId"] != event or ledger["capabilityId"] != path.parent.name:
            raise _fail("ledger_location_mismatch", relative(path))
        ledgers[path.parent / event] = ledger
        checked.append(relative(path))
    frozen_ledgers: dict[Path, dict] = {}
    for path in sorted(root.glob(f"*/msr-*{FROZEN_SUFFIX}")):
        event = path.parent / path.name[: -len(FROZEN_SUFFIX)]
        if event not in ledgers:
            raise _fail("frozen_ledger_without_ledger", relative(path))
        frozen = read_json(path)
        validate_evolution(frozen, ledgers[event])
        protocol = event.parent / f"{event.name}{PROTOCOL_SUFFIX}"
        text = protocol.read_text(encoding="utf-8") if protocol.is_file() else ""
        if document_sha256(frozen) not in text or frozen.get("frozenOn", "") not in text:
            raise _fail("frozen_ledger_not_cited_by_protocol", relative(path))
        frozen_ledgers[event] = frozen
        checked.append(relative(path))
    for protocol in sorted(root.glob(f"*/msr-*{PROTOCOL_SUFFIX}")):
        event = protocol.parent / protocol.name[: -len(PROTOCOL_SUFFIX)]
        if event not in frozen_ledgers:
            raise _fail("protocol_without_frozen_ledger", relative(protocol))
        record = event.parent / f"{event.name}.md"
        if not record.is_file() or lf_normalised_sha256(protocol) not in record.read_text(encoding="utf-8"):
            raise _fail("protocol_hash_not_recorded_in_record", relative(protocol))
    for path in sorted(root.glob(f"*/msr-*{DECISION_SUFFIX}")):
        event = path.parent / path.name[: -len(DECISION_SUFFIX)]
        if event not in frozen_ledgers:
            raise _fail("decision_without_frozen_ledger", relative(path))
        decision = read_json(path)
        protocol = event.parent / f"{event.name}{PROTOCOL_SUFFIX}"
        if decision.get("protocolSha256") != lf_normalised_sha256(protocol):
            raise _fail("decision_protocol_hash_mismatch", relative(path))
        snapshot_path = event.parent / f"{event.name}{SNAPSHOT_SUFFIX}"
        if not snapshot_path.is_file():
            raise _fail("decision_without_snapshot", relative(path))
        snapshot = read_json(snapshot_path)
        record_text = (event.parent / f"{event.name}.md").read_text(encoding="utf-8")
        if lf_normalised_sha256(path) not in record_text or lf_normalised_sha256(snapshot_path) not in record_text:
            raise _fail("decision_hash_not_recorded_in_record", relative(path))
        validate_decision(decision, snapshot, frozen_ledgers[event])
        # After the decision the working ledger only grows, and nothing is dated before it.
        validate_evolution(snapshot, ledgers[event], since=date.fromisoformat(decision["decidedOn"]))
        checked.append(relative(snapshot_path))
        checked.append(relative(path))
    for path in sorted(root.glob(f"*/msr-*{SNAPSHOT_SUFFIX}")):
        if relative(path) not in checked:
            raise _fail("snapshot_without_decision", relative(path))
    return checked
