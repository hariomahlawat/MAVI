# Stage 4 — X1 Edge-Margin Experiment (owner decision O3)

**Date:** 2026-10-13. **Class:** bounded Development experiment.

**Nothing frozen was changed.** The following are untouched:
- the release profile (`afb03b6c…`);
- the frozen E-A and E-B results;
- the protocol and thresholds;
- the INADEQUATE verdict (P3).

**Outcome:** the candidate rule recovers **0 of the 10** selection-related failures. Coverage is unchanged at **C = 51/77 = 0.662**. There are **no regressions**.

## Question and design

**Question:** does exempting a vehicle's bottom-border contact from `edgeMarginFloor` recover the near views that evidence selection discards?

**Rule `x1-bottom-edge-exempt-vehicle-v1`:**
- The candidate wraps the production scorer and changes one scalar.
- For a **Vehicle** candidate, the edge margin given to the selector is `min(left, top, right)`.
- Everything else is the release profile's:
  - quality and selection scores;
  - the confidence (0.5), sharpness (0.05) and occlusion floors;
  - the role rules;
  - the encoder and byte caps;
  - Person candidates.
- Nothing reads plate pixels; no plate-aware selection.

**Implementation:** `tools/benchmarks/plates/x1_run.py`. No product code changes; the candidate profile exists only as this experiment wrapper.

**Arms.** All three use the same 200 BDD100K MOT val derived videos (derivation manifest `a295809d…`):

| Arm | What it does |
|---|---|
| `live` | the qualified runtime through the worker's own composition (RTMDet → ByteTrack → `VideoProcessor`, release profile), recording every per-frame detection |
| `baseline` | replays the recorded detections through the real tracker and selector |
| `candidate` | the same replay with the rule applied |

**Identities.** Each arm and sequence has its own ProcessingRun id, `uuid(sha256("stage4-x1/<arm>/<sequence>"))`.

**Evaluation:** `tools/benchmarks/plates/x1_eval.py`, with the frozen rules unchanged:
- the frozen association policy and rates;
- truth `709a560b…`;
- E-A `cc718922…` (`h_min` = 32 px);
- both pinned instruments;
- `coverage.evaluate_track`.

## Reproducibility

| Check | Result |
|---|---|
| live = baseline replay (every Track, observation, crop and trajectory SHA-256) | **200/200 sequences identical** |
| live evidence = the platform's sealed H3-attempt2 evidence (multiset of crop SHA-256 per sequence) | **200/200 identical** |
| baseline evaluation = frozen E-B (track state and evidence-readability, every oracle-readable track) | **identical; 0 differences**, C = 51/77 |
| baseline vs candidate trajectories | 200/200 identical: the rule does not touch tracking or association |
| second replay of both arms and second candidate evaluation | **byte-identical** (see *Repeatability*) |

## Results

| | Frozen E-B | Baseline | Candidate |
|---|---|---|---|
| C (union of instruments) | 51/77 = 0.662 | 51/77 | **51/77** |
| Matched-Track C (R_ev / matched R_oracle) | — | 51/63 | **51/63** |
| fast-plate-ocr | — | 51/77 | 51/77 |
| rapidocr (below the support floor) | — | 15/29 | 15/29 |
| Recovered selection failures | — | — | **0 / 10** |
| Regressions (readable → not readable) | — | — | **0** |
| Association state changes | — | — | 0 |

The **theoretical maximum** of any selection-only remedy for these failures is 10/77, giving C = 61/77 = 0.792. That would be **MARGINAL, not ADEQUATE**. X1 achieved none of it.

## Why: frame-edge exclusions by border

The counts below cover all 114,235 Vehicle candidates (every Track at every frame) in the baseline arm. A label such as `left+top` means the box is under the floor on both of those borders. "Edge only" means the candidate met every other floor.

