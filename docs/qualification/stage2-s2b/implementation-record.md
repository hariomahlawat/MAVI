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

**Final: 72 killed of 73; one equivalent (M72)** (M36–M39 guard the cold-review fixes, §6.1; M40–M48 the lease-lifetime repairs, §6.2; M49–M60 the fence schedule, §6.3; M61–M64 evidence coverage and crop-level integrity health, §6.4; M65–M67 incidents across ambiguous commits and heartbeat presence, §6.5; M68–M73 the janitor scan, the release-removed host and the worker's renewal, §6.6. M61 was first written so that it did not compile and was rerun as a valid mutant. M38 and M39 first survived and their tests were made deterministic; M40 was first written so that it did not compile and was rerun as a valid mutant).

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
| M36 | publication cancelled with the request (client timeout aborts Phase C) | `VisualAttributeCompletionService.cs` | **killed** | `AClientThatGoesAwayAfterTheSealDoesNotAbortThePublication` |
| M37 | heartbeat left running during `/complete` | `runner.py` | **killed** | `test_a_renewal_refused_while_completing_neither_cancels_nor_misreports_the_publication` |
| M38 | next lease does not wait for in-flight inference | `runner.py` | **killed** (after the test asserted lease ordering) | `test_inference_is_serial_and_no_lease_is_taken_while_it_runs` |
| M39 | caller shutdown swallowed as lease loss | `runner.py` | **killed** (after the race was made deterministic) | `test_shutdown_during_a_lease_loss_is_not_swallowed` |
| M40 | Phase A does not open a publication window | `VisualAttributeCompletionService.cs` | **killed** | `AnAbandonedPublicationPastTheDeadlineIsFailedOnceItsWindowLapses` |
| M41 | a heartbeat may shorten the lease | `VisualAttributeAnalysis.cs` | **killed** | `AHeartbeatNeverShortensAPublicationWindow` |
| M42 | publication window unbounded past the deadline | `VisualAttributeAnalysis.cs` | **killed** | `APublicationWindowOutlivesTheDeadlineByAtMostOneLease` |
| M43 | deadline transition ignores a live lease (domain) | `VisualAttributeAnalysis.cs` | **killed** | `APublicationWindowOutlivesTheDeadlineByAtMostOneLease` |
| M44 | deadline sweep selects units with a live lease (batch liveness) | `VisualAttributeLifecycle.cs` | **killed** | `APublishingUnitNeverStarvesTheDeadlineSweepOfAnAbandonedOne` |
| M45 | fence skips the check after a blocking read | `LeaseFencedStream.cs` | **killed** | `AnEvidenceStreamStopsWhenTheLeaseExpiresMidRead` |
| M46 | fence re-checks only at lease expiry (no interval) | `LeaseFencedStream.cs` | **killed** | `AnEvidenceStreamStopsWhenTheOwnerGaveUpAndAnotherAttemptHoldsTheUnit` |
| M47 | upload body not fenced | `VisualAttributeEndpoints.cs` | **killed** | `AnUploadStopsWhenOwnershipIsReclaimedMidBodyAndStagesNothing` |
| M48 | evidence fence never revalidates ownership | `VisualAttributeEndpoints.cs` | **killed** | `AnEvidenceStreamStopsWhenTheLeaseExpiresMidRead` |
| M49 | first row read at the granted lease expiry | `LeaseFencedStream.cs` | **killed** | `AnEvidenceStreamStopsWithinOneRecheckIntervalOfItsAuthorisationAfterAHandOver` |
| M50 | first interval measured from building the stream (`08d1f60`) | `LeaseFencedStream.cs` | **killed** | `AnEvidenceStreamStopsWithinOneRecheckIntervalOfItsAuthorisationAfterAHandOver` |
| M51 | after a row read, the next is due at the renewed expiry | `LeaseFencedStream.cs` | **killed** | `AnUploadStopsWithinOneRecheckIntervalWhenTheOwnerGaveUpAndAnotherAttemptClaimed` |
| M52 | periodic row read removed | `LeaseFencedStream.cs` | **killed** | `AnEvidenceStreamStopsWhenTheOwnerGaveUpAndAnotherAttemptHoldsTheUnit` |
| M53 | known-expiry enforcement removed | `LeaseFencedStream.cs` | **killed** | `AnEvidenceStreamStopsAtItsLeaseExpiryInsideARecheckInterval` |
| M54 | interval boundary off by one (`<=`) | `LeaseFencedStream.cs` | **killed** | `AnUploadStopsWithinOneRecheckIntervalWhenTheOwnerGaveUpAndAnotherAttemptClaimed` |
| M55 | expiry boundary off by one (`<=`) | `LeaseFencedStream.cs` | **killed** | `AnUploadStopsAtItsLeaseExpiryInsideARecheckInterval` |
| M56 | ownership = any live lease | `VisualAttributeLifecycle.cs` | **killed** | `AnEvidenceStreamStopsWhenTheOwnerGaveUpAndAnotherAttemptHoldsTheUnit` |
| M57 | ownership = same worker (capability and attempt ignored) | `VisualAttributeLifecycle.cs` | **killed** | `AnUploadStopsWithinOneRecheckIntervalWhenTheOwnerGaveUpAndAnotherAttemptClaimed` |
| M58 | post-read check removed | `LeaseFencedStream.cs` | **killed** | `AnEvidenceStreamStopsAtItsLeaseExpiryInsideARecheckInterval` |
| M59 | row read ignores cancellation | `LeaseFencedStream.cs` | **killed** | `CancellationReachesTheInnerReadAndTheRowRead` |
| M60 | evidence interval measured after authorisation | `VisualAttributeEndpoints.cs` | **killed** | `AnEvidenceStreamStopsWithinOneRecheckIntervalOfItsAuthorisationAfterAHandOver` |
| M61 | artefact need not account for every leased crop | `AttributePredictionsValidator.cs` | **killed** | `AnArtefactThatOmitsALeasedCropFromAnAnalysedTrackPublishesNothing` |
| M62 | an Unavailable Track's reason need not be one a crop reports | `AttributePredictionsValidator.cs` | **killed** | `AnUnavailableTrackMustGiveAReasonItsObservationsReport` |
| M63 | crop-level integrity reasons not counted in health | `AttributePredictionsValidator.cs` | **killed** | `ACropThatFailedItsIntegrityCheckOnAnAnalysedTrackIsAnOperatorIncident` |
| M64 | a decode failure counted as an integrity incident | `AttributePredictionsValidator.cs` | **killed** | `ACropThatCouldNotBeDecodedIsNotAnIntegrityIncident` |
| M65 | crop incidents recorded only after a clean commit | `VisualAttributeCompletionService.cs` | **killed** | `ACorruptCropIsAnIncidentEvenWhenTheCommitLandedAmbiguouslyAndTheRetryIsAReplay` |
| M66 | a crop reported again counts again | `VisualAttributeIntegrityMonitor.cs` | **killed** | `ACorruptCropIsCountedOnceAcrossAFailedCommitAndItsRetry` |
| M67 | an accepted heartbeat is not worker presence | `VisualAttributeEndpoints.cs` | **killed** | `AHeartbeatingWorkerIsPresentForReadinessThroughALongAnalysis` |
| M68 | janitor scan capped before eligibility | `AttributeStagingJanitor.cs` | **killed** | `AReclaimableDirectoryListedAfterTheFirstThousandIsStillReclaimed` |
| M69 | janitor removals uncapped | `AttributeStagingJanitor.cs` | **killed** | `TheCycleCapBoundsRemovalsAndTheNextCycleTakesTheRest` |
| M70 | a cycle without a release skips the sweep | `VisualAttributeHostedService.cs` | **killed** | `WithTheReleaseRemovedTheSweepStillFailsAnAbandonedUnit` |
| M71 | the enabled host idles without a release | `VisualAttributeHostedService.cs` | **killed** | `WithTheReleaseRemovedTheEnabledHostKeepsRunningItsLifecycleCycle` |
| M72 | a renewal whose returned expiry has passed is accepted | `runner.py` | **equivalent** | the guard then reports the lease lost at once and the loop's own deadline check raises on its next pass: the outcome (`lease_lost`) is identical, so no test can observe it; the explicit check is kept as the stated rule, as in the vision worker |
| M73 | a late renewal rejected against the old deadline | `runner.py` | **killed** | `test_a_renewal_whose_response_arrives_after_the_old_deadline_is_honoured` |

Plan §17 mutations that have no code path in this design are recorded rather than invented: *delete a sealed object on rollback* (no deletion call exists; `AReclaimBetweenPhaseAAndPhaseCIsRefusedAndTheSealedOrphanIsSafe` asserts the orphan survives), *supersede on failed replacement* (supersession runs only inside a successful preferred Phase C; `APreferredCompletionSupersedesTheOldDefaultAndAFailedReplacementDoesNot`), *publish rows before the publication transaction* (rows are written only inside it; `AnAmbiguousCommitPublishesNothingAndTheRetryPublishesOnce`), *duplicate (run, identity) units* (the unique index arbitrates; `ConcurrentReconcilersCreateOneUnit`) and *let the fixture bypass production transport* (the fixture has no transport of its own; the E2E runs the real process).

### 6.1 Cold review

An independent read-only review of `ad01c2b..5c0ff30` found no P1. Dispositions:

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| 1 | P2 | Phase B/C ran on the request's cancellation token: a worker HTTP timeout or disconnect rolled back a publication the protocol says proceeds; the worker's heartbeat could cancel an in-flight `/complete` | **Fixed.** From the first side effect (the seal) the service runs on `CancellationToken.None`, bounded by the database command timeout; the worker stops its heartbeat before `/complete` (M36, M37) |
| 2 | P3 | A committed-but-ambiguous completion could be logged `lease_lost` when a later renewal met `not_running` | **Fixed** by the same heartbeat stop (M37) |
| 3 | P3 | Scoring threads outlived a cancelled attempt and could overlap the next attempt's | **Fixed.** One serial inference lane; no lease is taken while scoring still runs (M38) |
| 4 | P3 | Shutdown racing a lease loss could be swallowed | **Fixed** (`cancelling()` re-raise, M39) |
| 5 | P3 | An oversized evidence error body escaped transport classification | **Fixed** (`test_an_oversized_evidence_error_body_is_transport`) |
| 6 | P3 | Staging removed between Phase A and the artefact read gave 500 | **Fixed**: 409 `visual_attribute_prediction_not_staged` |
| 7 | P3 | Worker control responses were read whole before truncation | **Fixed**: every response streamed to its bound (`test_control_responses_are_read_to_their_bound`) |
| 8 | P3 | A claim commits the attempt before its Tracks are read; a database failure there costs one attempt with no grant | **Accepted.** The failure is a platform database fault; the attempt is bounded and reclaimed on lease expiry, exactly as a worker crash straight after a lease. Reading the grant inside the claim transaction would hold the row lock across a 10,000-Track read |
| 9 | P3 | Hosts configured with different releases would alternate activations and stop queueing | **Accepted as a stated assumption:** every platform host of one deployment serves the same release overlay (MAVI runs one platform host per installation; a rolling redeploy of a different release is a release change, and rollback semantics apply). Recorded here and in §7 |

### 6.2 Second review: ownership over the lifetime of an operation (PR #114 repair)

An independent review of head `97ff8f2` raised two findings; both were verified against plan §10, §12 and §13 and the code before any change, and both hold.

**Finding A — lease loss during an evidence read or upload (P2, fixed).** Authorisation happened only before the first byte: `Results.Stream` then copied the whole object, and the upload body streamed into staging, whatever happened to ownership meanwhile. Plan §10 requires that "lease loss/cancellation aborts streaming". A stale upload was never *usable* — staging is attempt-scoped and only the owning attempt's Phase A reads it — but it was still a write by a non-owner, and a stale evidence read delivered protected bytes after ownership ended.

*Invariant:* a lease-scoped stream is authorised for its lifetime. It continues only while the same worker, capability and attempt hold an unexpired lease; when that stops being true — plain expiry, a reclaim, or the owner's own failure followed by another attempt's claim — no further byte is delivered or staged. Mechanism: `LeaseFencedStream` brackets every read with a clock comparison and reads the unit's row (one primary-key read, no lock) only when the last-granted expiry is reached (a heartbeat may have renewed it) or once `RecheckInterval` (5 s) has passed since ownership was last observed — first by the request's authorisation, then by each read of the row (§6.3). That is exact because a unit changes executor before its lease expires only after its owner's own failure, which the interval catches. Evidence lost after the first byte aborts the connection (the worker sees an incomplete transfer and re-authorisation then reports the lost lease); lost before it, or during an upload, is a 409 `visual_attribute_lease_invalid`, and the staging store's temporary file is discarded — create-once semantics unchanged.

**Finding B — Phase B versus the platform sweep (P2, fixed).** Phase A released its row lock before sealing, and the sweep's "a publishing unit is locked" held only for the Phase A and C transactions. A final attempt whose lease expired during Phase B was failed `visual_attribute_attempts_exhausted`, and any unit whose absolute deadline passed during Phase B was failed `visual_attribute_deadline_exceeded`; Phase C then refused a completion no one else owned — contrary to §13 ("lease expiry by itself does not invalidate Phase C if no reclaim has occurred"), and dependent on when the sweep happened to run.

The existing state model represents the required invariant, so no new lifecycle state was introduced. *Invariant:* a completion validated at Phase A while its lease is live holds the unit for one publication window — a lease duration from Phase A, never more than one lease past the absolute deadline — and within it no reclaim, exhaustion or deadline transition can take the unit; Phase C remains fenced on ownership, not on the clock. Mechanism: Phase A extends the owner's lease (`BeginPublication`, in its existing short transaction); every rule that already waits for an expired lease therefore waits for the window; the deadline transition now also requires no live lease (in SQL, so a batch of protected units cannot starve an abandoned one, and in the domain); a heartbeat never shortens a lease. An ordinary lease is still capped at the deadline, so the deadline behaves exactly as before for every unit that is not publishing. When the window lapses unpublished — a crashed platform process, a stalled seal — reclaim, exhaustion and deadline proceed as for any expired lease, and the old attempt's Phase C is refused by ownership: abandoned work stays bounded by one lease. Replay precedence, attempt and capability fencing, atomic publication and the visibility barrier are unchanged; all state is in PostgreSQL, so the rule holds across hosts.

**Discriminating tests** (`VisualAttributeLeaseLifetimeTests`, real PostgreSQL; transfer tests on a real Kestrel socket with a raw two-half upload, because the in-memory test server buffers a request body before the endpoint runs, and gated so that ownership changes only once the platform is already streaming). Against the previous head `97ff8f2`, the ten tests targeting A and B failed and the three controls passed:

| Test | `97ff8f2` | fixed |
|---|---|---|
| `TheSweepCannotExhaustAFinalAttemptWhosePublicationIsInFlight` | fail | pass |
| `TheDeadlineSweepCannotFailAPublicationValidatedBeforeTheDeadline` | fail | pass |
| `AnAbandonedPublicationOfTheFinalAttemptIsExhaustedOnceItsWindowLapses` | fail | pass |
| `AnAbandonedPublicationPastTheDeadlineIsFailedOnceItsWindowLapses` | fail | pass |
| `APublicationWithinItsWindowIsNotReclaimable` | fail | pass |
| `APublicationOutlivingItsWindowIsReclaimedAndRefusedAtPhaseC` (control) | pass | pass |
| `AnEvidenceStreamStopsWhenOwnershipIsReclaimedMidRead` | fail | pass |
| `AnEvidenceStreamStopsWhenTheLeaseExpiresMidRead` | fail | pass |
| `AnEvidenceStreamStopsWhenTheOwnerGaveUpAndAnotherAttemptHoldsTheUnit` | fail | pass |
| `AnEvidenceStreamKeptAliveByHeartbeatsCompletes` (control) | pass | pass |
| `AnUploadStopsWhenOwnershipIsReclaimedMidBodyAndStagesNothing` | fail | pass |
| `AnUploadStopsWhenTheLeaseExpiresMidBody` | fail | pass |
| `AnUploadWhoseLeaseHoldsThroughoutIsStaged` (control) | pass | pass |

Added with the repair: `APublishingUnitNeverStarvesTheDeadlineSweepOfAnAbandonedOne` (sweep batch liveness) and five domain tests (`APublicationWindowHoldsTheUnitForOneLeaseFromPhaseA`, `APublicationWindowOutlivesTheDeadlineByAtMostOneLease`, `AHeartbeatNeverShortensAPublicationWindow`, `OnlyTheActiveOwnerCanBeginAPublication`, `TheFinalAttemptIsNotExhaustedWhilePublishing`). Existing race tests — reclaim between Phase A and C, expiry without reclaim, crash after seal, ambiguous commit and exact replay — pass unchanged.

**Adjacent review — P3, not changed:** (1) a unit leased before an operator *lowers* `MaximumAnalysisDurationSeconds` may hold an ordinary lease past its new deadline; the deadline transition now waits for that lease, at most one lease — bounded and consistent with the invariant. (2) `visual_attribute_evidence_read` (2000) is now logged when the object has been fully served rather than when serving starts; an interrupted read logs 2004 (lease lost) or nothing (client cancellation).

### 6.3 Third review: the fence's first interval (PR #114 repair)

A cold review of `08d1f60` reported that `LeaseFencedStream` scheduled its first ownership read at the granted lease expiry, so a hand-over by `/fail` and an immediate claim could go unseen for most of the original lease. Verified against the code before any change: the constructor already scheduled the first read one interval after the stream was built, not at the granted expiry, and `AnEvidenceStreamStopsWhenTheOwnerGaveUpAndAnotherAttemptHoldsTheUnit` (M46) already guarded that. **The finding as stated did not reproduce.** Tracing the stream's lifetime found a narrower, real form of it (P2, fixed): the interval was measured from *building the stream*, not from the *observation of ownership*. For evidence, the authorisation reads the row and the object is then opened; opening time went unfenced, so a slow open followed by a hand-over let a superseded attempt read for up to open time + 5 s after the last observation. `AnEvidenceStreamStopsWithinOneRecheckIntervalOfItsAuthorisationAfterAHandOver` (open takes 4 s, hand-over, stream released exactly 5 s after authorisation) received the whole crop at `08d1f60`.

*Invariant:* every byte a fenced stream hands on was read no later than one `RecheckInterval` after the unit's row last showed that the attempt owned it, and never at or after the lease expiry that row reported. Mechanism: the endpoint takes the time before its authorisation reads the row and passes it to the fence (`verifiedAtUtc`); the first read of the row is due one interval after it, each later one an interval after the previous read began, and a known expiry is enforced by the clock alone. The upload's fence starts with no known expiry and reads the row before its first byte. No per-chunk database access: `ReadsWithinTheIntervalAndTheLeaseNeverTouchTheDatabase`.

Tests added: the evidence case above; `AnUploadStopsWithinOneRecheckIntervalWhenTheOwnerGaveUpAndAnotherAttemptClaimed` (the *same* worker reclaims, so only attempt and capability distinguish it; released exactly one interval after the first fenced read, the first lease far from expiry); `AnEvidenceStreamStopsAtItsLeaseExpiryInsideARecheckInterval` and `AnUploadStopsAtItsLeaseExpiryInsideARecheckInterval` (expiry at the exact instant, inside an interval); and `LeaseFencedStreamTests` (schedule to the tick, same-owner revalidation, renewal, bytes read across a loss, end of stream, cancellation, a failing row read, disposal). The upload tests now signal once the first bytes have passed the fence rather than on entry to staging, so a hand-over provably follows an ownership observation. Against `08d1f60` only the evidence authorisation-origin test failed; the others pass there and are retained as boundary coverage, and each schedule mutant (M49–M60) is killed by at least one of them.

*Residual, P3, not changed:* bytes read while owned may still be delivered after a loss while a response write waits on back-pressure — at most one 80 KiB copy buffer plus transport buffers, all read under ownership. Closing that would need a fence on the write side for no change in what a superseded attempt can learn.

### 6.4 Automated review of `15967b3`: evidence coverage and crop-level integrity

Two findings from an automated reviewer, both verified against the code and fixed.

**Leased crops could be left out of the artefact (P2 by this record's scale; the reviewer labelled it P1).** The artefact validator refused foreign and duplicate Observation ids but never required a Track's observations to *equal* its leased set. A malformed worker could omit a usable crop and still publish — including an Unavailable `evidence_missing` Track with no observation to show for it — contrary to AGENTS.md's evidence-traceability rule. The lease hands the worker exactly the Track's accepted EvidenceCrops, the same set the validator's scope holds, and the worker reports every one (`runner.py`), so the stricter rule costs an honest worker nothing: the real-process end-to-end passes unchanged. *Invariant:* for every Track the artefact accounts for each leased crop exactly once, and an Unavailable Track's reason is one its crops report.

**Crop-level integrity failures were invisible to operator health (P2).** Health counted completion incidents from the Track's reason only. When one crop failed its SHA-256 and another scored, the Track was Analysed with no reason, and the corrupt accepted object never reached `/api/health`; the evidence endpoint cannot detect it, because the worker hashes what it reads. The artefact validator now counts the crops reported `evidence_integrity_failed` or `evidence_missing`, and that count is what the completion service records — one incident per crop, so an Unavailable Track with two corrupt crops is two. `evidence_decode_failed` is not an integrity incident.

Tests (all failed on `15967b3` before the fix, except the decode control): `AnArtefactThatOmitsALeasedCropFromAnAnalysedTrackPublishesNothing`, `AnArtefactThatOmitsEveryLeasedCropOfAnUnavailableTrackPublishesNothing`, `AnUnavailableTrackMustGiveAReasonItsObservationsReport`, `ACropThatFailedItsIntegrityCheckOnAnAnalysedTrackIsAnOperatorIncident`, and the control `ACropThatCouldNotBeDecodedIsNotAnIntegrityIncident`. `ACompletionPublishesFactsAndTheSealedArtefactAndTheRunBecomesReady` now expects two incidents (its Unavailable Track reports both crops corrupt).

### 6.5 Automated review of `73ca2b2`: incidents across ambiguous commits; heartbeat presence

Two further findings, both verified and fixed.

**Crop incidents lost when a commit lands but reports failure (P2).** §6.4 recorded crop-level incidents after the commit. A commit that lands and then throws returns `visual_attribute_publication_ambiguous` before that point, and the worker's identical retry is answered by committed replay, which never reaches it either, so the incidents never reached `/api/health`. *Invariant:* a crop the owning attempt reported missing or corrupt is one completion incident, counted once, whether or not the publication lands. Mechanism: the incidents are recorded — and logged as an Error, event 1994 — as soon as the owner's artefact validates (after Phase A, before the seal), and the monitor counts each crop once, so the retry of an ambiguous commit, or a later attempt reading the same crop, adds nothing. The remembered crops are bounded (65,536, oldest forgotten first). The counter is process-scoped, like the evidence-read counter beside it; the Error log is the durable record. Durable per-analysis storage would need a schema change and was not warranted.

**A busy worker read as absent (P2).** Readiness treated only a lease poll as proof of a READY worker, but a worker running an analysis polls again only when it finishes. After `WorkerPresenceSeconds` (180 s) a healthy long analysis read `no_ready_attributes_worker`, a false operator alarm. *Invariant:* a worker is present for an identity while it has, within the window, polled for it or had a renewal of a lease of it accepted. A worker leases only while READY, so an accepted renewal is the same proof as a poll; a refused renewal proves nothing.

Tests: `ACorruptCropIsAnIncidentEvenWhenTheCommitLandedAmbiguouslyAndTheRetryIsAReplay` and `AHeartbeatingWorkerIsPresentForReadinessThroughALongAnalysis` failed on `73ca2b2`; `ACorruptCropIsCountedOnceAcrossAFailedCommitAndItsRetry`, `ARefusedHeartbeatIsNotPresence` and `VisualAttributeIntegrityMonitorTests` (once per crop, bound) are the controls. A test seam after the commit (`AfterCommit`, beside the existing `BeforeCommit`) models a commit that lands but reports failure.

### 6.6 Automated review of `2b17903`: janitor scan, release removal, late renewals

Three further findings, all verified and fixed.

**The attribute janitor capped its scan, not its work (P2).** It stopped listing after 1,000 analysis directories, before judging any. When the first 1,000 listed were live (Queued, Running, or unknown within their grace), every reclaimable directory behind them was skipped on every cycle. *Invariant:* every directory is judged each cycle; the cap bounds the removals a cycle performs, and the rest wait for the next — as the VisionJob janitor does. Rows are read in batches of 1,000.

**Removing the release stopped the lifecycle (P2).** With the feature enabled and the release resolving `NotConfigured` (the role removed, or its binding disabled), the hosted service returned before its first cycle, so units already Running were never failed on exhaustion or deadline and their staging was never reclaimed. *Invariant:* without a release nothing new is activated or queued, but the sweep and the janitor run on schedule, so every existing unit still reaches an outcome. Only `VisualAttributes:Enabled=false` idles the host.

**The worker discarded a renewal that arrived late (P2).** After an accepted heartbeat, the worker compared the clock with the *old* deadline and cancelled a valid attempt as lease-lost when the response arrived after it (latency, scheduling, clock skew). The platform renews only a live lease and never shortens one, so the returned expiry is authoritative. *Invariant:* an accepted renewal replaces the deadline; only a returned expiry that has itself passed is a lost lease — the vision worker's rule.

Tests: `AReclaimableDirectoryListedAfterTheFirstThousandIsStillReclaimed` (the one removable directory is the one the listing yields last), `WithTheReleaseRemovedTheSweepStillFailsAnAbandonedUnit`, `WithTheReleaseRemovedTheEnabledHostKeepsRunningItsLifecycleCycle` and `test_a_renewal_whose_response_arrives_after_the_old_deadline_is_honoured` failed on `2b17903`; `TheCycleCapBoundsRemovalsAndTheNextCycleTakesTheRest` and `test_a_renewal_that_returns_an_expiry_already_past_is_a_lost_lease` are the controls.

## 7. Deferred and out of scope

- **Explicit re-analysis request** (ADR-013 §9: "an explicit, bounded request per run or camera/time window") has no API in S2b; the plan does not scope one. Supersession and rollback are proven with a sibling unit inserted directly (`APreferredCompletionSupersedesTheOldDefaultAndAFailedReplacementDoesNot`), standing in for that request.
- Real Model Packs (S2c), search v4 and E5–E8 (S3), UI (S4), Production/CUDA promotion, a generic IntelligenceJob: not in S2b.
- **One release per deployment:** all platform hosts must be configured with the same `VisualAttributes` release overlay (cold review #9).
- The worker reports `cuda` unsupported (`attribute_device_unsupported:cuda`) — the fixture is CPU-only; device policy for real models is S2c's.

## 8. Final verification

Recorded at the final head in the pull request.
