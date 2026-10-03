# Stage 3 S3.2 — Vehicle subclass measurement: export, corpus, labelling, evaluation

**Status:** implementation plan for review. Nothing here is implemented.
**Baseline:** `main@d7508201b217261bed9979390ebfaa0bf61b8e18` (PR #145, S3.1).
**Governing:**
- ADR-016: detector-native subclass, evaluation first.
- ADR-015: C+ — public material is for development and evaluation, never frozen qualification.
- ADR-005: hash-bound pipeline profile.
- ADR-013: Evidence Set.

**Question S3.2 answers.** Is the detector-native per-Track vehicle subclass good enough to carry into Stage-3 operational exposure, or is further development needed?

S3.2 produces the **evidence** for that decision. It does not make the decision, expose subclass, tune the vote, or add a classifier.

**This measurement is Track-conditional.** It evaluates subclass classification *given that MAVI produced the Track*. It is not an end-to-end detection or tracking accuracy measurement. Every result artefact and report states this.

---

## 1. Current baseline (checked in code)

| Capability | Location | S3.2 use |
|---|---|---|
| Subclass on `Track`: `object_subclass`, `object_subclass_vocabulary`, `object_subclass_source` (`detector-native:<pipelineProfileSha256>`), with three DB check constraints (state, value, identity) | `Mavi.Domain/Intelligence/Track.cs`, `VehicleSubclass.cs`; migration `20261002120000_AddTrackObjectSubclass` | the predictions under measurement |
| Vote: confidence-weighted, exact micro-units, `minShare` 0.6, `minMatchedDetections` 3, provisional | `src/vision/mavi_vision/common/subclass.py`; profile `phase1-detection-tracking-v1.json` `1.3.0-candidate` | measured as is; **never tuned on pilot data** |
| Run attestation (producer identity) | `GET /api/processing/runs/{id}/attestation`. Source: `ProcessingOrchestrator.GetCompletedRunAttestationAsync` (Completed with `CompletedAtUtc`). Response built in `Mavi.Api/Endpoints/ProcessingEndpoints.cs` | embedded in the export through one shared builder (T1) |
| Evidence Set: ≤4 role-tagged observations (Representative, NearView, EarlyDiverse, LateDiverse), each with frame, offset, box and evidence artefact (SHA-256 on the artefact row) | `TrackDetailResponse.Observations`; selector `evidence-selector-v1-two-tier`, scorer `quality-v2`, both in the hash-bound profile | the reviewer's crops and context frames |
| Provenance-bound evaluator: producer identity, attested profile equals the measured profile file, per-Track source check, fail-closed | `tools/phase1/evaluate_vehicle_subclass.py` (event-matching mode) | gains a Track-label mode (T2) |
| Optional `vehicleSubclass` on Phase-1 ground-truth events | `sample-data/ground-truth/phase1-ground-truth.schema.json` | unchanged; not used for Track labels |
| Public-data release record and use authorisation (R-5) | `tools/qualification/attributes/datasets/release.py` (`mavi-attribute-dataset-release-v1`, `parse_release`, `verify_release_files`, `authorise_release_use`) | the corpus release record (T7) |
| Import: ISO-MP4 container only (`.mp4`; brand not `qt`/`3gp`/`3g2`) | `Mavi.Application/Modules/Media/VideoImportService.cs` (`PhaseOneMp4ContainerPolicy`) | derivation step (T8) |

**Gaps, and how S3.2 closes them:**
- **Export path:** nothing exports Tracks with subclass. The Track API must not carry it in S3.2 (that is S3.3), and no Python DB driver is approved. → a read-only .NET export tool (T1).
- **Evaluator shape:** the evaluator matches Tracks to independent ground-truth *events*. Human labels attach to MAVI Tracks themselves, so routing them through event matching would be circular. → a Track-label mode (T2).

S3.1 needs no redesign. Inspection found no correctness blocker.

## 2. Objective

A defensible, attributable, Track-conditional measurement of detector-native subclass on real public traffic footage, from human Track-level labels:
- **pilot:** 100–150 usable Vehicle Tracks;
- **expansion:** toward 300–500 only if justified (§14).

It is compared against requirements recorded **before** the results are seen (§13).

## 3. Architecture and flow

```
public release ──T7 verify/record──▶ release record (+R-5) ──T8 derive──▶ MP4 + derivation manifest
     ──T9 import/process (Development host, profile 1.3.0-candidate)──▶ completed runs
     ──T1 export (read-only .NET)──▶ export + evidence/ (per run, hashed)
     ──T3 sample (prediction-blind)──▶ sample ──T4 pack (blind)──▶ labelling pack (manifest hash)
     ──T5 label (static page) ×reviewers──▶ drafts ──T5 freeze──▶ label artefacts (+ adjudication)
     ──T2/T6 evaluate (Track-label mode)──▶ measurement result ──T6 compare──▶ requirement status table
```

**Every arrow is hash-bound:**
- each artefact records the SHA-256 identities of its inputs;
- each consumer re-verifies them and refuses on mismatch;
- data artefacts live outside Git under `E:\MAVI-Controlled\…\S3\`;
- only schemas, tools, tests and the hash-only evidence record (§20) are committed.

## 4. Slice boundaries

| Slice | Tasks | Fixtures only? | Real CityFlow | R-5 | Development host | Human labelling |
|---|---|---|---|---|---|---|
| **S3.2a — tooling** | T1–T6 | **Yes** | – | – | – | – |
| **S3.2b — corpus intake** | T7–T9 | – | Yes | **Yes** | T9 | – |
| **S3.2c — pilot** | T10 | – | Yes | (done in b) | – | **Yes** |
| **S3.2d — expansion** | T11 (conditional) | – | Yes | – | maybe | **Yes** |

## 5. Contracts and schemas (all new, under `contracts/schemas/`, each with an example validated by `verify_repo`)

**Rules common to every artefact**
- **Canonical JSON:** UTF-8, sorted keys, no insignificant whitespace, round-trip float formatting, and no wall-clock fields.
- **Identity:** the SHA-256 of the canonical bytes.
- **Producers:** write once, and refuse an existing output.

| Schema | Purpose | Key members |
|---|---|---|
| `vehicle-subclass-measurement-export-v1` | one completed run | see T1 |
| `vehicle-subclass-sample-v1` | the selected Tracks | `seed`, `target`, `exportSha256s[]`, `requirements{sha256, gitCommit, gitPath}`, `excludedSampleSha256s[]`, `derivationSha256s[]`, `releaseRecordSha256`, `design{kind: continuation|supplemental, samplingAlgorithm, parameters, releaseId, parentSampleSha256s[], reason?}` (`reason` present exactly when `kind` is `supplemental`), `allocation{video: {available, floor, quota}}`, `strata`, `selected[]`, `overlapSelected[]`, `excluded{reason:count}`, `available{stratum:count}` |
| `vehicle-subclass-labeling-pack-v1` | the manifest of reviewer-visible evidence | see T4 |
| `vehicle-subclass-track-labels-v1` | one reviewer's committed decisions on one pack | see T5 |
| `vehicle-subclass-adjudication-v1` | resolution of overlap disagreements | see T5 |
| `vehicle-subclass-requirements-v1` | the pre-registered bar | see §13 |
| `vehicle-subclass-measurement-v1` | the result | see T2 |

The S3.1 Phase-1 ground-truth schema is not changed: Track-level labels are a different unit and get their own artefact, and the two never overlap.

**Label vocabulary (`mavi-vehicle-subclass-labels-v1`)**
- **Labels:** `car`, `truck`, `bus`, `motorcycle`, `unknown`.
- **`unknownReason`:** required with `unknown` and forbidden otherwise: `occluded`, `too-small`, `ambiguous-type`, `mixed-track`, `not-a-vehicle`, `other`. (Required so that every final `unknown`, carried or adjudicated, has a controlled reason, T5.)
- **`note`:** optional on any decision, at most 200 characters, single line.

These are review reasons, not `ObjectSubclass` values.

**Labelling guide (`mavi-vehicle-subclass-labeling-guide-v1`).** Labels are measurement truth only under a concrete, frozen annotation guide, because 80 % of pilot Tracks get only the primary reviewer's decision.
- **File:** `docs/qualification/stage3/s3-2-labeling-guide.md`, committed before any pack is built; its content is approved by the owner (§19) and is not decided by this plan.
- **Required content:** for each label, an operational definition, with an explicit rule for each boundary case: pickup, SUV, van, minivan, minibus or shuttle, box truck, tractor or trailer unit, emergency and service vehicles, scooter and moped, motorcycle with sidecar, bicycle, and partial or truncated vehicles; when to choose a class and when `unknown`/`ambiguous-type` (for example: a class only when the visible evidence fits its definition without relying on assumption); how to treat a Track that changes identity (`mixed-track`); and a few illustrative described examples (no CityFlow images committed).
- **Binding:** the pack builder (T4) takes `--labeling-guide <file> --labeling-guide-commit <sha>`, refuses unless the file is byte-identical at that commit (`labeling_guide_not_committed`), records `labelingGuide{sha256, gitCommit, gitPath}` in the manifest, and copies the guide into the pack (canonical UTF-8/LF, listed in `files[]`) where the page links to it. Labels bind the pack, so every decision is attributable to one guide version. All packs of one batch, and of batches pooled together, must bind the same guide (`labeling_guide_mismatch` in T2).

## 6. Ordered implementation tasks

### T1 — Read-only measurement export (S3.2a-1; fixtures only)

**Files**
- **New:** `src/platform/Mavi.Application/Modules/Processing/ProcessingRunAttestationFactory.cs`, `static ProcessingRunAttestationResponse Build(ProcessingRunAttestationSource, ParsedVisionRuntimeProvenance)`. The construction moves here, unchanged, from `ProcessingEndpoints.AttestationAsync`, which then calls it.
- **New:** `src/platform/Mavi.Infrastructure/Measurement/SubclassMeasurementExporter.cs`, `Task<SubclassMeasurementExport> ExportAsync(Guid runId, string pipelineProfilePath, CancellationToken)`.
- **New:** `tools/dotnet/Mavi.MeasurementExport/` (console csproj referencing Infrastructure; added to `MAVI.sln`, so CI builds it). CLI: `Mavi.MeasurementExport --run <guid> --pipeline-profile <file> --out <new-dir>`, reading the existing machine configuration for the connection string. The profile file is always supplied explicitly; the exporter never infers a path from a hash.
- **New:** `contracts/schemas/vehicle-subclass-measurement-export-v1.schema.json` plus an example.

**Contract**

| Member | Content |
|---|---|
| `schemaVersion` | |
| `processingRun` | `processingRunId`, `videoAssetId`, `status: "Completed"`, `completedAtUtc` (a stored fact, not wall-clock), `attestation` (the factory's response object) |
| `video` | `videoAssetId`, `cameraCode`, `sourceSha256`, `sourceSizeBytes`, `durationMs`, `width`, `height`, `frameRateNumerator`, `frameRateDenominator` |
| `profile` | `pipelineProfileSha256` (the attested value, which the supplied file must match), `evidenceSelectorVersion`, `evidenceScorerVersion` (parsed from the verified file) |
| `tracks[]`, by `localTrackNumber` | `id`, `localTrackNumber`, `objectClass`, `startOffsetMs`, `endOffsetMs`, `detectionCount`, `meanConfidence`, `maxConfidence`; Phase-1 `representative` `{videoOffsetMs, boundingBox}`; `objectSubclass`, `objectSubclassVocabulary`, `objectSubclassSource`; `observations[]` `{evidenceRole, evidenceRank, sourceFrameNumber, videoOffsetMs, boundingBox, qualityScore, evidenceSha256, evidenceSizeBytes, evidencePath}` (`qualityScore` is the stored `Observation.QualityScore`, the selector's quality signal; T3 stratifies on it); `trajectorySha256` |

- **Evidence bytes:** copied into `evidence/<sha256>.jpg`, each re-hashed.
- **Identity:** `exportSha256`, the SHA-256 of the export JSON.

**Pipeline-profile verification.** The exporter hashes the bytes of the `--pipeline-profile` file and requires that SHA-256 to equal the attested `pipelineProfileSha256` (`export_pipeline_profile_mismatch`). Only then does it parse the file and read the evidence selector and scorer versions and the vehicle-subclass block from it. A file that cannot be read or parsed, or lacks either version, is `export_pipeline_profile_invalid`; a verified profile with no vehicle-subclass block is `export_profile_not_stage3`.

**Snapshot invariant.** One `REPEATABLE READ` read-only transaction reads the run, its job, video asset, source artefact, Tracks, observations and evidence artefacts. Then:
- **Run and job:** the run is `Completed` with `CompletedAtUtc`, and its VisionJob is `Completed`, so finalisation is done. Otherwise `export_run_not_terminal`.
- **Attestation:** built from that same snapshot; a parse failure is `export_attestation_integrity`.
- **Linkage:**
  - every Track's run and video must be the run's (`export_track_run_mismatch`);
  - every observation's Track must be in the set (`export_observation_orphan`);
  - the run's video asset must be the one exported (`export_video_mismatch`).
- **Subclass state:** must be one of the four domain states, and a Stage-3 profile run must have vocabulary and source on every Vehicle Track (`export_subclass_state_invalid`). A run whose verified profile has no vehicle-subclass block is refused (`export_profile_not_stage3`).
- **Bytes:**
  - each evidence file is re-hashed against its artefact row (`export_evidence_changed`);
  - the source video file is re-hashed against its source artefact (`export_source_changed`);
  - any missing artefact is `export_provenance_incomplete`.
- **On refusal:** exit 2, and the output directory is removed.

**Tests**
- **`ProcessingRunAttestationFactoryTests`:** equals the endpoint JSON, and the existing `ProcessingRunAttestationApiTests` stay unchanged.
- **`SubclassMeasurementExportTests` (integration):**
  - a seeded 3.3 run with all four subclass states and a Person Track;
  - byte-identical repeat;
  - each refusal (*discriminating*: a run still `Finalizing`, a tampered evidence file, a Track re-pointed to another run by SQL, a malformed subclass row inserted after the test drops the subclass check constraints in the test database, a **wrong profile** (a valid profile file whose hash differs from the attested one, refused as `export_pipeline_profile_mismatch` with no output), and a malformed profile whose bytes are made to be the attested ones in a seeded run, refused as `export_pipeline_profile_invalid`);
  - only the requested run is exported.

**Windows/offline:** runs on the Development host, writes to E:, no network.

**Qualification:** none. No worker, profile or binding change, and no API surface change.

**Exit:** CI green, and the schema and example validated.

### T2 — Track-label evaluator mode and result (S3.2a-2; fixtures only)

**Files**
- **Changed:** `tools/phase1/evaluate_vehicle_subclass.py`, adding `evaluate_track_labels(batches, exports, measured_profile_sha256) -> dict` and a CLI mode `--sample <file>… --track-labels <file>… [--overlap-labels <file>… --adjudication <file>…] --export <file>… --pipeline-profile <file>`.
- **Batches.** A batch is one sample with its frozen primary labels and, optionally, its frozen overlap labels and adjudication. The pilot is one batch; an expansion adds a batch whose sample declares its design, `continuation` or `supplemental` (T3, §14). Files are paired by hash: labels to a sample by `sampleSha256`, an adjudication to its labels by `primaryLabelsSha256` and `overlapLabelsSha256`. A file that pairs with nothing, or with two things, is refused (`batch_pairing_invalid`).
- **Thresholds.** The evaluator takes no requirements and applies no threshold. Support status against the pre-registered minimum is computed only by T6.
- **Refactor:** `_producer`, the per-Track source check and the confusion/metric arithmetic become shared internal functions. The event mode's behaviour and tests are unchanged.

**Join and validation**
- **Truth by identity:** truth joins by `(processingRunId, trackId)` straight from the labels.
- **Exports:** every export is re-hashed against `labels.exportSha256s`, and its embedded attestation feeds the S3.1 producer check, which requires one producer identity across runs.
- **Profile:** the attested profile must equal the measured profile file's SHA-256.
- **Overlap and adjudication:** both frozen label files are supplied and re-hashed. The adjudication's `primaryLabelsSha256` and `overlapLabelsSha256` must equal those hashes, and each adjudicated item's `primary` and `overlap` values (label and `unknownReason`) must equal the decisions in those files for that Track (`adjudication_not_from_labels`). Reliability is computed from the two label files themselves, never from the adjudication's copies.
- **Truth set (final truth):** per batch, the primary decision (label and `unknownReason`) for Tracks outside the overlap, and for overlap Tracks the adjudication's `adjudicatedLabel` and `adjudicatedUnknownReason`, whether carried or adjudicated. `humanUnknown{reason:count}`, evaluable support and every metric are computed from this final truth, never from whichever reviewer happened to be primary. Both originals stay referenced.
- **Combining batches:** batches must be Track-disjoint (`batch_tracks_overlap`), and every batch's sample must bind the same requirements hash (T3).
  - **Primary aggregate:** the pilot plus any `continuation` batches only. A continuation is pooled only if its sample names the pilot sample as parent and has the same release, sampling algorithm version, sampling parameters, requirements hash and exact set of `exportSha256s` as the pilot, and its exports attest the same producer and profile (`continuation_design_mismatch` otherwise).
  - **Supplemental batches** are always reported separately, each in its own `supplemental[]` entry with its full metric set. They never change the primary aggregate's precision, recall, accuracy, coverage or any other prevalence-sensitive figure. S3.2 has no weighted pooling; if it is wanted later, it needs a separate explicit design and plan amendment.
  - Every batch is also reported on its own; the pilot's own result is reproduced unchanged inside any later result.

**Refusals**
- an export hash mismatch;
- a run or Track not in the exports (`labels_track_not_exported`);
- a label on a non-Vehicle Track;
- a `videoSourceSha256` differing from the export's;
- a duplicate decision;
- an adjudication referring to items outside the overlap, or to label sets other than the two given, or whose carried values differ from those label files;
- packs of one batch, or of pooled batches, bound to different labelling guides (`labeling_guide_mismatch`; frozen labels record the pack's `labelingGuide`);
- overlap labels whose recorded `viewKind` is not `overlap` or whose `parentPackSha256` is not the primary labels' `packSha256`, or primary labels whose `viewKind` is not `primary` (`overlap_pack_not_derived`);
- labels whose `sampleSha256` is not a supplied sample, or a sample whose requirements binding differs from another batch's;
- every S3.1 producer and source refusal (mixed producers, profile mismatch, missing or foreign source, missing attestation).

**Result (`vehicle-subclass-measurement-v1`)**

| Member | Content |
|---|---|
| `scope` | the Track-conditional statement (top of this plan), verbatim |
| `producer` | model, checkpoint, config, pipeline profile, runtime profile and variant, qualification, binding, MAVI commit, run ids |
| `inputs` | per batch: `sampleSha256`, primary and overlap `packSha256`, primary and overlap label-set hashes, `adjudicationSha256`; the bound `requirementsSha256`; export hashes, measured profile hash, source-video hashes |
| Support | `labelledTracks`, `humanUnknown{reason:count}`, `evaluableTracks` |
| MAVI outcomes | `resolved` and `abstained` over evaluable Tracks; `coverageOverEvaluable` |
| `confusion` | rows = 4 human classes; columns = 4 values + `undetermined` |
| `unknownRow` | MAVI outcomes on human-unknown Tracks, reported and never scored |
| `perClass` | `support`, `predicted`, `correct`, `precision`, `recall` (exact fractions; **`null` when undefined**). No support status here: that is T6's, against the requirements |
| Aggregates | `accuracyOverEvaluable`, `accuracyOverResolved`, `macroRecallOverClassesWithSupport` (classes with support > 0, named), as descriptive point estimates with `n` stated. **No confidence intervals** (see below) |
| `clusters` | `videoCount`, `cameraCount`, and per video and per camera: support, resolved, correct and the confusion, so the reader sees how concentrated the outcomes are |
| `errorReferences` | every mismatch and abstention as `{itemId, processingRunId, trackId, label, predicted}` |
| `reliability` | overlap agreement counts and the class-level disagreement matrix |
| `batches[]`, `supplemental[]` | per-batch results (design, sample hash, full metrics); supplemental measurements kept apart from the primary aggregate |

**Why no intervals.** Tracks are sampled from 6–10 videos on shared cameras, so outcomes are correlated within a scene, and CityFlow cameras can see the same vehicle. A binomial interval with the Track count as `n` would treat them as independent and understate uncertainty, and a clustered interval over so few clusters is itself unreliable. S3.2 therefore reports descriptive point estimates with the per-video and per-camera breakdown only. No clustered estimator is specified in this plan; an interval-based operational criterion would need an explicit later plan amendment, with its estimator, minimum number of clusters and tests, before any sampling.

**Tests**
- hand-computed fixtures;
- every refusal;
- a wrong-profile export;
- input order does not change the bytes;
- `null` for undefined precision (no predictions of a class);
- *mutation-style*: counting human `unknown` as evaluable, counting abstention as correct, or using the primary label where the adjudication differs each changes a pinned result;
- an adjudication whose carried `overlap` value was edited is refused, and reliability changes when the overlap file changes;
- a pilot and a continuation batch combine to the union, and Track-overlapping batches are refused;
- a continuation with a different sampling algorithm version, release or requirements is refused for pooling;
- a supplemental batch leaves the primary aggregate byte-identical to the pilot-only aggregate and appears only under `supplemental[]`;
- a continuation whose `exportSha256s` differ from the pilot's is refused for pooling;
- *discriminating*: an overlap Track labelled `car` by the primary and `unknown`/`too-small` by the overlap reviewer, adjudicated to `unknown`/`too-small`, is non-evaluable and counted in `humanUnknown{too-small}`; a mutant using the primary label scores it as `car` and fails;
- the per-video and per-camera breakdowns sum to the totals;
- the event-mode tests are untouched.

**Exit:** CI green.

### T3 — Prediction-blind sampler (S3.2a-2; fixtures only)

**File:** `tools/stage3/sample_tracks.py`. CLI: `--export <file>… --derivation <file>… --requirements <file> --requirements-commit <sha> --target N --overlap-fraction 0.2 --seed <text> --design continuation|supplemental [--reason <text>] [--exclude-sample <file>…] --out <file>`.

**Requirements binding (the pre-registration lock, §13).** The sampler refuses unless the requirements file is schema-valid and byte-identical to `git show <commit>:docs/qualification/stage3/s3-2-subclass-requirements.json`, with `<commit>` an ancestor of `HEAD`. The sample records `requirements {sha256, gitCommit, gitPath}`. Because labels bind the pack, the pack binds the sample, and the result names the sample, every result is chained to the requirements fixed before any Track was labelled.

**Exclusions (expansion).** Each `--exclude-sample` is a previous sample artefact, schema-checked and recorded by hash in `excludedSampleSha256s`. Its `selected[]` Tracks are removed from the pool before binning and counted under `excluded{previously-sampled}`.

**Design.** `--design` is required and is recorded with `samplingAlgorithm: "s3-2-video-quota-diversity-v1"`, the sampling parameters, the release id and `parentSampleSha256s` (the `--exclude-sample` hashes):
- **pilot:** `continuation` with no `--exclude-sample`, so no parent;
- **later continuation:** `continuation` with one or more parent samples; its set of exports must equal the pilot's `exportSha256s` set exactly (no added and no omitted video), so it draws only from the already processed pilot source pool (`continuation_pool_mismatch`);
- **supplemental:** `--reason` is required, non-empty, single line, at most 200 characters;
- `--reason` with `continuation` is refused, and `supplemental` without a reason is refused (`design_invalid`).

**Blindness, enforced in code.** One function, `_blind(track)`, returns the Track without `objectSubclass*`, `meanConfidence` and `maxConfidence`, and the sampler reads only its output.

**Usable Track.** A Vehicle Track with at least one evidence observation whose bytes verify.
- Detection count is **not** filtered, because it drives the vote's abstention.
- Exclusions are counted by reason.

**Algorithm `s3-2-video-quota-diversity-v1`** (all on `_blind` output; `h(x)` is SHA-256 of the UTF-8 bytes, compared as hex).

1. **Diversity bins.** Five prediction-independent dimensions, each binned into terciles 0/1/2 over the whole usable pool:
   - scale: the Representative box area as a fraction of the frame;
   - duration: `endOffsetMs − startOffsetMs`;
   - density: the number of other Vehicle Tracks in the same run whose time span overlaps this Track's;
   - luma: mean luma of the Representative crop;
   - quality: the Representative's `qualityScore` (a selector quality signal, not a subclass prediction).

   Where the Representative's bytes do not verify, the lowest-ranked verified observation stands in. Tercile cuts: sort the pool by `(value, h(seed‖runId‖trackId))`; positions below ⌊n/3⌋ are bin 0, below ⌊2n/3⌋ bin 1, the rest bin 2. No cross-product of dimensions is ever formed.
2. **Primary allocation, by video (run).** With `V` videos, `a_v` usable Tracks in video `v` and target `T`:
   - floor `f_v = min(a_v, ⌊T / (2V)⌋)`, the minimum-coverage intent (every camera has at least one video, so every camera is covered);
   - the remainder `T − Σf_v` is shared in proportion to `a_v − f_v` by largest remainder, ties broken by smallest `h(seed‖"alloc"‖runId)`;
   - a quota above `a_v` is capped and the excess re-shared the same way among videos with spare Tracks, until the quotas sum to `T`.
3. **Within each video's quota `q_v`: greedy marginal balancing.** Keep counts `c[d][b]` of Tracks already selected **in this video** per dimension `d` and bin `b`. Repeat `q_v` times: choose the unselected candidate with the smallest score `Σ_d c[d][bin_d]`, breaking ties by smallest `h(seed‖runId‖trackId)`; then update the counts. This favours bins under-represented so far in every dimension at once.
4. **Overlap for the second reviewer.** `k = ⌈overlapFraction × T⌉`, allocated over videos by step 2's rule applied to the selected counts (floor 1 per video while `k ≥ V`); within a video, the selected Tracks with the smallest `h(seed‖"overlap"‖runId‖trackId)`. It is chosen in the same run from blinded data, so it depends neither on predictions nor on any label.

The sample records, per selected Track, its video and its five bins, and per video `a_v`, `f_v` and `q_v`, so the allocation can be re-checked from the artefact.

**Refusals:** a bad export hash or schema; a target larger than the usable pool; a duplicate Track; requirements missing, schema-invalid, uncommitted or differing from the named commit (`requirements_not_committed`); an invalid exclusion sample; an export not matching exactly one derivation, or derivations from more than one release (`export_not_derived`); an invalid design (`design_invalid`: missing `--design`, `--reason` given with `continuation`, or `supplemental` with a missing, empty, multi-line or over-long reason); a continuation whose export set differs from the pilot's (`continuation_pool_mismatch`).

**Tests**
- determinism;
- an edited, uncommitted requirements file is refused (fixture git repository under the pytest temp dir);
- excluded Tracks never reappear, and the exclusion count adds up;
- *discriminating*: the selection and the overlap are identical when subclass and confidence values are permuted, deleted or replaced; a mutant reading `objectSubclass` fails;
- **allocation, executable:** on a fixture with hand-computed quotas, `q_v` equals the expected values exactly, including a largest-remainder tie, a capped video whose excess is re-shared, and floors that hold; quotas always sum to `T`;
- **balancing, executable:** on a fixture where each video's hash order is deliberately skewed toward one bin in every dimension, the selection equals a pinned golden, and its per-dimension bin imbalance (Σ over dimensions and bins of `(count − q_v/3)²`) is strictly below that of the hash-order-only selection of the same quotas; a mutant that ignores the bins fails;
- tercile cuts on a fixture with tied values match hand-computed bins;
- design: the pilot (`continuation`, no parent) and a later continuation with parents succeed; `continuation --reason …`, `supplemental` without or with an empty, multi-line or 201-character reason, and a continuation with an added or an omitted export are each refused with their code; the recorded `design` matches the CLI;
- an export with no matching derivation, or derivations naming two releases, is refused; the sample records the derivation hashes and release record hash;
- excluded counts add up;
- overlap ⊂ selected, with its per-video allocation as hand-computed.

**Exit:** CI green.

### T4 — Labelling pack and static labelling page (S3.2a-2; fixtures only)

**Files**
- **New:** `tools/stage3/build_labeling_pack.py`.
- **New:** `tools/stage3/labeling/index.html`, `labeling.js`, `labeling.css` (static, copied into each pack). `.gitattributes` gains `tools/stage3/labeling/* text eol=lf`; existing line-ending rules are unchanged.
- CLI: `--sample <file> --export <file>… --source <mp4>… --pipeline-profile <file> --labeling-guide <file> --labeling-guide-commit <sha> --seed <text> --reviewer-view primary|overlap [--parent-pack <primary-pack-dir>] --out <new-dir>`.
- **Overlap packs.** `--parent-pack` is required with `--reviewer-view overlap` and refused with `primary`. The builder verifies the parent: its manifest's canonical hash, its regenerated `pack-data.js`, `viewKind: primary`, and the same `sampleSha256`, `exportSha256s` and `labelingGuide` as this build (`parent_pack_invalid`). It then records the parent's hash as `parentPackSha256`. The overlap pack contains exactly the sample's `overlapSelected[]` Tracks.

**Per item**
- **Crops:** the Track's evidence crops, up to 4 and temporally separated by construction.
- **Context frames:** one per observation. The full frame is decoded with PyAV at `sourceFrameNumber`, downscaled to at most 1280 px long edge, and the box drawn.
- **No clips by default.** A `--clip` flag is a **documented fallback, not built** unless the pilot shows still evidence is insufficient.

**Blind by construction**
- No predicted subclass, confidence or MAVI ids appear in reviewer-visible files.
- `itemId` = first 16 hex characters of `sha256(packSeed‖runId‖trackId)`.
- Items are ordered by `itemId`.
- The overlap pack uses a different `packSeed`, so its order and ids differ from the primary's.

**Manifest (`vehicle-subclass-labeling-pack-v1`)**

| Member | Content |
|---|---|
| Inputs | `sampleSha256`, `exportSha256s`, `pipelineProfileSha256`, `evidenceSelectorVersion`, `evidenceScorerVersion`, `labelingGuide{sha256, gitCommit, gitPath}` |
| Extraction | decoder identity (`av` and `ffmpeg` versions), `renderRuleVersion: "context-v1"` |
| `items[]` | `{itemId, processingRunId, trackId, videoSourceSha256, views[{kind: crop\|context, evidenceRole, sourceFrameNumber, videoOffsetMs, path, sha256, sizeBytes}]}` |
| `files[]` | path, size and SHA-256 of every file in the pack **except** `pack-manifest.json` itself and `pack-data.js` (both derived, below) |
| `viewKind` | `primary` or `overlap`; `parentPackSha256` for an overlap pack |

**Identity:** `packSha256` is the SHA-256 of the canonical manifest bytes, computed outside the manifest and never stored in it.

**Derived `pack-data.js`.** Written after the manifest, as a deterministic function of the manifest bytes: `window.MAVI_PACK = {packSha256, items:[{itemId, views:[{path, label}]}]}`. It loads from `file://` with no server, so the page has the hash without fetching anything. It is outside `files[]` to avoid a circular hash; instead T5 and T6 regenerate it from the manifest and refuse if the on-disk bytes differ (`pack_data_mismatch`).

**Canonical bytes for text assets.** Every text file the builder writes, copied or generated (`index.html`, `labeling.js`, `labeling.css`, `pack-data.js`, the manifest), is written as UTF-8 without BOM with LF line endings: the builder decodes the template, normalises CRLF and CR to LF, and writes those bytes. Hashes are computed from the written canonical bytes, so a CRLF checkout cannot change any file hash or `packSha256`. A template that is not valid UTF-8 is refused (`pack_asset_not_utf8`).

**Reviewer-visible files:** `index.html`, `labeling.js`, `labeling.css`, `pack-data.js` and the images. The run→Track mapping lives only in `pack-manifest.json`, which also carries no predictions.

**Page behaviour**
- one item at a time, with previous and next;
- keys `1` car, `2` truck, `3` bus, `4` motorcycle, `0` unknown, then a reason picker;
- an optional note;
- autosave to `localStorage`, keyed by `packSha256` (resume convenience only);
- "Export decisions" downloads `{packSha256, reviewerName, decisions[{itemId, label, unknownReason?, note?}]}`;
- no network calls and no external URLs.

**Refusals (builder):** a source MP4 hash ≠ `videoSourceSha256`; a profile hash mismatch; a frame outside the video; an evidence hash mismatch; a labelling guide not committed unchanged; a missing, unexpected or invalid parent pack; an existing output.

**Tests**
- deterministic pack bytes;
- the manifest lists every pack file exactly once, except itself and `pack-data.js`;
- `pack-data.js` regenerates byte-identically from the manifest and carries its `packSha256`; an edited `pack-data.js` is refused;
- **leak test:** reviewer-visible files contain no `objectSubclass*` key, no subclass value adjacent to an item, no confidence and no Track or run ids;
- the drawn box matches the observation box (pixel check on a synthetic video);
- static page check: no `http(s)://`, no `fetch` or `XMLHttpRequest`;
- **Windows regression:** building from a copy of the templates converted to CRLF gives the same file hashes and the same `packSha256` as from the LF templates; every written text file contains no `\r`;
- primary and overlap packs share Tracks but no `itemId`;
- an overlap build without `--parent-pack`, or with a parent built from a different sample, export set or guide, or with an edited parent manifest, is refused; a valid build records the parent's hash, and frozen overlap labels then pass T2's lineage check;
- an uncommitted or edited labelling guide is refused, and the guide copy in the pack is listed in `files[]`.

**Windows/offline:** PyAV, Pillow and numpy are already in the venv. The page opens from disk in Edge or Chrome. No dependency change.

**Exit:** CI green.

### T5 — Freeze decisions; adjudicate the overlap (S3.2a-2; fixtures only)

**File:** `tools/stage3/freeze_labels.py`.
- `freeze --pack <dir> --decisions <draft> --reviewer-name <n> --reviewer-role <r> --reviewed-on <YYYY-MM-DD> --out <file>`
- `adjudicate-prepare --primary <labels> --overlap <labels> --pack <primary-pack-dir> --out <new-dir>`
- `adjudicate --primary <labels> --overlap <labels> --decisions <file> --adjudicator <n> --out <file>`, where `--decisions` holds `{itemId (the primary pack's), adjudicatedLabel, adjudicatedUnknownReason?}` for each item needing adjudication

**`vehicle-subclass-track-labels-v1`:** `{packSha256, viewKind, parentPackSha256?, labelingGuideSha256, sampleSha256, exportSha256s, reviewer{name, role}, reviewedOn, vocabulary, decisions[{itemId, processingRunId, trackId, videoSourceSha256, label, unknownReason?, note?}]}`, sorted by `(processingRunId, trackId)` and resolved through the pack manifest. `viewKind` and `parentPackSha256` (overlap only) are copied from the verified manifest, so T2 can check pack lineage without the packs.

**Freeze refusals**
- the draft's `packSha256` ≠ the pack's;
- an item missing or decided twice;
- an `itemId` not in the pack;
- a vocabulary violation;
- `unknownReason` without `unknown`, or `unknown` without `unknownReason`;
- a note too long or multi-line;
- an empty reviewer;
- an existing output.

**`vehicle-subclass-adjudication-v1`**
- Contents: `{primaryLabelsSha256, overlapLabelsSha256, adjudicator, adjudicatedOn, items[{processingRunId, trackId, primary{label, unknownReason?}, overlap{label, unknownReason?}, adjudicatedLabel, adjudicatedUnknownReason?, resolution: carried|adjudicated}]}`. Each reviewer's reason stays attributable to that reviewer.
- It refuses unless both label sets cover the same Tracks on the overlap, and both are complete.
- **Carried automatically** (`carried`) only when both reviewers chose the same non-`unknown` label, or both chose `unknown` with the same reason; the final label and reason are theirs.
- **Otherwise the adjudicator decides** (`adjudicated`): a different label, or `unknown` with different reasons, needs an explicit `adjudicatedLabel`, and an explicit `adjudicatedUnknownReason` when that label is `unknown`.
- **Final reason rules:** a non-`unknown` `adjudicatedLabel` carries no `adjudicatedUnknownReason`; an `unknown` one must carry a controlled reason (§5). Refusals: `adjudication_reason_missing`, `adjudication_reason_not_allowed`, `adjudication_reason_invalid`, and a decision for a carried item (`adjudication_decision_unexpected`).

**Prediction-blind adjudication**
- **When:** only after both label sets are frozen; `adjudicate-prepare` refuses unfrozen or non-schema label files.
- **What the adjudicator sees:** the reviewer evidence from the primary pack and the two human decisions for each disagreement, as an adjudication sheet (`adjudication-data.js` beside the pack page, items by primary `itemId`). Nothing else.
- **Predictions stay hidden:** `adjudicate-prepare` and `adjudicate` take no export, result or attestation input. Their only inputs are the frozen label files, the pack and the adjudicator's decisions, none of which carry predictions or confidences.
- **Diagnostic review comes last:** predictions are first shown by T6's `measurement-summary.md`, which T6 writes only when every batch with overlap labels has a frozen adjudication (`adjudication_missing`).

**Immutability.** Artefacts are content-addressed and written once.
- The artefacts used in a recorded measurement are named by hash in §20.
- Corrections produce **new** artefacts and a new measurement record; nothing is edited in place.

**Tests:** every refusal; determinism; frozen labels carry the manifest's `viewKind` and, for an overlap pack, its `parentPackSha256`; the adjudication carry-through (same label, and `unknown` with the same reason); `unknown` with different reasons requires an explicit final reason; `car` vs `unknown`/`too-small` adjudicated to `unknown` requires and records `adjudicatedUnknownReason`, and is refused without it; a reason on a non-`unknown` final label is refused; both originals are preserved in the result inputs; **adjudication blindness:** the two adjudication commands' argument parsers accept no export, result or attestation option, and the leak test of T4 run over the adjudication sheet and the adjudication artefact finds no `objectSubclass*` key, subclass prediction or confidence.

**Exit:** CI green.

### T6 — Measurement runner and requirement comparison (S3.2a-2; fixtures only)

**File:** `tools/stage3/run_subclass_measurement.py`. CLI: `--sample … --labels … [--overlap-labels … --adjudication …] --pack <dir>… --export … --pipeline-profile … --requirements <file> --out <new-dir>`, with the same repeatable batch inputs as T2.

**What it does**
- verifies every hash, including each pack's regenerated `pack-data.js`;
- verifies the requirements binding: the file's hash equals every sample's `requirements.sha256`, and it is byte-identical at the recorded `gitCommit` (`requirements_binding_mismatch`);
- runs T2;
- computes per-class support status against the requirements' minimum (`insufficient-support` below it);
- writes `measurement-result.json`;
- writes `requirement-comparison.json`: per criterion, `meets`, `does-not-meet`, `insufficient-support` or `no-requirement`;
- writes `measurement-summary.md`, which is generated tables plus error references pointing into the pack.

**It encodes no mechanism decision.** The comparison only reports criterion status.

**Refusals**
- the requirements file is missing or fails its schema;
- overlap labels without a frozen adjudication (`adjudication_missing`);
- any input hash mismatch;
- an existing output.

**Tests**
- an end-to-end synthetic pipeline: fixture export → sample → packs → scripted primary and overlap drafts → freeze → adjudicate → measure → compare. The output is byte-stable.
- comparison states for a criterion at, below and above its bound, and with null support;
- support status flips exactly at the pre-registered minimum;
- a requirements file differing from the one the samples bound is refused, even if committed.

**Exit:** CI green.

### T7 — Corpus verification and release record (S3.2b; ⚠ real release, ⚠ R-5)

See §8. **Exit:** the release record parses, `verify_release_files` passes, and for every selected source member `authorise_release_use(release, ["benchmarking", "development"], member=<member>)` returns no blockers. The rights inventory's `create-derivatives` status is recorded as R-5 determined it; this plan makes no assumption about it.

### T8 — MP4 derivation (S3.2b; ⚠ real release)

See §8. **File:** `tools/stage3/derive_mp4.py`. **Exit:** every pilot video, including any already importable, has a derivation manifest whose output re-derives byte-identically, and whose recorded authorisation for its mode returned no blockers (passthrough: `evaluate`; remux or transcode: `evaluate` and `create-derivatives`).

### T9 — Import, process, export (S3.2b; ⚠ Development host)

**Steps**
- Import each T8 output MP4 (passthrough, remux or transcode) through the public API, with one MAVI camera per corpus camera.
- Process on the shipped `1.3.0-candidate` with the real Model Pack.
- Export each run with T1.

**Video choice.** A bounded set of 6–10 videos chosen for camera and scene diversity, before the pilot. The choice is not based on any output. These processed videos are the only pool a later continuation may draw from; any video selected after the pilot is processed the same way but can only feed a `supplemental` batch (§14).

**Exit:** one export per video, all attesting one producer identity and the measured profile.

### T10 — Pilot (S3.2c; ⚠ human)

Run in order:
1. Commit the requirements (§13) and the approved labelling guide (§5).
2. Sample 120 Tracks with a 20 % overlap (T3), binding the committed requirements.
3. Build the primary and overlap packs (T4).
4. The primary reviewer labels; the overlap reviewer labels independently.
5. Freeze both, then adjudicate.
6. Measure and compare (T6).
7. Commit the evidence record (§20).

### T11 — Expansion (S3.2d; conditional; ⚠ human)

See §14. The expansion is declared `continuation` or `supplemental` before its sample is drawn, and the pilot's measurement record is never edited.

## 7. Testing strategy

- **.NET:** unit tests (attestation factory) and integration tests (export, against the CI PostgreSQL). Locally, the dev PostgreSQL may be used.
- **Python:** `tools/phase1/tests/` for the evaluator; new `tools/stage3/tests/` for the sampler, pack, freeze and runner, plus the end-to-end synthetic pipeline test. Pytest temp output goes to E: locally.
- **Discriminating tests, named above:**
  - sampler blindness;
  - pack leak;
  - snapshot invariants;
  - evaluator mutation pins (unknown, abstention, adjudication);
  - byte determinism for every artefact.
- **`verify_repo`:** validates the new schemas against their examples and registers `tools/stage3/` if its inventory checks require it.
- **CI:** existing workflows run the new tests. No new workflow is needed. `Mavi.MeasurementExport` is built by the solution build.

## 8. Corpus intake (CityFlow as the primary candidate)

**Nothing is assumed from CityFlow's reputation.** T7 verifies, and records as evidence files hashed into the release record:

| Item | Verification |
|---|---|
| Release/version | the exact edition and track obtained (for example the AI City Challenge CityFlowV2 / MTMC set), with its readme and version text saved |
| Source/access | the official access page and request process as presented. **The owner submits any request and accepts any agreement.** |
| Licence/terms | the agreement or licence text saved and hashed; scope recorded verbatim (purpose limits, redistribution, publication of derived metrics, retention) |
| Sizes and SHA-256 | every delivered archive and file, before extraction, then each extracted video |
| Camera/video metadata | `tools/stage3/probe_media.py` (offline-kit ffprobe): container, codec, profile, resolution, frame rate, duration, frame count, per video, as canonical JSON |
| Native tracks/boxes | file inventory and format (expected MOT-style per-frame boxes and ids), and coverage. CityFlow annotations are believed to cover only vehicles seen by several cameras; to be verified. **Not used as ground truth.** |
| Native type labels | whether any exist. CityFlow core is not known to carry vehicle type; any found are recorded as **untrusted for this purpose** (taxonomy and definitions differ) and never used as ground truth |
| Exposure | whether RTMDet's COCO training or any MAVI component used CityFlow (model card or paper, recorded); public benchmark status; recorded as `knownExposure` |
| Restrictions | anything limiting development or evaluation use, derived artefacts or metrics |

**Derivation (T8).** Every measured video goes through T8, so T9 always imports a T8 output and the chain has no gaps.
- **Passthrough** when the release file is already ISO-MP4 and accepted by `PhaseOneMp4ContainerPolicy` (checked by probe): the output is a byte copy, and `outputSha256` must equal `sourceSha256`.
- **Remux** (`-c copy` into MP4) when the stream codec is decodable by the worker and MP4-compatible.
- **Otherwise transcode** with a pinned recipe: offline-kit ffmpeg, `-c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -threads 1 -an -movflags +faststart`.
- **Inputs:** `--release <release-record> --member <path> --mode passthrough|remux|transcode --out <new-dir>`. The release record is parsed and its files verified (`verify_release_files`); the member must be listed in it, and its bytes must match the recorded hash.
- **Manifest** `vehicle-subclass-derivation-v1` per video: `{release{releaseId, releaseRecordSha256, member}, authorisation{purposes: ["benchmarking", "development"], operations, blockers: []}, sourceSha256, sourceMedia(probe), mode: passthrough|remux|transcode, ffmpegVersion, ffmpegSha256, args, outputSha256, outputMedia(probe)}`; `args` is empty and the ffmpeg members are `null` for passthrough. `releaseRecordSha256` covers the R-5 determination in force, so the manifest names which determination authorised these bytes; `operations` is `[]` for passthrough and `["create-derivatives"]` for remux or transcode, exactly as passed to `authorise_release_use`, and the manifest is written only when `blockers` is empty.
- **Downstream identity:** T3 takes `--derivation <file>…`. Each export's `video.sourceSha256` must equal exactly one derivation's `outputSha256` (`export_not_derived`), and all derivations must name one release. The sample records `derivationSha256s[]`, `releaseId` and `releaseRecordSha256` from them, so the chain release record → member → derivation → export → sample can be re-verified from hashes. A continuation must name the same release record as the pilot.
- **Determinism:** the first remux or transcode derivation is run twice and must be byte-identical.
- **Honesty:** a transcoded file is never described as identical to its source. **The derived MP4 is the measurement input.** Its hash is the export's `video.sourceSha256`, and the chain runs release → derivation → import → export.
- **Refusals:** a source not in the release record or not matching its recorded hash; release files that fail verification; authorisation blockers for the member and mode (`derivation_not_authorised`); an unknown codec; non-determinism; a passthrough whose output hash differs from its source; an existing output.

**If CityFlow is unsuitable** (no access, restrictive terms, unusable media, or too sparse for important classes after the pilot), the plan records why. One supplement is then proposed for owner approval; none is added automatically. Candidates:
- BDD100K: a moving dashcam, so a weak proxy for fixed CCTV;
- UA-DETRAC: fixed traffic cameras; availability and terms unverified.

## 9. Sampling

As T3. Before labels exist, allocation and balancing use only prediction-independent metadata. No class balance is claimed, because no trusted independent type label exists.

After the pilot, the **human** class support is inspected. Rare-class supplementation (§14) is decided only then, and only by sampling more footage, never by selecting on MAVI predictions. Because it is chosen after seeing labels, it is a `supplemental` batch, reported apart from the pilot's aggregate.

## 10. Labelling workflow

**Roles**
- **Primary reviewer:** R-4 (Aarav).
- **Overlap reviewer:** an independent annotator (Savita), to be confirmed.

**Independence**
- Each works from their own pack.
- The overlap pack hides the primary's decisions and all predictions.
- Adjudication happens only after both have frozen. The adjudicator sees the reviewer evidence and the two human decisions, never MAVI's predicted subclass or confidence; those stay hidden until the adjudication is frozen (T5).

**What the unknown reasons diagnose:**
- `occluded` and `too-small`: imagery;
- `mixed-track`: tracking (an identity switch);
- `not-a-vehicle`: invalid detections;
- `ambiguous-type`: taxonomy (for example pickup vs truck);
- `other` with a note: anything else.

The result tallies them separately (`humanUnknown`), from the final truth after adjudication. MAVI's outcomes on unknown Tracks are reported in `unknownRow`, so tracking or detection failures are visible without being scored as subclass errors.

## 11. Ground-truth freeze

As T5. Labels bind to the exact pack the reviewer used (`packSha256`, which covers every viewed image's hash), the sample, the exports, the reviewer and the declared review date. Artefacts used in a recorded measurement are immutable; corrections create new artefacts.

## 12. Evaluation

As T2 and T6. Reported metrics are exact fractions with explicit denominators; undefined metrics are `null`. They are descriptive: no confidence intervals in the pilot, because Track outcomes are clustered by video and camera (T2, "Why no intervals"). The per-video and per-camera breakdown is reported instead. No per-class conclusions are drawn beyond T6's support status.

**Error review** (diagnostic, only after all labels and adjudications are frozen): `errorReferences` index into the pack, so a reviewer can look at mismatches with predictions shown.

## 13. Pre-registered decision requirements

**Artefact.** `vehicle-subclass-requirements-v1` is committed to the repository (`docs/qualification/stage3/s3-2-subclass-requirements.json`) **before** the pilot result exists, and its hash is recorded in §20. It contains three distinct parts:

1. **Operational requirement:** per-class minimum precision and recall, and minimum coverage, if the owner can justify them. Each value may be `null` ("no defensible requirement yet").
2. **Minimum evidence support:** the evaluable support per class below which no per-class conclusion is drawn. Suggested at 30, as a proposal for the owner to decide.
3. **Insufficient-support outcome:** a class below the minimum gets `insufficient-support`, and no pass or fail is permitted for it.

Criteria are on descriptive point estimates only. An interval-based criterion is out of scope for S3.2 and would need an explicit later plan amendment, with its estimator, minimum clusters and tests, before sampling (T2, "Why no intervals").

**Ordering is enforced by binding, not by dates:**
- the sampler (T3) refuses unless the requirements file is committed unchanged at a named commit, and it records the file's hash, commit and path in the sample;
- packs bind the sample, labels bind the pack, and the result names the samples, so the requirements are fixed before any Track is labelled;
- the runner (T6) refuses unless the requirements it compares against are byte-identical to the ones every sample bound;
- changing the requirements after seeing a result therefore requires a fresh sample, fresh packs and fresh labels, all with new hashes visible in §20.

The tooling cannot prove when a person first looked at numbers; it proves that the comparison uses the requirements fixed before labelling began.

**If every operational value is `null`,** S3.2 still yields a valid measurement, and the mechanism decision stays open pending requirement definition.

**Thresholds are never chosen after viewing results.**

**No tuning in S3.2.**
- `minShare`, `minMatchedDetections`, class weighting and abstention policy are measured as implemented and never adjusted against pilot data.
- If tuning is warranted, it is a separate development step with its own data boundary; the pilot Tracks are then excluded from its evaluation.

## 14. Pilot and expansion logic

**Pilot:** 120 Tracks (100–150), with a 20 % overlap.

**Expand toward 300–500 Tracks only if at least one holds:**
- support is too small for the requirements;
- an important class is below the minimum support;
- the estimates are unstable;
- reviewer disagreement is excessive;
- more source diversity is needed;
- error analysis shows the pilot is unrepresentative.

**How expansion works.** It reuses T3–T6 with a new seed, gives T3 the earlier sample(s) as `--exclude-sample` so no Track is resampled, and binds the same requirements. Its design is declared before sampling:

- **A. Same-design continuation** (`--design continuation`): the same source pool, meaning exactly the pilot's processed videos (the pilot sample's `exportSha256s`; no video is added after the pilot), the same `s3-2-video-quota-diversity-v1` algorithm and parameters, earlier Tracks excluded, and the same producer, profile and requirements. It may be pooled with the pilot into the primary aggregate, with every batch still reported on its own.
- **B. Targeted supplementation** (`--design supplemental --reason …`): rare-class targeting after inspecting pilot labels, any video selected after the pilot (including more videos from the same release), a new dataset, source or domain, or a deliberately altered allocation. It is always reported as a separate supplemental or challenge measurement and never changes the primary aggregate's precision, recall, accuracy, coverage or other prevalence-sensitive figures. S3.2 has no weighted pooling; that would need a separate explicit design and amendment.

Either way it produces new artefacts and a new measurement record. **The pilot measurement is immutable**: the pilot record is not edited, and later results reproduce the pilot's own result unchanged.

The expansion decision, or the decision not to expand, is recorded in §20. S3.2 may finish after the pilot.

**Decision directions** the evidence informs; none is encoded in tooling:
- detector-native looks adequate for continued Stage-3 work;
- the evidence is insufficient and more data is needed;
- detector-native has specific deficiencies needing development;
- a learned classifier should be evaluated in a later slice.

## 15. Provenance and rights

**One governance path.** The release record, licence evidence, file hashes, purpose authorisation and exposure all use the existing release machinery (`mavi-attribute-dataset-release-v1`, `authorise_release_use`). No parallel mechanism.

**Requested use.** Purposes `["benchmarking", "development"]`, the repository's established purpose tokens; both exercise `evaluate` only. Authorisation is member-scoped, one call per selected source member:
- **measurement and passthrough derivation:** `authorise_release_use(release, ["benchmarking", "development"], member=<member>)`;
- **remux or transcode derivation** (a new media artefact): `authorise_release_use(release, ["benchmarking", "development"], operations=["create-derivatives"], member=<member>)`.

If `create-derivatives` is not `granted` in R-5's rights inventory, T8 refuses remux and transcode for that member (`derivation_not_authorised`, with the blockers), and only passthrough-eligible videos can be used. This plan does not infer or make the legal decision; R-5 supplies the determination.

**Blocked until R-5 decides.** With `determination: null`, `authorise_release_use` returns blockers, and T8 refuses to run without the passing authorisation for its mode; the call and its empty result are recorded in the derivation manifest.

**Never frozen qualification.** Public origin never confers frozen-qualification eligibility (`provenance.parse_purposes` refuses `frozen-qualification` for public origin). S3.2 artefacts record the authorised purposes `["benchmarking", "development"]`; no new purpose token is introduced. The result `scope` states that it is development/evaluation evidence and not frozen qualification.

**Media stays out of Git.** No CityFlow media, frames or crops are committed. Only hashes and metadata go in §20.

## 16. Qualification impact

**None.** No worker, pipeline profile, binding, Model Pack, runtime, qualification record or completion contract change.

The T1 attestation-factory extraction is behaviour-preserving and proven by the existing attestation API tests. Measurements are development evidence only.

## 17. Failure modes and refusals (summary)

| Stage | Refused when |
|---|---|
| Export | run or job not terminal; attestation integrity; pipeline-profile file not the attested one, or malformed; Track/run/video linkage; orphan observation; malformed subclass state; non-Stage-3 profile; evidence or source bytes changed; missing artefacts |
| Sample | bad export hash or schema; export not derived from the recorded release; invalid design or reason; continuation export set differing from the pilot's; target exceeds usable pool; duplicate Track; requirements not committed unchanged; invalid exclusion sample |
| Pack | source MP4, profile, evidence or frame mismatch; labelling guide not committed unchanged; overlap pack without a valid parent pack; text asset not UTF-8; `pack-data.js` not regenerating from the manifest |
| Freeze/adjudicate | labels not frozen before adjudication; pack identity altered; missing or duplicate item; item outside the pack; vocabulary violation; reason without `unknown` or `unknown` without reason; note invalid; reviewer missing; overlap coverage mismatch; adjudicated unknown reason missing, invalid or not allowed; decision for a carried item |
| Evaluate | export hash; labelling guides differ; continuation design or source-pool mismatch; overlap pack not derived from the primary pack; label for a non-exported or non-Vehicle Track; video hash mismatch; duplicates; batch pairing; adjudication not matching its label files; overlapping batches; mixed producers; profile mismatch; missing or foreign subclass source; missing attestation |
| Run/compare | missing requirements; overlap labels without a frozen adjudication; requirements differing from the samples' binding; any input hash mismatch |
| Derivation | source not in the release or not matching its hash; release files failing verification; unknown codec; non-deterministic output; passthrough hash mismatch; member not authorised for its mode (`evaluate` for passthrough; `evaluate` and `create-derivatives` for remux or transcode) |
| Release use | `authorise_release_use` blockers for the member and operations (R-5 absent, or an operation not granted) |

Every refusal exits with code 2, writes nothing, and gives a stable code.

## 18. Windows and offline handling

- **Offline:** all tools run offline on the Windows Development host.
  - The .NET tool needs the existing SDK and runtime.
  - The Python tools use only packages already in the repo venv (PyAV, Pillow, numpy, jsonschema).
  - Media probing and derivation use the offline-kit ffprobe/ffmpeg.
- **Storage:** data under `E:\MAVI-Controlled\…\S3\`, scratch under `E:\MAVI-Working`.
- **Labelling page:** opens from disk with no server.
- **Paths:** stored relative and forward-slashed inside artefacts, and never absolute.
- **Line endings:** every generated or copied text artefact (canonical JSON, the pack's HTML, JS and CSS) is written as UTF-8 with LF, and hashed from those bytes; a CRLF checkout does not change any identity (T4 regression test). Existing repository line-ending controls are unchanged.
- **Dependencies:** `offline-dependency-policy-v1.json` is unchanged.

## 19. Risks and open questions

**Human decisions and blockers (not solvable by code)**
1. CityFlow access request and acceptance of terms (owner).
2. Licence/terms review and the **R-5 determination** (R-5; this plan makes no legal judgement).
3. The pre-registered requirements (§13), including whether any operational threshold is defensible yet.
3a. The labelling guide's boundary rules (§5), approved by the owner before any pack is built.
4. Overlap reviewer identity: Savita proposed, to be confirmed.
5. The labelling work itself.
6. The expansion decision.
7. A Development host with the real Model Pack for T9.

**Risks**
- **Domain bias.** CityFlow is US intersection footage from fixed traffic cameras. Results describe that domain only.
- **Class imbalance.** Cars dominate; buses and motorcycles may be rare. Support is recorded honestly, and gaps are not padded.
- **Benchmark exposure** and possible overlap with public pretraining are recorded and caveated.
- **The measurement is Track-conditional.** Tracking failures appear as `mixed-track`, `not-a-vehicle` or unknown, not as subclass accuracy.
- **Night and adverse weather** coverage may be limited; it is recorded from the probe and sample strata.
- **Transcoding** may alter pixels. It is recorded in the derivation manifests, and remux is preferred.
- **Label noise** limits what the measurement can show; that is why the overlap reliability is reported.

## 20. Exit evidence

**S3.2 is complete when all of the following exist:**
1. **S3.2a merged with CI green,** including:
   - export snapshot-invariant tests;
   - the sampler blindness and executable allocation/balancing tests;
   - the pack leak test, the CRLF pack-identity regression and the adjudication-blindness test;
   - evaluator mutation pins;
   - the byte-stable end-to-end synthetic pipeline.
2. **A release record** with verified hashes, terms evidence, exposure and the R-5 determination; and derivation manifests that re-derive byte-identically, each with the member-scoped authorisation its mode requires.
3. **A committed requirements file,** bound by hash and commit into every sample, and matched by the runner.
4. **A recorded pilot.** Every input hash recorded (release, derivations, exports, sample, packs, label sets, adjudication, requirements, labelling guide, result), plus:
   - the requirement-comparison table;
   - support per class, with insufficient-support classes named;
   - reviewer agreement;
   - a single attested producer identity and profile hash.
5. **A recorded expansion decision,** with an expansion measurement if one is undertaken.
6. **Nothing exposed or added:** no API, search, UI, Production, classifier or tuning change.

*Evidence record (filled during S3.2c/d): artefact hashes, the summary tables and the decisions go here. Data stays outside Git.*
