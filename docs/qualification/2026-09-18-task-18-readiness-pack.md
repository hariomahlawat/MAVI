# Task 18 Qualification Readiness Pack

**Date:** 2026-09-18  
**Planning baseline:** `feature/task-10-rtmdet-bytetrack@557d5ccc356ae39766d95eec93ce0fdf49fdef31`  
**Planning PR:** #45  
**Purpose:** determine whether MAVI may begin **authoritative** Phase-1 production qualification.

## Decision

**Overall readiness: BLOCKED — authoritative production qualification must not start yet.**

The repository is technically ready to perform readiness preparation and rehearsal, but several mandatory release-governance inputs are intentionally unresolved. Starting final CCTV, profile CUDA qualification, or release-promotion evidence now would create evidence against an unfrozen policy/candidate and would therefore be wasteful or invalid.

This is not a product-failure result. It is a controlled readiness result.

---

## Executive READY / BLOCKED matrix

| Area | Status | Evidence / current state | Required action |
|---|---|---|---|
| Current planning baseline | **READY** | Integration baseline is `557d5ccc...`; Task-18 plan is re-baselined in PR #45 | Keep execution branches based on accepted current integration |
| Historical Task-18 branch | **READY / SUPERSEDED** | PR #39 closed without merge | None |
| Runtime/Model component architecture | **READY** | Runtime Pack / Model Pack / Application Overlay split is merged and cold-reviewed | Preserve component identities during candidate freeze |
| Windows CPU Runtime Pack identity | **READY** | `mavi-runtime-v2-5d6229da58554bc951ddc8bd719574c1b33109a7916afdf717339d8847e39e61` | Re-confirm on frozen production candidate |
| Linux CPU Runtime Pack identity | **READY** | `mavi-runtime-v2-bd94fded938183dce8dc50390d48e97d913d9dad9dc98b528a962ad32314ff61` | Re-confirm on frozen production candidate |
| Model Pack identity | **READY** | `mavi-model-v1-2abf67800cec8a9c63d735bf50e44ac695e8b8ccf01397e2cfd884305a5638b4` | Re-confirm on frozen production candidate |
| Windows CPU functional subsystem evidence | **READY — inherited evidence** | PR #44 completed real 1080p RTMDet/ByteTrack processing and job-level recovery | Do not repeat Development run solely for chronology |
| Linux CPU hosted runtime evidence | **READY — hosted only** | Qualification metadata marks Linux CPU passed | Still requires intended Production/offline topology evidence if Linux is in final topology |
| Deployment-profile model | **READY** | ADR-008 defines Development Auto/CUDA/CPU policy and Production profiles P1 Windows GPU, P2 Windows+Linux GPU, P3 Windows CPU | Qualify only the profile(s) claimed as supported; never inherit qualification across profiles |
| Development GPU policy | **READY** | Windows Development may use `Auto`, `CUDA` or `CPU`; GPU should be used when compatible/available | Implement/verify explicit device selection and visible provenance; no silent fallback |
| GPU scope | **READY — PROFILE-SPECIFIC** | GPU is required only for Production profiles that claim GPU support; P1 uses Windows CUDA, P2 uses Linux CUDA | Produce CUDA evidence for each GPU profile actually claimed as supported |
| CUDA/GPU evidence | **BLOCKED** | Windows CUDA and Linux CUDA remain unqualified | Qualify Windows CUDA for P1 and Linux CUDA for P2 independently; neither blocks an unrelated profile unless that profile is claimed |
| Acceptance tooling/profile reconciliation | **BLOCKED** | Existing closure tooling still assumes four platform variants and final Linux-CUDA scenarios | Refactor/review tooling so evidence requirements are derived from the Production profile(s) claimed as supported |
| Model release qualification | **BLOCKED** | Model manifest remains `verificationStatus=unverified`; qualification `overallResult=pending` | Complete mandatory gates before promotion |
| Acceptance corpus | **BLOCKED** | `qualificationCorpusManifestSha256=null` | Freeze approved held-out corpus + manifest |
| Person threshold | **BLOCKED** | `classThresholds.Person=null` | Approve before final evaluation |
| Vehicle threshold | **BLOCKED** | `classThresholds.Vehicle=null` | Approve before final evaluation |
| Empty-scene threshold | **BLOCKED** | `maximumUnmatchedTracks=null` | Approve before final evaluation |
| Performance thresholds | **BLOCKED / SCOPE DECISION** | `performanceThresholds=null` | Approve thresholds or explicitly remove performance as Phase-1 release gate |
| Production prerequisite policy | **BLOCKED** | `approvalStatus=pending`; production versions are not frozen | Observe intended topology, approve exact supported versions |
| Supported-update prior artifact | **BLOCKED / SCOPE DECISION** | Prior source is named but `applicationManifestSha256=null` | Freeze exact prior artifact or formally defer update proof |
| Application release artifact | **BLOCKED** | No Task-18 frozen application artifact/manifest yet | Build only after qualification candidate is frozen |
| Offline Binary Kit identity | **BLOCKED** | Kit is intentionally external to Git; no Task-18 candidate manifest has been captured | Select retained kit and record manifest SHA-256 |
| Production setup bundle | **BLOCKED** | No Task-18 final bundle identity yet | Assemble from frozen app + verified binary kit after readiness inputs are approved |
| Production deployment profiles | **READY** | ADR-008 approves P1 single-host Windows GPU, P2 split Windows+Linux GPU, and P3 single-host Windows CPU | Select the first Task-18 profile(s) to qualify, then freeze profile-specific prerequisites/host identities |
| Clean disconnected Production install | **NOT STARTED** | Task-18 evidence not yet run | Execute only after readiness becomes READY |
| Production E2E | **NOT STARTED** | Task-18 evidence not yet run | Execute after clean install |
| Failure/reprocess | **NOT STARTED** | Task-18 evidence not yet run | Execute after formal E2E environment is qualified |
| Backup + clean-target restore | **NOT STARTED** | Task-18 evidence not yet run | Execute after successful formal production case |
| Final release promotion | **BLOCKED BY DESIGN** | Mandatory evidence chain incomplete | Do not promote manually |

