# Scene Analytics Slice 7 — Hardening, Performance, Acceptance and Stage-1 Closure

**Date:** 2026-09-22  
**Status:** Planning branch; implementation MUST NOT start until this plan has passed independent cold review, the planning PR is merged, and post-merge `main` is green.  
**Planning branch:** `docs/scene-analytics-s7-plan`  
**Implementation branch:** `feature/scene-analytics-s7-hardening-acceptance` (create only after the planning gate above).  
**Planning baseline:** `main@2717918761fb35e4845b6887772ebdd5c7c6edf8` — PR #68 / Scene Analytics Slice 6 merged.  
**Parent plan:** `docs/superpowers/plans/2026-09-20-spatial-temporal-track-analytics.md`.  
**Architecture:** ADR-011 (scene analytics lifecycle/revisions) and ADR-012 (operator UI architecture).  
**UI contract:** `docs/architecture/ui-ux-design-specification.md`.  
**Scope:** Stage-1 closure only. No new analytical capability.

---

## 1. Objective and stop condition

Slice 7 is the final Scene Analytics slice. Its job is not to add another feature. It must demonstrate, with reproducible evidence, that the complete Stage-1 Spatial & Temporal Track Analytics capability already delivered by Slices 0–6 is semantically correct across layers; bounded and performant at representative and deliberately heavy scale; snapshot-, revision- and evidence-consistent under concurrency; fail-closed where evidence is missing, corrupt, stale or incomplete; operable through the complete operator workflow; accessible and visually conformant; reproducible on the supported Development path without undeclared online dependencies; and documented well enough that Stage 1 can be frozen and Stage 2 can start without carrying hidden obligations forward.

**Stage-1 stop rule:** once the acceptance matrix is satisfied, measured limits are recorded, no P1/P2-equivalent finding remains, independent cold review is clean, and exact-head CI is green, stop changing Stage 1. Cosmetic/P3 items that do not impair interpretation, accessibility, integrity, security or bounded operation go to backlog.

## 2. Explicit non-goals

Slice 7 MUST NOT introduce a new analytic metric/event/geometry/search predicate; trajectory v2; visual attributes, ANPR/OCR, similarity, ReID/entities; live RTSP; persisted raster heatmaps or cache absent measured need and plan amendment; generic reporting/dashboard; new UI archetype/redesign; new dependency merely for benchmarks/fuzzing; speculative indexes; or Production-profile qualification owned by Task 18.

Task 18 remains independent. Slice 7 may reuse its machinery, but MUST NOT claim Production qualification from Development evidence.

## 3. Frozen invariants

- ADR-011 identity is `(ProcessingRun, SceneConfigurationRevision, AlgorithmVersion)`; pinned historical fact-bearing units remain readable.
- Search, aggregate and heatmap results are visibility-snapshot consistent.
- Scene edits never silently reinterpret history.
- Unknown/pending/stale/failed/disabled/not-configured are distinct. **Incomplete or unknown evidence must never be represented as observed zero.**
- Every accepted fact traces to sealed trajectory evidence plus pinned revision and algorithm.
- Evidence integrity fails closed; missing/corrupt evidence never silently thins a result.
- Heatmap is an on-demand rendering of accepted trajectory evidence, not a source of truth.
- Slice-6 counting semantics remain frozen unless a correctness defect is proven.
- One Evidence Player/timeline/layer contract remains shared.
- ADR-012/UI specification remains normative.
- No dependency bypasses offline/dependency policy.

## 4. Deferred-obligation inventory

Implementation begins by re-auditing exact `main` and reconciling this register before code changes.

