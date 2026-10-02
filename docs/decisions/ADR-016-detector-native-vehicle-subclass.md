# ADR-016: Detector-native Vehicle Subclass

**Status:** Accepted owner decision for capability Stage 3, 2026-10-02 (readiness analysis and plan reviewed by the owner).

**Date:** 2026-10-02

**Related:** ADR-005 (qualified vision runtime: class mapping lives in the hash-bound pipeline profile); ADR-013 §1 (Capability Replacement Boundary); ADR-014 (component binding v2); `docs/superpowers/plans/capability-implementation-roadmap.md` Stage 3.

## Context

The qualified RTMDet-m COCO checkpoint distinguishes `car`, `truck`, `bus` and `motorcycle`, but the Phase-1 pipeline maps all four to the broad `Vehicle` class after the detector's own suppression and before tracking, and then discards the native label. One Vehicle Track can therefore contain detections of several native classes. `bicycle` is not a Phase-1 source class: the pipeline drops it, so no bicycle has ever produced a Track. The roadmap's statement that bicycle maps to Vehicle is wrong.

## Decision

1. **Source.** A Vehicle Track's subclass is detector-native: the qualified detector's own class, carried from detection through tracking (pass-through only; association is unchanged) to the Track accumulator. No classifier, model, dataset or external dependency is added.
2. **Vocabulary.** `mavi-vehicle-subclass-v1` = `car | truck | bus | motorcycle`. Bicycle is excluded, because adding it would change the existing Vehicle Track population. SUV, van and make/model are not offered: the detector does not distinguish them.
3. **Track-level resolution.** Every detection matched to the Track votes its confidence, as integer micro-units, for its native class. The subclass is resolved only when one class has the unique highest total, its share is at least `minShare`, and at least `minMatchedDetections` detections voted; otherwise it is undetermined. Both thresholds live in the pipeline profile (`vehicleSubclass`, profile schema 1.2); they are provisional until the development measurement freezes them.
4. **Representation.** Three immutable, nullable Track fields, written when the processing run is finalised and never rewritten: `object_subclass`, `object_subclass_vocabulary` and `object_subclass_source` (`detector-native:<pipeline profile SHA-256>`). Person Tracks and pre-Stage-3 Tracks carry none of the three; a Stage-3 Vehicle Track always carries vocabulary and source, and a subclass only when resolved. The database enforces exactly these states.
5. **Contract.** Completion 3.3 is the 3.2 body plus `objectSubclassVocabulary` and `objectSubclassSource` (body level; the source must name this body's pipeline profile) and `objectSubclass` (per Track, present only when resolved, never null; never on a Person Track). It has its own digest domain. The worker emits 3.3 as the vision role's contract; the platform keeps accepting and replaying 3.2.
6. **Replacement.** Search reads the subclass through one repository seam. A future classifier would follow the Stage-2 analysis pattern (immutable analyses and per-Track outcomes), and the seam would then resolve which source applies, by a rule decided in an ADR at that time; historical subclass facts are never rewritten.
7. **Evaluation first.** The subclass is measured on MAVI-held development clips before any operator exposure. API, search and UI exposure is a later increment and happens only if that measurement supports it. The product meaning is "detector-reported vehicle type"; it is not a Task-18 acceptance criterion.

## Consequences

- **Compatibility.** Tracking only passes the native class through; association never reads it. For a fixed association, every Track's identity, geometry, observations, trajectory bytes, confidences, evidence selection and crops, broad class and the evidence accounting are identical to the pre-Stage-3 output: the Track-identity gate runs the real detector mapping, accumulator, evidence and staging against a golden made on `main@68b5b48b`. Real ByteTrack association is covered by the adapter's pass-through test and the qualified runtime job, not by the gate. The completion body and digest, the pipeline profile version and hash, the binding's contract and the qualification record's bound profile hash change by design.
- **Rollout.** The platform (binary and migration) must be upgraded before workers: a 3.3 worker refuses to lease from a platform that does not advertise 3.3.
- **Qualification.** The checkpoint, model manifest, Model Pack id, runtime profile, dependency locks, runtime packs and Offline Binary Kit are unchanged. The pipeline profile is a new version, so the qualification record's policies are re-derived (the record remains `pending`) and the identity pins are re-issued. Existing qualification evidence does not cover subclass quality.
- **Rollback.** Forward-only for stored 3.3 finalization payloads, as for 3.2: a platform rolled back below this change cannot replay them. The new columns are nullable, so an older binary inserting Tracks still writes a valid pre-Stage-3 row.
- **Trade-off accepted.** The source-precedence rule for a second subclass source is deferred until one exists, instead of introducing a separate subclass-analysis table now.
