# MAVI Stage 2 — Visual Attributes

**Status:** Draft architecture and implementation plan for independent review. No Stage-2 feature code is authorised by this document until the architecture review is closed and ADR-013 is accepted.  
**Date:** 2026-09-23  
**Baseline:** `main@ca23adf55b0b4a14faf58e12d048a3c90221557c` — Stage 1 closed; post-merge Quality Gate #1945 and Task 17 Acceptance Validation #1089 green.  
**Roadmap position:** Stage 2, immediately after Spatial & Temporal Track Analytics.  
**Related:** capability-roadmap.md; capability-implementation-roadmap.md; ADR-005; ADR-006; ADR-007; ADR-009; ADR-011; ADR-012; dependency-and-offline-packaging-policy.md.

## 1. Purpose

Stage 2 adds evidence-backed visual appearance attributes to MAVI while establishing the architectural pattern for future model-based post-Track intelligence.

The product goal is not merely to attach labels to Tracks. The Stage-2 architecture must make every analytical capability independently replaceable, versioned, evidence-linked, re-runnable, bounded, offline-capable and qualification-traceable.

MAVI owns the intelligence semantics. Models are replaceable engines.

A Stage-2 result must therefore answer all of the following:

- what attribute was observed;
- on which Track;
- from which accepted evidence observation/crop;
- with what confidence;
- under which attribute schema;
- by which model/model pack and model version;
- under which inference configuration;
- in which attribute-analysis run;
- when the analysis occurred;
- whether the Track was analysed, unavailable, failed or not yet analysed.

No attribute is an identity claim.

## 2. Product outcomes

Examples of operator queries:

- person + red upper clothing + backpack;
- person + dark lower clothing;
- vehicle + white colour.

A result opens directly into the supporting Track evidence and source video. The UI exposes confidence and provenance and distinguishes observed, unknown and unavailable states.

The first Stage-2 capability set is intentionally small. Candidate v1 attributes are:

### Person
- upper-clothing colour;
- lower-clothing colour;
- bag/backpack presence;
- headwear/helmet presence, only if qualification demonstrates sufficient reliability.

### Vehicle
- dominant vehicle colour.

Vehicle subclass is not a Stage-2 requirement. Stage 3 owns expanded operational object/vehicle classes. Stage 2 may retain a model output internally for evaluation, but it must not expose subclass operationally unless Stage-3 ownership is deliberately revised.

Explicit non-goals:
- age;
- gender;
- ethnicity;
- face attributes or face recognition;
- fine-grained garment taxonomy;
- brand recognition;
- vehicle make/model;
- identity inference;
- cross-camera association;
- automatic Entity creation;
- natural-language search.

## 3. Architectural quality standard

Stage 2 adopts these rules:

1. **Logical modules are independently replaceable.** Detector, tracker, evidence selector, attribute inferencer, plate/OCR inferencer, embedding inferencer and future analytical engines communicate through MAVI-owned contracts.
2. **Logical architecture is independent of deployment topology.** A component may initially run in the existing Python process without becoming architecturally coupled to that process.
3. **Raw Track evidence and derived intelligence are different lifecycle classes.** Attribute-model failure must not invalidate an otherwise valid detection/tracking result.
4. **Historical analytical results are immutable.** Re-analysis creates a new analysis identity/version; it never silently rewrites the meaning of an old result.
5. **Every exposed analytical observation is evidence-linked.**
6. **Unknown is not false; unavailable is not unknown.**
7. **No model capability is exposed merely because a model can emit it.** Qualification determines the operational vocabulary.
8. **Offline and qualification disciplines are part of the feature, not release cleanup.**

## 4. Repository reality at Stage-2 entry

The current platform already contains `VisualAttribute` with:
- `TrackId`;
- optional `ObservationId`;
- `AttributeType`;
- `Value`;
- `Confidence`;
- optional `ModelName`;
- optional `ModelVersion`;
- `CreatedAtUtc`.

The table currently has a Track index and a confidence check. It is not populated by the processing path.

The current worker completion contract carries, per Track:
- broad object class;
- offsets and confidence summary;
- exactly one representative observation;
- one representative JPEG thumbnail;
- one trajectory artefact.

