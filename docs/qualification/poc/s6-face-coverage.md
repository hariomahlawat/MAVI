# PoC S6: usable-face coverage on the demo corpus (register C5A.2)

**Protocol:** `s6-face-coverage-v1`, frozen in `tools/poc/faces_coverage.py` before it ran (2026-10-29).
**Evidence class:** Development (ADR-020). No ground truth: detector output only.
**Raw outputs:** `E:\MAVI-Controlled\PoC\S6\coverage\`. `SHA256SUMS` SHA-256 is `fdce72ad67402f77b1aec2adbf1694f86e32e6143e8808f652279730e55a66b1`.

## Question

This is the roadmap entry decision for Stage 5A. The `faces` role reads the Person Evidence Set. For what share of Person Tracks does that set contain a face large enough to embed?

## Method

| | |
|---|---|
| Corpus | The 12 S2 demo clips, one Completed ProcessingRun each, in the Development database `mavi_poc_s2_20261029` (S2 evidence, B4). 9 clips have Person Tracks. |
| Unit | Person Track (110 in total). |
| Input | Every accepted `EvidenceCrop` of the Track (351 crops), each checked against its recorded size and SHA-256 (0 mismatches). This is exactly the set a post-Track role leases (ADR-013 §4). |
| Detector | YuNet `face_detection_yunet_2026may.onnx` (opencv_zoo `48b10fa5`, MIT; SHA-256 `ebafce4e…f0f0`). It runs through the role's own decoder, `mavi_vision.faces.detector`, on ONNX Runtime 1.31.0 CPU. Crops are padded to multiples of 32, never resized. NMS IoU is 0.3 and top-k 5000. |
| Decoder check | On the 137 MEVA crops at score ≥ 0.6, the decoder equals OpenCV 4.12 `FaceDetectorYN` (2023mar graph): 43 of 43 faces, maximum difference 3e-5. |
| Usable face (primary) | Score ≥ **0.9** (the publisher's default) and a box shorter side ≥ **32 px** in source pixels. Below about 32 px, recognition accuracy collapses on surveillance-resolution benchmarks. |
| Primary number | Per clip, the Person Tracks with at least one usable face, divided by all Person Tracks. |

## Result (primary, frozen)

**2 of 110 Person Tracks (1.8 %) have a usable face. Both are in s2-12.**

| Clip | Person Tracks | Crops | Median crop shorter side (px) | Any face at 0.9 | Usable (≥ 32 px, 0.9) |
|---|---:|---:|---:|---:|---:|
| s2-01 Düsseldorf junction | 36 | 118 | 41.5 | 0 | 0 |
| s2-02 Sofia junction | 29 | 90 | 62 | 1 | 0 |
| s2-06 Beynost level crossing | 1 | 3 | 589 | 0 | 0 |
| s2-07 Shibuya crossing | 2 | 4 | 24.5 | 0 | 0 |
| s2-08 MEVA bus stop | 3 | 11 | 159 | 0 | 0 |
| s2-09 MEVA parking lot | 2 | 4 | 52.5 | 0 | 0 |
| s2-10 MEVA cafe lobby | 8 | 30 | 104.5 | 0 | 0 |
| s2-11 MEVA school hall | 20 | 64 | 36 | 0 | 0 |
| s2-12 MEVA stairwell | 9 | 28 | 232.5 | 2 | **2** |
| s2-03, s2-04, s2-05 | 0 | 0 | — | — | — |

The usable faces at 0.9 have shorter sides of 48.2, 51.4, 52.1 and 52.7 px.

### Sensitivity (predeclared, reported, not decided on)

Person Tracks with a face at or above the shorter side:

| Score | ≥ 16 px | ≥ 24 px | ≥ 32 px | ≥ 48 px | ≥ 64 px |
|---|---:|---:|---:|---:|---:|
| 0.9 | 3 | 3 | 2 | 2 | 0 |
| 0.6 | 33 | 23 | 15 | 6 | 1 |

## Post-hoc diagnostic (hypothesis only, not the result)

**Why look.** A one-off visual look at detections of ≥ 24 px checked whether the publisher's 0.9 threshold rejects true faces. It was diagnostic only. Nothing was labelled, and the temporary contact sheet was deleted afterwards.

**What it showed:**
- Every detection scoring 0.85–0.89 looked like a true face. These were in s2-01, s2-02, s2-08 and s2-12.
- Detections scoring 0.6–0.8 included backs of heads (s2-06, s2-08) and a dark region (s2-10).

**Coverage at intermediate thresholds,** counted from the same raw detections:

| Score | ≥ 24 px | ≥ 32 px | Clips with any at ≥ 32 px |
|---|---:|---:|---|
| 0.8 | 15 | 8 | s2-02 2/29, s2-12 6/9 |
| 0.7 | 18 | 11 | s2-02 2/29, s2-08 2/3, s2-12 7/9 |

A 0.8 threshold is a hypothesis from this look. It is not evidence. Adopting it needs a run on clips this look did not use, frozen before that run.

## Reading

- **Faces are rare.** Usable faces are rare in this corpus. Only the close stairwell camera (s2-12) shows faces of embeddable size. The traffic clips show faces of 25–55 px on a few pedestrians, but those are public-space Commons clips and are not opted in (ADR-022 §3).
- **No cross-camera demonstration.** The other MEVA face clips, the cafe lobby s2-10 and the school hall s2-11, have no usable face at the frozen threshold. A cross-camera "previous appearances" face demonstration is not possible on this corpus at any threshold. At 0.8, s2-10 adds at most one Track of 24–31 px.
- **Unknown dominates.** It is the honest majority result.

**Owner decision S6-1** (coverage and demonstration scope) is raised with the coordinator. The options and recommendation are in the S6 report.
