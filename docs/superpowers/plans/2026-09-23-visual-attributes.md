# MAVI Stage 2 — Visual Attributes

**Status:** Architecture frozen and implementation-sequencing plan accepted. This documentation PR contains no Stage-2 feature implementation.  
**Date:** 2026-09-23  
**Baseline:** `main@ca23adf55b0b4a14faf58e12d048a3c90221557c` — Stage 1 closed; post-merge Quality Gate #1945 and Task 17 Acceptance Validation #1089 green.  
**Roadmap position:** Stage 2, immediately after Spatial & Temporal Track Analytics.  
**Related:** capability-roadmap.md; capability-implementation-roadmap.md; ADR-005; ADR-006; ADR-007; ADR-009; ADR-011; ADR-012; dependency-and-offline-packaging-policy.md.

## 1. Purpose

Stage 2 adds evidence-backed visual appearance attributes to MAVI while establishing the architectural pattern for future model-based post-Track intelligence.

The product goal is not merely to attach labels to Tracks. The Stage-2 architecture must make every analytical capability independently replaceable, versioned, evidence-linked, re-runnable, bounded, offline-capable and qualification-traceable.

MAVI owns the intelligence semantics. Models are replaceable engines.

A Stage-2 result must therefore answer all of the following:

- what attribute was observed;
- on which Track;
- from which accepted evidence observation/crop;
- with what confidence;
- under which attribute schema;
- by which model/model pack and model version;
- under which inference configuration;
- in which attribute-analysis run;
- when the analysis occurred;
- whether the Track was analysed, unavailable, failed or not yet analysed.

No attribute is an identity claim.

## 2. Product outcomes

Examples of operator queries:

- person + red upper clothing + backpack;
- person + dark lower clothing;
- vehicle + white colour.

A result opens directly into the supporting Track evidence and source video. The UI exposes confidence and provenance and distinguishes observed, unknown and unavailable states.

The first Stage-2 capability set is intentionally small. Candidate v1 attributes are:

### Person
- upper-clothing colour;
- lower-clothing colour;
- bag/backpack presence;
- headwear/helmet presence, only if qualification demonstrates sufficient reliability.

### Vehicle
- dominant vehicle colour.

Vehicle subclass is not a Stage-2 requirement. Stage 3 owns expanded operational object/vehicle classes. Stage 2 may retain a model output internally for evaluation, but it must not expose subclass operationally unless Stage-3 ownership is deliberately revised.

Explicit non-goals:
- age;
- gender;
- ethnicity;
- face attributes or face recognition;
- fine-grained garment taxonomy;
- brand recognition;
- vehicle make/model;
- identity inference;
- cross-camera association;
- automatic Entity creation;
- natural-language search.

## 3. Architectural quality standard

Stage 2 adopts these rules:

1. **Logical modules are independently replaceable.** Detector, tracker, evidence selector, attribute inferencer, plate/OCR inferencer, embedding inferencer and future analytical engines communicate through MAVI-owned contracts.
2. **Logical architecture is independent of deployment topology.** A capability's contracts do not depend on which process or host runs it. The Stage-2 default is a separate attributes process from the same Runtime Pack (ADR-013 §8); co-hosting in the detector process is not the default and requires a written isolation argument.
3. **Raw Track evidence and derived intelligence are different lifecycle classes.** Attribute-model failure must not invalidate an otherwise valid detection/tracking result.
4. **Historical analytical results are immutable.** Re-analysis creates a new analysis identity/version; it never silently rewrites the meaning of an old result.
5. **Every exposed analytical observation is evidence-linked.**
6. **Unknown is not false; unavailable is not unknown.**
7. **No model capability is exposed merely because a model can emit it.** Qualification determines the operational vocabulary.
8. **Offline and qualification disciplines are part of the feature, not release cleanup.**

## 4. Repository reality at Stage-2 entry

Stage 2 is constrained by the implementation already merged at Stage-1 closure:

