# External Evidence Ledger (template)

> Write the ledger as `<capabilityId>/<event-id>-evidence-ledger.json`. At `PROTOCOL_FROZEN`, copy it to `<event-id>-evidence-ledger-frozen.json` with `"frozenOn": "YYYY-MM-DD"` added, record the copy's canonical SHA-256 and its `frozenOn` in the protocol, and record the protocol's LF-normalised SHA-256 in the event record. Afterwards the working ledger may only grow, and everything added is dated on or after `frozenOn` (`../candidate-credibility.md` §7). Follow `../candidate-credibility.md` (MSR method v1 revision M1). Check it with `python tools/qualification/model_selection_check.py ledger <path>`. The repository test suite validates every committed ledger. The ledger holds **external evidence only**: no MAVI measurement or MAVI-produced evidence (reserved `mavi` groups, repository or MAVI sources, MAVI datasets are refused), no licence field, no weights, imagery or credentials. `UNKNOWN` marks an unknown identity value; nothing is guessed. Unknown fields are refused.

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
  "disposition": {"status": "DISCOVERED | SHORTLISTED | NOT_SHORTLISTED | REFERENCE_ONLY | DEFERRED | BENCHMARK_BASELINE (M3)",
                  "reasonClass": "technical | credibility | evaluation-permission | availability | resources | null",
                  "reason": "…", "revisitTrigger": "…", "decidedBy": "…",
                  "emergingShortlistBasis": "<only when an emerging candidate is SHORTLISTED>",
                  "reviewedBy": "<a second person; required with emergingShortlistBasis>"}
}
```

Optional top-level `identifierExemptions` (`../candidate-credibility.md` §4.5): `[{"candidateId", "fieldKind":
"repository-url | source-url | artefact-filename | model-identifier", "value": "<exact raw value>", "reason": "…"}]`,
fixed at freeze.

Field rules:
- `methodCode` is present only for `method` candidates. Their `identity` is the **backbone** checkpoint.
- A `mavi-baseline` identity is `{"repository": "MAVI", "revision": "<commit | UNKNOWN>"}` with no evidence and no claims.
- **M3 only** (`methodRevision: msr-v1-m3`). Every M3 ledger is a composition-group member and carries the frozen
  block, identical in both group events (`../candidate-credibility.md` §4.4, README §14.3):
  `"compositionUniverse": {"componentEvents": [{"eventId": "msr-…", "subTask": "T-…", "rankingLayer": "A | B", "k": 3,
  "rankingGateIds": ["<sorted gate ids>"], "rankingRule": {"rule": "lexicographic-v1", "keys": [{"metric": "…",
  "direction": "max | min"}]}}, {…the other event…}], "compositionGateIds": ["baseline", "<sorted gate ids>"],
  "mpid": 0.02, "includePackageableBaselines": true}`. A revision of a STOPPED group adds
  `"supersedes": {"eventId": "<stopped event>", "frozenLedgerSha256": "…", "stoppedSealSha256s": ["…"]}`.
  A `BENCHMARK_BASELINE` entry (computed class `reference-only`, reason class `technical`; at most one per group) carries
  `"benchmarkBaseline": {"purpose": "…", "protocolSection": "…", "configurationSha256": "…", "adapterSha256": "…",
  "hostManifests": {"<target-profile-id>": [{"path": "…", "kind": "executable | runtime-library | data", "sha256": "…", "size": 1}]},
  "evaluationPermissions": [{"artefactKind": "executable | runtime-libraries | model-data", "sha256s": ["<sorted exact hashes>"],
  "decidedBy": "…", "decidedOn": "YYYY-MM-DD", "primarySourceSha256": "…"}],
  "compositions": [{"compositionId": "…", "partnerEventId": "<the other group event>",
  "eligiblePartners": [{"candidateId": "…", "identitySha256": "<canonical SHA-256 of the partner's identity block>"}],
  "excludedPartners": [{"candidateId": "…", "identitySha256": "…", "reason": "…"}],
  "derivationRule": "highest-ranked-partner-passing-every-layer-a-gate",
  "gateScope": "all-ordinary-compositions"}]}` (exactly one composition; `listed-compositions` is disabled).
  No other entry may carry it. `hostManifests` has one key per decision target profile; each profile lists at least one
  `executable`, every pinned identity file as `data`, and one kind per hash. One permission per artefact kind, covering
  exactly the manifest files of that kind (`model-data`: the pinned identity files plus every `data` file).
  `eligiblePartners` and `excludedPartners` together are exactly the partner event's shortlist. No shortlisted ordinary
  candidate of either group event may pin a benchmark-only executable, model, data or identity file.
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
- **licence:** no key or text anywhere mentions a licence, except the reason and revisit trigger of an `evaluation-permission` disposition, a field whose whole normalised value is exactly "license plate", "license plates", "licence plate" or "licence plates", and an exact identifier declared in `identifierExemptions` (below).
- **MAVI:** no reserved `mavi` group, MAVI path, MSR event file or `evidence-store:` source, and no item text naming MAVI.
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
 "inputsSha256": "<canonical SHA-256 of kind, subTasks, identity, authors, publication, architecture, claims>",
 "checkpointSha256s": ["<sorted weight hashes; [] until pinned>"]}
```

