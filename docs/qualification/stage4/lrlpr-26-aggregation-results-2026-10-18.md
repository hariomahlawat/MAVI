# Stage 4 — LRLPR-26 Multi-frame Aggregation: Execution Record (2026-10-18)

**Class:** Development only. Production, VisionJob, `summarise_track`, search, plate contracts, release profiles and the frozen P3 evidence are all unchanged. O3 stays open.

**Outcome: STOPPED BEFORE PHASE 4.** The methodology gate (`AGENTS.md`, *Experimental methodology*) stopped the run.

| Question | Answer |
|---|---|
| Is the run INVALID? | No. Every integrity check passed |
| Was EVAL scored? | No |
| Was EVAL truth compared? | No. EVAL truth was never compared with any OCR output or scored. EVAL annotations were read only to build or regenerate the split and to re-verify the annotation digest |
| Is there a decision? | None of SUPPORTED, NOT SUPPORTED or INCONCLUSIVE is claimed |

The DEV phase shows that the frozen decision rule cannot answer the recall half of the question on this OCR. The reason is explained under *Why the run stopped*. The owner decides what happens next.

## Owner decision: v1 closed as METHOD-LIMITED (2026-10-18)

The owner closed v1 as **METHOD-LIMITED / STOPPED BEFORE EVALUATION**. v1 EVAL will not be run.

**Why it is method-limited.** The run passed its integrity checks, but it did not establish a valid comparative aggregation result. The principal failure was the baseline OCR's lack of capability: OC1-S cannot read the LRLPR-26 LR crops.

**What this does not show.** It does not establish that consensus or temporal aggregation is inherently ineffective.

**What stays unchanged:**
- the frozen protocol, thresholds and outcome (`2c7d4732`), which are not revised retrospectively;
- the implementation;
- the DEV selection and the diagnostics;
- the cold-review findings and corrections;
- the controlled evidence, manifests and hashes;
- the DEV/EVAL split.

**State of the EVAL partition.** EVAL annotations were accessed only for split generation and digest verification. EVAL truth was never compared with OCR results or scored.

**The dataset.** LRLPR-26 remains an authorised research dataset.

This record holds aggregate counts only. It contains no plate text, no per-track text and no image.

## Frozen identities

