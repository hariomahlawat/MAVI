# Stage 2 S2c — public-data slice for person attributes and vehicle colour (C+)

> **For agentic workers:** implement vertical by vertical, with tests first. This plan authorizes no training, no candidate-model execution, no frozen-qualification work and no change to B0 records.

**Status:** plan, amended after review (rev 2).
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
| 1 (person) | **UPAR** colour labels, PA-100K rows only | `github.com/speckean/UPAR-Challenge-2027` @ `a19ab2fb6470140606d3c1982c303937b58fbd14` (2026-09-21); files `data/annotations/task1/train/gt.csv` (SHA-256 `31ba2922558da52411a8ea25de3962a3b0b1d253af23566c16503a04e09ecef7`) and `data/annotations/task1/val/gt.csv` (SHA-256 `783be600e359052c9dafe856cbfa2aee45bbd4e3eac10309394e2388bcf7c2bc`) | annotations "CC BY-NC-SA 3.0" (DE); "source image datasets retain their respective licenses" | Format summary below; R-5 item 2 |
| 2 (vehicle) | **VeRi-776** | the release received by e-mail, pinned at receipt (archive SHA-256 and the native colour table) | "used for non-commercial purposes" (vehiclereid.github.io/VeRi) | Owner request with the scope of use; R-5 item 3 |
| optional | **MEVA**, at most 6 static ground-camera clips | a list of S3 object keys and SHA-256s, pinned before any download | "All MEVA data is available for use under a CC BY-4.0 license" (mevadata.org) | Attribution only |

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

A dataset use is authorised only when `authorise_release_use(release, purposes, member)` returns no blockers. It returns a blocker for each of the following:
- rights not `PERMITTED_FOR_ENGINEERING_USE`, or with no `reviewedBy`/`evidence` (empty or denied);
- privacy with no `reviewedBy`/`basis` (empty or denied);
- the release licence code not in `licenceCodes`;
- a purpose not covered by `determination.purposes`;
- an R-5 ruling `PERMITTED` with `ruledBy`/`reference` missing when the licence is share-alike, NC/ND, unrecognised or bespoke terms;
- an excluded member.

For datasets, NC/ND or bespoke terms are acceptable when R-5 rules them `PERMITTED` for the requested purposes. The Commons rule is unchanged: NC/ND stays blocked there.

### 3.3 Artefact disposition (lineage, not dataset-wide inheritance)

Here "packageable" means a **MAVI engineering disposition for one artefact and one delivery route**. It is not a legal conclusion; R-5 owns interpretation.

- **Rights inventory.** Each determination records the rights inventory from MSR §5, for the declared non-commercial profile, as granted / not granted / not stated:
  - evaluate;
  - train or fine-tune;
  - create derivatives;
  - run operationally;
  - redistribute weights or derived weights for the delivery route.
- **Lineage.** An artefact (head, calibration, threshold, output mapping) records its **actual lineage**: the releases whose images or labels its producing step read, per attribute.
- **Disposition rule.** `artefact_disposition(lineage, profile, route)` returns `CLEARED` only if every release in the lineage grants every right that the artefact's use and route exercise. Otherwise it returns `NOT_COVERED` or `PENDING_R5`. Unresolved rights stay blocked.
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
| Component result | `mavi-attribute-component-result-v1` | store | §8 |

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
- **Exact SHA-256 duplicates** are resolved deterministically. Within a role, keep one sample (lowest member path). Across roles, drop the copy from the non-benchmark role. Every drop is recorded.
- **Near duplicates:** `dhash64`/`hamming` produce a **bounded candidate report** (Hamming ≤ 4; at most 10,000 pairs; cross-role pairs first). The report never deletes anything. Exclusion needs a listed `excludedMembers` entry (stronger confirmation). Colour-distinct images are never removed because of a dHash match.

**Contamination notes** go in every result:
- known exposure, for example PO-7 trained on PA-100K;
- broad use of PA-100K and VeRi in pretraining;
- the synthetic-group caveat.

## 7. Baselines in this slice (honest identities)

- **`mavi-dev-colour-probe-v1`.** A development probe, **not PC-B0/VC-B0**; nothing about PC-B0/VC-B0 is fixed by it. Pinned in code, with its method identity as the SHA-256 of its parameters:
  - **regions:** upper is rows 15–50% of crop height, lower is rows 55–90%, both over the central 60% of width;
  - **conversion:** sRGB → CIE-Lab (D65) by the standard formulas;
  - **naming:** per pixel, the nearest of 11 fixed Lab reference centres;
  - **output:** the most frequent name;
  - **abstains** when the crop is undecodable, the region is under 400 pixels, or the winning share is below 0.40.
- **`dataset-prevalence-diagnostic-v1`.** Training-role prevalence per presence attribute, **not PO-B0**, because there is no camera grouping. It is a diagnostic only.

## 8. Metrics (source-native and proxy are never operational)

Each result reports, per attribute and role:
- eligible rows and support per value;
- truth-missing, unsupported and unscorable counts;
- abstentions and the coverage denominator;
- a confusion matrix;
- the `semantics` label: `source-native` (under PA-100K or UPAR definitions) or `proxy` (a subset mapping to a MAVI attribute).

For binary source labels, precision, recall and F1 are reported **as source-native**. Negatives are source zeros, not MAVI `absent`. No result is named MAVI operational accuracy or F1, and no full bag or headwear coverage is claimed.

## 9. Implementation sequence

| # | Step | Tests first (each kills a plausible mutant) | Done when |
|---|---|---|---|
| 1 | Pin PA-100K (archive SHA-256s; probe the annotation-file format locally and record it here; if it is MATLAB v5, reuse the `scipy` pin already in `vision-runtime` and update `offline-dependency-policy-v1.json` in the same change). The VeRi request goes out in parallel | — | pinned files and format summary committed |
| 2 | Release verification and authorisation: shared `determination_blockers`, `authorise_release_use`, `artefact_disposition` | empty rights; empty privacy; denied rights or privacy; purpose not covered; licence not covered; missing R-5 for NC-SA or bespoke terms; excluded member; a valid release determination reused across all members; Commons tests unchanged | §3 enforced |
| 3 | PA-100K and UPAR adapters behind the neutral row seam | synthetic rows in the real formats; the UPAR `task1` header is required; the misaligned top-level CSV is refused; unknown labels refused | — |
| 4 | Person still manifest | official splits preserved; benchmark never in training or selection; group `kind` recorded; exact duplicates deterministic; a colour-distinct dHash collision is not removed; the near-duplicate report is bounded; role→purpose refusal; per-attribute label lineage; no frozen role; byte-identical rerun; a deterministic smoke subset (seeded 2,000 images) | manifest built |
| 5 | First person results: support and prevalence, source-native and proxy confusion, missing, unsupported and unscorable counts, colour probe output | hand-computed fixtures; denominators include abstentions; proxy and source labels kept apart | smoke result, then a full benchmark-role result |
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
- exact duplicates are resolved deterministically, and near-duplicate screening cannot delete colour-distinct images;
- mappings are explicit and hash-bound;
- missing, unsupported and unscorable rows are counted;
- source-native and proxy metrics never present themselves as MAVI operational metrics;
- baselines carry honest identities;
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

**Follow-on:**
- S2c.3 evaluation environment and candidate runners on these manifests;
- wiring `artefact_disposition` into training-manifest and pack provenance (S2c.6);
- MAVI's own labels where a gap or a rights limit is measured;
- further sources only against measured gaps;
- protected capture for the frozen test, kept separate.
