# ADR-008: Phase-1 Production Topology

**Status:** Accepted  
**Date:** 2026-09-18

## Context

Task 18 requires a single, explicit production topology before authoritative qualification begins. Earlier Phase-1 plans assumed a Windows operational plane, PostgreSQL data plane and Linux NVIDIA Vision worker, while subsequent implementation added:

- one-click offline Windows Production setup;
- MAVI-owned PostgreSQL 18 + pgvector;
- application-local FFmpeg;
- independently deployable Python Vision workers;
- reusable Runtime Binary Pack / Model Pack / Application Overlay distribution;
- exact component-integrity checks;
- a qualified Windows CPU Development execution path.

The later work does not eliminate the architectural separation between the operational plane and the Vision plane. It does, however, make the Windows application/database host substantially more self-contained and reproducible.

Task 18 must therefore state the supported Phase-1 Production topology explicitly rather than inheriting a historical diagram by implication.

## Decision

The **Phase-1 Production acceptance topology** is a disconnected, on-premises two-host deployment with three logical planes.

### Host A — Windows Operational + Data Host

A supported Windows Server/Windows production host runs:

1. **IIS / ASP.NET Core operational plane**
   - MAVI API;
   - compiled React application;
   - application-local FFmpeg/ffprobe;
   - machine-owned MAVI Production configuration.

2. **MAVI-owned PostgreSQL 18 + pgvector data plane**
   - dedicated MAVI PostgreSQL service;
   - Production database `mavi`;
   - no dependence on an unrelated system PostgreSQL installation;
   - managed backup/restore under the MAVI operational procedure.

The operational and database planes remain logically distinct for evidence, topology identity, backup/restore and prerequisite validation even though the canonical Phase-1 deployment co-locates them on Host A.

### Host B — Linux NVIDIA Vision Worker

A separate x86_64 Linux host runs the Production Vision worker using:

- the exact qualified Linux CUDA Runtime Binary Pack;
- the exact required Model Pack;
- the current qualified Application / Release Overlay;
- a frozen NVIDIA driver/CUDA runtime combination;
- no Internet dependency;
- no silent CPU fallback during GPU-qualified acceptance.

The worker communicates with Host A over the controlled internal LAN through the supported MAVI worker/API contract. Model/runtime packages are supplied only from approved offline media/component storage.

### Network boundary

Both hosts operate inside the same controlled disconnected deployment boundary:

- no runtime Internet dependency;
- no CDN;
- no remote model/package resolution;
- no online licence/activation requirement;
- only explicitly approved internal endpoints;
- qualification captures the concrete host/topology identities.

## GPU scope

**GPU/CUDA execution is part of the Phase-1 Production acceptance scope.**

This decision does **not** claim that GPU is already qualified. It means Task 18 cannot reach final Phase-1 acceptance until the required Linux NVIDIA/CUDA evidence is produced and passes.

Windows CPU and Linux CPU evidence remain valuable subsystem/runtime evidence but do not substitute for the Production Linux CUDA worker requirement.

## Rationale

1. The operational application and database installation now have a mature, reproducible Windows offline setup path.
2. Keeping PostgreSQL on the canonical Windows Production host minimizes deployment complexity for Phase 1 while preserving a distinct logical data-plane identity for backup/restore and acceptance evidence.
3. The Vision plane remains independently deployable and computationally isolated from the operational host.
4. The existing Phase-1 production acceptance tooling, prerequisite policy and recovery/performance contracts already model a Linux NVIDIA worker.
5. Phase-1 production throughput/recovery qualification was designed around a dedicated accelerator worker. Removing that requirement would be a product-scope change, not a housekeeping simplification.
6. The topology remains fully offline and consistent with ADR-003 and ADR-007.

## Qualification implications

Task 18 must now collect and freeze exact prerequisite observations for:

### Windows Operational + Data Host
- Windows product/version/build;
- IIS version;
- ASP.NET Core/.NET runtime;
- PostgreSQL version;
- pgvector version;
- MAVI install/config roots;
- managed-media/evidence roots;
- host identity.

### Linux NVIDIA Vision Host
- distribution/release;
- architecture;
- CPython identity;
- Linux CUDA Runtime Pack identity;
- Model Pack identity;
- NVIDIA driver;
- CUDA runtime;
- exact venv/environment fingerprint;
- host identity.

The canonical Production acceptance event must prove:

- Host A application/API/UI health;
- MAVI-owned PostgreSQL/pgvector availability;
- Host B worker READY;
- actual CUDA execution;
- no silent CPU fallback;
- controlled internal connectivity;
- no external runtime dependency.

## Non-goals

This ADR does not:

- approve exact OS/runtime/driver versions;
- qualify CUDA hardware;
- promote model/release metadata;
- require Development to use Linux or GPU;
- prohibit future scale-out to multiple workers or a separate database host.

Those changes require their own reviewed deployment/qualification decisions.

## Consequences

- Task-18 readiness item **Production topology** becomes READY.
- Task-18 **GPU scope** is resolved: GPU is required for Phase-1 Production acceptance.
- **GPU qualification remains BLOCKED** until real Linux NVIDIA/CUDA evidence exists.
- `phase1-production-prerequisites-v1.json` remains pending until exact observed versions are reviewed and frozen.
- Final Task-18 production E2E, failure/reprocess and recovery/performance scenarios must execute with the qualified Linux CUDA worker.
- Windows CPU PR #44 evidence remains inherited subsystem evidence, not the final Production worker proof.
