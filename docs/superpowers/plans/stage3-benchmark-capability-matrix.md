# Stage 3 — benchmark capability matrix (candidate labelled datasets)

**Status:** current research and planning document for S3.2d (ADR-017; the two current roadmaps; the S3.2 plan §14 amendment). It records verified facts only; a field marked **TODO** has not been verified. **Every field material to the intended benchmark use must be verified before execution; non-material unresolved fields may remain TODO** if they do not affect the validity, reproducibility, admissibility or interpretation of the measurement. Material fields normally include: exact dataset and release identity; actual accessibility; the usable labelled split; the annotation and task semantics MAVI uses; the native class definitions used for mapping; the mapping declarations; the intended research-use and admissibility status; source and provenance sufficient to identify the release; and known or plausible benchmark exposure where it is material to interpretation. Fields irrelevant to the chosen evaluation may stay TODO. This matrix is a working comparison, not a clearance checklist. Nothing here admits, acquires or downloads a dataset.

**Purpose.** Compare candidate labelled video datasets as Development and benchmarking evidence for the detector-native vehicle subclass (`mavi-vehicle-subclass-v1` = `car | truck | bus | motorcycle`), and for later Stage-3 evidence domains. The comparison fields come first; dataset rows are filled only with facts read from an authoritative source (the official page where available, otherwise the dataset paper, the author's or institution's repository, a maintained project repository, a conference or challenge archive or a reputable archival source; ADR-017 §7 "Authoritative facts"), with the date and source of the check.

## Fields

| Field | Meaning |
|---|---|
| Dataset / release | The exact edition and version that would be used. |
| Source | The authoritative source the facts were read from: the official page or documentation where available, otherwise the paper, author or institution repository, maintained project repository, challenge archive or reputable archival source, with its uncertainty noted. |
| Accessible | Whether the data can actually be obtained today, from where, and how it was checked. A reputable archival or research-hosted copy counts when the release identity can be established and no restriction prohibits the use (ADR-017 §7 "Sources and copies"); an anonymous or unverifiable mirror does not. |
| Paid / free | Whether obtaining it requires payment or a licence purchase. |
| Access mechanism | Direct download, registration, request form, institutional email, agreement. |
| Native task | Detection, tracking (MOT), classification, attributes. |
| Native classes | The dataset's own class list, verbatim where possible. |
| MAVI mapping | Per native class, as the adapter must declare it (ADR-017 §4): native class → MAVI class or none; mapping kind `exact`, `subset` or `unsupported`; reason. |
| Capability coverage | Derived from the per-class declarations, for the vehicle-subclass capability as a whole: `full` (every MAVI class has an `exact` native class), `partial` (some MAVI classes do), `none`. This is a summary, not a mapping kind. |
| Video / still | Continuous video with per-frame annotation, or still images. |
| Camera / domain | Fixed CCTV, dashcam, aerial, hand-held; country or region; conditions. |
| Annotation structure | Per-frame boxes with track identities; attributes; format. |
| Usable split | Which split carries labels MAVI may evaluate against (published test labels are often withheld). |
| Likely benchmark role | Primary benchmark (exact coverage preferred, not required), domain-diversity benchmark, challenge or regression set. |
| Known / possible model exposure | Whether the qualified detector (RTMDet-m COCO) or any MAVI component may have trained on this data or its source imagery. |
| Research-use status | ADR-017 §7: RESEARCH-ADMISSIBLE, RESEARCH-UNCERTAIN or BLOCKED, with the basis. |
| Redistribution limits | What the terms say about redistributing the data or derived crops. |
| Unresolved questions | What must be checked before use. |

## Source rules that apply to every row

- Prefer the original publisher or official project source for provenance and terms. When it is unavailable, a reputable author-maintained repository, institutional archive, research-hosted mirror, challenge archive or other lawfully obtainable source is acceptable if the dataset and release identity can be established and no explicit restriction prohibits the intended research use. Record where the copy came from, why it is credible, its release identity, hashes or manifest, and any uncertainty.
- An original server that has gone offline does not make a dataset BLOCKED by itself. BLOCKED applies when no lawful copy with an establishable identity can be obtained, access is denied or paid and not purchased, access controls would have to be bypassed, or the terms prohibit the use.
- This is Development benchmarking (ADR-017 §9); it makes no legal conclusion about any dataset.

## Mapping rules that apply to every row

