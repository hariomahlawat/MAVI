# Scene Analytics Slice 7 Plan — Independent Cold Review

**Date:** 2026-09-22  
**Reviewed baseline:** `main@2717918761fb35e4845b6887772ebdd5c7c6edf8` (PR #68 merged)  
**Planning branch reviewed:** `docs/scene-analytics-s7-plan`  
**Scope:** planning correctness only; no Slice-7 feature implementation.

## Method

The plan was reviewed as a fresh Stage-1 closure proposal against the merged parent Spatial & Temporal Track Analytics plan, Slice 4 performance/security review, Slice 5 plan/implementation deferrals, Slice 6 plan/review, ADR-011, ADR-012, the UI/UX specification and both capability roadmaps. Searches covered Slice-7 references plus deferred/P3/TODO/performance/acceptance/qualification/EXPLAIN/corpus/index/cache obligations. The review deliberately separated Task-18 Production qualification from Stage-1 Development acceptance.

## Findings and disposition

### P2 — parent §Z write-side qualification was initially omitted — CLOSED

The first Slice-7 draft concentrated on read-side aggregate/search/heatmap qualification and did not explicitly require parent §Z's SceneAnalysis unit duration and rows-written measurements for both the Development corpus and a synthetic 1,000-Track run.

**Correction:** the plan now has a dedicated analytics-unit throughput section and an implementation task/exit-gate item for both required profiles. It also calls out the reconciliation/claim query when material to measured lifecycle cost.

### P2 — 100k-fact requirement was too aggregate-centric — CLOSED

The first draft required a 100k-fact aggregate case but did not state the parent requirement precisely enough: every §S predicate and every §T aggregate must have latency measured at `10^5` facts with PostgreSQL plan evidence.

**Correction:** §8 now states that exact requirement and binds it to PostgreSQL 18 `EXPLAIN (ANALYZE, BUFFERS)`.

### P2 — real-stack corpus was not specific enough — CLOSED

The first draft said “scripted corpus” but did not pin the parent's three scenarios.

**Correction:** the deferred register now names the three FFmpeg-scripted Development scenarios: straight line crossing, zone dwell then exit, stationary then depart; expected facts come from scripted motion rather than visual judgement.

### P2 — cross-OS determinism comparison detail was under-specified — CLOSED

The parent plan freezes Windows/Linux deterministic fact comparison with doubles rounded to six decimals.

**Correction:** corpus integrity now carries this exact comparison rule.

### P3 — roadmap/status documents were stale after PR #68 — CLOSED

The parent plan and two capability roadmaps still described Slice 6 as next / Slices 0–5 merged.

**Correction:** all three are rebaselined to merge commit `27179187`, state Slices 0–6 merged and identify Slice 7 as the final Stage-1 unit.

## Scope-boundary review

The revised plan correctly keeps the following outside Slice 7: new analytics capability; trajectory v2; visual attributes; ANPR/OCR; similarity/ReID; live RTSP; generic reporting; UI redesign; speculative cache/index/dependency; and Task-18 Production-profile qualification.

Development offline/real-worker acceptance is retained because it is an explicit Stage-1 exit obligation. It is labelled Development evidence and cannot be used to claim Production support.

## Performance-review assessment

The revised order is sound: freeze environment/objectives → build deterministic corpus → capture untouched baseline → inspect PG18 plans and write/read envelopes → remediate only from evidence → repeat identical measurements. This prevents post-hoc SLA selection and speculative optimization. Existing 50-run, 2,000-Track and 512-bucket bounds remain safety/resource contracts until measurements justify a deliberate change.

## Correctness and evidence assessment

The plan explicitly protects the central Stage-1 invariants: pinned revision/algorithm identity, visibility snapshot consistency, fact-bearing historical units, SHA-256 evidence integrity, no silent thinning of corrupt/missing evidence, and “unknown/incomplete is never observed zero.” The cross-layer C1 golden matrix is an appropriate defence against individually-green layers disagreeing semantically.

## Review-process assessment

The stop rule is bounded. P1/P2-equivalent findings block closure; non-material P3/cosmetic findings do not create an infinite review loop. Internal cold review is the normal gate; external Codex is optional only for unresolved material architectural uncertainty.

## Final planning verdict

After the corrections above:

- **Open P1 planning findings:** 0
- **Open P2 planning findings:** 0
- **Open material P3 planning findings:** 0
- **Task-18 scope leakage:** none identified
- **Speculative dependency/index/cache authorization:** none
- **Implementation readiness:** suitable to proceed through the planning PR gate.

Implementation must still wait for this planning PR to pass exact-head CI and merge; the implementation branch is then created from the resulting green `main`.
