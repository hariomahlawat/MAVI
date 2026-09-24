# Evidence selector parameter note (S1.2c)

**Status:** Complete. The C1 scripted corpus and two real benchmark clips (MOT17-02-FRCNN, MOT17-13-FRCNN at 1920×1080) were measured through the production RTMDet → ByteTrack → Evidence Set path, on a runtime built from the repository's qualified `linux-x86_64-cpu` definition (`mmcv` rebuilt locally from its pinned source; §4).
- The first real-clip measurement found **F1** (§8): the quality-v1 occlusion proxy counted the detector's sub-floor residue.
- On the owner's decision (option (a), 2026-09-24), F1 was fixed as scorer **`quality-v2`** (ADR-013 §4 occlusion-proxy amendment). The profile SHA is now **`503225be…23fb`**, and the qualification record is rebound with every gate `pending`.
- The measurement was then **re-run from scratch** on the final implementation.
- **Every selector parameter was re-adjudicated from the quality-v2 results, and every default is retained** (§9).

This note qualifies nothing.

**Date:** 2026-09-24
**Asked for by:** S1.2 implementation plan §5 ("before S1.2c merges, record a measurement note over the C1 scripted corpus and ≥ 2 real Development clips … adjust defaults in the same PR").
**Profile measured (final):** `src/vision/config/pipelines/phase1-detection-tracking-v1.json`, schema 1.1, `profileVersion` 1.2.0-candidate, SHA-256 `503225be736d9622ed110aa69e49a83dde4ae02c858d5e8fa41e527b1c4b23fb`, scorer `quality-v2`. The before results used SHA `47560e0e…3eba` (scorer `quality-v1`); the only difference is `scorerVersion`. `profileVersion` stays 1.2.0-candidate, following this PR's precedent for `selectorVersion`: the candidate version has not been released, and the SHA is the binding identity. The qualification record `models/qualifications/rtmdet-m-coco-phase1-v1.json` binds the final SHA and stays `pending`.

## 1. Purpose

This is the engineering measurement that plan §5 requires before S1.2c merges. It checks that the selector's defaults behave as intended on real detector and tracker output: no systematic over-rejection, under-filtering, encode churn or role starvation. It is **not** Stage-2 model-quality qualification, a performance qualification or an S1.4 acceptance row. Two public clips are a calibration corpus, not a tuning target. Where values performed similarly, the existing value is kept.

## 2. Scripted corpus (C1)

### Method

`tools/vision/dev/measure_evidence_parameters.py` (a Development tool, not a runtime component) generates the three C1 scripted-corpus videos with ffmpeg (`tools/vision/dev/scripted_corpus.py`). It runs each video through the real `VideoProcessor` with the shipped profile's evidence policy, the real `QualityV1Scorer` and the real `JpegLadderEncoder`. Only detection and tracking are scripted: they report the box ffmpeg drew on each frame, as `fixture_worker_harness.py` does. Reproduce from the repository root:

```
PYTHONPATH=src/vision python tools/vision/dev/measure_evidence_parameters.py <work-dir>
```

Host: Linux x86_64, Python 3.13, Pillow 11.3.0, PyAV 16.1.0, system ffmpeg. Every video is 640×360 at 25 fps, with a 40×80 white box on a 0x202020 matte and detections on frames 25–274 (250 per Track).

### 2.1 Results (one confirmed Track per video)

| Scenario | Sharpness min / median / max | Area | Edge margin min / median / max | Frames passing: confidence / sharpness / edge / occlusion / **all** | Roles filled | Encodes per Track |
|---|---|---|---|---|---|---|
| line-crossing | 0.000 / 0.000 / 0.0219 | 0.0139 | 0.000 / 0.031 / 0.389 | 100 % / **0 %** / 52 % / 100 % / **0 %** | Representative only (fallback, frame 40) | 5 |
| zone-dwell-exit | 0.0219 / 0.0219 / 0.0226 | 0.0139 | 0.069 / 0.389 / 0.389 | 100 % / **0 %** / 100 % / 100 % / **0 %** | Representative only (fallback, frame 29) | 3 |
| stationary-then-depart | 0.0219 / 0.0219 / 0.0222 | 0.0139 | 0.069 / 0.269 / 0.389 | 100 % / **0 %** / 100 % / 100 % / **0 %** | Representative only (fallback, frame 25) | 1 |

Crops were 701–789 bytes at the first ladder step. Nothing was omitted by admission.

### 2.2 Reading

