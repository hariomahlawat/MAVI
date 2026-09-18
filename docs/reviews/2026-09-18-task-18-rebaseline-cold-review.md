# Task 18 Re-baseline — Independent Cold Review

**Date:** 2026-09-18  
**Repository:** `hariomahlawat/MAVI`  
**Current integration branch:** `feature/task-10-rtmdet-bytetrack`  
**Current integration head:** `557d5ccc356ae39766d95eec93ce0fdf49fdef31`  
**Historical Task-18 PR:** #39, branch `feature/task-18-phase1-production-qualification`  
**Historical Task-18 head:** `9c3cb87e141e2a7016db91d6f2726354a7f1dad7`

## Review posture

This review treats the existing Task-18 plan as an external planning artifact and re-evaluates it against the present repository rather than assuming its original premises remain valid. The objective is not to preserve prior wording; it is to identify what still constitutes a valid Phase-1 production-qualification contract after the subsequent runtime, deployment and offline-packaging work.

No product implementation is changed by this review.

---

## Executive conclusion

The **intent** of the historical Task-18 plan remains valid: Task 18 should be an evidence-producing production qualification and Phase-1 closure activity, not a new analytical-feature task.

The historical plan is **not execution-ready** on the current repository.

PR #39 was created from integration commit `57f9efd5090f01486ff8a197c6a4aaeda285d065`. The current integration branch is now `557d5ccc356ae39766d95eec93ce0fdf49fdef31`. Direct comparison shows the current integration branch is **490 commits ahead and 3 commits behind the old Task-18 planning branch**. The intervening changes are not cosmetic: they materially changed setup, offline packaging, runtime ownership, model ownership, component identity, worker observability, CI qualification and functional evidence.

The old Task-18 branch must therefore be treated as historical planning input and superseded by a new plan based on the current integration head.

---

## Material changes since the historical Task-18 baseline

The current baseline now includes capabilities that the old plan either did not know about or represented differently:

1. **One-click offline Development and Production setup**
   - repository-controlled setup contracts;
   - application-local FFmpeg;
   - isolated PostgreSQL + pgvector ownership;
   - offline binary catalog and dependency policy;
   - deterministic Offline Binary Kit.

2. **Runtime / Model / Application decoupling**
   - third-party-only Runtime Binary Pack;
   - independent immutable Model Pack;
   - first-party Application / Release Overlay;
   - content-derived component identities;
   - content-addressed reusable offline component store.

3. **Stronger installed-state integrity**
   - live CPython identity verification;
   - installed third-party closure revalidation;
   - `pip check`;
   - installed Model Pack hash/path/undeclared-file verification.

4. **Additional exact-head CI boundaries**
   - MAVI Quality Gate;
   - Task 10 Runtime Qualification;
   - Task 12 Offline Runtime Pack;
   - Task 17 Acceptance Validation;
   - Vision Runtime Component Boundary;
   - Vision Model Pack.

5. **Worker observability and recovery hardening**
   - attempt-local progress;
   - heartbeat progress;
   - watchdog incident evidence;
   - worker-loss retry/recovery behavior.

6. **Real Windows CPU functional evidence**
   - qualified Runtime and Model component reuse;
   - environment verification;
   - RTMDet/ByteTrack worker readiness;
   - real 1920x1080 video processing;
   - worker interruption and automatic job-level retry;
   - final persisted `Completed` / `Processed` state.

These changes materially alter what Task 18 should prove and what it should avoid re-proving.

---

## Cold-review findings

### T18-CR-01 — historical execution baseline is stale

**Severity:** Blocking for execution.  
**Disposition:** Re-baseline required.

The historical Task-18 plan freezes `57f9efd...` as its initial software baseline. That SHA predates the deployment/offline/runtime changes listed above. Executing qualification against that plan would either omit current architecture or require ad-hoc interpretation while evidence is being produced.

**Required correction:** Task 18 must branch and plan from current integration head `557d5ccc...` or a later explicitly accepted successor.

---

### T18-CR-02 — historical packaging model no longer matches the runtime ownership model

**Severity:** Blocking for evidence identity.  
**Disposition:** Replace with component-aware freeze.

The historical plan is heavily centered on monolithic candidate/production runtime bundles and platform locks. The current architecture separates:
- Runtime Binary Pack;
- Model Pack;
- Application / Release Overlay;
- Offline Binary Kit/component store.

A final qualification record that does not bind these identities independently would fail to prove which heavy components and which first-party application were actually exercised.

**Required correction:** the Task-18 freeze record must bind the exact application head/artifact, Runtime Pack ID, Model Pack ID, component-requirements file/hash, Offline Binary Kit manifest/hash, and any production setup bundle identity.

---

### T18-CR-03 — prior Windows CPU functional evidence is valuable but is not final production acceptance

**Severity:** Important scope correction.  
**Disposition:** Preserve as inherited engineering evidence; do not count as final production-topology proof.

PR #44 produced strong Windows CPU functional evidence. Repeating that exact Development-mode 2m28s test merely to satisfy chronology would waste time and CPU capacity.

However, the evidence was not a clean-machine Production setup qualification and was not the final Phase-1 production topology event.

**Required correction:** Task 18 should reference the PR #44 run as prior subsystem evidence and avoid an unnecessary duplicate Development test. It must still execute a fresh production-mode smoke/E2E against the exact frozen Task-18 candidate.

---

### T18-CR-04 — current acceptance policy is intentionally incomplete

**Severity:** Blocking for formal acceptance.  
**Disposition:** Governance inputs must be frozen before authoritative qualification.

