# BDD100K MOT 2020 — acquisition and preparation (S3.2d-1 Slice 4)

**Status:** operator instructions for the first real benchmark input. Nothing here downloads data, and nothing in CI does. No real benchmark has been executed; H3 remains OPEN.

## What is used

- **Dataset and release.** BDD100K box tracking, the "MOT 2020" packages: *MOT 2020 Labels* (`box_track_20`, Scalabel format, 115 MB, md5 `6be40e0ca56a83ddeba2ed6bff50f9e6`) and *MOT 2020 Images* (`images/track`). Source: official `doc/source/download.rst` in `github.com/bdd100k/bdd100k`, read 2026-10-04.
- **Split.** `val` only (public labels).
- **Adapter.** `tools/benchmarks/datasets/bdd100k_mot.py` (adapter id `bdd100k-mot`).
- **Descriptor template.** `docs/qualification/stage3/benchmarks/bdd100k-mot-2020.descriptor-template.json`. Its manifest is empty, as it must be before acquisition.
- **Mapping.** `docs/qualification/stage3/benchmarks/bdd100k-mot-2020.mapping.json` (car, truck, bus and motorcycle `exact` with caveats; the rest `unsupported`).

## Acquisition (operator action)

1. Sign in to the official BDD100K user portal (`bdd-data.berkeley.edu`, download page `download.html`) **over verified HTTPS only**, and accept the BDD100K licence there ("I Agree"). The documented host `dl.cv.ethz.ch` no longer resolves in DNS, and on 2026-10-04 the portal's HTTPS certificate named another host (`unlisted.berkeleyvision.org`). A certificate that does not match the portal is a hard stop: never sign in, accept the licence or download over plain HTTP or past a certificate warning. Wait for, or obtain from the dataset maintainers, a verified official HTTPS endpoint. Registration, sign-in and licence acceptance are the operator's own actions: never automated, never bypassed, and download links are never fetched without them.
2. From the portal, download the *MOT 2020 Labels* and the val part of *MOT 2020 Images*. Check the labels archive against the published md5 above, and record each archive's name, size and SHA-256 for the descriptor's provenance.
3. Keep archives, images and labels outside Git and outside the repository working tree, on local storage the operator controls. Never commit dataset bytes, crops, screenshots, derived MP4s or trajectories.

## Canonical source layout

Create one source root that contains **only** the val members, laid out exactly as the official packages name them:

```text
<source-root>/
  labels/box_track_20/val/<videoName>.json
  images/track/val/<videoName>/<frame name>.jpg
```

- Each label file is the per-video Scalabel JSON list as shipped. Do not edit, reformat or merge it.
- Each frame image sits at `<videoName>/<name>`, where `name` is the label record's own field. The adapter reads the path from `name`, never from a frame number. Frame index 0 is `…-0000001.jpg` in the official data.
- Do not keep `train`, `test`, archives or notes under the source root. The frozen manifest covers every file under the root, and other splits only slow reconciliation.

## Freeze, prepare, execute, evaluate

1. Copy the template to a working descriptor outside Git. Set `source.retrievedOn` to the actual download date. Leave everything else unchanged unless the licence accepted at download differs from the quoted text.
2. Freeze the manifest once:

```bash
python -m tools.benchmarks.cli describe --descriptor <working-descriptor.json> --mapping docs/qualification/stage3/benchmarks/bdd100k-mot-2020.mapping.json --freeze-manifest --source-root <source-root> --out <frozen-descriptor.json>
```

3. Prepare the benchmark input with the verified FFmpeg pack:

```bash
python -m tools.benchmarks.cli prepare --descriptor <frozen-descriptor.json> --source-root <source-root> --split val --adapter bdd100k-mot --media-tools <ffmpeg-pack> --out <new-derived-dir>
```

`prepare` reconciles the whole manifest first, so a missing, changed or extra file is refused before any parsing. It then writes canonical ground truth and one labelled-rate MP4 per video at 5 fps.

4. Run MAVI once per prepared video on a fresh, dedicated Development catalogue with the measured S3.2 pipeline profile (the T9 pattern), exporting each run with the T1 export tool:

```bash
python -m tools.benchmarks.cli execute --derived <derived-dir> --pipeline-profile <profile.json> --api http://localhost:<port> --journal <journal.json> --exports <exports-dir> --evidence-root <mavi-evidence-root> --export-exe <export-tool>
```

5. Evaluate, writing the association, result and report once:

