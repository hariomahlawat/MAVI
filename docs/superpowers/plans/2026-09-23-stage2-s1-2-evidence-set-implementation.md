# MAVI Stage 2 — S1.2 Track Evidence Set: implementation plan

**Status:** Implementation-ready plan, revision 2 (after the first independent cold review); awaiting a second independent review. No S1.2 code exists yet.  
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
| `VisionJob.Status ∈ {Queued, Leased, Completed, Failed, Cancelled}`; `AttemptCount` increments on lease; a Completed job is never re-leased; a Failed job that is requeued gets `AttemptCount+1` on its next lease | `Mavi.Domain/Processing/VisionJob.cs`, `ProcessingOrchestrator.LeaseAsync` |
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
| `evidence/quality.py` | replaceable scorer | `class QualityScorer(Protocol): def score(self, ctx: FrameContext, bbox) -> CandidateQuality`; `QualityV1Scorer` wraps today's formula + occlusion proxy | S1.2c |
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
- **Qualified candidate** (all must hold): `confidence ≥ confidenceFloor`; `sharpness ≥ sharpnessFloor`; `edgeMargin ≥ edgeMarginFloor`; `occlusionIou < occlusionIouCeiling`, where `occlusionIou = max IoU(candidate.bbox, d.bbox)` over every other detection `d` in the frame (identity by `frame_ordinal`; 0.0 if none).
- **Scores** (`CandidateQuality`): `quality_score = representative_quality(frame, bbox)` (formula v1); `selection_score = quantize(clamp01(quality_score − occlusionPenaltyWeight·occlusionIou))`; `area = bbox.width·bbox.height`. `quantize(x) = floor(x·10⁶)/10⁶`, applied before any comparison and before emission (§8).
- **Near-duplicate** of a selected frame S: `same source_frame_number`, or `|offset − S.offset| ≤ duplicateWindowMs and IoU(bbox, S.bbox) ≥ duplicateIouThreshold`.
- **Separated** from S: `|offset − S.offset| ≥ minSeparationMs`.
- **Admissible**: the encoder returned bytes ≤ the role's cap (§6.1). An unadmissible candidate never becomes a holder; the holder stays.

### 4.2 Per-role rules

Evaluated for every accepted frame in which the Track has a candidate, in the order below. Each rule reads only the candidate, `FrameContext`, the profile and the selector's current holders. A holder is `SelectedEvidence(role, offset_ms, source_frame_number, confidence, bbox, quality, image: EncodedImage)`.

| Role | Eligibility | Replacement rule (strict) | Tie | Window / freeze | Encodes bounded by |
|---|---|---|---|---|---|
| **Representative** (mandatory, rank 0) | qualified | `selection_score > holder.selection_score + replaceEpsilon` **and admissible** | equal or within ε keeps the earlier frame | whole Track; never frozen | ≤ 1/replaceEpsilon |
| **NearView** | qualified; not near-duplicate of the Representative holder | `area > holder.area·(1 + nearViewGrowth)` and admissible (first qualified non-duplicate candidate seeds it) | equal area keeps earlier | whole Track | ≤ ⌈ln(1/areaMin)/ln(1+nearViewGrowth)⌉ |
| **EarlyDiverse** | qualified; `offset − track_start ≤ earlyWindowMs`; separated from and not near-duplicate of Representative and NearView holders **at evaluation time** | `selection_score > holder.selection_score + replaceEpsilon` and admissible | keeps earlier | frozen once `offset − track_start > earlyWindowMs` | ≤ 1/replaceEpsilon |
| **LateDiverse** | qualified; `offset − holder.offset ≥ lateRefreshIntervalMs` (or no holder); separated from and not near-duplicate of every other holder at evaluation time | replace when eligible and admissible (trailing view, not best view) | n/a | whole Track | ≤ trackDuration / lateRefreshIntervalMs |

Notes that make the table exact:

