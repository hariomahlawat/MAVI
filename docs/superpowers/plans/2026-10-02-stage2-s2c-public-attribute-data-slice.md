# Stage 2 S2c — public-data slice for person attributes and vehicle colour (C+)

> **For agentic workers:** implement vertical by vertical, with tests first. This plan authorizes no training, no candidate-model execution, no frozen-qualification work and no change to B0 records.

**Status:** plan, amended after review (rev 3: final contract fixes).
**Date:** 2026-10-02.
**Starting baseline:** `main@6eb85597136c77d3cdbaf607832d24d0430340c8`, which includes:
- #137, ADR-015 (C+);
- #138, purpose-aware acquisition and frozen eligibility;
- #139, operating principles.

**Governing:**
- ADR-015;
- parent plan `2026-09-28-stage2-s2c-learned-attribute-model-packs.md`: §6 tasks; §9.3 licence classes; §9.5 baselines; §12 packs; owner constraint A, under which MAVI is non-commercial;
- MSR method `docs/qualification/model-selection/README.md` §2.1 and §5, the rights inventory per declared profile and delivery route;
- the candidate attribute task `tools/qualification/attributes/corpus/data/attribute-task-v1-candidate.json`;
- the annotation guide.

**Goal:** a first reproducible person-attribute component measurement from public data, through a verified release, explicit intended-use authorisation, explicit label mapping and honest metrics. VeRi-776 is the second vertical; MEVA is optional. Gaps are measured, not guessed.

**Evidence levels, kept separate:**
- **component:** labelled stills;
- **track:** aggregation over MAVI Tracks;
- **end-to-end:** original video through MAVI.

Still images never stand in for track-level or end-to-end evidence (ADR-015 §1).

---

## 1. Baseline facts (checked against code at `6eb85597`)

**Reused as is:**
- **Attribute vocabulary.**
  - Upper/lower colour: 11 values plus a conditional `multicolour`.
  - Vehicle colour: 11 values including `beige` and `silver`, plus `multicolour`; `grey+silver` is a `valueMergeCandidate`.
  - Presence attributes are `absent`/`present`; `person-headwear` is conditional.
  - Seven `unscorableReasons`.
- **C+ provenance:** origins, purposes, `PARTITION_PURPOSES`, `frozen_blockers`.
- **Canonical hashing helpers.**

**What the code actually does, and how this plan treats it:**

| Fact in code | Consequence here |
|---|---|
| `admission._determination` checks **structure only**. It accepts empty `rights`/`privacy` dicts and a null `r5Ruling`. Authorisation semantics live in `purpose_approval_blockers`, mixed with Commons video and revision checks | Parsing is never treated as authorisation (§3) |
| `duplicates.find_pairs` and the duplicate audit are tied to `CorpusManifest`. `dhash64` works on greyscale: solid red, green, blue and white all hash to `0` (verified locally) | Reuse only `dhash64`/`hamming`, and only as a screening signal (§6) |
| PC-B0/VC-B0 are defined in prose only (parent §9.5: region band, dominant chroma cluster, CIE-Lab naming; confidence is the share of pixels). No geometry, palette or implementation exists | This slice does **not** implement them (§7) |
| PO-B0 is a per-camera training-prevalence reference with a global prior | PA-100K has no camera grouping, so no PO-B0 here (§7) |
| No external-dataset importer, still-image manifest, crop-evaluation harness, or OMZ/SigLIP/DINOv2 adapter exists | Built here, except candidate adapters, which wait for the S2c.3 environment |
| MAVI is non-commercial. Licence fitness is judged per **declared deployment profile and delivery route**, by a human (parent §9.3; MSR §2.1) | Disposition is per artefact and route, with R-5 interpreting (§3.3) |

## 2. Sources and pinned releases

Licence lines were checked on official pages on 2026-10-02. "Among the sources reviewed" applies to every comparison; this was a bounded survey, not proof that nothing better exists.

