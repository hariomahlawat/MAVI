# Vehicle taxonomy review against BDD100K (S3.2d-1 Slice 4)

**Status:** recommendation, not adopted. `mavi-vehicle-subclass-v1` (`car | truck | bus | motorcycle`, ADR-016) stays the only implemented vocabulary. This review records what the BDD100K labels suggest MAVI's taxonomy should become, and what a change would touch.

**Principle.** The four-class v1 vocabulary was an initial Stage-3 scope, not a permanent constraint. MAVI's taxonomy may add, remove, merge, split or redefine classes when real labelled evidence shows a more useful capability. Each change is a new capability version. Results measured under v1 keep their v1 meaning and are never rewritten.

## BDD100K vehicle-like categories

Sources, all read 2026-10-04: `format.rst` lists the eight box-tracking classes. `evaluate.rst` names three distractor classes. The official `box_track.toml` lists raw-name aliases, including `van` and `caravan`, which it folds into `car`. `trailer` is also mapped to `truck` for matching ignore regions there. Labelled support per class is not known until the release is acquired; Slice 5 counts it from the prepared ground truth.

| Native concept | PR #164 (v1) treatment | Assessment | Proposed treatment | Implement now? |
|---|---|---|---|---|
| car | `car` exact | Core class; common search term. | Retain. | Already done. |
| truck | `truck` exact | Core class. Pickup handling undocumented in BDD100K. | Retain. A tractor unit with its trailer stays one `truck`, as in the v1 guide. | Already done. |
| bus | `bus` exact | Core class; visually distinct. | Retain. | Already done. |
| motorcycle (raw `motor`) | `motorcycle` exact | Core class. Scooter handling undocumented. | Retain. | Already done. |
| trailer | `vehicle-unresolved` (native class kept) | Operationally useful: towing, logistics and detached-trailer searches. Visually distinct, with no cab and no driver. BDD100K labels it as a named class. Additive: v1 labels a trailer-only Track `unknown`, so no other class changes meaning. | **Leading candidate** for the next taxonomy version, defined as towed equipment with no cab, tracked on its own. A tractor unit with a trailer stays `truck`. | No. Measure support first; a detector that outputs trailers is also needed. |
| van | `vehicle-unresolved` (native class kept; not folded into car) | Very common and frequently searched ("white van"). v1 splits vans by body into car or truck, the guide's largest source of `ambiguous-type`. A `van` class would cut ambiguity in both. BDD100K MOT gives little evidence: `van` is only a legacy raw alias that the official evaluation folds into `car`. UA-DETRAC, VisDrone and KITTI label van. | **Candidate class**, decided with evidence from datasets that label van. This would re-partition car and truck, so their v1 results would not stay comparable. | No. Decide after a van-labelled benchmark (H4 work). |
| caravan | `vehicle-unresolved` | Mixes towed caravans and motorhomes; rare. | Stays unresolved. Under a v2, a towed caravan seen alone fits `trailer`; the native label cannot tell which. | No change. |
| other vehicle | `vehicle-unresolved` | A heterogeneous catch-all. | Stays unresolved. No MAVI class mirrors it. | No change. |
| bicycle | outside capability | Non-motorised. ADR-016 excludes it because adding it changes the Vehicle Track population. The COCO detector already emits it, so it is the cheapest class to add. | Outside v1. Worth considering only as a deliberate change to the broad Vehicle class. | No. |
| train | outside capability | Rail vehicle; little value for road CCTV. | Outside. | No change. |
| pedestrian, rider, other person | outside capability | People, not vehicles. | Outside. | No change. |

## Recommendation

**Leading candidate for the next taxonomy version:** `trailer`, which would give `car | truck | bus | motorcycle | trailer`. It is not a selected production class. The decision depends on the labelled support in the acquired release, visual separability, detector feasibility and operational value. The change would be additive: the four v1 classes keep their meaning, so v1 pilot and benchmark results stay comparable for those classes, and only Tracks v1 recorded as trailer-only `unknown` change treatment. The approach is to preserve trailer evidence now, measure it, and then make the product decision from real support.

**Van** is a further candidate on the same terms. It would re-partition car and truck, so it needs van-labelled evidence; BDD100K's tracking labels do not label van.

**A version change is not warranted inside PR #164.** The current detector (RTMDet-m COCO) cannot output `trailer` or `van` (ADR-016 §2). A v2 vocabulary is therefore only meaningful together with a detector capability that emits it. The BDD100K adapter already preserves every native class in the prepared ground truth, so a v2 mapping can be scored on the same prepared data later.

**H3 execution is not structurally blocked.** However, unresolved vehicle categories (trailer, van, caravan, other vehicle) may make individual class precision unavailable under the current evaluator: a MAVI class predicted on a `vehicle-unresolved` Track makes that class's precision `not-available`. Slice 5 must quantify their actual support and impact before H3 is relied upon for the later H5 capability decision.

## Follow-up change if a v2 is adopted

One dedicated change, ADR first (an amendment to ADR-016, or a new ADR). It would touch:

- **Detector capability:** a qualified detector that emits `trailer`, with its model, component binding, offline dependency policy, licences and runbooks. Training on BDD100K `train` must be recorded as benchmark exposure.
- **Vision worker:** `src/vision/mavi_vision/common/subclass.py`, `src/vision/mavi_vision/common/control_plane.py` (completion contract literal and vocabulary), a new pipeline profile under `src/vision/config/pipelines/`, and `src/vision/mavi_vision/runtime/profile.py`.
- **Contracts:** a new completion version (`vision-job-complete-v3.4` schema and example), the measurement export and measurement schemas, and `benchmark-class-mapping-v1` (its `capability` and `maviClass` enums are v1-only).
- **Platform:** `Mavi.Contracts/Worker/WorkerContractRules.cs`, `Mavi.Domain/Intelligence/VehicleSubclass.cs`, `VisionResultValidator.cs`, and the `tracks` check constraints with a new migration.
- **Qualification:** labelling guide v2, `s3-2-subclass-requirements.json` (a v2 requirements file), and the evaluator's per-class tables.
- **UI and API:** no subclass filter exists yet. A future filter must be vocabulary-aware.