- Representative first: if a frame wins Representative, the other roles are evaluated against the **new** Representative holder in that frame, so a frame cannot become both Representative and NearView.
- An unadmissible would-be replacement leaves the holder unchanged and is counted (`unadmissible_by_role`).
- When a Representative replacement makes an existing supplemental holder a near-duplicate of the new Representative, the supplemental is **not** dropped immediately; duplicates are resolved once, at `resolve()`.
- No candidate ever qualifies → Representative empty at retirement → **the attempt fails** (`evidence_representative_missing` → `pipeline_processing_failed`). The profile loader rejects `confidenceFloor > tracker.trackActivationThreshold`, so the confidence floor alone can never disqualify every frame of a confirmed Track.

**Why the online Representative rule equals "best admissible candidate seen so far" (C1).** Let A be the set of qualified candidates seen so far whose encoding is admissible, ordered by `(selection_score, −offset)` with the ε rule. Invariant: after each frame, `holder = ε-max(A)` (the earliest candidate among those within ε of the top score). Induction: initially A = ∅ and holder = none. On a new candidate c: (i) if c is not qualified, A and holder are unchanged. (ii) If c is qualified but does not beat the holder by more than ε, c may or may not be admissible — either way it cannot be the ε-max, so A' = A ∪ {c} (or A) has the same ε-max; holder unchanged is correct. (iii) If c beats the holder by more than ε, c is encoded: if admissible, A' = A ∪ {c} and c is its ε-max → holder := c; if unadmissible, c ∉ A' = A → holder unchanged is correct. Encoding only happens in case (iii), and an earlier admissible lower-scoring candidate that was displaced is never needed again: it can only be the ε-max of A' if c is unadmissible, and in that case it was never displaced. The K-candidate reservoir therefore adds no reachable outcome. Adversarial encoder measurement E6 is retained because admissibility at the floor is a measured property, not a proof; the online rule needs no proof of admissibility, only the encoder's answer.

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
  "selectorVersion": "evidence-selector-v1",
  "scorerVersion": "quality-v1",
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
| Temporary disk bound? | Σ over live Tracks of 24 B × points spilled ≈ 24 × 30 × 86,400 = 62 MB per 24 h live Track; deleted at that Track's retirement (`remove`). It never coexists with the canonical artefact for the same Track beyond the finalisation window. |
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
| Authority predicate (per job directory, one DB read `SELECT status, attempt_count, completed_at_utc, updated… FROM vision_jobs WHERE id = @jobId`) | **Completed / Failed / Cancelled:** every attempt directory is deletable once `now ≥ terminalAtUtc + Grace`. **Leased:** `attempt-k` with `k < AttemptCount` is deletable immediately (fenced by the lease); `k ≥ AttemptCount` is never touched. **Queued with AttemptCount ≥ 1** (requeued after failure): `attempt-k` with `k ≤ AttemptCount` is deletable (the next lease is `AttemptCount+1`); `k > AttemptCount` is never touched. **Queued with AttemptCount = 0:** nothing (no attempt has run; any directory is unexpected → 1401). **No row:** deletable only when the directory's last-write time is older than `UnknownJobGrace` (default 24 h) — covers a job row purged by another lifecycle; logged at Warning. |
| Grace | `Grace` default 5 minutes after the terminal transition: long enough for the worker's own fast-path `cleanup()` to run first (avoids deleting under a process that is itself deleting; both are idempotent and tolerate ENOENT), short enough to bound retention. |
| Schedule | On host start (after DB readiness) and every `IntervalMinutes` (default 15). One instance per host; `SemaphoreSlim(1)` prevents overlap. Per cycle it enumerates at most `MaxDirectoriesPerCycle` (default 1,000) job directories, oldest first, so a backlog is drained across cycles without a long stall. |
| Deletion | Handle-relative and link-safe: open the job directory and attempt directory with `FileOptions`-based handles that fail on reparse points (`FileAttributes.ReparsePoint` check after open; on Windows `FILE_FLAG_OPEN_REPARSE_POINT` semantics via `FileSystemEnumerable` with `AttributesToSkip = 0` and explicit refusal); recurse only into real directories; delete leaf files then directories bottom-up; a symlink/junction *entry* is deleted as an entry, never followed. Mirrors the worker's POSIX `rmtree(dir_fd=)` / Windows `_remove_attempt_tree_no_reparse` discipline. A directory whose root is itself a link is refused (EventId 1402 `staging_janitor_path_escape`, Error) and left in place. |
| Idempotency | Every run recomputes from filesystem + DB; a directory removed by the worker meanwhile is a no-op. |
| Observability | EventIds 1400 (cycle summary: scanned, deleted dirs, freed bytes, skipped, failures), 1401, 1402, 1403 (deletion failed, with path and exception; Warning), 1404 (same directory failed ≥ 3 consecutive cycles; Error). Counters exposed through the existing health endpoint's details (`stagingJanitor.lastRunUtc`, `lastFailureCount`, `consecutiveFailures`). |
| Repeated failure | Never crashes the host; the directory stays; retried every cycle; 1404 escalates. A failing janitor never blocks completion, leasing or serving. |
| Interaction with S1.1 worker cleanup | Both remain: the worker's `cleanup()` (own attempt, after success — fast path, §6.3 of S1.1 unchanged for failure) and `cleanup_superseded_attempts()` (at lease) reduce retention to seconds in the normal case; the janitor guarantees the bound when the worker dies or never runs again. |
| Worst-case retention window (platform up) | `Grace + IntervalMinutes` ≈ **20 minutes** after the terminal transition for a completed/failed job with a dead worker; **≤ 1 cycle** for superseded attempts of a leased job. If the platform is down, no completions happen either, so no new staging becomes reclaimable; the backlog drains at `MaxDirectoriesPerCycle` per cycle on restart. |
| Bounded retained staging (platform up) | ≤ (jobs reaching a terminal state within 20 min) × (per-attempt staging, §9.4) + live attempts' staging. With one worker completing at most a few jobs per 20 min, this is a handful of attempts, each ≤ 1 GiB crops + trajectories after the worker's own admission removals (or ≤ 5.19 GiB + trajectories if the worker died before removals). |

