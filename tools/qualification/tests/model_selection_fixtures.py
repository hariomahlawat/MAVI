"""Synthetic External Evidence Ledger fixtures (candidate-credibility.md).

Every name, group, URL and hash here is invented. None describes a real model, and
none is evidence about one.
"""

from __future__ import annotations

import copy
import hashlib

from model_selection.credibility import (
    CredibilityError,
    DECISION_SCHEMA,
    LEDGER_SCHEMA,
    METHOD_REVISION,
    _check_evidence,
    credibility_class,
    document_sha256,
    provenance_confidence,
    _pinned_files,
)


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def commit(label: str) -> str:
    return hashlib.sha1(label.encode()).hexdigest()


def evidence(evidence_id, kind, group, relation, *, recorded="2026-10-01", source=None, **extra):
    item = {
        "evidenceId": evidence_id,
        "type": kind,
        "producer": {"group": group, "relation": relation},
        "source": source or f"https://example.invalid/{group}/{evidence_id}",
        "locator": "Table 2",
        "retrievedOn": recorded,
        "retrievedSha256": sha(f"doc-{evidence_id}"),
        "recordedAt": recorded,
        "summary": f"synthetic {kind}",
    }
    item.update(extra)
    return item


def claim(claim_id, origin, *, subtask="T-VC", object_class="vehicle", supporting=()):
    return {
        "claimId": claim_id,
        "subTask": subtask,
        "objectClass": object_class,
        "kind": "task-quality",
        "metric": "top-1 accuracy",
        "value": "90.0",
        "dataset": "synthetic-colour-set",
        "split": "test",
        "originEvidenceId": origin,
        "supportingEvidenceIds": list(supporting),
    }


def checkpoint_identity(label, *, publisher="original-organisation", pinned=True):
    return {
        "repository": f"https://example.invalid/{label}/repo",
        "organisation": f"{label}-org",
        "revision": commit(label) if pinned else "UNKNOWN",
        "tag": "v1.0",
        "files": [{"path": "weights/model.bin", "sha256": sha(f"weights-{label}") if pinned else "UNKNOWN"}],
        "publisher": publisher,
        "derivation": None,
        "integrityConflict": None,
    }


def exact(label):
    return {"sha256": sha(f"weights-{label}")}


def base_entry(candidate_id, label, *, kind="checkpoint", subtasks=("T-VC",)):
    return {
        "candidateId": candidate_id,
        "candidateName": f"Synthetic {label}",
        "candidateKind": kind,
        "subTasks": list(subtasks),
        "identity": checkpoint_identity(label),
        "authors": {"names": [f"Author of {label}"], "groups": [f"{label}-lab"]},
        "publication": {
            "status": "peer-reviewed",
            "venue": "Synthetic Conference 2026",
            "reference": f"https://example.invalid/{label}/paper",
            "basis": None,
        },
        "architecture": {"description": "convolutional classifier", "documentedBy": "E-PAPER"},
        "evidence": [evidence("E-PAPER", "first-party-claim", f"{label}-lab", "author")],
        "claims": [claim("C1", "E-PAPER")],
        "popularitySignals": [],
        "caveats": [],
        "classification": None,
        "classificationHistory": [],
        "disposition": {
            "status": "SHORTLISTED",
            "reasonClass": None,
            "reason": "reported evidence on vehicle colour",
            "revisitTrigger": None,
            "decidedBy": "synthetic-reviewer",
        },
    }


def established(candidate_id="VC-EST", label="est"):
    entry = base_entry(candidate_id, label)
    entry["evidence"] += [
        evidence("E-REPRO", "independent-reproduction", "other-lab", "independent",
                 scope="exact-checkpoint", reproducedArtefact=exact(label), independenceBasis="no shared authors"),
        evidence("E-ADOPT", "adoption", "framework-team", "independent",
                 scope="method", independenceBasis="separate organisation"),
    ]
    return entry


