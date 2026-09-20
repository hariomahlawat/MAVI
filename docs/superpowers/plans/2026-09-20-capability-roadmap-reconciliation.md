# Capability Paper → Laptop-Development Milestones (Reconciliation)

**Date:** 2026-09-20  
**Baseline:** `main@0225779`; unmerged work on `feature/visual-intelligence-workspace` (PR #50) and `feature/windows-cuda-pre-c2` (PR #49, frozen)  
**Product direction:** recorded-video functionality on the development laptop first; live cameras/VMS last. Offline compatibility and the Development-evidence / Production-qualification distinction (ADR-008, ADR-009) are preserved throughout.

This document maps the capability paper (as summarised in `docs/superpowers/specs/2026-09-08-visual-intelligence-memory-design.md` §1–§2 and the architecture design §6–§7) onto what exists, in four honest states. It does not restate or reinterpret historical evidence; the dated plans and reviews under `docs/superpowers/plans/`, `docs/reviews/` and `docs/qualification/` remain the record of what was verified when.

## States

- **Merged and verified** — on `main`, with exact-head CI green and the cited evidence.
- **Implemented, unmerged** — complete on a branch with CI green, awaiting review/merge.
- **Groundwork without a usable feature** — schema, module boundary or contract exists; no operator-facing capability.
- **Future** — not started; sequencing only.

## Mapping

| Capability-paper element | State | Where / evidence | Next laptop milestone |
|---|---|---|---|
| Camera registry with camera-local time authority | Merged and verified | Task 15; `/api/cameras`, Cameras page; ADR-004 | — |
| Import recorded MP4 with manual recording time; MAVI-owned media | Merged and verified | Task 15; `/api/videos/import`, Import page | — |
| Durable processing-run / vision-job lifecycle (lease, heartbeat, fail, complete, recovery, watchdog) | Merged and verified | Tasks 7–9, 13, 17; `docs/superpowers/plans/2026-09-16-task-17-runtime-progress-watchdog-device-hardening.md` | — |
| Person/vehicle detection + single-camera tracking (RTMDet + ByteTrack), qualified CPU runtime | Merged and verified on Windows CPU Development | Task 10, Task 12 runtime bundle; Windows CPU functional evidence in the Phase-1 roadmap re-baseline | Windows CUDA Development qualification is PR #49's stream (frozen; operator-executed C6.R/C7) |
| Atomic Track/observation/trajectory persistence with sealed evidence | Merged and verified | Task 13; ADR-006 | — |
| Structured Track search (camera, class, time, duration, confidence) with stable cursor snapshot | Merged and verified | Task 14 API, Task 16 UI | — |
| Evidence-linked source-video playback at Track offset | Merged and verified | Task 14 range content, Task 16 Review page | — |
| Processing status, failure status, retry | Merged and verified (API); operator inventory/queue pages **implemented, unmerged** | Task 15; PR #50 Videos/Processing pages, `framesProcessed`/`tracksCreated` on status | Merge PR #50 after review |
| Search → in-place inspector → full review → return; bounding-box and trajectory overlay; design system | Implemented, unmerged | PR #50; `docs/superpowers/plans/2026-09-19-visual-intelligence-workspace.md`; `docs/reviews/2026-09-20-pr50-correctness-review.md` (real-stack evidence with fixture worker; laptop checks listed) | Laptop run of the listed checks; merge |
| Model/pipeline version traceability, run attestation | Merged and verified (API); surfaced in Review page **implemented, unmerged** | Task 13/17 attestation endpoint; PR #50 provenance panel | Merge PR #50 |
| Human review of Tracks (confirm/reject with audit) | Groundwork without a usable feature | `ReviewStatus` enum on `Track`/`Entity` (display-only); `Audit` and `Identity` module folders are reserved boundaries with no code | `docs/superpowers/plans/2026-09-20-audited-review-and-cases-plan.md` (next increment) |
| Investigation cases collecting selected Tracks and notes | Groundwork without a usable feature | `Investigations` module boundary reserved; no schema | Same plan, second slice |
| Historical runs per video (paginated) | Future | Search already scopes to the latest completed run per video and accepts `processingRunId` for a historical run; no runs-list endpoint | Small API + Processing detail tab |
| Visual attributes (colour, type) | Groundwork without a usable feature | `VisualAttribute` table exists, unpopulated (spec §7.8) | Future; after review/cases |
| Persistent Entity (visual identity) | Groundwork without a usable feature | `Entity` table dormant; `Track.EntityId` nullable; spec §3.4 forbids automatic grouping in Phase 1 | Future; only after human-review semantics exist |
| Image similarity / ReID / embeddings search | Future | pgvector present; no embeddings produced or stored | Separate increment; needs model qualification |
| Face recognition, ANPR/OCR | Future (out of Phase-1 scope) | — | Separate increments with their own qualification |
| Mission rules, anomaly/pattern-of-life, relationship intelligence | Future | `Missions` module boundary reserved | After investigations |
| Natural-language / LLM-VLM search | Future | — | Not before offline-capable models are qualified |

## Recorded separately

**Live integration (RTSP ingestion, VMS integration).** Future and last by product direction. Nothing on any branch ingests live streams; the import path is file-based by design (spec §2.2). This will need its own ADR covering buffering, retention and the authority of camera time.

**Formal Production qualification.** Task 18 (`docs/superpowers/plans/2026-09-18-task-18-phase1-production-qualification-rebaseline.md`) remains the active qualification task and is independent of feature delivery. No Production profile (P1/P2/P3) is advertised as supported; PR #49's Development CUDA evidence cannot satisfy P1/P2 (ADR-009). Nothing in PR #50 changes qualification semantics, checkpoint validation or device policy.

## Sequencing on the laptop

1. Land PR #50 after the laptop checks in the review report.
2. Audited human review + basic cases (planned; prerequisites: operator identity, audit records).
3. Historical runs endpoint and Processing detail history.
4. Visual attributes, then similarity search, each as a separate qualified increment.
5. Live ingestion and VMS integration last.
