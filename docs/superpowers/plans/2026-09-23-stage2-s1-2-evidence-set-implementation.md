# MAVI Stage 2 — S1.2 Track Evidence Set: implementation plan

**Status:** Implementation-ready plan, revision 3 (after the second independent cold review; janitor precision only). **S1.2a implemented** (platform v3 and staging janitor; deviations D1–D3 recorded in its PR). **S1.2b implemented** (worker trajectory spool; implementation notes and deviations E1–E7 in §16.1). **S1.2c implemented and merged in PR #79** (`main@2060599a9786651f36071742034076369520d0ce`; worker Evidence Set and completion 3.0; deviations E8–E24 and test mapping in §16.2). E8 (two-tier Representative) was **accepted by the owner on 2026-09-24** (ADR-013 §4 amendment). The §5 measurement note is **complete**. It covers the scripted corpus plus MOT17-02-FRCNN and MOT17-13-FRCNN at 1920×1080, through the production RTMDet → ByteTrack → Evidence Set path (E23). Its finding **F1** (the quality-v1 occlusion proxy counted sub-floor detections) was fixed on the owner's decision as scorer **`quality-v2`** (E24; ADR-013 §4 occlusion-proxy amendment, accepted 2026-09-24). The measurement was then re-run from scratch: fallback Representatives fell from 58.7 % to 14.3 %, and every selector default was re-adjudicated and retained. The profile SHA is `503225be…23fb`, and the qualification record is rebound with every gate `pending`.
**Date:** 2026-09-23  
**Baseline:** `main@4b6141f52d6d6a0a72de664e60b8cd4441487799` (PR #75, S1.1 merged)  
**Parent plan:** `docs/superpowers/plans/2026-09-23-stage2-s1-track-evidence-set.md` §7–§8, §10.2, §12–§16  
**Governing architecture:** ADR-005, ADR-006, ADR-007, ADR-009, ADR-013 (§3–§7, §19), Stage-2 acceptance register rows B1–B4 (B5 is S1.3; B6 is S1.4)  
**Non-goals:** everything the parent plan §3 excludes, plus the Track-detail read contract and Evidence Set viewer (S1.3) and qualification claims (S1.4)

This plan converts the parent S1 architecture into three independently mergeable and deployable PRs:

- **S1.2a — platform first:** the platform accepts completion **v2 and v3**, persists the Evidence Set, seals `EvidenceCrop` artefacts, advertises which completion versions it accepts, and gains the **staging janitor** that reclaims worker staging with database authority. The worker on `main` still emits v2.
- **S1.2b — worker trajectory spool:** the worker stops holding a Track's trajectory in RAM; points are spooled to attempt-scoped staging in fixed chunks and streamed into the byte-identical canonical v1 artefact at retirement. No wire change. This closes the live-memory bound before any Evidence Set bytes are added to it.
- **S1.2c — worker Evidence Set + v3:** in-loop selection/encoding/admission and v3 emission; the worker refuses to start against a platform that does not accept v3.

Revision 2 resolves two P1 findings from the first cold review — the total live-memory bound was not actually independent of Track duration (§9, §6.3), and post-completion staging cleanup was not crash-safe (§6.5, §10.5) — and records every knock-on change in §17. Where this plan corrects the parent plan or touches an ADR, it says so; nothing is changed silently.

---

## 1. Purpose

S1.1 gave the pipeline exact-once Track retirement and whole-Track finalisation, but three things are still unbounded or unowned:

1. the Representative is one raw RGB crop per live Track, encoded at JPEG q90 with no resize or size cap, and the wire is v2 (one thumbnail per Track);
2. each live Track holds its full trajectory in RAM as `list[TrajectoryPoint]` (≈ 80 B per detection), which grows for as long as the Track lives — a Track that spans the whole video makes live memory grow with video length;
3. nothing removes the staging of a *successfully completed* attempt; under v3 that staging can reach several GiB per job.

S1.2 delivers:

1. a deterministic, bounded, model-neutral **Track Evidence Set** (Representative + NearView + EarlyDiverse + LateDiverse) selected in the single decode pass, with **in-loop encoding** so live memory holds bounded JPEG bytes, never raw crops;
2. **bounded per-live-Track memory independent of Track and video duration**, by spooling trajectory points to attempt-scoped staging in fixed chunks and producing the canonical, byte-identical trajectory v1 artefact by streaming at retirement;
3. **completion schema v3 / digest v3** carrying observation descriptors, validated, sealed and persisted transactionally by the platform;
4. a **crash-safe staging lifecycle**: a platform-owned janitor with database authority reclaims completed, failed and superseded attempts' staging within a stated window, with the worker's own cleanup as a fast path only;
5. a **safe rollout**: platform bilingual before any worker speaks v3; a v3 worker cannot emit v3 at a platform that does not accept it.

---

## 2. Current state (verified at `4b6141f`)

### Worker (`src/vision/mavi_vision`)

| Fact | Where |
|---|---|
| `Tracker.update()` returns `TrackerUpdate(candidates, retired_track_ids)`; `VideoProcessor` finalises each Track once at retirement or EOS through `_finalise_track` | `pipeline/process_video.py` L139–230 |
| `_TrackAccumulator` holds `trajectory: list[TrajectoryPoint]` and `representative: _RepresentativeCandidate(observation, crop: np.ndarray)` — one raw RGB crop **and all trajectory points** per live Track | `process_video.py` L46–57 |
| `_accumulate` does **not** receive the frame's `detections`; the occlusion proxy has no input today | `process_video.py` L155, L246 |
| Representative replacement is any strict improvement on `(quality, confidence, -offset, -frame)` — unbounded re-selection | `process_video.py` L325–345 |
| `representative_quality = clamp(0.45·sharpness + 0.35·area/0.20 + 0.20·edgeMargin/0.10)`; sharpness = mean absolute gradient of the grey crop / 64 | `quality/scoring.py` |
| The only JPEG encoder: Pillow, `quality=90, optimize=False, progressive=False, subsampling=2`, no resize, no cap | `pipeline/finalization.py` L106–120 |
| `prepare_track` validates the whole point tuple (count = detections, strictly increasing offsets, inside the Track) and calls `serialize_trajectory(points)`, i.e. `msgpack.packb({"v":1,"points":[[offset,cx,cy],…]}, use_bin_type=True)` — requires every point in memory | `finalization.py` L40–115, `video/trajectory.py` |
| The trajectory v1 bytes are consumed by `deserialize_trajectory` (worker), `TrajectoryDecoder.cs` (Scene Analytics; **`MaximumSamples = 1_000_000`**, `MinimumSamples = 2`) and `trajectory.ts` (web); golden fixture `tests/fixtures/scene-analytics/worker-trajectory-v1.*` | `video/trajectory.py`; `Mavi.Application/…/Engine/TrajectoryDecoder.cs` L21–60 |
| `ProcessedTrack` is descriptor-only (S1.1); `RepresentativeObservation` carries `quality_score` | `common/analytical.py` |
| Staging keys `thumbnails/{trackId}.jpg`, `trajectories/{trackId}.msgpack`; `write_bytes(relative_name, content: bytes, …)` computes size/SHA over an in-memory payload, writes a temp file with `fsync`, then atomically publishes; **no append, no streamed write, no single-object delete** | `storage/artifact_store.py`, `artifact_store_posix.py` L45–120, `artifact_store_windows.py` |
| `cleanup()` removes the current attempt; `cleanup_superseded_attempts()` removes lower attempts of the same job (S1.1); **neither runs after a successful `complete()`** | `worker/runner.py` L330–370 |
| Pipeline profile schema is `Literal["1.0"]`, `extra="forbid"`; its SHA-256 enters provenance and the completion digest; `models/qualifications/rtmdet-m-coco-phase1-v1.json.pipelineProfileSha256` must match (`verify_repo`) | `runtime/profile.py`, `runtime/qualification.py` L986–1030 |
| Wire models: every message `schema_version: Literal["2.0"]`; `VisionJobComplete` sums thumbnail+trajectory bytes against 512 MiB; **the worker computes no digest** | `common/control_plane.py`, `worker/client.py` |

### Platform (`src/platform`)

| Fact | Where |
|---|---|
| `WorkerContractRules.SchemaVersion="2.0"`, 10,000 Tracks, 32 MiB body, 64 MiB/artefact, 512 MiB aggregate | `Mavi.Contracts/Worker/WorkerContractRules.cs` |
| All four handlers compare `SchemaVersion` for equality; `VersionProblem()` says "2.0 is required"; `ProcessingResultStore` L52 re-checks equality under the row lock | `VisionJobEndpoints.cs` L24/33/53/69/106 |
| Validator requires exact staging keys, sorts Tracks ordinally, computes the digest with tag `mavi:vision-completion-digest:v2` — **digest is .NET-only** | `VisionResultValidator.cs` L130–140, L175, L218–354 |
| Store seals thumbnail then trajectory per Track into the evidence root, writes rows, compensates newly sealed keys on failure; replay re-validates and compares digests, never re-seals; **the store never touches staging after sealing** | `ProcessingResultStore.cs` L143–361 |
| The platform reads staging through `IMediaStore.OpenReadAsync` on the shared media root (`MediaStorage:RootPath`); `LocalMediaStore` also has `WriteAsync`, `ExistsAsync`, `DeleteAsync(storageKey)` (single file, root-escape checked) and refuses symlinked directories; `StorageRootSafety` resolves link targets | `Storage/LocalMediaStore.cs` L107–168, `StorageRootSafety.cs` |
| `VisionJob` is created `Queued` with `AttemptCount = 0`; `Lease` sets `Leased` and increments `AttemptCount`; `Complete`/`Fail`/`Exhaust` are terminal (`Completed`/`Failed`). **No method returns a job to `Queued`**, and **no method produces `Cancelled`** (the enum value exists; only `ProcessingRun` has a cancellation path). Retrying a failed video (`QueueAsync`) creates a **new** `ProcessingRun` and a **new** `VisionJob`; `ProcessingFailureRecoveryTests` asserts two jobs after a retry | `Mavi.Domain/Processing/VisionJob.cs`, `VisionJobStatus.cs`, `ProcessingOrchestrator.QueueAsync`/`LeaseAsync`, `tests/Mavi.IntegrationTests/ProcessingFailureRecoveryTests.cs` L100 |
| Platform background-service precedent: `SceneAnalyticsHostedService : BackgroundService` in the API host (ADR-011 decision 1 placement) | `Mavi.Api/SceneAnalytics/SceneAnalyticsHostedService.cs` |
| Task-13 retention model: "a later garbage collector may reclaim … abandoned staging attempts" — deferred, never specified | `docs/superpowers/plans/2026-09-13-task-13-vision-result-persistence.md` §9.3 |
| `Observation` has `ObservationType` (string column, **no CHECK**), frame/offset/bbox(float)/confidence/quality, `ThumbnailArtifactId` FK **SetNull**; enum `{TrackStart, Representative, BestQuality, TrackEnd}`, only Representative ever written | `Observation.cs`, `ObservationConfiguration.cs` |
| `ArtifactType {SourceVideo, Thumbnail, TrackTrajectory}`; content serving allow-lists `Thumbnail+image/jpeg` and `TrackTrajectory+application/msgpack` | `ContentReadService.cs` L107–135, `ContentCatalog.cs` L56–93 |
| Migrations are hand-written `yyyyMMddHHmmss_VerbNoun.cs` + snapshot; integration tests need `MAVI_TEST_DB_CONNECTION` (Quality Gate provides pgvector/pg18); storage-safety tests run on Windows and Linux in `task14-read-security.yml` | `Persistence/Migrations/`, `tests/Mavi.IntegrationTests/PostgresFixture.cs`, `.github/workflows/task14-read-security.yml` |
| Contract fixtures: `contracts/schemas/vision-job-complete-v2.schema.json`, example, conformance vectors; `verify_repo.check_contracts` hard-codes the v2 stems | `contracts/`, `tools/verify_repo.py` L828–853 |

---

## 3. Architecture

### 3.1 Component map (worker)

```
DecodedFrame + detections ──► Detector ──► Tracker.update ──► TrackerUpdate
                                                                 │ candidates
                                                                 ▼
          ┌──────────────────── VideoProcessor (orchestration only) ────────────────────┐
          │  per candidate:                                                              │
          │    TrackState.record(frame, candidate)     scalars + TrajectorySpool.append   │
          │    EvidenceSelector.observe(FrameContext, candidate, TrackState)   [S1.2c]    │
          │        ├─ QualityScorer.score(...) -> CandidateQuality                        │
          │        └─ EvidenceEncoder.encode(crop, role) -> EncodedImage | None           │
          │  per retired id / at EOS:                                                      │
          │    TrajectorySpool.finalise() -> streamed canonical v1 artefact (store)        │
          │    EvidenceSelector.resolve(track) -> tuple[SelectedEvidence]      [S1.2c]    │
          │    prepare_track(...) -> PreparedTrack (scalars + evidence payloads)           │
          │    ArtifactPublisher.publish_track -> ProcessedTrack (descriptors)             │
          │  after loop:                                                        [S1.2c]    │
          │    EvidenceAdmission.admit(finalised) -> admitted set + omitted keys           │
          │    ArtifactPublisher.remove_omitted(keys)                                      │
          └────────────────────────────────────────────────────────────────────────────┘
          runner: complete() ──► store.cleanup()  (fast path; the platform janitor is authoritative)
```

New modules (all under `src/vision/mavi_vision/`):

| Module | Responsibility | Interface (owner) | PR |
|---|---|---|---|
| `video/trajectory_spool.py` | per-live-Track bounded point buffer; spills fixed chunks to attempt staging; streams the canonical v1 artefact at retirement | `class TrajectorySpool: def append(offset_ms, cx, cy) -> None; def finalise(sink: Callable[[Iterator[bytes]], ArtifactDescriptor]) -> TrajectorySummary; def discard() -> None`; `TrajectorySummary(point_count, first_offset_ms, last_offset_ms)`; created by `TrajectorySpoolFactory(store, chunk_points)` | S1.2b |
| `video/trajectory.py` (ext) | streaming encoder producing bytes identical to `serialize_trajectory` | `def iter_trajectory_v1(point_count: int, points: Iterable[tuple[int, float, float]]) -> Iterator[bytes]` | S1.2b |
| `evidence/roles.py` | `EvidenceRole` enum, canonical order, wire/key tokens, per-role caps | `EvidenceRole(StrEnum)`: `REPRESENTATIVE="representative"`, `NEAR_VIEW="near-view"`, `EARLY_DIVERSE="early-diverse"`, `LATE_DIVERSE="late-diverse"`; `ROLE_ORDER`; `role_cap_bytes(role)` | S1.2c |
| `evidence/quality.py` | replaceable scorer | `class QualityScorer(Protocol): def score(self, ctx: FrameContext, bbox) -> CandidateQuality`; `QualityV1Scorer` wraps today's formula + occlusion proxy (as built: `QualityV2Scorer`, credible-competitor proxy, E24) | S1.2c |
| `evidence/encoder.py` | crop → bounded JPEG via fixed ladder | `class EvidenceEncoder: def encode(self, crop: np.ndarray, cap_bytes: int) -> EncodedImage | None` | S1.2c |
| `evidence/selector.py` | per-Track role state machine; holds ≤ 4 `EncodedImage` per live Track | `class EvidenceSelector: def observe(ctx, candidate, track_start_ms) -> None; def resolve() -> tuple[SelectedEvidence, ...]` | S1.2c |
| `evidence/admission.py` | run-level quota admission, pure function | `admit(tracks, quota_bytes) -> AdmissionResult(admitted, omitted_keys, accounting)` | S1.2c |

Store capabilities added (both backends, same no-follow discipline): `append_bytes(relative_name, content)` (S1.2b; open-append-close, no fsync, spool namespace only), `write_stream(relative_name, chunks: Iterator[bytes], media_type)` (S1.2b; temp file + incremental SHA/size + `fsync` + atomic publish, exactly like `write_bytes`), `remove(relative_name)` (S1.2b; used by the spool at retirement and by `remove_omitted` in S1.2c).

Everything in `evidence/` and the spool depends only on `common/analytical.py`, `video/reader.py`, `detection/interfaces.py`, the store's typed interface and the profile section. None of it imports the tracker or the worker client.

### 3.2 Replaceability

| Component | Replaced by | Identity change |
|---|---|---|
| Tracker | any `Tracker` returning `TrackerUpdate` (S1.1) | profile `tracker` section |
| Quality scorer | a new `QualityScorer` selected by `evidence.scorerVersion` | profile SHA → provenance/digest; new ProcessingRun (ADR-013 §3) |
| Evidence selector policy | new `evidence.selectorVersion` (role rules frozen by ADR-013 §4; only parameters and scorer change without an ADR) | profile SHA |
| Image encoder | another `EvidenceEncoder`; a different codec needs a new media type in the wire enum and platform allow-list → contract change | schema version |
| Trajectory format | the spool is internal; `iter_trajectory_v1` is the only place that knows v1; a v2 trajectory is a new `iter_trajectory_v2` + media type/version negotiation (separate qualified slice) | — |
| Staging reclamation | the janitor is a platform service behind `IStagingJanitor` with a pluggable filesystem walker; a non-local media store would supply its own walker | — |
| Embedding/ReID | out of scope; enters `CandidateQuality` through a new scorer version | profile SHA |
| Persistence/indexing | `Observation` rows are role-typed; the read side (S1.3) projects them | — |

### 3.3 Platform components

- **Contracts:** v3 request shape beside v2; `WorkerContractRules.CompletionSchemaVersions = {"2.0","3.0"}`; new evidence-quota constants; `GET /api/vision/contract`.
- **Validator:** one `Validate(routeJobId, request, videoDurationMs)` dispatching on `SchemaVersion`; v2 normalises to one Representative observation; v3 validates observations; digest tag per version.
- **Store:** seals every observation artefact + trajectory per Track; `Observation` rows with role/rank/score; `Artifact(EvidenceCrop)` for v3, `Artifact(Thumbnail)` for v2.
- **Staging janitor (new):** `StagingJanitorHostedService : BackgroundService` in the API host + `IStagingJanitor` in Infrastructure; database predicate decides deletability; handle-relative/no-follow deletion under `staging/` only (§6.5).
- **Content:** `EvidenceCrop + AcceptedEvidence + image/jpeg` added to the serving allow-list and catalog rule.

---

## 4. Evidence roles and selection algorithm (S1.2c)

Roles, caps and order are frozen by ADR-013 §4–§5. Numeric parameters live in the profile (§5).

### 4.1 Definitions

- **Frame context** `FrameContext(frame: DecodedFrame, detections: tuple[DetectionCandidate, ...])` — the detector output the tracker was given (both classes, including detections the tracker did not confirm).
- **Qualified candidate** (all must hold): `confidence ≥ confidenceFloor`; `sharpness ≥ sharpnessFloor`; `edgeMargin ≥ edgeMarginFloor`; `occlusionIou < occlusionIouCeiling`, where `occlusionIou = max IoU(candidate.bbox, d.bbox)` over every other **credible** detection `d` in the frame, of either class: `d.confidence ≥ confidenceFloor` (0.0 if none). This is scorer `quality-v2` (E24; ADR-013 §4 occlusion-proxy amendment, accepted 2026-09-24). The candidate's own detection is excluded before the credibility filter (E9). quality-v1 counted every detection down to `detectorInferenceFloor` (parameter note F1).
- **Scores** (`CandidateQuality`): `quality_score = representative_quality(frame, bbox)` (formula v1); `selection_score = quantize(clamp01(quality_score − occlusionPenaltyWeight·occlusionIou))`; `area = bbox.width·bbox.height`. `quantize(x) = floor(x·10⁶)/10⁶`, applied before any comparison and before emission (§8).
- **Near-duplicate** of a selected frame S: `same source_frame_number`, or `|offset − S.offset| ≤ duplicateWindowMs and IoU(bbox, S.bbox) ≥ duplicateIouThreshold`.
- **Separated** from S: `|offset − S.offset| ≥ minSeparationMs`.
- **Admissible**: the encoder returned bytes ≤ the role's cap (§6.1). An unadmissible candidate never becomes a holder; the holder stays.

### 4.2 Per-role rules

Evaluated for every accepted frame in which the Track has a candidate, in the order below. Each rule reads only the candidate, `FrameContext`, the profile and the selector's current holders. A holder is `SelectedEvidence(role, offset_ms, source_frame_number, confidence, bbox, quality, image: EncodedImage)`.

| Role | Eligibility | Replacement rule (strict) | Tie | Window / freeze | Encodes bounded by |
|---|---|---|---|---|---|
| **Representative** (mandatory, rank 0) | qualified — *as implemented, two-tier: a fallback holder is allowed until the first qualified admissible candidate (E8, ADR-013 §4 amendment accepted 2026-09-24)* | `selection_score > holder.selection_score + replaceEpsilon` **and admissible** | equal or within ε keeps the earlier frame | whole Track; never frozen | ≤ 1/replaceEpsilon |
| **NearView** | qualified; not near-duplicate of the Representative holder | `area > holder.area·(1 + nearViewGrowth)` and admissible (first qualified non-duplicate candidate seeds it) | equal area keeps earlier | whole Track | ≤ ⌈ln(1/areaMin)/ln(1+nearViewGrowth)⌉ |
| **EarlyDiverse** | qualified; `offset − track_start ≤ earlyWindowMs`; separated from and not near-duplicate of Representative and NearView holders **at evaluation time** | `selection_score > holder.selection_score + replaceEpsilon` and admissible | keeps earlier | frozen once `offset − track_start > earlyWindowMs` | ≤ 1/replaceEpsilon |
| **LateDiverse** | qualified; `offset − holder.offset ≥ lateRefreshIntervalMs` (or no holder); separated from and not near-duplicate of every other holder at evaluation time | replace when eligible and admissible (trailing view, not best view) | n/a | whole Track | ≤ trackDuration / lateRefreshIntervalMs |

Notes that make the table exact:

- Representative first: if a frame wins Representative, the other roles are evaluated against the **new** Representative holder in that frame, so a frame cannot become both Representative and NearView.
- An unadmissible would-be replacement leaves the holder unchanged and is counted (`unadmissible_by_role`).
- When a Representative replacement makes an existing supplemental holder a near-duplicate of the new Representative, the supplemental is **not** dropped immediately; duplicates are resolved once, at `resolve()`.
- No candidate ever qualifies → Representative empty at retirement → **the attempt fails** (`evidence_representative_missing` → `pipeline_processing_failed`). *(As implemented, two-tier, E8, ADR-013 §4 amendment accepted 2026-09-24: a Track with no qualified frame keeps a fallback Representative. The attempt fails only when no candidate at all is admissible.)* The profile loader rejects `confidenceFloor > tracker.trackActivationThreshold`, so the confidence floor alone can never disqualify every frame of a confirmed Track.

*(As implemented, E8/E12: the argument below covers the qualified tier once it is reached. The fallback tier is the same ε-fold over all admissible candidates, so in step (i) an unqualified candidate can still move a fallback holder. The first qualified admissible candidate resets A to itself. The no-reservoir conclusion holds for both tiers.)* **Why the online Representative rule equals "best admissible candidate seen so far" (C1).** Let A be the set of qualified candidates seen so far whose encoding is admissible, ordered by `(selection_score, −offset)` with the ε rule. Invariant: after each frame, `holder = ε-max(A)` (the earliest candidate among those within ε of the top score). Induction: initially A = ∅ and holder = none. On a new candidate c: (i) if c is not qualified, A and holder are unchanged. (ii) If c is qualified but does not beat the holder by more than ε, c may or may not be admissible — either way it cannot be the ε-max, so A' = A ∪ {c} (or A) has the same ε-max; holder unchanged is correct. (iii) If c beats the holder by more than ε, c is encoded: if admissible, A' = A ∪ {c} and c is its ε-max → holder := c; if unadmissible, c ∉ A' = A → holder unchanged is correct. Encoding only happens in case (iii), and an earlier admissible lower-scoring candidate that was displaced is never needed again: it can only be the ε-max of A' if c is unadmissible, and in that case it was never displaced. The K-candidate reservoir therefore adds no reachable outcome. Adversarial encoder measurement E6 is retained because admissibility at the floor is a measured property, not a proof; the online rule needs no proof of admissibility, only the encoder's answer.

### 4.3 Retirement resolution (`resolve()`)

1. Take holders in `ROLE_ORDER`.
2. For each supplemental holder H (NearView, EarlyDiverse, LateDiverse in order): omit H if it is a near-duplicate of, or not separated from, **any earlier role already kept** (NearView exempt from the separation test against Representative — ADR-013 requires only non-duplication).
3. Ranks 0..n−1 in role order over the kept roles.
4. Output sorted by role order; `resolve()` is idempotent and pure.

Two observations of a Track therefore never share a source frame; **one image never satisfies two roles**; the wire and DB forbid two observations of one Track with the same `sourceFrameNumber` (§7.2).

### 4.4 Worked example

Track 0–20 s at 10 fps, all frames qualified and admissible, earlyWindowMs 3000, lateRefreshIntervalMs 5000, minSeparationMs 1000, replaceEpsilon 0.02, duplicateWindowMs 500:

- t=0.0 s score .40 area .010 → Representative. NearView: same frame → no. Early/Late: not separated → no.
- t=1.1 s score .41 area .012 → Rep keeps (.41 ≯ .42). NearView seeds (area .012). Early: NearView is now a holder in this frame and Early is not separated from it → no.
- t=2.2 s score .45 → Rep replaced. NearView: .012·1.25 = .015 not exceeded. Early: not separated from Rep (same frame) → no.
- t=2.9 s score .30 area .020 → NearView replaced (.020 > .015, Δt .7 s > duplicateWindow). Early: |2.9−2.2| < 1 → no.
- t=3.1 s → early window closed; Early **omitted**.
- LateDiverse: first frame separated from Rep (2.2) and NearView (2.9) is 3.9 s → holder; refreshed at ≥ 8.9, 13.9, 18.9 s → holder 18.9 s.
- `resolve()`: Rep(2.2), NearView(2.9) kept (Δt .7 > .5, not a duplicate by window), Late(18.9) kept. Ranks 0,1,2.

---

## 5. Profile section (numeric policy) — S1.2c

`src/vision/config/pipelines/phase1-detection-tracking-v1.json` gains one section and bumps `schemaVersion` to `"1.1"`; `profileVersion` → `"1.2.0-candidate"`. The loader accepts `Literal["1.1"]` only.

```json
"evidence": {
  "selectorVersion": "evidence-selector-v1",   // shipped as "evidence-selector-v1-two-tier" (§16.2 E19)
  "scorerVersion": "quality-v2",
  "confidenceFloor": 0.50,
  "sharpnessFloor": 0.05,
  "edgeMarginFloor": 0.005,
  "occlusionIouCeiling": 0.30,
  "occlusionPenaltyWeight": 0.0,
  "replaceEpsilon": 0.02,
  "nearViewGrowth": 0.25,
  "earlyWindowMs": 3000,
  "lateRefreshIntervalMs": 5000,
  "minSeparationMs": 1000,
  "duplicateWindowMs": 500,
  "duplicateIouThreshold": 0.85,
  "encoder": {
    "maxLongEdgePx": 1024, "initialQuality": 85,
    "representativeCapBytes": 65536, "supplementalCapBytes": 163840,
    "floorLongEdgePx": 128, "floorQuality": 50,
    "ladderScale": 0.8, "ladderQualities": [85, 75], "floorQualities": [65, 55, 50]
  },
  "runEvidenceCropQuotaBytes": 1073741824
}
```

The spool chunk size is **not** in the profile: it does not change any output (bytes are identical for any chunk size) and therefore is not qualification identity; it is a worker setting `MAVI_TRAJECTORY_SPOOL_CHUNK_POINTS` (default 4096, range 256..65536) in `common/settings.py`.

Loader rules (`_EvidenceProfileSchema`, `extra="forbid"`): floors/ceilings in [0,1]; `replaceEpsilon` in (0, 0.5]; `nearViewGrowth` in (0, 4]; windows positive ints ≤ 3,600,000; `confidenceFloor ≤ tracker.trackActivationThreshold`; encoder values **fixed** to the ADR-013 §5 constants and `runEvidenceCropQuotaBytes == 1 GiB` (the loader rejects other values — ADR bounds are not tuning knobs).

Defaults are initial engineering values. Before S1.2c merges, record a measurement note (`docs/qualification/2026-xx-xx-evidence-selector-parameter-note.md`) over the C1 scripted corpus and ≥ 2 real Development clips: sharpness/area/edge-margin distributions per confirmed Track, share of frames qualified per floor, roles filled per Track, re-encodes per Track; adjust defaults in the same PR. The profile SHA changes; `models/qualifications/rtmdet-m-coco-phase1-v1.json.pipelineProfileSha256` is re-derived in the same PR and stays `pending`.

---

## 6. Encoder, admission, spool and staging lifecycle

### 6.1 Crop and ladder (`evidence/encoder.py`, S1.2c)

1. **Crop** with the existing floor/ceil rule; empty crop → skipped and counted.
2. **Downscale** if `max(w,h) > 1024`: `Image.resize(LANCZOS)` to long edge 1024, other edge `max(1, round(other·1024/long))`; never upscale.
3. **Encode** JPEG `quality=q, optimize=False, progressive=False, subsampling=2`, no EXIF/ICC.
4. **Ladder:** q85 → q75 at current size → `long = max(128, floor(long·0.8))` at q75 until 128 (1024→819→655→524→419→335→268→214→171→136→128: 10 steps) → q65, q55, q50 at 128. First step with output ≤ cap wins; ≤ 15 encodes per candidate.
5. Floor exceeded → `None` (unadmissible).

Determinism per §8: bytes reproducible within one qualified runtime variant (golden SHA per variant); across variants only dimensions, size ≤ cap and decodability.

### 6.2 Run-level admission (`evidence/admission.py`, S1.2c)

Pure function over the finalised descriptor-only Tracks:

1. Σ Representative bytes > quota → `AdmissionError("representative_quota_exceeded")` (fail closed; impossible under 10,000 × 64 KiB = 625 MiB, kept as invariant).
2. Rounds NearView → EarlyDiverse → LateDiverse; within a round sort by `(−selection_score, track_id)`; `track_id` ordinal order equals eventual `LocalTrackNumber` order (pinned by A6).
3. Admit while `running_total + size ≤ quota`; otherwise omit **and continue**.
4. Output admitted set, omitted staging keys, `EvidenceAccounting` per role.

`VideoProcessor` then rebuilds each `ProcessedTrack.observations` without omitted roles (re-ranking 0..n−1), calls `publisher.remove_omitted(keys)` (lease-fenced), and attaches `accounting` to `VisionProcessingResult`.

**Why admission stays at end of run (reviewed).** ADR-013 §6 orders admission by selector score across *all* Tracks of the run, which is unknowable before EOS. Alternatives examined: (a) holding encoded supplemental bytes in RAM until EOS — up to 30,000 × 160 KiB = 4.6 GiB of completion-time memory, violating the memory class boundary; (b) per-Track or first-come budgets — deterministic but not score-ordered, i.e. a change to the frozen ADR rule; (c) two-pass staging — no better than the current design. The design therefore stages every candidate at retirement (worst case 5.19 GiB transient, §9.4) and removes omitted ones before completion. In the realistic case (hundreds of Tracks) nothing is omitted and no candidate is written twice. What makes the transient bound acceptable is the crash-safe lifecycle in §6.5, not the fast path.

### 6.3 Trajectory spool (`video/trajectory_spool.py`, S1.2b)

**Problem.** The trajectory is the only per-live-Track structure that grows with the Track's life. A Track can live for the whole video, so with the point list in RAM, live memory is O(video length). This must be bounded without changing trajectory v1 as seen by its three consumers.

**Options analysed.**

*Option A — write the canonical v1 artefact incrementally while the Track is live.* The v1 payload is `fixmap(2) · "v" · 1 · "points" · array-header(N) · point×N`. The array header depends on N (fixarray < 16, `0xdc` + uint16 < 65536, `0xdd` + uint32), which is unknown until retirement, so the canonical bytes cannot be written prefix-first without either reserving the widest header (changes bytes for N < 65536 — not identical to today's serializer) or rewriting the header (needs a seek+rewrite on the temp file, which the hardened backends do not expose and which breaks the "temp → atomic publish" model). **Rejected as the primary mechanism**, but the observation that every *point* encodes independently is what Option B uses.

*Option B — fixed-size in-memory chunk, spilled to an internal spool, streamed conversion at retirement.* Points are appended to compact arrays (`array('q')` offsets, `array('d')` cx, `array('d')` cy — full precision, so the canonical float64 bytes are unchanged); when the chunk reaches `chunk_points` it is packed with `struct` (`<qdd`, 24 B/point) and appended to `spool/{trackId}.traj` in the attempt directory via `append_bytes` (open-append-close, no fsync). At retirement `finalise()` knows N = spilled + buffered, and yields: header bytes (computed with the same header rule msgpack uses) then, for each spilled chunk read back sequentially and then the in-memory remainder, `msgpack.packb([offset, cx, cy])` per point. `write_stream` consumes the iterator, hashing and counting as it writes the temp file, and publishes atomically. Peak RAM at retirement is one chunk plus the encoder's output buffer per chunk, never the whole Track. Byte identity with `msgpack.packb({...})` was verified for N ∈ {1, 15, 16, 255, 65535, 65536, 70000} (per-point encoding is context-free; header rule is fixarray/array16/array32; the map and keys encode identically). **Chosen.**

*Option C — narrow the S1.2 claim.* Rejected: the spool is ≈ 200 lines of worker code plus two backend primitives that the S1.2c staging removals need anyway (`remove`), it changes no external byte, and without it the central B2 claim ("worker memory bounded by live Tracks") is false for any long-lived Track.

**Answers to the required questions.**

| Question | Answer |
|---|---|
| Can v1 be written incrementally? | Not prefix-first (header needs N). Per point yes; hence chunk spool + streamed conversion. |
| Temporary internal format? | `<qdd` little-endian records, 24 B/point, internal to the worker, never referenced by any descriptor. |
| Does conversion load the whole trajectory? | No: spilled chunks are read sequentially with a bounded read size (one chunk); the remainder is already in RAM. |
| SHA/size incremental? | Yes: `write_stream` hashes while writing the temp file; the descriptor is produced from the running hash/count. |
| Lease lost mid-Track? | Spool files live under `staging/{job}/attempt-NNNN/spool/`; they are never published or referenced. Lease loss stops the loop at the next `check_owned()`; the attempt's staging (including spool) is removed by the next attempt (S1.1) or the janitor (§6.5). Spool appends are not lease-fenced (they are not publications); `write_stream` at retirement is fenced exactly like `write_bytes`. |
| Failed attempt? | `cleanup()` removes the whole attempt directory including `spool/`. |
| Temporary disk bound? | Σ over live Tracks of 24 B × points spilled ≈ 24 × 30 × 86,400 = 62 MB per 24 h live Track; deleted at that Track's retirement (`remove`). During one finalisation the spool, the `write_stream` temp file and (for an instant) the published artefact coexist for that Track — peak ≈ 3 × 24·D — see §9.4; finalisations are sequential so this is one Track's worth at a time. |
| Per-frame write overhead? | None per frame: one append per `chunk_points` (default 4096 ≈ 2.3 min at 30 fps). No fsync on the spool. No persistent file descriptors (open-append-close), so live-Track count does not consume fds/handles. |
| Deterministic and portable? | Output bytes are identical to today's serializer and independent of chunk size (T2). Append/stream/remove use the existing handle-relative, no-follow backends on POSIX and Windows. |
| Validation at retirement? | `prepare_track` receives `TrajectorySummary(point_count, first_offset_ms, last_offset_ms)`; monotonicity is enforced on append (`offset ≤ last` → `trajectory_offsets_not_monotonic`, attempt fails); count and bounds checks are unchanged in meaning. |

**Consumer constraint discovered.** `TrajectoryDecoder.cs` refuses more than **1,000,000 samples**; a Track longer than ≈ 9.3 h at 30 fps already produces an artefact Scene Analytics reports as `trajectory_invalid`. S1.2 does not change this (it is the platform's stated hostile-input ceiling), but the spool makes such Tracks *producible* without exhausting worker memory, so the plan records it as an open item for S1.4/Scene Analytics (§20) rather than silently.

### 6.4 Live memory classes (restated)

- **Live processing memory:** per live Track, ≤ 4 encoded images + one trajectory chunk + scalars (§9.1) — bounded by constants, independent of Track and video duration.
- **Completion metadata:** per finalised Track, descriptors only (§9.3).
- **Staging disk:** spool + staged evidence + trajectories (§9.4), reclaimed by §6.5.
- **Completion request:** descriptors only (§9.5).

### 6.5 Staging lifecycle: crash-safe reclamation

**Problem.** After the platform seals evidence and commits, the job is Completed and never re-leased, so S1.1's superseded-attempt cleanup never runs for it; if the worker dies right after `complete()` returns, its staging (up to §9.4) survives indefinitely. "Worker cleanup best-effort + GC deferred" is not a bound.

**Options analysed.**

*Option A — platform deletes the source staging objects after commit.* Feasible in the local topology: the platform reads staging through `LocalMediaStore` on the same media root and already has `DeleteAsync`. But deletion inside the completion transaction is wrong (a rollback would need the bytes back for compensation, and a replay must still validate the same request), and deletion after commit but before the HTTP response is still not crash-safe (the platform can die between commit and delete). It also entangles a large filesystem walk with the request path that holds no lock but delays the worker's response. **Rejected as the correctness mechanism; not adopted even as a fast path** (the janitor covers the same window within minutes, and one mechanism is easier to reason about).

*Option B — durable janitor with database authority.* The database is the only authority on whether an attempt can still be accepted: the row lock in `CompleteAsync`, `Status` and `AttemptCount`. A background service in the API host walks `staging/` and deletes exactly the attempt directories the database proves dead. Crash-safe by construction (state is the filesystem + DB; every run is idempotent). **Chosen.**

*Option C — atomic move from staging into the evidence root.* Rejected: ADR-006 requires the evidence root to be filesystem-disjoint and link-free from the worker-writable media root (`StorageRootSafety.AreDisjointAndLinkFree`), so a rename cannot cross it; and sealing must verify size/SHA while streaming, which a rename does not. Ownership transfer would also remove compensation semantics (ADR-006 §5).

**Janitor specification (`Mavi.Infrastructure/Storage/StagingJanitor.cs`, `Mavi.Api/Storage/StagingJanitorHostedService.cs`, S1.2a).**

| Aspect | Rule |
|---|---|
| Namespace | Only `{MediaStorage:RootPath}/staging/{jobId}/attempt-NNNN` directories where `jobId` parses as a `Guid` and the attempt name matches `attempt-[0-9]{4,10}` canonically (same rule as the worker's `superseded_attempt_number`). Anything else under `staging/` is logged once (EventId 1401 `staging_janitor_unrecognised_entry`) and never touched. Nothing outside `staging/` is ever enumerated. The evidence root is never touched. |
| Authority predicate (per job directory, one DB read `SELECT status, attempt_count, completed_at_utc FROM vision_jobs WHERE id = @jobId`). Every destructive rule below corresponds to a state the `VisionJob` aggregate can actually reach (§2); states it cannot reach are fail-closed. | **Completed / Failed** (legitimate terminal states; `Failed` via `Fail` or `Exhaust`): every `attempt-k` directory is deletable once `now ≥ CompletedAtUtc + Grace`. **Cancelled** (defined in `VisionJobStatus`, but no current code path produces it): handled conservatively as a terminal state with the same grace rule *because the enum defines it as terminal*, not because the janitor infers a transition; a `Cancelled` row is also logged once (EventId 1405 `staging_janitor_unexpected_status`) so its first appearance is visible. **Leased** (legitimate, `AttemptCount ≥ 1`): `attempt-k` with `k < AttemptCount` is deletable immediately (fenced by the lease authority); `k ≥ AttemptCount` is never touched by this rule. **Queued with AttemptCount = 0** (legitimate: never leased): no attempt has run, so any `attempt-*` directory is unexpected → logged 1401, **preserved**. **Queued with AttemptCount > 0** (impossible in the current aggregate — nothing sets `Status` back to `Queued`): treated as an **invariant violation** → logged 1406 `staging_janitor_invariant_violation` at Error, **nothing deleted**, no inference about dead attempts. **No row:** deletable only when the directory's last-write time is older than `UnknownJobGrace` (default 24 h) — covers a job row removed by another lifecycle; logged at Warning. A retried video is a *new* job id with its own directory, so the old `Failed` job and the new `Queued` job are judged independently by their own rows. |
| Grace | `Grace` default 5 minutes after the terminal transition: long enough for the worker's own fast-path `cleanup()` to run first (avoids deleting under a process that is itself deleting; both are idempotent and tolerate ENOENT), short enough to bound retention. |
| Schedule and per-cycle cap | On host start (after DB readiness) and every `IntervalMinutes` (default 15). One instance per host; `SemaphoreSlim(1)` prevents overlap. Each cycle enumerates every job directory under `staging/` (cheap: one `stat` per directory), computes eligibility for all of them, and **processes at most `MaxDirectoriesPerCycle` = M (default 1,000) eligible job directories, oldest eligible first**; the rest are counted as *deferred* and processed in later cycles. Eligibility is never cached across cycles. Directories deferred by the cap are not reported as reclaimed. |
| Deletion | Handle-relative and link-safe: open the job directory and attempt directory with `FileOptions`-based handles that fail on reparse points (`FileAttributes.ReparsePoint` check after open; on Windows `FILE_FLAG_OPEN_REPARSE_POINT` semantics via `FileSystemEnumerable` with `AttributesToSkip = 0` and explicit refusal); recurse only into real directories; delete leaf files then directories bottom-up; a symlink/junction *entry* is deleted as an entry, never followed. Mirrors the worker's POSIX `rmtree(dir_fd=)` / Windows `_remove_attempt_tree_no_reparse` discipline. A directory whose root is itself a link is refused (EventId 1402 `staging_janitor_path_escape`, Error) and left in place. |
| Idempotency | Every run recomputes from filesystem + DB; a directory removed by the worker meanwhile is a no-op. |
| Observability | Uses the existing logging and health-details model only (no new metrics subsystem). EventId 1400 cycle summary carries: `scanned` (job directories seen), `eligible` (reclaimable now), `processed` (this cycle), `removed` (directories successfully deleted), `freedBytes`, `failed`, `deferredByCap` (eligible − processed), `oldestEligibleAgeMinutes` (now − the oldest eligible directory's terminal/fence time), `backlogDepth` (= deferredByCap) and `estimatedCyclesToDrain` (= ⌈backlogDepth / M⌉). 1401 unrecognised entry; 1402 path escape (Error); 1403 deletion failed (Warning, path + exception); 1404 same directory failed ≥ 3 consecutive cycles (Error); 1405 unexpected status; 1406 invariant violation (Error). Health details expose `stagingJanitor.{enabled,lastRunUtc,lastCycleRemoved,failed,deferredByCap,backlogDepth,oldestEligibleAgeMinutes,consecutiveFailures}`. |
| Repeated failure and escalation thresholds | Never crashes the host; the directory stays; retried every cycle; 1404 escalates. Two configurable age thresholds turn the backlog into an operational signal: `WarnOldestEligibleMinutes` (default 60) → Warning 1407 `staging_janitor_backlog_warning` each cycle the oldest eligible age exceeds it; `ErrorOldestEligibleMinutes` (default 360) → Error 1408 `staging_janitor_backlog_critical` and health details flag `stagingJanitor.backlogState = "critical"`. A failing or lagging janitor never blocks completion, leasing or serving. |
| Interaction with S1.1 worker cleanup | Both remain: the worker's `cleanup()` (own attempt, after success — fast path, §6.3 of S1.1 unchanged for failure) and `cleanup_superseded_attempts()` (at lease) reduce retention to seconds in the normal case; the janitor guarantees the bound when the worker dies or never runs again. |
| Normal reclamation target (no backlog, platform up) | For a newly eligible directory when the next cycle has capacity: **≤ `Grace + IntervalMinutes`** after the terminal transition (**≤ 20 minutes** with defaults) for a completed/failed job with a dead worker; ≤ 1 cycle for superseded attempts of a leased job. This is the normal operational target, not a universal guarantee. |
| Backlog bound | With B eligible job directories older than a given directory and M processed per cycle, reclamation of that directory takes approximately **`Grace + ⌈(B + 1) / M⌉ × IntervalMinutes`**, subject to repeated deletion failures (a failing directory is retried but does not block others) and platform downtime (no cycles run). Example: B = 2,500, M = 1,000 → ≈ 5 + 3 × 15 = 50 minutes. The 1407/1408 thresholds make a growing backlog visible before it matters. If the platform is down, no completions happen either, so no new staging becomes reclaimable; on restart the backlog drains at M per cycle. |
| Bounded retained staging (platform up, no backlog) | ≤ (jobs reaching a terminal state within the normal target window) × (per-attempt staging, §9.4) + live attempts' staging. With one worker completing at most a few jobs per 20 min, this is a handful of attempts, each ≤ 1 GiB crops + trajectories after the worker's own admission removals (or ≤ 5.19 GiB + trajectories if the worker died before removals). Under backlog the retained total grows with B until drained; the observability row makes B and its age visible. |

**Ownership consequence.** Reclaiming worker staging becomes a **platform responsibility with database authority**, not a worker courtesy. This is a genuine new architectural responsibility (Task-13 §9.3 left it as "a later garbage collector"); it does not alter ADR-006's evidence-root ownership or sealing semantics. It is recorded as ADR-006 §6 (accepted 2026-09-23; §17 C3).

---

## 7. Wire contract v3 (S1.2a defines, S1.2c emits)

### 7.1 Message

Only the completion message changes; lease/heartbeat/fail stay `"2.0"`. `schemaVersion: "3.0"`; v2 top-level fields plus:

```json
"evidenceAccounting": {
  "representative": {"candidates": 412, "admitted": 412, "omitted": 0, "candidateBytes": 19345001, "admittedBytes": 19345001},
  "near-view":      {"candidates": 380, "admitted": 380, "omitted": 0, "candidateBytes": 40120333, "admittedBytes": 40120333},
  "early-diverse":  {"candidates": 201, "admitted": 201, "omitted": 0, "candidateBytes": 20014411, "admittedBytes": 20014411},
  "late-diverse":   {"candidates": 355, "admitted": 355, "omitted": 0, "candidateBytes": 37811902, "admittedBytes": 37811902}
}
```

### 7.2 Track

```json
{
  "trackId": "person-000001", "objectClass": "person",
  "startOffsetMs": 1200, "endOffsetMs": 18900,
  "detectionCount": 178, "meanConfidence": 0.83, "maxConfidence": 0.97,
  "trajectoryArtifact": {"storageKey": "staging/{job}/attempt-0001/trajectories/person-000001.msgpack",
                         "mediaType": "application/msgpack", "sizeBytes": 2141, "sha256": "…"},
  "observations": [
    {"role": "representative", "rank": 0, "offsetMs": 3400, "sourceFrameNumber": 102,
     "confidence": 0.95, "qualityScore": 0.612345, "selectionScore": 0.612345,
     "boundingBox": {"x": 0.21, "y": 0.15, "width": 0.18, "height": 0.52},
     "crop": {"storageKey": "staging/{job}/attempt-0001/evidence/person-000001-representative.jpg",
              "mediaType": "image/jpeg", "sizeBytes": 51233, "sha256": "…"}},
    {"role": "near-view", "rank": 1, "...": "..."},
    {"role": "late-diverse", "rank": 2, "...": "..."}
  ]
}
```

Rules (Python model and .NET validator):

- `observations`: 1..4 items, bound enforced **during JSON binding** (`BoundedVisionObservationListJsonConverter`) and in Pydantic (`max_length=4`);
- roles unique; ranks unique and contiguous `0..n−1` in `ROLE_ORDER`; `role == representative ⇔ rank == 0`; exactly one Representative;
- `sourceFrameNumber` unique within a Track;
- each observation: `start ≤ offsetMs ≤ end`; `0 ≤ sourceFrameNumber < framesProcessed`; `confidence ≤ maxConfidence`; scores finite in [0,1];
- `crop.storageKey == staging/{routeJobId:D}/attempt-{attempt:0000}/evidence/{trackId}-{role}.jpg`, `mediaType == "image/jpeg"`, `0 < sizeBytes ≤ roleCap`;
- `trajectoryArtifact` unchanged (key, media type, ≤ 64 MiB);
- aggregates: Σ crop bytes ≤ 1 GiB (`MaximumCompletionEvidenceCropBytes`); Σ trajectory bytes ≤ 512 MiB (`MaximumCompletionEvidenceBytes`, trajectory/other only); `evidenceAccounting` has all four roles, non-negative ints, `admitted ≤ candidates`, `admittedBytes ≤ candidateBytes`, and per role `admittedBytes == Σ sizeBytes of that role's crops`;
- ≤ 10,000 Tracks; body ≤ `MaximumCompletionRequestBodyBytes` (§7.4).

`qualityScore` (frame-quality formula, `scorerVersion`) and `selectionScore` (admission ordering) are both carried; equal in S1.2 with `occlusionPenaltyWeight = 0`; kept separate so a scorer change does not redefine persisted frame quality.

### 7.3 Digest v3 (server-side only)

Same encoding as v2. Sequence: tag `mavi:vision-completion-digest:v3`, jobId "D", attempt, frames, durationMs; provenance as v2; `evidenceAccounting` in role order (five ints each); Track count; per Track (ordinal): scalars; trajectory key/mediaType/size/sha; observation count; per observation (rank order): role token, rank, offset, frame, confidence, qualityScore, selectionScore, X, Y, W, H, crop key/mediaType/size/sha. A v2 body keeps the v2 sequence and tag.

### 7.4 Body limit

`MaximumCompletionRequestBodyBytes` → **48 MiB**, subject to `WorkerContractV3Tests.WorstShapeBodyFitsUnderLimit` (10,000 × 4 observations through the real DTOs; assert `bytes ≤ limit − 8 MiB`; parent estimate ≈ 22–23 MiB, superseded by measurement: the adversarial shape — 64-character Track ids, `int.MaxValue` counts, 17-digit doubles, 2⁵³ offsets, every crop at its cap — measures **29.24 MiB**, deliberately harsher than any realistic body). If measured > 32 MiB, stop (parent stop condition 3); the measurement is under that stop condition and under the ≤ 40 MiB (limit − 8 MiB) gate. The Kestrel global limit (3 GiB + 1 MiB) already exceeds it; the completion middleware remains the effective bound.

### 7.5 Contract artefacts

`contracts/schemas/vision-job-complete-v3.schema.json`; `contracts/examples/vision-job-complete-v3.example.json` (golden, with `contracts/test-vectors/vision-job-complete-v3-digest.json` pinning the file SHA and its .NET digest); `…-v3-conformance.json`; `control-plane-v3-invalid.json`; `tools/verify_repo.check_contracts` extended; `contracts/README.md` updated.

---

## 8. Determinism

| Aspect | Guarantee | Mechanism |
|---|---|---|
| Candidate comparison and ties | **semantic, all variants** | strict `>` with ε on quantised scores; equal keeps earlier; fixed role order |
| Score values | **bitwise within a qualified runtime variant**; cross-variant equal except at 10⁻⁶ quantisation boundaries | float64 numpy on the locked wheel set; `quantize` |
| JPEG bytes | **bitwise within a variant** (golden SHA per variant); cross-variant: dimensions, ≤ cap, decodable | fixed Pillow flags and ladder; Pillow 11.3.0 locked |
| Trajectory v1 bytes | **bitwise, all variants, independent of chunk size and of spilling** — identical to `serialize_trajectory` | per-point msgpack encoding is context-free; header rule replicated; T1/T2 |
| Resize ladder | **semantic, all variants** | integer arithmetic |
| Role/observation/Track ordering | **semantic, all variants** | `ROLE_ORDER`; contiguous ranks; ordinal Track sort |
| Digest | **bitwise for a given body** (server-side) | §7.3; golden fixture |
| Persistence ordering | `LocalTrackNumber = index+1` over ordinal order; observations in rank order | store |
| Cross-platform runtime | same role set/ranks/frames/bboxes for identical detector/tracker output; cross-OS detector parity is **not** asserted | per-variant qualification |

Not claimed: cross-variant byte identity of crops; cross-variant digest identity; determinism under a different Pillow/numpy build.

---

## 9. Memory, storage and request bounds

Symbols: L = live Tracks at an instant (bounded by the tracker: every live identity was matched within ≈ 1.03 s, so L ≤ maxDetectionsPerFrame × ⌈1.03·fps⌉; ≤ 3,100 pathological at 100 detections/frame and 30 fps, ≤ 100 typical); T = Tracks finalised so far (≤ 10,000); D = detections in one Track; C = spool chunk points (default 4096).

### 9.1 Live processing memory per live Track — **independent of D, Track duration and video duration**

| Item | Bytes | Note |
|---|---|---|
| Representative `EncodedImage` | ≤ 65,536 | cap |
| NearView / EarlyDiverse / LateDiverse `EncodedImage` | ≤ 3 × 163,840 = 491,520 | caps |
| Holder metadata (4 × ~200 B) | ≤ 1,024 | |
| Trajectory chunk buffer | 24 × C = 98,304 at C = 4096 | `array('q')` + 2 × `array('d')`; spilled when full |
| Spool bookkeeping (path, counts, last offset) | ≤ 256 | |
| Scalars | ≤ 200 | |
| **Total** | **≤ 656,840 B ≈ 642 KiB**, constant | at C = 4096; C = 65536 gives ≈ 2.1 MiB |

A 24-hour persistent Track costs the same ≈ 642 KiB of RAM as a 10-second one; its points live in the spool (§9.4). This replaces revision 1's "545 KiB + 12·D" and the invalid "Track duration, not video duration" distinction (§17 C4).

Worst-case live total: L = 100 → 62.7 MiB; L = 3,100 (pathological) → 1.94 GiB; both constant in video length. S1.4 measures peak RSS at volume.

### 9.2 Scratch during one candidate evaluation or one finalisation (transient)

| Item | Bytes |
|---|---|
| decoded frame (owned by the reader) | 3·W·H (4K: 24.9 MB) |
| crop copy | ≤ 3·W·H |
| resized image | ≤ 3 MiB |
| encoder output buffer | ≤ ~1.5 MB |
| sharpness float64 temporaries | ≤ 24 MB for a 1024² crop |
| finalisation: one spool chunk read buffer + per-chunk msgpack output | 24·C + ~24·C ≈ 192 KiB at C = 4096 |

Peak scratch ≈ 50 MB at 4K, constant.

### 9.3 Completion metadata per finalised Track

Scalars + ≤ 4 `ObservationDescriptor` + trajectory descriptor ≈ **2.3 KB** → 23 MB at T = 10,000. Admission reads these; no extra copy.

### 9.4 Staging disk per attempt

| Component | Bound | Lifetime |
|---|---|---|
| Spool (live Tracks) | Σ_live 24·D_spilled ≈ 62 MB per 24 h live Track; ≤ 24 × total detections of live Tracks | removed at each Track's retirement (`remove`), **after** the canonical artefact is published |
| Retirement transient (one Track at a time) | spool file (24·D) **+** the canonical temp file being written by `write_stream` (≈ 24·D) **+**, for the instant between publish and `remove`, the published canonical artefact — peak ≈ 3 × 24·D for that Track (≈ 186 MB for a 24 h Track), then back to the canonical size alone | bounded by one finalisation; finalisations are sequential |
| Evidence crops before admission | ≤ T × 557,056 = **5.19 GiB** at T = 10,000 (all four roles admissible) | removed to ≤ 1 GiB by `remove_omitted` before completion |
| Trajectories | Σ_T canonical size (≈ 24 B/point → ≤ 512 MiB quota) | until reclamation |
| **After completion** | 0 within seconds (worker fast path); otherwise janitor: normally ≤ `Grace + Interval` (20 min with defaults), or `Grace + ⌈(B+1)/M⌉ × Interval` under a backlog of B | §6.5 |
| **On failure** | 0 (`cleanup()`); otherwise janitor under the same normal/backlog bounds after `Failed` if the worker died | |
| **On lease loss** | removed at the next lease (S1.1) or by the janitor within one cycle of the job's next transition | |

### 9.5 Completion request

≤ 48 MiB by middleware; measured adversarial worst shape 29.24 MiB (gate ≤ 40 MiB, stop condition 32 MiB); realistic ≈ 9.6 MiB.

### 9.6 Accepted evidence per ProcessingRun

≤ 1 GiB crops + ≤ 512 MiB trajectories; the store re-sums admitted crop bytes and refuses > quota.

---

## 10. Persistence model and platform services (S1.2a)

### 10.1 Domain

`ObservationType → {Representative, NearView, EarlyDiverse, LateDiverse}`; `Observation` gains `EvidenceRank` (0..3) and `SelectionScore` ([0,1]); `AttachThumbnailArtifact` → `AttachEvidenceArtifact` (column unchanged); `ArtifactType` gains `EvidenceCrop`; domain rule `ObservationType == Representative ⇔ EvidenceRank == 0`.

### 10.2 Migration `2026MMDDHHMMSS_AddTrackEvidenceSet`

Up: add `evidence_rank integer NOT NULL DEFAULT 0`, `selection_score double precision NOT NULL DEFAULT 0`; `UPDATE observations SET selection_score = quality_score`; guard `RAISE EXCEPTION 'observations_legacy_type_present'` if any `observation_type NOT IN ('Representative')`; keep `evidence_rank DEFAULT 0` and make `selection_score NOT NULL` with a `BEFORE INSERT` trigger that fills an omitted value from `quality_score` (preceding-binary compatibility, below); constraints `ck_observations_type`, `ck_observations_rank (0..3)`, `ck_observations_role_rank ((observation_type='Representative') = (evidence_rank=0))`, `ck_observations_selection_score`; unique `(track_id, evidence_rank)`, `(track_id, observation_type)`, `(track_id, source_frame_number)`; FK `thumbnail_artifact_id` `SetNull → Restrict`. Down: reverse; never touches evidence bytes.

Backward readability: the preceding v2-only binary maps only known columns; new NOT NULL columns are populated for every row; migration-before-binary is safe; binary rollback before any v3 row is safe; rollback after v3 rows exist is unsupported (runbook).

**Preceding-binary compatibility (implemented, S1.2a deviation D1).** Revision 3 said to drop the defaults, which would falsify the rollback claim above: the platform applies migrations at start-up and an older binary starts against a database carrying this extra migration, then inserts observations with the v2 column list (no `evidence_rank`, no `selection_score`). The migration therefore keeps `evidence_rank DEFAULT 0` (every row an older binary can write is a rank-0 Representative) and a `BEFORE INSERT` trigger `tr_observations_default_selection_score` that sets `selection_score := quality_score` only when the inserted value is NULL — the same rule as the backfill. An explicit value is never overwritten; the current binary always writes both columns. `TrackEvidenceSetMigrationTests` insert with the preceding binary's exact column list and prove an explicit score survives. The default and trigger may be retired by a later migration once no supported rollback target predates S1.2a (i.e. when rolling back past S1.2a is no longer a supported operation).

### 10.3 Store

Per Track (ordinal): seal trajectory; seal each observation crop in rank order (`evidence/{job}/attempt-NNNN/crops/{trackId}-{role}-{sha}.jpg` for v3; `…/thumbnails/{trackId}-{sha}.jpg` for v2); rows; attach; save; `RepresentativeObservationId` (rank 0); visibility sequence; `job.Complete(digest)`; `run.MarkCompleted`; commit; compensation in reverse on failure. Replay unchanged.

### 10.4 Content serving

`EvidenceCrop + AcceptedEvidence + image/jpeg` in the allow-list; catalog rule as for Thumbnail.

### 10.5 Staging janitor

As specified in §6.5. Registration: `services.AddHostedService<StagingJanitorHostedService>()` behind `StagingJanitorOptions { Enabled = true, IntervalMinutes = 15, GraceMinutes = 5, UnknownJobGraceHours = 24, MaxDirectoriesPerCycle = 1000, WarnOldestEligibleMinutes = 60, ErrorOldestEligibleMinutes = 360 }`; `IStagingJanitor` (Infrastructure) does one cycle given a `TimeProvider`, so scheduling and deletion are tested separately, following the `SceneAnalyticsHostedService` / `ISceneAnalysisLifecycle` split.

---

## 11. Rollout, compatibility and rollback

### 11.1 Capability advertisement (S1.2a)

`GET /api/vision/contract` (same authorisation posture as the other worker endpoints under `/api/vision/jobs`, no body) → `200 {"schemaVersion":"2.0","completionSchemaVersions":["2.0","3.0"]}`. A v3 worker (S1.2c) calls it before READY; 404/malformed/missing `"3.0"` → `vision_platform_contract_unsupported`, not-ready, exit non-zero; re-checked on reconnect. A `400 worker_contract_version_unsupported` at `complete` is still a non-retryable attempt failure (defence in depth).

### 11.2 Deployment sequence

1. **Deploy S1.2a:** migration (additive) → platform binary. Verify: `GET /api/vision/contract` lists `"3.0"`; v2 workers keep completing; the janitor's first cycle reclaims any pre-existing completed-attempt staging (a one-time reclaim of historical v2 leftovers — small, but it is the first time this storage is bounded).
2. **Soak:** ≥ 1 v2 job completes and replays idempotently; janitor cycle summary (1400) observed.
3. **Deploy S1.2b:** worker with the spool. No wire change; v2 still emitted. Verify: trajectory artefacts of a soak job are byte-identical to the pre-S1.2b serializer for the same video (T1 in CI; the golden Scene Analytics fixture still decodes).
4. **Deploy S1.2c:** worker with profile `1.1`; checks the contract endpoint; emits v3.
5. **Later (out of S1.2):** retire v2 acceptance after (a) no release profile binds a v2 worker, (b) no `Leased` job's attempt was issued to a v2 worker, (c) an explicit decision records that v2 replay is no longer required (one lease duration after the last v2 worker stops). Separate PR.

### 11.3 Rollback

- S1.2c → S1.2b worker: v2 emitted; platform accepts; fine.
- S1.2b → S1.1 worker: identical trajectory bytes; fine.
- S1.2a binary after migration, before any v3 row: safe. After v3 rows: unsupported (runbook: roll the worker back first).
- Janitor: `StagingJanitor:Enabled=false` disables reclamation without affecting completion; staging then accumulates until re-enabled (stated cost).
- Migration down only with no v3 rows; never deletes evidence bytes.

---

## 12. Failure semantics (fail closed; lease/attempt semantics preserved)

| Situation | Behaviour | Code |
|---|---|---|
| encode raises | attempt fails; staging cleaned | `pipeline_processing_failed` |
| empty/invalid crop | candidate skipped, counted | telemetry |
| candidate over cap after ladder | unadmissible; holder unchanged | telemetry |
| no admissible Representative | attempt fails | `evidence_representative_missing` |
| malformed Evidence Set at `prepare_track` | `ValueError` → attempt fails | `pipeline_processing_failed` |
| trajectory non-monotonic on append; count/bounds mismatch at finalise | attempt fails (S1.1 codes) | `trajectory_offsets_not_monotonic`, `track_observation_missing` |
| spool append fails (disk full, I/O) | `StagingArtifactError` → attempt fails, cleanup | `pipeline_processing_failed` |
| spool chunk missing/short at finalise | `ValueError("trajectory_spool_corrupt")` → attempt fails | `pipeline_processing_failed` |
| staging write failure | unchanged | |
| lease lost between an encode and staging, or mid-spool | nothing published for live Tracks until retirement; every publication fenced; spool appends unfenced but never referenced; `LeaseLostError`; staging left for the next attempt/janitor | `lease_lost` |
| Representatives exceed run quota | attempt fails | `evidence_quota_exceeded` |
| v3 rejected by old platform | prevented at startup; else non-retryable | `vision_worker_contract_unsupported` |
| platform: observation/accounting rule violated | `vision_result_invalid` | validator codes |
| platform: crop missing/hash mismatch | existing artifact codes; compensation | |
| stale replay (v2 or v3) | same digest → success; else conflict | |
| mixed v2/v3 workers | both accepted; no fabricated supplementals for v2 | |
| worker dies right after successful `complete()` | job Completed; staging reclaimed by the janitor — normally within `Grace + Interval`, or per the backlog bound (§6.5) | EventId 1400 |
| worker dies mid-attempt (lease expires) | the job is re-leased (`Leased`, `AttemptCount+1`) and the next attempt removes lower attempts (S1.1); if the job exhausts attempts → `Failed` (`Exhaust`) → janitor | |
| janitor deletion fails / path escape | logged (1403/1402), retried each cycle, 1404 after 3; never affects completion | |
| janitor disabled | staging accumulates; health details show `stagingJanitor.enabled=false` | |

---

## 13. Qualification, CI and offline

### 13.1 Gates per PR

| Gate | S1.2a | S1.2b | S1.2c | Notes |
|---|---|---|---|---|
| **MAVI Quality Gate** (`dotnet build/test` with Postgres, `verify_repo`, Python suite, phase1 tools, web) | required | required | required | no path filter |
| **Task 17 Acceptance** | required | required | required | release truth stays pending |
| **Task 10 Runtime Qualification** | not triggered | required — the filter already covers `pipeline/**`; **widen** to `src/vision/mavi_vision/**`, `src/vision/tests/**`, `contracts/**` here so `video/**` and `storage/**` are covered | required | records exact head; `test_production_processor_runtime.py` updated per PR |
| **Task 10 Staging Security** (POSIX + Windows) | not triggered | required — add `append_bytes`/`write_stream`/`remove` tests to command and path filter | required | |
| **Task 14 read security** (POSIX + Windows `dotnet test` on storage safety) | required — **add** `StagingJanitor*.cs` and `StagingJanitorTests.cs` to its path filter and test filter, so janitor link-safety runs on Windows | — | — | |
| New v3 golden contract tests | .NET canonicalisation/digest, schema round-trip, worst-shape body; Python schema validation | — | emitter ↔ pinned digest | |
| Memory/bound tests | — | T1–T9 (Python suite) | E*, S*, A*, P*, M1–M5 | no multi-GiB fixture in CI |
| Staging lifecycle tests | J1–J14 (.NET, Postgres fixture + temp roots) | W5 (worker fast path) | P4 | |

### 13.2 Qualification truth

Profile SHA changes in S1.2c → qualification record re-derived, `pending`; Task 10 green recorded as "CPU matrices green on head X" only. B1/B3/B4 → "implemented, evidence pending S1.4"; B2 → "in-loop encoding and bounded trajectory spool implemented; RSS evidence pending S1.4"; B6 OPEN until S1.4.

### 13.3 Offline / dependency policy

**No** new Python package, .NET package, native library, codec, model, database extension, runtime-pack, model-pack or installer change. Pillow 11.3.0, numpy, msgpack are locked; `array`, `struct`, `tracemalloc` are stdlib; the janitor binds only operating-system libraries the platform already uses (libc; ntdll/kernel32), because `System.IO` has no handle-relative operations and path-based recursive deletion would weaken link safety (S1.2a deviation D3); it verifies the Linux open flags on the running kernel and fails closed otherwise. Overlay-only per ADR-007. `config/dependencies/offline-dependency-policy-v1.json` untouched.

---

## 14. Test matrix

Each test names the wrong implementation it catches.

### Trajectory spool (`tests/test_trajectory_spool.py`, S1.2b)

| Test | Catches |
|---|---|
| T1 `streamed_v1_bytes_identical_to_serialize_trajectory` — for N ∈ {1, 2, 15, 16, 255, 65535, 65536, 70000}, random offsets/centres: `b"".join(iter_trajectory_v1(...)) == serialize_trajectory(points)` | header rule or per-point encoding drift |
| T2 `bytes_identical_across_chunk_sizes_and_spill_counts` — same points with C ∈ {1, 7, 4096, N+1}; SHA equal | chunk-boundary artefacts |
| T3 `peak_live_memory_bounded_from_60_to_600_to_6000_points` — one persistent Track; `tracemalloc` peak of the processing loop for 6,000 points − peak for 600 points ≤ 64 KiB (both far below 24·C) | O(D) retention (list, cached chunks) |
| T4 `finalise_does_not_load_whole_trajectory` — instrument `read` sizes; max single read ≤ 24·C; total RAM sampled during finalise ≤ 2 chunks | whole-file read at retirement |
| T5 `lease_lost_mid_spool_leaves_no_published_trajectory_and_next_attempt_removes_spool` | unfenced publication; spool leak across attempts |
| T6 `failed_attempt_cleanup_removes_spool_directory`; `spool_removed_at_retirement` | spool leak within attempt |
| T7 `non_monotonic_append_fails_closed`; `corrupt_spool_chunk_fails_closed` | silent truncation/reordering |
| T8 `no_persistent_file_descriptors_per_live_track` — 2,000 live Tracks on POSIX with a lowered `RLIMIT_NOFILE`; no `EMFILE` | fd-per-Track design |
| T9 golden Scene Analytics fixture (`tests/fixtures/scene-analytics/worker-trajectory-v1.msgpack`) reproduced from its JSON points through the spool path | consumer-visible drift |

### Selector / encoder / admission / pipeline (S1.2c)

S1–S15, E1–E8, A1–A6, P1–P7 as in revision 1 of this plan (`git show f800378:docs/superpowers/plans/2026-09-23-stage2-s1-2-evidence-set-implementation.md` §14; carried forward verbatim into the implementation PR), plus:

| Test | Catches |
|---|---|
| **M1** `live_track_state_holds_no_ndarray` (gc scan after each frame) | raw crop retention |
| **M2** `evidence_image_memory_flat_with_track_duration` — one persistent Track, stub encoder returning fixed 100 KiB payloads; `tracemalloc` peak identical (± 64 KiB) for 60 / 600 / 6,000 frames; combined with T3 this proves total live memory is flat | any per-frame growth in the selector or accumulator |
| **M3** `encoded_bytes_per_live_track_never_exceed_caps` | oversize holders |
| **M4** `peak_traced_memory_flat_in_video_length_with_many_short_tracks` — 60 vs 600 vs 6,000 frames with a new 10-frame Track every 20 frames; peak difference bounded by completion-metadata growth (≤ 2.3 KB × ΔT + 64 KiB) | O(video-length) retention outside the metadata class |
| **M5** `finalised_metadata_holds_no_payload_bytes` (no `bytes` object > 1 KiB reachable from `finalised`) | payload retention in descriptors |

### Staging lifecycle — worker (S1.2b/S1.2c)

| Test | Catches |
|---|---|
| W5 `runner_cleans_own_staging_after_accepted_completion`; `cleanup_failure_does_not_fail_attempt` | fast path missing / affecting result |
| P4 `omitted_supplementals_removed_before_completion` (S1.2c) | leftovers |

### Staging janitor — platform (`tests/Mavi.IntegrationTests/StagingJanitorTests.cs`, S1.2a; temp media root + Postgres fixture)

| Test | Catches |
|---|---|
| J1 `terminal_job_attempt_removed_after_grace_not_before` (Completed and Failed; a synthetic `Cancelled` row is treated the same and logs 1405) | missing grace / never reclaiming |
| J2 `simulated_worker_death_after_completion_is_reclaimed` — complete via the real endpoint with staged files left in place; advance `TimeProvider`; one cycle → directory gone; accepted evidence bytes intact and servable | crash leak; deleting the wrong root |
| J3 `leased_job_current_and_later_attempts_never_removed_lower_attempts_removed_immediately` | fencing violation |
| J4 `queued_zero_attempt_with_staging_is_preserved_and_logged` (1401); `queued_positive_attempt_count_is_invariant_violation_preserved_and_logged` (synthetic row, 1406, nothing deleted) | destructive rule for a state the aggregate cannot reach |
| J5 `other_job_directories_untouched_when_one_is_reclaimed`; `non_canonical_names_untouched_and_logged` | over-broad deletion |
| J6 `cycle_is_idempotent_and_tolerates_concurrent_worker_cleanup` (directory removed between enumeration and delete) | ENOENT crash |
| J7 `symlinked_attempt_directory_is_refused_and_target_preserved` (POSIX) | link following |
| J8 `junction_attempt_directory_is_refused_and_target_preserved`; `nested_junction_inside_attempt_deleted_as_entry` (Windows; `task14-read-security.yml`) | reparse following |
| J9 `deletion_failure_is_logged_retried_and_escalates_after_three_cycles`; host keeps serving | silent failure / host crash |
| J10 `unknown_job_directory_removed_only_after_unknown_grace` | premature deletion |
| J11 `janitor_never_enumerates_outside_staging_prefix_or_evidence_root` (sentinel files) | scope escape |
| J12 `backlog_drains_across_cycles_with_per_cycle_cap` — 2·M + 1 eligible terminal directories with distinct ages; cycle 1 removes exactly the M oldest and reports `processed = removed = M`, `deferredByCap = M + 1`, `backlogDepth = M + 1`, `estimatedCyclesToDrain = 2`, `oldestEligibleAgeMinutes` = age of the oldest *remaining*; directories outside the processed batch still exist and are not counted as removed; cycles 2–3 finish; final `backlogDepth = 0` | cap ignored; deferred directories mis-reported as reclaimed; stale observability |
| J13 `backlog_age_thresholds_escalate` — oldest eligible age past `WarnOldestEligibleMinutes` → 1407 and health `backlogState = "warning"`; past `ErrorOldestEligibleMinutes` → 1408 and `"critical"`; back to `"normal"` when drained | silent backlog |
| J14 `retried_video_old_failed_job_and_new_queued_job_are_independent` — fail a job via the real `/fail` endpoint, retry the video via `QueueAsync` (new run + new `Queued`/0 job), stage directories for both ids; after grace the old job's directory is removed and the new job's directory is preserved (1401 if it has attempts, silent if empty) | cross-job inference |

### Wire and platform (S1.2a/S1.2c) — W1–W4, W6, N1–N8 unchanged from revision 1.

---

## 15. Exact file mapping

### S1.2a — platform and shared contracts

| Group | Files |
|---|---|
| Contracts | `Mavi.Contracts/Worker/WorkerContractRules.cs`; `VisionJobCompleteContracts.cs` (+observation, accounting; one request record with nullable `Representative`/`Observations`, version-driven validation); `CompletionIntegralJsonConverters.cs` (+observation list converter); `VisionContractCapabilitiesResponse.cs` |
| Validation | `Mavi.Application/Modules/Intelligence/VisionResultValidator.cs`; `IProcessingResultStore.cs` if needed |
| Persistence | `Mavi.Domain/Intelligence/Observation.cs`, `ObservationType.cs`; `Mavi.Domain/Media/ArtifactType.cs`; `Configurations/ObservationConfiguration.cs`; `Repositories/ProcessingResultStore.cs`; `Modules/Evidence/ContentReadService.cs`; `Repositories/ContentCatalog.cs` |
| Migration | `Persistence/Migrations/2026MMDDHHMMSS_AddTrackEvidenceSet.cs`, `MaviDbContextModelSnapshot.cs` |
| Staging janitor | `Mavi.Application/Abstractions/Storage/IStagingJanitor.cs`; `Mavi.Infrastructure/Storage/StagingJanitor.cs`, `StagingJanitorOptions.cs`, `StagingDirectorySafety.cs` (no-follow enumeration/deletion helpers, shared discipline with `StorageRootSafety`); `Mavi.Api/Storage/StagingJanitorHostedService.cs`; `Mavi.Infrastructure/DependencyInjection.cs`; `Mavi.Api/Program.cs` (hosted service + options + health details); `appsettings.json` (`StagingJanitor` section) |
| API | `Mavi.Api/Endpoints/VisionJobEndpoints.cs` (version set; `GET /contract`; per-message problem text); `Middleware/VisionCompletionRequestLimitMiddleware.cs` (constant) |
| Contract fixtures | `contracts/schemas/vision-job-complete-v3.schema.json`, `contracts/examples/…-v3.example.json`, `contracts/test-vectors/…-v3-conformance.json`, `…-v3-digest.json`, `control-plane-v3-invalid.json`, `contracts/README.md`; `tools/verify_repo.py` |
| CI | `.github/workflows/task14-read-security.yml` (janitor files + test filter) |
| Tests | `tests/Mavi.Application.Tests/VisionResultValidatorV3Tests.cs`, `VisionResultValidatorCanonicalizationTests.cs` (ext); `tests/Mavi.IntegrationTests/WorkerContractV3Tests.cs`, `VisionResultCompletionApiTests.cs` (ext), `MigrationTests.cs` (ext), `ContentApiTests.cs` (ext), **`StagingJanitorTests.cs`**, `StagingJanitorHostedServiceTests.cs` (scheduling with fake `TimeProvider`); `tests/Mavi.Domain.Tests/Task13CompletionDomainTests.cs` (ext); Python `test_contract_schema_canonicalization.py` (ext) |
| Docs | this plan; parent §16; `docs/runbooks/vision-runtime-model-component-lifecycle.md` (new "Completion contract v3 deployment order" and "Staging reclamation" sections); `contracts/README.md`; ADR-006 §6 (accepted 2026-09-23) and the ADR-013 staging sentence (§17 C3) |

### S1.2b — worker trajectory spool (no wire change)

| Group | Files |
|---|---|
| Spool | `mavi_vision/video/trajectory_spool.py` (new); `video/trajectory.py` (+`iter_trajectory_v1`, header helper; `serialize_trajectory` kept and now implemented via the iterator to guarantee identity) |
| Store | `storage/artifact_store.py` (`append_bytes`, `write_stream`, `remove`, `spool_key`); `artifact_store_posix.py`, `artifact_store_windows.py` (append with `O_APPEND`/`FILE_APPEND_DATA` on a handle-relative open that refuses links; streamed temp write with incremental SHA; single-leaf remove) |
| Pipeline | `pipeline/process_video.py` (`_TrackState` with `spool: TrajectorySpool`, scalars; no point list); `pipeline/finalization.py` (`prepare_track` takes `TrajectorySummary` + trajectory descriptor produced by the spool sink; drops `trajectory: tuple`); `storage/artifact_publisher.py` (`publish_trajectory_stream(track_id, chunks)`; `publish_track` takes the descriptor) |
| Settings | `common/settings.py` (`trajectory_spool_chunk_points`) |
| Runner | `worker/runner.py` (post-completion `cleanup()` fast path, W5) |
| Tests | new `test_trajectory_spool.py`; ext `test_track_finalization.py`, `test_track_lifecycle.py`, `test_process_video.py`, `test_artifact_store.py`, `test_artifact_store_windows.py`, `test_artifact_publisher.py`, `test_worker_runner.py`, `test_production_processor*.py` |
| CI | `task10-runtime-qualification.yml` (widen path filter); `task10-staging-security.yml` (new store tests) |
| Docs | this plan (status) |

### S1.2c — worker Evidence Set + v3

As revision 1's S1.2b mapping: `common/analytical.py` (observations, accounting), `evidence/*`, `process_video.py` (FrameContext, selector per live Track, admission + `remove_omitted`), `finalization.py` (multi-role payloads via the encoder), `artifact_publisher.py` (`evidence/{trackId}-{role}.jpg`, `remove_omitted`), `runtime/profile.py` (schema 1.1), profile JSON + qualification SHA, `control_plane.py` v3, `worker/client.py` (`complete` v3, `get_contract_capabilities`), `worker/runner.py`/`health.py`/`main.py` (startup check, 400 handling); tests S/E/A/P/M/W; `docs/qualification/…-parameter-note.md`; register rows.

---

## 16. Implementation sequence

### S1.2a (one PR, ~7 commits)
1. Domain + migration + snapshot + `MigrationTests`.
2. Contracts + converters + constants + `GET /api/vision/contract`.
3. Validator dispatch (v2 normalisation, v3 rules, digest v3) + tests; v2 tests untouched.
4. Store multi-observation sealing/persistence/compensation; content allow-list; integration tests.
5. **Staging janitor** (`IStagingJanitor`, safety helpers, hosted service, options, health details) + J1–J14 + Task-14 workflow filter.
6. Contract fixtures + `verify_repo` + canonicalisation tests (pins the golden digest).
7. Docs (parent §16, runbook, README).

Exit: Quality Gate + Task 17 + Task 14 green on the exact head; a `main` v2 worker completes against the S1.2a platform in the composition test; J2 proves crash-after-completion reclamation; J12 proves the backlog drain.

### S1.2b (one PR, ~4 commits; independent of S1.2a)
1. `iter_trajectory_v1` + T1/T2 (pure).
2. Store `append_bytes` / `write_stream` / `remove` on both backends + staging-security tests.
3. `TrajectorySpool`, `_TrackState`, `prepare_track`/publisher changes + T3–T9.
4. Runner fast-path cleanup + W5; Task 10 filter widening; docs.

Exit: Quality Gate, Task 17, Task 10 (both OS), Staging Security green on the exact head; T1/T9 prove byte identity; T3 proves the bound.

### 16.1 S1.2b as implemented (baseline `main@7609a3a`)

The spool follows §6.3 Option B. The code differs from §15 in these places, all confined to the worker, with no wire, digest or Scene Analytics change:

| ID | Plan | As implemented | Why |
|---|---|---|---|
| E1 | Store gains `append_bytes`, `write_stream`, `remove` | Also **`read_chunks(name, chunk_bytes, expected_size)`**: a handle-relative, no-follow sequential read that fails closed unless the file holds exactly `expected_size` bytes | Reading the spilled chunks back needs a hardened read; an ad-hoc `open()` would bypass the attempt-scoped, link-refusing backends |
| E2 | `common/settings.py` `trajectory_spool_chunk_points` | No setting. `VideoProcessor(..., trajectory_chunk_points=4096)` is a test seam only | The chunk size changes memory and I/O cadence, never bytes. It is not operator configuration |
| E3 | `spool_key(track_id)` | `spool_relative_name(track_id)` → `spool/{trackId}.traj` | A spool is never referenced by a descriptor, so it has no storage key |
| E4 | `publish_trajectory_stream(track_id, chunks)`; `publish_track` takes a descriptor | `publish_track(prepared, trajectory_chunks)` stages the thumbnail, then streams the trajectory through `write_stream` | This keeps one lease-fenced publication gateway and the existing thumbnail → trajectory order. `prepare_track` still validates everything before any publication |
| E5 | `_TrackState` | `_TrackAccumulator` keeps its name; its `trajectory` field is now a `TrajectorySpool` | Smaller diff. The lifecycle tests' gc scan already targets this class |
| E6 | Validation on append plus count checks | Also: every spill checks the file length, and a running SHA-256 of all spilled bytes is kept in constant memory. The read-back must match size, record alignment, monotonicity, value ranges, recorded endpoints and the digest | So a damaged or foreign-written spool fails closed instead of being published |
| E7 | `finalise(sink)` | `TrajectorySpool.finalise(publish)` passes the v1 byte iterator to `publish` and removes the spool file only after `publish` returned. A failed publish leaves the spool to attempt cleanup | The "remove only after a successful publish" rule is enforced in one place |

W5: `WorkerRunner(staging_cleaner=...)`, composed in `build_runner`, removes the accepted attempt's staging after `complete()` returns. It runs off the event loop, and a failure is logged and never changes the attempt; the janitor (§6.5) remains the crash-safe bound. The runner does not call it on failure (the processor cleans itself up) or on lease loss (the next attempt or the janitor handles that).

Test mapping. The request's T1–T9 map to the plan's §14 names as follows. T1/T2 are the plan's T1/T2. T3 is T3. T4 (ordering) is part of T1/T2 plus `test_points_stream_in_append_order_across_spill_and_buffer`, and bounded reads are the plan's T4. T5 (corruption) is the plan's T7. T6 (lease loss) is the plan's T5. T7 and T8 (failure and retry cleanup) are the plan's T6. T9 (descriptors and handles) is the plan's T8 at two levels: 2,000 spools, and a 300-Track pipeline under a lowered `RLIMIT_NOFILE`, with a handle count on Windows. The golden fixture is the plan's T9, run through the spool at chunk sizes 1, 2, 3 and 4096.

### S1.2c (one PR, ~7 commits; requires S1.2a **deployed** and S1.2b merged)
As revision 1's S1.2b sequence (profile → roles/quality/encoder → selector → admission → pipeline integration → wire/client/runner → measurement note/docs/register).

Exit: all gates green on the exact head; the worker's own emitted golden example matches the S1.2a pinned digest.

### 16.2 S1.2c as implemented (baseline `main@85ae91f`)

Seven commits: profile 1.1 → scorer and encoder → selector → admission and pipeline integration → wire 3.0, capability gate and runner → CI → S14 golden and measurement tool, then docs. No new dependency; `config/dependencies/offline-dependency-policy-v1.json` is untouched (§13.3 holds).

**Module layout.** `mavi_vision/evidence/`: `roles.py` (roles, order, caps, quota), `policy.py` (immutable `EvidencePolicy`, versions, integer-micro quantisation), `quality.py` (`QualityScorer` protocol, `QualityV2Scorer`, credible-competitor occlusion proxy, `scorer_for_policy`; E24), `encoder.py` (`EvidenceEncoder` protocol, `JpegLadderEncoder`), `selector.py` (`EvidenceSelector`), `admission.py` (pure `admit`), `errors.py`. Scorer, encoder and selector are replaceable behind their protocols; `VideoProcessor` takes `evidence_scorer` / `evidence_encoder` seams, and the profile's version strings name what is running.

| ID | Plan | As implemented | Why |
|---|---|---|---|
| **E8** | §4.2: Representative = best *qualified* admissible candidate; none → attempt fails | **Two-tier Representative.** Until a Track has a qualified admissible candidate, the holder is the ε-fold over all admissible candidates; the first qualified one displaces it, and from then on only qualified candidates can hold the role. Supplemental roles unchanged. No admissible candidate at all → `evidence_representative_missing` | The strict rule fails a whole run whenever one Track has no qualified frame (edge-clipped, persistently overlapped, low texture). The scripted corpus measures 0 % qualified frames (§5 note), so under the strict rule every corpus job fails. **ADR-013 §4 amendment, accepted 2026-09-24.** A Representative may therefore be unqualified; supplemental roles stay qualified-only. Completion 3.0 carries no qualified flag (a known limitation; see the ADR's wire boundary) |
| E9 | §4.1: occlusion excludes the candidate by `frame_ordinal` | Excludes the one detection with the candidate's class **and exact box**. No match → `evidence_candidate_detection_unmatched` (fail closed) | `TrackCandidate` carries no detection ordinal. Exact equality is reliable because ByteTrack and the fixture tracker return the detector's box object unchanged |
| E10 | §5 encoder block | Adds `encoder.encoderVersion: "evidence-jpeg-ladder-v1"`; every encoder value and the quota are fixed and the loader rejects anything else | So the profile (and therefore `pipelineProfileSha256` in provenance) names the scorer, the selector **and** the encoder |
| E11 | §4.1 `quantize(x) = floor(x·10⁶)/10⁶` | Scores are held and compared as integer millionths (`quality_micro`, `selection_micro`); `replaceEpsilon` is converted exactly and the loader rejects precision finer than 10⁻⁶. The wire value is `micro / 10⁶` | Integer comparison has no float edge cases at ε; the emitted values are identical |
| E12 | §4.2 C1 invariant: "the earliest candidate among those within ε of the top score" | The online rule is the **ε-fold**: the holder changes only when a candidate beats the *current holder* by more than ε. The two differ (scores .50, .515, .53 fold to .53; "earliest within ε of top" would pick .515). Tests assert the fold with an independent oracle (300 random trials); the no-reservoir argument holds for the fold unchanged | Correction of the invariant's wording, not of the rule |
| E13 | §11.1: not-ready and **exit non-zero** | The runner probes `GET /api/vision/contract` before its first lease and after any control-plane error. An incompatible, missing or malformed answer keeps the worker **not-ready and re-probed each poll**, with no lease and no v2 fallback. Local readiness reason: `vision_platform_contract_unsupported`, logged once per incompatible period. `get_worker_health` also refuses READY without confirmation, but it has no production caller yet; the effective gate is the runner's refusal to lease | Matches the request (stay not-ready, never lease) and the existing readiness loop; an exit loop under the service manager adds nothing |
| E14 | §11.1: `400 worker_contract_version_unsupported` at `complete` is a non-retryable attempt failure | `PlatformContractUnsupported` → `/fail` with `vision_worker_contract_unsupported`, the capability is un-confirmed, and the completion is neither retried nor re-sent as 2.0 | Terminal for the attempt; the platform's retry policy decides the job |
| E15 | §6.2 `AdmissionError("representative_quota_exceeded")` | `EvidenceError("evidence_quota_exceeded")`; all evidence errors are `EvidenceError(ValueError)` with a stable `.code` and surface as `pipeline_processing_failed` | One error family for the evidence package |
| E16 | S1.2b E4: publication order thumbnail → trajectory | Trajectory stream first, then each crop in rank order, each write lease-fenced (`evidence/{trackId}-{role}.jpg`); `remove_omitted` is lease-fenced and removes one regular-file leaf per omitted crop through the hardened `remove` | Crops are the part admission may later remove; staging them last keeps the ordering simple |
| E17 | §14 S14: golden selection on the C1 videos | Rendered losslessly in numpy from the same position model, in two variants (flat as drawn; textured). The flat outcome matches the real ffmpeg videos (fallback Representative at frames 40, 29, 25) | Pinned outcome independent of the x264 build |
| E19 | §5 `selectorVersion: "evidence-selector-v1"` | `evidence-selector-v1-two-tier` | E8 changes the Representative rule, so it carries its own name. The version string alone, not only the profile SHA, then distinguishes it from the strict rule. If E8 is rejected, the strict rule returns as `evidence-selector-v1` |
| E20 | — | The worker refuses a Track beyond the completion's 10,000-Track bound as soon as it appears (`track_limit_exceeded` → `vision_processing_failed`), before staging anything for it. A result that still fails the local v3 model is failed as `vision_result_invalid` without sending, not left to escape the runner | Found by the cold review. Without the cap, an over-large run staged up to ≈ 10 GiB and then crashed the worker loop on every re-lease (poison job) |
| E21 | §11.1: re-check "on reconnect" | The capability is probed before **every** lease | Found by the cold review. A platform downgraded between leases would otherwise cost one fully processed job a terminal `/fail` |
| E22 | §13.2: qualification record re-derived, `pending` | Also resets the `windows-x86_64-cpu` and `linux-x86_64-cpu` gates from `passed` to `pending` and removes their evidence (runs at head `695be6f`, which qualified the previous profile) | Those runs never exercised the evidence selector and encoder. The gates are re-earned by running the Task 10 CPU matrices against this exact profile (S1.4). Flagged by the Codex review |
| E23 | §5: real-clip measurement before merge | Measured with `tools/vision/dev/measure_evidence_real_clips.py` on a runtime built from the qualified `linux-x86_64-cpu` definition (supervisor READY, exact Python identity, the hash-locked graph with `mmcv` rebuilt locally from its pinned commit), for MOT17-02-FRCNN and MOT17-13-FRCNN. The official WebM previews are 960×540, so the primary clips are the benchmark's 1920×1080 `img1` JPEGs stream-copied into MP4 (MJPEG, byte-identical packets). The first run found F1 (fixed by E24). The final run, on quality-v2, retains every default | The official previews are not the benchmark resolution |
| E24 | §4.1: `occlusionIou` over every other detection | Scorer **`quality-v2`**: the proxy counts only competing detections, of either class, with `confidence ≥ confidenceFloor` (inclusive). The candidate's own detection is excluded before that filter. `scorer_for_policy` builds the scorer from the profile, and the loader refuses `quality-v1`. The profile SHA becomes `503225be…23fb`, the qualification record is rebound, and every gate stays `pending` | Parameter note F1: quality-v1 took every detection down to `detectorInferenceFloor` 0.05. 93 % of occlusion rejections came from sub-floor residue, 58.7 % of Representatives were fallbacks, and vehicles qualified in 1 frame of 2,801. No ceiling value separates such near-duplicates from real occlusion. Owner decision (option (a)); ADR-013 §4 occlusion-proxy amendment |
| E18 | — | `control_plane.VisionJobComplete` (2.0) is kept for the unchanged 2.0 contract tests; the worker never emits it. `VisionJobCompleteResponse.schemaVersion` accepts "2.0" and "3.0", and the client refuses any echo other than "3.0" | The platform echoes the request's version |

**Accounting semantics.** Per role, `candidates` = observations in the Tracks' resolved Evidence Sets (every one of them staged); `admitted` = observations kept after admission; `omitted = candidates − admitted`; bytes likewise. Views dropped by `resolve()` as duplicates were never staged and are not candidates. Representative `omitted` is always 0 (a run whose Representatives exceed the quota fails instead).

**Test mapping.**

| Plan ID | Test (file) |
|---|---|
| S1, S2 | `test_representative_replaces_only_beyond_epsilon`, `test_epsilon_boundary_is_strict_and_exact` (`test_evidence_selector.py`) |
| S3 | `test_unqualified_frames_never_hold_a_supplemental_role`, `test_qualification_thresholds_are_inclusive_floors` |
| S4 | `test_real_scorer_disqualifies_an_occluded_frame`; `test_occlusion_uses_every_other_credible_detection_of_both_classes` (`test_evidence_quality.py`) |
| E24 | `test_low_confidence_duplicate_is_ignored`, `test_detection_exactly_at_the_floor_is_counted_and_just_below_is_not`, `test_high_confidence_same_class_overlap_is_counted`, `test_high_confidence_cross_class_overlap_is_counted`, `test_the_strongest_credible_competitor_wins_over_a_stronger_sub_floor_overlap`, `test_a_sub_floor_source_detection_is_still_excluded_as_the_candidate_itself`, `test_the_competitor_floor_is_mandatory_and_bounded`, `test_the_policy_scorer_follows_the_profiles_confidence_floor` (`test_evidence_quality.py`); `test_real_scorer_ignores_a_sub_floor_overlap` (`test_evidence_selector.py`); `scorerVersion` `quality-v1` refused (`test_evidence_profile.py`) |
| S5, S6 | `test_near_view_grows_by_hysteresis_only`, `test_repeated_marginal_improvements_do_not_thrash`, `test_near_view_seeds_on_the_first_non_duplicate_and_never_on_the_representative_frame` |
| S7, S8 | `test_early_diverse_takes_the_best_view_inside_the_window_and_freezes_after_it`, `test_early_diverse_requires_separation_at_evaluation_time`, `test_early_window_is_anchored_to_track_start_not_frame_zero` |
| S9 | `test_late_diverse_is_a_trailing_view_refreshed_at_the_interval`, `test_late_diverse_does_not_refresh_too_soon` |
| S10, S11 | `test_resolve_omits_duplicates_in_role_order_and_reranks_contiguously`, `test_resolve_is_idempotent_and_pure` |
| S12, S13 | `test_better_candidate_that_fails_encoding_keeps_the_valid_holder`, `test_no_admissible_representative_resolves_to_nothing` |
| S14 | `test_golden_selection_on_the_scripted_corpus` (`test_evidence_scripted_corpus.py`) |
| S15 | `test_selector_holds_at_most_four_encoded_images_and_no_ndarray` |
| E8 (two-tier) | `test_representative_invariant_holds_against_an_independent_oracle`, `test_first_qualified_candidate_displaces_a_fallback_whatever_its_score`, `test_fallback_holders_follow_the_epsilon_rule_among_themselves`, `test_short_featureless_track_still_gets_a_fallback_representative` |
| E1–E4, E7, E8 (encoder) | `test_evidence_encoder.py`: exact ladder, never upscales, first step under cap, `None` after exactly 15 attempts, 1-px and extreme aspect ratios, baseline 4:2:0 without EXIF/ICC |
| E5, E6 | `test_golden_bytes_per_runtime_variant` (pinned for Linux / Pillow 11.3.0; other variants skip rather than claim), `test_adversarial_noise_is_admitted_as_measured_under_each_cap` |
| A1–A6 | `test_evidence_admission.py` (named in each docstring), plus skip-and-continue, exact-fill, re-ranking and input-order determinism |
| P1–P7 | `test_evidence_pipeline.py` (named in each docstring), plus encoder and staging-write failure cleanup |
| M1–M5 | `test_live_track_state_holds_no_ndarray_and_at_most_four_images` (M1, M3), `test_evidence_memory_is_flat_with_track_duration` (M2), `test_many_live_selectors_retain_only_their_holders` (M4), `test_result_observations_are_canonical_and_descriptor_only` (M5) |
| W1, W2 | `test_python_v3_model_rejects_every_shared_invalid_vector` (all 29 vectors of `control-plane-v3-invalid.json`, schema- and validator-level, the ones the .NET validator rejects), `test_python_v3_model_follows_the_shared_integer_conformance_corpus`, `test_worker_body_validates_against_the_v3_json_schema` (`test_worker_completion_v3.py`) |
| W3 | `test_worker_body_is_byte_equivalent_to_the_golden_example` (the emitter reproduces the golden example exactly, so it reproduces the S1.2a pinned digest), `test_pipeline_generated_body_validates_against_schema_and_model` |
| W4 | `test_worker_contract_capability.py` (never leases before "3.0"; re-probe; upgrade; terminal 400), `test_incompatible_or_malformed_capabilities_are_unsupported`, `test_contract_rejection_raises_unsupported_and_sends_nothing_else`, `test_worker_health_is_not_ready_until_platform_accepts_completion_3` |
| W6 | `test_worst_shape_body_stays_within_the_budget`: 10,000 Tracks × 4 roles through the real client, **24.72 MiB** (gate 40 MiB) |
| Profile | `test_evidence_profile.py` (versions, bounds, closed shape, any parameter change changes the SHA, qualification record re-derived and `pending`) |
| Staging security | evidence-name tests in `test_artifact_store.py` / `test_artifact_store_windows.py`; `test_evidence_pipeline.py` added to Task 10 Staging Security (Ubuntu + Windows) |

Each boundary leaves `main` buildable, testable, deployable and contract-compatible with the previous one: S1.2a changes no worker; S1.2b changes no byte any consumer sees; S1.2c is the only wire change and is guarded by the capability check.

---

## 17. Corrections to the parent plan and ADR flags

| ID | Finding | Correction | Ratification |
|---|---|---|---|
| **C1** | S1-14 introduced a K-candidate Representative fallback reservoir. | Online "best admissible" holder rule; equivalence proof in §4.2; E6 measurement retained. | **Owner — recommended for ratification** (replaces an owner correction) |
| **C2** | Parent §12.2/§12.6 require a Python-computed digest. | Digest stays server-side; cross-language agreement pinned on the body (§7.5). | Plan-level |
| **C3 (revised)** | Neither the parent plan nor ADR-013 §5 accounts for the staging of a *successfully completed* attempt; revision 1 proposed a best-effort worker cleanup, which is not crash-safe. | Platform-owned **staging janitor** with database authority (§6.5, §10.5): normal reclamation target ≤ `Grace + Interval` (20 min with defaults) and an explicit backlog bound `Grace + ⌈(B+1)/M⌉ × Interval`; worker cleanup demoted to fast path. This **moves ownership** of staging reclamation from "worker courtesy / later GC" to the platform. ADR-006 needs an **amendment** (new decision "6. Platform-owned reclamation of worker staging": the platform reclaims `staging/{job}/attempt-*` using the VisionJob row as sole authority; worker cleanup is an optimisation; normal reclamation target and backlog bound stated; destructive authority limited to states the aggregate can reach). ADR-013 §5's sentence "cleaned by the existing attempt cleanup" should read "reclaimed by the platform staging janitor (ADR-006 §6), with worker attempt cleanup as a fast path". Neither ADR was edited by the plan PR; S1.2a (PR #77) adds ADR-006 §6 and the ADR-013 wording, and the owner ratified §6 on 2026-09-23. | **Resolved — ADR-006 §6 accepted; ADR-013 wording updated** |
| **C4 (revised)** | Parent: "≤ 4 × 160 KiB plus its trajectory-in-progress" left the trajectory term unbounded; revision 1 quantified it as 12·D and wrongly called that "independent of video length". | Trajectory spool (§6.3): live memory per Track is a constant ≈ 642 KiB; the trajectory lives in attempt staging until retirement. Parent §6.4's "trajectory-in-progress" as *live processing memory* becomes "one trajectory chunk". | Plan-level (ADR-013 §5 already says live memory is bounded by live Tracks; this makes it true) |
| **C5** | v3 worker vs old platform burned an attempt. | Capability endpoint (§11.1). | Plan-level |
| **C6** | Resolve precedence unspecified for NearView/Late. | Uniform resolve rule (§4.3). | Plan-level |
| **C7** | `SelectionScore` vs `QualityScore` duplication. | Kept, rationale §7.2. | — |
| **C8 (new)** | Parent §16 has two S1.2 PRs; the spool has no wire dependency and the S1.2c evidence work builds on it. | Three PRs: S1.2a, S1.2b (spool), S1.2c (Evidence Set + v3). | Plan-level (parent §16 pointer updated) |
| **C9 (new)** | `TrajectoryDecoder.MaximumSamples = 1_000_000` means a Track > ≈ 9.3 h at 30 fps is `trajectory_invalid` for Scene Analytics today; the spool makes such Tracks producible without exhausting memory. | Recorded as an S1.4 / Scene Analytics hardening item (§20); not changed in S1.2. | Plan-level |

---

## 18. Acceptance criteria

**S1.2a done when:** migration applied and tested; platform accepts v2 and v3 with distinct digests; v3 persists ≤ 4 observations with role/rank/score and `EvidenceCrop` artefacts; content serving covers `EvidenceCrop`; `GET /api/vision/contract` advertises both; golden v3 fixture and digest pinned; worst-shape body ≤ 48 MiB − 8 MiB; **staging janitor reclaims completed/failed/superseded attempts under J1–J14, including the crash-after-completion case, the per-cycle-cap backlog drain with truthful observability, the fail-closed `Queued` states and the retried-video independence, on POSIX and Windows**; Quality Gate + Task 17 + Task 14 green on head; a `main` v2 worker completes against it.

**S1.2b done when:** trajectory artefacts are byte-identical to the previous serializer (T1, T2, T9); per-live-Track memory is constant in Track length (T3, T4); spool is removed at retirement, on failure and by the next attempt (T5, T6); fd usage does not scale with live Tracks (T8); store primitives pass staging-security tests on both OSes; runner fast-path cleanup (W5); Task 10 filter widened; all gates green on head.

**S1.2c done when:** worker emits v3 conforming to the schema and pinned example; S/E/A/P/M/W tests green; no `np.ndarray` retained per live Track (M1); evidence-image memory flat with Track duration (M2) and total live memory flat with video length given constant live Tracks (M4); omitted evidence removed before completion; worker refuses READY without v3 acceptance; profile `1.1` with re-derived qualification SHA; measurement note committed; all gates green on head.

Register: B1, B3, B4 → "implemented — evidence pending S1.4"; **B2 → "in-loop encoding, retirement finalisation and bounded trajectory spool implemented; live memory per Track constant; RSS evidence pending S1.4"**; B5, B6 unchanged.

---

## 19. Deferred to S1.3 / S1.4 / later

- `TrackDetail.observations[]`, web types, Evidence Set viewer (S1.3).
- Peak-RSS at volume, staging bytes per run, sealing wall time at bound, admission rates, janitor reclamation timing under load, Task-10 rebinding, CUDA/E2E rebinding (S1.4).
- v2 acceptance removal (§11.2 step 5).
- Garbage collection of **orphaned sealed evidence** in the evidence root (ADR-006 §5 leftovers) — still deferred; the janitor deliberately never touches the evidence root.
- Retention/purge policy for supplemental crops (ADR-013 §19).
- `TrajectoryDecoder.MaximumSamples` policy for Tracks longer than ≈ 9.3 h (C9).
- Crop pixel dimensions on the wire (excluded; revisit with the attribute lease contract).
- Trajectory v2 (separate slice).

---

## 20. Open risks

| Risk | Mitigation | Residual |
|---|---|---|
| Selector defaults poorly tuned | measurement note done (scripted + 2 real clips; re-measured on quality-v2; all defaults retained); `confidenceFloor ≤ activation` enforced | profile revision after S1.4 evidence |
| A consumer treats a fallback Representative as qualified evidence (S1.2c) | ADR-013 §4 amendment and `contracts/README` forbid inferring qualification from the role; supplemental roles are qualified-only | completion 3.0 has no qualified flag; a qualification-sensitive feature must add an explicit contract first |
| A later Representative replacement makes the NearView holder a near-duplicate; `resolve()` drops it, and a new NearView must beat the dropped holder's area by × (1 + growth) (S1.2c cold review) | deterministic; accepted by §4.2 note 3; measured on real clips: 1 of 52 held NearViews dropped (1.9 %, quality-v2) | measure NearView loss at volume in S1.4 |
| F1 (resolved by E24): the quality-v1 occlusion proxy counted every detection down to `detectorInferenceFloor` 0.05 | scorer `quality-v2` counts only competing detections ≥ `confidenceFloor`; re-measured (fallback 58.7 % → 14.3 %, vehicles 14/15 → 0/15) | a real occluder seen only below `confidenceFloor` no longer disqualifies; credible same-object `car`/`truck` boxes still block 6.1 % of vehicle candidates; sharpness is scale- and texture-dependent (a future scorer version) |
| The capability gate is invisible outside the log (S1.2c) | the runner never leases without "3.0"; logged once per incompatible period | `get_worker_health` has no production caller yet; wiring a health surface is future work |
| Floor-size JPEG of pathological content > 64 KiB | E6 per variant; online best-admissible rule; attempt fails only with zero admissible frames | accepted per ADR |
| CPU: sharpness + ≤ 15 encodes per replacement | ε/hysteresis/window bounds; S1.4 measures | cheaper sharpness in a scorer v2 |
| Pathological live-Track count (L ≈ 3,000 → ≈ 1.9 GiB live) | bound stated; constant in video length; S1.4 measures | Development hosts |
| Spool I/O on slow disks (one 96 KiB append per Track per ≈ 2.3 min at 30 fps) | no fsync; open-append-close; S1.4 measures | negligible expected |
| Janitor and worker both deleting the same directory | both idempotent; ENOENT tolerated; grace ordering | none |
| Janitor misconfigured `RootPath` | it only ever enumerates `{RootPath}/staging`; `StorageRootSafety` validates the root at start; J11 | none |
| Platform down for a long period, or a reclamation backlog (B > M) | no completions occur while down; on restart the backlog drains at M per cycle under the stated bound; 1407/1408 thresholds and health `backlogDepth`/`oldestEligibleAgeMinutes` make it visible | retention above the normal target until drained |
| A future `VisionJob` transition (requeue, cancel) is added without updating the janitor | the janitor fails closed on `Queued && AttemptCount > 0` (1406) and logs `Cancelled` (1405); J4/J1 pin this; any such transition must revisit §6.5 | none beyond visibility |
| Tracks > 1,000,000 samples (C9) | recorded; producible now | Scene Analytics `trajectory_invalid` for such Tracks (pre-existing) |
| Sealing time under the row lock with ≤ 5 objects/Track | unchanged authority semantics; S1.4 measures | |
| Cross-OS detector/tracker parity not asserted | out of scope; stated | |
| Stale N−1 writer racing attempt N cleanup (S1.1) | unchanged | retryable failure |
| v2 retirement timing | explicit conditions §11.2 | separate decision |
