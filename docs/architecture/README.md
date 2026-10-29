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

What MAVI builds next is decided by `docs/superpowers/plans/capability-roadmap.md` (capability-first: Spatial & Temporal Track Analytics, Visual Attributes, expanded classes, ANPR/OCR, Visual Similarity, **Face Intelligence (Stage 5A)**, ReID candidates, event analytics, **Structured Intelligence Query + aggregations**, and **Ask MAVI**; audited review/cases and live RTSP/VMS ingestion later). That roadmap is a development sequence. It is distinct from Task 18 Production qualification: a capability merged to `main` is Development capability until its exact release evidence passes, and Development CUDA evidence (ADR-009) never satisfies a Production profile.

## Capability and model architecture

MAVI is deliberately **capability-oriented, not model-family-oriented**. ADR-014 makes the stable contract the semantic capability, while model/vendor/framework identity belongs to the selected Model Pack and Runtime Pack. Different specialist model families may therefore coexist when measured technical performance supports them. Framework reuse, runtime footprint and offline packaging are operational/engineering selection axes; licence/deployment assessment is separate from technical ranking under the Model Selection Record method.

The same principle applies to operator intelligence queries. **Advanced Search** remains the precise deterministic evidence-query builder. Future Stage 8 adds typed deterministic aggregations and explicit Track/Event/Entity cardinality; Stage 9 **Ask MAVI** is a separate simple Investigation surface that translates ordinary language into that whitelisted contract. The language model interprets the question; the application/database query engine computes factual answers; every answer remains linked to its structured interpretation and evidence.

## Key documents

