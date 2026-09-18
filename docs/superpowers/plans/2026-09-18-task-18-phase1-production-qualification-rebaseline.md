# Task 18 — Phase-1 Production Qualification and Closure Re-baseline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or an equivalent reviewed execution workflow. Do not begin authoritative qualification until the Readiness Pack is approved. Steps use checkbox syntax for tracking.

**Status:** Proposed authoritative Task-18 execution plan replacing PR #39.

**Goal:** Qualify and close MAVI Phase 1 on the exact current deployment/runtime architecture using production-representative offline evidence, without re-running already-proven Development evidence unnecessarily or making unevidenced GPU/release claims.

**Architecture:** Freeze the Application / Release Overlay, Runtime Binary Pack, Model Pack and Offline Binary Kit as independently identified components, then qualify the actual intended Production topology through staged readiness, clean installation, production-mode E2E, recovery, lifecycle and evidence-closure gates. Existing PR #44 CPU functional evidence is retained as prior subsystem evidence but does not replace final Production acceptance.

**Planning baseline:** `feature/task-10-rtmdet-bytetrack@557d5ccc356ae39766d95eec93ce0fdf49fdef31`

**Cold review:** `docs/reviews/2026-09-18-task-18-rebaseline-cold-review.md`

**Readiness Pack:** `docs/qualification/2026-09-18-task-18-readiness-pack.md`  
**Machine-readable readiness:** `docs/qualification/task18-readiness-v1.json`  
**Current readiness:** **BLOCKED — authoritative qualification not yet authorized.**

---

## Global constraints

- Task 18 is an operational qualification/closure task, not a new analytical-feature task.
- No final evidence may be created against a candidate whose behavior-bearing identity is still changing.
- All release claims are limited to the hardware/runtime actually qualified.
- CPU evidence never implies CUDA/GPU qualification.
- No online package/model/runtime resolution is permitted in disconnected qualification.
- Runtime Pack, Model Pack and Application Overlay identities are recorded independently.
- Private CCTV media, credentials and operational secrets remain outside Git.
- Thresholds and corpus identities must be frozen before authoritative quality evaluation.
- Release metadata is promoted only through approved tooling after every mandatory gate passes.
- A failed mandatory gate produces `NOT ACCEPTED` or `QUALIFICATION INCOMPLETE`; it is never converted to pass by manual metadata editing.

---

# Phase 0 — Planning and repository re-baseline

## Task 0.1 — Supersede stale Task-18 planning

- [x] Use current integration head as the sole source branch for new Task-18 execution.
- [x] Retain PR #39 and its three planning commits as historical evidence only.
- [x] Close PR #39 as superseded; it was closed without merge on 18 Sep 2026 and points to PR #45.
- [x] Update the Phase-1 roadmap so Task 17 is complete and Task 18 is active.

**Exit criterion:** there is one unambiguous Task-18 plan based on current integration history.

## Task 0.2 — Re-establish deterministic repository baseline

At the chosen final planning/execution head:

- [ ] MAVI Quality Gate green.
- [ ] Task 10 Runtime Qualification green.
- [ ] Task 12 Offline Runtime Pack green.
- [ ] Task 17 Acceptance Validation green.
- [ ] Vision Runtime Component Boundary green.
- [ ] Vision Model Pack green.
- [ ] no unresolved material review thread on the baseline.
- [ ] repository verification green.

**Rule:** moving the executable head invalidates this baseline and requires the appropriate exact-head gates again.

---

# Phase 1 — Task-18 Qualification Readiness Pack

This is the immediate next execution artifact. No authoritative qualification begins before it is complete.

## Task 1.1 — Freeze candidate component identities

Create a machine-readable readiness record containing at least:

- [ ] source/integration commit;
- [ ] application build/artifact identity and SHA-256;
- [ ] component-requirements file/hash;
- [ ] Runtime Pack ID + manifest hash;
- [ ] Model Pack ID + manifest hash;
- [ ] Offline Binary Kit manifest/hash;
- [ ] Production setup bundle identity, if already assembled;
- [ ] database migration identity/state;
- [ ] acceptance-profile hash;
- [ ] production-prerequisite-policy hash;
- [ ] supported-update-policy hash;
- [ ] model qualification metadata hash.