1. **Browser trajectory parser parity (Slice 5 P3):** reject finite x/y outside `[0,1]` with discriminating malformed-artifact tests.
2. **Measured index review (Slice 4):** re-measure analytical queries at corpus volume on PostgreSQL 18 with `EXPLAIN (ANALYZE, BUFFERS)`; PG16 observations are not qualification evidence.
3. **Analytics-unit throughput (§Z parent plan):** measure unit duration and rows written for the Development corpus and for a synthetic 1,000-Track run. This qualifies the post-processing stage itself, not only its read paths.
4. **Aggregate scale (Slice 6):** at least `10^5` relevant persisted facts.
5. **Heatmap timing (Slice 6):** repeatable 50-run timing; record resolved runs and candidate Analysed Tracks.
6. **Heatmap limits:** re-evaluate 50 covered runs and 2,000 candidate Analysed Tracks; retain/lower/raise/remove only from evidence while remaining bounded.
7. **Evidence bytes:** if cheap metadata exists at the accepted seam, record aggregate accepted bytes; do not open artifacts merely to discover size.
8. **512-bucket server cap:** response/resource bound, not performance claim; change only by explicit evidence-backed contract decision.
9. **Normal UI ≤120 buckets:** preserve unless usability evidence demonstrates a problem; separately exercise server bound.
10. **Real-stack deterministic corpus:** specifically the parent plan's three short FFmpeg-scripted videos (line crossing, zone dwell then exit, stationary then depart) through the real worker path and analytics host, with expected facts derived from scripted motion rather than visual judgement. parent-plan Development-laptop real-worker acceptance and analytics evidence.
11. **Cross-OS deterministic golden evidence:** prove deterministic pure semantics where OS independence is claimed.
12. **Failure injection/qualification closure:** parent plan assigns these plus independent cold review, P1/P2 remediation, evidence and docs to Slice 7.
13. **Visual QA closure:** final Stage-1 pass under ADR-012/UI specification.

Closed Slice-5 overflow accessibility P3s, Slice-6 planning P3=0, and repaired PR #68 review findings are regression obligations, not invitations to redesign.

## 5. Reference environment and target-freeze rule

Before qualification measurements, record exact git SHA; OS/build; CPU/logical cores; RAM; storage; PostgreSQL **18.x exact version/settings**; pgvector; .NET; Node/npm; browser; worker/model/runtime-pack identity; Development CPU/GPU path; corpus identity; and cold/warm-cache method.

**Performance objectives MUST be frozen before the measured acceptance run.** First inventory existing repository expectations and actual reference hardware; then define separate objectives for interactive metadata/search/aggregate work and heavier heatmap work. Hard resource limits are separate from latency objectives. Do not choose an SLA after seeing results.

## 6. Deterministic qualification corpus

Build with existing dependencies; avoid committing large binaries outside repository policy.

### C1 — semantic reference

Human-auditable exact-answer scenarios: outside→enter→exit; begin/end inside; boundary samples; repeated visits; overlapping zones; dwell/stationary/stopped thresholds; both crossing directions; frozen touch/no-cross cases; one-sample and long trajectories; multiple classes; complete-zero; incomplete coverage; failed/unavailable analysis; current/superseded revisions; historical pinned identity.

### C2 — representative operational

Representative cameras/videos/runs/Tracks/facts/geometries/evidence for normal operator-path performance and UI acceptance.

### C3 — heavy synthetic

At least `10^5` relevant facts; increasing Track/fact volume, window width, geometry count, bucket count through normal values toward 512, heatmap runs 1/5/10/25/50, and candidate Analysed Tracks increasing to near 2,000.

**Corpus integrity:** synthetic rows obey real visibility/revision/relational invariants. Pure deterministic geometry/temporal fixtures must also reproduce the parent-plan cross-OS contract: identical facts on Windows and Linux CI, comparing doubles after the frozen six-decimal rounding. Heatmap tests use sealed artifacts with real SHA-256 metadata and the accepted storage seam. Each corpus records deterministic seed/config and a reproducible manifest.

## 7. Semantic end-to-end golden matrix

Trace C1 through `trajectory → facts/outcome → Track search → detail/explanation → aggregate → heatmap → UI`. Record pinned identity, expected facts, search inclusion, provenance, aggregate/occupancy, heatmap contribution, coverage and operator state. Cross-layer mismatch is a correctness defect even if isolated tests pass.

Explicitly verify unique Tracks vs repeated visits, entry/exit/direction, sample occupancy/peak, boundary/tie rules, class parity, complete-zero vs incomplete-zero, and historical correctness after newer revision activation.

