# Evidence selector parameter note (S1.2c)

**Status:** Partial. Scripted corpus measured; real Development clips **not yet measured**. The profile defaults are unchanged, and this note does not qualify anything.
**Date:** 2026-09-24
**Asked for by:** S1.2 implementation plan §5 ("before S1.2c merges, record a measurement note over the C1 scripted corpus and ≥ 2 real Development clips … adjust defaults in the same PR").
**Profile measured:** `src/vision/config/pipelines/phase1-detection-tracking-v1.json`, schema 1.1, `profileVersion` 1.2.0-candidate, SHA-256 `9eb642f85c9c5091e56d0c8acda7efedfa21411f264a19297e56fa10f48f27c7`. The qualification record `models/qualifications/rtmdet-m-coco-phase1-v1.json` binds this SHA and stays `pending`.

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
- **The strict ADR-013 §4 rule would fail all three jobs.** With no qualified frame there is no qualified Representative, and plan §4.2 fails the attempt (`evidence_representative_missing`). The worker instead keeps a fallback Representative (the proposed two-tier amendment, E8 in plan §16.2). These videos are what the scripted-corpus workflow and the fixture harness process.
- **Edge margin works as intended.** In line-crossing the box runs along the top edge from frame 155 (margin 0): 48 % of its frames fail the edge floor, and the textured variant of the same motion (`test_evidence_scripted_corpus.py`) stops qualifying there.
- **Encodes stay small.** Encodes are 1–5 per Track over 250 frames here, and 5–7 with all four roles in the textured variant. The ε and hysteresis rules bound re-encoding, not Track length.
- **Area is constant** (the box never changes size), so NearView growth was not exercised by the real videos; the selector tests cover it.

## 4. Defaults

No default is changed. The corpus cannot justify tuning: lowering `sharpnessFloor` until a flat synthetic box qualifies would tune to an artificial scene. Every other floor behaved as designed.

## 5. Still open (blocks the plan §5 merge condition)

- **≥ 2 real Development clips.** These were not available in this environment and need the qualified detector. Record per confirmed Track: sharpness, area and edge-margin distributions; the share of frames passing each floor; roles filled; encodes; and how many Tracks use a fallback Representative. Then confirm or adjust `sharpnessFloor`, `edgeMarginFloor`, `replaceEpsilon`, `nearViewGrowth`, `earlyWindowMs` and `lateRefreshIntervalMs` in the same PR. Any change alters the profile SHA and the qualification record's `pipelineProfileSha256`, which stays `pending`.
- **Admission rates, peak RSS and staging bytes at volume** belong to S1.4 and are not claimed here.
