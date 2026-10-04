# ADR-017: Benchmark-first Development and Research Dataset Reuse

**Status:** Accepted owner decision, 2026-10-04 (Hari Om Ahlawat). Documentation adoption: it changes no code, validator, schema, runtime behaviour, acceptance row or qualification rule by itself.

**Date:** 2026-10-04

**Related:** ADR-015 (public-first Development, protected final qualification), which this ADR refines prospectively for Development data strategy and leaves otherwise intact; ADR-016 (detector-native vehicle subclass), unchanged; `docs/architecture/engineering-operating-principles.md` principles 4–6; the Stage-3 register `docs/reviews/2026-10-03-stage3-vehicle-subclass-acceptance.md`.

**Amends:** ADR-015 §5 (public acquisition and rights) prospectively, for Development, research evaluation and public benchmarking only. ADR-015's historical B0/S1 closure, its purpose pools, and its frozen-qualification admission contract (§3) and sequencing (§4) stand unchanged.

## Context

Stage 3 measured the detector-native vehicle subclass through a manual path: a frozen public-video pool, blind human labelling of 120 Tracks, adjudication and a T6 measurement (register G rows). That pilot works and its evidence is valid. It also shows the cost of the path: one 120-Track pilot yielded 103 evaluable cars, 7 buses, 5 trucks and 0 motorcycles, so three of four classes sit below the pre-registered support floor of 30. Reaching that floor for every class by hand would take hundreds more labelled Tracks per expansion round, with the same reviewers, packs and freezes.

Meanwhile the research community already publishes video datasets with per-frame boxes, track identities and vehicle class labels, under research-use terms. MAVI's own operating principles (4–6) already say to reuse proven datasets and benchmarks and to apply qualification-grade controls only where the claim needs them. What the repository lacked was a clear rule that makes benchmark reuse the default and manual annotation the justified exception, and a Development admissibility posture that does not block research use on imperfect licence wording.

## Decision

> **Capability follows validated evidence where practical.** For MAVI Development, component evaluation and research benchmarking, established labelled public and research datasets and benchmarks are the default evidence source. Manual annotation is a documented last-mile option for a demonstrated benchmark gap, not a prerequisite. Dataset-native taxonomies are respected and mapped explicitly; capability scope may follow what strong external evidence validates. Research-accessible data is admissible for Development on a research-forward, not licence-disregarding, posture. Final protected qualification stays separate.

### 1. Benchmark-first principle

Before proposing a manual annotation campaign, new bespoke ground truth, owner capture for Development, or a new human-review effort, an agent or engineer searches for existing labelled datasets and benchmarks that answer the engineering question, and records what was found. If a suitable benchmark exists, the Development evidence comes from it.

### 2. Manual annotation rule

Manual annotation is proposed only when all of these hold: no suitable labelled benchmark exists for the specific capability; the capability remains operationally important; the evidence gap is documented; and the owner explicitly accepts the annotation effort. It is not required merely because MAVI's desired ontology differs slightly from a benchmark, one class is missing from one dataset, or another public dataset uses another vocabulary.

### 3. Capability and evidence flexibility

Capability scope may evolve around strong existing evidence. An exact dataset mapping may validate a capability directly; a partial taxonomy may validate only a subset; different datasets may validate different subsets. Unsupported mappings are never fabricated. A class or feature that no strong evidence supports is deferred or stays Development-only; it does not hold back the classes that evidence does support. Exposure decisions remain per capability subset and per evidence domain, under the stage's acceptance register.

### 4. Dataset-native taxonomy

Public datasets are not forced into one MAVI ontology. Every dataset adapter declares, per native class: the native dataset class; the MAVI mapped class or capability, if any; the mapping kind (`exact`, `subset`, `unsupported`); the reason; and any evaluation exclusion. A lossy or semantically unjustified mapping is never treated as exact ground truth. A benchmark's own labels are reported in their own terms alongside any MAVI mapping.

### 5. Existing labels as ground truth

Where public video already provides track identities, per-frame boxes and class labels, MAVI evaluates against those labels. Humans are not asked to relabel the same data to turn it into a MAVI-specific Track truth. Deterministic adapter and association logic does that transformation, with its own tests.

