# ADR-014: Capability Binding v2, Model-Pack Neutrality and Capability-Scoped Qualification

**Status:** Proposed architecture-freeze candidate  
**Date:** 2026-09-23  
**Related:** ADR-005 Model Pack architecture; ADR-007 Runtime Pack architecture; ADR-009 Development vs Production qualification; ADR-013 modular post-Track intelligence

## Context

The current vision runtime was built around one detector capability. Repository review shows detector identity is embedded in several assumptions:
- component selection exposes one singular model pack;
- runtime profile carries one checkpoint/resolved configuration;
- qualification compares manifests against detector-era checkpoint/config hashes;
- model-manifest shape assumes detector/MMDetection fields;
- provenance does not durably persist modelPackId/runtimePackId per capability.

Stage 2 introduces additional model capabilities. Treating each new model as merely “another pack” without changing the binding/qualification architecture would create false qualification claims and repeated special cases.

MAVI therefore needs a capability-oriented component-binding layer before a second operational model is shipped.

## Decision

### 1. Component binding is an ordered set of capability bindings

The platform component-selection contract evolves from a singular model binding to a versioned shape conceptually equivalent to:

```json
{
  "schemaVersion": 2,
  "runtimePackId": "...",
  "capabilityBindings": [
    {
      "capabilityId": "detector",
      "modelPackId": "...",
      "enabled": true,
      "qualificationIdentity": "..."
    }
  ]
}
```

The schema is intentionally open to future declared capability ids. It must not hard-code Stage-2-only structural fields such as `personAttributesModel`.

Expected capability ids include, without limiting the schema:
- `detector`;
- `person-attributes`;
- `vehicle-attributes`;
- `plate-detector`;
- `ocr`;
- `embedding`.

Unknown capability ids fail closed unless explicitly supported by the selected runtime/application version.

### 2. Capability id is a stable contract name, not a model name

A capability id identifies the semantic function expected by MAVI.

Model/version/vendor/framework identity belongs to the bound Model Pack.

Replacing RTMDet with another qualified detector does not rename `detector`. Replacing one clothing classifier with another does not rename `person-attributes`.

### 3. Model manifests become capability-neutral

Model Pack manifest v2 contains the common identity required for any learned component:
- manifest schema/version;
- modelPackId;
- capabilityId(s) implemented;
- model/checkpoint artefact(s), SHA-256 and byte size;
- declared input contract;
- declared output contract/schema;
- framework/runtime compatibility;
- licence identifier/text reference and review status;
- provenance/build/source metadata required by policy.

Capability-specific optional sections may declare framework details such as resolved MMDetection configuration, tokenizer/vocabulary, OCR grammar or embedding dimension.

A resolved MMDetection config is therefore not a mandatory property of every Model Pack.

Unknown fields remain fail-closed under a versioned schema.

### 4. Runtime Pack describes executable/runtime capability, not one checkpoint

Runtime Pack identity describes the qualified executable environment:
- Python/package/native dependency graph;
- platform/runtime variant;
- supported capability interfaces/roles;
- device policy;
- executable entry points;
- integrity hashes.

The runtime profile must no longer require one detector checkpoint as the identity of the runtime itself.

Model bytes and model identity remain in Model Packs and capability bindings.

This deliberately changes the current runtime-profile hash. Existing detector qualification records affected by that identity change must be re-derived/reconciled in the same implementation slice; they are not silently inherited.

### 5. Runtime Pack may expose multiple independently startable roles

A Runtime Pack may support one or more roles, for example:
- `vision` / detector-tracker;
- `attributes`;
- later `embeddings` or other specialist roles.

Each role declares:
- supported capability ids;
- readiness contract;
- device requirements/policy;
- executable/entry point;
- runtime provenance.

Supporting multiple roles in one Runtime Pack does not require co-hosting them in one process.

### 6. Qualification is capability-scoped

A qualification record binds the evidence to a specific:
- capabilityId;
- Model Pack identity;
- Runtime Pack identity/variant;
- capability schema/output contract;
- pipeline/aggregation policy where relevant;
- corpus/test protocol;
- hardware/profile classification;
- gate set and result.

Gate names are capability-specific. Detector-era gates are not imposed on an attribute classifier merely because both use the same runtime graph.

Common gates may be shared by policy, including:
- integrity/offline installation;
- licence;
- startup/readiness;
- runtime compatibility;
- bounded failure/recovery;
- provenance completeness.

Capability-specific examples:
- detector: detection/tracking accuracy and runtime gates;
- attributes: per-attribute precision/recall/abstention and aggregation gates;
- embeddings: retrieval/verification metrics and index/version compatibility;
- OCR: character/plate sequence metrics and grammar/normalisation gates.

