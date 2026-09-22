# Scene Analytics Slice 7 — qualification corpus and harnesses

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance` (PR #70), with PR #71 integrated by fast-forward
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668` (PR #69, Slice-7 plan merged)
**Plan:** `docs/superpowers/plans/2026-09-22-scene-analytics-s7-hardening-acceptance.md` §6

---

## 1. Environment of this pass, and what it means for the evidence

| Item | Value |
|---|---|
| PostgreSQL in the current repair/handoff container | **16.15** (Ubuntu 16.15-0ubuntu0.24.04.1) — cannot qualify |
| PostgreSQL 18 used by the earlier, superseded pass | **18.6** (Ubuntu 18.6-1.pgdg24.04+2), pgvector 0.8.6, native cluster — real, but its commit was not repository-reachable; non-authoritative |
| **PostgreSQL 18 used for authoritative qualification** | **18.6**, pgvector **0.8.6**, Windows Development machine, port 5433, database `mavi_test`; clean tree at reachable SHA `5f5166628b0c4af04cc8f7efcd40f7022f5095c4` |
| Vision runtime | **Absent** — no `onnxruntime`, no `cv2`, no GPU, no model weights (weights are correctly never in Git) |

Consequences, stated once and applied throughout this slice's documents:

- PostgreSQL 18 qualification **PASSED** on the Development machine at exact reachable SHA `5f5166628b0c4af04cc8f7efcd40f7022f5095c4`. The earlier Ubuntu pass and its files remain superseded observations and are not reused.
- Real-worker Development acceptance **PASSED** on the same machine, including restart persistence. PostgreSQL qualification and real-worker acceptance are separate results; neither stands in for the other.

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
| **C3 heavy synthetic** | **PASS** — qualified at 110,000 relevant facts on the Development machine, SHA `5f516662…` | 40 runs × 250 Tracks; seed 20260922. The same deterministic shape the superseded pass had observed, now measured from a reachable commit |
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

The superseded local PostgreSQL 18 pass observed all 40 runs and meaningful §S/§T populations, but its commit provenance was not repository-reachable, so it qualified nothing and its raw files are not reused.

The fresh files it called for now exist: `plan-qualification.json`, `analytics-unit-throughput.json` and `heatmap-envelope.json` from the Development machine at `5f516662…`, each reporting `qualification evidence`. They are held outside the repository with SHA-256 hashes; see the performance report §8.

## 8. The real-stack scripted corpus (parent plan §Z, plan §4 item 10)

The parent plan asks for **three short FFmpeg-scripted videos** — line crossing, zone dwell then exit, stationary then depart — run through the real worker path (fixture detector) and the real analytics host, with expected facts derived from the scripted motion rather than by eye. Before this pass they did not exist: `tools/vision/dev/fixture_worker_harness.py` knew only the single PR-50 walk.

They now exist, with one source of truth, `tests/fixtures/scene-analytics/scripted-corpus-v1.json`:

| Scenario | Scripted motion (box centre, whole pixels, 640×360 at 25 fps, frames 25–274) | Expected facts, derived from the motion |
|---|---|---|
| `line-crossing` | straight up at 2 px/frame, then a slow drift right | exactly one crossing of *Kerb*, `AToB`, at 3,400 ms (bracket 3,360–3,440); no zone; heading N; never stationary |
| `zone-dwell-exit` | in from the left, a slow drift inside *Pad*, out to the right | one visit to *Pad*: entry 2,640–2,680 ms, exit 9,240–9,280 ms, dwell 6,560–6,640 ms, loitering against its 5 s threshold; heading E; never stationary |
| `stationary-then-depart` | held still for 7 s, then away to the right | one stationary interval from 1,000 ms ending 7,960–8,160 ms; the *Far* zone never entered; heading E |

Each scenario carries its derivation in prose beside its numbers. **Three things read the same file**, so none can drift from the others:

- **The videos.** `tools/vision/dev/scripted_corpus.py generate` renders them with ffmpeg; `verify` decodes every frame and checks the drawn box against the position model. All three verified exactly: 300 frames each, the box at the modelled pixel on every detection frame and absent on every other. Two generator defects were caught by `verify` on the way, which is why it exists: the `drawbox` filter evaluates its position once rather than per frame, and `overlay` in 4:2:0 snaps to the chroma grid and moved every odd-pixel box by one pixel. The generator composites in 4:4:4 and encodes H.264 at CRF 0, so luma is exact. The videos are generated, never committed.
- **The detections.** `MAVI_FIXTURE_SCENARIO=<scenario>` makes the fixture worker harness report exactly that box on each frame. The worker records one trajectory point per detected frame at the box centre, at the frame's media offset.
- **The expected facts.** `ScriptedCorpusTests` (Application suite) builds that trajectory and runs the **real engine** against each scenario's scene, asserting every expected fact. All three pass.

**One of my derivations was wrong, and the frozen rule was right.** The first line-crossing script moved at 0.87 px/frame, so the centre spent four samples inside the 3.6 px on-line band. Plan §K freezes that a Track which lingers in the band for more than k = 3 samples is not credited with a crossing, and the engine correctly reported none. The script now crosses at 2 px/frame. This is recorded as a **known characteristic of the frozen rule** rather than a defect: at 25 fps, a crossing slower than about 0.0033 of the frame height per frame is not counted.

**What is executed and what is not.** The videos, the detections model and the expected facts are verified here. The run through the real worker control plane and analytics host is **NOT EXECUTED** — this environment has no worker runtime environment — and is the Development-machine action in `docs/runbooks/scene-analytics-stage1-development-acceptance.md` §C, which ends in `scripted_corpus.py check`, asserting the analysed Track's facts through the API. The single `2min.mp4` real-video run does not substitute for these three.
