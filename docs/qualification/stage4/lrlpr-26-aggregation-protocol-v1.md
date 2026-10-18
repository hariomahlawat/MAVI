# Stage 4 — LRLPR-26 Multi-frame Aggregation Protocol v1 (FROZEN, revision 3)

**Date:** 2026-10-18.

**Status:** FROZEN on owner approval, 2026-10-18: "I approve freezing the revised LRLPR-26 multi-frame aggregation protocol and authorise its bounded Development-only implementation and execution." Frozen at the commit that renames this file from `lrlpr-26-aggregation-protocol-v1-proposed.md` (revision 3 content, commit `e0cce486`, unchanged apart from these status lines). Nothing had been run when it froze: no OCR call had been made on LRLPR-26 data. The freezing commit adds:
- `lrlpr-26-split-v1.json`;
- `lrlpr-26-aggregation-rules-v1.json`, which holds this document's grid, rules and seeds in machine form, plus the pre-execution resolutions R1–R8 made before any OCR call. Two of them correct facts stated here: R1 (the split formula below is applied as written; the stratum table below came from an unprefixed probe and is superseded by the counts in the split file) and R8 (the dataset record's `train.zip` SHA-256 had a one-digit transcription error, corrected in the record).

**Revision 2** applies the owner's corrections A–F of 2026-10-18:
- the confidence-weighted policy gains a fixed minimum of two agreeing readings;
- the selection and infeasible cases are defined;
- the measures are split into track-level and prediction-level;
- the primary statistics use a bootstrap over plate-identity groups;
- A is compared with C, and the simpler C is preferred when the two are equivalent.

**Revision 3** applies the owner's three pre-freeze corrections:
1. reading eligibility honours MAVI's OCR acceptance floor;
2. integrity failures yield INVALID, not INCONCLUSIVE;
3. the decision rule separates negative evidence from indeterminate evidence.

It also adds a guard against zero confidence weight in A.

**Class:** Development only. There is no training and no change to VisionJob, `summarise_track`, search semantics, plate-control contracts, release profiles or the frozen P3 evidence. O3 stays open.

**Data:** the train split only (`lrlpr-26-dataset-record-2026-10-18.md`), because the held test archives are unlabelled.

## Question and boundary

On a five-LR-frame plate-crop track read by MAVI's existing OCR, does temporal aggregation reduce incorrect plate texts compared with MAVI's union, without losing too much correct recognition? The OCR is OC1-S: fast-plate-ocr `cct_s_v2_global`, through the `fast-plate-ocr-onnx-v1` adapter.

**Evidence class.** The results are in-domain experimental evidence on a partition of the authors' training set: Brazilian and Mercosur plates, two scenarios from one camera.

**Not measured:**
- vehicle detection, Track association or wrong-vehicle attachment in congested scenes;
- Indian-domain performance;
- MAVI's end-to-end 52/110 figure.

**Consequence.** An improvement here does not resolve X4-0's wrong-Track returns; that question belongs to O1A. No number from this protocol shares a denominator with E-B, the pilot, B1 or X4-0.

## Adapter (minimal, read-only)

The adapter is `tools/benchmarks/datasets/lrlpr26.py`. It adds no new dependencies: Pillow and the plates venv are already declared.

**Steps:**
1. **Discover tracks.** It walks `train/<Scenario>/<Layout>/track_NNNNN/` and accepts exactly `lr-001…005`, `hr-001…005` and `annotations.json`. Anything else fails closed.
2. **Emit records.** Each track becomes a `CropTrack(track_id, scenario, layout, lr_frames[5], truth)`:
   - the LR frames are kept as paths and SHA-256 values, in frame order;
   - the truth is `normalise(plate_text)`, using MAVI's existing normaliser with no format-based correction.

   HR frames and corners are never recognition inputs.
3. **Bind to the inventory.** Each run is bound to the existing per-file manifests and archive SHA-256 values. Any changed byte fails the run.

**Contracts.** The adapter does not use or revise `benchmark-plate-truth-v1`. The experiment consumes `CropTrack` directly.

