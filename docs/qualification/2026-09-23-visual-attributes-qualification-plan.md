# Stage 2 Visual Attributes — Qualification Plan

**Status:** Draft pre-implementation qualification protocol  
**Date:** 2026-09-23  
**Purpose:** Define how Stage-2 model quality is judged before model selection/threshold tuning can bias acceptance.

## 1. Principle

MAVI exposes only attributes whose measured evidence supports operational use.

A model output is not a product capability until:
- the attribute semantic is frozen;
- the corpus covers relevant operating conditions;
- the threshold is predeclared/frozen;
- accuracy and abstention behaviour are measured;
- evidence provenance is complete;
- offline/runtime compatibility is proven.

## 2. Qualification units

Qualification is recorded per:
- attribute schema version;
- attribute pipeline version;
- model/modelPackId;
- runtimePackId / runtime variant;
- object class;
- attribute type;
- confidence threshold;
- corpus version.

Changing any material identity requires a new or explicitly inherited qualification determination.

## 3. Corpus requirements

The labelled corpus should include, where available:
- multiple cameras/scenes;
- persons and vehicles separately;
- daylight and lower-light examples;
- indoor/outdoor variation;
- near/mid/far object scale bands;
- frontal/side/rear or varied aspect;
- blur/sharpness bands;
- partial occlusion;
- frame-edge clipping;
- illumination/white-balance variation;
- visually similar colour confusions;
- bag/headwear difficult negatives.

No single demonstration video may qualify an attribute.

Training data and qualification corpus must be separate where model training/fine-tuning occurs.

## 4. Metrics

### Categorical attributes
Record:
- per-class precision;
- per-class recall;
- F1;
- macro/micro summaries;
- confusion matrix;
- abstention/unknown rate;
- coverage by scale/quality band.

### Presence attributes
Record:
- positive precision/recall;
- negative precision/recall if an explicit `absent` value is proposed;
- false-positive rate;
- false-negative rate;
- unknown/abstention rate.

### Confidence
If confidence is shown or used as a search gate:
- reliability/calibration curve or equivalent;
- observed precision by confidence band;
- selected operational threshold rationale.

## 5. Exposure rule

Each attribute/value family has a predeclared minimum gate before operator exposure.

The final numeric gates are frozen during S0 after corpus inspection but **before** final evaluation on the qualification set.

If an attribute fails:
- it remains disabled in the operational schema;
- it may remain available to engineering diagnostics;
- the product does not weaken the gate to preserve planned scope.

## 6. Evidence-selection qualification

Measure whether the bounded Track Evidence Set preserves useful appearance evidence.

Record:
- percentage of eligible Tracks with at least one usable evidence crop;
- evidence count distribution;
- crop resolution distribution;
- selector score distribution;
- redundancy/diversity metric where defined;
- failure cases by scale/occlusion/blur.

Compare Representative-only inference against Track-Evidence-Set inference on the same corpus. The evidence-set complexity is retained only if it produces material quality/coverage value.

## 7. Performance qualification

Measure separately on CPU and CUDA Development variants where applicable:
- model initialization;
- mean/p50/p95 inference time per evidence crop;
- mean/p50/p95 per Track;
- batch behaviour;
- RAM;
- VRAM;
- throughput;
- timeout/watchdog behaviour;
- bounded recovery after model failure;
- attribute-analysis backlog behaviour.

## 8. Search/data qualification

At realistic fact volume:
- PostgreSQL query plan;
- query count;
- p50/p95 latency;
- allocation/memory where measurable;
- pagination stability;
- multi-attribute AND semantics;
- snapshot consistency during concurrent new analysis publication;
- no N+1 evidence fetch.

A summary/materialization table is introduced only if measurements justify it.

## 9. Resilience

Prove:
- cancellation during evidence read;
- cancellation during inference;
- model exception;
- malformed model output;
- missing/corrupt evidence;
- stale lease completion;
- retry after failure;
- re-analysis with a new model;
- no partial default publication on failed completion;
- previous completed analysis remains intact after failed replacement analysis.

## 10. Offline qualification

With network disconnected:
- install/verify required Runtime Pack;
- install/verify Model Pack;
- start worker;
- analyse real Track evidence;
- persist attributes;
- search attributes;
- open supporting evidence;
- verify no remote request or model-hub resolution.

## 11. Acceptance evidence

Stage 2 cannot close on screenshots alone. Required evidence includes:
- frozen corpus manifest;
- model/runtime/component identities and hashes;
- accuracy report;
- threshold table;
- performance report;
- query qualification;
- offline run;
- real-video end-to-end operator workflow;
- exact-head CI;
- independent cold review.