- VisionJob performs a single decode pass. Per-frame images and boxes are not retained after processing; trajectory v1 cannot reconstruct bounding boxes.
- VisionJob completion currently has detector-era bounded-result rules and one Representative thumbnail/trajectory shape.
- accepted evidence is .NET/platform owned; Python workers do not have a supported direct read path into the accepted-evidence root.
- SceneAnalytics is an in-process .NET lifecycle; VisionJob is a Python-facing HTTP lease/heartbeat/complete plane. Their fencing implementations are similar but not identical.
- component/runtime selection, model manifests and qualification are presently detector-centric and assume one model/checkpoint identity.
- VisualAttribute exists as groundwork but its current free-form/per-row model shape is not sufficient for immutable analysis identity, explicit Unknown semantics or evidence-preserving supersession.
- Track-search cursor v3 is camera-bound because of Scene Analytics semantics; Stage-2 attribute search is not inherently single-camera.
- UI specification currently protects row density and one-status-badge semantics and therefore must be amended rather than bypassed.

These are architecture inputs, not implementation inconveniences to work around.

## 5. Governing architecture decisions

Stage 2 is governed by:

1. **ADR-013** — raw Track Evidence Set, derived-attribute lifecycle, process/failure isolation, evidence-read boundary, persistence semantics, search identity, qualification-as-architecture.
2. **ADR-014** — capability binding v2, capability-neutral Model Packs, Runtime Pack/model separation, capability-scoped qualification and pack provenance.
3. **ADR-006** — accepted-evidence ownership/integrity boundary.
4. **ADR-009** — Development and Production qualification separation.
5. **ADR-012 + UI specification** — operator-interface architecture and amendment discipline.

If this plan conflicts with an Accepted governing ADR, the ADR governs and this plan must be reconciled.

## 6. Target logical architecture

```text
Source video
   │
   ▼
Vision worker: decode → detector → tracker
   │
   ├─ deterministic in-loop candidate selection
   │      Representative / NearView / EarlyDiverse / LateDiverse
   │      JPEG encode on selection/replacement; no K raw RGB arrays
   │
   ▼
VisionJob completion v3 / digest v3
   │
   ▼
.NET validates + seals EvidenceCrop artefacts
   │
   ├─ Tracks / trajectory / Observations
   └─ bounded Track Evidence Set
   │
   ▼
ProcessingRun visible
   │
   ▼
Reconciler queues VisualAttributeAnalysis(run × immutable identity)
   │
   ▼
Attribute worker process (same qualified Runtime Pack initially; role=attributes)
   │
   ├─ leases analysis
   ├─ fetches only lease-authorised accepted evidence through API
   ├─ verifies size + SHA before decode
   ├─ executes capability-bound person/vehicle model packs
   ├─ deterministic Track aggregation
   └─ returns final Track outcomes + sealed prediction artefact descriptor
   │
   ▼
.NET fenced completion
   │
   ├─ VisualAttributeAnalysis
   ├─ VisualAttributeTrackOutcome
   ├─ VisualAttribute final rows
   └─ AttributePredictions sealed artefact
   │
   ▼
Search v4 / Investigation / Review
```

Detector/tracker validity does not depend on the attribute plane.

## 7. Capability Replacement Boundary

MAVI domain semantics remain stable while inference engines remain replaceable.

For a model replacement conforming to the same qualified capability contract, Stage 2 must require changes only to the relevant:
- Model Pack;
- capability binding;
- qualification/provenance identity;
- optional versioned schema/policy when semantics actually change.

It must not require redesign of Track, Observation, Search, Investigation, Review or evidence integrity.

This principle is deliberately future-facing for OCR, ANPR, embeddings and specialist classifiers.

## 8. Track Evidence Set

### 8.1 Ownership and lifecycle

Evidence selection is a **VisionJob raw-processing output**, not a later post-Track stage.

It is versioned in the processing pipeline profile. A selector/bounds change therefore creates a new ProcessingRun and new Track identities under trajectory v1.

Stage 2 does not promise “re-run evidence selection only.”

### 8.2 Roles

Maximum candidate roles per Track:

| Rank/role | Purpose |
|---|---|
| 0 Representative | primary display/overall-quality evidence; mandatory |
| NearView | largest qualified box / strongest useful pixel support |
| EarlyDiverse | earlier temporally separated qualified view |
| LateDiverse | later temporally separated qualified view |

Selection is deterministic and model-neutral.

Quality terms may include area, sharpness, detector confidence, clipping penalty, temporal separation and concurrent-box overlap as an occlusion proxy.

No face/plate/demographic/downstream-model-specific scoring is allowed.

