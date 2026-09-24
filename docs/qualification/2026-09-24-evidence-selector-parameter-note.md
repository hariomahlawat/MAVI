# Evidence selector parameter note (S1.2c)

**Status:** Complete. The C1 scripted corpus and two real benchmark clips (MOT17-02-FRCNN, MOT17-13-FRCNN) were measured through the production RTMDet → ByteTrack → Evidence Set path, on a runtime built from the repository's qualified `linux-x86_64-cpu` definition (`mmcv` rebuilt locally from its pinned source; §4). **No selector parameter change is justified under the current scorer. Every default is retained**, so the profile bytes, `pipelineProfileSha256` and the qualification record are unchanged. The measurement also found one material issue that is outside the parameter space: the occlusion proxy's input set (finding **F1**, §7). It needs an owner decision (§8). This note qualifies nothing.
**Date:** 2026-09-24
**Asked for by:** S1.2 implementation plan §5 ("before S1.2c merges, record a measurement note over the C1 scripted corpus and ≥ 2 real Development clips … adjust defaults in the same PR").
**Profile measured:** `src/vision/config/pipelines/phase1-detection-tracking-v1.json`, schema 1.1, `profileVersion` 1.2.0-candidate, SHA-256 `47560e0e2f5d9c8c7cb74d990ea11515bc31c7d4a9a30f6f624949aeb7213eba`. The real clips ran on this exact profile. The scripted corpus ran on the preceding revision (`9eb642f8…`), which differs only in `selectorVersion` (`evidence-selector-v1` → `evidence-selector-v1-two-tier`); every numeric value and behaviour is identical. The qualification record `models/qualifications/rtmdet-m-coco-phase1-v1.json` binds this SHA and stays `pending`.

## 1. Purpose

