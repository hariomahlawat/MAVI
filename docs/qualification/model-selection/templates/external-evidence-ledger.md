# External Evidence Ledger (template)

> Write the ledger as `<capabilityId>/<event-id>-evidence-ledger.json`, following `../candidate-credibility.md` (MSR method v1 revision M1). Check it with `python tools/qualification/model_selection_check.py ledger <path>`. The repository test suite validates every committed ledger. The ledger holds **external evidence only**: no MAVI measurement, no licence field, no weights, imagery or credentials. `UNKNOWN` marks an unknown identity value; nothing is guessed. Unknown fields are refused.

## Document

```json
{
  "schema": "mavi-external-evidence-ledger-v1",
  "eventId": "msr-<capabilityId>-<year>-<nn>",
  "capabilityId": "<capabilityId>",
  "objectClass": "person | vehicle | …",
  "subTasks": ["T-PC", "T-PO"],
  "methodRevision": "msr-v1-m1",
  "candidates": [ <entry>, … ]
}
```

## Candidate entry

```json
{
  "candidateId": "PC-1",
  "candidateName": "<family and variant as the source names it>",
  "candidateKind": "checkpoint | method | mavi-baseline",
  "subTasks": ["T-PC"],
  "methodCode": {"repository": "<url>", "revision": "<40/64-hex commit>"},
  "identity": {
    "repository": "<original source url | UNKNOWN>",
    "organisation": "<publishing organisation | UNKNOWN>",
    "revision": "<immutable 40/64-hex commit or hub revision | UNKNOWN>",
    "tag": "<release tag, informational | null>",
    "files": [{"path": "<file in the revision>", "sha256": "<hex | UNKNOWN>"}],
    "publisher": "original-author | original-organisation | recognised-framework-maintainer | third-party | unknown",
    "derivation": null,
    "integrityConflict": null
  },
  "authors": {"names": ["…"], "groups": ["<group-token>"]},
  "publication": {"status": "peer-reviewed | preprint-established-group | official-model-documentation | preprint | none",
                  "venue": "<venue, required for peer-reviewed>", "reference": "<citation or url>",
                  "basis": "<why the group is established; required for preprint-established-group>"},
  "architecture": {"description": "…", "documentedBy": "<evidenceId of a non-repetition item | null>"},
  "evidence": [ <evidence item>, … ],
  "claims": [ <claim>, … ],
  "popularitySignals": [{"signal": "github-stars | downloads | citations | other", "value": "…", "observedOn": "YYYY-MM-DD", "source": "…"}],
  "caveats": ["…"],
  "classification": {"class": "<computed>", "provenanceConfidence": "High | Medium | Low"},
  "classificationHistory": [ <history entry>, … ],
  "disposition": {"status": "DISCOVERED | SHORTLISTED | NOT_SHORTLISTED | REFERENCE_ONLY | DEFERRED",
                  "reasonClass": "technical | credibility | evaluation-permission | availability | resources | null",
                  "reason": "…", "revisitTrigger": "…", "decidedBy": "…"}
}
```

Field rules:
- `methodCode` is present only for `method` candidates. Their `identity` is the **backbone** checkpoint.
- A `mavi-baseline` identity is `{"repository": "MAVI", "revision": "<commit | UNKNOWN>"}` with no evidence and no claims.
- `derivation` is required when the publisher is `recognised-framework-maintainer`: `{"fromRepository", "fromRevision", "fromSha256", "conversionDocumentedBy": "<evidenceId>"}`.
- `integrityConflict` records, for example, retrieved bytes that differ from the published hash. Any value makes the candidate `excluded-discovery`.
- `classification` must equal what the validator computes (`candidate-credibility.md` §3). Run the checker and copy its output. Never assert the class.

## Evidence item

