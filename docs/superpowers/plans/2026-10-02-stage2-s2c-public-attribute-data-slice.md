# Stage 2 S2c — public-data slice for person attributes and vehicle colour (C+)

> **For agentic workers:** implement slice by slice with tests first. This plan authorizes no training, no frozen-qualification work and no change to B0 records.

**Status:** plan for review.
**Date:** 2026-10-02.
**Starting baseline:** `main@6eb85597136c77d3cdbaf607832d24d0430340c8`, which includes #137 (ADR-015, C+), #138 (purpose-aware acquisition and frozen eligibility) and #139 (operating principles).
**Governing:** ADR-015; parent plan `2026-09-28-stage2-s2c-learned-attribute-model-packs.md` (§6 tasks, §9 evaluation, §12 packs); candidate attribute task `tools/qualification/attributes/corpus/data/attribute-task-v1-candidate.json`; annotation guide `docs/qualification/stage2-s2c/annotation-guide.md`.
**Goal:** import the first public data for the six attributes, with release-level clearance, explicit label mapping and split integrity, and run a baseline component evaluation. Video is an optional, small track-level step. Gaps are measured, not guessed.
**Attributes:** `person-upper-colour`, `person-lower-colour`, `person-backpack`, `person-bag`, `person-headwear`, `vehicle-colour`.
**Evidence levels, kept separate:**
- **component:** labelled stills and crops;
- **track:** aggregation over MAVI Tracks;
- **end-to-end:** original video → VideoAsset → detector/tracker → Evidence Sets → attributes.

Still images never stand in for track-level or end-to-end evidence (ADR-015 §1).

---

## 1. What exists and what is missing

**Reused as is:**
- the attribute vocabulary (task v1 candidate):
  - upper/lower colour: 11 values plus a conditional `multicolour`;
  - vehicle colour: 11 values, including `beige` and `silver`, plus `multicolour`;
  - presence attributes are `absent`/`present`, with `person-headwear` conditional;
  - the seven `unscorableReasons`;
- C+ provenance (`attributes/corpus/provenance.py`: origins, purposes, `frozen_blockers`);
- the determination shape from #138 (`admission._determination`: purposes, licence codes, rights, privacy, R-5 ruling);
- `canonical.py` (canonical JSON and hashing helpers);
- `duplicates.dhash64` / `find_pairs`;
- the corpus manifest and annotation tooling, for the optional video step only.

**Missing, and built here:**
- an external dataset release record;
- a still-image dataset manifest (the "separate source/training manifest" of ADR-015 §1);
- label-mapping tables;
- source adapters;
- a component benchmark runner with MAVI's deterministic colour baselines.

There is no OMZ, SigLIP or DINOv2 adapter, and none is added: candidate runtimes need the separate S2c.3 evaluation environment.

**Constraints:**
- The corpus manifest (`mavi-attribute-corpus-manifest-v1`) is **not** extended to stills. It stays MAVI Track evidence.
- The Commons helper stays Commons-only.

## 2. First sources (smallest useful batch)

Licence statements were checked against official pages on 2026-10-02.

| Role | Source | Why first | Licence (official) | Use in this slice | `derivedArtefacts` |
|---|---|---|---|---|---|
| Person: images, backpack/bag/hat labels | **PA-100K** (100k surveillance crops, 598 scenes; 80k/10k/10k split by tracklet) | The only large pedestrian-attribute set with an explicit permissive licence. It labels backpack, handbag, shoulder bag and hat directly | **CC BY 4.0** (HydraPlus-Net README; line added 2021; camera rights and consent undocumented) | training, development, selection, benchmarking, regression | `packageable` only if R-5 accepts the provenance caveat; otherwise `internal-only` |
| Person: clothing-colour labels | **UPAR** annotations, PA-100K images only (12 per-image colour flags per region: 11 colours plus `Other`) | The only per-image colour labels on PA-100K. Its 11 colours equal MAVI's 11 exactly | **CC BY-NC-SA 3.0 DE** for the annotations; images keep their own licence (UPAR-Challenge-2027 README) | development, selection, benchmarking, regression; training only for internal experiments | `internal-only` |
| Vehicle colour | **VeRi-776** (about 50k images, 776 vehicles, 20 fixed urban CCTV cameras over 24 h; identity-disjoint split) | Fixed CCTV, a real colour vocabulary, identity groups, obtainable by request | "used for non-commercial purposes" (request by e-mail to the VeRi contact) | training, development, selection, benchmarking, regression | `internal-only` |
| Optional track-level | **MEVA**, at most 6 static ground-camera clips | Clear licence, documented consent and ethics approval, fixed cameras, pedestrians and vehicles, continuous video | **CC BY 4.0** (mevadata.org); AWS S3 | track-level development and regression only; MAVI labels the tracks | `packageable` |

