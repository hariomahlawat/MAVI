# ANPR / OCR — Stage-4 Acceptance Register

**Status:** **OPEN — evidence-adequacy verdict recorded: INADEQUATE** (Development measurement, 2026-10-13; frozen).
- E-A and E-B were executed on real data with verified instruments. The frozen decision rule gives **INADEQUATE**: C = 51/77 = 0.662 < 0.70; encoding loss 0.97 pp and 1.95 pp, both ≤ 5 pp.
- **O5 complete.** The ground truth is now **human-reviewed, AI-assisted**. Recomputed under the frozen protocol: C = 53/79 = 0.671, encoding loss 0.61 pp and 1.52 pp, **INADEQUATE (unchanged)**. The frozen AI-label result is preserved.
- The root cause is in `docs/qualification/stage4/adequacy-root-cause-2026-10-13.md` (corrected after X1):
  - selection: near views fail side- or top-edge contact (9 tracks), the sharpness floor (5) and NearView hysteresis (1); bottom contact blocks none;
  - tracking and association at 5 fps.
- X1 (bottom-border exemption): 0/10 recovered, **rejected** by the owner.
- PR-3 to PR-5 proceed; PR-6 is held (O3). Indian validation is split: O1A (tracking, IDD-X approved) and O1B (ANPR/OCR, OPEN). PR #213 stays Draft.

