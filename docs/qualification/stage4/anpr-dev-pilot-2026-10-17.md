# Stage 4 — Development ANPR/OCR pilot through MAVI (Issue #225), 2026-10-17

**Status: Development diagnostics only.** This is not model-selection, qualification or acceptance evidence, and it
does not PASS any register row. The frozen evidence-adequacy verdict (INADEQUATE, C = 53/79 = 0.671) and every frozen
artefact are unchanged. Protected D was not opened, no M3 Model Selection Event was run, and O3, O1B and the PR-6 hold
are unchanged. The models are unverified Development Model Packs, and Production refuses them.

## What ran

| Stage | Component | Identity |
|---|---|---|
| Vision (recorded video → Tracks → sealed evidence) | release binding `7ef22619…`, profile `phase1-detection-tracking-v1` `afb03b6c…`, RTMDet-m Model Pack `mavi-model-v2-86754e36…` | Runtime Pack `mavi-runtime-v2-89fd8bfc…` (`windows-x86_64-cuda`, installed pack); `cuda:0` NVIDIA GeForce GTX 1650 Ti, driver 576.83, CUDA 12.4, attested on all 70 runs |
| Plates (lease → evidence → detect → read → publish) | Development role binding `development-plates-onnx-pilot-v1` (`9996d7ca…`), plate profile `plates-onnx-pilot` 1.0.0 `43a75330…` (`developmentOnly`, no `fixtureSeed`) | runtime family `plates-onnx-v1` (`3307311e…`, Development-only graph `onnxruntime-cpu-v1`, `unpacked-environment`), CPU; analysis identity `c86c930b038d4f933f66ec2ed2f0c886f2df18dc932f79ec2f703c5f882f066e` (platform and worker derive the same value) |
| Plate detector | PD5-V5M: PP-OCRv5_mobile_det (official PaddlePaddle ONNX, revision `e6f4fa85…`), adapter `ppocr-db-onnx-v1` | `mavi-model-v2-f9a7f8a0…`; `inference.onnx` `a4319856…`, `inference.yml` `98069072…` |
| OCR | OC1-S: fast-plate-ocr `cct_s_v2_global` (release `arg-plates`), adapter `fast-plate-ocr-onnx-v1` | `mavi-model-v2-f6a826af…`; `cct_s_v2_global.onnx` `384bbbd2…`, plate config `0335c74a…` |
| Application | branch `stage4/anpr-dev-pilot` | vision runs `maviCommit` `c672550e`; API binaries built from the same platform source (no platform source change on the branch) |