- **The corpus's box is featureless by construction.** Sharpness is the mean absolute grey gradient of the crop divided by 64, and a uniform box yields almost none. No frame reaches the 0.05 floor, so no frame qualifies and no supplemental role is ever filled. This is a property of the synthetic scene, not evidence that 0.05 is too high for real subjects.
- **The strict ADR-013 §4 rule would fail all three jobs.** With no qualified frame there is no qualified Representative, and plan §4.2 fails the attempt (`evidence_representative_missing`). The worker instead keeps a fallback Representative (the two-tier rule, E8 in plan §16.2, accepted by the owner on 2026-09-24 as the ADR-013 §4 amendment). **Fallback-Representative rate on this corpus: 3 of 3 Tracks (100 %).** A fallback Representative is not qualified evidence, and no supplemental role was filled. These videos are what the scripted-corpus workflow and the fixture harness process.
- **Edge margin works as intended.** In line-crossing the box runs along the top edge from frame 155 (margin 0): 48 % of its frames fail the edge floor, and the textured variant of the same motion (`test_evidence_scripted_corpus.py`) stops qualifying there.
- **Encodes stay small.** Encodes are 1–5 per Track over 250 frames here, and 5–7 with all four roles in the textured variant. The ε and hysteresis rules bound re-encoding, not Track length.
- **Area is constant** (the box never changes size), so NearView growth was not exercised by the real videos; the selector tests cover it.

### 2.3 Defaults (scripted corpus)

No default is changed. The corpus cannot justify tuning: lowering `sharpnessFloor` until a flat synthetic box qualifies would tune to an artificial scene. Every other floor behaved as designed.

**Re-run under quality-v2** (commit `3175cae`, profile `503225be…23fb`). The results are identical: the same floors, fallback frames 40 / 29 / 25, encodes 5 / 3 / 1 and crop bytes. Each scripted scene has one detection per frame, so the occlusion proxy is 0 under either scorer.

## 3. Real-clip corpus

MOTChallenge MOT17 training sequences, used for qualification only. They are licensed CC BY-NC-SA 3.0 (MOTChallenge terms), and they are never committed or redistributed. No clip, frame or output is in Git.

**Source decision.** The official "sequence videos" (`https://motchallenge.net/sequenceVideos/<seq>-raw.webm`) turned out to be **960×540 VP9 previews**, not the benchmark's 1920×1080. The primary corpus is therefore built from the benchmark's own full-resolution frames: the `img1` JPEGs of each sequence, read from the official `https://motchallenge.net/data/MOT17.zip` (5,860,214,001 bytes) by HTTP range requests. Only the two sequences' members were fetched, and `zipfile` verified each member's CRC-32. MAVI's import accepts only `.mp4` (`VideoImportOptions.AllowedExtensions`). Each sequence was therefore **stream-copied** into MP4 with the runtime's own PyAV 16.1.0 / FFmpeg 8.0.1: every official JPEG became one MJPEG packet (pts = frame index, time base 1/fps). There was no decode, no re-encode, no rescale and no frame-rate change. A demux check confirms that every packet is byte-identical to its source JPEG (600/600 and 750/750). The WebM previews were also remuxed to MP4 without re-encoding, and measured as a **supplementary** lower-resolution, lossy-compressed variant (§6.6).

| | MOT17-02-FRCNN (primary) | MOT17-13-FRCNN (primary) |
|---|---|---|
| Scene | Crowded pedestrian street, static camera | Busy road, camera on a moving bus, people and vehicles |
| Source | `MOT17.zip` → `MOT17/train/MOT17-02-FRCNN/img1/000001–000600.jpg` | `MOT17.zip` → `MOT17/train/MOT17-13-FRCNN/img1/000001–000750.jpg` |
| Fetched | 2026-09-24 03:56–04:22 UTC | same |
| Frames-tree SHA-256¹ | `8bbae6756ebfe652ded1809fcbe2a527e57f99a168ea563587a120a7df2b2615` | `39bf43f24f4a8b2c391f15a7556707c9e369e39e0b5d873f01806f9a61d844a1` |
| Measured file | `MOT17-02-FRCNN-1080p-mjpeg.mp4`, 105,652,679 B | `MOT17-13-FRCNN-1080p-mjpeg.mp4`, 175,317,278 B |
| File SHA-256 | `e07f9a54ea82e77fcdc23880df9047dbfefe7e297c212fef1ccacf484647f33a` | `4ee19cc9b6792f63f4053305f7da1dde6f077ff4293fade23810575c3117a17e` |
| Container / codec | MP4 / MJPEG (yuvj420p) | MP4 / MJPEG (yuvj420p) |
| Size, rate, length | 1920×1080, 30 fps, 600 frames, 20.0 s | 1920×1080, 25 fps, 750 frames, 30.0 s |
| `seqinfo.ini` | frameRate 30, seqLength 600, 1920×1080 | frameRate 25, seqLength 750, 1920×1080 |
| Ground truth (context only)² | 62 considered pedestrian identities | 110 considered pedestrian identities, 23 annotated cars |

¹ SHA-256 over the concatenation, in file-name order, of `basename + NUL + raw 32-byte SHA-256 digest of the JPEG bytes`, for every `img1` frame.
² From `MOT17Labels.zip` (SHA-256 `0aa79322…82b2b9`). Used only to describe the scenes. It never fed the detector, the tracker or the selector.

Supplementary files (§6.6):