Although `ObservationType` contains `TrackStart`, `Representative`, `BestQuality` and `TrackEnd`, the current result store persists only the Representative observation from worker completion.

Therefore MAVI does **not** currently possess a reusable multi-view Track evidence set. That is an architectural constraint, not a documentation detail.

## 5. Target logical architecture

Stage 2 shall move toward:

```text
Recorded Video
    ↓
Detector
    ↓
Tracker
    ↓
Track Finalisation
    ↓
Capability-neutral Evidence Selection
    ↓
Platform-owned sealed Track evidence
    ↓
Post-Track Intelligence Plane
    ├─ Visual Attributes       ← Stage 2
    ├─ ANPR/OCR                ← Stage 4
    ├─ Embeddings/Similarity   ← Stage 5
    └─ future specialist models
    ↓
.NET validation and durable intelligence
    ↓
Search / Investigation / Evidence Review / Events
```

The key separation is:

**Track evidence is a durable input. Attribute inference is a derived, repeatable analysis over that evidence.**

## 6. Track Evidence Set

### 6.1 Why one representative image is insufficient

A representative frame is selected to summarize the Track. It is not necessarily the strongest frame for:
- upper/lower clothing;
- bag visibility;
- headwear;
- vehicle colour;
- plate visibility;
- future embedding quality.

Stage 2 therefore introduces a bounded, capability-neutral **Track Evidence Set**.

### 6.2 Evidence-selection policy

The selector is deterministic/versioned and evaluates candidate observations using factors such as:
- bounding-box pixel area;
- detector confidence;
- image sharpness/blur;
- clipping at frame edges;
- occlusion proxy where measurable;
- temporal separation;
- redundancy;
- view diversity where deterministically measurable.

The exact score and candidate bound are frozen in Slice 0/1 after measurement. A reasonable design target is a small bounded set, not every frame.

The selector must not depend on the selected attribute model. Otherwise changing the attribute model would also redefine raw Track evidence.

### 6.3 Persistence semantics

Selected evidence becomes platform-owned accepted evidence and remains linked to:
- Track;
- Observation;
- source frame number;
- video offset;
- bounding box;
- selection policy name/version;
- selection rank/score where retained;
- sealed crop artefact.

The exact schema is not frozen here. Two implementation options remain for Slice 0 review:
- extend Observation with generic evidence-selection metadata; or
- introduce a separate TrackEvidenceSelection record referencing Observations.

The design must support one Observation satisfying multiple future analytical capabilities without duplicating image bytes.

### 6.4 Upgrade semantics

Changing evidence-selection policy creates a new evidence-generation identity. Existing evidence is not silently reinterpreted. Re-generating evidence may require re-running the Track-finalisation path because current trajectory v1 does not retain per-sample bounding-box dimensions.

A future richer trajectory format may reduce that cost; Stage 2 must not require trajectory-v2 to begin.

## 7. Post-Track Intelligence Plane

### 7.1 Architectural decision

Visual Attributes shall be designed as an independent post-Track intelligence capability.

It must **not** be semantically part of detector/tracker completion.

The initial deployment may co-host the attribute executor inside the existing `mavi_vision` process/runtime for operational simplicity, but the contracts and lifecycle must permit later extraction to a separate worker/node without changing durable semantics.

ADR-013 records this decision in detail.

### 7.2 Why this boundary matters

It allows:
- attribute-model upgrades without re-running detection/tracking;
- historical Track re-analysis;
- attribute failure without failing raw Track ingestion;
- independent model packs and qualification;
- future reuse by OCR and embeddings;
- capacity scaling per analytical capability;
- separate retry/failure/readiness semantics.

### 7.3 Control-plane direction

Stage 2 should not overload `VisionJobCompleteRequest` with derived attribute output if doing so would make attribute completion part of raw processing completion.

The preferred design is a dedicated strict attribute-analysis contract and lifecycle, while reusing proven patterns:
- lease ownership;
- attempt count;
- claim token hashing;
- heartbeat/expiry;
- stale-attempt fencing;
- bounded completion;
- idempotent completion digest;
- accepted-evidence access;
- visibility sequencing where search publication requires it.

