# ADR-013: Modular Post-Track Intelligence and Evidence Architecture

**Status:** Accepted — Stage-2 architecture freeze; amended 2026-09-23 by the second independent cold pass (see *Architecture-freeze gate*)  
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

The selection method is frozen; only its numeric parameters are set in S1 after measurement and recorded in the pipeline profile:

- a **qualified candidate** is an observation whose detector confidence, sharpness and frame-edge margin each meet the profile's floors and whose occlusion proxy (maximum IoU with any concurrent box in the same frame) is below the profile's ceiling;
- **Representative** is the highest-scoring qualified candidate over the whole Track (the current selector rule, now versioned);
- **NearView** is the qualified candidate with the largest normalised box area that is not a near-duplicate of Representative;
- **EarlyDiverse** is the highest-scoring qualified candidate inside the Track's early window — the first `earlyWindowMs` after Track start; **LateDiverse** is the most recent qualified candidate, refreshed at most once per `lateRefreshIntervalMs`, so at retirement it is a view from the Track's final stretch; each must lie at least the profile's minimum separation from every already-selected frame and must not be a near-duplicate of one. *(Amended 2026-09-23 by the S1 plan review: the earlier "first/last temporal third" definition needs the Track's final duration, which a one-pass selector does not know until retirement, and would therefore require retaining candidate pixels for the whole Track. The anchored early window and refreshed trailing view keep the intent — one early and one late well-separated view — with exactly one encoded candidate per role at any time. See `docs/reviews/2026-09-23-stage2-s1-plan-review-resolution.md`.)*
- **near-duplicate** means the same source frame, or a frame within the profile's duplicate window whose box IoU with a selected frame exceeds the profile's threshold;
- a role that has no qualified candidate is omitted for that Track; roles are never filled with unqualified frames.