**Tests.** Tests use synthetic fixtures only. No dataset bytes or plate strings enter Git.

## Development/Evaluation split

**Grouping.**
- Tracks are joined by union-find when they share a normalised plate text or any byte-identical image (20 hash groups across 4 tracks).
- Each resulting component is one plate-identity group.

**Assignment.** A group is EVALUATION if `int(sha256("lrlpr26-split-v1|" + min_text_in_group), 16) % 2 == 1`, otherwise DEVELOPMENT.

**Measured stratum counts (DEV/EVAL):**

| Scenario | Layout | DEV | EVAL |
|---|---|---:|---:|
| A | Brazilian | 2,547 | 2,453 |
| A | Mercosur | 2,490 | 2,510 |
| B | Brazilian | 1,001 | 999 |
| B | Mercosur | 3,975 | 4,025 |

**Split file contents.** The split file holds `track_id → DEV|EVAL`, its SHA and these counts. It holds no texts and no text hashes, because plate-format hashes can be enumerated.

**Session and camera dependence (accepted and disclosed).**
- There is no session metadata: no EXIF and no timestamps.
- Track-ID separation is not proof of separate recording sessions, and the median gap of 954 IDs between repeats of one plate does not establish independence.
- DEV and EVAL share one camera per scenario and probably overlapping capture periods.
- Controlling for this is not feasible alongside plate grouping:
  - ID blocks combined with text grouping collapse each scenario into one group holding half the tracks;
  - a block split that drops the conflicting tracks loses 1,484–1,738 EVAL tracks.
- This residual dependence is accepted because only one threshold per policy family is selected and nothing is trained.

## Pipeline phases

1. **Read.** OC1-S reads every LR frame of all 20,000 tracks once. The rank-0 raw text and confidence are stored per frame. Nothing is scored.
2. **Repeat.** Phase 1 is run a second time, and the two outputs must be canonical-equal. Otherwise execution stops with INVALID (see *Integrity*).
3. **Select on DEV.** DEV tracks are scored and the thresholds selected by the rules below. The selection is written to `selection.json`, and its SHA is recorded before phase 4.
4. **Evaluate once.** EVAL tracks are scored once, with the policies bound to `selection.json`. The EVAL scorer refuses to run without a matching selection SHA, and EVAL truth is first compared in this phase.
5. **Secondary.** These run afterwards, are reported only, and never feed into the decision:
   - **Block-split sensitivity:** phases 3–4 rerun on a block split (500-ID blocks, conflict tracks excluded), with thresholds re-selected on that split's own DEV.
   - **Frame budget:** SB, U and the selected C and A on the first 1, 3 and 5 frames.

## Integrity (NO RESULT / INVALID)

Execution stops, and no scientific outcome is produced, on any of these failures:
- an inventory, manifest or archive hash mismatch;
- a phase-2 repeat that is not canonical-equal;
- a missing or mismatched `selection.json` SHA, or a parameter-file SHA mismatch;
- a split-file SHA mismatch;
- an adapter fail-closed error.

The run is then recorded as **INVALID**, with the cause. No partial metrics are reported as results. The run may be repeated only after the defect is fixed, with no change to the frozen rules.

## Readings

**Eligibility (common to S1, SB, U, C and A).** A frame's reading is eligible when both conditions hold:
1. **Floor.** Its rank-0 confidence is ≥ `ocrConfidenceFloor`. This is the rule that makes a plate `read` in `pipeline.py`. The floor is read from `src/vision/config/plates/development-plates-onnx-pilot-parameters-v1.json` (value 0.5, SHA-256 `cce6ff6d…`), and the run is bound to that file hash.
2. **Normalisation.** `normalise()` returns OK.

Together these reproduce exactly which readings `summarise_track` admits.

**Ineligible frames.** Empty output, a reading below the floor, a normalisation failure and an OCR error all make a frame ineligible. An ineligible frame:
- contributes no text, no support and no weight;
- still counts in the OCR-call cost.