Whether this is a capability-specific `VisualAttributeJob` or the first typed instance of a generic post-Track `IntelligenceJob` is a Slice-0 decision. Avoid a prematurely generic “god job”; any generic abstraction must have at least the concrete Stage-2 semantics and a credible Stage-4/5 fit.

## 8. Attribute analysis identity

A Stage-2 analysis result needs an immutable analysis identity separate from ProcessingRun.

Conceptually:

```text
VisualAttributeAnalysis
- Id
- ProcessingRunId / Track scope
- AttributeSchemaVersion
- EvidenceSelectionPolicyVersion
- AttributePipelineVersion
- ModelPack identity/identities
- Runtime/component provenance
- State
- Attempt/lease identity
- Created/started/completed timestamps
- Publication/visibility identity
```

Every `VisualAttribute` row must be bound to the analysis that produced it.

A newer analysis may supersede an earlier one for default search while the earlier result remains historically readable.

## 9. Attribute schema and semantics

The attribute vocabulary is versioned configuration under `config/vision/`.

The schema defines:
- attribute type;
- object-class applicability;
- allowed values;
- whether the attribute is categorical, boolean-like or other;
- operational exposure status;
- minimum qualified confidence threshold;
- model/output mapping;
- display label;
- schema version.

Colour vocabulary must be intentionally small and qualification-driven. The exact v1 colour set is frozen only after model/corpus evaluation.

### 9.1 Presence attributes

For presence-like attributes such as backpack:

- `present` is an observed positive result above the qualified threshold;
- an explicit `absent` result is allowed only if the model and corpus support reliable negative classification and the schema defines that semantic;
- otherwise low-confidence/non-detection becomes `unknown`, not `absent`.

### 9.2 Coverage states

At minimum Track-level Stage-2 readiness distinguishes:

- **Ready / analysed** — the applicable attribute analysis completed;
- **Unknown** — analysis completed but no qualified value could be asserted for the requested attribute;
- **Unavailable** — the Track lacks required evidence/model applicability or predates analysable evidence;
- **Pending** — eligible analysis not complete;
- **Failed** — analysis attempted and failed;
- **Stale** — a newer default analysis identity exists or required model/schema changed.

Search must never turn Pending/Unavailable/Failed into an observed negative.

## 10. Attribute evidence and aggregation

The inferencer may evaluate several evidence observations per Track.

Raw model observations may disagree. MAVI must use a deterministic, versioned aggregation policy.

The default Track-level searchable attribute is therefore not “whatever one crop said”; it is the output of a frozen aggregation rule over bounded evidence observations.

The plan must record:
- crop-level model output;
- supporting ObservationId(s);
- confidence;
- aggregation policy/version;
- final Track-level attribute observation.

For UI explainability, at least one supporting evidence observation must be retained for every exposed value. Conflicting observations may be shown when operationally useful.

## 11. Provenance

The existing detector-oriented runtime provenance is insufficient to represent an independent attribute model cleanly.

Stage 2 shall record attribute-producer provenance including at least:
- component/capability id;
- attribute pipeline version;
- model id/version;
- modelPackId;
- manifest SHA-256;
- checkpoint/model-artifact SHA-256 as applicable;
- resolved config SHA-256;
- qualification id/hash;
- runtimePackId or compatible runtime identity;
- application build/commit;
- actual execution device;
- dependency/runtime identity required to reproduce the result.

Do not repurpose detector provenance fields to mean attribute provenance.

## 12. Model interface

The MAVI-owned logical interface is model-neutral.

Conceptually:

```text
VisualAttributeInferencer
Input:
  Track evidence observations
  Attribute schema version
  execution/model context

Output:
  bounded evidence-level attribute observations
  producer provenance
```

Model-specific tensors/classes must not cross into platform contracts.

A future model replacement must require no database/API/UI redesign if it implements the same qualified MAVI semantics.

## 13. Persistence direction

The existing `VisualAttribute` table should be evolved, not discarded.

Expected additions/changes to evaluate:
- analysis id / producer identity FK;
- schema version or analysis-derived schema binding;
- deterministic normalized type/value codes;
- supporting ObservationId required for evidence-backed values where applicable;
- uniqueness/idempotency constraint per analysis/type/value/observation or per frozen semantic;
- search indexes driven by measured query plans.

