# Stage 4 — B1 NearView Scale-Normalised Sharpness Experiment (#228)

**Date:** 2026-10-18. **Class:** bounded Development experiment (same-data counterfactual). **Not** a profile change, **not** Production evidence, **not** a Model Selection Event.

**Unchanged by this work:** the release profile `afb03b6c…`; all production `mavi_vision` code; the frozen E-A/E-B results; the frozen P3 verdict **INADEQUATE (53/79)**; O3, PR-6, protected D and licensing.

**Result (observed):**

| Measure | Arm A (original) | Arm B (B1) |
|---|---|---|
| O5 E-B coverage | 53/79 | **55/79** |
| Track gains / losses | — | **+2 / 0** |
| Exact search hits, offline #226 PD5/OC1-S path (110 text-usable GT Tracks) | 52/110 | **56/110** |
| Search hit gains / losses | — | **+4 / 0** |

Every change comes from B1-admitted NearView crops. Person, Representative and trajectories are unchanged on all 200 sequences.

By the pre-declared rule the decision is **C: propose a separate owner O3 decision**. It is subject to the limitations below.

## Frozen candidate (before any outcome)

**Record:** `docs/qualification/stage4/b1-candidate-v1.json`, SHA-256 `e3eb0998…0aeb`. It was committed as `a184cb1e` at 08:38 IST (local time), before any outcome-producing run: the first output, a one-sequence smoke, is from 08:43, and the inventory from 08:47. See the limitation on how this ordering is attested.

**Rule:**
- Sharpness is the production mean-gradient formula over the whole Vehicle `crop_region`, after resizing it to 128 px height with Pillow 11.3.0 `BILINEAR` (default `reducing_gap`; width `max(1, round(w·128/h))`).
- It is computed only when the native crop height is greater than 128 px. Crops are never upscaled.
- The floor is unchanged at 0.05.
- A **b1-only** candidate fails the original sharpness floor, passes the B1 sharpness and passes every unchanged confidence, edge and occlusion gate. Such a candidate is eligible for **NearView only**, under the unchanged duplicate and growth-hysteresis rules. It keeps the production quality and selection scores, and it is held with `qualified=false` (experiment-admitted).

**Decision rule:**
- **A:** net ≤ 0, or any loss with net ≤ 1.
- **C:** 0 losses and net ≥ 2.
- **B:** otherwise.

**Provenance caveat:** the hypothesis was selected from the exploratory 19/26 diagnostic (`sharpness-floor-diagnostic-2026-10-13.md`) on the same BDD100K family. This is a within-dataset follow-on, not an independent validation.

## Implementation (Development tooling only)

- **`tools/benchmarks/plates/b1_nearview.py`:** `B1NearViewSelector` subclasses `EvidenceSelector`.
  - The **unchanged production `observe` runs first** for every candidate.
  - Only for a b1-only Vehicle candidate is the production NearView rule then applied, with the holders as they stand.
  - `b1_composition` swaps `process_video.EvidenceSelector` for one run and restores it afterwards.
  - Arm A asserts that the production class is in use.
- **`b1_run.py`:**
  - Fail-closed inventory that binds every input.
  - Replay of the retained X1 detector streams through the real ByteTrack, `VideoProcessor`, `JpegLadderEncoder` and staging.
  - Per-candidate logs with `qualifiedOriginal`/`qualifiedNearB1`, written as deterministic gzip (mtime 0, no file name).
  - The index binds the canonical decoded SHA-256, the gzip SHA-256 and the row count of every log, plus every result, staged artefact and input.
  - `verify` and `equal` reject any missing, extra or changed item.
- **`b1_eval.py`:** preflight counters; `x1_eval.evaluate` against the O5 truth; Track-level accounting.
- **`b1_plates.py`:** the Phase 2 offline plate path (see Phase 2).
- **Dependencies:** none new. Pillow 11.3.0 is already pinned for the vision runtime and the instruments. Replay used the Development vision runtime venv as X1 did (it is the one with `trackers` 2.6.0), with no CUDA and no detector inference.
- **Tests:** `tools/benchmarks/tests/test_plates_b1.py`, 30 tests:
  - role isolation;
  - sharpness-only admission;
  - edge, confidence and occlusion gates still reject;
  - growth hysteresis and duplicate rules unchanged;
  - encode refusal;
  - Person never assessed;
  - shadow mode holds nothing;
  - the seam equals production on 300 random streams without b1-only candidates;
  - the Representative is identical on 300 random streams with them;
  - the frozen resize;
  - composition seam restore;
  - deterministic and tamper-evident logs;
  - `verify` fail-closed cases (7 kinds);
  - canonical repeat equality;
  - the offline search predicate.