**Plate detection stays bypassed.** This is intentional: each LR image is already a plate crop, and the experiment isolates OCR aggregation.

For each track, n is the number of eligible readings, from 0 to 5. The support s(t) of a text t is the number of eligible readings with that text, and w(t) is the sum of their confidences.

## Policies

| Id | Rule | n = 0 | n = 1 |
|---|---|---|---|
| S1 | Accept the reading of `lr-005` if it is eligible. Never consults other frames | abstain | accept, if the one eligible frame is `lr-005` |
| SB | Accept the eligible reading with the highest confidence. A tie goes to the lowest frame index | abstain | accept |
| U | Accept every distinct eligible text. This is MAVI's current union semantics: the floor plus `summarise_track`'s distinct rank-0 texts | empty (abstain) | accept |
| C(k) | Let t\* be the text with the largest support. Accept t\* if s(t\*) ≥ k and no other text has equal support | abstain | abstain (s < 2) |
| A(τ) | Let t\* be the text with the largest w. Accept t\* if s(t\*) ≥ 2, w(t\*) / Σ w(all eligible) ≥ τ, and no other text has equal w | abstain | abstain (s < 2) |

**Notes on the policies:**
- **Zero-weight guard in A.** If Σ w(all eligible) is zero or non-finite, A abstains. The adapter already rejects non-finite confidences, and the floor makes a zero total impossible, but the guard is explicit.
- **Secondary arm U-raw.** U-raw is the union of every normalised text with no floor. It is labelled secondary: it is **not** MAVI's current behaviour and is excluded from the decision rule.
- **Disagreement.** In A, conflicting readings stay in the denominator, so disagreement lowers t\*'s share. In C, conflicting readings take support from t\*.
- **Minimum support in A.** The fixed requirement of s(t\*) ≥ 2 removes the case where one unsupported reading holds 100% of the weight. No confidence calibration is added.
- **S1's fixed frame.** `lr-005` is the last frame. It is fixed in advance and is not chosen on any outcome.

**Threshold grids:**
- C: k ∈ {2, 3, 4, 5};
- A: τ ∈ {0.50, 0.60, 0.70, 0.80, 0.90, 1.00}.

τ = 1.00 means every eligible reading agrees and at least two exist.

## Threshold selection (DEV only)

The rules are applied separately to each family, C and A:
1. **Feasible configurations.** A configuration is feasible if its DEV incorrect-text acceptance is ≤ 1.0% of DEV tracks.
2. **Choosing among feasible ones.** Select the feasible configuration with the highest DEV correct-text recall. Remaining ties are broken by:
   1. lower incorrect-text acceptance;
   2. then the stricter threshold (larger k or τ).
3. **If none is feasible,** the family is **INFEASIBLE** at the target:
   - its strictest configuration (k = 5 or τ = 1.00) is still scored on EVAL;
   - it is labelled infeasible and reported descriptively;
   - it cannot be SUPPORTED.

S1, SB and U have no thresholds.

## Measures

Every policy is scored on the same EVAL tracks. Abstentions stay in the denominator.

| Measure | Definition |
|---|---|
| Correct-text recall | Tracks whose truth text is among the accepted texts ÷ all tracks |
| Incorrect-text acceptance | Tracks accepting at least one text other than the truth ÷ all tracks |
| Prediction-level precision | Correct accepted (track, text) pairs ÷ all accepted pairs |
| Coverage | Tracks with at least one accepted text ÷ all tracks |
| Wrong texts per track | Accepted non-truth texts ÷ all tracks, together with its distribution (0, 1, ≥ 2) |
| Cost | OCR calls per track (1 for S1, 5 otherwise), plus CPU ms per track |

**Measure conventions:**
- **Abstentions.** An abstention is neither correct nor incorrect. It lowers recall and coverage and is never removed from the denominator.
- **Union.** U can accept a correct and an incorrect text on the same track. That track then counts towards both recall and incorrect-text acceptance.
- **CPU timing.** CPU time is the median of three timed passes on one machine with ORT threads fixed. Aggregation cost is negligible and is reported as measured.