- MAVI's taxonomy is versioned and may evolve from benchmark evidence (the v1 four classes were an initial scope). A dataset class that would make a coherent, useful MAVI class is recorded as a taxonomy candidate rather than forced into an existing class (`docs/qualification/stage3/vehicle-taxonomy-review-bdd100k.md`).
- A native class maps to a MAVI class where its practical meaning is operationally compatible with the MAVI label definition (the labelling guide `docs/qualification/stage3/s3-2-labeling-guide.md` is the reference for the current classes); meaningful differences are recorded as caveats, and a difference that would change what an operator means by the class makes it `subset` or `unsupported`.
- Mapping kinds are declared per native class. `exact`: the native class is operationally compatible with one MAVI class under the guide. `subset`: the native class falls entirely within one MAVI class but does not cover it (for example a `sedan` class into `car`), so it supports precision for that class but not recall on its own. `unsupported`: no MAVI class fits without assumption (for example `van`, which the guide splits by body into `car` or `truck`), or the class is outside the capability.
- Capability coverage is a derived summary (`full`, `partial`, `none`), never a substitute for the per-class declarations.
- Native classes outside the current MAVI classes (for example van, trailer, bicycle, tricycle, rider) are kept and reported in their own terms. They are never folded into a MAVI class by a mapping the data does not support, and official leaderboard rules (such as distractor classes) are not copied into MAVI semantics without analysis.
- A dataset whose vehicle classes are partially mappable can still serve as a domain-diversity benchmark for the classes it does support.

## Candidate rows

Facts below were checked on 2026-10-04 with the fetch results noted. Where an official page could not be reached, the row says so and the field is **TODO**.

### BDD100K (box tracking)

| Field | Value |
|---|---|
| Dataset / release | BDD100K box tracking, the "MOT 2020" packages: labels `box_track_20` (115 MB, md5 `6be40e0ca56a83ddeba2ed6bff50f9e6`, Scalabel format, train and val) and images `images/track` (train, val, test); tracking videos are "a subset of the 100K videos, but the videos are resampled to 5Hz from 30Hz" (official docs `doc/source/download.rst`, read 2026-10-04). Frames are JPEG files named by each label record's `name` (official Scalabel sample `tests/eval/testcases/box_track/track_sample_anns.json`, read 2026-10-04). **TODO:** video and track counts per split (observable at acquisition; not material to the adapter). |
| Source | Official documentation in the project repository `github.com/bdd100k/bdd100k`: `doc/source/{format,download,license,evaluate}.rst` and the official evaluation config `bdd100k/configs/box_track.toml` (read 2026-10-04); the Scalabel format specification `github.com/scalabel/scalabel` `doc/src/format.rst` and its official box-tracking sample (read 2026-10-04). The rendered site `doc.bdd100k.com` no longer resolves in DNS (checked 2026-10-04 against two public resolvers) and has no archived copy, so its annotation-instruction pages could not be read; the repository copy is the authoritative source text. |
| Accessible | Yes: data is obtained at `dl.cv.ethz.ch/bdd100k/data/` after agreeing to "the BDD100K license" (download.rst). Agreement acceptance is an acquisition precondition. |
| Paid / free | Free for research: the licence permits use "for educational, research, and not-for-profit purposes, without fee" (license.rst). |
| Access mechanism | Download portal with licence agreement; **TODO:** whether an account is required. |
| Native task | Detection and box tracking, among ten tasks (repository README). |
| Native classes | Box tracking evaluates "pedestrian, rider, car, truck, bus, train, motorcycle, bicycle" (format.rst). The official MOT evaluation also names three distractor classes, "other person", "trailer" and "other vehicle" (evaluate.rst). The official config folds the raw names `bike, caravan, motor, person, van` into `bicycle, car, motorcycle, pedestrian, car` (box_track.toml `[name_mapping]`). No written class definitions exist in the repository documentation (format.rst; the deleted `doc/source/category.rst` in the repository history lists names only). |
| MAVI mapping | Adopted in Slice 4 (`docs/qualification/stage3/benchmarks/bdd100k-mot-2020.mapping.json`) on the operational-compatibility standard: car, truck, bus, motorcycle → the same MAVI class `exact`, with caveats recorded per row (van handling within `car`, truck pickup handling, motorcycle scooter handling and the bus/minibus boundary undocumented). Raw `van` and `caravan` stay native classes → `unsupported` (`vehicle-unresolved`) instead of being folded into `car` as the official config does, because the guide splits vans by body. Pedestrian, rider, other person, bicycle, train → `unsupported` (`outside-capability`); other vehicle, trailer → `unsupported` (`vehicle-unresolved`) under v1; `trailer` is the recommended additive class of a future v2 and `van` a further candidate (`docs/qualification/stage3/vehicle-taxonomy-review-bdd100k.md`). |
| Capability coverage | `full` by declaration (all four MAVI classes `exact`), with the caveats in the mapping. |
| Video / still | Video sequences annotated at 5 Hz (resampled from 30 Hz) with per-frame boxes and track identities (Scalabel). |
| Camera / domain | Moving dashcam, United States, varied weather and time of day (weak proxy for fixed CCTV; S3.2 plan §8 already notes this). |
| Annotation structure | Per video, a JSON list of frame records `{name, videoName, frameIndex, labels[] {id, category, attributes {occluded, truncated, crowd}, box2d {x1, y1, x2, y2}}}` (format.rst; Scalabel format.rst; official sample). Label ids are stable within a video and distinct across videos (download.rst). `frameIndex` starts at 0 while frame file numbers start at 1 (official sample). Boxes include the pixel at `x2, y2` (width `x2 - x1 + 1`, format.rst), and official labels reach `x2` = image width at the edge (official sample). The official config declares a 1280 × 720 image size (box_track.toml); the adapter reads the size from each frame instead. |
| Usable split | `val` (public labels; download.rst lists train and val labels and train, val and test images). |
| Likely benchmark role | Leading candidate for the primary benchmark measurement (S3.2d-2), subject to verification; not a structural prerequisite. |
| Known / possible model exposure | **TODO.** RTMDet-m COCO is trained on COCO, not BDD100K, as far as the model card states; verify, and record any BDD100K use in MAVI's component history (none known). |
| Research-use status | RESEARCH-ADMISSIBLE on the quoted licence text (research use expressly permitted without fee); to be confirmed against the full licence accepted at download. Commercial use is reserved to "BDD and BAIR Commons members and their affiliates". |
| Redistribution limits | The licence requires the copyright notice and licence paragraphs to "appear in all copies, modifications, and distributions"; MAVI does not redistribute (ADR-017 §7). |
| Unresolved questions | `crowd`: the official evaluation ignores false positives overlapping a crowd box by more than half (evaluate.rst); this is not MAVI's ignore rule, so the adapter keeps crowd boxes as ordinary ground truth and emits no ignore regions (results are not comparable with official BDD100K MOT scores). Written class definitions (not material under the adopted mapping; caveats recorded). Video and track counts; account requirement (observable at acquisition). |