| Vertical | Source | Pinned identity | Licence (official text) | Notes |
|---|---|---|---|---|
| 1 (person) | **PA-100K** images and the 26 native binary labels | the dataset linked from `github.com/xh-liu/HydraPlus-Net` README; image files `release_data/NNNNNN.jpg`; official split by index: 000001–080000 train, 080001–090000 val, 090001–100000 test | "under CC-BY 4.0 license" (README; line added 2021) | Camera rights and consent are undocumented, which is R-5 item 1. **The annotation-file format is unverified until the archive is in hand** (step 1) |
| 1 (person) | **UPAR** colour labels, PA-100K rows only | `github.com/speckean/UPAR-Challenge-2027` @ `a19ab2fb6470140606d3c1982c303937b58fbd14` (2026-09-21); files `data/annotations/task1/train/gt.csv` (SHA-256 `e42084aa43b31d4074624265b8239437afc6e47a359a8c0129fae4513a77d424`; corrected 2026-10-02, the earlier value `31ba2922…` is the misaligned top-level `train.csv`) and `data/annotations/task1/val/gt.csv` (SHA-256 `783be600e359052c9dafe856cbfa2aee45bbd4e3eac10309394e2388bcf7c2bc`) | annotations "CC BY-NC-SA 3.0" (DE); "source image datasets retain their respective licenses" | Format summary below; R-5 item 2 |
| 2 (vehicle) | **VeRi-776** | the release received by e-mail, pinned at receipt (archive SHA-256 and the native colour table) | "used for non-commercial purposes" (vehiclereid.github.io/VeRi) | Owner request with the scope of use; R-5 item 3 |
| optional | **MEVA**, at most 6 static ground-camera clips | a list of S3 object keys and SHA-256s, pinned before any download | "All MEVA data is available for use under a CC BY-4.0 license" (mevadata.org) | Attribution only |

**PA-100K pinned** (step 1, 2026-10-02; files in the controlled source-media store, release record `pa-100k-2017`, first pinned with `determination: null` as SHA-256 `fa8cc479098993582ae3f0adf5292d46cc1749f08901aa096a3d81a8df25e6e7`; since the narrow R-5 determination of §11 it is SHA-256 `bec9a026c8afe53a90a4a93ed94b5d3f67d45525daead0b7596fe96f76eec558`, with every pinned file unchanged):

| File | Bytes | SHA-256 |
|---|---|---|
| `README.txt` | 794 | `c2f4b84c3ab0c1450cfc2c96be5c46c37d19a1f7c4012539acba6fb7d9b6e794` |
| `annotation.zip` | 338,633 | `64411ff2fc1c44b4d77b9da7b6da51d2f67f6af004b7927efbebe34b526cb3e9` |
| `data.zip` | 450,818,381 | `ded122754063d30c06f9c2a407c189130a9034fecde353fd1cd12e4c499b889b` |
| licence statement (HydraPlus-Net `README.md` @ `2b056d36d670d8760c1caea65802534703c1379f`) | 7,686 | `cadf4987a4ddc54d247a39f1856441d8e514a3d7824aacb3a65da0d24968235e` |

- **Source:** the official Google Drive folder `0B5_Ra3JsEOyOUlhKM0VPZ1ZWR2M`, linked from that README.
- **`annotation.zip`:** contains `annotation.mat` (579,061 bytes, SHA-256 `2838933c41ba1ca8a76284f47ef671dc4c61d1326fb5899ddac915a1917e96d3`). It is a **MATLAB 5.0 MAT-file**: little-endian, created 2017-07-26. Its variables are `train_images_name`, `val_images_name`, `test_images_name`, `train_label`, `val_label`, `test_label` (n × 26) and `attributes` (26 × 1). The adapter reads it with `scipy.io.loadmat`, under the `scipy` pin.
- **`data.zip`:** stored without compression, with exactly 100,000 members named `release_data/release_data/NNNNNN.jpg`. These are UPAR's keys without its `PA100k/` prefix.

**UPAR pinned** (2026-10-02): files in the controlled source-media store, release record `upar-challenge-2027-a19ab2fb`, first pinned with `determination: null` as SHA-256 `3889472a59b2f54edce14ce16488b4e8f9ba21482c1f7a73d95a0d376299384c`; since the narrow R-5 determination of §11 it is SHA-256 `b6bec458b8d847a358584eceab96888b413317c5e4b6ddd873dbb82533cd4b22`, with every pinned file unchanged. The licence statement is the README at the pinned revision (SHA-256 `03af31a3cbb6a5fe95336b81793b8c7f68e56b80bf00e92b821b2ee49e948a0e`).

