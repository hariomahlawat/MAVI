# Stage 3 — benchmark capability matrix (candidate labelled datasets)

**Status:** current research and planning document for S3.2d (ADR-017; the two current roadmaps; the S3.2 plan §14 amendment). It records verified facts only. A field marked **TODO** has not been verified against the official source and must be verified before the dataset is used. Nothing here admits, acquires or downloads a dataset.

**Purpose.** Compare candidate labelled video datasets as Development and benchmarking evidence for the detector-native vehicle subclass (`mavi-vehicle-subclass-v1` = `car | truck | bus | motorcycle`), and for later Stage-3 evidence domains. The comparison fields come first; dataset rows are filled only with facts read from official documentation, with the date and source of the check.

## Fields

| Field | Meaning |
|---|---|
| Dataset / release | The exact edition and version that would be used. |
| Official source | The publisher's page or documentation that the facts were read from. |
| Accessible | Whether the data can actually be obtained today, and how it was checked. |
| Paid / free | Whether obtaining it requires payment or a licence purchase. |
| Access mechanism | Direct download, registration, request form, institutional email, agreement. |
| Native task | Detection, tracking (MOT), classification, attributes. |
| Native classes | The dataset's own class list, verbatim where possible. |
| MAVI mapping | Per native class: the mapped MAVI class or capability, or none. |
| Mapping quality | `exact`, `subset` or `incompatible` for the vehicle-subclass capability as a whole. |
| Video / still | Continuous video with per-frame annotation, or still images. |
| Camera / domain | Fixed CCTV, dashcam, aerial, hand-held; country or region; conditions. |
| Annotation structure | Per-frame boxes with track identities; attributes; format. |
| Usable split | Which split carries labels MAVI may evaluate against (published test labels are often withheld). |
| Likely benchmark role | Exact-taxonomy benchmark, domain-diversity benchmark, challenge or regression set. |
| Known / possible model exposure | Whether the qualified detector (RTMDet-m COCO) or any MAVI component may have trained on this data or its source imagery. |
| Research-use status | ADR-017 §7: RESEARCH-ADMISSIBLE, RESEARCH-UNCERTAIN or BLOCKED, with the basis. |
| Redistribution limits | What the terms say about redistributing the data or derived crops. |
| Unresolved questions | What must be checked before use. |

## Mapping rules that apply to every row

- A native class maps to a MAVI class only where the native definition fits the MAVI label definition without assumption (the approved labelling guide `docs/qualification/stage3/s3-2-labeling-guide.md` is the reference for the four MAVI classes).
- `exact`: every MAVI class has a one-to-one native class. `subset`: some MAVI classes have one, others do not, or a native class spans two MAVI classes. `incompatible`: no defensible mapping for the capability.
- Native classes outside the four MAVI classes (for example van, bicycle, tricycle, rider) are kept and reported in their own terms. They are never folded into a MAVI class by a mapping the data does not support.
- A dataset whose vehicle classes are partially mappable can still serve as a domain-diversity benchmark for the classes it does support.

## Candidate rows

Facts below were checked on 2026-10-04 with the fetch results noted. Where an official page could not be reached, the row says so and the field is **TODO**.

### BDD100K (box tracking)

| Field | Value |
|---|---|
| Dataset / release | BDD100K, multi-object (box) tracking task. **TODO:** exact release version. |
| Official source | Project repository `github.com/bdd100k/bdd100k` (read 2026-10-04): tasks include "multi-object detection tracking, multi-object segmentation tracking". The documentation site `doc.bdd100k.com` and `bdd-data.berkeley.edu` could not be reached from the Development machine on 2026-10-04 (DNS and certificate errors). |
| Accessible | **TODO** (download portal not reached). |
| Paid / free | **TODO**. |
| Access mechanism | **TODO** (believed to need an account on the download portal; unverified). |
| Native task | Detection and box tracking, among ten tasks (repository README). |
| Native classes | **TODO:** not on the pages reached. Believed to include car, truck, bus, motorcycle, bicycle, rider, pedestrian, train and traffic sign/light classes; **verify against the official label specification before use**. |
| MAVI mapping | If the believed class list is confirmed: car→`car`, truck→`truck`, bus→`bus`, motorcycle→`motorcycle` (`exact` for all four); rider, bicycle, train, pedestrian: outside the capability, reported natively. |
| Mapping quality | Potentially `exact`; **unverified**. |
| Video / still | Video sequences with per-frame boxes and track identities (believed; **TODO** frame rate and sequence counts). |
| Camera / domain | Moving dashcam, United States, varied weather and time of day (weak proxy for fixed CCTV; S3.2 plan §8 already notes this). |
| Annotation structure | **TODO**. |
| Usable split | **TODO** (training and validation labels are believed public; test labels believed withheld). |
| Likely benchmark role | Leading candidate for the first exact-taxonomy benchmark (S3.2d-2), subject to verification. |
| Known / possible model exposure | **TODO.** RTMDet-m COCO is trained on COCO, not BDD100K, as far as the model card states; verify, and record any BDD100K use in MAVI's component history (none known). |
| Research-use status | **TODO** (terms not reached). To be classified under ADR-017 §7 from the official licence text. |
| Redistribution limits | **TODO**. |
| Unresolved questions | Exact class list and definitions for the tracking task; licence text; portal access; frame rate; whether track identities are consistent per sequence; occlusion and truncation attributes. |

### UA-DETRAC

