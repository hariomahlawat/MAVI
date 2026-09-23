# MAVI Stage 2 — S1.2 Track Evidence Set: implementation plan

**Status:** Implementation-ready plan; awaiting independent review. No S1.2 code exists yet.  
**Date:** 2026-09-23  
**Baseline:** `main@4b6141f52d6d6a0a72de664e60b8cd4441487799` (PR #75, S1.1 merged)  
**Parent plan:** `docs/superpowers/plans/2026-09-23-stage2-s1-track-evidence-set.md` §7–§8, §10.2, §12–§16  
**Governing architecture:** ADR-005, ADR-006, ADR-007, ADR-009, ADR-013 (§3–§7, §19), Stage-2 acceptance register rows B1, B3, B4 (B2 partially closed by S1.1; B5 is S1.3; B6 is S1.4)  
**Non-goals:** everything the parent plan §3 excludes, plus the Track-detail read contract and Evidence Set viewer (S1.3) and qualification claims (S1.4)

This plan converts the parent S1 architecture into two independently mergeable PRs:

- **S1.2a — platform first:** the platform accepts completion **v2 and v3**, persists the Evidence Set, seals `EvidenceCrop` artefacts and advertises which completion versions it accepts. The worker on `main` still emits v2; nothing changes operationally.
- **S1.2b — worker second:** the worker selects, encodes and admits the bounded Evidence Set in the decode loop and emits v3. It refuses to start against a platform that does not advertise v3.

Every statement below was checked against the code at the baseline. Where this plan corrects the parent plan, the correction is listed in §17 and nothing is silently changed.

---

## 1. Purpose

S1.1 gave the pipeline exact-once Track retirement and whole-Track finalisation, but the Representative is still one raw RGB crop per live Track, encoded at JPEG q90 with no resize or size cap, and the wire is still v2 (one thumbnail per Track). S1.2 delivers:

1. a deterministic, bounded, model-neutral **Track Evidence Set** (Representative + NearView + EarlyDiverse + LateDiverse) selected in the single decode pass;
2. **in-loop encoding** so live memory holds bounded JPEG bytes, never raw crops;
3. **completion schema v3 / digest v3** carrying observation descriptors, with the platform validating, sealing and persisting them transactionally;
4. a **safe rollout**: platform bilingual before any worker speaks v3, and a v3 worker that can never emit v3 at a platform that does not accept it.

---

## 2. Current state (verified at `4b6141f`)

### Worker (`src/vision/mavi_vision`)

| Fact | Where |
|---|---|
| `Tracker.update()` returns `TrackerUpdate(candidates, retired_track_ids)`; `VideoProcessor` finalises each Track once at retirement or EOS through `_finalise_track` | `pipeline/process_video.py` L139–230 |
| `_TrackAccumulator` holds `trajectory: list[TrajectoryPoint]` and `representative: _RepresentativeCandidate(observation, crop: np.ndarray)` — one raw RGB crop per live Track | `process_video.py` L46–57 |
| `_accumulate` does **not** receive the frame's `detections`; the occlusion proxy has no input today | `process_video.py` L155, L246 |
| Representative replacement is any strict improvement on `(quality, confidence, -offset, -frame)` — unbounded re-selection | `process_video.py` L325–345 |
| `representative_quality = clamp(0.45·sharpness + 0.35·area/0.20 + 0.20·edgeMargin/0.10)`; sharpness = mean absolute gradient of the grey crop / 64 | `quality/scoring.py` |
| The only JPEG encoder: Pillow, `quality=90, optimize=False, progressive=False, subsampling=2`, no resize, no cap | `pipeline/finalization.py` L106–120 |
| `ProcessedTrack` is descriptor-only (S1.1); `RepresentativeObservation` carries `quality_score` | `common/analytical.py` |
| Staging keys `thumbnails/{trackId}.jpg`, `trajectories/{trackId}.msgpack`; `write_bytes` computes size and SHA-256; **no single-object delete** exists | `storage/artifact_store.py`, `artifact_publisher.py` |
| **Staging of a successfully completed attempt is never removed** — neither by the worker after `complete()` nor by the platform | `worker/runner.py` L330–370; `ProcessingResultStore.cs` |
| Pipeline profile schema is `Literal["1.0"]`, `extra="forbid"`; its SHA-256 over exact bytes enters provenance and the completion digest; `models/qualifications/rtmdet-m-coco-phase1-v1.json.pipelineProfileSha256` must match (`verify_repo`) | `runtime/profile.py`, `runtime/qualification.py` L986–1030 |
| Wire models: every message `schema_version: Literal["2.0"]`; `VisionJobComplete` sums thumbnail+trajectory bytes against 512 MiB; **the worker computes no digest** | `common/control_plane.py`, `worker/client.py` |
| Trajectory v1 msgpack `{v:1, points:[[offsetMs, cx, cy]…]}` is consumed by Scene Analytics and the web decoder and must not change | `video/trajectory.py`; STA plan L17, L542 |

### Platform (`src/platform`)

| Fact | Where |
|---|---|
| `WorkerContractRules.SchemaVersion="2.0"`, 10,000 Tracks, 32 MiB body, 64 MiB/artefact, 512 MiB aggregate | `Mavi.Contracts/Worker/WorkerContractRules.cs` |
| All four handlers compare `SchemaVersion` for equality; `VersionProblem()` says "2.0 is required"; `ProcessingResultStore` L52 re-checks equality under the row lock | `VisionJobEndpoints.cs` L24/33/53/69/106 |
| Validator requires exact staging keys, checks representative/thumbnail/trajectory, sorts Tracks ordinally, computes the digest with domain tag `mavi:vision-completion-digest:v2` — **digest is .NET-only** | `VisionResultValidator.cs` L130–140, L175, L218–354 |
| Store seals thumbnail then trajectory per Track (`evidence/{job}/attempt-NNNN/{thumbnails|trajectories}/{trackId}-{sha}.{ext}`), writes `Artifact(Thumbnail|TrackTrajectory)`, `Track`, one `Observation(Representative)`, attaches `RepresentativeObservationId` after the first save, compensates newly sealed keys on failure; replay re-validates and compares digests, never re-seals | `ProcessingResultStore.cs` L143–361 |
| `Observation` has `ObservationType` (string column, **no CHECK**), frame/offset/bbox(float)/confidence/quality, `ThumbnailArtifactId` FK **SetNull**; enum `{TrackStart, Representative, BestQuality, TrackEnd}`, only Representative ever written | `Observation.cs`, `ObservationConfiguration.cs` |
| `ArtifactType {SourceVideo, Thumbnail, TrackTrajectory}`; content serving allow-lists `Thumbnail+image/jpeg` and `TrackTrajectory+application/msgpack`; a Thumbnail is servable if any Observation references it and the run is Completed | `ContentReadService.cs` L107–135, `ContentCatalog.cs` L56–93 |
| Migrations are hand-written `yyyyMMddHHmmss_VerbNoun.cs` + snapshot; integration tests need `MAVI_TEST_DB_CONNECTION` (Quality Gate provides pgvector/pg18) | `Persistence/Migrations/`, `tests/Mavi.IntegrationTests/PostgresFixture.cs` |
| Contract fixtures: `contracts/schemas/vision-job-complete-v2.schema.json`, example, conformance vectors; `verify_repo.check_contracts` hard-codes the v2 stems | `contracts/`, `tools/verify_repo.py` L828–853 |

---

## 3. Architecture

### 3.1 Component map (worker)

```
DecodedFrame + detections ──► Detector ──► Tracker.update ──► TrackerUpdate
                                                                 │ candidates
                                                                 ▼
                      ┌──────────────── VideoProcessor (orchestration only) ────────────────┐
                      │  per candidate:                                                     │
                      │    TrackState.record(frame, candidate)      (scalars + trajectory)   │
                      │    EvidenceSelector.observe(FrameContext, candidate, TrackState)      │
                      │        ├─ QualityScorer.score(...) -> CandidateQuality               │
                      │        └─ EvidenceEncoder.encode(crop, role) -> EncodedEvidence|None │
                      │  per retired id / at EOS:                                             │
                      │    EvidenceSelector.resolve(track) -> tuple[SelectedEvidence]         │
                      │    prepare_track(...) -> PreparedTrack (payloads)                     │
                      │    ArtifactPublisher.publish_track -> ProcessedTrack (descriptors)    │
                      │  after loop:                                                          │
                      │    EvidenceAdmission.admit(finalised) -> admitted set + omitted keys   │
                      │    ArtifactPublisher.remove_omitted(keys)                             │
                      └────────────────────────────────────────────────────────────────────┘
```

New modules (all under `src/vision/mavi_vision/`):

| Module | Responsibility | Interface (owner) |
|---|---|---|
| `evidence/roles.py` | `EvidenceRole` enum, canonical order, wire tokens, key tokens, per-role caps | `EvidenceRole(StrEnum)`: `REPRESENTATIVE="representative"`, `NEAR_VIEW="near-view"`, `EARLY_DIVERSE="early-diverse"`, `LATE_DIVERSE="late-diverse"`; `ROLE_ORDER`; `role_cap_bytes(role)` |
| `evidence/quality.py` | replaceable scorer | `class QualityScorer(Protocol): def score(self, ctx: FrameContext, bbox) -> CandidateQuality`; `QualityV1Scorer` wraps today's formula + occlusion proxy; `CandidateQuality(sharpness, area, edge_margin, occlusion_iou, quality_score, selection_score)` |
| `evidence/encoder.py` | crop → bounded JPEG via fixed ladder | `class EvidenceEncoder: def encode(self, crop: np.ndarray, cap_bytes: int) -> EncodedImage | None`; `EncodedImage(data: bytes, width: int, height: int, quality: int, ladder_step: int)` |
| `evidence/selector.py` | per-Track role state machine; holds ≤ 4 `EncodedImage` per live Track | `class EvidenceSelector: def observe(ctx, candidate, track_start_ms) -> None; def resolve() -> tuple[SelectedEvidence, ...]`; one instance per live Track, created by `EvidenceSelectorFactory(profile.evidence, scorer, encoder)` |
| `evidence/admission.py` | run-level quota admission, pure function | `admit(tracks: Sequence[ProcessedTrack], quota_bytes: int) -> AdmissionResult(admitted: frozenset[(track_id, role)], omitted_keys: tuple[str, ...], accounting: EvidenceAccounting)` |
| `evidence/__init__.py` | re-exports only | — |

`quality/scoring.py` keeps `representative_quality`/`_normalized_sharpness` (used by `QualityV1Scorer`); nothing else imports it directly after S1.2b.

Everything in `evidence/` depends only on `common/analytical.py`, `video/reader.py` (`DecodedFrame`), `detection/interfaces.py` (`DetectionCandidate`) and the profile section. It does not import the tracker, the store or the worker.

### 3.2 Replaceability

| Component | Replaced by | Identity change |
|---|---|---|
| Tracker | any `Tracker` returning `TrackerUpdate` (S1.1) | profile `tracker` section |
| Quality scorer | a new `QualityScorer` implementation selected by `evidence.scorerVersion` | profile SHA → provenance/digest; new ProcessingRun (ADR-013 §3) |
| Evidence selector policy | new `evidence.selectorVersion` (role rules are frozen by ADR-013 §4; only numeric parameters and scorer may change without an ADR) | profile SHA |
| Image encoder | another `EvidenceEncoder` (e.g. different codec) requires a new media type in the wire enum and the platform allow-list → contract change, not a profile change | schema version |
| Embedding/ReID | out of scope; a future signal enters `CandidateQuality` through a new scorer version, never through the selector | profile SHA |
| Persistence/indexing | `Observation` rows are role-typed; the read side (S1.3) projects them | — |

### 3.3 Platform components

- **Contracts:** v3 request records beside v2; `WorkerContractRules.CompletionSchemaVersions = {"2.0","3.0"}`; new constants for evidence quotas.
- **Validator:** one entry point `Validate(routeJobId, request, videoDurationMs)` that dispatches on `SchemaVersion`; v2 normalises to the same `ValidatedVisionResult` (one Representative observation, `SelectionScore = QualityScore`, artefact category `thumbnails`); v3 validates observations. Digest domain tag per version.
- **Store:** seals every observation artefact + trajectory per Track; writes `Observation` rows with role/rank/score; `Artifact(EvidenceCrop)` for v3, `Artifact(Thumbnail)` for v2.
- **Capability endpoint:** `GET /api/vision/contract` → `{"schemaVersion":"2.0","completionSchemaVersions":["2.0","3.0"]}` (see §11).
- **Content:** `EvidenceCrop + AcceptedEvidence + image/jpeg` added to the serving allow-list and the catalog rule (an Observation's `ThumbnailArtifactId` referencing an `EvidenceCrop`).

---

## 4. Evidence roles and selection algorithm

Roles, caps and order are frozen by ADR-013 §4–§5. Numeric parameters live in the profile (§5).

### 4.1 Definitions

- **Frame context** `FrameContext(frame: DecodedFrame, detections: tuple[DetectionCandidate, ...])` — the detector output the tracker was given for this frame (both classes, including detections the tracker did not confirm).
- **Qualified candidate** (all must hold): `confidence ≥ confidenceFloor`; `sharpness ≥ sharpnessFloor`; `edgeMargin ≥ edgeMarginFloor`; `occlusionIou < occlusionIouCeiling`, where `occlusionIou = max IoU(candidate.bbox, d.bbox) over d in detections, d is not the candidate's own detection` (identity by `frame_ordinal`; 0.0 if no other detection).
- **Scores** (`CandidateQuality`): `quality_score = representative_quality(frame, bbox)` (formula v1, unchanged); `selection_score = quantize(clamp01(quality_score − occlusionPenaltyWeight·occlusionIou))`; `area = bbox.width·bbox.height`. `quantize(x) = floor(x·10⁶)/10⁶` — six decimals, applied before any comparison and before emission (see §8).
- **Near-duplicate** of a selected frame S: `same source_frame_number`, or `|offset − S.offset| ≤ duplicateWindowMs and IoU(bbox, S.bbox) ≥ duplicateIouThreshold`.
- **Separated** from S: `|offset − S.offset| ≥ minSeparationMs`.
- **Admissible**: the encoder returned bytes ≤ the role's cap (§6). An unadmissible candidate never becomes a role holder; the holder stays.

### 4.2 Per-role rules

Evaluated for every accepted frame in which the Track has a candidate, in the order below. Every rule reads only: the candidate, `FrameContext`, the profile, and the selector's own state (current holders). Each holder is `SelectedEvidence(role, offset_ms, source_frame_number, confidence, bbox, quality, image: EncodedImage)`.

| Role | Eligibility | Replacement rule (strict) | Tie | Window / freeze | Encodes bounded by |
|---|---|---|---|---|---|
| **Representative** (mandatory, rank 0) | qualified | `selection_score > holder.selection_score + replaceEpsilon` | equal or within ε keeps the earlier frame | whole Track; never frozen | ≤ 1/replaceEpsilon (score ∈ [0,1]) |
| **NearView** | qualified; not near-duplicate of the Representative holder | `area > holder.area·(1 + nearViewGrowth)` (first qualified candidate that is not a near-duplicate of Representative seeds it) | equal area keeps earlier | whole Track | ≤ ⌈ln(1/areaMin)/ln(1+nearViewGrowth)⌉ (area ≥ areaMin = 1 px² / frame area) |
| **EarlyDiverse** | qualified; `offset − track_start ≤ earlyWindowMs`; separated from and not near-duplicate of Representative and NearView holders **at evaluation time** | `selection_score > holder.selection_score + replaceEpsilon` | keeps earlier | frozen once `offset − track_start > earlyWindowMs` (no further evaluation) | ≤ 1/replaceEpsilon |
| **LateDiverse** | qualified; `offset − holder.offset ≥ lateRefreshIntervalMs` (or no holder); separated from and not near-duplicate of every other holder at evaluation time | replace unconditionally when eligible (it is a trailing view, not a best view) | n/a (eligibility decides) | whole Track | ≤ trackDuration / lateRefreshIntervalMs |

Notes that make the table exact:

- Representative first: if the same frame wins Representative, NearView/Early/Late are evaluated against the **new** Representative holder in that frame, so a frame cannot become both Representative and NearView.
- A candidate that would replace a supplemental holder but whose encoding is unadmissible leaves the holder unchanged and is counted in telemetry (`unadmissible_by_role`). For Representative the same rule gives the ADR's fallback for free: the holder is always the best **admissible** qualified candidate (§17, correction C1).
- When a Representative replacement makes an existing supplemental holder a near-duplicate of the new Representative, the supplemental holder is **not** dropped immediately (that would lose evidence if the Representative moves again); duplicates are resolved once, at `resolve()`.
- No candidate ever qualifies → Representative empty at retirement → **the attempt fails** (`evidence_representative_missing`, `VideoProcessingError`, `vision_processing_failed`). A Track that ByteTrack confirmed has ≥ `minimumConsecutiveFrames` detections at ≥ `trackActivationThreshold` confidence; with `confidenceFloor ≤ trackActivationThreshold` and `sharpnessFloor`/`edgeMarginFloor` at their measured defaults this is rare but possible (e.g. a fully occluded Track). The profile loader **rejects** `confidenceFloor > tracker.trackActivationThreshold` so the confidence floor alone can never disqualify every frame of a confirmed Track.

### 4.3 Retirement resolution (`resolve()`)

1. Take holders in `ROLE_ORDER`.
2. For each supplemental holder H (NearView, EarlyDiverse, LateDiverse in that order): omit H if it is a near-duplicate of, or not separated from, **any earlier role already kept**. (NearView is exempt from the separation test against Representative — ADR-013 requires it only to be non-duplicate; Early/Late require both.)
3. Ranks are assigned 0..n−1 in role order over the kept roles.
4. Output is `tuple[SelectedEvidence]` sorted by role order; `resolve()` is idempotent and does not mutate state.

Two observations in one Track therefore never share a source frame. **One image never satisfies two roles**; the wire and DB forbid two observations of one Track with the same `sourceFrameNumber`, and there is no byte deduplication because there is nothing to deduplicate (§7.2).

### 4.4 Worked example

Track 0–20 s at 10 fps, all frames qualified, earlyWindowMs 3000, lateRefreshIntervalMs 5000, minSeparationMs 1000, replaceEpsilon 0.02:

- t=0.0 s score .40 area .010 → Representative, NearView seeds? No: NearView requires non-duplicate of Representative and this is the same frame → no NearView yet; EarlyDiverse requires separation from Representative → none; LateDiverse requires separation → none.
- t=1.1 s score .41 area .012 → Rep: .41 ≯ .42 keep; NearView seeds (area .012, separated); Early: .41 > (none) and separated from Rep and NearView? not separated from NearView (same frame) → wait: separation is against *holders at evaluation time*; NearView became a holder in this frame before Early is evaluated → Early not eligible this frame.
- t=2.2 s score .45 → Rep replaced (.45 > .42); NearView: area .012·1.25 = .015 not exceeded, and is the NearView holder (t=1.1) still non-duplicate of the new Rep? Not re-checked until resolve. Early: separated from Rep (t=2.2)? |2.2−2.2| < 1 s → no.
- t=2.9 s score .30 area .020 → Rep keep; NearView replaced (.020 > .015; not a near-duplicate of Rep at 2.2 if IoU < .85 or Δt > .5 s); Early: separated from Rep (0.7 s < 1 s) → no.
- t=3.1 s → early window closed (3.1 > 3.0), Early frozen: **omitted** (never got a holder).
- LateDiverse: first eligible frame separated from Rep (2.2) and NearView (2.9) is t=3.9 s → holder; refreshed at ≥ 8.9, 13.9, 18.9 s → holder t=18.9 s at retirement.
- `resolve()`: Rep(2.2), NearView(2.9): near-duplicate of Rep? Δt .7 > .5 → not duplicate by window; kept. Late(18.9) kept. Ranks 0,1,2. Early omitted.

The example shows two properties the tests pin: Early can legitimately be omitted on short/dense Tracks, and NearView is judged against Representative at resolve time only.

---

## 5. Profile section (numeric policy)

`src/vision/config/pipelines/phase1-detection-tracking-v1.json` gains one section and bumps `schemaVersion` to `"1.1"`; `profileVersion` moves to `"1.2.0-candidate"`. The loader accepts `Literal["1.1"]` only (no dual-schema: the profile is release metadata, not a wire contract).

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
    "maxLongEdgePx": 1024,
    "initialQuality": 85,
    "representativeCapBytes": 65536,
    "supplementalCapBytes": 163840,
    "floorLongEdgePx": 128,
    "floorQuality": 50,
    "ladderScale": 0.8,
    "ladderQualities": [85, 75],
    "floorQualities": [65, 55, 50]
  },
  "runEvidenceCropQuotaBytes": 1073741824
}
```

Loader rules (`_EvidenceProfileSchema`, `extra="forbid"`): every floor/ceiling in [0,1]; `replaceEpsilon` in (0, 0.5]; `nearViewGrowth` in (0, 4]; windows are positive ints ≤ 3,600,000; `confidenceFloor ≤ tracker.trackActivationThreshold`; encoder values fixed to the ADR-013 §5 constants (`maxLongEdgePx == 1024`, caps 65536/163840, floor 128/50) — the loader **rejects** other values, because those are ADR bounds, not tuning knobs; `runEvidenceCropQuotaBytes == 1 GiB` likewise. The tuning knobs are the selector parameters only.

The numbers above are initial engineering defaults. Before S1.2b merges, record a short measurement note (`docs/qualification/2026-xx-xx-evidence-selector-parameter-note.md`) over the C1 scripted corpus and at least two real Development clips: distribution of sharpness/area/edge-margin per confirmed Track, share of frames qualified per floor, roles filled per Track, re-encodes per Track. Adjust defaults from that note in the same PR. These are selector engineering parameters, not model-quality thresholds; changing them later is a profile change (ADR-009 requalification rule).

The profile SHA changes; `models/qualifications/rtmdet-m-coco-phase1-v1.json.pipelineProfileSha256` is re-derived in the same PR and the record stays `pending` (§13). `profileId` is unchanged so the qualification/manifest relationship holds.

---

## 6. Encoder and admission

### 6.1 Crop and ladder (`evidence/encoder.py`)

Input: the source frame (uint8 RGB), the authoritative normalised bbox, the role cap.

1. **Crop** with the existing floor/ceil rule (`_crop_rgb`); empty crop → `EncodeFailure("crop_empty")`.
2. **Downscale** if `max(w, h) > maxLongEdgePx`: `Image.resize((w', h'), Image.LANCZOS)` with `long' = 1024`, the other edge `max(1, round(other · 1024 / long))`. Never upscale.
3. **Encode** JPEG: `quality=q, optimize=False, progressive=False, subsampling=2`, no EXIF/ICC (`Image.fromarray` attaches none). Same flags as today; only quality and size change.
4. **Ladder** (fixed, deterministic; step index recorded):
   - step 0: q85 at current size; step 1: q75 at current size;
   - steps 2..k: `long_edge = max(floorLongEdgePx, floor(long_edge · ladderScale))` at q75, until `long_edge == floorLongEdgePx` (from 1024: 819, 655, 524, 419, 335, 268, 214, 171, 136, 128 → 10 steps);
   - then q65, q55, q50 at the floor size.
   - Stop at the first step whose output ≤ cap. Worst case 15 encodes per candidate.