```bash
python -m tools.benchmarks.cli evaluate --descriptor <frozen-descriptor.json> --derived <derived-dir> --exports <exports-dir> --evidence-root <mavi-evidence-root> --mapping docs/qualification/stage3/benchmarks/bdd100k-mot-2020.mapping.json --policy <association-policy.json> --requirements <requirements.json> --pipeline-profile <profile.json> --out <results-root>
```

## Derived annotation path for H3-v1 (`bdd100k-mot-coco`)

The raw `box_track_20` labels are currently unavailable from BDD100K's distribution infrastructure. For H3-v1 only, the benchmark may instead use one pinned derivative of the val labels, read by the adapter `bdd100k-mot-coco` (`tools/benchmarks/datasets/bdd100k_mot_coco.py`, descriptor and mapping under `docs/qualification/stage3/benchmarks/bdd100k-mot-2020-cocofmt.*`).

- **Artefact.** `bdd_box_track_val_cocofmt.json` from the MASA authors' Hugging Face repository `dereksiyuanli/masa`, commit `25ed372c47f2c46cf36fd446d1b657b656bc7ea9`, 117,094,032 bytes, SHA-256 `074ff79555483296cf7ccadddeeceeec7a83452c900506dc46588ed3a3e65d5d` (the Hub's LFS object id). The adapter refuses any other file before parsing it. It is a derivative and is never described as the raw release.
- **Conversion lineage.** It is the output of the official conversion `bdd100k.label.to_coco -m box_track` with `configs/box_track.toml`. Its fields are exactly those of Scalabel's `to_coco` box-track converter of April to early May 2021 (`scalabel/scalabel` commits `55cd90e` to `d0a018f`). Unlike today's converter, that version also writes `ignore = 1` for a former distractor.
- **Why it is admissible for Development H3-v1.** The conversion keeps every field H3 scores: video name, frame index, frame file name, the raw label id (`scalabel_id`, used as the track id), the class after the official name mapping, and the box with Scalabel's inclusive `x2, y2`. The adapter inverts the box and clips it exactly as the raw adapter does, so an ordinary label yields the same ground truth. The adapter itself verifies only the SHA-256. Before an H3 run, the operator runs the `lineage` check below and records its result with the run.
- **Lineage reference.** The raw reference is `scalabel/scalabel` at commit `071d073598e7c988134dc70a5c0c52761226bf42`, path `tests/eval/testcases/box_track/track_sample_anns.json`, git blob `3e19c83dba4b2b3e222d9db61d5888b049a60fcf`. It holds val video `b1c66a42-6f7d68ca` in full: 202 frames and 3,241 labelled boxes, with string ids, fractional boxes, classes and crowd flags. Its 202 frame names are exactly that video's JPEGs in the val image package. `lineage` compares the exact raw and derived frame-index sets, file names, track ids, category after the official mapping, the box under inclusive `x2, y2`, `iscrowd` and `ignore`. The reference writes every id with an `a-` prefix (`a-00122062`) that the derivative's `scalabel_id` does not carry (`00122062`). That uniform prefix is passed to `lineage` explicitly, never silently stripped.
- **Lineage result (2026-10-05).** 202 raw and 202 derived frames, with identical frame-index sets and file names. All 3,241 boxes match on track id (with the declared `a-` prefix), category, box (bit-identical), `iscrowd` and `ignore`. There are no mismatches.
- **Real-file validation (2026-10-05).** The adapter reconciles the derivative with the extracted val images exactly: the same 200 videos, all 39,973 JPEGs referenced once, contiguous frame indices, and a declared 1280 × 720 equal to every JPEG header. It produced valid ground truth for all 200 sequences: 18,842 tracks.
- **Source layout.** `labels/box_track_20_cocofmt/bdd_box_track_val_cocofmt.json` beside the unmodified `images/track/val/<videoName>/<frame>.jpg` tree extracted from the image archive (200 videos, 39,973 frames).
- **Crowd and distractors.** The conversion recodes the distractor classes `trailer`, `other vehicle` and `other person` as `truck`, `car` and `pedestrian`, with `iscrowd = 1` and `ignore = 1`. Raw crowd boxes carry `iscrowd = 1` and `ignore = 0`. The adapter accepts `ignore = 1` only together with `iscrowd = 1` and only on those three classes. Ground-truth ignore follows `ignore = 1` only, never `iscrowd` alone. A former distractor is an ignored frame, so distractors never enter class precision or recall, and they are never emitted as native classes. A genuine crowd box stays ordinary ground truth of its class, exactly as on the raw path: BDD100K's overlap-based crowd rule is not MAVI's ignore rule.
- **Class-inconsistent ids.** In 46 of the 18,842 val tracks (0.24%), one label id changes class between frames, mostly id reuse such as car to pedestrian. Such a track has no single class meaning. Every frame of it is ignored evidence (ignoredGt, in no population), with its first class recorded but never scored.
- **Car remains scored.** The generic BDD `box_track` conversion maps `van` and `caravan` to `car` if such aliases are present. The published MOT 2020 taxonomy does not list them as native MOT classes. `car`, `truck`, `bus` and `motorcycle` stay `exact`, with the usual caveat that BDD100K does not define every body-style boundary.
- **What it cannot support.** Any raw alias present would be folded into the eight classes without trace, and the occluded and truncated attributes are dropped. H3-v1 makes no claim about `trailer`, `other vehicle`, `van` or `caravan` from this source, and it gives no evidence for a taxonomy change.
- **Licence.** The annotation is a converted representation of BDD100K labels hosted by the MASA authors. Development use of the underlying labels is governed by the BDD100K data and label licence (educational, research and not-for-profit use without fee). MASA is the retrieval and conversion source; its repository licence is not treated as relicensing the BDD100K annotation data.
- **Provenance in the working descriptor.** The committed template is reproducible, not a record. The working descriptor frozen for an H3 run sets `source.retrievedOn` to the date the annotation was actually retrieved, 2026-10-05. It keeps the image provenance as it happened: the owner obtained the MOT 2020 val image archive from the Berkeley BDD100K MOT mirror (`images20-track-val-1.zip`, 4,983,938,716 bytes, SHA-256 `4d678810a14095ab4064013d81e3bc2bda45f730bfc09c3e66d3a5ef1c076778`, MD5 `743ab4c7b5ff8eeebd60bbfd15b20bd6`). No independently published checksum for this archive was found.

