# Stage 4 — Evidence-Adequacy Measurement Protocol (E-A, E-B, verdict)

**Status:** Frozen with Stage 4 PR-1, before any real dataset or instrument result exists. Every result
(`benchmark-plate-adequacy-v1`) binds this file by its LF-normalised SHA-256. A change to this file after a result
exists is a protocol revision, recorded in the register (P3), and voids the results it could bias.
**Governing:**
- the Stage 4 plan, `docs/superpowers/plans/2026-10-12-stage4-anpr-ocr.md` §3;
- ADR-013 §4–§6 (Evidence Set, encoding, quotas);
- ADR-017 (benchmark-first; §6 association; §7 admissibility; §8 exposure; §9 qualification boundary).

**Class:** Development measurement evidence. Never Production qualification.

**Revision 1 (2026-10-12, before any result).** Added rules R6 (masked labels) and R7 (detector vehicle candidates).
They were made while onboarding the first real releases, before any instrument read a benchmark plate:
- UC3M-LP anonymises characters in every plate;
- the still-image releases carry no vehicle box.
No threshold, floor or verdict rule changed.

## 1. Question

Do MAVI's existing sealed evidence crops keep enough plate pixels and clarity for useful ANPR? The question is asked
of the **evidence**, not of any one model. The selector, VisionJob and the production processing policy are not changed
by this protocol.

## 2. Implementation (executable; nothing here is prose-only)

| Concern | Code |
|---|---|
| Plate ground truth `benchmark-plate-truth-v1` | `tools/benchmarks/capabilities/plates/truth.py`, `contracts/schemas/benchmark-plate-truth-v1.schema.json` |
| Normalisation `mavi-plate-normalisation-v1` | `tools/benchmarks/plates/normalisation.py`; .NET `Mavi.Application.Modules.Plates.PlateNormalisation`; vectors `contracts/test-vectors/plate-normalisation-v1.json` |
| Production crop and encoder | `tools/benchmarks/capabilities/plates/measure.py`, which imports `mavi_vision.quality.scoring.crop_region` and `mavi_vision.evidence.encoder.JpegLadderEncoder(PRODUCTION_ENCODER_POLICY)` |
| E-A | `tools/benchmarks/capabilities/plates/adequacy.py` |
| E-B | `tools/benchmarks/capabilities/plates/coverage.py`, plus the harness's existing `prepare`, `execute` and `benchmark-association-v1` |
| Verdict | `tools/benchmarks/capabilities/plates/verdict.py` |
| Instruments | `tools/benchmarks/capabilities/plates/instruments.py` and `benchmark-plate-instrument-v1` specifications under `docs/qualification/stage4/instruments/` |
| Commands | `python -m tools.benchmarks.plates.cli truth\|ea\|eb\|verdict` |
| Datasets | `tools/benchmarks/datasets/ufpr_alpr.py` (sequences), `tools/benchmarks/datasets/voc_plates.py` (Indian stills) |

## 3. Data and partitions

- **Sources.** Only releases with an ADR-017 release record (a `benchmark-dataset-release-v1` descriptor) are used.
  - The manifest is frozen from the obtained tree.
  - Every byte is re-verified on read.
  - `BLOCKED` is refused.
- **Leakage.** UFPR-ALPR is measured on its `testing` split only; `training` and `validation` stay unread, reserved for any later fine-tuning event. The Indian VOC sample is evaluation-only. No result of this protocol selects or tunes a model.
- **Ordering and identity.** Items are sorted by `itemId`; sequences by id. The truth document's SHA-256 is the dataset-sample identity.

## 4. Measurements

### 4.1 E-A — encoding loss (per ground-truth plate)

1. **Vehicle association.**
   - The candidate is the dataset's own vehicle box. When the dataset has none, the candidates are phase-1 detector boxes from a pinned `benchmark-plate-vehicle-candidates-v1` file.
   - A candidate qualifies when it contains at least **9/10** of the plate rectangle's area. The smallest qualifying box wins; ties go to the smaller `y`, then the smaller `x`.
   - No qualifying box makes the plate `unassociated`. It stays a row and is excluded from ΔEM with that reason.