**Reporting.** Results are reported overall and per scenario/layout stratum.

## Statistics

- **Primary: paired bootstrap over plate-identity groups.**
  - Resampling unit: whole EVAL groups.
  - 2,000 resamples, seed `20261018`.
  - Output: percentile 95% confidence intervals for each paired policy difference on each measure.
- **Exploratory only:** track-level McNemar tests. Tracks within a group are correlated, so these p-values can overstate confidence.

## Decision rule (fully specified before execution)

### Step 1 — compare each selected, feasible family X ∈ {C\*, A\*} with U

X is **SUPPORTED against U** if both conditions hold:
1. **Fewer wrong texts.** The upper bound of the 95% CI on (incorrect-text acceptance of X − U) is below 0.
2. **Recall kept.**
   - the point estimate of the recall loss (U − X) is ≤ 3.0 percentage points;
   - and its CI upper bound is ≤ 5.0 percentage points.

### Step 2 — prefer the simpler policy

**If both C\* and A\* are SUPPORTED,** A\* is preferred only if both hold:
- the paired CI for A\* − C\* favours A\* and excludes 0 on at least one of correct-text recall, incorrect-text acceptance and coverage;
- and no measure has a CI that favours C\* and excludes 0.

Otherwise C\* is preferred. This is a simplicity default when an advantage for A\* is not demonstrated; it is not a claim that the two policies are equivalent. A higher OCR confidence alone is never a reason to prefer A\*.

**If only one of them is SUPPORTED,** that one is preferred.

### Step 3 — outcome (valid runs only)

A confidence interval that crosses zero does not show that there is no effect. NOT SUPPORTED therefore needs evidence against the predetermined targets, not merely an absence of evidence for them.

| Outcome | Condition |
|---|---|
| **SUPPORTED** | At least one family is SUPPORTED (step 1). Report the preferred policy (step 2) and its configuration |
| **NOT SUPPORTED** | Every family has negative evidence, meaning at least one of: (a) INFEASIBLE on DEV (the 1.0% target cannot be met); (b) the lower bound of the CI on (incorrect-text acceptance of X − U) is ≥ 0, so X does not reduce wrong texts; (c) the lower bound of the CI on its recall loss is above 3.0 percentage points, so the recall target is clearly missed |
| **INCONCLUSIVE** | Any other valid run. For example, a CI on the wrong-text difference that spans 0, or a recall-loss CI that straddles the 3.0 or 5.0 point limits. The evidence is reported as indeterminate, not as a negative result |

These conditions reuse only the predetermined 1.0%, 3.0-point and 5.0-point targets; no new thresholds are introduced.

**What an outcome can and cannot do:**
- It informs the O3 aggregation question for the owner and nothing else.
- It does not change `summarise_track`, search, profiles or Production.
- It decides no architecture.

## External validation (not a blocker)

The officially annotated test release, 3,000 tracks with text and layout labels, would give a stronger external check. The authorised route is the official request: the signed agreement, e-mailed from a university account to the first author. The owner's team may already have it through its approval.

If an authorised copy is obtained, the frozen `selection.json` policies are scored on it once, with no re-selection. That run gets its own record and must not delay or change this protocol.

## Caveats

- **Label noise.** The labels are semi-automatic, so some "incorrect" texts may be label errors.
  - Optional diagnostic (ADR-017 small diagnostic labelling): a human check, against the HR frames, of up to 100 EVAL tracks where the preferred policy accepted a wrong text.
  - It is reported separately and changes no outcome.
- **No HR inputs.** HR frames are excluded as recognition inputs, because the labels were derived from them.
- **Model exposure.** fast-plate-ocr's global training data may include Brazilian plates. Absolute accuracy may be optimistic, while policy differences on the same model are less affected.
- **Scale.** 2 runs of 100,000 CPU OCR calls each. At the pilot's per-crop rate this is expected to take about an hour or less.