**Ownership consequence.** Reclaiming worker staging becomes a **platform responsibility with database authority**, not a worker courtesy. This is a genuine new architectural responsibility (Task-13 §9.3 left it as "a later garbage collector"); it does not alter ADR-006's evidence-root ownership or sealing semantics. §17 C3 flags the ADR-006 amendment for ratification.

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

`MaximumCompletionRequestBodyBytes` → **48 MiB**, subject to `WorkerContractV3Tests.WorstShapeBodyFitsUnderLimit` (10,000 × 4 observations through the real DTOs; assert `bytes ≤ limit − 8 MiB`; parent estimate ≈ 22–23 MiB). If measured > 32 MiB, stop (parent stop condition 3). The Kestrel global limit (3 GiB + 1 MiB) already exceeds it; the completion middleware remains the effective bound.

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
| Spool (live Tracks) | Σ_live 24·D_spilled ≈ 62 MB per 24 h live Track; ≤ 24 × total detections of live Tracks | removed at each Track's retirement (`remove`) |
| Evidence crops before admission | ≤ T × 557,056 = **5.19 GiB** at T = 10,000 (all four roles admissible) | removed to ≤ 1 GiB by `remove_omitted` before completion |
| Trajectories | Σ_T canonical size (≈ 24 B/point → ≤ 512 MiB quota) | until reclamation |
| **After completion** | 0 within seconds (worker fast path) or **≤ 20 min** (janitor) | §6.5 |
| **On failure** | 0 (`cleanup()`), or janitor ≤ 20 min after `Failed` if the worker died | |
| **On lease loss** | removed at the next lease (S1.1) or by the janitor within one cycle of the job's next transition | |

### 9.5 Completion request

≤ 48 MiB by middleware; measured worst shape ≈ 22–23 MiB; realistic ≈ 9.6 MiB.

### 9.6 Accepted evidence per ProcessingRun

≤ 1 GiB crops + ≤ 512 MiB trajectories; the store re-sums admitted crop bytes and refuses > quota.

---

## 10. Persistence model and platform services (S1.2a)

### 10.1 Domain

`ObservationType → {Representative, NearView, EarlyDiverse, LateDiverse}`; `Observation` gains `EvidenceRank` (0..3) and `SelectionScore` ([0,1]); `AttachThumbnailArtifact` → `AttachEvidenceArtifact` (column unchanged); `ArtifactType` gains `EvidenceCrop`; domain rule `ObservationType == Representative ⇔ EvidenceRank == 0`.