2. **Crop.** The tight vehicle crop is taken by `crop_region` (a test pins the mapping origin to its pixels).
3. **Encode.** The production encoder runs at the Representative cap (64 KiB) and the supplemental cap (160 KiB; NearView, EarlyDiverse, LateDiverse).
   - A crop the ladder cannot fit is `not admitted` for that role. Its plate counts as **not read** in that role.
4. **Map and measure.**
   - The plate rectangle is mapped into the decoded encoded crop by the crop origin and the encoded/crop scale. A plate wholly outside the crop counts as not read.
   - Recorded for native and each role:
     - character height (proxy below);
     - plate width;
     - Laplacian-variance blur;
     - JPEG quality, ladder step, encoded size and scale.
5. **Read.**
   - Every pinned instrument reads the native plate region and each encoded plate region.
   - Each read records the raw text, the v1 normalisation, confidence, exact match and CER.
   - **Exact match** is normalised read == normalised ground truth.

**Character-height proxy.** The mean of the plate polygon's left and right edge lengths, divided by the line count (1 when the layout is unknown). It is declared, not measured per character.

### 4.2 E-B — Track evidence coverage (per ground-truth vehicle track)

1. `prepare` encodes the labelled frames at the descriptor rate, and `execute` processes them through the product API on the release pipeline profile, unchanged.
2. Exports are read by exact bytes. Every evidence crop is verified against its export SHA-256 and size before decode.
3. Ground-truth vehicle tracks are matched to MAVI Tracks by `benchmark-association-v1` (ADR-017 §6; predictions never consulted).
4. An observation's frame must satisfy `videoOffsetMs == round_half_up(sourceFrameNumber × 1000 / rate)`. Otherwise the run is refused (`frame_alignment`).
5. **Oracle-readable:** some labelled frame's native plate has character height ≥ `h_min` and is read exactly by an instrument.
6. **Evidence-readable:** some evidence crop of the associated MAVI Track is read exactly by an instrument.
   - The read is of that frame's labelled plate, mapped through the observation's production crop geometry.
   - A frame without a plate label is recorded, never guessed.

## 5. Frozen decision rules

**Resolutions.** These are explicit resolutions of points the plan leaves open; they are fixed here and in code.

| # | Rule |
|---|---|
| R1 | **Support floor 50**, for every population a criterion rests on: each `h_min` bin, the ΔEM population per instrument, R_oracle, and each stratum. A stratum below it is *insufficient evidence*, never pass or fail |
| R2 | **`h_min`.** Native character-height bins with lower bounds 0, 10, 15, 20, 32 px.<br>The **reference instrument** has the higher native EM in the ≥ 32 px bin (ties: higher overall native EM, then instrument id).<br>`h_min` is the lower bound of the smallest bin `b` such that `b` **and every larger bin** have support ≥ 50 and reference EM ≥ 9/10 × the ≥ 32 px bin's EM.<br>It is NOT MEASURED when the top bin's support is < 50 or its EM is 0. The tail requirement makes `h_min` a monotone threshold even when the bin curve is not monotone |
| R3 | **ΔEM** = 100 × (native exact − encoded exact) / n percentage points, as an exact rational. Per instrument and cap, over text-usable, associated plates with native character height ≥ `h_min`. The verdict uses the **supplemental** cap; the Representative cap is reported beside it |
| R4 | **C** = R_ev / R_oracle, with "an instrument" meaning the **union** of the two pinned instruments, in both oracle and evidence. Per-instrument C is reported beside it.<br>A ground-truth track without a MAVI Track stays in R_oracle and is not evidence-readable; its association state is recorded.<br>Tracks without a text-usable plate are counted separately and never enter R_oracle |
| R5 | **Instrument failure.** Any instrument read error makes the verdict NOT MEASURED |
| R6 | **Masked labels.** A release that anonymises characters labels each one `*`. Such a label is normalised position by position (ASCII only); masked positions are kept.<br>A read is **exact** only when its normalised text has exactly the truth's length **and** equals it at every unmasked position. CER treats a masked position as matching any character.<br>A label that is all masks is unusable (`fully-masked`).<br>Why: the masked pixels are identical in the native image and every encoded crop, so the rule leaves ΔEM's comparison intact; without it no plate of such a release could ever match |
| R7 | **Detector vehicle candidates.** For releases without a vehicle box, the candidates are the production `RTMDetDetector` detections of the vehicle source classes (`car`, `truck`, `bus`, `motorcycle`) at or above the release pipeline profile's evidence `confidenceFloor` — the floor a detection must meet to be qualified evidence (ADR-013 §4).<br>They are produced by `tools/benchmarks/plates/vehicle_candidates.py` inside the vision Runtime Pack's environment, which starts the worker's own runtime composition. The candidates file binds the truth's SHA-256 and the runtime provenance |

