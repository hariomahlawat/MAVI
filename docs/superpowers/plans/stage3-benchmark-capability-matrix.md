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
| Likely benchmark role | Exact-taxonomy benchmark, domain-diversity benchmark, challenge or regression set. |
| Known / possible model exposure | Whether the qualified detector (RTMDet-m COCO) or any MAVI component may have trained on this data or its source imagery. |
| Research-use status | ADR-017 §7: RESEARCH-ADMISSIBLE, RESEARCH-UNCERTAIN or BLOCKED, with the basis. |
| Redistribution limits | What the terms say about redistributing the data or derived crops. |
| Unresolved questions | What must be checked before use. |

## Source rules that apply to every row

- Prefer the original publisher or official project source for provenance and terms. When it is unavailable, a reputable author-maintained repository, institutional archive, research-hosted mirror, challenge archive or other lawfully obtainable source is acceptable if the dataset and release identity can be established and no explicit restriction prohibits the intended research use. Record where the copy came from, why it is credible, its release identity, hashes or manifest, and any uncertainty.
- An original server that has gone offline does not make a dataset BLOCKED by itself. BLOCKED applies when no lawful copy with an establishable identity can be obtained, access is denied or paid and not purchased, access controls would have to be bypassed, or the terms prohibit the use.
- This is Development benchmarking (ADR-017 §9); it makes no legal conclusion about any dataset.

## Mapping rules that apply to every row

- A native class maps to a MAVI class only where the native definition fits the MAVI label definition without assumption (the approved labelling guide `docs/qualification/stage3/s3-2-labeling-guide.md` is the reference for the four MAVI classes).
- Mapping kinds are declared per native class. `exact`: the native class definition coincides with one MAVI class under the guide. `subset`: the native class falls entirely within one MAVI class but does not cover it (for example a `sedan` class into `car`), so it supports precision for that class but not recall on its own. `unsupported`: no MAVI class fits without assumption (for example `van`, which the guide splits by body into `car` or `truck`), or the class is outside the capability.
- Capability coverage is a derived summary (`full`, `partial`, `none`), never a substitute for the per-class declarations.
- Native classes outside the four MAVI classes (for example van, bicycle, tricycle, rider) are kept and reported in their own terms. They are never folded into a MAVI class by a mapping the data does not support.
- A dataset whose vehicle classes are partially mappable can still serve as a domain-diversity benchmark for the classes it does support.

## Candidate rows

Facts below were checked on 2026-10-04 with the fetch results noted. Where an official page could not be reached, the row says so and the field is **TODO**.

### BDD100K (box tracking)

| Field | Value |
|---|---|
| Dataset / release | BDD100K, multi-object (box) tracking task. **TODO:** exact release version. |
| Source | Project repository `github.com/bdd100k/bdd100k` (read 2026-10-04): tasks include "multi-object detection tracking, multi-object segmentation tracking". The documentation site `doc.bdd100k.com` and `bdd-data.berkeley.edu` could not be reached from the Development machine on 2026-10-04 (DNS and certificate errors). |
| Accessible | **TODO** (download portal not reached). |
| Paid / free | **TODO**. |
| Access mechanism | **TODO** (believed to need an account on the download portal; unverified). |
| Native task | Detection and box tracking, among ten tasks (repository README). |
| Native classes | **TODO:** not on the pages reached. Believed to include car, truck, bus, motorcycle, bicycle, rider, pedestrian, train and traffic sign/light classes; **verify against the official label specification before use**. |
| MAVI mapping | If the believed class list is confirmed: car→`car` `exact` (passenger car); truck→`truck` `exact`, **reason to verify:** whether BDD100K `truck` includes pickups and cargo vans as the guide does; bus→`bus` `exact`; motorcycle→`motorcycle` `exact`, **verify** whether scooters and mopeds are included; rider, bicycle, train, pedestrian→none `unsupported` (outside the capability). All **TODO** until the official class definitions are read. |
| Capability coverage | Potentially `full`; **unverified**. |
| Video / still | Video sequences with per-frame boxes and track identities (believed; **TODO** frame rate and sequence counts). |
| Camera / domain | Moving dashcam, United States, varied weather and time of day (weak proxy for fixed CCTV; S3.2 plan §8 already notes this). |
| Annotation structure | **TODO**. |
| Usable split | **TODO** (training and validation labels are believed public; test labels believed withheld). |
| Likely benchmark role | Leading candidate for the primary benchmark measurement (S3.2d-2), subject to verification; not a structural prerequisite. |
| Known / possible model exposure | **TODO.** RTMDet-m COCO is trained on COCO, not BDD100K, as far as the model card states; verify, and record any BDD100K use in MAVI's component history (none known). |
| Research-use status | **TODO** (terms not reached). To be classified under ADR-017 §7 from the official licence text. |
| Redistribution limits | **TODO**. |
| Unresolved questions | Exact class list and definitions for the tracking task; licence text; portal access; frame rate; whether track identities are consistent per sequence; occlusion and truncation attributes. |

### UA-DETRAC