The current `config/acceptance/phase1-acceptance-v1.json` contains unresolved acceptance inputs:
- `qualificationCorpusManifestSha256 = null`;
- Person threshold = `null`;
- Vehicle threshold = `null`;
- empty-scene maximum unmatched Tracks = `null`;
- performance thresholds = `null`.

This is correct for an unapproved baseline, but it means formal CCTV/performance acceptance cannot yet produce a meaningful release decision.

**Required correction:** thresholds/corpus identities must be approved before authoritative evidence is captured. They must not be selected after observing final qualification results.

---

### T18-CR-05 — production prerequisite policy is still pending

**Severity:** Blocking for production acceptance.  
**Disposition:** Must be approved and frozen.

`config/acceptance/phase1-production-prerequisites-v1.json` currently has `approvalStatus = pending` and null Windows/IIS/.NET, PostgreSQL/pgvector, Linux, NVIDIA and CUDA version fields.

The historical plan correctly treats prerequisite identity as mandatory evidence, but current execution cannot pass that gate until the actual supported production baseline is decided.

**Required correction:** approve exact production prerequisite versions from the real intended deployment topology before final qualification.

---

### T18-CR-06 — supported-update policy is not yet evidence-complete

**Severity:** Blocking only for the update/closure gate.  
**Disposition:** Complete before supported-update qualification.

The current supported-update policy identifies a prior source commit, but `applicationManifestSha256` remains null. A supported-update test without a cryptographically retained prior artifact would be a scenario demonstration, not a reproducible release qualification.

**Required correction:** freeze the exact supported prior application artifact/manifest or explicitly remove supported-update proof from Phase-1 closure through a reviewed scope decision. Do not improvise a prior release during the test.

---

### T18-CR-07 — CUDA/GPU qualification status must not be inferred

**Severity:** Blocking for any GPU claim.  
**Disposition:** Explicit scope decision required.

The old Task-18 plan made Windows/Linux CUDA evidence mandatory. The current repository and PR #44 documentation explicitly state that CUDA/GPU execution is **not qualified**.

The review must not silently demote an originally mandatory requirement merely because hardware evidence is unavailable, and it must not claim GPU support from CPU CI.

**Required correction:** before execution, record one of two legitimate states:
1. CUDA/GPU remains a Phase-1 acceptance requirement — Task 18 cannot close until the required GPU topology and evidence exist; or
2. Phase-1 product scope is formally revised to CPU-only through an explicit approved requirements/ADR change, with GPU deferred.

Until that decision exists, GPU-dependent closure remains pending.

---

### T18-CR-08 — final topology must be re-derived from current deployment architecture

**Severity:** High.  
**Disposition:** Re-freeze topology; do not copy the old diagram.

The old plan assumes a specific Windows operational plane + PostgreSQL plane + Linux NVIDIA worker topology. Subsequent work introduced owned PostgreSQL/pgvector setup, application-local native media tools, Windows CPU installation and reusable Vision components.

That does not automatically prove the old topology is wrong; it proves it is no longer safe to assume it is still normative.

**Required correction:** define the intended Phase-1 production topology from current architecture and deployment policy, then qualify that topology exactly.

---

### T18-CR-09 — exact-head rules need a material-equivalence provision for non-behavioral close-out commits

**Severity:** Medium.  
**Disposition:** Clarify evidence invalidation.

The project correctly uses exact-head CI. It also already learned that re-running long functional video qualification solely for documentation-only changes is unnecessary when executable/runtime/model material is unchanged.

**Required correction:** Task 18 must distinguish:
- exact-head CI/repository qualification;
- behavior-bearing evidence invalidation;
- documentation/record-only changes proven not to alter execution material.

This prevents both unsafe evidence reuse and needless expensive reruns.

---

### T18-CR-10 — PR #39 must not be merged after re-baselining

**Severity:** Repository hygiene.  
**Disposition:** Supersede.

PR #39 remains open and mergeable but carries the stale three-commit planning branch. Merging it after the new plan would reintroduce an obsolete baseline and contradictory roadmap text.

**Required correction:** mark PR #39 superseded and close it once the replacement planning PR exists.

---

## Evidence that should be preserved rather than repeated

The following are valid engineering inputs to Task 18 but are not substitutes for final production acceptance:

- PR #44 exact-head six-gate CI evidence;
- PR #44 Runtime Pack / Model Pack integrity cold review;
- source-only component reuse proof;
- Windows CPU Development environment verification;
- successful real RTMDet/ByteTrack video processing;
- job-level recovery after worker interruption;
- persisted `Completed` / `Processed` outcome.

Task 18 should reference these as prior subsystem evidence and concentrate new effort on the remaining production/release gates.

---

## Remaining authoritative closure blockers at re-baseline time

Before Phase-1 can legitimately reach a `release-verified` / accepted state, the revised plan must resolve or explicitly disposition:

1. final qualification candidate identity;
2. approved production topology;
3. acceptance corpus identity and class/empty-scene/performance thresholds;
4. approved production prerequisite versions;
5. supported prior-release artifact for update proof, if update proof remains mandatory;
6. clean disconnected Production installation proof;
7. exact production-mode functional E2E;
8. controlled failure/reprocess proof;
9. backup + clean-target restore proof;
10. final evidence manifest / independent assessment;
11. CUDA/GPU requirement decision and evidence if retained;
12. release promotion only after all mandatory gates are satisfied.

---

## Review verdict

The repository is ready to **plan and execute a re-baselined Task 18**, but not ready to start authoritative production qualification immediately.

The correct next artifact is a **Task-18 Qualification Readiness Pack** built from current integration head `557d5ccc...`. That pack must resolve the policy/topology/input uncertainties before evidence-producing qualification begins.

No product-code defect was identified by this planning review that requires immediate remediation before readiness work starts.