## Raw-label adapter semantics (`bdd100k-mot`)

This section and the next apply only when the original raw `box_track_20` Scalabel labels are available and used with the `bdd100k-mot` adapter. The H3-v1 derived path is described above.

- **Tracks.** The label `id` is the ground-truth track id within its video ("objects across videos are always distinct even if they have the same id", download.rst).
- **Timing.** Frames are "resampled to 5Hz from 30Hz" (download.rst). Label `frameIndex` k is offset k × 200 ms in the derived video. A gap in frame indices is refused by `prepare`.
- **Boxes.** Scalabel boxes include the pixel at `x2, y2`. The inclusive extent is clipped to the image, because official labels reach `x2` equal to the image width. Frame size is read from each JPEG header.
- **Classes.** These are the eight box-tracking classes plus the three distractor classes named by the official evaluation (`other person`, `other vehicle`, `trailer`). The official config's synonym aliases are applied (`motor` → `motorcycle`; `person` → `pedestrian`; `bike` → `bicycle`). Its `van` and `caravan` → `car` folding is not applied. `van` and `caravan` stay native classes mapped `vehicle-unresolved`, because MAVI splits vans by body. Any other category is refused.
- **Crowd and other attributes.** They do not change ground truth. A `crowd` box stays ordinary ground truth of its class, and no ignore regions are emitted. The official evaluation instead ignores false positives that overlap a crowd box or a distractor box by more than half (evaluate.rst). MAVI results are therefore not comparable with official BDD100K MOT scores.

## Raw-label path caveats

- **Car and vans.** BDD100K's documentation does not say how vans labelled `car` are split. The MAVI guide puts windowless cargo vans in `truck`. Any cargo van labelled `car` is a domain caveat on car precision and truck recall.
- **Taxonomy evolution.** Every native class is kept in the prepared ground truth. The mapping scores only `mavi-vehicle-subclass-v1`. `trailer` is the leading candidate for the next taxonomy version, and `van` is a further candidate, both subject to measured support (`vehicle-taxonomy-review-bdd100k.md`). A later version re-maps the same prepared data.
- **Definitions.** The repository documentation gives no written definitions for truck, bus or motorcycle. The mapping uses their practical meaning in a road-scene dataset.
- **Domain.** The footage is moving dashcam video from the United States, a weak proxy for fixed CCTV.
- **Exposure.** The descriptor records exposure as `unknown` until the detector's training data is checked for BDD100K.
