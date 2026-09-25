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
- no locally modified worker default.

The harness may enable asynchronous finalization through its test-only controls exactly as designed by F4-A. That does not change the measured source SHA.

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

Retain the raw output outside authoritative evidence initially, then copy it into:

`docs/qualification/stage2-s1/exploratory/<M1-sha12>/`

only in the later F4-C PR.

Mark it:

- `authoritative: false`
- reason: `exploratory-configuration-freeze`

### B3-A exploratory gate

For every available exploratory OS:

- HTTP completion succeeds;
- response is `finalizing`;
- one payload row;
- no publication;
- no accepted-evidence files;
- claim triple null;
- worker release proof passes;
- **max hand-off ≤ 15,000 ms**.

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
- job ending Failed at the full envelope.

Do not tune around a functional failure.

---

## 7. Configuration derivation

From exploratory B3-B outputs compute, using the slower available OS:

- `S_batch_max` = maximum per-batch wall;
- `S_batch_p95`;
- `L_first` = claim → first extension;
- `T_max` = maximum hand-off → publication;
- `T_p95`;
- `P_max` = maximum publication transaction;
- extension overhead = total extension round-trip time / seal wall.

No value is chosen by intuition.

### 7.1 SealingBatchSize

Start with 200.

Keep 200 unless either:

1. extension overhead > 5% of seal wall; or
2. `S_batch_max > ClaimExtensionSeconds / 4`.

If overhead > 5%, increase batch size only enough to bring expected extension overhead ≤ 5%.

If batch wall is too large, reduce batch size so the measured/estimated maximum batch remains comfortably below one quarter of `ClaimExtensionSeconds`.

Any change from 200 requires the freeze document to show the arithmetic and the recovery trade-off.

### 7.2 ClaimExtensionSeconds

Choose:

`>= 4 × S_batch_max`

Then:

- round up to the next 30 seconds;
- minimum 30 seconds.

### 7.3 ClaimSeconds

Choose:

`>= max(ClaimExtensionSeconds, 4 × L_first, 4 × P_max)`

Then round up to the next 60 seconds.

### 7.4 MaximumFinalizationAttempts

Keep 3 unless exploratory crash/recovery evidence demonstrates that three attempts are insufficient for deterministic adoption/recovery.

Changing attempts requires explicit review; it is not a performance knob.

### 7.5 MaximumFinalizationDurationSeconds

Choose:

`>= MaximumFinalizationAttempts × (ClaimSeconds + 2 × T_max)`

Also require:

`>= 2 × T_max`

Round up to the next 300 seconds.

### 7.6 Values normally retained

Unless measurement provides a concrete reason:

- `PollIntervalSeconds = 5`
- `MaxConcurrentFinalizations = 1`
- `PayloadCleanupGraceSeconds = 0`

Do not raise concurrency merely because the host appears idle. A product need plus acceptable contention evidence is required.

### 7.7 Effective bound

Record:

`MaximumFinalizationDurationSeconds + ClaimSeconds + PollIntervalSeconds`

and convert it to minutes/hours in the freeze document.

Stop if:

- derived `MaximumFinalizationDurationSeconds > 21600`; or
- effective bound > 24 hours.

---

## 8. Activation decision gate

F4-C is allowed to ship completion 3.1 / Finalizing only if:

- exploratory B3-A max ≤ 15 s on every available exploratory OS;
- exploratory B3-B max ≤ ½ of the **derived** `MaximumFinalizationDurationSeconds`;
- no premature visibility;
- one publication per job;
- one sequence allocation per publication;
- concurrency integrity holds;
- no crash/recovery stop condition is discovered;
- no hidden dependency is discovered;
- derived maximum duration ≤ 21600 s;
- effective bound ≤ 24 h.

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
- `S_batch_max`, `S_batch_p95`, `L_first`, `T_max`, `T_p95`, `P_max`;
- extension overhead;
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

Also distinguish failed finalization from inference/processing failure where the existing API already provides enough information.

Do not change backend lifecycle semantics.

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
- failed finalization is distinguishable from inference failure when the contract supplies that distinction.

Update visual-QA fixture states:

- `processing-finalizing`;
- `processing-failed-finalization`.

### 10.4 U1 merge gate

Before merge:

- web typecheck;
- web unit/integration tests;
- visual-QA fixture run;
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
- activation-gate tests reflect the new shipped state without weakening 2.0 compatibility.

Do not remove 2.0 compatibility unless separately planned.

### 11.3 Deployment and rollback documentation

Update the runbook:

Normal rollout:
1. deploy API/platform hosts that understand Finalizing and completion 3.1;
2. verify health;
3. deploy workers defaulting to 3.1.

Rollback:
1. move workers back to completion 3.0 first;
2. wait until `FinalizingJobs == 0`;
3. require `MalformedClaims == 0`;
4. only then disable async finalization.

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
- configuration arithmetic;
- slower-OS selection;
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

M2 is **exactly the merge commit of F4-C**, provided U1 is already present in its ancestry.

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