**Exit criterion:** every behavior-bearing component used by the candidate is uniquely identifiable.

## Task 1.2 — Freeze the intended Production topology — COMPLETE

ADR-008 now controls Phase-1 Production topology:

- [x] Host A Windows operational role: IIS / ASP.NET Core / React + application-local FFmpeg.
- [x] Host A data role: MAVI-owned PostgreSQL 18 + pgvector, logically distinct but canonically co-located for Phase 1.
- [x] Host B Vision role: separate Linux x86_64 NVIDIA worker.
- [x] Production Vision execution target: CUDA; no silent CPU fallback in final acceptance.
- [x] CPU runtime evidence retained as subsystem/variant evidence, not final Production-worker proof.
- [x] managed-media and accepted-evidence stores remain MAVI-owned and separately identified.
- [x] controlled disconnected LAN boundary; no runtime Internet dependency.
- [x] backup/restore must restore to a distinct clean target/topology.

Exact OS/IIS/.NET/PostgreSQL/pgvector/Linux/NVIDIA/CUDA versions remain Task 1.4 prerequisite-freeze work, not topology design.

Authority: `docs/decisions/ADR-008-phase1-production-topology.md`.

## Task 1.3 — Approve acceptance inputs before observing final outcomes

Complete `config/acceptance/phase1-acceptance-v1.json` through reviewed policy, not ad-hoc editing during qualification:

- [ ] qualification corpus manifest SHA-256;
- [ ] Person acceptance threshold;
- [ ] Vehicle acceptance threshold;
- [ ] empty-scene unmatched-track threshold;
- [ ] performance thresholds, if performance is a Phase-1 release gate;
- [ ] exact matching rules retained/frozen.

The corpus/ground truth and thresholds are frozen together before authoritative evaluation.

## Task 1.4 — Approve production prerequisites

Complete and approve `phase1-production-prerequisites-v1.json` for the actual topology:

- [ ] Windows product/version/build;
- [ ] IIS version;
- [ ] .NET runtime version;
- [ ] PostgreSQL version;
- [ ] pgvector version;
- [ ] worker OS/Python identity;
- [ ] NVIDIA driver/CUDA runtime if GPU remains required.

**Exit criterion:** policy state is no longer `pending`.

## Task 1.5 — Resolve supported-update evidence policy

Choose and record one reviewed path:

**Path A — update proof remains mandatory**
- [ ] retain exact approved prior application artifact;
- [ ] populate prior application manifest SHA-256;
- [ ] prove its accepted starting state;
- [ ] freeze migration policy.

**Path B — update proof is removed from Phase-1 closure**
- [ ] approve a scope/requirements change;
- [ ] update acceptance tooling/docs consistently;
- [ ] record update qualification as deferred.

No “best available prior build” may be invented during acceptance.

## Task 1.6 — Produce Readiness Pack assessment

- [x] Human-readable readiness report created.
- [x] Machine-readable readiness record created.
- [x] READY / BLOCKED assessment completed against current repository state.
- [x] Authoritative qualification explicitly withheld while mandatory blockers remain.

Current result: **BLOCKED**. Production topology and GPU scope are now resolved by ADR-008. Remaining mandatory blockers are CUDA qualification evidence, acceptance corpus/thresholds, Production prerequisite approval, supported-update artifact/scope, final application artifact, Offline Binary Kit identity and final candidate freeze.

**Readiness exit criterion:** all mandatory items are READY. A BLOCKED mandatory item prevents authoritative evidence capture.

---

# Phase 2 — Non-authoritative Production rehearsal

Use the exact intended topology and candidate components, but mark all outputs **REHEARSAL / NON-AUTHORITATIVE**.

Validate:

- [ ] offline media transfer;
- [ ] one-click Production setup;
- [ ] PostgreSQL/pgvector startup;
- [ ] IIS/API/UI startup;
- [ ] Runtime Pack installation/reuse;
- [ ] Model Pack installation/reuse;
- [ ] worker READY;
- [ ] permissions/storage roots;
- [ ] logging locations;
- [ ] evidence collection paths;
- [ ] backup tooling;
- [ ] outbound network isolation.