### UA-DETRAC

| Field | Value |
|---|---|
| Dataset / release | UA-DETRAC. |
| Source | The original site `detrac-db.rit.albany.edu` now redirects (301) to the University at Albany CVML lab page (read 2026-10-04), which describes the dataset: "10 hours of videos captured with a Cannon EOS 550D camera at 24 different locations at Beijing and Tianjin in China", over 140,000 frames at 25 fps, 960×540, 8,250 annotated vehicles and about 1.21 million boxes. |
| Accessible | **Uncertain.** The lab page gives no download link, so the original distribution appears unavailable. Under the source rules above, a reputable author-maintained, institutional, research-hosted or challenge-archive copy may be used if the release identity (version, file manifest or hashes) can be established and no restriction prohibits research use; an anonymous mirror may not. **TODO:** identify such a copy, record its origin, credibility basis, release identity and hashes. |
| Paid / free | **TODO**. |
| Access mechanism | **TODO**. |
| Native task | Vehicle detection and multi-object tracking: "100 challenging video sequences captured from real-world traffic scenes", annotated with "occlusion, weather, vehicle category, truncation, and vehicle bounding boxes" (arXiv 1511.04136 abstract, read 2026-10-04). |
| Native classes | **TODO:** not on the lab page. Believed to be car, bus, van, others; **verify**. |
| MAVI mapping | If confirmed: car→`car` `exact` (**verify** whether DETRAC `car` includes SUVs and pickups; pickups would make it `unsupported`); bus→`bus` `exact`; van→none `unsupported` (the guide splits vans by body into `car` or `truck`, which the native label does not resolve); others→none `unsupported` (undefined mix). No truck or motorcycle class. |
| Capability coverage | `partial` at best (car and bus). |
| Video / still | Video, per-frame boxes with track identities (believed). |
| Camera / domain | Fixed traffic cameras, China, day and night, varied weather. Closest domain to MAVI's intended CCTV use. |
| Annotation structure | **TODO** (believed XML per sequence with vehicle type, occlusion and truncation). |
| Usable split | **TODO**. |
| Likely benchmark role | Domain-diversity benchmark for fixed-camera traffic (S3.2d-3), car and bus only. |
| Known / possible model exposure | **TODO**. |
| Research-use status | **TODO.** Classified from the dataset's published terms (the paper and original release notes count as sources). BLOCKED only if no lawful copy with an establishable release identity can be obtained or the terms prohibit the use; the original server being offline is not by itself BLOCKED. |
| Redistribution limits | **TODO**. |
| Unresolved questions | Whether a credible copy with an establishable release identity exists (original or reputable archival); class list; terms. |