---

## Frozen component facts already available

### Component requirements

The current application requirements select:

- Runtime profile: `mmdetection-phase1-v1`
- Windows CPU Runtime Pack: `mavi-runtime-v2-5d6229da58554bc951ddc8bd719574c1b33109a7916afdf717339d8847e39e61`
- Linux CPU Runtime Pack: `mavi-runtime-v2-bd94fded938183dce8dc50390d48e97d913d9dad9dc98b528a962ad32314ff61`
- Model Pack: `mavi-model-v1-2abf67800cec8a9c63d735bf50e44ac695e8b8ccf01397e2cfd884305a5638b4`
- Model checkpoint SHA-256: `229f527ca88498e8894a778a62a878a322b4a3ea2cae09ea537d34b7e907792b`
- Resolved config SHA-256: `377d9f57abf6a73a6c308f765b70fc571715448c62998819d609d2eebc7c5ee3`

Windows CPU runtime binds:
- third-party lock SHA-256 `66517c8ff1de06d30093b497cbc1eddbeb6f0a879c920849b8a2f91eafaebb33`
- runtime requirements SHA-256 `555ecfd8e8ef433e83375a54b05e4e6249fa242425c1b19952ffcb2e1bc446f4`
- native ABI `win_amd64-msvc-14.44-sdk-10.0.26100.0`

Linux CPU runtime binds:
- third-party lock SHA-256 `b1d0970df273538feceff678bb27a3722140c7c3c7317aadfbf83a88103b3a6b`
- runtime requirements SHA-256 `991d07a5d2b6d04aae387c1d5c029c3f3407f460447f1a1477adb7cf410f0094`
- native ABI `glibc-2.39-libstdcxx-GLIBCXX_3.4.33-gcc-14.2.0-linux_x86_64`

These are valid current component-selection facts. They are **not yet the final Task-18 release-candidate freeze**, because application artifact, Offline Binary Kit and policy/topology identities remain unresolved.

---

## Existing qualification state

Current model qualification records:

- Windows x86_64 CPU: **passed**
- Linux x86_64 CPU: **passed**
- Windows x86_64 CUDA: **pending**
- Linux x86_64 CUDA: **pending**
- Windows offline install: **pending**
- Linux offline install: **pending**
- CCTV quality baseline: **pending**
- Linux NVIDIA recovery/performance: **pending**
- Overall result: **pending**

Current runtime profile status is `partial`, consistent with CPU-hosted qualification and pending CUDA hardware qualification.

The PR #44 Development functional run adds strong Windows CPU execution evidence beyond hosted CI, but it does not change the formal pending release gates above.

---

## Current policy blockers

### Acceptance profile

The acceptance profile is deliberately incomplete and therefore cannot yet support authoritative quality/release decisions:

- corpus manifest hash: unset;
- Person threshold: unset;
- Vehicle threshold: unset;
- empty-scene threshold: unset;
- performance thresholds: unset.

**Control:** no final held-out corpus evaluation shall occur until these values are reviewed and frozen.

