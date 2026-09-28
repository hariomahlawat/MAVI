# Visual Attributes — Stage-2 Acceptance Register

**Status:** Open — S2a closed; S2b planning  
**Date opened:** 2026-09-23  
**Reconciled:** 2026-09-28  
**Current implementation baseline:** `main@406172657599350ecbb27819865ecc9482c6c97d`

This register is authoritative for Stage-2 exit criteria. Other plans reference this table rather than maintain a second independently numbered acceptance list.

Nothing unexecuted is marked PASS.

## Current verdict

**ARCHITECTURE FROZEN — S2a COMPONENT BINDING v2 CLOSED; S2b ATTRIBUTE LIFECYCLE NEXT.**

S1 implementation is merged; B1–B6 remain OPEN wherever the retained S1.4 qualification/evidence requirement has not yet been entered as executed evidence in this register. S2a.1–S2a.4 are merged through PR #112 at `main@406172657599350ecbb27819865ecc9482c6c97d`. C1–C7 are reconciled below from retained S2a implementation and exact-head verification evidence. S2b remains unimplemented; D/E rows remain OPEN until executed evidence exists.

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
| A9 | v4 attribute-search cursor identity and combined analytics+attribute semantics are frozen | PASS |
| A10 | UI/UX specification is amended for Unknown, Evidence Set review and row-density rules | PASS |
| A11 | Qualification protocol covers annotation agreement, data splits, support, generalisation, aggregation, abstention, licensing, retrieval and requalification triggers | PASS |
| A12 | Final independent cold architecture review reports no open P1/P2; ADR-013/014 can move to Accepted | PASS |

## B. Evidence-set / raw-processing acceptance

| ID | Requirement | Status |
|---|---|---|
| B1 | Deterministic four-role candidate selector implemented with documented tie-breaking | OPEN — implementation merged; retained S1.4 evidence entry still required |
| B2 | JPEG encoding occurs in-loop; exact-once retirement/finalisation and live-memory bound are proven | OPEN — implementation merged; retained S1.4 evidence entry still required |
| B3 | Crop/run byte caps and 10,000-Track completion-body bound are enforced | OPEN — implementation merged; retained S1.4 evidence entry still required |
| B4 | Vision completion schema v3/digest v3 and Observation evolution pass contract tests | OPEN — implementation merged; retained S1.4 evidence entry still required |
| B5 | TrackDetail observations and Evidence Set viewer expose accepted roles without breaking Representative behaviour | OPEN — implementation merged; real-video/operator evidence entry still required |
| B6 | Relevant Task-10 CPU matrices are rerun; CUDA/E2E evidence is rebound when produced; no stale qualification claim remains | OPEN |

## C. Component-binding v2 acceptance

| ID | Requirement | Status |
|---|---|---|
| C1 | `capabilityBindings[]` schema supports detector + future capability ids without Stage-2-only structural fields | PASS — S2a merged through PR #110/#112; repository/binding validation retained on the merged baseline |
| C2 | Model-manifest v2 common schema is capability-neutral; detector-specific config is optional/capability-specific | PASS — S2a manifest-v2 cut-over merged and exercised by exact-head repository/model-pack gates |
| C3 | Runtime profile is decoupled from a privileged model checkpoint and the schema supports independently startable roles | PASS — schema/runtime identity decoupling is merged. Limitation: only `vision` is implemented/startable on the S2a baseline; activation of the independent `attributes` role is D5/S2b, not evidence that a second role already exists |
| C4 | Capability-scoped qualification-record shape and common/capability-specific gates are implemented | PASS — capability-scoped qualification shape merged; no Production/CUDA promotion implied |
| C5 | modelPackId/runtimePackId/capabilityId are persisted in provenance/digests where the S2a contracts require them | PASS — completion/provenance validation and persistence merged and covered by exact-head gates |
| C6 | verify_repo, offline packaging and CI fail closed on binding/manifest/runtime mismatch | PASS — PR #112 exact head `911ae9f27fcbc9ebf48431d6fdc9dd9ae2750ad9`: Quality Gate, Task 12, Vision Model Pack and Task 17 green before merge |
| C7 | Existing detector qualification hashes/records affected by profile v2 are deliberately reconciled and behaviour-regression tests pass | PASS — S2a identity freeze/reconciliation retained detector qualification state; RTMDet remained pending/unverified and no Production/CUDA promotion occurred |

