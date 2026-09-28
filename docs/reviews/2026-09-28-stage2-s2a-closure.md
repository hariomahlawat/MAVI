# Stage 2 S2a — Component Binding v2 Closure

**Status:** Closed on `main@406172657599350ecbb27819865ecc9482c6c97d`  
**Date:** 2026-09-28  
**Scope:** S2a.1–S2a.4 only; this record does not claim S2b or later Stage-2 acceptance.

## 1. Closure statement

S2a is complete. The repository has migrated from the detector-centric single-model component contract to Component Binding v2 and has integrated that contract through validation, runtime/model installation, offline component-store assembly, Setup-MAVI preflight and final readiness verification.

The governing composition authority is the repository Component Binding. Runtime Pack, Model Pack and capability identities are selected by binding id, not by directory order, timestamps or implicit detector assumptions.

## 2. Merged implementation chain

S2a was delivered through the reviewed S2a implementation sequence culminating in:

- PR #110 — Component Binding v2 cut-over / S2a.3;
- PR #111 — hardened S2a.4 implementation plan;
- PR #112 — Setup/offline-kit integration / S2a.4, merged as `406172657599350ecbb27819865ecc9482c6c97d`.

PR #112 merged only after exact-head Quality Gate, Task 12, Vision Model Pack and Task 17 evidence was green and all P1/P2 review findings were resolved.

## 3. Acceptance C1–C7 reconciliation

The Stage-2 acceptance register remains authoritative. On the merged S2a baseline, C1–C7 are satisfied by implementation and retained verification evidence:

- **C1 PASS** — `capabilityBindings[]` is the capability-neutral composition shape and supports detector plus future capability ids without Stage-2-only structural fields.
- **C2 PASS** — Model manifest v2 has a capability-neutral common shape; detector-specific resolved configuration is capability-specific rather than universally mandatory.
- **C3 PASS** — Runtime profile v2 is decoupled from a privileged checkpoint and declares independently startable roles.
- **C4 PASS** — qualification records are capability-scoped and separate common from capability-specific gates.
- **C5 PASS** — capability/model/runtime identities are durable provenance and participate where required in binding/digest contracts.
- **C6 PASS** — repository verification, component-store verification, offline packaging, Setup preflight and CI fail closed on binding/manifest/runtime/model mismatch.
- **C7 PASS** — detector-era identity migration was deliberately reconciled; S2a did not silently promote RTMDet or change Production/CUDA qualification state.

A follow-on documentation reconciliation should reflect these PASS states in `docs/reviews/2026-09-23-visual-attributes-acceptance.md`; this closure record is evidence, not a second acceptance register.

## 4. Frozen S2a invariants carried into S2b

S2b must preserve all of the following:

1. Component Binding v2 remains the only composition authority.
2. Model Pack identity is capability-neutral and Runtime Pack identity is independent of a privileged model checkpoint.
3. Roles and capabilities are resolved from binding ids; no directory-order or first-pack selection is permitted.
4. Binding SHA is the offline-kit compatibility boundary; `applicationOverlay.revision` is provenance, not a second compatibility identity.
5. Setup validates the complete required composition before first installation mutation.
6. A successful copy/install is not READY; final launcher/component compatibility verification is required.
7. Multiple Model Packs are supported; S2b must not reintroduce a one-model assumption.
8. Development and Production qualification remain distinct under ADR-009.
9. S2a does not promote RTMDet, Production qualification or CUDA qualification.
10. Attribute lifecycle semantics belong to S2b; real attribute models belong to S2c.

## 5. Deliberately deferred items

The previously identified family-wide Production-qualification question remains deliberately deferred to the appropriate qualification/promotion work. S2a did not change that policy merely to close the component-binding migration.

Real person/vehicle attribute Model Packs, learned inference quality, corpus qualification and operational vocabulary remain S2c/S5 concerns. S2b uses a deterministic fixture inferencer only.

## 6. Next slice

The next implementation slice is **S2b — Attribute lifecycle with fixture inferencer**. Its purpose is to prove the asynchronous lifecycle, fencing, evidence transport, prediction upload/sealing, process isolation and bounded output contracts without coupling lifecycle correctness to a learned model.
