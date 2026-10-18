# Stage 4 — LRLPR-26 Dataset Release Record (ADR-017 §7)

**Date:** 2026-10-18.
**Class:** Development data intake: acquisition and validation only. No training, experiment or Production change.
**Descriptor:** `docs/qualification/stage4/benchmarks/lrlpr-26.descriptor-template.json` (`benchmark-dataset-release-v1`). Its manifest is empty, as for the other Stage-4 templates. No adapter exists yet (see *Adapter*).

This record holds counts and hashes only. Dataset bytes, images, plate strings and per-track text are not in Git.

## Provenance and permission

- **Dataset.** LRLPR-26, Laroca et al., ICPR 2026, pp. 256–275 (doi 10.1007/978-3-032-31936-4_18; arXiv 2604.22506).
- **Official reference.** https://github.com/raysonlaroca/lrlpr-26-dataset (README, `license-agreement.pdf`) and https://icpr26lrlpr.github.io/.
- **Provenance basis (owner decision, recorded verbatim).** "obtained by the owner's team through the official LRLPR-26 agreement; mirror held by the owner's team; owner attestation 2026-10-18; signed agreement and original download confirmation held by owner".
- **Retrieved from.** The owner's team mirror, on 2026-10-18:
  - one GitHub LFS object, `data.zip`, in https://github.com/qwerty070806/lrlpr-2026;
  - three Dropbox shared files, linked from that repository's `Dataset_download_links.txt`.
  The share links are not reproduced here.
- **Not accessed.** Zenodo record 20422103, which is restricted (HTTP 403).
- **Status.** `RESEARCH-ADMISSIBLE`. **Permission: RESOLVED (owner confirmation, 2026-10-18).** The project owner confirms that LRLPR-26 was obtained with the dataset authors' permission and is used in accordance with the applicable licence agreement for academic, non-commercial research.
- **Basis of this record.** The owner's confirmation. The agent did not inspect the agreement or any correspondence with the authors, and claims nothing beyond the confirmation.
- **Earlier wording superseded.** An earlier revision of this record (`792b9f3b`) treated permission as an open question. It is superseded by the owner's confirmation and is not pursued further unless contradictory evidence arises.
- **Unchanged.** The use restrictions below, the provenance chain, the hashes and the controlled-storage requirements all still apply. MAVI holds a local research copy only and does not redistribute it.

## Use constraints

- Academic, non-commercial research only.
- No redistribution or modification without the authors' permission. The data is:
  - never re-hosted or uploaded;
  - never committed;
  - never placed in a MAVI Runtime Pack, the developer offline cache, or any shared or offline bundle.