### C-section retained evidence record

- implementation chain: PR #110 (S2a.3 cut-over), PR #111 (S2a.4 plan), PR #112 (S2a.4 implementation);
- merged baseline: `406172657599350ecbb27819865ecc9482c6c97d`;
- final PR #112 exact head: `911ae9f27fcbc9ebf48431d6fdc9dd9ae2750ad9`;
- environment: repository CI plus Windows PowerShell 5.1 and PowerShell 7 coverage in Task 17 for Setup contracts;
- workflows/results: MAVI Quality Gate PASS; Task 12 PASS; Vision Model Pack PASS; Task 17 PASS;
- retained implementation evidence: PR #112 records 28/28 deliberate mutations caught and no unresolved P1/P2 at merge;
- limitation/non-claim: C3 does not claim an implemented second role; C1–C7 do not claim RTMDet Production qualification, CUDA qualification, family-wide Production qualification, or any real attribute Model Pack;
- reviewer/date: independent cold review completed before PR #112 merge; register reconciled 2026-09-28.

## D. Attribute lifecycle and evidence-read acceptance

| ID | Requirement | Status |
|---|---|---|
| D1 | VisualAttributeAnalysis unit/lifecycle is independent of ProcessingRun success | OPEN |
| D2 | Shared fencing/hash primitives are extracted only where semantics match; no third copy-and-diverge implementation | OPEN |
| D3 | Python-facing lease/heartbeat/complete/fail endpoints and transport contracts are contract-tested | OPEN |
| D4 | Lease-scoped evidence read and prediction-upload endpoints authorise only the leased unit's Observations/artefact; worker verifies SHA/size before decode; attribute role touches no platform filesystem | OPEN |
| D5 | Attribute worker runs as an independent process/role with independent READY/device/provenance/failure domain | OPEN |
| D6 | Model unavailable at startup leaves work Queued without consuming attempts | OPEN |
| D7 | Stale attempts, reclaim, retry, cancellation semantics, malformed output and failure isolation pass | OPEN |
| D8 | Prediction-level outputs are sealed as bounded `AttributePredictions`; lifecycle publication is atomic and final relational rows remain Track-level only | OPEN |

## E. Persistence/search semantics acceptance

Ownership is split deliberately: **S2b establishes and proves E1–E4 persistence/integrity semantics as part of the lifecycle publication boundary; S3 adds and proves E5–E8 search/cursor/query-plan semantics.** E1–E4 remain OPEN until S2b implementation evidence exists.

| ID | Requirement | Status / owner |
|---|---|---|
| E1 | Analysis/outcome/attribute relational constraints match ADR-013, including Restrict evidence linkage and unique final outcome | OPEN — S2b |
| E2 | Every applicable completed Track/attribute has exactly one `Observed` or `Unknown` row; missing row is not Unknown; run readiness distinguishes NotConfigured from NotApplicable | OPEN — S2b |
| E3 | Track-level `Unavailable` is explicit with reason and never masquerades as Unknown/Absent | OPEN — S2b |
| E4 | Supersession occurs only on successful completion; historical analysis remains readable and late obsolete completion cannot become default | OPEN — S2b |
| E5 | v4 HMAC cursor pins resolved attribute identity/coverage and rejects tampering | OPEN — S3 |
| E6 | Repeated attribute predicates are canonical in URL, fingerprint and cache key | OPEN — S3 |
| E7 | Attribute-only search supports multi-camera scope; combined analytics predicates retain analytics camera scope and pin both identities | OPEN — S3 |
| E8 | PostgreSQL plan/query-count/p50/p95 evidence passes at realistic and worst-supported fact volume with no N+1 evidence I/O | OPEN — S3 |

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

## Evidence log rule

For every PASS entry retain:
- exact commit SHA;
- environment/runtime/model/capability identities where applicable;
- corpus/protocol version where applicable;
- command/workflow/run or equivalent retained evidence;
- result;
- retained artefact/report hash where applicable;
- limitation/non-claim;
- reviewer/date.

A section may be partially green while Stage 2 remains open. Overall Stage 2 is complete only when every applicable requirement in this authoritative register is PASS.