- `AGENTS.md` — binding engineering rules.
- `docs/architecture/engineering-operating-principles.md` — implementation-first operating principles: executable controls over prose, reuse of proven research and implementations, proportionate evidence.
- `docs/architecture/experimental-methodology.md` — standing rule for consequential experiments, benchmarks, qualification and parameter studies: challenge the proposed method before running it, freeze before reading outcomes, label evidence status, supersede rather than overwrite defective analyses, and cold-review before a conclusion is promoted (independently where the claim requires it).
- `docs/architecture/dependency-and-offline-packaging-policy.md` — dependency/change methodology.
- `docs/architecture/ui-ux-design-specification.md` — adopted UI/UX design specification (v2.3; v2.0 is the Stage 3.5 architecture freeze of 2026-10-07, v2.1 adds the prospective Ask MAVI/Advanced Search interface boundary, v2.2 the narrow §26 harness-observability exception, v2.3 the Stage 4 plate search and evidence §17.2): workspace archetypes, token/colour architecture, operational-state taxonomy, support tiers, accessibility, visual QA, product craftsmanship, edge-state and performance standards. Normative for all frontend work; the UI-1 → UI-5 programme and its transitional clause are kept as historical record.
- `docs/architecture/phase1-production-topology.md` — Development device policy and Production deployment profiles (ADR-008).
- `docs/decisions/ADR-009-development-cuda-qualification-separation.md` — Development CUDA hardware evidence is explicitly non-Production and cannot satisfy P1/P2.
- `docs/decisions/ADR-011-scene-analytics-lifecycle-and-revisions.md` — scene-configuration revisions and the deterministic scene-analytics post-processing stage, including attempt fencing and analytics search readiness.
- `docs/decisions/ADR-012-operator-interface-design-architecture.md` — adopted operator-interface design architecture: workspace archetypes, colour-role and token architecture, accessibility and visual-QA obligations; amended 2026-10-07 (Stage 3.5) with craftsmanship/support tiers/state grammar/CI visual regression/WCAG 2.2 AA, and amended 2026-10-12 to keep **Ask MAVI** as a distinct simple Investigation surface over the same deterministic query contract as Advanced Search.
- `docs/decisions/ADR-013-modular-post-track-intelligence-and-evidence.md` — **accepted** Stage-2 architecture: VisionJob-owned bounded Track Evidence Set, independent attribute lifecycle/process, lease-scoped hash-verified evidence reads, immutable outcomes and v4 search identity.
- `docs/decisions/ADR-014-capability-binding-v2.md` — **accepted** architecture generalising Runtime/Model Pack binding from the detector-era single-model shape to capability bindings, capability-neutral model manifests and capability-scoped qualification.
- `docs/decisions/ADR-015-public-first-protected-qualification.md` — **accepted** owner policy C+: public-first Development, protected final qualification (Stage 2 S2c origin; frozen-qualification admission contract).
- `docs/decisions/ADR-016-detector-native-vehicle-subclass.md` — **accepted** Stage-3 decision: detector-native vehicle subclass, evaluation before exposure.
- `docs/decisions/ADR-017-benchmark-first-development-and-research-dataset-reuse.md` — **accepted** cross-cutting Development data strategy: established labelled benchmarks first, explicit dataset-native mappings, significant annotation campaigns only for a demonstrated gap (small diagnostics need a technical rationale), release-level research-dataset admissibility statuses, the lightest evidence process appropriate to the claim, and the protected final-qualification boundary preserved. Prospectively refines ADR-015 §5 for Development.
- `docs/decisions/ADR-018-plate-search-denormalised-track-start.md` — **accepted** Stage-4 PR-4 decision: the plate search reads candidate texts in page order by a trigger-maintained copy of the Track's start time (a search accelerator, never a semantic authority), with the backfill, the run invariant and the drift check.
- `docs/decisions/ADR-019-plate-coverage-end-time-index-and-search-parallelism.md` — **accepted** Stage-4 PR-4 decision: a `tracks (object_class, end_timestamp_utc)` index for the windowed plate coverage count, and `SET LOCAL max_parallel_workers_per_gather = 0` scoped to the plate search's own transaction.
- `docs/decisions/ADR-020-poc-deployment-profile.md` — **accepted** owner decision 2026-10-28: the `poc-single-host` deployment profile (amends ADR-008 by addition) for the end-to-end PoC — one Windows host, Development evidence class, Development-grade packs including an `sm_75;sm_89` CUDA variant, mandatory "not Production-qualified" disclosure; P1/P2/P3, ADR-009 and Task 18 unchanged.
- `docs/decisions/ADR-021-embedding-model-storage-and-similarity-candidates.md` — **accepted owner decision pending** (PoC S4, register C5.1): SigLIP 2 base as the PoC embedding Model Pack (two ONNX towers, offline, `unverified`); `embeddings` post-Track role over lease-scoped evidence with failure isolation; 768-d mean vectors over crops ≥ 80 px; pgvector `track_embeddings` with exact, snapshot-stable cosine search; results are *Similarity candidates*, never identity, no `EntityId` write.
- `docs/qualification/model-selection/README.md` — Model Selection Record methodology (MSR method v1, accepted by PR #115; S2c.0 only reconciles that acceptance into the implementation baseline): how every learned component's model choice is recorded (candidates retained, reported vs MAVI-measured evidence, technical ranking separate from licence/deployment qualification) and what a future replacement must beat. Decision history, not an acceptance or qualification authority.
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

**Cross-cutting agent rules and architectural authority.** Root `AGENTS.md` sets binding engineering safeguards for all work; `CLAUDE.md` is a tool-facing entry point, not a separate source of architectural authority. Accepted ADRs govern their specific architectural decisions. The engineering operating principles govern how work is carried out within those safeguards and decisions. Read task-relevant governing documents rather than every ADR. If two binding requirements appear substantively incompatible, identify the conflict and seek the smallest explicit reconciliation; do not silently ignore one or assume the more permissive text prevails.

When two current documents conflict, this order decides for architectural and procedural documents, highest first; it does not silently waive cross-cutting `AGENTS.md` safeguards:

1. **Accepted ADRs** (`docs/decisions/`) — architectural decisions and invariants. A later ADR that amends an earlier one says so in its header; otherwise both stand.
2. **Architecture policies and specifications** (`docs/architecture/`) — the dependency/offline policy, the UI/UX specification, topology.
3. **Roadmaps** (`docs/superpowers/plans/capability-roadmap.md` for sequence, `capability-implementation-roadmap.md` for per-stage technical impact).
4. **The current stage's parent plan and acceptance register** — the plan states how the ADRs are implemented for that stage; the acceptance register (`docs/reviews/<date>-<stage>-acceptance.md`) is the only authoritative exit gate for that stage and no other document may keep a second numbered acceptance list.
5. **Runbooks** for operational procedure. Qualification plans (`docs/qualification/`) govern qualification protocol for their stage under the ADRs and register. The Model Selection Record methodology and its records (`docs/qualification/model-selection/`) are decision and evidence history. They rank below the register and the qualification plan, and never act as an acceptance or qualification authority.
6. **Dated task plans, design specs and review records** — history. They are never rewritten to match later decisions; where they could mislead, they carry a supersession note pointing at the governing document.

For Stage 2 (Visual Attributes) the governing set is ADR-013, ADR-014, ADR-015 and ADR-017 (Development data strategy: established labelled research datasets and benchmarks before new labels; frozen final qualification unchanged), `docs/superpowers/plans/2026-09-23-visual-attributes.md`, `docs/qualification/2026-09-23-visual-attributes-qualification-plan.md` and the register `docs/reviews/2026-09-23-visual-attributes-acceptance.md`. For Stage 3 (Vehicle Subclass) the governing set is ADR-016, ADR-017 (Development data strategy, cross-cutting), the two current roadmaps (`capability-roadmap.md`, `capability-implementation-roadmap.md`), `docs/superpowers/plans/2026-10-03-stage3-s3-2-vehicle-subclass-measurement.md` and the register `docs/reviews/2026-10-03-stage3-vehicle-subclass-acceptance.md`; `docs/qualification/stage3/s3-2b-real-corpus-intake-and-derivation.md` is the S3.2b-2 operational runbook. The two current roadmaps (item 3) always govern sequencing and prerequisites for every stage and are never treated as outside a stage's set. Any other document outside the relevant stage's set that describes Stage-2 or Stage-3 behaviour differently is historical. Within each set, the documents rank as ordered above.
