# Stage 2 S2a — Component Binding v2 Closure

**Status:** Closed on `main@406172657599350ecbb27819865ecc9482c6c97d`  
**Date:** 2026-09-28  
**Scope:** S2a.1–S2a.4 only; this record does not claim S2b or later Stage-2 acceptance.

## 1. Closure statement

S2a implementation is complete. The repository migrated from the detector-centric single-model component contract to Component Binding v2 and integrated that contract through validation, runtime/model installation, offline component-store assembly, Setup-MAVI preflight and final readiness verification.

The governing composition authority is the repository Component Binding. Runtime Pack, Model Pack and capability identities are selected by binding id, not by directory order, timestamps or implicit detector assumptions.

## 2. Merged implementation chain

S2a culminated in:

- PR #110 — Component Binding v2 cut-over / S2a.3;
- PR #111 — hardened S2a.4 implementation plan;
- PR #112 — Setup/offline-kit integration / S2a.4, merged as `406172657599350ecbb27819865ecc9482c6c97d`.

PR #112 merged only after exact-head Quality Gate, Task 12, Vision Model Pack and Task 17 evidence was green and all P1/P2 review findings were resolved.

## 3. Acceptance authority

`docs/reviews/2026-09-23-visual-attributes-acceptance.md` is the sole authoritative Stage-2 acceptance register. This closure record does not maintain an independent PASS list.

PR #113 reconciles the register itself with the retained S2a evidence. In particular, C3 is deliberately narrow: Component Binding/runtime-profile v2 provides the multi-role schema and decouples runtime identity from a privileged checkpoint, but only the `vision` role is implemented/startable on the S2a baseline. Activating an independently startable `attributes` role is S2b work.

No S2a closure statement claims RTMDet Production qualification, CUDA qualification, family-wide Production qualification, a real attribute Model Pack, or S2b functionality.

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
