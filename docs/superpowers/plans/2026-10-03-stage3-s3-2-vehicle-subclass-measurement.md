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
| `vehicle-subclass-sample-v1` | the selected Tracks | `seed`, `target`, `exportSha256s[]`, `strata`, `selected[]`, `overlapSelected[]`, `excluded{reason:count}`, `available{stratum:count}` |
| `vehicle-subclass-labeling-pack-v1` | the manifest of reviewer-visible evidence | see T4 |
| `vehicle-subclass-track-labels-v1` | one reviewer's committed decisions on one pack | see T5 |
| `vehicle-subclass-adjudication-v1` | resolution of overlap disagreements | see T5 |
| `vehicle-subclass-requirements-v1` | the pre-registered bar | see §13 |
| `vehicle-subclass-measurement-v1` | the result | see T2 |

The S3.1 Phase-1 ground-truth schema is not changed: Track-level labels are a different unit and get their own artefact, and the two never overlap.

**Label vocabulary (`mavi-vehicle-subclass-labels-v1`)**
- **Labels:** `car`, `truck`, `bus`, `motorcycle`, `unknown`.
- **`unknownReason`:** optional, only with `unknown`: `occluded`, `too-small`, `ambiguous-type`, `mixed-track`, `not-a-vehicle`, `other`.
- **`note`:** optional on any decision, at most 200 characters, single line.

These are review reasons, not `ObjectSubclass` values.

## 6. Ordered implementation tasks

### T1 — Read-only measurement export (S3.2a-1; fixtures only)

**Files**
- **New:** `src/platform/Mavi.Application/Modules/Processing/ProcessingRunAttestationFactory.cs`, `static ProcessingRunAttestationResponse Build(ProcessingRunAttestationSource, ParsedVisionRuntimeProvenance)`. The construction moves here, unchanged, from `ProcessingEndpoints.AttestationAsync`, which then calls it.
- **New:** `src/platform/Mavi.Infrastructure/Measurement/SubclassMeasurementExporter.cs`, `Task<SubclassMeasurementExport> ExportAsync(Guid runId, CancellationToken)`.
- **New:** `tools/dotnet/Mavi.MeasurementExport/` (console csproj referencing Infrastructure; added to `MAVI.sln`, so CI builds it). CLI: `Mavi.MeasurementExport --run <guid> --out <new-dir>`, reading the existing machine configuration for the connection string.
- **New:** `contracts/schemas/vehicle-subclass-measurement-export-v1.schema.json` plus an example.

**Contract**

