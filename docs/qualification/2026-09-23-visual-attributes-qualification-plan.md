# Stage 2 Visual Attributes — Qualification Plan

**Status:** Architecture-freeze candidate; pre-implementation protocol  
**Date:** 2026-09-23  
**Purpose:** Predeclare the evidence, data-splitting, quality, performance, offline and requalification rules before model selection or threshold tuning can bias acceptance.

## 1. Principle

MAVI exposes only attributes whose measured evidence supports operational use.

Inference functioning is not qualification. A model output becomes an operator-facing capability only when:
- the attribute semantic and value vocabulary are frozen;
- the evidence-selection contract is frozen;
- the labelling protocol is frozen;
- validation/tuning data is separated from the frozen qualification test set;
- class/value support is sufficient;
- thresholds and aggregation policy are frozen before the frozen test set is evaluated;
- accuracy, abstention and generalisation are measured;
- provenance and licensing are complete;
- runtime/offline compatibility is proven;
- retrieval behaviour is measured in the product workflow.

A planned attribute that fails its gate remains disabled. The gate is not weakened to preserve roadmap scope.

## 2. Qualification identity

Qualification is recorded per:
- capabilityId;
- attribute schema version/SHA;
- attribute pipeline version;
- evidence-selection pipeline/profile version;
- aggregation-policy version/SHA;
- modelPackId and model-manifest SHA;
- runtimePackId / runtime variant;
- object class;
- attribute type/value family;
- confidence/decision threshold(s);
- labelled corpus version;
- qualification protocol version;
- hardware/profile classification.

A material change to any identity above triggers requalification unless an explicit policy entry documents why prior evidence remains valid.

Development and Production evidence remain distinct under ADR-009.

## 3. Corpus governance

### 3.1 Dataset partitions

Where training/fine-tuning occurs, data is partitioned into:
- training set;
- tuning/validation set;
- frozen qualification test set.

The frozen test set is not inspected for threshold, vocabulary, aggregation-policy or model-selection decisions after freeze.

If the selected model is entirely pretrained and no MAVI fine-tuning occurs, a validation/tuning split is still required for threshold and aggregation decisions, distinct from the frozen test set.

**Training-data disjointness.** The frozen qualification test set must be demonstrably disjoint from any data the candidate model was trained or tuned on. Public person-attribute or vehicle-colour benchmark corpora that a third-party checkpoint may have seen are therefore ineligible as the frozen test set; the frozen set is MAVI-sourced footage or footage whose disjointness from the model's declared training sources is recorded in the corpus manifest. A candidate whose training sources cannot be established is qualified only on MAVI-sourced footage.

### 3.2 Scene/camera separation

Corpus metadata records camera/scene identity.

Qualification reports:
- pooled metrics;
- per-camera/scene metrics where support permits;
- **leave-one-camera-out / held-camera generalisation** or an equivalent explicit unseen-camera protocol.

No single demonstration video or single camera may qualify an attribute.

### 3.3 Operating-condition coverage

The corpus should intentionally cover, where relevant:
- multiple cameras/scenes;
- persons and vehicles separately;
- daylight and lower-light conditions;
- indoor/outdoor variation;
- near/mid/far object scale bands;
- varied viewpoints/aspect;
- motion blur and sharpness bands;
- partial occlusion;
- frame-edge clipping;
- illumination/white-balance variation;
- visually similar colour confusions;
- difficult negatives for bag/headwear presence;
- tracker/detector error crops and non-subject crops;
- crowded/overlap cases;
- evidence sets with fewer than the maximum supplemental roles.

Coverage gaps are reported as limitations, not silently ignored.

## 4. Labelling protocol and agreement

Before the qualification corpus is labelled, each exposed attribute has a written annotation guide defining:
- allowed values;
- Unknown/Unlabelable criteria;
- treatment of partial visibility;
- treatment of mixed colours/patterns;
- bag/headwear boundary cases;
- vehicle dominant-colour rules;
- minimum visual evidence needed to assign a ground-truth value.

A representative double-labelled subset is required.

Record:
- annotator count;
- disagreement rate;
- agreement statistic appropriate to the attribute (for example Cohen/Fleiss kappa or percent agreement where justified);
- adjudication procedure;
- final adjudicated ground truth.

An attribute whose ground truth cannot be labelled consistently is not operationally exposed merely because a model predicts it.