| Borders under the floor | Edge failures | Edge only |
|---|---|---|
| left | 13,457 | 7,164 |
| right | 12,684 | 5,759 |
| left+right | 1,334 | 304 |
| left+top | 802 | 401 |
| right+top | 379 | 169 |
| **bottom** | **252** | **200** |
| top | 250 | 179 |
| bottom+left | 238 | 178 |
| bottom+right | 209 | 25 |
| bottom+left+right | 118 | 0 |
| left+right+top | 41 | 2 |
| bottom+left+right+top | 2 | 0 |
| bottom+top | 1 | 0 |

- **Bottom-only contact is rare.** It accounts for 252 of 29,767 edge failures (0.85 %).
- **What the candidate admitted:** exactly those 200 bottom-only, otherwise-qualified candidates, and nothing else. Every other combination is unchanged.
- **Left and right contact dominate.** In this front-facing dashcam data, the closest views of a vehicle are cut by the **side** borders as it passes or turns, not by the bottom border.

## The 10 selection failures: per-track attribution

This attribution comes from the selector's own per-candidate qualification records at each track's best oracle frames (largest native plate), using the same records in both arms.

| Track | Kept frames | Best oracle frames: plate char px, cause | Borders that still block under X1 |
|---|---|---|---|
| b1d0a191-2ed2269e/00125713 | 9, 14, 41, 42 | 45: 47 px, fails confidence+edge+occlusion; 44: 35 px, edge; 43: 33 px, **qualified, not kept** (NearView growth hysteresis, area not > 1.25× frame 42) | right |
| b1d7b3ac-995f9d8a/00119235 | 140, 151, 157 | 175–177: 48–53 px, edge (and sharpness at 176) | top, left |
| b1dd58c1-8b546ba7/00113707 | 130, 134, 164 | 175–177: 33–44 px, edge | left |
| b1ea0ae4-4f770228/00121829 | 146 | 154: 39 px, sharpness+edge | right |
| b1ea0ae4-4f770228/00121841 | 186, 187 | 200–201: 33–39 px, sharpness+edge | right |
| b204a5c1-05981158/00130594 | 32, 35 | 40, 41, 95: 32–34 px, edge | right |
| b21c68e6-65674a17/00121309 | 83, 88, 101, 102 | 108, 109, 132: 69–72 px, **sharpness only** | — |
| b21c86ac-2eb7ba16/00115627 | 23, 25, 80 | 0: Track not yet present; 1: sharpness+edge; 2: sharpness | right |
| b21c86ac-2eb7ba16/00115628 | 43, 75, 100, 101 | 106: sharpness+edge; 104–105: sharpness | left |
| b237db93-fab44bf2/00116092 | 146, 149 | 151: 38 px, edge | right |

**Summary of causes:**
- **Edge contact on a border X1 does not exempt (left, right or top) blocks 9 tracks:** right 6, left 3, top 1 (one track touches both left and top).
- **The sharpness floor blocks 5 tracks**, alone or with the edge. One of them, 00121309, is blocked by sharpness alone at 69–72 px plates. Near, large plates can have low normalised sharpness, so this floor is itself a candidate cause.
- **One track has a qualified near frame that the NearView hysteresis rejected.**
- **No track is blocked by bottom contact.**

## Evidence quality and negative controls

Changed Vehicle observations: **13 of 11,892** (two sequences: `b23b2649-1a78948d`, `b23b2649-6af03cd5`; plus one late re-ranking in `b24f03f7-ff66eaca`).

**Roles affected:**

| Role | Replaced | Added | Removed |
|---|---|---|---|
| NearView | 7 | | |
| Representative | 1 | | |
| EarlyDiverse | 1 | 1 | |
| LateDiverse | 1 | 1 | 1 |

**Negative controls:**
- **No unqualified evidence admitted.** Every new observation is a qualified candidate, so the confidence, sharpness and occlusion floors still hold.
- **Changed crops are mostly larger views of the same vehicle.**
  - In the 8 NearView/Representative replacements, the kept frame is 1–3 frames later, with a box area 1.4–3× larger and a crop 4–13 KiB larger.
  - The two diverse-role changes in `b24f03f7` keep comparable or smaller views (a cascade, not a bottom exemption).