**Not first, with reasons:**
- **PETA:** research-only; its split is not identity-disjoint; it includes withdrawn sources.
- **RAP v1/v2:** signed no-transfer agreement; non-commercial; indoor mall only.
- **Market-1501 attributes:** no licence; labels are per identity, not per image.
- **MSP60K and VRAI:** no licence stated.
- **UFPR-VCR/VeSV:** academic e-mail required; eligibility unconfirmed. Keep as the VeRi alternative.
- **CompCars, VehicleID, CityFlow:** non-commercial agreements, with unclear colour labels or distribution.
- **MOT17/20:** licence currently unverifiable; mostly moving cameras.
- **UA-DETRAC, BDD100K, IDD:** no colour labels, or wrong viewpoint.
- **Duke- and Oxford-derived sets:** withdrawn.

**Commercial path:** no clearly licensed vehicle-colour or clothing-colour label set exists. Packageable colour heads therefore need MAVI's own labels, on PA-100K or the CC BY 4.0 UVH-26 Indian CCTV set. This is follow-on work (§11). It is not a reason to delay the internal benchmark.

**Unresolved rights items. Each blocks only the import that depends on it:**
1. R-5: PA-100K packageable or internal-only, given the undocumented capture rights. Also a privacy basis for surveillance crops processed internally.
2. R-5: UPAR NC-SA for internal R&D, and whether share-alike attaches to derived labels or heads (they stay internal-only either way).
3. Owner: request VeRi-776 by e-mail, and keep the reply as the rights evidence. Ask explicitly about internal model training.
4. MEVA: attribution notice only; there is no open question.

## 3. Clearance model: reuse #138 determinations

There is one **release record** per downloaded release. A release record embeds one #138-shaped determination: purposes, licence codes, rights, privacy and R-5 ruling. It is validated by the same function, made public as `admission.parse_determination`.

| Bound by SHA-256 | Reused across the release | Per-file treatment |
|---|---|---|
| every archive or file obtained (size and SHA-256); the licence text, as retained; the determination; each label-mapping table | rights, privacy, R-5, approved purposes and `derivedArtefacts`, for all members | only exceptions: a member excluded on privacy grounds (listed by sample ID), or a corrupt or duplicate file (recorded by the importer) |

**Rules, enforced in code:**
- **No network code.** The operator places release files in the controlled store, and the importer refuses any file whose size or SHA-256 differs from the record.
- **Restricted licences** (NC/ND or bespoke terms) are accepted for datasets only with an R-5 `PERMITTED` ruling and `derivedArtefacts: internal-only`. The Commons purpose-approval rule is unchanged: NC/ND stays blocked there.
- **Most restrictive wins.** A dataset manifest joining several releases (PA-100K images with UPAR labels) inherits the most restrictive `derivedArtefacts`. A guard `require_packageable(manifest)` refuses `internal-only` inputs. The future training-manifest and Model Pack `component-provenance` step (S2c.6) must call it; a test pins the guard now.
- Every release is `origin: public`. `frozen-qualification` is not a dataset role, and the public-origin rule in `provenance.parse_purposes` refuses it again.

## 4. Records and import architecture

New package `tools/qualification/attributes/datasets/` (standard library, Pillow and the existing canonical helpers). Records live in the controlled store; mapping tables live in Git. No imagery goes in Git.

| Record | Schema | Content |
|---|---|---|
| Release | `mavi-attribute-dataset-release-v1` | `releaseId`, name and version, `officialUrl`, `licence {codes, url, textSha256}`, `files [{path, sizeBytes, sha256}]`, `determination`, `derivedArtefacts`, `knownExposure` (for example "PO-7 trained on PA-100K"; widely used in pretraining) |
| Label mapping | `mavi-attribute-label-mapping-v1` | per source label, a target: `value`, `negative-binary`, `unscorable:<reason>`, `merged:<set>` or `unmapped`. Each table is hash-bound and in Git |
| Still dataset | `mavi-attribute-still-dataset-v1` | release and mapping hashes; per sample: `sampleId` (image SHA-256), `releaseId`, member path, size, `objectClass`, `group` (vehicle ID; PA-100K index block), `sourceSplit`, `role`, and per attribute `{outcome, value, basis}`; the effective `derivedArtefacts`; the hash of the dedup report |
| Benchmark result | `mavi-attribute-component-benchmark-v1` | dataset hash, role, method identity, per-attribute confusion, support, coverage and macro-F1, and contamination notes. Evidence level `component` |