At least one annotator of the double-labelled subset must be independent of model selection and threshold tuning, and annotation is completed blind to model output.

## 5. Minimum support

Before a class/value can pass an operational gate, the frozen test set must contain a predeclared minimum number of evaluable examples for that class/value and sufficient difficult negatives where applicable.

The numeric support table is recorded from validation/tuning evidence during S5, before the frozen test set is scored; it is not a freeze-time constant.

Values below support threshold are reported as **insufficient evidence**, never merged into a passing macro score.

## 6. Metrics

### 6.1 Categorical attributes

Record at crop level and aggregated Track level:
- per-class precision;
- per-class recall;
- F1;
- macro/micro summaries;
- confusion matrix;
- Unknown/abstention rate;
- coverage by scale/quality/occlusion band;
- per-camera/held-camera performance.

Track-level metrics are the operator-facing primary metrics.

### 6.2 Presence attributes

Record:
- positive precision/recall;
- false-positive rate;
- false-negative rate;
- Unknown/abstention rate;
- negative precision/recall only if an explicit qualified `absent` semantic is proposed.

No implicit negative is inferred from Unknown or missing analysis.

### 6.3 Aggregation quality

Compare:
- individual evidence-crop predictions;
- Representative-only prediction;
- bounded Evidence-Set aggregated prediction.

Record:
- precision/recall change;
- Track-level abstention change;
- error cases introduced by aggregation;
- sensitivity to evidence-count reduction.

The aggregation policy is versioned and frozen before final test evaluation.

### 6.4 Confidence/calibration

If confidence is persisted, displayed or used as a decision/search gate, record:
- reliability/calibration curve or equivalent;
- observed precision by confidence band;
- selected threshold rationale;
- threshold sensitivity on validation data.

Thresholds are chosen from validation/tuning data, not the frozen test set.

## 7. Unknown, abstention and invalid evidence

Qualification must demonstrate that:
- low-quality/ambiguous evidence produces Unknown rather than forced labels;
- non-subject crops caused by tracker/detector errors tend toward Unknown/Unavailable rather than confident false attributes;
- corrupt/hash-mismatched evidence becomes Unavailable;
- unsupported/applicability mismatches become NotApplicable at the correct level;
- missing model/startup incompatibility does not fabricate failed attribute rows.

Unknown is a product semantic and is therefore measured, not treated as an implementation exception.

## 8. Evidence-selection qualification

The Stage-2 Track Evidence Set is itself qualified.

Record:
- percentage of accepted Tracks with a valid mandatory Representative;
- supplemental-role admission rates;
- candidate/admitted/omitted counts by role;
- run-level evidence bytes and cap utilisation;
- crop dimension/encoded-size distributions;
- selector score distribution;
- redundancy/diversity metrics;
- failure cases by scale/occlusion/blur/crowding;
- quality impact of deterministic byte-cap re-encoding.

Compare Representative-only inference against Evidence-Set inference on the same labelled tracks.

The Evidence Set is retained only if it provides material Track-level quality/coverage benefit while respecting the declared bounds.

The architecture remains model-neutral even if qualification later changes the numeric evidence bounds.

## 9. Retrieval/product metrics

Model accuracy alone is insufficient. For each operator-exposed predicate/value family, evaluate realistic search result sets.

Record at predeclared result depths (for example N=10/25/50 where corpus size permits):
- result-set precision at N;
- recall/coverage where ground truth supports it;
- proportion of results whose supporting evidence is directly reviewable;
- Unknown/Unavailable exclusion semantics;
- conjunction behaviour for multi-attribute AND queries.

The report must state the exact population, query predicate and analysis identity.

## 10. Performance and resource qualification

Measure separately for supported CPU and CUDA Development variants where applicable:
- model initialization;
- READY time;
- mean/p50/p95 inference time per evidence crop;
- mean/p50/p95 per Track;
- batch behaviour;
- RAM;
- VRAM;
- sustained throughput;
- backlog drain behaviour;
- heartbeat margin versus lease duration;
- timeout/watchdog behaviour;
- bounded recovery after model failure;
- behaviour when detector and attribute roles share one host but separate processes;
- **variant equivalence**: where a release profile binds the same Model Pack on more than one runtime variant (CPU and CUDA), Track-level outcomes on the frozen test set must agree within a predeclared tolerance, because runtime variant is provenance rather than analysis identity (ADR-013 §11); a variant that fails equivalence is not bound for that profile.

