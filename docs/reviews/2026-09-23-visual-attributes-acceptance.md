# Visual Attributes — Stage-2 Acceptance Register

**Status:** Open — S2a closed; S2b closed; S2c.0 closed (PR #116); S2c.1 in progress (tooling merged in PR #117; F1 OPEN); S2c.2a candidate credibility protocol merged (PR #118); S2c.2b-1 quality/statistical protocol in review (PR #119)  
**Date opened:** 2026-09-23  
**Baseline:** `main@ca23adf55b0b4a14faf58e12d048a3c90221557c`  
**Reconciled:** 2026-09-28 against S2a `main@406172657599350ecbb27819865ecc9482c6c97d`; S2b closure evidence reconciled against `main@f7b03a24aba8b8bd303ed3a93b26622395e94c5f`; PR #115 acceptance authority is `main@677afb6b73edf436e23f8d275bb95a7d5b3badac`; the S2c.0 implementation baseline is `main@647d8f605d7c29bb6984408cb4d7e87eb5dcc163` (merge of PR #116)

This register is authoritative for Stage-2 exit criteria. Other plans must reference this table rather than maintain a second independently numbered acceptance list.

Nothing unexecuted is marked PASS.

## Current verdict

**ARCHITECTURE FROZEN — S2a COMPONENT BINDING v2 CLOSED; S2b ATTRIBUTE LIFECYCLE CLOSED; PR #115 S2c PLAN ACCEPTED; S2c.0 BASELINE CLOSED (PR #116). S2c.1 IN PROGRESS: CORPUS/LABEL TOOLING MERGED (PR #117); F1 OPEN PENDING OPERATIONAL EVIDENCE. S2c.2a CANDIDATE CREDIBILITY PROTOCOL MERGED (PR #118); S2c.2b-1 QUALITY/STATISTICAL PROTOCOL IN REVIEW (PR #119); NO MODEL SELECTED.**

S1 implementation is merged; B1–B6 remain OPEN wherever the retained S1.4 qualification/evidence requirement has not yet been entered as executed evidence in this register. S2a.1–S2a.4 are merged through PR #112 at `main@406172657599350ecbb27819865ecc9482c6c97d`; C1–C7 remain reconciled below. S2b is closed through PR #114 at `main@f7b03a24aba8b8bd303ed3a93b26622395e94c5f`: final PR head `37376fb28e4be181642eace65d09dec7884c550f` passed exact-head runs 36403353060, 36403353027 and 36403353097, and merged main passed MAVI Quality Gate #2150 (36406745354), Task 17 #1284 (36406745355) and Task 10 #807 (36406745357). The durable closure record is `docs/reviews/2026-09-28-stage2-s2c-0-baseline.md`; the obsolete "exact-head CI pending" qualifiers are therefore removed from D1–D8/E1–E4 without changing their already-recorded PASS status. E5–E8 remain OPEN for S3. PR #115 merged the independently reviewed S2c plan at `main@677afb6b73edf436e23f8d275bb95a7d5b3badac`; that merge accepted its governing ADR/qualification/MSR decisions. S2c.0 reconciled those already-effective decisions; its merge (PR #116, `main@647d8f605d7c29bb6984408cb4d7e87eb5dcc163`) is the implementation baseline. No F/G row changed status because of S2c.0. S2c.1 delivers the F1 tooling (manifests, partitions, leakage audits, annotation guide v1, independent labelling, agreement, frozen-test seal) but no operational evidence yet, so F1 remains OPEN.

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

Evidence, not authority: the Model Selection Records under `docs/qualification/model-selection/` (accepted MSR method v1) record why each capability's model was chosen. A row may cite a closed record; no record is an acceptance claim.

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
| A12 | Final independent cold architecture review reports no open P1/P2; ADR-013/014 can move to Accepted | PASS — Fable's second pass amended R-01–R-22; the final handover review then found and amended R-23 (tracker-retirement contract / staging contradiction). PASS applies only to the final amended documentation head; see the review-resolution record. |

**Implementation gate:** satisfied for architecture. S1/S2 implementation may begin only in a follow-on implementation change; this documentation PR contains no Stage-2 feature code.

## B. Evidence-set / raw-processing acceptance

| ID | Requirement | Status |
|---|---|---|
| B1 | Deterministic four-role candidate selector implemented with documented tie-breaking | OPEN — implemented and merged in S1.2c / PR #79; the two-tier Representative and scorer `quality-v2` follow the accepted ADR-013 §4 amendments; evidence pending S1.4 |
| B2 | JPEG encoding occurs in-loop; the model-neutral tracker emits exact-once retired Track ids with no post-retirement reappearance (mapping released on retirement, fresh id on backend id reuse); the whole Track — trajectory, Representative, supplemental candidates — is finalised and staged once at retirement/end-of-stream and only descriptors remain; earlier attempts' staging is removed on new lease; retirement/reactivation/no-reappearance/end-of-stream tests, on both the ByteTrack adapter and the fixture tracker, prove the live-Track memory bound | OPEN — in-loop encoding, retirement finalisation (S1.1), bounded trajectory spool (S1.2b) and the bounded Evidence Set (S1.2c / PR #79) are merged; live memory per Track constant by construction; RSS evidence pending S1.4 |
| B3 | Representative and supplemental byte caps, reduction floors, score-ordered admission and the 1 GiB run EvidenceCrop quota are enforced; body bound re-derived; all contract-tested at the 10,000-Track bound | OPEN — implemented and merged in S1.2c / PR #79, worker worst-shape body 24.72 MiB; evidence pending S1.4 |
| B4 | Vision completion schema v3, digest v3, validator/store/sealing and Observation evolution pass contract tests | OPEN — platform side merged in S1.2a; worker emission and cross-language vectors merged in S1.2c / PR #79; evidence pending S1.4 |
| B5 | `TrackDetail.observations[]` and evidence viewer expose accepted roles without breaking Representative behaviour | OPEN — implementation is merged: server read contract in S1.3a / PR #82 and viewer in S1.3b / PR #83 (`main@81b43dec32bec0c5e876d2df372503016c05dbdf`); real-video/operator acceptance evidence remains S1.4 |
| B6 | Relevant Task-10 CPU matrices are rerun; CUDA/E2E evidence is rebound when produced; no stale qualification claim remains | OPEN |

## C. Component-binding v2 acceptance

| ID | Requirement | Status |
|---|---|---|
| C1 | `capabilityBindings[]` schema supports detector + future capability ids without Stage-2-only structural fields | PASS — implemented across S2a; retained mutation evidence: `docs/qualification/stage2-s2a/mutations-s2a-1.md`, `mutations-s2a-2.md`, `mutations-s2a-3.md`, and `mutations-s2a-4.md`; merged through PR #112 at `main@406172657599350ecbb27819865ecc9482c6c97d` |
| C2 | Model-manifest v2 common schema is capability-neutral; detector-specific config is optional/capability-specific | PASS — manifest-v2 cut-over is covered by the retained S2a mutation records above and the exact-head repository/model-pack gates on PR #112 head `911ae9f27fcbc9ebf48431d6fdc9dd9ae2750ad9` |
| C3 | Runtime profile is decoupled from a privileged model checkpoint and supports independently startable roles | PASS — schema/runtime identity decoupling is implemented and retained in the S2a mutation evidence. Limitation: only `vision` is implemented/startable on the S2a baseline; activation of the independent `attributes` role is D5/S2b, not evidence that a second role already exists |
| C4 | Capability-scoped qualification-record shape and common/capability-specific gates are implemented | PASS — retained S2a mutation records exercise the capability-scoped qualification shape and fail-closed gates; PR #112 exact-head Quality Gate/Task 12/Vision Model Pack/Task 17 all passed; no Production/CUDA promotion implied |
| C5 | modelPackId/runtimePackId/capabilityId are persisted in provenance/digests | PASS — S2a.3 retained evidence includes `docs/qualification/stage2-s2a/mutations-s2a-3.md` and `docs/qualification/stage2-s2a/record-replay-s2a-3/`; exact-head PR #112 gates revalidated the merged contracts |
| C6 | verify_repo, offline packaging and CI fail closed on binding/manifest/runtime mismatch | PASS — PR #112 exact head `911ae9f27fcbc9ebf48431d6fdc9dd9ae2750ad9`: MAVI Quality Gate PASS; Task 12 PASS; Vision Model Pack PASS; Task 17 PASS. S2a.4 retained mutation record `docs/qualification/stage2-s2a/mutations-s2a-4.md` records 28/28 deliberate mutations caught |
| C7 | Existing detector qualification hashes/records affected by profile v2 are deliberately reconciled and behaviour-regression tests pass | PASS — retained reconciliation: `docs/qualification/stage2-s2a/2026-09-27-detector-identity-reconciliation.md`; retained S2a.3/S2a.4 mutation and record/replay evidence above; RTMDet remains pending/unverified and no Production/CUDA promotion occurred |

### C-section retained evidence record

- implementation chain: S2a.1–S2a.4, culminating in PR #112;
- merged baseline/result SHA: `406172657599350ecbb27819865ecc9482c6c97d`;
- final PR #112 exact head: `911ae9f27fcbc9ebf48431d6fdc9dd9ae2750ad9`;
- environment/runtime/model/capability identities: repository/component identities frozen by the S2a binding/manifest/runtime files and identity-freeze tests; Windows PowerShell 5.1 and PowerShell 7 exercised for Setup contracts in Task 17;
- commands/workflows/runs: PR #112 exact-head MAVI Quality Gate, Task 12, Vision Model Pack and Task 17 — all PASS before merge;
- retained reports/artefacts: `docs/qualification/stage2-s2a/mutations-s2a-1.md`, `mutations-s2a-2.md`, `mutations-s2a-3.md`, `mutations-s2a-4.md`, `record-replay-s2a-3/`, and `2026-09-27-detector-identity-reconciliation.md`; their repository blob/content hashes are retained by Git at the merged baseline;
- result: C1–C7 satisfied at the S2a boundary described above;
- limitation/non-claim: C3 does not claim an implemented second role; C1–C7 do not claim RTMDet Production qualification, CUDA qualification, family-wide Production qualification, or any real attribute Model Pack;
- reviewer/date: independent cold reviews of the S2a implementation and final exact-head merge gate completed in the PR #112 review history on 2026-09-28; this register reconciliation does not substitute for that retained review history.

## D. Attribute lifecycle and evidence-read acceptance

| ID | Requirement | Status |
|---|---|---|
| D1 | VisualAttributeAnalysis unit/lifecycle is independent of ProcessingRun success | PASS — separate aggregate/table, queued only for completed visible runs within the current activation (`OnlyVisibleApplicableRunsOfTheCurrentActivationAreQueued`); a Failed unit never touches the run (`ATerminalFailureEndsTheUnit`); record `docs/qualification/stage2-s2b/implementation-record.md` §5, M18–M20 |
| D2 | Shared fencing/hash primitives are extracted only where semantics match; no third copy-and-diverge implementation | PASS — deliberate requirement amendment retained: `CanonicalSha256` extracted and adopted by VisionJob/SceneAnalysis/Artifact (regression suites green); `LeaseCapabilityService` reused unchanged; claim SQL deliberately not genericised; record `docs/qualification/stage2-s2b/implementation-record.md` §1 |
| D3 | Python-facing lease/heartbeat/complete/fail endpoints and transport contracts are contract-tested | PASS — deliberate requirement amendment retained: header-only capability. `VisualAttributeApiTests` (header only, body token refused, no echo, cap/cap+1 per route), `VisualAttributeContractBoundTests`, worker `test_contract_constants_match_the_platform`; mutations M10, M11, M27; record `docs/qualification/stage2-s2b/implementation-record.md` §4, §6 |
| D4 | Lease-scoped evidence read and prediction-upload endpoints authorise only the leased unit's Observations/artefact; worker verifies SHA/size before decode; the attribute role touches no platform filesystem | PASS — cross-run IDOR and other-attempt upload refused (`EvidenceIsServedWithItsRecordedSizeAndOnlyToTheLeasedRun`, `AnUploadIsVerifiedAgainstItsDeclaredDigestAndLease`); at-rest size checked before headers; worker digest before decode (`test_evidence_transport_is_never_evidence`); settings carry no media root; mutations M12, M13, M21, M22, M28 |
| D5 | Attribute worker runs as an independent process/role with independent READY/device/provenance/failure domain | PASS — `attributes` role through the shared registry/resolver/environment policy (`test_the_attributes_role_resolves_through_the_shared_resolver`, contract-capability refusals); real process E2E `TheFixtureWorkerPublishesARunThroughTheRealLeasePlane` (run by the quality gate); Production refuses the fixture on both sides (M14, M15) |
| D6 | Model unavailable at startup leaves work Queued without consuming attempts | PASS — UNAVAILABLE worker never creates a lease client (`test_a_missing_model_pack_leaves_the_role_unavailable_and_it_never_leases`, M30); a worker of another identity never consumes an attempt (`AWorkerOfAnotherIdentityNeverClaimsOrConsumesAnAttempt`, M20); readiness reports `no_ready_attributes_worker` |
| D7 | Stale attempts, reclaim, retry, cancellation, malformed output and failure isolation pass | PASS — reclaim between Phase A and C, expiry without reclaim, crash after seal, ambiguous commit, concurrent duplicates (`VisualAttributeCompletionProtocolTests`); retryable/terminal/deadline/exhaustion (`VisualAttributeLifecycleTests`); lease loss cancels work without `/fail`, malformed output terminal (`test_attribute_role.py`); cancellation here is worker-side lease-loss cancellation — the attribute plane has no operator cancel; mutations M01–M05, M17–M19, M31–M33 |
| D8 | Prediction-level outputs are sealed as bounded `AttributePredictions`; lifecycle publication is atomic and final relational rows remain Track-level only | PASS — canonical JSON artefact sealed content-addressed in Phase B; one publication transaction behind the visibility barrier (`PublicationWaitsForTheVisibilityBarrier`, M16); schema refused unless its worst-case artefact fits 64 MiB in both languages (vector, M29); synchronous completion measured at 10,000 Tracks (≤ 3.7 s, barrier ≤ 14.3 ms); record `docs/qualification/stage2-s2b/implementation-record.md` §4–§5 |

## E. Persistence/search semantics acceptance

Ownership is split deliberately: **S2b establishes and proves E1–E4 persistence/integrity semantics as part of the lifecycle publication boundary; S3 adds and proves E5–E8 search/cursor/query-plan semantics.** *(2026-09-28: S2b closure evidence is recorded under Current verdict and in the S2c.0 reconciliation record; there is no remaining pending S2b closure entry.)*

| ID | Requirement | Status / owner |
|---|---|---|
| E1 | Analysis/outcome/attribute relational constraints match ADR-013, including Restrict evidence linkage and unique final outcome | PASS — S2b — `VisualAttributePersistenceTests` (CHECK shapes, Restrict FKs, unique (analysis, Track, type), unique (run, identity)); COPY writes keep every constraint (M35) |
| E2 | Every applicable completed Track/attribute has exactly one `Observed` or `Unknown` row; missing row is not Unknown; run readiness distinguishes NotConfigured from NotApplicable | PASS — S2b — row cardinality and Observed/Unknown shape (`VisualAttributeCompletionValidatorTests`, M24, M25); readiness states (`VisualAttributeReadinessRuleTests`) |
| E3 | Track-level `Unavailable` is explicit with reason and never masquerades as Unknown/Absent | PASS — S2b — authoritative reasons only, transport never evidence (`test_evidence_transport_is_never_evidence`, M07, M08); E2E publishes `evidence_missing` for a Track whose crops are gone |
| E4 | Supersession occurs only on successful completion; historical analysis remains readable and late obsolete completion cannot become default | PASS — S2b — `ALateObsoleteCompletionIsHistoryAndARollbackReDerivesItAsTheDefault`, `APreferredCompletionSupersedesTheOldDefaultAndAFailedReplacementDoesNot` (M06, M23) |
| E5 | v4 HMAC cursor pins resolved attribute identity/coverage and rejects tampering | OPEN — S3 |
| E6 | Repeated attribute predicates are canonical in URL, fingerprint and cache key | OPEN — S3 |
| E7 | Attribute-only search supports multi-camera scope; combined analytics predicates retain analytics camera scope and pin both identities | OPEN — S3 |
| E8 | PostgreSQL plan/query-count/p50/p95 evidence passes at realistic and worst-supported fact volume with no N+1 evidence I/O | OPEN — S3 |

## F. Model/qualification acceptance

Ownership (clarified 2026-09-28 by the S2c plan; no status changes): the parent plan assigns S2c "labelled-corpus engineering evaluation" and S5 "freeze thresholds, frozen-test evaluation, CPU/CUDA Development evidence" and "all remaining F/G requirements". The owner column below states which slice is expected to close each row; *contributes* means the slice produces evidence the closing slice consumes. An owner is not a claim.

| ID | Requirement | Status | Closing owner |
|---|---|---|---|
| F1 | Annotation guide, double-label agreement/adjudication and corpus partition manifests are frozen before final evaluation | OPEN — S2c.1 tooling and guide v1 delivered; evidence record `docs/qualification/stage2-s2c/corpus/f1-evidence-record.json` computes OPEN (no operational corpus, annotators, pilot, main labelling or seal yet) | S2c |
| F2 | Minimum class/value support table and operational gates are frozen from validation/tuning evidence before frozen-test scoring | OPEN | S5 (S2c contributes validation evidence) |
| F3 | Person/vehicle Model Packs have complete licence, integrity, offline and provenance records | OPEN | S2c (licence approval is a human gate) |
| F4 | Crop-level, Representative-only and aggregated Track-level metrics are reported with abstention/Unknown rates | OPEN | S5 (S2c contributes validation-partition metrics) |
| F5 | Held-camera/unseen-camera generalisation meets declared gates or limitations disable affected exposure | OPEN | S5 (S2c contributes validation leave-one-camera-out) |
| F6 | Non-subject/error crops demonstrate safe abstention behaviour | OPEN | S5 (S2c contributes) |
| F7 | Operator-facing predicate retrieval precision-at-N/coverage evidence meets declared gates | OPEN | S5 after S3 (needs search v4) |
| F8 | CPU Development qualification passes; CUDA Development evidence is recorded where applicable without Production claim | OPEN | S5 (S2c contributes CPU, and CUDA where hardware exists, Development execution evidence) |
| F9 | Runtime/model version-skew, OOM/failure recovery and shared-host process isolation pass | OPEN | S5 (S2c contributes the engineering evidence; the parent plan gives resilience to S5) |
| F10 | Requalification-trigger matrix is exercised/documented for the final Stage-2 identity | OPEN | S5 (S2c drafts the matrix) |

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

### S2b closure / S2c.0 baseline reconciliation — 2026-09-28

- S2b final PR head: `37376fb28e4be181642eace65d09dec7884c550f`; merged baseline: `main@f7b03a24aba8b8bd303ed3a93b26622395e94c5f`.
- Exact-head PR runs: MAVI Quality Gate `36403353060`, deterministic/Windows validation `36403353027`, CPU Ubuntu/Windows runtime qualification `36403353097` — all success.
- Post-merge main runs: MAVI Quality Gate #2150 (`36406745354`), Task 17 #1284 (`36406745355`), Task 10 #807 (`36406745357`) — all success.
- Retained S2b implementation record: `docs/qualification/stage2-s2b/implementation-record.md`.
- S2c planning acceptance: PR #115 head `33a701d0045b6fa8961a10f69189313d60e6111c`, MAVI Quality Gate #2159 PASS, Task 17 #1293 PASS, zero unresolved review threads at merge.
- S2c.0 reconciliation record: `docs/reviews/2026-09-28-stage2-s2c-0-baseline.md`; it becomes the implementation baseline only after this change passes exact-head CI and merges.
- Non-claims: no learned model selected; no F/G model-quality row promoted; no CUDA or Production qualification implied.

### S2c.1 corpus/label tooling — 2026-09-28

- Baseline: `main@647d8f605d7c29bb6984408cb4d7e87eb5dcc163` (merge of PR #116, S2c.0).
- Delivered: `tools/qualification/attributes/corpus/` (tooling and README), `docs/qualification/stage2-s2c/annotation-guide.md` (v1, candidate vocabulary), `docs/qualification/stage2-s2c/s2c-1-implementation-record.md`, and the F1 evidence record with its fail-closed checker.
- Evidence class: tooling tests on **synthetic fixtures only**; they prove the mechanisms, not annotation agreement, corpus diversity or camera/site support.
- F1: OPEN. Missing external inputs are listed in the evidence record.
- Merged in PR #117 at `main@1d9c0ff8dd67cbd65acaf2d0942efbea5e19fd18` (see the S2c.1 implementation record for the review rounds).

### S2c.2a candidate credibility protocol — 2026-09-29

- Baseline: `main@1d9c0ff8dd67cbd65acaf2d0942efbea5e19fd18` (merge of PR #117, S2c.1 tooling).
- Delivered: MSR method v1 revision M1 (`docs/qualification/model-selection/candidate-credibility.md`), the External Evidence Ledger template, and the ledger/decision-summary validator `tools/qualification/model_selection_check.py`, with tests on synthetic fixtures only.
- No row changes. It selects, downloads and benchmarks no model, writes no ledger for a real event, and claims no MAVI result. F1, F3 and every other F/G row keep their state; S2c.2, S2c.3 and S2c.4 are OPEN.
- Merged in PR #118.

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