| Item | Identity |
|---|---|
| Protocol | `lrlpr-26-aggregation-protocol-v1.md`, revision 3, FROZEN at `2c7d4732` (PR #234) |
| Rules | `lrlpr-26-aggregation-rules-v1.json` `3c14f0523adfb9dae7b434cf141ce8447aaa04c81ca8db789a7aa0ac1c1684be`, with pre-execution resolutions R1–R8 |
| Split | `lrlpr-26-split-v1.json` `5c06efa964dcaaa9c8edbf3aa19fb318b8b2d0d89cc8b1b77e14624854f9d138` |
| Data | `train.zip` `fb95f86dbf5666ce…7f7c9fb8f` (R8 correction); per-file manifest `efa5bb08…e72b8c` |
| OCR | OC1-S `cct_s_v2_global.onnx` `384bbbd2cea3ef54761d3df70822ef3a349ee1a112aeafddbe0e3ba06bc6e47b`; plate config `0335c74a305173bb6f393efed0fde03cadeaa0b649ed8e19f431016d8232d0a6` |
| Floor | `development-plates-onnx-pilot-parameters-v1.json` `cce6ff6d548aedc5fbffd32e30e97e1be3aa4cfb7e877ad6b2ed814805cc6d8e`; `ocrConfidenceFloor` 0.5, inclusive |
| Tooling | `60d784d5` |
| Inventory | `112b1b30d6109c4d6a15a0101f9db00eb52cd71434056ca405f130fe7c557a8a` |
| Selection record | `lrlpr-26-selection-v1.json` `fc2b0e145c210b3383c095f32ced0597a741a32c05e66f6af8ca34da707f2021`, committed `dac0795b` |

**Data checks.**
- Phase 0 hash-bound all 200,000 images, all 20,000 annotations, both archives and the manifest.
- It regenerated the committed split byte-identically from the data.

**Pre-execution resolutions** (recorded in the rules before any OCR call):
- **R1.** The protocol's split formula is applied as written, with the `lrlpr26-split-v1|` prefix. The protocol's own stratum table came from an unprefixed probe. Actual DEV/EVAL counts:

  | Stratum | DEV | EVAL |
  |---|---:|---:|
  | A/Brazilian | 2,440 | 2,560 |
  | A/Mercosur | 2,533 | 2,467 |
  | B/Brazilian | 1,038 | 962 |
  | B/Mercosur | 4,077 | 3,923 |
  | **Total** | **10,088** | **9,912** |

  There are 16,946 plate-identity groups.
- **R8.** The dataset record's `train.zip` SHA-256 had a one-digit transcription error. Before correcting it, every `train.zip` member was checked: all are byte-equal to the LFS-authenticated `data.zip` `train.tar`.
- **R2–R7.** These cover the image grouping, the block-split definition, exact arithmetic in A, the third timing pass, output-contract ineligibility and the measures counted in step 2. See the rules file.

## Phases 1, 2 and 2T: OCR read

OC1-S read 100,000 LR frames per pass, using the unchanged `FastPlateOcrRecogniser.read` with `cpu_session`.

**Integrity.** The phase-1, phase-2 and phase-2T records are **canonical-equal**: records SHA `c8e19855…669bc`, gzip bytes also equal.

**Frame status:**

| Status | Frames |
|---|---:|
| `ok` | 98,651 |
| `empty` | 1,349 |
| `ocrError` | 0 |
| `outputInvalid` | 0 |

**Cost.** Each value is the median of the three passes, over all 20,000 tracks. The cost is truth-free.

| Measure | Value |
|---|---:|
| OCR calls per track | 5 (S1: 1) |
| OCR CPU per track | 625 ms (S1: 125 ms) |
| Image decode | 1.2 ms per track |
| Wall time per pass | 1,559 s |

**Run conditions.**
- **Machine:** Intel64 Family 6 Model 165, 12 logical CPUs, Windows 11, Python 3.12.10, onnxruntime 1.31.0.
- **ORT settings:** 10 worker processes, each with 1 intra-op and 1 inter-op ORT thread.

Per-call CPU under 10 concurrent workers is about 125 ms. A single-process synthetic probe measured about 45 ms (no evidence file retained), so contention probably inflates these figures. Aggregation cost was not measured, because it belongs to the phase-4 scorer, which was not run.

## Phase 3: DEV selection (10,088 tracks)

| Policy (DEV) | Correct-text recall | Incorrect-text acceptance | Precision (pairs) | Coverage | Wrong texts / track | Tracks with 0 / 1 / ≥2 wrong |
|---|---:|---:|---:|---:|---:|---|
| S1 | 69 (0.68%) | 4,445 (44.06%) | 1.53% (69/4,514) | 44.75% | 0.441 | 5,643 / 4,445 / 0 |
| SB | 86 (0.85%) | 7,272 (72.09%) | 1.17% (86/7,358) | 72.94% | 0.721 | 2,816 / 7,272 / 0 |
| U | 157 (1.56%) | 7,357 (72.93%) | 0.81% (157/19,374) | 72.94% | 1.905 | 2,731 / 2,146 / 5,211 |
| C(k=2) | 29 (0.29%) | 244 (2.42%) | 10.62% | 2.71% | 0.024 | — |
| **C(k=3) = C\*** | 9 (0.09%) | 33 (0.33%) | 21.43% (9/42) | 0.42% | 0.003 | — |
| C(k=4) | 2 (0.02%) | 10 (0.10%) | 16.67% | 0.12% | 0.001 | — |
| C(k=5) | 0 | 5 (0.05%) | 0.00% | 0.05% | 0.0005 | — |
| A(τ=0.50) | 12 (0.12%) | 103 (1.02%) | 10.43% | 1.14% | 0.010 | — |
| **A(τ=0.60) = A\*** | 11 (0.11%) | 54 (0.54%) | 16.92% (11/65) | 0.64% | 0.005 | — |
| A(τ=0.70) | 3 (0.03%) | 24 (0.24%) | 11.11% | 0.27% | 0.002 | — |
| A(τ=0.80) | 2 (0.02%) | 16 (0.16%) | 11.11% | 0.18% | 0.002 | — |
| A(τ=0.90) | 0 | 11 (0.11%) | 0.00% | 0.11% | 0.001 | — |
| A(τ=1.00) | 0 | 11 (0.11%) | 0.00% | 0.11% | 0.001 | — |

**Selection by the frozen rule:**
- **C\*:** k = 3. C is FEASIBLE: k = 2 is infeasible at 2.42%, and k = 3, 4 and 5 are feasible. Among the feasible ones, k = 3 has the highest recall.
- **A\*:** τ = 0.60. A is FEASIBLE: τ = 0.50 is infeasible at 1.02%, and τ = 0.60 has the highest recall among the feasible configurations.

These are observed DEV values. They are not EVAL results, and they serve only for selection and for this stop decision.

## Why the run stopped (methodology gate)

**Assumption the protocol needs.** OC1-S must read LR frames correctly often enough for "without losing too much correct recognition" to be testable. The step-1 recall targets are a point loss ≤ 3.0 percentage points and a CI upper bound ≤ 5.0 percentage points.

**Evidence against it (observed, DEV only):**
- U's correct-text recall is 1.56% (157/10,088).
- Only 203 of the 49,789 `ok` DEV frame readings equal the truth exactly. Most readings are 5 or more edits from the truth (37,491).
- *Inferred, not shown:* the shared harness path has no gross defect, and the LR crops are below OC1-S's working resolution.
  - This rests on a diagnostic outside the protocol, from which no result is drawn. On 300 DEV tracks (every 33rd DEV track; 151 Scenario A, 149 Scenario B), the identical OC1-S path read **273/300 `hr-005` frames exactly, against 4/300 `lr-005` frames**.
  - The HR agreement is partly circular, because the labels are semi-automatic OCR on the HR frames. It rules out a gross harness defect, but it is not evidence of OC1-S's HR accuracy.
  - The LR crop median is about 47–49 × 19 px. The 47×19 figure comes from intake validation; the cold review measured 49×19 on a 505-track DEV sample.
  - The diagnostics ran after `selection.json` was written and before it was committed. The file did not change: the committed copy is byte-equal to it.
- `diagnostics/hr-vs-lr-pipeline-check.json` and `dev-reading-distance.json` in the evidence store hold aggregate counts only.

**Conclusion this would invalidate.**
- Recall loss (U − X) can never exceed recall(U), which is about 1.6 percentage points on DEV. On EVAL, the 3.0 and 5.0 point targets could bind only if recall(U) roughly doubled, so the outcome is practically, not mathematically, fixed. The recall conditions of step 1 therefore hold for *any* policy, including one that always abstains, whose incorrect-text difference against U would be about −73 percentage points.
- Step 1 would return **SUPPORTED** for C\* and A\* by construction, through a floor effect, not because aggregation keeps recognition.
- The step-2 A\*-vs-C\* comparison would rest on about 10 correct tracks.
- Reporting that SUPPORTED would mislead the O3 aggregation question.

**What the DEV data does show** (observed, DEV only, not a decision):
- On LR crops, MAVI's union semantics accept a wrong text on about 73% of tracks.
- Consensus (k = 3) cuts wrong-text acceptance to 0.33%. Even so, most texts that reach consensus are wrong: precision is 21%.

**Continuation options (owner decision).** Each option except the first needs a new protocol revision, frozen before any further DEV reads.

**Outcome-informed knowledge, to be disclosed in any revision.** DEV already shows that C\* and A\* retain only 9/157 (5.7%) and 11/157 (7.0%) of U's correct tracks. Any recall floor or relative-retention criterion chosen now is outcome-informed. EVAL is still unscored, and its truth has never been compared with OCR output, so a corrected protocol can use it once.

1. **Close v1 as method-limited.** The question is not answerable with OC1-S on LRLPR-26 LR crops. EVAL stays unscored and O3 stays open.
2. **Base-capability gate plus a relative recall criterion.** Add a pre-EVAL gate requiring a minimum DEV recall(U), together with a relative-retention recall criterion, so the targets can bind. With OC1-S on LR crops the gate fails, which is itself the finding.
3. **A different recogniser that reads LR crops.** Rerun the frozen policies with a recogniser that reads LR crops at a useful rate.
   - The recogniser must not have been trained on the LRLPR-26 train split. Competition models are therefore contaminated for this population.
   - Any new model or dependency falls under the offline-dependency and licence rules.
4. **An established human-labelled multi-frame benchmark** on which OC1-S's per-frame accuracy is non-trivial (ADR-017 reuse-first).
5. **HR frames as recognition inputs.** HR frames are within OC1-S's working range, but their labels were derived from them by OCR. Wrong texts would be undercounted, so this option must be disclosed as partly circular.

If, once informed, the owner still wants the frozen phase 4 run, it can be executed as is and labelled as a limited run. The floor-effect limitation must then accompany every conclusion drawn from it. The tooling refuses phase 4 unless the run is bound to the committed selection record.

**Process lesson.** The failed assumption, that OC1-S reads LR crops at a non-trivial rate, could have been checked before the freeze with a small DEV probe. The methodology gate fired only after 3 × 100,000 OCR calls. Any future protocol revision includes a base-capability probe before it freezes.

**Known tooling notes for any reuse** (the run's validity is unaffected):
- `lrlpr26_eval.py` loads EVAL truth before checking the selection SHA; the check should come first.
- `verify` needs EVAL truth, so it is not a DEV-only backup check.
- Pool workers reload the model files without re-hashing them.

**Not run:**
- phase 4, the EVAL scoring with its bootstrap and McNemar;
- phase 5, the block-split sensitivity and the frame budget, both of which are defined on top of phase 4.

## Limitations

- **Evidence class.** This is in-domain evidence on a partition of the authors' training set. Brazil/Mercosur plates only, two scenarios, one camera each.
- **Not measured:** plate detection (bypassed by design), Track association and wrong-vehicle attachment, and the Indian domain. Nothing here is comparable with the 52/110 figure, E-B, B1 or X4-0.
- **Labels.** The labels are semi-automatic, produced by OCR on the HR frames.
- **Model exposure.** fast-plate-ocr's training data may include Brazilian plates. Even so, OC1-S's LR accuracy is near zero.
- **Session dependence.** Session and camera dependence between DEV and EVAL is accepted per the protocol.
- **Scope.** The stop concerns the method's ability to answer the question with this OCR. It is not a statement about multi-frame aggregation in general.

## Evidence

The evidence directory, which holds OCR raw texts, stays on controlled storage only:

| Location | Content |
|---|---|
| `E:\MAVI-Working\lrlpr26-exp\` | Working directory |
| `E:\MAVI-Controlled\Benchmarks\stage4-lrlpr26-agg\` | Byte-identical copy |
| `E:\MAVI-Controlled\Benchmarks\stage4-lrlpr26-agg.MANIFEST.sha256` | Manifest |

**Backup verification:**
- `lrlpr26_read.py verify --inventory` passed on all three passes.
- `lrlpr26_read.py equal` passed.
- The selection recomputed from the backup is byte-equal. No log of this check was retained. The cold review independently recomputed all 13 DEV configurations from `phase1/records.jsonl.gz`, and they match exactly.

The source data in `E:\MAVI-Controlled\Benchmarks\lrlpr-26\` was read only. Its archive SHA-256 values still match the corrected record.
