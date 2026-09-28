# Stage 2 S2b — implementation record

- **Plan:** `docs/superpowers/plans/2026-09-28-stage2-s2b-attribute-lifecycle.md` (merged in PR #113)
- **Starting baseline:** `main@ad01c2b181bc3ca8f45338ab706be870758c4c79` (merge of PR #113; no intervening commits)
- **Branch:** `feature/stage2-s2b-attribute-lifecycle`
- **Governing:** ADR-006, ADR-009, ADR-011, ADR-013 (amended in this slice, §3 below), ADR-014, the Stage-2 acceptance register

This is the running record for the slice. It states what was reused, what was extracted and what is new, the decisions made where the plan left an implementation choice, and the evidence produced. It is not an acceptance register: D1–D8 and E1–E4 status lives only in `docs/reviews/2026-09-23-visual-attributes-acceptance.md`.

## 1. Baseline reconciliation (plan §3)

| Requirement | Existing primitive | Decision |
|---|---|---|
| Lease capability: 32 random bytes, Base64Url, SHA-256 at rest, constant-time match | `ILeaseCapabilityService` / `LeaseCapabilityService` (VisionJob) | **Reuse unchanged.** It is already a shared service; the attribute plane is its second consumer, not a third copy. SceneAnalysis keeps its in-process raw-byte token: it is never on the wire and its ownership semantics differ (ADR-011 D4). |
| Canonical lower-case SHA-256 validation | about nine private copies (`VisionJob`, `SceneAnalysis`, `Artifact`, `AcceptedEvidenceStore`, validators …) | **Extract narrowly** to `Mavi.Domain.Common.CanonicalSha256`; the new aggregate and the domain types that already duplicate it use the one rule. Regression suites of VisionJob, SceneAnalysis and Artifact prove behaviour is unchanged. Contract-layer copies stay (Contracts has no Domain reference by design). |
| `FOR UPDATE SKIP LOCKED` claim | three hand-written claim queries | **Not genericised** (plan §6). Eligibility, reclaim and exhaustion differ per plane; the attribute plane writes its own claim with its own identity fence. |
| Completion digest | `VisionResultValidator.ComputeDigest` (frozen v2/v3/v3.2 domains) | **Not shared.** A shared writer would put frozen digest vectors at risk for no semantic gain. The attribute digest has its own domain tag `mavi:visual-attribute-completion-digest:v1`. |
| Accepted-evidence read | `IAcceptedEvidenceReader` (path-safe, handle-verified, no size bound, no hash) | **Reuse.** The endpoint adds the size check before headers and the lease/IDOR authorisation. |
| Sealing | `IAcceptedEvidenceStore.SealAsync` (streamed copy, fsync, create-once, adopt-if-identical) | **Reuse unchanged** for Phase B. The accepted key is content-addressed and not attempt-scoped (plan §12). |
| Staging | worker-written `staging/{job}/attempt-NNNN`; `StagingJanitor` authoritative on `vision_jobs` | **New platform-owned namespace** `staging-attributes/{analysisId}/attempt-NNNN/` under `MediaStorage:RootPath`, outside the directory the VisionJob janitor scans; a separate janitor authoritative on `visual_attribute_analyses`, reusing the handle-relative `StagingDirectory` deletion primitive. |
| Visibility barrier / sequence | `ProcessingVisibilityBarrier` (shared advisory lock and `processing_visibility_sequence`) | **Reuse.** Rows are written before the exclusive lock; the lock is held only for sequence allocation, completion and supersession. |
| Placeholder `VisualAttribute` entity / `visual_attributes` table | per-row model name/version, nullable `ObservationId` with SetNull, no `AnalysisId`; nothing reads or writes it | **Replaced** by the ADR-013 §14 shape in the S2b migration (table dropped and recreated; it has never held data written by any code path). |
| `EmbeddingExtractor` Protocol | declared, zero usages | **Removed** in S2b.1 (plan §3). Stage 5 designs its own contract; S2b's inferencer abstraction is attribute-specific. |
| Worker HTTP client | `WorkerApiClient` is VisionJob-shaped (routes, completion versions, video lease) | **New client** `mavi_vision.attributes.client` for the attribute plane; `LeaseGuard` is reused. |
| Role registry / resolver | `IMPLEMENTED_ROLE_ENTRY_POINTS = {vision}`, `IMPLEMENTED_CAPABILITIES = {detector}`, detector-only pipeline profile loading | **Extended in place:** the `attributes` role entry point `mavi_vision.attributes.main`, the attribute capability ids, the attribute pipeline profile loader and the attribute provenance contract are registered; the resolver dispatches pipeline-profile loading by role kind. No second composition path. |
| Shipped Component Binding (`phase1-bindings-v2.json`) | vision role only | **Unchanged** (plan §20: no Component Binding identity change). The fixture is bound only in Development/test overlays. |

No contradiction with a governing decision was found that required stopping. One mechanism the ADRs require but do not name — how the platform learns the preferred identity — is decided in §3 and recorded as an ADR-013 implementation amendment.

## 2. Plan items that are implementation choices

Recorded here as they are made; each is a P3-level choice inside the plan's decided semantics.

1. **Wire contract version** `mavi-visual-attribute-control-v1` for lease/heartbeat/fail/complete; the prediction artefact schema is `mavi-attribute-predictions-v1`.
2. **Routes** (all under `/api/attributes/analyses`): `POST /lease`, `POST /{id}/heartbeat`, `GET /{id}/evidence/{observationId}`, `PUT /{id}/predictions`, `POST /{id}/complete`, `POST /{id}/fail`.
3. **Header-only capability:** request header `X-Mavi-Lease-Capability`; the lease response returns the new capability in the same response header and never in a JSON body. Attempt and worker travel in the JSON envelope for POSTs and in `X-Mavi-Attempt` / `X-Mavi-Worker-Id` for the GET and the PUT. A JSON property named `leaseToken` is rejected.
4. **Encoding:** canonical UTF-8 JSON (sorted keys, no insignificant whitespace, no NaN), trailing LF. The platform never re-serialises: it hashes the bytes received and validates structurally with a streaming reader.
5. **Authoritative evidence failures** are HTTP 422 with `visual_attribute_evidence_missing` or `visual_attribute_evidence_integrity_failed`; everything else the worker cannot complete (resets, timeouts, 5xx, truncated bodies) is transport failure.

## 3. Platform source of the preferred identity (ADR-013 implementation amendment)

ADR-013 §9 fixes the identity at queue time from "the enabled capability bindings" and the plan makes "the currently enabled Component Binding" the authority for the default. The platform has never read the binding: until now it learned component identity only from completions. S2b therefore gives the platform a read-only view of the same release overlay the worker composes from:

- `VisualAttributes:ComponentBindingPath` — the release Component Binding (the file whose SHA is `componentBindingSha256`);
- `VisualAttributes:PipelineProfilePath` — the attribute pipeline profile (schema, aggregation policy, parameters, each pinned by SHA-256).

The platform derives the identity tuple and its fingerprint from exactly those bytes, with the same canonical derivation as the worker (cross-language test vector). Neither configured → readiness `NotConfigured` and nothing is queued; the shipped release configures neither. The worker presents its own resolved fingerprint on every lease request and the claim query is fenced on it, so a worker composed from a different binding can never take ownership of — or consume an attempt of — a unit it cannot reproduce (the SceneAnalysis engine-fence pattern).

**Trade-off accepted:** the platform now parses a narrow, fail-closed subset of the binding and the attribute pipeline profile. The alternative — a second, platform-local declaration of the identity — would create two authorities that can drift silently; the lease fence would catch the drift but only as permanently Pending work.

## 4. Numeric bounds

Every bound is a named constant in `VisualAttributeContractRules` (platform) mirrored in `mavi_vision.attributes.contracts` / `pipeline` (worker; `test_contract_constants_match_the_platform` holds the copies equal). None inherits the ~3 GiB Kestrel import limit: `VisualAttributeRequestLimitMiddleware` sets the per-route `MaxRequestBodySize` and refuses a declared length over it with 413 before the endpoint runs; every other attribute route admits no body.

| Bound | Value | Derivation | Tests (cap / cap+1) |
|---|---|---|---|
| Tracks per analysis | 10,000 | the existing `WorkerContractRules.MaximumCompletionTracks`; bounded converter refuses the 10,001st while reading | `OneTrackOverTheBoundIsRefusedWhileReading` |
| Crops per Track | 4 | the Evidence Set bound (four roles) | lease model `max_length`; 10k × 4 measured below |
| Lease response | 16 MiB (worker read cap) | measured 8,391,173 B at 10,000 Tracks × 4 crops (~210 B per descriptor + ~40 B per Track) — ~2× headroom; the worker refuses a larger body unread, so no lease paging was needed | `test_a_lease_response_over_its_bound_is_refused_unread`; timing test asserts ≤ cap at 10k |
| Lease / heartbeat request | 4 KiB each | three short fields | `EveryControlRouteRefusesItsCapPlusOne(lease, heartbeat)` |
| Fail request | 16 KiB | 4,000-character message + envelope | `EveryControlRouteRefusesItsCapPlusOne(fail)` |
| Completion request | 32 MiB | 4 KiB provenance + 10,000 × (192 B Track envelope + 8 rows × (192 B row envelope + 64 + 64 B tokens)) ≈ 27.5 MB; literal worst shape serialises inside the cap | `TheWorstShapeCompletionFitsTheCompletionRouteCap`, `EveryControlRouteRefusesItsCapPlusOne(complete)` |
| Rows per Track | 8 | per-object-class attribute-type limit; refused while reading | `OneRowOverThePerClassBoundIsRefused` |
| Prediction upload | 64 MiB | the existing per-artefact bound (plan §15); streamed to disk, hashed while streaming, never buffered | `EveryControlRouteRefusesItsCapPlusOne(predictions)`, `AShortOrLongBodyIsNeverStaged` |
| Schema → artefact | worst case ≤ 64 MiB | header 4 KiB + 10,000 × max per class of (192 + Σ decisions (len(type) + max len(value) + 192) + 4 × (160 + Σ types (len(type) + 6 + Σ values (len(value) + 28)))); tokens are unescaped `[a-z0-9-]`, numbers are shortest round-trip doubles (≤ 24 characters). A schema over it is refused by **both** loaders (`attribute_schema_invalid:artifact_bound`) | vector `visual-attribute-artifact-bound-v1.json` (fixture 22,424,096 B; largest accepted 67,104,096 B; smallest refused 67,154,096 B, one character apart); `test_the_worst_case_bound_is_an_upper_bound_of_the_real_encoder` encodes the largest accepted schema's worst artefact with the production encoder and finds it within the bound |
| Evidence response | exactly the recorded size | the at-rest length is checked before any header; a mismatch is 422, never a truncated or padded 200 | `AnAcceptedObjectThatDisagreesWithItsRecordIsAnAuthoritativeIntegrityFailure` |
| Schema tokens | ≤ 64 characters; ≤ 16 types, ≤ 8 per class, ≤ 32 values | ADR-013 §12 vocabulary limits (the artefact bound above is the binding constraint in practice) | parser suites in both languages |
| Heartbeat margin | interval + request timeout < 0.75 × 60 s | the platform's minimum lease is 60 s; a renewal must start and finish inside the shortest lease | `test_the_heartbeat_margin_is_bounded_by_the_shortest_lease` |

## 5. Evidence produced

All commands were run on this branch against PostgreSQL 18 (`MAVI_TEST_DB_CONNECTION` port 5433), .NET 10 Release and the `mavi_vision` Python environment; one suite at a time, always after a build.

### 5.1 Commits

| Commit | Content |
|---|---|
| `cd8cc27` | control plane over HTTP; three-phase completion; staging store and janitor; 33 integration tests |
| `b44bab3` | derived artefact and completion bounds (cross-language vector); COPY fact writes; 10k measurement |
| `42dda39` | the `attributes` role process on the Component Binding v2 path |
| `58d7c3b` | fixture end-to-end through the real lease plane; quality gate runs it |
| `89c0498` | validator unit suite; barrier, startup-refusal and no-echo tests |

### 5.2 Synchronous completion at the 10,000-Track bound (plan §13)

`MAVI_S2B_TIMING_TRACKS=10000 dotnet test tests/Mavi.IntegrationTests --filter FullyQualifiedName~VisualAttributeCompletionTiming` — the real lease, upload and completion routes, 10,000 person Tracks × 4 accepted crops (40,000 crops), timings from the publication log (event 1990). The budget is the one ADR-006 §7 applies to a completion request: 15 s bounded by the lease; the barrier reference is the vision publication's 1.67–2.29 s hold (`f4-configuration-freeze.md`).

| Shape | Rows | Completion wall (3 runs) | Phase A | Seal | Phase C | Barrier hold |
|---|---|---|---|---|---|---|
| fixture (2 types per person) | 20,000 | 1,590.7 / 1,704.1 / 1,900.2 ms | 316–355 ms | 38–54 ms | 623–713 ms | 19.3–20.3 ms |
| worst admitted (8 types per person) | 80,000 | 3,290.7 / 3,299.1 / 3,676.3 ms | 266–318 ms | 65–177 ms | 1,697–1,827 ms | 8.5–14.3 ms |

The first measurement used change-tracked EF inserts and was **not** safe at the worst admitted shape: 11,195 ms of which 9,215 ms Phase C (fixture shape 4.2–4.7 s, barrier 168–254 ms). The cost was the per-entity insert path, not the protocol, so Phase C now writes Track outcomes and attribute rows with binary `COPY` on the publication transaction's own connection (`VisualAttributeFactWriter`; domain factories build every row, every constraint still applies, nothing is visible before commit). Lease response 8,391,173 B; artefact 32,450,494 B and completion body 12,931,716 B at the worst shape.

**Decision: synchronous completion stands.** The worst admitted shape completes in ≤ 3.7 s (≥ 4× inside the 15 s budget) and holds the barrier ≤ 14.3 ms, two orders of magnitude below the vision publication's reference. No `Finalizing` hand-off is required, so none was implemented. The test asserts the 15 s budget; the default quality-gate shape is 200 Tracks.

### 5.3 Suites

| Suite | Result |
|---|---|
| Domain `VisualAttribute*` | see §5.4 full runs |
| Application `VisualAttribute*` (parser, readiness, contract bounds, completion validator) | 68 passed |
| Integration `VisualAttribute*` (persistence, lifecycle, API, protocol races, staging/janitor, timing, E2E) | 59 passed, 1 skipped without `MAVI_S2B_WORKER_PYTHON`; E2E 1 passed with it |
| Python `test_attribute_role.py` + `test_attribute_pipeline.py` | 37 + 20 passed |
| Python full suite | 2,884 passed, 30 skipped |
| `tools/verify_repo.py` | PASSED |

### 5.4 Final verification

Recorded at the final head in §8.


## 6. Mutation matrix

Runner: `mutate_s2b.py` (scratchpad, not shipped) applies one exact-text mutation, rebuilds the solution for a .NET mutation, runs the guarding suites (Domain/Application/Integration `VisualAttribute*`, the latter with the E2E enabled; or the Python role/pipeline/resolver suites) and restores the file byte for byte (SHA-256 checked); the solution is rebuilt clean at the end. A mutation that does not build would be recorded `invalid`; none was.

Run 1 killed 32 of 35. The three survivors were test gaps, not defects, and were closed before run 2:

- **M18** (deadline anchored at queue) — the deadline test queued and first-claimed at the same instant; it now claims five hours after queueing.
- **M19** (claim ignores the deadline) — `CanClaim` re-checks the deadline in memory, so the SQL predicate's job is liveness; new `AUnitPastItsDeadlineNeverStarvesQueuedWork` proves an expired unit is passed over rather than selected and skipped on every poll.
- **M20** (claim not fenced on identity) — the other-identity test never activated identity B, so the claim returned before reaching SQL; it now activates B first.

**Final: 35 of 35 killed.**

| ID | Mutation | File | Result | First killing test |
|---|---|---|---|---|
| M01 | attempt fencing omitted (IsOwnedBy) | `VisualAttributeAnalysis.cs` | **killed** | `ARefusedHeartbeatChangesNothing` |
| M02 | capability-hash fencing omitted (IsOwnedBy) | `VisualAttributeAnalysis.cs` | **killed** | `ARefusedHeartbeatChangesNothing` |
| M03 | Phase C re-fence omitted | `VisualAttributeCompletionService.cs` | **killed** | `AReclaimBetweenPhaseAAndPhaseCIsRefusedAndTheSealedOrphanIsSafe` |
| M04 | Phase C re-fences status only (not attempt/capability) | `VisualAttributeCompletionService.cs` | **killed** | `AReclaimBetweenPhaseAAndPhaseCIsRefusedAndTheSealedOrphanIsSafe` |
| M05 | lease expiry checked before committed replay | `VisualAttributeCompletionService.cs` | **killed** | `AnAmbiguousCommitPublishesNothingAndTheRetryPublishesOnce` |
| M06 | supersession by completion order (every completion is preferred) | `VisualAttributeCompletionService.cs` | **killed** | `ALateObsoleteCompletionIsHistoryAndARollbackReDerivesItAsTheDefault` |
| M07 | transient evidence transport mapped to Unavailable (client) | `client.py` | **killed** | `test_evidence_transport_is_never_evidence[truncated]` |
| M08 | transient evidence transport mapped to Unavailable (runner) | `runner.py` | **killed** | `test_evidence_transport_fails_the_attempt_as_retryable_and_never_as_unavailable` |
| M09 | VisionJob janitor given authority over attribute staging | `StagingJanitor.cs` | **killed** | `TheVisionJobJanitorHasNoAuthorityOverAttributeStaging` |
| M10 | attribute route limits removed | `Program.cs` | **killed** | `EvidenceAndUnknownAttributeRoutesAdmitNoBody` |
| M11 | body capability token accepted (heartbeat) | `VisualAttributeContracts.cs` | **killed** | `ABodyNamingTheCapabilityIsRefusedOnEveryControlRequest` |
| M12 | cross-run evidence authorised | `VisualAttributeLifecycle.cs` | **killed** | `EvidenceIsAuthorisedOnlyForTheLeasedRunsAcceptedCrops` |
| M13 | worker SHA-256 verification skipped | `client.py` | **killed** | `test_evidence_transport_is_never_evidence[persistent-digest]` |
| M14 | fixture allowed in Production (worker) | `resolver.py` | **killed** | `test_production_refuses_the_fixture` |
| M15 | fixture allowed in Production (platform) | `VisualAttributeReleaseStartup.cs` | **killed** | `TheDevelopmentOnlyFixtureStartsOnlyInDevelopmentOrTesting` |
| M16 | visibility barrier bypassed | `VisualAttributeCompletionService.cs` | **killed** | `PublicationWaitsForTheVisibilityBarrier` |
| M17 | Phase C reads the tracked (stale) unit | `VisualAttributeCompletionService.cs` | **killed** | `ConcurrentIdenticalCompletionsPublishOnce` |
| M18 | deadline anchored at queue creation | `VisualAttributeAnalysis.cs` | **killed** (run 2, after the tests were strengthened) | `TheDeadlineIsEnforcedWithNoWorkerPolling` |
| M19 | claim ignores the deadline | `VisualAttributeLifecycle.cs` | **killed** (run 2, after the tests were strengthened) | `AUnitPastItsDeadlineNeverStarvesQueuedWork` |
| M20 | claim not fenced on the worker's identity | `VisualAttributeLifecycle.cs` | **killed** (run 2, after the tests were strengthened) | `AWorkerOfAnotherIdentityNeverClaimsOrConsumesAnAttempt` |
| M21 | another attempt's upload accepted | `VisualAttributeLifecycle.cs` | **killed** | `AnUploadIsVerifiedAgainstItsDeclaredDigestAndLease` |
| M22 | different-SHA upload replay accepted | `AttributeStagingStore.cs` | **killed** | `AnUploadIsStagedOnceAndOnlyTheSameBytesReplay` |
| M23 | rollback does not re-derive a Superseded analysis as default | `VisualAttributeReadiness.cs` | **killed** | `RollbackReDerivesTheDefaultFromTheExistingSuccessfulAnalysis` |
| M24 | Unknown treated as Absent (worker aggregation) | `predictions.py` | **killed** | `test_mean_score_argmax_observes_above_the_floor_and_is_unknown_below_it` |
| M25 | Observed row with a foreign supporting Observation accepted | `VisualAttributeCompletionValidator.cs` | **killed** | `EachRuleRefusesAloneWithItsCode` |
| M26 | device included in the semantic identity (worker) | `pipeline.py` | **killed** | `test_the_identity_vector_is_reproduced` |
| M27 | capability echoed on heartbeat | `VisualAttributeEndpoints.cs` | **killed** | `AHeartbeatNeedsTheHeaderCapabilityAndNeverTheBody` |
| M28 | evidence served without the at-rest size check | `VisualAttributeEndpoints.cs` | **killed** | `AnAcceptedObjectThatDisagreesWithItsRecordIsAnAuthoritativeIntegrityFailure` |
| M29 | schema artefact bound removed (platform) | `VisualAttributeRelease.cs` | **killed** | `ASchemaWhoseWorstCaseArtefactExceedsTheUploadCapIsRefused` |
| M30 | worker leases while UNAVAILABLE | `main.py` | **killed** | `test_a_missing_model_pack_leaves_the_role_unavailable_and_it_never_leases` |
| M31 | heartbeat not concurrent with the attempt | `runner.py` | **killed** | `test_the_heartbeat_runs_concurrently_with_slow_inference` |
| M32 | lost lease answered with /fail | `runner.py` | **killed** | `test_a_lost_lease_cancels_the_work_and_is_never_answered_with_fail` |
| M33 | expired lease accepted by lease-scoped operations | `VisualAttributeAnalysis.cs` | **killed** | `ARefusedHeartbeatChangesNothing` |
| M34 | janitor removes the Running attempt's staging | `AttributeStagingJanitor.cs` | **killed** | `TheJanitorNeverRemovesTheRunningAttemptsStaging` |
| M35 | COPY fact writes skipped (rows never persisted) | `VisualAttributeCompletionService.cs` | **killed** | `TheFixtureWorkerPublishesARunThroughTheRealLeasePlane` |

Plan §17 mutations that have no code path in this design are recorded rather than invented: *delete a sealed object on rollback* (no deletion call exists; `AReclaimBetweenPhaseAAndPhaseCIsRefusedAndTheSealedOrphanIsSafe` asserts the orphan survives), *supersede on failed replacement* (supersession runs only inside a successful preferred Phase C; `APreferredCompletionSupersedesTheOldDefaultAndAFailedReplacementDoesNot`), *publish rows before the publication transaction* (rows are written only inside it; `AnAmbiguousCommitPublishesNothingAndTheRetryPublishesOnce`), *duplicate (run, identity) units* (the unique index arbitrates; `ConcurrentReconcilersCreateOneUnit`) and *let the fixture bypass production transport* (the fixture has no transport of its own; the E2E runs the real process).

## 7. Deferred and out of scope

- **Explicit re-analysis request** (ADR-013 §9: "an explicit, bounded request per run or camera/time window") has no API in S2b; the plan does not scope one. Supersession and rollback are proven with a sibling unit inserted directly (`APreferredCompletionSupersedesTheOldDefaultAndAFailedReplacementDoesNot`), standing in for that request.
- Real Model Packs (S2c), search v4 and E5–E8 (S3), UI (S4), Production/CUDA promotion, a generic IntelligenceJob: not in S2b.
- The worker reports `cuda` unsupported (`attribute_device_unsupported:cuda`) — the fixture is CPU-only; device policy for real models is S2c's.

## 8. Final verification

Recorded at the final head in the pull request.