### 10.2 Migration `2026MMDDHHMMSS_AddTrackEvidenceSet`

Up: add `evidence_rank integer NOT NULL DEFAULT 0`, `selection_score double precision NOT NULL DEFAULT 0`; `UPDATE observations SET selection_score = quality_score`; guard `RAISE EXCEPTION 'observations_legacy_type_present'` if any `observation_type NOT IN ('Representative')`; drop the defaults; constraints `ck_observations_type`, `ck_observations_rank (0..3)`, `ck_observations_role_rank ((observation_type='Representative') = (evidence_rank=0))`, `ck_observations_selection_score`; unique `(track_id, evidence_rank)`, `(track_id, observation_type)`, `(track_id, source_frame_number)`; FK `thumbnail_artifact_id` `SetNull → Restrict`. Down: reverse; never touches evidence bytes.

Backward readability: the preceding v2-only binary maps only known columns; new NOT NULL columns are populated for every row; migration-before-binary is safe; binary rollback before any v3 row is safe; rollback after v3 rows exist is unsupported (runbook).

### 10.3 Store

Per Track (ordinal): seal trajectory; seal each observation crop in rank order (`evidence/{job}/attempt-NNNN/crops/{trackId}-{role}-{sha}.jpg` for v3; `…/thumbnails/{trackId}-{sha}.jpg` for v2); rows; attach; save; `RepresentativeObservationId` (rank 0); visibility sequence; `job.Complete(digest)`; `run.MarkCompleted`; commit; compensation in reverse on failure. Replay unchanged.

### 10.4 Content serving

`EvidenceCrop + AcceptedEvidence + image/jpeg` in the allow-list; catalog rule as for Thumbnail.

### 10.5 Staging janitor

As specified in §6.5. Registration: `services.AddHostedService<StagingJanitorHostedService>()` behind `StagingJanitorOptions { Enabled = true, IntervalMinutes = 15, GraceMinutes = 5, UnknownJobGraceHours = 24, MaxDirectoriesPerCycle = 1000 }`; `IStagingJanitor` (Infrastructure) does one cycle given a `TimeProvider`, so scheduling and deletion are tested separately, following the `SceneAnalyticsHostedService` / `ISceneAnalysisLifecycle` split.

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
| worker dies right after successful `complete()` | job Completed; staging reclaimed by the janitor within `Grace + Interval` | EventId 1400 |
| worker dies mid-attempt (lease expires) | next attempt removes lower attempts (S1.1); if the job exhausts attempts → `Failed` → janitor | |
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
| Staging lifecycle tests | J1–J11 (.NET, Postgres fixture + temp roots) | W5 (worker fast path) | P4 | |

### 13.2 Qualification truth

Profile SHA changes in S1.2c → qualification record re-derived, `pending`; Task 10 green recorded as "CPU matrices green on head X" only. B1/B3/B4 → "implemented, evidence pending S1.4"; B2 → "in-loop encoding and bounded trajectory spool implemented; RSS evidence pending S1.4"; B6 OPEN until S1.4.

### 13.3 Offline / dependency policy

