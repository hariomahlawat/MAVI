# Evidence selector parameter note (S1.2c)

**Status:** Partial. Scripted corpus measured; real Development clips **not yet measured**. The profile defaults are unchanged, and this note does not qualify anything.
**Date:** 2026-09-24
**Asked for by:** S1.2 implementation plan §5 ("before S1.2c merges, record a measurement note over the C1 scripted corpus and ≥ 2 real Development clips … adjust defaults in the same PR").
**Profile measured:** `src/vision/config/pipelines/phase1-detection-tracking-v1.json`, schema 1.1, `profileVersion` 1.2.0-candidate, SHA-256 `47560e0e2f5d9c8c7cb74d990ea11515bc31c7d4a9a30f6f624949aeb7213eba`. The measurement ran on the preceding revision (`9eb642f8…`). That revision differs only in `selectorVersion` (`evidence-selector-v1` → `evidence-selector-v1-two-tier`), and every numeric value and every behaviour is identical. The qualification record `models/qualifications/rtmdet-m-coco-phase1-v1.json` binds this SHA and stays `pending`.

## 1. What was measured and how

`tools/vision/dev/measure_evidence_parameters.py` (a Development tool, not a runtime component) generates the three C1 scripted-corpus videos with ffmpeg (`tools/vision/dev/scripted_corpus.py`). It runs each video through the real `VideoProcessor` with the shipped profile's evidence policy, the real `QualityV1Scorer` and the real `JpegLadderEncoder`. Only detection and tracking are scripted: they report the box ffmpeg drew on each frame, as `fixture_worker_harness.py` does. Reproduce from the repository root:

```
PYTHONPATH=src/vision python tools/vision/dev/measure_evidence_parameters.py <work-dir>
```

Host: Linux x86_64, Python 3.13, Pillow 11.3.0, PyAV 16.1.0, system ffmpeg. Every video is 640×360 at 25 fps, with a 40×80 white box on a 0x202020 matte and detections on frames 25–274 (250 per Track).

## 2. Results (one confirmed Track per video)

| Scenario | Sharpness min / median / max | Area | Edge margin min / median / max | Frames passing: confidence / sharpness / edge / occlusion / **all** | Roles filled | Encodes per Track |
|---|---|---|---|---|---|---|
| line-crossing | 0.000 / 0.000 / 0.0219 | 0.0139 | 0.000 / 0.031 / 0.389 | 100 % / **0 %** / 52 % / 100 % / **0 %** | Representative only (fallback, frame 40) | 5 |
| zone-dwell-exit | 0.0219 / 0.0219 / 0.0226 | 0.0139 | 0.069 / 0.389 / 0.389 | 100 % / **0 %** / 100 % / 100 % / **0 %** | Representative only (fallback, frame 29) | 3 |
| stationary-then-depart | 0.0219 / 0.0219 / 0.0222 | 0.0139 | 0.069 / 0.269 / 0.389 | 100 % / **0 %** / 100 % / 100 % / **0 %** | Representative only (fallback, frame 25) | 1 |

Crops were 701–789 bytes at the first ladder step. Nothing was omitted by admission.

## 3. Reading

- **The corpus's box is featureless by construction.** Sharpness is the mean absolute grey gradient of the crop divided by 64, and a uniform box yields almost none. No frame reaches the 0.05 floor, so no frame qualifies and no supplemental role is ever filled. This is a property of the synthetic scene, not evidence that 0.05 is too high for real subjects.
- **The strict ADR-013 §4 rule would fail all three jobs.** With no qualified frame there is no qualified Representative, and plan §4.2 fails the attempt (`evidence_representative_missing`). The worker instead keeps a fallback Representative (the two-tier rule, E8 in plan §16.2, accepted by the owner on 2026-09-24 as the ADR-013 §4 amendment). **Fallback-Representative rate on this corpus: 3 of 3 Tracks (100 %).** A fallback Representative is not qualified evidence, and no supplemental role was filled. These videos are what the scripted-corpus workflow and the fixture harness process.
- **Edge margin works as intended.** In line-crossing the box runs along the top edge from frame 155 (margin 0): 48 % of its frames fail the edge floor, and the textured variant of the same motion (`test_evidence_scripted_corpus.py`) stops qualifying there.
- **Encodes stay small.** Encodes are 1–5 per Track over 250 frames here, and 5–7 with all four roles in the textured variant. The ε and hysteresis rules bound re-encoding, not Track length.
- **Area is constant** (the box never changes size), so NearView growth was not exercised by the real videos; the selector tests cover it.

