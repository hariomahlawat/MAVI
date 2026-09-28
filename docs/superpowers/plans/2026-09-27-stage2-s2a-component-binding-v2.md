# Stage 2 — S2a Component Binding v2: implementation plan

- **Date:** 2026-09-27
- **Status:** S2a.0 — plan accepted for cold review. Nothing here is implemented. No acceptance-row status changes. No behaviour change in S2a.0.
- **Baseline (frozen S1 engineering baseline):** `c176b048e278f7097d49254efc47d89917f687c0`
- **Companion decision note:** `docs/qualification/stage2-s1/2026-09-27-s1-engineering-baseline-closure-identity.md`
- **Governing authority:** ADR-014 (accepted, amended 2026-09-23), ADR-007, ADR-009, ADR-013; `docs/superpowers/plans/2026-09-23-visual-attributes.md` §9/§12/§22; acceptance rows C1–C7 in `docs/reviews/2026-09-23-visual-attributes-acceptance.md`.
- **Precedence:** where this plan and ADR-014 differ, ADR-014 governs. Where this plan and the parent plan §9 differ, ADR-014 governs (parent plan §9 still carries the rejected "one Runtime Pack identity" bullet; corrected in S2a.5).
- **ADR amendment required before S2a.1:** decisions P-3 (v2 `modelPackId` derivation replaces ADR-007 L21's formula), P-8 (`runtimePackId` nullable with `runtimePackSource`, versus ADR-014 §8's unconditional list), P-14 (`modelPackId` not in the *source* manifest, versus ADR-014 §3) and the field name `qualificationId` (ADR-014 §1 shows `qualificationRecordId`) change ADR text. They are raised as a short ADR-014 amendment (with an ADR-007 note) in a docs-only PR that must merge before S2a.1 starts; this plan does not edit the ADRs.

---

## 1. Scope and non-goals

### 1.1 In scope (C1–C7)

| Row | Deliverable in this plan |
|---|---|
| C1 | Component binding v2 (`capabilityBindings[]`, roles, Runtime Pack families keyed by variant). §4.1 |
| C2 | Model manifest v2, capability-neutral common schema; MMDetection config becomes a capability-specific section. §4.2 |
| C3 | Runtime profile v2 without a privileged checkpoint; roles declared in the overlay binding. §4.3 |
| C4 | Qualification record v2, capability-scoped, common + capability gate sets. §4.4 |
| C5 | `capabilityId`, `modelPackId`, `runtimePackId`/`runtimePackSource`, `componentBindingSha256` persisted in provenance and in a new completion digest domain (completion schema 3.2). §4.5 |
| C6 | `verify_repo`, offline kit tooling, installers/launcher and CI fail closed on binding/manifest/runtime mismatch. §6–§8 |
| C7 | RTMDet identities (runtime-profile SHA, manifest SHA, modelPackId, qualificationId) deliberately re-derived; RTMDet remains `pending`/`unverified`; behaviour regression proven by record/replay comparison and Task-10. §9 |

### 1.2 Non-goals (explicitly out)

- No `VisualAttributeAnalysis` lifecycle, no attribute worker role implementation, no attribute models, no attribute search (S2b/S2c/S3).
- No promotion of RTMDet qualification status. Every RTMDet gate stays `pending`; the manifest stays `unverified`.
- No Production qualification. No CUDA qualification.
- No change to S1 measured semantics: evidence roles, scorer `quality-v2`, selector `evidence-selector-v1-two-tier`, caps, finalization configuration, completion 3.1 exchange semantics, sealing plan, accepted-evidence keys. Completion 3.2 adds provenance fields only.
- No new Runtime Pack. The `mmdetection-phase1-v1` locks are unchanged byte-for-byte, so every `runtimePackId` is unchanged.
- No change to `tools/qualification/s1_evidence.py` rules, and no rerun of S1 units. See the companion decision note.
- No general qualification-platform rewrite. S2a's own evidence is engineering regression + boundary proof + one Task-10 rerun (§15).
- No rewrite of the S1.4 qualification harnesses beyond the changes forced by the composition change and the P-16 completion-setting retirement (§5.3 lists them exactly).

### 1.3 Architectural decisions inherited (not re-opened)

From ADR-014: bindings are an ordered set (§1); capability id ≠ model name (§2); model manifests are capability-neutral (§3); Runtime Pack identity carries no checkpoint, roles or entry points (§4); roles live in the overlay (§5); qualification is capability-scoped (§6) with explicit narrow inheritance (§7); provenance persists pack identities and they enter the digest (§8); startup fails closed per role (§9); Development ≠ Production (§10); offline completeness is verified per binding (§11).
From ADR-007: three layers (Runtime Pack / Model Pack / overlay); pack ids derive from material inputs, never from commit or qualification bookkeeping; v1 installed state is rejected, not reinterpreted.

---

## 2. Current-state inventory (verified at `c176b048`)

### 2.1 Artefacts (all singular, all v1)

| Artefact | Path | Schema | Coupling that v2 removes |
|---|---|---|---|
| Application binding | `src/vision/config/components/mmdetection-phase1-v1.json` | `mavi-vision-component-requirements-v1` | one `modelPack` object; no roles; no capability ids |
| Model manifest | `models/manifests/rtmdet-m-coco-phase1-v1.json` (SHA `0049875d…`) | `"1.0"` (`manifest.py:70-117`, `extra=forbid`) | `checkpoint`, `resolvedConfig`, `backend`, `architecture` mandatory |
| Runtime profile | `src/vision/runtime/mmdetection-phase1-v1/runtime.json` (SHA `b3c59ac4…`) | `"1.0"` (`qualification.py:556-658`) | top-level `checkpoint` and `resolvedConfig`; every `platformVariants[*].resolvedConfigSha256` bound to the detector config |
| Qualification record | `models/qualifications/rtmdet-m-coco-phase1-v1.json` | `"1.0"` (`qualification.py:669-765`) | binds `checkpointSha256`, `resolvedConfigSha256`, `runtimeProfileSha256 b3c59ac4…`, `modelManifestSha256 0049875d…`; detector-era `MANDATORY_QUALIFICATION_GATES` imposed on every record |
| Pipeline profile | `src/vision/config/pipelines/phase1-detection-tracking-v1.json` (SHA `503225be…`) | `"1.1"` | names one `modelId` — **unchanged by S2a** |

### 2.2 Code paths that hold the single-model assumption

