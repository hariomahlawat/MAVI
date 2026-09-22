# Scene Analytics Slice 7 — performance and bounded-resource evidence

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance` (PR #70), with PR #71 integrated by fast-forward
**Qualification candidate (measured):** `5f5166628b0c4af04cc8f7efcd40f7022f5095c4`
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`

---

## 1. Qualification status, stated first

**PostgreSQL 18 qualification: PASS**, on the Development machine, against exact repository-reachable SHA `5f5166628b0c4af04cc8f7efcd40f7022f5095c4`, from a clean tree. All three harnesses reported `qualification evidence`. Details and figures are in §8.

Three bodies of measurement appear in this report, and only one is authoritative:

| Section | Measurement | Standing |
|---|---|---|
| §4 | PostgreSQL 16.15 in the repair container | Engineering observations — PostgreSQL 16 cannot qualify |
| §6 | An earlier PostgreSQL 18.6 pass on Ubuntu | **Superseded, non-authoritative** — its named commit was not repository-reachable |
| §8 | The Development machine, PostgreSQL 18.6, SHA `5f516662…` | **Authoritative qualification evidence** |

The harness does not rely on a reader remembering this. `QualificationGate.CaptureEnvironmentAsync` reads the live `server_version`, records it beside every result, and computes `isQualificationGradeDatabase`. It is `false` for the PostgreSQL 16 engineering observations in §4. It read `true` for the superseded PostgreSQL 18 pass recorded in §6, which is precisely why the server check alone was not sufficient: the run was on the right server and still could not qualify, because its source provenance was not trustworthy. That is the gap the provenance guard now closes — and the §8 run passed it, on a clean tree at a resolvable, reachable commit.

## 2. Harnesses built

All under `tests/Mavi.IntegrationTests/Qualification/`, gated on `MAVI_QUALIFICATION=1`, **no new dependency**.

| Harness | Exit-gate item | What it measures |
|---|---|---|
| `PlanQualificationTests` | 3, 5 | Every §S predicate family (23, including all eight headings), and every §T aggregate at three bucket sizes × three class filters (unfiltered, Person, Vehicle) — nine measurements, because the class filter changes `BaseCandidates` and so the joins and cardinalities of every fact query. Each is timed across the whole §T path (repository fetch **and** `AnalyticsAggregator.Compute`, whose cost grows with facts and buckets) and `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)`-captured from the SQL the product actually issued |
| `ThroughputQualificationTests.OneAnalyticalUnit…` | 4 | One analytical unit over a synthetic 1,000-Track run with real sealed trajectories: duration, ms/Track, analysed and unavailable counts, rows written per fact table |
| `ThroughputQualificationTests.TheHeatmap…` | 6 | The heatmap at the **frozen** envelope — `MaximumHeatmapRuns` covered runs and `MaximumHeatmapTracks` candidates — at three grid widths |

Three always-on guards keep these from drifting into decoration:

- `TheMeasurementPlanNamesEverySearchPredicateTheContractDefines` reflects over `TrackAnalyticsQuery`'s primary constructor, so a §S predicate added in a later slice fails the build rather than quietly falling out of "every predicate".
- `TheEnvelopeMeasuredIsTheEnvelopeEnforced` reads `AnalyticsQueryRules`, so the harness cannot keep measuring a limit the product no longer has.
- `TheVersionThatQualifiesIsTheVersionTheProductRequires` reads `DatabasePrerequisiteOptions`, so the version that counts as qualification-grade cannot drift from the one the platform accepts.

## 3. A defect in the harness, found by running it

The first heatmap-envelope run built 50 runs and 2,000 Tracks and then reported **0 covered runs, 0 candidate Tracks**, while the heatmap itself contributed 40 Tracks, then 40, then 80 across three successive calls.