Selection method (frozen in ADR-013 §4; numeric floors set in S1 and recorded in the pipeline profile): a *qualified candidate* meets confidence, sharpness, edge-margin and occlusion-proxy floors; Representative is the best-scoring qualified candidate overall; NearView the largest-area qualified non-duplicate; EarlyDiverse/LateDiverse the best-scoring qualified candidates in the first/last temporal third that are at least the minimum separation from every selected frame. A role with no qualified candidate is omitted, never filled with an unqualified frame.

Tie rule within a role: selector score descending → source-frame number ascending. Roles are evaluated in fixed order.

### 8.3 Encoding and bounds

Initial v1 Evidence Set contract:

- maximum roles per Track: 4;
- maximum long edge: 1024 px;
- JPEG quality target: 85;
- Representative encoded cap: 64 KiB;
- supplemental encoded cap: 160 KiB each;
- deterministic quality/downscale reduction is allowed only to meet a declared cap;
- total sealed `EvidenceCrop` bytes per ProcessingRun: 1 GiB.

At 10,000 Tracks the mandatory Representative worst case is 625 MiB, leaving 399 MiB for supplemental crops — at most ≈2,550 of a possible 30,000, i.e. roughly 8.5 % of Tracks receive any supplemental evidence in that worst case. The quota is a degradation bound; a typical run of hundreds of Tracks receives every qualified role.

Supplemental evidence is admitted in deterministic rounds by role (NearView, EarlyDiverse, LateDiverse); within a round Tracks are ordered by candidate selector score descending, then LocalTrackNumber, until the 1 GiB run budget is exhausted. The mandatory Representative is never displaced by supplemental evidence.

The 64 KiB Representative cap implies an effective Representative ceiling of roughly 600–700 px long edge for large subjects; Representative is the display/summary crop and NearView is the analytic-resolution carrier. Deterministic reduction never goes below 128 px long edge or quality 50.

While a Track is live its current best candidate per role is held encoded (≤544 KiB per live Track); when the tracker ends the Track its candidates are written once to attempt-scoped staging and only descriptors are retained. Worker memory is bounded by live Tracks; transient staging before admission is bounded by 10,000 × 544 KiB ≈ 5.2 GiB and is cleaned with the attempt.

Completion reports candidate/admitted/omitted counts and bytes by role. The v2 512 MiB aggregate bound becomes the trajectory/other-artefact quota; EvidenceCrop bytes count against the separate 1 GiB quota.

The HTTP completion body carries metadata/descriptors, not image bytes; `MaximumCompletionRequestBodyBytes` is re-derived for v3 and contract-tested at the 10,000-Track, four-role bound.

### 8.4 Observation evolution

Observation gains:
- EvidenceRank;
- EvidenceRole;
- SelectionScore;
- EvidenceCrop artifact linkage.

Representative remains directly addressable for existing UI/search convenience.

Legacy observation enum values that are not backed by real semantics must be deliberately mapped or retired.

## 9. Component Binding v2

Before any real attribute model can ship, Stage 2 must remove the current single-model assumption.

The component-selection contract becomes:
- one Runtime Pack identity;
- a list of Runtime Pack families, each keyed by platform variant (the dimension the current component manifest already has);
- declared roles (`vision`, `attributes`, …), each naming the family it runs from and the capability ids it serves;
- ordered `capabilityBindings[]`, each identifying a stable capability id + Model Pack + role + qualification record.

A future capability that needs a different dependency graph (the Stage-4 OCR engine) binds a different family through its own role; no v3 of the binding schema is required for it.

Capability ids describe semantic function, not model brand/framework.

Initial Stage-2 ids:
- `detector`;
- `person-attributes`;
- `vehicle-attributes`.

The schema must also naturally support later:
- `plate-detector`;
- `ocr`;
- `embedding`.

Model-manifest v2 has a capability-neutral common schema. Detector/MMDetection resolved config becomes capability-specific optional metadata rather than a mandatory field for all models.

Runtime-profile v2 describes executable/dependency capability and startable roles; it no longer treats one detector checkpoint as the Runtime Pack identity.

This is a deliberate identity migration. Any affected existing RTMDet qualification hashes/records are re-derived/reconciled in the same implementation slice.

## 10. Attribute worker topology and control plane

### 10.1 Default topology

The attribute executor is a **separate process/failure domain** from detector/tracker, initially supplied by the same qualified Runtime Pack.

It has:
- independent READY state;
- independent device policy, set per role in the deployment profile — on the 4 GiB Development GPU the attributes role may run on CPU while the detector holds CUDA; silent fallback remains prohibited (ADR-008);
- independent lease/heartbeat, with VisionJob-style expiry semantics (an expired lease or mismatched attempt refuses completion, failure and evidence reads);
- independent provenance;
- independent crash/OOM containment.

