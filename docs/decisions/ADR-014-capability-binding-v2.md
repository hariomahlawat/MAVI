# ADR-014: Capability Binding v2, Model-Pack Neutrality and Capability-Scoped Qualification

**Status:** Accepted — Stage-2 architecture freeze; amended 2026-09-23 by the second independent cold pass (see *Acceptance gate*); amended 2026-09-27 to align with the S2a implementation plan merged at `main@76886ae1` (see *Amendment 2026-09-27*)  
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
  "schemaVersion": "mavi-vision-component-binding-v2",
  "bindingId": "...",
  "runtimePacks": [
    {
      "runtimePackFamilyId": "mmdetection-phase1-v1",
      "variants": {
        "windows-x86_64-cpu":  { "runtimePackId": "...", "thirdPartyLockSha256": "...", "runtimeRequirementsSha256": "...", "nativeAbi": "..." },
        "linux-x86_64-cpu":    { "runtimePackId": "...", "thirdPartyLockSha256": "...", "runtimeRequirementsSha256": "...", "nativeAbi": "..." },
        "windows-x86_64-cuda": { "runtimePackId": "...", "thirdPartyLockSha256": "...", "runtimeRequirementsSha256": "...", "nativeAbi": "..." }
      }
    }
  ],
  "roles": [
    { "roleId": "vision", "runtimePackFamilyId": "mmdetection-phase1-v1", "capabilityIds": ["detector"],
      "entryPoint": "...", "readinessContract": "...", "provenanceContract": "vision-job-complete-v3.2" }
  ],
  "capabilityBindings": [
    {
      "capabilityId": "detector",
      "roleId": "vision",
      "modelPackId": "mavi-model-v2-...",
      "qualificationId": "...",
      "enabled": true
    }
  ]
}
```

The example is the S2a shape. A later role (for example `attributes`, serving `person-attributes` and `vehicle-attributes`) is added as another `roles[]` entry together with one enabled binding per capability it serves; it needs no new structural field. `linux-x86_64-cuda` is absent from `variants` because it is a known but not yet releasable variant (§4a), not because it is optional.

Binding rules fixed by the S2a plan:
- **Runtime Pack family id is the runtime profile id** (`runtimePackFamilyId == runtimeProfileId`); there is no second family identity.
- **Ordering:** `capabilityBindings[]` are sorted by `capabilityId`, unique; any other order or a duplicate fails closed. This is the order used by identity fingerprints that consume the bindings (ADR-013 §11, §16).
- **Required vs optional is per role, not per binding.** Every capability a role serves must have exactly one enabled binding, or that role does not become READY; other roles are unaffected (§9). A disabled binding keeps its role from starting; nothing is enabled by default.
- **Naming:** a binding refers to its qualification record by `qualificationId`, the same field name the record itself carries.

Three properties of this shape are deliberate:

- **Runtime Packs are a list, and a binding names its role, which names its Runtime Pack family.** The current component manifest already keys Runtime Packs by platform variant (`runtimePacks["windows-x86_64-cpu"]` …); v2 keeps that variant dimension inside a family. A single top-level `runtimePackId` was rejected because the Stage-4 OCR engine is a native runtime with its own lock (capability roadmap, prerequisite matrix) and would have forced a v3 immediately. A role that needs a different dependency graph binds a different family; roles that share one graph share one family.
- **Roles are declared in this application/release overlay, not in the Runtime Pack.** A Runtime Pack contains only third-party material (ADR-007); which first-party entry point runs which capability is an application decision.
- **A binding references a qualification record; capability qualification status per platform variant lives in that record**, because CPU and CUDA variants of the same binding are qualified separately (ADR-009).

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

Three artefacts are distinct and must not be conflated:

1. **Source model manifest** (in Git, under the application overlay) — authored, capability-neutral description of a learned component;
2. **Built Model Pack manifest and install state** (outside Git; produced by the pack builder and the installer) — the measured, as-built record of one pack;
3. **`modelPackId`** — a derived material identity, never an authored field.

The **source model manifest v2** carries the common identity required for any learned component:
- manifest schema/version;
- model id and model version;
- capabilityId(s) implemented;
- artefacts: each with an `artifactRole`, a logical relative path and its SHA-256;
- declared input contract;
- declared output contract/schema;
- framework/runtime compatibility (the Runtime Pack families it may run on);
- licence: identifier, the artefact role of the licence notice, and review status;
- provenance/build/source metadata required by policy.

It does **not** carry `modelPackId` and does **not** carry byte sizes: an authored size would be an unmeasured claim. The **built Model Pack manifest** carries the derived `modelPackId` and each artefact's measured byte size and SHA-256, verified against the bytes; the **install state** records the `modelPackId` and artefact hashes and binds the built manifest by its SHA-256.

**`modelPackId` derivation (v2).** `modelPackId = "mavi-model-v2-" + SHA-256(canonical JSON of {schemaVersion: "mavi-vision-model-pack-v2", modelId, modelVersion, capabilityIds (sorted), artifacts: [{artifactRole, sha256}] (sorted by artifactRole)})`, encoded with sorted keys, compact separators and a trailing newline, as the existing pack identities are (`component_identity._digest_payload`). The `schemaVersion` input is the pack-identity schema, not the source manifest's own `schemaVersion`. Only material inputs participate; application commit, build provenance and qualification bookkeeping are never inputs. Builders compute it; the component binding and the offline kit inventory carry it; the worker resolver and repository verification re-derive it from the source manifest and compare; a mismatch fails closed.

**Licence notice is a Model Pack artefact.** Every Model Pack ships its licence notice as an artefact with role `licence-notice`; it therefore participates in `modelPackId` from the first v2 identity, so the id is frozen once at the cut-over and any later change to the notice is a visible identity change, never a silent one. For RTMDet the notice is the Apache-2.0 `LICENSE` of the already pinned mmdetection source revision. Licence review status is recorded as found — for RTMDet it remains pending review — and a `verified` manifest requires an approved review. Recording the notice implies no qualification or promotion.

Capability-specific optional sections may declare framework details such as resolved MMDetection configuration, tokenizer/vocabulary, OCR grammar or embedding dimension.

A resolved MMDetection config is therefore not a mandatory property of every Model Pack.

Unknown fields remain fail-closed under a versioned schema.

### 4. Runtime Pack describes the executable dependency environment, not one checkpoint

Runtime Pack identity describes the qualified third-party executable environment:
- Python/package/native dependency graph and its exact-hash lock;
- platform/runtime variant and native ABI;
- integrity hashes.

It does **not** carry roles, entry points or device policy: under ADR-007 the pack contains no first-party code, and those are properties of the application/release overlay (§1) and the deployment profile (ADR-008). The runtime profile (`runtime.json`) that describes a family must no longer require one detector checkpoint as the identity of the runtime itself.

Model bytes and model identity remain in Model Packs and capability bindings.

This deliberately changes the current runtime-profile hash. Existing detector qualification records affected by that identity change must be re-derived/reconciled in the same implementation slice; they are not silently inherited.

### 4a. One variant model: runtime profile, binding and qualification record answer different questions

The governed platform variants are one closed set: `windows-x86_64-cpu`, `windows-x86_64-cuda`, `linux-x86_64-cpu`, `linux-x86_64-cuda`. There is no second variant model; three artefacts answer three different questions about that set:

1. **Runtime profile** — which variants the Runtime Pack family knows and tracks, and each variant's runtime-graph releasability and qualification state (a statement about the dependency environment only — no model or capability claim). It lists every variant in the set.
2. **Component binding** — which variants the release can actually select and deploy now.
3. **Qualification record** — evidence and status across the whole governed variant set.

A variant's class is derived from the runtime profile and the tracked lock material only; it is never declared a second time:

- **Known but not yet releasable** — the runtime profile marks the variant `pending-hardware-qualification`, its release-lock entry is `pending-hardware-qualification`, and no lock file is tracked for it. The binding omits it. The qualification record keeps it with `runtimePackId: null`, status `pending`, every gate `pending`, and no profile qualification on that variant. It cannot start a role, pass qualification, become verified, or satisfy Production. Today: `linux-x86_64-cuda`.
- **Deployable** — lock material exists and the variant is not pending hardware qualification. The binding contains it with a non-null `runtimePackId`; binding, lock and qualification record cross-check. It may proceed subject to environment and qualification rules (§9, §10; a deployable variant whose release lock is still pending, such as Windows CUDA today, remains Development-only and is never `verified`).
- **Anything else fails closed** — an unknown variant, a variant that fits neither class, a deployable variant omitted from the binding (an omission is never read as "optional"), or a not-yet-releasable variant declared in the binding.

No placeholder Runtime Pack entry is ever created for a known-but-not-yet-releasable variant (no tracked lock file), and nothing derives a Runtime Pack identity from a qualification record.

**Development evidence shape.** A runtime-profile variant no longer records a resolved-config SHA-256: that is model identity and moves to the capability (the Model Pack's `resolved-config` artefact and the qualification record's `artifactSha256`). ADR-009's Development/Production separation is unchanged; existing Development evidence keeps its historical binding and is quoted, with old and new identities, in the S2a reconciliation record.

### 5. The application overlay declares independently startable roles

The overlay may declare one or more roles that run from a Runtime Pack family, for example:
- `vision` / detector-tracker;
- `attributes`;
- later `embeddings`, `ocr` or other specialist roles.

Each role declares:
- the Runtime Pack family it runs from;
- the capability ids it serves;
- its readiness contract;
- its first-party executable/entry point;
- the provenance it emits, as exactly one declared `provenanceContract`.

Its device policy comes from the deployment profile per role (ADR-008; ADR-013 §8). Several roles sharing one Runtime Pack family does not require co-hosting them in one process, and a role may later move to a different family or host without changing the bindings' meaning.

**The declared provenance contract is machine-enforced.** At startup the role's effective completion schema must equal its declared `provenanceContract`; otherwise the role does not become READY. A binding can therefore never claim a contract the role does not emit. The only exception is an explicit, Development-only compatibility override: it must be set deliberately, is logged, forces the run's verification status to `unverified` (non-qualifying by construction), and is refused in Production.

### 6. Qualification is capability-scoped

A qualification record binds the evidence to a specific:
- capabilityId;
- Model Pack identity;
- Runtime Pack identity per variant (`runtimePackId` for each deployable variant; `null` for a known but not yet releasable variant, §4a);
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
- runtime Pack identity **and its source** (below);
- runtime manifest/profile SHA;
- component binding SHA;
- runtime variant;
- actual device;
- platform build/commit;
- capability/pipeline schema version.

**Runtime Pack identity is reported truthfully, never fabricated.**
- Execution from an installed Runtime Pack reports its `runtimePackId` with `runtimePackSource = "installed-pack"`. The identity is re-derived from the installed pack's material inputs and must equal the binding entry for the observed variant.
- Development or CI execution from an unpacked environment (for example a virtual environment installed from the lock) reports `runtimePackSource = "unpacked-environment"` with no `runtimePackId`. The binding's id is never copied into provenance merely because no pack is installed.
- A `verified` or Production execution requires `installed-pack` with a matching `runtimePackId`. Unpacked execution is always `unverified`.

These fields are part of the relevant completion/analysis digest. Adding them to an existing completion contract is done under a new completion schema version with its own digest domain; stored digests of earlier versions are never reinterpreted, and replay selects the domain from the version persisted with the payload.

Derived application rows may reference their analysis header instead of repeating all model fields.

### 9. Selection and startup fail closed

At startup, a role validates:
- required capability binding exists and is enabled;
- Model Pack exists and matches its manifest hashes;
- capability id is supported by the runtime role;
- runtime/model compatibility declaration matches;
- required qualification status is allowed for the current environment;
- the observed platform variant is declared in the binding (a known but not yet releasable variant never starts, §4a);
- the effective completion schema matches the role's declared `provenanceContract` (§5);
- offline/dependency policy is satisfied.

A missing or incompatible capability of another role does not invalidate unrelated roles. For example, an unavailable attributes pack does not prevent the detector/tracker worker from becoming READY when its own bindings are valid.

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

The explicit migration aid is a one-shot, tested generator that reads the v1 binding, manifest, runtime profile and qualification record and writes their v2 equivalents; it is not a runtime reader. After the cut-over, v1 artefacts and v1 install state are rejected, not reinterpreted, and no period with two binding systems remains. New writes/releases use v2.

## Consequences

### Positive
- MAVI can add models without repeatedly redesigning runtime selection.
- Runtime and model identity are separated correctly.
- Qualification claims become truthful per capability.
- future OCR/embedding/specialist models fit the same binding contract.
- one broken capability of another role does not unnecessarily block unrelated workers.

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
5. Pack ids and hashes are durable provenance; a Runtime Pack identity is reported in execution provenance only when a pack is actually installed.
6. Unsupported/mismatched bindings fail closed.
7. Offline release completeness is verified for every bound capability.
8. Development qualification never becomes a Production claim by inheritance.

## Acceptance gate

The second independent cold pass on 2026-09-23 found that the first accepted shape carried one top-level `runtimePackId`, omitted the platform-variant dimension the existing component manifest already has, and placed roles/entry points inside the Runtime Pack contrary to ADR-007. Those were corrected in place (§1, §4, §5) and are recorded in the review-resolution document.

ADR-014 was accepted after the 2026-09-23 architecture review resolution and cold consistency pass confirmed:
- compatibility with ADR-005/007/009;
- no detector-specific mandatory field remains in the common model-manifest contract;
- migration/requalification consequences are explicitly represented in the Stage-2 implementation roadmap;
- no future Stage-4/5 capability requires a structural binding redesign.

## Amendment 2026-09-27

This amendment aligns ADR-014 with the S2a implementation plan (`docs/superpowers/plans/2026-09-27-stage2-s2a-component-binding-v2.md`, merged at `main@76886ae1`). It records decisions the plan pinned where the 2026-09-23 text was open or differed; it introduces no new architecture.

| Topic | 2026-09-23 text | Amended decision | Plan reference |
|---|---|---|---|
| Qualification reference | binding field `qualificationRecordId` | `qualificationId`, matching the record | §4.1 |
| Binding schema version | `"schemaVersion": 2` (illustrative) | string `mavi-vision-component-binding-v2`, like every existing loader | P-1 |
| Family identity | `mmdetection-phase1` (illustrative) | `runtimePackFamilyId == runtimeProfileId` | P-2 |
| `modelPackId` | a manifest v2 field | derived material identity (§3); not in the source manifest | P-3, P-14 |
| Byte size | a manifest v2 field | measured and recorded in the built Model Pack manifest; not authored in the source manifest. Install state binds the built manifest by SHA-256 and records the installed identity/integrity fields required by the implementation | P-14 |
| Licence | licence reference and review status | licence notice is an artefact in the identity from the first v2 id; RTMDet review pending | P-15 |
| Ordering / optionality | "ordered", "required"/"optional" undefined | sorted by `capabilityId`; required per role | P-5, P-6 |
| Binding provenance | — | `componentBindingSha256` in provenance and in the new completion digest domain (`mavi:vision-completion-digest:v3.2`) | P-7, P-11 |
| Runtime Pack provenance | `runtimePackId` always present | installed-pack vs unpacked-environment; never fabricated; verified/Production require an installed pack | P-8 |
| Role provenance | a role declares the provenance it emits | one `provenanceContract`, machine-enforced; explicit Development-only non-qualifying override | P-7, P-16 |
| Development evidence shape | variant carries resolved-config SHA (ADR-009) | config identity moves to the capability; historical evidence quoted in reconciliation | §4.3 |
| Variants | per-variant status in the record | one closed variant set; runtime profile / binding / record roles; known-not-releasable vs deployable vs fail-closed (§4a) | P-17 |
| Migration aid | "compatibility reader" | one-shot tested generator; v1 rejected after cut-over | §4.1 |

The 2026-09-23 example also listed an `attributes` role without a binding for its capabilities. Under the per-role rule that role could not start, so the example now shows only the S2a role and states how a later role is added.

Non-claims unchanged by this amendment: RTMDet remains `pending` on every variant and its manifest `unverified`; no Production or CUDA qualification is claimed; existing detector qualification identities are reconciled deliberately in S2a, never inherited; S1 remains formally OPEN.

## Proposed note 2026-09-28 (S2c planning): Development overlay binding

**Status: Proposed with the S2c plan (`docs/superpowers/plans/2026-09-28-stage2-s2c-learned-attribute-model-packs.md` §12.8); effective on acceptance of that planning change.** The repository today tracks exactly one binding and refuses any tracked Model Pack manifest or qualification record that no binding uses. S2c must run unverified learned attribute packs in Development without changing the release binding (whose SHA is the kit compatibility boundary and appears in every VisionJob's provenance) and without placing unverified packs in any Production kit. Decision: a tracked binding is either **the release binding** or a declared **Development overlay binding**. An overlay contains the release binding's roles, families and bindings unchanged and may add roles and their capability bindings; `verify_repo` checks the containment, counts a pack as bound when an overlay binds it, and refuses an overlay that alters anything the release binding declares. Only Development deployment profiles may select an overlay. This is enforced in code as well as by Setup: every pipeline profile an overlay role uses is `developmentOnly: true`, so the platform refuses it outside Development/Testing and the worker resolver refuses it in Production. An overlay is declared by an explicit path list owned by `verify_repo`, and its file name must start with `development-`; any other additional tracked binding still fails `binding_multiple_not_supported`. No binding schema field changes. *Trade-off:* two tracked bindings to verify, in exchange for keeping the release binding, its kit boundary and detector provenance untouched while an attribute capability is still unverified.

## Proposed note 2026-09-28 (S2c planning): Model Selection Records

**Status: Proposed with the S2c plan (§9.0, §9.6); effective on acceptance of that planning change.**

**Context.** Capability-scoped qualification (§6) records whether an exact Model Pack passed its gates. It does not record why that model was chosen, which alternatives were considered, or what a successor must beat. Without that history a later replacement can be justified by novelty alone.

**Decision.**
- Every Model Pack bound for a learned capability is the outcome of a recorded **Model Selection Event** under `docs/qualification/model-selection/README.md` (MSR method v1).
- The event keeps three assessments separate: technical, operational/engineering, and licence/deployment qualification. Licence never enters the technical ranking.
- The event retains every candidate, with the exact bytes evaluated.
- The event separates reported from MAVI-measured evidence.
- Once closed, the record is immutable.
- Each learned capability's gate set gains its own selection gate, `<capabilityId>-model-selection`. It is capability-prefixed because gate names are unique across all gate sets, and it is not in `common-v1`, so existing records are unaffected. Its evidence is the closed record, cited by path and LF-normalised SHA-256 with the existing `{kind, reference, sha256}` evidence shape. `verify_repo` re-derives that hash, the index hashes of every closed record, and the protocol hashes.
- A per-profile licence/deployment determination is evidence of the existing common `licence` gate in `profileQualifications`, not a licence-class-dependent gate.
- A replacement opens a new event and compares the challenger with the re-measured incumbent (§7 already makes a new pack a new qualification identity).
- The licence axis assesses the **declared MAVI deployment profile**, which is non-commercial ("enterprise-grade" means engineering quality). Each right the profile exercises is recorded separately; commercial-use permission is not required on its own, and redistribution is never assumed from "free of cost".
- **System scale is a selection criterion**: a model or composition is not selected on single-worker accuracy alone if its projected resource profile makes MAVI unsuitable at the declared scale (currently up to 500 cameras). The projection is reproducible and never presented as a scale qualification it did not execute.
- A multi-component capability selects a **composition** of sub-task components by a bounded rule frozen before results.
- Packs bound before this note (the Phase-1 detector) have no record. Their first replacement event states "selection history unrecorded (pre-methodology)".

No qualification-record schema field changes; the gate-set configuration gains capability gate sets. The MSR is decision history: the acceptance register remains the acceptance authority, and the qualification record the qualification authority.

*Trade-off:* each selection costs a written record and one hash check. In exchange, model choices stay auditable and reversible on evidence rather than memory.
