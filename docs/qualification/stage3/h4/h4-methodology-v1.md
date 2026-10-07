# Stage 3 H4 — domain-diversity methodology v1 (event `H4-2026-10-06`)

**Status:** frozen before any H4 inference. The machine-readable freeze is `h4-methodology-v1.json` beside this file; where the two differ, the JSON governs. **Governing:** ADR-017 (benchmark-first Development; §7 admissibility; §8 no silent contamination claims); ADR-014 2026-10-06 note (Development replacement bindings); the Stage-3 register (row H4); the S3.2d harness plan; `AGENTS.md` "Experimental methodology" (challenge → freeze → execute → cold review).

## 1. Question

Does the scale-1280 Development candidate retain useful detector, tracking and vehicle-subclass performance outside the BDD100K H3 domain? The comparison is on identical footage, against the scale-640 A2 Development reference. What domain-specific tracking cost accompanies any gain?

H4 is domain-diversity evidence. It is not another H3 optimisation, and it is not a Production qualification.

## 2. Producers (frozen by PR #174; unchanged)

| Arm | Producer | Component binding | Model Pack |
|---|---|---|---|
| reference | `a2-scale640` | `f7ace806…89b7` | `mavi-model-v2-86754e36…6700` |
| candidate | `a2-scale1280` | `03d3a00b…2fa3` | `mavi-model-v2-9f1f9f70…d871` |

- **Shared pipeline profile:** both arms run the one A2 Development pipeline profile `phase1-detection-tracking-a2` 1.0.0-development (`b4c6a6cf…e62e`).
- **Shared runtime:** one checkpoint, and the CUDA Runtime Pack `mavi-runtime-v2-89fd8bfc…3a1d`.
- **Causal difference:** the detector Model Pack only, meaning test Resize/Pad 640 against 1280.
- **Not compared:** the 0.70 release-reference profile.

## 3. Methodology challenge (recorded before freezing)

- **Confounding between arms.** Both arms run the same prepared MP4s, harness, mapping, association policy, requirements, frame time and evaluation tooling. Inside one domain, `h4.compare` refuses results that differ in anything but the producer. The PR #174 journal binding stops one arm's journal from resuming as the other.
- **Frame rate.**
  - VisDrone states no frame rate. 30/1 is declared as an assumption.
  - Both arms share the same assumed timing, so there is no explicit between-arm input asymmetry.
  - The paired result is still conditional on the assumed cadence. The A2 tracker's lifecycle is timestamp-sensitive (a 1.0 s lost buffer), and the two arms feed it different detector streams, so a different true cadence could change the two arms' tracking differently. (Corrected 2026-10-07; this is an interpretation correction only, and no input, run or frozen value changed.)
  - UAVDT's 30 fps is stated by its authors.
  - H3 ran at 5 Hz, so absolute rates are not comparable with H3 (§8).
- **Odd frame dimensions.**
  - Several VisDrone sequences are 1904×1071 or 1360×765, which libx264's 4:2:0 encoder refuses.
  - `prepare` pads them by one black row or column at the bottom or right; it never scales or crops.
  - It re-expresses the ground truth in the padded frame (the same pixels), and the manifest row records the padding.
  - Both arms see the same video.
  - This was found when the first preparation attempt refused these sequences, before any inference.
- **Effective scale.**
  - The candidate's canvas is 1280 for every source.
  - Its effective scale is min(1280/W, 1280/H), so it differs by source resolution. VisDrone ranges from 680×382 to 3840×2160; UAVDT is 1080×540.
  - Source resolution is recorded per sequence. The candidate is "test scale 1280", not "native".
- **Domain coverage.**
  - Both accessible sources are aerial (drone) video. They differ materially from BDD100K's dashcam footage, and from each other: UAVDT adds night, fog, altitude and view variation.
  - Fixed-camera traffic (UA-DETRAC) has no authoritative copy. KITTI requires registration. Both are recorded as unavailable, and no fixed-camera conclusion is drawn.
- **Taxonomy.**
  - VisDrone scores car, truck, bus and motor (as motorcycle). Its van, tricycle and awning-tricycle are vehicle-unresolved, and so remain in Scope A's expected-vehicle population.
  - VisDrone `others` (11) is "an object of no listed category", not evaluated by the VisDrone toolkits, so it is ignored on every frame. This was corrected after an independent cold review, before any inference.
  - UAVDT scores car, truck and bus only. No motorcycle evidence comes from UAVDT.
- **Subset selection.** Every sequence of each selected split is used. No sequence is chosen by any MAVI result.
- **Corpus size.**
  - VisDrone contributes 9,481 frames over 24 sequences.
  - UAVDT-M, if acquired, contributes all 50 sequences.
  - The total is below the 80,000-frame planning target. This is deliberate: it uses whole sequences of the GT-available splits, and stays within this host's disk (18 GB free on the controlled drive) and an overnight GPU window. A larger, partial-sequence subset would add volume without adding domains.
- **Detector saturation.** `max_per_img` saturation cannot be measured from formal runs, which record track outputs only. It is not reported.

## 4. Data

| Domain | Partitions | Sequences / frames | Frame time | Research use |
|---|---|---|---|---|
| VisDrone2019-MOT (adapter `visdrone2019-mot` v2) | `val`, `test-dev` | 24 / 9,481 | 30/1, assumed | RESEARCH-UNCERTAIN |
| UAVDT-Benchmark-M (adapter `uavdt-m` v1, conditional) | `test`, `train` | 50 / all frames | 30/1, stated | RESEARCH-ADMISSIBLE |