**Roles:** `training`, `development` (tuning), `selection`, `benchmark` and `regression`.
- `benchmark` is the published test split, left untouched.
- `regression` is a named sample list drawn from non-training roles.

**Adapters** each parse one source format into neutral rows: `pa100k.py` (annotation file), `upar.py` (CSV keyed by image path), `veri.py` (label XML with colour ID).

**Builder:**
1. join the rows;
2. apply the mappings;
3. assign roles;
4. run deduplication;
5. write the manifest, byte-identical on rerun.

**CLI:** `attribute_dataset_cli.py`, with the commands `verify-release`, `build`, `verify` and `benchmark`.

## 5. Label mapping (nothing is silently collapsed)

| MAVI attribute | PA-100K | UPAR (PA-100K subset) | VeRi-776 |
|---|---|---|---|
| upper / lower colour | — | `*-Color-{11}` map 1:1. `Other` → `unmapped`, **not** `multicolour`. Several positives → `unscorable:ambiguous` | — |
| backpack | `Backpack` 1 → `present`; 0 → `negative-binary` | `Accessory-Backpack`, used for cross-checking only | — |
| bag | `HandBag` OR `ShoulderBag` → `present`; both 0 → `negative-binary`. `HoldObjectsInFront` → `unmapped`, never a bag | `Accessory-Bag`, cross-check only | — |
| headwear | `Hat` 1 → `present`; 0 → `negative-binary`. Hats only: helmets, hoods and headscarves are uncovered, so negatives are weaker | `Accessory-Hat`, cross-check only | — |
| vehicle colour | — | — | black, white, red, blue, yellow, green, brown and orange map 1:1; gray → `merged:{grey,silver}` (VeRi has no silver); golden → `unmapped`. There is no beige or multicolour, so recall for those cannot be measured. This colour list comes from secondary sources; step 3 confirms it from the release's own colour list before the table is fixed |

**`negative-binary` semantics:**
- A source 0 cannot tell absent from not visible. Metrics therefore report positive-class precision and recall separately and mark negatives as weak.
- MAVI's ground-truth `absent` semantics are not claimed.

**Merged values:** scoring for a merged value uses the coarse vocabulary (grey or silver), matching the task's `valueMergeCandidates`.

**Light conditions:** VeRi night or achromatic frames cannot be detected from the source labels. Results are reported per camera, and night limitations are recorded rather than inferred.

## 6. Splits, deduplication and contamination

**Split integrity:**
- Published test splits become `benchmark` and are never used for training or development.
- PA-100K:
  - train → training, except a seeded 10% by contiguous index block → development;
  - val → selection;
  - test → benchmark.
- VeRi:
  - train identities → training, except a seeded 10% of vehicle IDs → development;
  - test identities, query included, are split 50/50 by a seeded vehicle-ID hash into selection and benchmark. VeRi has no published colour protocol.
- A vehicle ID never spans roles; the builder enforces this.

**Deduplication (practical; no impossible guarantees for non-frozen data):**
- exact SHA-256 duplicates within and across releases;
- `dhash64` near-duplicates across roles. A training member that near-duplicates a selection or benchmark member is dropped from training, and every drop is recorded;
- UPAR is joined to PA-100K by path and image hash. A path without a matching image is reported, never guessed.

**Contamination notes** are recorded in the release record and every benchmark result:
- known candidate exposure (PO-7 on PA-100K);
- PA-100K's and VeRi's broad use in pretraining;
- web-scale backbones of unknown exposure.

Public benchmark numbers carry a contamination and domain caveat. They are never qualification claims.

## 7. Model integration

- **Now:** baseline component benchmark with no new runtime dependency:
  - PC-B0/VC-B0: deterministic region chroma with CIE-Lab naming, the MAVI baselines in plan §9.5;
  - a prevalence baseline for presence attributes.

  This proves the manifest → crops → metrics path end to end on public data.
- **Next (S2c.3 environment):** candidate runners read crops by `sampleId` from the still-dataset manifest:
  - OMZ 0230 and 0042;
  - SigLIP 2 and DINOv2 heads.
- **Training manifests (§9.7):** cite the still-dataset hash and must pass `require_packageable` before any artefact can enter a Model Pack.
- **Calibration** is fitted only on training-derived data, per ADR-015.