5. **Floor exceeded** → return `None` (unadmissible). No exception; the caller counts it.

Determinism: within one qualified runtime variant (same Pillow/libjpeg/numpy build per the runtime lock) the bytes are reproducible; golden SHA-256 tests pin fixtures per variant (`tests/fixtures/evidence/*.png` inputs → expected SHA table keyed by `MAVI_RUNTIME_VARIANT`). Across variants only dimensions, byte count ≤ cap and decodability are asserted (§8).

### 6.2 Run-level admission (`evidence/admission.py`)

Input: the finalised `ProcessedTrack`s (descriptor-only, each with ≤ 4 observations) and the quota. Pure function; no I/O.

1. Sum Representative bytes; if > quota → `AdmissionError("representative_quota_exceeded")` (fail closed; impossible under 10,000 × 64 KiB = 625 MiB but kept as an invariant).
2. Rounds: NearView, then EarlyDiverse, then LateDiverse. Within a round, candidates sorted by `(−selection_score, track_id)`; `track_id` ordinal order equals eventual `LocalTrackNumber` order (parent §7.4; pinned by `test_track_id_order_matches_platform_local_track_number`).
3. Admit while `running_total + size ≤ quota`; otherwise omit **and continue** (a smaller later candidate may still fit — deterministic because the order is fixed).
4. Output: admitted set, omitted staging keys, and `EvidenceAccounting` per role: `candidates, admitted, omitted, candidate_bytes, admitted_bytes` (ints).

