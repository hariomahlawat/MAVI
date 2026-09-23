# Stage 2 S1 — Track Evidence Set: implementation-plan review resolution

**Date:** 2026-09-23  
**Reviewed head:** PR #74 `8c310acc19e5cc04a30efb3dc50dcdbd236b7b3d` on `main@6809606e596d121186b5244869760073fe82072a`  
**Scope:** planning/documentation only. No S1 code was implemented. Findings were verified against `tracking/interfaces.py`, `tracking/bytetrack.py`, `tracking/fixture.py`, `pipeline/process_video.py`, `pipeline/finalization.py`, `common/analytical.py`, `storage/artifact_*`, `worker/client.py`, `common/control_plane.py`, `WorkerContractRules.cs`, `VisionJobEndpoints.cs`, `VisionCompletionRequestLimitMiddleware.cs`, `ProcessingResultStore.cs`, the EF configurations, `TrackDetailResponse.cs`, `TrackSearchRepository.GetDetailAsync`, `api/tracks.ts` and the tracker/pipeline/completion tests.

## Findings

| ID | Priority | Finding | Evidence | Correction |
|---|---:|---|---|---|
| S1-01 | P1 | ADR-013 §4 defined EarlyDiverse/LateDiverse by the Track's first/last **temporal third**. The final duration is unknown until retirement and frames are discarded after decode, so a one-pass selector cannot pick "best in the last third" without retaining candidate pixels for the whole Track — the very unboundedness the Evidence Set exists to avoid. | `process_video.py` single pass; `iter_frames` streams and discards; retirement is the first point the duration is known | **Architecture amendment, ratification requested.** ADR-013 §4 amended in place: EarlyDiverse = best qualified candidate in an anchored early window (`earlyWindowMs` from Track start, frozen when the window closes); LateDiverse = most recent qualified view refreshed at most once per `lateRefreshIntervalMs`. Intent preserved (one early and one late well-separated view); exactly one encoded candidate per role at any time. Parent plan §8.2 and S1 plan §2/§7.2 aligned. |
| S1-02 | P1 | The "live-Track memory bound" was still false at the type level: `ProcessedTrack` carries `trajectory: tuple[TrajectoryPoint, ...]` and `ArtifactPublisher.publish_track` copies every point into it, so the **result object** retains all points for all Tracks until completion even after retirement-time staging. | `common/analytical.py` `ProcessedTrack.trajectory`; `artifact_publisher.py` L60 | S1 plan §6.4: `ProcessedTrack` becomes descriptor-only; trajectory invariants move to `prepare_track`; three memory classes (live / completion-metadata / staging) defined and bounded separately; canonical completion ordering stated. |
| S1-03 | P2 | The retirement margin "one accepted-frame interval" is ambiguous under variable frame rate and did not require the id to be absent from the update. | `test_native_time_budget_retains_inside_and_expires_beyond_one_second`: the backend drops a lost track at the first update whose media time exceeds the budget and re-spawns a new native id | S1 plan §2/§6.2: retire at update U iff the id is absent from U's confirmed outputs and `U.offset_ms − last_seen > budget_ms + 1000/referenceFrameRate` (nominal interval from the profile); per class domain; evaluated on every accepted frame; map pruned so it equals the live set. |
| S1-04 | P2 | Representative fallback ("next-best candidate if the cap cannot be met at the floor") implied retaining alternate candidates; the plan did not say how many. | Arithmetic: at the 128 px floor a crop is ≤ 128×128 px = 49,152 raw bytes < 64 KiB | S1 plan §7.3: the ladder always terminates admitted; the fallback branch is unreachable and kept only as a fail-closed invariant; no alternates retained. Fixed reduction ladder specified; determinism promised per runtime variant only. |
| S1-05 | P2 | Selector re-encode churn was unbounded: replacing a candidate on every score improvement re-encodes a JPEG per frame per live Track. | `_is_better_representative` replaces on any strict improvement | S1 plan §7.2: replacement epsilon, NearView growth hysteresis, early-window freeze and late refresh interval bound re-encodes per Track; occlusion proxy uses all detections of the frame, both classes. |
| S1-06 | P2 | The 250-byte descriptor estimate was provisional; measured compact JSON gives ≈ 877 B per v2 Track and ≈ 2.3 KB per four-observation v3 Track — ≈ 22 MiB at 10,000 Tracks against a 32 MiB limit. | serialisation of realistic DTO shapes | S1 plan §7.7: engineering estimate recorded; new limit 48 MiB pending the mandated worst-shape contract test; stop condition if measured > 32 MiB. |
| S1-07 | P2 | Cross-attempt staging cleanup lacked an authority argument; a filesystem-only rule could be misread as trusting directory names. | `VisionJobLease.attempt_count`; `ProcessingOrchestrator.LeaseAsync` increments under `FOR UPDATE`; completion refuses `vision_job_attempt_mismatch` | S1 plan §6.5: authority is the platform lease's attempt number; delete only `attempt-k` for k < N; never k ≥ N or other jobs; stale N−1 cannot delete N. |
| S1-08 | P2 | Version scope was unstated: the whole control plane (lease, heartbeat, fail) is `"2.0"`, not only completion; endpoints check equality in four handlers and `ProcessingResultStore` L52. Dual-accept justification was asserted, not argued. | `VisionJobEndpoints.cs`; `control_plane.py` `Literal["2.0"]` on every message | S1 plan §7.5/§7.6: only the completion message moves to `"3.0"`; the other three stay `"2.0"`; digest domain tags per version; dual-accept justified by idempotent replay (`CompletePersistsAuthoritativeIntelligenceAndExactReplayIsIdempotent`) and in-flight workers; deployment order and the new-worker/old-platform failure mode stated. |
| S1-09 | P2 | Task 10 does not trigger on `mavi_vision/pipeline/**` or `tracking/**`, so S1.1's "runs Task-10 regression" would not happen automatically; the qualification record's `pipelineProfileSha256` will change with the profile schema bump. | `task10-runtime-qualification.yml` path filters; `verify_qualification_relationships` | S1 plan §10.2: `workflow_dispatch` on S1.1's head with run ids recorded; trigger extension in S1.2; qualification record SHA re-derived in the same PR, remaining `pending`; explicit non-claims. |
| S1-10 | P2 | S1.2 combined platform migration/dual-accept and worker v3 emission in one PR, contradicting the plan's own deployment order. | S1 plan §14 order vs §16 | S1 plan §16: S1.2a platform (migration, contracts, dual-accept, golden fixture, limit) then S1.2b worker (selector, encoder, admission, emission). No incompatible intermediate state: the platform is bilingual before any worker speaks v3. |
| S1-11 | P3 | Observation schema left role/rank consistency and the legacy-value guard implicit; crop FK stays `SetNull`. | `ObservationConfiguration.cs` `OnDelete(SetNull)` | S1 plan §8.1: `ObservationType` keeps its name with the four-role vocabulary; migration fails if legacy values exist; CHECK ties role↔rank; `SelectionScore` double with range CHECK; FK → Restrict; historical rows get rank 0 and score = quality_score. |
| S1-12 | P3 | Worker Track-id ordering vs platform `LocalTrackNumber` was flagged as unproven. | `VisionResultValidator` `StringComparer.Ordinal` sort; `ProcessingResultStore` `index + 1`; ids are ASCII `[a-z0-9._-]` | S1 plan §7.4: proven equivalent (Python code-point sort = .NET ordinal for ASCII; zero padding); contract test pins it. |
| S1-13 | P3 | Omitted supplemental staging deletion was optional; UI accessibility/loading states and the scope guard were thin; guarantee→test mapping was implicit. | — | S1 plan §7.4 (must delete), §9.4, §12.4/§12.6, §6.6 tests 13–17. |