| Concern | Location |
|---|---|
| Composition root | `mavi_vision/runtime/qualification.py:1077-1196` `verify_release_selection` (manifest ↔ runtime checkpoint/config ↔ record) |
| Worker paths | `mavi_vision/common/settings.py:24-40` (six singular paths; the worker never reads the binding file) |
| Supervisor | `mavi_vision/runtime/supervisor.py:237-345, 814-826` (always `MMDetectionRuntime`, one provenance) |
| Provenance | `mavi_vision/runtime/provenance.py:158-228` (`RuntimeProvenance` without pack ids), `:336-354` (runtime variant inferred from the host), `:357-422` (`_runtime_binding_mismatch` compares the runtime variant's `resolvedConfigSha256` to the model config) |
| Pack identity | `mavi_vision/runtime/component_identity.py:30-34, 71-79` (`modelPackId` = f(modelId, checkpoint, config)) |
| Wire contract | `contracts/schemas/vision-job-complete-v3.1.schema.json` `$defs/provenance` (`additionalProperties:false`, 23 required fields); `Mavi.Contracts/Worker/VisionJobCompleteContracts.cs:22-53` (`JsonUnmappedMemberHandling.Disallow`) |
| Digest | `Mavi.Application/Modules/Intelligence/VisionResultValidator.cs:478-610` (domain `mavi:vision-completion-digest:v3` shared by 3.0 and 3.1; fixed field order; golden vector `contracts/test-vectors/vision-job-complete-v3-digest.json`) |
| Persistence | `processing_runs.runtime_provenance_json jsonb` (untyped blob); `detector_name`/`detector_version` columns filled from `modelId`/`modelVersion` |
| Platform validation | `VisionRuntimeProvenanceParser.cs:76-192` — shape only; the platform pins no expected identity |
| verify_repo | `tools/verify_repo.py:48-51` (`REQUIRED_PATHS` omits the binding file), `:143-153` (`RELEASE_TEXT_ROOTS` omits `config/components`), `:1201-1525` (`check_vision_release_metadata`: runtime checkpoint/config must equal manifest) |
| Builders | `tools/vision/build_model_pack.py` (two hard-wired artefacts), `sync_offline_vision_components.py:232` (Windows-CPU-only), `verify_offline_component_ownership.py:66-86` (exactly one runtime + one model pack) |
| Installers/launcher | `tools/setup/Start-MaviVisionWorker.ps1:83,146-171`, `Mavi.VisionRuntime.Common.psm1:72-98, 316-367`, `Install-MaviVisionModelPack.ps1:6,23,70-76`, `Test-MaviEnvironment.ps1:95-121`, `Sync-MaviOfflineVisionComponentStore.ps1:31` |
| CI | `.github/workflows/vision-runtime-component-boundary.yml:158-178`, `vision-model-pack.yml:121-132` (compare against v1 shape); `task12-offline-bundle.yml` never compares the built `runtimePackId` to the binding |
| Snapshots | `docs/qualification/task18-readiness-v1.json` `componentSelection` (unvalidated; already lacks the CUDA pack id) |

### 2.3 Pre-existing defects found during inventory

- **D-1 (operator path; repaired in S2a.4):** `tools/setup/Setup-MAVI.ps1:357-369` probes `bundle-manifest.json`, but `Install-MaviVisionRuntime.ps1:30` requires `runtime-pack-manifest.json`. Guided setup therefore never auto-installs a Runtime Pack (it prints INFO "bundle not present") and never installs a Model Pack. The manual runbook path works. Not touched in S2a.0.
- **D-2 (harness design; principle recorded now, narrow fix no earlier than S2a.5):** `tools/qualification/s1_memory.py:665` records `runtimeVariant` from `MAVI_RUNTIME_VARIANT`, which no operator document sets; a null is only rejected at `derive`, after the runs. The .NET harnesses derive the variant from the OS (`S1QualificationSupport.RuntimeVariant()`). Principle for all future qualification tooling: validate required identity **before** the expensive run starts; fail immediately if it is absent or inconsistent; prefer host/runtime-derived identity; never discover a mandatory provenance omission after hours of execution. `s1_memory.py` is not modified in S2a.0–S2a.4.
- **D-3 (documentation; S2a.5):** parent plan §9 bullet "one Runtime Pack identity" contradicts ADR-014 §1.

---

## 3. Design decisions this plan pins (ADR-014 leaves them open)

| # | Decision | Rationale |
|---|---|---|
| P-1 | `schemaVersion` strings follow repository convention: `mavi-vision-component-binding-v2`, model manifest `"2.0"`, runtime profile `"2.0"`, qualification record `"2.0"`, model pack manifest `mavi-vision-model-pack-v2`, model install state `mavi-vision-model-install-v2`, inventory `mavi-offline-vision-component-inventory-v2`. | ADR-014 §1 example (`2`) is "conceptually equivalent"; every existing loader is a string `Literal`. |
| P-2 | **Runtime Pack family id == `runtimeProfileId`** of the profile directory (`mmdetection-phase1-v1`). No second id. | One identity per family; the profile *is* the family description (ADR-014 §4 "the runtime profile that describes a family"). |
| P-3 | **`modelPackId` v2 derivation:** `mavi-model-v2-` + SHA-256 of canonical JSON (`sort_keys`, compact separators, trailing `\n`, as `component_identity._digest_payload` does today) of `{schemaVersion:"mavi-vision-model-pack-v2", modelId, modelVersion, capabilityIds:[sorted], artifacts:[{artifactRole, sha256} sorted by artifactRole]}`. The source manifest in Git does **not** carry `modelPackId`; builders, the binding file and the kit inventory carry it, and `verify_repo` re-derives it. | Identity from material inputs only (ADR-007). Capability-neutral (no config/checkpoint privilege; no byte size — size is measured by the builder, not asserted by the author). RTMDet's id changes deliberately (C7); bytes do not. |
| P-4 | Capability ids are a closed registry in code (`mavi_vision/runtime/capabilities.py`: `detector`, `person-attributes`, `vehicle-attributes`, `plate-detector`, `ocr`, `embedding`). The binding schema accepts any lowercase kebab id syntactically; the resolver and `verify_repo` reject ids outside the registry. Only `detector` has a runtime implementation in S2a; every other id is *declarable* but *not startable* (resolver error `capability_not_implemented`). | ADR-014 §1 L60/L70 both satisfied: open schema, fail-closed application. |
| P-5 | **Ordering:** `capabilityBindings[]` must be in ordinal order of `capabilityId`; a validator rejects any other order and duplicates. The canonical identity fingerprint (ADR-013 §11/§16, used later by S2b) is therefore declaration order. | Removes the "ordered" ambiguity with zero runtime cost. |
| P-6 | **Required vs optional:** a role's `capabilityIds` are all required for that role to become READY. Optionality is per role, not per binding: a role whose bindings are invalid fails; other roles are unaffected. No `optional` flag. | Satisfies ADR-014 §9 ("unavailable attributes pack does not prevent the detector worker") with the minimal shape. |
| P-7 | **Completion schema 3.2** = 3.1 exchange + five provenance fields (§4.5). New digest domain `mavi:vision-completion-digest:v3.2`. 3.0/3.1 bodies are still accepted and must **not** carry the new fields; 3.2 bodies must. Replay uses the schema version persisted with the finalization payload. Worker default flips to `"3.2"` in S2a.3, and only when the worker can truthfully emit every required identity field; the platform's asynchronous set becomes `{"2.0","3.1","3.2"}` from S2a.2 (3.0 stays synchronous-only). **The role's declared `provenanceContract` is machine-enforced** (P-16). | Stored v3 digests stay replayable; the S1.4 F4-C activation-gate pattern is reused unchanged. |
| P-8 | `runtimePackId` in provenance is required when `production_mode` or when the effective `verificationStatus` is `verified`; otherwise it may be `null`, always paired with `runtimePackSource: "installed-pack" \| "unpacked-environment"`. A Linux CI venv built from the lock is `unpacked-environment`. An installed pack is cross-checked (id, `platformVariant`, `thirdPartyLockSha256`) against the binding and the family's `releaseLocks`. | Truthful: a venv is not a pack. Forbids a verified/Production claim without pack identity. Never fabricates an id. |
| P-9 | The worker locates manifests and records by **scanning** `models/manifests/*.json` and `models/qualifications/*.json` under the overlay and indexing by derived `modelPackId` / `qualificationId`. Two files deriving the same id fail closed (`model_manifest_ambiguous`). Per-path env vars `MAVI_MODEL_MANIFEST_PATH`, `MAVI_QUALIFICATION_RECORD_PATH`, `MAVI_RUNTIME_PROFILE_PATH` are **removed**; because `WorkerSettings` uses `extra="ignore"` (`settings.py:14`), an explicit `os.environ` check in `main.py` rejects any of them (`settings_v1_composition_rejected`). `MAVI_PIPELINE_PROFILE_PATH` stays (pipeline policy is not a component). | One composition source (constraint 14). `verify_repo` moves to the same derived-id index (today it indexes by `modelId`, `:1304`). |
| P-10 | **Store layout, one formula everywhere.** An artefact resolves at `<model_root>/<relativePath>` (unchanged, `qualification.py:1136-1137`). Manifest v2 requires every `relativePath` of a pack to share one first segment, its `packDirectory` (today `rtmdet-m-coco-phase1-v1`), unique across manifests (`verify_repo` enforces both). `model_root` is a shared **store** root and each pack is self-contained in `<store>/<packDirectory>/`: its artefacts, its `model-pack-manifest.json` and its `model-install.json` (v2). Windows: `MAVI_VISION_MODEL_ROOT` becomes the store root (default `…\VisionModels`, replacing the per-model default at `Install-MaviVisionModelPack.ps1:6` and `Start-MaviVisionWorker.ps1:129`). `Install-MaviVisionModelPack.ps1` v2 stages and swaps **per pack** (`<store>/<packDirectory>`, not the whole root as `:108-110,124-138` do today) and scopes the declared-file integrity check to that directory (`:55-62` and `Mavi.VisionRuntime.Integrity.psm1:59-63` are per-pack in v2), so installing a second pack never touches or fails the first. The Task-10 `.qualification-model-root` layout (`task10…yml:618-622`) is unchanged. v1 `model-install.json` is rejected (re-install required), mirroring ADR-007's treatment of v1 runtime state. **The installer that produces this v2 state ships in S2a.3, in the same PR as the launcher that requires it** (§5.4). | Multi-pack without new concepts or path changes; installability preserved through the cut-over. |
| P-11 | `componentBindingSha256` (SHA-256 of the binding file bytes) is added to provenance and the 3.2 digest. | Cheapest durable identity of the *whole* selection; makes any binding edit visible in every completion. |
| P-12 | Gate sets are declared in `config/acceptance/capability-gate-sets-v1.json`: `common-v1` (`offline-install`, `licence`, `startup-readiness`, `runtime-compatibility`, `bounded-failure-recovery`, `provenance-completeness`) and `detector-v1` (`detection-tracking-accuracy`, `cctv-quality-baseline`, `recovery-performance`). Gates are evaluated **per variant**; variant coverage and OS are structural (the `variants` map), not gate names. The eight v1 gate names (`qualification.py:33-44`: four variant names, `windows-/linux-offline-install`, `cctv-quality-baseline`, `linux-nvidia-recovery-performance`) are mapped to their v2 home in the reconciliation document (variant names → `variants.<v>.status`; the two install gates → `common-v1/offline-install` under the matching variants; the two quality/perf gates → `detector-v1`). A record names `gateSetIds`; the loader requires every gate of every named set under every variant (status may be `pending`). | C4 with one small policy file and no self-referential gate names. |
| P-13 | **Windows CUDA stays deployable for Development only.** Under P-17 `windows-x86_64-cuda` is *deployable* (tracked `windows-x86_64-cuda.lock`; variant status `qualified-development-hardware`), so the binding declares it; its `releaseLocks` entry is `pending-hardware-qualification` with no `sha256`, so the resolver/launcher refuse `verified`/Production on it exactly as today. | The current binding already does this and Development Auto (`Resolve-MaviVisionCudaAvailability`) depends on it. |
| P-17 | **One variant model, three roles.** The closed variant universe is `_RUNTIME_VARIANTS` (`qualification.py:546-553`: `windows-x86_64-cpu`, `windows-x86_64-cuda`, `linux-x86_64-cpu`, `linux-x86_64-cuda`). The **runtime profile** says what the family knows and is tracking (its `platformVariants` and `releaseLocks` keys equal the universe, as the v1 loader already enforces, `:587-622`); the **binding** says what the release can select and deploy now; the **qualification record** carries evidence/status across the whole universe. Each variant's class is **derived from the runtime profile and the tracked lock files only** — it is never declared a second time:<br>**A. known, not yet releasable** — `platformVariants[v].status == "pending-hardware-qualification"` **and** `releaseLocks[v].status == "pending-hardware-qualification"` **and** no tracked `<family>/<v>.lock`. Must be **absent** from the binding; the record carries it with `runtimePackId: null`, `status: "pending"` and every gate `pending`; it can never be `passed`, be the `runtimeVariant` of any `profileQualifications` entry (and therefore of any `qualifiedProfiles` id — that list holds deployment-profile ids and must equal the `profileQualifications` keys, `qualification.py:755-756`), satisfy `verified`/Production, or start a role. Today: `linux-x86_64-cuda`.<br>**B. deployable** — a tracked `<family>/<v>.lock` exists **and** `platformVariants[v].status != "pending-hardware-qualification"`. Must be **present** in the binding with a non-null `runtimePackId`; binding, lock file and record ids cross-check; it may proceed subject to environment/qualification rules (P-8, P-13). Today: `windows-x86_64-cpu`, `linux-x86_64-cpu`, `windows-x86_64-cuda`.<br>**C. anything else fails closed** — a variant key outside the universe; a runtime-profile variant matching neither A nor B (lock file present but variant pending, or no lock file but variant not pending: `runtime_variant_classification_invalid:<v>`); a class-B variant omitted from the binding (`binding_variant_missing:<v>` — an omission is never read as "optional"); a class-A variant declared in the binding (`binding_variant_not_releasable:<v>`). No fake Linux-CUDA Runtime Pack entry is introduced. | Removes the contradiction between a four-variant record and a three-variant binding without a second variant model; preserves the Linux-CUDA non-claim exactly as the frozen baseline states it. |
| P-14 | **Source manifest carries no `sizeBytes`.** Built pack manifests and install state carry measured sizes (as `build_model_pack.py` and `test_model_pack_builder.py:97` already do). ADR-014 §3's "byte size" is satisfied at the pack layer. | No source manifest in the repo carries sizes; asserting one by hand would be a fabricated number. |
| P-15 | **Licence:** the licence notice is a Model Pack **artefact with `artifactRole: "licence-notice"` in the v2 source manifest from S2a.3**, so it participates in the v2 `modelPackId` (P-3) from the moment that id is first frozen; the id never changes again in S2a.4. For RTMDet the notice is the Apache-2.0 `LICENSE` file at the mmdetection commit already pinned in `vision-model-pack.yml`; its SHA-256 is recorded in the manifest in S2a.3, the model-pack workflow fetches it beside the checkpoint from S2a.3, and the Task-10 `.qualification-model-root` includes it. Manifest v2 also carries licence metadata (`spdxId`, `noticeArtifactRole`, `reviewStatus`) with `reviewStatus: "pending-review"` (no approval exists; policy `vision-model-runtime-bundles` requires approval before promotion). A `verified` manifest requires `reviewStatus: "approved"`. | Identity frozen once (C7 reconciled exactly once); complete at the pack layer per ADR-014 §11; no promotion implied. |
| P-16 | **Provenance contract enforcement.** A role declares exactly one `provenanceContract` (`vision-job-complete-v3.2`). At startup the resolver requires the worker's effective completion schema version to equal the contract's version, else `role_provenance_contract_mismatch` and the role never becomes READY. The only way to run another version is the explicit, Development-only variable `MAVI_COMPLETION_SCHEMA_OVERRIDE` ∈ {`3.1`, `3.0`}: `3.1` for a platform with asynchronous finalization enabled, `3.0` for a platform held at `VisionFinalization:Enabled=false` (the synchronous set is {2.0, 3.0}, `WorkerContractRules.cs:28-29`; the worker's capability probe still fails closed on a mismatched pair). Either override is rejected when `production_mode` is true (`completion_override_forbidden_in_production`), forces the effective `verificationStatus` to `unverified` (the run is non-qualifying by construction), and is logged as `completion_schema_override_active` at startup and on every completion. The S1.4 setting `MAVI_COMPLETION_SCHEMA_VERSION` is retired in S2a.3 (setting it fails closed, `settings_v1_composition_rejected`); the runbook and `contracts/README.md:19` passages that document it are rewritten in S2a.3, not S2a.4. | The binding can never claim a contract the role does not emit; rollback stays possible but is visible, non-qualifying and impossible in Production. |

---

## 4. Target v2 schemas

Every schema is strict (`extra="forbid"`), versioned by a `Literal` `schemaVersion`, UTF-8, LF, no BOM (covered by `RELEASE_TEXT_ROOTS`).

### 4.1 Component binding v2 — `src/vision/config/components/phase1-bindings-v2.json`

```json
{
  "schemaVersion": "mavi-vision-component-binding-v2",
  "bindingId": "phase1-v2",
  "runtimePacks": [
    {
      "runtimePackFamilyId": "mmdetection-phase1-v1",
      "variants": {
        "windows-x86_64-cpu":  { "runtimePackId": "mavi-runtime-v2-5d6229da…", "thirdPartyLockSha256": "66517c8f…", "runtimeRequirementsSha256": "555ecfd8…", "nativeAbi": "win_amd64-msvc-14.44-sdk-10.0.26100.0" },
        "linux-x86_64-cpu":    { "runtimePackId": "mavi-runtime-v2-bd94fded…", "thirdPartyLockSha256": "b1d0970d…", "runtimeRequirementsSha256": "991d07a5…", "nativeAbi": "glibc-2.39-libstdcxx-GLIBCXX_3.4.33-gcc-14.2.0-linux_x86_64" },
        "windows-x86_64-cuda": { "runtimePackId": "mavi-runtime-v2-89fd8bfc…", "thirdPartyLockSha256": "f95a7970…", "runtimeRequirementsSha256": "aef75d19…", "nativeAbi": "win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75" }
      }
    }
  ],
  "roles": [
    {
      "roleId": "vision",
      "runtimePackFamilyId": "mmdetection-phase1-v1",
      "capabilityIds": ["detector"],
      "entryPoint": "mavi_vision.worker.main",
      "readinessContract": "worker-health-v2",
      "provenanceContract": "vision-job-complete-v3.2"
    }
  ],
  "capabilityBindings": [
    {
      "capabilityId": "detector",
      "roleId": "vision",
      "modelPackId": "mavi-model-v2-<derived>",
      "qualificationId": "rtmdet-m-coco-phase1-v2",
      "enabled": true
    }
  ]
}
```

Validator rules (`mavi_vision/runtime/binding.py`, pure, no I/O beyond the file):
1. `runtimePacks[*].runtimePackFamilyId` unique; each variant key ∈ the closed variant set (the file-local check; the cross-file rule that the family's variant keys equal exactly its class-B set, P-17, is enforced by the resolver and `verify_repo`); each variant entry has all four fields with SHA/ID syntax checks (`runtimePackId` matches `^mavi-runtime-v2-[0-9a-f]{64}$`).
2. `roles[*].roleId` unique; `runtimePackFamilyId` must exist in `runtimePacks`; `capabilityIds` non-empty, unique, each in the registry (P-4); `entryPoint` is a dotted module path; `readinessContract`/`provenanceContract` are known contract ids (closed sets in code).
3. `capabilityBindings` sorted by `capabilityId` (P-5), unique; `roleId` exists; the role's `capabilityIds` contains the `capabilityId`; every role capability has exactly one **enabled** binding (P-6); `modelPackId` matches `^mavi-model-v2-[0-9a-f]{64}$`; `qualificationId` non-empty text.
4. A binding whose `enabled` is false is retained in the file but its role cannot start (`capability_binding_disabled`). No default enabling.
5. Unknown fields anywhere → reject. Unknown `schemaVersion` (including the v1 string) → `component_binding_schema_unsupported`.

**v1 acceptance:** none at runtime after S2a.3. The v1 file is deleted in S2a.3; `verify_repo` fails if any file under `config/components` has a schema other than v2. ADR-014's "compatibility reader as explicit migration aid" is `tools/vision/migrate_component_binding_v1.py`, a one-shot, tested generator that reads the v1 binding + v1 manifest + v1 runtime profile + v1 record and writes the four v2 files; it is used once in S2a.3 and is not a runtime reader.

### 4.2 Model manifest v2 — `models/manifests/rtmdet-m-coco-phase1-v2.json`

```json
{
  "schemaVersion": "2.0",
  "modelId": "rtmdet-m-coco-phase1",
  "modelVersion": "1.0.0",
  "capabilityIds": ["detector"],
  "artifacts": [
    { "artifactRole": "checkpoint",      "relativePath": "rtmdet-m-coco-phase1-v1/rtmdet_m_8xb32-300e_coco_20220719_112220-229f527c.pth", "sha256": "229f527c…" },
    { "artifactRole": "licence-notice",  "relativePath": "rtmdet-m-coco-phase1-v1/LICENSE", "sha256": "<sha256 of mmdetection LICENSE at the pinned commit, recorded in S2a.3>" },
    { "artifactRole": "resolved-config", "relativePath": "rtmdet-m-coco-phase1-v1/rtmdet_m_resolved.py", "sha256": "377d9f57…" }
  ],
  "inputContract":  { "kind": "video-frame-rgb", "colourSpace": "RGB" },
  "outputContract": { "schemaId": "detector-output-v1" },
  "runtimeCompatibility": { "runtimePackFamilyIds": ["mmdetection-phase1-v1"] },
  "licence": { "spdxId": "Apache-2.0", "noticeArtifactRole": "licence-notice", "reviewStatus": "pending-review" },
  "provenance": { "publisher": "OpenMMLab", "sourceUrl": "<checkpoint URL already in vision-model-pack.yml>", "sourceRevision": "<mmdetection commit already pinned in vision-model-pack.yml>" },
  "verificationStatus": "unverified",
  "qualificationId": null,
  "capabilitySpecific": {
    "detector": {
      "backend": "mmdetection",
      "architecture": "rtmdet-m",
      "classVocabulary": [ "...80 COCO classes, unchanged..." ],
      "checkpointArtifactRole": "checkpoint",
      "resolvedConfigArtifactRole": "resolved-config"
    }
  }
}
```

Rules: `artifacts[*].artifactRole` unique, `relativePath` passes the existing logical-path validator and all share one first segment (`packDirectory`, P-10); `licence.noticeArtifactRole` must name an artifact (every Model Pack ships its notice; the resolver re-hashes it like any artefact and fails `model_artifact_hash_mismatch:licence-notice`); `capabilityIds` non-empty, sorted, in registry; `capabilitySpecific` keys ⊆ `capabilityIds`; the `detector` section is **required iff** `"detector" ∈ capabilityIds` and must reference existing artifact roles; `verificationStatus=="verified"` ⇒ `qualificationId` non-null and `licence.reviewStatus=="approved"` (P-15).

`ModelManifest` dataclass becomes capability-neutral; a typed `DetectorModelSection` accessor returns the detector section or raises `capability_section_missing`. `MMDetectionRuntime` reads checkpoint/config through the section, so its behaviour is unchanged.

**Fixture proving neutrality (S2a.1 test):** `src/vision/tests/fixtures/model-manifests/embedding-fixture-v2.json` — `capabilityIds:["embedding"]`, two artifacts (`licence-notice`, `weights`; no config), a `licence` block naming `licence-notice`, `capabilitySpecific.embedding:{dimension:512}`. It must load, derive an id, and be **rejected by the resolver** with `capability_not_implemented`.

### 4.3 Runtime profile v2 — `src/vision/runtime/mmdetection-phase1-v1/runtime.json`

Changes to the existing file (all else byte-identical):
- `schemaVersion: "2.0"`.
- **Removed:** top-level `checkpoint`, top-level `resolvedConfig`, and `platformVariants[*].resolvedConfigSha256` (and the evidence-shape validator's requirement for it, `qualification.py:421-497`). Manifest v2 also drops v1's free-text `purpose` (superseded by `capabilityIds`).
- Unchanged: `runtimeProfileId`, `qualificationStatus`, `pythonMinor`, `semanticGraph`, `platformVariants[*]` other fields (`status`, `workflowRunId`, `jobId`, `evidenceHeadSha`, `pythonIdentity`, `binaryVersions`, `developmentEvidence`), `releaseLocks`.

Loader (`_RuntimeProfileSchemaV2`): identical validators minus the config relationship, plus the P-17 classification of every variant (`runtime_variant_classification_invalid:<v>` for a variant that is neither class A nor class B; the lock-file part of the test is done where the file system is visible — the resolver and `verify_repo` — while the loader checks the status pair). `validate_runtime_relationships` keeps the Python-minor and torch/torchvision binary↔semantic checks. `verify_runtime_release_locks` unchanged. `_RuntimeCheckpointSchema` and `_RuntimeResolvedConfigSchema` are deleted; a v2 profile containing `checkpoint` is rejected.

Consequence: `runtimeProfileSha256` changes from `b3c59ac4…` to a new value; every consumer of it is re-derived in S2a.3 (§9).

Honesty note for the reconciliation record: the Task-10 evidence behind `platformVariants.*.status = qualified-hosted-cpu` was captured through the RTMDet probe. It remains valid as *runtime-graph* evidence (imports, compiled ops, Python identity, lock install); it makes no model claim, and the record says so.

### 4.4 Qualification record v2 — `models/qualifications/rtmdet-m-coco-phase1-v2.json`

```json
{
  "schemaVersion": "2.0",
  "qualificationId": "rtmdet-m-coco-phase1-v2",
  "capabilityId": "detector",
  "modelPackId": "mavi-model-v2-<derived>",
  "modelId": "rtmdet-m-coco-phase1",
  "modelManifestSha256": "<sha256 of the v2 manifest>",
  "artifactSha256": { "checkpoint": "229f527c…", "licence-notice": "<sha256>", "resolved-config": "377d9f57…" },
  "runtimePackFamilyId": "mmdetection-phase1-v1",
  "runtimeProfileSha256": "<sha256 of runtime.json v2>",
  "outputContract": { "schemaId": "detector-output-v1" },
  "policies": { "pipelineProfileId": "phase1-detection-tracking-v1", "pipelineProfileSha256": "503225be…" },
  "protocol": { "corpusId": null, "protocolVersion": null },
  "gateSetIds": ["common-v1", "detector-v1"],
  "variants": {
    "windows-x86_64-cpu":  { "status": "pending", "runtimePackId": "mavi-runtime-v2-5d6229da…", "gates": { "…every gate of both sets…": "pending" } },
    "windows-x86_64-cuda": { "status": "pending", "runtimePackId": "mavi-runtime-v2-89fd8bfc…", "gates": { "…": "pending" } },
    "linux-x86_64-cpu":    { "status": "pending", "runtimePackId": "mavi-runtime-v2-bd94fded…", "gates": { "…": "pending" } },
    "linux-x86_64-cuda":   { "status": "pending", "runtimePackId": null, "gates": { "…": "pending" } }
  },
  "profileQualifications": {},
  "evidence": {},
  "overallResult": "pending",
  "supersedes": { "qualificationId": "rtmdet-m-coco-phase1-v1", "reason": "ADR-014 runtime-profile v2 / manifest v2 identity migration; model bytes unchanged; no gate result carried forward" }
}
```

Rules (variant semantics per P-17):
- `variants` keys equal the closed qualification-variant universe exactly: a missing key fails `qualification_variant_missing:<v>`, an extra key `qualification_variant_unknown:<v>`.
- **Class-B (deployable, declared in the binding):** `runtimePackId` is **required** and must equal `binding.runtimePacks[family].variants[v].runtimePackId`; a `null` there fails `qualification_runtime_pack_required:<v>` (for example a null for `windows-x86_64-cpu` or `linux-x86_64-cpu`).
- **Class-A (in the runtime profile, explicitly `pending-hardware-qualification`, no lock file, therefore absent from the binding):** `runtimePackId` must be `null` (`qualification_runtime_pack_forbidden:<v>` otherwise); `status` must be `"pending"` and every gate `"pending"`; no `profileQualifications` entry — and therefore no `qualifiedProfiles` id — may have `runtimeVariant == v` (`qualification_pending_variant_claims_pass:<v>`). Today this is `linux-x86_64-cuda`.
- A variant that is neither class A nor class B (C) is invalid; a binding omission is **not** interpreted as optional unless the runtime profile and the tracked lock files make the variant class A (P-17).
- The record is evidence and status only: nothing ever reads a Runtime Pack identity *from* it; it is compared, never used as a source.
- Every gate of every named gate set present per variant; existing profile-qualification rules kept verbatim (`profileQualifications`, `deploymentProfilePolicySha256`, `runtimeVariant`, `qualifiedProfiles`); `overallResult=="passed"` requires every gate of the `runtimeVariant` of every profile in `qualifiedProfiles` to be `passed`; `supersedes` optional, informational. `verify_qualification_relationships` compares `{qualificationId, capabilityId, modelPackId, modelId, modelManifestSha256, artifactSha256, runtimePackFamilyId, runtimeProfileSha256, variants.*.runtimePackId, policies.*}` to the live files and the binding. The runtime-profile evidence-shape validator (`qualification.py:421-497`) drops its `resolvedConfigSha256` requirement for qualified variants in the v2 loader.

### 4.5 Provenance and completion schema 3.2

Additions to `$defs/provenance` (new file `contracts/schemas/vision-job-complete-v3.2.schema.json`, copied from 3.1 with these five **required** properties; `contracts/schemas/vision-job-finalization-response-v3.2.schema.json` copied from 3.1 with `schemaVersion` const `"3.2"`):

| Field | Type | Source on the worker |
|---|---|---|
| `capabilityId` | registry id | the role's capability that produced the VisionJob (`detector`) |
| `modelPackId` | `mavi-model-v2-…` | derived from the loaded manifest (P-3), cross-checked against the binding and the installed `model-pack-manifest.json` if present |
| `runtimePackId` | `mavi-runtime-v2-…` or `null` (P-8) | installed `runtime-pack-manifest.json` (`MAVI_RUNTIME_PACK_MANIFEST_PATH`, set by the launcher), cross-checked against `binding.runtimePacks[family].variants[runtimeVariant]` and `releaseLocks[runtimeVariant]` |
| `runtimePackSource` | `"installed-pack" \| "unpacked-environment"` | as above |
| `componentBindingSha256` | sha256 | SHA-256 of the binding file bytes |

Digest (`VisionResultValidator.ComputeDigest`): for `CompletionSchema.V32` the domain tag is `mavi:vision-completion-digest:v3.2` and, immediately after `AddNullable(provenance.PlatformLockSha256)`, the validator appends `Add(CapabilityId)`, `Add(ModelPackId)`, `AddNullable(RuntimePackId)`, `Add(RuntimePackSource)`, `Add(ComponentBindingSha256)`. Everything else is byte-identical to v3. New golden vector `contracts/test-vectors/vision-job-complete-v3.2-digest.json` plus example `contracts/examples/vision-job-complete-v3.2.example.json`; the v3 vector is retained and still asserted.

Validation: for 3.0/3.1 bodies the five fields must be absent (`provenance_v32_field_in_v3_body`); for 3.2, `capabilityId`, `modelPackId`, `runtimePackSource` and `componentBindingSha256` are **required** and `runtimePackId` is **optional** in the schema (absent and `null` are equivalent, exactly like `qualificationId`/`platformLockSha256` in 3.1), with the validator enforcing the pairing: `RuntimePackSource=="installed-pack"` ⇒ `RuntimePackId` present; `RuntimePackSource=="unpacked-environment"` ⇒ `RuntimePackId` absent/null **and** `VerificationStatus=="unverified"` (`provenance_runtime_pack_required`). The `.NET` contract record gains five nullable properties with `JsonIgnore(WhenWritingNull)`, so 3.1 serialisation stays byte-identical and a null `runtimePackId` re-serialises as absent without violating the 3.2 schema. Golden vectors: one 3.2 body with an installed pack, one with `unpacked-environment`.

Platform plumbing S2a.2 must change (3.2 is an **asynchronous-only** exchange, like 3.1): `WorkerContractRules.AsynchronousCompletionSchemaVersions`, `IsAcceptedCompletionSchemaVersion`, `IsKnownCompletionSchemaVersion`, `IsAsynchronousCompletionSchemaVersion` (`WorkerContractRules.cs:28-53`); `VisionResultValidator.CompletionSchema` gains `V32` and every `schema == CompletionSchema.V3` branch (`:131,227,591`) is audited to cover `V32`; `VisionFinalizationPayloadCodec.Encode/Decode` (`:35,78` hard-reject anything but 3.1 today) accept 3.1 and 3.2 and keep the version inside the codec document; the response factories (`VisionJobCompleteContracts.cs:197,202`) and the worker acknowledgement check (`worker/client.py:294`, `control_plane.py:1030`) accept `"3.2"`. The `VisionFinalizationPayload` entity has no schema column and gains none: the persisted version lives in the codec document, and the executor decodes before validating (`VisionFinalizationExecutor.cs:241,254`), so the digest domain is selected from the persisted version once the codec is widened.

Persistence: `runtime_provenance_json` (jsonb) needs no migration. `ProcessingRunAttestationResponse` gains the five fields (nullable, absent for historical rows). No new columns.

**Replay rule (S2a.2 must prove):** the persisted finalization payload carries the completion `schemaVersion`; replay selects the digest domain from that persisted version, never from the platform's current default. S2a.2 adds a test that stores one 3.1 payload and one 3.2 payload and replays both to their stored digests, and a negative test that a 3.2 payload replayed under the v3 domain does not match.

---

## 5. Worker composition (S2a.3)

### 5.1 New modules

- `mavi_vision/runtime/capabilities.py` — registry (P-4), `CapabilityId` newtype, `IMPLEMENTED_CAPABILITIES = {"detector"}`.
- `mavi_vision/runtime/binding.py` — `ComponentBinding` dataclasses + strict pydantic loader + `load_component_binding(path) -> (ComponentBinding, sha256)`.
- `mavi_vision/runtime/model_pack_identity.py` — v2 derivation (P-3); `component_identity.py` keeps `runtime_pack_id` and **deletes** `model_pack_id` v1. Every consumer of the v1 derivation or of a v1 artefact is migrated **in S2a.3** so `main` stays green (§5.5).
- `mavi_vision/runtime/resolver.py` —
  ```
  resolve_role(*, binding, role_id, runtime_variant, overlay_root, model_root,
               runtime_pack_manifest_path | None, production_mode, deployment_profile…) -> ResolvedRole
  ResolvedRole(role, family_profile: RuntimeProfileV2, runtime_profile_sha256, runtime_pack: ResolvedRuntimePack,
               capabilities: {capability_id: ResolvedCapability})
  ResolvedCapability(binding, manifest, manifest_sha256, model_pack_id, artifact_paths: {role: Path},
                     qualification, qualification_sha256, verification_status)
  ```
  Order of checks, each fail-closed with a stable code: role exists → family profile loads → locks verified → P-17 classification of every family variant (`runtime_variant_classification_invalid:<v>`, `binding_variant_missing:<v>`, `binding_variant_not_releasable:<v>`) → the observed variant has a binding entry, else `runtime_variant_not_declared:<variant>` (today `linux-x86_64-cuda` always ends here; the resolver never consults the qualification record to find a Runtime Pack) → `thirdPartyLockSha256 == sha256(<family>/<variant>.lock)` (the lock **file**, so a `pending-hardware-qualification` variant such as `windows-x86_64-cuda`, whose `releaseLocks` entry has no `sha256`, still cross-checks; a `verified`/Production claim additionally requires `releaseLocks[variant].status == qualified-offline-lock`, exactly as `provenance.py:425-439` does today) → installed runtime pack (if any): `runtimePackId` is **re-derived** from the installed manifest's material inputs through `component_identity.runtime_pack_id` and must equal both the manifest's id field and the binding entry; `platformVariant` must equal the observed variant; its `thirdPartyLockSha256` must equal the binding entry → for each capability of the role: binding enabled → capability implemented → manifest found uniquely by derived id → `runtimeCompatibility` contains the family → artefacts re-hashed → qualification record found by id and relationships verified (including `variants[runtime_variant].runtimePackId == binding entry`) → environment policy (`verify_release_selection`'s existing verified/unverified/production rules, per capability; a verified manifest without an installed pack in Development downgrades to `unverified` exactly as `provenance.py:452-468` does today; in `production_mode` it fails `runtime_pack_required`) → offline/dependency policy check (the existing `platform_lock_sha256` requirement, ADR-014 §9).
  Sequencing with device resolution: today the variant derives from the *actual* device (`provenance.py:336-354`), so the launcher/`main.py` resolve the device policy first (unchanged) and call `resolve_role` with the observed variant; `resolve_role` never chooses a device.
- `verify_release_selection` is **deleted**; its body becomes `_verify_capability(...)` inside the resolver with the same error codes where they still apply (tests updated by code, not by loosening).

### 5.2 Changed modules

- `common/settings.py`: add `component_binding_path` (default `src/vision/config/components/phase1-bindings-v2.json`), `role_id: Literal["vision"] = "vision"`, `runtime_pack_manifest_path: Path | None`; remove `model_manifest_path`, `qualification_record_path`, `runtime_profile_path` (derived from the family: `src/vision/runtime/<family>/runtime.json`); keep `pipeline_profile_path`. Replace `completion_schema_version` with `completion_schema_override: Literal["3.0","3.1"] | None = None` (P-16); the effective version is the role's `provenanceContract` version unless the override is set. `MAVI_COMPLETION_SCHEMA_VERSION` is retired and rejected.
- `runtime/supervisor.py`: takes `ResolvedRole`; builds `MMDetectionRuntime` from `resolved.capabilities["detector"]`; provenance via `build_runtime_provenance(resolved_capability=…, resolved_runtime_pack=…, binding_sha256=…)`.
- `runtime/provenance.py`: `RuntimeProvenance` gains `capability_id`, `model_pack_id`, `runtime_pack_id | None`, `runtime_pack_source`, `component_binding_sha256`; `_runtime_binding_mismatch` drops the `resolved_config_sha256` comparison (the config identity is now in the capability, not the variant) and adds the installed-pack comparison. The host-derived `_runtime_variant_key` stays as the *observed* variant; when an installed pack is present its `platformVariant` must equal the observed variant (`runtime_pack_variant_mismatch`).
- `worker/client.py` `_map_provenance`; `common/control_plane.py` `VisionRuntimeProvenance` (+5 fields, validated).
- `runtime/mmdetection.py`: reads artefacts through the detector section; `RuntimeMetadata` unchanged.
- `worker/main.py`: constructs the resolver from settings.

### 5.3 Harness and tooling changes forced by §5.2 (listed so the closure diff is explicit)

Three kinds of forced change. None changes measured semantics; the two `s1_memory.py` edits are behavior-bearing under `s1_evidence.py` and are stated in the PR body:
- **Composition paths** (manifest/record path → binding path + role): `tools/vision/trace_inference_window.py:542-545`, `tools/vision/{build_offline_bundle,build_failure_matrix_evidence,build_development_e2e_evidence}.py`, `tools/phase1/{qualify_offline_variant,run_production_scenario,qualify_failure_reprocess}.py`, `tests/Mavi.IntegrationTests/Qualification/S1QualificationSupport.cs` (worker env), `.github/workflows/task10-runtime-qualification.yml:615-640`. The pipeline-profile path constants (`fixture_worker_harness.py:57`, `measure_evidence_parameters.py:47`, `s1_memory.py:81`) are **not** changed (P-9 keeps `MAVI_PIPELINE_PROFILE_PATH`).
- **Retired completion setting** (P-16): `tests/Mavi.IntegrationTests/Qualification/S1FinalizationRecoveryTests.cs:298` (sets `MAVI_COMPLETION_SCHEMA_VERSION=3.1` → becomes the override or is dropped), `tools/qualification/s1_memory.py:573` (`WorkerSettings(completion_schema_version="3.1")`, behavior-bearing, stated in the PR body), `src/vision/tests/test_worker_completion_v3.py:66`, `docs/runbooks/vision-runtime-model-component-lifecycle.md:88-188` and `contracts/README.md:19`. `tools/qualification/tests/test_s1_evidence.py:187-195` asserts the checker's `worker_completion_default` (regex over `completion_schema_version: Literal[...] = "…"`, `s1_evidence.py:481-483`) against the **live** `settings.py`; it changes its fixture source to a pinned copy of the pre-S2a `settings.py` — a test-fixture change, not a checker rule change (the checker reads `settings.py` at the *measured* SHA, which for any S1 identity is pre-S2a). This is one more concrete reason the note's "then-current invalidation rules" apply to any post-S2a S1 closure.
- **`RuntimeProvenance` constructors** gain the five new fields (no defaults — a default would be a fabricated identity): `tools/qualification/s1_memory.py:598-610` (constructor arguments only; the checker rules and `runtimeVariant` logic are untouched, but this edit is behavior-bearing under `s1_evidence.py` and is stated in the PR body) and `tools/vision/dev/fixture_worker_harness.py:119`.

### 5.5 Every v1 consumer migrated in S2a.3 (so `main` never goes red)

`tools/vision/build_model_pack.py` (imports v1 `model_pack_id`; reads v1 `checkpoint`/`resolvedConfig`), `tools/vision/sync_offline_vision_components.py` (v1 binding schema, `:225-234`), `tools/vision/verify_offline_component_ownership.py` (single-pack, `:66-86`), `tools/vision/build_offline_bundle.py`, `tools/setup/Mavi.Setup.Common.psm1` and `Sync-MaviOfflineVisionComponentStore.ps1:31` (v1 binding path), `Mavi.VisionRuntime.Common.psm1` `Resolve-MaviVisionCudaAvailability:369-494` (reads v1 `runtimePacks["windows-x86_64-cuda"]`), `Install-MaviVisionModelPack.ps1` (v1 pack schema, `:70-76`), `Test-MaviVisionModelPackStateContracts.ps1`, `src/vision/tests/{test_offline_component_ownership,test_model_pack_builder,test_offline_vision_component_store,test_runtime_projection_repository_contract,test_windows_cuda_host_runbook}.py`. The Python tools therefore move to v2 in S2a.3, as does `Install-MaviVisionModelPack.ps1` v2 (§5.4); N-pack kit assembly, the Setup-MAVI repair and the lifecycle runbook's kit sections remain S2a.4.

### 5.4 PowerShell (S2a.3: launcher **and** the minimum v2 Model Pack installer; S2a.4: kit assembly, Setup repair, runbooks)

Installability rule: after S2a.3 merges, a Windows Development host must be able to reach READY using only repository tooling at that head. S2a.3 therefore ships `Install-MaviVisionModelPack.ps1` v2 (reads a `mavi-vision-model-pack-v2` pack, verifies every artefact SHA, stages `<store>/<packDirectory>/` — artefacts by `relativePath`, `model-pack-manifest.json`, `model-install.json` v2 — and swaps it per pack, rejects v1 state) together with the launcher. `Install-MaviVisionRuntime.ps1` is unchanged in S2a.3 (Runtime Packs and their ids are unchanged). The reinstall instruction in §11 refers to this S2a.3 installer.

- `Start-MaviVisionWorker.ps1`: read binding v2; role `vision`; family → `runtime.json` v2; variant entry → existing runtime-pack checks (unchanged assertions, new source); for each capability binding: scan `<store>\*\model-pack-manifest.json` for exactly one manifest whose `modelPackId` equals the binding's (the launcher runs before the Python resolver and never re-derives P-3); none → the existing `launch_model_pack_not_installed` (`Start-MaviVisionWorker.ps1:132`, kept); more than one → new `launch_model_pack_ambiguous`; the match fixes `packDirectory`; a v1 `model-install.json` there raises the existing `launch_model_state_schema_unsupported` (`:137`); `Assert-MaviVisionWorkerComponentCompatibility` becomes `-RequiredModelPacks @(…)` (array) and compares `modelPackId` + every artefact SHA. Sets `MAVI_COMPONENT_BINDING_PATH`, `MAVI_ROLE_ID`, `MAVI_RUNTIME_PACK_MANIFEST_PATH`, `MAVI_MODEL_ROOT`; no longer sets the removed variables.
- `Install-MaviVisionModelPack.ps1` v2 and `Mavi.VisionRuntime.Common.psm1` (both S2a.3): `Assert-MaviVisionModelPackManifest` v2 (artifacts list, `capabilityIds`); `New-MaviVisionModelInstallState` v2 (`mavi-vision-model-install-v2`: `modelPackId, modelId, capabilityIds, artifactSha256{}, modelPackManifestSha256, installedAtUtc, installRoot`); `Test-MaviVisionModelPackReuse` v2; v1 state → reject (`model_install_state_v1_rejected`).
- `Test-MaviVisionWorkerComponentContracts.ps1`, `Test-MaviVisionModelPackStateContracts.ps1`, `Test-MaviEnvironment.ps1`: updated in the same PR; the string-fragment pins move to v2 identifiers.

---

## 6. `verify_repo` (S2a.3)

Add to `REQUIRED_PATHS`: the binding file. Add `COMPONENT_BINDING_ROOT = src/vision/config/components` to `RELEASE_TEXT_ROOTS`. `check_vision_release_metadata` becomes:

1. Load every `models/manifests/*.json` as v2; index by derived `modelPackId` (duplicate id → fail) and by `modelId`.
2. Load every runtime profile as v2; index by `runtimeProfileId`; locks verified and tracked (unchanged).
3. Load every qualification record as v2; index by `qualificationId`.
4. Load every binding under `config/components` (exactly one expected in S2a; more than one → fail `binding_multiple_not_supported` until a release-profile overlay exists).
5. Cross-checks, each a `fail(...)`:
   - every family in the binding is a known runtime profile; every runtime-profile variant classifies as A or B (P-17) using the tracked lock files; the binding's variant keys for the family equal exactly its class-B set; for every declared variant, `thirdPartyLockSha256 == sha256(<family>/<variant>.lock)` (pending lock status allowed per P-13);
   - every record's `variants` keys equal the universe; each class-B variant has a non-null `runtimePackId` equal to the binding entry; each class-A variant has `runtimePackId: null`, `status: pending`, every gate `pending`, and is the `runtimeVariant` of no `profileQualifications` entry; rejects in particular a null id for `windows-x86_64-cpu`, a null id for `linux-x86_64-cpu`, a null id for any binding-declared variant, a missing record entry, an unknown variant, and a class-A variant marked `passed` or `verified`;
   - every capability binding's `modelPackId` derives from exactly one manifest, whose `capabilityIds` contains the binding's `capabilityId` and whose `runtimeCompatibility` contains the role's family;
   - every capability binding's `qualificationId` names a record whose identity fields match (§4.4);
   - the pipeline profile's `modelId` matches the manifest bound to `detector` (unchanged rule, new lookup);
   - unknown capability id anywhere → fail;
   - any v1-schema file under `models/**`, `src/vision/runtime/**` or `src/vision/config/components/**` → fail;
   - the offline binary catalog's `visionRuntime.runtimeProfileId` and `semanticGraph` still reconcile with `runtime.json` v2 (unchanged check);
   - `docs/qualification/task18-readiness-v1.json` is **not** validated (historical snapshot); S2a.3 adds a one-line note in it that identities are as of Task-18 and superseded by the binding file.
6. **Retained verbatim** (anti-promotion rules that exist today and now get negative fixtures): an `unverified` manifest must not claim a `qualificationId` (`verify_repo.py:1423-1427`); a `verified` manifest requires a `qualified` runtime profile (`:1429-1435`); a record bound to an `unverified` manifest must stay `pending` (`:1516-1521`).

Negative fixtures for each `fail` in `src/vision/tests/test_verify_repo_vision_metadata.py` (new, beside the existing `test_verify_repo_release_hazards.py`; `quality-gate.yml` runs pytest in `src/vision`, `tools/phase1/tests` and `tools/qualification/tests` only).

---

## 7. Offline packaging and installers (Python pack tools and the minimum Model Pack installer in S2a.3 per §5.4–§5.5; kit assembly, Setup repair and runbooks in S2a.4)

- `build_model_pack.py` → v2 (S2a.3): `--source-manifest` v2; copies every `artifacts[*]`, the licence notice included (P-15); emits `model-pack-manifest.json` `mavi-vision-model-pack-v2` `{modelPackId, modelId, modelVersion, capabilityIds, assembledFromCommit, artifacts:[{relativePath,sizeBytes,sha256,artifactRole}]}`; id from P-3; `sizeBytes` measured (P-14).
- `sync_offline_vision_components.py` → repeatable `--runtime-pack` and `--model-pack`; any declared variant; inventory v2 `{schemaVersion, runtimePacks:[{runtimePackId, platformVariant, relativePath, materialIdentity}], modelPacks:[{modelPackId, relativePath, materialIdentity}], applicationOverlay:{revision, componentBinding, componentBindingSha256}}`; **completeness:** every `runtimePackId` and `modelPackId` reachable from the binding for the requested variants must be present or the sync fails (`kit_incomplete:<id>`); an id present in the kit but not in the binding fails (`kit_unbound_component:<id>`).
- `verify_offline_component_ownership.py` → N packs; no artefact hash shared between any two packs; overlay keys `{revision, componentBinding, componentBindingSha256}`.
- `Sync-MaviOfflineVisionComponentStore.ps1` (N packs), `Install-MaviVisionRuntime.ps1` (unchanged), `Setup-MAVI.ps1` (**D-1 repair**: today a legacy `bundle-manifest.json` makes Setup call the installer, which throws at `Install-MaviVisionRuntime.ps1:15`, and a missing one yields INFO; the repair probes `runtime-pack-manifest.json` under the existing `MAVI_VISION_BUNDLE_ROOT` / `..\MAVI-Vision-Runtime-Bundle` root **and** the kit store `vision\runtime\<runtimePackId>` / `vision\models\<modelPackId>` from `component-inventory.json`, installs every bound Model Pack, then runs the launcher's compatibility assertion so a runtime-without-model install is reported as a failure, not INFO).
- **Discriminating PowerShell contract tests (in `tools/setup/Test-*.ps1`, run by Task 17):**
  1. **S2a.4 (D-1):** a kit whose runtime directory contains `bundle-manifest.json` but no `runtime-pack-manifest.json` → Setup reports the runtime as **not installable** (not INFO "bundle not present");
  2. **S2a.3:** runtime installed, bound Model Pack absent from the store → launcher fails with `launch_model_pack_not_installed`, never READY; two packs with the same `modelPackId` → `launch_model_pack_ambiguous`;
  3. **S2a.3:** stale v1 `model-install.json` present → installer rejects with `model_install_state_v1_rejected`; launcher rejects with `launch_model_state_schema_unsupported`; re-install required;
  4. **S2a.3:** installed runtime/model set does not match the binding (installed `runtimePackId` ≠ binding entry; installed pack's artefact SHA ≠ manifest; `model-install.json` identity ≠ pack manifest) → `launch_component_compatibility_failed`.
  5. **S2a.4:** kit inventory's `componentBindingSha256` differs from the repository binding → Setup refuses the kit (`kit_binding_mismatch`).
- `config/dependencies/offline-dependency-policy-v1.json` policy `vision-model-runtime-bundles`: `stagingPath` gains `src/vision/config/components`; no new dependency is introduced (nothing to add to the binary catalog).
- Runbooks `docs/runbooks/vision-runtime-model-component-lifecycle.md` (N packs, binding file) and `mavi-offline-setup.md` (D-1) updated.

---

## 8. CI (S2a.3 unless noted)

| Workflow | Change |
|---|---|
| `vision-runtime-component-boundary.yml` | Reads binding v2: for each matrix variant, `binding.runtimePacks[family].variants[variant] == recomputed`; asserts `schemaVersion == mavi-vision-component-binding-v2`. The matrix stays the three class-B variants; `test_runtime_projection_repository_contract.py` (already pinning matrix == binding variants, `:133-158`) additionally asserts binding variants == the P-17 class-B set. |
| `vision-model-pack.yml` | S2a.3: fetches the `LICENSE` from the already-pinned mmdetection checkout beside the checkpoint, builds the v2 pack with `build_model_pack.py` v2, compares the derived `modelPackId` and every artefact SHA (licence notice included) to `binding.capabilityBindings[detector]`, uploads the pack named by the v2 id. Trigger paths updated. S2a.4 makes no identity-affecting change. |
| `task12-offline-bundle.yml` | **New step (S2a.3):** built `runtimePackId` must equal `binding.runtimePacks[family].variants[variant].runtimePackId` (closes the gap: today it is never compared). |
| `task10-runtime-qualification.yml` | Production smoke uses the resolver (binding + role); the `.qualification-model-root` gains the `LICENSE` artefact; evidence set gains a copy of the binding and its SHA; the semantic-graph step reads `runtime.json` v2 (no change to the check). Run once on the S2a.3 head (cut-over gate) and once on the S2a.5 head (implementation-roadmap rule 3: completion payload change). |
| `quality-gate.yml` | No structural change; new tests run under existing steps. `verify_repo` covers the binding. |
| `task17-acceptance.yml` | Path/env updates only (§5.3). |

---

## 9. Detector qualification reconciliation (S2a.3 artefacts, S2a.5 record)

Identities that change and where each is re-derived:

| Identity | Old | New | Re-derived in |
|---|---|---|---|
| Runtime profile SHA | `b3c59ac4…` | sha256(runtime.json v2) | qualification record v2; provenance of every new run; Task-10 evidence |
| Model manifest SHA | `0049875d…` | sha256(manifest v2) | qualification record v2 |
| `modelPackId` | `mavi-model-v1-2abf6780…` | `mavi-model-v2-…` (P-3; artefact set = checkpoint + licence-notice + resolved-config, frozen once in S2a.3 and unchanged by S2a.4) | binding; kit inventory; model-pack workflow; `task18-readiness` note |
| `qualificationId` | `rtmdet-m-coco-phase1-v1` | `rtmdet-m-coco-phase1-v2` | binding; record v2 (`supersedes` v1) |
| `runtimePackId` (×3) | unchanged | unchanged | — (locks are byte-identical; the boundary workflow proves it) |
| Pipeline profile SHA | `503225be…` | unchanged | — |
| Checkpoint / config SHA | unchanged | unchanged | — |

Rules: the v1 record and v1 manifest files are **deleted** in S2a.3 (no two systems); their content and hashes are quoted in `docs/qualification/stage2-s2a/2026-09-xx-detector-identity-reconciliation.md` together with the new hashes and the statement "no gate result carried forward; RTMDet remains pending on every variant; the manifest remains unverified". `verify_repo` refuses a v1 file under `models/**` or `src/vision/runtime/**`.

**Behaviour regression (C7 proof):**
1. **Record/replay compare (Linux CPU, cheap, discriminating):** the producer is `tools/vision/dev/measure_evidence_real_clips.py` (the B1 mechanism); run it at `c176b048` and at the S2a.3 head on the same real clips. `tools/qualification/s1_b1.py compare` (which strips provenance and host timing, `:53-56`) must report zero detection/track/evidence-byte differences. A **new small test**, `tools/qualification/tests/test_s2a_provenance_diff.py`, diffs the two runs' provenance and asserts the differing keys are exactly `{capabilityId, modelPackId, runtimePackId, runtimePackSource, componentBindingSha256, runtimeProfileSha256, modelManifestSha256, qualificationId, qualificationSha256, maviCommit, maviBuild, schemaVersion}` — nothing else — so a change to tracker parameters, dependency versions or evidence bytes fails. (This one test is the only qualification-tooling addition in S2a.)
2. **Digest replay:** stored 3.1 payload replays to its stored digest after S2a.2/S2a.3.
3. **Task-10** on the S2a.3 head: ByteTrack qualification, production composition, production smoke all `passed`, `headSha` bound.
4. Existing `src/vision/tests` suites (100 `test_*.py` files) and `.NET` suites green at exact head.

---

## 10. Failure behaviour (complete list of new fail-closed codes)

Variant classification (resolver + `verify_repo`, P-17): `runtime_variant_classification_invalid:<v>`, `binding_variant_missing:<v>`, `binding_variant_not_releasable:<v>`, `qualification_variant_missing:<v>`, `qualification_variant_unknown:<v>`, `qualification_runtime_pack_required:<v>`, `qualification_runtime_pack_forbidden:<v>`, `qualification_pending_variant_claims_pass:<v>`.
Resolver/launcher: `role_provenance_contract_mismatch`, `completion_override_forbidden_in_production`, `component_binding_schema_unsupported`, `component_binding_invalid:<field>`, `capability_bindings_unordered`, `capability_binding_duplicate`, `capability_unknown:<id>`, `capability_not_implemented:<id>`, `capability_binding_missing:<role>:<id>`, `capability_binding_disabled`, `role_unknown:<id>`, `runtime_family_unknown:<id>`, `runtime_variant_not_declared:<variant>`, `runtime_lock_binding_mismatch:<variant>`, `runtime_pack_manifest_mismatch:<id|variant|lock>`, `runtime_pack_variant_mismatch`, `runtime_pack_required` (production/verified without an installed pack), `model_manifest_ambiguous:<id>`, `model_manifest_missing:<id>`, `model_pack_id_mismatch`, `model_runtime_incompatible`, `model_artifact_hash_mismatch:<role>`, `qualification_record_missing:<id>`, `qualification_identity_mismatch` (existing), `settings_v1_composition_rejected`; worker, S2a.2 only: `completion_32_requires_binding`.
Platform: `provenance_capability_invalid`, `provenance_model_pack_invalid`, `provenance_runtime_pack_invalid`, `provenance_runtime_pack_required`, `provenance_runtime_pack_source_invalid`, `provenance_component_binding_invalid`, `provenance_v32_field_in_v3_body`.
Installer/launcher (S2a.3): `model_install_state_v1_rejected` (installer, on a v1 `model-install.json`), `launch_model_state_schema_unsupported` (launcher, existing `Start-MaviVisionWorker.ps1:137`, now the v1-state rejection at launch), `launch_model_pack_not_installed` (existing `:132`, kept), `launch_model_pack_ambiguous` (new), `launch_component_pack_requirement_missing` (existing `:159`, binding lacks an entry), `launch_component_compatibility_failed` (existing). Kit (S2a.4): `kit_incomplete:<id>`, `kit_unbound_component:<id>`, `kit_binding_mismatch`.
verify_repo/CI: as listed in §6 and §8.

Every code has a test that triggers it and one mutation that would silence it (§12).

---

## 11. Rollback / forward-only

- **Forward-only:** artefact migration (S2a.3). After S2a.3, Windows Development hosts re-install the Model Pack with the S2a.3 `Install-MaviVisionModelPack.ps1` v2 (shipped in the same PR). Rolling back is `git revert` of the PR plus re-install with the v1 installer (v2 install state is rejected by v1 code and vice versa). Documented in the PR body.
- **Reversible only by the explicit Development override:** `MAVI_COMPLETION_SCHEMA_OVERRIDE=3.1` (asynchronous platform) or `=3.0` (platform held at `VisionFinalization:Enabled=false`) per P-16, while the platform accepts them (S2a.2 onward). Either is refused in `production_mode`, forces `verificationStatus: unverified`, is logged, and drops the C5 fields from new completions (they are 3.2-only). Normal READY always satisfies the role's declared `provenanceContract`; there is no silent rollback. 3.0/3.1 removal from the platform is not part of S2a.
- **Deliberate tightening (not rollback-relevant):** at `c176b048` a Development worker whose observed variant is `linux-x86_64-cuda` runs as `unverified`: the RTMDet manifest is `unverified` (`models/manifests/rtmdet-m-coco-phase1-v1.json`), so `_effective_verification_status` returns `unverified` at `provenance.py:453-455` without any variant check; with a verified manifest the Development downgrade would instead come from `_runtime_binding_mismatch` (`:365-366`, `runtime.json` is `partial`, or `:392`) via `:458-468`. From S2a.3 it fails closed with `runtime_variant_not_declared:linux-x86_64-cuda`. No supported setup reaches that state (Linux installs are the CPU lock; there is no Linux CUDA lock), so this changes no supported path; the PR body states it.
- **Database:** no migration; nothing to roll back.

---

## 12. Test strategy and mutation matrix

### 12.1 Unit/contract tests (S2a.1–S2a.4)

| Requirement | Test | Mutation that must be caught |
|---|---|---|
| missing capability binding fails | `test_binding.py::test_role_capability_without_binding` | drop the "every role capability has a binding" loop |
| duplicate binding fails | `::test_duplicate_capability_binding` | replace set with list |
| unordered bindings fail | `::test_unordered_bindings` | remove the order check |
| unsupported platform variant fails | `::test_unknown_variant_key` | widen `_RUNTIME_VARIANTS` |
| runtime family references nonexistent role / role references nonexistent family | `::test_role_family_unknown` | drop the lookup |
| capability references wrong Model Pack | `test_resolver.py::test_binding_model_pack_id_not_derivable` | compare by `modelId` instead of derived id |
| detector behaviour unchanged | §9 record/replay allow-list test; `test_mmdetection_runtime.py` unchanged assertions | change a tracker parameter in the profile → compare fails |
| Model Pack not coupled back into Runtime Pack | `test_runtime_profile.py::test_v2_rejects_checkpoint` and `test_binding.py::test_family_variant_has_no_model_fields` | allow extra fields |
| future non-detector capability representable | `test_model_manifest.py::test_embedding_fixture_loads_without_detector_fields`; `test_resolver.py::test_embedding_not_implemented` | make detector section mandatory |
| offline bundle rejects incomplete/mismatched set | `test_offline_vision_component_store.py::test_missing_bound_model_pack`, `::test_unbound_pack_rejected`, `test_offline_component_ownership.py::test_cross_pack_duplicate_n_packs` | skip completeness loop |
| provenance records exact resolved ids | `test_runtime_provenance.py::test_pack_ids_from_resolver`; `test_worker_main.py` end-to-end map | hard-code a constant |
| binding cannot claim a contract the role does not emit | `test_resolver.py::test_provenance_contract_mismatch_blocks_ready`; `::test_override_forces_unverified_and_logs`; `::test_override_rejected_in_production`; `test_worker_settings.py::test_legacy_completion_version_rejected` | skip the contract comparison; let the override keep `verified` |
| runtimePackId never fabricated | `test_runtime_provenance.py::test_no_installed_pack_yields_null_and_unpacked_source`; `::test_verified_requires_pack`; `::test_installed_pack_variant_mismatch` | default to the binding's id when no pack is installed |
| digest changes when binding identity changes | `CompletionDigestGoldenTests` v3.2 vector + `VisionResultValidatorTests::DigestChangesWithComponentBindingSha` (flip one hex char) | drop `Add(ComponentBindingSha256)` |
| replay uses persisted schema version | `VisionFinalizationReplayTests::Stored31And32PayloadsReplayUnderTheirOwnDomain`; negative cross-domain test | select domain from the platform default |
| P-17 legitimate class-A case | `test_variant_classification.py::test_linux_cuda_pending_absent_from_binding_null_id_is_valid` (runtime profile `linux-x86_64-cuda` = `pending-hardware-qualification` with no lock file; binding omits it; record `runtimePackId: null`, `status: pending`) → **valid** | treat any null as illegal |
| null id for a binding-declared variant | `::test_null_runtime_pack_for_windows_cpu_rejected`, `::test_null_runtime_pack_for_linux_cpu_rejected`, `::test_null_runtime_pack_for_windows_cuda_rejected` → `qualification_runtime_pack_required` | accept null whenever the lock is pending |
| unknown / unclassifiable variant | `::test_record_variant_outside_universe_rejected` (`linux-arm64-cuda`, null id) → `qualification_variant_unknown`; `::test_runtime_profile_missing_variant_rejected` → `runtime_platform_variants_incomplete`; `::test_record_missing_variant_rejected` → `qualification_variant_missing` | drop the key-set equality |
| class-A variant claims a pass | `::test_pending_variant_status_passed_rejected`, `::test_pending_variant_gate_passed_rejected`, `::test_profile_qualification_on_pending_variant_rejected` (a `P2` entry with `runtimeVariant: linux-x86_64-cuda`, listed in `qualifiedProfiles`) → `qualification_pending_variant_claims_pass` | skip the class-A status/gate check |
| omission is not "optional" | `::test_binding_omits_deployable_variant_rejected` (drop `linux-x86_64-cpu` from the binding) → `binding_variant_missing`; `::test_binding_declares_pending_variant_rejected` (add a `linux-x86_64-cuda` entry) → `binding_variant_not_releasable` | accept any subset of the universe |
| class-A variant given a Runtime Pack id | `::test_class_a_non_null_runtime_pack_rejected` (`linux-x86_64-cuda` given a well-formed `mavi-runtime-v2-…` id in the record) → `qualification_runtime_pack_forbidden` | skip the class-A null check |
| **mutation: drop the `platformVariants` pending requirement from class A** | `::test_non_pending_variant_without_lock_rejected` — a **loader-valid** fixture: `linux-x86_64-cuda` set to `qualified-development-hardware` with valid `developmentEvidence`, `pythonIdentity` and `binaryVersions` (so `qualification.py:596-601` and the evidence-shape validator accept it), `releaseLocks` still `pending-hardware-qualification`, no lock file, binding omits it, record null; run through `verify_repo` and the resolver (where the lock file is visible) → must fail `runtime_variant_classification_invalid` | classify as A without the variant-status test → the fixture is accepted as class A and the test fails |
| **mutation: drop the `releaseLocks` pending requirement from class A** | `::test_pending_variant_with_wheelhouse_lock_status_rejected` — `linux-x86_64-cuda` `platformVariants` pending, `releaseLocks` `pending-wheelhouse-freeze` (a legal status, `qualification.py:501-505`), no lock file, binding omits it, record null → must fail `runtime_variant_classification_invalid` | classify as A without the release-lock-status test → accepted as class A and caught |
| resolver never starts a class-A variant | `test_resolver.py::test_linux_cuda_observed_variant_fails_closed` → `runtime_variant_not_declared:linux-x86_64-cuda`, role never READY; `::test_resolver_does_not_read_runtime_pack_from_record` (record given a well-formed id for a class-A variant in a fixture that bypasses `verify_repo` → resolver still fails at the binding) | fall back to the record's id |
| qualification record cannot claim wrong tuple | `test_qualification_record.py::test_v2_identity_mismatch_{capability,model_pack,runtime_sha,manifest_sha}` | remove a key from `expected` |
| stale v1/v2 mixed configuration fails | `test_verify_repo_vision_metadata.py::test_v1_manifest_rejected`, `test_worker_settings.py::test_v1_env_paths_rejected`, PowerShell v1 install-state test | accept `schemaVersion in {"1.0","2.0"}` |
| 3.1 body with 3.2 fields rejected; 3.2 body without them rejected | `VisionResultValidatorTests` ×2; `test_contract_schema_canonicalization.py` schema conformance | make fields optional |
| installer/launcher fail closed (S2a.3) | §7 tests 2–4 | accept v1 state; take the first of two matching packs; skip the pack-set comparison |
| Windows setup defect and kit binding (S2a.4) | §7 tests 1 and 5 | restore the `bundle-manifest.json` probe; skip the inventory SHA check |
| S2a.2 cannot select 3.2 without a binding | `test_worker_settings.py::test_completion_32_requires_binding` | drop the validator |

### 12.2 Mutation procedure

Same as PR #101/#102: each validator/resolver PR carries `docs/qualification/stage2-s2a/mutations-<slice>.md` listing each mutation applied by hand (diff snippet), the test(s) that failed, and restoration. Minimum: every row of §12.1 plus every code in §10.

### 12.3 Cold-review checkpoints

1. S2a.0 (this plan): architecture cold review before S2a.1 starts.
2. After S2a.1: schema review against ADR-014 §1–§7 with the embedding fixture as the neutrality probe.
3. After S2a.3, **before merge**: full review of resolver, launcher, `verify_repo`, the reconciliation table, and the cut-over gate evidence (§13.1).
4. After S2a.5: C1–C7 register review; roadmap consistency.

---

## 13. PR sequence, cut-over gate and exact-head CI

### 13.0 Sequence

| PR | Branch | Contents | Depends on | Ships behaviour? |
|---|---|---|---|---|
| **S2a.0** | `feature/stage2-s2a-plan` | this document; the S1 engineering-baseline / closure-identity decision note | — | no |
| **S2a.1** | `feature/stage2-s2a-1-contracts` | `capabilities.py`, `binding.py`, manifest v2 schema + `DetectorModelSection`, runtime profile v2 schema, qualification record v2 schema + gate-set policy file, `model_pack_identity.py`, migration generator `tools/vision/migrate_component_binding_v1.py`, fixtures (detector + embedding), tests, mutation record | S2a.0 | no (nothing loads them yet; v1 artefacts untouched) |
| **S2a.2** | `feature/stage2-s2a-2-completion-3-2` | `.NET` contracts (+5 fields), validator/digest domain, schema files 3.2, golden vector 3.2, example, canonicalization test, replay tests (§4.5), attestation response; worker `control_plane`/`client` accept `"3.2"` in `SUPPORTED_COMPLETION_SCHEMA_VERSIONS`; the S1.4 setting `MAVI_COMPLETION_SCHEMA_VERSION` still exists at this head (retired in S2a.3 by P-16) with its `Literal` widened to `{"3.0","3.1","3.2"}`, default 3.1, and a settings validator raising `completion_32_requires_binding` for `3.2` because the worker cannot yet supply the fields | S2a.1 (registry for `capabilityId` validation) | platform accepts 3.2; nothing emits it |
| **S2a.3** | `feature/stage2-s2a-3-cutover` | resolver, settings (P-16 override), supervisor, provenance, worker emits 3.2 by contract, v2 artefacts written by the migration generator (binding, manifest incl. licence-notice artefact, runtime.json, record) and v1 files deleted, Python pack tools v2 (§5.5), `verify_repo`, boundary/model-pack/task12/Task-10 workflows, launcher + **`Install-MaviVisionModelPack.ps1` v2** + Common.psm1 + PowerShell contract tests, harness/tool updates (§5.3), reconciliation doc (§9), record/replay compare evidence | S2a.1, S2a.2 | **yes** — one atomic PR; a Windows Development host can reinstall and reach READY from this head alone |
| **S2a.4** | `feature/stage2-s2a-4-offline-kit` | N-pack kit assembly and completeness checks (`Sync-MaviOfflineVisionComponentStore.ps1`, kit inventory v2 end-to-end), Setup-MAVI D-1 repair with §7 tests 1 and 5, kit-section runbook updates, dependency-policy staging path. **No identity change**: `modelPackId`, `runtimePackId`, manifest and record SHAs are exactly those frozen in S2a.3 (a test pins them). | S2a.3 | guided Windows setup path |
| **S2a.5** | `feature/stage2-s2a-5-closure` | S2a evidence record (§15), Task-10 rerun on head, C1–C7 register PASS with evidence log, roadmap/parent-plan §9 correction, ADR-014 "implementation record" section, and — only if narrowly justified — the D-2 `s1_memory.py` early-variant check with its own tests | S2a.4 | no |

Why S2a.3 is one PR: the binding file, `verify_repo`, the boundary/model-pack workflows, the Python pack tools (§5.5), the launcher, the Model Pack installer and the worker all read the same artefacts; splitting them leaves either a red `main` or two binding systems. It is large but mechanical, and S2a.1/S2a.2 carry all the logic and tests in advance so S2a.3 is mostly wiring plus generated artefacts.

### 13.1 Exact cut-over gate (S2a.3 merge conditions — all required)

1. Quality Gate green on the exact PR head (`.NET`, Python, `verify_repo`, S1.4 tooling tests, web).
2. `Vision Runtime Component Boundary` green on the exact head for all three variants (proves every `runtimePackId` unchanged against the v2 binding).
3. `Vision Model Pack` green on the exact head (derived v2 `modelPackId` equals the binding).
4. `Task 12 Offline Runtime Pack` green on the exact head with the new id-comparison step.
5. `Task 10 Runtime Qualification` dispatched against the exact head for both CPU variants: `bytetrack-qualification.json`, `production-composition-qualification.json`, `production-runtime-smoke.json` all `passed`, `headSha` == PR head.
5a. `Task 17 Acceptance` green on the exact head (it is the only workflow that runs the PowerShell contract tests `Test-MaviVision*Contracts.ps1` / `Test-MaviSetupContracts.ps1`, `task17-acceptance.yml:112,181-184`, on `windows-latest`).
5b. **Installability proof:** the PowerShell contract tests include installing a v2 pack fixture with `Install-MaviVisionModelPack.ps1` v2 into a temporary store and passing the launcher's `Assert-MaviVisionWorkerComponentCompatibility` against the v2 binding, plus §7 tests 2–4; and the licence-notice artefact is present in the built pack and in the `.qualification-model-root`.
6. Record/replay compare (§9 item 1) committed under `docs/qualification/stage2-s2a/` with the allow-list test passing.
7. Reconciliation document present with old/new hashes; RTMDet record `overallResult: pending`, manifest `unverified`.
8. Mutation record for the resolver/provenance/verify_repo changes, including both P-17 class-A mutations (variant-status and release-lock-status).
8a. `verify_repo` green on the real artefacts with `linux-x86_64-cuda` classified A (record null/pending, absent from the binding) and the three class-B variants cross-checked; the §12.1 P-17 negative fixtures pass.
9. Cold review sign-off recorded in the PR.
10. S2a.3 is the **behavioural** cut-over (the first PR that changes what the worker and platform do). Under the current S1 checker the *closure* consequence arrives earlier: S2a.1 already adds files under `src/vision/mavi_vision/runtime/*` and `config/acceptance/*`, which are unmapped behavior-bearing paths and invalidate every S1 unit (companion decision note). The S2a.1 PR body states that; the S2a.3 PR body restates it.

### 13.2 Exact-head CI requirements per PR

| PR | Required green on exact head |
|---|---|
| S2a.0 | Quality Gate (docs-only; `verify_repo` must still pass) |
| S2a.1 | Quality Gate. PR body states the S1-checker consequence (§13.1 item 10). |
| S2a.2 | Quality Gate; Task 10 (completion contract change → rule 3); Task 17 (contract-vector checks) |
| S2a.3 | §13.1 |
| S2a.4 | Quality Gate; Task 12; Vision Model Pack; Task 17 (PowerShell contract tests incl. the D-1 test) |
| S2a.5 | Quality Gate; Task 10 (final evidence run); Task 17 |

---

## 14. Resolved questions (previously open)

| Question | Resolution | Evidence |
|---|---|---|
| `sizeBytes` in the source manifest | Not carried (P-14). | No source manifest in the repo carries sizes; `build_model_pack.py` measures them and `test_model_pack_builder.py:97` asserts them against bytes. |
| CUDA declared-but-pending | Kept (P-13). | Current binding declares `windows-x86_64-cuda`; `runtime.json` lock is `pending-hardware-qualification`; `Resolve-MaviVisionCudaAvailability` reads the declared id for Development Auto. |
| Licence notice as a Model Pack artefact | Yes, and **in the identity from S2a.3** (P-15); manifest carries metadata with `pending-review`. | Deriving the id without the notice in S2a.3 and adding it in S2a.4 would change `modelPackId` twice (P-3 hashes the full artefact set); the mmdetection commit is already pinned in `vision-model-pack.yml`, so the notice's SHA is obtainable before S2a.3. |
| S1 closure identity | Decided by the companion note; no checker change, no waiver, no retroactive closure. | — |

No question remains that changes architecture or user policy.

---

## 15. S2a qualification evidence (bounded)

S2a introduces no scaling or envelope units. Its evidence is:

| Kind | Units | Evidence |
|---|---|---|
| engineering regression | C1–C5 | Quality Gate (Python + `.NET` + `verify_repo`) on the closure head; mutation records |
| boundary proof | C6, C7 | boundary / model-pack / task12 workflows; `verify_repo` negative fixtures; record/replay compare; Task-10 on the S2a.3 and S2a.5 heads |
| formal release qualification | none in S2a | — |

The S2a.5 evidence record is a markdown file plus the retained JSON/JUnit artefacts under `docs/qualification/stage2-s2a/evidence/<sha12>/`, with SHA-256 of each retained file and the workflow run ids. **No new checker or manifest tooling is built in S2a.**

**Recorded for a future dedicated slice (not S2a):** a qualification manifest with immutable measured identity, per-unit retained results, resumable campaigns, explicit dependency-scoped invalidation (a surface path may be excused for a unit only by a mutation-proven discriminating regression suite that passes on the new SHA; envelope units additionally need a reduced-N characterization run within recorded tolerance), and the four evidence kinds (engineering regression / scaling characterization / boundary proof / formal release). That redesign is the prerequisite for any formal S1 closure on a post-S2a `main` (companion decision note) and belongs to S5 planning, reviewed on its own.

---

## 16. Acceptance mapping C1–C7 (evidence each row will cite)

| Row | Evidence at closure (S2a.5) |
|---|---|
| C1 | binding v2 file + `binding.py` tests incl. embedding fixture + mutation record; `verify_repo` green |
| C2 | manifest v2 + `DetectorModelSection`; embedding fixture loads with no detector field; `test_v2_rejects_checkpoint` |
| C3 | runtime.json v2 without checkpoint/config; roles in the binding; supervisor starts role `vision` from the resolver; Task-10 production smoke |
| C4 | record v2 + gate-set policy file + identity-mismatch tests + P-17 variant-semantics tests (class-A valid; null for class B, unknown, missing and class-A-claims-pass rejected) |
| C5 | 3.2 golden vector; attestation shows pack ids; stored 3.1/3.2 replay tests; a real Development run's provenance retained as evidence showing `runtimePackSource` truthfully |
| C6 | negative tests for every `verify_repo`/kit/workflow check (incl. binding variant set == class-B set); task12 id check; boundary + model-pack workflows green on head; §7 tests 1–5 |
| C7 | reconciliation document with old/new hashes, recording that `linux-x86_64-cuda` stays class A (pending, no pack, null id) exactly as at `c176b048`; record/replay compare allow-list test; Task-10 on head; RTMDet still `pending`/`unverified` |

Every PASS row records commit SHA, workflow run ids, artefact hashes and the non-claim "RTMDet qualification unchanged: pending; no Production or CUDA claim" per the register's evidence-log rules.

---

## 17. S2a.1 implementation record (errata pinned during implementation)

S2a.1 implemented §4.1–§4.4 as Python contracts. It found the following plan gaps and resolved each in the stricter direction. None changes ADR-014 architecture.

| # | Plan text | Implemented | Reason |
|---|---|---|---|
| E-1 | §4.2 example `provenance.sourceUrl` | `provenance.{publisher, sourceRepository, sourceRevision}`, all non-URL text, enforced at the schema boundary (`model_provenance_network_locator`) by the one `RELEASE_NETWORK_LOCATORS` rule, which now lives in `mavi_vision.runtime.manifest` and which `verify_repo` delegates to | `models/manifests` is in `RELEASE_TEXT_ROOTS`; `verify_repo`'s `RELEASE_NETWORK_LOCATORS` scan (`tools/verify_repo.py:128-140, 1142-1147`) rejects any `https://` in release metadata. The URL stays in `vision-model-pack.yml`. |
| E-2 | P-4 / §10: the resolver rejects unregistered capability ids | The binding, manifest and record schemas also reject them (`capability_unknown:<id>`); the resolver still rejects unimplemented ids (`capability_not_implemented`) | Fails closed earlier; the S2a.1 validators and the resolver use one registry (`capabilities.py`). |
| E-3 | §4.1 rule 3 "exactly one **enabled** binding" vs rule 4 "disabled binding retained" | File rule: exactly one binding (enabled or not) per role capability. Start-time rule (S2a.3 resolver): the binding must be enabled (`capability_binding_disabled`). `enabled` is a strict JSON boolean. | Rules 3 and 4 were contradictory as written. |
| E-4 | P-12 gate sets: names only | Each gate set declares `scope: "common"` or `scope: "capability"` with `capabilityIds`. A record must carry exactly the applicable sets in canonical order, and at least one capability-scoped set (`qualification_gate_sets_mismatch`, `qualification_capability_gate_set_missing`). | Without applicability a detector record could pass without detector gates, and detector gates could be imposed on another capability (ADR-014 §6). |
| E-5 | §4.4 `evidence: {}` (shape unspecified) | `evidence` is keyed variant → gate → evidence. A passed gate needs evidence and a pending gate may not have any, per variant. | Gates are evaluated per variant (P-12). |
| E-6 | §4.2 `capabilitySpecific` sections | A closed registry of section schemas (`detector`, and `embedding` for the neutrality fixture). An unregistered section fails (`capability_section_unsupported`). | "Unknown fields remain fail-closed" (ADR-014 §3). |
| E-7 | §4.2 licence rules | `licence.noticeArtifactRole` must be `licence-notice`, and the detector section's checkpoint and config roles must be distinct and not the notice. | Otherwise the notice could be re-pointed at the checkpoint and drop out of the identity (P-15). |
| E-8 | P-14 "built pack manifests and install state carry measured sizes" | Only the built Model Pack manifest carries measured sizes; the install state binds that manifest by SHA-256 (§5.4 field list; ADR-014 §3 as amended) | P-14 contradicted §5.4. |
| E-9 | Identity-bearing text | `modelId` is kebab-case; `modelVersion` is restricted ASCII; the runtime profile id (= family id) is kebab-case; no control characters in any identity text; v2 JSON rejects duplicate object keys | One name has one encoding, and the bytes a reviewer reads are the bytes parsed. |
| E-10 | §13.0 S2a.3: generator writes the v2 artefacts | The generator never overwrites and reads lock and requirements files beside its **input** runtime profile. S2a.3 therefore generates into a temporary directory and then moves the four files into place. The v2 `runtime.json` replaces the v1 file at the same path. Publication is create-only and rollback-protected. Each destination is created, never replaced, from a fully written temporary file, so a pre-existing destination is never replaced, and rollback removes only paths this invocation recorded as created. On a staging or publication failure, or an interrupt raised there, the generator attempts to remove every destination and temporary file that invocation recorded, and one failed removal does not stop the others. For an ordinary error it exits 2 and names any destination it could not remove on stderr (`migration_publication_failed:left=...`); an interrupt is re-raised after the same rollback attempt. This is not an unconditional atomicity guarantee: an asynchronous interrupt between creating a destination and recording it, or a filesystem that refuses the removal, can leave a created file behind, and a killed process runs no rollback at all. | Recorded so the S2a.3 cut-over does not rediscover it. |
| E-11 | Generator "one consistent v1 identity set" | The generator validates model, runtime-profile, lock, requirements and record identity, and re-derives every bound `runtimePackId` from the variant, that variant's recorded `pythonIdentity.version`, the verified lock and requirements hashes and the bound `nativeAbi`; a stale id fails `runtime_pack_id_mismatch:<variant>` instead of being copied into the v2 binding and record. It copies `policies.pipelineProfileId` and `policies.pipelineProfileSha256` from the v1 record **as recorded**, without reading or hashing the live pipeline profile. Live `policies.*` reconciliation is the job of the S2a.3 resolver and `verify_repo`. | Keeps the generator's claim exact. |

Recorded and not changed in S2a.1:
- `policies` is optional (ADR-014 §6: "where relevant"). The only two encodings of "no policy" are: (1) the `policies` key is omitted; or (2) `policies` is present with both `pipelineProfileId` and `pipelineProfileSha256` set to null. Explicit `"policies": null`, `{}`, a half-populated object (one field present or non-null without the other), unknown fields and malformed values fail closed. Whether S2a.3 requires the pipeline policy for `detector` is decided there.
- Source-manifest artefact order is free, because the identity sorts. Tests pin identity order-independence.

---

## 18. S2a.2 implementation record (errata pinned during implementation)

S2a.2 implemented §4.5 on the platform, and the §13.0 S2a.2 row on the worker. The platform accepts completion 3.2; nothing emits it. It found the following plan gaps and resolved each in the stricter direction. None changes ADR-014 architecture, and none is an S2a.3 step.

| # | Plan text | Implemented | Reason |
|---|---|---|---|
| E2-1 | §4.5 intro: "five **required** properties" | Four are required (`capabilityId`, `modelPackId`, `runtimePackSource`, `componentBindingSha256`); `runtimePackId` is optional, and absent and `null` are the same body. | §4.5 Validation paragraph and P-8 say so explicitly; the intro sentence contradicted them. |
| E2-2 | §4.5 Validation: "for 3.0/3.1 bodies the five fields must be absent" | 2.0 bodies must also omit them (`provenance_v32_field_in_v3_body`). | 2.0 shares the provenance record; otherwise a 2.0 body could carry an identity that no 2.0 digest binds. |
| E2-3 | §13.0: "S2a.1 (registry for `capabilityId` validation)" | The registry is published as the 3.2 schema enum and mirrored by `VisionRuntimeProvenanceParser.KnownCapabilityIds`. Cross-language tests bind the schema enum to `mavi_vision.runtime.capabilities.KNOWN_CAPABILITIES` (Python) and to the .NET set. | Same pattern as the device-resolution-reason vocabulary. The platform cannot import the Python registry, and the schema must be the one published vocabulary. |
| E2-4 | §4.5 `modelPackId` "derived from the loaded manifest" | The platform checks the `mavi-model-v2-`/`mavi-runtime-v2-` grammar (exact prefix, 64 lower-case hex, fixed length) and the pairing only. It never derives, re-derives or invents an identity. | Derivation is the worker's, in S2a.3. The hardening point was re-checked: no S2a.2 path calls `model_pack_id`/`runtime_pack_id` with raw values, so no validation had to be centralised. |
| E2-5 | §4.5 "the response factories … accept `"3.2"`" | The factories take the version and echo it. They refuse a synchronous or unknown version (`ArgumentException`). The worker requires the echoed version to be the one it sent, for 3.1 and 3.2. | Otherwise a 3.1 worker could accept a 3.2 answer, now that the hand-off model reads both versions. |
| E2-6 | §4.5 Persistence: attestation "gains the five fields" | Stored provenance has no version. The attestation reader applies the 3.2 rules exactly when any of the five members is present, so a partial or unpaired stored identity is an integrity failure. The attestation members are omitted when null. | Stored rows were validated at ingest; re-reading them under laxer rules would hide corruption. |
| E2-7 | §4.5 golden vectors | `vision-job-complete-v3.2.example.json` (installed pack) and `vision-job-complete-v3.2-unpacked-environment.example.json` are the 3.1 golden example with only the five members added. Their pack ids and binding hash are synthetic, grammar-valid placeholders, like every other hash in these examples. | No real Runtime Pack identity is paired with placeholder lock hashes, and no qualified identity changes. |
| E2-8 | §12.1 "`test_contract_schema_canonicalization.py` schema conformance" | A shared negative corpus, `contracts/test-vectors/control-plane-v3.2-invalid.json`. The published schema, the .NET validator (with the exact code) and `verify_repo` all reject every case. `verify_repo` also requires the 3.2 schema to equal one pinned delta over 3.1 (`expected_completion_v32_schema`). | Tests every rule at each boundary; a schema edit cannot drift from the validator. |
| E2-9 | §13.0 "`client` accept `"3.2"` in `SUPPORTED_COMPLETION_SCHEMA_VERSIONS`" | Done, but inert. `MAVI_COMPLETION_SCHEMA_VERSION=3.2` fails with `completion_32_requires_binding`, and `VisionJobCompleteV3` still admits only 3.0/3.1, so even settings forced past validation send nothing. | "Nothing emits it" (§13.0) is proven twice, not assumed. |

Recorded and not changed in S2a.2:

- The .NET binder reads an explicit JSON `null` as absent for the five members, as it does for every nullable provenance member. A 2.0/3.0/3.1 body carrying `"runtimePackId": null` (or another member as `null`) is accepted by the platform although the published earlier-version schema refuses it. The null never reaches the digest or the stored provenance: the members are written only when non-null. Closing this needs presence tracking in the contract binder, which the 3.2 `runtimePackId` rule ("absent and null are the same body") does not want.
- `ProcessingResultStore` (the synchronous path) still accepts only 2.0, and 3.0 when the gate is off. A 3.2 body can reach it only through the asynchronous set, so no change was needed.

---

## 19. S2a.3 implementation record (errata pinned during implementation)

S2a.3 is the behavioural cut-over: the worker composes the vision role only through the component binding v2 and emits completion 3.2; every v1 composition input is refused. Identities are reconciled in `docs/qualification/stage2-s2a/2026-09-27-detector-identity-reconciliation.md`; mutations in `docs/qualification/stage2-s2a/mutations-s2a-3.md`. It found the following plan gaps and resolved each in the stricter direction. None changes ADR-014 architecture.

| # | Plan text | Implemented | Reason |
|---|---|---|---|
| E3-1 | §5.2 "delete the v1 loaders" | The v1 runtime readers are deleted from `mavi_vision` (manifest, runtime profile, record, `verify_release_selection`, v1 `model_pack_id`). Their schema classes survive verbatim only in the tooling module `tools/vision/v1_release_schemas.py`, imported by nothing but the one-shot generator (`test_v1_release_schemas_are_tooling_only` proves the importer set and that no `mavi_vision` module names a v1 reader). | The generator must still read v1 to prove its output; no runtime path may. |
| E3-2 | §9 "the v1 record and v1 manifest files are deleted" | Deleted from the release roots; byte-identical copies are frozen as test fixtures (`src/vision/tests/fixtures/component-binding-v1/`, SHA-256 pinned), together with a copy of the v1 runtime profile and the licence notice blob. | The generator-equality test and the reconciliation need the exact consumed bytes; every loader refuses them. |
| E3-3 | §5.4 worker variables | Adds `MAVI_OVERLAY_ROOT` (default the working directory): the directory holding `models/`, `src/vision/runtime/` and `config/acceptance/`. | The resolver must find the family profile, manifests, records and gate sets for a checkout, an offline bundle's `release/` and the Windows launcher alike. |
| E3-4 | P-8 "verified requires an installed pack" | `verified` also requires the record's variant for the *observed* runtime variant to be `passed` (Development downgrades, Production refuses `qualification_variant_not_passed`). | A pack installed for a variant the record never passed must not be labelled verified. |
| E3-5 | P-12 vs v1 deployment-profile gate names | A deployment profile's v1 gate names map to "that variant's `status == passed` (every gate passed)", and the profile's evidence must cover every gate of that variant (`qualification_profile_evidence_missing`). | No weaker, gate-by-gate reading exists in v2 records. |
| E3-6 | §17 "whether S2a.3 requires the pipeline policy for `detector` is decided there" | Required: a detector record without `policies` fails `qualification_policies_required:detector`; any record's policy is reconciled against the live pipeline profile (`qualification_policy_mismatch`). | The detector's tracker parameters are qualified evidence. |
| E3-7 | §10 code list | Adds `model_capability_mismatch:<id>`, `runtime_pack_binding_id_mismatch:<variant>` (every pinned id is re-derived from its tracked lock at family load, for every declared variant, not only the observed one), `runtime_variant_resolution_mismatch` (provenance refuses a live runtime on another variant), `completion_contract_version_not_a_role_contract` (a 3.0/3.1 contract exists only as the override), `settings_v1_composition_rejected:<names>` with worker exit code 2, and `launch_model_pack_ambiguous`. | Each closes a path §10 left implicit. |
| E3-8 | §9 "differing keys are exactly {…}" | The record/replay test requires the differing provenance keys to be a subset of the allow-list and the identity keys to have changed to exactly the reconciled values. `schemaVersion` is not in B1 summaries, `mavi_build` was the same in both runs, and summaries use the runtime's snake_case names. | "Exactly" would fail on keys that legitimately did not differ; the reconciled-value assertions keep it discriminating. |
| E3-9 | §5.5 Phase-1 tools (plan gap) | Readers are ported to the resolver. The writers are fenced: `promote_phase1_release.py` and `compute_target_verified_manifest.py` refuse every invocation with `v2_promotion_not_supported_by_this_slice` before reading or writing anything, and `assess_phase1_closure.py` always carries the pending item `qualification-evidence-binding:v2_promotion_not_supported_by_this_slice`. | The plan defines no v2 promotion model: how v1-named gate evidence binds to per-variant gates, how a v2 record's variants and profile index advance, and how a v2 manifest becomes `verified`. Applying v1 rules silently would be an unreviewed promotion model. A later slice defines v2 promotion in an ADR. RTMDet stays `unverified`/`pending`; tests prove no promotion path exists. |
| E3-10 | §5.3 `build_offline_bundle.py` | A bundle's `release/` is an application overlay in the repository layout, verified by the same resolver at input, assembly and staged-bundle time. It ships every lock and requirements file the binding pins (ADR-009 follow-up 5), and the bundle id covers the binding SHA and the Model Pack id. A `production` bundle is refused by the resolver's own policy (`runtime_pack_required` at best). | A bundle-built environment is not an installed Runtime Pack (P-8). |
| E3-11 | §6 cross-checks | `verify_repo` also fails on a tracked manifest or record that no capability binding reaches. | Otherwise its relationships would never be checked. |
| E3-12 | §6 and §5 rules stated twice | The resolver's record identity and policy rules are public functions (`check_record_identity`, `check_record_policies`), and `verify_repo` calls them and `load_role_family` rather than re-implementing them. | One rule, not two copies. |
| E3-13 | ADR-009 C4 variant patch | `build_development_hardware_evidence.py` no longer emits `resolvedConfigSha256` into the variant patch (a v2 family profile carries no model identity) but still requires the runtime verification to report a well-formed digest, which stays inside the hashed verification the bundle binds. It does not compare that digest with the Model Pack manifest. | The family profile carries no model identity; the evidence bundle still carries the one reported. |
| E3-14 | §7 kit completeness "for the requested variants" | The requested variants are those of the supplied Runtime Packs. A pack for an unbound variant fails `kit_variant_not_bound:<variant>`. N-pack kit assembly and the Setup repair remain S2a.4. | "Requested" was not defined. |
| E3-15 | §5.4 launcher | The launcher keeps its overlay checks keyed by `qualificationId`. It refuses a store whose manifests are unreadable, and reserves dot-prefixed pack directory names for the installer's stage and rollback directories. | An unreadable manifest could hide a duplicate id. |
| E3-16 | fixture identity | The fixture worker harness names the all-zero `mavi-model-v2-000…` Model Pack id (like its all-zero digests) and the binding it was composed from. | It runs no Model Pack; nothing is borrowed from the real binding. |
| E3-17 | P-8 installed pack | `installed-pack` also requires the running interpreter to be the pack's own `<installRoot>/venv` (`sys.prefix`), else `runtime_pack_not_running_environment`; tools assessing a pack on disk name that environment explicitly. | Cold review: a manifest path alone let an unpacked venv claim a pack id. |
| E3-18 | §4.1 rule 2 `entryPoint` | The role's `entryPoint` must be the module this package runs for it (`IMPLEMENTED_ROLE_ENTRY_POINTS`: `vision` → `mavi_vision.worker.main`, the module the launcher starts), else `role_entry_point_unsupported:<role>`, in the resolver and `verify_repo`. | PR review: a syntactically valid but different entry point was attested under the binding SHA while the fixed worker ran. |
| E3-19 | §4.2 `inputContract` | A bound Model Pack's `inputContract` must be the one the capability's runtime consumes (`detector`: `video-frame-rgb`, `colourSpace: RGB`), else `model_input_contract_unsupported:<capability>`, in the resolver and `verify_repo`. | PR review: `MMDetectionRuntime` consumes RGB frames and provenance attests `inputColourSpace = RGB`, whatever the pack declared. |

Recorded and not changed in S2a.3:

- `s1_memory.py` and the S1 recovery harness now reach the 3.1 body through the Development override (constructor arguments and one environment variable; the measured body is unchanged). This is behavior-bearing under `s1_evidence.py`. `test_s1_evidence.py` pins the pre-S2a `settings.py` it measures against (`tools/qualification/tests/fixtures/pre-s2a-worker-settings.py`). At a post-S2a.3 measured SHA the B3 activation rule finds no completion default and refuses, so **S1 remains OPEN** and no S1 closure is implied.
- Production readiness still requires the family runtime profile's `qualificationStatus: qualified` (`production_runtime_not_qualified`), which `check_runtime_qualification_status` withholds while any variant or lock is pending, the class-A `linux-x86_64-cuda` included. This is the base's rule, unchanged by the cut-over (§4.3 keeps `qualificationStatus`). So a qualified CPU variant cannot reach Production until every family variant is qualified. Moving Production readiness to the observed variant alone is a change to a Production gate and belongs in an ADR-014/ADR-009 amendment and the promotion slice, not here (PR review, recorded).
- The PowerShell contract scripts ran under PowerShell 7 on Linux; `Test-MaviSetupContracts.ps1` is Windows-only. Windows PowerShell 5.1 compatibility is proven only by Task 17 on Windows.

## 20. S2a.4 implementation record (errata pinned during implementation)

Scope and gate: `docs/superpowers/plans/2026-09-28-stage2-s2a-4-setup-offline-integration.md`. Base `main@137af862f5bd39740fa234cea9bdc1e6f7b7c4a3`. The slice introduces no identity change: `modelPackId`, `runtimePackId`, the binding, the manifest, the qualification record and the runtime profile are byte-identical to S2a.3, and `test_the_identities_s2a4_consumes_are_frozen` pins them. It makes no qualification change and promotes nothing. Mutation record: `docs/qualification/stage2-s2a/mutations-s2a-4.md` (24 of 24 caught).

| # | Plan text | Implemented as | Why |
|---|---|---|---|
| E4-1 | S2a.4 §2/§3.2 "passes the existing component-store verification" | `verify` checks the store's integrity but never compares it with a binding, so it cannot yield `kit_binding_mismatch`, `kit_incomplete` or `kit_unbound_component` at Setup time. `sync_offline_vision_components.py plan` fills that gap. It validates the repository binding, derives role `vision`'s Windows CPU Runtime Pack and every enabled Model Pack, runs `verify`, and then checks the inventory against the binding. Each source is the inventory entry of the required id. `Mavi.VisionSetup.psm1` calls it; PowerShell reads no inventory itself. | The one verifier gap S2a.4 §7 allows closing. No second composition reader. |
| E4-2 | §3.4 "identifies the expected binding file" | An inventory naming another binding file is `kit_binding_mismatch`, like a SHA mismatch. | §6 forbids new codes. |
| E4-3 | §3.5 revision | Reported (`Vision kit provenance`, `last-setup-result.json` `vision.kitApplicationRevision`), never compared. The plan tool has no revision input. | Binding SHA is the composition identity. |
| E4-4 | §4.3 "or the existing explicit Runtime Bundle root" | A Runtime Bundle root supplies the Runtime Pack only. It holds `<root>\runtime-pack-manifest.json` or `<root>\<variant>\runtime-pack-manifest.json`, and its id and material fields must be the binding entry's (`kit_unbound_component:<id>`, `runtime_requirement_mismatch:<key>`). Every bound Model Pack must then already be installed, else `kit_incomplete:<modelPackId>` before any install. A legacy `bundle-manifest.json` without a runtime manifest is `kit_incomplete:<runtimePackId>` ("not an installable Runtime Pack"). | D-1, with no new code. |
| E4-5 | source precedence (unstated) | 1. `MAVI_VISION_BUNDLE_ROOT` (process, then machine), used as given and never replaced; a missing directory fails. 2. The store in the Setup bundle/kit. 3. The sibling `MAVI-Vision-Runtime-Bundle`. | Explicit operator intent must not be silently overridden. |
| E4-6 | no Vision source at all (unstated) | Setup completes the rest and reports `Vision composition WARN not installed`; `last-setup-result.json` `vision.status = "not-installed"`. It never reports READY for vision. Any found source that fails preflight, install or readiness fails Setup. | §4.7 forbids READY or INFO for a partial install. It does not make vision mandatory for a workstation without components. |
| E4-7 | §4.7 "existing worker component compatibility assertion used by the launcher" | `Start-MaviVisionWorker.ps1 -VerifyOnly` runs every launch check up to and including `launch_component_compatibility_failed` and returns before the worker environment or process. Setup uses it with `-DevicePolicy cpu`. | Reuses the launcher instead of copying its checks. |
| E4-8 | §4.8 CUDA optional | A bound Windows CUDA Runtime Pack is installed only when the source carries it, after the Model Packs. Absent is INFO. The plan tool offers it only if the binding declares the variant. | Nothing becomes required or qualified. |
| E4-9 | §5 partial install | `Invoke-MaviVisionComponentInstallation` installs in the order CPU runtime, Model Packs by ordinal `modelPackId`, optional runtime, then the readiness check. A failure names the component and the packs installed so far; nothing is rolled back. The installers' own reuse makes a rerun converge. | As specified. |
| E4-10 | implementation hazard | Setup passes plain script blocks, not `GetNewClosure()` blocks. From a closure's dynamic module, the installers' `Import-Module -Force` unloads Setup's own copies of `Mavi.Setup.Common` and `Mavi.VisionRuntime.Common`. This was reproduced during implementation; a contract-test source pin covers it (mutation M21). | A Setup that loses `Write-MaviSetupStatus` after the vision install would fail after a successful install. |
| E4-11 | §7 `Sync-MaviOfflineVisionComponentStore.ps1` | `-RuntimePackRoot`/`-ModelPackRoot` take several packs; the wrapper prefers the workspace `.venv` Python, which has `mavi_vision`'s dependencies. | N-pack kit assembly end to end. |
| E4-12 | §10 Task 17 | `Test-MaviVisionSetupContracts.ps1` runs in Task 17 on PowerShell 7 (Linux job) and Windows PowerShell 5.1 (Windows job, after `pip install -e ./src/vision`). `tools/vision/**` is added to Task 17's paths. | The contracts are only as good as the job that runs them. |
| E4-13 | documentation scope | `docs/runbooks/local-development.md` is also rewritten. It told operators to use a `bundle-manifest.json` Runtime Bundle whose commit matches HEAD. | §9: remove every instruction relying on `bundle-manifest.json`. |
| E4-14 | combined setup bundle (PR review) | `New-MaviOfflineSetupBundle.ps1 -IncludeDevelopmentPayload` copies the kit's `vision\` store into the bundle before hashing its files, after running the store verifier when the workspace Python exists. Setup run from the bundle with `-RepositoryRoot` then finds `<bundle>\vision\component-inventory.json`. | Without it the combined bundle could never deliver the Vision components. |
| E4-15 | §3 preflight for a Runtime Bundle source (owner review) | Each already-installed bound Model Pack must pass, in preflight, the launcher's non-mutating per-pack checks. These are: manifest valid; pack directory; `model-install.json` bound to the installed manifest by SHA-256; state identity equal to the manifest; the capability provided; every artefact re-hashed (`Assert-MaviVisionSetupInstalledModelPack`). Otherwise `kit_incomplete:<modelPackId>`. | A stale or corrupt pack would otherwise be found only by the readiness check, after the Runtime Pack install. |
| E4-16 | §3 preflight for a Runtime Bundle source (second cold review) | Each Runtime Pack located in a Runtime Bundle (CPU and, if present, CUDA) is proven by the store's own component validator before any installer runs: `sync_offline_vision_components.py plan --runtime-pack <dir>` (`_validate_component`) checks every artefact's size and SHA-256, undeclared files and symlinks, and that the pack is the binding's entry for its variant. The failure codes are `component_artifact_*`, `kit_unbound_component:<id>` and `runtime_requirement_mismatch:<key>`. The PowerShell locator now only finds the pack by its declared variant (and diagnoses D-1). | A damaged optional CUDA pack, installed last, would otherwise fail only after the CPU Runtime Pack was installed. Identity checks now live in one place. |

**Preflight invariant (E4-15, E4-16).** Every component that Setup intends to rely on — whether supplied by the selected source or already installed — passes its authoritative non-mutating validation before the first installation mutation. The authorities are:

- the component-store validator for store packs and Runtime Bundle packs;
- the launcher's per-pack checks, including `Assert-MaviVisionInstalledModelPackIntegrity`, for already-installed Model Packs;
- the binding plan for identity and completeness.

Recorded and not changed in S2a.4:

- The family-wide Production qualification rule recorded under §19 is unchanged.
- `Test-MaviSetupContracts.ps1` remains Windows-only. Setup-MAVI's wiring of the real Runtime Pack installer and the launcher readiness check is proven from source and by Task 17's Windows parse. A physical Windows install is not part of hosted CI.