- **Sharpness falls but stays above the floor.** It is lower in 8 of the 10 changed observations present in both arms (minimum 0.054, floor 0.05).
- **Confidence is about the same.** It is lower in 2 of those 10 (by 0.01–0.03).
- **None of the 13 changed observations falls on a usable labelled plate frame:**
  - 3 are at frames without a plate label;
  - 6 are on Tracks without a usable plate;
  - the other 4 are on MAVI Tracks not associated with any ground-truth vehicle.

  So no readability gain or loss is measurable on them, and no labelled reading changed.
- **No regressions; the evidence-role structure is unchanged.** One LateDiverse shifted rank because an EarlyDiverse was added.

## Repeatability

**Already established (single pass):**
- **Determinism of the selection step:** the baseline replay reproduces live, and live reproduces the platform's sealed evidence, in all 200 sequences.
- **Determinism of the evaluation:** the frozen E-B and E-A repeats were row-identical (register), and the baseline evaluation reproduces the frozen E-B.

**Independent repeat (complete):**
- A second replay of both arms from the recorded detections (`repeat/`) produced **byte-identical** index files: baseline `98b1f7d3…` = `98b1f7d3…` and candidate `418b0fd3…` = `418b0fd3…`. Every per-sequence result is hashed inside them.
- A second candidate evaluation produced a **byte-identical** file, `candidate-eval.json` `e3a24d3f…`, so its rows and summary are equal.

## Run identities and hashes

All files are outside Git under `E:\MAVI-Controlled\Benchmarks\stage4-x1\`.

| Artefact | SHA-256 |
|---|---|
| `live/index.json` (ProcessingRun ids, per-sequence results and detections hashes, runtime provenance) | `53b29146…` |
| `baseline/index.json` | `98b1f7d3…` |
| `candidate/index.json` (rule, 16,209 Vehicle candidates with a changed edge margin) | `418b0fd3…` |
| `baseline-eval.json` | `903b9813…` |
| `candidate-eval.json` | `e3a24d3f…` |
| `compare.json` | `8b0bd8a5…` |
| `verify.json` | `69e7b828…` |
| `attribution.json` | `a00ac387…` |
| `attribution-summary.json` | `2b23a2b4…` |

**Provenance (live):**
- model `rtmdet-m-coco-phase1` 1.0.0 (checkpoint `229f527c…`);
- pipeline profile `phase1-detection-tracking-v1` 1.3.0-candidate (`afb03b6c…`);
- qualification `rtmdet-m-coco-phase1-v2`;
- runtime `mmdetection-phase1-v1` on `windows-x86_64-cuda`, GTX 1650 Ti;
- MAVI commit `180e25ea`.

**Example ProcessingRun id:** candidate `b1d0a191-2ed2269e` → `234a470d-a271-02e6-86b9-de3d411fc428`.

## Conclusion and recommendation

**Reject X1 as formulated.** It is safe: no regressions, no unqualified evidence and a negligible footprint. But it addresses a border that blocks none of the failures, so it has no effect on E-B.

**The measured blockers are:**
- side- and top-border contact (9 tracks);
- the sharpness floor at near views (5 tracks);
- NearView growth hysteresis (1 track).

**Any revision is a new owner decision and is not implemented here:**
- **X1′ — role-specific near-view qualification.** For example, apply the edge floor to the vehicle box only where the plate region could be cut, or relax all-border contact for NearView only. This verges on plate-aware selection (X3), which the owner has excluded at this stage.
- **A sharpness-floor study.** The sharpness metric is normalised. At large near views it falls below 0.05 while the plate is clearly readable (00121309: 69–72 px plates).

**The ceiling stays MARGINAL.** Even full recovery of all 10 gives C = 0.792 (MARGINAL). The 14 unassociated tracks need native-frame-rate tracking evidence (O1/LSV-LP) before any tracker change.

**PR-6 stays held.**
