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

## Architecture decision

The revised documentation is suitable to proceed to the formal architecture-freeze gate.

Feature implementation remains blocked until ADR-013 and ADR-014 status are formally accepted and acceptance-register architecture items A1–A12 are marked PASS against the final reviewed head.