`VideoProcessor` then: (a) rebuilds each `ProcessedTrack.observations` without omitted roles, **re-ranking** 0..n−1 in role order (ranks are contiguous on the wire; the platform re-checks); (b) calls `publisher.remove_omitted(keys)` (§6.3); (c) attaches `accounting` to `VisionProcessingResult.evidence_accounting`.

### 6.3 Staging removals (new store capability)

`StagingArtifactStore.remove(relative_name)`: validates the relative name like `write_bytes`, then removes exactly that leaf through the hardened backend (POSIX: `unlink` with `dir_fd` on the attempt directory after an `O_NOFOLLOW` stat proving a regular file; Windows: open-by-handle with `FILE_OPEN_REPARSE_POINT`, refuse reparse/directory, `_mark_delete`). Missing leaf is a no-op. Lease-fenced by `ArtifactPublisher.remove_omitted(keys)` (`check_owned()` before each removal).

`StagingArtifactStore.cleanup()` is additionally called by the **runner after a successful `complete()`** (best-effort, logged on failure, never affects the accepted result). Rationale and correction in §17 C3: today a completed attempt's staging is never removed; under v3 it may reach ~5 GiB per job.

---

## 7. Wire contract v3

### 7.1 Message

Only the completion message changes. Lease, heartbeat and fail stay `"2.0"` (parent §7.5). `schemaVersion: "3.0"`. Top-level fields as v2 (`jobId, workerId, leaseToken, attemptCount, framesProcessed, processingDurationMs, provenance, tracks`) plus:

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
  "trackId": "person-000001",
  "objectClass": "person",
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

Rules (Python model and .NET validator both):