**Cause.** The corpus assigned completion visibility sequences from a local counter (1, 2, 3 …). A reader allocates its snapshot from the database's `processing_visibility_sequence` and admits only rows at or below it. On a freshly reset database the first reader's snapshot is 1, the second's 2 — so a corpus numbered locally is almost entirely *invisible*, and each successive call sees one more run.

**Consequence, which is the serious part.** The already-committed `PlanQualificationTests` shares that corpus. Every §S and §T measurement it would have produced on the Development machine would have been taken over a near-empty database: fast, plausible-looking and meaningless. The bug survived the earlier smoke run because a harness that writes an evidence file and asserts the file exists does not notice that every row count in it is zero.

**Fix.** The corpus now publishes the way the pipeline does — one transaction per video, the completion barrier held across a real `nextval` — and, before returning a manifest, takes a reader's own snapshot and refuses to hand back a corpus that snapshot cannot see.

**After the fix:** all 23 §S predicate families return rows and the aggregate sees its facts.

## 3b. Three further defects in the harness, from independent review

All three were in the harness rather than the product, and all three would have produced qualification evidence that looked fine.

1. **The default corpus was half the required volume.** 40 runs × 120 Tracks × 11 facts is **52,800** relevant facts, not the 528,000 a comment claimed — a tenfold arithmetic error on my part. Since those defaults drive the unchanged PostgreSQL 18 command, every §S and §T plan would have been measured below the mandatory 10⁵ prerequisite. Defaults are now 40 × 250 = 110,000 (11.0 facts per Track, confirmed by measurement rather than by arithmetic), the fact count and the prerequisite are both written into the evidence file, and a run on the required server **fails** if the corpus is undersized rather than quietly reporting it.

2. **The §T timer stopped at the repository.** `AggregateAsync` only materialises the fact set; the counting rules — occupancy, unique tracks, repeated visits, the per-bucket series — are `AnalyticsAggregator.Compute`, and their cost grows with facts and buckets. The reported latency was one an operator never experiences. The clock now spans both.

3. **The class-filtered §T path was never planned.** Every aggregate measurement passed `null` for the object class, so the filtered path — which changes `BaseCandidates` and therefore the joins and cardinalities of every fact query — went unmeasured. Now measured as its own case: at a 4-run shape check the filters partition cleanly (1,992 Person + 1,008 Vehicle = 3,000 unfiltered visits), so they are demonstrably not the unfiltered call in disguise.

4. **The throughput harness returned green when nothing was claimable.** A regression in corpus construction or lifecycle eligibility would have passed the qualification command having measured no throughput at all — the same shape of silent emptiness as the visibility defect above. It now writes the diagnostic and then fails.

5. **`isQualificationGradeDatabase` accepted 18 or later.** The platform's own prerequisite check is an equality, so a run against 19 is a run against a planner the product refuses; labelling it qualification-grade would let it be presented as satisfying the PostgreSQL 18 exit gate. It now requires exactly 18, and an always-on test pins that number to the product's.

## 3c. A second independent review, and the worst defect yet

A cold review of the harness found three more ways a PostgreSQL 18 run could report green without having measured its subject. Auditing around them found three more again. All are fixed, and the fix is a shared mechanism rather than six patches, because this is now the third time the same shape of mistake has appeared.

### The §S measurements never exercised a single §S predicate

`PlanQualificationTests` called `TrackSearchRepository.SearchAsync`. That method applies only the **non-analytic** base candidate set — camera, window, class — and discards the analytics query entirely; the §S predicates live in `SearchAnalyticsAsync`.

So all 23 §S predicate families planned and timed **the same plain Track search**, while the evidence named a different predicate each time. Nothing looked wrong: rows came back, the plans were real `EXPLAIN` output, the file was complete.

The evidence from before the fix shows it plainly — every predicate returning exactly the page size, from exactly one database query:

| Predicate | rows | DB queries |
|---|---|---|
| `zoneId (default dwelled)` | 50 | 1 |
| `motionDirection=N` … `NW` | 50 each | 1 each |

