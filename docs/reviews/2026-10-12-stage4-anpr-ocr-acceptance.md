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
| P1 | Plate harness: ground truth, adapters, mappings, association, evaluators and verdict, with tests; ADR-017 release records | **PASS (level 1: harness implemented and tested)** | Ground truth `benchmark-plate-truth-v1` (`contracts/schemas/benchmark-plate-truth-v1.schema.json`, `tools/benchmarks/capabilities/plates/truth.py`). Production-path measurement `measure.py` imports `crop_region` and `JpegLadderEncoder(PRODUCTION_ENCODER_POLICY)`; a test pins byte equality with the production encoder. E-A `adequacy.py`; E-B `coverage.py` over the existing `benchmark-association-v1`; verdict `verdict.py`; instruments `instruments.py` (pinned by hash). Adapters `tools/benchmarks/datasets/ufpr_alpr.py` (sequences; also drives `prepare`/association) and `voc_plates.py` (Indian stills). CLI `tools/benchmarks/plates/cli.py`; result schema `benchmark-plate-adequacy-v1`. Tests: `tools/benchmarks/tests/test_plates_{contract,measurement,datasets}.py` (fixtures only). Release records: `docs/qualification/stage4/benchmarks/*.descriptor-template.json` (pinned to the adapters by test). Search record: `docs/qualification/stage4/benchmark-search-2026-10-12.md`. **Not** level 2: no release is onboarded (P3a). Model-selection evaluators A–D and the query generator (assigned to PR-1, omitted): see *Correction and repair record* below |
| P2 | Normalisation `mavi-plate-normalisation-v1` frozen; identical in Python and .NET | **PASS** | Contract and 36 vectors: `contracts/test-vectors/plate-normalisation-v1.json` (NFKC; ASCII-only upper-casing; nine named separators removed; everything else outside `[A-Z0-9]` rejects; no confusable substitution; advisory format class). Python `tools/benchmarks/plates/normalisation.py`, tested by `test_plates_contract.py`. .NET `Mavi.Application.Modules.Plates.PlateNormalisation`, tested by `tests/Mavi.Application.Tests/Plates/PlateNormalisationVectorTests.cs` (38 tests). Both read the same vector file |
| P3a | Level 2: datasets onboarded and validated (ADR-017 record, frozen manifest, fail-closed reconciliation on real bytes, truth hashed) | **PASS (Development)** | (1) **UC3M-LP**, Zenodo 17152029: archive MD5 `496e3b5e66b78d231f71d85c0e5e11a3` equals the record; SHA-256 `3b7ad510…223d`; CC BY 4.0; descriptor `0d88240c…`; test truth `02a127d3…` (371 images, 463 plates, 2 anonymised characters each; 24 five- or six-point polygons refused and listed). (2) **DataCluster Indian sample** at revision `2bb7cd4e`: CC BY-NC-ND 4.0; descriptor `caee87e9…`; truth `21c8759f…` (47 images, 52 plates, 25 text-labelled; EXIF-orientation defect found and fixed). (3) **BDD100K MOT 2020 val** (the Stage-3 H3 release, descriptor `7169263a…`, BDD100K licence already held), with R8 agent-verified plate labels: proposals `7d303d84…`, decisions `c258bfdd…`, labels `0bc089b1…`, sequence truth `709a560b…` (106 tracks, 488 frames, 485 text-usable). LSV-LP: licence permits academic non-commercial use (README `902ce892…` retained), but the Dropbox share is disabled (traffic limit) and Baidu needs an account. Only the 3-video official sample was obtained (`95c5c7c5…`) — below support, not used. Search record: `docs/qualification/stage4/benchmark-search-2026-10-12.md` |
| P3b | Instruments pinned and verified | **PASS** | `fast-plate-ocr` 1.1.0 (`cct-s-v2-global`, ONNX `384bbbd2…`, config `0335c74a…`; MIT) and `rapidocr-onnxruntime` 1.4.4 (PP-OCRv4 det `d2a7720d…`, rec `48fc40f2…`, cls `e47acedf…`; Apache-2.0). Both are verified against the real packages; the plate-specific adapter's colour handling was fixed. ONNX Runtime 1.31.0 runs on CPU, single-threaded and sequential. Specifications: `docs/qualification/stage4/instruments/*.json`. Environment: CPython 3.12.10, exact pins in `tools/benchmarks/plates/requirements-instruments.txt`, declared in the dependency policy (Development benchmark only); Pillow 11.3.0 and numpy 2.5.3 equal the vision lock. Pre-annotation detector (R8 geometry only, never an instrument): `open-image-models` 0.6.0, YOLOv9-s-608 plates `2b878b38…` (MIT) |
| P3c | Level 3: E-A executed | **EXECUTED** | **BDD100K (verdict input):** result `cc718922…` (tooling `b45bdcdf`). `h_min` = **32 px** (reference: plate-specific; native EM by bin 0/6, 2/15, 10/39, 72/117, 271/308). ΔEM at the supplemental cap, n = 308 plates from 65 sequences, full-plate basis: **plate-specific 0.97 pp** (271 → 268), **generic 1.95 pp** (84 → 78). Representative cap: 0.97 pp and 2.27 pp. No instrument errors. **UC3M-LP:** result `5de0e349…`; the repeat has identical rows and summary. Executed, **not accepted**: anonymisation erases characters, so native agreement is 6/449 and 0/449 — a floor effect. Its formal ΔEM of 0 pp is excluded from the verdict. Post-hoc diagnostic (masks removed, plate-specific): native 233, supplemental 232, representative 223 of 449. **DataCluster Indian:** `589f9f5d…` (repeat identical). NOT MEASURED (24 plates in the top bin, below the floor of 50); diagnostic only |
| P3d | Level 3: E-B executed | **EXECUTED** | BDD100K MOT val, the real MAVI Stage-3 H3 run on the release pipeline profile `afb03b6c…` (commit `35907342`; 200 exports with sealed evidence crops, each verified by SHA-256 and size; frame alignment checked). Association `bea73d13…/association.json`. Result `3db69e53…`. **R_oracle = 77** oracle-readable tracks (77 distinct vehicles), **R_ev = 51**, **C = 0.662**. The 26 failures are: matched but not readable 12; unmatchedGt 7; fragmentedGt 6; unverifiedGt 1. Evidence-readable tracks by role: Representative 48, NearView 43, LateDiverse 18, EarlyDiverse 14. Post-hoc diagnostic (not verdict evidence): among the 63 matched tracks, C = 51/63 = 0.81. 18 evidence observations had no verified plate label at their frame. Per-instrument C: plate-specific 51/77; generic 15/29 (insufficient) |
| P3 | Level 4: evidence-adequacy verdict (plan §3.4) with strata; protocol hashed before results | **MEASURED: INADEQUATE — confirmed on human-reviewed, AI-assisted labels (O5 complete): C = 53/79 = 0.671; frozen AI-label result C = 51/77 = 0.662 preserved** | Verdict `b740ce45…`: INADEQUATE, reason `coverage_below_0.70`. Protocol `docs/qualification/stage4/adequacy-protocol.md`, revision 1 (R6–R8 and the R6 clarification, all recorded before the results they govern; no threshold changed). Reproducibility: see *Reproduction and repeatability*. Limitations: E-B is US/Israel dashcam (BDD100K), 1280×720 at 5 fps labelled frames — **not Indian-domain validation**; the R8 labels are now human-reviewed, AI-assisted (O5 complete; `docs/qualification/stage4/o5-human-reviewed-recomputation-2026-10-13.md`); selection is bounded to the 240 widest-plate tracks |
| P4 | MSR events PLANNED → PROTOCOL_FROZEN; entry criteria §4.2 met | NOT STARTED | Gated on P3 (plan §4.2 item 1) |
| P5 | A–E measured; gates; technical ranking by D; consistent-wrong gate | NOT STARTED | PR-2 |
| P6 | Licence/deployment determinations per profile; owner implementation choice | NOT STARTED | PR-2 |
| P7 | Plate lifecycle: lease, fencing, evidence integrity, three-phase completion, supersession | **PASS (Development, fixture inferencer)** — P16: PR #217 final content head `c3ec75ec`, MAVI Quality Gate 38417824409, Task 10 Runtime Qualification 38417824408, Task 17 Acceptance Validation 38417824591, Qualification Tooling Windows 38417824410, all success; with the local evidence below | PR-3, branch `stage4/pr3-plate-lifecycle` on `main@4e69ec3f`; ADR-013 implementation amendment items 11–15, accepted by the owner on 2026-10-13 as an architecture decision (not qualification evidence). **Lease and fencing:** a capability-specific `PlateAnalysis`; a fingerprint-fenced `FOR UPDATE SKIP LOCKED` claim of Vehicle Tracks only; heartbeat; attempt, capability and owner fencing on every lease-scoped call; reclaim only after expiry; deadline and attempt exhaustion, including a Queued unit left with no permitted attempt after `MaximumAttempts` is lowered (`PlateAnalysisTests`, `PlateApiTests`). **Evidence integrity:** lease-scoped reads refuse a missing or size-mismatched accepted crop with an authoritative `422` and an integrity count; transport faults are retried, never evidence. A worker's `evidence_missing`/`evidence_integrity_failed` crop is a claim the platform confirms against the object at rest before sealing, reason included (missing ⇒ `evidence_missing`; wrong size or SHA-256 ⇒ `evidence_integrity_failed`); any other claim is refused (`plate_evidence_claim_contradicted`, retryable). Confirmed incidents are counted once per crop for a publication, its replay, or a commit whose outcome is unknown (best-effort, in-process health signal). **Three-phase completion:** fenced validation (typed rules; the bounded v1 profile 2/1/3 with no truncation; the frozen normalisation re-derived by the platform; one cross-language reading order, UTF-16 code units, vector `plate-reading-order-v1.json`; a duplicate reading has no order, so the worker abstains that crop with `ocr_output_invalid` and the rest of the run publishes — `ACropAbstainedForAnOcrOutputFaultKeepsItsProposalsAndTheRestOfTheRunPublishes`); streamed artefact check; idempotent content-addressed seal; re-fenced publication with binary `COPY`. A reclaim between seal and publication publishes nothing; a lost publication commit (`BeforeCommit` seam) publishes nothing and its replay publishes exactly once (`AnAmbiguousPublicationCommitPublishesNothingAndItsReplayPublishesExactlyOnce`); a constraint violation in the rows or in the unit's own update is refused for good (`plate_persistence_refused`; the worker fails the attempt with the non-retryable `plate_publication_refused`, never `plate_output_invalid`), and a transient database fault is retried. **Outcome completeness:** a published analysis has exactly one outcome (Analysed or Unavailable) for every leased Vehicle Track; a missing, duplicate, unleased, extra or outcome-less Track is refused before anything is published (`PlateCompletionValidatorTests`; `APublishedAnalysisHasExactlyOneOutcomeForEveryLeasedVehicleTrack`). **Supersession:** only on a successful preferred completion; the default is derived and a binding rollback re-derives it. **Completion at the 10,000-Track bound** (the row-worst 2/1/3 shape, 210,000 fact rows; not the byte-worst): artefact 48,540,608 B, 14,503,488 B below the worst-case bound 63,044,096 B; completion 7.99–8.30 s inside the 15 s request budget (8.27 s re-confirmed after the cold-review fixes); barrier hold 23–27 ms; ≈ 0.9 GiB managed allocation; synchronous completion stands — `docs/qualification/stage4/2026-10-13-plate-completion-at-the-track-bound.md`. **Real worker end to end:** `PlateEndToEndTests` runs `mavi_vision.plates.main` through the real lease plane to Ready |
| P8 | Failure isolation (VisionJob, attributes and runs unaffected by a plate crash or OOM) | **PASS (Development, fixture inferencer)** — P16: PR #217 final content head `c3ec75ec`, MAVI Quality Gate 38417824409, Task 10 Runtime Qualification 38417824408, Task 17 Acceptance Validation 38417824591, Qualification Tooling Windows 38417824410, all success; with the local evidence below | What is proven, and how: (1) **Worker process loss during a live lease** — `PlateEndToEndTests.AWorkerKilledMidAttemptCostsOnlyItsLeaseAndNoPartialFactIsEverVisible` kills the real `mavi_vision.plates.main` at its completion call, after its predictions artefact is staged and while a test gate holds that request *before* the platform processes it. The lease expires and is reclaimed; attempt 2 by another worker completes to Ready with one accepted artefact; one-snapshot sampling every 50 ms throughout shows plate facts only as zero rows or as the full published set; row digests of `processing_runs`, `tracks`, `observations`, `vision_jobs`, `visual_attribute_analyses`, `visual_attributes` and every `artifacts` row except `PlatePredictions` are unchanged, with a **completed, published attribute unit** and the run's VisionJob present. This kill does **not** interrupt the platform mid-publication. (2) **Failure inside the publication** — `PlateApiTests.AnAmbiguousPublicationCommitPublishesNothingAndItsReplayPublishesExactlyOnce` fails the Phase C commit after every row is written and the barrier is held: nothing partial is visible (one snapshot), readiness stays Pending, and the replay publishes exactly once. (3) **Crash or exhaustion without a worker** — `PlateApiTests.APlateCrashOrExhaustionLeavesTheRunTracksAndAttributeUnitsUntouched`. (4) **Process and storage isolation** — the plates role is its own process and lease plane, with no VisionJob or attribute lease touched; its staging `staging-plates/` has its own janitor, and the attribute janitor has no authority over it (`PlateStagingTests`). **Not covered:** no OOM injection (an OOM is a process loss, as in (1)), and no crash of the platform process itself mid-publication (the ambiguous-commit seam stands in for it). Local results: integration plate tests on an isolated database; the quality gate sets `MAVI_S2B_WORKER_PYTHON`, so CI runs (1) |
| P9 | Bounded re-analysis; idempotent queueing | **PASS (Development, fixture inferencer)** — P16: PR #217 final content head `c3ec75ec`, MAVI Quality Gate 38417824409, Task 10 Runtime Qualification 38417824408, Task 17 Acceptance Validation 38417824591, Qualification Tooling Windows 38417824410, all success; with the local evidence below | **Queueing:** automatic only for runs completed after the identity's activation (no backfill); idempotent through the (run, identity) unique index, which also resolves concurrent queuers. **Explicit re-analysis** `POST /api/plates/reanalysis` takes exactly one of: a run list, which queues exactly the supplied runs, never newer ones; or a camera window, which selects for every VideoAsset overlapping it exactly its latest completed, visible ProcessingRun. That is the highest visibility sequence, unique by `ux_processing_runs_visibility_sequence`, so there is no tie; older, superseded or never-visible runs are never selected. `Plates:MaximumRunsPerReanalysisRequest` (at most the plan's 100) applies after that selection, and a request over it is refused whole; repeat requests are no-ops; the response and audit event 2125 carry the exact selected run ids, and a refused request that reaches the handler is audited with its scope and refusal code (event 2126; a request carries no plate value). A body that fails JSON binding is rejected by the framework before the handler and is not audited. Tests: `PlateReanalysisSelectionTests` (5) and `PlateApiTests.ReanalysisIsExplicitBoundedAndIdempotent` |
| P10 | Search semantics, coverage, cursor v4, regression of existing populations, wire tests | NOT STARTED | PR-4 |
| P11 | Index plan and p95 budget at seeded scale; log redaction | NOT STARTED | PR-4 |
| P12 | UI journey, §34 sweep and a11y on plate states | NOT STARTED | PR-5 |
| P13 | Model/Runtime Packs: hashes, licence notices, `verify_repo`, disconnected install | NOT STARTED | PR-6 |
| P14 | Real end-to-end Track-level D through the product path, consistent with P5 | NOT STARTED | PR-6 |
| P15 | Engineering budget and 500-camera projection (M-E, projected) | NOT STARTED | PR-6 |
| P16 | Exact-head CI green for each Stage-4 PR | **PR-1: PASS (final content head)**; **PR-3: PASS (final content head)** | PR #213 final content head `a01b39211dd57427e70d1eda9e37d7dd061d84ae` (Codex review fixes): MAVI Quality Gate run 38355874050 success, Task 10 Runtime Qualification 38355874035 success, Task 17 Acceptance Validation 38355874138 success, Qualification Tooling Windows 38355874023 success (43 checks pass, 2 skipped, 0 failing). Earlier heads: `2ff686ce` (runs 38352852989/983/986/995) and implementation head `150bd5ae` (runs 38258983601/558/589/535), all success. This register update is documentation only and is not itself re-cited here; its own head's CI is reported on the PR. **PR-3:** PR #217 final content head `c3ec75ecc6c20d6eeb8d5a6e652ad1fde2300c70`: MAVI Quality Gate run 38417824409 success, Task 10 Runtime Qualification 38417824408 success, Task 17 Acceptance Validation 38417824591 success, Qualification Tooling Windows 38417824410 success (32 checks pass, 7 skipped, 0 failing). The register update recording this (P7–P9 to PASS and this entry) is documentation only and is not itself re-cited here |