## 8. PostgreSQL 18 plan qualification

On C2/C3 capture `EXPLAIN (ANALYZE, BUFFERS)` for analytical Track search; each §S predicate family and meaningful combinations; coverage; zone/dwell/stationary; crossing/direction; each §T aggregate; repeated visits; class-filtered aggregates; heatmap scope/candidate resolution. **The parent §Z requirement is explicit: measure the latency of every §S predicate and every §T aggregate at `10^5` facts**, not merely an aggregate-only 100k-fact case.

Record planning/execution time, actual/estimated rows, buffers, scan types, sort/hash, spills and API query count.

**Index rule:** no speculative index. Require problematic measured plan → hypothesis → before/after same-corpus evidence → write/storage regression consideration → retain only for material benefit. Preserve pre-optimization evidence.

## 9. Analytics-stage and aggregate performance envelope

### 9.1 Analytics-unit throughput

Qualify the write-side post-processing stage required by parent-plan §Z. Measure complete SceneAnalysis unit duration and rows written for (a) the Development scripted corpus and (b) a synthetic 1,000-Track run. Record Track outcomes and each derived-fact family row count, total rows, attempt/identity, geometry count and trajectory sample volume. Where existing instrumentation permits, separate trajectory decode/engine/persistence/final-commit time without adding permanent production telemetry solely for benchmarking. Also inspect the reconciliation/claim query at representative corpus volume if it is material in the measured unit lifecycle.

### 9.2 Aggregate read envelope

Vary fact/Track volume, bucket count, geometry count, window width, class and coverage. C3 MUST include `10^5` facts. Record endpoint/query time where reliably observable, DB query count, response size, cardinality and repeatable memory/GC observations. Identify dominant scaling dimension; do not tune to one synthetic number.

## 10. Heatmap/evidence-I/O envelope

Benchmark 1/5/10/25/50 covered runs and controlled candidate Track increases to the accepted ceiling. Record resolved runs, candidate Tracks, trajectories opened, samples decoded, cheap accepted bytes, DB scope time, artifact read, SHA verification, decode, grid accumulation, total time, memory/GC and cancellation latency where measurable.

For both 50-run and 2,000-Track limits write an explicit **retain/lower/raise/remove** decision with evidence. Removal requires another demonstrable bound.

Caching/persisted raster remains out of scope. If objectives cannot be met, stop and amend the plan with bottleneck, invalidation identity, storage/offline impact and correctness model before implementing cache.

## 11. Failure and resilience matrix

Required cases: missing artifact; SHA mismatch; decodable wrong-digest artifact; malformed/truncated msgpack; non-finite coordinate; browser coordinate outside `[0,1]`; missing reference frame; identity mismatch; failed analysis; stale/superseded history; pending/running analysis; evidence-store read failure; cancellation during heavy heatmap; API restart; PostgreSQL restart/reconnect on supported Development workflow; operator retry.

Assert status/error vocabulary, no false zero, no silent partial-as-complete, no path/secret/internal exception leakage, correct recovery, immutable history. Cancellation must be exercised at realistic C3 volume and release expensive work promptly.

## 12. Concurrency and snapshot consistency

Use deterministic barriers/hooks, never sleep-based race tests. Race reads with ProcessingRun visibility, SceneAnalysis completion, aggregate/heatmap completion, revision activation, re-analysis/supersession, continuation after newer revision, and relevant retry/reclaim fencing.

Prove no mixed visibility generation; aggregate/heatmap coverage and facts share one snapshot; revision geometry/facts cannot mix; pagination stays pinned; historical results remain reproducible.

## 13. Browser trajectory parser parity

Add RED tests for x/y <0 and >1; demonstrate old acceptance where applicable; reject using existing evidence-unavailable/error contract; preserve exact 0/1; verify worker/application/browser semantic parity without a second definition.

## 14. Security and bounded-resource re-review

Re-review strict query whitelist/value parsing, cursor integrity, arbitrary IDs, historical identity semantics, oversized windows/buckets/grids, run/Track fan-out, malformed evidence, path traversal/disclosure, enumeration/error leakage, resource exhaustion, cancellation and response-size bounds. Use existing dependencies for adversarial/property tests; no fuzzing dependency solely for this slice.