Do not add a per-Track summary table until measured PostgreSQL evidence demonstrates a need. Begin with typed attribute rows plus bounded `EXISTS`/join predicates and measure.

## 14. Search contract

Stage-2 predicates extend the same strict Track search architecture:
- whitelist;
- canonical URL state;
- stable filter fingerprint;
- snapshot semantics;
- bounded pagination;
- explicit coverage/readiness disclosure.

Multiple attribute predicates must have a canonical order and an unambiguous AND/OR contract.

Required examples:
- Person AND upper-colour red;
- Person AND upper-colour red AND backpack present;
- Vehicle AND colour white.

The exact HTTP representation is frozen in Slice 3 after contract review; do not invent ad-hoc query-string repetition without canonicalization tests.

Attribute-analysis identity/version used by the search must be pinned into the snapshot/fingerprint semantics where required so pagination cannot change meaning mid-search.

## 15. Operator experience

Stage 2 follows ADR-012.

Search:
- disclosed Visual Attributes filter group;
- no overwhelming model-centric controls;
- only operationally qualified attributes appear;
- confidence defaults should be schema/qualification driven rather than arbitrary operator tuning unless a mission requirement justifies manual thresholding.

Results:
- compact attribute chips;
- uncertainty/unknown not hidden;
- coverage state visible.

Investigation / Evidence Review:
- show attribute value;
- confidence;
- supporting crop;
- exact source frame/video jump;
- model/pipeline provenance in the provenance surface;
- where multiple supporting views matter, allow inspection without cluttering the primary workspace.

The UI must never imply identity from appearance attributes.

## 16. Offline/dependency architecture

Every Stage-2 model ships as a Model Pack under ADR-005/ADR-007:
- immutable model identity;
- manifest;
- cryptographic hashes;
- licence/notices;
- runtime compatibility;
- qualification record;
- offline-kit location.

Prefer models that run on the existing qualified runtime graph.

If a model requires new Python/native dependencies:
- update dependency policy;
- regenerate exact platform locks/projections;
- rebuild/requalify affected Runtime Pack(s);
- update Offline Binary Kit;
- verify disconnected install/run;
- record CPU/CUDA applicability separately.

No first-run network access, model hub lookup or telemetry.

## 17. Qualification strategy

Qualification is capability-specific and predeclared before selecting thresholds.

The Stage-2 corpus must cover at least:
- persons and vehicles separately;
- camera/view diversity;
- daylight / low light where Development corpus permits;
- indoor/outdoor where applicable;
- object scale bands;
- blur;
- partial occlusion;
- clipping;
- colour illumination variation;
- difficult negatives for bag/headwear.

Metrics:
- per-attribute precision/recall/F1;
- confusion matrix for categorical attributes;
- calibration/reliability where confidence is exposed;
- unknown/abstention rate;
- coverage rate by quality/scale band;
- latency and memory per Track/evidence set.

Operational exposure thresholds are frozen before final acceptance. An attribute failing its gate remains disabled even if the model emits it.

CPU qualification is mandatory for the supported CPU Development path. CUDA Development execution is separately evidenced where available. Neither equals Production qualification under ADR-009.

## 18. Performance and resource bounds

Freeze and test bounds for:
- evidence candidates per Track;
- bytes per crop;
- attribute observations per Track;
- completion body size;
- concurrent attribute units;
- model batch size;
- inference timeout/watchdog;
- DB rows per Track;
- search fan-out.

Performance acceptance must measure:
- attribute inference throughput;
- end-to-end post-Track latency;
- memory/VRAM;
- evidence storage growth;
- search query count/latency at realistic fact volume;
- cancellation/failure behaviour.

No N+1 path is acceptable.

## 19. Failure and re-analysis

Attribute analysis failure:
- does not alter ProcessingRun completion;
- does not delete Track evidence;
- is retryable under fenced ownership;
- does not publish partial default-search results unless a future contract explicitly supports partial results.

