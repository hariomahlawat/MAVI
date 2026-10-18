# Stage 4 X4-0: offline multi-frame counterfactual (2026-10-18)

**Status:** Development-only experiment, authorised by the owner on 2026-10-18 with three corrections. It changes no Production code, contract, profile, platform or ADR. P3 stays 53/79 INADEQUATE. This is not qualification, Model Selection or acceptance evidence.

**Decision under the frozen rule: INCONCLUSIVE.**
- Extra Track-frames add many exact search hits: +13 to +16 at K ≤ 8, and +26 when every frame is read natively.
- They also add wrong-Track returns: +8 to +16 at K ≤ 8.
- No K ≤ 8 arm meets the frozen PURSUE condition (W ≤ +2), and not every arm meets REJECT.

## 1. Question and method

**Question.** On the #226 pilot population, do extra Track-frames read by the unchanged PD5-V5M/OC1-S plate path add exact search hits beyond the sealed four roles (A0)? If so:
- at what frame budget K;
- at what cost in wrong texts and wrong-Track returns;
- and does the gain need native pixels (X4), or does it survive JPEG encoding (VisionJob-K)?

The frozen record also asks whether one plate-aware frame (P1) would be enough.

**Frozen record.** `docs/qualification/stage4/x4-0-rules-v1.json`, sha256 `ffac3f56757e9ff1993395ff6471cfba6798ab08646829269d333a69206da767`.
- Committed `659ac787` at 2026-10-18T13:00:33+05:30.
- Committed before any X4 code existed or ran, and before any outcome.
- The only earlier observation was a 60-crop timing smoke of `analyse_crop`. No texts or hits were inspected.
- The record fixes:
  - the population and the catalogue;
  - the arms and the selection rules;
  - K ∈ {4, 8, all};
  - primary aggregation (`summarise_track`: union of distinct texts) and secondary aggregation (majority-vote consensus);
  - the metrics, including wrong texts, wrong-Track returns and every scouting cost;
  - ceiling labels;
  - the decision rule, including INCONCLUSIVE.

**Methodology gate (AGENTS.md).** Each assumption was checked against the implementation before the run:

| Assumption | How it was checked |
|---|---|
| The retained B1 Arm A per-candidate logs give box and identity for every scored Vehicle Track-frame | Verified |
| The extra frames can be decoded exactly as VisionJob decoded them | Decode gate below |
| The plate path can read more than four crops without touching the v1 lease | Isolated seam below |

Two consequences of the brief's proposed rule were recorded *before outcomes*:
- **Losses cannot occur under the primary union rule**, because every arm keeps A0's crops. Losses are meaningful only for consensus.
- **P1's "about 1/K of the cost" premise fails once its scouting pass is counted.** The scouting pass runs the detector on every Pool frame.

**Seam (owner correction 1).**
- All experiment code is in `tools/benchmarks/plates/x4_*.py`.
- Extra frames never become a `LeaseObservation` or `LeaseTrack`.
- Crops are analysed by the production `pipeline.analyse_crop`, through an experiment handle (role `x4-extra`).
- Texts come from a seam summariser, asserted equal to the production `summarise_track` on all 2,612 A0 Tracks.
- The tests show that the v1 lease still refuses more than four observations, and that no X4 module writes to a `mavi_vision` attribute.

**Frames.**
- Each derived 5 fps MP4 is decoded by the production `iter_frames`, sequentially from frame 0 with no seek.
- Every decoded frame's RGB SHA-256 is recorded: 13,966 frames.
- Crops use the production `crop_region` with the logged box.
- Encoded crops use the production `JpegLadderEncoder` at the supplemental cap (160 KiB).
- Native crops are lossless PNG.
- **Decode gate:** for 5,236/5,236 A0 Observations, the following all match:
  - the logged box equals the Observation box;
  - the decoded offset equals the Observation offset;
  - re-encoding at the role's own cap reproduces the sealed crop SHA-256.

**Selection never uses truth.**
- A-K uses the model-neutral rule: K equal frame-number bins, the largest logged box area per bin, then a fill by area.
- P1 uses only the per-crop maximum PD5 detector score.
- `x4_select.py` imports only the standard library. AST tests show:
  - selection, extraction and inference reference no truth, association or pilot names;
  - `evaluate()` reads truth only after the selection and text digests are fixed.