## 15. Operator workflow acceptance

Execute **Camera → Scene Configuration → Processing/readiness → Search → Investigation → evidence explanation → Analytics Workbench Activity → Heatmap** against realistic data. Verify navigation, provenance, coverage/readiness, incomplete/stale/failed wording, URL filters, historical evidence, mode validity/refresh, and one shared player. No client action should bypass a guard the server predictably refuses.

Acceptance is not redesign; non-material cosmetics go to backlog.

## 16. Accessibility and visual QA

Run §26 at 1366×768, 1440, 1920 and ~2560 with long names, dense activity, sparse/dense heatmaps, complete-zero, incomplete coverage, loading/error/stale, corrupt/unavailable evidence, historical revision and disabled/refused controls.

Verify keyboard/focus, disabled semantics, semantic chart/spatial equivalents, non-colour communication, screen-reader structure/names, scroll ownership/overflow and required contrast. Classify every finding P1/P2/P3.

## 17. Development offline/clean-machine acceptance

This is Stage-1 Development acceptance, **not Task-18 Production qualification**. Using the frozen offline path: verify manifests; provision PostgreSQL 18/extension; migrate; start API/frontend/worker/runtime/analytics service; import/process scripted corpus through real worker; configure/wait analysis; execute E2E acceptance; restart services and prove persistence; verify no undeclared Internet fetch. Record exact package/runtime identities and exceptions.

## 18. Instrumentation discipline

Prefer `tools/`, tests and review scripts over production telemetry added only for qualification. Temporary instrumentation is removed before final validation or intentionally retained with documentation/tests. Commit compact evidence; large traces follow artifact policy.

## 19. Required evidence documents

Implementation must produce dated equivalents of:

- `docs/reviews/2026-09-22-scene-analytics-s7-corpus.md`
- `docs/reviews/2026-09-22-scene-analytics-s7-performance.md`
- `docs/reviews/2026-09-22-scene-analytics-s7-semantic-acceptance.md`
- `docs/reviews/2026-09-22-scene-analytics-s7-resilience-concurrency.md`
- `docs/reviews/2026-09-22-scene-analytics-s7-security.md`
- `docs/reviews/2026-09-22-scene-analytics-s7-ui-acceptance.md`
- `docs/reviews/2026-09-22-scene-analytics-stage1-acceptance.md`

Use actual implementation date if later. Each final report states exact commit, environment, corpus, commands/tooling, measurements, exceptions and evidence locations.

## 20. Documentation closure

Update stale Stage-1 status in parent plan, `capability-roadmap.md`, `capability-implementation-roadmap.md`, UI spec only for stale status, `docs/runbooks/local-development.md`, and API/runbook docs only where measured limits/behaviour require it. After acceptance, roadmaps say Stage 1 closed and **Stage 2 — Visual Attributes** next. Task 18 remains independent.

## 21. Implementation sequence

- [ ] **1 Rebaseline/audit:** start from merged planning PR on green `main`; search Slices 0–6 plans/reviews/code for deferred/TODO/P3/performance/acceptance obligations and reconcile §4.
- [ ] **2 Freeze environment/objectives** before measured acceptance.
- [ ] **3 Build C1/C2/C3 corpus tooling** and integrity-valid evidence.
- [ ] **4 Establish untouched baseline** before optimization.
- [ ] **5 Semantic E2E golden acceptance.**
- [ ] **6 PostgreSQL 18 plan qualification.**
- [ ] **7 Analytics-stage + aggregate qualification:** parent §Z Development-corpus and synthetic 1,000-Track unit duration/rows-written measurement, then aggregate scale including `10^5` facts.
- [ ] **8 Heatmap/evidence-I/O qualification**, including 1/5/10/25/50 runs and limit decision.
- [ ] **9 Resilience/cancellation/concurrency.**
- [ ] **10 Browser parser parity** with discriminating tests.
- [ ] **11 Evidence-supported remediation only.**
- [ ] **12 Re-run identical measurements** and preserve before/after.
- [ ] **13 Security/resource review.**
- [ ] **14 Operator/accessibility/visual acceptance.**
- [ ] **15 Offline real-stack Development acceptance.**
- [ ] **16 Documentation closure/evidence reports.**
- [ ] **17 Full repository validation.**
- [ ] **18 Independent cold review** of exact diff/evidence; repair material findings in one bounded pass.
- [ ] **19 Exact-head CI:** no drift; required workflows green; zero unresolved material findings/threads.
- [ ] **20 Merge/post-merge confirmation** and freeze Stage 1.

