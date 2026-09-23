# ADR-013: Modular Post-Track Intelligence and Evidence Architecture

**Status:** Proposed — requires independent architecture review before acceptance  
**Date:** 2026-09-23

## Context

MAVI Stage 1 established a durable recorded-video intelligence core: detector/tracker output becomes platform-owned Tracks, Observations, sealed thumbnails and sealed trajectory artefacts; deterministic scene analytics then runs as an independent post-processing lifecycle.

Stage 2 introduces the first additional learned capability after detection/tracking: Visual Attributes.

A simplistic design would run an attribute classifier inside the existing detector/tracker completion path and append attribute rows to the same completion transaction. That is operationally easy but creates long-term coupling:

- attribute-model failure can threaten valid detector/tracker completion;
- changing the attribute model pressures the detector/tracker qualification boundary;
- historical Tracks cannot be re-analysed independently;
- future OCR and embedding capabilities repeat the same coupling;
- one representative thumbnail is not sufficient evidence for all future appearance tasks.

The product requirement is a long-lived, upgradeable operational system. Analytical components must therefore be replaceable without redesigning durable MAVI semantics.

## Decision

### 1. Separate raw Track evidence from derived model intelligence

Detection/tracking produces **raw Track evidence**.

Visual Attributes, OCR, embeddings and later learned capabilities are **derived post-Track intelligence**.

A derived capability does not define whether a ProcessingRun succeeded.

### 2. Introduce a capability-neutral bounded Track Evidence Set

A Track may have several selected, accepted evidence observations/crops.

Selection is:
- deterministic;
- bounded;
- versioned;
- independent of the attribute model;
- linked to original source frames and bounding boxes;
- sealed through the platform-owned accepted-evidence boundary.

The Representative observation remains the primary display summary but is not the only analytical evidence source.

### 3. Treat Visual Attributes as an independent logical component

The attribute inferencer consumes MAVI-owned Track evidence and emits MAVI-owned attribute observations.

It is not allowed to:
- persist directly to PostgreSQL;
- redefine Track identity;
- create Entity identity;
- publish model-specific structures into application contracts.

### 4. Logical separation does not require immediate process separation

The Stage-2 attribute executor may initially run inside the existing `mavi_vision` process/runtime.

That is a deployment choice only.

Its lifecycle, input/output contract and durable semantics must permit later movement to:
- a separate worker process;
- a separate GPU node;
- a differently scaled worker pool;

without changing the meaning of persisted attributes or the application/search contract.

### 5. Attribute analysis has an independent lifecycle and identity

Attribute analysis is re-runnable independently of detection/tracking when the required sealed Track evidence exists.

A new model/schema/policy creates a new analysis identity. Existing results remain immutable.

Default search may select the current completed analysis identity; historical analysis remains traceable.

### 6. Attribute failure cannot invalidate Track evidence

A valid completed ProcessingRun and its sealed Track evidence remain valid even if:
- the attribute model is unavailable;
- inference times out;
- analysis fails;
- a model pack is upgraded;
- re-analysis is pending.

The operator sees the corresponding attribute coverage/readiness state.

### 7. Reuse proven control-plane properties

The post-Track lifecycle shall reuse the established MAVI properties:
- bounded input/output;
- lease ownership;
- attempt fencing;
- stale-attempt rejection;
- heartbeats/expiry;
- idempotent completion digest;
- deterministic validation;
- immutable provenance;
- fail-closed evidence access;
- explicit retry/re-analysis.

Implementation may share libraries/patterns with VisionJob and SceneAnalytics but must not blur their domain meanings.

### 8. Future model-based stages should follow the same architectural pattern

Stage 4 ANPR/OCR and Stage 5 embeddings should preferentially consume sealed Track evidence through the same architectural boundary where their evidence needs permit it.

This ADR does not force one generic database table or one generic worker job for all capabilities. Reuse is at the architectural contract/pattern level unless concrete requirements justify a shared abstraction.

## Consequences

### Positive

- detector/tracker correctness is isolated from downstream model churn;
- attribute models can be upgraded and historical Tracks re-analysed;
- evidence quality can improve independently from model architecture;
- future model capabilities inherit a clean boundary;
- model/runtime qualification becomes capability-scoped;
- application/search semantics remain stable across model replacements;
- attribute failures become observable degraded capability rather than failed video processing;
- separate worker scaling remains available without redesign.

### Costs

- Stage 2 must build a bounded multi-view Track evidence path;
- a second analytical lifecycle/control plane is required;
- additional persistence and readiness semantics are needed;
- offline packaging/qualification becomes multi-model;
- more explicit provenance is required;
- some historical Tracks may remain unavailable until suitable evidence is generated.

These costs are accepted because they buy long-term replaceability, re-analysis and failure isolation.

## Alternatives considered

### A. Add attributes directly to VisionJob completion

Rejected as the target architecture. It makes derived model success part of raw Track publication and makes model upgrades unnecessarily coupled to detector/tracker execution.

### B. Run a completely separate attribute service immediately

Not required. Process separation is premature if the same qualified runtime and hardware can host the component efficiently. Logical separation and a stable contract are sufficient at Stage-2 entry.

### C. Use only the Representative thumbnail

Rejected as the long-term evidence contract. One display-oriented frame cannot be assumed to be optimal for clothing, bag, headwear, vehicle colour, plates and embeddings.

### D. Store every frame/crop

Rejected. It creates unacceptable storage, I/O and privacy/resource cost. The evidence set is bounded and selected.

### E. Build a universal generic “AI job” abstraction now

Rejected unless S0 review proves a clean type-safe abstraction using Stage 2 plus credible Stage-4/5 requirements. Premature generalization would hide capability-specific semantics.

## Invariants

Stage 2 and later model-based capabilities must not violate:

1. Python/model components do not directly own durable operational intelligence.
2. Every persisted analytical assertion is reproducible from versioned producer identity and accepted evidence.
3. Track and Entity remain different concepts.
4. Unknown/unavailable/pending/failed are not observed negatives.
5. Historical analytical meaning is immutable.
6. Search remains whitelist-validated, canonical and snapshot-stable.
7. Worker/model outputs are bounded.
8. Dependencies and model bytes are fully offline-declared and integrity-verified.
9. Development evidence never becomes a Production qualification claim.
10. No model replacement requires a redesign of MAVI domain semantics if the replacement implements the same qualified contract.