**No** new Python package, .NET package, native library, codec, model, database extension, runtime-pack, model-pack or installer change. Pillow 11.3.0, numpy, msgpack are locked; `array`, `struct`, `tracemalloc` are stdlib; the janitor uses `System.IO` only. Overlay-only per ADR-007. `config/dependencies/offline-dependency-policy-v1.json` untouched.

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
| J1 `completed_job_attempt_removed_after_grace_not_before` | missing grace / never reclaiming |
| J2 `simulated_worker_death_after_completion_is_reclaimed` — complete via the real endpoint with staged files left in place; advance `TimeProvider`; one cycle → directory gone; accepted evidence bytes intact and servable | crash leak; deleting the wrong root |
| J3 `leased_job_current_and_later_attempts_never_removed_lower_attempts_removed_immediately` | fencing violation |
| J4 `queued_requeued_job_removes_attempts_up_to_attempt_count_only` | off-by-one on requeue |
| J5 `other_job_directories_untouched_when_one_is_reclaimed`; `non_canonical_names_untouched_and_logged` | over-broad deletion |
| J6 `cycle_is_idempotent_and_tolerates_concurrent_worker_cleanup` (directory removed between enumeration and delete) | ENOENT crash |
| J7 `symlinked_attempt_directory_is_refused_and_target_preserved` (POSIX) | link following |
| J8 `junction_attempt_directory_is_refused_and_target_preserved`; `nested_junction_inside_attempt_deleted_as_entry` (Windows; `task14-read-security.yml`) | reparse following |
| J9 `deletion_failure_is_logged_retried_and_escalates_after_three_cycles`; host keeps serving | silent failure / host crash |
| J10 `unknown_job_directory_removed_only_after_unknown_grace`; `queued_zero_attempt_directory_logged_not_removed` | premature deletion |
| J11 `janitor_never_enumerates_outside_staging_prefix_or_evidence_root` (sentinel files) | scope escape |

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
| Docs | this plan; parent §16; `docs/runbooks/vision-runtime-model-component-lifecycle.md` (new "Completion contract v3 deployment order" and "Staging reclamation" sections); `contracts/README.md`; ADR-006 amendment **only if ratified** (§17 C3) |

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
5. **Staging janitor** (`IStagingJanitor`, safety helpers, hosted service, options, health details) + J1–J11 + Task-14 workflow filter.
6. Contract fixtures + `verify_repo` + canonicalisation tests (pins the golden digest).
7. Docs (parent §16, runbook, README).

Exit: Quality Gate + Task 17 + Task 14 green on the exact head; a `main` v2 worker completes against the S1.2a platform in the composition test; J2 proves crash-after-completion reclamation.

### S1.2b (one PR, ~4 commits; independent of S1.2a)
1. `iter_trajectory_v1` + T1/T2 (pure).
2. Store `append_bytes` / `write_stream` / `remove` on both backends + staging-security tests.
3. `TrajectorySpool`, `_TrackState`, `prepare_track`/publisher changes + T3–T9.
4. Runner fast-path cleanup + W5; Task 10 filter widening; docs.

Exit: Quality Gate, Task 17, Task 10 (both OS), Staging Security green on the exact head; T1/T9 prove byte identity; T3 proves the bound.

### S1.2c (one PR, ~7 commits; requires S1.2a **deployed** and S1.2b merged)
As revision 1's S1.2b sequence (profile → roles/quality/encoder → selector → admission → pipeline integration → wire/client/runner → measurement note/docs/register).

Exit: all gates green on the exact head; the worker's own emitted golden example matches the S1.2a pinned digest.

Each boundary leaves `main` buildable, testable, deployable and contract-compatible with the previous one: S1.2a changes no worker; S1.2b changes no byte any consumer sees; S1.2c is the only wire change and is guarded by the capability check.

---

## 17. Corrections to the parent plan and ADR flags