## Phase 0 — inventory, parity, preflight

**Inventory** (`E:\MAVI-Working\b1\inventory.json`, `706a3826…`): **PASS**. It covers:
- the manifest `a295809d…` (200 sequences; every video and ground-truth file against the manifest);
- 200 detector streams against the X1 live index `53b29146…`;
- X1 baseline results `98b1f7d3…`;
- O5 truth `8d1d03b2…`, E-A `db2656f1…`, E-B `b3aa0b4d…` and verdict `6dc95563…`;
- the historical AI-label inputs `709a560b…`/`cc718922…`/`3db69e53…`;
- descriptor `7169263a…`;
- the instrument model files, the profile and the code-file hashes.

**Baseline parity:** **all four checks pass.**

| Check | Result |
|---|---|
| Arm A vs X1 baseline (every Track, trajectory, observation and crop SHA-256) | **200/200** identical |
| Arm A vs the platform's sealed H3-attempt2 evidence | **200/200** identical |
| Arm A O5 evaluation vs E-B `b3aa0b4d…` (16,874 rows: state, usable, oracle, evidence) | **0 differences**, 53/79 |
| Preflight shadow arm vs Arm A | identical |

**Preflight** (`preflight-summary.json` `a4993619…`), over the full 200-sequence population:

| Count | Vehicle candidates |
|---|---|
| All candidates | 114,235 |
| Fail the original sharpness floor | 16,736 |
| — B1 sharpness undefined (crop ≤ 128 px tall) | 3,022 |
| — B1 sharpness below the floor | 6,634 |
| — Pass B1 sharpness | 7,080 |
| — of those, blocked by unchanged gates (edge alone 4,168) | 5,643 |
| **— of those, b1-only (all three conditions)** | **1,437** |

- The 1,437 b1-only candidates are on **367 Tracks** in **138 sequences**.
- Under the production state, 869 of them would have had a NearView opportunity (296 Tracks); 422 were blocked by growth hysteresis and 146 by being a duplicate of the Representative.
- The stop rule did not fire, so Phase 1 ran.

## Phase 1 — Arm A vs Arm B, full 200 sequences

| Arm | Index | O5 evaluation |
|---|---|---|
| A | `1c9d84b0…` | `5fcd2c8e…` |
| B | `f999623e…` | `21ea88e7…` |

Accounting: `account.json` `3812d292…`.

**Run identities:** `uuid(sha256("stage4-b1/<arm>/<sequence>"))`.

| | A | B |
|---|---|---|
| C (union of instruments; fast-plate-ocr is identical) | 53/79 = 0.671 | **55/79 = 0.696** (still < 0.70) |
| Matched-not-readable | 12 | 10 |
| Unassociated failures (fragmented 6, unmatched 7, unverified 1) | 14 | 14 (B1 cannot reach them) |
| Association state changes | — | 0 |

**Gains** (each is a B1-admitted NearView read exactly at a labelled frame):
- `b21c68e6-65674a17/00121309`: NearView frame 101 → 109; box area 0.039 → 0.348; 41 KiB crop; original sharpness 0.036, B1 sharpness 0.082.
- `b21c86ac-2eb7ba16/00115628`: frame 100 → 105; area 0.035 → 0.196.

**Losses: 0.**

**Readable Tracks whose reading-preserving roles changed: 7** (6 lost a reading role, 1 gained one).

| Track(s) | Change |
|---|---|
| 00118784, 00124432, 00128926, 00118036, 00124539 | lost a reading NearView: a NearView that read at a labelled frame was replaced by a B1 crop at an unlabelled frame (unmeasurable). 00124432 and 00128926 also lost a reading LateDiverse. |
| 00125165 | kept its NearView reading; lost only a LateDiverse reading |
| 00121826 | **gained** a NearView reading (`[representative]` → `[near-view, representative]`) |

- The B1 replacement crop is not always larger: on 00128926 it has the same area as the A view and comes earlier in time.
- At role level (fast-plate-ocr), reading NearView instances go from 44 to 42 and reading LateDiverse from 19 to 16.
- All 7 Tracks stay evidence-readable under both instruments, and their Phase 2 hit status is the same in both arms (6 hits, 1 miss).
- Evidence-readable Track counts by role (union of instruments, from the evaluation summaries):

| Role | A | B |
|---|---|---|
| NearView | 45 | 43 |
| LateDiverse | 19 | 16 |
| Representative | 49 | 49 |
| EarlyDiverse | 15 | 15 |

**Evidence changes** (319 Vehicle observations on 283 Tracks, in 111 of 200 sequences):

