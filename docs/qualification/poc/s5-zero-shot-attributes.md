# PoC S5: zero-shot attributes, calibration note

**Status:** IN PROGRESS. Protocol v2 is frozen and committed, the held Tracks are selected and scored, and the **labels are not yet entered**. The thresholds in `src/vision/config/attributes/parameters-siglip2-zero-shot-v1.json` are therefore the **provisional uncalibrated value 0.5 for every attribute**. Register row C2.1 stays IN PROGRESS until the calibration result below is entered.
**Evidence class:** Development (ADR-020). Zero-shot, Development; not qualified, not a Stage-2 S2c learned Model Pack, and closing no Stage-2 F/G row.
**Governing:** plan slice S5; ADR-021 and its 2026-10-29 amendment; register rows C2.1 and C2.2.

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

## 5. Calibration result

**Not run: waiting for owner decision S5-1, the label source.** Once the labels exist, `tools/poc/attributes_zero_shot_spike.py calibrate` writes `calibration.json` and `thresholds.json`, and `tools/poc/attributes_zero_shot_profile.py --thresholds` regenerates the release. The thresholds become a new identity; the old one reads as Stale. The per-attribute thresholds, precision and coverage then go here.

## 6. Honest limits

- **Domain.** The held crops are US dash-camera footage (BDD100K), not fixed CCTV. Person crops are small, and lighting and compression differ from the demo corpus.
- **Generalisation.** A threshold that meets 0.80 precision on about 50 calibration crops per class is a Development scope, not a qualified operating point. The check-half interval states how wide the uncertainty is.
- **Zero-shot only.** No training or fine-tuning is done; a learned Model Pack is Stage-2 S2c's.

## 7. Evidence

The folder `E:\MAVI-Controlled\PoC\S5\spike\` (protocol v2) contains `selection.json`, `scores-cpu.json`, `labels-template.csv`, `contact-sheet.html` and `SHA256SUMS`. The withdrawn v1 outputs are in `E:\MAVI-Controlled\PoC\S5\spike-v1-withdrawn\`, also with `SHA256SUMS`. When calibration runs, it will also hold `labels.csv`, `calibration.json` and `thresholds.json`.