and the captured SQL for `motionDirection=N` referenced `tracks` and **none** of `track_motion_summaries`, `track_zone_visits`, `track_line_crossings`, `track_zone_summaries`, `scene_analyses`.

After the fix, the same shape check over a 120-Track corpus:

| Predicate | rows | DB queries |
|---|---|---|
| `zoneId (default dwelled)` | 51 | 8 |
| `motionDirection=N` | 18 | 8 |
| `motionDirection=NE` | 13 | 8 |
| `motionDirection=E` | 15 | 8 |
| `motionDirection=SE` | 17 | 8 |
| `motionDirection=S` | 10 | 8 |
| `motionDirection=SW` | 14 | 8 |
| `motionDirection=W` | 16 | 8 |
| `motionDirection=NW` | 17 | 8 |

The eight headings now sum to 120 — the whole population, partitioned — which is what a real `motionDirection` filter must do.

This is exit-gate item 3. Had PostgreSQL 18 been available before this review, the slice would have produced a complete plan/timing document for "every §S predicate" in which no §S predicate was ever planned.

### The other five

| Finding | Why it could pass falsely | Repair |
|---|---|---|
| Throughput green despite failed or partial execution | The only acceptance assertion was that the evidence file existed, so a failed executor, a short population or missing facts all passed | Ten integrity expectations derived from product semantics: unit succeeded, every Track analysed, none unavailable, one outcome and one motion summary per Track, one zone summary per Track per zone, visits and crossings both exercised, unit `Completed` and published |
| Heatmap envelope not proven | Resolved scope and service result were recorded but never asserted, so a fraction of the corpus — or none — still emitted a timing file | Scope must equal the product's own `MaximumHeatmapRuns` and `MaximumHeatmapTracks`; every measurement must succeed, have every candidate contribute, read exactly `candidates × sealed samples`, honour the requested grid width and produce a populated grid |
| §S/§T could measure nothing | Corpus volume was enforced but not per-measurement meaning | Each measurement must be valid, capture SQL, produce a real `EXPLAIN` plan, reach the fact table its predicate names, and select from the corpus |
| SQL or plan capture could vanish silently | Zero captured statements produced zero plans and stayed green | Captured-statement count and plan text are now expectations |
| Stale evidence could be mistaken for current | A run that threw left the previous run's complete, plausible file in place | Each harness claims its filename first with an explicitly incomplete record, so a failed run leaves a file that says so |
| `MAVI_QUALIFICATION=true` skipped silently | Only `1` enabled the pass; anything else was treated as unset | Any other value throws — an operator who believes the qualification ran must not be told it passed |
| Overrides could shrink a qualification run | `MAVI_QUAL_UNIT_TRACKS=20` produced a file headed "1,000-Track run" | The workload shape is a qualification prerequisite, recorded and enforced on the required server |
| Provenance could not identify the binary | `gitSha` reports the parent commit of a dirty tree quite happily | The built assembly's module id and build timestamp are recorded beside it |

### The mechanism, not the six patches

Every harness now routes its expectations through `QualificationVerdict`, which separates two things that were previously conflated:

- **Integrity** — the measurement did not exercise its subject. Fatal on any server, because a harness that measured the wrong thing is broken on PostgreSQL 16 just as much as on 18.
- **Prerequisite** — the run is real but cannot be called qualification evidence (server version, corpus volume, workload shape). Fatal only on the required server; elsewhere recorded, and the run stays an engineering observation.

Every expectation is written into the evidence file beside the numbers it qualifies, and the file names its own status: `qualification evidence`, `engineering observation — not qualification evidence`, or `qualification failure`. The governing rule is that no evidence is better than false evidence, so an unmet expectation fails the run — and the evidence is still written, so the failure can be investigated. Qualification-grade runs additionally require a clean working tree and a reported SHA that resolves to a local commit object; pushed/repository reachability remains an external handoff check because qualification must also work offline.