## 22. Test strategy and anti-theatre rule

Material repairs require discriminating tests: fail against pre-fix behaviour or a negative probe where practical; assert execution boundary, not only UI state; deterministic clocks/barriers over sleeps; do not weaken assertions. Performance evidence is reference-machine qualification, not brittle CI timing assertions; CI validates corpus/tool correctness.

## 23. Final validation matrix

At exact head: Domain; Application; Integration on PostgreSQL 18; API/contracts; frontend Vitest/typecheck/production build; `verify_repo`; dependency/offline policy; corpus reproducibility; semantic golden matrix; PG18 plans/performance; aggregate/heatmap qualification; resilience/concurrency/cancellation; operator/accessibility/visual QA; Development real-worker/offline acceptance.

Environment exclusions must be explicit, reproduced/understood and irrelevant to the diff; “known failure” alone is insufficient.

## 24. Severity/review policy

**P1:** evidence corruption, wrong answer/provenance, snapshot/revision mixing, security boundary failure, serious unbounded resource path. Fix.  
**P2:** reachable functional/operational/accessibility defect, material failure against pre-frozen objective, misleading incomplete state, bounded-resource bypass. Fix.  
**P3:** cosmetic/local maintainability/usability improvement without material correctness/accessibility/integrity/security/resource impact. Record; fix only if trivial/local/low risk.

Internal cold review is the normal final gate. External Codex is optional only for unresolved material architectural uncertainty, not an infinite review loop.

## 25. Formal Stage-1 exit gate

Stage 1 closes only when all are true:

1. Stage-1 functional acceptance met.
2. C1 agrees across trajectory/facts/search/explanation/aggregate/heatmap/UI.
3. PostgreSQL 18 plans and corpus timings are recorded, including latency/plan evidence for every §S predicate and every §T aggregate at `10^5` facts.
4. Analytics-unit duration and rows-written evidence is recorded for both the Development corpus and synthetic 1,000-Track run.
5. Aggregate scale qualification is recorded, including the required `10^5`-fact cases.
6. Heatmap 50-run/candidate envelope is recorded and both fan-out limits explicitly decided.
7. No demonstrated N+1/unbounded DB/evidence-I/O path remains.
8. Cancellation/failure is proven at realistic volume.
9. Snapshot/revision consistency is proven under concurrency.
10. Incomplete/unknown never appears as observed zero.
11. Browser parser matches the normalized-coordinate contract.
12. Security/resource review has no open P1/P2.
13. Operator workflow/accessibility/visual QA pass.
14. Development offline/real-worker acceptance is recorded with no undeclared dependency.
15. No policy-violating dependency/runtime drift is introduced.
16. Relevant suites and exact-head CI are green except explicitly proven irrelevant environment exclusions.
17. Documentation reflects measured reality, limits and known limitations.
18. Independent cold review is clean of P1/P2.
19. No unresolved material review thread remains.
20. Post-merge critical verification on `main` is green.

Then mark Stage 1 complete and advance to **Stage 2 — Visual Attributes**. Do not hold Stage 1 for optional polish.

## 26. Planning-review gate

Before this plan merges: verify every Slice-7 deferral from Slices 0–6 is represented; Task-18 scope remains separate; targets freeze before measurement; corpus cannot bypass evidence/visibility/revision semantics; baseline-before-optimization is explicit; no speculative index/cache/dependency is authorized; stop rule is bounded; perform independent cold review against merged code/docs; correct all P1/P2 planning findings before implementation.