**Stopping rule:** any functional defect is fixed through normal branch/PR review. After such a fix, freeze a new candidate and restart affected readiness/evidence stages.

---

# Phase 3 — Clean disconnected Production installation qualification

This is new authoritative evidence; PR #44 Development-mode functional evidence does not replace it.

On a clean/reprovisioned target:

- [ ] use only approved offline media / Offline Binary Kit;
- [ ] execute Production setup;
- [ ] verify exact application build;
- [ ] verify PostgreSQL/pgvector identity;
- [ ] verify Runtime Pack ID and live closure;
- [ ] verify Model Pack ID and live artifact integrity;
- [ ] verify component compatibility;
- [ ] verify IIS/API/UI health;
- [ ] verify worker READY;
- [ ] prove no first-run Internet dependency;
- [ ] retain installation/setup logs and manifests.

**Exit criterion:** clean offline Production installation is reproducible and hash-bound to the frozen candidate.

---

# Phase 4 — Exact production-mode functional acceptance

Execute a fresh production-mode scenario against the frozen candidate.

## Task 4.1 — Formal target-containing E2E

Prove:

`Camera/source → managed import → queue → qualified worker → completed run → Track search → Track detail → representative evidence read`

Require:

- [ ] exact imported source hash/ETag;
- [ ] exact ProcessingRun identity;
- [ ] worker/runtime/model provenance;
- [ ] at least one accepted reviewable Track for target-containing media;
- [ ] representative evidence hash/read verification;
- [ ] final persisted `Completed` / `Processed` state;
- [ ] no silent CPU/GPU fallback relative to the declared execution target.

## Task 4.2 — Empty-scene diagnostic

Using frozen reviewed empty-scene media:

- [ ] run an independent processing event;
- [ ] evaluate against the approved empty-scene threshold;
- [ ] retain authoritative zero/allowed-unmatched result evidence;
- [ ] ensure it cannot be substituted for the formal target-containing E2E.

## Task 4.3 — Prior evidence treatment

Record PR #44 as inherited subsystem evidence for:
- Runtime/Model reuse;
- Development environment verification;
- RTMDet/ByteTrack execution;
- worker retry/recovery.

Do not count it twice as final Production E2E.

---

# Phase 5 — Failure, recovery and reprocess qualification

Execute a controlled production-topology failure using approved fault-injection mechanics.

Prove:

- [ ] first attempt failure is retained truthfully;
- [ ] source media remains unchanged;
- [ ] stale/failed accepted evidence cannot become authoritative;
- [ ] reprocess creates a distinct ProcessingRun/attempt identity;
- [ ] recovered/reprocessed run completes successfully;
- [ ] final Track/evidence state belongs only to the accepted run;
- [ ] job-level retry semantics are recorded accurately.

Do not claim frame-level resume unless separately implemented and tested.

---

# Phase 6 — Formal quality and performance qualification

## Task 6.1 — Person/Vehicle held-out quality

Against the frozen corpus and thresholds:

- [ ] independently recompute Person metrics;
- [ ] independently recompute Vehicle metrics;
- [ ] preserve exact corpus and ground-truth hashes;
- [ ] reject post-result threshold/annotation tuning;
- [ ] retain per-case and aggregate evidence.

## Task 6.2 — Performance/soak

Only if performance thresholds are approved as Phase-1 gates:

- [ ] measure throughput;
- [ ] measure approved latency metric(s);
- [ ] execute soak duration;
- [ ] measure memory growth;
- [ ] record watchdog/recovery behavior;
- [ ] compare observations against pre-approved thresholds.

If thresholds remain undefined, status is `QUALIFICATION INCOMPLETE`, not pass.

---

# Phase 7 — CUDA/GPU decision and qualification

## Task 7.1 — Resolve release scope

Before any release claim, record explicitly:

### If GPU is required for Phase 1
- [ ] qualify the required OS/GPU topology;
- [ ] freeze NVIDIA driver/CUDA/Python/runtime identities;
- [ ] prove actual CUDA device execution;
- [ ] prove no silent CPU fallback;
- [ ] run required production smoke/E2E/performance evidence on that topology.

### If GPU is deferred
- [ ] approve a Phase-1 scope/ADR change;
- [ ] remove GPU claims from release metadata and operator docs;
- [ ] retain GPU work as a future qualification task.