## 3d. The provenance round, and why a right-server run still failed to qualify

The PostgreSQL 18 pass in §6 was executed on the correct server, completed its workloads, and wrote three evidence files whose own verdicts read as satisfied. It still cannot qualify PR #71, and the reason is worth stating plainly because it is a class of false-green the earlier rounds did not cover: **the harness knew what database it was talking to, and nothing about where its own code came from.** The commit its evidence named was not reachable in the repository, so the numbers described a source state nobody can check out.

Four findings came out of that review, and all four are repaired here.

| Finding | Root cause | Repair |
|---|---|---|
| **P1** — evidence referenced an unreachable commit | The gate recorded `gitSha` from `.git/HEAD` and never asked whether that SHA resolved, or whether the tree it was built from was clean | `RequireRepositoryProvenance` adds two qualification prerequisites — clean working tree, and a reported SHA that resolves to a local commit object — wired into all three heavy harnesses. Both are captured from live `git`, and a missing signal is refused rather than assumed |
| **P2** — heatmap cold/warm labelling was wrong | Repetition 1 of *each* width was called cold-ish, but all widths share one process, so only the very first call is anything like cold | A single global invocation counter: invocation 1 is `cold-ish`, 2+ are `warm`. Grid width, repetition within width, global invocation number and cache state are all recorded. The workload is unchanged, and no process isolation was added to manufacture a cold sample |
| **P2** — qualification documentation contradicted itself | The same head was described as both PASS on PostgreSQL 18 and not qualification evidence | Each environment now carries one standing: this container's PostgreSQL 16 is observations, the earlier PostgreSQL 18 pass is superseded, and qualification was pending a reachable-head rerun — since satisfied by the Development-machine run in §8. The PASS claims drawn from the superseded run are gone |
| **P2** — exact-head CI marked PASS from the parent SHA | PR #70's green checks were read as PR #71's | Exit-gate item 21 is PENDING until every required workflow passes on the final pushed PR #71 head. A parent-head result does not qualify a child head whose executable code differs |

**What the guard does not claim.** A clean tree plus a resolvable commit is an inference, not an attestation: it does not cryptographically bind the compiled assembly to that commit. It is deliberately the simplest check that closes the observed hole, and the evidence records `testAssemblyModuleId` and `testAssemblyBuiltUtc` beside it so a reader can tell which binary produced a file. Pushed-to-remote reachability stays an external handoff check, because qualification has to work on a disconnected Development machine.

## 4. Engineering observations (PostgreSQL 16.15, NOT qualification)

Environment: Ubuntu 24.04, 4 logical cores, .NET 10.0.12, PostgreSQL 16.15, pgvector 0.6.0, `shared_buffers` 128MB, `work_mem` 4MB.

### 4.1 Analytical unit

| Tracks | Duration | Per Track | Outcome |
|---|---|---|---|
| 20 (shape check) | 586 ms | 29.3 ms | 20 analysed, 0 unavailable |

Not run at 1,000 here; the harness takes `MAVI_QUAL_UNIT_TRACKS` and defaults to 1,000 on the Development machine.

### 4.2 Heatmap at the frozen envelope

50 covered runs, 2,000 candidate Tracks, all 2,000 contributing, 48,000 samples read from disk through the production evidence reader:

| Grid width | Cells | Duration |
|---|---|---|
| 48 | 1,296 | 332 ms |
| 96 | 5,184 | 293 ms |
| 128 | 9,216 | 288 ms |

Cost is dominated by evidence I/O rather than grid size, which is what the design predicts: the same 48,000 samples are read regardless of how finely they are binned. **This is not a basis for an acceptance decision** — the envelope decision belongs to a PostgreSQL 18 run.

## 5. Open finding carried forward (still OPEN — see §8.3)

