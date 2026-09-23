# Visual Attributes — Stage-2 Acceptance Register

**Status:** Open — architecture-first acceptance register  
**Date opened:** 2026-09-23  
**Baseline:** `main@ca23adf55b0b4a14faf58e12d048a3c90221557c`

This register is authoritative for Stage-2 exit criteria. Other plans must reference this table rather than maintain a second independently numbered acceptance list.

Nothing unexecuted is marked PASS.

## Current verdict

**ARCHITECTURE FROZEN — IMPLEMENTATION NOT STARTED.**

The documentation/architecture gate is closed on the reviewed PR head. Feature implementation remains a separate follow-on activity and has not started.

## Governing documents

- `docs/decisions/ADR-013-modular-post-track-intelligence-and-evidence.md`
- `docs/decisions/ADR-014-capability-binding-v2.md`
- `docs/qualification/2026-09-23-visual-attributes-qualification-plan.md`
- `docs/architecture/ui-ux-design-specification.md`
- `docs/superpowers/plans/2026-09-23-visual-attributes.md`
- `docs/superpowers/plans/capability-roadmap.md`
- `docs/superpowers/plans/capability-implementation-roadmap.md`
- ADR-005 / ADR-006 / ADR-007 / ADR-009 / ADR-011 / ADR-012
- dependency/offline-packaging policy

## A. Architecture-freeze gate

| ID | Requirement | Status |
|---|---|---|
| A1 | ADR-013 resolves evidence generation, attribute lifecycle, worker topology, evidence-read boundary, persistence semantics, search identity and retention/privacy costs | PASS |
| A2 | ADR-014 resolves capability-binding v2, capability-neutral Model Pack shape, runtime/model separation and capability-scoped qualification | PASS |
| A3 | Track Evidence Set roles, deterministic tie rule, in-loop encoding and run/Track bounds are explicit | PASS |
| A4 | VisionJob completion schema v3 / digest v3 and Task-10/E2E requalification consequences are explicit | PASS |
| A5 | Evidence-policy upgrade semantics explicitly require a new ProcessingRun/new Track identities with trajectory v1 | PASS |
| A6 | Accepted-evidence reads are platform-served, lease-scoped and hash-verified; Python direct evidence-root access remains prohibited | PASS |
| A7 | VisualAttributeAnalysis lifecycle/control-plane semantics are frozen, including heartbeat/fencing/retry/supersession | PASS |
| A8 | Observed / Unknown / Unavailable / Pending / Failed / Absent semantics are non-overlapping and reflected in persistence/API/UI plans | PASS |
| A9 | v4 attribute-search cursor identity (capability identity fingerprint, not the full tuple) and combined analytics+attribute semantics are frozen | PASS |
| A10 | UI/UX specification is amended for Unknown, Evidence Set review and row-density rules | PASS |
| A11 | Qualification protocol covers annotation agreement, data splits, support, generalisation, aggregation, abstention, licensing, retrieval and requalification triggers | PASS |
| A12 | Final independent cold architecture review reports no open P1/P2; ADR-013/014 can move to Accepted | PASS — the second independent cold pass (2026-09-23) found and amended further P1/P2 gaps in place (see review resolution, *Second independent pass*); PASS is on the amended head |

**Implementation gate:** satisfied for architecture. S1/S2 implementation may begin only in a follow-on implementation change; this documentation PR contains no Stage-2 feature code.

## B. Evidence-set / raw-processing acceptance

| ID | Requirement | Status |
|---|---|---|
| B1 | Deterministic four-role candidate selector implemented with documented tie-breaking | OPEN |
| B2 | JPEG encoding occurs in-loop; candidates are staged on selection and the accumulator holds descriptors only, so memory is bounded by live Tracks | OPEN |
| B3 | Representative and supplemental byte caps, reduction floors, score-ordered admission and the 1 GiB run EvidenceCrop quota are enforced; body bound re-derived; all contract-tested at the 10,000-Track bound | OPEN |
| B4 | Vision completion schema v3, digest v3, validator/store/sealing and Observation evolution pass contract tests | OPEN |
| B5 | `TrackDetail.observations[]` and evidence viewer expose accepted roles without breaking Representative behaviour | OPEN |
| B6 | Relevant Task-10 CPU matrices are rerun; CUDA/E2E evidence is rebound when produced; no stale qualification claim remains | OPEN |

## C. Component-binding v2 acceptance

| ID | Requirement | Status |
|---|---|---|
| C1 | `capabilityBindings[]` schema supports detector + future capability ids without Stage-2-only structural fields | OPEN |
| C2 | Model-manifest v2 common schema is capability-neutral; detector-specific config is optional/capability-specific | OPEN |
| C3 | Runtime profile is decoupled from a privileged model checkpoint and supports independently startable roles | OPEN |
| C4 | Capability-scoped qualification-record shape and common/capability-specific gates are implemented | OPEN |
| C5 | modelPackId/runtimePackId/capabilityId are persisted in provenance/digests | OPEN |
| C6 | verify_repo, offline packaging and CI fail closed on binding/manifest/runtime mismatch | OPEN |
| C7 | Existing detector qualification hashes/records affected by profile v2 are deliberately reconciled and behaviour-regression tests pass | OPEN |