| Field | Value |
|---|---|
| Dataset / release | UA-DETRAC. |
| Official source | The original site `detrac-db.rit.albany.edu` now redirects (301) to the University at Albany CVML lab page (read 2026-10-04), which describes the dataset: "10 hours of videos captured with a Cannon EOS 550D camera at 24 different locations at Beijing and Tianjin in China", over 140,000 frames at 25 fps, 960×540, 8,250 annotated vehicles and about 1.21 million boxes. |
| Accessible | **Uncertain.** The lab page gives no download link. The dataset is widely mirrored, but a mirror is not the official source; **TODO:** find the official distribution or treat as not obtainable. |
| Paid / free | **TODO**. |
| Access mechanism | **TODO**. |
| Native task | Vehicle detection and multi-object tracking (lab page). |
| Native classes | **TODO:** not on the lab page. Believed to be car, bus, van, others; **verify**. |
| MAVI mapping | If confirmed: car→`car`, bus→`bus`; van→none (`unsupported`: the guide maps vans by body to `car` or `truck`, which the native label does not resolve); others→none; no truck or motorcycle class. |
| Mapping quality | `subset` at best (car and bus only). |
| Video / still | Video, per-frame boxes with track identities (believed). |
| Camera / domain | Fixed traffic cameras, China, day and night, varied weather. Closest domain to MAVI's intended CCTV use. |
| Annotation structure | **TODO** (believed XML per sequence with vehicle type, occlusion and truncation). |
| Usable split | **TODO**. |
| Likely benchmark role | Domain-diversity benchmark for fixed-camera traffic (S3.2d-3), car and bus only. |
| Known / possible model exposure | **TODO**. |
| Research-use status | **TODO**. If the official distribution is not obtainable, BLOCKED under ADR-017 §7 ("cannot actually be obtained"). |
| Redistribution limits | **TODO**. |
| Unresolved questions | Whether an official distribution still exists; class list; terms. |

### VisDrone (VID / MOT)

| Field | Value |
|---|---|
| Dataset / release | VisDrone-VID / VisDrone-MOT. |
| Official source | `github.com/VisDrone/VisDrone-Dataset` (read 2026-10-04): "288 video clips formed by 261,908 frames and 10,209 static images, captured by various drone-mounted cameras", 14 Chinese cities, "more than 2.6 million bounding boxes", attributes including "scene visibility, object class and occlusion". Tasks: image detection, video detection, single-object tracking, multi-object tracking, crowd counting. |
| Accessible | Direct links (Google Drive and Baidu) on the repository page; **no login or agreement shown on that page**. |
| Paid / free | Free (no fee stated). |
| Access mechanism | Direct download links. |
| Native task | Detection in images and video; MOT. |
| Native classes | **TODO:** the page names "pedestrians, cars, bicycles, and tricycles" as examples only; the full list (believed to include car, van, truck, bus, motor, bicycle, tricycle, awning-tricycle, pedestrian, people) must be read from the task's annotation specification. |
| MAVI mapping | If confirmed: car→`car`, truck→`truck`, bus→`bus`, motor→`motorcycle` (`exact` candidates); van→`unsupported` (see UA-DETRAC); tricycle, awning-tricycle, bicycle→outside the capability. |
| Mapping quality | Potentially `exact` for the four MAVI classes with van excluded; **unverified**. |
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
| Official source | `cvlibs.net/datasets/kitti/eval_tracking.php` (read 2026-10-04): "21 training sequences and 29 test sequences"; "8 different classes" labelled, with only "Car" and "Pedestrian" formally evaluated; downloads require login, and registration asks users to "detail their status, describe their work and specify the targeted venue". |
| Accessible | Yes, after registration (official page). |
| Paid / free | Free (no fee stated). |
| Access mechanism | Account registration with stated purpose. |
| Native task | 2D and 3D multi-object tracking from a moving car. |
| Native classes | Eight labelled classes; **TODO:** confirm the list (believed Car, Van, Truck, Pedestrian, Person (sitting), Cyclist, Tram, Misc). |
| MAVI mapping | If confirmed: Car→`car`, Truck→`truck`; Van→`unsupported`; no bus or motorcycle class; Cyclist, Tram→outside the capability. |
| Mapping quality | `subset` (car and truck). |
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
| Official source | `aicitychallenge.org/ai-city-challenge-dataset-access/` (read 2026-10-04): datasets are "available without requiring a data access request form. Password protection has been removed for all datasets listed below"; registration for the evaluation systems needs an "institutional or non-commercial email address". |
| Accessible | Yes for the listed datasets, per the official page (2026-10-04). Earlier Stage-3 planning assumed a request form; that is no longer stated. |
| Paid / free | Free (no fee stated). |
| Access mechanism | Direct access for listed datasets; registration only for evaluation. |
| Native task | Multi-camera vehicle tracking and re-identification; other tracks vary by year. |
| Native classes | **TODO.** CityFlow tracking annotations are not known to carry vehicle type (S3.2 plan §8); the current challenge tracks list other classes (people, robots, forklifts). Not a vehicle-subclass benchmark unless a type-labelled subset is confirmed. |
| MAVI mapping | None confirmed. |
| Mapping quality | `incompatible` for vehicle subclass unless type labels are found. |
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

1. Verify every **TODO** above against official sources and record the check date and page; classify each dataset's research-use status under ADR-017 §7 with its basis.
2. Choose the first exact-taxonomy benchmark (S3.2d-2) only after the class list and definitions are confirmed against the labelling guide; BDD100K box tracking is the leading candidate, not a decision.
3. Record known or possible exposure of the qualified detector per dataset before any result is reported.
4. Do not download, mirror or commit dataset bytes while completing this matrix.