```json
{
  "evidenceId": "E1",
  "type": "first-party-claim | repetition | independent-reproduction | independent-benchmark | adoption | public-scrutiny",
  "producer": {"group": "<group-token>", "relation": "author | author-affiliated | independent"},
  "source": "<citation or url of this document>",
  "locator": "<table, section or page>",
  "retrievedOn": "YYYY-MM-DD",
  "retrievedSha256": "<hex of the retrieved document | UNKNOWN>",
  "recordedAt": "YYYY-MM-DD",
  "summary": "…",
  "repeats": "<evidenceId; repetition only>",
  "scope": "exact-checkpoint | method",
  "reproducedArtefact": {"sha256": "<weight hash>"},
  "independenceBasis": "<why this producer is independent>",
  "retracted": {"at": "YYYY-MM-DD", "reason": "…"}
}
```

Type rules:
- **repetition:** needs `repeats` and may not carry `scope`, `reproducedArtefact` or `independenceBasis`.
- **independent types** (`independent-reproduction`, `independent-benchmark`, `adoption`):
  - need `relation: independent`, a group outside `authors.groups`, `independenceBasis` and `scope`;
  - may not reuse a first-party item's `source`.
- **independent-benchmark:** scope is `method`.
- **exact-checkpoint scope:** needs `reproducedArtefact`, as a hash in `identity.files` or as `{"repository", "revision"}` equal to the identity.
- **retracted items** stay in the ledger, with the date and reason.

## Claim

```json
{"claimId": "C1", "subTask": "T-PC", "objectClass": "person", "kind": "task-quality | runtime",
 "metric": "…", "value": "…", "dataset": "…", "split": "…",
 "originEvidenceId": "<root, never a repetition>", "supportingEvidenceIds": ["…"]}
```

Every figure is class R (reported, not reproduced by MAVI). `runtime` claims are context only: the 500-camera assessment uses MAVI measurements (`candidate-credibility.md` §10).

## History entry

```json
{"at": "YYYY-MM-DD", "from": "<previous class | null>", "to": "<class>", "reason": "…",
 "evidenceIds": ["…"], "recordedBy": "…", "reviewedBy": "<a different person>",
 "identitySha256": "<canonical SHA-256 of the identity block>",
 "checkpointSha256s": ["<sorted weight hashes; [] until pinned>"]}
```

Rules:
- Append an entry whenever the computed class or the identity changes.
- A `to: established` entry must be supported by the evidence recorded on or before its date.
- Once `checkpointSha256s` is non-empty, it never changes. A different checkpoint is a new candidate entry.

## Decision summary (from S2c.4 on; not written in S2c.2a)

`<event-id>-decision.json`, schema `mavi-model-selection-decision-v1`:

```json
{"schema": "mavi-model-selection-decision-v1",
 "eventId": "…", "eventState": "TECHNICAL_DECISION_RECORDED | QUALIFICATION_PENDING | CLOSED",
 "outcome": "<MSR outcome when CLOSED | null>",
 "decidedOn": "YYYY-MM-DD",
 "ledgerSha256": "<canonical SHA-256 of the ledger>", "protocolSha256": "…",
 "targetProfiles": ["<profile-id>"],
 "evaluated": [{"candidateId": "…", "artefactSha256s": ["…"], "maviRevision": "<baseline commit | null>",
                "technicalGates": "passed | failed", "comparativeScore": 0.0, "taskQualityScore": 0.0,
                "measurementSha256": "…"}],
 "licence": {"<candidateId>": {"<profile-id>": "NOT_ASSESSED | REVIEW_PENDING | CLEARED | CONSTRAINED | NOT_CLEARED"}},
 "strongestReported": {"candidateId": "…", "claimId": "…"},
 "highestTaskQualityEvaluated": "…", "strongestEvaluatedTechnical": "…",
 "strongestClearedPerProfile": {"<profile-id>": "<candidateId | null>"},
 "implementation": {"components": ["…"], "decidedBy": "…", "rationale": "…"}}
```

The validator checks `candidate-credibility.md` §8:
- the evaluated set equals the shortlist;
- the evaluated bytes equal the ledger identity;
- the derived "strongest" outputs;
- implementation eligibility.
