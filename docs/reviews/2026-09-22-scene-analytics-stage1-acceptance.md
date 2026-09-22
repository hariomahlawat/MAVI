# Spatial & Temporal Track Analytics — Stage-1 acceptance status

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance`
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`

---

## Verdict

**Stage 1 is NOT closed.** Mandatory exit-gate evidence remains unexecuted because this environment cannot produce it. Nothing in this document, and nothing in the roadmaps, claims otherwise.

This slice is **partially complete**. What was executed is recorded truthfully below; what was not is marked `NOT EXECUTED — environment blocked` and is not waived, re-scoped or softened.

## Environment limitation, established by test rather than assumption

| Blocker | Evidence |
|---|---|
| PostgreSQL 18 unavailable | Installed server is 16.15. `apt.postgresql.org` returns HTTP 403 through the agent proxy; Docker CLI present but no daemon, so `pgvector/pgvector:pg18` cannot be pulled |
| Real worker unavailable | No `onnxruntime`, no `cv2`, no GPU, no model weights |

The plan states that PostgreSQL 16 observations are not qualification evidence. That rule is applied throughout; the harness computes `isQualificationGradeDatabase` from the live server and labels its own output.

## Exit gate

| # | Requirement | Status |
|---|---|---|
| 1 | Stage-1 functional acceptance met | **NOT EXECUTED** — depends on 2–6, 15 |
| 2 | C1 agrees across trajectory/facts/search/explanation/aggregate/heatmap/UI | **NOT EXECUTED** — C1 not built; per-layer golden fixtures exist but the cross-layer trace does not |
| 3 | PG18 plan/timing for every §S predicate and §T aggregate at 10^5 facts | **NOT EXECUTED — environment blocked.** Harness built, committed and smoke-proven end to end |
| 4 | Analytics-unit duration/rows for Development corpus and synthetic 1,000-Track run | **NOT EXECUTED** — harness not written |
| 5 | Aggregate 10^5-fact qualification | **NOT EXECUTED — environment blocked.** Harness covers it |
| 6 | Heatmap 50-run/candidate envelope | **NOT EXECUTED** — harness not written |
| 7 | Both fan-out limits have evidence-backed decisions | **NOT EXECUTED** — requires 6 |
| 8 | No demonstrated N+1/unbounded DB or evidence-I/O path | **PARTIAL.** N+1 disproven for the aggregate by an always-on test holding query count constant across geometry. **An unbounded materialisation path is OPEN (P2)** — see the security document |
| 9 | Cancellation/failure proven at realistic volume | **NOT EXECUTED — environment blocked** |
| 10 | Snapshot/revision consistency under concurrency | **NOT EXECUTED** in this pass. Slice-4/6 barrier ordering tests exist; the deterministic race probes do not |
| 11 | Incomplete/unknown never appears as observed zero | **PASS** for the surfaces built in Slices 4–6, by existing tests: incomplete scopes render no figure and no map, and complete-zero renders as a real observation |
| 12 | Browser trajectory parser obeys `[0,1]` | **PASS** — fixed this pass, RED tests first, shared rule, complement tests guard the closed interval |
| 13 | Security/resource review has no open P1/P2 | **FAIL** — one open P2 (unbounded aggregate materialisation). No P1 |
| 14 | Operator workflow / accessibility / visual QA | **NOT EXECUTED** in this pass |
| 15 | Development offline/real-worker acceptance | **NOT EXECUTED — environment blocked** |
| 16 | No policy-violating dependency/runtime drift | **PASS** — no dependency added; `verify_repo.py` green |
| 17 | Relevant suites green | **PASS** — Domain 195, Application 369, Integration 623/625, frontend 821. The two integration failures are the PostgreSQL 18 prerequisite assertion, reproduced and explained |
| 18 | Documentation reflects measured reality | **PASS** for this pass's documents |
| 19 | Independent cold review has no P1/P2 | **PARTIAL** — performed on this diff; the pre-existing P2 above remains open by design |
| 20 | Zero unresolved material review threads | **PASS** — none open |
| 21 | Exact-head CI green | Reported on the PR |

## What this pass did complete

1. **Browser trajectory parser `[0,1]` parity** — the one known deferred code defect, closed test-first against the frozen Domain rule.
2. **Qualification corpus and measurement harnesses** — deterministic, invariant-obeying, dependency-free, and runnable unchanged against PostgreSQL 18.
3. **An always-on N+1 regression guard** for the aggregate read.
4. **A reconciled obligation register** and the security/bounded-resource review, including one previously unrecorded P2.

## Remaining work

Environment-bound items are listed with executable commands in the handoff report and in `2026-09-22-scene-analytics-s7-corpus.md` §4. Items 2, 4, 6, 10 and 14 are further engineering, not merely execution, and are not environment-blocked.