## D. Attribute lifecycle and evidence-read acceptance

| ID | Requirement | Status |
|---|---|---|
| D1 | VisualAttributeAnalysis unit/lifecycle is independent of ProcessingRun success | OPEN |
| D2 | Shared fencing/hash/claim primitives are extracted where semantics match; no third copy-and-diverge implementation | OPEN |
| D3 | Python-facing lease/heartbeat/complete/fail endpoints and generic transport envelope are contract-tested | OPEN |
| D4 | Lease-scoped evidence read and prediction-upload endpoints authorise only the leased unit's Observations/artefact; worker verifies SHA/size before decode; the attribute role touches no platform filesystem | OPEN |
| D5 | Attribute worker runs as an independent process/role with independent READY/device/provenance/failure domain | OPEN |
| D6 | Model unavailable at startup leaves work Queued without consuming attempts | OPEN |
| D7 | Stale attempts, reclaim, retry, cancellation, malformed output and failure isolation pass | OPEN |
| D8 | Prediction-level outputs are sealed as bounded `AttributePredictions`; final relational rows remain Track-level only | OPEN |

## E. Persistence/search semantics acceptance

| ID | Requirement | Status |
|---|---|---|
| E1 | Analysis/outcome/attribute relational constraints match ADR-013, including Restrict evidence linkage and unique final outcome | OPEN |
| E2 | Every applicable completed Track/attribute has exactly one `Observed` or `Unknown` row; missing row is not Unknown; run readiness distinguishes NotConfigured from NotApplicable | OPEN |
| E3 | Track-level `Unavailable` is explicit with reason and never masquerades as Unknown/Absent | OPEN |
| E4 | Supersession occurs only on successful completion; historical analysis remains readable | OPEN |
| E5 | v4 HMAC cursor pins resolved attribute identity/coverage and rejects tampering | OPEN |
| E6 | Repeated attribute predicates are canonical in URL, fingerprint and cache key | OPEN |
| E7 | Attribute-only search supports multi-camera scope; combined analytics predicates retain analytics camera scope and pin both identities | OPEN |
| E8 | PostgreSQL plan/query-count/p50/p95 evidence passes at realistic and worst-supported fact volume with no N+1 evidence I/O | OPEN |

## F. Model/qualification acceptance

| ID | Requirement | Status |
|---|---|---|
| F1 | Annotation guide, double-label agreement/adjudication and corpus partition manifests are frozen before final evaluation | OPEN |
| F2 | Minimum class/value support table and operational gates are frozen from validation/tuning evidence before frozen-test scoring | OPEN |
| F3 | Person/vehicle Model Packs have complete licence, integrity, offline and provenance records | OPEN |
| F4 | Crop-level, Representative-only and aggregated Track-level metrics are reported with abstention/Unknown rates | OPEN |
| F5 | Held-camera/unseen-camera generalisation meets declared gates or limitations disable affected exposure | OPEN |
| F6 | Non-subject/error crops demonstrate safe abstention behaviour | OPEN |
| F7 | Operator-facing predicate retrieval precision-at-N/coverage evidence meets declared gates | OPEN |
| F8 | CPU Development qualification passes; CUDA Development evidence is recorded where applicable without Production claim | OPEN |
| F9 | Runtime/model version-skew, OOM/failure recovery and shared-host process isolation pass | OPEN |
| F10 | Requalification-trigger matrix is exercised/documented for the final Stage-2 identity | OPEN |

## G. Operator/offline/security acceptance

| ID | Requirement | Status |
|---|---|---|
| G1 | Search → Investigation → supporting Evidence Set → source Review works on real video | OPEN |
| G2 | Unknown/Unavailable/coverage/provenance presentation matches the amended UI spec and accessibility requirements | OPEN |
| G3 | Offline Binary Kit installs/verifies both roles and all bound packs with network disconnected | OPEN |
| G4 | Disconnected end-to-end attribute analysis uses lease-scoped evidence read and performs no remote resolution | OPEN |
| G5 | Security/privacy review has no open P1/P2; no face-oriented selector or direct Python evidence-root access exists | OPEN |
| G6 | Relevant suites and exact-head CI are green | OPEN |
| G7 | Documentation is reconciled to measured reality; no planned claim is presented as executed evidence | OPEN |
| G8 | Final independent Stage-2 cold review has no open P1/P2/material review thread | OPEN |
| G9 | Post-merge critical verification on `main` is green | OPEN |

## Evidence log

For every PASS entry retain:
- exact commit SHA;
- environment/runtime/model/capability identities;
- corpus/protocol version where applicable;
- command/workflow/run number;
- result;
- retained artefact/report hash where applicable;
- limitation/non-claim;
- reviewer/date.

A section may be partially green while Stage 2 remains open. Overall Stage 2 is complete only when every applicable requirement in this authoritative register is PASS.
