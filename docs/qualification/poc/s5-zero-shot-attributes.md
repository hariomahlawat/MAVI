# PoC S5: zero-shot attributes, calibration note

**Status:** **Uncalibrated by owner decision S5-1, option D (2026-10-30).** Every attribute ships with the predeclared threshold 0.5 and the disclosure "zero-shot, uncalibrated, Development" (release identity aa9a83bc…d82a).

- **The trial is feasibility evidence only.** The protocol v3 tuning on UPAR over PA-100K (§5) was run and is kept as evidence that calibration is feasible. Its thresholds are **not** shipped.
- **What it showed.** Lower clothing colour stayed at 0.38–0.45 precision at every threshold, and headwear could not be measured. The owner chose to disclose the limitation rather than tune it.
- **Scope extension.** The owner's evaluate-to-tuning extension record is marked unused.
- **Labels.** No owner labels were made, and no AI-made label counts as calibration.

## 1. What is calibrated

The SigLIP 2 base Model Pack of S4 (`embeddings-siglip2-base-p16-224-dev-v1`) scores each crop against prompt-ensembled text prototypes, over the frozen attribute vocabulary (`tools/qualification/attributes/corpus/data/attribute-task-v1-candidate.json`). It covers:

| Attribute | Values | Kind |
|---|---|---|
| `person-upper-colour`, `person-lower-colour` | the 11 candidate basic colours | categorical, softmax over values |
| `vehicle-colour` | the 11 candidate vehicle colours | categorical |
| `person-carried-bag` | `present` | presence: bag or backpack, the candidate merge `person-carried-bag` |
| `person-headwear` | `present` | presence |

A presence attribute is never asserted absent (Stage-2 plan §13). `multicolour` (conditional in the candidate vocabulary) is not offered. The prompts are in the committed parameters, and their SHA-256 is part of the analysis identity.

Each attribute's abstention threshold `t` is mapped onto the `mean-score-argmax` policy's 0.5, so a row is Observed only when its value's mean (abstention-normalised) score reaches it, and Unknown otherwise. Calibration means choosing `t` per attribute.

## 2. Method problem found before running

The plan asked for thresholds from held crops of the S4 spike set. That set cannot answer the question, for two reasons:

- **No labels.** The S4 crops come from the BDD100K H3 exports, which carry no colour, bag or headwear labels.
- **Too few persons.** Its selections hold only 4–18 Person crops of at least 80 px.

The only labelled attribute datasets MAVI has cleared are PA-100K and UPAR. R-5 approved them for evaluation only; choosing a threshold is tuning, which is not approved (`E:\MAVI-Controlled\Evidence\S2c\2026-10-02-r5-pa100k-upar-eval\03-r5-decision-record.json`). This was reported to the coordinator before any calibration ran, as owner decision **S5-1**.

## 3. Frozen protocol (`docs/qualification/poc/s5-zero-shot-protocol-v2.json`)

