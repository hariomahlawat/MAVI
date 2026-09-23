# ADR-013: Modular Post-Track Intelligence and Evidence Architecture

**Status:** Accepted — Stage-2 architecture freeze  
**Date:** 2026-09-23  
**Supersedes:** any Stage-2 planning text that treats attribute inference as part of VisionJob completion or treats Representative as the only analytical image evidence

## Context

MAVI Stage 1 established the durable recorded-video intelligence boundary: detector/tracker execution produces platform-owned ProcessingRuns, Tracks, Observations, sealed evidence artefacts and trajectories; deterministic scene analytics then runs as a separately versioned derived-analysis lifecycle.

Stage 2 introduces learned appearance intelligence. The product requirement is not merely to append labels. MAVI must remain upgradeable for years: detector, attribute, OCR, ANPR, embedding and later specialist models must be replaceable without redesigning Track, Observation, Search, Investigation or Review semantics.

Repository review also establishes three constraints that the Stage-2 architecture must acknowledge explicitly:

1. decoded frames and per-frame boxes are available only while VisionJob is processing the source video;
2. accepted evidence is owned by the .NET platform boundary and is not directly readable by a Python executor;
3. the current runtime/model-pack and qualification shape is detector-centric and must evolve before multiple model capabilities can be shipped honestly.

## Decision

### 1. Stable domain semantics; replaceable inference capabilities

MAVI owns durable intelligence semantics. Models are replaceable engines.

A replacement model that conforms to the same qualified capability contract must not require redesign of:
- Track or Observation identity;
- accepted-evidence integrity;
- Search/Investigation/Review contracts;
- historical analysis meaning;
- operator-facing attribute semantics.

A model replacement changes its pack/binding/qualification/provenance identity and, where necessary, the versioned capability schema. It does not silently rewrite historical intelligence.

This is the **Capability Replacement Boundary**.

### 2. Raw Track evidence and derived intelligence have different lifecycles

Detection/tracking produces raw Track evidence.

Visual Attributes, OCR, embeddings and future learned capabilities produce derived intelligence from accepted evidence.

Derived-capability failure never invalidates an already valid completed ProcessingRun.

### 3. The Track Evidence Set is produced inside VisionJob

Evidence selection is not a post-Track background stage. It is part of raw video processing because decoded frames, bounding boxes and concurrent-track context exist only in the VisionJob decode/tracking loop.

VisionJob therefore produces, for every accepted Track:
- the Track and trajectory;
- one mandatory Representative evidence crop;
- zero or more bounded supplemental evidence crops selected from deterministic roles.

The Stage-2 VisionJob contract is versioned to **completion schema v3 / digest v3**. The evidence-selection policy id/version is part of the pipeline profile and processing provenance.

Changing the evidence-selection policy requires a new ProcessingRun and therefore new Track identities. Stage 2 does not claim that evidence can be regenerated independently from existing trajectory v1.

### 4. Evidence selection is deterministic, role-based and model-neutral

The maximum candidate set is four roles:

1. **Representative** — primary display/overall-quality crop; rank 0 and mandatory.
2. **NearView** — largest qualified box / highest useful pixel support.
3. **EarlyDiverse** — an earlier well-separated qualified view.
4. **LateDiverse** — a later well-separated qualified view.

Selection uses only model-neutral Track/frame information available during raw processing: object area, sharpness, detector confidence, frame-edge clipping, temporal separation and an occlusion proxy derived from overlap with concurrent boxes. No face-oriented, plate-oriented, demographic or downstream-model-specific selector is allowed.

Near-duplicate candidates are removed deterministically. Tie-breaking is stable and documented: score descending, then source-frame number ascending, then role priority.

Representative remains the primary display summary. Supplemental roles exist to improve later analytical coverage, not to redefine the Track.

### 5. Evidence crops are encoded in-loop and staged, not retained as RGB arrays

Candidate crops are JPEG-encoded when selected/replaced in the processing loop and staged as bounded artefacts. The worker must not retain K raw RGB arrays per live Track.

Initial Stage-2 evidence encoding contract:
- maximum candidate roles per Track: **4**;
- maximum long edge: **1024 px**;
- initial JPEG quality target: **85**;
- mandatory Representative encoded size cap: **64 KiB**;
- supplemental crop encoded size cap: **160 KiB each**;
- crop dimensions and encoding quality may be reduced deterministically to satisfy the byte cap; the source-frame/bounding-box linkage remains authoritative.

