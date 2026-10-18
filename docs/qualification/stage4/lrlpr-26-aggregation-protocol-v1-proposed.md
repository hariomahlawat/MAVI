# Stage 4 — LRLPR-26 Multi-frame Aggregation Protocol v1 (PROPOSED)

**Date:** 2026-10-18.
**Status:** PROPOSED, for owner review.
- Nothing has been run.
- The protocol is frozen only when the owner approves it. The commit that freezes it adds the split file and the frozen candidate JSON.

**Class:** Development only. No training, no Production change, no profile change; O3 stays open.
**Data:** `lrlpr-26-dataset-record-2026-10-18.md`. Train split only, because the held test archives have no labels.

## Question

Given five LR frames of one plate, which text-level aggregation policy gives the best trade-off between correct text accepted and incorrect text accepted? The OCR is MAVI's existing one: OC1-S, fast-plate-ocr `cct_s_v2_global`, through the `fast-plate-ocr-onnx-v1` adapter.

**What this answers:** it isolates the aggregation stage.

**What it does not answer:**
- detection, association or wrong-Track behaviour;
- Indian-domain performance;
- MAVI's 52/110 search figure.

Its numbers are never compared on a shared denominator with E-B, the pilot, B1 or X4-0.

## Adapter (minimal)

The adapter is `tools/benchmarks/datasets/lrlpr26.py`. It is read-only and has no new dependencies; Pillow and the plates venv are already declared.

**What it does:**
1. Discovers `train/<Scenario>/<Layout>/track_NNNNN/`. It accepts exactly `lr-001…005` and `hr-001…005` plus `annotations.json`, and fails closed on anything else.
2. Emits one `CropTrack(track_id, scenario, layout, lr_frames[5], truth)`, where `lr_frames` are paths and SHA-256 values in frame order.
   - Truth is normalised by MAVI's existing `normalise()`. There is no format-based correction.
   - Corners and HR frames are read but not used as recognition inputs.
3. Binds every run to an inventory: the per-file manifest SHA plus the archive SHA. A changed byte fails the run.

**What it does not do:**
- It does not touch `benchmark-plate-truth-v1`. That contract is built around scene images with plate regions, and crop tracks do not fit it.
- It does not revise any contract. The experiment consumes `CropTrack` directly; a contract revision is deferred until there is a reason to make one.

**Tests:** synthetic fixture tracks only. No dataset bytes or plate strings enter Git.

## Split (deterministic, plate-text-grouped)

**Grouping unit.** Tracks are joined (union-find) when they:
- share a normalised plate text; or
- share any byte-identical image (20 hash groups, 4 tracks).

**Assignment.** Each component goes to EVALUATION if `int(sha256("lrlpr26-split-v1|" + min_text_in_component), 16) % 2 == 1`, and to DEVELOPMENT otherwise.

**Measured on the held train (counts only).** The split comes out near 50/50 in every stratum:

| Stratum | DEV | EVAL |
|---|---:|---:|
| A / Brazilian | 2,547 | 2,453 |
| A / Mercosur | 2,490 | 2,510 |
| B / Brazilian | 1,001 | 999 |
| B / Mercosur | 3,975 | 4,025 |

**Split file.** `lrlpr-26-split-v1.json` holds `track_id → DEV|EVAL`, its SHA and the stratum counts. It holds no texts and no text hashes. A hash of a plate string can be reversed by enumerating the small plate format space, so it would leak the plate.

### Scene/session leakage check

The metadata permits only a limited check:
- Images carry no EXIF or timestamps; Scenario-B JPEGs have only JFIF headers.
- The only session proxy is track ID order. IDs are unique across folders and run by scenario: A is 1–10,000 and B is 10,001–22,999.

**Repeated plates are mostly recurring vehicles, not the same pass.** The gaps between consecutive repeats of one text have a median of 954 IDs. Only 210 of the 3,054 gaps are ≤100 IDs, and only 4 are ≤1.