- `config/dependencies/offline-dependency-policy-v1.json` therefore gains no entry: the dataset is not a dependency and is never packaged.
- Images may appear only in academic publications and presentations. Cite Laroca et al., ICPR 2026.
- The data is held on owner-controlled local storage only, at `E:\MAVI-Controlled\Benchmarks\lrlpr-26\`.

## Archives

| Source | Archive | Bytes | SHA-256 |
|---|---|---:|---|
| GitHub LFS (`qwerty070806/lrlpr-2026`) | `data.zip` | 619,329,117 | `46e25df0adddbd5b08c9ca4576d9e656fa7d43d2a5dec3b40e206714f9a7a667` (equals the LFS pointer oid) |
| Dropbox | `train.zip` | 719,723,859 | `fb95f86dbf5666ce7d2f577605d55516f9ec558d25944f870dfca8b7f7c9fb8f` (corrected 2026-10-18; see below) |
| Dropbox | `test-public.zip` | 6,034,618 | `9259c908655a792d9373030d36e0358369d269df5750134512318587418bf580` |
| Dropbox | `test-blind.zip` | 18,131,638 | `be90a89153bebc4a6c55a988e01fbb91e0f2a5ec28296c59e5bbaecb794355a1` |

- `data.zip` contains `train.tar`, `test-public.tar` and `test-blind.tar`.
- **Correction, 2026-10-18 (before the aggregation protocol froze).** Revisions up to `e0cce486` gave the `train.zip` SHA-256 as `fb95f86d8f5666ce…`; the 10th hex digit was mistyped (`8` for `b`). The held archive hashes to the value above, with the byte count unchanged. Before the correction, all 220,000 file members of `train.zip` were compared with `data.zip`'s `train.tar`, which matches its Git LFS oid: same paths, same bytes. The other three archive hashes were already correct.
- Every member of the three tars is byte-identical to the same path in the Dropbox zips: 200,000 + 5,000 + 15,000 images, and 20,000 annotation files with identical text. The two sources are one release, so neither adds data the other lacks.
- Extraction was checked before writing. Every archive had zero absolute paths, zero `..` entries, zero links or special members and zero encrypted entries. The uncompressed totals were checked against free space, and the highest per-entry compression ratio was 6.9.
- Per-file SHA-256 manifests are kept locally beside the data. They are not in Git.

## Validated contents (Pillow, read-only decode of every image)

| Split | Tracks | Images per track | Images | Annotations | Decode failures |
|---|---:|---|---:|---|---:|
| train, Scenario A, Brazilian | 5,000 | 5 LR + 5 HR (PNG) | 50,000 | text, layout, corners | 0 |
| train, Scenario A, Mercosur | 5,000 | 5 LR + 5 HR (PNG) | 50,000 | text, layout, corners | 0 |
| train, Scenario B, Brazilian | 2,000 | 5 LR + 5 HR (JPEG) | 20,000 | text, layout | 0 |
| train, Scenario B, Mercosur | 8,000 | 5 LR + 5 HR (JPEG) | 80,000 | text, layout | 0 |
| test-public | 1,000 | 5 LR (JPEG) | 5,000 | **none** | 0 |
| test-blind | 3,000 | 5 LR (JPEG) | 15,000 | **none** | 0 |

### Annotations
- Each `annotations.json` holds `plate_text`, `plate_layout` (`Brazilian` or `Mercosur`) and `corners`.
- `plate_layout` agrees with the folder for all 20,000 train tracks. Totals: 7,000 Brazilian and 13,000 Mercosur.
- The normalised text matches the layout's pattern for all 20,000: `LLLNNNN` for Brazilian and `LLLNLNN` for Mercosur. One raw text differs from its normalised form.
- **Corners** (Scenario A only):
  - Every one of the 10,000 tracks has four corners for each of its 10 images.
  - In 28 tracks the image keys carry a doubled extension (`.png.png`).
  - In 2 tracks the coordinates are floats rather than integers.
  - Scenario B has no corners, as the official README states.

### Image sizes
| Images | Width range | Width median | Height range | Height median |
|---|---|---:|---|---:|
| LR | 24–68 | 47 | 12–36 | 19 |
| HR | 50–164 | 108 | 22–61 | 39 |

All images are RGB.

### Track identity
- Track IDs are unique within every split.
- Every image lies in exactly one track directory, and there are no stray files.
- Test track IDs do not reuse train IDs.
- test-public is a strict subset of test-blind: all 1,000 IDs and all 5,000 images are byte-identical.

### Duplicates and repeated plates in train
- **Byte-identical images:** 148 hash groups (252 surplus copies).
  - 128 groups lie within one track; these are repeated frames.
  - 20 groups span tracks, but involve only 4 tracks, and none cross scenarios.
- **Repeated plates:** 1,646 normalised plate texts occur in more than one track, covering 4,700 of the 20,000 tracks. The tracks hold 16,946 distinct texts.
  - No text occurs in both Scenario A and Scenario B.
  - So "one track = one vehicle" does not hold in train. A frozen split must group by plate text as well as by track.

### Test against train
- No test image is byte-identical to a train image.
- The official claim that no test plate appears in train **cannot be checked**, because the held test archives contain no labels.

## Completeness against the official release

| Official release | Held | Status |
|---|---|---|
| 20,000 train tracks (A 10,000 + B 10,000), 5 LR + 5 HR, with annotations | Identical structure and counts | **Complete** |
| 3,000 test tracks, 5 LR each, annotated after the competition | 3,000 test-blind tracks (+ the 1,000-track public subset) with LR images only | **Images complete; test labels absent** |

The held material is the competition-era distribution. The post-competition annotated test is **not** held.

**Test release distinction (dated correction, 2026-10-18).** The two test releases differ:
- **Held:** the competition test archives, test-public (1,000 tracks) and test-blind (3,000 tracks). They contain LR images only and no labels.
- **Official:** the official repository README, as read on 2026-10-18, now documents a release of "the official competition training and test sets, both released with annotations". Its 3,000 test tracks carry LP text and LP layout.

The held test-blind images are presumably the same tracks, but this is unverified without the labelled release. The authorised route to the annotated test is the official request: the signed agreement, e-mailed from a valid university account to the first author. The owner may also already hold it through the team's original approval. MAVI does not use any other copy of the test labels. Until an authorised labelled test is held, every LRLPR-26 measurement is made on a frozen partition of train.

## Suitability

**Supported**, on train tracks with labels:
- five-frame recognition: every track has 5 LR frames, plus 5 HR frames as a reference;
- temporal aggregation, comparing single-best, union, consensus and confidence-calibrated abstention;
- wrong-text and abstention-against-recall evaluation, on a frozen track-level DEVELOPMENT/EVALUATION partition of train, made before any tuning. The partition must:
  - group tracks by normalised plate text;
  - be stratified by scenario and layout;
  - never split frames at random.

**Not supported:**
- **Wrong-Track association.** The data holds plate crops only: no scene, no vehicle boxes, no neighbouring vehicles. LRLPR-26 cannot measure whether MAVI attaches a plate to the correct Vehicle Track.
- **Blind-holdout or official test-set scoring.** The test labels are absent.
- **Indian-domain validity.** The plates are Brazilian and Mercosur only, from two fixed-camera scenarios.

## Known limitations

- **Semi-automatic labels.** The organisers produced the labels by OCR on the HR patches and note that occasional residual errors may exist.
- **Scenario A is UFPR-SR-Plates.** UFPR-SR-Plates is the earlier public release by the same group, so its own train/validation/test split conflicts with any Scenario-A partition.
- **Exposure is possible.** It is a public competition dataset, so public recognisers may have trained on it.
- **Annotation quirks** (the doubled `.png.png` keys and float corners) need tolerant parsing.

## Overlap with MAVI-held datasets (counts only)

| Dataset | Comparison | Result |
|---|---|---|
| UFPR-ALPR | No local copy is held; only the adapter and test fixtures exist | Not measurable. Same group and city (Curitiba), different capture. Check before any cross-dataset use |
| UC3M-LP (train + test; 2,547 plates, all character-masked) | Exact text, and masked-wildcard text, against the 16,946 train texts; SHA-256 of 1,975 images | 0 text matches, 0 wildcard matches, 0 image matches |
| DataCluster Indian sample (25 text labels, 47 images) | Exact text; image SHA-256 | 0 text matches, 0 image matches |

## Adapter

No LRLPR-26 adapter exists in `tools/benchmarks/datasets/`, so none was implemented. Feeding LRLPR-26 into the benchmark framework needs an adapter that:

1. Discovers `train/<Scenario>/<Layout>/track_*/` with `lr-00{1..5}` and `hr-00{1..5}` (PNG for Scenario A, JPEG for Scenario B).
2. Emits one plate-truth item per track, carrying:
   - the frames in order;
   - `plate_text`;
   - layout, mapped to `one-line`;
   - corners when present, with tolerant `.png.png` keys.
   Plate crops have no vehicle box.
3. Reads a frozen partition file (track ID to DEVELOPMENT/EVALUATION, grouped by normalised text) rather than splitting in code.
4. Records the label-provenance caveat and the possible exposure.

The existing `benchmark-plate-truth-v1` contract is built around scene images with plate regions. Whether a crop-track form fits that contract, or needs a contract revision first, is a design decision for the experiment owner.