## 2. Identities

| Item | Identity |
|---|---|
| Base | main `c3649b8b`; code commit `6fd54568` (clean tree; every run checks code hashes against the inventory) |
| X4 inventory | `E:\MAVI-Working\x4\inventory.json` `e8f32a42…5705b` |
| B1 inventory / Arm A index / A-eval | `706a3826…` / `1c9d84b0…` / `5fcd2c8e…` (association and oracleReadable only) |
| B1 plates phase 2 / account | `e8113709…` / `3812d292…` |
| Videos | derivation manifest `a295809d…`, per-sequence SHA-256 |
| Pilot result | `4c346df9…` |
| O5 truth (evaluation only) | `8d1d03b2…` |
| Models | PD5-V5M `a4319856…`, OC1-S `384bbbd2…`, parameters `cce6ff6d…` (single-threaded CPU ONNX) |
| Population | 70 pilot sequences, 110 GT text Tracks (79 oracle-readable); catalogue 2,612 Vehicle Tracks; 51,883 Track-frames, of which 46,647 are Pool frames (mean 17.9 per Track) |
| A0 gate | sealed-only inference `a0-infer` `8ff6faf5…`; `a0-gate.json` `5eaf70a3…` |
| Run | extract `6af74ec0…` (repeat byte-identical); infer `b66fe49e…` (103,702 distinct crops, 0 over-bound outputs); `eval.json` `06a8d273…` |
| Interpreters | extraction: repo `.venv` (Py 3.13, PyAV 16.1.0, Pillow 11.3.0); inference and evaluation: `plates-venv` (Py 3.12, onnxruntime 1.31.0, Pillow 11.3.0) |

## 3. A0 parity (stop gate): PASS

- A0 reproduces **52/110**, with **110/110** per-Track agreement with the #226 pilot.
- The crop set is identical: 5,806 = 5,806 across all classes; 5,236 are Vehicle crops.
- Agreement with B1:
  - B1's own offline predicate also gives 52;
  - per-Track hits equal B1 phase 2;
  - the seam summary equals the production summary on 2,612/2,612 Tracks.
- **Wrong-Track returns** are counted in the 70-sequence catalogue: A0 = 16. B1's 200-sequence catalogue gives 18, so the two are not directly comparable.

## 4. Results (primary aggregation)

**Column key:**
- **G:** hits gained over A0 (/110).
- **L:** hits lost relative to A0.
- **Wrong-Track (Δ):** wrong-Track returns, with the change from A0 in brackets.
- **Tracks w/ text:** catalogue Tracks carrying any text (of 2,612).
- **Wrong texts:** distinct wrong texts on matched GT Tracks.
- **Frames decoded:** sequential decode from frame 0 to the last frame needed in each sequence.
- **Detector passes:** crops given to the plate detector, including P1's scouting crops.
- **Plate CPU s:** detector plus OCR CPU seconds.

| Arm | Hits /110 | /79 | G | L | Wrong-Track (Δ) | Tracks w/ text | Wrong texts | Extra frames | Frames decoded | Detector passes | OCR reads | Plate CPU s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A0 | 52 | 45 | 0 | 0 | 16 | 197 | 34 | 0 | 0 | 5,236 | 547 | 301 |
| A-4 | 65 | 54 | +13 | 0 | 24 (+8) | 294 | 71 | 8,782 | 13,802 | 14,018 | 1,369 | 992 |
| A-8 | 68 | 55 | +16 | 0 | 26 (+10) | 328 | 106 | 15,021 | 13,856 | 20,257 | 1,951 | 1,406 |
| A-all | 76 | 61 | +24 | 0 | 43 (+27) | 370 | 599 | 46,647 | 13,948 | 51,883 | 8,516 | 4,900 |
| A-4-native | 65 | 53 | +13 | 0 | 28 (+12) | 315 | 76 | 8,782 | 13,802 | 14,018 | 1,420 | 994 |
| A-8-native | 67 | 54 | +15 | 0 | 32 (+16) | 347 | 112 | 15,021 | 13,856 | 20,257 | 2,034 | 1,412 |
| A-all-native | 78 | 62 | +26 | 0 | 48 (+32) | 384 | 586 | 46,647 | 13,948 | 51,883 | 8,861 | 4,954 |
| P1 (incl. scouting) | 62 | 53 | +10 | 0 | 28 (+12) | 302 | 50 | 598 | 13,948 | 51,883 | 1,145 | 4,159 |

