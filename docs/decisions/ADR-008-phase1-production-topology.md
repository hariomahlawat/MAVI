# ADR-008: Development Device Policy and Phase-1 Production Deployment Profiles

**Status:** Accepted  
**Date:** 2026-09-18

## Context

MAVI must support practical development on a single engineer workstation while also supporting production deployments ranging from a single capable Windows machine to a split operational/accelerator topology.

Earlier Phase-1 planning implicitly treated a Windows operational host plus a separate Linux NVIDIA worker as the only final production topology. That is unnecessarily restrictive:

- the normal developer may have only one Windows laptop;
- that laptop may have an NVIDIA GPU and should be able to use it;
- the Windows Production host may itself have a suitable GPU;
- the Vision worker is already an independently deployable component behind a stable worker/API contract;
- Runtime Binary Packs and Model Packs are platform/device-specific and independently qualified.

The architecture should therefore define **logical planes and qualified deployment profiles**, not prescribe one physical host layout for all environments.

## Decision

MAVI uses one common application architecture with environment-specific **device policy** and **deployment profiles**.

### 1. Development reference topology

The supported Development reference topology is a **single Windows workstation/laptop** running:

- React UI;
- ASP.NET Core API;
- MAVI-owned PostgreSQL + pgvector;
- application-local FFmpeg;
- MAVI Vision worker;
- required Model Pack;
- the appropriate qualified Windows Runtime Binary Pack.

Development must support explicit device selection:

- **Auto** — prefer a compatible available GPU when a qualified Windows CUDA runtime exists; otherwise use CPU;
- **CUDA** — require GPU/CUDA and fail clearly if unavailable or incompatible;
- **CPU** — force CPU for reproducibility, debugging and regression comparison.

Any automatic device fallback must be visible in logs and processing provenance. Silent GPU-to-CPU fallback is prohibited.

A developer does **not** need a second machine or Linux host for routine feature development.

### 2. Production deployment profiles

Phase-1 Production supports profile-based qualification. A profile is supported only after its exact platform/device combination has passed the required qualification evidence.

#### P1 — Single-host Windows GPU

One supported Windows Production machine runs:

- IIS / ASP.NET Core API;
- React UI;
- application-local FFmpeg;
- MAVI-owned PostgreSQL + pgvector;
- MAVI Vision worker;
- qualified Windows CUDA Runtime Binary Pack;
- qualified Model Pack;
- NVIDIA GPU.

This is the preferred simple GPU deployment when one Windows machine has adequate GPU, CPU, memory and storage capacity.

#### P2 — Split-host Windows + Linux GPU

Host A — Windows:
- IIS / ASP.NET Core API;
- React UI;
- application-local FFmpeg;
- MAVI-owned PostgreSQL + pgvector.

Host B — Linux x86_64:
- MAVI Vision worker;
- qualified Linux CUDA Runtime Binary Pack;
- qualified Model Pack;
- NVIDIA GPU.

Both hosts operate on the controlled disconnected LAN. This profile is suited to dedicated compute, isolation and future scale-out.

#### P3 — Single-host Windows CPU

One Windows Production machine runs the complete stack using the qualified Windows CPU Runtime Binary Pack.

This profile is valid for lower-throughput deployments only after the exact Production CPU profile has passed the required acceptance/performance gates. Existing Development CPU evidence is useful but does not by itself qualify P3 for Production.

### 3. Logical planes remain stable

Regardless of physical profile, MAVI retains the same logical boundaries:

- **Operator plane** — React;
- **Operational plane** — ASP.NET Core API/orchestration;
- **Data plane** — PostgreSQL + pgvector and managed storage;
- **Vision plane** — Python worker;
- **Integration plane** — explicit worker/API contracts.

Co-location does not collapse evidence boundaries. Production qualification still records distinct operational, data, storage and Vision identities.

### 4. Offline/network boundary

All Production profiles are offline-by-design:

- no runtime Internet dependency;
- no CDN;
- no remote package/model resolution;
- no online telemetry/licensing/activation requirement;
- only approved internal endpoints;
- all Runtime/Model components arrive through approved offline media/component stores.

## Qualification model

Qualification attaches to the **deployment profile and device/runtime combination**.

Examples:

- Windows CPU evidence does not qualify Windows CUDA;
- Windows CUDA does not qualify Linux CUDA;
- Linux CUDA does not qualify Windows CUDA;
- a Development laptop run does not automatically qualify the same machine layout for Production;
- a Production profile cannot silently use another device when the declared profile requires CUDA.

The application/API/UI contracts, model, pipeline and persisted domain semantics remain common across profiles.

## Phase-1 closure rule

Phase-1 product closure does **not** require every conceivable deployment profile to be qualified simultaneously.

Instead:

1. the release must explicitly identify which Production profile(s) are supported;
2. every profile claimed as supported must have complete evidence for its exact platform/device/runtime/topology;
3. unsupported or pending profiles remain explicitly unqualified;
4. no documentation or installer may imply support for a profile whose evidence is incomplete.

For the immediate Task-18 path, **P1 — Single-host Windows GPU** is the most practical first GPU Production profile because the developer/test environment is already Windows and may use the laptop GPU when compatible. P2 can be qualified later on dedicated Linux NVIDIA hardware without blocking continued development.

P3 remains available as a CPU Production profile only if its performance/acceptance gates are explicitly satisfied.

## Tooling reconciliation requirement

Existing Phase-1 acceptance tools and qualification metadata were created under the earlier four-variant / Linux-CUDA-centric closure model. Some currently hard-code:

- Windows CPU;
- Windows CUDA;
- Linux CPU;
- Linux CUDA;
- Linux NVIDIA recovery/performance;
- final scenarios tied specifically to Linux CUDA.

ADR-008 changes the deployment qualification model to profile-based support. Therefore those tools/configuration must be reviewed and, where necessary, refactored **before authoritative Task-18 qualification** so that:

- a release can declare one or more supported Production profiles;
- the assessor requires only the gates applicable to each claimed profile;
- it never weakens required evidence for a claimed profile;
- pending profiles remain pending rather than blocking unrelated qualified profiles.

Until this reconciliation is implemented and reviewed, authoritative release qualification remains blocked.

## Rationale

1. A single Windows laptop must remain a first-class Development environment.
2. Available laptop GPU capacity should be usable rather than ignored.
3. A capable Windows Production host can reasonably run the complete stack including CUDA.
4. The independently deployable Vision worker already supports split-host scale-out without requiring it everywhere.
5. Profile-specific qualification is more accurate than treating one physical topology as the product architecture.
6. Explicit device selection and provenance prevent silent fallback from weakening evidence.
7. This model minimizes deployment burden while preserving a path to higher-performance dedicated Linux GPU workers.

## Consequences

- Development remains fully possible on one Windows laptop.
- Development can use Windows CUDA when a compatible/qualified GPU runtime is available.
- CPU mode remains deliberately supported for regression/debugging.
- Production may be single-host Windows GPU, split-host Windows+Linux GPU, or single-host Windows CPU.
- Qualification is profile-specific.
- No Production profile is considered supported until its exact evidence is complete.
- Current Task-18 acceptance tooling requires profile-model reconciliation before authoritative qualification begins.