A future separate executable or GPU node must fit the same contract. The role has no filesystem dependency on the platform host: evidence is read and the prediction artefact is uploaded through lease-scoped API endpoints (§11).

### 10.2 Lifecycle aggregate

Use capability-specific `VisualAttributeAnalysis`, not a generic IntelligenceJob database aggregate.

Unit: `(ProcessingRun, immutable analysis identity)`.

Lifecycle:
- Queued;
- Running;
- Completed;
- Failed;
- Superseded.

Fields include attempt/fencing state, lease expiry, heartbeat, completion digest, visibility sequence, provenance and output counts.

Supersession occurs only after successful completion. A binding change does not re-analyse history automatically: earlier units read as Stale and remain readable; re-analysis is an explicit bounded request per run or camera/time window, as for scene analytics. One unit covers one ProcessingRun and fails as a whole if it exceeds its configured maximum duration.

### 10.3 Shared primitives

Before adding the third asynchronous plane, extract shared infrastructure only where semantics truly match:
- lease capability/token handling;
- canonical SHA representation;
- SKIP LOCKED claim helper/pattern;
- idempotent completion digest validation.

Do not force VisionJob, SceneAnalysis and VisualAttributeAnalysis into one generic domain table.

The reusable completion envelope is generic; payloads are typed per capability.

## 11. Accepted-evidence read contract

Python never mounts/browses the accepted-evidence root.

The attribute lease carries permitted Observation artefact descriptors including expected size/SHA.

The worker fetches bytes through a lease-scoped platform API, verifies size/SHA before decoding, then runs inference.

Any mismatch/inaccessible evidence produces a Track-level `Unavailable` outcome with reason.

The read endpoint is lease-bound (capability in a header, never in the URL), authorises only Observations of the leased unit's ProcessingRun while the unit is Running with a matching attempt and unexpired lease, streams at most the recorded `SizeBytes`, offers no listing, and logs every read.

The `AttributePredictions` artefact travels the same way in reverse: a lease-scoped, size-capped upload endpoint receives the bytes, verifies declared size/SHA while streaming, stages under an attempt-scoped key and seals under ADR-006 at completion. The attribute worker writes to no platform filesystem, not even worker staging.

This boundary is mandatory because it preserves both forensic ownership and future remote-GPU topology.

## 12. Analysis identity and provenance

VisualAttributeAnalysis identity is exactly:
- ProcessingRunId;
- attribute schema version/SHA;
- attribute pipeline version;
- aggregation policy version/SHA;
- ordered capability/Model Pack identities;
- parameters SHA.

Runtime Pack identity/variant, actual device and platform build/commit are provenance on the header and enter the digest, but are not identity (ADR-013 §11): a variant or build change must not manufacture a superseding analysis. Binding one model pack on more than one runtime variant requires qualified variant equivalence.

Persist provenance including:
- capabilityId;
- modelPackId;
- model/checkpoint/config hashes as applicable;
- runtimePackId;
- runtime profile/manifest hash;
- actual device;
- schema/pipeline/aggregation versions;
- build/commit.

Identity/provenance fields participate in the completion digest.

## 13. Attribute schema and outcome semantics

Candidate operational v1 attributes remain deliberately narrow:

**Person**
- upper-clothing colour;
- lower-clothing colour;
- bag/backpack presence;
- headwear/helmet presence only if qualification passes.

**Vehicle**
- dominant vehicle colour.

Vehicle subclass remains Stage 3 unless roadmap ownership is deliberately changed.

No demographic/biometric/face attributes are introduced.

For every applicable `(Track, attribute type)` in a completed analysis exactly one final row exists:

- `Observed` → qualified value present; SupportingObservation required;
- `Unknown` → null value; analysis attempted but no qualified value.

Track-level `Unavailable` is represented separately with reason. Run-level readiness distinguishes `NotConfigured` (no enabled attribute binding in the release) from `NotApplicable` (bound, but no applicable Track in the run).

Confidence on an Observed row is the aggregation policy's score for the asserted value; one value per Track per attribute, with two-tone cases expressed only through a qualified schema value such as `multicolour`.

`Absent` is a schema value only for an attribute whose qualification explicitly supports reliable negative semantics.