- `observations`: 1..4 items, bound enforced **during JSON binding** (new `BoundedVisionObservationListJsonConverter`, mirroring the Track-list converter) and in the Pydantic model (`max_length=4`).
- roles unique; ranks unique and contiguous `0..n−1` in `ROLE_ORDER`; `role == representative ⇔ rank == 0`; exactly one Representative.
- `sourceFrameNumber` unique within a Track (no image serves two roles).
- every observation: `start ≤ offsetMs ≤ end`; `0 ≤ sourceFrameNumber < framesProcessed`; `confidence ≤ maxConfidence`; `qualityScore`, `selectionScore` finite in [0,1] with ≤ 6 decimals accepted as any finite double (the validator does not enforce quantisation; the worker guarantees it);
- `crop.storageKey` must equal exactly `staging/{routeJobId:D}/attempt-{attempt:0000}/evidence/{trackId}-{role}.jpg`, `mediaType == "image/jpeg"`, `0 < sizeBytes ≤ roleCap` (64 KiB Representative, 160 KiB others);
- `trajectoryArtifact` unchanged (key, `application/msgpack`, ≤ 64 MiB);
- aggregates: Σ crop bytes ≤ 1 GiB (`MaximumCompletionEvidenceCropBytes`); Σ trajectory bytes ≤ 512 MiB (`MaximumCompletionEvidenceBytes`, now trajectory/other only); `evidenceAccounting` present with all four roles, non-negative ints, `admitted ≤ candidates`, `admittedBytes ≤ candidateBytes`, and **`admittedBytes` per role equals the sum of that role's crop `sizeBytes` over all Tracks** (a cheap cross-check that catches a worker whose accounting and descriptors disagree);
- `≤ 10,000` Tracks; body ≤ `MaximumCompletionRequestBodyBytes` (re-derived, §7.4).

`qualityScore` and `selectionScore` are both carried: `qualityScore` is the frame-quality formula (versioned `scorerVersion`), `selectionScore` is what admission ordered by. In S1.2 with `occlusionPenaltyWeight = 0` they are equal; they are kept separate so a scorer change does not redefine the persisted frame-quality semantics.

### 7.3 Digest v3

Server-side only (there is no worker digest today; §17 C2). Same incremental SHA-256 encoding as v2 (length-prefixed UTF-8; `AddNumber` invariant shortest round-trip; `AddNullable` markers). Sequence:

1. `"mavi:vision-completion-digest:v3"`, jobId "D", attempt, frames, durationMs;
2. provenance exactly as v2;
3. `evidenceAccounting` in role order: for each role the five ints;
4. Track count; per Track (ordinal order): trackId, `ObjectClass.ToString()`, start, end, detectionCount, mean, max; trajectory key/mediaType/size/sha; observation count; per observation (rank order): role token, rank, offset, frame, confidence, qualityScore, selectionScore, X, Y, W, H, crop key/mediaType/size/sha.

A v2 body keeps the v2 sequence and tag, so stored v2 digests only ever match v2 replays.

### 7.4 Body limit

`MaximumCompletionRequestBodyBytes` becomes **48 MiB**, subject to the mandated measurement: S1.2a adds `WorkerContractV3Tests.WorstShapeBodyFitsUnderLimit` which serialises a 10,000-Track × 4-observation request through the real .NET DTOs (compact camelCase, 64-hex SHAs, realistic key lengths) and asserts `bytes ≤ limit − 8 MiB`. Parent estimate: ≈ 2.3 KB/Track → ≈ 22–23 MiB. If measured > 32 MiB, stop (parent stop condition 3) rather than raise the limit again. The Kestrel global limit (video import size + overhead) already exceeds 48 MiB; the completion middleware remains the effective bound.

### 7.5 Contract artefacts

- `contracts/schemas/vision-job-complete-v3.schema.json` (JSON Schema, `const "3.0"`, `$defs.observation`, `$defs.evidenceAccounting`, role enum, per-role `sizeBytes` maxima via `if/then`);
- `contracts/examples/vision-job-complete-v3.example.json` — the **golden v3 fixture** with a pinned digest (`contracts/test-vectors/vision-job-complete-v3-digest.json`: `{"exampleSha256": "...", "completionDigest": "..."}`), asserted by `.NET VisionResultValidatorCanonicalizationTests` (compute) and by Python `test_contract_schema_canonicalization.py` (schema-validate + SHA of the file so both sides pin the same bytes);
- `contracts/test-vectors/vision-job-complete-v3-conformance.json` (integer/provenance edge cases as v2 plus observation edge cases) and `control-plane-v3-invalid.json`;
- `tools/verify_repo.check_contracts` extended with the v3 stems; `contracts/README.md` states "completion 2.0 and 3.0 accepted; worker emits 3.0 from S1.2b".

---

## 8. Determinism

| Aspect | Guarantee | Mechanism |
|---|---|---|
| Candidate comparison and ties | **semantic, all variants** | strict `>` with ε on quantised scores; equal keeps earlier frame; roles in fixed order; one candidate per Track per frame |
| Score values | **bitwise within a qualified runtime variant**; cross-variant equal except at 10⁻⁶ quantisation boundaries | float64 numpy on the same wheel set; `quantize` to 6 decimals |
| JPEG bytes | **bitwise within a variant** (golden SHA per variant); cross-variant: dimensions, ≤ cap, decodable | fixed Pillow flags and ladder; runtime lock pins Pillow 11.3.0 |
| Resize ladder | **semantic, all variants** (integer step sizes) | integer arithmetic on long edge |
| Role, observation, Track ordering | **semantic, all variants** | `ROLE_ORDER`; ranks contiguous; Tracks sorted by id (worker) and ordinally re-sorted by the validator |
| Digest | **bitwise for a given body** (server-side) | v3 sequence §7.3; golden fixture |
| Persistence ordering | `LocalTrackNumber = index+1` over ordinal Track order; observations inserted in rank order; same `createdAtUtc` per completion | existing store behaviour extended |
| Cross-platform runtime | Windows and Linux CPU variants produce the **same role set, ranks, frames and bboxes** for the same video and profile **provided detector/tracker outputs are identical**; Task 10 does not assert cross-OS detector parity today and S1.2 does not claim it | qualification records per variant |

Not claimed: cross-variant byte identity of crops; cross-variant digest identity; determinism under a different Pillow/numpy build.

---

## 9. Memory, storage and request bounds

Symbols: L = live Tracks at an instant (bounded by the tracker: every live identity was matched within the last `lostTrackBufferSeconds + 1/referenceFrameRate` ≈ 1.03 s, so L ≤ maxDetectionsPerFrame × ⌈1.03·fps⌉; at 100 detections/frame and 30 fps, L ≤ 3,100 pathological, ≤ 100 typical), T = Tracks finalised so far (≤ 10,000), D = detections in one Track.

### 9.1 Live processing memory (per live Track)

| Item | Bytes | Note |
|---|---|---|
| Representative `EncodedImage` | ≤ 65,536 | cap |
| NearView / EarlyDiverse / LateDiverse `EncodedImage` | ≤ 3 × 163,840 = 491,520 | caps |
| Holder metadata (4 × ~200 B) | ≤ 1,024 | dataclasses |
| Trajectory-in-progress | 12 × D | **compact arrays** (`array('q')` offsets int64 8 B + two `array('f')` float32 4 B… = 16 B/point; use int32 ms offsets: 4+4+4 = 12 B/point; offsets ≤ 2³¹−1 ms = 24.8 days, validated) — 30 fps × 1 h Track = 108,000 points = 1.3 MB |
| Scalars | ≤ 200 | |
| **Total** | **≤ 558,280 B + 12·D ≈ 545 KiB + 12·D** | |

Trajectory-in-progress is the one term that grows with **Track** duration (not video length); a 24 h stationary Track costs 31 MB. This is accepted and stated (parent said "plus its trajectory-in-progress" without the figure). Today's `list[TrajectoryPoint]` costs ≈ 80 B/point; S1.2b switches to arrays (§17 C4).

Worst-case live total at L = 100: 54.5 MiB + trajectories; at pathological L = 3,100: 1.65 GiB + trajectories — acceptable for Development hosts and recorded in the S1.4 measurement; the bound is **independent of video length** and of T.

### 9.2 Scratch during one candidate evaluation (transient, not per Track)