**UPAR format** (probed at the pinned revision; probe files deleted; summary retained here):
- **Header and rows:** UTF-8 CSV. The header line is `# image,` followed by 40 attribute names. Each row is `PA100k/release_data/release_data/NNNNNN.jpg` (or a Market1501 or PETA path) followed by 40 integers in {0,1}.
- **Colour columns:** 12 per region, `{Upper,Lower}Body-Color-{Black,Blue,Brown,Green,Grey,Orange,Pink,Purple,Red,White,Yellow,Other}`. Bags and hat are `Accessory-Backpack`, `Accessory-Bag` and `Accessory-Hat`.
- **Use only `task1/*/gt.csv`.** The top-level `data/annotations/train.csv` header lacks the `image` column (40 names over 41 cells).
- **PA-100K coverage:**
  - `task1/train/gt.csv` covers **79,001 of the 80,000 official train images**;
  - `task1/val/gt.csv` covers **9,986 of the 10,000 official test images**;
  - **no official PA-100K val image has UPAR truth**.
- **Encoding:** every PA-100K row has at least one positive colour per region; UPAR removed images with unknown colour. Multiple positives: upper 177, lower 49 (train); upper 18, lower 9 (test).
- **Missing truth stays missing.** Images absent from UPAR have no colour label, and none is ever inferred.

**Not selected first, among the sources reviewed:**
- PETA: research-only; split not identity-disjoint; withdrawn constituents.
- RAP: no-transfer agreement; indoor mall.
- Market-1501 attributes: no licence; labels per identity.
- MSP60K, VRAI: no licence stated.
- UFPR-VCR/VeSV: academic e-mail eligibility unconfirmed; the VeRi alternative.
- CompCars, VehicleID, CityFlow: restrictive agreements; unclear colour labels.
- MOT17/20: licence unverifiable today.
- UA-DETRAC, BDD100K, IDD: no colour labels, or a moving camera.
- Duke- and Oxford-derived sets: withdrawn.

## 3. Clearance: structure, authorisation, disposition

### 3.1 Release record (structure)