| Field | Value |
|---|---|
| Dataset / release | UA-DETRAC. |
| Source | The original site `detrac-db.rit.albany.edu` now redirects (301) to the University at Albany CVML lab page (read 2026-10-04), which describes the dataset: "10 hours of videos captured with a Cannon EOS 550D camera at 24 different locations at Beijing and Tianjin in China", over 140,000 frames at 25 fps, 960×540, 8,250 annotated vehicles and about 1.21 million boxes. |
| Accessible | **Uncertain.** The lab page gives no download link, so the original distribution appears unavailable. Under the source rules above, a reputable author-maintained, institutional, research-hosted or challenge-archive copy may be used if the release identity (version, file manifest or hashes) can be established and no restriction prohibits research use; an anonymous mirror may not. **TODO:** identify such a copy, record its origin, credibility basis, release identity and hashes. |
| Paid / free | **TODO**. |
| Access mechanism | **TODO**. |
| Native task | Vehicle detection and multi-object tracking (lab page). |
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
| Unresolved questions | Whether an official distribution still exists; class list; terms. |

### VisDrone (VID / MOT)

| Field | Value |
|---|---|
| Dataset / release | VisDrone-VID / VisDrone-MOT. |
| Source | `github.com/VisDrone/VisDrone-Dataset` (read 2026-10-04): "288 video clips formed by 261,908 frames and 10,209 static images, captured by various drone-mounted cameras", 14 Chinese cities, "more than 2.6 million bounding boxes", attributes including "scene visibility, object class and occlusion". Tasks: image detection, video detection, single-object tracking, multi-object tracking, crowd counting. |
| Accessible | Direct links (Google Drive and Baidu) on the repository page; **no login or agreement shown on that page**. |
| Paid / free | Free (no fee stated). |
| Access mechanism | Direct download links. |
| Native task | Detection in images and video; MOT. |
| Native classes | **TODO:** the page names "pedestrians, cars, bicycles, and tricycles" as examples only; the full list (believed to include car, van, truck, bus, motor, bicycle, tricycle, awning-tricycle, pedestrian, people) must be read from the task's annotation specification. |
| MAVI mapping | If confirmed: car→`car` `exact`; truck→`truck` `exact` (**verify** pickup handling); bus→`bus` `exact`; motor→`motorcycle` `exact` (**verify** that `motor` means motorised two-wheelers including scooters); van→none `unsupported` (see UA-DETRAC); tricycle, awning-tricycle, bicycle, pedestrian, people→none `unsupported` (outside the capability). All **TODO** until the task's annotation specification is read. |
| Capability coverage | Potentially `full` with van excluded; **unverified**. |
| Video / still | Video clips with per-frame boxes and track identities for MOT (believed; **TODO** format). |
| Camera / domain | Aerial drone views at varied altitudes; small objects; China. Far from CCTV geometry; useful as an adverse-scale diversity benchmark. |
| Annotation structure | **TODO**. |
| Usable split | **TODO** (train and val labels believed public). |
| Likely benchmark role | Domain-diversity benchmark (aerial, small scale), S3.2d-3. |
| Known / possible model exposure | **TODO**. |
| Research-use status | **TODO.** No licence statement was found on the repository page; if none exists in the release either, RESEARCH-UNCERTAIN under ADR-017 §7 (openly obtainable, terms incomplete), recorded as such. |
| Redistribution limits | **TODO**. |
| Unresolved questions | Full class list and definitions; MOT annotation format; any terms in the download bundle. |

### KITTI (tracking)

| Field | Value |
|---|---|
| Dataset / release | KITTI object tracking benchmark. |
| Source | `cvlibs.net/datasets/kitti/eval_tracking.php` (read 2026-10-04): "21 training sequences and 29 test sequences"; "8 different classes" labelled, with only "Car" and "Pedestrian" formally evaluated; downloads require login, and registration asks users to "detail their status, describe their work and specify the targeted venue". |
| Accessible | Yes, after registration (official page). |
| Paid / free | Free (no fee stated). |
| Access mechanism | Account registration with stated purpose. |
| Native task | 2D and 3D multi-object tracking from a moving car. |
| Native classes | Eight labelled classes; **TODO:** confirm the list (believed Car, Van, Truck, Pedestrian, Person (sitting), Cyclist, Tram, Misc). |
| MAVI mapping | If confirmed: Car→`car` `exact` (**verify** KITTI's Car definition against SUVs); Truck→`truck` `exact`; Van→none `unsupported` (body not resolved); Cyclist, Tram, Pedestrian, Person (sitting), Misc→none `unsupported` (outside the capability). No bus or motorcycle class. |
| Capability coverage | `partial` (car and truck). |
| Video / still | Image sequences at about 10 fps with per-frame 2D boxes and track identities (believed; the page confirms per-image 2D boxes for evaluation). |
| Camera / domain | Moving car, Karlsruhe, daytime. |
| Annotation structure | Per-frame 2D boxes, occlusion state, truncation (official page). |
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

1. Verify the **material** TODO fields for the datasets actually chosen (release identity, accessibility and source, usable split, annotation semantics, native class definitions, mappings, research-use status, exposure where material) against authoritative sources, recording the check date and source; non-material fields may stay TODO. Classify each chosen dataset's research-use status under ADR-017 §7 with its basis.
2. Choose the primary benchmark (S3.2d-2) once the class definitions are confirmed against the labelling guide. Prefer an exact-coverage benchmark where reasonably available; otherwise the strongest benchmark or combination with explicit mappings. BDD100K box tracking is the leading candidate, not a decision and not a prerequisite.
3. Record known or possible exposure of the qualified detector per dataset before any result is reported.
4. Do not download, mirror or commit dataset bytes while completing this matrix.