Profile parameters (fixed in the committed profile before any plate output existed):
- at most 2 proposals per crop, at most 1 plate per crop, at most 1 reading per plate;
- detector floor 0.6 (the pack's own DB `box_thresh`), OCR floor 0.5;
- no excluded roles.

The pilot catalogue was `mavi_anpr_pilot_cuda_20261017` (tablespace on E:), with media and evidence roots under
`E:\MAVI-Working\anpr-pilot-cuda\host`. It held only what the pilot created.

## Decision 1 — licence (PD2) and the composition actually run

PD2-S was **not** executed.
- The weights licence is precisely identified as AGPL-3.0, from two primary sources: the model card front matter
  (`README.md` `a784848e…`, "license: agpl-3.0") and the ONNX metadata of the acquired file (`301e4239…`).
- The source and provenance are pinned: Hugging Face `morsetechlab/yolov11-license-plate-detection` @ `251a30d7…`,
  and the publisher SHA-256 equals the acquired bytes.
- The training-data provenance is PARTIAL. The Roboflow Universe `license-plate-recognition-rxg4e` v11 dataset terms
  are UNVERIFIED.
- The ledger status is `REVIEW_PENDING` (`plates-2026-01-licence-provenance-ledger.json` on the local branch
  `stage4/pr2-model-selection-prep` @ `8790a412`).
- The ledger itself states that licence clearance is a human determination.

The AGPL obligations for MAVI's integration were not determined. Under AGPL §2, private, unconveyed, unmodified
running is unconditional. However, whether network interaction or redistribution of a Model Pack triggers source
obligations is unresolved for MAVI's intended use. Because the licence position could not promptly be *established*,
Decision 1's alternative was run: **PD5-V5M (Apache-2.0) + OC1-S (MIT)**, as an experimental comparison, with no
assumption about its accuracy.

Evidence for the alternative (retained bytes in `E:\MAVI-Controlled\Benchmarks\plate-candidates\licence-evidence\2026-10-13\`):

| Pack | Code licence | Weights licence | Notice shipped in the pack |
|---|---|---|---|
| PD5-V5M | Apache-2.0 (PaddleOCR `LICENSE` `3840c5c0…`) | Apache-2.0, official model card front matter (`README.md` `951c1556…`) | the PaddleOCR `LICENSE` |
| OC1-S | MIT (`fpo-LICENSE` `a953e626…`) | MIT, maintainer statement on issue #97 (`fpo-issue97-comments.json` `654f6d80…`, "all code and as well as .keras/.onnx artifacts/models are MIT") | the fast-plate-ocr `LICENSE` |

Both packs remain `REVIEW_PENDING` for the `mavi-nc-research-dev` profile in the PR-2 ledger. The owner's Decision 1
names them as the already-cleared alternative, and this note relies on that decision; it does not add a clearance.

Neither pack is redistributed, released or used in Production. Training-data exposure to BDD100K is `unknown` for
both. OC1-S is byte-identical to the PR-1 plate-specific instrument (owner D5 excluded it from selection), so this
pilot is not selection evidence for it.

## Decision 2 — footage and terms

The footage is BDD100K MOT 2020 val, the Stage-3 H3 release:
- descriptor `7169263a…`;
- derived 5 fps sequences from the preserved H3 staging directory (derivation manifest `a295809d…`, every video
  re-hashed before import);
- R8 labels, human-reviewed and AI-assisted (truth `8d1d03b2…`).

Terms: the H3 descriptor records `researchUse` RESEARCH-ADMISSIBLE. The BDD100K data and label licence permits use
"for educational, research, and not-for-profit purposes, without fee", and redistribution is not permitted by default.
This pilot is non-commercial Development research, run on a single local host. No image, crop or label leaves the
controlled and working stores, and none is in Git, so the existing terms cover it.

This is not Indian-domain validation, not protected D and not O1B holdout data. The personal night recordings were not
used.

## Method (predeclared)

The checkpoint `E:\MAVI-Working\checkpoints\anpr-pilot.md` recorded the following before any plate output existed.

- **Subset.** Every val sequence with at least one R8 GT track whose plate is text-usable: **70 sequences,
  110 GT tracks**, all of them processed (no sampling). The processing order is
  `sha256("mavi-anpr-dev-pilot-2026-10-17/" + sequenceId)`, and the subset file is `af45dfef…`. This stratum contains
  the whole frozen E-B population: all 110 text-usable tracks, 79 of them oracle-readable.
- **Path.** Real MAVI API throughout:
  1. camera, import and `POST /api/videos/{id}/process` (T9 helpers), then the CUDA vision worker;
  2. the API restarted with the pilot plate release (`Plates__*` process overrides), then
     `POST /api/plates/reanalysis` for the 70 runs (202: 70 queued);
  3. the plates worker on CPU leased, read the sealed evidence over HTTP, detected, read, uploaded and completed;
  4. `GET /api/processing/runs/{id}/plates` showed Ready for 70/70;
  5. `GET /api/tracks?plateText=…&plateMatch=exact`, Track detail `plates`, `GET /api/artifacts/{id}/content` and
     `GET /api/videos/{id}/content` were then queried.
- **Measurement.** `tools/benchmarks/plates/dev_pilot.py`:
  - T1 exports of the runs;
  - association with the frozen policy `a8e2e7f1…` (`vehicle-tracks-association-v1`, labelled rate 5/1);
  - evidence readability by the E-B definition (`coverage.evaluate_track`, both frozen instruments, `h_min` 32 px);
  - the product search and detail APIs.
- **Failure attribution.** Each GT track is assigned the first cause that applies, in this order:
  1. `track_association`;
  2. `evidence_unavailable`;
  3. **search hit**;
  4. `searchable_text_missing`;
  5. `source_evidence`: not instrument-readable from the R8 geometry in any crop;
  6. `detector_miss`: no selected box covers ≥ 50 % of the mapped truth plate in any readable crop;
  7. `ocr_error`.

**Caveat (circularity).** OC1-S is the same bytes as the plate-specific instrument. "Source evidence" and "OCR"
causes are therefore defined relative to that model. `ocr_error` means a wrong reading of the pilot's own box. It is not
an independent OCR assessment.

## Results

**Pipeline health.**
- 70/70 vision runs Completed on `cuda:0`: mean processing 19.7 s per sequence, about 30 s end to end.
- 70/70 plate analyses Completed on the first attempt.
- 2,612 Vehicle Tracks analysed, 0 Unavailable, 0 attempt failures.
- 547 plate observations, 333 kept readings, 252 searchable Track texts on 197 Tracks.
- Search coverage: 2,612 in scope, 2,612 Ready.

**Against R8 truth (110 GT text tracks).**

| Measure | All text tracks | Oracle-readable tracks |
|---|---|---|
| GT tracks | 110 | 79 |
| Associated to exactly one MAVI Track (`matched`) | 86 | 65 |
| Evidence-readable (frozen E-B definition, new evidence) | 62 | 53 |
| **Found by exact plate search on the associated Track** | **52 (47.3 %)** | **45 (57.0 %)** |
| Found, given evidence-readable | 52 / 62 (83.9 %) | 45 / 53 (84.9 %) |
| Detector covered the true plate, given evidence-readable (derived from the cause order; coverage is not computed for hits) | 54 / 62 | 46 / 53 |
| Exact reading, given the detector covered the plate (derived, as above) | 52 / 54 | 45 / 46 |

**Failure attribution (first cause; every one of the 110 tracks is listed in the raw result).**

| Cause | All 110 | Oracle-readable 79 | Detail |
|---|---|---|---|
| Search hit (success) | 52 | 45 | the exact R8 text returns the associated Track |
| Track association | 24 | 14 | unmatched 14, fragmented 8, unverified 2 |
| Source evidence | 24 | 12 | all "poor": the plate is not instrument-readable in any labelled crop |
| Detector miss | 8 | 7 | another region selected 5, no plate selected 3 |
| OCR error | 2 | 1 | `T700349C` read as `T00349C`/`700349C`; `NARTEA` read as `NARTFA` |
| Evidence unavailable | 0 | 0 | — |
| Searchable text missing | 0 | 0 | — |

**Search precision on the 108 distinct truth texts.**
- 51 queries return the correct associated Track. Two GT tracks share a text with another GT track, so 52 tracks are
  found by 51 queries.
- 13 further results are returned. The retained measurement output stores only per-query counts, not result Track
  ids, so their identity and sequence are not verified here. 10 of the 13 are on queries whose GT track failed
  association and 1 on a source-evidence failure, so they are plausibly fragments of the same vehicle; they are
  counted neither as hits nor as errors.
- Open-set false positives cannot be measured: about 2,500 Vehicle Tracks carry no R8 label.

**Review and playback.** For all 52 hits:
- the Track detail `plates` block was Ready and Analysed, with provenance naming both Model Packs, the normalisation
  and the summary policy;
- every plate observation's source evidence crop was retrieved through `GET /api/artifacts/{id}/content` (valid JPEG);
- the video answered a ranged `GET /api/videos/{id}/content` with 206 `video/mp4`.

Raw record: `review-playback-check.json` (`0e8e82d2…`). PR-5 operator UI was not part of this slice.

The per-sequence results (all 70 evaluated sequences) are in the table at the end of this note.

## Comparability with the frozen 53/79

The regenerated H3 evidence matches the frozen H3/E-B basis on:
- Runtime Pack `89fd8bfc…` (`windows-x86_64-cuda`);
- Model Pack `86754e36…`;
- binding `7ef22619…` and profile `afb03b6c…`;
- association policy `a8e2e7f1…`;
- device `cuda:0` GTX 1650 Ti, driver 576.83;
- derived videos `a295809d…`;
- R8 truth.

It differs in the MAVI commit (`c672550e` against `35907342`) and in covering 70 of the 200 sequences. Association is
per sequence, and the 70 include every text track.

Re-applying the frozen E-B definition to the new evidence gives **evidence-readable 53 of 79 oracle-readable tracks**.
Per track, the association state, oracle readability and evidence readability agree with the frozen human-reviewed E-B
rows on **110/110** tracks. Comparability is therefore *established empirically for this population*.

This is a reproduction on regenerated evidence, made as a Development diagnostic. It neither replaces nor amends the
frozen result. CUDA here is Development hardware evidence (`qualified-development-hardware` runtime variant), not
qualification. The earlier CPU attempt (below) used a different device, and comparability was neither assumed nor
measured for it.

## What the pilot shows (diagnostic, not a selection claim)

- The real path works end to end through the normal worker and the database:
  - real ONNX models produced detector and OCR outputs;
  - the outputs were published as plate facts;
  - the facts were searchable through the product API;
  - the evidence behind them was inspectable.
- Where the evidence carries a readable plate, the Apache/MIT composition finds the Track by exact search for about
  84 % of tracks.
- The dominant losses are upstream:
  - Track association: 24 of 110;
  - evidence that does not carry a readable plate: 24 of 110.

  These are the same limitations the frozen adequacy verdict measured, and the planned source-evidence-selection
  experiment targets them.
- The detector is a text-line proposer, not a plate detector, and in 5 cases it selected other text. This is a property
  of the PD5 alternative; PD2 was not run for the licence reason above.

## Superseded attempts (retained, not used)

The first catalogue, `mavi_anpr_pilot_20261017`, is preserved and not used for any result:
- 48 runs Completed on CPU (`windows-x86_64-cpu`, `mavi-runtime-v2-5d6229da…`, about 105 s per sequence);
- after the owner switched vision to CUDA, 5 runs of the same assets were completed on `cuda:0` in that catalogue
  before the owner directed a separate catalogue.

Run IDs and devices: `E:\MAVI-Working\anpr-pilot\out\cpu-catalogue-runs.csv`, plus `journal.json` and
`journal-cuda.json` in the same directory. No plate analysis ran in that catalogue.

## Identities and raw outputs (outside Git)

| Item | Value |
|---|---|
| Pilot result | `E:\MAVI-Working\anpr-pilot-cuda\out\pilot-result.json`, `4c346df9…` |
| Journal (70 runs) | `E:\MAVI-Working\anpr-pilot-cuda\journal.json`; run-id list SHA-256 `3c9396a1…` |
| Plate readiness / re-analysis | `out\plate-readiness.json`, `out\reanalysis-response.json` |
| T1 exports | `E:\MAVI-Working\anpr-pilot-cuda\exports\<runId>\` |
| Logs (API, vision, plates worker, drivers) | `E:\MAVI-Working\anpr-pilot-cuda\host\logs\` |
| Model store (staged, hash-verified) | `E:\MAVI-Working\anpr-pilot\models\` (`tools/vision/plates_pilot_packs.py stage --controlled-store`) |
| Plates runtime | `E:\MAVI-Working\anpr-pilot\plates-venv` (CPython 3.12.10, lock-installed `--no-index --require-hashes`) |

Adapter parity with the read-only PR-2 prep adapters (Development check):
- OCR: 60/60 O5 audit plate crops identical to fast-plate-ocr 1.1.0 (text exact, confidence within 1e-6);
- detector: 80/80 O5 evidence crops with boxes identical to `adapters.load("PD5-V5M", maxDet 2, rowMerge vertical-stack-v1)` + `pr3.Pr3Detector`.

## Per-sequence results

| # | Sequence | Processing run | Vehicle Tracks | R8 text tracks | Search hits | Failures (cause count) |
|---|---|---|---|---|---|---|
| 1 | `b1e6efc0-2552cc5d` | `01a14987-66ec-7076-841d-f8d2e4413036` | 13 | 1 | 0 | association 1 |
| 2 | `b1d0a191-06deb55d` | `01a14989-5110-7ea7-9a1f-25d4b9ebe6c4` | 27 | 1 | 1 | none |
| 3 | `b237db93-fab44bf2` | `01a14989-edc0-7a12-9725-18ae5d537a9d` | 22 | 2 | 0 | source evidence 2 |
| 4 | `b214d1e1-f248c616` | `01a1498a-631c-7967-bffb-edfad7b938fc` | 29 | 2 | 1 | source evidence 1 |
| 5 | `b255cd6c-0bdf0ac7` | `01a1498a-d882-7dd0-b0c7-111e3dd36dca` | 12 | 1 | 0 | association 1 |
| 6 | `b1d10d08-ec660956` | `01a1498b-4dfc-7ce3-a7c8-26713ba9c870` | 45 | 1 | 0 | association 1 |
| 7 | `b1d59b1f-a38aec79` | `01a1498b-c358-72a8-abba-8ddef755716a` | 5 | 1 | 0 | association 1 |
| 8 | `b21c86ac-2eb7ba16` | `01a1498c-38d5-7fc7-870b-47039c46738a` | 108 | 2 | 0 | source evidence 2 |
| 9 | `b204a5c1-05981158` | `01a1498c-ae43-7e59-8a9b-febf193f695a` | 19 | 1 | 0 | source evidence 1 |
| 10 | `b1d968b9-563405f4` | `01a1498d-23d1-7212-b70e-02660af407f6` | 36 | 1 | 1 | none |
| 11 | `b21bfb83-ea32f716` | `01a1498d-9956-70ec-81c1-2cefba6c2536` | 8 | 1 | 1 | none |
| 12 | `b1d9e136-9ab25cb3` | `01a1498e-0eee-77b3-a453-02434e70b154` | 25 | 1 | 1 | none |
| 13 | `b23c9e00-b425de1b` | `01a1498e-845b-7355-98f0-17cbbc93b8bb` | 28 | 1 | 0 | detector 1 |
| 14 | `b1d0a191-03dcecc2` | `01a1498f-211b-74a8-8378-88f2c229edac` | 41 | 1 | 0 | association 1 |
| 15 | `b1f4491b-dd8dfed5` | `01a1498f-967a-763a-95b2-37db21fe3803` | 17 | 1 | 0 | source evidence 1 |
| 16 | `b1d7b3ac-afa57f22` | `01a14990-0be1-71c5-a754-bf54fa397783` | 14 | 1 | 0 | detector 1 |
| 17 | `b251064f-30002542` | `01a14990-8157-78a7-a9af-e82dbef5f803` | 40 | 1 | 1 | none |
| 18 | `b1d0a191-2ed2269e` | `01a14990-f6b7-7216-9f96-8340485ae5dd` | 31 | 4 | 2 | source evidence 2 |
| 19 | `b1c9c847-3bda4659` | `01a14991-6c31-751b-8487-333a2eb2eb09` | 92 | 2 | 1 | association 1 |
| 20 | `b1dd58c1-8b546ba7` | `01a14991-e197-77f6-a4c9-76306228db07` | 68 | 2 | 1 | source evidence 1 |
| 21 | `b1d7b3ac-995f9d8a` | `01a14992-5726-7299-bf90-d1703eae77c2` | 31 | 7 | 4 | association 1, source evidence 2 |
| 22 | `b1d971b4-ac67ca0d` | `01a14992-cc9b-791d-941b-b95206bf9d39` | 62 | 1 | 0 | association 1 |
| 23 | `b20eae11-6817ba7a` | `01a14993-4230-78f7-9bda-9a895cc1266c` | 13 | 1 | 1 | none |
| 24 | `b251064f-8d92db81` | `01a14993-b7a5-7b5b-99ce-bf66801411d4` | 79 | 1 | 1 | none |
| 25 | `b1d7b3ac-0bdb47dc` | `01a14994-2d0c-7c00-a0ac-8ba5cf05d0b3` | 42 | 1 | 1 | none |
| 26 | `b251b746-00138418` | `01a14994-a291-783d-8f5d-45a3ab937351` | 8 | 1 | 1 | none |
| 27 | `b1d9e136-6c94ea3f` | `01a14995-1801-771a-9b94-1dfce22cd8b5` | 51 | 1 | 1 | none |
| 28 | `b1f85377-44885085` | `01a14995-8d74-7c92-82b4-0964638265a7` | 41 | 4 | 1 | association 2, detector 1 |
| 29 | `b23bb45f-ddeea1d8` | `01a14996-02e8-7131-b4e5-497052d65214` | 24 | 1 | 1 | none |
| 30 | `b1d7b3ac-9e14f05f` | `01a14996-786a-71c0-95c1-756ca5bf7779` | 51 | 5 | 1 | association 2, source evidence 2 |
| 31 | `b1e1a7b8-a7426a97` | `01a14996-edd8-747e-b836-820c80fe6517` | 31 | 1 | 1 | none |
| 32 | `b20b69d2-64b9cdb8` | `01a14997-6347-7c6a-8035-b3ab15920572` | 32 | 1 | 0 | detector 1 |
| 33 | `b255cd6c-2f889586` | `01a14997-d8cf-72a3-9fd6-b896e592f582` | 38 | 1 | 1 | none |
| 34 | `b1d0a191-5490450b` | `01a14998-4e4e-75c8-9409-8a185de3c3b8` | 26 | 1 | 1 | none |
| 35 | `b20841f9-cef732d5` | `01a14998-c3d2-7cf8-be8c-e4f5a6cd3452` | 39 | 1 | 1 | none |
| 36 | `b1ea0ae4-4f770228` | `01a14999-3932-780f-9460-27d5c81271fe` | 50 | 10 | 3 | association 2, source evidence 5 |
| 37 | `b1cd1e94-549d0bfe` | `01a14999-ae95-755c-bd23-26afea7b825a` | 34 | 1 | 1 | none |
| 38 | `b1f0efd9-37a14dda` | `01a1499a-23e8-73c7-93bf-998f1a5a7678` | 32 | 1 | 1 | none |
| 39 | `b216243d-ad4306b9` | `01a1499a-9948-7815-a0e9-c5a58e8e1013` | 11 | 1 | 1 | none |
| 40 | `b23b2649-6af03cd5` | `01a1499a-e784-751a-ba2d-004b1622cbdd` | 35 | 3 | 0 | association 1, detector 1, source evidence 1 |
| 41 | `b1ceb32e-51852abe` | `01a1499b-5cf7-7d48-947d-b4b9cd34792f` | 23 | 1 | 1 | none |
| 42 | `b1c81faa-c80764c5` | `01a1499b-d282-7d93-891e-dcbb7c59da37` | 2 | 1 | 0 | association 1 |
| 43 | `b23a79d1-e434acaa` | `01a1499c-47eb-701b-80ac-4bd088a3a65f` | 23 | 1 | 1 | none |
| 44 | `b250fb0c-01a1b8d3` | `01a1499c-bd55-7105-887c-14e075b2a1e0` | 43 | 2 | 0 | association 1, detector 1 |
| 45 | `b1d10d08-c35503b8` | `01a1499d-32b9-7660-ab9c-b062a738be5b` | 76 | 1 | 1 | none |
| 46 | `b1ebfc3c-cc9c2bb8` | `01a1499d-a826-7a7b-930b-988f3e23eb15` | 23 | 1 | 0 | association 1 |
| 47 | `b1d7b3ac-36f2d3b7` | `01a1499e-1dc9-7eb9-ab4b-1215609a2032` | 13 | 2 | 2 | none |
| 48 | `b23493b1-3200de1c` | `01a1499e-936a-7512-8b78-077bf6100200` | 62 | 1 | 0 | detector 1 |
| 49 | `b1f4491b-d8d1459c` | `01a1499f-08d8-7fb2-b60b-6af9f288f6f9` | 17 | 1 | 0 | OCR 1 |
| 50 | `b1f4491b-07b32e8c` | `01a1499f-7e2b-7011-a4b1-f7f9566fefcc` | 49 | 1 | 1 | none |
| 51 | `b1f25ff6-1ddb7e43` | `01a1499f-f38c-78fa-a2e1-f2cccf30a126` | 43 | 5 | 3 | association 1, source evidence 1 |
| 52 | `b2331b83-648e56ca` | `01a149a0-68df-770b-a567-c3f39f39b3e5` | 25 | 1 | 1 | none |
| 53 | `b20e291a-6012d836` | `01a149a0-de49-7906-8179-54431c600c9b` | 70 | 1 | 1 | none |
| 54 | `b1f4491b-16256d7c` | `01a149a1-7ac5-7f3e-a69e-8e994c6ad179` | 39 | 2 | 0 | association 2 |
| 55 | `b1e1a7b8-0aec80e8` | `01a149a1-f022-77d3-ba64-8e9e76c7ffc6` | 22 | 1 | 1 | none |
| 56 | `b1d0091f-f2c2d2ae` | `01a149a2-6575-751e-b59f-9505852807c5` | 23 | 1 | 1 | none |
| 57 | `b20e291a-32ac11c1` | `01a149a2-db31-7097-8e50-f0ca7ef2f1c4` | 75 | 1 | 1 | none |
| 58 | `b1ff4656-0435391e` | `01a149a3-508d-75a8-bd38-21e1906197f5` | 77 | 1 | 0 | association 1 |
| 59 | `b202cae2-672e61c5` | `01a149a3-c5e3-787c-83f4-ef66695c0126` | 119 | 1 | 1 | none |
| 60 | `b20b69d2-7767e6b6` | `01a149a4-625c-714d-a96f-89cac1c2e99b` | 30 | 1 | 1 | none |
| 61 | `b21742c2-0e7a2b57` | `01a149a4-d7ac-7a54-b400-06a572a90f95` | 21 | 1 | 1 | none |
| 62 | `b2194b15-1825056a` | `01a149a5-4d1f-7541-a025-371d63e44f7f` | 25 | 1 | 1 | none |
| 63 | `b1f20aa0-50213047` | `01a149a5-c28d-7c10-b765-5f4cefb05592` | 2 | 1 | 1 | none |
| 64 | `b205eb4d-f84aaa1a` | `01a149a6-37df-7ca9-bc22-103a30d0d16b` | 65 | 1 | 0 | detector 1 |
| 65 | `b21c68e6-65674a17` | `01a149a6-ad33-7542-a65e-b8b696b42971` | 14 | 1 | 0 | source evidence 1 |
| 66 | `b1fbf878-b31a8293` | `01a149a7-2288-7818-a1fc-f1ac2e034070` | 31 | 1 | 0 | OCR 1 |
| 67 | `b1e8ad72-c3c79240` | `01a149a7-983f-7f62-9880-54153693c17c` | 24 | 1 | 1 | none |
| 68 | `b1f4491b-33824f31` | `01a149a8-0dbc-73be-83bb-c121e1d5aa7b` | 36 | 1 | 0 | association 1 |
| 69 | `b1dac7f7-6b2e0382` | `01a149a8-aa51-71fb-97fb-3f714c0dac6a` | 73 | 2 | 0 | association 1, source evidence 1 |
| 70 | `b1dce572-c6a8cb5e` | `01a149a9-46c9-705f-b3b4-3d4a8530fe21` | 57 | 1 | 0 | source evidence 1 |
