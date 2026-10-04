# Stage 3 S3.2d-1 — the MAVI Benchmark Harness (implementation-ready plan)

**Status:** planning only; nothing here is implemented. Baseline `main@906fc8a7fcdfebac646ecedf503a77cb34fecc6a` (PR #159 merged).
**Date:** 2026-10-04
**Governing:** ADR-017 (benchmark-first Development; §4 mappings, §6 association, §7 admissibility, §11 harness shape); ADR-016 (detector-native source, unchanged); ADR-015 (public-first Development, protected final qualification); the two current roadmaps; the S3.2 plan §14 amendment; the Stage-3 register (`docs/reviews/2026-10-03-stage3-vehicle-subclass-acceptance.md`, the only exit authority; this plan closes nothing). Operating principles 5a, 6a and 6b apply: benchmark first, the lightest evidence process appropriate to a Development claim, few authoritative documents.
**Register rows served:** H2 (framework and tooling) is what this plan builds; H3 (primary benchmark measurement) is the first consumer, planned in §12 and executed in a later task; H4 and H5 are later.

## 1. Objective and non-goals

**Objective.** A reusable, deterministic benchmark harness that evaluates a MAVI capability against an existing labelled research dataset without new human labels: a shared envelope for identity and provenance, dataset adapters, capability-specific ground truth, prediction-independent association of ground-truth tracks to MAVI Tracks, a capability evaluator, and a reproducible result. Stage-3 vehicle subclass is the first consumer.

**Non-goals.** No change to the detector, Model Pack, pipeline profile (`1.3.0-candidate`, `afb03b6c…`), thresholds (`minShare` 0.6, `minMatchedDetections` 3), vocabulary or stored Track values. No API, search or UI exposure. No change to T1–T10 tooling semantics or T10 evidence. No dataset download in the planning task. No universal ground-truth schema. No qualification claim: every result is Development or reference evidence (ADR-017 §8–§9).

## 2. Repository facts the design rests on (read, not assumed)

- **T1 export** (`vehicle-subclass-measurement-export-v1`, `tools/dotnet/Mavi.MeasurementExport`): per run, `video` (`videoAssetId`, `cameraCode`, `sourceSha256`, `width`, `height`, `frameRateNumerator/Denominator`, `durationMs`), `profile.pipelineProfileSha256`, the run `attestation` (producer identity: `maviCommit`, `modelPackId`, `runtimePackId`, `pipelineProfileSha256`, `checkpointSha256`, `componentBindingSha256`, device, …), and `tracks[]` with `id`, `objectClass`, `startOffsetMs`, `endOffsetMs`, `detectionCount`, `objectSubclass` (nullable), `objectSubclassSource`, `objectSubclassVocabulary`, `trajectorySha256`, and `observations[]` (at most four: `sourceFrameNumber`, `videoOffsetMs`, normalised `boundingBox {x, y, width, height}`, evidence crop hash). The exporter copies crops, not trajectories.
- **Trajectory artefact** (`src/vision/mavi_vision/video/trajectory.py`, format v1): msgpack `{"v": 1, "points": [[offset_ms, center_x, center_y], …]}` with strictly increasing offsets and normalised centres in [0, 1]. **It carries no box size.** It is sealed at finalization under the evidence root as `evidence/{jobId}/attempt-NNNN/trajectories/{trackId}-{sha256}.msgpack` (`EvidenceSealingPlan.AcceptedEvidenceKey`), and the export's `trajectorySha256` names it. The export does not carry the vision job id, so the harness locates a trajectory by its hash (`*-{sha256}.msgpack` under the evidence root) and verifies the bytes.
- **Consequence for association.** Frame-level IoU between MAVI and ground truth is not available from stored data. Boxes exist only at the ≤ 4 observation frames. Association therefore uses per-frame **centre containment** (MAVI trajectory centre inside the ground-truth box) and normalised centre distance, with observation-box IoU as a spot check (§7). Storing per-point boxes would be a product change (trajectory v2); it is recorded as a possible later improvement, not required for S3.2d-1.
- **Existing helpers** (`tools/stage3/artefacts.py`): canonical JSON, SHA-256, `write_once`, `OutputDirectory`, schema `validate`, `read_artefact`, `Export` (export reading and integrity checks), `load_exports` (duplicate run/video/source refusal), `git_binding`. `tools/phase1/evaluate_vehicle_subclass.py`: attestation validation (`_validate_attestation`), single-producer check (`_producer`), per-Track outcome (`_track_outcome`: subclass or `undetermined`), exact-fraction metrics. `tools/stage3/run_subclass_measurement.py`: `status()` with the support-floor-first ordering. `tools/stage3/ingest_source_pool.py`: a stdlib `Api` client for `GET/POST /api/cameras`, `POST /api/videos/import` (multipart), `POST /api/videos/{id}/process`, `GET /api/videos/{id}/processing`, and the export command invocation. `tools/stage3/media_tools.py` and `derive_mp4.py`: verified FFmpeg pack and MP4 derivation. `tools/qualification/attributes/datasets/mapping.py`: an existing label-mapping shape (`parse_mapping`, `mapping_sha256`, `apply_mapping`) for the S2c still-image datasets.
- **Dependencies.** `msgpack` is a vision-runtime dependency (declared in `config/dependencies/offline-dependency-policy-v1.json`) and is present in the repository venv; the tools surface (`tools/requirements.txt`) does not declare it. Reading trajectories from the harness adds it to the tools surface (Slice 2; AGENTS dependency rule). `scipy` is already a tools dependency; the association does not need it (§7.5).
- **Catalogue practice.** T9 ran on a fresh, dedicated Development catalogue and media store with process-scope configuration overrides (register F1). Benchmark runs follow the same practice: one dedicated catalogue and media store per dataset release, never the ordinary Development catalogue.
- **Store layout convention.** Stage-3 evidence lives under the controlled-store root `E:\MAVI-Controlled` with store-relative citations. Benchmarks use `E:\MAVI-Controlled\Benchmarks\<dataset>\<release>\` (§10). Dataset bytes never enter Git.

## 3. Architecture

```
dataset release ──adapter──▶ shared envelope (identity, release, split, provenance/admissibility, mappings,
                             exposure, MAVI execution identity, reproducibility)
                             + capability-specific canonical ground truth
                             (vehicle tracking/subclass: sequence, frame, time, box, native track id, native class)
        ──MAVI execution (import → process → T1 export; trajectories read by hash)──▶ MAVI Tracks
        ──capability-specific association (geometry and time only)──▶ matched / fragment / ambiguous / unmatched
        ──capability evaluator──▶ scope A: end-to-end coverage; scope B: Track-conditional subclass quality
        ──result + evidence (canonical, hashed, write-once)
```

**Shared core owns:** dataset and release identity; split identity; source and access identity; provenance and research-use status (ADR-017 §7, release-level); the native-taxonomy declaration and per-class mappings (§6); exposure metadata (§13); MAVI execution identity (producer from attestations, profile hash, export and trajectory hashes); run identity; the result envelope and its deterministic hash; reproducibility metadata (adapter, mapping, association-policy and runner identities). **Capability modules own:** the ground-truth record shape they need, the association geometry, the evaluator and the result body. Nothing capability-specific sits in the core; nothing dataset-specific sits in the evaluator.

## 4. Module and file layout

```
tools/benchmarks/
  __init__.py
  core/
    envelope.py        # BenchmarkRun envelope: build, hash, write-once; no capability fields
    descriptor.py      # dataset release descriptor + admissibility record (schema benchmark-dataset-release-v1)
    mapping.py         # per-native-class mapping model (schema benchmark-class-mapping-v1)
    identity.py        # deterministic hashing of policies/configs; re-exports canonical helpers
    mavi.py            # read exports (artefacts.Export), locate+verify trajectories, producer identity
  datasets/
    __init__.py        # DatasetAdapter protocol
    synthetic.py       # fixture adapter (tests only, deterministic generator)
    bdd100k_mot.py     # Slice 4: first real adapter (Scalabel box-tracking labels)
  capabilities/
    vehicle_tracks/
      ground_truth.py  # GtTrack / GtBox records; adapter output contract for tracking capabilities
      association.py   # containment-based GT↔MAVI association; policy dataclass; no class fields
    vehicle_subclass/
      evaluate.py      # scope A coverage + scope B Track-conditional classification
      report.py        # markdown summary (generated tables only)
  cli.py               # describe | prepare | execute | evaluate (thin)
  tests/
    fixtures/ …        # synthetic sequences, tiny MP4s via media_tools, golden hashes
    test_descriptor.py test_mapping.py test_association.py test_evaluate.py test_synthetic_e2e.py test_cli.py
contracts/schemas/benchmark-dataset-release-v1.schema.json  (+ example)
contracts/schemas/benchmark-class-mapping-v1.schema.json    (+ example)
contracts/schemas/benchmark-association-v1.schema.json      (+ example)
contracts/schemas/benchmark-vehicle-subclass-result-v1.schema.json (+ example)
```

`tools/benchmarks` is a new top-level tool package, like `tools/stage3`, so the harness is not Stage-3-local. The capability package is `vehicle_tracks` (association for any tracked-object capability) plus `vehicle_subclass` (the first evaluator); person attributes or ANPR would add their own `capabilities/<name>/` with their own truth and evaluator and reuse `core/`.

**Reuse decisions.**
- *Reuse as-is:* `artefacts.Export`, `load_exports`, `validate`, `read_artefact`, `canonical_json`, `sha256_hex`, `write_once`, `OutputDirectory`, `media_tools` pack verification, `run_subclass_measurement.status` semantics (imported, not copied), `evaluate_vehicle_subclass._track_outcome` and `_producer`.
- *Extract to a shared helper (Slice 1, behaviour-preserving, tested byte-identical):* the stdlib `Api` client from `ingest_source_pool.py` into `tools/stage3/mavi_api.py`, re-exported by `ingest_source_pool` so T9's tests and semantics are untouched.
- *Leave untouched:* T3–T6 (sampler, packs, freeze, runner), T7–T9 pool/map/release semantics, all Stage-3 evidence. The harness does not reuse T3–T6 abstractions: their unit is a human-labelled Track; the harness's unit is a GT track associated to a MAVI Track.
- *New:* everything under `tools/benchmarks/` and the four contracts. An image-sequence-to-MP4 encoder (BDD100K and VisDrone ship labelled frames as JPEG sequences) is new code in `datasets/` built on `media_tools` (pinned FFmpeg arguments, deterministic output, recorded in the envelope).

## 5. Contracts

All artefacts follow the Stage-3 rules: canonical JSON, identity = SHA-256 of canonical bytes, write-once, no wall-clock field inside anything hashed (timestamps, where kept, live only in an unhashed sidecar or the run log).

**`benchmark-dataset-release-v1`** (release-level provenance and admissibility; ADR-017 §7): `schemaVersion`; `datasetId` (slug); `datasetName`; `release` (exact version or edition string); `task` (`box-tracking`, `detection`, …); `source` {`kind`: `official` | `author-repository` | `institutional-archive` | `research-mirror` | `challenge-archive`; `url`; `retrievedOn`; `credibilityBasis` (required when kind ≠ `official`)}; `access` {`mechanism`: `direct` | `registration` | `agreement` | `request`; `preconditions[]`}; `intendedUse` (`development-benchmarking`); `researchUse` {`status`: `RESEARCH-ADMISSIBLE` | `RESEARCH-UNCERTAIN` | `BLOCKED`; `basis`; `termsReference`; `redistribution`: `not-permitted-by-default`}; `splits[]` {`name`, `labelled`: bool, `role`}; `nativeTaxonomy[]` {`code`, `name`, `definition`}; `frameTime` {`kind`: `index-at-fps` | `per-frame-timestamp`; `fpsNumerator`, `fpsDenominator`}; `manifest` {`kind`: `file-hashes` | `archive-hashes`; `entries[]` {`path`, `sizeBytes`, `sha256`}} (written after acquisition; may be empty before); `exposure` (§13). One record per release; a per-file review is not modelled, by design.

**`benchmark-class-mapping-v1`** (§6): `schemaVersion`; `datasetId`; `release`; `capability` (`mavi-vehicle-subclass-v1`); `mappings[]` {`nativeClass`, `maviClass` | null, `kind`: `exact` | `subset` | `unsupported`, `reason`, `evaluation`: `scored` | `precision-only` | `excluded`}. Identity = hash of canonical bytes, recorded in every result.

**`benchmark-association-v1`** (§7 output): envelope reference; `policy` {`version`, `timeToleranceMs`, `minOverlapFrames`, `minContainment`, `ambiguityMargin`, `fragmentContainment`}; `sequences[]` {`sequenceId`, `videoAssetId`, `processingRunId`, `pairs[]` {`gtTrackId`, `maviTrackId`, `overlapFrames`, `containment`, `meanNormalisedDistance`, `gtCoverage`, `maviCoverage`, `spotCheckIoU[]`}, `ambiguousGt[]`, `unmatchedGt[]`, `fragmentMavi[]`, `unmatchedMavi[]`, `ignoredMavi[]`}. **No class, subclass or confidence field anywhere in this artefact.**

**`benchmark-vehicle-subclass-result-v1`** (§8): the envelope; `associationSha256`; `mappingSha256`; `scopeA` (coverage) and `scopeB` (Track-conditional classification), each with its own `scope` statement; per-sequence breakdown; `requirements` reference where the support floor is taken from the registered requirements (`ca28702f…`).

The envelope embedded in the association and result artefacts: `benchmarkRunId` (hash of the inputs below), `dataset` {`datasetId`, `release`, `split`, `descriptorSha256`}, `sequences[]` (ids and derived-video hashes), `mavi` {`maviCommit`, `pipelineProfileSha256`, `producer` (the single attested producer), `exportSha256s[]`, `trajectorySha256s[]`}, `tooling` {`adapterId`, `adapterVersion`, `mappingSha256`, `associationPolicySha256`, `runnerVersion`}, `exposure` (§13).

## 6. Mapping semantics

Per native class, never per dataset (ADR-017 §4; AGENTS item 3). Kinds:
- `exact`: the native definition coincides with one MAVI class under the labelling guide (`docs/qualification/stage3/s3-2-labeling-guide.md`, the reference for the four MAVI classes). `evaluation: scored`: counts in precision and recall of that class.
- `subset`: the native class lies entirely within one MAVI class but does not cover it (for example `sedan` → `car`). `evaluation: precision-only`: a MAVI prediction of that class on such a track is correct, and the track counts in that class's precision denominator, but the class's recall is not claimed from this dataset unless an `exact` class also exists for it.
- `unsupported`: no MAVI class fits without assumption (`van`: the guide splits vans by body; `others`; `tricycle`; `rider`), or the class is outside the capability. `evaluation: excluded` from classification scoring, but **always present** in coverage (scope A) and in the "excluded native classes" counts of scope B.

Rules the evaluator enforces: a MAVI class with no `exact` native class in the dataset gets `recall: not-in-dataset`, never a number; macro averages run only over classes present with an `exact` mapping and adequate support; a mapping file naming a native class the adapter never emits, or omitting one it does emit, is refused (`mapping_incomplete`); kinds are declared, never inferred. The dataset-level coverage summary (`full`/`partial`/`none`, as in the capability matrix) is derived for reporting and is not an input.

**Worked example** (dataset classes `car`, `bus`, `van`, `other`; MAVI `car | truck | bus | motorcycle`): `car → car exact`, `bus → bus exact`, `van → unsupported` (body not resolved), `other → unsupported`. Scope B scores car and bus precision and recall; truck and motorcycle are `not-in-dataset`; van and other tracks appear in coverage and in the excluded counts; a MAVI `truck` prediction on a `van` track is neither right nor wrong, it is excluded.

## 7. GT ↔ MAVI Track association (`capabilities/vehicle_tracks/association.py`)

**Inputs** (geometry and time only): per sequence, GT tracks as `{gtTrackId, frames[] {frameIndex, timeMs, box (normalised x, y, w, h), ignore: bool}}` with class **stripped before** the association call (the ground-truth loader passes a projection that has no class field; a test asserts the projection's field set); MAVI Tracks as `{maviTrackId, points[] {offsetMs, cx, cy}, observations[] {offsetMs, box}}` with subclass and confidence **absent** from the projection. Ignore regions (VisDrone category 0 / score 0, KITTI `DontCare`, BDD100K `crowd`) are passed as boxes, not tracks.

**7.1 Time alignment.** The adapter declares `frameTime`. Where the derived MP4 is encoded from exactly the labelled frames at the dataset's labelled rate (the default for 5 Hz BDD100K MOT and VisDrone sequences), GT frame *k* has `timeMs = round(k × 1000 × fpsDen / fpsNum)` and MAVI offsets coincide up to encoder timestamp rounding; the policy tolerance is `timeToleranceMs = half the labelled frame interval` (100 ms at 5 Hz). Where the derived video has more frames than the labels (an original 30 fps clip with 5 Hz labels), the same rule picks the nearest MAVI point within tolerance; frames without GT are ignored. Frame rate differences are therefore handled by time, never by frame-index arithmetic across rates.

**7.2 Per-frame evidence.** For each GT frame with a MAVI point within tolerance: `inside` = the MAVI centre lies within the GT box; `d` = Euclidean distance between the MAVI centre and the GT box centre, divided by the GT box diagonal (both normalised). Box conventions are converted by the adapter (pixel `x1 y1 x2 y2` or `left top width height` to normalised `x y w h` using the declared frame size); the adapter is tested on that conversion.

**7.3 Pair score.** For a candidate pair: `overlapFrames` = GT frames with an aligned MAVI point; `containment` = inside ÷ overlapFrames; `meanNormalisedDistance`; `gtCoverage` = overlapFrames ÷ GT frames; `maviCoverage` = overlapFrames ÷ MAVI points within the GT's time span. Candidates are generated only for pairs whose time spans overlap (interval sort, §7.5).

**7.4 Assignment and outcomes** (policy v1 defaults; chosen from geometry and synthetic fixtures, §7.6):
- Eligible pair: `overlapFrames ≥ minOverlapFrames (3)` and `containment ≥ minContainment (0.5)`.
- Order eligible pairs by (`containment` desc, `overlapFrames` desc, `meanNormalisedDistance` asc, `gtTrackId`, `maviTrackId`): fully deterministic.
- Greedy one-to-one: take pairs in order, skipping any whose GT or MAVI Track is already assigned.
- Ambiguity: before accepting a pair for GT *g*, if another unassigned eligible MAVI Track *m′* has `containment ≥ best − ambiguityMargin (0.1)` and `overlapFrames ≥ minOverlapFrames`, *g* is `ambiguous` and neither candidate is assigned to it (both stay available for other GT). Symmetric rule for a MAVI Track with two near-equal GT candidates (crossing objects).
- After assignment: an unassigned MAVI Track with `containment ≥ fragmentContainment (0.5)` against an **assigned** GT is `fragmentMavi` (MAVI fragmentation; coverage scope only); an unassigned GT whose frames are mostly covered (`gtCoverage ≥ 0.5`) by an **assigned** MAVI Track is `mergedGt` (MAVI merged two identities); an unassigned MAVI Track whose centres fall inside ignore boxes for ≥ 50 % of its points is `ignoredMavi`; the rest are `unmatchedGt` / `unmatchedMavi`.
- Spot check: for each assigned pair, IoU between each MAVI observation box and the GT box at the aligned frame; reported as `spotCheckIoU[]`. Diagnostic only in v1; it is not used to assign or reject, so the assignment depends on nothing but trajectory geometry.
- **Class leakage protection:** the association module imports nothing from the subclass evaluator, its input projections have no class or confidence field (asserted by test), and the mutation test in §9 proves that changing every MAVI subclass and every native class leaves the association artefact byte-identical.

**7.5 Method choice.** Compared: (a) greedy best-score matching; (b) Hungarian global assignment on a containment matrix; (c) frame-level matching accumulated to track level; (d) track-level overlap matrix then assignment. (c) is what §7.2–7.3 compute, so the real choice is between (a) and (b) on the pair-score matrix. Hungarian maximises the *sum* of scores and can accept a weak pair to free a strong one, which is hard to explain in an evidence report and interacts badly with explicit ambiguity rejection; greedy with the ambiguity rule accepts only pairs that are individually strong and unambiguous, which is what a reviewer must be able to verify by hand from the artefact. **Choice: greedy with explicit ambiguity rejection** (a). Complexity: candidate generation by sorting both track sets by start time and sweeping, O((G + M) log(G + M) + P) for P temporally overlapping pairs; scoring O(P × F) for F aligned frames per pair; assignment O(P log P). Hungarian (O(n³)) is kept as a documented alternative if ambiguity rates in real data prove greedy inadequate; switching would be a new policy version, recorded in the envelope.

**7.6 Threshold provenance.** `minContainment` 0.5 (the MAVI centre inside the GT box at least half of the overlapping frames), `minOverlapFrames` 3, `ambiguityMargin` 0.1, `fragmentContainment` 0.5 are set from geometric reasoning and validated on the synthetic fixtures of §9 (crossing, fragments, jitter). They are never chosen from benchmark subclass outcomes. Any change is a new policy version with its own fixtures.

**Limitation stated in every association artefact:** MAVI trajectories are centre points; containment is a necessary, not sufficient, condition for the same physical object, so association errors are possible for objects whose boxes overlap for long periods (platoons, queues). The ambiguity rule rejects the symmetric cases; the spot check exposes the rest. A trajectory format carrying boxes would strengthen this and is recorded as a possible product change (not for S3.2d-1).

## 8. Evaluation semantics (`capabilities/vehicle_subclass/evaluate.py`)

Two scopes, two sections, two scope statements (S3.2 plan §2 and §14).

**Scope A — end-to-end association coverage (detection and tracking; not subclass accuracy).** Per sequence and overall: GT tracks total, eligible (non-ignored), assigned, ambiguous, merged, unmatched; MAVI Tracks total, assigned, fragment, ignored, unmatched; association rate = assigned ÷ eligible GT; per native class (including `unsupported` ones) the same counts, so a class MAVI never tracks is visible here.

**Scope B — Track-conditional subclass quality (on assigned pairs only).** Each assigned pair yields (native class, mapping, MAVI outcome) where the MAVI outcome is `_track_outcome`: a MAVI class or `undetermined`. Then: confusion over MAVI classes for `exact` GT; `precision-only` contributions for `subset` GT; `excluded` counts for `unsupported` GT; per class precision, recall, support (exact-GT count), `undetermined` share (abstention coverage), accuracy over resolved and over evaluable; `not-in-dataset` for classes without exact GT; `insufficient-support` below the registered floor of 30 (`run_subclass_measurement.status` ordering; the floor is read from the registered requirements and recorded by hash, so benchmark and pilot speak the same language; no operational pass or fail is claimed, as every operational minimum is `null`). Macro figures are computed only over classes with exact GT and adequate support, and the result lists which classes they cover.

**Partial-taxonomy guarantees:** no recall for an absent class; no coercion of `unsupported` classes; `subset` never inflates recall; excluded counts always visible; dataset coverage summary derived and labelled.

## 9. Tests (discriminating, deterministic)

- **Adapter (synthetic and BDD100K):** pixel→normalised conversion for both box conventions; sequence and frame discovery; stable native track ids across frames; native classes emitted exactly as declared; ignore/crowd/DontCare handling; malformed label refusal (`adapter_label_invalid`); frame-time computation at 5 Hz and 30 Hz.
- **Mapping:** exact, subset, unsupported semantics; unknown native class refusal; missing native class refusal; hash stability; the dataset summary is derived, not read.
- **Association (synthetic trajectories):** perfect one-to-one; partial temporal overlap above and below `minOverlapFrames`; two MAVI Tracks for one GT (one assigned, one `fragmentMavi`); one MAVI Track spanning two GT identities (`mergedGt`); crossing objects with a symmetric tie (`ambiguous`); identical scores resolved by the deterministic order; low-containment rejection; unmatched GT and MAVI; ignore-region MAVI Track; time tolerance at the boundary; **mutation:** every MAVI subclass flipped and every native class permuted → association bytes identical; a static test that the association input projections and output schema contain no class or confidence field.
- **Evaluator:** exact mapping confusion; subset precision-only behaviour; unsupported exclusion with visible counts; `undetermined` handling; per-class support and `insufficient-support`; `not-in-dataset` recall; macro coverage list; the worked example of §6 as a fixture.
- **Envelope and determinism:** two runs over the same inputs are byte-identical for every artefact; hashes stable across Windows and Linux (LF, canonical JSON); a changed mapping or policy changes `benchmarkRunId`.
- **Synthetic end-to-end:** a tiny synthetic dataset (two sequences, six GT tracks, generated frames encoded to MP4 by the pinned FFmpeg pack) → synthetic exports and trajectories written by the fixture → association → evaluation → report, with golden hashes pinned; the mutation test runs over this pipeline too.
- **CLI:** refusal codes and exit status; write-once refusal; resume semantics (§11).
Tests run under `tools/benchmarks/tests` in the Quality Gate alongside `tools/stage3/tests`.

## 10. Store layout (Development, outside Git)

```
E:\MAVI-Controlled\Benchmarks\<datasetId>\<release>\
  source\          downloaded archives or frames, as received (hashed in the descriptor manifest)
  annotations\     native labels, as received
  derived\         per-sequence MP4 (pinned FFmpeg args), derivation manifest with hashes
  mavi\            per-sequence T1 export directories + copied, hash-verified trajectory msgpacks
  results\<benchmarkRunId>\   association, result, report (write-once)
```
Git holds: adapters, schemas and examples, tests, mapping files, release descriptors (metadata and hashes only), and benchmark summaries cited by hash in the register. No frames, videos, crops or trajectories.

## 11. CLI flow (`python -m tools.benchmarks.cli …`; Windows-first)

1. `describe --descriptor <release.json>`: validate the descriptor and mapping, print status and preconditions; refuse `BLOCKED`; with `--manifest-root`, compute and freeze the source manifest (write-once).
2. `prepare --descriptor … --split val --out <derived>`: adapter discovers sequences; encodes derived MP4s with the verified FFmpeg pack; writes ground truth per sequence (canonical) and a derivation manifest; refuses an existing output.
3. `execute --derived … --api http://localhost:<port> --journal … --export-exe …`: the T9 pattern (shared `Api`): fresh-catalogue check, one camera per sequence, import, process, journal before polling, T1 export per run, then locate and copy each `trajectorySha256` from the evidence root (`--evidence-root`), verifying bytes. Resumable from the journal only within the same catalogue; refuses pre-existing assets.
4. `evaluate --derived … --mavi … --mapping … --policy … --out <results/run>`: association then evaluation, both scopes, report; everything write-once; `benchmarkRunId` printed.
Refusals use the `S32Error`-style `refused <code>` convention. `prepare` and `evaluate` are deterministic and regenerable into a new output directory; `execute` is journalled like T9. The subclass predictions are first read by `evaluate`'s scope-B step, after association has been written; `associate` is not a separate command, but the association artefact is written and hashed before scope B runs, so the mutation test can prove independence on the artefact.

## 12. First benchmark execution path (S3.2d-2; planned, not executed)

**Verified on 2026-10-04 (sources in the capability matrix).** BDD100K box tracking ("MOT 2020", `mot_20`): labels are a 115 MB Scalabel package covering train and val; the tracking videos are "a subset of the 100K videos, but the videos are resampled to 5Hz from 30Hz"; box tracking uses 8 classes `pedestrian, rider, car, truck, bus, train, motorcycle, bicycle`; download at `dl.cv.ethz.ch/bdd100k/data/` after agreeing to the BDD100K licence, which permits "educational, research, and not-for-profit purposes, without fee". Unverified: the exact video and track counts per split, image resolution (believed 1280×720), the `crowd` attribute semantics, and whether frame JPEGs or 5 Hz videos are shipped for `images/track`.

**Recommendation:** BDD100K MOT 2020 **val** split (public labels) as the primary benchmark (H3), with mapping `car → car exact`, `truck → truck exact` (verify that BDD100K `truck` includes pickups as the guide does; if not, `subset`), `bus → bus exact`, `motorcycle → motorcycle exact` (verify scooter inclusion), `pedestrian, rider, bicycle, train → unsupported`. Coverage potentially `full`. Research-use status: RESEARCH-ADMISSIBLE on the quoted licence text, confirmed at acquisition when the full licence is accepted. Role: primary taxonomy benchmark; domain caveat: moving dashcam, United States. Exposure: RTMDet-m is trained on COCO; no MAVI component is known to have used BDD100K; recorded as "no known exposure; possible indirect overlap not identified" (§13).

**Frame-rate decision (technical, decided here):** process the 5 Hz labelled-frame sequence encoded to MP4 at 5 fps, so GT and MAVI frames coincide exactly and association needs no interpolation; record that MAVI's tracker ran at 5 fps, below its usual rate, as a caveat on both scopes. If the 30 fps source clips are obtainable for the same videos, a second run at 30 fps with 5 Hz GT alignment (§7.1) is a diagnostic comparison, not a second primary measurement.

**Acquisition preconditions (owner or operator action, not automated):** accept the BDD100K licence on the portal; download `mot_20` labels and the `images/track` val package to `source\`; freeze the manifest. No bypass of the agreement.

**Decision gate if verification changes the picture:** (1) confirm the 8-class list and `truck`/`motorcycle` definitions from the Scalabel label specification; (2) confirm the val split's video count and that frames or videos are what is shipped; (3) read the full licence at acceptance. Fallback if BDD100K cannot be acquired: VisDrone MOT (aerial; `car, van, truck, bus, motor` evaluated; `motor → motorcycle exact` to verify) as primary with `van` and aerial caveats, supplemented by UAVDT (aerial; `car, truck, bus`) — a combination (ADR-017 §3) rather than waiting for one dataset.

**Domain diversity (H4 candidates, later):** fixed-camera traffic: UA-DETRAC (`car, bus` exact if a credible copy with establishable identity exists; original site offline); aerial: UAVDT (`car, truck, bus`; "research purpose only"; Google Drive) and VisDrone MOT. KITTI tracking (registration; `Car, Truck` exact, `Van` unsupported) is a weaker third. nuScenes is noted for its explicit definitions (car includes vans and SUVs; truck includes pickups; motorcycle includes scooters) but its annotations are 3D cuboids needing projection, so it is not a first-choice 2D tracking benchmark. MIO-TCD and similar still-image sets could support component-level classification checks, not Track evidence.

## 13. Exposure and contamination metadata

The envelope's `exposure` block: `{status: known | possible | unknown | none-known, basis, notes}` per dataset, populated from the model card and MAVI component history before a result is reported; interpretation text in the report: "Development/reference evidence; not independent generalisation evidence" when status is not `none-known`. A possible exposure never discards a benchmark; it changes the sentence under the table.

## 14. Deterministic failure modes

`descriptor_invalid`, `descriptor_blocked`, `mapping_invalid`, `mapping_incomplete`, `adapter_label_invalid`, `adapter_frame_missing`, `derivation_pack_mismatch`, `export_invalid` (from `artefacts`), `trajectory_missing`, `trajectory_hash_mismatch`, `trajectory_format_unsupported` (not v1), `producer_mixed` (exports attest different producers), `profile_mismatch`, `association_policy_invalid`, `output_exists`. Each refusal names the sequence or file; nothing is written on refusal.

## 15. Performance

BDD100K MOT val is on the order of two hundred videos of about two hundred frames at 5 Hz; GT tracks per video are tens to low hundreds, MAVI Tracks similar. Candidate pairs after temporal pruning are at most a few thousand per video, each scored over ≤ 200 frames: pure-Python association runs in seconds per video and minutes for the split. Goal: `evaluate` for the val split completes in under 30 minutes on the Development machine without optimisation; `prepare` and `execute` are dominated by encoding and MAVI processing (hours, like T9).

## 16. Implementation slices (one PR each; small)

1. **Contracts and synthetic core.** `tools/common`-style extraction of the `Api` client; `core/` (envelope, descriptor, mapping, identity, mavi readers); the four schemas with synthetic examples registered for `verify_repo`; `datasets/synthetic.py`; tests for descriptor, mapping, envelope determinism. No association yet.
2. **Vehicle Track association.** `capabilities/vehicle_tracks/` ground truth and association; trajectory reading (adds `msgpack` to `tools/requirements.txt` and the dependency policy's tools surface, per AGENTS); the full association fixture set including the mutation test.
3. **Vehicle-subclass evaluator and synthetic end-to-end.** `capabilities/vehicle_subclass/`; both scopes; report; `cli.py`; golden synthetic E2E; CI wiring. **H2 evidence complete here.**
4. **First real adapter.** `datasets/bdd100k_mot.py` (Scalabel reader, frame-sequence encoder, descriptor and mapping files); a fixture built from a handful of synthetic Scalabel-format records (no dataset bytes); acquisition and run instructions.
5. **First real execution** (separate task; S3.2d-2 / H3): acquire under the licence, `describe → prepare → execute → evaluate`, record evidence in the register.

## 17. Acceptance evidence for H2

H2 PASS when slices 1–3 are merged with green exact-head CI and the register records: the four contract names and example hashes; the association policy v1 identity; the synthetic E2E golden result hash; the mutation test's presence; the module list; the `msgpack` tools-surface declaration. No real dataset is required for H2. H3 then records the first real measurement with the envelope fields of §5 and the exposure block of §13.

## 18. Risks and open questions

- **Centre-only trajectories** limit association strength (§7). Mitigation: ambiguity rejection, spot checks, honest counts; possible later trajectory v2.
- **5 Hz processing** changes tracker behaviour; recorded as a caveat; a 30 fps diagnostic run is optional.
- **BDD100K definitions** for `truck` and `motorcycle` are unverified; the mapping kind may become `subset`.
- **Acquisition** needs a manual licence acceptance (owner or operator); nothing in the harness bypasses it.
- **UA-DETRAC availability** is uncertain; H4 does not depend on it.
- **Owner decisions required now:** none for implementing slices 1–3. Before slice 5: accept the BDD100K licence and confirm the val split as the first primary benchmark, or choose the VisDrone + UAVDT combination.