| ID | Finding | Correction | Ratification |
|---|---|---|---|
| **C1** | S1-14 introduced a K-candidate Representative fallback reservoir. | Online "best admissible" holder rule; equivalence proof in §4.2; E6 measurement retained. | **Owner — recommended for ratification** (replaces an owner correction) |
| **C2** | Parent §12.2/§12.6 require a Python-computed digest. | Digest stays server-side; cross-language agreement pinned on the body (§7.5). | Plan-level |
| **C3 (revised)** | Neither the parent plan nor ADR-013 §5 accounts for the staging of a *successfully completed* attempt; revision 1 proposed a best-effort worker cleanup, which is not crash-safe. | Platform-owned **staging janitor** with database authority (§6.5, §10.5), worst-case retention ≈ 20 min; worker cleanup demoted to fast path. This **moves ownership** of staging reclamation from "worker courtesy / later GC" to the platform. ADR-006 needs an **amendment** (new decision "6. Platform-owned reclamation of worker staging": the platform reclaims `staging/{job}/attempt-*` using the VisionJob row as sole authority; worker cleanup is an optimisation; retention window stated). ADR-013 §5's sentence "cleaned by the existing attempt cleanup" should read "reclaimed by the platform staging janitor (ADR-006 §6), with worker attempt cleanup as a fast path". Neither ADR is edited in this PR. | **Owner — ADR-006 amendment + ADR-013 §5 wording** |
| **C4 (revised)** | Parent: "≤ 4 × 160 KiB plus its trajectory-in-progress" left the trajectory term unbounded; revision 1 quantified it as 12·D and wrongly called that "independent of video length". | Trajectory spool (§6.3): live memory per Track is a constant ≈ 642 KiB; the trajectory lives in attempt staging until retirement. Parent §6.4's "trajectory-in-progress" as *live processing memory* becomes "one trajectory chunk". | Plan-level (ADR-013 §5 already says live memory is bounded by live Tracks; this makes it true) |
| **C5** | v3 worker vs old platform burned an attempt. | Capability endpoint (§11.1). | Plan-level |
| **C6** | Resolve precedence unspecified for NearView/Late. | Uniform resolve rule (§4.3). | Plan-level |
| **C7** | `SelectionScore` vs `QualityScore` duplication. | Kept, rationale §7.2. | — |
| **C8 (new)** | Parent §16 has two S1.2 PRs; the spool has no wire dependency and the S1.2c evidence work builds on it. | Three PRs: S1.2a, S1.2b (spool), S1.2c (Evidence Set + v3). | Plan-level (parent §16 pointer updated) |
| **C9 (new)** | `TrajectoryDecoder.MaximumSamples = 1_000_000` means a Track > ≈ 9.3 h at 30 fps is `trajectory_invalid` for Scene Analytics today; the spool makes such Tracks producible without exhausting memory. | Recorded as an S1.4 / Scene Analytics hardening item (§20); not changed in S1.2. | Plan-level |

---

## 18. Acceptance criteria

**S1.2a done when:** migration applied and tested; platform accepts v2 and v3 with distinct digests; v3 persists ≤ 4 observations with role/rank/score and `EvidenceCrop` artefacts; content serving covers `EvidenceCrop`; `GET /api/vision/contract` advertises both; golden v3 fixture and digest pinned; worst-shape body ≤ 48 MiB − 8 MiB; **staging janitor reclaims completed/failed/superseded attempts under J1–J11, including the crash-after-completion case, on POSIX and Windows**; Quality Gate + Task 17 + Task 14 green on head; a `main` v2 worker completes against it.

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
| Selector defaults poorly tuned | measurement note before S1.2c merges; `confidenceFloor ≤ activation` enforced | profile revision after S1.4 evidence |
| Floor-size JPEG of pathological content > 64 KiB | E6 per variant; online best-admissible rule; attempt fails only with zero admissible frames | accepted per ADR |
| CPU: sharpness + ≤ 15 encodes per replacement | ε/hysteresis/window bounds; S1.4 measures | cheaper sharpness in a scorer v2 |
| Pathological live-Track count (L ≈ 3,000 → ≈ 1.9 GiB live) | bound stated; constant in video length; S1.4 measures | Development hosts |
| Spool I/O on slow disks (one 96 KiB append per Track per ≈ 2.3 min at 30 fps) | no fsync; open-append-close; S1.4 measures | negligible expected |
| Janitor and worker both deleting the same directory | both idempotent; ENOENT tolerated; grace ordering | none |
| Janitor misconfigured `RootPath` | it only ever enumerates `{RootPath}/staging`; `StorageRootSafety` validates the root at start; J11 | none |
| Platform down for a long period | no completions occur; backlog drains at 1,000 dirs/cycle on restart | bounded by cycle count |
| Tracks > 1,000,000 samples (C9) | recorded; producible now | Scene Analytics `trajectory_invalid` for such Tracks (pre-existing) |
| Sealing time under the row lock with ≤ 5 objects/Track | unchanged authority semantics; S1.4 measures | |
| Cross-OS detector/tracker parity not asserted | out of scope; stated | |
| Stale N−1 writer racing attempt N cleanup (S1.1) | unchanged | retryable failure |
| v2 retirement timing | explicit conditions §11.2 | separate decision |