**Rule:** absence of GPU hardware is not itself an approval to change scope.

---

# Phase 8 — Application lifecycle qualification

## Task 8.1 — Fresh install

Already proven in Phase 3; bind that exact evidence into closure.

## Task 8.2 — Supported offline update

If retained as a mandatory gate:

- [ ] install exact approved prior artifact;
- [ ] capture authoritative pre-update state;
- [ ] update offline to frozen target;
- [ ] apply controlled migrations;
- [ ] verify exact target build;
- [ ] verify authoritative post-update state;
- [ ] verify retained data/product operation;
- [ ] retain prior/target artifact manifests.

---

# Phase 9 — Backup and clean-target restore

After a successful formal production case exists:

- [ ] capture source topology identity;
- [ ] back up PostgreSQL;
- [ ] back up managed source media;
- [ ] back up accepted evidence;
- [ ] build immutable backup manifests;
- [ ] restore to a distinct clean database/storage target;
- [ ] start against restored topology;
- [ ] verify restored topology identity;
- [ ] run authoritative-state verification;
- [ ] re-read representative source/evidence;
- [ ] verify ProcessingRun/Track/Artifact/provenance relationships.

A database-only backup or restore check against the original live deployment cannot pass.

---

# Phase 10 — Evidence custody and independent assessment

Maintain an external evidence root such as:

```text
phase1-qualification/
  00-readiness/
  01-rehearsal/
  02-clean-install/
  03-production-e2e/
  04-failure-reprocess/
  05-quality-performance/
  06-gpu-if-required/
  07-update/
  08-backup-restore/
  09-promotion/
  10-final-closure/
```

Every retained evidence object records:
- deterministic filename;
- SHA-256;
- candidate/source identity;
- component IDs where applicable;
- host/topology role identity;
- execution/context identity;
- capture timestamp where required.

Create a final evidence manifest that re-hashes every retained object.

Run the canonical independent assessor against the underlying evidence; do not trust only an aggregate `passed` field.

---

# Phase 11 — Release promotion and closure

Promotion occurs only after all mandatory evidence is complete.

- [ ] run canonical release-promotion tooling;
- [ ] prohibit hand-edited `verified` metadata;
- [ ] rebuild/select exact Production release artifacts from the frozen candidate;
- [ ] run any required post-promotion disconnected smoke;
- [ ] assemble final production-acceptance evidence;
- [ ] independently re-open and validate all mandatory evidence;
- [ ] issue one final status:
  - `ACCEPTED`;
  - `NOT ACCEPTED`;
  - `QUALIFICATION INCOMPLETE`.

## Closure rule

Phase 1 is closed only when the final status is `ACCEPTED` and every mandatory claim in operator/release documentation is backed by evidence from the actual qualified topology.

---

# Evidence invalidation matrix

| Change | Exact-head CI | Re-run production install/E2E? | Rebuild Runtime Pack? | Rebuild Model Pack? |
|---|---|---|---|---|
| Documentation-only wording | Yes as repository gate | No, if interpretation/execution material unchanged and recorded | No | No |
| First-party Vision/application behavior | Yes | Yes, affected stages | Usually no | No |
| Runtime dependency/lock/Python/ABI | Yes | Yes | Yes | No |
| Model checkpoint/resolved config | Yes | Yes | No | Yes |
| Acceptance threshold/corpus | Yes | Yes, affected quality/closure | No | No |
| Production prerequisite policy | Yes | Yes, affected topology/install stages | Possibly | Possibly |
| Offline setup behavior | Yes | Yes, install/lifecycle stages | Depends on material input | Depends on material input |

---

# Immediate next action

Do **not** start with CUDA runs, CCTV metrics or final release promotion.

The immediate next action after this plan is accepted is:

> **Resolve readiness actions R3–R5 in `docs/qualification/2026-09-18-task-18-readiness-pack.md`: freeze acceptance policy, approve exact Production prerequisites from the approved topology, and resolve supported-update scope/artifact.**

Only after R1–R5 are resolved should the final application artifact, Offline Binary Kit and Production setup bundle be frozen and authoritative qualification begin. This sequencing prevents expensive runs against an unfrozen policy, topology or artifact identity.