These are product bounds, not quality claims. Qualification determines whether the resulting evidence remains sufficient for an exposed capability.

### 6. Evidence storage is bounded at both Track and ProcessingRun level

Contract v3 separates evidence-crop quota from other analytical artefact quotas.

For one ProcessingRun:
- mandatory Representative evidence is admitted first;
- total sealed EvidenceCrop bytes are capped at **1 GiB**;
- supplemental roles are admitted in deterministic rounds (NearView for eligible Tracks, then EarlyDiverse, then LateDiverse), with Tracks ordered by LocalTrackNumber within a round;
- once the run-level evidence budget is exhausted, remaining supplemental candidates are omitted; Representative is never omitted for an accepted Track;
- completion metadata records candidate/admitted/omitted counts and bytes by role.

At the existing maximum of 10,000 Tracks, the 64 KiB Representative cap yields a worst-case mandatory crop budget of 625 MiB, leaving bounded headroom for supplemental evidence inside the 1 GiB evidence quota.

The completion HTTP body carries descriptors, never crop bytes. Sealed artefact validation remains hash/size checked.

Any change to these constants is a pipeline-profile change and triggers the requalification rules defined by ADR-009 and the Stage-2 qualification plan.

### 7. Observation/evidence semantics are explicit

Observation evolves to represent the accepted Track Evidence Set:
- `EvidenceRank`: nullable integer; rank 0 is Representative;
- `EvidenceRole`: Representative | NearView | EarlyDiverse | LateDiverse;
- `SelectionScore`: deterministic selector score;
- source frame number, video offset and bounding box remain authoritative linkage;
- crop artefact type is `EvidenceCrop`.

Unused legacy observation-type promises must either be mapped deliberately to these roles or retired; Stage 2 must not leave dead enum values that imply unsupported behaviour.

### 8. Attribute execution is a separate process and failure domain

Default Stage-2 deployment is a **second process from the qualified Runtime Pack**, initially expressed as a role such as `--role attributes`.

It has:
- independent READY/health state;
- independent lease lifecycle;
- independent device policy;
- independent provenance;
- independent failure domain.

A classifier OOM/crash must not kill or invalidate a detector/tracker VisionJob.

The architectural contract does not require the same executable forever. A future `mavi_attributes` or remote GPU worker may replace the initial process without changing platform semantics.

### 9. Attribute analysis is capability-specific; the transport envelope is reusable

Stage 2 introduces `VisualAttributeAnalysis`, not a generic IntelligenceJob aggregate.

The analysis unit is one `(ProcessingRun, analysis identity)`. It has its own status, attempts, lease, heartbeat, completion digest, provenance and visibility sequence.

Python-facing HTTP endpoints provide lease / heartbeat / complete / fail semantics.

Before adding this third asynchronous control plane, shared primitives are extracted where semantics genuinely match:
- lease capability/token handling;
- canonical SHA-256 representation;
- `FOR UPDATE SKIP LOCKED` claim helper/pattern;
- idempotent completion-digest verification.

The reusable transport envelope is:

`schemaVersion, jobId, workerId, leaseToken, attemptCount, provenance, payload`.

Capability payloads remain typed and capability-specific.

If the required model/capability is unavailable at worker startup, units remain Queued and attempts are not consumed.

### 10. Accepted evidence is served by the platform; Python never mounts the evidence root

The accepted-evidence root remains .NET-owned.

An attribute lease payload identifies each required Observation and expected artefact SHA-256/size. The executor obtains bytes only through a **platform-served, lease-scoped evidence-read endpoint** in the same API trust family as its job lease.

The executor:
1. presents the active lease capability;
2. requests the permitted Observation artefact;
3. verifies received size and SHA-256 before decode/inference;
4. fails that Track as `Unavailable` on mismatch or inaccessible evidence.

Direct filesystem access from the attribute worker to the accepted-evidence root is prohibited.

This boundary is topology-independent and therefore supports later separate GPU nodes without changing semantics.

### 11. Analysis identity is immutable and qualification-relevant

A VisualAttributeAnalysis identity includes at minimum:
- ProcessingRunId;
- attribute schema version/SHA;
- attribute pipeline version;
- aggregation-policy version/SHA;
- ordered capability/model-pack identities;
- parameters SHA-256;
- runtime-pack identity/variant;
- platform build/commit identity.