**Session control is not achievable alongside plate grouping:**
- Combining ID blocks of 50–500 tracks with text grouping collapses each scenario into one component holding 50% of all tracks.
- A block split that excludes the conflicting tracks loses 1,484–1,738 EVAL tracks and unbalances the strata.

**Accepted residual risk.** DEV and EVAL share one camera per scenario and overlapping capture periods. This is acceptable because the experiment tunes at most two thresholds and trains nothing.

**Sensitivity check.** The frozen thresholds are re-scored on a block split (500-ID blocks, conflict tracks excluded). The result is reported but is not a decision input.

## Policies (LR frames only as recognition inputs)

Each LR frame is read once, at the adapter's own preprocessing. A reading counts only if `normalise()` returns OK, the same rule `summarise_track` uses.

| Id | Policy | Track output |
|---|---|---|
| S1 | Single fixed frame (`lr-005`) | Its text. This is a cost floor and needs no aggregation |
| SB | Single best | The reading with the highest confidence. Ties go to the lowest frame index |
| U | Union. This is MAVI's current semantics (distinct rank-0 texts, as in `summarise_track`) | The set of all distinct texts |
| C | Consensus | The plurality text, if its support is ≥ k (k ∈ {2, 3}, chosen on DEV). Otherwise it abstains; ties abstain |
| A | Confidence-weighted abstention | The winner is the text with the largest summed confidence. It is accepted if its weight share is ≥ τ; otherwise the policy abstains |

**Thresholds.**
- k and τ are chosen on DEV only, from the precision-coverage curve. Each is set at the highest coverage where incorrect-text acceptance stays ≤ 1.0% of DEV tracks, so the precision target is fixed now, not after seeing results.
- The thresholds are then frozen and applied once to EVAL.

**Secondary frame-budget check.** SB, U and A are also run on the first k frames, for k = 1, 3, 5. The frame selection is fixed, not adaptive.

## Measures (per track, on EVAL)

- **Recall:** correct text accepted / tracks. For U, a track counts as correct if the truth is in the set.
- **Incorrect-text acceptance:** tracks with any accepted text that is not the truth, divided by tracks. U also reports the mean number of wrong texts per track.
- **Precision:** correct / accepted.
- **Coverage:** accepted / tracks. An abstention is neither correct nor incorrect.
- **Cost:** OCR invocations per track, and CPU time per track. CPU time is the median of three timed repeats on one machine, with ORT threads fixed.
- **Reporting:**
  - Results are reported per stratum, by scenario and by layout.
  - 95% confidence intervals use a bootstrap that resamples whole plate-text components (2,000 resamples, fixed seed).
  - Paired policy comparisons use McNemar's test on the same tracks.

## Frozen decision rule (primary comparison: A against U on EVAL)

- **SUPPORTED:**
  - A's incorrect-text acceptance is lower than U's, and the upper bound of the 95% CI on (A − U) is below 0;
  - and A's recall loss against U is ≤ 3.0 percentage points, with the CI upper bound ≤ 5.0.
- **NOT SUPPORTED:**
  - the wrong-text reduction CI includes 0;
  - or the recall loss upper bound is > 5.0 percentage points.
- **INCONCLUSIVE:** anything else, including a repeat mismatch or an inventory failure.
- C and SB are reported descriptively.
- A result here informs the O3 aggregation question only. It does not change `summarise_track`, search or any Production profile.

## Controls and caveats

- **Determinism:** a repeat run must give canonical-equal outputs before any result is read.
- **Label noise:** the labels are semi-automatic, so some "incorrect" texts may be label errors.
  - Optional diagnostic: a human check of up to 100 EVAL tracks where A accepted a wrong text at high confidence, against the HR frames. This is small diagnostic labelling (ADR-017) and the result is reported separately.
  - HR frames are not used as recognition inputs, because the labels were derived from them, which would make the result circular.
- **Exposure:** the training data of fast-plate-ocr's global model is not documented here and may include Brazilian plates. Absolute accuracy may therefore be optimistic, while policy differences on the same model are less affected.
- **Scale:** 20,000 tracks × 5 frames is 100,000 CPU OCR calls. At the pilot's per-crop rate this is expected to take well under an hour.