| Item | Bytes |
|---|---|
| decoded frame (already resident, owned by the reader) | 3·W·H (4K: 24.9 MB) |
| crop copy | ≤ 3·W·H (usually far smaller) |
| resized image | ≤ 3 × 1024 × 1024 = 3 MiB |
| encoder output buffer | ≤ ~1.5 MB (noise at q85, 1024²) |
| sharpness float64 grey + gradient temporaries | ≤ 8·w·h × 3 (for a 1024² crop: 24 MB; today's formula, unchanged) |

Freed before the next candidate; peak scratch ≈ 50 MB at 4K, constant.

### 9.3 Finalised completion metadata (per finalised Track)

`ProcessedTrack` scalars + ≤ 4 `ObservationDescriptor` (each: 4 ints/floats, bbox, `ArtifactDescriptor` with 512-char-max key ~120 B, sha 64) + trajectory descriptor ≈ **2.3 KB** → 23 MB at T = 10,000. Admission needs no extra copy (it reads the descriptors).

### 9.4 Staging disk (per attempt)

≤ T × (65,536 + 3 × 163,840) = 10,000 × 557,056 = **5.19 GiB** of crops before admission, plus trajectories (12·D serialised ≈ same order as v2). After admission and `remove_omitted`: ≤ 1 GiB crops + trajectories. After successful completion: **0** (runner cleanup, §6.3). On failure: 0 (existing cleanup). On lease loss: removed by the next attempt (S1.1).

### 9.5 Completion request

≤ 48 MiB by middleware; measured worst shape ≈ 22–23 MiB (§7.4). Realistic (quota-limited) ≈ 8.4 MiB + 460 B × ≤ 2,550 admitted supplementals ≈ 9.6 MiB.

### 9.6 Accepted evidence (per ProcessingRun)

≤ 1 GiB crops + ≤ 512 MiB trajectories, enforced by validator and DB `Artifact.SizeBytes` sums in the store before sealing (the store re-sums admitted crop bytes and refuses `> quota` even if the validator were bypassed).

---

## 10. Persistence model (S1.2a)

### 10.1 Domain

- `ObservationType` → `{ Representative, NearView, EarlyDiverse, LateDiverse }` (legacy `TrackStart, BestQuality, TrackEnd` removed from the enum; guard in migration).
- `Observation` gains `EvidenceRank: int` (0..3), `SelectionScore: double` ([0,1]); `Create(...)` takes both; `AttachThumbnailArtifact` renamed `AttachEvidenceArtifact` (property stays `ThumbnailArtifactId`/column `thumbnail_artifact_id` to avoid a column rename; the read side maps it). Domain rule: `ObservationType == Representative ⇔ EvidenceRank == 0`.
- `ArtifactType` gains `EvidenceCrop`.
- `Track.AttachRepresentativeObservation` unchanged; completion transaction requires exactly one rank-0 observation per Track.

### 10.2 Migration `2026MMDDHHMMSS_AddTrackEvidenceSet` (hand-written, with snapshot)

Up:
1. `ALTER TABLE observations ADD evidence_rank integer NOT NULL DEFAULT 0, ADD selection_score double precision NOT NULL DEFAULT 0;`
2. `UPDATE observations SET selection_score = quality_score;` (historical Representatives: rank 0, score = quality)
3. Guard: `DO $$ BEGIN IF EXISTS (SELECT 1 FROM observations WHERE observation_type NOT IN ('Representative')) THEN RAISE EXCEPTION 'observations_legacy_type_present'; END IF; END $$;`
4. `ALTER TABLE observations DROP DEFAULT` on both new columns (defaults were for the backfill only);
5. constraints: `ck_observations_type CHECK (observation_type IN ('Representative','NearView','EarlyDiverse','LateDiverse'))`; `ck_observations_rank CHECK (evidence_rank BETWEEN 0 AND 3)`; `ck_observations_role_rank CHECK ((observation_type = 'Representative') = (evidence_rank = 0))`; `ck_observations_selection_score CHECK (selection_score >= 0 AND selection_score <= 1)`; unique `(track_id, evidence_rank)`; unique `(track_id, observation_type)`; unique `(track_id, source_frame_number)`;
6. FK `observations.thumbnail_artifact_id → artifacts` delete behaviour `SetNull → Restrict`;
7. `ck_artifacts_type` is not added (artifact_type has no CHECK today; keep consistent).

Down: drop the constraints/indexes, restore `SetNull`, drop the two columns. Down never touches evidence bytes.

Backward readability: the preceding platform binary (v2-only) maps only the columns it knows; the new NOT NULL columns have values for every existing row and new rows are written only by the new binary, so **migration-before-binary is safe** and a binary rollback after migration (before any v3 row) is also safe. A binary rollback after v3 rows exist is unsupported (v2 binary would read NearView rows as unknown enum strings) — stated in the runbook.

`MigrationTests`: `TrackEvidenceSetMigrationBackfillsRankAndScore` (seed a Representative row pre-migration, assert rank 0 and score = quality, constraints present, FK Restrict), `TrackEvidenceSetMigrationRefusesLegacyObservationTypes`.

### 10.3 Store (`ProcessingResultStore.CompleteAsync`)

Per validated Track (ordinal order):
1. seal trajectory → `evidence/{job}/attempt-NNNN/trajectories/{trackId}-{sha}.msgpack` (unchanged);
2. for each observation in rank order: seal crop → `evidence/{job}/attempt-NNNN/crops/{trackId}-{role}-{sha}.jpg` (v3) or `…/thumbnails/{trackId}-{sha}.jpg` (v2 normalised);
3. `Artifact(EvidenceCrop | Thumbnail)` rows, `Track`, `Observation` rows with role/rank/scores, attach artefacts; save; attach `RepresentativeObservationId` (rank 0); visibility sequence; `job.Complete(digest)`; `run.MarkCompleted`; commit;
4. compensation of every newly sealed key in reverse order on failure (existing logic; now ≤ 5 objects per Track).

Replay: unchanged logic; the validator dispatches on the replayed body's version and the stored digest can only match the same version.

### 10.4 Content serving

`ContentReadService` allow-list: `EvidenceCrop + AcceptedEvidence + image/jpeg`. `ContentCatalog`: an `EvidenceCrop` artefact is servable if an Observation references it and its Track's run is Completed (same rule as Thumbnail). No new endpoint; `/api/artifacts/{id}/content` serves crops. Track detail still returns the Representative only (S1.3 adds `observations[]`).

---

## 11. Rollout, compatibility and rollback

### 11.1 Capability advertisement (new, S1.2a)

`GET /api/vision/contract` (same authorisation posture as the other worker endpoints under `/api/vision/jobs`, no body) → `200 {"schemaVersion":"2.0","completionSchemaVersions":["2.0","3.0"]}`.

Why: a v3 worker against an old platform would otherwise learn of the mismatch only at `complete`, after processing a whole video, and each such failure burns an attempt. The lease/heartbeat messages cannot carry this (they are frozen `"2.0"` with `extra="forbid"` on the worker; adding a field would break old workers against a new platform). A separate read-only endpoint is additive and harmless to old workers, which never call it.

Worker (S1.2b): at startup, before READY, `GET /api/vision/contract`; if the response is 404, malformed, or lacks `"3.0"`, the worker logs `vision_platform_contract_unsupported`, reports not-ready and exits non-zero. It re-checks on every reconnect. Belt-and-braces: a `400 worker_contract_version_unsupported` at `complete` is still handled as a non-retryable attempt failure (`_best_effort_fail(lease, "vision_worker_contract_unsupported")`) rather than a retry loop.

### 11.2 Deployment sequence

1. **Deploy S1.2a**: run migration (additive; §10.2), then the platform binary. Verify: `GET /api/vision/contract` lists `"3.0"`; existing v2 workers keep completing; `MigrationTests` and `VisionResultCompletionApiTests` green on the deployed head.
2. **Soak**: at least one full v2 job completes and replays idempotently on the S1.2a platform (integration test mirrors this).
3. **Deploy S1.2b**: worker binary + profile `1.1`. Worker checks the contract endpoint, then emits v3.
4. **Later (out of S1.2)**: retire v2 acceptance only after (a) no release profile binds a v2-emitting worker, (b) every `vision_jobs` row with status `Leased` has `attempt` issued to a v3 worker or has expired, (c) an explicit decision records that v2 **replay** is no longer required — which means no Completed job may still be retried by a v2 worker (bounded by the worker's retry/lease lifetime, in practice one lease duration after the last v2 worker stops). Removal is a separate PR that deletes the v2 branch of the validator, the v2 example and the `"2.0"` entry from `completionSchemaVersions`.

The sequence in the task brief is confirmed by the code: the platform is the only side that validates, so it must be bilingual first; the worker is the only emitter, so it moves second; the capability endpoint makes step 3 fail closed instead of failing late.

### 11.3 Rollback

- Rollback S1.2b (worker) → old worker emits v2; platform still accepts; no data issue.
- Rollback S1.2a binary after migration but before any v3 completion → safe (§10.2).
- Rollback S1.2a binary after v3 rows exist → unsupported; rows with NearView/EarlyDiverse/LateDiverse would fail enum mapping in the old binary. Runbook states: roll the worker back first, then leave the platform at S1.2a.
- Migration down → only after no v3 rows exist; it never deletes evidence bytes (ADR-006 §5 direction).

---

## 12. Failure semantics (fail closed, existing lease/attempt semantics preserved)

| Situation | Behaviour | Code |
|---|---|---|
| encode raises (Pillow error, invalid array) | attempt fails (`ProcessingDependencyError`-like `EvidenceEncodeError` mapped to `VideoProcessingError("pipeline_processing_failed")`), staging cleaned | `vision_processing_failed` |
| empty/invalid crop for a candidate | candidate skipped, counted; not a failure (the existing `representative_crop_empty` becomes a skip because the selector already had a holder or will get one) | telemetry `crop_invalid` |
| candidate over cap after ladder exhaustion | unadmissible; holder unchanged; counted | telemetry `unadmissible_by_role` |
| no admissible Representative at retirement/EOS | attempt fails | `evidence_representative_missing` → `vision_processing_failed` |
| malformed Evidence Set at `prepare_track` (rank gap, duplicate role/frame, observation outside Track) | `ValueError` → attempt fails (worker-side invariant, cannot happen with the selector; kept as fail-closed) | `pipeline_processing_failed` |
| trajectory/detection-count mismatch | unchanged S1.1 checks in `prepare_track` | `track_observation_missing` etc. |
| staging write failure | unchanged (`StagingArtifactError` → `pipeline_processing_failed`, cleanup) | |
| lease lost between a replacement encode and staging | nothing is staged for live Tracks until retirement; at retirement every `write_bytes` is `check_owned()`-fenced; `remove_omitted` fenced too; lost lease → `LeaseLostError`, staging untouched (S1.1 semantics) | `lease_lost` |
| Representatives exceed run quota | `AdmissionError` → attempt fails | `evidence_quota_exceeded` |
| v3 rejected by an old platform (400 version) | non-retryable attempt failure; but prevented at startup by the contract check | `vision_worker_contract_unsupported` |
| platform: unknown role, duplicate role/rank/frame, missing rank 0, cap exceeded, key mismatch, accounting mismatch | `vision_result_invalid` (400) | validator codes `observation_*`, `evidence_accounting_invalid` |
| platform: crop missing/hash mismatch at sealing | existing `vision_result_artifact_missing` / `…_integrity_failed`, compensation | |
| stale worker replay (v2 or v3) | same digest → success; different → `vision_job_completion_conflict` | |
| mixed v2/v3 workers during rollout | both accepted; each job's rows follow its own version; no fabrication of supplemental evidence for v2 | |
| post-completion staging cleanup fails | logged; accepted result unaffected; staging left for GC | |

---

## 13. Qualification, CI and offline

### 13.1 Gates per PR

| Gate | S1.2a | S1.2b | Notes |
|---|---|---|---|
| **MAVI Quality Gate** (`quality-gate.yml`): `dotnet build/test` (Postgres service), `verify_repo.py`, Python suite, phase1 tools tests, web tests/typecheck/build | required | required | no path filter; runs on every PR |
| **Task 17 Acceptance** (`task17-acceptance.yml`) | required (touches `src/platform/**`, `contracts/**`, `docs/**`) | required | asserts release truth stays pending |
| **Task 10 Runtime Qualification** (`task10-runtime-qualification.yml`) | not triggered (platform only) | required — **widen path filter** to `src/vision/mavi_vision/**`, `src/vision/tests/**`, `contracts/**` in S1.2b (parent §10.2); both `MAVI_RUN_QUALIFIED_*` suites and the evidence-set golden SHA tests run here per variant | records exact head |
| **Task 10 Staging Security** (`task10-staging-security.yml`) | not triggered | required — `remove()` on POSIX and Windows; add `test_artifact_store_remove*.py` to its command and path filter | |
| **Task 14 read security** | required if `ContentReadService`/`AcceptedEvidenceReader` paths change (allow-list edit) | — | |
| New **v3 golden contract tests** | `.NET`: canonicalisation digest fixture, schema round-trip, worst-shape body; Python: schema validation of the example | Python emitter produces a body that validates against the v3 schema and, replayed through the .NET validator test, yields the pinned digest | |
| **Memory/bound tests** | — | Python unit tests (§14 M1–M4) in the normal suite; no multi-GiB fixture in CI | |
| **Production composition** (`test_production_processor_runtime.py`) | — | updated to assert 4-role staging and post-completion cleanup | in Task 10 |
| Windows/Linux parity | Task 10 both OSes; staging security both OSes | same | crop bytes compared per variant only |

### 13.2 Qualification truth

- The profile SHA changes in S1.2b → `models/qualifications/rtmdet-m-coco-phase1-v1.json.pipelineProfileSha256` is re-derived in the same PR; `overallResult` stays `pending`; no gate flips. Task 10 green on the S1.2b head is recorded as "CPU matrices green on head X", nothing more (parent §10.2 non-claims).
- B1/B3/B4 rows may move to "implemented, evidence pending S1.4" only; B6 stays OPEN until S1.4.

### 13.3 Offline / dependency policy

S1.2 requires **no** new Python package, .NET package, native library, codec, model, database extension, runtime-pack or model-pack change, or installer update. Pillow 11.3.0 (LANCZOS + libjpeg) and numpy are already in every runtime lock; `array` and `tracemalloc` are stdlib; the platform uses no image library (it never decodes crops). Per ADR-007 the selector/encoder/profile are overlay-only changes. `config/dependencies/offline-dependency-policy-v1.json` is untouched.

---

## 14. Test matrix

Each test names the wrong implementation it catches. Files are new unless marked (ext).

### Selector (`tests/test_evidence_selector.py`)

| Test | Catches |
|---|---|
| S1 `representative_replaces_only_beyond_epsilon` — scores .50, .51, .53 → holder frame 3 only after .53 | replacement on any improvement (unbounded re-encode) |
| S2 `equal_scores_keep_earlier_frame` and `within_epsilon_keeps_earlier` | later-frame bias / `>=` |
| S3 `unqualified_frames_never_hold_any_role` (one axis below floor each: confidence, sharpness, edge margin, occlusion) | missing floor |
| S4 `occlusion_proxy_uses_all_detections_of_both_classes` — an unconfirmed vehicle detection overlapping a person disqualifies the frame | proxy computed on confirmed candidates only |
| S5 `near_view_grows_by_hysteresis_only` — areas .010, .012, .0126 → no replacement until > .0125 | replacing on any larger area |
| S6 `near_view_never_seeds_on_representative_frame` | Rep/NearView sharing a frame |
| S7 `early_diverse_frozen_after_window` — a perfect candidate at window+1 ms is ignored | window not enforced |
| S8 `early_diverse_requires_separation_at_evaluation_time` | separation checked only at resolve |
| S9 `late_diverse_refreshes_at_interval_and_is_trailing` — candidates every 500 ms; holder offsets are 0, 5000, 10000…; last holder ≤ retirement | best-score late view instead of trailing; refresh ignoring interval |
| S10 `resolve_omits_duplicates_in_role_order_and_reranks_contiguously` — NearView made duplicate by a later Rep move is dropped, Late keeps rank 1 | ranks with gaps; wrong precedence |
| S11 `resolve_is_idempotent_and_pure` | state mutation in resolve |
| S12 `unadmissible_candidate_leaves_holder` (encoder stub returns None) | holder replaced by unadmissible |
| S13 `no_admissible_representative_is_reported` | silent Track without Representative |
| S14 `golden_selection_on_scripted_corpus` — C1 scripted videos → pinned `(role, frame)` sets | any behaviour drift |
| S15 `selector_holds_at_most_four_encoded_images_and_no_ndarray` (gc scan after every frame) | raw crop retention in the selector |

### Encoder (`tests/test_evidence_encoder.py`)

| Test | Catches |
|---|---|
| E1 `ladder_steps_are_exact` — stub encode-size function, assert the sequence (85,1024),(75,1024),(75,819)…(75,128),(65,128),(55,128),(50,128) | wrong ladder |
| E2 `never_upscales` | resize of small crops |
| E3 `stops_at_first_step_under_cap` | over-reduction |
| E4 `returns_none_past_floor` (stub always oversize) | exception/hang or unbounded loop |
| E5 `golden_sha_per_runtime_variant` (fixture PNGs → SHA table keyed by variant; skipped when the variant is not in the table) | non-deterministic encoding within a variant |
| E6 `adversarial_noise_1024_fits_supplemental_cap_and_128_noise_fits_representative_cap` — random noise seeded; asserts admissibility **as measured**, recorded per variant | floor not actually admissible (S1-14 concern) |
| E7 `extreme_aspect_ratios_and_one_pixel_edges` | crashes at 1-px edges |
| E8 `output_has_no_exif_icc_and_is_baseline_420` | metadata leakage / progressive |

### Admission (`tests/test_evidence_admission.py`)

| Test | Catches |
|---|---|
| A1 `representatives_always_admitted_then_rounds_by_role` | round order |
| A2 `within_round_orders_by_score_desc_then_track_id` | wrong secondary key |
| A3 `tight_quota_omits_and_continues` — a later smaller candidate is admitted after a larger one is omitted | stop-at-first-omit |
| A4 `representatives_over_quota_fail_closed` | silent omission of Representatives |
| A5 `accounting_sums_match_descriptors` | inconsistent accounting |
| A6 `track_id_order_matches_platform_local_track_number` (fixture of mixed ids sorted in Python == ordinal .NET order recorded in a shared vector) | ordering divergence |

### Pipeline (`tests/test_track_lifecycle.py` ext, `tests/test_process_video.py` ext)

| Test | Catches |
|---|---|
| P1 `retirement_stages_full_evidence_set_once` — files for each kept role appear after retirement, never before; `publish_track` called once per Track | early/duplicate staging |
| P2 `eos_finalises_evidence_of_live_tracks_only` | double finalisation |
| P3 `lease_lost_during_evidence_staging_publishes_nothing_further` (expire after first crop write; remaining role files absent; no result) | unfenced writes |
| P4 `omitted_supplementals_are_removed_from_staging_and_absent_from_result` (quota forced tiny via profile override in test) | leftovers referenced or retained |
| P5 `attempt_n_cleans_n_minus_one_including_evidence_dir` (ext of S1.1) | |
| P6 `result_observations_are_canonically_ordered` | order dependence |
| P7 `no_representative_fails_attempt_and_cleans_staging` | |
| **M1** `live_memory_holds_no_ndarray_per_track` — after each frame, gc scan: no `np.ndarray` reachable from any live accumulator/selector | raw crop retention |
| **M2** `peak_traced_memory_is_flat_in_video_length` — same single persistent Track over 60 vs 600 vs 1,200 synthetic frames (fixture detector/tracker, stub encoder returning fixed bytes); `tracemalloc` peak difference between 600 and 1,200 frames ≤ 12 B × 600 × 2 + 64 KiB | O(video-length) retention anywhere in the loop (including the `finalised`/`live` dicts and the selector) |
| **M3** `encoded_bytes_per_live_track_never_exceed_caps` | oversize holders |
| **M4** `trajectory_in_progress_is_compact_array` (12 B/point ± slack via `sys.getsizeof`) | list of dataclasses regression |

### Wire and worker (`tests/test_control_plane_contracts.py` ext, `tests/test_worker_client.py` ext, `tests/test_contract_schema_canonicalization.py` ext)

| Test | Catches |
|---|---|
| W1 v3 model rejects: 5 observations; duplicate role; rank gap; Representative rank≠0; duplicate frame; crop over role cap; Σ crops > 1 GiB; accounting mismatch | permissive model |
| W2 v3 example validates against the v3 schema and its SHA matches the digest vector file | fixture drift |
| W3 `client.complete` emits `schemaVersion "3.0"`, observations in rank order, quantised scores (≤ 6 decimals), accounting present | emitter drift |
| W4 `worker_refuses_ready_when_platform_lacks_v3` (contract endpoint 404 / missing "3.0") and `handles_version_400_as_non_retryable` | attempt-burning loop |
| W5 `runner_cleans_staging_after_successful_completion` and `cleanup_failure_does_not_fail_attempt` | staging growth |
| W6 worst-shape 10,000×4 body serialised by the Python model ≤ 48 MiB − 8 MiB | body bound |

### Platform (.NET)

| Test | Catches |
|---|---|
| N1 `VisionResultValidatorV3Tests`: rejection table for every rule in §7.2; digest deterministic and order-independent; v2 body still yields the v2 digest and tag | rule gaps; digest collision |
| N2 `VisionResultValidatorCanonicalizationTests`: v3 example → pinned digest; v2 example → unchanged pinned digest | canonicalisation drift |
| N3 `WorkerContractV3Tests`: example round-trip; observation bound enforced at binding (5 items → 400 before validation); 413 above 48 MiB; worst-shape ≤ limit − 8 MiB; **both** `2.0` and `3.0` accepted at `/complete`; lease/heartbeat/fail still reject `3.0`; `GET /api/vision/contract` shape | dual-accept regression |
| N4 `VisionResultCompletionApiTests` (ext): v3 persists 1–4 observations with role/rank/score and `EvidenceCrop` artefacts; Representative link = rank 0; idempotent v3 replay; v2 body on the upgraded store still persists Thumbnail rows and replays; sealing failure on the third crop rolls back and compensates all newly sealed objects of the Track; DB commit failure after all evidence sealed compensates; store refuses admitted crops > 1 GiB even if a test validator is stubbed | partial-set persistence; compensation gaps |
| N5 `MigrationTests` (§10.2) | migration semantics |
| N6 Domain: `Observation.Create` role/rank consistency; `ObservationType` has exactly four members | |
| N7 `ContentApiTests`: `EvidenceCrop` served for a Completed run's Observation; not served when unreferenced or run not Completed | serving gaps |
| N8 `Task14` read-security suites unchanged and green | |

---

## 15. Exact file mapping

### S1.2a — platform (and shared contracts)

| Group | Files |
|---|---|
| Contracts | `src/platform/Mavi.Contracts/Worker/WorkerContractRules.cs` (versions set, `MaximumCompletionEvidenceCropBytes`, role caps, 48 MiB); `VisionJobCompleteContracts.cs` (+`VisionTrackObservationContract`, `VisionEvidenceAccountingContract`, `VisionTrackResultContractV3` or nullable `Observations` on the existing record — prefer **one request record with both `Representative` and `Observations` nullable** and version-driven validation, to keep a single binding path); `CompletionIntegralJsonConverters.cs` (+observation list converter); `Mavi.Contracts/Worker/VisionContractCapabilitiesResponse.cs` |
| Validation | `Mavi.Application/Modules/Intelligence/VisionResultValidator.cs` (dispatch, v3 rules, digest v3, v2 normalisation to `ValidatedObservation` list); `IProcessingResultStore.cs` if result record changes |
| Persistence | `Mavi.Domain/Intelligence/Observation.cs`, `ObservationType.cs`; `Mavi.Domain/Media/ArtifactType.cs`; `Mavi.Infrastructure/Persistence/Configurations/ObservationConfiguration.cs`; `Repositories/ProcessingResultStore.cs`; `Storage/…` none; `Modules/Evidence/ContentReadService.cs`; `Repositories/ContentCatalog.cs` |
| Migration | `Mavi.Infrastructure/Persistence/Migrations/2026MMDDHHMMSS_AddTrackEvidenceSet.cs`, `MaviDbContextModelSnapshot.cs` |
| API | `Mavi.Api/Endpoints/VisionJobEndpoints.cs` (complete accepts set; new `GET /contract`; per-message `VersionProblem` text); `Middleware/VisionCompletionRequestLimitMiddleware.cs` (constant only) |
| Contract fixtures | `contracts/schemas/vision-job-complete-v3.schema.json`, `contracts/examples/vision-job-complete-v3.example.json`, `contracts/test-vectors/vision-job-complete-v3-conformance.json`, `…-v3-digest.json`, `control-plane-v3-invalid.json`, `contracts/README.md`; `tools/verify_repo.py` `check_contracts` |
| Tests | `tests/Mavi.Application.Tests/VisionResultValidatorV3Tests.cs`, `VisionResultValidatorCanonicalizationTests.cs` (ext); `tests/Mavi.IntegrationTests/WorkerContractV3Tests.cs`, `VisionResultCompletionApiTests.cs` (ext), `MigrationTests.cs` (ext), `ContentApiTests.cs` (ext); `tests/Mavi.Domain.Tests/Task13CompletionDomainTests.cs` (ext); Python `src/vision/tests/test_contract_schema_canonicalization.py` (ext, schema-validate the v3 example) |
| Docs | this plan (status), parent plan §16 pointer, `docs/runbooks/vision-runtime-model-component-lifecycle.md` (new "Completion contract v3 deployment order" section), `contracts/README.md` |

### S1.2b — worker

| Group | Files |
|---|---|
| Analytical models | `src/vision/mavi_vision/common/analytical.py` (+`EvidenceRole` import/re-export, `ObservationDescriptor(role, rank, offset_ms, source_frame_number, confidence, bounding_box, quality_score, selection_score, crop: ArtifactDescriptor)`, `ProcessedTrack.observations: tuple[ObservationDescriptor, ...]` replacing `representative`+`thumbnail`, `representative` property = rank 0, `EvidenceAccounting`, `VisionProcessingResult.evidence_accounting`) |
| Selector/scorer/encoder/admission | `mavi_vision/evidence/{__init__,roles,quality,encoder,selector,admission}.py`; `quality/scoring.py` unchanged |
| Pipeline | `pipeline/process_video.py` (`FrameContext` passed to selector; `_TrackAccumulator` → `_TrackState` with compact arrays and a `selector` field; `_finalise_track` uses `selector.resolve()`; admission + `remove_omitted` after the drain; `evidence_representative_missing`); `pipeline/finalization.py` (`prepare_track` takes `tuple[SelectedEvidence]` and returns payload per observation; JPEG encoding moves to the encoder; trajectory checks unchanged) |
| Artifact publisher/store | `storage/artifact_publisher.py` (`publish_track` writes `evidence/{trackId}-{role}.jpg` per observation + trajectory; `remove_omitted`); `storage/artifact_store.py` (`evidence_key(track_id, role)`, `remove`); `artifact_store_posix.py`, `artifact_store_windows.py` (`remove_file` no-follow) |
| Profile/config | `runtime/profile.py` (`EvidenceProfile`, `EncoderProfile`, schema `1.1`); `src/vision/config/pipelines/phase1-detection-tracking-v1.json`; `models/qualifications/rtmdet-m-coco-phase1-v1.json` (`pipelineProfileSha256`); `runtime/provenance.py` unchanged (profile version/sha already flow) |
| Wire/worker | `common/control_plane.py` (`VisionCompletionObservation`, `VisionCompletionTrack` v3 shape, `VisionEvidenceAccounting`, `VisionJobComplete.schema_version: Literal["3.0"]`, crop/trajectory quotas, accounting cross-check); `worker/client.py` (`complete` v3 mapping; `get_contract_capabilities`); `worker/runner.py` (startup capability check; post-completion cleanup; 400-version handling); `worker/health.py`/`main.py` (not-ready reason) |
| Tests | new: `test_evidence_selector.py`, `test_evidence_encoder.py`, `test_evidence_admission.py`, `test_evidence_profile.py`; ext: `test_track_lifecycle.py`, `test_process_video.py`, `test_track_finalization.py`, `test_artifact_publisher.py`, `test_artifact_store.py`, `test_artifact_store_windows.py`, `test_control_plane_contracts.py`, `test_completion_contract_bounds.py`, `test_worker_client.py`, `test_worker_runner.py`, `test_worker_end_to_end_contract.py`, `test_production_processor.py`, `test_production_processor_runtime.py`, `test_analytical_models.py`, `test_lease_ownership_matrix.py`; fixtures `src/vision/tests/fixtures/evidence/*.png` + `golden-sha.json` |
| Qualification tooling | `.github/workflows/task10-runtime-qualification.yml` (path filter widening; add `test_evidence_*.py` to the boundary step); `task10-staging-security.yml` (add remove tests); `tools/vision/dev/fixture_worker_harness.py` (v3 path); `docs/qualification/…-evidence-selector-parameter-note.md` |
| Docs | this plan (status), parent plan S1.2b pointer, ADR-013 §5 one-sentence precision (§17 C3, only if ratified), Stage-2 acceptance register rows B1/B3/B4 → "implemented; evidence pending S1.4" |

---

## 16. Implementation sequence

### S1.2a (one PR, ~6 commits)

1. Domain + migration + snapshot + `MigrationTests`.
2. Contracts + converters + constants (48 MiB, quotas) + `GET /api/vision/contract`.
3. Validator dispatch (v2 normalisation, v3 rules, digest v3) + `VisionResultValidatorV3Tests`; v2 tests untouched and green.
4. Store: multi-observation sealing/persistence/compensation; content allow-list; integration tests.
5. Contract fixtures (schema, example, digest vector, conformance, invalid) + `verify_repo` + canonicalisation tests (pins the golden digest).
6. Docs: parent §16 pointer, runbook deployment order, README.

Exit: Quality Gate + Task 17 green on the exact head; a v2 worker from `main` completes against the S1.2a platform in the composition integration test (`WorkerContractV3Tests.V2WorkerStillCompletes`).

### S1.2b (one PR, ~7 commits; requires S1.2a merged)

1. Profile section `1.1` + loader + qualification SHA re-derivation + `test_evidence_profile.py`.
2. `evidence/roles.py`, `quality.py`, `encoder.py` + tests E1–E8 and golden fixtures.
3. `evidence/selector.py` + tests S1–S15.
4. `evidence/admission.py` + tests A1–A6.
5. Pipeline integration: `_TrackState` compact arrays, `FrameContext`, selector per live Track, `prepare_track`/publisher multi-role, store `remove`, admission + removal; tests P1–P7, M1–M4; staging-security tests.
6. Wire v3 + client + runner (capability check, post-completion cleanup); tests W1–W6; production composition test.
7. Task 10 trigger widening; measurement note; docs/register updates.

Exit: Quality Gate, Task 17, Task 10 (both OS) and Staging Security green on the exact head; the v3 golden example produced by the worker's own emitter matches the S1.2a pinned digest through the .NET canonicalisation test.

---

## 17. Corrections to the parent plan (do not implement silently)

| ID | Finding | Correction | Ratification |
|---|---|---|---|
| **C1** | S1-14 (owner correction) introduced a bounded reservoir of K next-best encoded Representative candidates to implement the ADR fallback. With in-loop encoding the same guarantee falls out of a simpler rule: a candidate becomes the Representative holder only if its encoding is admissible, so the holder is always the best **admissible** qualified candidate and the fallback happens online with **no extra state**. K reservoir would add K × 64 KiB per live Track and a second replacement policy for no additional guarantee. The ADR text ("falls back to the next-best qualified candidate; the run fails only if no Representative can be produced") is satisfied verbatim. | §4.2; E6 keeps the adversarial measurement S1-14 demanded. | **Owner** (replaces an owner correction) |
| **C2** | Parent §12.2/§12.6 require "Python and .NET compute the same v3 digest on the golden fixture". The worker computes no digest (`client.py` sends none; the digest is server-side idempotency state). Adding a Python digest would duplicate canonicalisation logic without a consumer. | Cross-language agreement is pinned on the **body**: Python emits/validates the golden example against the v3 schema and pins its SHA; .NET computes and pins the digest of that same file (§7.5). | Plan-level |
| **C3** | Neither parent nor ADR-013 §5 ("cleaned by the existing attempt cleanup") accounts for the staging of a **successfully completed** attempt: nothing removes it today. v2 leaves KBs per Track; v3 leaves up to ~5 GiB per job (or ~1 GiB after admission removals). | Worker runs `cleanup()` best-effort after a successful `complete()` (§6.3); accepted evidence is already sealed under ADR-006 so staging is dead. ADR-013 §5 sentence should read "…cleaned by attempt cleanup on failure, by the next attempt on lease loss, and by the worker after acceptance". | **Owner** (one-sentence ADR precision) |
| **C4** | "Live memory ≤ 4 × 160 KiB plus its trajectory-in-progress" leaves the second term unquantified; today it is ≈ 80 B/point. | Compact arrays at 12 B/point; bound stated with arithmetic (§9.1) as O(Track duration), independent of video length and Track count. | Plan-level |
| **C5** | The parent's "new worker against old platform gets 400 and must not retry indefinitely" still burns one attempt per job. | `GET /api/vision/contract` capability check before READY (§11.1); 400 handling kept as defence in depth. | Plan-level (additive endpoint; no ADR) |
| **C6** | Parent §7.2 step 5 drops EarlyDiverse "at retirement if the Representative later moves onto its frame" but was silent for NearView/Late and for the order of precedence. | Uniform resolve rule in role order (§4.3); NearView exempt from separation (ADR wording) but not from duplication. | Plan-level |
| **C7** | Parent §8.1 keeps `SelectionScore` and `QualityScore` as separate columns with identical values in S1.2. | Kept deliberately (frame quality vs selection ordering) with the rationale stated (§7.2); no change, recorded so it is not mistaken for duplication. | — |

No ADR *decision* changes. C1 and C3 touch ADR-013 §5 wording only; they are flagged for ratification in the planning PR and are not applied to the ADR in this PR.

---

## 18. Acceptance criteria

S1.2a is done when: migration applied and tested; platform accepts v2 and v3 with distinct digests; v3 persists ≤ 4 observations with role/rank/score and `EvidenceCrop` artefacts; content serving covers `EvidenceCrop`; `GET /api/vision/contract` advertises both; golden v3 fixture and digest pinned; worst-shape body measured ≤ 48 MiB − 8 MiB; Quality Gate + Task 17 green on head; a `main` v2 worker completes against it.

S1.2b is done when: worker emits v3 conforming to the schema and pinned example; selector/encoder/admission tests S1–S15, E1–E8, A1–A6, P1–P7, M1–M4, W1–W6 green; no `np.ndarray` retained per live Track (M1) and peak memory flat in video length (M2); post-completion staging cleanup in place; worker refuses READY without v3 acceptance; profile `1.1` with re-derived qualification SHA; Task 10 both OS + Staging Security + Quality Gate + Task 17 green on head; measurement note committed.

Register: B1, B3, B4 → "implemented — evidence pending S1.4"; B2 stays as S1.1 left it plus "in-loop encoding implemented"; B5, B6 unchanged.

---

## 19. Deferred to S1.3 / S1.4 / later

- `TrackDetail.observations[]`, web types, Evidence Set viewer (S1.3).
- Peak-RSS measurement at volume, staging bytes per run, sealing wall time at bound, admission rates, Task-10 rebinding statement, CUDA/E2E rebinding (S1.4).
- v2 acceptance removal (separate decision, §11.2 step 4).
- Garbage collection of orphaned sealed evidence and abandoned staging (Task-13 deferral; unchanged).
- Retention/purge policy for supplemental crops (ADR-013 §19 trigger).
- Crop pixel dimensions on the wire (useful for NearView consumers; deliberately excluded to avoid worker-declared, platform-unverifiable fields; revisit with the attribute lease contract).
- Trajectory v2 (unchanged; separate slice).

---

## 20. Open risks

| Risk | Mitigation in this plan | Residual |
|---|---|---|
| Selector defaults poorly tuned → Early/Late rarely fill or Representative floor rejects real Tracks | measurement note before merge; `confidenceFloor ≤ activation` enforced | parameters may need a profile revision after S1.4 evidence |
| Floor-size JPEG of pathological content > 64 KiB | E6 measured per variant; online best-admissible rule; attempt fails only with zero admissible frames | accepted per ADR |
| CPU cost: sharpness + up to 15 encodes per replacement | ε/hysteresis/window bounds; S1.4 measures selector + encode CPU/frame | may motivate a cheaper sharpness proxy in a scorer v2 |
| Pathological live-Track count (L ≈ 3,000) | bound stated; S1.4 measures | Development hosts only |
| Sealing time under the row lock with ≤ 5 objects/Track | unchanged authority semantics; S1.4 measures | |
| Cross-OS detector/tracker parity not asserted | out of scope; stated in §8 | |
| Stale N−1 writer racing attempt N cleanup (S1.1 risk) | unchanged | retryable failure |
| v2 retirement timing | explicit conditions §11.2 | separate decision |
