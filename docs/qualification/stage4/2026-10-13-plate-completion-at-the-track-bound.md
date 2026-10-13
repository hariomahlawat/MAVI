# Stage 4 PR-3: synchronous plate completion at the 10,000-Track bound

**Kind.** Development evidence record (engineering measurement). It is not a qualification, a scale qualification or a CI gate.

**Question.** Does a plate completion at the supported bound complete synchronously, inside the request budget, with the visibility barrier held briefly? The bound is 10,000 Vehicle Tracks × 4 accepted crops under the bounded v1 profile (2 proposals, 1 plate, 3 readings) and the 64 MiB artefact cap. If it does not, a `Finalizing` hand-off would be needed. This is the attribute plane's question (S2b implementation record §5.2), asked of the plate plane.

## Method

**Command.** `MAVI_PLATE_TIMING_TRACKS=10000 dotnet test tests/Mavi.IntegrationTests --filter FullyQualifiedName~PlateCompletionTiming`. The test is `PlateCompletionTimingTests`.

**What it exercises.** The real lease, upload and completion routes and the real three-phase completion service, including:
- streamed artefact validation;
- the content-addressed seal;
- the binary-`COPY` fact writer;
- the visibility barrier.

It runs on PostgreSQL. The quality gate runs the same test at 200 Tracks.

**Shape: the row-worst shape the profile admits — not the byte-worst.** It maximises the rows and the work: every one of the 40,000 crops is scored with both proposals. It does not reach the artefact's byte bound (see *Sizes*). Each crop has:
- one plate, read with three readings above the floor;
- every raw text at the maximum 32 code units, each escaped as `\uXXXX`. These are fullwidth alphanumerics, which NFKC maps to ASCII, so every plate is read.

Every plate yields its own distinct Track text. The rows written per completion are:

| Table | Rows |
|---|---|
| `plate_track_outcomes` | 10,000 |
| `plate_observations` | 40,000 |
| `plate_readings` | 120,000 |
| `plate_track_texts` | 40,000 |
| **Total** | **210,000** |

**Phase timings.** These come from the publication log (event 2100, added in this change, mirroring attribute event 1990):
- phase A (fenced validation);
- streamed artefact validation;
- phase B (seal);
- phase C (publication) and its row writes;
- barrier hold.

**Wall time.** It is measured at the HTTP client.

**Memory.** Measured during the completion request only, with two figures:
- the process working set, sampled every 10 ms against its value just before the request;
- the managed bytes allocated meanwhile.

The platform runs in-process with the test client, so both figures are for the whole test process. They are an upper bound on the platform's share.

**Host.** Development laptop:
- Intel Core i7-10750H, 15.8 GiB RAM, Windows 11;
- .NET SDK 10.0.401;
- PostgreSQL 18.6 on localhost.

**Commit.** Branch `stage4/pr3-plate-lifecycle`, measured on the working tree of this commit.

**Runs.** Three runs, each in a fresh test process and database.

## Results

### Sizes

The sizes were identical in every run.

| Quantity | Measured | Limit | Use of limit |
|---|---|---|---|
| Lease response | 8,401,109 B | 16 MiB worker read cap | 50 % |
| `PlatePredictions` artefact | 48,540,608 B | worst-case bound 63,044,096 B (`WorstCasePredictionArtifactBytes(2, 1, 3)`) | 77 % of the bound |
| `PlatePredictions` artefact | 48,540,608 B | 64 MiB cap | 72 % of the cap |

**Byte headroom.** The measured artefact is 14,503,488 B below the worst-case bound and 18,568,256 B below the cap. The bound is an upper bound built from fixed per-element envelopes (for example 160 B per Track text and a maximum-length encoding of every number), which honest output does not fill; that bound — not this measurement — is what guarantees that every admitted artefact fits 64 MiB (vector `plate-artifact-bound-v1.json`). The timings here are for the row-worst shape; an artefact nearer the byte bound would add streaming and hashing time roughly in proportion to its bytes (artefact validation and the seal, ≈ 1 s here), not rows.
| Completion body | 44,821,697 B | 64 MiB cap | 67 % |

### Timings (ms)

