# Stage 2 Visual Attributes — Architecture Review Resolution

**Date:** 2026-09-23  
**Review basis:** independent PR #73 architecture review received after the initial planning draft  
**Scope:** architecture/documentation only; no Stage-2 feature implementation

## Verdict

All P1 and P2 findings from the independent review are resolved in the architecture-freeze candidate documents.

No implementation is authorised merely by this resolution record. The governing acceptance register remains authoritative.

## Finding disposition

| Finding | Priority | Disposition |
|---|---:|---|
| F-01 Multi-model packaging/qualification did not exist | P1 | **Resolved.** ADR-014 defines capability-binding v2, capability-neutral Model Pack manifest v2, Runtime Pack/model separation, capability-scoped qualification, pack provenance and deliberate detector qualification reconciliation. |
| F-02 Evidence Set belongs in VisionJob and old bounds did not close | P1 | **Resolved.** ADR-013 makes selection VisionJob output, completion schema/digest v3, in-loop JPEG staging, four bounded roles and a run-level EvidenceCrop quota with 10,000-Track arithmetic. Task-10/E2E rebinding is explicit. |
| F-03 No evidence-read path for Python inferencer | P1 | **Resolved.** ADR-013 requires platform-served, lease-scoped evidence reads with size/SHA verification; direct Python evidence-root access is prohibited. |
| F-04 SceneAnalytics control-plane pattern did not transfer directly | P2 | **Resolved.** Capability-specific VisualAttributeAnalysis + Python HTTP lease/heartbeat/complete/fail; shared fencing/hash/claim primitives; generic transport envelope only. |
| F-05 Crop-level predictions needed a non-relational home | P2 | **Resolved.** Bounded sealed AttributePredictions artefact; relational rows hold final Track-level semantics. |
| F-06 Unknown could not be represented as missing row | P2 | **Resolved.** Every applicable completed Track/attribute has exactly one Observed or Unknown row; Track-level Unavailable is separate; UI spec gains explicit Unknown. |
| F-07 v3 cursor is camera-bound | P2 | **Resolved.** v4 HMAC cursor pins attribute identity/coverage; attribute-only queries may be multi-camera; combined analytics queries pin both identities and retain analytics camera scope. |
| F-08 Evidence reselection implies new ProcessingRun/Tracks | P2 | **Resolved.** ADR-013 and parent plan explicitly state this for trajectory v1. |
| F-09 Co-hosting weakened failure isolation | P2 | **Resolved.** Default is a second process/failure domain from the same Runtime Pack; future separate executable/node remains contract-compatible. |
| F-10 Evidence crops/slots must serve later stages | P2 | **Resolved.** Representative/NearView/EarlyDiverse/LateDiverse roles, 1024px long-edge ceiling, deterministic temporal/occlusion diversity and model-neutral scoring. |
| F-11 VisualAttribute schema defects | P2 | **Resolved.** Analysis header, Restrict evidence FK, schema-coded type/value, unique final row, measured search index; per-row model identity removed as authority. |
| F-12 Pack identities absent from provenance | P2 | **Resolved.** ADR-013/014 require capabilityId/modelPackId/runtimePackId plus hashes/variant/device/build in provenance/digest. |
| F-13 Qualification protocol gaps | P2 | **Resolved.** Qualification plan now includes annotation agreement, validation/frozen-test split, minimum support, held-camera generalisation, aggregation/abstention, non-subject crops, licensing, retrieval metrics, version skew and requalification triggers. |
| F-14 UI conflicts with adopted specification | P2 | **Resolved.** UI spec amended for Unknown, Evidence Set viewer, observations[], filter/presentation rules; one-badge-per-row remains authoritative. |
| F-15 Documentation coherence | P2 | **Resolved.** Acceptance register is the sole numbered exit gate; roadmaps restored Task-10/E2E implications; memory-design §15 is explicitly historical/superseded for Stage-2 evidence selection. |
| F-16 Unused TrackStart/BestQuality/TrackEnd promise | P3 | **Resolved as architecture rule.** Legacy roles must map deliberately to ADR-013 roles or be retired; no second selector is allowed. |
| F-17 Duplicate fencing/SHA implementations | P3 | **Resolved as implementation requirement.** S2b extracts shared primitives before a third control plane is added. |
| F-18 Retention repeatedly deferred | P3 | **Resolved as accepted cost with trigger.** Dedicated retention policy required before Production Stage-2 release or configured storage-growth trigger, whichever comes first. |
| F-19 Privacy impact of additional person crops | P3 | **Resolved.** Existing evidence authorisation applies; no face-oriented selector; no Python root access; additional crops are treated as accepted evidence. |
| F-20 Dead EmbeddingExtractor protocol | P3 | **Recorded cleanup requirement.** S2b must not adopt it as a generic inferencer abstraction. It is either removed as dead code or explicitly retained/documented as Stage-5-only groundwork before S2b closes. |

