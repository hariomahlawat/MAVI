# MAVI Stage 2 — S1.4 F4 M1→M2 Execution Plan

**Status:** execution-grade plan for the interval after F4-A and before authoritative qualification.  
**Date:** 2026-09-25  
**Starting point / M1:** `main@aa30054478a13248d8bbfb6e1a228359b7d8645d` (merge of PR #95, F4-A harness/checker).  
**Parent plan:** `docs/superpowers/plans/2026-09-25-s1-4-b3-f4-qualification-closure-implementation.md`.  
**Scope:** exploratory B3-A/B3-B at M1, configuration derivation, U1 Finalizing UI, F4-C freeze/activation, and definition of M2.  
**Non-goal:** no authoritative B1–B6 verdicts, no closure record, no S2 capability work.

---

## 1. Purpose

F4-A is now on `main` and gives us the qualification machinery. The next work is deliberately separated into three stages:

1. **Exploratory measurement at M1** — validate the full 10,000-Track / 50,000-object harness and obtain the measurements needed to derive production finalizer timing values.
2. **U1** — make the existing truthful `phase="finalizing"` and failed-finalization state distinct in the operator UI.
3. **F4-C** — freeze the measured finalizer configuration, activate completion 3.1 / Finalizing as the shipped default, and merge to create **M2**.

Only M2 is eligible for authoritative S1.4 qualification.

The rule is: **measure M1 to choose configuration; qualify M2 to prove the shipped configuration.**

---

## 2. Starting invariants at M1

At `aa30054478a13248d8bbfb6e1a228359b7d8645d`:

- F4-A qualification checker/schema and B3-A/B3-B/crash harnesses are on `main`.
- `VisionFinalization:Enabled` remains `false` in shipped configuration.
- worker `completion_schema_version` remains `"3.0"` by default.
- asynchronous finalization can be enabled by the qualification harness, but it is not yet the shipped default.
- no authoritative F4 evidence exists.
- B1–B6 and disconnected remain OPEN.
- U1 has not landed.
- F4-C has not started.
- PR #87 remains historical and must not be cited by F4.

Any product change other than U1 or the reviewed F4-C freeze is outside this plan and is a stop condition.

---

## 3. Overall sequence

Execute in this order:

1. Record M1 identity and host identity.
2. Run exploratory B3-A at the full envelope.
3. Run exploratory B3-B at the full envelope.
4. Run the reduced/full crash harness only as needed to validate the activation decision; authoritative crash evidence waits for M2.
5. Derive candidate finalizer configuration mechanically from the retained M1 outputs.
6. Review the derivation; if any activation stop condition is hit, stop F4 and report.
7. Implement and merge U1.
8. Implement F4-C using the reviewed derived values.
9. Independently review F4-C.
10. Merge F4-C after U1.
11. The F4-C merge commit is **M2**.
12. Freeze M2: no behavior-bearing changes before authoritative qualification.

Do not combine U1 and F4-C into one PR.

---

## 4. Stage E1 — M1 exploratory qualification

### 4.1 Branching and repository state

Exploratory measurements are run against exact:

`aa30054478a13248d8bbfb6e1a228359b7d8645d`

The checkout must be:

- detached or branch at exact M1;
- clean;
- commit object present;
- no uncommitted harness changes;
- no locally modified `appsettings.json`;
- no locally modified worker default;
- no configuration outside the committed files: no `appsettings.development.machine.json` or `MAVI_MACHINE_CONFIG`, no `VisionFinalization__*` environment variable, and no `Command Timeout` in `MAVI_TEST_DB_CONNECTION`. The checker requires the output's effective configuration and command timeout to equal M1's committed values (§6.1).

The harness may enable asynchronous finalization through its test-only controls exactly as designed by F4-A. That does not change the measured source SHA.

Harness, checker and fixture surfaces are frozen from M1 until M2: `tests/Mavi.IntegrationTests/Qualification/**`, `tools/qualification/**` and `tools/web-visual-qa/**`. A change to any of them after an exploratory run discards that run (master §6 rule 1). Exploration then restarts at the new merge commit, which becomes the new M1, and the freeze document cites it.

### 4.2 Host identity

Before the first measurement retain:

- OS and build;
- CPU model and core count;
- RAM;
- filesystem;
- storage class and raw storage evidence;
- .NET version;
- Python version;
- PostgreSQL version/settings;
- repository SHA and clean-tree proof.

Use the F4-A host/storage probes. Do not type the storage class manually.

### 4.3 Linux first

Run the full envelope on the qualified Linux Development host first.

If a qualified Windows Development host is available, repeat the exploratory runs on Windows before freezing configuration.

If Windows is not yet available:
- Linux exploration may still derive a provisional candidate;
- the freeze document must state that only Linux contributed;
- F4-C may proceed only under the master-plan rule that the activation gate is satisfied on each **available** exploratory OS;
- authoritative M2 B3 still requires both Linux and Windows before S1.4 can close.

A hosted CI runner is never accepted for B3 timing.

---

## 5. Exploratory B3-A

Run:

`S1HandOffScaleTests.DurableHandOffWallTimeAtTheWorstShape`

at the contract maximum:

- 10,000 Tracks;
- four crop objects per Track;
- one trajectory object per Track;
- 50,000 real staged objects;
- finalizer host off;
- completion 3.1;
- n ≥ 30;
- ≥ 3 repeats;
- warm-up excluded.

Retain the raw output outside the repository initially. `MAVI_QUALIFICATION_OUT` is never under `docs/qualification/`. Copy it into:

`docs/qualification/stage2-s1/exploratory/<M1-sha12>/`

only in the later F4-C PR.

**Never edit a harness output.** Its bytes are retained exactly as the harness wrote them, and their SHA-256 is recorded.

On a qualified host at the full envelope, the M1 harness writes `authoritative: true`, because it cannot know a run is exploratory. That flag is therefore not what keeps an exploratory output out of authoritative evidence. Three things do, and all must hold:

1. the output's `environment.gitSha` is M1, and the checker refuses any output whose SHA is not the unit's measured SHA (M2);
2. the output's path is under `exploratory/`, and the checker refuses any cited artifact outside `evidence/<measured-sha12>/`;
3. a sidecar `docs/qualification/stage2-s1/exploratory/<M1-sha12>/exploratory-manifest.json` lists every retained output with its SHA-256, OS, `authoritative: false` and reason `exploratory-configuration-freeze`.

A copied, moved or relabelled M1 output is refused at M2 by (1) regardless of its path or flags.

### B3-A exploratory gate

For every available exploratory OS:

- HTTP completion succeeds;
- response is `finalizing`;
- one payload row;
- no publication;
- no accepted-evidence files;
- claim triple null;
- worker release proof passes;
- **max hand-off ≤ 15,000 ms**, where max is the maximum `handOffMs` over the non-warm-up samples of that OS's output. This is the checker's `timing_stats` recomputation, as the criterion binds `max` with warm-up excluded (master §8.4, §23).

The per-sample invariants above are `_Checker._b3a_content` (§6.1).

Any B3-A max above 15 s is a stop-and-report condition. Do not compensate by increasing worker timeout.

---

## 6. Exploratory B3-B

Run:

`S1FinalizationEnvelopeTests`

at:

- 10,000 Tracks;
- 50,000 staged objects;
- hosted finalizer;
- asynchronous 3.1 path;
- n ≥ 30;
- ≥ 3 repeats;
- warm-up excluded;
- synchronous reference n ≥ 5.

Use the committed M1 defaults as the exploratory configuration. The harness may activate the gate test-locally, but timing values must come from committed `appsettings.json`.

The synchronous 3.0 reference is informational only; no gate or rule uses it.

Retain per-sample raw data for:

- total hand-off → publication;
- claim acquisition;
- payload load;
- payload revalidation / plan bracket;
- seal wall;
- per-batch wall;
- extension count;
- graph-build bracket;
- relational graph persistence;
- graph SaveChanges;
- publication transaction;
- barrier wait;
- barrier hold;
- longest SQL statement;
- API host RSS;
- API process CPU;
- throughput;
- created/adopted object counts;
- premature visibility raw probes;
- sequence allocation;
- publication count;
- concurrency-overlap snapshot.

### 6.1 Exploratory outputs are evaluated by the merged checker, not by eye

Every exploratory output is evaluated with the per-output rules of the M1 checker (`tools/qualification/s1_evidence.py` at M1):
- `_Checker._b3a_content` for B3-A;
- `_Checker._b3b_content` for B3-B, with M1's committed `VisionFinalization` section, M1's barrier SQL and M1's runtime command timeout (30 s). This includes `visibility_problems` recomputed from the raw probes and `concurrency_problems` with the overlap recomputation;
- `_Checker._crash_content` for any crash output.

The function-by-function invocation and its full output are retained beside the exploratory outputs.

**Any finding other than shape or authoritative-flag findings on a deliberately reduced diagnostic is a stop condition.** A full-envelope output must produce no finding at all.

So a run cannot look healthy while a check silently did not run: for example, no Track-detail probe, or no observed overlap.

### B3-B exploratory stop conditions

Stop F4 immediately if any run shows:

- premature visibility;
- API phase not `finalizing` while DB job is Finalizing;
- publication count != 1;
- sequence allocation count != 1;
- invalid publication timeline;
- graph-persistence bracket failure;
- non-positive graph persistence;
- loss of required concurrency overlap;
- max live claims above configured limit;
- API 5xx or timeout during finalization;
- claim-extension count inconsistent with batch size;
- accepted evidence accounting mismatch;
- command exceeding effective runtime timeout;
- job ending Failed at the full envelope;
- any §6.1 checker finding (including `premature_visibility_unproven`, `metric_without_producer`, `concurrency_integrity_failed` "no overlap exercised", `frozen_configuration_mismatch`).

Do not tune around a functional failure.

---

## 7. Configuration derivation

No value is chosen by intuition. Every value below is a fixed function of the retained M1 outputs, written before any exploratory output is opened.

### 7.0 Inputs: definitions, units and pooling

- **Samples.** Every sample of every full-envelope exploratory B3-B output, on every available OS, **including warm-up samples**. Maxima size safety margins, and the first finalization after a host start is a cold one. A run with any stop condition contributes nothing; F4 stops instead (§6).
- **Units.** Harness values are milliseconds or ticks. Convert exactly: `seconds = ms / 1000`, `seconds = ticks / stopwatchFrequency`. There is no intermediate rounding. Configuration values are integer seconds.
- **Cross-OS pooling (this replaces "the slower OS").** Each input is the maximum of **its own metric** over the pooled samples of all available OS. The governing OS may differ per input: for example, Windows may have the longest publication and Linux the longest batch. The freeze document records each input's per-OS maximum and which OS governed it.

| Input | Definition from retained M1 fields |
|---|---|
| `S_batch_max` | max of every `perBatchWallMs` element (consecutive extension returns; each includes one extension round trip) |
| `G_max` | max of `(graphBuildBracket.publishEntered − graphBuildBracket.lastExtensionReturned) / publicationTimeline.stopwatchFrequency` (last extension → `PublishAsync` entry) |
| `P_max` | max of `(commitCompleted − transactionBegun) / stopwatchFrequency` from `publicationTimeline.ticks` (the checker's `publishTransactionMs`) |
| `L_first` | max over samples of `payloadLoadMs + payloadRevalidationAndPlanMs + max(perBatchWallMs of that sample)`. The last term conservatively covers two segments M1 does not retain separately: claim return → load entry, and the initial `ExtendClaimAsync` round trip. Each is of the order of one extension round trip, which every per-batch wall contains. |
| `T_max` | max of `acceptedAtUtc → publicationTimeline.commitCompletedUtc` (the checker's `totalMs`) |
| `S_batch_p95`, `T_p95` | nearest-rank p95 over the same pooled samples; recorded only, used by no rule |
| extension overhead | **not observable at M1**: the outputs retain no per-extension round trip. Recorded as "not measured". |

Rounding: `ceilTo(x, g) = g × ⌈x / g⌉`, so an exact multiple is unchanged.

### 7.1 SealingBatchSize

`SealingBatchSize = 200`, or stop.
- The master's first trigger (extension overhead > 5 %) cannot be evaluated from M1 outputs, so it cannot fire in this plan.
- The second trigger is evaluated against M1's committed `ClaimExtensionSeconds` (300): if `S_batch_max > 75` s, stop and report.

A different batch size cannot be measured at M1, because the harness runs the committed configuration. It is never estimated.

### 7.2 ClaimExtensionSeconds

`E_req = 4 × max(S_batch_max, G_max + P_max)`

`ClaimExtensionSeconds = max(300, ceilTo(E_req, 30))`

The executor extends the claim once before sealing and after every batch (`VisionFinalizationExecutor`, the `ExtendClaimAsync` calls). The last extension precedes graph build and `PublishAsync`. `PublishAsync` re-proves ownership at the row lock and again in `VisionJob.CompleteFinalization` (`FinalizationOwnedBy(claimToken, completionNowUtc)`), which runs **after** graph persistence and barrier acquisition. The claim live at that instant is the last extension's grant, `ClaimExtensionSeconds`, not `ClaimSeconds`.

If that grant expires first, the publication rolls back as stale. The next attempt repeats the same graph build and publication and fails the same way, so the job is deterministically exhausted. The grant must therefore cover a batch **and** graph build plus the publication transaction.

This **corrects** master §10.2, whose `ClaimExtensionSeconds` rule sizes only the batch and places the publication term on `ClaimSeconds`.

### 7.3 ClaimSeconds

`C_req = max(ClaimExtensionSeconds, 4 × L_first, 4 × P_max)`

`ClaimSeconds = max(300, ceilTo(C_req, 60))`

`ClaimSeconds ≥ ClaimExtensionSeconds` holds by construction, as the options validator requires. The initial claim must survive claim → load → revalidation → initial extension.

### 7.4 MaximumFinalizationAttempts

`MaximumFinalizationAttempts = 3`. The crash harness at M1 is optional and diagnostic. If it runs, every H row must pass (§6.1) or F4 stops. If crash evidence shows that three attempts are insufficient, stop and report; attempts are never changed in F4-C.

### 7.5 MaximumFinalizationDurationSeconds

`M_req = max(MaximumFinalizationAttempts × (ClaimSeconds + 2 × T_max), 2 × T_max)`, all in seconds.

`M_bound = ceilTo(M_req, 300)`

If `M_bound > 21600`, stop and report. Otherwise `MaximumFinalizationDurationSeconds = 21600`, the M1 committed value.

### 7.6 Values retained

- `PollIntervalSeconds = 5`
- `MaxConcurrentFinalizations = 1`
- `PayloadCleanupGraceSeconds = 0`

Do not raise concurrency merely because the host appears idle. A product need plus acceptable contention evidence is required, and that is not part of F4-C.

### 7.7 Effective bound

Record `MaximumFinalizationDurationSeconds + ClaimSeconds + PollIntervalSeconds` in seconds and in hours. Stop if it exceeds 86,400 s (24 h).

### 7.8 Values are never lowered below M1's in F4-C

Every derived value is a **floor**. The frozen value is `max(M1 committed value, derived floor)`, as §7.2–7.5 write it.

The deadline runs from `FinalizationAcceptedAtUtc` for every Finalizing row, claimed or not. `VisionJob.CanClaimFinalization` refuses at the deadline, and reconciliation exhausts a never-claimed row once it passes. With `MaxConcurrentFinalizations = 1`, a backlog of `k` worst-shape hand-offs needs about `k × T` before its last job is claimed. The §7.5 formula models one job's attempts, not a backlog.

Lowering `MaximumFinalizationDurationSeconds` toward `M_req` would therefore exhaust queued jobs that were never attempted. Lowering `ClaimSeconds` or `ClaimExtensionSeconds` changes recovery latency, which F4 does not qualify. Lowering any value is a separate, reviewed product decision with a backlog model, outside this plan.

### 7.9 What the gate does and does not prove (master §10.3)

`M_req ≥ 2 × T_max`, so the M1 stop `M_bound ≤ 21600` already implies `T_max ≤ 10,800 s = ½ × MaximumFinalizationDurationSeconds`. At M1 the "B3-B max ≤ ½ derived Max" gate is therefore implied by construction and is not independent evidence. It becomes an independent test only at M2, on new measurements against the frozen values.

The freeze document states this. Values are never re-frozen from M2 results (§14).

### 7.10 Illustrative arithmetic (not a measurement)

For `S_batch_max = 1.2 s`, `G_max = 4 s`, `P_max = 22 s`, `L_first = 6 s`, `T_max = 150 s`:

| Value | Arithmetic | Frozen |
|---|---|---|
| `ClaimExtensionSeconds` | `E_req = 4 × max(1.2, 26) = 104` → `ceilTo(104, 30) = 120`; `max(300, 120)` | 300 |
| `ClaimSeconds` | `C_req = max(300, 24, 88) = 300` → `ceilTo(300, 60) = 300`; `max(300, 300)` | 300 |
| `MaximumFinalizationDurationSeconds` | `M_req = max(3 × (300 + 300), 300) = 1800` → `M_bound = 1800 ≤ 21600` | 21600 |
| Effective bound | `21600 + 300 + 5 = 21905` | 21905 s ≈ 6.08 h |

With `P_max = 80 s` instead:
- `E_req = 4 × 84 = 336` → `ClaimExtensionSeconds = 360`.
- `C_req = max(360, 24, 320) = 360` → `ClaimSeconds = 360`.
- `M_req = 3 × (360 + 300) = 1980` → `M_bound = 2100`; `MaximumFinalizationDurationSeconds = 21600`.
- Effective bound: `21600 + 360 + 5 = 21965` s.

---

## 8. Activation decision gate

F4-C is allowed to ship completion 3.1 / Finalizing only if:

- exploratory B3-A max ≤ 15 s on every available exploratory OS;
- every §6.1 checker evaluation of every exploratory output returns no finding;
- exploratory B3-B max ≤ ½ of the frozen `MaximumFinalizationDurationSeconds` (implied by the `M_bound` stop, §7.9);
- `SealingBatchSize` stays 200 (§7.1) and `MaximumFinalizationAttempts` stays 3 (§7.4);
- no premature visibility;
- one publication per job;
- one sequence allocation per publication;
- concurrency integrity holds;
- no crash/recovery stop condition is discovered;
- no hidden dependency is discovered;
- `M_bound` ≤ 21600 s (§7.5);
- effective bound ≤ 86,400 s (§7.7).

If any condition fails:

- do not open F4-C as an activation PR;
- retain the exploratory output;
- document the failure;
- repair the product in a separate reviewed slice;
- restart the affected exploration on the repair SHA.

---

## 9. Freeze decision document

Create:

`docs/qualification/stage2-s1/f4-configuration-freeze.md`

in the F4-C branch.

It must include:

- M1 exact SHA;
- host identity per exploratory OS;
- paths and SHA-256 of retained exploratory outputs;
- explicit non-authoritative label;
- `S_batch_max`, `G_max`, `P_max`, `L_first`, `T_max` (per OS and pooled, with the governing OS of each), `S_batch_p95`, `T_p95`;
- extension overhead recorded as "not measured at M1" (§7.0);
- the §6.1 checker evaluations and their (empty) findings;
- the `exploratory-manifest.json` path and SHA-256;
- rule-by-rule arithmetic;
- current value → derived value table;
- effective maximum bound;
- activation gate result;
- statement that authoritative qualification has not started;
- independent-review section.

No exploratory file may live under `evidence/<M2>/`.

---

## 10. U1 — truthful Finalizing UI PR

U1 is a small, separate product PR from current `main` after the execution-plan PR is merged.

### 10.1 Scope

Use the existing API truth:

`phase == "finalizing"`

to show a distinct operator-visible Finalizing state on the Processing page.

Also distinguish failed finalization from inference/processing failure. The existing API already provides the distinction, and U1 must use exactly it: `latestRun.phase == "failed"` and `latestRun.failureCode` starts with `vision_finalization_` (`VisionJob.FinalizationFailureCodePrefix`; for example `vision_finalization_exhausted`). U1 invents no other signal.

Do not change backend lifecycle semantics.

**Files:** `src/web/mavi-web/src/**` only (master §24 U1). U1 does not modify `tools/web-visual-qa/**`. The `processing-finalizing` and `processing-failed-finalization` states and their expectations were fixed by F4-A as the B5 criteria, and U1 must make them pass unmodified.

### 10.2 UX requirements

The operator must be able to distinguish at least:

- queued;
- processing/inference;
- **finalizing**;
- completed;
- failed finalization.

Do not present Finalizing as generic `Running / Progress`.

Keep the treatment visually consistent with the existing MAVI design system; no unrelated redesign.

### 10.3 Tests first

Add focused web tests proving:

- `phase=finalizing` renders a distinct Finalizing state;
- Finalizing cannot regress to the generic Running/Progress label;
- completed remains unchanged;
- failure rendering remains correct;
- `phase == "failed"` with a `vision_finalization_*` failure code is labelled as a finalization failure and not as an inference failure. `phase == "failed"` with any other code keeps the existing failure rendering.
- The state is read from `latestRun.phase`, never from `run.status` (`Running` spans both inference and finalizing).

Run the existing F4-A visual-QA states `processing-finalizing` and `processing-failed-finalization` against the real component, unmodified. They fail on `main` today, and U1 is what makes them pass.

### 10.4 U1 merge gate

Before merge:

- web typecheck;
- web unit/integration tests;
- visual-QA run of the two unmodified F4-A states, passing;
- full required CI;
- independent cold review with no P1/P2.

Merge U1 before F4-C.

---

## 11. F4-C — configuration freeze and shipped activation

Create F4-C only after:

- exploratory outputs are complete;
- derivation is reviewed;
- activation gate passes;
- U1 is merged.

F4-C is intentionally product-bearing.

### 11.1 Required product changes

Update:

`src/platform/Mavi.Api/appsettings.json`

with:

- `VisionFinalization:Enabled = true`;
- the derived/frozen timing values;
- unchanged values explicitly retained where applicable.

Update:

`src/vision/mavi_vision/common/settings.py`

so:

`completion_schema_version = "3.1"`

is the shipped worker default.

### 11.2 Required tests

Update/add tests that pin:

- `VisionFinalization:Enabled == true` as shipped default;
- exact frozen timing values;
- option validation:
  `ClaimExtensionSeconds <= ClaimSeconds <= MaximumFinalizationDurationSeconds`;
- worker default emits completion 3.1;
- worker accepts the 3.1 hand-off acknowledgement;
- default worker accepts the activated platform contract;
- completion 3.1-only platform is supported by the default worker;
- activation-gate tests reflect the new shipped state without weakening 2.0 compatibility, and assert that the activated platform refuses completion 3.0 (the designed retirement).

Do not remove 2.0 compatibility unless separately planned.

### 11.3 Deployment and rollback documentation

**Activation retires completion 3.0 at the platform, by design** (`WorkerContractRules.AsynchronousCompletionSchemaVersions` is `["2.0", "3.1"]`). An activated platform advertises and accepts 2.0 and 3.1 only. A 3.0 worker fails closed at the probe and leases nothing, and a live 3.0 completion is refused with `worker_contract_version_unsupported`. F4-C keeps 2.0 and does not claim that 3.0 remains accepted.

F4-C updates the runbook's "Asynchronous finalization (S1.4 B3 F3): activation, rollback, health" section only to say that `Enabled = true` and worker `3.1` are now the shipped defaults. It keeps every existing safety step in substance:
- the same value on every API host, checked on each host's health;
- the intended probe pause for 3.0 workers between platform and worker activation;
- `finalizingJobs == 0` **and** `countsRefreshedAtUtc` within the last two `PollIntervalSeconds` before disabling;
- stop if `malformedClaims > 0`.

It also states the staged path now that the shipped default activates on deployment. For a multi-host rollout, deploy with an explicit machine-configuration override `VisionFinalization:Enabled = false` on every host, then remove the override on every host.

Normal rollout:
1. deploy the platform on every API host;
2. confirm `enabled` on every host's health;
3. deploy workers defaulting to 3.1.

Rollback:
1. set every worker to completion 3.0 (they fail closed at the probe, so no new hand-off arrives);
2. wait until `finalizingJobs == 0` with `countsRefreshedAtUtc` fresh;
3. require `malformedClaims == 0`;
4. only then disable async finalization on every host.

Never disable the gate while Finalizing rows remain.

### 11.4 F4-C boundaries

F4-C must not:

- change finalizer algorithms;
- change selector/scorer/profile;
- change evidence format;
- add dependencies;
- change B3 criteria;
- modify UI beyond already-merged U1;
- contain authoritative measurement results.

If exploratory data implies an algorithm change, F4-C stops and a separate product PR is required.

---

## 12. F4-C validation

Before review:

- `dotnet build MAVI.sln --configuration Release`;
- Domain tests;
- Application tests;
- Integration tests serially;
- worker pytest;
- web typecheck/tests if shared contracts are touched;
- qualification checker tests;
- `python tools/verify_repo.py`.

Run focused activation/default tests first.

No authoritative B3 run is performed on the F4-C branch.

Small smoke tests are permitted and must be labelled non-authoritative.

---

## 13. Independent review gates

### Gate A — exploratory record review

Before U1/F4-C implementation is considered final, independently review:

- host identity;
- full envelope;
- sample counts;
- warm-up exclusion;
- raw output integrity;
- stop conditions;
- configuration arithmetic, in seconds, per §7.0–7.8;
- per-metric cross-OS maxima (not one "slower OS");
- the §6.1 checker evaluations;
- unedited outputs (hashes equal the manifest);
- no manual tuning.

### Gate B — U1 cold review

Attack:

- Finalizing still rendered as Running;
- state sourced from `run.status` instead of truthful `phase`;
- failed finalization conflated with inference failure;
- fixture-only behavior not wired to real component.

### Gate C — F4-C cold review

Attack:

- activation true but worker still defaults 3.0;
- worker 3.1 but gate remains false;
- frozen values differ from derivation;
- derived values copied incorrectly;
- config loaded from a test override instead of shipped file;
- rollback order unsafe;
- production dependency added;
- qualification checker loosened to accommodate new values;
- authoritative evidence accidentally generated before M2.

All P1/P2 findings are fixed before merge.

---

## 14. Definition of M2

M2 is **exactly the merge commit of F4-C**, provided U1 is already present in its ancestry. F4-C and U1 are merged with a merge commit, never squash or rebase, so M2 is a merge commit reachable from `main` (master §7.1).

Between M1 and M2 the only behavior-bearing changes are U1 (`src/web/mavi-web/src/**`) and F4-C. The M1→M2 diff record lists every path. Any other behavior-bearing path, or any harness, checker or fixture path (§4.1), invalidates the exploratory derivation, which is then redone at a new M1.

Record:

- U1 merge SHA;
- F4-C PR head;
- F4-C merge SHA;
- M1 → M2 behavior-bearing diff;
- frozen configuration;
- activation defaults.

After M2 is declared:

- no product-bearing change;
- no harness/checker change;
- no config change;
- no UI change;
- no dependency change

may land until the authoritative qualification sequence is complete, unless affected units are explicitly invalidated and rerun.

That exception never covers the `VisionFinalization` values or the activation defaults.

**No re-freeze from authoritative results** (master §10.4 item 5). If an authoritative M2 run fails a criterion, F4 stops and reports. The frozen values are not changed on the basis of M2 measurements.

A new freeze requires:
1. a recorded failed-M2 outcome;
2. a product change or new exploration at a new SHA;
3. a new F4-C;
4. a new M2.

The failed M2 is never re-labelled.

---

## 15. Work products

This interval produces exactly:

1. exploratory B3-A/B3-B outputs bound to M1;
2. `f4-configuration-freeze.md`;
3. U1 PR and merge SHA;
4. F4-C PR and merge SHA;
5. M2 declaration.

It does **not** produce:

- authoritative B1–B6 PASS;
- authoritative disconnected PASS;
- F4-E evidence record;
- S1.4 closure;
- S2 work.

---

## 16. Completion criteria for this execution plan

The M1→M2 phase is complete only when:

1. full-envelope exploratory B3-A and B3-B have run at M1 on every available qualified exploratory OS;
2. every exploratory stop condition is clear;
3. configuration values are mechanically derived and reviewed;
4. U1 is merged and truthfully renders Finalizing;
5. F4-C ships `Enabled=true` and worker default `3.1`;
6. frozen values equal the reviewed derivation;
7. exact-head CI for F4-C is green;
8. independent cold review raises no P1/P2;
9. F4-C merges and its merge SHA is recorded as M2;
10. authoritative qualification has not started before M2.

The next plan after this one is not another architecture plan. It is the existing F4 master plan §25 authoritative execution sequence at M2.

---

## 17. Amendment record (independent cold review of `9a68f7d`)

| # | Sev | Defect in `9a68f7d` | Correction |
|---|---|---|---|
| A1 | P1 | `ClaimExtensionSeconds ≥ 4 × S_batch_max` ignores that `CompleteFinalization` re-proves ownership after graph build, persistence and barrier, under the last extension's grant. A derived 30 s extension could expire mid-publication and deterministically exhaust worst-shape jobs. | §7.2 `E = max(300, ceilTo(4 × max(S_batch_max, G_max + P_max), 30))`; corrects master §10.2 |
| A2 | P1 | "Choose ≥" allowed lowering `Max`, `Claim` and `Extension` to formula minima. Deadlines run from acceptance and never-claimed rows are exhausted at the deadline, so with `MaxConcurrentFinalizations = 1` a small backlog would fail unattempted jobs. | §7.8 never lower below M1; §7.5 `Max = 21600` unless `M_bound > 21600` (stop) |
| A3 | P2 | Inputs undefined against retained fields: no unit conversion, rounding, sample set or cross-OS rule; "extension overhead" and `L_first` not retained as worded; the batch rule circular | §7.0 definitions; §7.1 batch 200 or stop |
| A4 | P2 | "Slower OS" undefined; different inputs can be governed by different OS | §7.0 per-metric cross-OS maximum |
| A5 | P2 | "Mark `authoritative: false`" implied editing raw outputs; the M1 harness writes `authoritative: true` on a qualified host; exploratory outputs were judged by eye, so a run with a check that never ran could look healthy | §5 no edits, SHA/path/manifest protections; §6.1 merged-checker evaluation as a stop |
| A6 | P2 | §14 allowed a post-M2 config change "if rerun" (a re-freeze from authoritative results); the ½-Max gate's constructional nature was not stated; harness changes between M1 and M2 were not addressed | §14 no re-freeze; §7.9 transparency; §4.1 and §14 harness freeze and M1→M2 diff rule |
| A7 | P2 | U1 could skip the failed-finalization distinction ("when the contract supplies it", though it does) and could edit the F4-A visual-QA expectations | §10.1 exact signal and file scope; §10.3 unmodified F4-A states |
| A8 | P2 | Rollout and rollback text omitted that activation retires 3.0, the every-host rule, count freshness, and the staged path once the default activates | §11.2, §11.3 |