Ties within a role resolve deterministically: a candidate replaces the current holder only on strict improvement (score, or area for NearView, by at least the profile's replacement epsilon), so equal scores keep the earlier frame. Roles are evaluated in the order Representative, NearView, EarlyDiverse, LateDiverse, so the same Track always yields the same set.

Representative remains the primary display summary. Supplemental roles exist to improve later analytical coverage, not to redefine the Track.

### 5. Evidence crops are encoded in-loop and staged only when a Track retires

Candidate crops are JPEG-encoded when selected/replaced in the processing loop and held as bounded encoded bytes while the Track remains live. They are written to attempt-scoped staging once, when that Track retires (or at end-of-stream for Tracks still live). The worker must not retain K raw RGB arrays per live Track and must not rewrite staging on every candidate replacement.

Initial Stage-2 evidence encoding contract:
- maximum candidate roles per Track: **4**;
- maximum long edge: **1024 px**;
- initial JPEG quality target: **85**;
- mandatory Representative encoded size cap: **64 KiB**;
- supplemental crop encoded size cap: **160 KiB each**;
- crop dimensions and encoding quality may be reduced deterministically to satisfy the byte cap; the source-frame/bounding-box linkage remains authoritative.

These are product bounds, not quality claims. Qualification determines whether the resulting evidence remains sufficient for an exposed capability.

Two consequences are stated so they are not discovered in implementation:

- At quality 85 a 1024-px-long-edge crop of natural imagery typically encodes to 100–160 KiB, so the 64 KiB Representative cap implies an effective Representative ceiling of roughly 600–700 px long edge for large subjects. **Representative is the display/summary crop; NearView (160 KiB) is the analytic-resolution carrier** on which later plate/embedding work depends. Qualification §8 measures the quality impact of both caps.
- Deterministic reduction has a floor: the long edge is never reduced below **128 px** and quality never below **50**. A candidate that still exceeds its cap at the floor is not admitted for that role (Representative then falls back to the next-best qualified candidate; the run fails only if no Representative can be produced for an accepted Track).

**Memory, Track retirement and staging behaviour.** The current pipeline retains one raw RGB crop per Track for the whole run and the current model-neutral `Tracker` protocol returns only per-frame `TrackCandidate` values; it exposes no Track-retirement event. Contract v3 therefore requires an explicit model-neutral lifecycle extension rather than having `VideoProcessor` duplicate ByteTrack's lost-track timing.

The tracker boundary evolves conceptually to return a per-frame update containing:
- current evidence-bearing Track candidates; and
- zero or more **retired MAVI Track ids**.

A Track id is emitted as retired **exactly once**, only when the tracker adapter guarantees that the identity can no longer reappear under that attempt's association semantics (for ByteTrack, after its lost-track buffer has expired). A retired id may never appear in a later update, and a retired id is never emitted in the same update as a candidate for that id. At end-of-stream the pipeline finalises every still-live Track without a retirement event. The adapter owns backend-specific retirement semantics; `VideoProcessor` consumes the generic retirement signal and does not maintain an independent shadow timeout.

Two rules make the no-reappearance guarantee hold by construction rather than by trusting backend internals:
- **Mapping release.** The adapter's native-id → MAVI-id map (today `_person_native_to_mavi` / `_vehicle_native_to_mavi`, which is never pruned) releases the entry on retirement. If the backend ever re-emits a released native id, the adapter allocates a **fresh** MAVI id from its monotonic counter; a MAVI id is therefore never reused within an attempt regardless of backend id-reuse behaviour, and the map is bounded by live Tracks.
- **Retire strictly after the backend can re-associate.** Where the adapter derives retirement from the backend's configured budget rather than from an explicit backend removal signal, it retires only once the elapsed media time since the id's last emission exceeds that budget by at least one accepted frame interval, so the adapter can never retire an id the backend could still match. Retired ids within one update are emitted in a deterministic order.

An adapter that poisons its attempt (`bytetrack_attempt_invalidated`) has already failed the attempt; retirement state is attempt-scoped and starts empty with every new adapter, like the id counters.

**What retirement finalises.** Retirement is the point at which *everything* for that Track is complete: the trajectory point list, the confidence summary, the Representative and the supplemental candidates. Contract v3 therefore finalises the whole Track at retirement — the trajectory artefact and Representative crop are encoded and staged once, supplemental candidates are staged once, and the accumulator is replaced by descriptors plus scalar summary. The trajectory list is the larger resident structure (one `TrajectoryPoint` per detection; a long Track holds thousands), so leaving it resident until end-of-video would defeat the live-Track bound even with crops staged. Nothing in the completion contract requires per-Track data to stay resident: `VisionResultValidator` sorts Tracks itself and the digest is order-independent.

While a Track is live, its current best candidate per role is held **encoded** (a replacement re-encodes and discards the predecessor), so memory per live Track is at most 4 × 160 KiB ≈ 544 KiB plus its trajectory-in-progress, and worker memory is bounded by *live* Tracks rather than all Tracks. Staging disk is bounded by all candidates before run-level admission: at 10,000 Tracks that is at most 10,000 × 544 KiB ≈ 5.2 GiB of transient attempt-scoped staging plus trajectories, reclaimed by the platform staging janitor (ADR-006 §6, accepted 2026-09-23), with worker attempt cleanup as a fast path. Run-level admission (§6) happens at finalisation, when every candidate is known; omitted supplemental candidates are simply never referenced. Because an attempt's staging can now reach several GiB, S1 also bounds staging **across attempts** of one job: when a new attempt is leased, the worker removes staging left by earlier attempts of the same job (those attempts are fenced out and their descriptors can never be accepted), rather than relying only on later policy cleanup.

The deterministic fixture tracker used by tests and the fixture worker harness must implement the same retirement contract, so the retirement, reactivation-before-expiry, no-reappearance and end-of-stream cases can be exercised without the native backend.

The live-Track memory-bound claim is not considered implemented until retirement exact-once/no-reappearance semantics are contract-tested against the tracker adapter, including disappearance within the lost buffer, reappearance before expiry, retirement after expiry, and end-of-stream drain.

### 6. Evidence storage is bounded at both Track and ProcessingRun level

Contract v3 separates evidence-crop quota from other analytical artefact quotas.

For one ProcessingRun:
- mandatory Representative evidence is admitted first;
- total sealed EvidenceCrop bytes are capped at **1 GiB**;
- supplemental roles are admitted in deterministic rounds (NearView for eligible Tracks, then EarlyDiverse, then LateDiverse); within a round Tracks are ordered by the candidate's selector score descending, then LocalTrackNumber ascending, so the strongest supplemental evidence is admitted first rather than the earliest Track;
- once the run-level evidence budget is exhausted, remaining supplemental candidates are omitted; Representative is never omitted for an accepted Track;
- completion metadata records candidate/admitted/omitted counts and bytes by role.

At the existing maximum of 10,000 Tracks, the 64 KiB Representative cap yields a worst-case mandatory crop budget of 625 MiB, leaving 399 MiB of headroom for supplemental evidence inside the 1 GiB quota. Since supplemental crops are capped at 160 KiB, that headroom admits **at most ≈2,550 supplemental crops of a possible 30,000**: in the worst-case run only the NearView round is partially filled and roughly 8.5 % of Tracks receive any supplemental evidence. The quota is a degradation bound, not a coverage promise; a typical run of hundreds of Tracks receives every qualified role. Qualification §8 reports admission rates so this trade-off is measured, and the constants may be re-derived from that evidence through the pipeline-profile change rule below.

The existing 512 MiB aggregate evidence bound of contract v2 becomes the trajectory/other-artefact quota in v3; EvidenceCrop bytes are counted against the separate 1 GiB quota; the 64 MiB per-artefact cap is unchanged.

The completion HTTP body carries descriptors, never crop bytes. Each additional descriptor is on the order of 250 bytes (storage key, media type, size, SHA-256, role, score, frame linkage), so 10,000 Tracks × 3 supplemental descriptors add roughly 7.5 MiB to a body that today approaches 20 MiB at the same Track count. `MaximumCompletionRequestBodyBytes` (currently 32 MiB) is re-derived for v3 and contract-tested at the 10,000-Track, four-role bound before S1 closes. Sealed artefact validation remains hash/size checked.

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

Two processes on one GPU each hold a CUDA context and model weights. The Development GPU has 4 GiB of VRAM (`docs/qualification/2026-09-18-windows-cuda-c1-compatibility-decision.md`, *4 GB VRAM operating constraint*), so co-residency is not free. Therefore:
- each role has its **own device policy** in the deployment/release profile (ADR-008 device policies apply per role); on a single-GPU host the profile decides which roles use CUDA, and the attributes role may run on CPU while the detector holds the GPU;
- silent GPU-to-CPU fallback remains prohibited for every role (ADR-008); the resolved device is in each role's provenance;
- qualification §10 measures RAM/VRAM with both roles co-resident on one host and records the supported combinations per profile.

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

Lease semantics follow the **VisionJob** shape, not the SceneAnalysis shape, because the executor is a separate process that may be remote: the lease has an expiry that heartbeats extend; completion, failure and evidence reads are refused once the lease has expired or the attempt number no longer matches; a reclaim issues a new attempt and a new token. Lease duration must exceed the heartbeat interval by a configured margin, and a unit that exceeds its configured maximum duration fails as a whole rather than publishing partial results. One unit covers one ProcessingRun; at the 10,000-Track bound a CPU unit may run for hours, which the heartbeat design accommodates and qualification §10 measures.

The identity a queued unit will carry is resolved from the enabled capability bindings at queue time, so it changes only when the bindings change. A binding change does **not** automatically re-analyse history: existing units become Stale for readiness and remain readable; re-analysis is an explicit, bounded request per run or camera/time window, exactly as scene-analytics re-analysis is today. Automatic historical backfill is out of Stage 2.

### 10. Accepted evidence is served by the platform; Python never mounts the evidence root

The accepted-evidence root remains .NET-owned.

An attribute lease payload identifies each required Observation and expected artefact SHA-256/size. The executor obtains bytes only through a **platform-served, lease-scoped evidence-read endpoint** in the same API trust family as its job lease.

The executor:
1. presents the active lease capability;
2. requests the permitted Observation artefact;
3. verifies received size and SHA-256 before decode/inference;
4. fails that Track as `Unavailable` on mismatch or inaccessible evidence.

The read endpoint is bound to the unit's lease, not to the operator session:
- the lease capability travels in a header, never in the URL, and no response, log or error may echo it (the existing VisionJob fail-endpoint rule applies);
- a read is authorised only while the unit is `Running`, the attempt number matches and the lease is unexpired; the requested Observation must belong to a Track of that unit's ProcessingRun; a stale or foreign request is `409`, never a partial body;
- the response is bounded to the artefact's recorded `SizeBytes` and streamed from the accepted-evidence root through `IAcceptedEvidenceReader`; there is no listing or search endpoint;
- every read is logged with unit id, attempt, Observation id, bytes and outcome, so evidence access by executors is auditable;
- cancellation of the unit ends in-flight reads.

The **prediction artefact travels the same way in reverse**. The attribute executor does not write to worker staging or to any platform filesystem: it uploads the `AttributePredictions` bytes through a lease-scoped, size-capped upload endpoint in the same trust family; the platform verifies the declared size and SHA-256 while streaming, stages under an attempt-scoped key and seals it under ADR-006 at completion exactly as VisionJob artefacts are sealed. A completion whose declared artefact SHA does not match the uploaded bytes is `vision_result_artifact_integrity_failed` and nothing publishes.

Direct filesystem access from the attribute worker to the accepted-evidence root, and to worker staging, is prohibited.

With reads and the single upload both network contracts, the attribute role has **no filesystem dependency on the platform host**. This is what makes later separate GPU nodes real rather than aspirational.

### 11. Analysis identity is immutable and qualification-relevant

A VisualAttributeAnalysis identity is exactly:
- ProcessingRunId;
- attribute schema version/SHA;
- attribute pipeline version;
- aggregation-policy version/SHA;
- ordered capability/model-pack identities;
- parameters SHA-256.

Runtime-pack identity and variant, actual device, platform build and commit are **provenance, not identity**: they are recorded on the analysis header and enter the completion digest, but they do not create a new analysis. This follows ADR-011 Decision 3 (the commit never participates in identity or staleness). Were the variant part of identity, running the same model on a CPU host and later on a CUDA host would manufacture a "newer" analysis that supersedes a semantically identical one, and every deployment would mark history Stale. The corollary is a qualification obligation: a release profile may bind a model pack on more than one runtime variant only when qualification has shown those variants produce equivalent outcomes within the declared tolerance (qualification plan §10/§16); otherwise the profile binds the qualified variant alone.

A materially different identity creates a new immutable analysis. A completed newer analysis may supersede the previous default. Historical analyses remain readable.

Supersession occurs only on successful completion.

### 12. Explicit readiness and outcome semantics

Run-level readiness:
- NotConfigured — no enabled attribute capability binding exists in the release, so no analysis is expected (the analogue of a camera without scene configuration);
- NotApplicable — the capability is bound but the run has no Track to which any schema attribute applies;
- Pending;
- Ready;
- Failed;
- Stale.

NotConfigured and NotApplicable are reported separately so that "attributes are not deployed" is never read as "this run had nothing to analyse".

Track-level analysis outcome:
- Analysed;
- Unavailable, with reason.

For every applicable `(Track, attribute type)` in a completed analysis, exactly one final attribute row exists with:
- `Outcome = Observed`, non-null qualified value, supporting Observation required; or
- `Outcome = Unknown`, null value.

Missing row is not Unknown. It means the attribute was not part of that completed applicable analysis.

`Absent` is a qualified schema value only where the attribute schema explicitly defines reliable negative semantics.

An Observed row's confidence is the aggregation policy's score for the asserted value, in [0,1]; its meaning is defined by the aggregation-policy version recorded on the analysis header and it is displayed under UI-spec §24. An attribute holds one value per Track per analysis; a garment or vehicle that is genuinely two-tone is represented only through a qualified schema value such as `multicolour`, never through two rows.

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

The artefact is a versioned, self-describing document: it carries its own schema identifier and version, the analysis identity it belongs to, and per-observation raw scores for every class the model emits (bounded by schema × observations, on the order of a few MiB at 10,000 Tracks × 4 crops × 20 classes). It is capped by the existing 64 MiB per-artefact bound, delivered through the lease-scoped upload in §10, sealed under ADR-006 and read only through `IAcceptedEvidenceReader`; it is never indexed or queried relationally. The concrete encoding is an S2b decision constrained to dependencies already on the qualified graph (MessagePack is already such a dependency); no new serialisation library may be introduced for it.

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
- the resolved **attribute capability identity fingerprint** — the SHA-256 of the canonical tuple (attribute schema SHA, attribute pipeline version, aggregation-policy SHA, ordered capability/model-pack ids, parameters SHA), i.e. the §11 identity without the run; the first page resolves the tuple from the enabled bindings and returns it in full in the coverage block, and the cursor carries only the 64-hex fingerprint;
- attribute coverage counts/state required to preserve result meaning;
- analytics identity as well when analytics and attribute predicates are combined.

Per-run analysis units are not pinned individually: a continuation page resolves, for each visible run, the fact-bearing `VisualAttributeAnalysis` whose identity fingerprint equals the pinned one, which is unique per run. A superseding analysis published mid-pagination has a different fingerprint and cannot change what an open result set means; the superseded unit remains fact-bearing and readable for the pinned fingerprint.

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

A second independent cold pass on 2026-09-23 (recorded in `docs/reviews/2026-09-23-visual-attributes-architecture-review-resolution.md`, *Second independent pass*) found further P1/P2 gaps in this ADR — the prediction-artefact delivery path, the attribute lease semantics, the evidence-read endpoint contract, the selector method, memory/staging behaviour, the admission order and worst-case coverage, per-role device policy, the `NotConfigured` readiness state and the v4 cursor identity representation — and amended the text above in place. The architecture gate is closed on the amended text. Feature implementation remains a separate explicit step and was not part of this documentation PR.