| Run | Lease | Upload | **Completion wall** | Phase A | Artefact validation | Seal | Phase C (rows) | Barrier hold | Outside the phases¹ |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 855.3 | 345.4 | **8,303.1** | 1,246.0 | 829.4 | 184.6 | 4,470.6 (4,442.8) | 26.4 | 1,572.5 |
| 2 | 813.5 | 357.3 | **8,227.8** | 1,142.6 | 810.4 | 193.2 | 4,639.0 (4,614.1) | 23.9 | 1,442.6 |
| 3 | 877.2 | 340.3 | **7,993.8** | 1,123.8 | 788.5 | 187.1 | 4,525.1 (4,501.0) | 23.3 | 1,369.3 |

**Confirmation after the cold-review fixes** (the claim check runs only when a crop is reported unavailable, so it costs nothing at this shape): one more run on an isolated database gave lease 873.2 ms, upload 349.7 ms, completion wall **8,273.2 ms**, phase A 1,105.7 ms, artefact validation 812.6 ms, seal 186.4 ms, publication 4,661.1 ms (rows 4,633.1 ms), barrier 27.1 ms, managed allocation 897.5 MiB, with identical sizes — within run-to-run variation of the three runs above.

¹ Completion wall minus the four service phases. This is mostly reading and binding the 44.8 MB request body before the service runs.

### Memory during the completion request

| Run | Working set before | Peak working set | Increase | Managed bytes allocated |
|---|---|---|---|---|
| 1 | 610.3 MiB | 690.5 MiB | +80.2 MiB | 899.5 MiB |
| 2 | 1,179.0 MiB | 1,194.5 MiB | +15.6 MiB | 898.5 MiB |
| 3 | 1,229.7 MiB | 1,245.3 MiB | +15.6 MiB | 897.4 MiB |

The working-set increase depends on how much memory the GC already held from building the 93 MB test inputs, so it varies between runs. The managed allocation is the stable figure: about 0.9 GiB per worst-shape completion, of which the 210,000 domain rows and the parsed body account for most.

### Budgets

| Budget | Value | Respected? |
|---|---|---|
| Completion request (ADR-006 §7; the worker's `request_timeout_seconds` default) | 15 s | **Yes.** Worst 8.30 s, about 1.8× headroom |
| Barrier hold (reference: the vision publication's 1.67–2.29 s, `f4-configuration-freeze.md`) | — | 23–26 ms, about two orders of magnitude below |
| Lease during publication | Phase A extends the lease by one publication window (≥ 60 s, `Plates:LeaseSeconds`) | **Yes.** Seal plus publication take ≤ 4.9 s, so no reclaim can overtake them |
| Maximum analysis duration (`Plates:MaximumAnalysisDurationSeconds`, 6 h default) | 6 h | **Yes.** The completion is ≤ 8.3 s of it |

## Decision

**Synchronous completion stands.** The row-worst admitted shape completes in ≤ 8.3 s, inside the 15 s request budget. The visibility barrier is held for ≤ 26 ms. No `Finalizing` hand-off is required, so none is implemented. The test asserts:
- the artefact is within its worst-case bound and the 64 MiB cap;
- the completion body is within its cap;
- the 15 s budget is met.

**Recorded limits of this evidence:**
- **Headroom is narrower than the attribute plane's.** The plate plane has about 1.8×, against ≥ 4× for 80,000 attribute rows in ≤ 3.7 s.
  - Phase C is the main cost: about 4.5 s for 210,000 constrained rows, already written with binary `COPY`.
  - Reading the 44.8 MB body adds about 1.4 s.
  - If a slower host exceeds the worker's timeout, the worker replays the identical body: publication is one transaction, and the platform answers a replay of a committed completion. This costs time, not correctness.
  - Two optimisation candidates follow, should a host need them. Neither changes the contract, the profile or the normalisation.
    - The ~0.9 GiB allocation per completion.
    - Phase A's 1.1–1.2 s (lease-scope read plus typed validation).
- **Scope of the measurement.** It is one Development laptop, not CI and not a Production host profile. The 10,000-Track figures are opt-in (`MAVI_PLATE_TIMING_TRACKS`); the quality gate runs 200 Tracks.
- **Raw logs.** Raw run lines were kept outside Git at `E:\MAVI-Working\tmp\pr3\timing-run{1,2,3}.txt`.
