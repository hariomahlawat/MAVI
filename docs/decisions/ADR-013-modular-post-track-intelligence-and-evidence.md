# ADR-013: Modular Post-Track Intelligence and Evidence Architecture

**Status:** Accepted — Stage-2 architecture freeze; amended 2026-09-23 by the second independent cold pass (see *Architecture-freeze gate*)  
**Date:** 2026-09-23  
**Amended:** 2026-09-24 — §4 two-tier Representative (S1.2c), ratified by the owner; 2026-09-24 — §4 credible-competitor occlusion proxy (scorer `quality-v2`, S1.2c), decided by the owner; 2026-09-28 — S2b implementation amendment (see *Implementation amendment 2026-09-28 (S2b)*); 2026-09-28 — S2c learned-model amendment items 8–10 accepted by PR #115 after independent review and exact-head CI; S2c.0 reconciles that acceptance into the implementation baseline; 2026-10-13 — Stage-4 plate implementation amendment items 11–15 (see *Implementation amendment 2026-10-13 (Stage 4 plates)*), accepted by the owner on 2026-10-13 as an architecture decision  
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

Selection uses only model-neutral Track/frame information available during raw processing: object area, sharpness, detector confidence, frame-edge clipping, temporal separation and an occlusion proxy derived from overlap with concurrent boxes *(amended 2026-09-24: credible concurrent boxes only; see the occlusion-proxy amendment below)*. No face-oriented, plate-oriented, demographic or downstream-model-specific selector is allowed.

The selection method is frozen; only its numeric parameters are set in S1 after measurement and recorded in the pipeline profile:

- a **qualified candidate** is an observation whose detector confidence, sharpness and frame-edge margin each meet the profile's floors and whose occlusion proxy (maximum IoU with any concurrent box in the same frame) is below the profile's ceiling; *(Amended 2026-09-24, S1.2c: a concurrent box counts only if it is a **credible competing detection**, of either class, whose detector confidence is at or above the profile's `confidenceFloor`. This is scorer `quality-v2`; see the occlusion-proxy amendment below.)*
- **Representative** is the highest-scoring qualified candidate over the whole Track (the current selector rule, now versioned); *(Amended 2026-09-24, S1.2c: before a Track's first qualified admissible candidate, a fallback Representative may hold the role. See the two-tier amendment below.)*
- **NearView** is the qualified candidate with the largest normalised box area that is not a near-duplicate of Representative;
- **EarlyDiverse** is the highest-scoring qualified candidate inside the Track's early window — the first `earlyWindowMs` after Track start; **LateDiverse** is the most recent qualified candidate, refreshed at most once per `lateRefreshIntervalMs`, so at retirement it is a view from the Track's final stretch; each must lie at least the profile's minimum separation from every already-selected frame and must not be a near-duplicate of one. *(Amended 2026-09-23 by the S1 plan review: the earlier "first/last temporal third" definition needs the Track's final duration, which a one-pass selector does not know until retirement, and would therefore require retaining candidate pixels for the whole Track. The anchored early window and refreshed trailing view keep the intent — one early and one late well-separated view — with exactly one encoded candidate per role at any time. See `docs/reviews/2026-09-23-stage2-s1-plan-review-resolution.md`.)*
- **near-duplicate** means the same source frame, or a frame within the profile's duplicate window whose box IoU with a selected frame exceeds the profile's threshold; *(Amended 2026-09-24, S1.2c: as implemented, IoU **at or above** the threshold, per plan §4.1.)*
- a role that has no qualified candidate is omitted for that Track; roles are never filled with unqualified frames. *(Amended 2026-09-24, S1.2c: this now holds for the three supplemental roles only. The mandatory Representative follows the two-tier rule below.)*

Ties within a role resolve deterministically: a candidate replaces the current holder only on strict improvement (score, or area for NearView, by at least the profile's replacement epsilon), so equal scores keep the earlier frame. *(Amended 2026-09-24, S1.2c: "improvement" is strict. A score must exceed the holder's by **more than** `replaceEpsilon`, and a NearView area must exceed `holder · (1 + nearViewGrowth)`; ε does not apply to NearView. This follows plan §4.2.)* Roles are evaluated in the order Representative, NearView, EarlyDiverse, LateDiverse, so the same Track always yields the same set.

> **Amendment (S1.2c, 2026-09-24): two-tier Representative.**
>
> **Status of this amendment:** Accepted 2026-09-24. The owner ratified it with the S1.2c implementation. Plan `docs/superpowers/plans/2026-09-23-stage2-s1-2-evidence-set-implementation.md` §16.2 (E8, E19) and `docs/qualification/2026-09-24-evidence-selector-parameter-note.md` record the implementation and the evidence.
>
> *Problem.* Read strictly, the two rules above require every accepted Track to have at least one qualified frame, and §5 fails the whole attempt when a Track has no Representative. Real Tracks can have none: a subject that stays clipped by the frame edge, one that stays overlapped by another box, or a low-texture subject below the sharpness floor. The C1 scripted corpus shows it outright. Its uniform box measures sharpness 0–0.023, below the 0.05 floor, in every frame of all three videos, so under the strict rule every corpus job fails with `evidence_representative_missing`. One such Track would fail a whole ProcessingRun and discard every other Track's evidence, and a retry fails the same way.
>
> *Rule.*
> 1. The Representative is mandatory for every accepted Track.
> 2. While a Track has no qualified admissible candidate, the Representative is the best **admissible** candidate under the ε rule: a candidate replaces the holder only when its selection score is **strictly greater** than the holder's plus `replaceEpsilon`, so equal or near-equal scores keep the earlier frame. This holder is a *fallback Representative*.
> 3. The first qualified admissible candidate displaces a fallback Representative, whatever its score relative to the fallback.
> 4. Once the Representative is qualified, only qualified candidates may replace it, under the same ε rule.
> 5. NearView, EarlyDiverse and LateDiverse stay **qualified-only**. A fallback Representative never relaxes their eligibility.
> 6. The attempt fails if no admissible candidate exists at all (`evidence_representative_missing`). Run-level admission (§6) never omits a Representative; if the Representatives alone exceed the quota, the run fails (`evidence_quota_exceeded`).
>
> The rule is online, needs no reservoir, and encodes only would-be replacements. The worker implements it as selector version **`evidence-selector-v1-two-tier`**, a name distinct from the strict rule, so strict and two-tier outcomes are never reported under one selector identity. The version is part of the pipeline profile and therefore of `pipelineProfileSha256` in completion provenance.
>
> *Semantic consequence (binding on consumers).*
> - **The existence of a Representative does not imply that it passed every selector quality floor.** It is the Track's mandatory display/summary crop, not "qualified evidence".
> - Supplemental roles remain qualified-only, and are therefore the appropriate raw evidence roles for downstream analytical coverage when qualification is required.
> - No downstream capability may infer "qualified" from `role == representative`.
>
> *Wire boundary (known limitation).* Completion 3.0 carries no per-observation qualified flag. A consumer has the observation's `qualityScore`, the role (supplemental roles are qualified by construction), and the selector version via the pipeline-profile provenance; nothing on the wire says whether a given Representative is a fallback. A later analytical feature that must consume the Representative under a qualification-sensitive rule has to introduce or derive an explicit qualification contract first (for example a contract revision carrying the tier, or its own re-scoring of the crop). Adding such a flag is deliberately not part of S1.2c.
>
> *Trade-off accepted.* A Track can carry a Representative that fails a quality floor. In exchange, one hard Track no longer fails the whole run and discards every other Track's evidence, and later analytical coverage still never rests on unqualified supplemental frames.

> **Amendment (S1.2c, 2026-09-24): credible-competitor occlusion proxy (scorer `quality-v2`).**
>
> **Status of this amendment:** Accepted 2026-09-24. The owner decided it on the real-clip measurement: option (a) of finding F1 in `docs/qualification/2026-09-24-evidence-selector-parameter-note.md`. Plan `docs/superpowers/plans/2026-09-23-stage2-s1-2-evidence-set-implementation.md` §4.1 and §16.2 (E24) record the implementation.
>
> *Problem.* "Any concurrent box" was implemented as every detection the tracker was given, down to the profile's `detectorInferenceFloor` (0.05). RTMDet's NMS runs per source class, so that set includes:
> - low-confidence part-boxes and duplicates of the subject itself;
> - same-object `car` / `truck` / `bus` boxes, which all map to `vehicle`.
>
> On the 1920×1080 MOT17-02 / MOT17-13 measurement:
> - 93 % of occlusion rejections came only from boxes below `confidenceFloor`;
> - 58.7 % of Representatives were fallbacks;
> - vehicles qualified in 1 frame of 2,801.
>
> By the benchmark's ground truth, the persons rejected this way were almost as visible as those accepted (median visibility 1.00). No `occlusionIouCeiling` value separates near-duplicates of the subject from real occlusion.
>
> *Rule.*
> 1. The occlusion proxy is the maximum IoU between the candidate's box and any **credible competing detection** in the same frame.
> 2. A competing detection is credible when its detector confidence is **at or above** the profile's `confidenceFloor`. That is the floor a detection must itself meet to qualify as evidence. It is inclusive: a detection exactly at the floor counts.
> 3. Both object classes count, and so do detections the tracker did not confirm.
> 4. The candidate's own source detection is excluded exactly once (same class, exact box) **before** the credibility filter, because a tracker may confirm a candidate from a sub-floor detection. A candidate whose source detection is absent fails closed.
> 5. Nothing else changes: the frame-quality formula, quantisation, `occlusionIouCeiling`, `occlusionPenaltyWeight`, the qualification floors and the two-tier Representative.
>
> The worker implements the rule as scorer version **`quality-v2`**, and the profile loader refuses `quality-v1`. The scorer version is part of the pipeline profile and therefore of `pipelineProfileSha256` in completion provenance, so quality-v1 and quality-v2 outcomes are never reported under one identity. The competitor floor is not a separate parameter: it is `confidenceFloor`, so the proxy and the qualification floor cannot drift apart.
>
> *Trade-off accepted.* A genuinely occluding neighbour that the detector sees only below `confidenceFloor` no longer disqualifies a frame. In the ground-truth sample, 10.1 % of the persons that quality-v1 rejected only through sub-floor boxes were less than half visible, against 3.4 % of those that passed. In exchange, the proxy stops treating the detector's own residue as occlusion. Qualified evidence then becomes the common case on real footage, and vehicles can qualify at all.

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
- Deterministic reduction has a floor: the long edge is never reduced below **128 px** and quality never below **50**. A candidate that still exceeds its cap at the floor is not admitted for that role (Representative then falls back to the next-best qualified candidate; the run fails only if no Representative can be produced for an accepted Track). *(Amended 2026-09-24, S1.2c: the online rule keeps the current admissible holder when a better candidate is not admissible. A fallback Representative is possible under the §4 two-tier amendment.)*

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

The artefact is a versioned, self-describing document: it carries its own schema identifier and version, the analysis identity it belongs to, and per-observation raw scores for every class the model emits (bounded by schema × observations, on the order of a few MiB at 10,000 Tracks × 4 crops × 20 classes). It is capped by the existing 64 MiB per-artefact bound, delivered through the lease-scoped upload in §10, sealed under ADR-006 and read only through `IAcceptedEvidenceReader`; it is never indexed or queried relationally. The concrete encoding is an S2b decision constrained to dependencies already on the qualified graph; no new serialisation library may be introduced for it. *(Corrected 2026-09-28, S2b: MessagePack is on the qualified graph only on the Python side — `msgpack` for the worker's trajectories; the .NET platform has no MessagePack dependency and must not gain one for this artefact. S2b chose canonical UTF-8 JSON, which both stacks already read and write. See implementation amendment item 6.)*

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

## Implementation amendment 2026-09-28 (S2b)

This amendment records how S2b implements §9–§13 where the text above left the mechanism open or where the merged S2b plan (`docs/superpowers/plans/2026-09-28-stage2-s2b-attribute-lifecycle.md`) and the acceptance register already refined it. It changes no decision above; each item states the trade-off it accepts.

1. **The platform reads the preferred identity from the release overlay (§9, §11).** "Resolved from the enabled capability bindings at queue time" requires the platform to know those bindings, and until S2b it never read the Component Binding. The platform is configured with the path of the release Component Binding and of the attribute pipeline profile (the attribute schema, aggregation policy and parameters, each pinned by SHA-256) and derives the identity tuple and its fingerprint (§16) from exactly those bytes, with the same canonical derivation the worker uses. Nothing configured means `NotConfigured`. Every attribute lease request carries the worker's own resolved fingerprint and the claim is fenced on it, so a worker composed from a different binding can neither take ownership of a unit nor consume one of its attempts. *Trade-off:* the platform parses a narrow, fail-closed subset of the binding. A second, platform-local declaration of the identity was rejected: two authorities could drift, and the lease fence would surface the drift only as permanently pending work.
2. **The lease capability travels only in a header (§9, §10).** The reusable envelope of §9 carries `schemaVersion, jobId, workerId, attemptCount, provenance, payload`; `leaseToken` is removed from it. Every attribute route — lease response included — carries the capability in the `X-Mavi-Lease-Capability` header, never in a JSON body, URL, digest, persisted payload, log or error. This is the register's deliberate D3 amendment. *Trade-off:* the attribute plane differs from the VisionJob body-token convention, which remains unchanged.
3. **Transport failure is not evidence unavailability (§10 step 4).** A Track is `Unavailable` only for a platform-authoritative condition — the sealed object is missing, or its bytes do not match the recorded size and SHA-256 at rest, or a fully received body disagrees with the descriptor — and such a condition also raises an operator-visible integrity signal. A reset, timeout, 5xx or truncated transfer is retried within the lease; if it persists, the attempt fails as retryable and no Track outcome is published. *Trade-off:* a persistently unreachable object costs attempts before the unit fails, instead of silently publishing a permanent `Unavailable` for a transient cause.
4. **Completion is a three-phase protocol (§10, §13).** Phase A validates under a row lock and releases it; Phase B seals the prediction artefact outside any transaction to a content-addressed accepted key that is not attempt-scoped (identical bytes from a retry adopt the sealed object); Phase C re-acquires the unit row `FOR UPDATE`, re-verifies status, attempt and capability hash, and only then publishes rows, sequence and supersession in one transaction. Lease expiry after Phase A does not by itself invalidate Phase C; a reclaim does. Accepted objects are never deleted as compensation (ADR-006 §5). **Invariant:** a completion that passes Phase A while its lease is live is entitled to reach Phase C for one *publication window* — a lease duration from Phase A — and within that window no platform action may take the unit from it: no reclaim, no attempts-exhausted transition and no deadline transition. The window is carried by the existing lease (Phase A extends the owner's lease; no new lifecycle state), so every rule that already waits for an expired lease honours it, and the deadline transition, too, applies only to a unit with no live lease. The window may outlast the absolute deadline by at most one lease duration and cannot be extended further, and a heartbeat never shortens a lease. When the window lapses without a Phase C commit (the platform process died, or the seal stalled), reclaim, exhaustion and deadline proceed as for any expired lease, and Phase C of the old attempt is then refused by ownership, so abandoned work stays bounded. *Trade-off:* the absolute deadline bounds when a completion must be *validated*; its publication may end up to one lease later.
5. **Default selection is derived, not labelled (§11).** The default analysis of a run is the fact-bearing analysis whose fingerprint equals the currently preferred one; completion order never decides it. `Completed` and `Superseded` record history and are never rewritten on a binding change, so a rollback re-derives the default from an existing successful analysis. When only obsolete identities have completed there is no default and readiness is `Stale`.
6. **The artefact is canonical JSON and its size is bounded by the schema (§13).** `AttributePredictions` is canonical UTF-8 JSON (sorted keys, compact separators, ASCII only, no NaN, one trailing LF); the platform hashes the bytes it received and validates them with a streaming reader, never re-serialising. The "few MiB" estimate above becomes an enforced rule: an attribute schema is refused — by the platform's release parser and by the worker's loader alike — unless the worst-case artefact an honest worker can produce under it at 10,000 Tracks × 4 crops fits the 64 MiB upload cap (cross-language vector `contracts/test-vectors/visual-attribute-artifact-bound-v1.json`). *Trade-off:* long attribute tokens or large value sets are refused at release time rather than failing at the upload cap in the field. **Evidence coverage:** for every Track the artefact accounts for each leased crop exactly once — scored, or unavailable with a reason — so no usable evidence can be left out silently; an Unavailable Track's reason is one its crops report. A crop the worker found missing or not matching its recorded digest is counted in the operator integrity health (`/api/health`) as one completion incident, whether or not its Track was still analysed from its other crops: the platform cannot see that mismatch itself, because the worker hashes what it reads. It is recorded (and logged, event 1994) as soon as the owner's artefact validates, not after the commit, so a commit that lands but reports failure — answered on retry by committed replay — loses nothing; each crop counts once, so the retry adds nothing.
7. **Lease-scoped streams are authorised for their lifetime (§10).** An evidence read or a prediction upload is authorised before its first byte and remains so only while the same attempt still holds an active lease: when ownership is lost mid-stream — expiry, reclaim, or the owner's own failure followed by another attempt's claim — the stream stops. An evidence response already started is aborted (the worker sees an incomplete transfer, never a short success); an upload is refused and its temporary staging file discarded, so nothing is staged. The check costs a clock comparison per read; the database is consulted only when the lease last granted is reached (a heartbeat may have renewed it) and once a bounded interval has passed since ownership was last observed (first by the request's authorisation, then by each read of the row), which is exact because another executor can take a unit only after its lease expires, except after the owner's own failure. *Trade-off:* a long transfer pays one primary-key read per interval.


## Amendment 2026-09-28 (S2c learned models)

**Status: Accepted by PR #115.** PR #115 merged the independently reviewed S2c plan at `main@677afb6b73edf436e23f8d275bb95a7d5b3badac`; its exact head `33a701d0045b6fa8961a10f69189313d60e6111c` passed MAVI Quality Gate #2159 and Task 17 Acceptance Validation #1293 with no unresolved review threads. Items 8–10 below are therefore governing decisions for S2c implementation. S2c.0 records/reconciles this already-effective acceptance; it is not a second architecture-approval event. They do not themselves claim any learned-model, Development, CUDA or Production qualification. Planning against the merged S2b implementation (`main@f7b03a2`) found three points where a real learned model needs a decision the text above leaves open. Each item states the trade-off it accepts. None changes the lifecycle, the evidence-read boundary, supersession, default derivation or the Unknown/Unavailable semantics.

8. **Model-specific inference sits behind a capability adapter declared by the Model Pack (§1, §15; ADR-014 §3).** The worker verifies each crop (S2b), decodes it once under the Evidence Set pixel bound and applies admissibility (item 9); a learned `person-attributes` or `vehicle-attributes` Model Pack then supplies, through a registered `capabilitySpecific.<capabilityId>` section, an `adapterId` from a closed, versioned registry in the attributes role, its preprocessing specification, its output mapping and the attribute schema (id, version, SHA-256) whose values it scores. The adapter returns, per attribute type, either a score in [0,1] for each schema value or, only when the model has an explicit applicability/visibility output declared by its output mapping, the abstention reason `model_not_applicable`; preprocessing, label mapping and any calibration fitted for that model are pack artefacts and therefore inside `modelPackId`, and model outputs outside the schema are discarded by the mapping. The platform continues to know only the capability contract and the pack identity. *Trade-off:* refitting a calibration or changing a mapping is a new Model Pack identity and a requalification trigger; a model family no registered adapter can run needs reviewed worker code, not data.
9. **Crop admissibility, per-attribute abstention and artefact versioning are explicit (§4 amendment, §7, §11, §12, §13).** The attribute pipeline declares a versioned admissibility method (its parameters in the identity-bearing parameters file) applied to every decoded crop before any score: for example a minimum subject size per object class and an achromatic/infrared test that makes colour attributes inapplicable to a crop. A crop/type pair that fails is recorded in the `AttributePredictions` artefact as *abstained* with a reason from a closed vocabulary and contributes no score. How scored but low-evidence crops are weighed (for example an evidence floor for categorical types and top-k pooling for presence types) belongs to the versioned aggregation method, not to admissibility. **The Representative:** the lease cannot say whether a Representative is a qualified frame or a fallback, and that cannot be derived; until an explicit qualification contract carries the selector's `qualified` flag (a separate §4 amendment, if evidence justifies it), the default policy records every Representative crop as abstained (`representative_qualification_unknown`), so an Observed value rests only on qualified supplemental evidence — the conservative reading of the parent plan's §8.2. A Track with at least one crop that was verified and decoded is `Analysed` even when every crop abstained for every attribute, and each attribute without a scored crop is `Unknown`; `Unavailable` keeps its S2b meaning. This is artefact schema `mavi-attribute-predictions-v2` (a per-observation `abstained` map beside S2b's `scores`). Because a unit of a non-preferred identity can still be leased and completed, the artefact version and the admissibility method become **identity**: pipeline profile schema v2 declares both, canonical identity v2 includes both (v1 and v2 identities cannot collide), and the platform persists the artefact version on the identity activation and validates each unit's artefact against its own identity. Sealed v1 artefacts remain valid history and are never reinterpreted. *Trade-off:* one more artefact version, a pipeline-profile and identity version and a migration, in exchange for Unknown that is measured and attributable, and a coverage cost (Representative-only Tracks yield Unknown) that is measured rather than hidden.
10. **The vision lock is never widened for an attribute model (§8; ADR-014 §1).** Per-role device policy and the prohibition of silent fallback (§8, ADR-008) and per-role Runtime Pack families (ADR-014 §1) already apply to the attributes role. The new rule is only this: if the selected learned model needs a dependency outside the vision role's Runtime Pack family, the attributes role binds its own family, so the qualified detector environment is not requalified for an attribute model; and that route is taken only when the S2c bake-off shows a material quality advantage over candidates on the existing graph. *Trade-off:* a second Runtime Pack (build, kit bytes, CUDA variant qualification of its own) whenever it is taken.

## Implementation amendment 2026-10-13 (Stage 4 plates)

**Status: Accepted — owner architecture decision, 2026-10-13.** Proposed in Stage 4 PR-3 (`docs/superpowers/plans/2026-10-12-stage4-anpr-ocr.md` §9.1 B1–B4; recorded here before the plate lifecycle was implemented, as that plan requires) and accepted by the owner on 2026-10-13 with every trade-off below as stated. The acceptance is an architecture decision, **not** qualification evidence: it qualifies no model, Runtime Pack, host or measurement, and claims no Development, CUDA or Production qualification. The 2/1/3 output bound and the 64 MiB artefact bound are unchanged by it. It applies §8–§14 and items 1–10 to a second learned post-Track capability family — `plate-detector` and `ocr`, served by one `plates` role — and records the points where a plate reading needs a decision the attribute text leaves open. It changes no decision above and claims no Development, CUDA or Production qualification. The search-side decisions (plan B5, literal normalised matching; B6, time ordering) belong to PR-4 and the §16 v4 cursor, not here. Every item holds whatever the Stage-4 evidence-adequacy verdict is: alternatives X1 and X3 of the plan (§3.5) change only which crops exist, and X2 would add a lease entry kind by its own §10 amendment; the aggregate, facts and completion below are unchanged by any of them.

11. **Plates get their own analysis aggregate; only identical primitives are shared (§9; plan B1).** `PlateAnalysis` is one unit per `(ProcessingRun, plate identity)` with the §9 lease shape, items 1–5 and 7 unchanged in meaning: status `Queued, Running, Completed, Failed, Superseded`; attempts consumed at claim; a fingerprint-fenced `FOR UPDATE SKIP LOCKED` claim; three-phase completion with the item-4 publication window; default derived from the preferred identity (item 5). Its tables (`plate_analyses`, `plate_identity_activations`, `plate_attempt_failures`, `plate_track_outcomes`, `plate_observations`, `plate_readings`, `plate_track_texts`) and its control plane (`mavi-plate-control-v1`, `/api/plates/analyses`, capability only in `X-Mavi-Lease-Capability`, item 2) are separate from the attribute plane's. **Identity** is the canonical JSON `mavi-plate-identity-v1` of: the plate pipeline id and version; the artefact schema version (`mavi-plate-predictions-v1`, so a v2 artefact can never collide, as item 9 requires); the normalisation id and SHA-256 (the SHA-256 of `contracts/test-vectors/plate-normalisation-v1.json`, which holds the rules and conformance vectors frozen by the owner on 2026-10-13, `6e505158…bf935`; a semantic change needs a new id, never an edit of v1); the Track-text summary policy id, version and SHA-256; the ordered `(capabilityId, modelPackId)` pairs for `ocr` and `plate-detector`; and the parameters SHA-256. Its fingerprint is the SHA-256 of those bytes (vector `contracts/test-vectors/plate-identity-v1.json`). The activation keeps the exact parameters and summary-policy bytes, so a unit of an obsolete identity is still validated against its own rules. Shared code is limited to primitives whose semantics are already identical — `CanonicalSha256`, the lease capability service, `IAcceptedEvidenceReader`, and (when the plate endpoints land) the lease-fenced stream and evidence-read handler, generalised by parameter with the attribute integration tests as the unchanged regression guard. The state machine is duplicated, not abstracted. *Trade-off:* structural duplication between two aggregates and two control planes, in exchange for no generic job framework (alternative G) and no change to the qualified attribute plane.
12. **A plate crop is held by reference, never as new image bytes (§2, §6, §13; plan B2).** A `PlateObservation` names its source Observation — whose crop bytes are already sealed and pinned by size and SHA-256 — and the plate box in that decoded crop's pixel space, with the crop's decoded width and height. The box is in the relational row and in the sealed `PlatePredictions` artefact, whose SHA-256 is on the analysis header, so the plate region is a deterministic function of sealed inputs. The UI cuts the region client-side from the existing evidence-content endpoint. No plate-image artefact type, upload protocol or storage quota exists. *Trade-off:* there is no separately downloadable plate image, and every view decodes the full evidence crop; in exchange there is one integrity source, no new upload path and no evidence growth.
13. **Every kept reading is a relational row; the artefact holds every raw output and is bounded by the profile (§13, §14; plan B3).** §13 keeps attributes to Track-level rows. A plate reading is operator-facing final semantics — the operator must see each reading, its confidence and the crop it came from — so plates persist one `plate_observations` row per selected plate and one `plate_readings` row per kept reading, beside Track outcomes and the search-acceleration `plate_track_texts`. The rules: readings are ranked by confidence, descending, with equal confidences ordered by raw text in ascending UTF-16 code-unit order (strict; one order on both sides of the wire, vector `contracts/test-vectors/plate-reading-order-v1.json`); a plate is `Read` when its rank-0 reading reaches the profile's OCR confidence floor, and then exactly the readings at or above the floor are kept as ranks `0..m-1`; otherwise it is `Unreadable` and has no reading rows. A Track text is one distinct normalised rank-0 text of the Track's `Read` plates under the versioned summary policy; it never replaces a reading. **The platform owns normalisation of persisted text:** the completion carries raw text only, and the platform derives `normalised_text`, the outcome and the advisory format class with the same pinned function its search parser uses (`mavi-plate-normalisation-v1`), and refuses a completion whose Track texts disagree with its own derivation. Raw text is at most 32 UTF-16 code units, at most two lines joined by one LF, with no other C0 control character and no DEL; an adapter output outside that is an inference abstention, never truncated. Any other character is kept verbatim, and a reading that the frozen normalisation rejects (for example one containing a noncharacter) stays visible and is never searchable. Because NFKC can expand one code unit into at most four alphanumeric characters (enumerated by test), a normalised text is at most 128 characters. **Bound (owner decision 2026-10-13):** the 64 MiB artefact cap and the 10,000-Track run bound stay, and v1 has a bounded processing profile: the plate detector is configured to emit at most two proposals per evidence crop, at most one plate per crop is accepted, and the recogniser emits at most three candidate readings for it. These limits are explicit contract constants; a profile's own values (within them) are parameters and therefore identity. A model that emits more than its configured bound violates the contract and the attempt fails (`plate_output_invalid`); output is never truncated after inference, and everything emitted inside the bounds is retained. `PlatePredictions` is canonical JSON as in item 6, recording every leased crop exactly once, every detector proposal with its score and every reading of the accepted plate; Track texts reference their best plate rather than repeating text. A profile is refused — by the platform's release parser and the worker's loader alike — unless it lies inside the v1 limits, whose worst-case artefact and completion body at 10,000 Tracks × 4 crops fit the 64 MiB cap (vector `contracts/test-vectors/plate-artifact-bound-v1.json`). Per-character scores and plate polygons are not recorded in v1. **Consequences made explicit at acceptance (owner, 2026-10-13):** the bounded `PlatePredictions` profile retains no per-character OCR confidence or score, so Stage-4 semantics are **reading-level, not character-confidence-level** — a reading's `confidence` is the recogniser's confidence in the whole reading. No API, UI or qualification claim may imply that character-level confidence exists, and no historical artefact may ever be reinterpreted as if such scores had been stored. If PR-2, PR-6 or a later capability needs per-character confidence, that requires a **new versioned artefact and pipeline contract** with the corresponding requalification — never an in-place extension of existing artefacts. *Trade-off:* more rows than attributes, a second plate in one crop is never read, and a fourth OCR alternative is never seen; widening any limit is a new contract version with its own measured bound. In exchange every reading is attributable, the sealed record is complete, and the search text has a single authority.
14. **Every evidence role is read, and its role is recorded (§4, §7; plan B4).** Unlike attributes (item 9), the plate pipeline does not abstain on the Representative: a reading carries its own detector and OCR confidence, and a fallback Representative is evidence of what the camera saw, not of a colour. Its role is stored with every plate observation's source Observation and is never read as "qualified". If the Stage-4 measurement shows Representative readings harm Track-level precision, the identity-bearing parameter `excludedRoles` removes the role; that is a parameter change, not an architecture change. *Trade-off:* a fallback Representative may contribute low-confidence or conflicting readings, which stay visible as candidates and are measured per role.
15. **Abstention, unavailability and the meaning of "no plate" are explicit (§12; plan §2.5, §2.7).** Each leased crop is exactly one of `scored`, `abstained` (`decode_failed`, `detector_error`, `ocr_error`, `ocr_output_invalid`), `excluded` (its role is in `excludedRoles`) or `unavailable` (`evidence_missing`, `evidence_integrity_failed`, item 3 unchanged). The worker's `unavailable` crops are claims the platform confirms before anything is sealed: it checks each claimed accepted object at rest (missing, wrong size or wrong SHA-256), bounded by the claimed crops; a claim the object at rest contradicts refuses the completion (`plate_evidence_claim_contradicted`, a retryable attempt failure, so the next attempt re-reads the crop). Completion integrity incidents are counted once per crop when a completion is published, when it is replayed, and when its commit outcome is unknown (which may later prove to have rolled back). That count is a best-effort, in-process operator signal; the authoritative record is the published Track outcomes' reasons. A Track is `Analysed` only when at least one of its crops was scored; `Analysed` with no plate observation means "no plate was found in the scored evidence", never "the vehicle has no plate". A Track with no scored crop is `Unavailable` with the most severe of its crops' reasons (`evidence_integrity_failed`, `evidence_missing`, `evidence_decode_failed`, `plate_inference_failed`), or `no_accepted_evidence` when it had no crop the profile reads, so an inference fault is never published as a negative fact. Run readiness has the §12 states, with `NotApplicable` for a run without Vehicle Tracks. The Development fixture inferencer runs under the Development binding mechanism and is refused in Production; real components bind their own `plates-<engine>-v1` Runtime Pack family (item 10). *Trade-off:* a crop that fails inference costs its Track coverage instead of being guessed around, and that cost is visible as `Unavailable` rather than as a missing plate. **Recorded exception (owner decision, 2026-10-13; a trade-off, not qualification evidence):** an OCR-output-fault abstention (`ocr_output_invalid`, including a duplicate or otherwise non-strict reading sequence) keeps the crop's detector proposals, their scores and the reason code, but **not** that crop's readings, because the v1 abstained-crop shape has no slot for them. This is the same as the existing malformed-reading path and an explicit exception to item 13's "everything emitted inside the bounds is retained"; retaining rejected readings would require a new `PlatePredictions` artefact version.

## Implementation amendment 2026-10-13 (Stage 4 plate search, PR-4)

**Status: Proposed in Stage 4 PR-4** (`docs/superpowers/plans/2026-10-12-stage4-anpr-ocr.md` §2.8, §5.4, §5.5, §9.1 B5–B6). These are the search-side decisions the PR-3 amendment above deferred to PR-4 and to §16. It changes no decision above, no PR-3 lifecycle semantics and claims no qualification. Every confidence the search and Track-detail contracts expose (`maxConfidence`, a reading's `confidence`) is reading-level, as item 13 fixes — none implies per-character confidence; and the detail's plate observations are the selected plates of scored crops only, so an abstained crop (including item 15's OCR-output-fault exception) has no entry and no reading there.

16. **Plate matching is literal on normalised text, ordered by time (plan B5, B6).** `plateText` is normalised by the frozen `mavi-plate-normalisation-v1` — the function the platform applies to persisted readings — and must yield 3–15 `[A-Z0-9]` characters; `plateMatch` is `contains` (default), `prefix` or `exact`. A Track matches when a fact-bearing plate analysis of its run, of the pinned identity and published inside the snapshot, has a `plate_track_texts` row for it whose text matches; there is no confusable expansion and no edit distance. The predicate implies `objectClass=Vehicle` and is ANDed with every other predicate; with analytic predicates the single-camera analytics scope stays authoritative, while plate-only searches span cameras. Ordering stays `StartTimestampUtc DESC, Id DESC`. *Trade-off:* an O/0-type OCR error is missed rather than guessed (its recall cost is measured by the Stage-4 benchmark); the strongest matches are not first, in exchange for a stable snapshot cursor, and every row explains its match.
17. **The v4 cursor carries capability-tagged derived pins (§16).** v4 is the v3 envelope (HMAC-SHA-256 under the cursor signing key, verified before parsing) around: the keyset and snapshot; a list of derived-predicate pins, each a capability tag, a 64-hex identity fingerprint and that capability's coverage counts — today exactly one, `plates`, with its six counts; and, only when analytic predicates are combined, the analytics identity and coverage a v3 cursor carries. A continuation evaluates against the pinned plate identity and never re-resolves the release, so neither a superseding analysis nor a binding change mid-pagination can change what an open result set means. The tag lets visual-attribute search join the list without a v5; a v4 decoder refuses an unknown tag. The worst-case encoded length is contract-tested against a 1 024-character bound. Unlike v2 and v3, the filter fingerprint inside v4 is **keyed**: a plate text is a potentially identifying cue from a space small enough (3–15 of 36 symbols) that an unkeyed digest in a readable cursor could be reversed offline. The configured key material serves the two purposes through domain-separated derived keys, HMAC-SHA-256(key, `mavi-track-cursor-v4/mac`) for the envelope and HMAC-SHA-256(key, `mavi-track-cursor-v4/filter-fingerprint`) for the fingerprint, so neither purpose's output can stand in for the other's. *Trade-off:* none beyond v3's — a key rotation already invalidates every open signed cursor; introducing the derivation invalidated v4 cursors minted before it, which are short-lived navigation tokens.
18. **Plate coverage counts Vehicle Tracks by their run's readiness at the snapshot.** `plateCoverage` is computed on the first page over the base candidate scope (every ordinary filter and the latest-run scope, before the plate and analytic predicates) and pinned in the cursor. Each run is classified once by PR-3's readiness rule, with analyses published after the snapshot treated as still running, and its Vehicle Tracks are counted into `ready`, `pending`, `failed`, `stale` or `notConfigured`; the buckets partition `vehicleTracksInScope`. It is present on every plate search, so an empty page is never read as "no such plate". *Trade-off:* a Track of a Ready run whose own outcome is `Unavailable` counts as ready (its run was analysed; the Track's own state is on the detail), and a unit that failed after the snapshot is reported failed rather than pending — the imprecision the analytic coverage already accepts.
19. **Indexes and `pg_trgm` (plan §2.8).** Migration `AddPlateSearchIndexes` adds a GIN `gin_trgm_ops` index (contains) and a `text_pattern_ops` b-tree (prefix and exact) on `plate_track_texts.normalised_text`, in their own configuration so PR-3's schema is untouched. `pg_trgm` is PostgreSQL contrib, already inside the MAVI PostgreSQL runtime pack; staging, Setup, startup and `Test-MaviEnvironment` now verify it. The predicate itself uses no `pg_trgm` operator, so without the index a contains search is still exact, only slower. A page is page-bounded where it can be (cold review P1-1). The search walks the scope in page order in batches, checks each batch's Track ids against the predicate by key, and switches to a scope-restricted sparse read of the text index (capped) when the first batch holds no match. Coverage counts are authoritative: immutable per-run Vehicle Track counts, cached by count only, and a header mismatch is reported (event 1423). **Budget: not met.** On the frozen skewed corpus and query set (`mavi-plate-search-skewed-v1`, `mavi-plate-search-queries-v1`, Development host, 10^6 Tracks), p95 ≤ 300 ms holds for selective, digit, exact and no-match texts, run-scoped pages, pages 2 and 5, and NotConfigured or no-run-Ready searches (≤ 63 ms). It is missed by broad state-code texts installation-wide (`KA0` 498 ms, prefix `KA0` 374 ms, `KA01` 989 ms, prefix `KA01` 842 ms), by a one-day window (1 270 ms), and by a text dense only in old data (≈ 63 s, the walk's declared worst case). The mechanisms and the options are recorded for an owner decision; nothing was tuned after measuring. *Trade-off:* every plate completion maintains two more indexes (≈ +0.5 s at the 10 000-Track worst shape, still ≤ 9.3 s against 15 s), and the walk's worst case grows with the scope. Evidence: `docs/qualification/stage4/2026-10-13-plate-search-at-scale.md`.
20. **No query value is logged; request telemetry is sanitised, not removed (plan §5.5; owner decisions 2026-10-13).** The claim is exactly this: MAVI's server and application logging does not persist a sensitive URL or query value — plate text, cursor values or any other query or filter value — not even hashed, since a hash of a 3–15 character plate text is reversible by enumeration. It is **not** a claim that plate text never appears in a URL: the search is a GET whose query string carries it, and the operator UI keeps search state in the URL (UI spec §17), so it can be in the browser's address bar and history. As defence in depth, every response — the API's and the SPA's — carries `Referrer-Policy: no-referrer`, so a browser does not send a plate-bearing URL onward as the `Referer` of later requests. Three request-logging surfaces can write a raw request target, and each is closed: (a) ASP.NET Core's request start/finish lines (`Microsoft.AspNetCore.Hosting.Diagnostics`) and (b) Kestrel's bad-request diagnostics (`Microsoft.AspNetCore.Server.Kestrel.BadRequests`, which log a malformed request's target at `Debug`) are suppressed below `Warning` in code; (c) the IIS W3C request log of the in-process IIS host, whose default fields include `cs-uri-query` and `cs(Referer)` — and once the UI navigates with plate filters, the Referer of later requests carries them too — is configured by MAVI Setup with a fixed field set without the query, the Referer and cookies, and `Test-MaviEnvironment` fails when they are logged, including under server-wide central or binary logging, which Setup does not change. The platform emits its own request events instead (`request_starting` 1430, `request_finished` 1431) carrying exactly: the HTTP method, the matched **route template** (never the path, which may carry identifiers), the status code, the elapsed time and the trace id. A Track search adds only `plateFilterPresent` (`true`/`false`) and `plateMatch` when it is one of `contains`/`prefix`/`exact`; any other value a caller sent is recorded as `none`. The plate search's own event (1421) adds the match mode and counts. *Trade-off:* the request line no longer shows which resource or filter was asked for — an operator correlating a slow request with its query uses the trace id with the client, not the log; IIS logs lose the query and Referer for every MAVI request, not only plate searches; a provider-specific logging rule naming an exact framework category could still re-enable the raw lines, which no shipped configuration does; and an operator who re-enables IIS query logging by hand is caught by `Test-MaviEnvironment`, not prevented. A POST search would keep plate text out of URLs altogether but is a contract change for the owner, not taken here.