Missing row is not Unknown.

## 14. Evidence-level predictions and aggregation

Evidence-level model outputs are preserved for forensic replay without exploding relational row count.

Each completed analysis seals one bounded, versioned, self-describing `AttributePredictions` artefact (≤ the existing 64 MiB per-artefact cap; encoding chosen in S2b from dependencies already on the qualified graph) containing:
- observation-level raw outputs/scores;
- aggregation inputs;
- aggregation result;
- internally retained non-exposed outputs where policy permits;
- schema/version identity.

Relational `VisualAttribute` rows store final Track semantics only.

Aggregation is deterministic, versioned and qualification-relevant.

Every Observed value references supporting Observation evidence.

## 15. Persistence target

Conceptual entities:

### VisualAttributeAnalysis
Immutable identity + lifecycle/fencing + provenance + PredictionArtifactId + coverage/counts + visibility/supersession state.

### VisualAttributeTrackOutcome
`(AnalysisId, TrackId) → Analysed | Unavailable(reason)`.

### VisualAttribute
- AnalysisId FK Restrict;
- TrackId;
- schema-coded AttributeType;
- Outcome Observed|Unknown;
- nullable schema-coded Value;
- nullable confidence;
- SupportingObservationId required for Observed, FK Restrict;
- unique `(AnalysisId, TrackId, AttributeType)`.

Model name/version is not duplicated as row authority; the analysis header owns producer identity.

Initial measured-search index candidate:
`(attribute_type, value, analysis_id, track_id)`.

## 16. Search contract

Stage 2 extends structured Track search with explicit attribute predicates.

Requirements:
- strict whitelist and schema validation;
- canonical repeated-predicate ordering in URL, fingerprint and cache key;
- multi-attribute AND semantics;
- explicit Unknown/Unavailable coverage behaviour;
- no implicit negative from missing analysis;
- snapshot-stable pagination.

Attribute search introduces **cursor v4**.

v4 pins:
- Track-search snapshot identity/keyset position;
- the resolved attribute capability identity **fingerprint** (SHA-256 of the canonical schema/pipeline/aggregation/model-pack/parameters tuple — the analysis identity without the run); the full tuple is returned in the first page's coverage block, and per-run analyses are resolved on continuation by that fingerprint;
- relevant attribute coverage state/counts.

Attribute-only search may span cameras.

When Scene Analytics predicates are combined with attributes:
- Scene Analytics single-camera requirement still applies;
- both analytics identity and attribute identity are pinned.

Cursor is HMAC-signed; encoded length is re-derived and contract-tested.

## 17. Operator experience

The adopted UI specification governs.

Stage-2 amendments now require:
- explicit non-colour-only Unknown state;
- bounded Evidence Set viewer in Investigation/Review;
- `TrackDetail.observations[]` while retaining direct Representative access;
- attribute filtering through the established filter rail/chip grammar;
- inspector key/value presentation;
- provenance/coverage presentation;
- no arbitrary badge swarm on result rows.

Result rows remain compact. Evidence and explanation live in inspectors/review surfaces.

## 18. Qualification architecture

The qualification plan is predeclared and is part of Stage-2 architecture.

It requires:
- annotation guide;
- double-labelled subset + inter-annotator agreement/adjudication;
- train/tune-validation/frozen-test separation;
- predeclared minimum support per value;
- held-camera/unseen-camera generalisation;
- crop vs Representative vs aggregated Track metrics;
- abstention/Unknown metrics;
- non-subject/error crop tests;
- retrieval precision-at-N/coverage;
- licence gate;
- CPU/CUDA Development evidence where applicable;
- offline execution;
- version-skew/failure isolation;
- explicit requalification triggers.

Final numeric operational gates and support thresholds are frozen using validation/tuning evidence before the frozen test set is scored.

## 19. Performance/resource boundaries

Stage 2 measures and gates:
- evidence bytes/run and omission rates by role;
- worker READY/model-load time;
- CPU/GPU RAM/VRAM;
- crop and Track inference p50/p95;
- sustained backlog drain;
- lease heartbeat margin;
- DB query plan/query count/p50/p95;
- v4 cursor size;
- end-to-end Search → Investigation → Review latency.

No hidden unbounded list, artifact payload or evidence fetch is permitted.

## 20. Failure, re-analysis and retention

