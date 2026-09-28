# Stage 2 S2a/S2b Reconciliation Amendment

**Status:** Normative planning reconciliation for PR #113.  
**Date:** 2026-09-28  
**Baseline:** `main@406172657599350ecbb27819865ecc9482c6c97d` (PR #112 merged).  
**Authority:** This amendment reconciles stale Stage-2 summary wording with the authoritative acceptance register, accepted ADR-013/ADR-014, the S2a closure evidence, and the implementation-grade S2b plan. It does not create a second acceptance list.

## 1. Purpose and precedence

Two older planning summaries pre-date completion of S2a and still describe Stage 2 as if S1.4 were active and all persistence/supersession work belonged to S3:

- `docs/superpowers/plans/2026-09-23-visual-attributes.md`;
- `docs/superpowers/plans/capability-implementation-roadmap.md`.

For Stage-2 status and slice ownership after `main@406172657599350ecbb27819865ecc9482c6c97d`, the following order applies:

1. accepted ADR-013 and ADR-014 for architecture;
2. `docs/reviews/2026-09-23-visual-attributes-acceptance.md` for acceptance state and evidence;
3. `docs/superpowers/plans/2026-09-28-stage2-s2b-attribute-lifecycle.md` for S2b implementation semantics;
4. this amendment for reconciliation of the two stale summary documents above.

This amendment supersedes only the stale status/slice-summary statements identified below. All other content in the older plans remains in force unless separately amended by an accepted governing document.

## 2. Current Stage-2 state

The current Stage-2 sequence is:

- **S1 Track Evidence Set:** implemented/merged; acceptance evidence remains governed by the acceptance register.
- **S2a Component Binding v2:** implemented and merged through PR #112; C1–C7 status and retained evidence are owned by the authoritative acceptance register. C3 is satisfied only at the schema/composition level: the schema supports multiple roles, but only `vision` is startable at the S2a baseline. Enabling an independently startable `attributes` role is S2b work.
- **S2b Attribute lifecycle with fixture inferencer:** next implementation slice. No real attribute model is introduced. *(Status 2026-09-28: merged through PR #114 at `main@f7b03a24aba8b8bd303ed3a93b26622395e94c5f`.)*
- **S2c Real Model Packs:** follows S2b. *(Status 2026-09-28: PR #115 accepted the plan in `docs/superpowers/plans/2026-09-28-stage2-s2c-learned-attribute-model-packs.md`; S2c.0 baseline reconciliation is in progress and S2c.1 follows only after its exact-head CI and merge.)*
- **S3 Search/query integration:** follows the S2b persistence foundation.

The following capability-implementation-roadmap statements are stale and superseded for current Stage-2 status:

- the summary phrase **“S1.4 hardening/qualification in progress”**;
- the later statement **“S1.4 hardening/qualification is active … No acceptance-register row changes until S1.4 evidence.”**

Neither statement may be used to override the current acceptance register or prevent evidence-backed C-row reconciliation after merged S2a work.

## 3. Slice ownership reconciliation

The older parent-plan slice table assigned all “final outcome rows, supersession, v4 cursor, canonical predicates, measured PostgreSQL plans” to S3. That ownership is now refined because S2b cannot prove an atomic lifecycle/publication boundary without persisting the lifecycle’s fact-bearing outcome rows and supersession state.

The reconciled ownership is:

| Slice | Reconciled ownership |
|---|---|
| **S2b Attribute lifecycle with fixture inferencer** | Shared fencing primitives; `VisualAttributeAnalysis`; Python HTTP control plane; lease-scoped evidence reads; prediction upload/staging/sealing; independent `attributes` process; deterministic fixture inferencer; `VisualAttributeTrackOutcome`; final `VisualAttribute` rows; successful-completion supersession/default-selection semantics; lifecycle/publication integrity. This slice owns the persistence integrity represented by acceptance E1–E4, while D1–D8 remain its lifecycle acceptance set. |
| **S2c Real Model Packs** | Person/vehicle Model Packs, Development execution, provenance and labelled-corpus engineering evaluation. No search ownership. |
| **S3 Persistence/search integration** | Search-facing integration over the already-persisted S2b facts: cursor v4, canonical predicates/fingerprints, query/index work and measured PostgreSQL plans. This slice owns E5–E8. It must not redesign S2b fact identity, publication or supersession semantics. |

Therefore the stale S3 summary **“final outcome rows, supersession, v4 cursor, canonical predicates, measured PostgreSQL plans | Acceptance E1–E8 PASS”** is superseded by the table above.

## 4. S2a closure authority

`docs/reviews/2026-09-28-stage2-s2a-closure.md` is a closure narrative, not an acceptance authority. PASS/OPEN state and retained evidence belong only in `docs/reviews/2026-09-23-visual-attributes-acceptance.md`.

In particular:

- C3 must never be read as evidence that a second worker role is already startable;
- S2a does not claim an `attributes` executable/launcher;
- S2a does not claim a real attribute Model Pack;
- S2a does not promote RTMDet to Production qualification;
- S2a does not promote CUDA to Production qualification;
- S2a does not close the deferred family-wide Production qualification policy.

## 5. S2b/S3 acceptance mapping

S2b implementation evidence may satisfy the integrity/persistence requirements E1–E4 only when the authoritative acceptance register records retained evidence for those rows. The S2b plan itself must not mark them PASS.

S3 remains responsible for E5–E8 and the search/query performance evidence associated with them.

No row becomes PASS merely because a plan assigns ownership to a slice.

## 6. No scope expansion

This reconciliation changes documentation ownership only. It introduces no code, schema, dependency, runtime, Model Pack, qualification promotion, search implementation or UI implementation.

The S2b implementation remains fixture-only. Real learned inference remains S2c.

## 7. Consolidation rule

When either older summary document is next edited for substantive Stage-2 work, its stale status/slice table should be folded forward from this amendment and this amendment may then be retired. Until then, this file is the explicit normative bridge preventing contradictory planning guidance.