## Verdict

**READY FOR IMPLEMENTATION AFTER FINAL OWNER REVIEW**, conditional on the owner ratifying the ADR-013 §4 amendment (S1-01). Everything else is plan precision, not architecture.

## Boundary

No S1 feature implementation was performed. PR #74 remains open and draft.


## Final owner review (2026-09-23)

The owner review ratified **S1-01**: replacing final-duration temporal thirds with a streamable anchored early window and refreshed trailing late view is accepted as an amendment to ADR-013 §4. The amendment preserves the architectural intent (bounded, deterministic, model-neutral early/late diversity) while making it implementable in the single-pass pipeline.

One additional plan defect was found during this review:

| ID | Priority | Finding | Correction |
|---|---:|---|---|
| S1-14 | P2 | S1-04 treated `128×128×3 = 49,152` raw RGB bytes as a proof that the JPEG at the floor can never exceed the 64 KiB Representative cap. Encoded JPEG size is not mathematically bounded by raw RGB size, so the plan had eliminated Representative fallback using an invalid proof and diverged from ADR-013's fail-closed fallback semantics. | §7.3 now treats floor admissibility as a measured/contract-tested property. A bounded online reservoir of next-best qualified Representative candidates is retained as encoded bytes; the reservoir size K is profile/versioned and chosen from measurement. If the primary floor encoding exceeds the cap, fallback candidates are tried in deterministic score order; if none can be admitted, the VisionJob fails. Adversarial encoder tests are mandatory on every qualified runtime variant. |

### Owner verdict

With S1-01 ratified and S1-14 corrected, no open P1/P2 planning defect is known at this review point. Exact-head CI still governs merge readiness.

No S1 feature code was implemented.
