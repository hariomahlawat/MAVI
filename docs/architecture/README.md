# MAVI Architecture Index

The approved architectural baseline is defined in `docs/superpowers/specs/2026-09-08-mavi-repository-architecture-design.md`, together with accepted ADRs under `docs/decisions/`.

## Core boundaries

1. **Operator plane:** React/TypeScript.
2. **Operational plane:** ASP.NET Core modular monolith.
3. **Vision plane:** independently deployable Python AI workers.
4. **Data plane:** PostgreSQL 18 + pgvector and abstracted media storage.
5. **Integration plane:** explicit, versioned contracts between operational and vision components.

## Deployment and dependency policy

MAVI is offline-by-design. The current operator deployment contract is:

- Development: `Setup-MAVI-Development.cmd` → restart Visual Studio once → F5.
- Production: canonical offline media → `Setup-MAVI-Production.cmd` → MAVI ready.

All future dependency-bearing features must follow `docs/architecture/dependency-and-offline-packaging-policy.md`. The machine-readable direct-dependency baseline is `config/dependencies/offline-dependency-policy-v1.json`, and `python tools/verify_repo.py` fails closed on undeclared .NET/npm/Python dependency drift.

Large third-party binary payloads are staged through canonical `vendor/...` locations and assembled into manifest-verified offline media rather than being assumed from PATH or downloaded on first run.

## Deployment profiles

ADR-008 separates Development convenience from Production qualification. Development is supported on one Windows laptop/workstation and may use CPU or a compatible Windows GPU. Production is profile-based: P1 single-host Windows GPU, P2 split-host Windows + Linux GPU, and P3 single-host Windows CPU. Each Production profile is qualified independently; no profile inherits another profile's evidence.

## Current maturity

Phase-1 implementation includes the operational API/UI, PostgreSQL/pgvector persistence, media processing integration, qualified-runtime/acceptance tooling, one-click Development/Production setup infrastructure and disconnected-release qualification machinery.

Implementation completion remains distinct from release verification: CUDA, disconnected-host, quality/performance, lifecycle and recovery evidence must still be executed against the exact frozen release before reporting a release as verified.

## Current capability roadmap

What MAVI builds next is decided by `docs/superpowers/plans/capability-roadmap.md` (capability-first: Spatial & Temporal Track Analytics, then Visual Attributes, expanded object classes, ANPR/OCR, visual similarity and ReID candidates, event analytics, richer structured search; audited review/cases and live RTSP/VMS ingestion later). That roadmap is a development sequence. It is distinct from Task 18 Production qualification: a capability merged to `main` is Development capability until its exact release evidence passes, and Development CUDA evidence (ADR-009) never satisfies a Production profile.

## Key documents

- `AGENTS.md` — binding engineering rules.
- `docs/architecture/dependency-and-offline-packaging-policy.md` — dependency/change methodology.
- `docs/architecture/ui-ux-design-specification.md` — adopted UI/UX design specification (v1.0): workspace archetypes, token/colour architecture, operational-state taxonomy, accessibility and visual QA standards, and the sequential UI-1 → UI-5 foundation programme. Normative for frontend work from UI-1 onward.
- `docs/architecture/phase1-production-topology.md` — Development device policy and Production deployment profiles (ADR-008).
- `docs/decisions/ADR-009-development-cuda-qualification-separation.md` — Development CUDA hardware evidence is explicitly non-Production and cannot satisfy P1/P2.
- `docs/decisions/ADR-011-scene-analytics-lifecycle-and-revisions.md` — scene-configuration revisions and the deterministic scene-analytics post-processing stage, including attempt fencing and analytics search readiness.
- `docs/qualification/2026-09-18-windows-cuda-c1-compatibility-decision.md` — current sanitized Windows-CUDA Development engineering candidate and change-control boundary.
- `docs/runbooks/local-development.md` — supported Development workflow.
- `docs/runbooks/mavi-offline-setup.md` — offline media preparation and installation.
- `docs/runbooks/offline-readiness.md` — milestone/release offline-readiness checks.
- `docs/runbooks/phase1-acceptance.md` — formal Phase-1 qualification.
- `docs/superpowers/plans/capability-roadmap.md` — authoritative capability-first development roadmap and documentation index.
- `docs/superpowers/plans/capability-implementation-roadmap.md` — implementation-level roadmap: stage dependencies, technical impact per stage, qualification-preservation matrix.
- `docs/superpowers/plans/2026-09-18-task-18-phase1-production-qualification-rebaseline.md` — Production qualification stream (independent of the capability roadmap).


## Documentation precedence

Dated files under `docs/superpowers/plans/` and task-specific design specs are retained as implementation/history records and may describe the state or workflow that existed when that task was planned. They are not operator runbooks.

For current Development, Production, dependency packaging and qualification procedures, use the current architecture policy, accepted ADRs and `docs/runbooks/`. When a historical task plan conflicts with a current runbook, the current runbook governs operational procedure.