**P2 — the aggregate read materialises an unbounded number of fact rows.** Query *count* is constant in geometry (proven by an always-on test at 4 zones/2 lines versus 12 zones/6 lines), so there is no N+1. Row *volume* is bounded only by the requested window. A limit decision requires PostgreSQL 18 measurement, and the parent brief forbids introducing speculative indexes, caches or limits from PostgreSQL 16 observations alone. It therefore stays open, recorded, and assigned to the qualification run.


## 6. The superseded independent PostgreSQL 18 pass (observations only)

**Status: superseded by §8.** The measurements below came from the earlier local pass and are retained only as historical observations. Review established that its claimed SHA was not repository-reachable, so they are not qualification evidence. The reachable-head PostgreSQL 18 run it called for has since been made on the Development machine at `5f516662…` and passed; that run, in §8, is authoritative, and nothing in this section may be cited in its place.

### Reference environment and method

- Ubuntu 24.04.4 LTS, Linux 6.18.44, x86-64; Intel Xeon Platinum 8272CL; 3 host-visible CPUs / 2 .NET process-available cores; 17 GiB RAM; overlay filesystem with 32 GiB total and 29 GiB free. No host or PostgreSQL tuning was performed.
- PostgreSQL `18.6 (Ubuntu 18.6-1.pgdg24.04+2)`, pgvector `0.8.6`; `shared_buffers=128MB`, `work_mem=4MB`, `effective_cache_size=4GB`, `maintenance_work_mem=64MB`, `max_parallel_workers_per_gather=2`, `random_page_cost=4`, `jit=on`; native Ubuntu cluster, no container/resource limit added.
- .NET 10.0.12; deterministic seed `20260922`. Corpus setup was excluded from per-query timing. §S/§T ran sequentially after corpus construction. In the single heatmap process only the first overall call is `cold-ish`; all eight subsequent calls are `warm`. No fastest-run selection.
- Superseded command: `MAVI_QUALIFICATION=1 MAVI_QUALIFICATION_OUT=/tmp/mavi-qual-4d11049 MAVI_TEST_DB_CONNECTION=... dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --no-restore --filter '<the three qualification facts>'`. Its timings below are retained only to explain the prior decision; they do not qualify PR #71.

### §S and plans

The generated corpus held 40 runs, 10,000 Tracks, 4 zones, 2 lines and **110,000 relevant facts** (30,000 visits, 20,000 crossings, 40,000 zone summaries, 10,000 motion summaries, 10,000 outcomes). All 23 cases passed, including all eight motion headings, combinations, explicit revision/algorithm identity, zone relations, dwell, line/direction, stationary and loitering. Every analytic case returned 51 rows (the requested page plus continuation probe), issued a bounded 7–9 statements, referenced its expected analytics table, and had captured `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)`. Representative complete-path timings were 451 ms (`lineId`), 497 ms (`sceneRevisionId`), 517 ms (zone+motion+stationary+loitering), and 1,712 ms (`zoneId` cold-ish).

Across the captured statements PostgreSQL used index/index-only scans extensively (879/132 occurrences), with 32 sequential scans at small or broad intermediate relations, 57 hash joins and 712 nested loops. No external sort or disk spill was reported; maximum individual plan execution time was 986 ms. The broad sequential scans were not demonstrated pathological at this corpus and no speculative index was added. Query count remained bounded; no N+1 growth was observed.

### §T and the open materialisation question

Every combination of 60/900/3,600-second buckets and unfiltered/Person/Vehicle class was measured through database materialisation **and** application aggregation. Unfiltered cases materialised 30,000 visits, 20,000 crossings, 26,565 summaries and 10,000 intervals; Person materialised 19,920/13,280/17,653/6,640 and Vehicle 10,080/6,720/8,912/3,360. Every case used 10 database statements.