| Member | Content |
|---|---|
| `schemaVersion` | |
| `processingRun` | `processingRunId`, `videoAssetId`, `status: "Completed"`, `completedAtUtc` (a stored fact, not wall-clock), `attestation` (the factory's response object) |
| `video` | `videoAssetId`, `cameraCode`, `sourceSha256`, `sourceSizeBytes`, `durationMs`, `width`, `height`, `frameRateNumerator`, `frameRateDenominator` |
| `profile` | `pipelineProfileSha256`, `evidenceSelectorVersion`, `evidenceScorerVersion`, read from the attestation and **not** re-derived |
| `tracks[]`, by `localTrackNumber` | `id`, `localTrackNumber`, `objectClass`, `startOffsetMs`, `endOffsetMs`, `detectionCount`, `meanConfidence`, `maxConfidence`; Phase-1 `representative` `{videoOffsetMs, boundingBox}`; `objectSubclass`, `objectSubclassVocabulary`, `objectSubclassSource`; `observations[]` `{evidenceRole, evidenceRank, sourceFrameNumber, videoOffsetMs, boundingBox, evidenceSha256, evidenceSizeBytes, evidencePath}`; `trajectorySha256` |

- **Evidence bytes:** copied into `evidence/<sha256>.jpg`, each re-hashed.
- **Identity:** `exportSha256`, the SHA-256 of the export JSON.

The two evidence version members are taken from the profile file named by `pipelineProfileSha256` only after re-hashing it; otherwise the export refuses.

**Snapshot invariant.** One `REPEATABLE READ` read-only transaction reads the run, its job, video asset, source artefact, Tracks, observations and evidence artefacts. Then:
- **Run and job:** the run is `Completed` with `CompletedAtUtc`, and its VisionJob is `Completed`, so finalisation is done. Otherwise `export_run_not_terminal`.
- **Attestation:** built from that same snapshot; a parse failure is `export_attestation_integrity`.
- **Linkage:**
  - every Track's run and video must be the run's (`export_track_run_mismatch`);
  - every observation's Track must be in the set (`export_observation_orphan`);
  - the run's video asset must be the one exported (`export_video_mismatch`).
- **Subclass state:** must be one of the four domain states, and a Stage-3 profile run must have vocabulary and source on every Vehicle Track (`export_subclass_state_invalid`). A run whose attested profile has no vehicle-subclass block is refused (`export_profile_not_stage3`).
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
  - each refusal (*discriminating*: a run still `Finalizing`, a tampered evidence file, a Track re-pointed to another run by SQL, a malformed subclass row inserted after the test drops the subclass check constraints in the test database);
  - only the requested run is exported.

**Windows/offline:** runs on the Development host, writes to E:, no network.

**Qualification:** none. No worker, profile or binding change, and no API surface change.

**Exit:** CI green, and the schema and example validated.

### T2 — Track-label evaluator mode and result (S3.2a-2; fixtures only)

**Files**
- **Changed:** `tools/phase1/evaluate_vehicle_subclass.py`, adding `evaluate_track_labels(labels, adjudication, exports, measured_profile_sha256) -> dict` and a CLI mode `--track-labels <file> --export <file>… --pipeline-profile <file> [--adjudication <file>]`.
- **Refactor:** `_producer`, the per-Track source check and the confusion/metric arithmetic become shared internal functions. The event mode's behaviour and tests are unchanged.

**Join and validation**
- **Truth by identity:** truth joins by `(processingRunId, trackId)` straight from the labels.
- **Exports:** every export is re-hashed against `labels.exportSha256s`, and its embedded attestation feeds the S3.1 producer check, which requires one producer identity across runs.
- **Profile:** the attested profile must equal the measured profile file's SHA-256.
- **Truth set:** the primary label set, with the adjudicated label replacing the primary on overlap items where they disagreed. Both originals stay referenced.

**Refusals**
- an export hash mismatch;
- a run or Track not in the exports (`labels_track_not_exported`);
- a label on a non-Vehicle Track;
- a `videoSourceSha256` differing from the export's;
- a duplicate decision;
- an adjudication referring to items outside the overlap, or to label sets other than the two given;
- a labels `packSha256` that differs from the adjudication's;
- every S3.1 producer and source refusal (mixed producers, profile mismatch, missing or foreign source, missing attestation).

**Result (`vehicle-subclass-measurement-v1`)**

| Member | Content |
|---|---|
| `scope` | the Track-conditional statement (top of this plan), verbatim |
| `producer` | model, checkpoint, config, pipeline profile, runtime profile and variant, qualification, binding, MAVI commit, run ids |
| `inputs` | export hashes, `packSha256`, label-set hash(es), `adjudicationSha256`, measured profile hash, source-video hashes |
| Support | `labelledTracks`, `humanUnknown{reason:count}`, `evaluableTracks` |
| MAVI outcomes | `resolved` and `abstained` over evaluable Tracks; `coverageOverEvaluable` |
| `confusion` | rows = 4 human classes; columns = 4 values + `undetermined` |
| `unknownRow` | MAVI outcomes on human-unknown Tracks, reported and never scored |
| `perClass` | `support`, `predicted`, `correct`, `precision`, `recall` (exact fractions; **`null` when undefined**) and `insufficientSupport` (below the pre-registered minimum, §13) |
| Aggregates | `accuracyOverEvaluable`, `accuracyOverResolved`, `macroRecallOverSupportedClasses`, with `wilson95` intervals for the two accuracies only and `n` stated |
| `errorReferences` | every mismatch and abstention as `{itemId, processingRunId, trackId, label, predicted}` |
| `reliability` | overlap agreement counts and the class-level disagreement matrix |

**Tests**
- hand-computed fixtures;
- every refusal;
- a wrong-profile export;
- input order does not change the bytes;
- `null` for undefined precision (no predictions of a class);
- *mutation-style*: counting human `unknown` as evaluable, counting abstention as correct, or using the primary label where the adjudication differs each changes a pinned result;
- `insufficientSupport` flips exactly at the threshold;
- Wilson values hand-checked;
- the event-mode tests are untouched.

**Exit:** CI green.

### T3 — Prediction-blind sampler (S3.2a-2; fixtures only)

**File:** `tools/stage3/sample_tracks.py`. CLI: `--export <file>… --target N --overlap-fraction 0.2 --seed <text> --out <file>`.

**Blindness, enforced in code.** One function, `_blind(track)`, returns the Track without `objectSubclass*`, `meanConfidence` and `maxConfidence`, and the sampler reads only its output.

**Usable Track.** A Vehicle Track with at least one evidence observation whose bytes verify.
- Detection count is **not** filtered, because it drives the vote's abstention.
- Exclusions are counted by reason.

**Strata (prediction-independent):**
- camera / video;
- apparent scale: representative box area as a fraction of the frame, in terciles;
- duration, in terciles;
- traffic density: concurrent Vehicle Tracks, in terciles;
- lighting proxy: mean luma of the representative crop, in terciles;
- evidence-quality proxy: the Representative's `qualityScore`, in terciles. It is a selector quality signal, not a subclass prediction.

**Selection**
- **Allocation:** proportional to availability, with each camera guaranteed a floor of ⌊target / (2·cameras)⌋.
- **Within a stratum:** the smallest `sha256(seed‖runId‖trackId)` first.

**Overlap for the second reviewer.** About 20 % of the selected items, drawn by `sha256(seed‖"overlap"‖runId‖trackId)` with each camera stratum represented.
- It is chosen in the same run, so it depends neither on predictions nor on any label.

**Refusals:** a bad export hash or schema; a target larger than the usable pool; a duplicate Track.

**Tests**
- determinism;
- *discriminating*: the selection and the overlap are identical when subclass and confidence values are permuted, deleted or replaced; a mutant reading `objectSubclass` fails;
- the camera floor holds;
- excluded counts add up;
- overlap ⊂ selected.

**Exit:** CI green.

### T4 — Labelling pack and static labelling page (S3.2a-2; fixtures only)

**Files**
- **New:** `tools/stage3/build_labeling_pack.py`.
- **New:** `tools/stage3/labeling/index.html`, `labeling.js`, `labeling.css` (static, copied into each pack).
- CLI: `--sample <file> --export <file>… --source <mp4>… --pipeline-profile <file> --seed <text> --reviewer-view primary|overlap --out <new-dir>`.

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
| Inputs | `sampleSha256`, `exportSha256s`, `pipelineProfileSha256`, `evidenceSelectorVersion`, `evidenceScorerVersion` |
| Extraction | decoder identity (`av` and `ffmpeg` versions), `renderRuleVersion: "context-v1"` |
| `items[]` | `{itemId, processingRunId, trackId, videoSourceSha256, views[{kind: crop\|context, evidenceRole, sourceFrameNumber, videoOffsetMs, path, sha256, sizeBytes}]}` |
| `files[]` | every file's path, size and SHA-256 |
| `viewKind` | `primary` or `overlap`; `parentPackSha256` for an overlap pack |

**Identity:** `packSha256` is the SHA-256 of the canonical manifest.

**Reviewer-visible files:** `index.html`, `pack-data.js` (`window.MAVI_PACK = {items:[{itemId, views:[{path, label}]}]}`, which loads from `file://` with no server) and the images. The run→Track mapping lives only in `pack-manifest.json`, which also carries no predictions.

**Page behaviour**
- one item at a time, with previous and next;
- keys `1` car, `2` truck, `3` bus, `4` motorcycle, `0` unknown, then a reason picker;
- an optional note;
- autosave to `localStorage`, keyed by `packSha256` (resume convenience only);
- "Export decisions" downloads `{packSha256, reviewerName, decisions[{itemId, label, unknownReason?, note?}]}`;
- no network calls and no external URLs.

**Refusals (builder):** a source MP4 hash ≠ `videoSourceSha256`; a profile hash mismatch; a frame outside the video; an evidence hash mismatch; an existing output.

**Tests**
- deterministic pack bytes;
- the manifest lists every file exactly once;
- **leak test:** reviewer-visible files contain no `objectSubclass*` key, no subclass value adjacent to an item, no confidence and no Track or run ids;
- the drawn box matches the observation box (pixel check on a synthetic video);
- static page check: no `http(s)://`, no `fetch` or `XMLHttpRequest`;
- primary and overlap packs share Tracks but no `itemId`.

**Windows/offline:** PyAV, Pillow and numpy are already in the venv. The page opens from disk in Edge or Chrome. No dependency change.

**Exit:** CI green.

### T5 — Freeze decisions; adjudicate the overlap (S3.2a-2; fixtures only)

**File:** `tools/stage3/freeze_labels.py`.
- `freeze --pack <dir> --decisions <draft> --reviewer-name <n> --reviewer-role <r> --reviewed-on <YYYY-MM-DD> --out <file>`
- `adjudicate --primary <labels> --overlap <labels> --decisions <file> --adjudicator <n> --out <file>`

**`vehicle-subclass-track-labels-v1`:** `{packSha256, sampleSha256, exportSha256s, reviewer{name, role}, reviewedOn, vocabulary, decisions[{itemId, processingRunId, trackId, videoSourceSha256, label, unknownReason?, note?}]}`, sorted by `(processingRunId, trackId)` and resolved through the pack manifest.

**Freeze refusals**
- the draft's `packSha256` ≠ the pack's;
- an item missing or decided twice;
- an `itemId` not in the pack;
- a vocabulary violation;
- `unknownReason` without `unknown`;
- a note too long or multi-line;
- an empty reviewer;
- an existing output.

**`vehicle-subclass-adjudication-v1`**
- Contents: `{primaryLabelsSha256, overlapLabelsSha256, adjudicator, adjudicatedOn, items[{processingRunId, trackId, primary, overlap, adjudicated}]}`.
- It refuses unless both label sets cover the same Tracks on the overlap, and both are complete.
- Agreed items are carried through unchanged; disagreements need an adjudicated label.

**Immutability.** Artefacts are content-addressed and written once.
- The artefacts used in a recorded measurement are named by hash in §20.
- Corrections produce **new** artefacts and a new measurement record; nothing is edited in place.

**Tests:** every refusal; determinism; the adjudication carry-through; both originals are preserved in the result inputs.

**Exit:** CI green.

### T6 — Measurement runner and requirement comparison (S3.2a-2; fixtures only)

**File:** `tools/stage3/run_subclass_measurement.py`. CLI: `--labels … --adjudication … --export … --pipeline-profile … --requirements <file> --out <new-dir>`.

**What it does**
- verifies every hash;
- runs T2;
- writes `measurement-result.json`;
- writes `requirement-comparison.json`: per criterion, `meets`, `does-not-meet`, `insufficient-support` or `no-requirement`;
- writes `measurement-summary.md`, which is generated tables plus error references pointing into the pack.

**It encodes no mechanism decision.** The comparison only reports criterion status.

**Refusals**
- the requirements file is missing or fails its schema;
- any input hash mismatch;
- an existing output.

**Tests**
- an end-to-end synthetic pipeline: fixture export → sample → packs → scripted primary and overlap drafts → freeze → adjudicate → measure → compare. The output is byte-stable.
- comparison states for a criterion at, below and above its bound, and with null support.

**Exit:** CI green.

### T7 — Corpus verification and release record (S3.2b; ⚠ real release, ⚠ R-5)

See §8. **Exit:** the release record parses, `verify_release_files` passes, and `authorise_release_use(release, ["development", "benchmarking"])` returns no blockers.

### T8 — MP4 derivation (S3.2b; ⚠ real release)

See §8. **File:** `tools/stage3/derive_mp4.py`. **Exit:** every pilot video has a derivation manifest whose output re-derives byte-identically.

### T9 — Import, process, export (S3.2b; ⚠ Development host)

**Steps**
- Import each derived MP4 through the public API, with one MAVI camera per corpus camera.
- Process on the shipped `1.3.0-candidate` with the real Model Pack.
- Export each run with T1.

**Video choice.** A bounded set of 6–10 videos chosen for camera and scene diversity. The choice is not based on any output.

**Exit:** one export per video, all attesting one producer identity and the measured profile.

### T10 — Pilot (S3.2c; ⚠ human)

Run in order:
1. Commit the requirements (§13).
2. Sample 120 Tracks with a 20 % overlap (T3).
3. Build the primary and overlap packs (T4).
4. The primary reviewer labels; the overlap reviewer labels independently.
5. Freeze both, then adjudicate.
6. Measure and compare (T6).
7. Commit the evidence record (§20).

### T11 — Expansion (S3.2d; conditional; ⚠ human)

See §14.

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

**Derivation (T8).**
- **When:** if a video is not ISO-MP4 importable.
- **Remux** (`-c copy` into MP4) when the stream codec is decodable by the worker and MP4-compatible.
- **Otherwise transcode** with a pinned recipe: offline-kit ffmpeg, `-c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -threads 1 -an -movflags +faststart`.
- **Manifest** `vehicle-subclass-derivation-v1` per video: `{sourceSha256, sourceMedia(probe), mode: remux|transcode, ffmpegVersion, ffmpegSha256, args, outputSha256, outputMedia(probe)}`.
- **Determinism:** the first derivation is run twice and must be byte-identical.
- **Honesty:** a transcoded file is never described as identical to its source. **The derived MP4 is the measurement input.** Its hash is the export's `video.sourceSha256`, and the chain runs release → derivation → import → export.
- **Refusals:** a source not in the release record; an unknown codec; non-determinism; an existing output.

**If CityFlow is unsuitable** (no access, restrictive terms, unusable media, or too sparse for important classes after the pilot), the plan records why. One supplement is then proposed for owner approval; none is added automatically. Candidates:
- BDD100K: a moving dashcam, so a weak proxy for fixed CCTV;
- UA-DETRAC: fixed traffic cameras; availability and terms unverified.

## 9. Sampling

As T3. Before labels exist, stratification uses only prediction-independent metadata. No class balance is claimed, because no trusted independent type label exists.

After the pilot, the **human** class support is inspected. Rare-class supplementation (§14) is decided only then, and only by sampling more footage, never by selecting on MAVI predictions.

## 10. Labelling workflow

**Roles**
- **Primary reviewer:** R-4 (Aarav).
- **Overlap reviewer:** an independent annotator (Savita), to be confirmed.

**Independence**
- Each works from their own pack.
- The overlap pack hides the primary's decisions and all predictions.
- Adjudication happens only after both have frozen.

**What the unknown reasons diagnose:**
- `occluded` and `too-small`: imagery;
- `mixed-track`: tracking (an identity switch);
- `not-a-vehicle`: invalid detections;
- `ambiguous-type`: taxonomy (for example pickup vs truck);
- `other` with a note: anything else.

The result tallies them separately (`humanUnknown`). MAVI's outcomes on unknown Tracks are reported in `unknownRow`, so tracking or detection failures are visible without being scored as subclass errors.

## 11. Ground-truth freeze

As T5. Labels bind to the exact pack the reviewer used (`packSha256`, which covers every viewed image's hash), the sample, the exports, the reviewer and the declared review date. Artefacts used in a recorded measurement are immutable; corrections create new artefacts.

## 12. Evaluation

As T2 and T6. Reported metrics are exact fractions with explicit denominators; undefined metrics are `null`. Wilson intervals are given only for the two aggregate accuracies, with `n`. No per-class confidence claims are made beyond the support flags.

**Error review** (diagnostic, after freeze): `errorReferences` index into the pack, so a reviewer can look at mismatches with predictions shown.

## 13. Pre-registered decision requirements

**Artefact.** `vehicle-subclass-requirements-v1` is committed to the repository (`docs/qualification/stage3/s3-2-subclass-requirements.json`) **before** the pilot result exists, and its hash is recorded in §20. It contains three distinct parts:

1. **Operational requirement:** per-class minimum precision and recall, and minimum coverage, if the owner can justify them. Each value may be `null` ("no defensible requirement yet").
2. **Minimum evidence support:** the evaluable support per class below which no per-class conclusion is drawn. Suggested at 30, as a proposal for the owner to decide.
3. **Insufficient-support outcome:** a class below the minimum gets `insufficient-support`, and no pass or fail is permitted for it.

**Ordering is enforced:**
- the runner refuses to compare without a requirements file;
- §20 records the requirements commit, which must predate the result's creation date in the evidence record.

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

**How expansion works**
- It reuses T3–T6 with a new seed, excluding labelled Tracks.
- It processes more corpus videos if needed (T8–T9).
- It produces new artefacts and a new measurement record.

The expansion decision, or the decision not to expand, is recorded in §20. S3.2 may finish after the pilot.

**Decision directions** the evidence informs; none is encoded in tooling:
- detector-native looks adequate for continued Stage-3 work;
- the evidence is insufficient and more data is needed;
- detector-native has specific deficiencies needing development;
- a learned classifier should be evaluated in a later slice.

## 15. Provenance and rights

**One governance path.** The release record, licence evidence, file hashes, purpose authorisation and exposure all use the existing release machinery (`mavi-attribute-dataset-release-v1`, `authorise_release_use`). No parallel mechanism.

**Requested use:** `development` and `benchmarking`, operation `evaluate` only.

**Blocked until R-5 decides.** With `determination: null`, `authorise_release_use` refuses, and T8 refuses to run without a passing authorisation.

**Never frozen qualification.** Public origin never confers frozen-qualification eligibility (`provenance.parse_purposes` refuses `frozen-qualification` for public origin). Every S3.2 artefact carries `purpose: development-evaluation`, and the result scope says it is not qualification evidence.

**Media stays out of Git.** No CityFlow media, frames or crops are committed. Only hashes and metadata go in §20.

## 16. Qualification impact

**None.** No worker, pipeline profile, binding, Model Pack, runtime, qualification record or completion contract change.

The T1 attestation-factory extraction is behaviour-preserving and proven by the existing attestation API tests. Measurements are development evidence only.

## 17. Failure modes and refusals (summary)

| Stage | Refused when |
|---|---|
| Export | run or job not terminal; attestation integrity; Track/run/video linkage; orphan observation; malformed subclass state; non-Stage-3 profile; evidence or source bytes changed; missing artefacts |
| Sample | bad export hash or schema; target exceeds usable pool; duplicate Track |
| Pack | source MP4, profile, evidence or frame mismatch |
| Freeze/adjudicate | pack identity altered; missing or duplicate item; item outside the pack; vocabulary violation; reason without `unknown`; note invalid; reviewer missing; overlap coverage mismatch |
| Evaluate | export hash; label for a non-exported or non-Vehicle Track; video hash mismatch; duplicates; mixed producers; profile mismatch; missing or foreign subclass source; missing attestation |
| Run/compare | missing requirements; any input hash mismatch |
| Derivation | source not in the release; unknown codec; non-deterministic output |
| Release use | `authorise_release_use` blockers (R-5 absent) |

Every refusal exits with code 2, writes nothing, and gives a stable code.

## 18. Windows and offline handling

- **Offline:** all tools run offline on the Windows Development host.
  - The .NET tool needs the existing SDK and runtime.
  - The Python tools use only packages already in the repo venv (PyAV, Pillow, numpy, jsonschema).
  - Media probing and derivation use the offline-kit ffprobe/ffmpeg.
- **Storage:** data under `E:\MAVI-Controlled\…\S3\`, scratch under `E:\MAVI-Working`.
- **Labelling page:** opens from disk with no server.
- **Paths:** stored relative and forward-slashed inside artefacts, and never absolute.
- **Line endings:** canonical JSON is written with LF.
- **Dependencies:** `offline-dependency-policy-v1.json` is unchanged.

## 19. Risks and open questions

**Human decisions and blockers (not solvable by code)**
1. CityFlow access request and acceptance of terms (owner).
2. Licence/terms review and the **R-5 determination** (R-5; this plan makes no legal judgement).
3. The pre-registered requirements (§13), including whether any operational threshold is defensible yet.
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
   - the sampler blindness test;
   - the pack leak test;
   - evaluator mutation pins;
   - the byte-stable end-to-end synthetic pipeline.
2. **A release record** with verified hashes, terms evidence, exposure and the R-5 determination; and derivation manifests that re-derive byte-identically.
3. **A committed requirements file,** predating the result.
4. **A recorded pilot.** Every input hash recorded (release, derivations, exports, sample, packs, label sets, adjudication, requirements, result), plus:
   - the requirement-comparison table;
   - support per class, with insufficient-support classes named;
   - reviewer agreement;
   - a single attested producer identity and profile hash.
5. **A recorded expansion decision,** with an expansion measurement if one is undertaken.
6. **Nothing exposed or added:** no API, search, UI, Production, classifier or tuning change.

*Evidence record (filled during S3.2c/d): artefact hashes, the summary tables and the decisions go here. Data stays outside Git.*