Failure rules:
- attribute failure never invalidates completed raw processing;
- startup model-unavailable does not consume analysis attempts;
- stale lease completions are rejected;
- failed replacement analysis does not supersede prior completed analysis;
- hash mismatch becomes Unavailable, never pass-through;
- re-analysis with a new immutable identity is supported when required evidence exists.

Evidence-policy changes under trajectory v1 require new video ProcessingRuns/new Tracks.

Superseded analyses and orphaned supplemental crops remain under current evidence retention until a dedicated policy exists. A dedicated retention policy must be completed before Production Stage-2 release or when operational storage threshold triggers it, whichever occurs first.

## 21. Security and privacy

- accepted evidence remains platform-owned;
- attribute workers get lease-scoped read only;
- no direct Python evidence-root access;
- evidence hashes are verified before inference;
- native-resolution person crops are treated as evidence, not convenience thumbnails;
- access follows existing Track/evidence authorization;
- no face-oriented selection criterion is allowed;
- no demographic/biometric capability is introduced;
- all model/runtime/offline bytes are integrity-verified and licence-reviewed.

## 22. Architecture-first implementation slices

S0 architecture closure is complete. Feature coding remains a separate follow-on activity and begins only through the defined implementation slices.

| Slice | Scope | Exit gate |
|---|---|---|
| **S0 Architecture freeze** | ADR-013/014, Evidence Set arithmetic/roles, evidence-read contract, cursor v4, UI amendments, qualification protocol, acceptance register and roadmaps reconciled | Acceptance A1–A12 PASS; no P1/P2 cold-review finding |
| **S1 Track Evidence Set** | in-loop selector/encoding with staged-on-selection candidates, completion schema v3 + digest v3 (re-derived body bound), validator/store/sealing, Observation evolution, observations[] and evidence viewer; Task-10/E2E rebinding | Acceptance B1–B6 PASS |
| **S2a Component binding v2** | capabilityBindings[], manifest v2, runtime profile v2, qualification record shape, pack provenance, verifier/offline/CI migration, detector qualification reconciliation | Acceptance C1–C7 PASS |
| **S2b Attribute lifecycle with fixture inferencer** | shared fencing primitives, VisualAttributeAnalysis, Python HTTP plane, lease-scoped evidence read and prediction upload, sealed prediction artefact, independent attributes process; remove the unused `EmbeddingExtractor` protocol or explicitly retain/document it as Stage-5-only groundwork rather than reusing it as a generic inferencer abstraction | Acceptance D1–D8 PASS using deterministic fixture; no real model |
| **S2c Real Model Packs** | person/vehicle packs, Development model execution, provenance and labelled-corpus engineering evaluation | model packs install/run truthfully as Development/unverified until gates pass |
| **S3 Persistence + search** | final outcome rows, supersession, v4 cursor, canonical predicates, measured PostgreSQL plans | Acceptance E1–E8 PASS |
| **S4 Operator UI** | filters, Unknown/Unavailable/coverage/provenance, evidence workflow, spec-conformant visual QA | applicable G1/G2 PASS |
| **S5 Hardening / qualification / acceptance** | freeze thresholds, frozen-test evaluation, CPU/CUDA Development evidence, offline, resilience, scale, docs | all remaining F/G requirements PASS |

No slice may claim later qualification early.

## 23. Stage-2 exit gate

The **only authoritative Stage-2 acceptance list** is:

`docs/reviews/2026-09-23-visual-attributes-acceptance.md`

This parent plan intentionally does not duplicate its numbering.

Stage 2 is complete only when every applicable acceptance-register requirement is PASS on retained evidence and post-merge verification is green.

## 24. Decisions deliberately deferred after architecture freeze

The following are legitimate later implementation/qualification choices and do not block S0 once their decision method is fixed:
- exact third-party person/vehicle model checkpoint;
- final operational vocabulary values that depend on corpus labelability;
- numeric exposure thresholds and minimum-support counts, which must be frozen from validation/tuning evidence before frozen-test evaluation;
- whether later OCR/embedding roles remain in the same Runtime Pack or move to separate packs/executables;
- long-term purge/retention durations, subject to the mandatory Production/threshold trigger in ADR-013.

The following are **not deferred**:
- capability binding architecture;
- evidence ownership/generation boundary;
- worker process isolation;
- evidence-read security topology;
- immutable analysis/supersession semantics;
- Unknown/Unavailable semantics;
- search identity/pagination semantics;
- qualification methodology.