| Sequence | WebM (official) | Remuxed MP4 (measured) |
|---|---|---|
| MOT17-02-FRCNN | `MOT17-02-FRCNN-raw.webm`, 5,539,659 B, SHA-256 `8d1872d9d9bf0b2ea55b775f2d9faa0385d6907647dca3cb6c7cead7e3a00920`, fetched 2026-09-24 03:50 UTC | 5,540,888 B, SHA-256 `bec13e2e7b9129642bd66a2ac767c768f2fb6f1384549d599058f9923f781fac`; VP9 960×540, 30 fps, 600 frames |
| MOT17-13-FRCNN | `MOT17-13-FRCNN-raw.webm`, 7,869,562 B, SHA-256 `19075cdf256ef23ce5432e16ab4b6a8c5a75b5d8f0c5548955f6eacf672a06c5`, fetched 2026-09-24 03:50 UTC | 7,867,006 B, SHA-256 `5ca4cc578dbc1a320c8a292400b6e3a88a70b7265b641a73e2f7b02928795132`; VP9 960×540, 25 fps, 750 frames |

All four files decode through MAVI's `iter_frames` with monotonic offsets (0, 33, 67 … 19967 ms and 0, 40, 80 … 29960 ms). The decoded RGB of the MJPEG files differs from a Pillow/libjpeg decode of the same JPEGs by a mean of 0.8 grey levels. That is the difference between the two JPEG decoders and their chroma upsampling, not a re-encode.

## 4. Runtime identity

The runtime was built from the repository's own qualified definition for `linux-x86_64-cpu`, the same recipe as the Task 10 hosted-CPU job. No ad-hoc environment was used.

| Item | Value |
|---|---|
| Host | Linux x86_64 (Ubuntu 24.04, kernel 6.18), 4 vCPU, 15 GiB RAM, no GPU |
| Python | 3.12.14 CPython, build `main, Aug 13 2026 02:47:42`, GCC 13.3.0. This is the `actions/python-versions` release `3.12.14-31661455385` (`python-3.12.14-linux-24.04-x64.tar.gz`, SHA-256 `5a031682…1e622257fff`), the interpreter the runtime profile's `pythonIdentity` pins. The supervisor verified it on every run. |
| Packages | `linux-x86_64-cpu.lock`: all 60 entries except `mmcv` installed with `pip --require-hashes --no-deps --only-binary=:all:` (PyPI and `download.pytorch.org/whl/cpu`) |
| `mmcv` 2.1.0 | Built from the pinned source commit `57c4e25e06e2d4f8a9357c84bcd24089a284dc88` against the locked torch (`MMCV_WITH_OPS=1`), as the Task 10 job builds it. **Deviation:** the local wheel's SHA-256 is `dfc6313a…d6d4af`, not the lock's `4fbeb417…`, because a native build is not byte-reproducible. Source, version and ABI are the same, and the supervisor's semantic-graph check passed. |
| Semantic graph | torch 2.6.0+cpu, torchvision 0.21.0+cpu, mmcv 2.1.0, mmengine 0.10.7, mmdet 3.3.0, trackers 2.6.0, supervision 0.30.2, scipy 1.18.1, numpy 2.5.3, opencv 5.0.0 (opencv-python 5.0.0.93), av 16.1.0, pillow 11.3.0 |
| Model Pack | `rtmdet-m-coco-phase1` 1.0.0, manifest SHA-256 `0049875d…8d7d`. Checkpoint `rtmdet_m_8xb32-300e_coco_20220719_112220-229f527c.pth` from `download.openmmlab.com`, SHA-256 `229f527ca88498e8894a778a62a878a322b4a3ea2cae09ea537d34b7e907792b` (verified). The resolved config was generated with `tools/vision/resolve_mmdet_config.py` from MMDetection commit `44ebd17b…ab64a`; its SHA-256 `377d9f57…c5ee3` equals the manifest's. |
| Runtime profile | `mmdetection-phase1-v1`, SHA-256 `b3c59ac4…6c873`, variant `linux-x86_64-cpu` |
| Qualification | `rtmdet-m-coco-phase1-v1`, record SHA-256 `7d7083d9…f3e7b9` (quality-v2; `911c3fe4…668d` for the quality-v1 runs), bound to the profile SHA below, `verificationStatus` `unverified`, every gate `pending` (Development) |
| Pipeline | profile `phase1-detection-tracking-v1` 1.2.0-candidate. **Final:** SHA-256 `503225be736d9622ed110aa69e49a83dde4ae02c858d5e8fa41e527b1c4b23fb`, scorer **`quality-v2`**. **Before:** `47560e0e…3eba`, scorer `quality-v1`. Selector `evidence-selector-v1-two-tier`, encoder `evidence-jpeg-ladder-v1`. Tracker: ByteTrack (`trackers` 2.6.0), activation 0.7, high 0.6, IoU 0.1, 2 frames, lost buffer 1.0 s at 30 fps reference. Frame policy every-frame. Detector inference floor 0.05. |
| Device | configured `cpu` (`MAVI_DEVICE_POLICY=cpu`, Development mode); actual `cpu` |
| Supervisor | `RuntimeSupervisor` from `WorkerSettings` reached READY. The qualified ByteTrack (10) and production-composition (1) suites and the harness suite (3) passed on this runtime. |
| Code | **Final (quality-v2):** measured from scratch at commit `3175cae` (fresh output directory, 2026-09-24 05:51–05:58 UTC). **Before (quality-v1):** commit `73e0315` (also reproduced exactly at `9917817`). The provenance's `mavi_commit` records each. |