| Bucket / class | DB ms | App ms | Total ms | Allocated | GC 0/1/2 |
|---|---:|---:|---:|---:|---:|
| 60 / any | 2,673 | 4,849 | 7,522 | 41.8 MiB | 3/3/2 |
| 60 / Person | 2,149 | 2,996 | 5,145 | 32.1 MiB | 1/0/0 |
| 60 / Vehicle | 941 | 1,452 | 2,393 | 15.9 MiB | 1/0/0 |
| 900 / any | 2,241 | 302 | 2,542 | 37.4 MiB | 2/1/1 |
| 3,600 / any | 2,590 | 117 | 2,707 | 36.8 MiB | 2/1/1 |

The evidence confirms linear row-volume and allocation exposure even though query count is bounded. At 110,000 relevant facts it completed without spill or failure, but the 60-second unfiltered case consumed 7.5 seconds and 41.8 MiB of managed allocation. **Conclusion on the carried P2:** do not disguise the response cap as a work bound and do not add a speculative row cutoff that would make aggregates wrong. Retain the implementation for this slice, explicitly carry a P2 to design a semantics-preserving server-side aggregation or documented scope bound before a wider production envelope. The measurement streams completed without integrity failure, but nothing here is a pass: the pass/fail decision on the carried P2 belonged to the reachable-head rerun, which has now happened (§8) but whose §T figures have not yet been transcribed or dispositioned — see §8.3. Stage 1's “no open P1/P2” exit item remains unmet.

### Analytical unit

The requested and claimed population was 1,000 Tracks. All 1,000 were analysed, 0 unavailable, the unit finished `Completed` and published visibility sequence 2. In 4,089 ms (244.6 Tracks/s), it wrote 1,000 outcomes, 185 visits, 4,000 zone summaries, 1,391 crossings and 1,000 motion summaries.

### Heatmap envelope and recommendation

Scope resolution proved exactly **50 covered runs and 2,000 candidate Tracks**. Every one contributed; every call opened the deterministic population and read 48,000 samples. Timings in execution order were: width 48, 738/675/570 ms (median 675); width 96, 540/591/537 ms (median 540); width 128, 611/451/571 ms (median 571). Grids contained 1,296/5,184/9,216 cells. The result remained well below one second here with no integrity failure.

**Provisional recommendation, since confirmed by the authoritative run (§8.3): retain both 50-run and 2,000-Track bounds.** The envelope is safe on this constrained Development reference process and protects evidence I/O fan-out; one machine's speed is not a reason to raise or remove a resource guard. Cancellation phase timing, evidence-byte totals and per-phase read/SHA/decode/grid timings are not exposed by the current seam and remain observations not claimed by this pass.

## 7. Validation of the current PR #70 head

Executed in the repair container on **PostgreSQL 16.15**. Ordinary-suite results only; not qualification evidence. This head adds tests, fixtures and Development tooling after the measured SHA; it changes no production source file and none of the qualification harnesses or their shared corpus (see the Stage-1 register, *The measured SHA and the current head*).

| Suite | Result |
|---|---|
| Domain | 195 passed |
| Application | 373 passed (369 + the four `ScriptedCorpusTests` cases) |
| Integration | **657 passed, 2 failed of 659** — the eight new resilience, race-probe and C1-contract tests pass; both failures are `DatabaseStartupMigrationTests` asserting the PostgreSQL 18 prerequisite against 16.15, which pass in CI's PostgreSQL 18 job |
| Frontend | 826 tests pass (821 + the five C1 operator-contract tests); typecheck clean; production build succeeds |
| `python tools/verify_repo.py` | PASSED |
| Evidence-assembler guard coverage | 52/52 guards pinned |
| Dependency surface | Zero files differ from `main` across `*.csproj`, `package.json`, lockfiles and `config/dependencies/` |

Exact-head CI is reported on PR #70 and nowhere else.

## 8. Development-machine PostgreSQL 18 qualification — authoritative

**Status: PASS**, on exact reachable SHA `5f5166628b0c4af04cc8f7efcd40f7022f5095c4`.

