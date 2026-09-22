# Spatial & Temporal Track Analytics — Stage-1 acceptance status

**Date:** 2026-09-22
**Branch:** `harioahlawat/execute-postgresql-18-qualification-pass` (PR #71), stacked on `feature/scene-analytics-s7-hardening-acceptance` (PR #70)
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`

---

## Verdict

**Stage 1 is NOT closed.** PostgreSQL 18 qualification for PR #71 is blocked pending a rerun from a pushed, repository-reachable final head; mandatory non-PG18 evidence and the aggregate-materialisation P2 also remain open.

This slice is **partially complete**. What was executed is recorded truthfully below; what was not is explicitly marked and is not waived, re-scoped or softened.

## Environments, and which of them can qualify

| Environment | Server | Standing |
|---|---|---|
| This repair/handoff container | PostgreSQL **16.15** | Engineering observations only. The plan is explicit that PostgreSQL 16 cannot qualify, and the harness computes `isQualificationGradeDatabase` from the live server rather than from a claim |
| The earlier independent pass | PostgreSQL **18.6**, pgvector 0.8.6, native on Ubuntu 24.04.4 | **Superseded.** The run was real and its methodology is recorded in the performance report, but the commit it claimed was not repository-reachable, so it closes no gate |
| The Development machine | PostgreSQL 18 exactly | Where qualification must be rerun, from the final pushed PR #71 head |

The real RTMDet/ByteTrack worker remains unavailable in every environment above: no runtime pack, model weights or GPU were supplied.

## Exit gate

| # | Requirement | Status |
|---|---|---|
| 1 | Stage-1 functional acceptance met | **NOT EXECUTED** — depends on 2–6, 15 |
| 2 | C1 agrees across trajectory/facts/search/explanation/aggregate/heatmap/UI | **PARTIAL.** C1 is built and passing across trajectory → facts → §S search → §T aggregate (`SemanticAcceptanceTests`, expected answers hand-derived from the frozen rules before running). The trace does **not** extend to the bounded explanation, the heatmap or the UI projection |
| 3 | PG18 plan/timing for every §S predicate and §T aggregate at 10^5 facts | **BLOCKED.** Prior local measurements are superseded; rerun required from the pushed final PR #71 head |
| 4 | Analytics-unit duration/rows for Development corpus and synthetic 1,000-Track run | **BLOCKED/PARTIAL.** Synthetic qualification must be rerun from the pushed final PR #71 head; real Development scripted corpus remains NOT EXECUTED |
| 5 | Aggregate 10^5-fact qualification | **BLOCKED.** Exact-head rerun required; the unbounded materialisation design remains an open P2 |
| 6 | Heatmap 50-run/candidate envelope | **BLOCKED.** Exact-head rerun required with only the first overall call labelled cold-ish |
| 7 | Both fan-out limits have evidence-backed decisions | **BLOCKED** pending the exact-head heatmap rerun |
| 8 | No demonstrated N+1/unbounded DB or evidence-I/O path | **PARTIAL.** N+1 disproven for the aggregate by an always-on test holding query count constant across geometry. **An unbounded materialisation path is OPEN (P2)** — see the security document |
| 9 | Cancellation/failure proven at realistic volume | **NOT EXECUTED.** Failure and cancellation are tested, but only on a one-Track world; the harness to run them against the C3 corpus is not written, so this is engineering work as well as a blocked execution |
| 10 | Snapshot/revision consistency under concurrency | **NOT EXECUTED** in this pass. Slice-4/6 barrier ordering tests exist; the deterministic race probes do not |
| 11 | Incomplete/unknown never appears as observed zero | **PASS** for the surfaces built in Slices 4–6, by existing tests: incomplete scopes render no figure and no map, and complete-zero renders as a real observation |
| 12 | Browser trajectory parser obeys `[0,1]` | **PASS** — fixed this pass, RED tests first, shared rule, complement tests guard the closed interval |
| 13 | Security/resource review has no open P1/P2 | **FAIL** — one open P2 (unbounded aggregate materialisation). No P1 |
| 14 | Operator workflow / accessibility / visual QA | **NOT EXECUTED** in this pass |
| 15 | Development offline/real-worker acceptance | **NOT EXECUTED — environment blocked** |
| 16 | No policy-violating dependency/runtime drift | **PASS** — no dependency added; `verify_repo.py` green |
| 17 | Relevant suites green | **PASS for the ordinary suites, on PostgreSQL 16.15.** See §Validation below. This gate is about the ordinary suites, not about PG18 qualification, which is item 3–7 and remains BLOCKED |
| 18 | Documentation reflects measured reality | **PASS** for this pass's documents |
| 19 | Independent cold review has no P1/P2 | **FAIL.** The reviewed false-green paths are repaired but await reachable-head requalification; the aggregate-materialisation P2 also remains open |
| 20 | Zero unresolved material review threads | **PENDING.** The four PR #71 findings are repaired and pushed. The two that depend on evidence rather than code — reachable-head qualification and exact-head CI — stay open until that evidence exists, so threads are not resolved merely because the code changed |
| 21 | Exact-head CI green | **PENDING.** Parent-head checks do not qualify PR #71; this gate remains pending until every required workflow passes on the final pushed PR #71 head |

## Validation

Executed in the repair/handoff container, on **PostgreSQL 16.15**. These are ordinary-suite results; none of them is PostgreSQL 18 qualification evidence.

| Suite | Result |
|---|---|
| Domain | 195 passed |
| Application | 369 passed |
| Integration | **649 passed, 2 failed of 651.** Both failures are `DatabaseStartupMigrationTests` asserting the PostgreSQL 18 prerequisite against this container's 16.15 — the product correctly refusing a server it does not support |
| Frontend | **not re-run in this pass, and not required:** no frontend file differs between PR #70's head and this one. The parent's result stands for the unchanged code |
| `python tools/verify_repo.py` | PASSED |
| Dependency surface | unchanged — no diff in any `*.csproj`, `package.json`, lockfile or `config/dependencies/` between the baseline and this head |

The heavy qualification harnesses were **not** run to produce evidence here: this container cannot qualify, and the working tree was not a clean reachable commit for most of the pass. That is the provenance guard behaving as designed rather than an omission.

## What this pass did complete

1. **Browser trajectory parser `[0,1]` parity** — the one known deferred code defect, closed test-first against the frozen Domain rule.
2. **Qualification corpus and measurement harnesses** — deterministic, invariant-obeying, dependency-free, and runnable unchanged against PostgreSQL 18.
3. **An always-on N+1 regression guard** for the aggregate read.
4. **A reconciled obligation register** and the security/bounded-resource review, including one previously unrecorded P2.
5. **Corpus C1**, the cross-layer semantic trace Stage 1 did not have, which pinned two frozen rules that had been documented but never asserted.
6. **The analytical-unit and heatmap-envelope harnesses**, and with them a defect in the qualification corpus itself: visibility sequences issued from a local counter made the corpus nearly invisible to any reader's snapshot, so every §S and §T measurement the plan harness would have produced would have been taken over a near-empty database. The corpus now publishes under the real barrier and refuses to return a manifest a reader cannot see.
7. **A fail-closed qualification mechanism.** Two further review rounds found seven more ways the harness could report green without measuring its subject — the worst being that all 23 §S measurements used the non-analytic search and therefore exercised no §S predicate whatsoever. Every harness now states its expectations through `QualificationVerdict`, which separates an integrity failure (the measurement did not happen, fatal anywhere) from a missing qualification prerequisite (recorded, and fatal only on the required server), writes every expectation into the evidence, and refuses to call an unproven run evidence. Details in `2026-09-22-scene-analytics-s7-performance.md` §3c.

## Remaining work

Environment-bound items are listed with executable commands in the handoff report and in `2026-09-22-scene-analytics-s7-corpus.md` §4. Items 2, 9, 10 and 14 need further engineering as well as execution, and that engineering is not environment-blocked: the explanation/heatmap/UI legs of the C1 trace, the concurrency race probes, the failure-at-volume harness, and the UI acceptance pass.


## PostgreSQL 18 qualification addendum

The prior local qualification SHA was not repository-reachable, so its three JSON verdicts are superseded and close no gate. The repaired harness must be pushed and all three workloads rerun from the final PR #71 head. It does not close the C1 explanation/heatmap/UI trace, realistic-volume cancellation and deterministic races, real-worker/runtime-pack/GPU/CPU Development acceptance, operator workflow, accessibility or visual QA.