| Cause | Observations |
|---|---|
| B1-admitted NearView (215 replaced, 63 added) | 278 |
| EarlyDiverse/LateDiverse diversity cascade (replaced 27, added 10, removed 1) | 38 |
| NearView displaced by the B1 holder's later hysteresis or duplicate drop (removed 2, replaced 1) | 3 |

- Of the 1,437 b1-only candidates, 418 were held as NearView, 873 were refused by growth hysteresis and 146 were refused as duplicates of the Representative. None was refused by the encoder.
- On text-usable GT Tracks, 24 observations changed. On the B side, 17 crops on those Tracks are unmeasurable (no plate label at that frame): 11 B1-admitted NearViews and 6 EarlyDiverse/LateDiverse cascade crops. Of the B1-admitted NearViews there, 6 read and 1 did not read.
- **No gain is claimed for the unmeasurable crops.**

**Controls:**
- Person evidence: identical on all 1,050 Person Tracks.
- Representative: identical on all 6,057 Vehicle Tracks.
- All 7,107 trajectories identical.

**Crops:**
- In the 243 replaced observations, the B crop is larger in area in 226; the replacements add +1.17 MB in total.
- Vehicle evidence bytes: 70.10 MB → 72.25 MB (+3.1 %); NearView +7.4 %.
- Observations: NearView 4,027 → 4,088; EarlyDiverse 945 → 950; LateDiverse 863 → 867.

**Resources:**
- **CPU cost: unresolved, not attributable to B1.** Whole-replay CPU was A 902 s and B 998 s, but the arms ran in concurrent pairs, and the identical repeat of Arm A took 997 s (+10.5 % over A). B is within 0.1 % of its concurrent partner (repeat A), and repeat B, run alone, took 950 s. The B1 overhead is inside this run-to-run spread. The figures are whole-replay CPU, not selection CPU.

**Observed ceiling** (12 matched failures in Arm A):

| Track group | Count |
|---|---|
| Have any b1-only candidate | 6 (B1 held a NearView on all 6) |
| Have a b1-only candidate at a native-readable oracle frame (00121309, 00115627, 00115628) | 3 |
| Recovered under E-B | **2** |
| Remaining after B1 | 10 |
| — of those, with edge as the sole blocker at every native-readable oracle frame | **8** |
| — 00115627: a b1-only (sharpness-only) native-readable frame 2; B1 held frame 4 instead (it reads in Phase 2) | 1 |
| — 00129529: a qualified, readable oracle frame 38 that was not kept | 1 |

Per-Track detail is in `account.json` → `ceiling.tracks`.

00115627's B1 crop is at an unlabelled frame, so it is unmeasurable under E-B; Phase 2 shows that it reads.

**Repeat:** an independent second replay of each arm produced index files that are byte-identical to the first: A `1c9d84b0…` = `1c9d84b0…`, B `f999623e…` = `f999623e…`. `equal` reports canonical equality on every result, log, staging digest and gzip byte, in all 200 sequences.

## Phase 2 — #226 PD5/OC1-S path, offline (`plates-phase2.json` `e8113709…`)

**How it was run:** `b1_plates.py` runs each arm's sealed Vehicle crops through the product plate role's own code:
- `components_for` adapters `ppocr-db-onnx-v1` (PD5-V5M `a4319856…`) and `fast-plate-ocr-onnx-v1` (OC1-S `384bbbd2…`);
- the committed pilot parameters (`cce6ff6d…`);
- `analyse_crop` and `summarise_track`, in the plates venv.