**Protocol v1 is withdrawn.** v1 (`s5-zero-shot-protocol-v1.json`, committed in `d6262172`) was withdrawn on 2026-10-30, before any label existed. It thresholded one crop's softmax `p`. That is not the decision the runtime ships, which averages the abstention-normalised score over **every** crop of the Track and scores small crops as zero (cold review P2-1). v1's selection and scores are kept, unchanged, in `E:\MAVI-Controlled\PoC\S5\spike-v1-withdrawn\`.

**v2 is committed before any label exists.**

- **Held set.**
  - Seeded (`202610295`) from the same read-only H3 exports.
  - 100 Person and 100 Vehicle Tracks, each with at least one crop of shorter side ≥ 80 px. Every accepted crop of the Track is kept, and each crop's hash is checked.
  - At most 4 Tracks per run.
  - Split into seeded halves: calibration (even index) and check (odd index).
- **Labels.** One label per Track and attribute, judged from all the Track's crops, which the contact sheet shows side by side. Every applicable cell must be labelled; `calibrate` refuses a missing or out-of-vocabulary label.
- **Decision measured.** It is the runtime's own: `abstention_score` per crop, then `aggregate_track` (`mean-score-argmax` at 0.5). The spike calls the same functions.
- **Rule.** For each attribute, take the smallest threshold on the grid 0.30, 0.35 … 0.95 whose calibration-half Track precision is at least **0.80**, with at least **8** Observed rows. If no grid value qualifies, use 0.99.
  - An Observed decision on a Track labelled `unscorable` or `absent` counts as wrong.
  - An abstention counts only against coverage.
- **Reporting.** Check-half Track precision, with a Wilson 95% interval, and coverage. Thresholds are never re-chosen on the check half.

## 4. Held set and scores (raw outputs in `E:\MAVI-Controlled\PoC\S5\spike\`)

The selection read 369 eligible Person Tracks (100 chosen from 45 runs, 167 crops) and 4,031 eligible Vehicle Tracks (100 chosen from 69 runs, 202 crops). No crop failed its hash check. All 369 crops were scored on CPU (ONNX Runtime 1.31.0, `embeddings-onnx-v1`); crops under 80 px are recorded as small and score zero.

For orientation only, the withdrawn v1 run gave these unlabelled distributions of the top softmax `p` on the largest crop of the same seeded Tracks:

| Attribute | p10 / p50 / p90 of top `p` | Top-value counts (largest) |
|---|---|---|
| `person-upper-colour` | 0.34 / 0.64 / 0.91 | black 36, white 17, blue 15 |
| `person-lower-colour` | 0.34 / 0.58 / 0.88 | black 38, white 17, blue 16 |
| `person-carried-bag` | p(present) 0.04 / 0.21 / 0.72 | `present` > 0.5 on 26 of 100 |
| `person-headwear` | p(present) 0.01 / 0.10 / 0.41 | `present` > 0.5 on 5 of 100 |
| `vehicle-colour` | 0.38 / 0.71 / 0.96 | black 40, grey 17, white 15, silver 13 |

## 5. Trial calibration (protocol v3, `docs/qualification/poc/s5-zero-shot-protocol-v3.json`): feasibility evidence, not shipped

The protocol was frozen in `dc83dd51` before the tuning run. The owner's scope extension from "evaluate" to "tuning" for the UPAR and PA-100K releases is recorded in `E:\MAVI-Controlled\Evidence\S5\2026-10-29-owner-tuning-scope-extension.json` (SHA-256 `118622df…`). It is the owner's decision, not an R-5 licence ruling. Whether ShareAlike attaches to the tuned thresholds is still undecided.

**Data.** UPAR Task-1 labels over PA-100K images, read in memory from the pinned archive.
- **Tuning split:** PA-100K official train.
- **Held split:** PA-100K official test.
- The splits are image-disjoint. PA-100K has no identity or scene ids, so identity and scene disjointness is not claimed.
- Each split is 1,500 images with shorter side at least 80 px. Only 42% (tuning) and 38% (held) of the examined images reach that floor.
- Each image is a one-crop Track, decided through the runtime's own `abstention_score` and `aggregate_track`.

**Scoring.** 3,000 images on CPU (`embeddings-onnx-v1`), about 11 minutes.

| Attribute | Threshold | Held precision (Wilson 95%) | Held coverage | Outcome |
|---|---|---|---|---|
| `person-carried-bag` | **0.55** | 0.846 (0.807–0.879), 325/384 | 25.6% | target met on tuning (0.816, 423 Observed) |
| `person-upper-colour` | **0.80** | 0.797 (0.756–0.833), 338/424 | 28.3% | target met on tuning (0.818, 488 Observed); held point estimate just under 0.80 |
| `person-lower-colour` | 0.99 (fallback) | 0/1 | 0.07% | target **not met**: tuning precision 0.38–0.45 at every threshold, so the attribute is effectively always Unknown |
| `person-headwear` | 0.99 (fallback) | none Observed | 0% | target **not met** with at least 20 Observed (0.71 at 0.55, 24 Observed), so the attribute is effectively always Unknown |
| `vehicle-colour` | **0.5**, predeclared | not measured | not measured | uncalibrated rule, committed in `d6262172` before any demo-corpus run |

**Why lower colour fails** (hypothesis, not tested). UPAR's lower-body colour is often grey or black trousers on small, low-contrast crops, and the "trousers / pants / skirt" prompts do not separate them well. Changing the prompts would need a new protocol and is not done here.

**Release.** The trial thresholds were applied briefly as identity `11f06733…10e4`, which was used for the `e2e-v3` run. Owner decision S5-1 option D (2026-10-30) replaced them with the predeclared 0.5 for every attribute and the uncalibrated disclosure. The shipped identity is `aa9a83bc…d82a`.

## 6. Honest limits

- **Calibrated domain.** The person thresholds come from PA-100K surveillance crops, a different source from the demo cameras. They are a Development scope, not a measured accuracy for the demo cameras.

- **Domain.** The held crops are US dash-camera footage (BDD100K), not fixed CCTV. Person crops are small, and lighting and compression differ from the demo corpus.
- **Generalisation.** A threshold that meets 0.80 precision on about 50 calibration crops per class is a Development scope, not a qualified operating point. The check-half interval states how wide the uncertainty is.
- **Zero-shot only.** No training or fine-tuning is done; a learned Model Pack is Stage-2 S2c's.

## 7. Evidence

The folder `E:\MAVI-Controlled\PoC\S5\spike\` (protocol v2) contains `selection.json`, `scores-cpu.json`, `labels-template.csv`, `contact-sheet.html` and `SHA256SUMS`. The withdrawn v1 outputs are in `E:\MAVI-Controlled\PoC\S5\spike-v1-withdrawn\`, also with `SHA256SUMS`. No labels were made for it. The protocol v3 run is in `E:\MAVI-Controlled\PoC\S5\upar\`: `selection.json`, `scores-cpu.json`, `calibration.json`, `thresholds.json` and `SHA256SUMS` (SHA-256 `55ec78a7…`).
