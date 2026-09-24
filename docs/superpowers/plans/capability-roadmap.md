# MAVI Capability-First Development Roadmap

**Status:** Authoritative current capability-development roadmap. This file controls *what MAVI builds next*. It does not control Production qualification (Task 18) and it does not restate or reinterpret historical evidence.  
**Adopted:** 2026-09-20  
**Baseline:** `main@e38af446d4e287cb12a8cf3d881e0293f90f7d6d` (Scene Analytics Stage 1 / PR #70 merged and post-merge verified)  
**Product direction:** recorded-video intelligence capability first; heavier investigation/reporting workflow only once the data is rich enough to justify it; live cameras and VMS integration last. Offline operation and the Development-evidence / Production-qualification distinction (ADR-003, ADR-008, ADR-009) are mandatory throughout.  
**Supersedes:** the sequencing in `2026-09-20-audited-review-and-cases-plan.md` (now deferred) and the "Recommended next feature" originally written in `2026-09-19-visual-intelligence-workspace.md`. Both files are retained as records and carry a status note.

## 1. Baseline: what exists on `main` today

| Area | State on `main@ed1acf4` | Qualification status | Record |
|---|---|---|---|
| Recorded-video operator workflow (Cameras, Import, Videos, Processing, Search, inspector, Review with evidence playback and overlays) | Present | Development evidence: component tests, real API + PostgreSQL workflow with the fixture worker, mocked-API screenshots and axe scan | PR #50, `docs/reviews/2026-09-20-pr50-correctness-review.md` |
| RTMDet + ByteTrack person/vehicle detection and tracking, Windows CPU Development runtime | Present | **Protected qualified CPU Development path**: `windows-x86_64-cpu.lock` unchanged by PR #49; Task 10 / Task 12 CPU matrices green on every head | Task 10, Task 12, `docs/qualification/` |
| Windows CUDA Development runtime | Present: frozen build contract (CUDA 12.4, MSVC 14.44.35207, SDK 10.0.26100.0, `sm_75`), `windows-x86_64-cuda.lock`, contract-derived runtime pack, component binding, worker/launcher hardening, evidence tooling | **C4 Development hardware evidence** on a GTX 1650 Ti (`runtime.json` variant `qualified-development-hardware`). **Outstanding on the physical host:** C5.4 device-resolution checks, C6 five E2E runs, C7 37 failure-matrix cases; CUDA release lock remains `pending-hardware-qualification` (owner decision after C6/C7) | PR #49, `2026-09-18-windows-cuda-development.md`, `c8-pr49-readiness.md` |
| Durable processing lifecycle (lease, heartbeat, watchdog, recovery), atomic sealed Track/observation/trajectory persistence, structured search with stable cursor snapshot, run attestation | Present | Task 13–17 acceptance evidence | Task 13–17 plans |
| Production profiles P1 / P2 / P3 | Machinery present (Offline Binary Kit, setup, profile-aware qualification tooling) | **Not qualified.** No Production profile is advertised as supported. Development CUDA evidence cannot satisfy P1/P2 (ADR-009) | `2026-09-18-task-18-phase1-production-qualification-rebaseline.md` |
| `VisualAttribute` table, `Entity` table, `Track.EntityId`, `ReviewStatus` enum, `Audit`/`Identity`/`Investigations` module boundaries, pgvector extension | Groundwork only; unpopulated or display-only | — | `docs/superpowers/specs/2026-09-08-visual-intelligence-memory-design.md` |

Two things this table deliberately does **not** say: that Windows CUDA is Production-qualified (it is not; it has Development evidence through C4 only), and that any Production profile is supported (none is).

## 2. Sequencing decision — 20 September 2026

MAVI today understands recorded video, person/vehicle detections, Tracks, observations, trajectories, time, confidence and evidence playback. That is a sound base but semantically thin: a Track says little beyond *broad class, when, where in the frame, for how long, and with what confidence*.

Building an audited review and cases layer on top of that now would give operators a workflow for cataloguing detections rather than investigating intelligence. The decision is therefore to **increase what MAVI can understand and retrieve from video first**, and to build heavier investigation and reporting workflow **after** the underlying data justifies it. Deterministic capabilities that need no new model come before model-based ones, so each model-based step inherits searchable, explainable structure and a proven offline-qualification path.

The sequence:

| # | Capability | Kind | Why here |
|---|---|---|---|
| 1 | **Spatial & Temporal Track Analytics** | Deterministic; no new model | Largest intelligence gain from data already persisted; establishes scene configuration, derived-fact persistence and analytic search that every later stage reuses |
| 2 | Visual Attributes | Model-based (attribute classifier) | First appearance semantics; populates the existing `VisualAttribute` groundwork |
| 3 | Expanded operational object / vehicle classes | Qualification change, possibly detector change | Makes attribute and plate work class-aware |
| 4 | ANPR / OCR | Model + OCR engine | Vehicle identity cue tied to Track evidence |
| 5 | Visual Similarity / query-by-example | Embedding model + pgvector | "Find similar" over persons and vehicles; results are similarity candidates, never identity assertions |
| 6 | Person/Vehicle ReID and candidate Entity association | Builds on 5 | Proposes candidate associations; never silently merges Tracks |
| 7 | Event / Behaviour Analytics | Deterministic rules over 1, 2, 6 and time | Measurable events only, after their inputs exist |
| 8 | Richer structured search | API/UI | Exposes 1–7 as explicit predicates |
| 9 | Natural-language query translation | Offline model, translating to 8 | Only after deterministic structured semantics exist to translate into |
| 10 | Audited human review / cases | Identity, audit, workflow | When there is enough intelligence to investigate; design retained in the deferred plan |
| 11 | Live RTSP / VMS integration | Platform phase | After recorded-video intelligence is mature; see §6 |

Not next: live cameras; operator identity/audit as a major feature; cases or report generation. Identity/audit plumbing may still arrive earlier as a *small* enabler if a concrete operator mutation needs attribution, but it is not a roadmap stage.

## 3. Capability map

States: **Merged and verified** (on `main`, exact-head CI and cited evidence) · **Groundwork** (schema or boundary exists, no operator capability) · **Next** · **Planned** · **Deferred** (design retained, not active) · **Later phase**.

| Capability | State | Where / evidence | Roadmap position |
|---|---|---|---|
| Camera registry with camera-local time authority | Merged and verified | Task 15; ADR-004 | — |
| Recorded MP4 import with manual recording time; MAVI-owned media | Merged and verified | Task 15 | — |
| Processing lifecycle, status, retry; latest-run-per-video inventory | Merged and verified | Tasks 7–9, 13, 15, 17; PR #50 | Historical-runs listing is a small later increment |
| Person/vehicle detection + single-camera tracking | Merged and verified on Windows CPU Development; Windows CUDA Development through C4 | Task 10, Task 12, PR #49 | C5.4/C6/C7 host execution outstanding (qualification, not roadmap) |
| Sealed Track/observation/trajectory persistence | Merged and verified | Task 13; ADR-006 | Foundation for stage 1 |
| Structured Track search with stable cursor snapshot; Search → inspector → Review → back | Merged and verified | Task 14, Task 16, PR #50 | Extended by stages 1, 2, 4, 8 |
| Evidence playback with bounding-box and trajectory overlay; provenance panel | Merged and verified | Task 14, PR #50 | Reused by stage 1 to explain analytic matches |
| Spatial & temporal Track analytics | **Merged and verified — Stage 1 complete** | Slices 0–7 are merged. PostgreSQL 18 qualification, real-worker Development acceptance/restart persistence, realistic-volume resilience, deterministic concurrency probes, C1 semantic acceptance, accessibility/visual QA, runtime identity, Search → Investigation, PostgreSQL restart/reconnect, and disconnected scripted-worker acceptance all **PASSED**. PR #70 merged as `main@e38af446d4e287cb12a8cf3d881e0293f90f7d6d`; MAVI Quality Gate #1943, Task 10 Runtime Qualification #725, and Task 17 Acceptance Validation #1087 all passed on that exact commit, satisfying exit-gate item 20. Status and evidence: `docs/reviews/2026-09-22-scene-analytics-stage1-acceptance.md`. | Stage 1 — complete and frozen |
| Visual attributes | **In progress — slice S1 (Track Evidence Set) under implementation** | Stage-2 architecture is defined by the parent plan plus accepted ADR-013 (Track Evidence / analysis lifecycle) and ADR-014 (capability binding v2). Architecture gate A1–A12 is closed. S1.1 (whole-Track retirement, PR #75), S1.2a (platform completion v3 + staging janitor, PR #77), S1.2b (worker trajectory spool, PR #78) and S1.2c (worker Evidence Set + v3 emission, PR #79) are merged. S1.2 is complete on `main@2060599a9786651f36071742034076369520d0ce`; the S1.3 plan is accepted (PR #81). S1.3a (Track-detail `observations[]` read contract) is merged (PR #82); S1.3b (minimal Evidence Set UI) is implemented in PR #83, in review. The two-tier Representative (ADR-013 §4 amendment) was accepted on 2026-09-24. The real-clip parameter measurement is complete (MOT17-02/13). Its finding F1 was fixed by scorer `quality-v2` (ADR-013 §4 occlusion-proxy amendment, accepted 2026-09-24), and the re-measurement retained every selector default. No Stage-2 acceptance row is claimed yet (evidence is S1.4). | Stage 2 |
| Expanded object / vehicle subclasses | Planned | Product semantics are person/vehicle | Stage 3 |
| ANPR / OCR | Planned | No plate or OCR pipeline | Stage 4 |
| Visual similarity | Planned | pgvector present; no embeddings produced or stored | Stage 5 |
| ReID / Entity candidates | Groundwork → Planned | `Entity` dormant; `Track.EntityId` nullable; spec §3.4 forbids automatic grouping | Stage 6 |
| Event / behaviour analytics | Planned | — | Stage 7 |
| Natural-language search | Planned, last of the query work | — | Stage 9 |
| Human review decisions (confirm/reject with audit) | Groundwork → **Deferred** | `ReviewStatus` display-only; `Audit`/`Identity` boundaries empty | Stage 10 — `2026-09-20-audited-review-and-cases-plan.md` |
| Investigation cases | Groundwork → **Deferred** | `Investigations` boundary only | Stage 10 |
| Mission rules, relationship intelligence | Later | `Missions` boundary | After stages 6–7 |
| Face recognition | Not planned in this roadmap | — | Separate qualified increment only if a mission requirement justifies it |
| Live RTSP / VMS ingestion | **Later phase** | Import path is file-based by design | §6 |

## 4. What each future capability introduces

Every stage below that adds a model, Python library, native runtime, OCR engine, embedding model, npm or .NET package, database extension or OS prerequisite must, **in the same pull request**, update `config/dependencies/offline-dependency-policy-v1.json`, the offline packaging and setup path, verification, licences and runbooks (`docs/architecture/dependency-and-offline-packaging-policy.md`). Every model-based capability ships with a manifest, version, hash, runtime-compatibility statement, offline-pack location and its own qualification evidence, on the pattern the RTMDet Model Pack and Runtime Pack already follow (ADR-005, ADR-007). Nothing resolves online at install or first run.

| Stage | New technical prerequisites | Where offline / dependency qualification applies |
|---|---|---|
| 1 Spatial & Temporal Analytics | Scene-configuration schema and API; derived-fact tables and indexes; one geometry implementation in the .NET Application layer; scene editor UI | No new model or Python dependency. Any geometry or spatial library considered is a dependency and goes through the policy; the plan prefers in-house geometry |
| 2 Visual Attributes | VisionJob Evidence Set contract v3; component-binding v2; separate attribute worker role/process; lease-scoped evidence read; immutable VisualAttributeAnalysis; sealed raw prediction artefact; final Observed/Unknown rows; v4 attribute-search cursor | Model-manifest v2 + capability binding; runtime-profile v2 migration and detector qualification reconciliation; person/vehicle Model Packs; licences/offline inventory; predeclared labelled-corpus protocol; CPU and CUDA Development variants stated without Production inheritance |
| 3 Expanded classes | Class-vocabulary change in the qualified runtime profile and manifest; possibly a different detector checkpoint | A vocabulary change re-issues the qualification record; a new checkpoint is a new Model Pack qualification |
| 4 ANPR / OCR | Plate-detection model; OCR engine (native runtime, language/plate-format packs); plate-observation schema; normalisation rules; partial-plate search | OCR engine is a native runtime dependency with its own lock, licence and offline pack; regional plate grammar is configuration, not code |
| 5 Visual Similarity | Embedding model; embedding storage per Track (dimension, version); pgvector index (choose HNSW or IVFFlat after measuring); "Find Similar" API/UI | Embedding model as Model Pack; embedding version bound to results; index type is a schema decision recorded in a migration |
| 6 ReID / Entity candidates | Candidate-association records; review surface for candidates; cross-camera time/geometry constraints | Reuses stage-5 model; no automatic merge; association algorithm version bound to candidates |
| 7 Event analytics | Rule definitions over persisted facts; event records bound to inputs and rule version | No model; rules are configuration with revisions |
| 8 Richer structured search | API/UI predicates over 1–7; canonical URL state and snapshot semantics preserved | None |
| 9 Natural-language translation | An offline language model able to run on the qualified hardware; a strict translator to stage-8 predicates; refusal on untranslatable input | Heavy model dependency; qualified like any other Model Pack; never bypasses structured semantics |
| 10 Audited review / cases | Windows-integrated operator identity, `Reviewer` policy, append-only audit tables (ADR-010 to be written when activated) | In-box ASP.NET Core Negotiate; no new package expected |
| 11 Live ingestion | See §6 | Streaming architecture ADR first |

## 5. Architecture notes for later stages

These notes fix direction so later plans start from shared assumptions. They are not designs.

**Visual Attributes (stage 2).** Architecture-frozen plan: `2026-09-23-visual-attributes.md`, accepted ADR-013 and ADR-014. Raw multi-view Track evidence is selected inside VisionJob under explicit byte bounds; learned attributes run later in an independently leased/fenced process over lease-scoped hash-verified accepted evidence. Model/runtime binding is capability-oriented rather than detector-special-cased. Initial scope is person upper/lower clothing colour, bag/backpack, qualified headwear/helmet, and vehicle dominant colour. Vehicle subclass remains Stage 3 unless deliberately rebaselined. No attribute is exposed unless its frozen qualification gate is met.

**ANPR / OCR (stage 4).** Flow: `Vehicle Track → plate detection → plate crop as sealed evidence → OCR observations → searchable plate text`. A Track may carry several OCR observations (different frames, different readings) each with confidence; a normalised reading (character-class folding, separator removal) is derived per observation for search; partial-plate search matches normalised text; every hit links back to the crop and the source frame.

**Visual Similarity (stage 5).** Embeddings per Track representative crop(s) stored with model version and dimension; pgvector nearest-neighbour search; UI concept `Find Similar` from the inspector or Review page. Results are presented as **similarity candidates** with a score and evidence side-by-side, never as "same person" or "same vehicle".

**ReID (stage 6).** Only after similarity retrieval is stable. `Track` remains one observed trajectory; `Entity` is a hypothesised persistent real-world subject across Tracks. Initial ReID proposes candidate associations for an operator to inspect; `Track.EntityId` is written only by an explicit, attributable decision, which is why stage 10's identity/audit work becomes relevant here.

**Event analytics (stage 7).** Combine zones, trajectories, dwell, attributes, Entity candidates and time into measurable events: intrusion, loitering, wrong-way movement, stopped vehicle, repeated visit, crowd build-up, group movement, co-occurrence. Each event is bound to its inputs and rule version and is explainable from evidence. No claim of intent or anomaly detection is made before the measurable events it would rest on exist.

**Natural-language search (stage 9).** A translator from operator language to stage-8 structured predicates, with the translated query shown and editable before it runs. It never invents a predicate the structured layer does not have.

## 6. Live cameras: a separate later platform phase

Nothing on any branch ingests live streams; import is file-based by design. Live ingestion is not "the import path, but continuous". It adds platform concerns that recorded-video work never touches and that each need design and qualification: RTSP and VMS integration; reconnect and stream-health semantics; buffering and backpressure; clock and time authority for live frames (ADR-004 extended); retention and rolling storage; continuous jobs rather than run-per-video; GPU scheduling across streams; load shedding; long-running recovery. This phase begins with its own ADR and after recorded-video intelligence (stages 1–8) is mature. Nothing from it is implemented now.

## 7. Roadmap versus Task 18 qualification

These are two different sequences and must not be collapsed:

- **Task 18 — Production Qualification and Phase-1 Closure** (`2026-09-18-task-18-phase1-production-qualification-rebaseline.md`) is a qualification and release stream. It may proceed independently of, and in parallel with, capability development.
- **This roadmap** decides which capability is developed next.

Consequences: a new Development capability does not become Production-qualified by being merged; PR #49's Development CUDA evidence does not equal P1 or P2 qualification; and a future feature must not silently invalidate existing qualification evidence. Where a feature changes a qualified artefact (runtime profile, component binding, model manifest, checkpoint, pipeline profile), the qualification records that bind those artefacts by digest are re-derived deliberately and the change is stated in the PR, exactly as PR #49 did for the runtime-profile digest.

## 8. Documentation index

| Document | Role |
|---|---|
| `docs/superpowers/plans/capability-roadmap.md` (this file) | Authoritative current capability roadmap: what we build next and why |
| `docs/superpowers/plans/capability-implementation-roadmap.md` | Authoritative implementation roadmap: stage dependencies, per-stage technical impact, qualification-preservation matrix, risks, ADR needs |
| `docs/superpowers/plans/2026-09-20-spatial-temporal-track-analytics.md` | Completed implementation-grade plan for Stage 1; closed by PR #70 and post-merge verification on `main@e38af446d4e287cb12a8cf3d881e0293f90f7d6d` |
| `docs/superpowers/plans/2026-09-20-audited-review-and-cases-plan.md` | Deferred design for stage 10; not active |
| `docs/superpowers/plans/2026-09-19-visual-intelligence-workspace.md` | Record of the delivered operator workspace (PR #50); its original "next feature" is superseded here |
| `docs/superpowers/plans/2026-09-13-phase1-roadmap-rebaseline.md` | Phase-1 task status (Tasks 13–17 complete, Task 18 active) |
| `docs/superpowers/plans/2026-09-18-task-18-phase1-production-qualification-rebaseline.md` | Production qualification stream |
| `docs/superpowers/plans/2026-09-18-windows-cuda-development.md`, `c8-pr49-readiness.md` | Windows CUDA Development record and readiness; remaining C5.4/C6/C7 host work |
| `docs/architecture/ui-ux-design-specification.md`, ADR-012 | Adopted UI/UX design specification (v1.0) and the ADR accepting it; normative for frontend work, and source of the UI-1 → UI-5 foundation programme |
| `docs/architecture/README.md`, ADRs | Architecture baseline and decisions |
| `docs/architecture/dependency-and-offline-packaging-policy.md` | Dependency and offline packaging discipline every stage follows |

Historical plans and evidence documents are never rewritten to match this roadmap; where their statements were correct when written, they stand, and a status note points here.

## 9. Execution order from this baseline

1. ~~Finish and merge PR #49~~ — merged as `ed1acf4`.
2. ~~Establish the post-merge baseline~~ — §1.
3. ~~Spatial & Temporal Track Analytics~~ — **Stage 1 complete and frozen.** Slices 0–7 are merged. PR #70 merged as `main@e38af446d4e287cb12a8cf3d881e0293f90f7d6d`, and all three critical post-merge workflows passed on that exact commit, satisfying exit-gate item 20. Closure evidence is recorded in `docs/reviews/2026-09-22-scene-analytics-stage1-acceptance.md`.

   **UI Foundation programme is complete:** UI-1 → UI-5 are merged. Slice 5 extended the one Evidence Player/timeline/layer contract and is merged; Slice 6 heatmap UI uses the UI-2 Workbench grammar. This UI sequencing does not renumber Scene Analytics slices (0–7) or capability stages.

4. **Visual Attributes — Stage 2, IN PROGRESS.** Architecture freeze is complete. Slice S1 is being implemented per `2026-09-23-stage2-s1-2-evidence-set-implementation.md`: S1.1 (PR #75), S1.2a (PR #77), S1.2b (trajectory spool, PR #78) and S1.2c (Evidence Set + v3 emission, PR #79) are merged. S1.2 is complete on `main@2060599a9786651f36071742034076369520d0ce`; the two-tier Representative and scorer `quality-v2` are accepted, and the real-clip measurement retained every selector default. **S1.3 is in progress:** the plan is accepted (PR #81), S1.3a (read contract) is merged (PR #82), and S1.3b (minimal Evidence Set UI) is implemented in PR #83 and in review. S1.4 qualification evidence follows.
5. Expanded operational object / vehicle classes where useful.
6. ANPR / OCR.
7. Visual Similarity / Find Similar.
8. ReID / Entity candidate association.
9. Event / Behaviour Analytics.
10. Richer structured search; then natural-language translation.
11. Audited review / cases when semantic richness justifies them.
12. Live RTSP / VMS ingestion, after its ADR.

In parallel and independently: Task 18 Production qualification; PR #49's outstanding C5.4/C6/C7 host execution.