### VisDrone (VID / MOT)

| Field | Value |
|---|---|
| Dataset / release | VisDrone-VID / VisDrone-MOT. |
| Source | `github.com/VisDrone/VisDrone-Dataset` (read 2026-10-04): "288 video clips formed by 261,908 frames and 10,209 static images, captured by various drone-mounted cameras", 14 Chinese cities, "more than 2.6 million bounding boxes", attributes including "scene visibility, object class and occlusion". Tasks: image detection, video detection, single-object tracking, multi-object tracking, crowd counting. |
| Accessible | Direct links (Google Drive and Baidu) on the repository page; **no login or agreement shown on that page**. |
| Paid / free | Free (no fee stated). |
| Access mechanism | Direct download links. |
| Native task | Detection in images and video; MOT. |
| Native classes | MOT toolkit README (`github.com/VisDrone/VisDrone2018-MOT-toolkit`, read 2026-10-04): "ignored regions(0), pedestrian(1), people(2), bicycle(3), car(4), van(5), truck(6), tricycle(7), awning-tricycle(8), bus(9), motor(10), others(11)"; the MOT challenge evaluates "car, bus, truck, pedestrian, and van". |
| MAVI mapping | If confirmed: car→`car` `exact`; truck→`truck` `exact` (**verify** pickup handling); bus→`bus` `exact`; motor→`motorcycle` `exact` (**verify** that `motor` means motorised two-wheelers including scooters); van→none `unsupported` (see UA-DETRAC); tricycle, awning-tricycle, bicycle, pedestrian, people→none `unsupported` (outside the capability). All **TODO** until the task's annotation specification is read. |
| Capability coverage | Potentially `full` with van excluded; **unverified**. |
| Video / still | Video clips with per-frame boxes and track identities for MOT (believed; **TODO** format). |
| Camera / domain | Aerial drone views at varied altitudes; small objects; China. Far from CCTV geometry; useful as an adverse-scale diversity benchmark. |
| Annotation structure | Per-sequence text, one line per object per frame: `frame_index, target_id, bbox_left, bbox_top, bbox_width, bbox_height, score, object_category, truncation, occlusion`; in ground truth `score` 1 means evaluated and 0 ignored; truncation 0/1, occlusion 0/1/2 (toolkit README). |
| Usable split | **TODO** (train and val labels believed public). |
| Likely benchmark role | Domain-diversity benchmark (aerial, small scale), S3.2d-3; fallback primary with UAVDT if BDD100K cannot be acquired (S3.2d-1 plan §12). |
| Known / possible model exposure | **TODO**. |
| Research-use status | **TODO.** No licence statement was found on the repository page; if none exists in the release either, RESEARCH-UNCERTAIN under ADR-017 §7 (openly obtainable, terms incomplete), recorded as such. |
| Redistribution limits | **TODO**. |
| Unresolved questions | Full class list and definitions; MOT annotation format; any terms in the download bundle. |

### UAVDT (MOT)

