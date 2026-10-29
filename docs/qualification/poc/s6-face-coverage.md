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

## Re-measurement on the A6 clip (protocol `s6-face-coverage-v2`; owner decision D-S6-2(a))

**Protocol:** `s6-face-coverage-v2`, the `--protocol v2` mode of `tools/poc/faces_coverage.py`. It was committed (`fcba1d2f`) before any detection on its clip.
**Raw outputs:** `E:\MAVI-Controlled\PoC\S6\coverage-v2\`. `SHA256SUMS` SHA-256 `f3408441465e6537133e1535dccd0cd2aec039bc5fa561067dbb049258d27259`.

**Clip.** S2 amendment A6 added one clip: **s2-13**, MEVA G420, the school entrance hall. It comes from the same release and slot as s2-08 to s2-12. The other four candidate views were outdoor (S2 admissibility §13).

**Run.** The clip was processed into the same Development database and pipeline as v1: RTMDet `mavi-model-v2-86754e36…`, `windows-x86_64-cuda`, run `01a188f7-d6de-742e-beef-125ee7cf87cd`. That gave 30 Tracks, all 30 of them Person Tracks, with 103 evidence crops and 0 hash mismatches.

**Primary result (unchanged rule: score ≥ 0.9, shorter side ≥ 32 px): 5 of 30 Person Tracks (16.7 %) have a usable face.**

| Clip | Person Tracks | Crops | Median crop shorter side (px) | Any face at 0.9 | Usable (≥ 32 px, 0.9) |
|---|---:|---:|---:|---:|---:|
| s2-13 MEVA entrance hall | 30 | 103 | 148 | 6 | **5** |

**Sensitivity:**

| Score | ≥ 16 px | ≥ 24 px | ≥ 32 px | ≥ 48 px | ≥ 64 px |
|---|---:|---:|---:|---:|---:|
| 0.9 | 6 | 6 | 5 | 1 | 0 |
| 0.6 | 27 | 26 | 21 | 10 | 6 |

**Threshold rule (predeclared).** The detector threshold moves to 0.8 only if all three conditions hold for the band (0.8 ≤ score < 0.9, shorter side ≥ 32 px):

| Condition | Required | Measured | Holds |
|---|---|---|---|
| (i) detections in the band | ≥ 5 | 26 | yes |
| (ii) band detections that are faces, in one diagnostic look | ≥ 90 % | **20 / 26 = 77 %** | **no** |
| (iii) Person Tracks with a usable face added by the band | ≥ 1 | 13 | yes |

The faces criterion in (ii) was: the eyes or the front of the face are visible, frontal or profile. The six detections that did not meet it were crowns of heads looking down, a rear-side view and a hat brim hiding the eyes. Counting the two most borderline ones as faces would give 85 %, still under the bar.

The look is recorded as counts only, in `diagnostic-look.txt`. No label was kept, and the temporary sheet was deleted.

**Decision: the role keeps the detector threshold at 0.9.** `src/vision/config/faces/development-faces-adaface-v1.json` is unchanged.

**Reading.**
- **Coverage improved.** With s2-13, the corpus has usable faces in **7 of 140 Person Tracks** (5 %). They come from two indoor cameras: s2-12 (2/9) and s2-13 (5/30).
- **A same-slot demonstration becomes possible, subject to consent.** "Find this face" could be shown across two cameras of the same slot (s2-12 and s2-13), but only for actors whose face is usable in both. The protocol does not test whether the same actor appears in both, and no identity label is created. ADR-022 §3 opts in only s2-10, s2-11 and s2-12; s2-13 needs the owner's confirmation of consent for G420 and an amendment of §3 before it is opted in.
- **The 0.8 band is mostly faces.** At 77 % faces, it would add 13 Tracks, but a quarter of its detections would be crowns or rear views that embed poorly. The 0.9 rule keeps Unknown honest.
- **Unknown remains the majority result.**