A classifier OOM/crash must not invalidate the detector/tracker process or completed ProcessingRun.

## 11. Search/data qualification

At realistic and worst-supported fact volume:
- PostgreSQL query plan;
- query count;
- p50/p95 latency;
- allocation/memory where measurable;
- pagination stability;
- canonical predicate ordering;
- multi-attribute AND semantics;
- multi-camera attribute-only semantics;
- combined analytics + attribute identity pinning;
- snapshot consistency during concurrent analysis publication/supersession;
- no N+1 evidence fetch;
- v4 cursor length and tamper rejection.

A projection/materialization table is introduced only if measured plans justify it.

## 12. Lifecycle/resilience qualification

Prove:
- cancellation during evidence read;
- cancellation during inference;
- malformed model output;
- model exception/OOM;
- missing/corrupt evidence;
- hash mismatch;
- stale lease completion;
- heartbeat expiry and reclaim;
- retry after failure;
- re-analysis with a new model/aggregation identity;
- no partial default publication on failed completion;
- previous completed analysis remains intact after failed replacement analysis;
- supersession occurs only after successful completion;
- startup with required model unavailable leaves units Queued without consuming attempts;
- runtime/model version skew fails closed.

## 13. Component binding and provenance qualification

For capability-binding v2 prove:
- unsupported capability id fails closed;
- missing Model Pack fails closed for that role;
- model manifest hash mismatch fails closed;
- runtime/model compatibility mismatch fails closed;
- unrelated capability role can still become READY when an optional downstream capability is unavailable;
- modelPackId/runtimePackId/capabilityId appear in persisted provenance/digest;
- detector qualification records affected by runtime-profile v2 are explicitly reconciled rather than silently inherited.

## 14. Licence qualification

Every operational Model Pack has:
- licence identifier/text/source retained in the pack metadata;
- documented commercial/operational redistribution/use review;
- any attribution obligations captured in release material;
- no unresolved licence ambiguity at Stage-2 acceptance.

Licence review is a gate, not a documentation afterthought.

## 15. Offline qualification

With network disconnected:
- install/verify Runtime Pack;
- install/verify all Stage-2 Model Packs/bindings;
- start detector role;
- start attribute role independently;
- process real video to Track Evidence Set;
- lease an attribute analysis;
- fetch accepted evidence through the lease-scoped API;
- verify hashes;
- persist final outcomes + sealed prediction artefact;
- search attributes;
- open supporting evidence;
- verify no model-hub/package-index/remote request occurs.

## 16. Requalification triggers

At minimum, requalification is required for:
- Model Pack/checkpoint change;
- model input preprocessing change;
- attribute schema/value change;
- confidence/decision threshold change;
- aggregation-policy change;
- evidence selector scoring/role/bounds change;
- runtime dependency change that can affect numerical/model behaviour;
- runtime profile/variant change not explicitly covered by inheritance policy;
- capability-binding semantic change;
- material camera/domain expansion outside the qualified population;
- bug fix that can change predictions or evidence selection.

Documentation-only changes that cannot affect execution do not trigger model-quality requalification.

Each release records the exact trigger determination.

## 17. Acceptance evidence

Stage 2 cannot close on screenshots or one successful video.

Required retained evidence includes:
- frozen corpus manifest and partition manifest;
- annotation guide + agreement/adjudication report;
- minimum-support table;
- model/runtime/component identities and hashes;
- licence review;
- crop-level and Track-level accuracy report;
- held-camera/generalisation report;
- aggregation/abstention report;
- threshold table and validation rationale;
- evidence-selection report;
- performance/resource report;
- resilience/failure-isolation report;
- query/retrieval qualification;
- component-binding/provenance checks;
- disconnected offline run;
- real-video Search → Investigation → Evidence Review workflow;
- exact-head CI;
- independent cold review.

## 18. Freeze rule

Before any real attribute model is implemented:
1. annotation semantics are frozen;
2. dataset partition method is frozen;
3. minimum-support values are frozen;
4. operational metric gates are frozen using validation/tuning evidence only;
5. aggregation policy family and threshold-selection method are frozen;
6. frozen qualification test set is sealed.

Any later exception is documented as a protocol revision and invalidates prior final-test claims that it could bias.
