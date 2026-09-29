# External Evidence Ledger (template)

> Write the ledger as `<capabilityId>/<event-id>-evidence-ledger.json`. At `PROTOCOL_FROZEN`, copy it unchanged to `<event-id>-evidence-ledger-frozen.json` and record the copy's canonical SHA-256 in the protocol; afterwards the working ledger may only grow (`../candidate-credibility.md` §7). Follow `../candidate-credibility.md` (MSR method v1 revision M1). Check it with `python tools/qualification/model_selection_check.py ledger <path>`. The repository test suite validates every committed ledger. The ledger holds **external evidence only**: no MAVI measurement or MAVI-produced evidence (reserved `mavi` groups, repository or MAVI sources, MAVI datasets are refused), no licence field, no weights, imagery or credentials. `UNKNOWN` marks an unknown identity value; nothing is guessed. Unknown fields are refused.

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

For `person-attributes` the object class is `person` with sub-tasks `T-PC`, `T-PO`; for `vehicle-attributes` it is `vehicle` with `T-VC`. The validator refuses any other scope for those capabilities.

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
  "authors": {"names": ["…"], "groups": ["<author group>"], "affiliatedGroups": ["<affiliated group>"]},
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
                  "reason": "…", "revisitTrigger": "…", "decidedBy": "…",
                  "emergingShortlistBasis": "<only when an emerging candidate is SHORTLISTED>",
                  "reviewedBy": "<a second person; required with emergingShortlistBasis>"}
}
```

Field rules:
- `methodCode` is present only for `method` candidates. Their `identity` is the **backbone** checkpoint.
- A `mavi-baseline` identity is `{"repository": "MAVI", "revision": "<commit | UNKNOWN>"}` with no evidence and no claims.
- `derivation` is required when the publisher is `recognised-framework-maintainer`: `{"fromRepository", "fromRevision", "fromSha256", "conversionDocumentedBy": "<evidenceId>"}`.
- `integrityConflict` is null or `{"at": "YYYY-MM-DD", "reason": "…"}`, for example retrieved bytes that differ from the published hash. From its date the candidate is `excluded-discovery`.
- An `emerging` candidate is normally `REFERENCE_ONLY` with reason class `credibility`. Shortlisting it needs `emergingShortlistBasis` and a `reviewedBy` different from `decidedBy`.
- A checkpoint used for several sub-tasks is one entry. Method entries sharing a backbone repeat an identical `identity` block.
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
  "reproducedArtefact": {"sha256s": ["<every pinned weight hash>"]},
  "independenceBasis": "<why this producer is independent>",
  "subTask": "<independent-reproduction / -benchmark only>",
  "objectClass": "<independent-reproduction / -benchmark only>",
  "retracted": {"at": "YYYY-MM-DD", "reason": "…"}
}
```

Type rules:
- **repetition:** needs `repeats` and may not carry `scope`, `reproducedArtefact` or `independenceBasis`.
- **independent types** (`independent-reproduction`, `independent-benchmark`, `adoption`):
  - need `relation: independent`, a group outside `authors.groups`, `independenceBasis` and `scope`;
  - must be a distinct document: its normalised `source` and its `retrievedSha256` differ from every other item in the entry.
- **independent technical types** also carry `subTask` and `objectClass`, which must be the candidate's and the ledger's.
- **producers:** an `author` group is in `authors.groups`, an `author-affiliated` group in `authors.affiliatedGroups`; `independent` is in neither.
- **dates:** `retrievedOn` ≤ `recordedAt`; no future date.
- **independent-benchmark:** scope is `method`.
- **exact-checkpoint scope:** needs `reproducedArtefact`, as `{"sha256s": [...]}` equal to **all** pinned weight hashes, or as `{"repository", "revision"}` equal to the identity.
- **retracted items** stay in the ledger, with the date and reason.

## Claim

```json
{"claimId": "C1", "subTask": "T-PC", "objectClass": "person", "kind": "task-quality | runtime",
 "metric": "…", "value": "…", "dataset": "…", "split": "…",
 "originEvidenceId": "<a first-party claim or independent technical item>", "supportingEvidenceIds": ["…"]}
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
- No entry may claim more than the evidence active on its date supports. A `to: established` entry must be supported by the evidence it cites.
- Once `checkpointSha256s` is non-empty, it never changes. A different checkpoint is a new candidate entry.

## Decision summary (from S2c.4 on; not written in S2c.2a)

`<event-id>-decision.json`, schema `mavi-model-selection-decision-v1`:

```json
{"schema": "mavi-model-selection-decision-v1",
 "eventId": "…", "eventState": "TECHNICAL_DECISION_RECORDED | QUALIFICATION_PENDING | CLOSED",
 "outcome": "<MSR outcome when CLOSED | null>",
 "decidedOn": "YYYY-MM-DD",
 "ledgerSha256": "<canonical SHA-256 of the ledger>",
 "frozenLedgerSha256": "<canonical SHA-256 of the frozen ledger>",
 "protocolSha256": "<LF-normalised SHA-256 of <event-id>-protocol.md>",
 "targetProfiles": ["<profile-id>"],
 "evaluated": [{"candidateId": "…", "artefactSha256s": ["<ledger weight hashes + MAVI-trained hashes, sorted>"],
                "maviTrainedArtefacts": [{"sha256": "…", "trainingManifestSha256": "…"}],
                "maviRevision": "<baseline commit | null>",
                "technicalGates": "passed | failed", "comparativeScore": 0.0, "taskQualityScore": 0.0,
                "measurementSha256": "…"}],
 "licence": {"<candidateId>": {"<profile-id>": "NOT_ASSESSED | REVIEW_PENDING | CLEARED | CONSTRAINED | NOT_CLEARED"}},
 "strongestReported": {"candidateId": "…", "claimId": "…", "label": "reported, not reproduced by MAVI"},
 "highestTaskQualityEvaluated": "…", "strongestEvaluatedTechnical": "…",
 "strongestClearedPerProfile": {"<profile-id>": "<candidateId | null>"},
 "implementation": {"components": ["…"], "decidedBy": "…", "rationale": "…"}}
```

The validator checks `candidate-credibility.md` §8:
- the ledger and frozen-ledger hashes, and (repository check) the protocol hash;
- the evaluated set equals the frozen shortlist;
- the evaluated bytes equal the ledger identity plus declared MAVI-trained artefacts (a method needs at least one; a checkpoint none);
- the derived "strongest" outputs;
- implementation eligibility.