**PR-3 independent review gate (P7–P9; a process fact, not CI evidence).** Four independent cold-review rounds were held on PR-3: on `34af1e33`, `3effb91b`, `31973f4f` and `c3ec75ec`. Each earlier round's findings were fixed or recorded (see the known limitations below); the final round, on `c3ec75ec`, found no findings.

**PR-3 local development note (P7–P9).** Until PR-3's commit "re-pin identities to the frozen normalisation; bounded v1 profile", .NET restores on the Development workstation read the machine NuGet package cache on C: (read-only; no package was downloaded and no dependency changed). From that commit on, every NuGet, dotnet and temporary path was on E:. This is a local development deviation only; it affects no artefact, identity or result. PR-3 integration results were taken on an isolated PostgreSQL (a private throwaway cluster), never on a database shared with another worktree.

**PR-3 known limitations (recorded after the 2026-10-13 cold review; none is a Production claim).**
- **Canonical form is not verified by the platform.** The worker writes `PlatePredictions` as canonical JSON. The platform validates its content with a streaming reader and seals the received bytes by size and SHA-256, but does not re-serialise them or check byte-canonical form. The same holds for `AttributePredictions` (ADR-013 item 6).
- **`Plates:Enabled` off stops the whole authority loop.** It stops activation, queueing, the deadline/exhaustion sweep and the staging janitor, while the control plane still serves a configured release. A leased unit is then reclaimed only on lease expiry by another worker, and plate staging is never reclaimed. A deployment that serves plate workers runs the host on (`PlateOptions.Enabled`).
- **NFKC Unicode-table divergence.** The frozen `mavi-plate-normalisation-v1` (SHA-256 `6e505158…bf935`) relies on NFKC, and the worker's Python and the platform's .NET (ICU) may carry different Unicode versions. If they disagree on a character, the platform's re-derived Track texts differ from the worker's and the completion is refused (`plate_track_texts_invalid`), failing the unit. The frozen vectors pass on both sides; the semantics are unchanged, and a change needs a new normalisation id.
- **No authorisation on the re-analysis endpoint.** `POST /api/plates/reanalysis` has none, like every MAVI route before stage 10 (ADR-010). It is bounded and audited, but unauthenticated: a pre-Production limitation.
- **An OCR-output-fault abstention does not retain the crop's readings (owner decision, 2026-10-13; a recorded trade-off, not qualification evidence).** `ocr_output_invalid` — including a duplicate or non-strict reading sequence — keeps the crop's detector proposals, their scores and the reason code, but not its readings: the v1 abstained-crop shape has no slot for them. It is the same as the existing malformed-reading path, an explicit exception to "all outputs within the bounds are retained", and retaining rejected readings would require a new `PlatePredictions` artefact version (ADR-013 item 15).
- **Audit event 2126 covers only requests that reach the handler.** A re-analysis body that fails JSON binding is rejected by the framework before the handler and is not audited.
- **The integrity health counter is best-effort and in-process.** It counts once per crop on publication, replay and an unknown commit outcome (which may have rolled back). It restarts with the platform; the authoritative record is each published Track outcome's reason.
- **The evidence-claim check is not timed at scale.** At most one SHA-256 per claimed crop of matching size, inside the publication window; see the timing record.
- **The timing measurement is row-worst, not byte-worst.** The fit of every admitted artefact under 64 MiB rests on the worst-case bound vector, not on the measurement.

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