### 6. Automatic ground-truth to MAVI association

Benchmark evaluation uses a deterministic association layer built only from prediction-independent geometry and time: frame and time overlap, IoU across overlapping frames, temporal continuity, one-to-one matching constraints, and association support and purity. Ambiguous and unmatched cases are reported as such, in both directions (ground-truth tracks MAVI never produced, MAVI Tracks no ground truth covers). They are never resolved by consulting MAVI's predicted class, subclass or confidence. The association design and its contracts are a plan and implementation matter; this ADR fixes only the direction.

### 7. Research dataset admissibility (Development, research evaluation, public benchmarking)

| Status | Meaning | Use |
|---|---|---|
| **RESEARCH-ADMISSIBLE** | Research or academic use is expressly permitted; or the material is lawfully obtainable and no term prohibits the intended research evaluation. | Use for Development and benchmarking. |
| **RESEARCH-UNCERTAIN** | Openly obtainable for research, but the terms are incomplete or ambiguous. | Use for Development; record the ambiguity and the intended research purpose; do not redistribute the source material. Development use is not blocked solely by imperfect wording. |
| **BLOCKED** | The data cannot actually be obtained; required access approval is denied or unavailable; payment or a licence purchase is required and the project is not obtaining it; access would require bypassing authentication, paywalls or technical controls; or the terms explicitly prohibit the intended research or evaluation use. | Do not use. |

Rules: research-use permission is sufficient for Development; non-commercial or research-only wording does not by itself eliminate a dataset from academic Development use; ambiguity is recorded, not converted into a prohibition; an explicit prohibition of the intended use blocks; payment, authentication and access controls are never bypassed; public availability never authorises redistribution; dataset bytes stay out of ordinary Git. The status, its basis and the source terms are recorded with the dataset's provenance before the data is used.

### 8. No silent benchmark contamination claims

Public benchmark exposure is recorded honestly. A public benchmark score is Development or reference evidence. If a candidate model may have trained on the same benchmark or its source imagery, known or possible exposure is recorded with the result. A respected benchmark does not make a score independent final qualification.

### 9. Qualification boundary

Development and benchmarking may use public research datasets aggressively under §7. Final protected Production qualification, where MAVI wants a strong independent claim, uses a separately protected holdout under the governing qualification policy (ADR-015 §3–§4). Nothing here changes that boundary, Production gates, role independence or existing machine schemas.

### 10. Implementation-first consequence

This policy exists partly to accelerate Development. Weeks are not spent constructing new mini-datasets when an established labelled benchmark answers the engineering question. Executable adapters, mappings, association and tests are preferred to prose.

## Consequences

- **Historical evidence stands.** The Stage-3 T10 pilot (register G rows) is a bounded real-domain Development cross-check that exercised the full MAVI, blind-label, adjudication and measurement path. It is kept unchanged and is not the mechanism for scaling Stage-3 evaluation.
- **Stage 3 next.** The roadmaps and the S3.2 plan direct S3.2d toward benchmark architecture and adapters, then real labelled benchmark execution, instead of a manual 300–500-Track expansion.
- **Tooling gap, recorded not hidden.** The S2c source-acquisition helper (`tools/qualification/source_acquisition/admission.py`) rejects a file whose licence code carries NC or ND and holds an unknown licence pending; the S3.2 release machinery requires an R-5 `determination` before derivation. Both are stricter than §7 for research-benchmark Development use. They are not changed by this ADR. Benchmark intake under §7 needs its own executable adapter and provenance path (S3.2d-1), with tests, before any dataset is used; until then no tool is claimed to behave as §7 describes.
- **No runtime change.** ADR-016 remains the detector-native source decision. The pipeline profile, vocabulary `mavi-vehicle-subclass-v1`, `minShare`, `minMatchedDetections`, stored subclass values and the absence of operator exposure are unchanged. Benchmark evidence may later justify a replacement source through its own ADR (ADR-016 §6).
- **Trade-off accepted.** Public benchmarks bring domain mismatch (dashcam, aerial, other countries) and possible training exposure against the cost and slowness of manual labelling. MAVI accepts that trade for Development, records the caveats with every result, and keeps the protected qualification path for claims that need independence.