This is the engineering measurement that plan §5 requires before S1.2c merges. It checks that the initial selector defaults behave as intended on the real detector and tracker output: no systematic over-rejection, under-filtering, encode churn or role starvation. It is **not** Stage-2 model-quality qualification, a performance qualification or an S1.4 acceptance row. Two public clips are a calibration corpus, not a tuning target. Where values performed similarly, the existing value is kept.

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
| Python | 3.12.14 CPython, build `main, Aug 13 2026 02:47:42`, GCC 13.3.0. This is the `actions/python-versions` release `3.12.14-31661455385` (`python-3.12.14-linux-24.04-x64.tar.gz`, SHA-256 `5a031682…1e622257fff`), the interpreter the runtime profile's `pythonIdentity` pins. The supervisor verified it. |
| Packages | `linux-x86_64-cpu.lock`: all 60 entries except `mmcv` installed with `pip --require-hashes --no-deps --only-binary=:all:` (PyPI and `download.pytorch.org/whl/cpu`) |
| `mmcv` 2.1.0 | Built from the pinned source commit `57c4e25e06e2d4f8a9357c84bcd24089a284dc88` against the locked torch (`MMCV_WITH_OPS=1`), as the Task 10 job builds it. **Deviation:** the local wheel's SHA-256 is `dfc6313a…d6d4af`, not the lock's `4fbeb417…`, because a native build is not byte-reproducible. Source, version and ABI are the same, and the supervisor's semantic-graph check passed. |
| Semantic graph | torch 2.6.0+cpu, torchvision 0.21.0+cpu, mmcv 2.1.0, mmengine 0.10.7, mmdet 3.3.0, trackers 2.6.0, supervision 0.30.2, scipy 1.18.1, numpy 2.5.3, opencv 5.0.0 (opencv-python 5.0.0.93), av 16.1.0, pillow 11.3.0 |
| Model Pack | `rtmdet-m-coco-phase1` 1.0.0, manifest SHA-256 `0049875d…8d7d`. Checkpoint `rtmdet_m_8xb32-300e_coco_20220719_112220-229f527c.pth` from `download.openmmlab.com`, SHA-256 `229f527ca88498e8894a778a62a878a322b4a3ea2cae09ea537d34b7e907792b` (verified). The resolved config was generated with `tools/vision/resolve_mmdet_config.py` from MMDetection commit `44ebd17b…ab64a`; its SHA-256 `377d9f57…c5ee3` equals the manifest's. |
| Runtime profile | `mmdetection-phase1-v1`, SHA-256 `b3c59ac4…6c873`, variant `linux-x86_64-cpu` |
| Qualification | `rtmdet-m-coco-phase1-v1`, record SHA-256 `911c3fe4…668d`, `verificationStatus` `unverified`, every gate `pending` (Development) |
| Pipeline | profile `phase1-detection-tracking-v1` 1.2.0-candidate, SHA-256 `47560e0e…3eba`. Selector `evidence-selector-v1-two-tier`, scorer `quality-v1`, encoder `evidence-jpeg-ladder-v1`. Tracker: ByteTrack (`trackers` 2.6.0), activation 0.7, high 0.6, IoU 0.1, 2 frames, lost buffer 1.0 s at 30 fps reference. Frame policy every-frame. Detector inference floor 0.05. |
| Device | configured `cpu` (`MAVI_DEVICE_POLICY=cpu`, Development mode); actual `cpu` |
| Supervisor | `RuntimeSupervisor` from `WorkerSettings` reached READY. The qualified ByteTrack (10) and production-composition (1) suites and the harness suite (3) passed on this runtime. |
| Code | Primary corpus measured at commit `73e0315`, supplementary at `9917817` (PR #79 branch; the harness only differs by recorded columns). The provenance's `mavi_commit` records it. The primary corpus was also measured at `9917817`, and every statistic was identical. |

## 5. Method

`tools/vision/dev/measure_evidence_real_clips.py` is Development qualification tooling, not a runtime component. It builds the runtime as the worker does: `WorkerSettings` → `RuntimeSupervisor`, and it refuses to run unless the supervisor is READY. Each clip runs on the vision execution lane through exactly the `ProductionVisionProcessor` composition: `RTMDetDetector` → `ByteTrackTracker` → `VideoProcessor(evidence_policy=profile.evidence)`. That means real decode, real detections, real Tracks, the production `QualityV1Scorer`, the two-tier `EvidenceSelector`, the `JpegLadderEncoder`, retirement, staging and run-level admission.

The instrumentation observes and never decides:
- The scorer and encoder are wrapped to record the scalars they compute.
- `EvidenceSelector.observe` / `resolve` are tapped read-only, to record the Representative tier after each frame, the holders before `resolve()`, and why a held NearView was dropped (evaluated with the selector's own rule).
- Diagnostic columns attribute the occlusion proxy (the confidence and class of the box that produced its maximum, and the maximum IoU over boxes at or above `confidenceFloor`). The selector always used the production value.
- No pixel or selector is retained, and per-candidate rows are scalars.
- `test_measure_evidence_real_clips.py` proves that the instrumented run's Evidence Sets are identical to the plain production processor's (Tracks, roles, ranks, frames, scores and crop bytes). It runs in the Task 10 qualified job.
- Re-runs as the harness gained columns reproduced every count, rate and encode statistic exactly: the primary corpus at `9917817` and `73e0315` (both `summary.json` files compared), and the supplementary corpus at `5c005b8` and `9917817` (printed summaries compared).

The statistics describe the Tracks the tracker confirmed, not benchmark subjects: 21 confirmed Tracks in MOT17-02 against 62 annotated pedestrians. Percentiles are nearest-rank, at index `round(q·(n−1))` of the sorted values. "Candidate" means one Track candidate in one frame, over every confirmed Track; no Track is excluded. Rates are over candidates unless stated per Track. Reproduce from `src/vision`, with the worker settings in the environment:

```
PYTHONPATH=. python ../../tools/vision/dev/measure_evidence_real_clips.py <out> MOT17-02-FRCNN=<mp4> MOT17-13-FRCNN=<mp4>
```

The outputs (`summary.json` of about 84 KB, `candidates.csv.gz` of about 880 KB, and `<out>/staging`: the run's staged Evidence crops and trajectories, 157 files) stay local. The staging directory holds crops of benchmark subjects and is deleted after review. Peak RSS and processing time include the harness's own overhead (one scalar row per candidate and the diagnostics).

## 6. Results (primary corpus, 1920×1080)

### 6.1 Volume

| | MOT17-02 | MOT17-13 | Combined |
|---|---|---|---|
| Frames processed | 600 | 750 | 1,350 |
| Confirmed Tracks (person / vehicle) | 21 (21 / 0) | 42 (27 / 15) | 63 (48 / 15) |
| Candidates | 3,875 | 4,409 | 8,284 |
| Candidates per Track, min / p50 / max | 21 / 135 / 571 | 4 / 71 / 431 | 4 / 99 / 571 |
| Track duration, p10 / p50 / p90 | 1.5 / 4.5 / 14.0 s | 0.8 / 2.8 / 8.3 s | 0.8 / 3.5 / 12.7 s |

### 6.2 Distributions (all candidates)

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
| Occlusion proxy (IoU) | 02 | 0.001 | 0.262 | 0.428 | 0.557 | 0.617 | 0.641 | 1.0 |
| | 13 | 0 | 0.482 | 0.619 | 0.934 | 0.970 | 0.987 | 1.0 |
| | all | 0 | 0.335 | 0.514 | 0.621 | 0.942 | 0.977 | 1.0 |
| *Occlusion over boxes ≥ `confidenceFloor` (diagnostic)* | all | 0 | 0 | 0 | 0.018 | 0.110 | 0.234 | 0.998 |

Sharpness by class, p10 / p25 / p50: person 0.028 / 0.042 / 0.060, vehicle 0.045 / 0.064 / 0.103.

### 6.3 Floor pass rates (share of candidates)

| Floor (default) | MOT17-02 | MOT17-13 | Combined | Person | Vehicle |
|---|---|---|---|---|---|
| confidence ≥ 0.5 | 74.6 % | 84.4 % | 79.8 % | 77.3 % | 84.7 % |
| sharpness ≥ 0.05 | 54.6 % | 85.7 % | 71.2 % | 63.8 % | 85.6 % |
| edge margin ≥ 0.005 | 81.0 % | 89.1 % | 85.3 % | 81.3 % | 92.9 % |
| occlusion < 0.30 | **12.3 %** | **4.7 %** | **8.3 %** | 12.3 % | **0.5 %** |
| **all floors (qualified)** | **4.7 %** | **3.4 %** | **4.0 %** | 6.0 % | **0.04 %** (1 of 2,801) |
| *confidence + sharpness + edge only (diagnostic)* | 40.3 % | 69.5 % | 55.8 % | | |
| *all floors, occlusion over boxes ≥ 0.5 (diagnostic)* | 39.5 % | 69.3 % | 55.4 % | | |

### 6.4 Two-tier Representative and roles (per Track)

| | MOT17-02 | MOT17-13 | Combined |
|---|---|---|---|
| Tracks with ≥ 1 qualified candidate | 12 / 21 | 14 / 42 | 26 / 63 (41.3 %) |
| **Fallback Representative** | 9 / 21 (42.9 %) | 28 / 42 (66.7 %) | **37 / 63 (58.7 %)** |
| Fallback by class | person 9/21 | person 14/27, vehicle 14/15 | person 23/48 (47.9 %), vehicle 14/15 (93.3 %) |
| Fallback → qualified transitions | 12 | 12 | 24 (the other 2 qualified Tracks were qualified from their first candidate) |
| Tracks with no admissible Representative | 0 | 0 | 0 (both jobs completed) |
| Fallback Tracks that had a qualified candidate | 0 | 0 | 0 |
| Supplemental holders that are not qualified | 0 | 0 | 0 |
| Fallback Tracks with any supplemental role | 0 | 0 | 0 |
| NearView | 12 (57.1 %) | 7 (16.7 %) | 19 (30.2 %); 19/26 (73.1 %) of qualified Tracks |
| EarlyDiverse | 5 (23.8 %) | 2 (4.8 %) | 7 (11.1 %); 7/26 (26.9 %) |
| LateDiverse | 4 (19.0 %) | 1 (2.4 %) | 5 (7.9 %); 5/26 (19.2 %) |
| All four roles | 1 (4.8 %) | 1 (2.4 %) | 2 (3.2 %); 2/26 (7.7 %) |

The E8 behaviour holds on real footage:
- Every Track kept a Representative.
- No fallback was left on a Track that had a qualified candidate (24 fallback → qualified transitions). Displacement by the *first* admissible qualified candidate follows from the selector rule, with 0 encode refusals. The harness records the tier change, not its frame.
- No supplemental role was ever filled by, or relaxed for, an unqualified frame.
- 37 of 63 real Representatives are fallbacks, so `role == representative` visibly carries no qualification signal, as ADR-013 §4 (amended) states.

Among the 37 fallback Tracks, the failure rate per floor over their 4,185 candidates was confidence 25.3 %, sharpness 31.5 %, edge 20.6 % and occlusion **96.8 %**. **28 of the 37** had a candidate that passed confidence, sharpness and edge margin and failed only an occlusion maximum produced by boxes below `confidenceFloor` (finding F1).

### 6.5 Encodes, caps, NearView resolve drops, crops, runtime

- **Encode attempts per Track:** mean 3.59, median 2, max 14. The 14-attempt Track is `person-000010` in MOT17-02: 284 candidates and all four roles filled. That is 226 attempts for 8,284 candidates. **Re-encodes** (attempts beyond the final holders) were mean 2.08, median 1 and max 11.
- **JPEG cap refusals:** 0 (Representative 64 KiB, supplemental 160 KiB). Unadmissible-by-role: 0. Admission omitted nothing: 94 crops (63 + 19 + 7 + 5), 580,314 B, against the 1 GiB quota.
- **NearView dropped at `resolve()`:** 0 of 19 held at 1080p. In the supplementary run, 1 of 23 was dropped (4.3 %), as a near-duplicate of a later Representative. Over both corpora that is **1 of 42 (2.4 %)**. That Track still kept its Representative. The plan §20 residual is real, but it is not material on this corpus, and it stays with S1.4.
- **Encoded crops (bytes, p10 / p50 / max):** Representative 1,583 / 3,760 / 31,001; NearView 2,680 / 4,731 / 14,613; EarlyDiverse 1,937 / 5,562 / 11,818; LateDiverse 2,418 / 4,942 / 12,363. **Long edge in px (p10 / p50 / max):** Representative 76 / 203 / 700; NearView 147 / 276 / 535. Every crop was admitted at ladder step 0, well under its cap.
- **Runtime (engineering facts, not a performance qualification).** CPU on 4 vCPU, run at `9917817`; the `73e0315` re-run took 182.7 s and 219.6 s:
  - MOT17-02: 191.3 s for 20.0 s of video, 0.10× real time (3.1 fps).
  - MOT17-13: 224.6 s for 30.0 s, 0.13× (3.3 fps).
  - The whole run took 7 min 04 s including model load.
  - Peak RSS was 767–939 MiB across runs (process `ru_maxrss`, harness included). Staging was 0.73 MiB apparent across 157 files (1.1 MiB on disk).
  - No errors. Only upstream warnings: `FutureWarning` for `torch.cuda.amp.autocast`, `UserWarning` for `torch.meshgrid`, and MMEngine's notice that `data_preprocessor.mean/std` in the checkpoint are unused.

### 6.6 Supplementary: the official 960×540 VP9 previews

Same runtime and code. 56 Tracks, 8,182 candidates.
- **Pass rates:** confidence 76.8 %, sharpness 91.7 %, edge 85.5 %, occlusion **7.0 %**, all floors 5.1 %.
- **Fallback Representatives:** 27 / 56 (48.2 %), with 26 fallback → qualified transitions.
- **Role coverage:** NearView 39.3 %, EarlyDiverse 8.9 %, LateDiverse 14.3 %, all four 5.4 %.
- **Encodes:** mean 3.86, median 2.5, max 14. 0 cap refusals.
- **Occlusion:** 93.4 % of occlusion rejections are due only to sub-floor boxes.
- **Run time:** 168 s and 196 s.

Sharpness is resolution-dependent: the median is 0.113 at 540p against 0.066 at 1080p, because downscaling concentrates the gradient per pixel. The occlusion finding is the same at both resolutions.

## 7. Finding F1 — the occlusion proxy counts sub-floor detections (material; not a parameter)

The proxy is the maximum IoU with **every** other detection the tracker was given (plan §4.1; ADR-013 §4: "any concurrent box"). With `detectorInferenceFloor` 0.05 and RTMDet's per-source-class NMS (IoU 0.65), those detections include:
- low-confidence duplicates and part-boxes of the same person;
- for vehicles, same-object `car` / `truck` / `bus` boxes, which all map to `vehicle`. 2,587 of 2,787 blocked vehicle candidates have a same-class occluder with IoU > 0.65 (median 0.96). Per-class NMS at 0.65 leaves such overlaps in practice only across source classes: persons exceed 0.65 against a same-class box in just 6 cases, all edge-clipped after MAVI's post-NMS clipping. That makes these boxes, in practice, duplicates of the subject.

Measured at 1080p:
- **92.9 %** of occlusion rejections (7,061 of 7,598) are due *only* to boxes below `confidenceFloor`. The median confidence of the blocking box is 0.115, and 92.6 % of blocking boxes have the candidate's own class.
- Counting only boxes at or above `confidenceFloor` would pass 93.5 % of candidates on occlusion. The all-floor rate would rise from 4.0 % to 55.4 %.
- The fallback Representatives would fall from 37 to at most 9 of 63 (assuming those candidates encode, as every candidate here did): 28 of the 37 fallback Tracks had a candidate that failed only this way.
- Vehicles qualify in 1 frame of 2,801, and 14 of 15 vehicle Tracks use a fallback.

**Ground-truth context (descriptive only).** Each candidate was matched to the best MOT17 ground-truth box of its class in the same frame (IoU ≥ 0.5; persons: classes 1, 2, 7; vehicles: 3, 5). The table shows the annotated visibility of the matched boxes:

| Candidate group (1080p) | Candidates | Matched | GT visibility p25 / p50 / p75 | Visible ≥ 0.75 | Visible < 0.5 |
|---|---|---|---|---|---|
| person, passes occlusion | 672 | 587 | 0.90 / 1.00 / 1.00 | 84.3 % | 3.4 % |
| person, blocked only by boxes < `confidenceFloor` | 4,444 | 3,613 | 0.78 / 1.00 / 1.00 | 77.8 % | 10.1 % |
| person, blocked by a box ≥ `confidenceFloor` | 367 | 235 | 0.16 / 0.45 / 1.00 | 42.1 % | 51.9 % |
| vehicle, passes occlusion | 14 | 3 | 1.00 / 1.00 / 1.00 | 3 of 3 | 0 |
| vehicle, blocked only by boxes < `confidenceFloor` | 2,617 | 2,470 | 0.90 / 1.00 / 1.00 | 87.4 % | 2.8 % |
| vehicle, blocked by a box ≥ `confidenceFloor` | 170 | 160 | 1.00 / 1.00 / 1.00 | 84.4 % | 10.6 % |

The persons the proxy rejects only because of sub-floor boxes are, in the annotation, almost as visible as those it accepts. The proxy over boxes at or above the floor isolates the genuinely occluded ones (median visibility 0.45). The trade-off of the candidate fix is visible too: 10.1 % of the sub-floor-blocked persons are under half visible, against 3.4 % of those passing today.

**Why no parameter change addresses it.** The blocking boxes are near-duplicates of the subject (IoU ≈ 0.9 for vehicles), so no `occlusionIouCeiling` separates them from real occlusion. Raising the ceiling far enough would admit genuinely occluded crowd frames and still not qualify vehicles. `confidenceFloor` and `detectorInferenceFloor` do not help either: the first applies to the candidate, not to its occluders, and the second drives ByteTrack's low-confidence association and belongs to Task 10's qualified tracking behaviour. The defect is the proxy's **input set**, which is scorer semantics frozen by ADR-013 §4. Changing it is an architecture decision (a new scorer version and an ADR-013 §4 clarification), not a selector-parameter adjustment, so this note does not make it.

**Effect if left as is.** Output stays conservative and correct:
- supplemental roles stay qualified-only, and are filled for 30 % of Tracks (NearView);
- every job completes, because of the E8 fallback;
- 59 % of Representatives are fallbacks, so the Evidence Set is fallback-heavy on crowded real scenes and nearly always fallback for vehicles.

That matters to S1.3/S1.4 and to any downstream consumer of qualified evidence.

**Candidate fix (for the owner; not implemented).** Scorer `quality-v2`: the occlusion proxy counts only other detections with `confidence ≥ confidenceFloor`. The profile would then carry `scorerVersion` `quality-v2`, the profile SHA would be re-derived, the qualification record rebound with its gates kept `pending`, and this measurement re-run on the same corpus. A same-object de-duplication rule would be a further, separate option.

## 8. Parameter decisions

| Parameter | Current | Evidence (1080p corpus unless stated) | Decision | Final |
|---|---|---|---|---|
| `confidenceFloor` | 0.5 | 20.2 % of candidates fall below it: ByteTrack's second-stage association of low-confidence boxes (p10 confidence 0.17). This is the intended filter; the pass rate is 77 % for persons and 85 % for vehicles. It is bounded above by activation 0.7. | Retain | 0.5 |
| `sharpnessFloor` | 0.05 | Pass rate 71.2 % (person 63.8 %, vehicle 85.6 %). The floor sits near the person p25 (0.042) and below the median (0.060). It rejects small, soft, distant crops in MOT17-02, which is the quality intent. It is not the binding floor under the current proxy. With F1 fixed it would become the binding floor in MOT17-02, where only 59.4 % of candidates passing the other floors (occlusion over boxes ≥ 0.5) are sharp enough; MOT17-13 is at 91.1 % and the combined corpus at 77.3 %. At 540p the pass rate is 91.7 % (resolution effect, §6.6). | Retain | 0.05 |
| `edgeMarginFloor` | 0.005 | Pass rate 85.3 % (5.4 px vertically, 9.6 px horizontally at 1080p). The failures are boxes at the frame border (edge-margin p10 ≈ 0), which is real truncation. | Retain | 0.005 |
| `occlusionIouCeiling` | 0.30 | Pass rate 8.3 %, the binding floor. 93 % of its rejections come from sub-floor boxes (F1). No ceiling value separates those near-duplicates from real occlusion. Over boxes ≥ `confidenceFloor` it would pass 93.5 %, a plausible share for crowded scenes. | Retain the value. The defect is F1's input set, and it needs an owner decision. | 0.30 |
| `occlusionPenaltyWeight` | 0.0 | Selection equals quality. F1 makes any positive weight unsafe until the proxy is fixed. | Retain | 0.0 |
| `replaceEpsilon` | 0.02 | Re-encodes median 1 and mean 2.1 per Track; 226 encodes for 8,284 candidates. The worst churn is in the fallback tier: `vehicle-000011` (99 candidates, fallback only) re-encoded 11 times and `vehicle-000013` 10 times, as approaching vehicles' scores grow. The busiest qualified Track (`person-000010`, 284 candidates, all four roles) re-encoded 10 times. That is bounded, and not material; F1 would move most of it into the qualified tier. | Retain | 0.02 |
| `nearViewGrowth` | 0.25 | NearView on 19 of 26 qualified Tracks (73 %); no growth thrash (encodes above); 0 resolve drops at 1080p. | Retain | 0.25 |
| `earlyWindowMs` | 3000 | All 26 qualified Tracks had a qualified candidate inside the window, so the window is not what starves EarlyDiverse (7/26). The selector rules leave separation from the Representative / NearView and short qualified spans as the limits; that is inferred from the code, not measured per rule. | Retain | 3000 |
| `lateRefreshIntervalMs` | 5000 | The interval only limits *refreshing* an existing LateDiverse holder. LateDiverse (5/26) is limited by the qualified span: 11 of 26 qualified Tracks span < 1 s of qualified frames. | Retain | 5000 |
| `minSeparationMs` | 1000 | It limits Early/Late on short qualified spans. Shrinking it would admit views within a second of each other, near-duplicates in these scenes. Short Tracks are expected. | Retain | 1000 |
| `duplicateWindowMs` / `duplicateIouThreshold` | 500 / 0.85 | NearView resolve drops 0/19 (1080p) and 1/23 (540p), with no other resolve drop observed. | Retain | 500 / 0.85 |
| *Caveat* | | The four floors were judged on all 8,284 candidates. The role parameters (NearView growth, windows, separation, duplicate rule) were judged on a censored sample: 331 qualified candidates in 26 Tracks, with 7 EarlyDiverse and 5 LateDiverse. Their retention is **provisional**. If F1 is fixed (option (a), §9), the whole measurement is re-run and every parameter re-adjudicated. | | |
| Encoder and quota | fixed by ADR-013 §5 | 0 cap refusals; every crop admitted at ladder step 0; 580 KB of crops against 1 GiB. | Not tunable | — |

## 9. Conclusion

- **Real-clip gate: measured.** Two real benchmark clips (MOT17-02-FRCNN, MOT17-13-FRCNN at 1920×1080) went through the production detector, tracker and Evidence Set path on the qualified runtime, plus the C1 scripted corpus and a supplementary 540p variant.
- **Defaults: retained.** Real-world Development measurement completed; no parameter change is justified by the measured corpus under the current scorer. The role-parameter retentions are provisional (§8 caveat). The profile bytes, `pipelineProfileSha256` `47560e0e…3eba` and the qualification record are unchanged, and no qualification gate was reset or earned.
- **E8 two-tier behaviour: confirmed on real footage:**
  - every Track has a Representative;
  - fallback → qualified displacement always happened when possible (24 transitions);
  - supplemental roles are qualified-only;
  - no fallback relaxed any supplemental floor.
- **NearView resolve-drop residual:** 1 of 42 held NearViews (2.4 %). Not material; it stays with S1.4.
- **Material finding F1 (§7):** the occlusion proxy's input set drives a 58.7 % fallback-Representative rate and near-zero vehicle qualification. It is not fixable by any selector parameter, and fixing it is a scorer or ADR change. **It needs an owner decision before S1.2c merges:**
  - (a) fix it in S1.2c: `quality-v2`, an ADR-013 §4 clarification, a profile rebind, and a re-measurement with every parameter re-adjudicated; or
  - (b) accept it explicitly as a recorded residual for S1.4, with the fallback-heavy real-scene behaviour documented.
- **Not claimed:** admission at volume, peak RSS and staging at scale, GPU, and any Stage-2 acceptance row. Those belong to S1.4.