The exact-search predicate (normalised truth text among the associated Track's texts) is evaluated offline. **It is not the live API or catalogue.** No pilot catalogue was touched.

**Parity with the live #226 pilot:**
- Arm A's crops on the pilot's 70 sequences equal the pilot's exported evidence: 5,806 = 5,806.
- Offline Arm A gives **52/110 hits, agreeing with the pilot on 110/110 Tracks** (45 among the oracle-readable).

**Result:** hits **52 → 56 / 110**, with 0 lost; among the oracle-readable, 45 → 47. All four gains come from a B1-admitted NearView, the only change on each Track:

| GT Track | Oracle-readable | E-B status |
|---|---|---|
| 00121309 | yes | also an E-B gain |
| 00115627 | yes | crop at an unlabelled frame |
| 00121825 | no | — |
| 00118035 | no | — |

- 00115628 gains under E-B but not in search, so OCR or detection still fails on it.
- **Other returned Tracks:** 18 → 19. In B one more Track carries the text of the unassociated GT Track 00121843, and its identity is unverified. This is the same open question as the pilot's 13 extra hits.
- **Repeat:** byte-identical output.

## Recommendation — **C: propose a separate owner O3 decision** (frozen rule: 0 losses, net +2)

**Measured gain:** B1 recovers **2/79** E-B Tracks and **4/110** exact search hits, with no Track lost, no association change, unchanged Person and Representative evidence and +3.1 % evidence bytes. Any CPU cost is unresolved; it is within the run-to-run spread of the identical arm.

**What this does not establish:**
- The gain is below the observed ceiling of 3, and far below X1's 10. It does not change P3: even counterfactually, 55/79 = 0.696 is still below 0.70.
- It changes reading-preserving roles on 7 readable Tracks: 6 lose a reading role (their replacement crops are unmeasurable under the frozen labels, not shown to be worse) and 1 gains one. Phase 2 found no search loss on any of them.
- As evidence of generalisation it is weak. +2/79 is a deterministic same-data count; an exact paired test with 0 vs 2 discordant Tracks gives one-sided p = 0.25. The result is hypothesis-generating.
- So C is strictly an **owner O3 proposal**, conditional on independent validation and full requalification. It does not recommend adopting the change.
- It is a same-data follow-on of the exploratory study, on 5 fps BDD100K (US/Israeli). It is not Indian-domain or Production evidence.

**Contents of the O3 proposal:**
1. A NearView-only, scale-normalised sharpness assessment as a candidate profile change.
2. Before it is adopted:
   - validation on a population that did not inform the hypothesis (for example, native-fps footage under O1A/O1B);
   - a decision on the reading-role redundancy lost on 6 Tracks, the 17 unmeasurable replacement crops and the one additional unverified text return;
   - full requalification (ADR-013 §6, ADR-009).

The dominant residual selection blocker is edge contact. It is the sole blocker at every native-readable oracle frame for 8 of the 10 remaining matched failures, and it alone blocks 4,168 of the candidates that pass B1 sharpness. Any edge hypothesis still needs new proof (X1).

## Limitations

- **Same-data, post-hoc-selected hypothesis.** The counts are small (2 of 79; 4 of 110), and no confidence interval is claimed.
- **Labelled-frame sparsity.** 17 B-side crops on text-usable Tracks are unmeasurable under E-B (11 B1 NearViews, 6 cascade crops). Phase 2 measures real OCR on all crops, but the search predicate is offline, not the live platform.
- **Association.** 14 of 79 failures are tracking or association failures at 5 fps; B1 cannot affect them.
- **Accounting defect.** The first accounting run (`7dc4e497…`, kept as superseded) flagged every Representative as changed, because it compared storage keys that embed each arm's ProcessingRun id. It was corrected to compare SHA-256, size and frame (`860cc4b6`). No input, run or rule changed.
- **Historical 51/77 control.** The AI-label control was not recomputed for B1; it is not the decision population.
- **Freeze attestation (cold review P3-1).** Freeze-before-outcome is attested only by local commit timestamps and file times. All four commits were first pushed together, so there is no external anchor.
- **Tamper detection (P3-2).** A consistent rewrite of a log and its index digests passes `verify`; only the committed index SHA-256 catches it. Some expected input hashes (the X1 indexes, O5 truth/E-A/E-B, verdict, descriptor) are checked by an 8-hex prefix only.
- **Code identity of outputs (P3-3).** `account.json` was produced by the `b1_eval.py` fix about 28 s before it was committed in `860cc4b6`. Neither `account.json` nor `plates-phase2.json` records a code identity. The retained inventory binds `bb5b0877`'s file hashes, so a reproduction at head needs a regenerated inventory.
- **Phase 2 tool (P3-8).** `b1_plates.py` does not run `verify` and does not check that each evaluation is bound to its arm index; it checks result and crop SHA-256s only. It does not measure wrong-text false positives: Tracks carrying any text go from 311 to 315.

## Independent cold review

Independent cold review of `bc3576ad` (`E:\MAVI-Working\checkpoints\pr232-cold-review.md`): **CODE CONVERGED, no P1/P2.** Recommendation C is confirmed as the frozen rule's correct output. Its P3 corrections to this report are applied above. No code, input, run, frozen record, result or decision changed.

## Identities

All outputs are outside Git, under `E:\MAVI-Working\b1\`: `inventory.json`, `preflight/`, `A/`, `B/`, `repeat/{A,B}/`, the evaluations, `account.json` and `plates-phase2.json`, with the hashes above.

**Code commits:**
- `a184cb1e` (freeze);
- `bb5b0877` (implementation; the runs and inventory bind its file hashes);
- `860cc4b6` (Phase 2 tool; accounting control fix).