| Field | Value |
|---|---|
| Dataset / release | UAVDT benchmark (UAVDT-Benchmark-M for DET/MOT, UAVDT-Benchmark-S for SOT). |
| Source | Project page `sites.google.com/view/grli-uavdt/` (read 2026-10-04): "10 hours of raw videos", "100 video sequences of about 80,000 representative frames", about "0.84 million bounding boxes over 2,700 vehicles", 1080×540 at 30 fps; scenes include "squares, arterial streets, toll stations, highways, crossings and T-junctions". |
| Accessible | Google Drive links on the project page (research-hosted distribution by the authors). |
| Paid / free | Free. |
| Access mechanism | Direct download. |
| Native task | Detection, single-object tracking, multi-object tracking. |
| Native classes | "car, truck and bus" (project page). **TODO:** written definitions. |
| MAVI mapping | If definitions confirm: car→`car` `exact` (**verify** SUV/pickup handling), truck→`truck` `exact`, bus→`bus` `exact`; no van, motorcycle or two-wheeler class. |
| Capability coverage | `partial` (no motorcycle). |
| Video / still | Video, per-frame boxes with identities for MOT (believed; **TODO** MOT file format). |
| Camera / domain | Drone (aerial) at low, medium and high altitude; front, side and bird views; daylight, night, fog, rain; China. |
| Annotation structure | Attributes: illumination, altitude, camera view, duration; detection attributes for occlusion and out-of-view (project page). **TODO:** MOT text format. |
| Usable split | **TODO**. |
| Likely benchmark role | Domain-diversity benchmark (aerial, adverse weather), S3.2d-3; fallback primary with VisDrone if BDD100K cannot be acquired. |
| Known / possible model exposure | **TODO**. |
| Research-use status | RESEARCH-ADMISSIBLE candidate: the page states "This dataset is for research purpose only" and requests citation; research use is the intended use. **TODO:** confirm no further terms in the download bundle. |
| Redistribution limits | Not stated; not redistributed by MAVI. |
| Unresolved questions | MOT annotation format; class definitions; split. |

### nuScenes (3D; reference for definitions)

| Field | Value |
|---|---|
| Dataset / release | nuScenes (full dataset v1.0). |
| Source | Devkit documentation `github.com/nutonomy/nuscenes-devkit`, `docs/instructions_nuscenes.md` (read 2026-10-04). The terms-of-use page did not render for text extraction. |
| Accessible | **TODO** (believed to require registration; terms not read). |
| Paid / free | **TODO** (believed free for non-commercial use). |
| Access mechanism | **TODO**. |
| Native task | 3D detection and tracking; "3D bounding boxes" (devkit docs). 2D boxes need projection or the separate nuImages set. |
| Native classes | `vehicle.car` "Vehicle designed primarily for personal use, e.g. sedans, hatch-backs, wagons, vans, mini-vans, SUVs and jeeps"; `vehicle.truck` "Vehicles primarily designed to haul cargo including pick-ups, lorrys, trucks and semi-tractors"; `vehicle.bus.rigid`/`vehicle.bus.bendy` (more than 10 people); `vehicle.motorcycle` includes "all motorcycles, vespas and scooters"; also `vehicle.bicycle`, `vehicle.trailer`, `vehicle.construction`, emergency vehicles. |
| MAVI mapping | Definitions are close to the MAVI guide (pickups are trucks; scooters are motorcycles) except that nuScenes `car` includes vans, which the guide splits by body → `car` would be `subset`-like for MAVI `car` plus cargo vans misassigned; not evaluated further unless a 2D tracking projection is adopted. |
| Capability coverage | Not applicable as a 2D tracking benchmark without projection. |
| Video / still | Multi-camera vehicle sensor data with 3D cuboids at keyframes. |
| Camera / domain | Vehicle-mounted cameras, Boston and Singapore. |
| Annotation structure | 3D cuboids; instance identity across keyframes (devkit schema). |
| Usable split | **TODO**. |
| Likely benchmark role | Reference for class definitions; not a first-choice 2D tracking benchmark. |
| Known / possible model exposure | **TODO**. |
| Research-use status | **TODO** (terms page unreadable on 2026-10-04; believed non-commercial research licence). |
| Redistribution limits | **TODO**. |
| Unresolved questions | Whether a 2D projection path is worth building; terms. |

### KITTI (tracking)

