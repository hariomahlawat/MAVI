# PR #46 — Final Independent Cold Review

**Date:** 2026-09-18  
**Pull request:** #46 — `feat: make Phase 1 qualification deployment-profile aware`  
**Base:** `feature/task-10-rtmdet-bytetrack@557d5ccc356ae39766d95eec93ce0fdf49fdef31`  
**Reviewed executable head:** `5923d6f46907081ee8cfd445cb7b9462f33f5a46`  
**Review posture:** independent cold pass; implementation treated as new/untrusted until contracts were re-derived from code and evidence flow.

## Review objective

Determine whether PR #46 correctly implements ADR-008's deployment-profile model without allowing evidence, runtime identity, device identity or release state from one Production profile to qualify another.

The review specifically traced:

`Deployment Profile -> Runtime Variant -> Prerequisites -> Offline Bundle -> Variant Evidence -> Performance/Recovery -> Formal Scenario -> Failure/Reprocess -> Promotion -> Production Acceptance -> Closure`

Development `Auto/CUDA/CPU` behavior and Production worker startup were reviewed separately so Development convenience cannot weaken Production qualification.

## Architectural result

The implementation now supports:

- **P1** — single-host Windows GPU, runtime `windows-x86_64-cuda`;
- **P2** — Windows Operational/Data + Linux GPU worker, runtime `linux-x86_64-cuda`;
- **P3** — single-host Windows CPU, runtime `windows-x86_64-cpu`;
- Development on one Windows workstation/laptop with CPU, explicit CUDA, or visible Auto selection;
- additive multi-profile promotion without reverting an already-verified model manifest;
- profile-specific evidence retention via `profileQualifications`;
- fail-closed Production startup using explicit deployment profile, policy SHA-256, runtime variant and actual device.

No Production profile inherits qualification from another.

---

## Findings and remediation

### FCR-01 — HIGH — closure used legacy top-level evidence after additive promotion

**Finding**

Additive promotion correctly retained a per-profile evidence map, but final closure still compared observed evidence against the legacy top-level `qualification.evidence` map.

A later profile can legitimately replace a shared top-level gate entry, for example `cctv-quality-baseline`. This meant a previously qualified profile could be evaluated against another profile's later top-level evidence.

**Risk**

Cross-profile evidence contamination. P1 closure could fail against P2 bytes or, in a less obvious future extension, consult the wrong profile's evidence.

**Correction**

`assess_phase1_closure.py` now:

- resolves the selected profile's `profileQualifications[profileId]`;
- verifies deployment-profile policy SHA-256;
- verifies runtime variant;
- verifies every selected gate against that profile's own evidence map;
- compares observed evidence bytes only to the selected profile's retained hashes.

A regression test explicitly simulates a later promotion overwriting the legacy top-level quality evidence while proving the earlier profile still closes against its own evidence.

**Status:** FIXED.

---

### FCR-02 — HIGH — Production worker launch paths omitted mandatory profile identity

**Finding**

The Production worker now correctly requires an explicit deployment profile, but three execution paths still launched it with `MAVI_PRODUCTION_MODE=true` without setting:

- `MAVI_DEPLOYMENT_PROFILE`;
- `MAVI_DEPLOYMENT_PROFILE_POLICY_PATH`.

Affected paths:

- formal Production scenario;
- failure/reprocess scenario;
- Production offline-variant worker flow.

**Risk**

A real authoritative run would fail closed at worker startup despite unit/CI success, preventing Production qualification.

**Correction**

All Production worker launch paths now pass the exact profile and the policy embedded in the exact Production bundle. Regression coverage verifies formal and failure/reprocess worker environments, and the variant qualifier rejects a Production bundle lacking the embedded profile-policy contract.

**Status:** FIXED.

---

### FCR-03 — HIGH — offline variant qualifier called obsolete bundle-verifier signature

**Finding**

The profile-aware bundle builder changed the internal staged-release verifier from a release-status argument to a full verified-input contract. `qualify_offline_variant.py` still called the old signature.

**Risk**

Every real offline qualification run could fail with a type/attribute error even though isolated unit paths remained green.

**Correction**

A dedicated manifest-based bundle verifier now:

- loads the embedded deployment-profile policy;
- validates its SHA-256 against the bundle manifest;
- validates Production profile -> runtime-variant mapping;
- performs profile-scoped release verification;
- verifies model ID, runtime-profile ID and selected lock identity.

The offline qualifier consumes this manifest contract instead of calling a private builder function with stale arguments.

**Status:** FIXED.

---

### FCR-04 — HIGH — Production scenario CLI profile was not bound to bundle profile

**Finding**

Formal and failure/reprocess qualification selected a profile from the operator-supplied policy but did not independently require the exact Production bundle manifest to carry the same profile, policy SHA-256 and runtime variant.

**Risk**

A caller could request one profile while supplying a bundle issued for another profile and defer the mismatch until worker startup.

**Correction**