A materially different identity creates a new immutable analysis. A completed newer analysis may supersede the previous default. Historical analyses remain readable.

Supersession occurs only on successful completion.

### 12. Explicit readiness and outcome semantics

Run-level readiness:
- NotApplicable;
- Pending;
- Ready;
- Failed;
- Stale.

Track-level analysis outcome:
- Analysed;
- Unavailable, with reason.

For every applicable `(Track, attribute type)` in a completed analysis, exactly one final attribute row exists with:
- `Outcome = Observed`, non-null qualified value, supporting Observation required; or
- `Outcome = Unknown`, null value.

Missing row is not Unknown. It means the attribute was not part of that completed applicable analysis.

`Absent` is a qualified schema value only where the attribute schema explicitly defines reliable negative semantics.

Unknown, Unavailable, Pending, Failed and Absent must remain distinguishable in API, search and UI.

### 13. Raw crop predictions are sealed artefacts; relational rows hold final semantics

The executor may make multiple evidence-level predictions per Track and attribute. Those raw outputs are not expanded into large relational prediction tables.

Each completed analysis seals one bounded `AttributePredictions` artefact containing:
- per-observation raw class outputs/logits/scores;
- aggregation inputs;
- aggregation decisions;
- internally retained non-exposed outputs where permitted;
- schema/version metadata needed for forensic replay.

Relational persistence contains the final Track-level attribute outcomes only.

Every Observed row references a supporting Observation. Prediction artefact SHA and identity are recorded on the analysis header.

### 14. VisualAttribute persistence evolves around the analysis header

Conceptual shape:

**VisualAttributeAnalysis**
- identity/version fields;
- lifecycle/fencing fields;
- `PredictionArtifactId`;
- `VisibilitySequence`;
- `CompletionDigest`;
- `ProvenanceJson`;
- coverage/counts.

**VisualAttributeTrackOutcome**
- `(AnalysisId, TrackId)`;
- `Analysed | Unavailable`;
- optional reason.

**VisualAttribute**
- `AnalysisId` FK Restrict;
- `TrackId`;
- schema-coded `AttributeType`;
- `Observed | Unknown`;
- nullable schema-coded `Value`;
- nullable confidence;
- `SupportingObservationId` required when Observed, FK Restrict;
- unique `(AnalysisId, TrackId, AttributeType)`.

Per-row model name/version fields are not authoritative; producer provenance lives on the analysis header.

Search index starts with `(attribute_type, value, analysis_id, track_id)` and is retained/changed only on measured PostgreSQL plans.

### 15. Model/runtime component binding is capability-scoped

Stage 2 depends on the separate component-binding decision in ADR-014.

The platform no longer assumes one privileged detector Model Pack. Runtime/component selection binds declared capability ids to Model Packs, for example:
- `detector`;
- `person-attributes`;
- `vehicle-attributes`;
- later `plate-detector`, `ocr`, `embedding`, etc.

Model manifests are capability-neutral and qualification is capability-scoped.

ModelPackId and RuntimePackId are durable provenance for every model component.

### 16. Attribute search gets its own pinned cursor identity

Attribute search may span cameras. It therefore must not reuse the camera-bound Scene Analytics v3 cursor as-is.

Stage 2 defines a **v4 HMAC-signed cursor** that pins:
- Track-search snapshot position/sequence;
- resolved VisualAttributeAnalysis identity;
- attribute schema/pipeline/model/aggregation identity;
- attribute coverage counts/state required to preserve result meaning;
- analytics identity as well when analytics and attribute predicates are combined.

Repeated attribute predicates have canonical ordering in URL state, filter fingerprint and cache key.

When analytics predicates are present, their existing single-camera scope remains authoritative; attribute-only searches are not forced into a single-camera scope.

Encoded cursor length must be re-derived and contract-tested before S3 closes.

### 17. Qualification is part of architecture

No learned capability becomes operational merely because inference works.

Qualification identity and requalification triggers are defined before model selection. The Stage-2 qualification plan governs:
- labelling protocol and inter-annotator agreement;
- train/tune/validation/frozen-test separation;
- minimum class/value support;
- leave-one-camera-out generalisation;
- crop-level versus aggregated Track-level metrics;
- abstention/Unknown behaviour;
- non-subject crop handling;
- licensing;
- performance and device variants;
- version-skew/model-unavailable behaviour;
- operator-facing retrieval precision;
- requalification triggers.