### 8.1 Environment and provenance

- Windows Development machine; PostgreSQL **18.6**; pgvector **0.8.6**; port 5433; qualification database `mavi_test` (the live Development database `mavi_dev` was not used for qualification).
- The candidate tree was **clean** and the SHA was **repository-reachable**, which are exactly the two prerequisites the provenance guard (§3d) enforces before a run may call itself evidence.
- The three evidence files are held outside the repository by the operator and SHA-256 hashed. They are not committed and no repository path is claimed for them.

### 8.2 Results

| Harness | Result | Key figures |
|---|---|---|
| `PlanQualificationTests` | **PASS** — `qualification evidence` | §S/§T corpus at **110,000** relevant facts; every §S predicate family and every §T aggregate planned and timed — `plan-qualification.json` |
| `OneAnalyticalUnitOverASyntheticThousandTrackRunIsTimed` | **PASS** — `qualification evidence` | 1,000 Tracks; 1,000 analysed; 0 unavailable; unit `Completed`; ≈3.11 s, ≈3.11 ms/Track; rows written 1,000 outcomes, 4,000 zone summaries, 185 zone visits, 1,391 line crossings, 1,000 motion summaries — `analytics-unit-throughput.json` |
| `TheHeatmapIsTimedAtItsFrozenFanOutEnvelope` | **PASS** — `qualification evidence` | 50 covered runs; 2,000 candidate Tracks; 2,000 contributing; 48,000 samples — `heatmap-envelope.json` |

The throughput figures are internally consistent with the harness's own integrity expectations: 4,000 zone summaries is exactly one per Track per zone at the default four zones, and 1,000 outcomes and 1,000 motion summaries are one per analysed Track.

**Cross-OS determinism, observed rather than assumed.** The Windows Development run wrote exactly the rows the superseded Ubuntu pass (§6) had written from the same seed: 185 zone visits, 1,391 line crossings, 4,000 zone summaries, 1,000 outcomes, 1,000 motion summaries. The superseded pass cannot qualify anything, but agreement to the row between two operating systems is independent evidence that the seeded corpus and the engine are deterministic — which the parent plan requires, and which timings alone could never show.

### 8.3 Decisions this evidence supports, and the one it does not yet

- **Heatmap fan-out limits — RETAIN both 50 runs and 2,000 Tracks.** The product completed its full envelope with every integrity expectation met: every candidate contributed and every sealed sample was read. That is evidence the limits are workable. It is not evidence for widening them; one machine's headroom is not a reason to loosen a resource guard. Not measured by this harness, and so not claimed: plan §10's 1/5/10/25-run sweep, per-phase read/SHA/decode/grid timings, and cancellation latency.
- **Aggregate materialisation P2 — still OPEN, BLOCKED on transcription.** The authoritative `plan-qualification.json` contains, per §T case, the rows materialised, database and application time, allocated bytes and GC deltas the security review asks for. It is held outside the repository and was not available to the environment that prepared this revision, so its figures are not transcribed here and no number from another run is put in their place. `tools/qualification/summarize_aggregate_qualification.py` prints exactly those rows, with the file's SHA-256 and provenance, and refuses (exit 1) a file that is not qualification evidence. The decision rule to apply to them — written before they are seen, and awaiting the owner's approval — is in the security review §1.

  **Paste the summariser's output here:**

  *(pending — Development-machine action A in `docs/runbooks/scene-analytics-stage1-development-acceptance.md`)*

- **Development-corpus unit (exit-gate item 4a) — pending an operator read.** `tools/qualification/development-unit-record.sql` reads each unit's final-attempt duration, analysed/unavailable counts and rows written per fact table straight from `mavi_dev`. It was checked against a fresh 1,000-Track unit here, where it agreed row for row with the harness (1,000 / 185 / 4,000 / 1,391 / 1,000). Runbook action B.