| Field | Value |
|---|---|
| Dataset / release | KITTI object tracking benchmark. |
| Source | `cvlibs.net/datasets/kitti/eval_tracking.php` (read 2026-10-04): "21 training sequences and 29 test sequences"; "8 different classes" labelled, with only "Car" and "Pedestrian" formally evaluated; downloads require login, and registration asks users to "detail their status, describe their work and specify the targeted venue". |
| Accessible | Yes, after registration (official page). |
| Paid / free | Free (no fee stated). |
| Access mechanism | Account registration with stated purpose. |
| Native task | 2D and 3D multi-object tracking from a moving car. |
| Native classes | "Car", "Van", "Truck", "Pedestrian", "Person_sitting", "Cyclist", "Tram", "Misc", plus "DontCare" regions (devkit readme; read 2026-10-04 from a public copy of the devkit text, `github.com/pratikac/kitti`, since the devkit itself is behind registration — recorded as a non-original source). |
| MAVI mapping | If confirmed: Car→`car` `exact` (**verify** KITTI's Car definition against SUVs); Truck→`truck` `exact`; Van→none `unsupported` (body not resolved); Cyclist, Tram, Pedestrian, Person (sitting), Misc→none `unsupported` (outside the capability). No bus or motorcycle class. |
| Capability coverage | `partial` (car and truck). |
| Video / still | Image sequences at about 10 fps with per-frame 2D boxes and track identities (believed; the page confirms per-image 2D boxes for evaluation). |
| Camera / domain | Moving car, Karlsruhe, daytime. |
| Annotation structure | Per-frame label lines: frame, track id, type, truncated (0–1), occluded (0–3), alpha, 2D bbox left/top/right/bottom (0-based pixels), 3D dimensions, location, rotation_y (devkit readme copy). `DontCare` marks unlabelled regions the evaluation ignores. |
| Usable split | Training sequences (test labels withheld). |
| Likely benchmark role | Secondary domain-diversity benchmark; low vehicle-class coverage. |
| Known / possible model exposure | **TODO**. |
| Research-use status | **TODO.** Licence not stated on the page read; KITTI is believed to be published under a Creative Commons non-commercial licence, which under ADR-017 §7 does not by itself exclude academic Development use; **verify the exact licence text**. |
| Redistribution limits | **TODO**. |
| Unresolved questions | Class list; licence text; registration outcome. |

### AI City Challenge / CityFlow

| Field | Value |
|---|---|
| Dataset / release | AI City Challenge datasets, including CityFlow (multi-camera vehicle tracking). |
| Source | `aicitychallenge.org/ai-city-challenge-dataset-access/` (read 2026-10-04): datasets are "available without requiring a data access request form. Password protection has been removed for all datasets listed below"; registration for the evaluation systems needs an "institutional or non-commercial email address". |
| Accessible | Yes for the listed datasets, per the official page (2026-10-04). Earlier Stage-3 planning assumed a request form; that is no longer stated. |
| Paid / free | Free (no fee stated). |
| Access mechanism | Direct access for listed datasets; registration only for evaluation. |
| Native task | Multi-camera vehicle tracking and re-identification; other tracks vary by year. |
| Native classes | **TODO.** CityFlow tracking annotations are not known to carry vehicle type (S3.2 plan §8); the current challenge tracks list other classes (people, robots, forklifts). Not a vehicle-subclass benchmark unless a type-labelled subset is confirmed. |
| MAVI mapping | None: no vehicle type label is known in the tracking annotations, so every native track is `unsupported` for the subclass capability (reason: no type label). |
| Capability coverage | `none` for vehicle subclass unless type labels are found. |
| Video / still | Video, fixed traffic cameras. |
| Camera / domain | Fixed traffic cameras, United States intersections. |
| Annotation structure | **TODO**. |
| Usable split | **TODO**. |
| Likely benchmark role | Tracking-quality and fixed-camera domain evidence (end-to-end detection and tracking), not subclass ground truth. |
| Known / possible model exposure | **TODO**. |
| Research-use status | **TODO** (terms page not read). |
| Redistribution limits | **TODO**. |
| Unresolved questions | Whether any CityFlow edition carries vehicle type labels; terms. |

## Next steps (S3.2d-1 inputs)

The implementation-ready harness plan is `docs/superpowers/plans/2026-10-04-stage3-s3-2d-benchmark-harness.md`; its §12 states the current primary-benchmark recommendation (BDD100K MOT 2020 val) and the fallback combination (VisDrone MOT + UAVDT).

1. Verify the **material** TODO fields for the datasets actually chosen (release identity, accessibility and source, usable split, annotation semantics, native class definitions, mappings, research-use status, exposure where material) against authoritative sources, recording the check date and source; non-material fields may stay TODO. Classify each chosen dataset's research-use status under ADR-017 §7 with its basis.
2. Choose the primary benchmark (S3.2d-2) once the class definitions are confirmed against the labelling guide. Prefer an exact-coverage benchmark where reasonably available; otherwise the strongest benchmark or combination with explicit mappings. BDD100K box tracking is the leading candidate, not a decision and not a prerequisite.
3. Record known or possible exposure of the qualified detector per dataset before any result is reported.
4. Do not download, mirror or commit dataset bytes while completing this matrix.
