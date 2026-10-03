# Stage 3 S3.2 — Vehicle subclass measurement: export, corpus, labelling, evaluation

**Status:** S3.2a (T1–T6) is implemented and merged (PRs #147, #148; `main@8fd15857cdb2a33baa1dd36361e714d9c312bd95`) and is fixed baseline. This revision makes S3.2b (T7–T9) implementation-ready; nothing in S3.2b is implemented yet.
**Baseline:** originally `main@d7508201b217261bed9979390ebfaa0bf61b8e18` (PR #145, S3.1); S3.2b amendment against `main@8fd15857`.
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
- only schemas, tools, tests, the hash-only evidence record (§20) and small pre-registration documents (requirements, labelling guide, and in S3.2b the frozen source pool, the ingestion map and, where used, the Development ingestion convention; metadata only) are committed.

## 4. Slice boundaries

| Slice | Tasks | Fixtures only? | Real CityFlow | R-5 | Development host | Human labelling |
|---|---|---|---|---|---|---|
| **S3.2a — tooling** (merged) | T1–T6 | **Yes** | – | – | – | – |
| **S3.2b-1 — T7/T8 tooling** | T7, T8 tooling | **Yes** | – | – | – | – |
| **S3.2b-2 — corpus intake and derivation** | T7, T8 real | – | Yes | **Yes** | – | – |
| **S3.2b-3 — Development-host execution** | T9 | – | Yes (T8 outputs) | (done in b-2) | **Yes** | – |
| **S3.2c — pilot** | T10 | – | Yes | (done in b) | – | **Yes** |
| **S3.2d — expansion** | T11 (conditional) | – | Yes | – | maybe | **Yes** |

**Gates (fail-closed; each slice waits only on its own row).**

| Gate | Blocks | Does not block |
|---|---|---|
| none | – | **S3.2b-1 can begin immediately** |
| dataset access; the owner's acceptance of its terms; the R-5 determination | S3.2b-2 real execution | S3.2b-1 |
| a Development MAVI host with a fresh, dedicated catalogue and media store (created after the pool freeze); the real Model Pack and runtime | S3.2b-3 | S3.2b-1, S3.2b-2 |
| committed approved labelling guide; committed pre-registered requirements; a confirmed independent second reviewer | T10 (S3.2c) | S3.2b-1, S3.2b-2, S3.2b-3 |

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
| `vehicle-subclass-requirement-comparison-v1` | the requirement status table | see T6 |
| `vehicle-subclass-media-probe-v1` | one probed media file | see T7 |
| `vehicle-subclass-source-pool-v1` | the frozen source pool | see T7 |
| `vehicle-subclass-derivation-v1` | one derived MP4 (T8 produces it; T3 consumes it) | see T8 |
| `vehicle-subclass-ingestion-map-v1` | the T9 camera, time-zone and recording-start input | see T9 |
| `vehicle-subclass-t9-execution-v1` | release member → MAVI run → export mapping | see T9 |

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

### S3.2b sequencing (T7–T9)

S3.2b runs as three slices, in order. Each is fail-closed: a slice never starts on an unmet gate (§4).

| Slice | Content | Real data | Gates |
|---|---|---|---|
| **S3.2b-1 — T7/T8 tooling, fixtures only** | media probing, the approved-binary loader, derivation tooling, the `vehicle-subclass-media-probe-v1`, `vehicle-subclass-derivation-v1`, `vehicle-subclass-source-pool-v1`, `vehicle-subclass-ingestion-map-v1` and `vehicle-subclass-t9-execution-v1` contracts, the release/rights consumer checks, the import-policy parity vector, the T9 tool against a stubbed API (it needs no host), deterministic synthetic tests | none: no CityFlow, no R-5 decision, no Development host | **none; it can begin immediately** |
| **S3.2b-2 — real corpus intake and derivation** | the owner's dataset access; retained, hashed terms/licence; the R-5 determination; the release record; real `verify_release_files`; probes; the frozen 6–10 video source pool; real T8 derivations | the real release, kept outside Git | access and terms accepted by the owner; the R-5 determination |
| **S3.2b-3 — T9 Development-host execution** | the committed ingestion map; MAVI camera creation; import through the public API; real processing; T1 export; the T9 execution record and its producer/run checks | T8 outputs from S3.2b-2 | a Development MAVI host with a fresh, dedicated catalogue and media store created after the pool freeze; the real Model Pack and runtime; the shipped `1.3.0-candidate` profile |

The T10 human decisions (final labelling-guide rules, pre-registered requirements, the confirmed second reviewer) do **not** block S3.2b-1, S3.2b-2 or S3.2b-3.

**S3.2b scope boundaries.** S3.2b does not:
- alter T1–T6 contracts, except T3's schema validation of the derivation manifest (T8);
- change C+ corpus policy, make or encode an R-5 determination, choose terms on the owner's behalf, or authorise use of any real release;
- create the real requirements, the final labelling-guide rules, or confirm any reviewer;
- change the MAVI API, search, UI or import semantics;
- add a classifier, tune subclass thresholds, or alter Model Pack or Runtime Pack qualification;
- begin S3.2c/T10.

### Approved media binaries (shared by T7 and T8)

**New:** `tools/stage3/media_tools.py`.

**One location convention, the platform's own.** Every S3.2b tool that runs FFmpeg or ffprobe takes `--media-tools <dir>`. This is a MAVI FFmpeg dependency pack laid out as `vendor/ffmpeg/README.md` specifies and `NativeMediaToolStartup` verifies:
- `<dir>/manifest.json` with `schemaVersion` `"1.0"`, `runtimeId`, `version`, and `artifacts[{fileName, sha256}]`;
- `<dir>/<runtimeId>/ffprobe(.exe)` and `ffmpeg(.exe)`.

On the Development host that is the staged `vendor/ffmpeg` pack or the installed application's `tools/ffmpeg`.

**Verification (`media_tools_invalid` on any failure):**
- the manifest schema is checked;
- `runtimeId` must equal the host's runtime id (`win-x64` or `linux-x64`, derived as `MediaToolPathResolver.CurrentRuntimeId` derives it);
- each executable's SHA-256 must equal its manifest entry;
- `-version` output must contain the manifest `version`.

**What is never allowed:**
- PATH discovery;
- the web host's Development PATH fallback;
- an unlisted binary.

**What is recorded.** The directory is a runtime-only input and is never written into an artefact. Artefacts record only `{version, sha256}` per tool, where `version` is the manifest's `version` token, never raw `-version` output (some builds print a `configuration:` line that can contain build paths).

**Test packs.** Synthetic tests build a throwaway pack around the binary available to the test environment, with a manifest pinning its SHA-256. CI gets that binary from the same "Ensure FFmpeg" step the .NET job already uses, added to the job that runs `tools/stage3/tests`. This exercises the binding; it is not a claim about any release binary. A distribution FFmpeg is dynamically linked, so its executable SHA-256 does not pin the libraries it loads; the binding is meaningful as identity only for the static Windows pack used on the Development host.

### T7 — Release intake and media probing

#### S3.2b-1: `tools/stage3/probe_media.py` (fixtures only)

**CLI:** `--media-tools <dir> --input <file> --out <file>`.

**Probing.** It runs exactly the platform reader's `ffprobe -v error -print_format json -show_streams -show_format <input>` (`FfprobeVideoMetadataReader`), with no `-count_frames`. It applies the reader's selection rules:
- the first video stream;
- frame rate from `avg_frame_rate`, then `r_frame_rate`;
- duration from the format, then the stream.

**Record `vehicle-subclass-media-probe-v1`** (canonical JSON, write once):

| Member | Content |
|---|---|
| `sourceSha256`, `sourceSizeBytes` | of the probed bytes; the file name and path are never recorded |
| `ffprobe` | `{version, sha256}` from the verified pack |
| `format` | `{formatName, majorBrand \| null, durationMs}`; `majorBrand` raw, exactly as ffprobe reports the `major_brand` tag (the platform reader stores it raw too); `durationMs` as the reader computes it: decimal seconds × 1000, rounded half away from zero (Python `Decimal`, `ROUND_HALF_UP`), never float arithmetic |
| `videoStreamCount` | number of `codec_type == "video"` streams |
| `video` | `{codec, profile \| null, width, height, frameRateNumerator, frameRateDenominator, durationMs, frameCount \| null, frameCountSource: "container" \| null}`, or `null` when there is no video stream. `frameCount` is the stream's declared `nb_frames` only; frames are never counted by decoding |
| `maviImport` | `{policy: "phase1-mp4-container-v1", containerSupported, metadataValid}`. `metadataValid` is the platform reader's acceptance: a `format_name`; a first video stream with positive integer width and height, a non-empty `codec_name`, a positive `n/d` frame rate (`avg_frame_rate`, then `r_frame_rate`) and a positive duration (format, then stream). When it is false the corresponding `video` members are `null`. A single video stream is a T8 rule, not an import rule |

**Import compatibility, without a loose second copy.** `containerSupported` is an exact port of `PhaseOneMp4ContainerPolicy.IsSupported`, in its order:
- split the format name on `,` with entries trimmed and empty ones removed; one entry must equal `mp4` case-insensitively;
- take the raw brand, `Trim()` it (only the characters .NET `char.IsWhiteSpace` treats as white space), then remove trailing NUL characters, then lower-case it (ASCII only);
- it must be non-empty after that, must not equal `qt`, and must not start with `3gp` or `3g2`.

Python's `str.strip` uses a different white-space set, so the port strips the .NET set explicitly.

Sharing the C# code with Python is impractical, so one pinned vector, `contracts/test-vectors/phase1-mp4-container-policy-v1.json` (`{formatName, majorBrand, supported}` cases), is consumed by both sides:
- a new `Mavi.Application.Tests` test over the internal `PhaseOneMp4ContainerPolicy` (`InternalsVisibleTo` already exists);
- the Python probe tests.

The vector covers:
- supported ISO MP4 (`isom`, `mp42`);
- `qt  ` refused;
- `3gp4` and `3g2a` refused;
- a non-MP4 format (`matroska,webm`) refused;
- missing, empty, whitespace-only and NUL-padded-empty brands refused;
- case and padding: an upper-case brand (`QT  ` refused, `ISOM` supported), upper-case or space-padded format tokens (`MP4`, ` mp4 `), a leading-white-space brand;
- the order-sensitive cases, pinned with the platform's current results as they are: `"qt\0"` (refused) and `"qt \0"` (supported, because white space is trimmed before the NULs);
- a brand padded with `\x1c` (a character .NET and Python classify differently).

A change to either implementation without the vector fails one side. No platform code changes.

**Refusals:**
- `media_tools_invalid`;
- `probe_input_unreadable`;
- `probe_failed` (ffprobe non-zero exit or unparseable output);
- `probe_invalid_media` (ffprobe output without a `format` object);
- `output_exists`.

A file with no video stream or several video streams is a valid probe: `video` is `null` or the first stream, and `videoStreamCount` says which. Consumers decide.

**Tests (fixtures; tiny synthetic media):**
- deterministic canonical bytes;
- pack binding: a wrong SHA-256, wrong runtime or wrong version is refused, and a PATH-only binary is never used;
- the parity vector;
- a supported MP4;
- QuickTime, 3GP and 3G2 brands (made by remuxing a fixture with `-brand`/`-f mov`);
- a non-MP4 container;
- no video stream; two video streams;
- invalid bytes refused.

#### S3.2b-2: real release intake (⚠ owner, ⚠ R-5)

See §8 for what is verified and retained.

**Release record.** The record (`mavi-attribute-dataset-release-v1`) is authored with its `files[]`, `excludedMembers`, licence evidence, `knownExposure` and R-5's `determination`, and checked with:
- `parse_release`;
- `verify_release_files(release, <release-root>)`, with the release root outside every Git worktree (the verifier refuses otherwise);
- a probe of every candidate member.

**Exit:**
- the record parses;
- the files verify;
- every pool member has a probe;
- `authorise_release_use(release, ["benchmarking", "development"], member=<member>)` returns no blockers for every pool member;
- the source pool is frozen.

The `create-derivatives` status is recorded as R-5 determined it; this plan assumes nothing about it.

#### Frozen pilot source pool: `vehicle-subclass-source-pool-v1` (contract and tool in S3.2b-1, used in S3.2b-2)

**No existing artefact fits.** The S2c corpus manifest (`tools/qualification/attributes/corpus`) describes sources *after* MAVI processed them. The source-acquisition receipts (`tools/qualification/source_acquisition`) are per-file admission rules for the S2c pilot.

**New:** `tools/stage3/freeze_source_pool.py --release <record> --release-root <dir> --probe <file>... --selection <file> --out <file>`.

**Selection file.** It is human-authored and lists `{member, sourceCamera, inclusionReason}` for 6–10 members.

**Source-side facts only.** Selection may use only facts known independently of MAVI output:
- the corpus camera identity;
- scene or location metadata the release itself supplies;
- duration and resolution;
- time of day or weather, only when the release genuinely provides it;
- probe viability;
- broad camera and scene diversity.

It must never use MAVI subclass, confidence or Track outcomes, human vehicle-type labels, or T6 results. The tool has no option that accepts an export, attestation, label, sample or result.

**Record:**

| Member | Content |
|---|---|
| top level | `releaseId`, `releaseRecordSha256`, `kind: "pilot"` (or `"supplemental"` for any later pool), `selectionProcedure: {id: "s3-2-source-pool-manual-v1"}` |
| `members[]` | `{member, sha256, sizeBytes, probeSha256, sourceCamera, inclusionReason (≤200 chars, one line)}`, sorted by `member` |

**Checks.** It calls `parse_release` and `verify_release_files(release, root)`, then authorises each member with `authorise_release_use(release, ["benchmarking", "development"], operations=[], member=<member>)`. `inclusionReason` passes the repository's existing free-text and local-path checks (`refuse_local_paths`).

**Refusals** (`source_pool_invalid:*`):
- a release that does not parse or whose files fail verification (including a release root inside Git);
- a member not listed, excluded, or not matching its release entry;
- two members with identical `sha256` (they would later fail `export_video_duplicate`);
- a probe whose `sourceSha256` is not the member's;
- a member with authorisation blockers;
- duplicate members;
- fewer than 6 or more than 10 members for `pilot`;
- an inclusion reason that is empty, multi-line or longer than 200 characters.

**Frozen before inference.** The record contains metadata and hashes only. It is committed to the repository as `docs/qualification/stage3/s3-2-source-pool.json` before any member is imported. T9 verifies the binding exactly as T3 verifies the requirements (`artefacts.git_binding`: byte-identical at a commit that is an ancestor of `HEAD`).

If R-5 finds the terms forbid recording member names in the repository, the record stays in the controlled store. Instead `docs/qualification/stage3/s3-2-source-pool.sha256` (the record's SHA-256, one LF-terminated line) is committed before any import. T9 then `git_binding`s that digest file and checks the controlled-store record's SHA-256 against it.

**After freezing:**
- the pilot pool is the only continuation-eligible processed pool (T3 already refuses a continuation whose export set differs from the pilot's);
- any source selected after the freeze needs its own `kind: "supplemental"` pool record and can only feed a `supplemental` batch (§14);
- the primary pool is never widened.

**Tests:**
- a valid record;
- each refusal;
- determinism;
- no MAVI-output option exists.

### T8 — MP4 derivation (`tools/stage3/derive_mp4.py`)

**S3.2b-1:** tooling, schema and synthetic tests. **S3.2b-2:** real derivations of the frozen pool.

**CLI:** `--media-tools <dir> --release <release-record> --release-root <directory> --member <release-relative-path> --mode passthrough|remux|transcode --max-import-bytes <n> --out <new-dir>`.
- `--max-import-bytes` is the Development host's configured `VideoImport:MaximumFileSizeBytes` (default 3 GiB). It is recorded in the manifest as `importLimitBytes`, so the import check below is the host's own limit.
- `--release-root` and `--media-tools` are local, runtime-only paths and are never written into the manifest.
- `--member` is the canonical release-relative path recorded as `release.member`.

**Order of checks.** No second rights or provenance model exists; the existing functions are called as follows:
1. `parse_release` (`derivation_release_invalid`).
2. `verify_release_files(release, root)`: a root inside a Git worktree is `derivation_release_root_invalid`, and any reported problem is `derivation_release_files_mismatch`. This re-hashes the whole release on every call, including determinism repeats; the cost is accepted for simplicity.
3. The member must be in `files[]` (`derivation_member_not_listed`) and not in `excludedMembers` (`derivation_member_excluded`). It is copied into the staging directory while being hashed, and the copy must match the entry's size and SHA-256 (`derivation_member_changed`). Everything after this step, including FFmpeg, reads only that verified copy, so the file cannot change between hashing and use.
4. `authorise_release_use(release, ["benchmarking", "development"], operations=<ops>, member=<member>)`, with `<ops>` `[]` for passthrough and `["create-derivatives"]` for remux or transcode. Any blocker is `derivation_not_authorised`, with the blockers, and the manifest is written only when the list is empty.
   - T8 makes no legal judgement: R-5's determination lives in the release record, and T8 only consumes and enforces it.
   - `releaseRecordSha256` (the record's canonical identity, `release_sha256`) binds the exact determination in force.
   - C+ and R-5 semantics are unchanged.
5. `--mode` must be one of the three (`derivation_mode_invalid`). The source probe must succeed (`derivation_probe_failed`) with exactly one video stream.
6. The selected mode's precondition must hold. The tool never falls back to another mode:

| Mode | Precondition (else) | Output |
|---|---|---|
| `passthrough` | the source is importable (below) and has one video stream (`derivation_passthrough_not_importable`) | the source bytes copied, never rewritten |
| `remux` | codec in the remux allow-list, initially `("h264",)` (the codec the worker is known to decode; the importer itself has no codec check), and one video stream (`derivation_remux_codec_unsupported`). Widening the list is a plan amendment | FFmpeg, `-c:v copy` |
| `transcode` | any source passing step 5 | FFmpeg with the pinned recipe |

**Pinned FFmpeg arguments.** The manifest records them with `{input}` and `{output}` placeholders, never paths. The recipe is the plan's, with the stream-selection and metadata-stripping flags needed for byte reproducibility made explicit:
- **remux:** `-nostdin -hide_banner -loglevel error -i {input} -map 0:v:0 -c:v copy -an -sn -dn -map_metadata -1 -map_chapters -1 -fflags +bitexact -flags:v +bitexact -movflags +faststart -f mp4 {output}`
- **transcode:** `-nostdin -hide_banner -loglevel error -i {input} -map 0:v:0 -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -threads 1 -an -sn -dn -map_metadata -1 -map_chapters -1 -fflags +bitexact -flags:v +bitexact -movflags +faststart -f mp4 {output}`

**After FFmpeg runs:**
- a non-zero exit is `derivation_ffmpeg_failed`;
- an unverified or missing binary is `media_tools_invalid`.

**Importable** means: `maviImport.containerSupported`, `maviImport.metadataValid`, size ≤ `--max-import-bytes`, and the file name `video.mp4`. The output is probed and must be importable with one video stream (`derivation_output_not_importable`). The manifest must be consistent (`derivation_output_inconsistent`):
- `outputSha256` is the SHA-256 of the written `video.mp4`;
- `sourceMedia.sourceSha256 == sourceSha256` and `outputMedia.sourceSha256 == outputSha256`;
- passthrough requires `outputSha256 == sourceSha256`;
- remux and transcode require the output to differ from the source.

**Output layout and atomicity.**
- **Layout:** exactly `<out>/video.mp4` (the import extension MAVI accepts) and `<out>/derivation-manifest.json`.
- **Atomicity:** both are built in a hidden staging sibling and published by one rename (`artefacts.OutputDirectory`). A refusal or failure leaves no output directory.
- **Existing output:** an existing `<out>` is `output_exists`.
- **Manifest form:** canonical JSON with no absolute or local path.

**Contract `vehicle-subclass-derivation-v1`.** New: `contracts/schemas/vehicle-subclass-derivation-v1.schema.json` plus a synthetic example. T8 is its authoritative producer, and it contains exactly:
- `schemaVersion`;
- `release {releaseId, releaseRecordSha256, member}`;
- `authorisation {purposes, operations, blockers}`;
- `sourceSha256`, `sourceMedia` (the source's `vehicle-subclass-media-probe-v1` record);
- `mode`;
- `ffmpegVersion`, `ffmpegSha256`;
- `args`;
- `outputSha256`, `outputMedia` (the output's probe record);
- `importLimitBytes`.

The schema states the mode rules:
- **passthrough:** `operations == []`, `args == []`, `ffmpegVersion == null`, `ffmpegSha256 == null`, `outputSha256 == sourceSha256`. Equality between members is enforced by the T8 and T3 code; the schema pins the constants.
- **remux/transcode:** `operations == ["create-derivatives"]`; FFmpeg version and SHA-256 present; `args` equal to the pinned list for the mode.
- **always:** `purposes == ["benchmarking", "development"]` and `blockers == []`.

**T3 amendment, narrow.** T3 schema-validates each derivation manifest against `vehicle-subclass-derivation-v1` before its existing semantic checks (`_derivations`), which stay as they are as defence in depth. A manifest the schema refuses is `derivation_invalid:schema`. `tools/stage3/tests/s32fixtures.write_derivation` is updated to emit schema-valid manifests (real probe-record shapes, the pinned args per mode); the existing `derivation_invalid` test expectations still hold by prefix. No other T1–T6 contract changes.

**Determinism.** Identity holds within one pinned binary (version and SHA-256); cross-build reproducibility is never claimed.
- **Synthetic CI:** passthrough, remux and transcode each run twice must give byte-identical `video.mp4` and manifest bytes.
- **Real corpus:** the first real remux and the first real transcode, if exercised, are each run twice, and output and manifest bytes must match exactly. Any non-determinism blocks that mode until explained and recorded.

**Tests (S3.2b-1, fixtures; small synthetic media made by the test's FFmpeg; no corpus files in Git):**

| Area | Cases |
|---|---|
| Release/root | valid release and store verify; missing member; size mismatch; SHA-256 mismatch; excluded member; release root inside Git refused; malformed record; absent determination; member-scoped blockers (`pending-r5`, `not-granted`) |
| Passthrough | byte copy; `outputSha256 == sourceSha256`; no FFmpeg identity; `operations == []`; non-importable source refused; repeat byte-identical |
| Remux | refused without `create-derivatives` granted; pinned binary and args; output importable; source and output recorded separately; unsupported codec refused; repeat byte-identical |
| Transcode | exact pinned recipe; `create-derivatives` required; source and output hashes differ; output importable; repeat byte-identical |
| Failures | an authorisation blocker leaves no output; an FFmpeg failure leaves no output; existing destination refused; no absolute path in the manifest |
| Contract | the schema and example validate; T3 accepts a generated manifest of each mode; T3 refuses each unauthorised variant (wrong purposes, passthrough carrying `create-derivatives`, remux without it, non-empty blockers), now at schema validation (`derivation_invalid:schema`), with the semantic checks kept as defence in depth |

### T9 — Development-host execution (S3.2b-3; ⚠ Development host)

**New:** `tools/stage3/ingest_source_pool.py`. It is built and tested in S3.2b-1 against a stubbed API and run for real only in S3.2b-3. It drives MAVI through its product path only, using standard-library HTTP to the local API (multi-gigabyte uploads need a small streaming multipart encoder):
- `GET /api/cameras` and `POST /api/cameras`: one MAVI camera per `sourceCamera`;
- `POST /api/videos/import`: each frozen member's T8 `video.mp4`, multipart with `cameraId` and `recordingStartLocal`;
- `POST /api/videos/{id}/process`;
- `GET /api/videos/{id}/processing` until the run is terminal;
- the T1 tool (`Mavi.MeasurementExport --run --pipeline-profile --out`) for each completed run.

**What it never does:**
- write to the database directly;
- use a manual bypass;
- change platform import or processing semantics.

**Inputs:**
- the frozen source-pool record and its git binding (or its committed digest file; §T7);
- the committed ingestion map (`vehicle-subclass-ingestion-map-v1`, below) and its git binding;
- the T8 output directories;
- the measured pipeline profile file (the shipped `1.3.0-candidate`);
- the API base URL and a resume-journal location, which are runtime-only.

**Before any API call,** T9 verifies:
- both git bindings;
- that the map's `sourcePoolSha256` is the pool's;
- that the map has exactly one entry per pool member and no extras.

It creates no camera and imports nothing until all of these pass.

**Ingestion map `vehicle-subclass-ingestion-map-v1` (new; the machine-readable T9 camera and time input).** It is written after T7 has established what source metadata the release really carries, and committed before the first T9 import as `docs/qualification/stage3/s3-2-ingestion-map.json` (metadata only). If R-5 finds the terms forbid recording member names in the repository, the same committed-digest-file rule as the source pool applies: `docs/qualification/stage3/s3-2-ingestion-map.sha256`. Contents:

| Member | Content |
|---|---|
| `schemaVersion` | `vehicle-subclass-ingestion-map-v1` |
| `sourcePoolSha256` | the frozen pool record it maps |
| `cameras[]` | `{sourceCamera, cameraCode, name, timeZoneId}`: one per distinct pool `sourceCamera`. `cameraCode` is deterministic: `S32-` + the `sourceCamera` upper-cased with every character outside `A–Z`, `0–9` and `-` replaced by `-`, truncated to MAVI's 32-character limit (`Camera.Create` upper-cases and refuses longer codes); a collision after this normalisation is a duplicate camera code; `name` is the display name `POST /api/cameras` requires; `timeZoneId` is an explicit IANA id |
| `members[]` | exactly one per frozen member: `{member, cameraCode, recordingStartLocal, recordingTime}` |
| `recordingStartLocal` | a time-zone-less local wall-clock time, `YYYY-MM-DDTHH:MM:SS`, never with an offset or `Z`. It always travels with its camera's `timeZoneId`, exactly as MAVI's import interprets it |
| `recordingTime` | `{source: "release-metadata", evidence: {releaseRecordSha256, member}}` naming the release file that carries the value; or `{source: "development-convention", convention: {sha256, gitCommit, gitPath: "docs/qualification/stage3/s3-2-ingestion-convention.md"}}` |

- **Mixed cases.** Members may differ: some take trustworthy release metadata, others the Development convention.
- **Release metadata.** When the release provides trustworthy recording time and time zone, the map records those values and names the release evidence file (listed in the release record) that supports them.
- **Development convention.** Otherwise `docs/qualification/stage3/s3-2-ingestion-convention.md` is committed. It states how the deterministic Development-only `recordingStartLocal` and time-zone values are assigned, and that they are not claimed as actual source capture times. The convention document explains; the map is what T9 reads. Every map entry that uses it binds its SHA-256 and commit, and T9 verifies that binding (`artefacts.git_binding`).

**Map refusals** (`ingestion_map_invalid:*`, all before any API call):
- a pool member missing, an extra member, or a duplicate member;
- a member naming an unknown `cameraCode`;
- a duplicate `cameraCode`, or two cameras for one `sourceCamera`;
- an invalid or non-IANA `timeZoneId`;
- a malformed `recordingStartLocal`, or one that does not exist or is ambiguous in its zone (the importer refuses both);
- `sourcePoolSha256` not the pool's;
- a release-metadata entry whose release or member is not the pool's release and a listed file;
- a convention entry whose file is not byte-identical at its commit, or whose commit is not an ancestor of `HEAD`.

Zone validation uses Python's `zoneinfo`. Its `tzdata` package is present in the repository venv but undeclared, so S3.2b-1 declares it in `tools/requirements.txt` and the offline dependency policy, per the dependency rule.

**Host preconditions** (operational; T9 does not start without them):
- **A fresh, dedicated catalogue.** S3.2b-3 runs on a newly initialised Development MAVI catalogue (database) and managed-media store, provisioned for this S3.2 event only and created after the pilot source pool has been frozen and committed. No pre-existing application data or source video is present when T9 starts. If such a catalogue cannot be provided, T9 does not start.
- **Native-media verification.** The host runs with `MediaProcessing:AllowPathFallbackInDevelopment=false` and its normal native-media startup verification enabled. The product's own startup behaviour enforces this (`NativeMediaToolStartup`).

**What each control proves, and what it does not.**
- **The source-side-only selection procedure** (the committed pool record and its tool, which accepts no MAVI output) prevents this S3.2 event from choosing the pilot pool based on its own MAVI outputs.
- **The fresh, dedicated T9 catalogue** prevents T9 from reusing pre-freeze MAVI state within this controlled event.
- **Hashes do not prove freshness.** A release member could earlier have been imported as a different derivation with a different SHA-256, so source hashes are never treated as proof of freshness.
- **No proof about other machines.** MAVI cannot prove that the corpus bytes were never processed on some unrelated machine in the past, and the plan claims no such thing.

**Runs are never reused.**
- **Journal.** Every member's run is queued by T9 itself, and the queued run id is written to the T9 resume journal before polling.
- **Resume.** Resuming is allowed only within the same dedicated T9 instance, using the journal. A `video_duplicate` answer is accepted only when the journal shows that this same T9 event created or bound that asset, with the same camera and recording start; otherwise it is `t9_asset_preexisting`.
- **No outside runs.** A run is never taken from outside the journal.
- **Polling.** The public API exposes only the latest run, so while polling T9 requires `latestRun.processingRunId` to equal the run it queued (`t9_run_substituted`).

**Cameras.**
- Each map camera is created once with its `code`, `name` and `timeZoneId`.
- On a resume, cameras are looked up by code (`GET /api/cameras`) and must match the map's name and time zone (`t9_camera_mismatch`); they are never re-created.
- Each import sends the member's `recordingStartLocal` with that camera's `cameraId`.

**Media tools and what is not recorded.**
- T7 and T8 bind the exact verified FFmpeg/ffprobe pack (manifest, executable SHA-256s, versions) used for probing and derivation.
- T9 does not and cannot identify the running host's native-media pack: neither the product API nor the processing-run attestation exposes it, and no such field is recorded.
- This is acceptable because:
  - the copy, remux or transcode that creates the measured input is fully provenance-bound by T8;
  - T9 imports that exact hash-bound MP4 through the real product API;
  - the model and runtime producer identity stays bound by the processing-run attestation.

If a future qualification needs the native-media pack as part of the processing-run producer identity, that requires a separate product-provenance change, not a field fabricated by S3.2 tooling.

**Execution record `vehicle-subclass-t9-execution-v1`.** New; a small canonical evidence artefact, not a qualification framework. Its camera and time fields come only from the verified ingestion map.

| Member | Content |
|---|---|
| bindings | `sourcePoolSha256` (with `gitCommit`), `ingestionMapSha256` (with `gitCommit`), `releaseRecordSha256`, `measuredProfileSha256` |
| `producer` | the single producer identity carried by every attestation: model, checkpoint and manifest, pipeline and runtime profile, Model Pack, runtime pack, binding, `maviBuild`, `maviCommit`. Host identity only as far as the attestation already carries it (platform fields); no new host identifier |
| `cameras[]` | `{sourceCamera, cameraCode, name, timeZoneId}` from the map, plus the `cameraId` MAVI assigned |
| `members[]` | per frozen member: `{member, derivationManifestSha256, derivedSha256, cameraCode, recordingStartLocal, recordingTime, videoAssetId, processingRunId, attestationSha256, exportSha256}`, with `cameraCode`, `recordingStartLocal` and `recordingTime` copied from the map, and `attestationSha256` the canonical SHA-256 of the export's embedded attestation |

**Exit, checked before the record is written** (refusals `t9_*`):
- exactly one derivation per pool member; each schema-validates, its `release.releaseRecordSha256` is the pool's, its `release.member` is that pool member and its `sourceSha256` is that member's `sha256`;
- exactly one valid T1 export per frozen member; no missing, extra or substituted member or run;
- every export's `video.sourceSha256` equals its T8 `outputSha256`;
- no duplicate video asset or source content (`artefacts.load_exports` already refuses);
- all exports attest one producer identity and bind the measured profile (the S3.1 `_producer` check);
- every run is `Completed`, and is the one T9 queued and journalled for its member.

**Pilot sample binding (closes selection on MAVI output).** T3 binds a sample to exports and derivations but not to the frozen pool, so the pilot could otherwise be drawn from a subset of the T9 exports. `ingest_source_pool.py --verify-sample <sample> --execution <record>` refuses unless:
- the sample's `exportSha256s` equal the record's export set exactly;
- its `derivationSha256s` equal the record's `derivationManifestSha256` set;
- its `releaseRecordSha256` matches the record's.

T10 runs this check before building packs (T10 step 2), and its result is part of §20.

**Tests (S3.2b-1, fixtures, stubbed API):**
- **Ingestion map:**
  - a missing, extra or duplicate member;
  - an unknown camera; a duplicate camera code;
  - an invalid or non-IANA time zone;
  - a malformed, nonexistent or ambiguous local recording time;
  - a source-pool hash mismatch;
  - a wrong convention or release-evidence binding;
  - a deterministic valid mixed-source map (release metadata and the convention together).

  Each refusal happens before any stub API call.
- **Fresh catalogue:** `t9_asset_preexisting` for a duplicate answer the journal does not explain, including a member imported earlier as a different derivation; journal resume within the same instance; no run taken from outside the journal; `t9_run_substituted`.
- **Cameras:** created from the map; resumed by code; `t9_camera_mismatch`.
- **Record:** every exit refusal; camera and time fields equal the map's; no media-pack field; determinism.
- **Sample verifier:** its three refusals and its acceptance.

### T10 — Pilot (S3.2c; ⚠ human)

Run in order:
1. Commit the requirements (§13) and the approved labelling guide (§5).
2. Sample 120 Tracks with a 20 % overlap (T3), binding the committed requirements, from exactly the exports and derivations named by the T9 execution record; run the T9 sample verifier (`--verify-sample`) before building packs.
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
- **S3.2b-1:** probe, media-pack, source-pool, derivation and T9 (stubbed API) tests under `tools/stage3/tests/`; the import-policy parity vector consumed by a new `Mavi.Application.Tests` test and by the Python probe tests. The `repo-contracts` job, which runs `tools/stage3/tests`, gains the existing "Ensure FFmpeg" step.
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
| Camera/video metadata | `tools/stage3/probe_media.py` (T7; the verified FFmpeg dependency pack), one `vehicle-subclass-media-probe-v1` record per video |
| Native tracks/boxes | file inventory and format (expected MOT-style per-frame boxes and ids), and coverage. CityFlow annotations are believed to cover only vehicles seen by several cameras; to be verified. **Not used as ground truth.** |
| Native type labels | whether any exist. CityFlow core is not known to carry vehicle type; any found are recorded as **untrusted for this purpose** (taxonomy and definitions differ) and never used as ground truth |
| Exposure | whether RTMDet's COCO training or any MAVI component used CityFlow (model card or paper, recorded); public benchmark status; recorded as `knownExposure` |
| Restrictions | anything limiting development or evaluation use, derived artefacts or metrics |

**Derivation (T8).** Every measured video goes through T8 (passthrough, remux or transcode), so T9 always imports a T8 output and the chain release → derivation → import → export has no gaps. The full contract (CLI with `--release-root`, authorisation, explicit modes and their preconditions, pinned arguments, output layout, `vehicle-subclass-derivation-v1`, determinism and refusals) is in T8. A transcoded file is never described as identical to its source; **the derived MP4 is the measurement input**, and its hash is the export's `video.sourceSha256`.

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
- **measurement and passthrough derivation:** `authorise_release_use(release, ["benchmarking", "development"], operations=[], member=<member>)`;
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
| Probe | media pack missing, wrong runtime, hash or version (`media_tools_invalid`); input unreadable; ffprobe failure; invalid media; existing output |
| Source pool | release unparseable or files failing verification; member not listed, excluded or not matching its entry; duplicate members or identical member content; probe not of the member; authorisation blockers; not 6–10 pilot members; invalid inclusion reason |
| Derivation | malformed release; release root inside Git or files failing verification; member not listed, excluded or changed; authorisation blockers for the member and mode; invalid mode; probe failure; passthrough not importable; remux codec unsupported; FFmpeg missing, unverified or failing; output not importable; output identity inconsistent; non-deterministic repeat; existing output |
| Ingestion map | missing, extra or duplicate member; unknown or duplicate camera code; invalid or non-IANA time zone; malformed, nonexistent or ambiguous local recording time; source-pool hash mismatch; wrong convention or release-evidence binding |
| Execution (T9) | source pool or ingestion map not committed unchanged; a duplicate import the journal does not explain (`t9_asset_preexisting`); latest run not the queued one (`t9_run_substituted`); camera mismatch; derivation not of its pool member or release; missing, extra or substituted member or run; export source not the T8 output; duplicate video; mixed producers or wrong profile; run not completed; a pilot sample not drawn from exactly the recorded exports and derivations |
| Release use | `authorise_release_use` blockers for the member and operations (R-5 absent, or an operation not granted) |

Every refusal exits with code 2, writes nothing, and gives a stable code.

## 18. Windows and offline handling

- **Offline:** all tools run offline on the Windows Development host.
  - The .NET tool needs the existing SDK and runtime.
  - The Python tools use only packages already in the repo venv (PyAV, Pillow, numpy, jsonschema).
  - Media probing and derivation use only the verified MAVI FFmpeg dependency pack (`--media-tools`; manifest SHA-256, runtime id and version checked; never PATH). CI tests use a throwaway pack around the job's FFmpeg; the job running `tools/stage3/tests` gains the existing "Ensure FFmpeg" step.
- **Storage:** data under `E:\MAVI-Controlled\…\S3\`, scratch under `E:\MAVI-Working`.
- **Labelling page:** opens from disk with no server.
- **Paths:** stored relative and forward-slashed inside artefacts, and never absolute.
- **Line endings:** every generated or copied text artefact (canonical JSON, the pack's HTML, JS and CSS) is written as UTF-8 with LF, and hashed from those bytes; a CRLF checkout does not change any identity (T4 regression test). Existing repository line-ending controls are unchanged.
- **Dependencies:** FFmpeg/ffprobe are the existing `ffmpeg-win-x64` dependency, and T9 uses the standard library for local HTTP. One declaration is added in S3.2b-1: `tzdata` (already installed in the repository venv but undeclared) is declared in `tools/requirements.txt` and the offline dependency policy, because T9 validates IANA zones with `zoneinfo` on Windows. S3.2b-1 extends that entry's `setupIntegration` text in `offline-dependency-policy-v1.json` to name the Development tooling consumers (`tools/stage3` probe and derivation) alongside the application, so the policy states every consumer.
- **Runtime-only paths:** `--release-root`, `--media-tools`, the T8 output location and the API base URL are inputs, never artefact content.

## 19. Risks and open questions

**Human decisions and blockers (not solvable by code)**
1. CityFlow access request and acceptance of terms (owner). Blocks S3.2b-2.
2. Licence/terms review and the **R-5 determination** (R-5; this plan makes no legal judgement). Blocks S3.2b-2.
3. The pre-registered requirements (§13), including whether any operational threshold is defensible yet. Blocks T10 only.
3a. The labelling guide's boundary rules (§5), approved by the owner before any pack is built. Blocks T10 only.
4. Overlap reviewer identity: Savita proposed, to be confirmed. Blocks T10 only.
5. The labelling work itself.
6. The expansion decision.
7. A Development host with the real Model Pack for T9. Blocks S3.2b-3.
8. Whether the release carries trustworthy recording time and time zone, and otherwise the Development ingestion convention; then the ingestion map (decided after T7, committed before the first import).
9. A fresh, dedicated Development catalogue and media store for S3.2b-3, created after the pool freeze. Without it T9 does not start.

**Risks**
- **Domain bias.** CityFlow is US intersection footage from fixed traffic cameras. Results describe that domain only.
- **Class imbalance.** Cars dominate; buses and motorcycles may be rare. Support is recorded honestly, and gaps are not padded.
- **Benchmark exposure** and possible overlap with public pretraining are recorded and caveated.
- **The measurement is Track-conditional.** Tracking failures appear as `mixed-track`, `not-a-vehicle` or unknown, not as subclass accuracy.
- **Night and adverse weather** coverage may be limited; it is recorded from the probe and sample strata.
- **Transcoding** may alter pixels. It is recorded in the derivation manifests, and remux is preferred.
- **Label noise** limits what the measurement can show; that is why the overlap reliability is reported.

## 20. Exit evidence

> **Authority note (2026-10-03).** The Stage-3 acceptance register, `docs/reviews/2026-10-03-stage3-vehicle-subclass-acceptance.md`, is the only authoritative exit gate (`docs/architecture/README.md`, "Documentation precedence"). This section lists the evidence its rows require; it is not a second acceptance list. Evidence is recorded in the register, not here; the evidence-record placeholder at the end of this section is superseded.

**S3.2 is complete when all of the following exist:**
1. **S3.2a merged with CI green,** including:
   - export snapshot-invariant tests;
   - the sampler blindness and executable allocation/balancing tests;
   - the pack leak test, the CRLF pack-identity regression and the adjudication-blindness test;
   - evaluator mutation pins;
   - the byte-stable end-to-end synthetic pipeline.
2. **S3.2b evidence** (hashes and metadata only; raw media stays outside Git):
   - the exact release-record SHA-256, with the retained terms/access evidence and the R-5 determination inside that record;
   - the frozen source-pool record (committed before the first import) and its SHA-256;
   - the media probe hashes of every pool member and derived output;
   - the derivation manifest hashes, each with the member-scoped authorisation its mode requires;
   - the deterministic repeat evidence for the first real remux and transcode, where exercised;
   - the committed ingestion map and, where used, the ingestion convention, with their SHA-256s and commits;
   - a statement that T9 ran on a fresh, dedicated catalogue and media store created after the pool freeze;
   - the T9 execution record and its SHA-256;
   - the FFmpeg/ffprobe pack identity bound by T7/T8 (the T9 host's native-media pack is a host precondition, not recorded provenance);
   - the T1 export hashes, all attesting one producer identity and the measured profile across the pilot pool.
3. **A committed requirements file,** bound by hash and commit into every sample, and matched by the runner.
4. **A recorded pilot.** Every input hash recorded (release, derivations, exports, sample, packs, label sets, adjudication, requirements, labelling guide, result) and the T9 sample-verifier result, plus:
   - the requirement-comparison table;
   - support per class, with insufficient-support classes named;
   - reviewer agreement;
   - a single attested producer identity and profile hash.
5. **A recorded expansion decision,** with an expansion measurement if one is undertaken.
6. **Nothing exposed or added:** no API, search, UI, Production, classifier or tuning change.

*Evidence record (filled during S3.2c/d): artefact hashes, the summary tables and the decisions go here. Data stays outside Git.*