**Extraction cost.** Decode, crop and encode of every Track-frame, in both forms, took 472 s of CPU in total.

**Recovered misses by pilot cause (A-8):**
- source evidence: 11;
- detector miss: 3;
- OCR error: 2;
- association: 0, as expected.

**Encoding.**
- A-K and A-K-native differ by at most 2 hits; at K = 8 the encoded arm is 1 hit *ahead*.
- Native extras carry *more* wrong-Track returns and wrong texts.
- At K ≤ 8, JPEG encoding is not the limiting factor.

**P1.**
- Its single plate-aware frame adds +10.
- Its scouting pass costs as many detector passes as A-all (51,883), and about 3× the plate CPU of A-8.

**Secondary aggregation (consensus; reported only, not used by the decision).**

| Arm | Hits | Net change vs A0 consensus | Hits lost |
|---|---|---|---|
| A0 | 52 | — | — |
| A-4 | 64 | +12 | 1 |
| A-8 | 66 | +14 | 2 |
| A-8-native | 65 | +13 | 2 |
| A-all-native | 73 | +21 | 1 |
| P1 | 62 | +10 | 0 |

Consensus reduces wrong-Track returns, for example 41 against 48 for A-all-native. It can also lose hits that A0 had.

**Repeat.**
- Extraction: an independent repeat gives a byte-identical index, so the frame hashes, crop manifests and crop store are identical.
- Inference and evaluation: see §7.

## 5. Decision under the frozen rule

Each K ≤ 8 arm is measured relative to A0, using the frozen PURSUE and REJECT conditions:
- **PURSUE** needs G ≥ 8, L = 0, W ≤ +2 and sign-test p ≤ 0.05 (W is the change in wrong-Track returns).
- **REJECT** applies if G ≤ 4, or L > 0, or W ≥ G.

| Arm | G | W | Meets PURSUE? | Meets REJECT? |
|---|---|---|---|---|
| A-4 | +13 | +8 | no (W > 2) | no |
| A-8 | +16 | +10 | no | no |
| A-4-native | +13 | +12 | no | no |
| A-8-native | +15 | +16 | no | yes (W ≥ G) |

**Outcome: INCONCLUSIVE.** No arm meets PURSUE and not every arm meets REJECT. No design preference applies, because preferences are defined only under PURSUE.

**What this means (inference):**
- The hit gain is large and directionally clear: the paired gains are 13 to 16 with 0 losses.
- The frozen guard against search pollution (W ≤ +2) is not met. Under union semantics, every extra crop also adds texts that return other Tracks.
- Whether those returns are harmful (true false matches) or benign (another Track of the same vehicle) is not something the frozen metric distinguishes. See the post-hoc note in §6.

## 6. Ceilings, recomputed per Track (owner correction 2)

| Ceiling | Label | Value | Brief |
|---|---|---|---|
| Association bound: matched GT Tracks | derived | 86/110 (65 of 79 oracle-readable) | — |
| Brief's pilot-cause bound: 52 + source-evidence oracle-readable 12 + detector 8 + OCR 2 | derived | 74. All 22 Tracks are matched; 19 of the 22 are recovered by some arm. | ≤ 74 |
| X2: A0 plus native re-reads of A0's own frames | measured | 55/110 (47/79) | ≈ 53 |
| X4: every Track-frame read natively (A-all-native) | measured | 78/110 (62/79) | ≤ 74 [HYP] |
| X3: same frame access as X4 on 5 fps BDD | measured upper bound | 78/110 (plate-aware selection inside VisionJob not modelled) | ≈ 62 |
| Union of all arms | measured | 78/110 (62/79) | — |
| E-B matched-unreadable /79 | estimate (instrument-oracle quantity, not re-measured) | Of B1's 12 E-B matched-unreadable Tracks, 10 are search hits in some arm (A0: 0) | ≤ 11 |

**Corrections to the brief:**