**Verdict** (precedence top-down; exact comparisons):

| Verdict | Rule |
|---|---|
| NOT MEASURED | No C, R_oracle < 50, no `h_min`, a ΔEM missing or on n < 50 for any instrument, or any instrument error. **No data is never ADEQUATE** |
| INADEQUATE | C < 0.70, or ΔEM > 10 pp for any instrument |
| MARGINAL | 0.70 ≤ C < 0.85, or 5 pp < ΔEM ≤ 10 pp for any instrument |
| ADEQUATE | C ≥ 0.85 **and** ΔEM ≤ 5 pp for both instruments |

**Stated limitation.**
- E-A support counts **plates**, not independent vehicles. The 30 frames of one UFPR-ALPR sequence are 30 correlated plates of one vehicle.
- Every E-A result therefore also reports the number of distinct sequences (vehicles) in each population.
- The verdict does not apply a cluster correction: the plan's §3.4 rule is a plate-level rule. The register reads a population of few vehicles as limited evidence.
- E-B's support (R_oracle) counts tracks, i.e. vehicles, and needs no such caveat.

**Strata** are reported beside the verdict and never change it:
- vehicle class;
- layout (one-/two-line);
- illumination;
- occlusion;
- character-height bin;
- blur tertile (over the population);
- oblique (top-edge skew > 15°; `unavailable` for box-only labels);
- role (E-B).

## 6. Instruments

- Two pretrained OCR readers, one plate-specific and one generic, each pinned by a `benchmark-plate-instrument-v1` specification. The specification names:
  - the adapter;
  - the exact package versions;
  - the configuration;
  - every model file by path and SHA-256.
- Loading re-hashes every file and refuses any difference.
- Instruments run in the Development benchmark environment `tools/benchmarks/plates/requirements-instruments.txt`, on ONNX Runtime **CPU** for determinism. They are never a MAVI runtime dependency.
- Their training exposure to each dataset is recorded (ADR-017 §8).
- They **measure the evidence**. They are not Stage-4 selection candidates, and no result here ranks them.

## 7. Reproduction

```
python -m tools.benchmarks.plates.cli truth --descriptor <D> --source-root <S> --adapter ufpr-alpr --split testing --out truth.json
python -m tools.benchmarks.plates.cli ea --truth truth.json --descriptor <D> --source-root <S> --instrument <I1> --instrument <I2> --model-root <M> --out ea.json
python -m tools.benchmarks.cli prepare|execute|evaluate ...   # existing harness: derived video, MAVI runs, association
python -m tools.benchmarks.plates.cli eb --truth truth.json --descriptor <D> --source-root <S> --association association.json --exports <E> --ea ea.json --instrument <I1> --instrument <I2> --model-root <M> --out eb.json
python -m tools.benchmarks.plates.cli verdict --ea ea.json --eb eb.json --out verdict.json
```

- Results are retained create-only under `E:\MAVI-Controlled\Benchmarks\<datasetId>\<release>\results\<runId>\`.
- Their SHA-256s are recorded in the register.
- Dataset bytes, crops and model weights never enter Git.