## 8. Optional video step (track level)

- **Acquisition:** MEVA clips are placed by the operator and bound by the same release record. The Commons helper is not used, and no generic downloader is added.
- **Processing:** the clips go through the existing MAVI Development ingestion and VisionJob path. They become an operational corpus revision whose sources carry `provenance.origin = public`, with `acquisitionReceiptSha256` set to the release-record hash. #138 enforcement keeps them out of the frozen test automatically.
- **Labelling:** at most 150 Tracks, with the existing annotation tooling. The output is a track-level aggregation check.
- **Skip rule:** skip this step if Development ingestion of local files needs anything beyond configuration. Record the gap instead.

## 9. Implementation sequence

| # | Step | Tests first | Done when |
|---|---|---|---|
| 0 | Rights, in parallel: R-5 rulings 1–2, the VeRi request, MEVA attribution | — | determinations written into release records |
| 1 | Make `admission.parse_determination` public; add the dataset licence rule | NC/ND accepted for datasets only with R-5 and `internal-only`; Commons behaviour unchanged | existing acquisition tests green |
| 2 | Release record and file verification | wrong size or hash refused; missing determination refused; licence-text hash bound; local paths refused | — |
| 3 | Format probes, local and not retained (PA-100K annotation file version, VeRi XML), then the adapters | adapter fixtures built from synthetic rows in the real formats | if the PA-100K file is MATLAB v5, reuse the `scipy` pin already in `vision-runtime` and update `offline-dependency-policy-v1.json` in the same change |
| 4 | Mapping tables and mapping engine | `Other` is never `multicolour`; `HoldObjectsInFront` is never a bag; multi-positive is ambiguous; gray maps to the merged set; an unknown source label is refused | tables reviewed |
| 5 | Still-dataset builder | split preservation; benchmark never in training; ID groups never span roles; dedup drops recorded; most restrictive `derivedArtefacts`; no frozen role; byte-identical rerun | manifests built for PA-100K+UPAR and VeRi |
| 6 | Baseline benchmark | metrics against hand-computed fixtures; coverage counts unscorable rows; refuses a role outside its purposes | baseline results for all six attributes |
| 7 | Optional MEVA track step | the corpus revision is public-origin and frozen-ineligible (reuses #138 tests) | track aggregation check, or a recorded skip |

**Workload bounds (not adequacy thresholds):**

| Item | Bound |
|---|---|
| Releases | 3 still releases (PA-100K, UPAR annotations, VeRi-776) and at most 1 video release |
| Files | about 100k PA-100K images and about 50k VeRi images, as published, without sub-sampling; at most 6 MEVA clips totalling 30 minutes |
| Controlled storage | at most 15 GB (stills at most 10 GB, video at most 5 GB) |
| Adapters | 3 |
| Mapping tables | 3 |
| Human review | 3 release determinations, 1 R-5 session and at most 150 track labels |
| Engineering | about 1–2 weeks |

## 10. Acceptance criteria and non-goals

**Accept when:**
- the selected releases import cleanly and verify by hash;
- release determinations are reused across all members, with no per-file approvals;
- mappings are tested, and every unmapped label is counted;
- split, identity-group and dedup reports are recorded;
- `internal-only` cannot reach `require_packageable`;
- baseline component results exist for all six attributes;
- the optional track check runs, or its skip is recorded;
- a gap report lists measured coverage per attribute value, for example "no beige or multicolour vehicle labels" and "no hood or helmet negatives".

**Tests are discriminating:** each guard above has a test that a plausible mutant would fail, as in #138.

**Run before merging:** the full `tools/qualification/tests`, `tools/verify_repo.py` and `git diff --check`.

**Non-goals:**
- training or fine-tuning a candidate, or running OMZ, SigLIP or DINOv2 (S2c.3 environment);
- Model Pack changes;
- frozen-qualification data;
- changes to the corpus-manifest schema for stills;
- a generic downloader;
- more datasets;
- commercial colour relabelling;
- B0 records or the 63 decisions.

## 11. Follow-on

1. The S2c.3 evaluation environment and candidate runners on these manifests.
2. MAVI colour labels on PA-100K or UVH-26 crops, for packageable colour heads.
3. A `require_packageable` call in the training-manifest and Model Pack provenance path (S2c.6).
4. More sources only against a measured gap from §10, for example UFPR-VCR for night and beige.
5. Commissioned protected capture for the frozen test (ADR-015 §6). This stays separate.