Development evidence remains distinct from Production qualification under ADR-009.

### 18. UI specification is amended, not bypassed

Stage 2 must amend the adopted UI specification before implementation for:
- explicit Unknown presentation using a non-colour-only cue;
- Evidence Set viewer in Review/Inspector;
- `TrackDetail.observations[]`;
- attribute filter section semantics;
- provenance/coverage presentation.

Existing result-row density rules remain authoritative; Stage 2 does not add arbitrary multi-chip clutter contrary to the UI spec.

### 19. Retention and privacy

Additional native-resolution person/vehicle crops increase evidence-store exposure.

Controls:
- evidence access follows the existing Track/evidence authorisation boundary;
- no face-oriented selection criterion is allowed;
- the worker has no direct evidence-root access;
- superseded analyses and orphaned supplemental crops are retained under current evidence retention until a dedicated retention policy is adopted.

The absence of a dedicated purge policy is an accepted Stage-2 cost, with a mandatory trigger to design it before evidence-store growth reaches an operationally configured threshold or before Production release, whichever occurs first.

## Consequences

### Positive

- detector/tracker completion is isolated from downstream model churn and crashes;
- evidence is created at the only point where full frame context is available;
- later GPU-node extraction is real because evidence access is network-contract based;
- model/runtime binding becomes extensible beyond one detector;
- historical analyses remain reproducible;
- relational search rows stay compact while forensic raw predictions remain sealed;
- explicit Unknown/Unavailable semantics prevent silent false negatives;
- quality/qualification requirements are designed in rather than added after implementation.

### Costs

- VisionJob contract v3 and digest v3 are required;
- Task-10 CPU qualification matrices must be re-run for the changed raw-processing pipeline;
- CUDA end-to-end evidence, where produced, must bind to the new pipeline identity;
- component binding/runtime-profile evolution deliberately re-derives affected existing qualification hashes;
- a third asynchronous control plane is introduced;
- accepted-evidence read API and additional storage are required;
- superseded analyses/crops need future retention policy.

These are accepted costs.

## Alternatives rejected

### A. Attribute inference inside VisionJob completion
Rejected. Derived-model failure/churn must not determine raw Track validity.

### B. Evidence selection after Track persistence
Rejected. Source frames/per-frame boxes are no longer available without re-decoding.

### C. Direct filesystem mount of accepted evidence into Python
Rejected. It breaks the forensic ownership boundary and remote-worker topology.

### D. Co-host detector and attribute inference in one process by default
Rejected. It creates an avoidable shared crash/OOM failure domain.

### E. Store every crop prediction as relational rows
Rejected. It creates excessive row/body volume and couples raw model output to search schema.

### F. Missing row means Unknown
Rejected. Coverage would be ambiguous.

### G. Universal generic AI-job database abstraction now
Rejected. Reuse the transport/fencing primitives, not capability semantics.

### H. Store every frame/crop
Rejected. Storage/I/O/privacy cost is unbounded.

## Invariants

1. Python/model components never write operational PostgreSQL directly.
2. Every persisted learned assertion is traceable to accepted evidence and immutable producer identity.
3. Track and Entity remain different concepts.
4. Unknown, Unavailable, Pending, Failed and Absent remain semantically distinct.
5. Historical analytical meaning is immutable.
6. Search remains whitelist-validated, canonical and snapshot-stable.
7. Worker/model outputs and evidence storage are explicitly bounded.
8. Dependencies/model bytes are offline-declared, integrity-verified and licence-reviewed.
9. Development evidence never becomes a Production claim.
10. Capability replacement does not redesign stable MAVI domain semantics.
11. Accepted evidence remains platform-owned and hash-verified at every worker read.
12. Qualification/requalification rules are part of the capability contract.

## Architecture-freeze gate

ADR-013 was accepted after the 2026-09-23 architecture review resolution and cold consistency pass. The acceptance conditions were:
- ADR-014 component binding is coherent with ADR-005/007/009;
- the qualification plan contains no unresolved protocol gap;
- UI-spec amendments are written;
- Stage-2 plan/roadmaps use the same slice order and acceptance register;
- a final cold review reports no open P1/P2 architecture finding.

The architecture gate is closed. Feature implementation remains a separate explicit step and was not part of this documentation PR.