def emerging(candidate_id="VC-EMG", label="emg"):
    entry = base_entry(candidate_id, label)
    entry["publication"] = {"status": "preprint", "venue": None,
                            "reference": f"https://example.invalid/{label}/preprint", "basis": None}
    entry["evidence"] += [
        evidence(f"E-COPY{n}", "repetition", f"site-{n}", "independent", repeats="E-PAPER") for n in range(5)
    ]
    entry["claims"][0]["supportingEvidenceIds"] = [f"E-COPY{n}" for n in range(5)]
    return entry


def reference(candidate_id="VC-REF", label="ref"):
    entry = base_entry(candidate_id, label)
    entry["identity"] = checkpoint_identity(label, publisher="third-party")
    entry["disposition"] = {
        "status": "REFERENCE_ONLY",
        "reasonClass": "credibility",
        "reason": "community re-upload with self-reported figures only",
        "revisitTrigger": "the original authors publish the checkpoint",
        "decidedBy": "synthetic-reviewer",
    }
    return entry


def excluded(candidate_id="VC-EXC", label="exc"):
    entry = base_entry(candidate_id, label)
    entry["identity"] = checkpoint_identity(label, publisher="unknown", pinned=False)
    entry["identity"]["repository"] = "UNKNOWN"
    entry["disposition"] = {
        "status": "NOT_SHORTLISTED",
        "reasonClass": "credibility",
        "reason": "no identifiable original source",
        "revisitTrigger": None,
        "decidedBy": "synthetic-reviewer",
    }
    return entry


def method(candidate_id="VC-MTH", label="mth"):
    entry = base_entry(candidate_id, label, kind="method")
    entry["identity"] = checkpoint_identity(label, publisher="recognised-framework-maintainer")
    entry["identity"]["derivation"] = {
        "fromRepository": f"https://example.invalid/{label}/original",
        "fromRevision": commit(f"orig-{label}"),
        "fromSha256": sha(f"orig-{label}"),
        "conversionDocumentedBy": "E-CONV",
    }
    entry["methodCode"] = {"repository": f"https://example.invalid/{label}/code", "revision": commit(f"code-{label}")}
    entry["evidence"].append(evidence("E-CONV", "first-party-claim", f"{label}-lab", "author",
                                      source=f"https://example.invalid/{label}/conversion-notes"))
    return entry


def baseline(candidate_id="VC-B0"):
    return {
        "candidateId": candidate_id,
        "candidateName": "deterministic chroma + Lab naming",
        "candidateKind": "mavi-baseline",
        "subTasks": ["T-VC"],
        "identity": {"repository": "MAVI", "revision": "UNKNOWN"},
        "authors": {"names": ["MAVI"], "groups": ["mavi"]},
        "publication": {"status": "none", "venue": None, "reference": None, "basis": None},
        "architecture": {"description": "region chroma clustering", "documentedBy": None},
        "evidence": [],
        "claims": [],
        "popularitySignals": [],
        "caveats": [],
        "classification": None,
        "classificationHistory": [],
        "disposition": {
            "status": "SHORTLISTED",
            "reasonClass": None,
            "reason": "the floor every learned candidate must beat",
            "revisitTrigger": None,
            "decidedBy": "synthetic-reviewer",
        },
    }


def items(entry):
    return {item["evidenceId"]: item for item in entry["evidence"]}