## Review follow-up (Codex review of `b7e37793`, 2026-10-13)

These are tooling corrections only. No frozen result, threshold or verdict changes, and every recorded input satisfies the new checks.

- **E-B input binding.** E-B now refuses inputs that were not computed together:
  - an association whose envelope names a different descriptor or export set;
  - an E-A computed from a different truth, instrument specifications or instrument identities.

  The frozen and human-reviewed inputs pass: the descriptor is `7169263a…`, the 200 exports equal the envelope's, and the E-A and E-B instruments are identical.
- **UFPR truth.** An incompletely acquired sequence is now refused (`source_manifest_incomplete`) instead of being silently dropped.
- **Pixel adequacy `U_role`** (plan §3.4 criterion 3; reported, not part of the verdict rule) is now in the E-A summary. Computed from the recorded E-A rows:

  | Labels | Representative and supplemental, native ≥ `h_min` | All plates |
  |---|---|---|
  | Frozen | 308/308 = 1.000 | 308/485 = 0.635 |
  | Human-reviewed | 329/329 = 1.000 | 329/514 = 0.640 |

  No plate that is at least `h_min` natively falls below it after cropping and encoding (BDD vehicle crops are not downscaled). The coverage gap is selection and tracking, not pixels.
- **Instrument environment offline packaging (AGENTS.md):**
  - `Prepare-MaviDeveloperOfflineCache.ps1` now carries its CPython 3.12 win_amd64 wheelhouse and its model payloads (`tools/benchmarks/plates/instrument-payloads-v1.json`, SHA-256 verified).
  - `tools/benchmarks/plates/Install-PlateInstrumentEnvironment.ps1` installs it disconnected (`pip --no-index`, verified model staging).
  - Updated alongside: the binary catalog, the dependency policy, the Setup contract checks and the runbook.
  - Checked on this host: 57 binary wheels and 3 external payloads fetched; offline install into a fresh environment; the instruments read 12 audit plate crops identically, text and confidence, to the environment that produced the frozen results.