`mavi-attribute-dataset-release-v1` lives in the controlled store and holds no imagery. Fields:
- `releaseId`, name and version, `officialUrl`;
- pinned revision or receipt evidence;
- `licence {codes, url, textSha256}`;
- `files [{path, sizeBytes, sha256}]`;
- `excludedMembers [{path, reason}]`;
- `determination` (#138 shape, parsed by the shared structural parser);
- `knownExposure`.

**Binding rules:**
- Files are placed by the operator. The importer refuses any file whose size or SHA-256 differs, and any excluded member.
- There is no network code.

### 3.2 Intended-use authorisation (separate from parsing)

A new shared function, `determination_blockers(determination, licence_code, purposes)`, is factored out of `purpose_approval_blockers`. Both the Commons path and the dataset path call it. Commons video and revision checks stay Commons-only.

A dataset use is authorised only when `authorise_release_use(release, purposes, operations, member)` returns no blockers.

**Operations are a separate check from purposes.** Each purpose requires a pinned set of dataset operations (`PURPOSE_OPERATIONS` in code):

| Purpose | Required operations |
|---|---|
| `benchmarking`, `selection`, `regression-challenge`, `development` | `evaluate` |
| `tuning` | `evaluate`, `create-derivatives` (thresholds and parameters derived from the data) |
| `training` | `train`, `create-derivatives` |

- The checked set is the union of the operations each requested purpose requires and any extra `operations` the caller names.
- `run-operationally` and redistribution are never dataset-use operations here. They belong to the artefact and its route, through `artefact_disposition` (§3.3), so they are not checked twice.
- Granting a purpose never implies an operation.

**The rights inventory.** `determination.rights.inventory` lists each operation as `granted`, `not-granted`, `not-stated` or `pending-r5`. The dataset structural parser requires every operation key, with only those status values.

`authorise_release_use` returns a blocker for each of the following:
- rights not `PERMITTED_FOR_ENGINEERING_USE`, or with no `reviewedBy`/`evidence` (empty or denied);
- privacy with no `reviewedBy`/`basis` (empty or denied);
- the release licence code not in `licenceCodes`;
- a purpose not covered by `determination.purposes`;
- an operation whose status is not `granted`:
  - `not-granted` gives `rights-operation-not-granted:<op>`;
  - `not-stated` or `pending-r5` gives `rights-operation-pending-r5:<op>`;
  - both are blocking;
- an R-5 ruling `PERMITTED` with `ruledBy`/`reference` missing when the licence is share-alike, NC/ND, unrecognised or bespoke terms;
- an excluded member.

For datasets, NC/ND or bespoke terms are acceptable only when R-5 rules them `PERMITTED` and grants the operations used. R-5 interprets the inventory. The Commons rule is unchanged: NC/ND stays blocked there.

### 3.3 Artefact disposition (lineage, not dataset-wide inheritance)

Here "packageable" means a **MAVI engineering disposition for one artefact and one delivery route**. It is not a legal conclusion; R-5 owns interpretation.

- **Rights inventory.** Each determination records the rights inventory from MSR §5, for the declared non-commercial profile, as granted / not granted / not stated:
  - evaluate;
  - train or fine-tune;
  - create derivatives;
  - run operationally;
  - redistribute weights or derived weights for the delivery route.
- **Lineage.** An artefact (head, calibration, threshold, output mapping) records its **actual lineage**: the releases whose images or labels its producing step read, per attribute.
- **Disposition rule.** `artefact_disposition(lineage, operations, route)` returns `CLEARED` only if every release in the lineage grants every right that the artefact's producing operations and its route exercise. The routes are `local-acquisition` (`run-operationally`) and `offline-kit` (adds `redistribute-derived-weights`). Otherwise it returns `NOT_COVERED` (a right not granted, or privacy denied) or `PENDING_R5` (any other gap). Unresolved rights stay blocked. Each inventory is recorded for the declared non-commercial profile, so the profile is implicit in the determination.
- **Consequences:**
  - **Evaluation produces results, not artefacts**, so evaluation-only data never enters a training lineage.
  - **A presence head trained on PA-100K labels has a PA-100K-only lineage**, even though UPAR colour labels sit in the same manifest.
- **Timing.** This slice implements the function and its tests. Wiring it into training manifests and pack `component-provenance` happens in S2c.6. No Model Pack changes here.

### 3.4 Role → purpose mapping (explicit, validated)

| Manifest role | Required authorised purpose |
|---|---|
| `training` | `training` |
| `development` | `tuning` |
| `selection` | `selection` |
| `benchmark` | `benchmarking` |
| `regression` | `regression-challenge` |
| diagnostics (support, prevalence, smoke runs) | `development` |

The builder refuses a sample when any release supplying that sample's image **or the label used for that attribute** lacks the mapped purpose. There is no frozen role. Public origin is refused for `frozen-qualification` by `provenance.parse_purposes`.

## 4. Records and import seam

New package `tools/qualification/attributes/datasets/`, using the standard library, Pillow and the canonical helpers.

| Record | Schema | Location | Content |
|---|---|---|---|
| Release | `mavi-attribute-dataset-release-v1` | store | §3.1 |
| Label mapping | `mavi-attribute-label-mapping-v1` | Git (`attributes/datasets/data/mappings/`) | per source label → `value`, `source-binary` (positive or negative under source semantics), `unscorable:<reason>`, `merged:<set>`, `unsupported` or `unmapped`; plus `coverage` notes (what a MAVI attribute's definition includes that the source does not) |
| Still dataset | `mavi-attribute-still-dataset-v1` | store | release and mapping hashes; per sample: `sampleId` (image SHA-256), `releaseId`, member path, `sourceSplit`, `group {id, kind: authentic \| synthetic-allocation}`, `role`, and per attribute `{truth: present \| missing, outcome, value, semantics: source-native \| proxy, labelReleaseId}`; the dedup report hash |
| Component result | `mavi-attribute-component-result-v1` | store | §8, including the evidence binding (not implemented yet) |

**Adapter seam:** `adapters/<source>.py` yields neutral rows (`memberPath`, `sourceSplit`, `group`, `labels {sourceLabel: int}`). PA-100K and UPAR share this seam, and VeRi uses it later.

**Builder steps:**
1. join on the exact image path, then verify the image hash;
2. apply the mappings;
3. authorise per §3.4;
4. assign roles;
5. deduplicate;
6. write canonically, byte-identical on rerun.

**CLI:** `attribute_dataset_cli.py` with `verify-release`, `build`, `verify` and `measure`.

## 5. Label mapping (conservative)

| MAVI attribute | Source label → mapping | Coverage limits recorded |
|---|---|---|
| upper / lower colour | UPAR `*-Color-{11}` → the 1:1 value (the names match MAVI's 11 at the pinned revision); `Other` → `unmapped`, never `multicolour`; more than one positive → `unscorable:ambiguous`, never a single colour | `multicolour` is not represented. Images missing from UPAR → truth `missing` |
| backpack | PA-100K `Backpack` → `source-binary` (positive or negative under PA-100K semantics) | source semantics, not shown equivalent to annotation guide §5.1 |
| bag | PA-100K `HandBag` OR `ShoulderBag` → `source-binary`, **proxy**; `HoldObjectsInFront` → `unmapped`, never a bag | the proxy may miss totes, briefcases and shopping bags that MAVI counts |
| headwear | PA-100K `Hat` → `source-binary`, **proxy** for a subset of MAVI headwear | `Hat=0` is not evidence that a helmet, hood or headscarf is absent |
| vehicle colour (vertical 2) | **provisional** until the received release's native table is checked: black, white, red, blue, yellow, green, brown, orange → 1:1; gray → `merged:{grey,silver}` (evaluation only; MAVI's vocabulary is unchanged); golden → `unmapped` | no beige or multicolour; light conditions are not derivable from labels |

UPAR's `Accessory-*` columns are not used as truth in vertical 1. They are a separately licensed second opinion and may be reported as an agreement diagnostic only.

## 6. Splits, groups and deduplication

**PA-100K** (official splits preserved; it publishes no identity or tracklet IDs):
- train (000001–080000) is cut into **synthetic allocation groups** of 500 consecutive indices. A seeded 10% of those groups goes to `selection`, the rest to `training`.
- val → `development`. It has no colour truth; colour development uses no data in this slice.
- test → `benchmark`, complete and never used for training or selection.
- Synthetic groups are **not** identity- or tracklet-disjoint, so leakage between training and selection is possible and is disclosed in every result.

**VeRi-776** (authentic vehicle-ID groups):
- the complete published test set (test plus query) → `benchmark`;
- `development` and `selection` are seeded vehicle-ID fractions of the published train set;
- a vehicle ID never spans roles;
- the official ReID protocol is untouched. Colour evaluation is named the **MAVI VeRi colour protocol v1**.

**Deduplication:**
**Exact SHA-256 duplicates** are resolved by one deterministic rule. A group is all members with the same image SHA-256. Every drop and refusal is recorded.
1. **Within one role:** keep the lowest member path; drop the rest.
2. **Training against any evaluation role** (`development`, `selection`, `benchmark`, `regression`): remove every training copy. Evaluation copies are never lost to training, and benchmark material never reaches training.
3. **`benchmark` against another evaluation role:** keep the benchmark copy, and remove the others from their roles.
4. **Two or more of `development`, `selection` and `regression`, with no benchmark copy:** **refuse the build** (`duplicate_role_conflict`), listing the group. It is resolved only by an explicit `excludedMembers` entry. No precedence is guessed.

Rules apply in that order, and the output is byte-identical on rerun.

**Near duplicates** are a screening report only and never delete anything.
- **Seam:** extract the pigeonhole index from `duplicates.find_pairs` into a neutral primitive, `pigeonhole_pairs(values: {id: dhash64}, threshold, same_group=None)`, and make `find_pairs` call it.
  - With a threshold t < 8, two hashes within distance t share at least one exact byte, so only ids sharing a byte bucket are compared.
  - The corpus behaviour is unchanged, pinned by the existing duplicate tests.
  - The still path calls the primitive with no `CorpusManifest`.
  - No all-pairs comparison is introduced.
- **Bucket cap:** within a bucket the comparison is still pairwise. A bucket over a pinned size cap (2,048 members) is reported as `degenerate-bucket` with its count and is not expanded. This happens with low-texture images.
- **Report bounds:** threshold Hamming ≤ 4. Cross-role pairs come first, then pairs within a role, each ordered by (distance, a, b). At most 10,000 pairs are kept, and the totals are reported.
- **Exclusion** needs an explicit `excludedMembers` entry. Colour-distinct images are never removed because of a dHash match.

**Contamination notes** go in every result:
- known exposure, for example PO-7 trained on PA-100K;
- broad use of PA-100K and VeRi in pretraining;
- the synthetic-group caveat.

## 7. Baselines in this slice (honest identities)

- **`mavi-dev-colour-probe-v1`.** A development probe, **not PC-B0/VC-B0**; nothing about PC-B0/VC-B0 is fixed by it.
  - **Configuration file:** its full configuration lives in a committed file, `attributes/datasets/data/mavi-dev-colour-probe-v1.json`, which says "development probe; not PC-B0/VC-B0".
  - **Method identity:** the SHA-256 of that file in canonical JSON, recorded in every result.
  - **Code reads every value from the file;** no numeric constant lives in code. The file must specify:
    - **regions:** upper is rows 15–50% of crop height, lower is rows 55–90%, both over the central 60% of width; pixel bounds are `floor` of the fractional bounds; vehicle uses the central body band defined in the same file;
    - **decoding:** Pillow decode → 8-bit RGB (`convert("RGB")`, which drops alpha and expands greyscale), with no resize;
    - **conversion:** sRGB per IEC 61966-2-1 (linearisation with threshold 0.04045), the sRGB→XYZ matrix, the D65 reference white (Xn, Yn, Zn) and the CIE 1976 L\*a\*b\* formulas, computed in float64 with no quantisation;
    - **centres:** all 11 numeric Lab reference centres for the MAVI colour names; vehicle uses its own 11;
    - **distance:** CIE76 ΔE (Euclidean in Lab);
    - **ties:** a pixel equidistant to several centres takes the first in schema order; a tie between winning names takes the first in schema order;
    - **output:** the most frequent name, with its share;
    - **abstention:** `undecodable` (decode error); `insufficient-area` when the region has fewer than 400 pixels; `ambiguous` when the winning share is below 0.40.
  - **Centre values** are chosen when the probe is implemented and reviewed in that PR. They are not taken from PC-B0, which is undefined, and changing any value changes the method identity.
- **`dataset-prevalence-diagnostic-v1`.** Training-role prevalence per presence attribute, **not PO-B0**, because there is no camera grouping. It is a diagnostic only.

## 8. Metrics (source-native and proxy are never operational)

Each result reports, per attribute and role:
- eligible rows and support per value;
- truth-missing, unsupported and unscorable counts;
- abstentions and the coverage denominator;
- a confusion matrix;
- the `semantics` label: `source-native` (under PA-100K or UPAR definitions) or `proxy` (a subset mapping to a MAVI attribute).

For binary source labels, precision, recall and F1 are reported **as source-native**. Negatives are source zeros, not MAVI `absent`. No result is named MAVI operational accuracy or F1, and no full bag or headwear coverage is claimed.

**Only real predictions get confusion and F1.** In this slice that means colour, from the probe. Backpack, bag and headwear get support, prevalence and the missing, unsupported and unscorable counts only, until a real per-sample presence predictor exists. `dataset-prevalence-diagnostic-v1` is never treated as a predictor.

**Evidence binding (a hard contract for the result schema; not implemented yet).** Every component result must carry:
- the exact still-dataset manifest SHA-256. From it, the release records, mapping tables, roles and dedup report are recovered transitively;
- the method identity, which is its configuration SHA-256 (for example the colour-probe configuration);
- the executing code identity: the Git commit, a local-changes flag, and module hashes, as `review_inventory` already records.

A result without all three is refused.

## 9. Implementation sequence

| # | Step | Tests first (each kills a plausible mutant) | Done when |
|---|---|---|---|
| 1 | Pin PA-100K (archive SHA-256s; probe the annotation-file format locally and record it here; if it is MATLAB v5, reuse the `scipy` pin already in `vision-runtime` and update `offline-dependency-policy-v1.json` in the same change). The VeRi request goes out in parallel | — | pinned files and format summary committed |
| 2 | Release verification and authorisation: shared `determination_blockers`, `authorise_release_use`, `artefact_disposition` | empty rights; empty privacy; denied rights or privacy; purpose not covered; licence not covered; missing R-5 for NC-SA or bespoke terms; excluded member; purpose allowed but a required operation `not-granted` → blocked; purpose allowed but an operation `not-stated`/`pending-r5` → blocked as pending R-5; an evaluation purpose with only `evaluate` granted → permitted; `training` without `train` granted → blocked; a valid purpose with every required operation granted → permitted; a valid release determination reused across all members; Commons tests unchanged | §3 enforced |
| 3 | PA-100K and UPAR adapters behind the neutral row seam | synthetic rows in the real formats; the UPAR `task1` header is required; the misaligned top-level CSV is refused; unknown labels refused | — |
| 4 | Person still manifest | official splits preserved; benchmark never in training or selection; group `kind` recorded; exact duplicates: training vs benchmark, vs selection and vs development (the training copy is removed), selection vs benchmark (the benchmark copy is kept), development vs selection with no benchmark copy → refused; near duplicates: colour-distinct images with an identical dHash are reported and never removed, a known Hamming-near pair is found, a Hamming-far pair is not returned, cross-role pairs come first, the bounded ordering is deterministic, a degenerate bucket is capped, and `pigeonhole_pairs` keeps the corpus duplicate tests green (no all-pairs path); role→purpose refusal; per-attribute label lineage; no frozen role; byte-identical rerun; a deterministic smoke subset (seeded 2,000 images) | manifest built |
| 5 | First person results: support and prevalence for every attribute; source-native and proxy confusion for colour only (probe predictions); missing, unsupported and unscorable counts; the evidence binding of §8 | hand-computed fixtures; denominators include abstentions; proxy and source labels kept apart; probe output reproduced from its configuration file alone; changing one centre changes the method identity; pixel and winner ties follow schema order; each abstention reason is triggered | smoke result, then a full benchmark-role result |
| 6 | VeRi vertical, after access is granted and its native colour table is verified | VeRi ID groups never span roles; the full published test set is the benchmark; gray merged for evaluation only | VeRi result |
| 7 | Optional MEVA step | below | smoke run, or a recorded skip |

**MEVA binding** (only if it is exercised):
- Each clip gets an external import receipt `{releaseRecordSha256, memberPath, memberSha256, determinationSha256, purposes, placedAtUtc}`. That receipt's SHA-256 — not the release-record hash — is the source's `acquisitionReceiptSha256`.
- Clips go through MAVI Development ingestion as a public-origin, frozen-ineligible corpus revision (#138).
- A fixture-score run proves **pipeline structure only**. Track attribute quality needs MAVI labels on at most 150 Tracks and a real inferencer, so it is follow-on work.

**Workload bounds (not adequacy thresholds):**

| Item | Bound |
|---|---|
| Releases | 3 still releases (PA-100K, UPAR annotations, VeRi-776) and at most 1 video release |
| Images | the published files |
| Video | at most 6 clips, 30 minutes in total |
| Storage | at most 15 GB |
| Code | 3 adapters, 3 mapping tables |
| Human review | 3 release determinations, 1 R-5 session; track labels only if MEVA proceeds |

## 10. Acceptance criteria (first slice)

**Met when:**
- releases are pinned and their bytes verify by hash;
- structural parsing and intended-use authorisation are enforced separately;
- PA-100K and UPAR import through one adapter seam;
- official splits are preserved;
- authentic and synthetic groups are distinguished;
- exact duplicates follow the explicit role rule for every role combination, with conflicts refused;
- near-duplicate discovery uses the shared pigeonhole primitive and cannot delete colour-distinct images;
- authorisation checks both purposes and the rights-inventory operations they exercise;
- mappings are explicit and hash-bound;
- missing, unsupported and unscorable rows are counted;
- source-native and proxy metrics never present themselves as MAVI operational metrics;
- baselines carry honest identities, and the colour probe is reproducible from its hash-bound configuration;
- disposition follows actual lineage and the delivery route;
- public stills cannot become frozen-qualification data;
- the person vertical produces reproducible component measurements while VeRi and MEVA are still pending.

**Run before merging:** the full `tools/qualification/tests`, `tools/verify_repo.py` and `git diff --check`.

**Non-goals:**
- candidate training;
- SigLIP, DINOv2 or OMZ execution;
- Model Pack changes;
- frozen-qualification work;
- B0 changes;
- a generic downloader;
- corpus-manifest changes for stills;
- new policy;
- further dataset surveys unless a pinned release proves unusable.

## 11. Rights items (R-5 owns interpretation) and follow-on

**Rights items:**
1. PA-100K: the rights inventory for the declared non-commercial profile, given undocumented capture rights; a privacy basis for internal processing of surveillance crops.
2. UPAR: whether NC-SA covers the requested purposes, and whether share-alike attaches to labels or artefacts derived from them.
3. VeRi-776: the owner's written request and the reply recorded as evidence; R-5 maps it to the inventory.
4. MEVA: attribution notice.

**Narrow R-5 determination for items 1 and 2 (2026-10-02).**
- **Decision.** Aarav, R-5 Licence Review Owner, approved by phone ("I agree. Go ahead. All the best for your work.") the narrow request for PA-100K and UPAR Task 1.
- **What it covers:** the `benchmarking` and `development` purposes and the `evaluate` operation, for internal, local, offline, non-commercial research evaluation. It also covers:
  - PA-100K privacy processing for that use (the reply states no separate privacy basis, and the records assert none beyond this scope);
  - for UPAR, that evaluation and the reporting of its metrics under the NC/SA terms.
- **Still `pending-r5`:** `train`, `create-derivatives`, `run-operationally` and `redistribute-derived-weights`. Training, tuning and selection are not covered.
- **Not decided:** whether NC/SA obligations attach to trained heads, tuned thresholds, weights or other derived artefacts.
- **Evidence.** The reply was relayed verbatim by the MAVI owner; no screenshot or e-mail exists. The request is kept as prepared, not as transmitted. The relay and the request package are kept, outside Git, in `E:\MAVI-Controlled\Evidence\S2c\2026-10-02-r5-pa100k-upar-eval`, whose decision record has SHA-256 `68b1f7386c7a24dfc53ce4abe4d5c23c8df8f00d4f203d50486d8e6d47ef83a4`.
- **Step 5 canonical evidence.** Built on `main@699e7672` with no local changes, from the retained release records, and kept outside Git in `E:\MAVI-Controlled\Processing\S2c\2026-01\s2c-step5-person-component-2026-10-02`. Every rerun is byte-identical.

  | Run | Benchmark rows | Rows refused by role purpose | Manifest SHA-256 | Benchmark result SHA-256 |
  |---|---|---|---|---|
  | Smoke | 200 | 1,800 | `703e43cbbba82b40b101838daf9500f60f6d25ee15ac829a4835b5f522f0dde0` | `c0ff58cbbfb94093b3037d7685b8c26a15f000e1136bb6f0b8cc9b67396163d9` |
  | Full | 10,000 | 90,000 | `9eb1cedcb088eeb0233a6926b16013858e12f933943a2585ebced19c63d5e50b` | `d929cc092bfc39b7de6d14dc0ef5c69d916290da6a85ff5954110133e3858898` |

  Training, development and selection rows are refused because their roles map to `training`, `tuning` and `selection`.

**Follow-on:**
- S2c.3 evaluation environment and candidate runners on these manifests;
- wiring `artefact_disposition` into training-manifest and pack provenance (S2c.6);
- MAVI's own labels where a gap or a rights limit is measured;
- further sources only against measured gaps;
- protected capture for the frozen test, kept separate.