## 4. Defaults

No default is changed. The corpus cannot justify tuning: lowering `sharpnessFloor` until a flat synthetic box qualifies would tune to an artificial scene. Every other floor behaved as designed.

## 5. Still open (blocks the plan §5 merge condition)

- **≥ 2 real Development clips — not measured; this blocks merge.** See §6.
- **Admission rates, peak RSS and staging bytes at volume** belong to S1.4 and are not claimed here.

## 6. Real-clip measurement (prepared; blocked by network access, 2026-09-24)

**Planned corpus.** Public MOTChallenge benchmark sequences, used for qualification only. They are licensed CC BY-NC-SA 3.0 and are never committed or redistributed.

| Sequence | Character | Intended source |
|---|---|---|
| MOT17-02-FRCNN | Crowded pedestrian scene, static camera, 1920×1080, 30 fps, 600 frames | `https://motchallenge.net/sequenceVideos/MOT17-02-FRCNN-raw.webm` |
| MOT17-13-FRCNN | Busy road, moving (bus) camera, 1920×1080, 25 fps, 750 frames | `https://motchallenge.net/sequenceVideos/MOT17-13-FRCNN-raw.webm` |

The intended sources could not be fetched, so no file hash, size or media metadata is recorded yet. The frame counts and rates above are the benchmark's published values, not measurements.

**Harness.** `tools/vision/dev/measure_evidence_real_clips.py` (Development qualification tooling, not a runtime component).
- It builds the runtime exactly as the worker does: `WorkerSettings` → `RuntimeSupervisor` (it refuses to run unless READY) → the vision execution lane.
- It composes each clip exactly as `ProductionVisionProcessor` does: `RTMDetDetector` → `ByteTrackTracker` → `VideoProcessor(evidence_policy=profile.evidence)`.
- The production scorer and encoder are wrapped only to record what they compute. `EvidenceSelector.observe` / `resolve` are tapped read-only, to record the Representative tier after each frame and the holders before resolve.
- `test_measure_evidence_real_clips.py` proves the instrumented run's Evidence Sets are identical to the plain production processor's: the same Tracks, roles, ranks, frames, scores and crop bytes. It runs in the Task 10 qualified job.
- Outputs:
  - `summary.json`: runtime provenance; per clip, the SHA-256, size, codec, resolution, fps and duration, plus processing time and peak RSS; per Track, candidate and qualified frames, Representative tier and fallback→qualified transition, roles held before and after resolve, encodes, unadmissible counts and crop sizes; per clip and combined, the min/p10/p25/p50/p75/p90/max of sharpness, area, edge margin, confidence and occlusion, the per-floor and all-floor pass rates, fallback rate by Track and class, role coverage, NearView resolve drops and encode statistics.
  - `candidates.csv.gz`: scalar per-candidate rows, no pixels.
  - Both stay local and are not committed.

**Blocker (exact).** This session's egress policy returned 403 for:
- `motchallenge.net`: the clips;
- `download.pytorch.org`: the qualified `torch==2.6.0` / `torchvision==0.21.0` CPU wheels;
- `download.openmmlab.com`: the RTMDet-m checkpoint `rtmdet_m_8xb32-300e_coco_20220719_112220-229f527c.pth`, SHA-256 `229f527c…792b`.

These are the same sources the Task 10 qualified-runtime job uses. Runtime and model packs are not in Git by design, so the qualified runtime cannot be established here without them. Nothing was substituted: no other runtime, no fixture detector, and no ground-truth boxes.

**To complete the gate.**
1. On a host with the qualified Development runtime and the RTMDet Model Pack, download both clips.
2. Record each clip's SHA-256, size and media metadata (the harness also records them).
3. If the WebM files are not accepted by the MAVI import path, convert them locally with the runtime's FFmpeg without rescaling or changing the frame rate, and record the command and both hashes.
4. Run from `src/vision`, with the worker settings in the environment:
   `python ../../tools/vision/dev/measure_evidence_real_clips.py <out> MOT17-02-FRCNN=<file> MOT17-13-FRCNN=<file>`
5. Complete this section from `summary.json`, and adjudicate each parameter as in §4. Retain the defaults unless the evidence shows over-rejection, churn or role starvation. Any change re-derives the profile SHA and keeps the qualification gates `pending`.