- **Pinned bytes:**
  - Archive bytes, source URLs, the VisDrone frozen descriptor (`62fe0c4c…79c3`, 9,505 files) and the mapping (`d45e28d9…eaf1`) are pinned in the JSON.
  - UAVDT's archive hashes are recorded once acquired.
  - Any later change of the bytes ends UAVDT's use in this event.
- **UAVDT adapter.** It is written to the frozen rules in the JSON (classes, ignore areas, conditions), with tests, before any UAVDT inference.
- **UAVDT fallback.** If UAVDT is not acquired within the retry window, it is recorded as unavailable and H4 proceeds with VisDrone alone.

## 5. Execution

The unit is one (partition, arm) pair. Within each partition, the reference arm runs first. Each unit has its own:
- fresh PostgreSQL catalogue;
- media store and evidence root;
- journal, exports directory and logs;
- completion receipt.

Steps for each unit:
1. **Preflight.** Verify:
   - the frozen commit, the derived-video hashes and free disk;
   - Runtime Pack and Model Pack installation;
   - `Start-MaviVisionWorker.ps1 -DevelopmentProducer <id> -VerifyOnly`.
2. **Start.** Launch the API on the fresh catalogue, then the worker with the same `-DevelopmentProducer`.
3. **Run.** Run `tools.benchmarks.cli execute --development-producer <id>` against the unit's journal. It checks every export's attested producer against the frozen tuple immediately after each run, so a wrong producer stops the unit at its first sequence.
4. **Receipt.** When the unit completes, `tools.benchmarks.h4.receipt build` writes the unit receipt, which is then verified. A verified receipt makes the unit's inference immutable.
   - The receipt checks its producer tuple against the registry as committed at the freeze commit, not at HEAD, so no later change can redefine or invalidate it.
   - Its identity is a pure function of the retained evidence. The build time is kept in an unhashed sidecar.

Rules during execution:
- **Resume.** Rerun the identical command on the same journal and catalogue.
- **Infrastructure failures.** Repair them without touching the experimental variable, and rerun only the affected work under a recorded attempt.
- **Product failures.** Deterministic failures are H4 evidence and are never retried away.
- **Wrong producer.** Stop and preserve the attempt, mark it invalid, diagnose the cause, and rerun only that unit.

## 6. Evaluation (frozen)

- **Per unit.** Run `tools.benchmarks.cli evaluate` with association policy `a8e2e7f1…fe05` and requirements `ca28702f…2d75`. Both arms of a domain are evaluated by the same tooling.
- **Per domain.** Run `tools.benchmarks.h4.compare`. It:
  - re-verifies every result;
  - requires each envelope to name its arm's frozen tuple;
  - requires the methodology file to equal its blob at the freeze commit (`c2f3db25`), and records that commit and the file's SHA-256 in the comparison;
  - requires every partition and both results to carry the values frozen here: descriptor, dataset, adapter id and version, mapping, association policy, requirements, declared frame rate, the selected sequences and frame counts per partition, and the Runtime Pack id and variant;
  - re-verifies each (partition, arm) completion receipt from its retained derivation, exports, evidence and journal, and requires the result to evaluate exactly the receipted exports, before consuming that result;
  - reconstructs per-GT outcomes, which must reproduce Scope A.

  The three bindings above were added to the tooling on 2026-10-07, after VisDrone execution and before the comparison was formally recorded. They check values this freeze already fixed; none of them changed.

Per arm (Observed):
- expected-vehicle GT outcomes and ignored GT;
- association rate;
- Vehicle Track states;
- zero-assigned sequences;
- per-native-class coverage;
- the Scope B subclass block (support, recall, precision, accuracies, undetermined share, confusion);
- frame rate and source resolution.

Paired (Derived):
- ΔAssigned and Δassociation;
- a paired, partition-stratified sequence bootstrap of Δassociation (10,000 draws, seed 20261006, 95% percentile interval, descriptive only);
- extra Vehicle Tracks, extra fragmented GT and extra fragment MAVI Tracks per extra assigned GT, only when ΔAssigned > 0;
- per-GT-track transitions.

Strata:
- GT median source-height band, using H3's bands;
- native class;
- UAVDT conditions (illumination, altitude, view, long-term).

## 7. Interpretation

- **Labels.** Every statement is labelled Observed, Derived, Inferred or Hypothesis.
- **No thresholds.** No pass/fail threshold is set from H4 results.
- **Scope of comparison.** Arms are compared only within a domain. H3's BDD100K figures are context only and are never pooled.
- **Taxonomy limits.** A dataset contributes only to the classes its taxonomy supports.
- **Domain differences** are evidence, not defects.
- **What H4 can conclude.** H4 records per-domain, per-class evidence. It cannot produce a Production recommendation.

## 8. Not done during H4

No change to:
- detector scale, checkpoint, threshold, NMS or `max_per_img`;
- tracker activation, high-confidence threshold, minimum IoU, confirmation frames or lost buffer;
- class mapping or association policy.

No E2/E3, tiling, threshold sweep, other detector, H3 rerun, H5 decision, Development-pack promotion or qualification gate.
