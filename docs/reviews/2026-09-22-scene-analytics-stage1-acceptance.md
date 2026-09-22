# Spatial & Temporal Track Analytics — Stage-1 acceptance status

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance`
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`

---

## Verdict

**Stage 1 is NOT closed.** The PostgreSQL 18 qualification streams are complete, but mandatory non-PG18 exit-gate evidence and one measured aggregate-materialisation P2 remain open. Nothing in this document, and nothing in the roadmaps, claims otherwise.

This slice is **partially complete**. What was executed is recorded truthfully below; what was not is explicitly marked and is not waived, re-scoped or softened.

## Independent PostgreSQL 18 reference environment

PostgreSQL 18.6 with pgvector 0.8.6 was executed natively on Ubuntu 24.04.4 LTS (x86-64, Xeon Platinum 8272CL, 17 GiB RAM, 2 .NET-available logical cores). PostgreSQL settings and complete methodology are recorded in the performance report. The real RTMDet/ByteTrack worker remains unavailable: no runtime pack/model weights/GPU were supplied.

## Exit gate

| # | Requirement | Status |
|---|---|---|
| 1 | Stage-1 functional acceptance met | **NOT EXECUTED** — depends on 2–6, 15 |
| 2 | C1 agrees across trajectory/facts/search/explanation/aggregate/heatmap/UI | **PARTIAL.** C1 is built and passing across trajectory → facts → §S search → §T aggregate (`SemanticAcceptanceTests`, expected answers hand-derived from the frozen rules before running). The trace does **not** extend to the bounded explanation, the heatmap or the UI projection |
| 3 | PG18 plan/timing for every §S predicate and §T aggregate at 10^5 facts | **PASS.** PostgreSQL 18.6, 110,000 facts, all 23 §S cases and all nine §T bucket/class cases with generated SQL and `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)` |
| 4 | Analytics-unit duration/rows for Development corpus and synthetic 1,000-Track run | **PARTIAL.** Synthetic 1,000-Track PostgreSQL 18 run PASS: 1,000 analysed, 0 unavailable, 7,576 facts in 4.089 s. Real Development scripted corpus remains NOT EXECUTED |
| 5 | Aggregate 10^5-fact qualification | **PASS with carried P2.** All nine cases completed; full-path timing, DB/app split, allocation and GC observations recorded. The unbounded materialisation design remains an open P2 |
| 6 | Heatmap 50-run/candidate envelope | **PASS.** Exactly 50 covered runs, 2,000 candidates/contributors and 48,000 samples; three repetitions at each of 48/96/128 widths |
| 7 | Both fan-out limits have evidence-backed decisions | **PASS.** Retain 50 runs / 2,000 Tracks; measured safely below one second without treating one machine as grounds to raise/remove protection |
| 8 | No demonstrated N+1/unbounded DB or evidence-I/O path | **PARTIAL.** N+1 disproven for the aggregate by an always-on test holding query count constant across geometry. **An unbounded materialisation path is OPEN (P2)** — see the security document |
| 9 | Cancellation/failure proven at realistic volume | **NOT EXECUTED.** Failure and cancellation are tested, but only on a one-Track world; the harness to run them against the C3 corpus is not written, so this is engineering work as well as a blocked execution |
| 10 | Snapshot/revision consistency under concurrency | **NOT EXECUTED** in this pass. Slice-4/6 barrier ordering tests exist; the deterministic race probes do not |
| 11 | Incomplete/unknown never appears as observed zero | **PASS** for the surfaces built in Slices 4–6, by existing tests: incomplete scopes render no figure and no map, and complete-zero renders as a real observation |
| 12 | Browser trajectory parser obeys `[0,1]` | **PASS** — fixed this pass, RED tests first, shared rule, complement tests guard the closed interval |
| 13 | Security/resource review has no open P1/P2 | **FAIL** — one open P2 (unbounded aggregate materialisation). No P1 |
| 14 | Operator workflow / accessibility / visual QA | **NOT EXECUTED** in this pass |
| 15 | Development offline/real-worker acceptance | **NOT EXECUTED — environment blocked** |
| 16 | No policy-violating dependency/runtime drift | **PASS** — no dependency added; `verify_repo.py` green |
| 17 | Relevant suites green | **PASS** — see §Validation below. The only integration failures are the PostgreSQL 18 prerequisite assertion, reproduced and explained |
| 18 | Documentation reflects measured reality | **PASS** for this pass's documents |
| 19 | Independent cold review has no P1/P2 | **FAIL.** Harness false-green defects are repaired and requalified, but PostgreSQL 18 measurement confirms the pre-existing aggregate-materialisation P2 remains open pending a semantics-preserving bound/server-side design |
| 20 | Zero unresolved material review threads | **PASS based on public REST state** — five author replies address the five automated findings; anonymous API access cannot independently read GitHub thread-resolution flags |
| 21 | Exact-head CI green | **PASS at reviewed head `aa17a19a`** (quality, deterministic-validation, windows-script-validation). Local commits require new CI |

## Validation

| Suite | Result |
|---|---|
| Domain | 195 passed |
| Application | 369 passed |
| Integration | 644 passed on PostgreSQL 18.6 |
| Frontend | 821 passed, typecheck clean, production build succeeds |
| `python tools/verify_repo.py` | PASSED |
| Dependency surface | unchanged — no diff in any `*.csproj`, `package.json` or `config/dependencies/` between the baseline and this head |

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

Qualification code commit: `4d110490b3413eda5cd36c171581c6560314ffc0`. All three mandatory harness facts passed, and each JSON verdict says `qualification evidence`. This closes only the PostgreSQL measurement portion. It does not close the C1 explanation/heatmap/UI trace, realistic-volume cancellation and deterministic races, real-worker/runtime-pack/GPU/CPU Development acceptance, operator workflow, accessibility or visual QA.