Re-analysis:
- creates a new immutable analysis identity;
- may use a new model/schema/aggregation policy;
- can supersede the previous default;
- preserves old results/provenance;
- supports bounded historical backfill.

## 20. Security and privacy

Appearance attributes are operational observations, not identity.

Stage 2 must:
- retain evidence linkage;
- avoid demographic/biometric attributes outside scope;
- prevent model metadata from exposing file-system secrets or external URLs;
- keep all runtime/model access offline;
- treat attribute search/read access under the same operator security boundary as Tracks until later audited access-control stages add finer policy.

## 21. Implementation slices

| Slice | Scope | Gate |
|---|---|---|
| **S0 — Architecture freeze** | ADR-013; exact attribute semantics; evidence-set design; analysis lifecycle; schema/provenance contracts; corpus protocol; threat/resource review | independent cold review clean of P1/P2; no feature implementation |
| **S1 — Track Evidence Set** | capability-neutral bounded multi-view observation/crop selection; strict worker raw-evidence contract; .NET validation/sealing/persistence; selector versioning | deterministic selector tests; evidence-byte bounds; existing Track semantics unchanged |
| **S2 — Attribute lifecycle + model component** | attribute-analysis unit/job; model-neutral inferencer; Model Pack; real CPU model inference; strict completion validation; immutable analysis provenance | real model on labelled Development corpus; failure isolation from ProcessingRun |
| **S3 — Persistence + Search** | VisualAttribute evolution; readiness/coverage; search predicates; cursor/fingerprint/version pinning; query qualification | semantic golden tests; PostgreSQL plan/query-count/latency evidence |
| **S4 — Operator UI + Evidence explanation** | filters, chips, Investigation/Evidence Review crop/provenance, source-frame jump, unknown/unavailable/failed states | accessibility + visual QA + real-data workflow |
| **S5 — Hardening / qualification / acceptance** | thresholds freeze; CPU/CUDA Development evidence; offline run; scale/resilience; re-analysis; docs; cold review | Stage-2 exit gate all PASS |

Slices may be subdivided if review shows a risk boundary, but implementation must not collapse architecture, model, search and acceptance into one PR.

## 22. Stage-2 exit gate

Stage 2 closes only when all are true:

1. ADR-013 accepted.
2. Track Evidence Set is bounded, sealed and provenance/versioned.
3. Raw detection/tracking completion is independent of attribute success/failure.
4. Attribute analysis can be re-run without re-running detector/tracker when the required sealed evidence already exists.
5. Every exposed attribute links to accepted evidence.
6. Attribute schema and operational vocabularies are versioned.
7. Unknown/unavailable/pending/failed semantics are proven end to end.
8. Attribute producer/model provenance is complete and immutable.
9. Search predicates are canonical, fingerprinted and snapshot-stable.
10. No N+1 or unbounded evidence/model I/O path remains.
11. Model accuracy/calibration gates are frozen and met for every exposed attribute.
12. Attributes failing qualification are not exposed.
13. CPU Development model/runtime evidence passes.
14. CUDA Development evidence is recorded where applicable, without Production claims.
15. Offline Binary Kit contains all declared Stage-2 dependencies/model bytes and disconnected execution passes.
16. Historical/re-analysis/supersession semantics are tested.
17. Operator Search → Investigation → Evidence Review path passes on real video.
18. Accessibility and visual QA have no open P1/P2.
19. Exact-head CI and relevant qualification workflows are green.
20. Independent cold review has no open P1/P2.
21. Documentation reflects measured reality.
22. Post-merge critical verification on `main` is green.

## 23. Decisions intentionally deferred to S0 review

The following are not silently frozen by this draft:
- capability-specific AttributeJob vs reusable typed IntelligenceJob control plane;
- exact Track Evidence Set schema;
- exact number of evidence crops;
- exact evidence-quality scoring formula;
- exact v1 colour vocabulary;
- exact model architecture/checkpoint;
- one person model plus one vehicle model vs a shared model;
- exact HTTP encoding of multiple attribute predicates;
- whether explicit negative presence values are reliable enough to expose;
- whether any new runtime dependency is justified;
- whether a future richer trajectory format should become a Stage-2 follow-up.

No implementation should guess these decisions.