### 7. Qualification inheritance is explicit and narrow

No capability inherits qualification solely because it shares a Runtime Pack.

A runtime-only change may be inherited only when the qualification policy explicitly defines the unchanged identity and the evidence remains applicable.

A Model Pack replacement always creates a new capability qualification identity.

A runtime-profile structural migration from v1 to v2 requires explicit reconciliation of existing detector qualification identities even when model bytes are unchanged.

### 8. Provenance persists pack identities at the point of use

Every model execution provenance record includes at minimum:
- capabilityId;
- modelPackId;
- model manifest SHA;
- model/checkpoint/config SHA(s) as applicable;
- runtimePackId;
- runtime manifest/profile SHA;
- runtime variant;
- actual device;
- platform build/commit;
- capability/pipeline schema version.

These fields are part of the relevant completion/analysis digest.

Derived application rows may reference their analysis header instead of repeating all model fields.

### 9. Selection and startup fail closed

At startup, a role validates:
- required capability binding exists and is enabled;
- Model Pack exists and matches its manifest hashes;
- capability id is supported by the runtime role;
- runtime/model compatibility declaration matches;
- required qualification status is allowed for the current environment;
- offline/dependency policy is satisfied.

A missing or incompatible optional downstream capability does not invalidate unrelated roles. For example, an unavailable attributes pack does not prevent the detector/tracker worker from becoming READY when its own bindings are valid.

### 10. Development and Production remain distinct

ADR-009 remains authoritative.

A Development-qualified model/runtime binding cannot satisfy Production merely because the same pack is installed.

Production profiles retain their independent evidence and release gates.

### 11. Offline packaging remains complete and deterministic

Every capability binding reachable by a release profile must be represented in:
- offline dependency policy;
- Model Pack inventory;
- Runtime Pack inventory;
- licence inventory;
- integrity verification;
- installation/verification runbook.

No model hub, package index or first-run network resolution is allowed.

## Migration strategy

Implementation occurs as one dedicated Stage-2 architecture-enablement slice before real attribute models.

Required migration work includes:
1. component-selection schema v2 with `capabilityBindings[]`;
2. model-manifest v2 with capability-neutral common fields;
3. runtime-profile v2 decoupled from detector checkpoint identity;
4. capability-scoped qualification-record schema/policy;
5. provenance extension with modelPackId/runtimePackId/capabilityId;
6. verifier/offline-pack/CI updates;
7. deliberate detector qualification hash reconciliation;
8. compatibility tests proving current RTMDet/ByteTrack behaviour is unchanged apart from identity representation.

A compatibility reader may accept v1 configuration only as an explicit migration aid. New writes/releases use v2 after the slice closes.

## Consequences

### Positive
- MAVI can add models without repeatedly redesigning runtime selection.
- Runtime and model identity are separated correctly.
- Qualification claims become truthful per capability.
- future OCR/embedding/specialist models fit the same binding contract.
- one broken optional capability does not unnecessarily block unrelated workers.

### Costs
- current detector-era runtime hashes and qualification records must be reconciled;
- pack schemas, verification and CI become more sophisticated;
- migration code/tests are required.

These costs are accepted because Stage 2 is the first point at which the single-model assumption becomes structurally incorrect.

## Alternatives rejected

### A. Add `personAttributesModelPack` and `vehicleAttributesModelPack` fields
Rejected. This hard-codes the current stage and guarantees another schema redesign for OCR/embeddings.

### B. Duplicate one runtime profile per model
Rejected. It conflates executable dependency identity with model identity and multiplies qualification drift.

### C. Keep detector checkpoint embedded in runtime identity
Rejected. A runtime that can host multiple capability models cannot truthfully have one privileged checkpoint as its own identity.

### D. Treat shared Runtime Pack as shared model qualification
Rejected. Runtime compatibility and model capability quality are different claims.

## Invariants

1. Every learned capability is selected by a declared capability binding.
2. Model identity lives in Model Packs, not in domain semantics.
3. Runtime identity describes executable/dependency capability, not one privileged model checkpoint.
4. Qualification is capability-scoped and evidence-backed.
5. Pack ids and hashes are durable provenance.
6. Unsupported/mismatched bindings fail closed.
7. Offline release completeness is verified for every bound capability.
8. Development qualification never becomes a Production claim by inheritance.

## Acceptance gate

ADR-014 may move to Accepted only when a cold architecture review confirms:
- compatibility with ADR-005/007/009;
- no detector-specific mandatory field remains in the common model-manifest contract;
- migration/requalification consequences are explicitly represented in the Stage-2 implementation roadmap;
- no future Stage-4/5 capability requires a structural binding redesign.