**Date opened:** 2026-10-12\
**Baseline:** `main@78ec81de514874ed7dc536f2eee19669d1cfec6b` (merge of PR #212, the Stage 4 plan)

This register is the only authoritative exit gate for Stage 4. The plan
`docs/superpowers/plans/2026-10-12-stage4-anpr-ocr.md` (§7 PR sequence, §8 rows) references these row IDs; it keeps no second acceptance list.

**Nothing unexecuted is marked PASS.** A row becomes PASS only when its evidence is entered here: commits, CI run IDs, or artefact SHA-256s with their retained location. Dataset bytes, crops and model weights never enter Git.

## Completion levels (never implied by one another)

1. **Harness implemented and tested** — code and deterministic fixture tests, in CI.
2. **Dataset onboarded and validated** — a release obtained under its ADR-017 record, the manifest frozen, the adapter's fail-closed reconciliation run on the real bytes, and the truth document written and hashed.
3. **Experiment executed** — E-A and E-B run on onboarded data with pinned, verified instruments; results retained by hash.
4. **Measurement accepted** — the verdict recorded under the frozen protocol and accepted here.

Every Stage-4 row is **Development** evidence (ADR-009, ADR-017 §9). No row is Production qualification. Production
plate search would additionally need a protected Indian holdout (ADR-015 §3–§4), qualified Runtime Pack variants, a
plate retention/access policy and the Production audit profile (plan §8).

## P. Rows

| Row | Requirement | Status | Evidence |
|---|---|---|---|
| P1 | Plate harness: ground truth, adapters, mappings, association, evaluators and verdict, with tests; ADR-017 release records | **PASS (level 1: harness implemented and tested)** | Ground truth `benchmark-plate-truth-v1` (`contracts/schemas/benchmark-plate-truth-v1.schema.json`, `tools/benchmarks/capabilities/plates/truth.py`). Production-path measurement `measure.py` imports `crop_region` and `JpegLadderEncoder(PRODUCTION_ENCODER_POLICY)`; a test pins byte equality with the production encoder. E-A `adequacy.py`; E-B `coverage.py` over the existing `benchmark-association-v1`; verdict `verdict.py`; instruments `instruments.py` (pinned by hash). Adapters `tools/benchmarks/datasets/ufpr_alpr.py` (sequences; also drives `prepare`/association) and `voc_plates.py` (Indian stills). CLI `tools/benchmarks/plates/cli.py`; result schema `benchmark-plate-adequacy-v1`. Tests: `tools/benchmarks/tests/test_plates_{contract,measurement,datasets}.py` (fixtures only). Release records: `docs/qualification/stage4/benchmarks/*.descriptor-template.json` (pinned to the adapters by test). Search record: `docs/qualification/stage4/benchmark-search-2026-10-12.md`. **Not** level 2: no release is onboarded (P3a) |
| P2 | Normalisation `mavi-plate-normalisation-v1` frozen; identical in Python and .NET | **PASS** | Contract and 36 vectors: `contracts/test-vectors/plate-normalisation-v1.json` (NFKC; ASCII-only upper-casing; nine named separators removed; everything else outside `[A-Z0-9]` rejects; no confusable substitution; advisory format class). Python `tools/benchmarks/plates/normalisation.py`, tested by `test_plates_contract.py`. .NET `Mavi.Application.Modules.Plates.PlateNormalisation`, tested by `tests/Mavi.Application.Tests/Plates/PlateNormalisationVectorTests.cs` (38 tests). Both read the same vector file |
| P3a | Level 2: datasets onboarded and validated (ADR-017 record, frozen manifest, fail-closed reconciliation on real bytes, truth hashed) | **PASS (Development)** | (1) **UC3M-LP**, Zenodo 17152029: archive MD5 `496e3b5e66b78d231f71d85c0e5e11a3` equals the record; SHA-256 `3b7ad510…223d`; CC BY 4.0; descriptor `0d88240c…`; test truth `02a127d3…` (371 images, 463 plates, 2 anonymised characters each; 24 five- or six-point polygons refused and listed). (2) **DataCluster Indian sample** at revision `2bb7cd4e`: CC BY-NC-ND 4.0; descriptor `caee87e9…`; truth `21c8759f…` (47 images, 52 plates, 25 text-labelled; EXIF-orientation defect found and fixed). (3) **BDD100K MOT 2020 val** (the Stage-3 H3 release, descriptor `7169263a…`, BDD100K licence already held), with R8 agent-verified plate labels: proposals `7d303d84…`, decisions `c258bfdd…`, labels `0bc089b1…`, sequence truth `709a560b…` (106 tracks, 488 frames, 485 text-usable). LSV-LP: licence permits academic non-commercial use (README `902ce892…` retained), but the Dropbox share is disabled (traffic limit) and Baidu needs an account. Only the 3-video official sample was obtained (`95c5c7c5…`) — below support, not used. Search record: `docs/qualification/stage4/benchmark-search-2026-10-12.md` |
| P3b | Instruments pinned and verified | **PASS** | `fast-plate-ocr` 1.1.0 (`cct-s-v2-global`, ONNX `384bbbd2…`, config `0335c74a…`; MIT) and `rapidocr-onnxruntime` 1.4.4 (PP-OCRv4 det `d2a7720d…`, rec `48fc40f2…`, cls `e47acedf…`; Apache-2.0). Both are verified against the real packages; the plate-specific adapter's colour handling was fixed. ONNX Runtime 1.31.0 runs on CPU, single-threaded and sequential. Specifications: `docs/qualification/stage4/instruments/*.json`. Environment: CPython 3.12.10, exact pins in `tools/benchmarks/plates/requirements-instruments.txt`, declared in the dependency policy (Development benchmark only); Pillow 11.3.0 and numpy 2.5.3 equal the vision lock. Pre-annotation detector (R8 geometry only, never an instrument): `open-image-models` 0.6.0, YOLOv9-s-608 plates `2b878b38…` (MIT) |
| P3c | Level 3: E-A executed | **EXECUTED** | **BDD100K (verdict input):** result `cc718922…` (tooling `b45bdcdf`). `h_min` = **32 px** (reference: plate-specific; native EM by bin 0/6, 2/15, 10/39, 72/117, 271/308). ΔEM at the supplemental cap, n = 308 plates from 65 sequences, full-plate basis: **plate-specific 0.97 pp** (271 → 268), **generic 1.95 pp** (84 → 78). Representative cap: 0.97 pp and 2.27 pp. No instrument errors. **UC3M-LP:** result `5de0e349…`; the repeat has identical rows and summary. Executed, **not accepted**: anonymisation erases characters, so native agreement is 6/449 and 0/449 — a floor effect. Its formal ΔEM of 0 pp is excluded from the verdict. Post-hoc diagnostic (masks removed, plate-specific): native 233, supplemental 232, representative 223 of 449. **DataCluster Indian:** `589f9f5d…` (repeat identical). NOT MEASURED (24 plates in the top bin, below the floor of 50); diagnostic only |
| P3d | Level 3: E-B executed | **EXECUTED** | BDD100K MOT val, the real MAVI Stage-3 H3 run on the release pipeline profile `afb03b6c…` (commit `35907342`; 200 exports with sealed evidence crops, each verified by SHA-256 and size; frame alignment checked). Association `bea73d13…/association.json`. Result `3db69e53…`. **R_oracle = 77** oracle-readable tracks (77 distinct vehicles), **R_ev = 51**, **C = 0.662**. The 26 failures are: matched but not readable 12; unmatchedGt 7; fragmentedGt 6; unverifiedGt 1. Evidence-readable tracks by role: Representative 48, NearView 43, LateDiverse 18, EarlyDiverse 14. Post-hoc diagnostic (not verdict evidence): among the 63 matched tracks, C = 51/63 = 0.81. 18 evidence observations had no verified plate label at their frame. Per-instrument C: plate-specific 51/77; generic 15/29 (insufficient) |
| P3 | Level 4: evidence-adequacy verdict (plan §3.4) with strata; protocol hashed before results | **MEASURED: INADEQUATE — confirmed on human-reviewed, AI-assisted labels (O5 complete): C = 53/79 = 0.671; frozen AI-label result C = 51/77 = 0.662 preserved** | Verdict `b740ce45…`: INADEQUATE, reason `coverage_below_0.70`. Protocol `docs/qualification/stage4/adequacy-protocol.md`, revision 1 (R6–R8 and the R6 clarification, all recorded before the results they govern; no threshold changed). Reproducibility: see *Reproduction and repeatability*. Limitations: E-B is US/Israel dashcam (BDD100K), 1280×720 at 5 fps labelled frames — **not Indian-domain validation**; the R8 labels are now human-reviewed, AI-assisted (O5 complete; `docs/qualification/stage4/o5-human-reviewed-recomputation-2026-10-13.md`); selection is bounded to the 240 widest-plate tracks |
| P4 | MSR events PLANNED → PROTOCOL_FROZEN; entry criteria §4.2 met | NOT STARTED | Gated on P3 (plan §4.2 item 1) |
| P5 | A–E measured; gates; technical ranking by D; consistent-wrong gate | NOT STARTED | PR-2 |
| P6 | Licence/deployment determinations per profile; owner implementation choice | NOT STARTED | PR-2 |
| P7 | Plate lifecycle: lease, fencing, evidence integrity, three-phase completion, supersession | NOT STARTED | PR-3 |
| P8 | Failure isolation (VisionJob, attributes and runs unaffected by a plate crash or OOM) | NOT STARTED | PR-3 |
| P9 | Bounded re-analysis; idempotent queueing | NOT STARTED | PR-3 |
| P10 | Search semantics, coverage, cursor v4, regression of existing populations, wire tests | NOT STARTED | PR-4 |
| P11 | Index plan and p95 budget at seeded scale; log redaction | NOT STARTED | PR-4 |
| P12 | UI journey, §34 sweep and a11y on plate states | NOT STARTED | PR-5 |
| P13 | Model/Runtime Packs: hashes, licence notices, `verify_repo`, disconnected install | NOT STARTED | PR-6 |
| P14 | Real end-to-end Track-level D through the product path, consistent with P5 | NOT STARTED | PR-6 |
| P15 | Engineering budget and 500-camera projection (M-E, projected) | NOT STARTED | PR-6 |
| P16 | Exact-head CI green for each Stage-4 PR | **PR-1: PASS (implementation head)** | PR #213 implementation head `150bd5ae4c38c74c99015c966cfb2d4f495bdd6d`: MAVI Quality Gate run 38258983601 success (benchmark-harness lane included), Task 10 Runtime Qualification 38258983558 success, Task 17 Acceptance Validation 38258983589 success, Qualification Tooling Windows 38258983535 success. This register update is documentation only |

## Evidence-adequacy results (2026-10-13)

**Verdict: INADEQUATE** (`coverage_below_0.70`). Encoding loss passes. Selection coverage does not.

What drives it:
- 14 of the 26 coverage failures are ground-truth vehicles with **no associated MAVI Track** (tracking or association failures on 5 fps dashcam footage). Alternatives X1–X3 (encoder and role parameters; native-frame re-read; a plate-aware role) cannot recover these.
- 12 are matched tracks whose sealed evidence did not yield the plate; part of this is unlabelled evidence frames (18 observations).
- The plan's §3.5 alternatives are recorded, **not selected**:
  - **X1** — re-derive encoder or role parameters (new pipeline profile);
  - **X2** — a platform-served native-resolution source-frame region at an Observation's frame (ADR-013 §10 amendment);
  - **X3** — a plate-aware evidence role (ADR-013 §4 amendment).
- None is implemented. The choice is owner decision O3.

**Protocol gap found** (to be resolved by a future revision, not post hoc). The frozen rules set no minimum native readability for the ΔEM population. UC3M-LP shows the consequence: with near-zero native agreement, ΔEM is 0 pp and meaningless. That result is excluded here by judgement, not by rule.

## Owner decisions (2026-10-13) and their outcomes

MAVI is classified by the owner as a **non-commercial, open-source academic research project**. Dataset terms are assessed on that basis.

### O5 — label verification

**Decision:** keep the agent-checked labels and audit sheets; run an independent, stratified verification; never present AI verification as human verification; keep the frozen INADEQUATE result unless verified evidence establishes a legitimate correction.

**Outcome.**
- **Sample:** 94 tracks, chosen with a fixed seed. Strata:
  - all 26 coverage failures;
  - 20 of the 51 successes;
  - all 28 legible tracks that were not oracle-readable (borderline);
  - 20 of the tracks transcribed illegible.
- **Plus 40 geometry crops** for the matched failures.
- **Re-verification:** done blind by a **separate AI agent** in a fresh context. It had access only to anonymised crops and never saw the labels.
- **Hashes:** mapping `72d38e1e…` (withheld from the verifier); answers `6c18bc61…`.

| Stratum | Both transcribed, equal | Both illegible | Label only (verifier: illegible) | Verifier only | Disagree |
|---|---|---|---|---|---|
| failure (26) | 21 | — | 5 | — | 0 |
| success (20) | 18 | — | 2 | — | 0 |
| borderline (28) | 10 | — | 17 | — | 1 (`T0209`, one digit, not in R_oracle) |
| illegible (20) | — | 18 | — | 2 | 0 |

- **Agreement:** where both readers gave a text they agree on **49 of 50**.
- **Conservatism:** the second reader was more conservative (it declined 24 labelled plates).
- **Geometry:** 38 of 40 boxes accepted. The 2 rejected boxes lie on matched-failure tracks whose evidence was already unreadable there, so **no outcome changes**.

**No verified evidence establishes a correction, so the frozen result stands.**

**Sensitivity check (diagnostic):** keep only plates both readers confirmed — the 5 unconfirmed failures are dropped, and the success rate 18/20 is extrapolated to the 51 successes. That gives C ≈ 45.9 / 66.9 ≈ **0.69**, still below 0.70.

**Limitation at the time of this AI-only step:** no human had reviewed the labels (resolved by the O5 human review below). Both readers are AI models. They are independent of each other's output, of both OCR instruments and of MAVI, but not human. The retained sheets (`sheets/`, `geometry-legible/`, `o5/verifier/`) allow a later human audit.

**O5 COMPLETE (2026-10-13): labels are human-reviewed, AI-assisted.**
- **Review:** an independent human reviewer inspected all 125 audit rows (decisions: accept 91, correct 6, reject 28) and agrees with the AI pre-review on 125/125.
- **Record:** `O5_Human_Review_Completed.xlsx` `fa336951…`, record `human-review-record.json` `cc9d7e8f…`.
- **Derived labels:** `labels-human-reviewed.json` `4764bb5f…`; the original `labels.json` and `audit-form.csv` are unchanged.
- **Recomputation under the frozen protocol:**
  - `h_min` 32 px; ΔEM 0.61 pp (plate-specific);
  - R_oracle 77 → 79; R_ev 51 → 53; C = 0.671;
  - **INADEQUATE (unchanged)**;
  - verdict `6dc95563…`; the sensitivity variant is identical.
- **Changed tracks:** only the 5 human-corrected illegible tracks. 2 enter R_oracle and are evidence-readable; 3 are usable but not oracle-readable.
- **Full record:** `docs/qualification/stage4/o5-human-reviewed-recomputation-2026-10-13.md`.
- The frozen AI-label result (`b740ce45…`) is preserved.

*History (audit package as prepared):*
- **Location:** `E:\MAVI-Controlled\Benchmarks\stage4-bdd-plates\o5\human-audit\` (outside Git; BDD100K imagery is not redistributed).
- **Scope:** 100 tracks and 125 form rows:
  - all 26 failures;
  - the 20-track success sample;
  - the 28 borderline tracks;
  - 32 disputed tracks;
  - the 20-track illegible sample;
  - 18 unlabelled evidence frames.
- **Contents:**
  - original frames, plate crops, sealed MAVI evidence crops, annotations and track identities;
  - accept / correct / reject columns in `audit-form.csv` (`ae40d398…`, unfilled).
- **Patch 1** added the original source frames, GT vehicle boxes and annotation-detector proposals for the 20 illegible rows (A035, A044, A077–A094).
  - Hashes: `index.html` `abdf9758…`, `manifest.json` `126f2a9d…` (every added asset hashed).
  - The unpatched package is kept in `o5\human-audit-original\`.
- **Reviewer:** may be any independent competent person, not necessarily the owner.
- *(Superseded by the completion above.)* Until the human review, nothing in this register described the AI verification as human verification.

### O3 — investigate the tracking misses first

**Outcome:** `docs/qualification/stage4/adequacy-root-cause-2026-10-13.md`.

- **The 14 unassociated vehicles:**
  - tracker fragmentation 6;
  - low detector confidence 4;
  - association policy floors 3;
  - IoU gate 1.

  All measured on **5 fps** labelled frames, so not representative of native-rate tracking.
- **The 12 matched failures:**
  - **selection 10** — near views fail evidence qualification. *Corrected after X1 from the selector's own records:*
    - left, right or top edge contact blocks 9;
    - the sharpness floor blocks 5;
    - NearView hysteresis blocks 1;
    - bottom contact alone blocks none.

    The first statement, "the box touches the border (GT proxy)", was an unvalidated inference.
  - encoding 1;
  - frame quality 1.
- **Recommendation:**
  1. measure X1 (done; **rejected** — see below);
  2. re-measure tracking on native-frame-rate footage before any tracker change.
- **Nothing is implemented. PR-6 stays held.**

**X1 measured (2026-10-13):** `docs/qualification/stage4/x1-edge-margin-2026-10-13.md`.
- **Candidate rule:** `x1-bottom-edge-exempt-vehicle-v1`. It is an experiment wrapper only; the release profile is unchanged.
- **Inputs:** the same 200 sequences, labels, instruments and frozen rules.
- **Run identities:** new ProcessingRun identities per arm and sequence.
- **Reproducibility:** live = baseline replay = the platform's H3 evidence in 200/200 sequences, and the baseline evaluation equals the frozen E-B.

**Results:**
- C: 51/77 → **51/77**;
- matched-Track C: 51/63 → 51/63;
- **0 of 10** selection failures recovered;
- 0 regressions;
- 13 of 11,892 Vehicle evidence observations changed, all qualified.

The theoretical maximum of a selection-only remedy is 10/77, giving C = 61/77 = 0.792 — **MARGINAL, not ADEQUATE**.

**Owner decision (2026-10-13): X1 REJECTED as formulated.** It is accepted as valid diagnostic evidence, and its byte-identical repeat and all hashes are preserved.
- The bottom-border exemption is not implemented in the release profile.
- It is not broadened to the left, right or top borders.
- **Next authorised selector investigation:** a bounded, measurement-only study of the sharpness floor at large NearView crops. The release profile and the frozen acceptance criteria stay unchanged.
- Native-frame-rate evidence remains a prerequisite for any tracker change.
- **PR-6 stays held.**

**Sharpness-floor diagnostic (measurement only):** `docs/qualification/stage4/sharpness-floor-diagnostic-2026-10-13.md` (result `f9930bca…`).
- Of 230 readable plate frames (≥ 32 px) on matched Tracks, **26 (11.3 %) fail the 0.05 floor**; 84 % of all floor-failing frames are readable.
- **Cause 1, dilution:** the plate region itself is sharp (median 0.099; 25 of 26 at or above the floor), while the whole-box mean is 0.040.
- **Cause 2, scale dependence:** within-Track ρ(area, sharpness) has a median of −0.67 over 3,076 Tracks. At a fixed 128-px height, 19 of 26 pass.
- **No profile or threshold change and no PR-6 decision.** Any scale-normalised revision is a separate owner decision.

### O1 — Indian validation, split on 2026-10-13 (owner decision)

BDD100K results are never presented as Indian-condition validation.

**O1A — Indian native-frame-rate tracking validation: IDD-X APPROVED.**
- **Protocol:** `docs/qualification/stage4/o1a-idd-x-tracking-design-2026-10-13.md` (Development, frozen at commit `a00deb76`, SHA-256 `6f2f6365…`).
- **Design:**
  - 25 fps native vs 5 fps decimated replays of the same recorded detections, through the unchanged release-profile tracker;
  - frozen association policy; ground-truth-side metrics only (association outcome, fragmentation, continuity, detection support);
  - reference comparison against the BDD 5 fps observations.
- **Minimum subset:** ≥ 200 ground-truth vehicle Tracks from ≥ 30 validation-split front-view videos; scenarios ≥ 2 s; deterministic selection; estimated 4–8 GB.
- **Download gate:** nothing is downloaded until the owner confirms the portal allows selective acquisition (annotations first). The 160 GB archive is not downloaded.
- **Permission:** the organisation holds research/academic permission under the IIIT Hyderabad collaboration; the India Data DUA also applies.

**O1B — Indian ANPR/OCR validation: OPEN.**
- IDD-X is **excluded**: the distributed data has blurred licence plates. The collaboration permission does not restore missing plate pixels.
- The search continues for an admissible Indian video source with visible plates, or for a bounded, purpose-built Indian research corpus (ADR-017 §2).
- Per plan §3.3, the Indian Track-level gap blocks neither PR #213 nor PR-3. PR-2's entry criterion (§4.2 item 3) needs an Indian **still** dataset release record.

**Other leads:** the IITH accident CCTV dataset; terms not established.

### Development

- PR-3 is authorised with stand-in models, independently of PR #213.
  - First slice on branch `stage4/pr3-plate-lifecycle`, local and not pushed: the ADR-013 amendment, contracts, domain, migration and the Python fixture skeleton.
- PR-4 and PR-5 follow their dependencies.
- PR-6 is held; X1 did not remedy O3, and further profile changes need owner approval.

## Reproduction and repeatability

- **Hosts:** Windows 11 Development host (GTX 1650 Ti 4 GiB). Detector vehicle candidates run on the qualified CUDA vision runtime through the worker's own composition (`tools/benchmarks/plates/vehicle_candidates.py`). Instruments run on CPU, single-threaded, in CPython 3.12.10.
- **Commands:** `python -m tools.benchmarks.plates.annotate propose|sheets|labels …`, then `python -m tools.benchmarks.plates.cli truth|ea|eb|verdict …` (protocol §7).
- **Results:** retained create-only under `E:\MAVI-Controlled\Benchmarks\{stage4-bdd-plates,uc3m-lp,datacluster-indian-number-plates-sample}\…\results\`.
- **Repeatability:**
  - DataCluster E-A: repeat byte-identical (`589f9f5d…`).
  - UC3M-LP E-A: rows and summary identical; only the protocol and tooling identity differ, because the repeat ran after the R8 commit.
  - BDD E-A and E-B: repeat runs at the same tooling commit `b45bdcdf` are **byte-identical** — E-A `cc718922…`, E-B `3db69e53…`.
  - Verdict `b740ce45…`. O3 analysis `6f5b2e56…` and `1f3dea4a…`. O5 re-verification `6c18bc61…`.