## Cold-review checks after revision

The revised pack was checked for the following contradiction classes:

- attribute execution described as part of VisionJob completion — **not present**;
- Evidence Set described as a downstream/post-persistence generator — **not present**;
- direct Python accepted-evidence filesystem access — **prohibited consistently**;
- default detector/attribute co-hosting in one process — **not present**;
- one singular detector-oriented component binding presented as Stage-2 target — **superseded by ADR-014**;
- Unknown represented as null/missing analysis row — **not present**;
- second numbered Stage-2 exit gate diverging from the acceptance register — **removed**;
- UI result-row badge/chip expansion conflicting with §16 — **removed/amended**;
- legacy Phase-1 keyframe policy presented as an independent Stage-2 selector — **explicitly superseded**;
- Development CUDA evidence presented as Production qualification — **not present**.

## Remaining legitimate freeze-time items

These are not unresolved architecture defects:

1. exact person/vehicle checkpoint selection;
2. final label vocabulary values that depend on annotation consistency;
3. numeric operational accuracy/support thresholds chosen from validation data before frozen-test scoring;
4. final long-term retention duration, subject to the mandatory trigger;
5. whether later Stage-4/5 roles remain in the same Runtime Pack or split physically.

Their **decision method and boundary are frozen** even though the eventual values are not yet known.

## Second independent pass (2026-09-23, post-freeze)

A second cold review of the accepted documentation head, checked against the codebase, found gaps that the first cold pass had not. Each was amended in place in the governing documents; none required a change of direction.