def settle(entry, at="2026-10-02", reason="classified from recorded evidence"):
    """Set the declared classification to the computed one and append a history entry if needed."""
    try:
        _check_evidence(entry, "fixture")
    except CredibilityError:
        return entry  # a deliberately malformed entry: validate_ledger reports the defect
    computed = credibility_class(entry, items(entry))
    entry["classification"] = {"class": computed, "provenanceConfidence": provenance_confidence(entry, items(entry))}
    history = entry["classificationHistory"]
    record = {
        "at": at,
        "from": history[-1]["to"] if history else None,
        "to": computed,
        "reason": reason,
        "evidenceIds": [item["evidenceId"] for item in entry["evidence"] if item["recordedAt"] <= at],
        "recordedBy": "synthetic-curator",
        "reviewedBy": "synthetic-reviewer",
        "identitySha256": document_sha256(entry["identity"]),
        "checkpointSha256s": [] if entry["candidateKind"] == "mavi-baseline" else _pinned_files(entry["identity"]),
    }
    if not history or {k: history[-1][k] for k in ("to", "identitySha256", "checkpointSha256s")} != {
        k: record[k] for k in ("to", "identitySha256", "checkpointSha256s")
    }:
        history.append(record)
    return entry


def ledger(*entries, object_class="vehicle", capability="vehicle-attributes", subtasks=("T-VC",)):
    if not entries:
        entries = (baseline(), established(), emerging(), reference(), excluded(), method())
    return {
        "schema": LEDGER_SCHEMA,
        "eventId": f"msr-{capability}-2026-01",
        "capabilityId": capability,
        "objectClass": object_class,
        "subTasks": list(subtasks),
        "methodRevision": METHOD_REVISION,
        "candidates": [settle(copy.deepcopy(entry)) for entry in entries],
    }


def evaluated_row(entry, *, score, quality=None, gates="passed", extra_artefacts=()):
    if entry["candidateKind"] == "mavi-baseline":
        artefacts, revision = [], commit("mavi-baseline")
    else:
        artefacts, revision = sorted(set(_pinned_files(entry["identity"])) | set(extra_artefacts)), None
    return {
        "candidateId": entry["candidateId"],
        "artefactSha256s": artefacts,
        "maviRevision": revision,
        "technicalGates": gates,
        "comparativeScore": score if gates == "passed" else None,
        "taskQualityScore": score if quality is None else quality,
        "measurementSha256": sha(f"measurement-{entry['candidateId']}"),
    }


def decision(document, *, scores=None, licence=None, state="QUALIFICATION_PENDING", implementation=("VC-EST",)):
    """A consistent decision summary over every shortlisted candidate of ``document``."""
    shortlisted = [e for e in document["candidates"] if e["disposition"]["status"] == "SHORTLISTED"]
    scores = scores or {"VC-B0": 0.2, "VC-EST": 0.7, "VC-EMG": 0.9, "VC-MTH": 0.5}
    extras = {"VC-MTH": [sha("mavi-head")]}
    rows = [evaluated_row(e, score=scores[e["candidateId"]], extra_artefacts=extras.get(e["candidateId"], ()))
            for e in shortlisted]
    licence = licence or {row["candidateId"]: {"dev-profile": "CLEARED"} for row in rows}
    technical = {r["candidateId"]: r["comparativeScore"] for r in rows if r["technicalGates"] == "passed"}
    quality = {r["candidateId"]: r["taskQualityScore"] for r in rows}
    cleared = {c: s for c, s in technical.items() if licence[c]["dev-profile"] == "CLEARED"}
    return {
        "schema": DECISION_SCHEMA,
        "eventId": document["eventId"],
        "eventState": state,
        "outcome": "SELECTED_FOR_PACKAGING" if state == "CLOSED" else None,
        "decidedOn": "2026-12-01",
        "ledgerSha256": document_sha256(document),
        "protocolSha256": sha("protocol"),
        "targetProfiles": ["dev-profile"],
        "evaluated": rows,
        "licence": licence,
        "strongestReported": {"candidateId": "VC-EMG", "claimId": "C1"},
        "highestTaskQualityEvaluated": max(quality, key=quality.get),
        "strongestEvaluatedTechnical": max(technical, key=technical.get) if technical else None,
        "strongestClearedPerProfile": {"dev-profile": max(cleared, key=cleared.get) if cleared else None},
        "implementation": None if implementation is None else {
            "components": list(implementation),
            "decidedBy": "synthetic-owner",
            "rationale": "strongest cleared established candidate",
        },
    }