1. **The ≤ 74 bound is exceeded (78).**
   - The brief excluded the 12 "natively unreadable" source-evidence misses. Measured, **7 of those 12 are recovered** when every frame is read.
   - Oracle readability is judged only at plate-labelled frames, so it understates what other frames can show.
   - The brief's 22 also inconsistently *included* two Tracks that are not oracle-readable (`b1f85377-44885085/00118035`, `b1fbf878-b31a8293/00112829`).
2. **X2 is +3, not ≈ +1. X3 is not ≈ 62.** On 5 fps BDD, a VisionJob plate role sees exactly the frames X4 sees, so X3's frame-access ceiling equals X4's measured 78.
3. **Crops per Vehicle Track.** The brief's "2.2 crops per Vehicle Track" counts Person crops: 5,806 / 2,612. The Vehicle figure is 5,236 / 2,612 = 2.0.
4. **Unrecovered matched Tracks.** 8 matched GT Tracks are not hit by any arm. All 24 association misses stay unreachable, as expected.

**Post-hoc diagnostic (not frozen; does not change the decision).** `E:\MAVI-Working\x4\posthoc\wrong-track-attribution.json` attributes each wrong-Track return to one of four categories:
- a Track in another sequence;
- a same-sequence Track associated to the same GT vehicle;
- a same-sequence Track associated to another GT vehicle;
- a same-sequence Track that is unassociated.

Most of the added returns are same-sequence Tracks that no GT Track is associated with. They are plausibly fragments or duplicates of the same vehicle, but this is not established: A-eval lists only matched MAVI Tracks, so the "same GT vehicle" category is never populated.

| Arm | Other sequence | Same sequence, other GT vehicle | Same sequence, unassociated |
|---|---|---|---|
| A0 | 3 | 1 | 12 |
| A-4 | 3 | 1 | 20 |
| A-8 | 3 | 1 | 22 |
| A-4-native | 3 | 3 | 22 |
| A-8-native | 3 | 3 | 26 |
| A-all | 6 | 3 | 34 |
| A-all-native | 6 | 5 | 37 |
| P1 | 3 | 2 | 23 |

At K ≤ 8 with encoded crops, cross-sequence and other-vehicle returns do not rise at all. This suggests, but does not show, that the W guard mainly measures fragment pollution. A frozen follow-up would need its own rule (see the PR description), and it does not change this experiment's outcome.

## 7. Repeat equality

REPEAT_PLACEHOLDER

## 8. Limitations

- **Same data again.** This is the same BDD100K H3 data as #226, B1 and X1, so the result is hypothesis-generating, not an independent validation.
- **Sparse frames.** The data is 5 fps, about 20 frames per Track. K = 8 is about 45 % of a Track's Pool frames, and "all" is every frame. No higher-rate source exists locally.
- **Offline predicate.** The search predicate is offline (exact normalised text on the associated Track), not the live API.
- **Catalogue scope.** Wrong-Track returns are counted in the 70-sequence catalogue only. The A0 value is 16 here, against 18 in B1's 200-sequence catalogue.
- **Encoded crops and the cap.** Encoded extra crops use the supplemental cap. A VisionJob-K design would also face the run-level evidence quota, which this experiment does not model.
- **P1's design.** P1 scouts encoded crops of every Pool frame. Cheaper scouting, such as a sparse scouting schedule, is not tested.
- **Cost figures.** CPU is per-crop `process_time` from one run, with 8 parallel workers. Frames decoded assumes a sequential decode from frame 0, because random-seek equivalence is unproven.
- **Association is unaddressed.** 24/110 misses are association failures, and no evidence-side arm can reach them.
- **Wrong-Track returns are not attributed in the frozen metric.** Some are plausibly Tracks of the same vehicle (fragments) rather than false matches; see the post-hoc diagnostic.

## 9. Reproduce

`tools/benchmarks/plates/`: `x4_common.py` (inventory) → `x4_infer.py run` (sealed only) → `x4_eval.py a0-gate` → `x4_extract.py run` → `x4_infer.py run --extract` → `x4_eval.py`. Repeat with separate output directories, then compare with `x4_eval.py equal`. Tests: `tools/benchmarks/tests/test_plates_x4.py`.
