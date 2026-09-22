# Scene Analytics Slice 7 — qualification corpus and harnesses

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance`
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668` (PR #69, Slice-7 plan merged)
**Plan:** `docs/superpowers/plans/2026-09-22-scene-analytics-s7-hardening-acceptance.md` §6

---

## 1. Environment of this pass, and what it means for the evidence

| Item | Value |
|---|---|
| PostgreSQL qualification server | **18.6** (Ubuntu 18.6-1.pgdg24.04+2), pgvector 0.8.6 |
| PostgreSQL 18 available | **Yes** — native Ubuntu cluster on port 5432; no container |
| Vision runtime | **Absent** — no `onnxruntime`, no `cv2`, no GPU, no model weights (weights are correctly never in Git) |

Consequences, stated once and applied throughout this slice's documents:

- The independent PostgreSQL 18 §S/§T, analytical-unit and heatmap streams are **PASS** on code commit `4d110490b3413eda5cd36c171581c6560314ffc0`.
- Real-worker Development acceptance remains **NOT EXECUTED — environment blocked**; PostgreSQL qualification does not waive it.

## 2. What was built

All tooling lives in `tests/Mavi.IntegrationTests/Qualification/` and adds **no dependency**.

| File | Purpose |
|---|---|
| `QualificationGate.cs` | The opt-in switch, the evidence output contract, and live capture of the reference environment — including the PostgreSQL version that decides whether a run qualifies at all |
| `QualificationCorpus.cs` | Deterministic seeded corpus generator |
| `QualificationScene.cs` | Geometry parameterised by zone/line count, so geometry count is a variable dimension |
| `SqlCapture.cs` | Records the SQL the product actually issued and replays it under `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)` |
| `PlanQualificationTests.cs` | Every §S predicate and every §T aggregate, planned and timed |

### Corpus integrity

Every row is created through the **real domain factory** and the **real DbContext**, so domain invariants, foreign keys, unique constraints and check constraints all apply. Analytical units are driven through the genuine lifecycle — `Queue` → `Claim` with a real claim-token hash → `Complete` with the attempt count, token and visibility sequence — rather than by writing status columns directly. Runs are completed and given a visibility sequence exactly as the pipeline does.

This was not a formality. The domain and the schema rejected three separate generator bugs during development, each of which would have produced a corpus the product could never have created:

1. negative Track offsets, from a sign-wrapping cast in the seeded generator;
2. a motion summary whose longest stationary run exceeded its total;
3. a shared source-video digest, refused by `ux_artifacts_source_video_sha256`.

A generator that wrote rows directly would have "succeeded" at all three and measured queries against impossible data.

### Determinism

The seeded sequence is a written-out linear congruential generator, not `System.Random`, whose output is explicitly not guaranteed stable across runtimes. The same seed must rebuild the same corpus on the Development machine as here. The manifest records seed, camera, revision, geometry ids, run ids, window and every fact-family count.

## 2b. Fail-closed measurement

Building a valid corpus is necessary and not sufficient: a harness can hold a perfect corpus and still measure nothing over it. Two later review rounds found seven ways that could happen here, including one in which every §S predicate measurement ran the non-analytic search and so exercised no predicate at all.

Every harness now declares its expectations through `QualificationVerdict` and refuses to call an unproven run evidence. The distinction it enforces:

| State | Meaning |
|---|---|
| `qualification evidence` | On PostgreSQL 18 exactly, with every integrity and prerequisite expectation met |
| `engineering observation — not qualification evidence` | The measurement happened and is sound, but the run cannot qualify — usually the server version or corpus volume |
| `qualification failure` | The harness could not show it measured its subject. The evidence file is still written, and is not evidence |
| absent | NOT EXECUTED — the gate was closed |

Integrity expectations are fatal on any server, because a measurement that did not exercise its subject is broken regardless of where it ran. Prerequisite expectations are fatal only where the run could otherwise have been filed as qualification evidence.

## 3. Corpus coverage against plan §6

| Corpus | Status | Note |
|---|---|---|
| **C3 heavy synthetic** | **PASS** — built and measured at 110,000 relevant facts | 40 runs × 250 Tracks; 30,000 visits, 20,000 crossings, 40,000 zone summaries, 10,000 motion summaries and 10,000 outcomes; seed 20260922 |
| **C2 representative operational** | **Partially built** — the same generator at representative scale | The existing `SceneAnalyticsWorld` and the visual-QA fixtures already serve the operator-path and UI acceptance cases |
| **C1 semantic reference** | **PARTIAL** — authored trajectory passes trajectory → facts → §S → §T | The bounded explanation, heatmap and UI projection legs remain owed |

C1 is deliberately generated by hand rather than by seed: its value is that a human states the expected answer, which a generator cannot do.

## 4. Running it

```bash
MAVI_QUALIFICATION=1 \
MAVI_QUALIFICATION_OUT=/path/to/evidence \
MAVI_TEST_DB_CONNECTION="Host=localhost;Port=5432;Database=mavi_qual;Username=postgres;Password=..." \
dotnet test tests/Mavi.IntegrationTests --filter "FullyQualifiedName~Qualification"
```

Nothing in the harness is version-specific. The identical command produces the qualification evidence once `MAVI_TEST_DB_CONNECTION` points at PostgreSQL 18; the emitted `environment` block records which server answered.

## 5. Smoke run on this container (engineering evidence only)

- Corpus: 2 runs × 5 Tracks, 4 zones, 2 lines → 90 relevant facts.
- 26 measured families: 23 §S predicate families (including all eight `motionDirection` values) and 3 §T aggregate bucket sizes.
- Real `EXPLAIN (ANALYZE, BUFFERS)` plans captured for every one, with actual-versus-estimated rows, buffer counts, scan and sort types.
- Evidence file: `plan-qualification.json`, 390 KB.

**No latency number from this run is quoted as an objective or an acceptance result**, because the corpus was 90 facts on PostgreSQL 16. The run proves the harness works end to end; it qualifies nothing.

## 6. Observation carried into the performance document

The §T aggregate issues **10 database round trips** per call, not the four fact reads visible in `ReadFactsAsync` — the remainder is snapshot and scope resolution. That count is now pinned as **constant with respect to geometry** by `AnalyticsQueryShapeTests`, which runs in the ordinary suite.


## 7. PostgreSQL 18 evidence disposition

The live reader snapshot saw all 40 generated runs, and every §S predicate selected meaningful rows. Class-filtered §T populations differed and partitioned the deterministic Person/Vehicle population. A deliberately undersized PostgreSQL 18 smoke run failed closed (including empty heading cases and the 100,000-fact prerequisite), while the default 110,000-fact run emitted `qualification evidence`. The three raw files are `plan-qualification.json`, `analytics-unit-throughput.json`, and `heatmap-envelope.json`; the final exact-head copies are retained under `/tmp/mavi-qual-final-head/`. They are environment artefacts and are not committed.