## Correction and repair record: A–D evaluators and query generator (2026-10-13; revised after cold review 2026-10-14)

**Correction.** The Stage-4 plan (§7, PR-1 files) assigned these to PR-1:
- the model-selection evaluators A–D (`tools/benchmarks/capabilities/plates/evaluator.py`);
- the deterministic query generator (`queries.py`);
- a query-generator determinism test.

**PR-1 (PR #213) omitted them.** It delivered the ground truth, the dataset adapters, the evidence-adequacy experiments E-A/E-B and the verdict; P1's "evaluators" covered those adequacy evaluators only.

**This repair (PR #218, branch `stage4/plate-harness-evaluators`) closes that implementation omission. None of PR-1's frozen evidence, hashes, thresholds, calculations or INADEQUATE verdict changes, and no P1–P3 row status changes.** The adequacy measurement never used A–D.

**What the repair implements**
- The decisions it encodes are written in `docs/qualification/stage4/plate-selection-decision-record-2026-10-14.md`, which separates owner decisions, plan-derived rules, diagnostic-only values, proposed frozen values and still-open values.
- C and D run candidate outputs through PR-3's own `mavi_vision.plates.pipeline` and the frozen `mavi-plate-normalisation-v1`; confidence is reading-level.
- Any PR-3 output-contract violation is a hard CONTRACT_FAIL for the evaluation run, kept for audit and never scored through. That includes more than 2 detector proposals, also in A.
- The ranking OCR floor 0 is enforced in code; the diagnostic floors have separate entry points.
- Candidate silence scores zero. `INSUFFICIENT_EVIDENCE` is reserved for corpus deficiency.
- Every truth class is accounted for: text, unsupported, unqueryable, `NO_PLATE`, `UNREADABLE`, `NO_GT_VEHICLE`.
- Query sets are bound by SHA-256 to the population manifest.
- D terms, ΔD and the bootstrap replicates are exact rationals (no epsilon). The fast bootstrap is proven identical to re-evaluation.
- The superiority rule and the cluster unit (physical capture site) are the owner's.

**Tests:** `tools/benchmarks/tests/test_plates_selection_harness.py`, synthetic fixtures only; no dataset and no model is read.

**Gate.** This repair must merge before the PR-2 events reach `PROTOCOL_FROZEN` (plan §4.2 item 2). It is level 1 evidence (harness implemented and tested).

## Reproduction and repeatability

- **Hosts:** Windows 11 Development host (GTX 1650 Ti 4 GiB). Detector vehicle candidates run on the qualified CUDA vision runtime through the worker's own composition (`tools/benchmarks/plates/vehicle_candidates.py`). Instruments run on CPU, single-threaded, in CPython 3.12.10.
- **Commands:** `python -m tools.benchmarks.plates.annotate propose|sheets|labels …`, then `python -m tools.benchmarks.plates.cli truth|ea|eb|verdict …` (protocol §7).
- **Results:** retained create-only under `E:\MAVI-Controlled\Benchmarks\{stage4-bdd-plates,uc3m-lp,datacluster-indian-number-plates-sample}\…\results\`.
- **Repeatability:**
  - DataCluster E-A: repeat byte-identical (`589f9f5d…`).
  - UC3M-LP E-A: rows and summary identical; only the protocol and tooling identity differ, because the repeat ran after the R8 commit.
  - BDD E-A and E-B: repeat runs at the same tooling commit `b45bdcdf` are **byte-identical** — E-A `cc718922…`, E-B `3db69e53…`.
  - Verdict `b740ce45…`. O3 analysis `6f5b2e56…` and `1f3dea4a…`. O5 re-verification `6c18bc61…`.