Rules:
- Append an entry whenever the computed class, the identity or any classification input changes.
- No entry may claim more than the evidence active on its date supports. A `to: established` entry must be supported by the evidence it cites.
- Once `checkpointSha256s` is non-empty, it never changes. A different checkpoint is a new candidate entry.

## Decision summary (from S2c.4 on; not written in S2c.2a)

`<event-id>-decision.json`, schema `mavi-model-selection-decision-v1`. It is written together with the decision snapshot `<event-id>-evidence-ledger-decided.json`, which is the ledger as it stood on `decidedOn`. `ledgerSha256` cites the snapshot, the event record carries the LF-normalised SHA-256 of both the decision and the snapshot, and afterwards the working ledger may only grow from the snapshot, with nothing dated before `decidedOn`:

```json
{"schema": "mavi-model-selection-decision-v1",
 "eventId": "…", "eventState": "TECHNICAL_DECISION_RECORDED | QUALIFICATION_PENDING | CLOSED",
 "outcome": "<MSR outcome when CLOSED | null>",
 "decidedOn": "YYYY-MM-DD",
 "ledgerSha256": "<canonical SHA-256 of the decision snapshot>",
 "frozenLedgerSha256": "<canonical SHA-256 of the frozen ledger>",
 "protocolSha256": "<LF-normalised SHA-256 of <event-id>-protocol.md>",
 "targetProfiles": ["<profile-id>"],
 "evaluated": [{"candidateId": "…", "artefactSha256s": ["<ledger weight hashes + MAVI-trained hashes, sorted>"],
                "maviTrainedArtefacts": [{"sha256": "…", "trainingManifestSha256": "…"}],
                "maviRevision": "<baseline commit | null>",
                "technicalGates": "passed | failed | n/a (M3 benchmark-only baseline)", "comparativeScore": 0.0, "taskQualityScore": 0.0,
                "measurementSha256": "…", "hostManifestSha256s": {"<profile-id>": "<M3 benchmark-only baseline rows only>"}}],
 "licence": {"<candidateId>": {"<profile-id>": "NOT_ASSESSED | REVIEW_PENDING | CLEARED | CONSTRAINED | NOT_CLEARED"}},
 "strongestReported": {"candidateId": "…", "claimId": "…", "label": "reported, not reproduced by MAVI"},
 "highestTaskQualityEvaluated": "…", "strongestEvaluatedTechnical": "…",
 "strongestClearedPerProfile": {"<profile-id>": "<candidateId | null>"},
 "implementation": {"components": ["…"], "decidedBy": "…", "rationale": "…"}}
```

The validator checks `candidate-credibility.md` §8:
- the ledger and frozen-ledger hashes, and (repository check) the protocol hash;
- the evaluated set equals the frozen shortlist (plus, under M3, the frozen benchmark-only baselines);
- the evaluated bytes equal the ledger identity plus declared MAVI-trained artefacts (a method needs at least one; a checkpoint none);
- the derived "strongest" outputs;
- implementation eligibility;
- under M3, the benchmark-only baseline rules and the mandatory block below (`../candidate-credibility.md` §8);
- the outcome, by the unchanged M1 rules over the composition-derived rows, with every benchmark-only entity removed.

**M3 only.** A benchmark-only row also carries `"baselineSealSha256s": {"<compositionId>": "<seal SHA-256>"}`; every
ordinary row's `technicalGates` and `comparativeScore` are the composition-derived values; and each group event's
decision carries the identical mandatory block (`../candidate-credibility.md` §8):