## 5. Method

`tools/vision/dev/measure_evidence_real_clips.py` is Development qualification tooling, not a runtime component.
- **Runtime:** it builds the runtime as the worker does: `WorkerSettings` → `RuntimeSupervisor`, and it refuses to run unless the supervisor is READY.
- **Composition:** each clip runs on the vision execution lane through exactly the `ProductionVisionProcessor` composition: `RTMDetDetector` → `ByteTrackTracker` → `VideoProcessor(evidence_policy=profile.evidence)`. That means real decode, real detections, real Tracks, the profile's scorer from `scorer_for_policy` (quality-v2), the two-tier `EvidenceSelector`, the `JpegLadderEncoder`, retirement, staging and run-level admission.

The instrumentation observes and never decides:
- The scorer and encoder are wrapped to record the scalars they compute.
- `EvidenceSelector.observe` / `resolve` are tapped read-only, to record:
  - the Representative tier after each frame;
  - the holders before `resolve()`;
  - why a held NearView was dropped (evaluated with the selector's own rule).
- Diagnostic columns record the **superseded quality-v1 proxy** (maximum IoU over every detection) and the confidence and class of the box that produced it. These are the before/after counterfactual. The selector always used the production value.
- Normalised box scalars allow an offline match against MOT17 ground truth (descriptive context only).
- No pixel or selector is retained, and per-candidate rows are scalars.
- `test_measure_evidence_real_clips.py` proves that the instrumented run's Evidence Sets are identical to the plain production processor's (Tracks, roles, ranks, frames, scores and crop bytes). It runs in the Task 10 qualified job.
- Every re-run on unchanged code reproduced every count, rate and encode statistic exactly.

The statistics describe the Tracks the tracker confirmed, not benchmark subjects: 21 confirmed Tracks in MOT17-02 against 62 annotated pedestrians. The detector and tracker output is identical under both scorers: the same 63 Tracks and 8,284 candidates, with the same confidence, sharpness, area and edge-margin values. Only the occlusion proxy and what follows from it differ.

Percentiles are nearest-rank, at index `round(q·(n−1))` of the sorted values. "Candidate" means one Track candidate in one frame, over every confirmed Track; no Track is excluded. Rates are over candidates unless stated per Track. Reproduce from `src/vision`, with the worker settings in the environment:

```
PYTHONPATH=. python ../../tools/vision/dev/measure_evidence_real_clips.py <out> MOT17-02-FRCNN=<mp4> MOT17-13-FRCNN=<mp4>
```

The outputs stay local and are not committed:
- `summary.json`, about 96 KB;
- `candidates.csv.gz`, about 880 KB;
- `<out>/staging`, the run's staged Evidence crops and trajectories (216 files, 1.0 MiB). It holds crops of benchmark subjects and is deleted after review.

Peak RSS and processing time include the harness's own overhead.

## 6. Results — final (quality-v2, 1920×1080)

### 6.1 Volume

| | MOT17-02 | MOT17-13 | Combined |
|---|---|---|---|
| Frames processed | 600 | 750 | 1,350 |
| Confirmed Tracks (person / vehicle) | 21 (21 / 0) | 42 (27 / 15) | 63 (48 / 15) |
| Candidates | 3,875 | 4,409 | 8,284 |
| Candidates per Track, min / p50 / max | 21 / 135 / 571 | 4 / 71 / 431 | 4 / 99 / 571 |
| Track duration, p10 / p50 / p90 | 1.5 / 4.5 / 14.0 s | 0.8 / 2.8 / 8.3 s | 0.8 / 3.5 / 12.7 s |

### 6.2 Distributions (all candidates)

The detector-side signals are identical under both scorers:

| Signal | Clip | min | p10 | p25 | p50 | p75 | p90 | max |
|---|---|---|---|---|---|---|---|---|
| Sharpness | 02 | 0.0057 | 0.0262 | 0.0370 | 0.0526 | 0.0667 | 0.0812 | 0.2275 |
| | 13 | 0.0103 | 0.0449 | 0.0619 | 0.0889 | 0.1194 | 0.1412 | 0.1928 |
| | all | 0.0057 | 0.0306 | 0.0465 | 0.0661 | 0.0946 | 0.1277 | 0.2275 |
| Area (normalised) | 02 | 0.00037 | 0.0050 | 0.0099 | 0.0175 | 0.0360 | 0.0600 | 0.2913 |
| | 13 | 0.00032 | 0.0015 | 0.0028 | 0.0060 | 0.0128 | 0.0270 | 0.0990 |
| | all | 0.00032 | 0.0021 | 0.0043 | 0.0106 | 0.0225 | 0.0441 | 0.2913 |
| Edge margin | 02 | 0 | 0 | 0.0353 | 0.2106 | 0.3264 | 0.3678 | 0.4383 |
| | 13 | 0 | 0.0022 | 0.1100 | 0.2217 | 0.3549 | 0.4222 | 0.4762 |
| | all | 0 | 0.00004 | 0.0717 | 0.2191 | 0.3370 | 0.3950 | 0.4762 |
| Detector confidence | 02 | 0.059 | 0.138 | 0.489 | 0.703 | 0.763 | 0.798 | 0.861 |
| | 13 | 0.051 | 0.223 | 0.627 | 0.730 | 0.806 | 0.849 | 0.895 |
| | all | 0.051 | 0.170 | 0.596 | 0.718 | 0.783 | 0.831 | 0.895 |
| **Occlusion proxy, quality-v2** | 02 | 0 | 0 | 0 | 0.050 | 0.147 | 0.257 | 0.645 |
| | 13 | 0 | 0 | 0 | 0 | 0.062 | 0.197 | 0.998 |
| | all | 0 | 0 | 0 | 0.018 | 0.110 | 0.234 | 0.998 |
| *Occlusion proxy, quality-v1 (before)* | all | 0 | 0.335 | 0.514 | 0.621 | 0.942 | 0.977 | 1.0 |

Sharpness by class, p10 / p25 / p50: person 0.028 / 0.042 / 0.060, vehicle 0.045 / 0.064 / 0.103.

### 6.3 Floor pass rates (share of candidates)

| Floor (default) | MOT17-02 | MOT17-13 | Combined | Person | Vehicle |
|---|---|---|---|---|---|
| confidence ≥ 0.5 | 74.6 % | 84.4 % | 79.8 % | 77.3 % | 84.7 % |
| sharpness ≥ 0.05 | 54.6 % | 85.7 % | 71.2 % | 63.8 % | 85.6 % |
| edge margin ≥ 0.005 | 81.0 % | 89.1 % | 85.3 % | 81.3 % | 92.9 % |
| occlusion < 0.30 (quality-v2) | 93.3 % | 93.7 % | 93.5 % | 93.3 % | 93.9 % |
| **all floors (qualified)** | **39.5 %** | **69.3 %** | **55.4 %** | 46.7 % | 72.3 % |

537 candidates (6.5 %) are blocked by a credible occluder: 367 persons and 170 vehicles.

### 6.4 Two-tier Representative and roles (per Track)

| | MOT17-02 | MOT17-13 | Combined |
|---|---|---|---|
| Tracks with ≥ 1 qualified candidate | 17 / 21 | 37 / 42 | 54 / 63 (85.7 %) |
| **Fallback Representative** | 4 / 21 (19.0 %) | 5 / 42 (11.9 %) | **9 / 63 (14.3 %)** |
| Fallback by class | person 4/21 | person 5/27, vehicle 0/15 | person 9/48 (18.8 %), vehicle 0/15 |
| Fallback → qualified transitions | 5 | 3 | 8 (the other 46 qualified Tracks were qualified from their first candidate) |
| Tracks with no admissible Representative | 0 | 0 | 0 (both jobs completed) |
| Fallback Tracks that had a qualified candidate | 0 | 0 | 0 |
| Supplemental holders that are not qualified | 0 | 0 | 0 |
| Fallback Tracks with any supplemental role | 0 | 0 | 0 |
| NearView | 15 (71.4 %) | 36 (85.7 %) | 51 (81.0 %); 51/54 (94.4 %) of qualified Tracks |
| EarlyDiverse | 12 (57.1 %) | 11 (26.2 %) | 23 (36.5 %); 23/54 (42.6 %) |
| LateDiverse | 8 (38.1 %) | 8 (19.0 %) | 16 (25.4 %); 16/54 (29.6 %) |
| All four roles | 8 (38.1 %) | 4 (9.5 %) | 12 (19.0 %); 12/54 (22.2 %) |

The E8 behaviour holds:
- Every Track kept a Representative.
- No fallback was left on a Track that had a qualified candidate.
- No supplemental role was filled by, or relaxed for, an unqualified frame.
- Displacement by the *first* admissible qualified candidate follows from the selector rule, with 0 encode refusals. The harness records the tier change, not its frame.

**The 9 remaining fallback Tracks** are all persons. For each Track, the table names the floor(s) that block it: a frame would qualify if that floor alone were removed, or the floor fails in every frame.

| Clip | Tracks | Blocked by |
|---|---|---|
| MOT17-02 | `person-000003`, `-000019`, `-000020` (21–99 candidates) | sharpness alone |
| MOT17-02 | `person-000014` (153) | sharpness or confidence |
| MOT17-13 | `person-000005`, `-000012`, `-000015` (4–11 candidates) | frame edge in every frame |
| MOT17-13 | `person-000018` (46) | frame edge **and** sharpness in every frame |
| MOT17-13 | `person-000025` (35) | sharpness in every frame |

Sharpness is involved in 6 of the 9, and the frame edge in 4 (moving-camera subjects entering or leaving). The reviewed fallback crops show large near-camera subjects that are visibly motion-blurred in low light, and a subject in low-texture dark clothing. These are the soft, low-texture and truncated cases the two-tier Representative exists for.

**Ground-truth context (descriptive only).** Each candidate was matched to the best MOT17 box of its class in the same frame (IoU ≥ 0.5; persons 1, 2, 7; vehicles 3, 5):

| Group (quality-v2) | Candidates | Matched | GT visibility p25 / p50 / p75 | Visible ≥ 0.75 | Visible < 0.5 |
|---|---|---|---|---|---|
| person, qualified | 2,560 | 2,557 | 0.90 / 1.00 / 1.00 | 87.2 % | 4.7 % |
| person, blocked by a credible occluder | 367 | 235 | 0.16 / 0.45 / 1.00 | 42.1 % | 51.9 % |
| person, fails sharpness | 1,985 | 1,541 | 0.66 / 0.95 / 1.00 | 67.5 % | 16.2 % |
| vehicle, qualified | 2,026 | 2,009 | 0.90 / 1.00 / 1.00 | 88.5 % | 2.4 % |
| vehicle, blocked by a credible occluder | 170 | 160 | 1.00 / 1.00 / 1.00 | 84.4 % | 10.6 % |

Qualified person evidence is well visible, and the credible-occluder rule isolates the genuinely occluded persons. The 170 vehicle candidates blocked by credible boxes are mostly unoccluded by the annotation. The residue is same-object `car` / `truck` boxes that both reach `confidenceFloor` (maximum proxy 0.998). That is 6.1 % of vehicle candidates, and it costs no vehicle Track its qualified Representative (0 / 15 fallbacks). It is a recorded residual (§10), not a reason to change a parameter.

### 6.5 Encodes, caps, NearView resolve drops, crops, runtime

- **Encode attempts per Track:** mean 6.35, median 6, max 16. That is 400 attempts for 8,284 candidates (4.8 %). Re-encodes were mean 3.84, median 2, max 14.
  - The 14-re-encode Track is `vehicle-000011`: 99 candidates, qualified Representative only. Its score rises steadily as the vehicle approaches, and it passes ε each time.
  - The next are `vehicle-000002` (13; 332 candidates) and `person-000010` (12; 284 candidates, all four roles).
- **JPEG cap refusals:** 0. Unadmissible-by-role: 0. Admission omitted nothing: 153 crops (63 + 51 + 23 + 16), 875,395 B, against the 1 GiB quota. Every crop was admitted at ladder step 0.
- **NearView dropped at `resolve()`:** 1 of 52 held (1.9 %), as a near-duplicate of a later Representative (MOT17-13). The Track kept its Representative. The plan §20 residual is real but not material.
- **Encoded crops (bytes, p10 / p50 / max):** Representative 1,626 / 3,380 / 28,005; NearView 2,879 / 5,318 / 20,374; EarlyDiverse 1,755 / 4,763 / 14,707; LateDiverse 1,588 / 4,741 / 14,336. **Long edge in px (p10 / p50 / max):** Representative 85 / 193 / 700; NearView 142 / 248 / 504.
- **Runtime (engineering facts, not a performance qualification).** CPU on 4 vCPU:
  - MOT17-02: 181.4 s for 20.0 s of video, 0.11× real time (3.3 fps).
  - MOT17-13: 226.2 s for 30.0 s, 0.13× (3.3 fps).
  - The whole run took 6 min 57 s including model load.
  - Peak RSS was 767 MiB (939 MiB on one earlier run; harness included). Staging was 1.0 MiB.
  - No errors. Only upstream warnings: `FutureWarning` for `torch.cuda.amp.autocast`, `UserWarning` for `torch.meshgrid`, and MMEngine's notice that `data_preprocessor.mean/std` in the checkpoint are unused.

## 7. Before / after (quality-v1 at `73e0315` → quality-v2 at `3175cae`, same corpus and runtime)

| | quality-v1 | quality-v2 |
|---|---|---|
| Occlusion pass rate | 8.3 % | **93.5 %** |
| All-floor (qualified) candidates | 331 (4.0 %) | **4,586 (55.4 %)** |
| — persons / vehicles | 6.0 % / 0.04 % (1 of 2,801) | 46.7 % / 72.3 % |
| Tracks with a qualified candidate | 26 / 63 | **54 / 63** |
| Fallback Representatives | 37 / 63 (58.7 %) | **9 / 63 (14.3 %)** |
| — vehicles | 14 / 15 | **0 / 15** |
| NearView / EarlyDiverse / LateDiverse / all four | 30.2 / 11.1 / 7.9 / 3.2 % | **81.0 / 36.5 / 25.4 / 19.0 %** |
| Encode attempts per Track (mean / median / max) | 3.59 / 2 / 14 | 6.35 / 6 / 16 |
| Re-encodes per Track (mean / median / max) | 2.08 / 1 / 11 | 3.84 / 2 / 14 |
| Admitted crops / bytes | 94 / 580,314 B | 153 / 875,395 B |
| JPEG cap refusals | 0 | 0 |
| NearView resolve drops | 0 / 19 | 1 / 52 |
| Processing time (02 / 13) | 191.3 / 224.6 s | 181.4 / 226.2 s |

The first measurement predicted these results from its counterfactual columns (all-floor 55.4 %, at most 9 fallbacks), and they were met exactly. The rest of the run is unchanged: detections, Tracks, the other three floors and every encoder bound. More encodes per Track is the cost of 2.6× more qualified roles, and it stays small (4.8 % of candidates; ladder step 0 throughout).

## 8. Finding F1 (resolved) — the quality-v1 occlusion proxy counted sub-floor detections

*Found by the first real-clip measurement. Resolved by scorer `quality-v2` (owner decision, option (a), 2026-09-24; ADR-013 §4 occlusion-proxy amendment). Kept here as the record of why the scorer changed.*

The quality-v1 proxy was the maximum IoU with **every** other detection the tracker was given, down to `detectorInferenceFloor` 0.05, after RTMDet's per-source-class NMS (IoU 0.65). That set included:
- low-confidence part-boxes and duplicates of the same person;
- for vehicles, same-object `car` / `truck` / `bus` boxes, which all map to `vehicle`. 2,587 of 2,787 blocked vehicle candidates had a same-class occluder with IoU > 0.65 (median 0.96). After per-class NMS at 0.65 that happens in practice only across source classes: persons exceeded 0.65 against a same-class box in just 6 edge-clipped cases after MAVI's post-NMS clipping.

Measured under quality-v1 at 1080p:
- 92.9 % of occlusion rejections (7,061 of 7,598) were due *only* to boxes below `confidenceFloor`;
- the median blocking box had confidence 0.115;
- 92.6 % of blocking boxes had the candidate's own class.

**Ground-truth context (quality-v1 groups):**

| Candidate group | Candidates | Matched | GT visibility p25 / p50 / p75 | Visible ≥ 0.75 | Visible < 0.5 |
|---|---|---|---|---|---|
| person, passes the quality-v1 proxy | 672 | 587 | 0.90 / 1.00 / 1.00 | 84.3 % | 3.4 % |
| person, blocked only by boxes < `confidenceFloor` | 4,444 | 3,613 | 0.78 / 1.00 / 1.00 | 77.8 % | 10.1 % |
| person, blocked by a box ≥ `confidenceFloor` | 367 | 235 | 0.16 / 0.45 / 1.00 | 42.1 % | 51.9 % |
| vehicle, passes the quality-v1 proxy | 14 | 3 | 1.00 / 1.00 / 1.00 | 3 of 3 | 0 |
| vehicle, blocked only by boxes < `confidenceFloor` | 2,617 | 2,470 | 0.90 / 1.00 / 1.00 | 87.4 % | 2.8 % |
| vehicle, blocked by a box ≥ `confidenceFloor` | 170 | 160 | 1.00 / 1.00 / 1.00 | 84.4 % | 10.6 % |

The official 960×540 VP9 previews, measured under quality-v1 as a supplementary variant (56 Tracks, 8,182 candidates), showed the same defect: 93.4 % of occlusion rejections were due only to sub-floor boxes, with a 48.2 % fallback rate. Those files are described in §3.

**Why no parameter could fix it.** The blocking boxes were near-duplicates of the subject. No `occlusionIouCeiling` separates them from real occlusion. The fix had to change the proxy's input set, which is scorer semantics.

**Trade-off accepted with the fix.** A real occluder that the detector sees only below `confidenceFloor` no longer disqualifies a frame: 10.1 % of the persons rescued from quality-v1 were less than half visible, against 3.4 % of those that passed. After the fix, qualified persons are 87.2 % at least 0.75 visible and 4.7 % below 0.5 (§6.4).

## 9. Parameter decisions (re-adjudicated on the quality-v2 measurement)

| Parameter | Current | Evidence (quality-v2, 1080p) | Decision | Final |
|---|---|---|---|---|
| `confidenceFloor` | 0.5 | 20.2 % of candidates fall below it: ByteTrack's second-stage association of low-confidence boxes (p10 confidence 0.17). The pass rate is 77 % for persons and 85 % for vehicles. It now also sets which competing detections count as occluders, and that is what fixed F1 (occlusion pass 93.5 %). It is bounded above by activation 0.7. A change moves both roles, and nothing measured asks for one. | Retain | 0.5 |
| `sharpnessFloor` | 0.05 | Now the binding floor: pass rate 71.2 % (MOT17-02 54.6 %, persons 63.8 %). It is involved in 6 of the 9 fallback Tracks, and is the only blocker in 4. The reviewed crops of those Tracks are motion-blurred or low-texture, which is the quality intent, and qualified person evidence is 87.2 % at least 0.75 visible. The measure is per-pixel gradient energy, so it is scale- and texture-dependent: sharpness-failing person candidates are *larger* (median area 0.028 against 0.0096). Lowering the floor would admit the blurred near-camera crops, not fix that dependence. That is a scorer question (§10). | Retain | 0.05 |
| `edgeMarginFloor` | 0.005 | Pass rate 85.3 % (5.4 px vertically, 9.6 px horizontally at 1080p). The failures are boxes at the frame border, which is real truncation. 4 of the 9 fallback Tracks are MOT17-13 subjects at the border in every frame (4–46 candidates). | Retain | 0.005 |
| `occlusionIouCeiling` | 0.30 | Under quality-v2 it blocks 6.5 % of candidates. Blocked persons are the genuinely occluded ones (GT median visibility 0.45; 51.9 % under half visible). The vehicle residue from credible same-object boxes (170 candidates) costs no vehicle Track its qualified Representative. It was not tuned around F1 and needs no change now. | Retain | 0.30 |
| `occlusionPenaltyWeight` | 0.0 | Selection equals quality. A positive weight would be a new ordering design, and nothing measured asks for one. | Retain | 0.0 |
| `replaceEpsilon` | 0.02 | Re-encodes median 2, mean 3.8 and max 14 per Track (a steadily approaching vehicle). That is 400 encodes for 8,284 candidates, every one at ladder step 0: bounded CPU, with no oscillation. A larger ε would trade the best frame for fewer encodes, and nothing measured asks for it. | Retain | 0.02 |
| `nearViewGrowth` | 0.25 | NearView on 51 of 54 qualified Tracks (94.4 %), with 1 resolve drop in 52 and no growth thrash. | Retain | 0.25 |
| `earlyWindowMs` | 3000 | EarlyDiverse on 23 of 54 qualified Tracks. Of the 31 without it, 10 have < 1 s of qualified frames in the window and 1 has none. The rest are limited by the required separation from the Representative / NearView, which in 3.5-s median Tracks are often themselves early. Widening the window would move "early" toward "middle". | Retain | 3000 |
| `lateRefreshIntervalMs` | 5000 | LateDiverse on 16 of 54 qualified Tracks. Of the 38 without it, 15 Tracks last < 2 s and 10 have < 1 s of qualified frames in total. The interval only limits *refreshing* a holder, never the first fill. | Retain | 5000 |
| `minSeparationMs` | 1000 | It limits Early/Late on short qualified spans (10 of 54 qualified Tracks span < 1 s). Shrinking it would admit views within a second of each other, near-duplicates in these scenes. | Retain | 1000 |
| `duplicateWindowMs` / `duplicateIouThreshold` | 500 / 0.85 | 1 NearView resolve drop in 52, and no other resolve drop. | Retain | 500 / 0.85 |
| Encoder and quota | fixed by ADR-013 §5 | 0 cap refusals; every crop admitted at ladder step 0; 875 KB of crops against 1 GiB. | Not tunable | — |

Unlike the quality-v1 adjudication, the role parameters are now judged on 4,586 qualified candidates in 54 Tracks, with 51 NearViews, 23 EarlyDiverse and 16 LateDiverse. They are no longer provisional.

## 10. Conclusion

- **Real-clip gate: satisfied.** The C1 scripted corpus and two real benchmark clips (MOT17-02-FRCNN, MOT17-13-FRCNN at 1920×1080) were measured through the production detector, tracker and Evidence Set path. After the F1 fix, the measurement was re-run from scratch on the final implementation.
- **F1: fixed** as scorer `quality-v2` (ADR-013 §4 occlusion-proxy amendment, accepted 2026-09-24):
  - fallback Representatives fell from 58.7 % to 14.3 %;
  - vehicles went from 14 of 15 fallbacks to 0;
  - qualified candidates rose from 4.0 % to 55.4 %;
  - role coverage roughly tripled.
- **Defaults: all retained after re-adjudication.** Real-world Development measurement completed; no parameter change is justified by the measured corpus. The profile changed only in `scorerVersion`, so the SHA is now `503225be…23fb`. The qualification record is rebound and every gate is `pending`; no gate held evidence, so none was invalidated.
- **E8 two-tier behaviour: confirmed on real footage.**
  - Every Track has a Representative.
  - No fallback remains where a qualified candidate existed.
  - Supplemental roles are qualified-only, and no fallback relaxed any floor.
- **Residual risks** (for S1.4; none blocks S1.2c):
  1. **Sharpness is scale- and texture-dependent.** It is per-pixel gradient energy, so large near-camera and dark-clothed subjects score low. It is involved in 6 of the 9 remaining fallbacks. A normalised sharpness would be a future scorer version.
  2. **Credible cross-class duplicates.** Same-object `car` / `truck` boxes both at or above `confidenceFloor` still block 6.1 % of vehicle candidates, though no vehicle Track loses its qualified Representative.
  3. **Sub-floor real occluders.** A real occluder seen only below `confidenceFloor` no longer disqualifies a frame (the accepted F1 trade-off).
  4. **NearView resolve drop.** It is measured at 1 in 52, and should be re-measured at volume.
  5. **Not claimed:** admission at volume, peak RSS and staging at scale, and GPU. Those belong to S1.4.