Both Production scenario validators now fail before execution unless:

- `bundle.deploymentProfile == selected profile`;
- `bundle.deploymentProfilePolicySha256 == selected policy SHA-256`;
- `bundle.platformVariant == selected runtime variant`.

**Status:** FIXED.

---

### FCR-05 — MEDIUM — readiness/runbook retained global four-variant and universal-GPU assumptions

**Finding**

Operational documentation still instructed users to qualify all four runtime variants, assemble CPU+CUDA OS aggregates and treated GPU qualification as a universal mandatory readiness blocker.

That contradicted ADR-008 and would incorrectly block CPU-only P3.

**Correction**

Documentation and machine-readable readiness now state:

- P1 requires Windows CUDA;
- P2 requires Linux CUDA;
- P3 requires Windows CPU;
- GPU evidence is conditional on the claimed profile;
- the selected profile's exact offline variant is aggregated independently;
- the profile-aware toolchain is implemented;
- the next mandatory governance decision is Production profile selection.

Legacy unused prerequisite-role policy text was removed from the acceptance assembler.

**Status:** FIXED.

---

## Cold-review checks that passed by inspection

### Profile policy

- P1/P2/P3 have fixed, unique Production runtime variants.
- CUDA requirement is derived from the runtime variant and validated.
- prerequisite roles include explicit Windows CPU, Windows CUDA and Linux worker identities.
- single-host P1/P3 topology requires Vision host identity to equal the Windows operational host identity.

### Development device behavior

- Development remains a single Windows machine.
- CPU remains first-class.
- explicit CUDA does not silently become CPU.
- Auto selects CUDA only when the Windows CUDA Runtime Pack is installed, declared by the current Application Overlay and the GPU is actually usable.
- otherwise Auto falls back visibly to CPU.
- CPU and CUDA remain separate immutable runtime environments.

### Production startup

- Production requires `MAVI_DEPLOYMENT_PROFILE`.
- Production forbids `Auto`.
- selected profile, policy SHA-256, runtime variant and actual host/device must agree.
- P2 cannot execute as a Windows CUDA worker.
- Production bundle construction requires an explicit qualified profile.

### Promotion

- first profile can promote an unverified manifest;
- later profiles are additive;
- verified manifest bytes remain stable during additive qualification;
- existing qualified profiles are preserved;
- requalifying the same profile does not duplicate the profile index;
- stale deployment-profile policy invalidates prior profile qualification for further promotion;
- each profile retains its own exact gate-evidence map.

### Offline bundle

- Production bundle contains one selected runtime lock, not unrelated profile locks;
- deployment-profile policy is embedded and hash-bound;
- production bundle ID includes deployment-profile identity;
- changing an unrelated profile lock does not change another profile's bundle identity;
- qualification reopens and verifies the embedded profile policy and selected lock.

### Acceptance and closure

- prerequisites are exact-role/profile scoped;
- formal/empty/failure scenarios are profile and device scoped;
- performance evidence is profile scoped;
- Production acceptance contains one selected Production variant;
- closure validates selected-profile evidence rather than a shared top-level map;
- missing real-world evidence remains pending and cannot be converted into success by metadata alone.

---

## Residual items that are not implementation defects

PR #46 does **not** make Task 18 ready for authoritative Production evidence. The following remain intentional readiness blockers:

- first Production profile(s) not yet selected;
- held-out acceptance corpus not frozen;
- Person threshold not frozen;
- Vehicle threshold not frozen;
- empty-scene threshold not frozen;
- performance thresholds not frozen;
- Production prerequisite policy remains pending;
- supported prior-release artifact/scope unresolved;
- final application artifact not frozen;
- Offline Binary Kit identity not frozen;
- final Production setup/bundle identity not frozen;
- Windows CUDA remains unqualified for P1;
- Linux CUDA remains unqualified for P2.

Windows/Linux GPU evidence is **conditional** and does not block CPU-only P3 unless P1/P2 is claimed.

---

## CI / merge gate

This review document changes documentation only. The final PR head after recording this review must still satisfy the exact-head repository gates.

Required before taking PR #46 out of Draft:

1. MAVI Quality Gate — green;
2. Task 10 Runtime Qualification — green;
3. Task 17 Acceptance Validation — green;
4. GitHub reports PR mergeable;
5. no unresolved material review finding;
6. no executable commit after this reviewed executable head unless the cold review is refreshed.

Additional Runtime Pack / Model Pack workflows remain governed by path triggers and prior exact qualification; lack of a new run is not itself new qualification evidence.

---

## Review conclusion

**IMPLEMENTATION REVIEW CLEAN AFTER REMEDIATION, SUBJECT TO FINAL EXACT-HEAD CI.**

No unresolved material code finding remains from this cold pass.

This conclusion means the **profile-aware qualification tooling is implementation-ready for merge once the final exact-head gates pass**. It does **not** authorize Task-18 Production qualification; the separate readiness record continues to control that decision.
