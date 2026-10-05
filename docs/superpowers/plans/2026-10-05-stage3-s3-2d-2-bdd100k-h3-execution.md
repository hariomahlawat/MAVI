# Stage 3 S3.2d-2 — H3 execution runbook: the first real BDD100K benchmark run

**Status:** implementation-ready runbook; not executed. Baseline `main@ce3da38fe7b1c769930d4a362feea31f1a9b9414` (PR #166 merged). H3 remains OPEN until the run in §7 is complete and its evidence is recorded (§9, §10).
**Date:** 2026-10-05
**Governing:** ADR-017 (benchmark-first Development; §7 admissibility, §8 no silent contamination claims); ADR-016 (detector-native subclass, unchanged); the Stage-3 register `docs/reviews/2026-10-03-stage3-vehicle-subclass-acceptance.md` (row H3; G9 thresholds `minShare` 0.6, `minMatchedDetections` 3); the harness plan `docs/superpowers/plans/2026-10-04-stage3-s3-2d-benchmark-harness.md` (architecture; not rewritten here); the acquisition guide `docs/qualification/stage3/bdd100k-mot-acquisition.md` (derived-path section).

## 1. Objective

Run the merged benchmark harness once, end to end, on the real BDD100K MOT 2020 `val` split through the derived-annotation adapter, and record the result as the H3 primary benchmark measurement. This run is **measurement, not tuning** (§8). It changes no code, threshold, model, mapping or taxonomy, and it does not close H4 or H5.

## 2. Exact baseline

| Item | Value |
|---|---|
| Repository commit | `main@ce3da38fe7b1c769930d4a362feea31f1a9b9414`, clean worktree (`evaluate` refuses `tooling_dirty` otherwise) |
| Harness | `tools/benchmarks` as merged: `describe`, `prepare`, `execute` (PR #165), `evaluate`; adapter `bdd100k-mot-coco` (PR #166) |
| Evaluator, association, mapping schema | unchanged from H2 |
| Capability | `mavi-vehicle-subclass-v1` = `car | truck | bus | motorcycle` |

## 3. Frozen inputs

### 3.1 Source

| Input | Identity |
|---|---|
| Image archive | `images20-track-val-1.zip`, 4,983,938,716 bytes, SHA-256 `4d678810a14095ab4064013d81e3bc2bda45f730bfc09c3e66d3a5ef1c076778`, MD5 `743ab4c7b5ff8eeebd60bbfd15b20bd6`; obtained by the owner from the Berkeley BDD100K MOT mirror; no independently published checksum exists |
| Extracted images | 200 sequences, 39,973 JPEGs, all 1280 × 720, contiguous frame numbers from 1; every archive member passed its CRC check |
| Annotation | `bdd_box_track_val_cocofmt.json`, 117,094,032 bytes, SHA-256 `074ff79555483296cf7ccadddeeceeec7a83452c900506dc46588ed3a3e65d5d`; MASA repository `dereksiyuanli/masa` commit `25ed372c47f2c46cf36fd446d1b657b656bc7ea9`; retrieved 2026-10-05 |
| Adapter | `bdd100k-mot-coco`, version `1`; it refuses any annotation whose SHA-256 is not the one above |
| Dataset / release / split | `bdd100k-mot-2020-cocofmt` / `MOT 2020 val (box_track_20) via MASA COCO-format derivative sha256:074ff795` / `val` |
| Frame time | `index-at-fps` 5/1: frame k at k × 200 ms |
| Descriptor template | `docs/qualification/stage3/benchmarks/bdd100k-mot-2020-cocofmt.descriptor-template.json`, SHA-256 `6371b0aab38049c8bb98dfb70d2eb15747a383eaa3755693a288b4d8ddf2c425` |
| Mapping | `docs/qualification/stage3/benchmarks/bdd100k-mot-2020-cocofmt.mapping.json`, SHA-256 `28e5ec5ef78ca9e4b36cc98b9d09bb33a5788bd21a4e5a797c14a100d3a318d3`: car, truck, bus, motorcycle → the same MAVI class `exact`; pedestrian, rider, train, bicycle → `unsupported` (`outside-capability`). `car → car exact` is settled and is not reopened |
| Research use | RESEARCH-ADMISSIBLE: BDD100K data and label licence (educational, research and not-for-profit use without fee); MASA is the retrieval and conversion source, not a relicensor |
| Exposure | `none-known`: the qualified detector trains on COCO 2017 only (resolved config SHA-256 `377d9f57abf6a73a6c308f765b70fc571715448c62998819d609d2eebc7c5ee3`), loads no other checkpoint, declares no pretrained backbone; no MAVI record names BDD100K |

### 3.2 Ground-truth semantics (merged; stated exactly)

| Annotation flags | Ground truth |
|---|---|
| `iscrowd = 0, ignore = 0` | ordinary GT of its class |
| `iscrowd = 1, ignore = 0` (genuine BDD crowd) | ordinary GT of its class, as on the raw adapter and under the frozen harness policy |
| `iscrowd = 1, ignore = 1` (converted distractor: former `trailer`, `other vehicle`, `other person`) | ignored frame; never scored |

Consequences: BDD100K's official crowd-overlap scoring is **not** reproduced, so these results are **not** official BDD100K MOT scores. A label id whose class changes between frames (46 of 18,842 tracks) is ignored on every frame, with its first class recorded but never scored. Real validation after the final crowd fix: 200 sequences, 18,842 tracks, 5,726 ignored frames, 236 fully ignored tracks (`ignoredGt`, in no population). Retained record: `E:\MAVI-Controlled\Stage3\S3.2d-2\validation\real-adapter-validation.json`.

### 3.3 Lineage evidence (existing; cited, not repeated)

Reference `scalabel/scalabel` commit `071d073598e7c988134dc70a5c0c52761226bf42`, path `tests/eval/testcases/box_track/track_sample_anns.json`, blob `3e19c83dba4b2b3e222d9db61d5888b049a60fcf`, video `b1c66a42-6f7d68ca`. Result: 202 raw and 202 derived frames with exact frame-index sets and file names; 3,241 boxes compared; track ids match under the declared uniform `a-` prefix transformation; category, bbox, `iscrowd` and `ignore` all match; zero material mismatches. Retained record: `E:\MAVI-Controlled\Stage3\S3.2d-2\validation\lineage-b1c66a42-6f7d68ca.json`. A new lineage run is needed only if the annotation bytes change (they cannot: the SHA-256 is pinned).

### 3.4 MAVI side

| Input | Identity |
|---|---|
| Pipeline profile | `src/vision/config/pipelines/phase1-detection-tracking-v1.json`, `1.3.0-candidate`, vocabulary `mavi-vehicle-subclass-v1`, `minShare` 0.6, `minMatchedDetections` 3, SHA-256 `afb03b6c4da61fbf6021ef855307f80c5b7206996e7e21c8d297394b091a18bf` (the `execute` identity gate) |
| Component binding | `src/vision/config/components/phase1-bindings-v2.json`, SHA-256 `7ef226193232b90b0a20f8648a95f21e0bbc9416b353605c9be6d81262abe205` |
| Model Pack | `mavi-model-v2-86754e364c7560c407b531900de58eb5e66fd365685677f8f24a5a61b3186700` (qualification `rtmdet-m-coco-phase1-v2`; checkpoint SHA-256 `229f527ca88498e8894a778a62a878a322b4a3ea2cae09ea537d34b7e907792b`) |
| Runtime Pack | `windows-x86_64-cuda` `mavi-runtime-v2-89fd8bfcc32fb1bd8ab77f0deb9f33675ae228c75ffd11f13e6838e990003a1d` (the S3.2b-3 Development device decision: `cuda:0`, GTX 1650 Ti) |
| Requirements | `docs/qualification/stage3/s3-2-subclass-requirements.json`, SHA-256 `ca28702f82c6845298a2cf348d7b057024923c7a0a0f4fd496097bf1b7272d75` (the registered identity `evaluate` requires) |
| Association policy | `POLICY_V1` of `tools/benchmarks/capabilities/vehicle_tracks/policy.py`, written as canonical JSON; SHA-256 `a8e2e7f18d6912c226444a2639dc7ee928575085d683690b8408efc6eb8ffe05` |
| FFmpeg pack | the verified MAVI media-tools pack (`vendor/ffmpeg` on the Development host); its identity is read from the pack manifest at run time and written into the derivation manifest |
| Tooling | computed by `evaluate` over the loaded harness modules at the exact commit (`toolingSha256`, `toolingCommit`) |

## 4. Preflight (all must hold before §7 step 1)

```powershell
git -C <repo> rev-parse HEAD            # must print ce3da38fe7b1c769930d4a362feea31f1a9b9414
git -C <repo> status --porcelain        # must print nothing
```

- Hash the archive, annotation, template, mapping, profile, binding and requirements; each must equal §3.
- The installed Model Pack and Runtime Pack ids and the checkpoint SHA-256 equal §3.4 (`tools/setup/Start-MaviVisionWorker.ps1` verifies the installed pack manifests against the committed binding and refuses a mismatch at launch).
- Build the API, worker host and T1 export tool from this exact commit (`dotnet build MAVI.sln -c Debug`); the export tool is `tools/dotnet/Mavi.MeasurementExport/bin/Debug/net10.0/Mavi.MeasurementExport.exe`.
- `python -m pytest -q tools/benchmarks/tests` passes with the media pack (`MAVI_TEST_MEDIA_TOOLS`); `python tools/verify_repo.py` exits 0.
- The ordinary Development catalogue and media roots are not referenced anywhere in §5.
- Free disk: derived MP4s (hundreds of MB), the media store copy of each MP4, evidence crops and trajectories; keep at least 20 GB free on the controlled drive.

## 5. Controlled-store layout (outside Git; short paths)

Root `E:\MAVI-Controlled\Stage3\H3` (short on purpose: S3.2b-3 attempt 1 failed on a path longer than 260 characters under the API app host, and the API runs as `dotnet Mavi.Api.dll`).

```text
E:\MAVI-Controlled\Stage3\H3\
  src\                      the source root (§7 step 2): labels\box_track_20_cocofmt\bdd_box_track_val_cocofmt.json
                            and images\track\val\<videoName>\<videoName>-NNNNNNN.jpg, nothing else
  desc\working.json         the working descriptor (template with actual retrieval facts)
  desc\frozen.json          written once by describe --freeze-manifest
  derived\                  written once by prepare (200 sequences, derivation-manifest.json)
  host\db-name.txt          the dedicated catalogue name, e.g. mavi_s32d2_h3_20261005
  host\m\  host\ev\         the dedicated media store and evidence root (API process-scope overrides)
  host\logs\                API, worker, execute and evaluate logs
  exec\journal.json         the execute journal (runtime only; never evidence)
  exec\exports\<runId>\     one T1 export per processing run
  results\<benchmarkRunId>\ association.json, result.json, report.md (write-once)
  evidence\                 hashes.txt, validation and lineage records, catalogue-creation record
```

Write-once outputs must **not** exist before their step: `desc\frozen.json` (`describe --freeze-manifest` refuses `output_exists`), `derived\` (`prepare` creates it; an existing path is `output_exists`) and the run directory under `results\` (`evaluate` creates it; `results\` itself may exist). `exec\exports\` and `host\ev\` must exist before `execute`.

The already-extracted tree `E:\MAVI-Controlled\Stage3\S3.2d-2\extracted\bdd100k` holds exactly the 39,973 JPEGs plus the annotation at the adapter path (its freeze reconciled 39,974 entries on 2026-10-05). Use it as `src` by moving or junction-free copying; never add a file to it.

## 6. Exact commands

All commands are PowerShell, run from the repository root at the exact commit, with these variables set first (the call operator `&` is required to run the interpreter held in `$Py`):

```powershell
$Repo = "<repository root at ce3da38f>"; $Py = "$Repo\.venv\Scripts\python.exe"; $H3 = "E:\MAVI-Controlled\Stage3\H3"
Set-Location $Repo
```

```powershell
# validate the working descriptor and the mapping against its taxonomy
& $Py -m tools.benchmarks.cli describe --descriptor $H3\desc\working.json --mapping docs\qualification\stage3\benchmarks\bdd100k-mot-2020-cocofmt.mapping.json
```

```powershell
# freeze the source manifest once (path, size, SHA-256 of every file under src); prints the frozen descriptor SHA-256
& $Py -m tools.benchmarks.cli describe --descriptor $H3\desc\working.json --freeze-manifest --source-root $H3\src --out $H3\desc\frozen.json
```

```powershell
# reconcile the whole manifest, write canonical ground truth and one 5 fps MP4 per sequence; prints the derivation manifest SHA-256
& $Py -m tools.benchmarks.cli prepare --descriptor $H3\desc\frozen.json --source-root $H3\src --split val --adapter bdd100k-mot-coco --media-tools $Repo\vendor\ffmpeg --out $H3\derived
```

```powershell
# one MAVI run per sequence on the fresh catalogue; prints "<sequenceId> <processingRunId> <exportSha256>" per sequence
& $Py -m tools.benchmarks.cli execute --derived $H3\derived --pipeline-profile src\vision\config\pipelines\phase1-detection-tracking-v1.json --api http://localhost:<port> --journal $H3\exec\journal.json --exports $H3\exec\exports --evidence-root $H3\host\ev --export-exe $Repo\tools\dotnet\Mavi.MeasurementExport\bin\Debug\net10.0\Mavi.MeasurementExport.exe --poll-seconds 15
```

```powershell
# association, evaluation and report, written once to results\<benchmarkRunId>; prints the run id
& $Py -m tools.benchmarks.cli evaluate --descriptor $H3\desc\frozen.json --derived $H3\derived --exports $H3\exec\exports --evidence-root $H3\host\ev --mapping docs\qualification\stage3\benchmarks\bdd100k-mot-2020-cocofmt.mapping.json --policy $H3\desc\policy.json --requirements docs\qualification\stage3\s3-2-subclass-requirements.json --pipeline-profile src\vision\config\pipelines\phase1-detection-tracking-v1.json --out $H3\results
```

`$H3\desc\policy.json` is `POLICY_V1` as canonical JSON. It is written and hashed in step 1, before anything runs, and the same file is passed to `evaluate` in step 14 (§3.4):

```powershell
& $Py -c "from pathlib import Path; from tools.benchmarks.capabilities.vehicle_tracks import policy; from tools.benchmarks.core.identity import canonical_json; Path(r'$H3\desc\policy.json').write_bytes(canonical_json(policy.POLICY_V1))"
```

Step 9's per-class check needs an aggregation over the 200 canonical ground-truth files, because the derivation manifest records only sequence identity, frame counts, source paths and hashes:

```powershell
& $Py -c "import collections, json, pathlib; c = collections.Counter(t['nativeClass'] for p in pathlib.Path(r'$H3\derived\sequences').glob('*/ground-truth.json') for t in json.loads(p.read_bytes())['tracks']); print(sum(c.values()), dict(sorted(c.items())))"
```

After `evaluate`, re-verify the written run with the harness's own reader, which re-checks the association, the result bound to it and the regenerated report:

```powershell
& $Py -c "from pathlib import Path; from tools.benchmarks import run; run.verify(Path(r'$H3\results\<benchmarkRunId>'))"
```

The export tool and the API read the default Development machine configuration plus process-scope overrides for the dedicated catalogue (`ConnectionStrings__Mavi` with the H3 database name), media store (`MediaStorage__RootPath` = `$H3\host\m`) and evidence root (`MediaStorage__EvidenceRootPath` = `$H3\host\ev`), exactly as S3.2b-3 attempt 2 did. The worker is started with `tools/setup/Start-MaviVisionWorker.ps1 -ApiBaseUrl http://localhost:<port> -WorkerId s32d2-h3-worker-01 -MediaRoot $H3\host\m -DevicePolicy cuda`.

## 7. Execution sequence

| Step | Action | Estimate | Safe restart point |
|---|---|---|---|
| 1 | Create `$H3` with `src`, `desc`, `host\m`, `host\ev`, `host\logs`, `exec\exports` and `evidence` only; leave `derived`, `results` and `desc\frozen.json` absent (§5); write `desc\policy.json` (§6) so the association policy is frozen before anything runs; record `hashes.txt` for the archive, annotation, template, mapping, profile, binding, requirements and that policy file | minutes | any time before step 6 |
| 2 | Assemble `src` in the adapter layout (§5): the extracted image tree plus the annotation at `labels/box_track_20_cocofmt/`; no other file | minutes (move) or ~10 min (copy 5 GB) | redo freely before step 6 |
| 3 | Verify the annotation size and SHA-256 and the image count (39,973) against §3.1 | 1 min | — |
| 4 | Create `desc\working.json` from the template | 1 min | — |
| 5 | Set only working-run values: `source.retrievedOn` = the actual retrieval date of the annotation (2026-10-05, already the template's value). Change nothing else: the adapter binds `datasetId`, `release`, `task`, `frameTime` and the taxonomy, and `exposure` already states `none-known` with its basis. Run `describe --mapping` (§6) | 1 min | — |
| 6 | `describe --freeze-manifest` (§6): hashes 39,974 files once; record the printed frozen descriptor SHA-256 | 3–7 min (measured 146–399 s) | if interrupted, delete the partial `frozen.json` and rerun; the result is deterministic |
| 7 | Reconciliation is the first thing `prepare` does; no separate command. A refusal here (`source_manifest_*`, `source_root_invalid`) is a source-tree problem: fix the tree, never the manifest | — | — |
| 8 | `prepare` (§6): writes `derived\` only on success; 200 libx264 encodes at 5 fps | hours; measure the first sequences and extrapolate (a 1280 × 720, ~200-frame encode at `preset slow`, `crf 16` is typically 1–3 min on this host) | `prepare` writes a new directory atomically: if interrupted, delete the partial output and rerun from the frozen descriptor (ground truth and encodes are deterministic) |
| 9 | Inspect `derived\derivation-manifest.json`: 200 sequences, frame counts summing to 39,973, `frameRate` 5/1, adapter `bdd100k-mot-coco` v1, FFmpeg identity, one `groundTruthSha256` per sequence; then run the §6 aggregation command over `derived\sequences\*\ground-truth.json` (the manifest itself carries no classes) and compare its total (18,842) and per-class track counts with §3.2 (car 13,866; truck 744; bus 193; motorcycle 46; pedestrian 3,603; rider 133; bicycle 251; train 6; these are raw GT track counts, not benchmark support, which is assigned exact-GT pairs after association) | 10 min | — |
| 10 | Create the dedicated catalogue (new PostgreSQL database with the `vector` extension, as `prepare_t9_catalogue` did for S3.2b-3) and empty `host\m`, `host\ev`; record creation time and emptiness in `evidence\`; start the API with the §6 overrides as `dotnet Mavi.Api.dll`; start the worker; confirm `GET /api/cameras` and `GET /api/videos` are empty | 15 min | — |
| 11 | `execute` (§6): per sequence, camera `BDD-<SEQUENCE-ID>`, import, run queued and journalled before polling, `Completed`, T1 export; then the exit checks (one producer, the measured profile, exports bound to the derived videos, every sealed trajectory present) | hours; measure the first sequences (each is a 40 s clip at 5 fps) | journal-based resume, step 12 |
| 12 | If interrupted operationally, rerun the identical `execute` command: the journal (bound to this derivation manifest and descriptor) resumes without re-importing or re-queueing, and refuses anything it did not create (`t9_catalogue_not_fresh`, `t9_asset_preexisting`, `t9_run_substituted`). A `t9_run_failed` sequence is not resumable: that is a §8.2 stop | — | the journal |
| 13 | Verify completeness: 200 export directories, each export `Completed` and bound to its derived video, 200 distinct runs, one producer identity; `execute` exits 0 only when this holds | 10 min | — |
| 14 | Confirm `desc\policy.json` still hashes to its step-1 value; `evaluate` (§6) | minutes | write-once; a rerun with identical inputs refuses `output_exists` |
| 15 | `evaluate` writes `association.json` (class-free) before the result; keep the directory intact; hash all three files | 1 min | — |
| 16 | Read `report.md`; transcribe Scope A and Scope B into the evidence block (§9) without rounding away denominators | 1 h | — |
| 17 | Record H3 in the register (§9) only when steps 1–16 are complete and internally consistent (the run id, hashes and counts agree across the derivation manifest, exports, association and result) | 1 h | — |

## 8. Rules during the run

### 8.1 No tuning

The first authoritative H3 run is measurement. During it, do not change thresholds (`minShare`, `minMatchedDetections`), the association policy, the model, checkpoint, tracker or detector, the taxonomy or mapping; do not hand-correct labels; do not delete difficult sequences; do not rerun selectively to improve results. If the result is poor, record it first. Any later improvement is a separately versioned Development experiment, evaluated against a frozen benchmark state, and never rewrites the original H3 evidence.

### 8.2 Defect stop

If `describe`, `prepare`, `execute` or `evaluate` exposes a genuine harness or adapter defect (a raw exception, a refusal that the source and inputs do not explain, a `t9_run_failed`, a wrong count): **stop the H3 event.** Then reproduce the defect; make the smallest focused fix; add a discriminating regression test; open a separate PR; get exact-head CI and review green; merge; restart H3 from the new merged `main` with a new frozen descriptor and a new catalogue. Never patch code mid-event and continue under the same evidence identity.

### 8.3 Operational interruption

A process restart, machine reboot, temporary service stop or network blip may be resumed only where the harness permits: steps 6 and 8 by rerunning from the frozen descriptor, step 11 through the journal. The benchmark identity (commit, frozen descriptor, derivation manifest, catalogue) must be unchanged.

### 8.4 Coverage-limited result

If `scopeA.coverageLimited` is true (`coverageLimitedGtRate` above 1/10, the policy's escalation threshold), H3 is still recorded, but the register entry says so and the owner decides whether H3 may be relied upon for H5 (harness plan §7.7).

## 9. H3 evidence block for the register

Enter one block under a new section "H. S3.2d-2 — primary benchmark measurement (H3)" and fill row H3. Record, by value:

**Dataset and provenance:** dataset id, release, split, adapter id and version; frozen descriptor SHA-256 (printed by step 6) and manifest entry count (39,974); annotation SHA-256 and image archive SHA-256 and MD5 (§3.1); mapping SHA-256; research-use status and basis; exposure status and basis; lineage reference and result (§3.3); the GT semantics table (§3.2) and the validation counts.

**Domain and interpretation caveats** (from the acquisition guide; recorded with the result so they travel with it): the footage is moving dashcam video from the United States, a weak proxy for fixed CCTV; the derived annotation folds any raw `van`/`caravan` alias into `car` and BDD100K does not document how vans are split, so a cargo van labelled `car` counts against car precision and truck recall; results are not official BDD100K MOT scores (§3.2); no claim about `trailer`, `other vehicle`, `van` or `caravan` can be drawn from this source.

**MAVI execution:** exact MAVI commit; Runtime Pack id; Model Pack id; checkpoint SHA-256; component binding SHA-256; pipeline profile SHA-256; requirements SHA-256; association policy SHA-256; `toolingSha256` and `toolingCommit` from the envelope; catalogue name and creation record; derivation manifest SHA-256 and FFmpeg identity; expected sequences (200) and completed sequences; the 200 processing run ids (or their list's SHA-256).

**Scope A** (from `result.scopeA`): `expectedVehicleGt` {total, assigned, ambiguous, fragmented, merged, unverified, unmatched}; `ignoredGt`; `maviTracks` {total, assigned, fragment, unverified, ignored, unmatched}; `associationRate`; `coverageLimitedGtRate` and `coverageLimited`; `maviUnverifiedRate`; `perNativeClass` coverage counts for all eight classes; `outsideCapabilityGt` {total, vehicleTracksOnOutsideCapabilityGt}; per-sequence rates where any sequence is coverage-limited.

**Scope B** (from `result.scopeB`), for each of car, truck, bus, motorcycle: `support` and `supportStatus` (the registered floor); `recall`; `precision` {status, value, `precisionAmongJudgedTracks`, `unjudgeablePredictions`} (`not-available` recorded as such); `accuracyOverResolved`; `accuracyOverEvaluable`; `undeterminedShare`; confusion counts from `confusion`; `requirementStatus`. Also `overall` (assignedExact, resolved, correct, undetermined, both accuracies, undetermined share); `macro` and the classes it includes; `taxonomyCoverage`; `excluded` native classes with their counts.

**Identities:** `benchmarkRunId`; SHA-256 of `association.json`, `result.json` and `report.md`; `result.associationSha256` equal to the association file's hash.

H3 is never reduced to one accuracy number.

## 10. H3 acceptance semantics

H3 means **"primary real benchmark measurement recorded"**: the run is complete (200 of 200 sequences), reproducible (frozen descriptor, derivation manifest, journal-bound resumability as in §7 step 12 and §8.3, write-once results), provenance-bound (every identity in §9), association quality reported under the frozen policy, and interpretable enough to serve as the primary Development benchmark measurement.

H3 does **not** mean that any class passed its requirement, that anything is Production-qualified, that operator exposure is approved, or that the taxonomy is frozen. H3 can PASS as an evidence-completeness gate even when class performance is poor or support is insufficient, provided the run is valid and complete. Performance findings feed H5. After H3: H4 remains OPEN (or is later recorded NOT TRIGGERED with a rationale); H5 remains OPEN; X1 and X2 remain blocked.

## 11. Post-H3 decision tree

| Outcome | Next |
|---|---|
| Valid, complete run; association rate acceptable; classes supported | Record H3 PASS; proceed to H4 (domain diversity) planning |
| Weak association or detection (`associationRate` low, high `unverified`/`unmatched`, or `coverageLimited`) | Record H3 as measured; diagnose detection, tracking and association-facing implementation (centre-only trajectories, §7.7 escalation) as a separate experiment |
| Good association, weak subclass quality (low accuracy, high undetermined share, confusion) | Record H3 as measured; subclass or model improvement path as a separately versioned experiment |
| One or more classes have benchmark support below the registered floor of 30 after association (support is assigned exact-GT pairs, not raw track counts; the raw counts in §3.2 and step 9 do not predict it) | Record honestly with `supportStatus`; H4 and H5 resolve what the evidence supports |
| Implementation defect during the run | §8.2: prerequisite fix PR, merge, restart H3 from the new `main` |
