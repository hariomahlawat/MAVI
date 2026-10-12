# Stage 4 — Evidence-Adequacy Root-Cause Analysis (owner decision O3)

**Date:** 2026-10-13. **Class:** post-hoc Development diagnostic.

This analysis explains the frozen E-B result; it **does not change** that result, its thresholds, its denominator or the INADEQUATE verdict (register P3).

**Inputs** (all hash-bound and read-only):

| Input | Hash |
|---|---|
| E-B result | `3db69e53…` |
| E-A result | `cc718922…` |
| Association artefact | Stage-3 H3 run `bea73d13…` |
| Stage-3 detector diagnostic | production `RTMDetDetector` on every derived frame of the same derivation manifest `a295809d…` under the same release profile `afb03b6c…` |
| MAVI trajectories | read from the H3 evidence root by SHA-256 |

**Outputs** (outside Git):

| File | SHA-256 |
|---|---|
| `E:\MAVI-Controlled\Benchmarks\stage4-bdd-plates\results\root-cause-o3.json` | `6f5b2e56…` |
| `selection-cause-o3.json` | — |

**Scripts:** `E:\MAVI-Working\stage4\root_cause.py` and `selection_cause.py`.

## Frozen result being explained

- R_oracle = 77 (77 distinct vehicles); R_ev = 51; **C = 0.662 → INADEQUATE**.
- Encoding loss passed: 0.97 pp and 1.95 pp.
- The 26 failures:
  - **14** ground-truth vehicles have no associated MAVI Track;
  - **12** are matched, but the sealed evidence did not yield the plate.

## A. The 14 unassociated vehicles — detection vs tracking vs association

Classification rules, applied in order:
- the association state, as recorded by the frozen `vehicle-tracks-association-v1` policy;
- then the detector recall at the tracker's high-confidence threshold (0.6), counting detections with IoU ≥ 0.5 to the ground-truth box;
- then whether any MAVI Track overlaps.

| Cause | Tracks | Evidence |
|---|---|---|
| **Tracking: identity fragmentation** (`fragmentedGt`) | 6 | Detected at ≥ 0.6 in 59–93 % of their frames, yet the identity is split across several MAVI Tracks, none covering ≥ 50 % of the vehicle |
| **Detection: low detector confidence** | 4 | Detected at any confidence in most frames, but at ≥ 0.6 in only 14–50 % (for example 11 of 80 frames, 14 of 49 frames) |
| **Association: overlapping MAVI Track below the policy floors** | 3 | Detections present; candidate MAVI Tracks fail the containment, coverage or continuity floors |
| **Association: spot-check IoU gate** (`unverifiedGt`) | 1 | A MAVI Track contains the vehicle, but the IoU spot check failed |

## B. The 12 matched tracks — why the sealed evidence did not yield the plate

Each failure was checked against the native read at the same evidence frame (E-A rows) and the plate's size in the crop.

| Cause | Tracks |
|---|---|
| **Selection: every labelled evidence frame shows the plate below `h_min`** (12–28 px in the crop), while the vehicle's best native frames show 34–72 px | **10** |
| Encoding: readable natively at an evidence frame (Representative, 39 px), not in its sealed crop | 1 |
| Frame quality: evidence frames large enough, unreadable even natively | 1 |

The encoding stage is nearly lossless at this resolution: BDD vehicle crops are under 1024 px, so they are not downscaled. **The dominant crop-retention cause is which frames the selector keeps.**

### Why the selector did not keep the near frames (10 tracks, best 1–3 native frames each, 25 frames)

At the frames where the plate is largest:
- the matched MAVI Track **is present** (a trajectory point exists) in 24 of 25;
- the detector confidence is **0.58–0.89**, above the 0.5 evidence floor;
- the ground-truth vehicle box **touches the frame edge** (edge margin ≤ 0.002) in **23 of 25**, and is within 0.044 of it in the other 2.

The release profile's evidence selector requires `edgeMarginFloor` 0.005 for a qualified candidate (ADR-013 §4). That rule therefore **disqualifies exactly the closest views**. A vehicle near the camera has its box run off the bottom of the frame, while its plate is still wholly inside the frame.

The Representative falls back to the best admissible frame, and the supplemental roles are qualified-only. So no role can hold a near view.

## Findings

1. **The INADEQUATE coverage is not caused by JPEG encoding.** E-A loss is ≤ 2 pp; 1 of 77 tracks is lost to encoding.
2. **The largest single cause is the frame-edge qualification floor** (10 of 77 tracks; 13 % of oracle-readable vehicles). It excludes near views whose box touches the frame border. This floor is a numeric parameter of the frozen, model-neutral selection method. Re-deriving it, for example tolerating contact with the bottom border, is **alternative X1** (a new pipeline profile and ProcessingRun identity, with requalification per ADR-013 §6 and ADR-009). It needs no plate-aware selector (X3) and no ADR-013 §10 change (X2).
3. **Tracking and association account for 14 of 77** (18 %): fragmentation 6, detection confidence 4, association policy 4. These numbers come from **5 fps** derived video (BDD100K MOT labels frames at 5 fps). ByteTrack's association is sensitive to frame rate, so the share is **not** representative of MAVI at native 25–30 fps. X1–X3 cannot recover these.

## Recommended corrective action (evidence-supported; nothing is implemented)

1. **Measure X1 (edge-margin floor) before anything else.** Run a bounded Development experiment:
   - re-derive `edgeMarginFloor`, for example 0 for the bottom border or role-specific for NearView, in a candidate pipeline profile;
   - re-run the existing E-B pipeline on the same BDD sequences and labels (new ProcessingRuns);
   - compare C under the same frozen rule.

   The analysis predicts at most +10 of 77 tracks, which would take C from 0.662 to ≤ 0.79. Any profile change remains a pipeline-profile change with its requalification consequences. **This is the owner's O3 decision; PR-6 stays held.**
2. **Re-measure tracking on native-frame-rate footage before changing the tracker.** LSV-LP (25 fps, per-frame plate truth, admissible under MAVI's academic non-commercial classification) when its share is re-enabled, or an Indian 25 fps source (O1). That separates real tracker weakness from the 5 fps artefact.
3. **No change to the encoder, the role byte caps (X1 encoder part) or the plate-aware role (X3) is indicated** by this evidence.

## Limitations

- **Domain.** BDD100K is US and Israeli dashcam footage at 5 fps. This is **not Indian-domain validation** (O1 remains open).
- **Labels.** The R8 labels are agent-verified, not human-verified. See O5 (register); an independent blind re-verification by a separate agent is recorded there.
- **Labelling gaps.** 18 evidence observations had no verified plate label; they are counted as not readable, as the frozen rule requires. Affected tracks are listed in `root-cause-o3.json`.
- **The X1 prediction is an upper bound.** It assumes the near frame would be selected and read.