### Production prerequisites

The production prerequisite policy remains `pending`. The following exact values are unresolved:

- Windows product/version/build;
- IIS version;
- .NET runtime version;
- PostgreSQL version;
- pgvector version;
- worker distribution/release/Python;
- NVIDIA driver/CUDA runtime if GPU remains required.

The dependency catalog provides packaging baselines (for example PostgreSQL 18, FFmpeg 9.0.1 and ASP.NET Hosting Bundle baseline 10.0.11), but those packaging baselines are **not a substitute** for approving the exact acceptance topology observations.

### Supported update

The policy currently names prior source commit `fef04c18c80d83730a448136e325ce1022166758`, but its retained application manifest hash is null.

A supported-update qualification is therefore blocked until an exact prior artifact is retained and cryptographically identified, unless a reviewed scope change defers this requirement.

---

## Exact-head CI status for the planning PR

PR #45 is documentation-only. On its current planning head, the path-triggered checks observed at readiness-pack preparation time are:

- MAVI Quality Gate #1598 — **passed**
- Task 17 Acceptance Validation #742 — **passed**

The heavy Runtime/Model workflows are not treated as newly qualified by this documentation-only planning PR merely because their paths did not execute. The executable baseline remains the already-qualified integration content from PR #44. Before authoritative Task-18 evidence starts, the final executable qualification candidate must establish the complete required exact-head gate set appropriate to that candidate.

---

## Readiness actions — controlled order

### R1 — approve Development and Production deployment profiles — COMPLETE

**Status: READY.** ADR-008 now defines:
- Development reference topology: one Windows laptop/workstation;
- Development device policy: `Auto`, `CUDA`, or `CPU`;
- P1: single-host Windows GPU Production;
- P2: split-host Windows operational/data + Linux NVIDIA worker;
- P3: single-host Windows CPU Production;
- controlled disconnected Production boundary with explicit runtime/model identities.

A second machine is not required for normal development. See `docs/decisions/ADR-008-phase1-production-topology.md` and `docs/architecture/phase1-production-topology.md`.

### R2 — resolve GPU scope — COMPLETE

**Status: READY — PROFILE-SPECIFIC.** GPU support is not a universal Phase-1 prerequisite. It is mandatory for any Production profile advertised as GPU-capable. Windows CUDA qualifies P1; Linux CUDA qualifies P2; P3 is CPU-only. No profile inherits qualification from another, and no CUDA path may silently fall back to CPU.

### R3 — freeze acceptance policy before final testing

Approve:
- held-out corpus;
- Person threshold;
- Vehicle threshold;
- empty-scene threshold;
- performance thresholds or an explicit performance-gate deferral.

### R4 — freeze production prerequisite versions

Use the intended acceptance hosts and the existing prerequisite collector to obtain observations. Review them, then populate and approve the canonical policy. Do not fabricate version values from developer machines.

### R5 — resolve update-proof scope

Retain the exact prior application artifact and manifest, or approve a formal deferral.

### R6 — freeze the executable candidate

Only after R1–R5:
- create/freeze application artifact;
- capture application artifact manifest SHA-256;
- select/capture exact Offline Binary Kit manifest SHA-256;
- re-confirm component requirements, Runtime Pack ID and Model Pack ID;
- assemble candidate Production setup media;
- establish fresh exact-head CI;
- generate the final machine-readable candidate-freeze record.

### R7 — run rehearsal

Run one non-authoritative Production rehearsal.

### R8 — begin authoritative evidence

Only when all mandatory readiness rows are READY.

---

## Evidence custody structure

Use an external controlled root; do not commit private CCTV data, credentials, raw operational logs or large evidence blobs to Git.

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

The Git repository should retain schemas, policy, runbooks, hashes and compact qualification records—not sensitive/raw evidence payloads.

---

## Authorization gate

**Authoritative Task-18 qualification is NOT AUTHORIZED by this readiness pack.**

It becomes authorized only when the machine-readable readiness record has no mandatory `BLOCKED` item and the reviewed candidate freeze identifies the exact application, Runtime Pack, Model Pack, Offline Binary Kit, topology and acceptance-policy inputs.

R1 and R2 are now resolved. Before authoritative qualification, the acceptance toolchain must also be reconciled with ADR-008 because it still contains legacy four-variant/Linux-CUDA-centric closure assumptions. The next professional actions are: select the first Production profile(s) to qualify, complete the profile-tooling reconciliation, then resolve **R3–R5** — acceptance policy, exact profile-specific Production prerequisites, and supported-update artifact/scope.