| ID | Priority | Finding | Evidence | Amendment |
|---|---:|---|---|---|
| R-01 | P1 | ADR-014 §1 bound one top-level `runtimePackId` and dropped the platform-variant dimension. The Stage-4 OCR engine is a native runtime with its own lock (capability roadmap prerequisite matrix), so the shape would have needed a v3 immediately, contradicting its own acceptance gate. | `src/vision/config/components/mmdetection-phase1-v1.json` keys `runtimePacks` by variant; roadmap §4 row 4 | ADR-014 §1: `runtimePacks[]` families keyed by variant, declared `roles[]`, bindings name a role and a qualification record. Plan §9. |
| R-02 | P1 | The `AttributePredictions` artefact had no delivery path. Every existing artefact reaches sealing through worker-writable staging (`artifact_store.py`), so the attribute worker would have needed a platform filesystem, contradicting "later GPU-node extraction is real". | `ProcessingResultStore.cs` seals from `staging/…`; ADR-006 §1 | ADR-013 §10: lease-scoped, size-capped upload endpoint; the attribute role has no filesystem dependency on the platform host. Plan §10.1/§11; register D4. |
| R-03 | P2 | Memory/staging behaviour unspecified. The current loop retains one raw crop per Track for the whole run and finalises after decoding (`process_video.py` `_TrackAccumulator`, L95–226); four encoded crops retained the same way would be ≈5.2 GiB at 10,000 Tracks. | `process_video.py` L46–55, L204–226 | ADR-013 §5: stage on selection, descriptors only; memory bounded by live Tracks; transient staging bound stated. Register B2. |
| R-04 | P2 | Admission by `LocalTrackNumber` biased supplemental evidence to the earliest Tracks in dense runs; worst-case coverage (≈2,550 of 30,000 supplemental crops, ≈8.5 % of Tracks) was not stated. | ADR-013 §6 arithmetic | ADR-013 §6 and plan §8.3: score-ordered admission within a round; worst case stated as a degradation bound; v2 512 MiB becomes the trajectory quota. |
| R-05 | P2 | The 64 KiB Representative cap implies a ≈600–700 px effective ceiling at quality 85; no reduction floor existed, so a cap could be met by degrading a crop to noise. | JPEG bits-per-pixel at q85 | ADR-013 §5: Representative is display-grade, NearView is the analytic carrier; floors of 128 px / quality 50; fallback rule. |
| R-06 | P2 | Roles were named but not defined; "deterministic" was a promise without a method (qualified candidate, near-duplicate, separation, temporal thirds). | ADR-013 §4 | ADR-013 §4 and plan §8.2: method frozen, numeric floors set in S1 and recorded in the pipeline profile. |
| R-07 | P2 | Completion body bound not re-derived for four descriptors per Track. | `WorkerContractRules.cs` L9 (32 MiB) | ADR-013 §6: ≈+7.5 MiB at bound; `MaximumCompletionRequestBodyBytes` re-derived and contract-tested. Register B3. |
| R-08 | P2 | Attribute lease semantics unspecified between the two existing shapes (VisionJob: expiry invalidates; SceneAnalysis: expiry reclaimable with grace, no heartbeat); no unit-duration rule; no statement on automatic backfill after a binding change. | `VisionJob.RequireValidLease`; `SceneAnalysis.OwnedBy` | ADR-013 §9: VisionJob-style expiry with heartbeat; whole-unit failure on max duration; identity resolved at queue time; no automatic backfill. Plan §10.2. |
| R-09 | P2 | Evidence-read endpoint lacked its authorisation, bounding, audit and token-handling rules. | ADR-013 §10 | ADR-013 §10: header-only capability, Running/attempt/expiry checks, run-scoped Observation set, `SizeBytes` bound, no listing, per-read audit log. |
| R-10 | P2 | ADR-014 §4/§5 placed roles, entry points and device policy inside the Runtime Pack, contrary to ADR-007 (no first-party material in the pack). | ADR-007 L20 | ADR-014 §4/§5: roles live in the application overlay; device policy in the deployment profile. |
| R-11 | P2 | Two CUDA processes on the 4 GiB Development GPU were not addressed. | `2026-09-18-windows-cuda-c1-compatibility-decision.md`, *4 GB VRAM operating constraint* | ADR-013 §8: per-role device policy in the profile; co-resident VRAM measured in qualification §10; silent fallback prohibited. |
| R-12 | P2 | v4 cursor pinned the full analysis identity; several SHAs would exceed the v3 length envelope and per-run analysis ids are not one value. | `TrackCursorCodec.cs` L41 (768) | ADR-013 §16: pin a 64-hex capability identity fingerprint; full tuple in the coverage block; per-run resolution by fingerprint. Register A9. |
| R-13 | P2 | Qualification allowed a third-party checkpoint to be scored on a public benchmark it may have trained on; no annotator independence; §5 required S0 to record support numbers that §24 of the plan defers. | qualification §3.1, §4, §5 | Qualification §3.1 disjointness rule; §4 independent, blind annotator; §5 recorded in S5 before frozen-test scoring. |
| R-14 | P2 | Run readiness lacked `NotConfigured`; "attributes not deployed" would read as `NotApplicable`. | ADR-013 §12 | ADR-013 §12 and plan §13: `NotConfigured` distinct from `NotApplicable`. Register E2. |
| R-15 | P3 | Plan §3 rule 2 still said a component "may initially run in the existing Python process", contradicting ADR-013 §8. | plan §3 | Plan §3 corrected. |
| R-16 | P3 | Implementation roadmap said four Observation types "exist" and Stage 5 said best-quality crops are "present"; risk row said "one Model Pack per stage". | roadmap L15, L161, L279 | Corrected to repository reality and ADR-014. |
| R-17 | P3 | Memory-design §7.8, the component-lifecycle runbook and the runtime-pack design spec presented single-model / per-row-model shapes without a supersession note. | those documents | Supersession notes added; historical text retained. |
| R-18 | P3 | Confidence semantics and multi-valued attributes unstated; prediction-artefact format/caps unstated. | ADR-013 §12–13 | ADR-013 §12–13: aggregation-policy score, one value per attribute, `multicolour` via schema; artefact versioned, ≤64 MiB, existing-dependency encoding. |
| R-19 | P3 | No repository-wide precedence rule for conflicting current documents. | `docs/architecture/README.md` | README: six-level precedence order and the Stage-2 governing set. |
| R-20 | P3 | UI spec did not say how a matched attribute value may appear on a result row. | spec §16/§29 | Spec §29: plain secondary text only, never a badge/chip. |

**Verified unchanged from the first pass:** trajectory v1 = `[offset_ms, cx, cy]` (`video/trajectory.py` L16–25); single decode pass (`process_video.py` L110); one Representative persisted (`ProcessingResultStore.cs` L226–239); `VisualAttribute` unreferenced outside schema; evidence reads .NET-only (`AcceptedEvidenceReader`); component manifest singular `modelPack`; provenance without pack ids (`provenance.py` L158–188); v3 cursor camera-bound (`TrackCursorCodec.cs` L374–384).

## Architecture decision

The first cold consistency pass reported no open P1/P2; the second pass above shows that report was premature and records what it missed. After the amendments listed above, no open P1/P2 architecture finding remains in the governing documents. ADR-013 and ADR-014 remain Accepted on the amended text, and acceptance-register items A1–A12 are PASS on the amended documentation head.

Feature implementation is intentionally not part of this PR.