```json
"compositionAuthority": {
  "groupId": "<canonical SHA-256 of compositionUniverse>",
  "anchorCommit": "<the anchor recorded by open_protected_d and a committed D manifest>",
  "baselineSeals": [{"compositionId": "…", "sealSha256": "…", "status": "RESOLVED", "sealCommit": "<S0: first add of the seal>"}],
  "dExecutionStartedAt": "YYYY-MM-DDThh:mm:ssZ",
  "incumbent": "<compositionId of U> | null",
  "baseline": {"compositionId": "<gate-only compositionId>", "compositionSha256": "<from the seal>", "dScore": 0.0,
               "dResultSha256": "…"},
  "topK": {"<eventId>": ["<derived top-K, rank order>"]},
  "componentFinalists": {"<eventId>": ["<components of passing compositions, sorted>"]},
  "compositionCandidates": [{"compositionId": "C-<candidate>--<candidate>",
                             "components": [{"eventId": "msr-…", "candidateId": "…", "identitySha256": "…"}],
                             "gates": {"baseline": "passed | failed", "<other composition gate>": "passed | failed"},
                             "dScore": 0.0, "technicalGates": "passed | failed", "comparativeScore": 0.0,
                             "dResultSha256": "…", "baselineSealSha256s": {"<gate-only compositionId>": "<seal SHA-256>"}}],
  "rankedCompositions": ["<passing compositionId, non-increasing D-score>"],
  "frontier": ["<ranked compositionId>"],
  "strongestEvaluatedComposition": "<compositionId> | null",
  "implementationComposition": "<ranked compositionId> | null"}
```

`compositionCandidates` lists exactly the sealed set U, and every derived field is recomputed by the validator.

## Component rankings, baseline seal and D manifests (M3 only)

Committed canonical JSON beside the event's MSR files, each in its own commit in the order ranking ≺ seal ≺ D manifest,
never modified afterwards, and cited on exactly one record line (`Component ranking <event-id> SHA-256: <hash>`,
`Baseline seal <compositionId> SHA-256: <hash>`). Build and verify them with `m3_universe.component_ranking_document`,
`baseline_seal.derive_baseline_seal` and `m3_authority.open_protected_d` / `d_manifest_document` (README §14.3). Shape
contracts: `tools/qualification/model_selection/schemas/mavi-model-selection-component-ranking-v1.schema.json`,
`…-baseline-seal-v1.schema.json` and `…-d-manifest-v1.schema.json`.

```json
{"schema": "mavi-model-selection-component-ranking-v1", "eventId": "…", "frozenLedgerSha256": "…",
 "compositionUniverseSha256": "…", "rankingLayer": "A | B", "rankingGateIds": ["…"], "rankingRuleSha256": "…",
 "evidenceSha256": "<raw layer evidence>",
 "rows": [{"candidateId": "…", "identitySha256": "…", "gates": {"<gate id>": "passed | failed"},
           "metrics": {"<metric of the frozen rule>": 0.0}, "measurementSha256": "…"}]}
```

The rows are exactly the frozen shortlist; there is no rank key field, because the validator derives it.

```json
{"schema": "mavi-model-selection-baseline-seal-v1", "status": "RESOLVED",
 "eventId": "…", "capabilityId": "…", "compositionId": "…", "benchmarkBaselineId": "…",
 "benchmarkComponentIdentitySha256": "…", "protocolSha256": "…", "frozenLedgerSha256": "…", "stage1RuleSha256": "…",
 "eligibleUniverseSha256": "…", "layerAGatesSha256": "…", "partnerRankingRuleSha256": "…",
 "gateScope": "all-ordinary-compositions", "partnerEventId": "…", "partnerFrozenLedgerSha256": "…",
 "compositionUniverseSha256": "…", "componentRankingSha256s": {"<eventId>": "…", "<eventId>": "…"},
 "partnerCandidateId": "…", "partnerIdentitySha256": "…", "compositionSha256": "…", "ordinaryCompositionsSha256": "…",
 "protectedDState": "NOT_STARTED", "recordedAt": "YYYY-MM-DDThh:mm:ssZ", "recordedBy": "…"}
```

A protected-D manifest, committed on a commit descending from the anchor (`d_manifest_document`):

```json
{"schema": "mavi-model-selection-d-manifest-v1", "eventId": "<the benchmark-only baseline's event>",
 "manifestId": "RUN-1", "groupId": "…", "resultSha256": "…", "anchorCommit": "…", "ordinaryCompositionsSha256": "…",
 "baselineSeals": [{"compositionId": "…", "sealSha256": "…", "sealCommit": "<S0>"}]}
```

A STOPPED seal has the same common fields (`partnerFrozenLedgerSha256` and a `componentRankingSha256s` value may be
`null` when that input is absent), `"status": "STOPPED"`, `"protectedDAccessedAt"` (an instant for a
`protected-d-accessed` stop, else `null`), `"stopReason"` (one of `no-partner-passed-layer-a`, `partner-event-missing`,
`partner-event-inconsistent`, `partner-universe-inconsistent`, `identity-mismatch`, `resolution-ambiguous`,
`component-rank-ambiguous`, `component-ranking-inconsistent`, `protected-d-accessed`, `prerequisite-failed`),
`"stopDetail"` and `"stopEvidenceSha256s"`, and no partner, composition or U field. A STOPPED group is terminal
(README §14.3).
