# MAVI Stage 2 — S1.4 B3 F4: Qualification and Closure Implementation Plan

**Status:** Proposed implementation-grade plan for F4, revision 2. Documentation only. Nothing in this document is evidence; no verdict changes; no measurement was run to write it. It is reviewed independently before F4 execution begins.
**Revision 2 (2026-09-25):** amended after the independent cold review of revision 1 (`94f7cb3`). One P1: the B3-B visibility-barrier hold is now measured from the acquisition of the completion-exclusive advisory lock to the observed commit, never from the job row lock (§9.2.1). One P2: graph persistence is measured directly around `FinalizationGraphPersistence.AddAsync`, and no metric is derived by subtraction (§9.2.2). One P2: the operator-UI Finalizing gap is a sequencing prerequisite of M2 (Path A, §6.1, §15.3). Two hygiene items: the frozen F3 plan lands on `main` docs-only before F4-A (§6.1 step D0), and PR #87 is closed as historical, never consumed (§6.1 step H1). Every other rule of revision 1 is kept.
**Owner decisions recorded (2026-09-25):** (1) the qualified shipped path becomes completion 3.1 / Finalizing: F4-C sets `VisionFinalization:Enabled = true` and the worker default `completion_schema_version = "3.1"`, subject to the F4 configuration-freeze measurements (§10.5); (2) Path A: the Finalizing UI PR (U1) lands before M2 (§6.1).
**Date:** 2026-09-25
**Starting state:** `main@480afb0fac0150b6b4f77402ce7c31575580d911` (the merge of PR #92, S1.4 B3 F3).
**Parent plans:** `docs/superpowers/plans/2026-09-24-stage2-s1-4-hardening-qualification-implementation.md` (the S1.4 plan, §7.4 and §8 as amended on 2026-09-25); `docs/superpowers/plans/2026-09-25-s1-4-b3-asynchronous-finalization.md` (the B3 plan, §14, §16 F4, §17 qualification guards, §19, §21); the F3 plan `docs/superpowers/plans/2026-09-25-s1-4-b3-f3-finalizer-recovery-implementation.md` §17 (F4 hand-off), which at `480afb0` exists only on branch `docs/s1-4-b3-f3-finalizer-plan` at `44e1f7b` and lands on `main` in step D0 before F4-A (§2.5, §6.1).
**Governing acceptance:** `docs/reviews/2026-09-23-visual-attributes-acceptance.md` B1–B6.
**Scope:** F4 only: repair the qualification harness and checker for the repaired architecture, freeze the finalizer configuration from measurement, produce the authoritative S1.4 evidence on one exact `main` SHA, and write the closure record.
**Non-goals:** §27.

---

## 1. Purpose

F1–F3 repaired the B3 failure recorded at `bb331c6` (synchronous completion at the 10,000-Track envelope took up to 190.8 s against a 15 s bound). The completion path is now a bounded durable hand-off (`Leased → Finalizing`) plus a platform finalizer. F4 proves that repair and closes S1.4:

1. **Harness truth first.** The evidence tooling on `main` still measures and judges the retired synchronous path. F4 replaces it with tooling that measures the repaired path, with a discrimination test for every rule, before any authoritative number is produced.
2. **One exact SHA.** Every authoritative artifact binds to one merge commit on `main`, and the closure diff from that commit is classified path by path.
3. **Freeze from measurement.** The finalizer's production configuration is chosen from measured p95/max and product recovery requirements, committed, and the authoritative B3-B rerun on the resulting SHA.
4. **Rerun what F1–F3 invalidated.** Every S1 unit is measured at the final SHA. No PASS is carried forward from `bb331c6`.
5. **Closure or a truthful open record.** S1.4 closes only when B1–B6 and the disconnected unit are PASS on that SHA and the post-merge workflows agree. Otherwise the record says exactly what is open and why.

The execution rule of the S1.4 plan stands: **qualify the frozen identity; do not tune it while measuring it.** The one deliberate exception is the configuration freeze (§10), which is a reviewed product change on its own SHA, followed by a rerun.

A genuine product failure found during F4 (a bound violated, a crash-matrix row that does not converge, a hidden dependency, a UI that misreports state) is a stop-and-report condition (§30). F4 does not repair product code.

---

## 2. Exact starting state (surveyed at `480afb0`)

### 2.1 Repository

| Item | State |
|---|---|
| `main` | `480afb0fac0150b6b4f77402ce7c31575580d911`, merge of PR #92 (head `623b45d`). Clean tree. |
| Merged since the last measured SHA `bb331c6` | PR #86 (Task-10 skip fix), #88 (B3 architecture), #89 (F1), #90 (docs), #91 (F2), #92 (F3). 89 paths changed; classified in §4.1. |
| PR #87 | **Open**, unmerged, branch `feature/stage2-s1-2c-evidence-set-v3-worker`. Interim evidence at `bb331c6`: B3 FAIL, B6 FAIL, B4 PASS, others OPEN; retained files under `docs/qualification/stage2-s1/evidence/bb331c6/`. None of it is on `main`. F4 does not modify it. |
| Evidence on `main` | Only `docs/qualification/stage2-s1/b1-accepted-real-clip-baseline.json` (the accepted S1.2c baseline: 63 Tracks, 8,284 candidates). No evidence record, no summary. |
| Activation | `src/platform/Mavi.Api/appsettings.json` `VisionFinalization`: `Enabled false`, `MaxConcurrentFinalizations 1`, `PollIntervalSeconds 5`, `ClaimSeconds 300`, `ClaimExtensionSeconds 300`, `MaximumFinalizationAttempts 3`, `MaximumFinalizationDurationSeconds 21600`, `SealingBatchSize 200`, `PayloadCleanupGraceSeconds 0`. Worker `completion_schema_version` default `"3.0"` (`src/vision/mavi_vision/common/settings.py`). So the **shipped default is the synchronous 3.0 path**, the path that failed B3. |
| Effective bound | `VisionFinalizationOptions.EffectiveMaximumFinalizationBound = MaximumFinalizationDurationSeconds + ClaimSeconds` (21,900 s with defaults), plus one `PollIntervalSeconds` for reconciliation to observe it. |
| Npgsql command timeout | `CommandTimeoutSeconds 300` (`appsettings.json`). |
| Worker request timeout | `request_timeout_seconds` default 30 s, maximum 120 s. |

### 2.2 Qualification tooling on `main`

| Tool | State at `480afb0` | Consequence for F4 |
|---|---|---|
| `tools/qualification/s1_evidence.py` (1,657 lines) | B3 requires `b3.real-store-completion-wall-ms.<variant>` timings and `b3.sealing-scale-output.<variant>` artifacts; `_b3_headroom` applies 2× against the worker timeout to the **synchronous completion wall time**; `_sealing_output` binds to schema `s1-b3-sealing-scale-v1` with `sealedObjects == 50,000`; `ALWAYS_EVIDENCE` maps `S1SealingScaleTests.cs` and `QualificationGate.cs` to B3. B4 cites `test_worker_completion_v3.py`, `CompletionDigestGoldenTests`, `VisionResultCompletionV3ApiTests`, `VisionFinalizationSubmissionApiTests`, `VisionResultCompletionApiTests`, `VisionResultCompletionCommitFailureTests` (all exist), none of the F3 lifecycle/publication/executor/recovery suites. The docstring of the B4 entry already says "F4 re-derives the B4 set". | The checker judges the retired path and knows nothing of Finalizing, claims, the frozen configuration or the crash matrix. §22 replaces the B3 rules and extends B4/B5. |
| `tools/qualification/s1-qualification-evidence.schema.json` | Host requires `storageClass ∈ {ssd, hdd, nvme, network, hosted-runner}`; no field for how it was determined. No block for a frozen configuration. | §21, §22. |
| `tests/Mavi.IntegrationTests/Qualification/S1SealingScaleTests.cs` | Opt-in (`MAVI_QUALIFICATION=1`, `S1QualificationFact`), builds an `ApiTestFactory` with the activation gate **off**, posts completion **3.0**, times the synchronous POST including sealing, asserts Completed with Track rows. | Measures a path that is retired once the gate is on. Replaced (§8, §24 F4.2). |
| `tests/Mavi.IntegrationTests/VisionFinalizationSubmissionTimingTests.cs` | F2 diagnostic: `MAVI_F2_TIMING_TRACKS` (default 500), worst-shape 3.1 request that stages nothing, `IVisionFinalizationSubmissionStore.SubmitAsync` timings (`Validation`, `PayloadEncoding`, `Persistence`, `Total`), prints only. At 10,000 Tracks on the development host: ≈ 2.3 s total. | Proves the measurement points exist; not a harness (no n, repeats, output, identity). |
| `tests/Mavi.IntegrationTests/VisionFinalizationTimingTests.cs` | F3 diagnostic: `MAVI_F3_TIMING_TRACKS` (default 200), real staged objects, `VisionFinalizationExecutor.ExecuteAsync` on a claim, event 1504 message, working set before/after, prints only. At 200 Tracks: seal ≈ 1.6 s, publish ≈ 0.8 s, wall ≈ 2.4 s. | Same. |
| `FinalizationWorld` | Test world: `HandOffAsync` (with build callback), `ClaimAsync`, `PrepareAsync`, `StateAsync`, `SetClaimTripleAsync`, `ExecuteSqlAsync`, `Host()`, `HealthAsync`, `WaitUntilAsync`, `sharedWith` second host, `ControllableSealer` (`ThrowIoOnSeal`, `BeforeSeal`, deleting trap), `SqlTrace`, `DatabaseFault` (`Tripped`), `CommitFaults`. Runs with the finalizer host **off** and drives cycles directly. | Reusable for the crash-matrix harness (§11). |
| `QualificationGate.cs` | Captures environment: git SHA, tree clean, commit present, OS, arch, .NET, cores, PostgreSQL 18 grade, `pg.*` settings, test assembly identity; `Begin`/`Write` claim-then-overwrite output discipline. | Reused by every new .NET harness. |
| `tools/qualification/s1_memory.py`, `process_memory.py` | B2 harness (four §6.2 terms, staging lifecycle, `derive`); measures host identity incl. `stagingFilesystem`, not storage class. F2 pointed `measure_completion_peak` at the 3.1 body. | §13. |
| `tools/qualification/s1_b1.py` | Derives the four B1 counts from five retained runs. | Unchanged. |
| Task 10 workflow | `workflow_dispatch`; `concurrency: cancel-in-progress` per ref; matrix `ubuntu-latest`/3.12.14 and `windows-latest`/3.12.10; seven JUnit steps named in `TASK10_JUNIT_STEPS`; PR #86 moved the three ML-dependent probe tests to the post-install step. | B6 (§16). |
| Quality Gate | `ubuntu-latest`, Python 3.13 (not a qualified variant), TRX per .NET project, Vitest JUnit. `Mavi.IntegrationTests` reported 757 passed / 1 skipped at `bb331c6` (the skip is `S1SealingScaleTests`). | .NET/web suite provenance. |
| Disconnected | `tools/phase1/qualify_offline_variant.py` (`assert_outbound_internet_unavailable`, five targets), `qualify_linux_offline.sh` / `qualify_windows_offline.ps1` (Task-18 P2 CUDA flow), `tools/vision/build_offline_bundle.py` (`--source-commit`, `_verify_mavi_wheel_source`). No S1-specific disconnected runner; the S1.4 record schemas (`s1-disconnected-run-v1`) exist. | §19. |
| Visual QA | `tools/web-visual-qa/run.mjs` (real bundle, real Chromium via CDP, four widths, states in `states.mjs`); not in CI. | B5 (§15). |
| Windows | Golden-byte pin for `("win32", "11.3.0", "3.1.1")` exists; `S1SealingScaleTests.RuntimeVariant()`/`CpuModel()` (registry) and `FilesystemOf` (`DriveInfo.DriveFormat`) are portable; `process_memory.py` reads `PrivateUsage`. No Windows Development host was available to the execution environment that produced `bb331c6` (PR #87 §7). | §18. |

### 2.3 F3 surfaces the harness must measure

| Surface | Where |
|---|---|
| Hand-off timings | `VisionFinalizationSubmissionTimings(Validation, PayloadEncoding, Persistence, Total)` from `IVisionFinalizationSubmissionStore.SubmitAsync`; the HTTP response `VisionJobFinalizationResponse.State == "finalizing"`. |
| Finalization timings | Executor: `sealWatch`, `publishWatch`, `total`, hand-off-to-publish (`now − claim.AcceptedAtUtc`), extension count, `Sealing` summary (created/adopted/bytes), all in event 1504. Lifecycle: claim (`ClaimNextAsync`), `ExtendClaimAsync` → `Live | DeadlineReached | Lost`, `LoadInputsAsync`, `PublishAsync`. |
| Health | `/api/health` `details.visionFinalization.{enabled, finalizingJobs, liveClaims, malformedClaims, oldestFinalizingAcceptedAtUtc, countsRefreshedAtUtc, inFlight, lastCycleUtc, lastCycleClaimed, lastCycleExhausted, lastCyclePayloadsCleaned}`. |
| Status | `ProcessingPhases.Finalizing = "finalizing"` from `VisionJobStatus.Finalizing` (`IProcessingOrchestrator.PhaseOf`); `ProcessingRunStatus` has no Finalizing (run stays Running). |
| Events | 1500–1514 (runbook). |

### 2.4 Web client and Finalizing (survey finding)

`src/web/mavi-web/src/api/videos.ts` types `PROCESSING_PHASES = ['queued','processing','finalizing','completed','failed']`. **No component reads `phase`.** `ProcessingPage.tsx` renders `run.status` (Running/Completed/Failed) and `videoStatus`; the label logic is `isActiveStatus(run.status) ? 'Progress' : run.status`. No web test mentions `finalizing`. So an operator watching the Processing page during Finalizing sees "Running / Progress", and the API's truthful `phase` is not shown. This is a product gap F4 must not fix inside its harness or evidence work. Because B5 requires a distinct Finalizing state (§15.3), closure depends on a small separate UI product PR that lands before M2 (Path A, §6.1 step U1).

### 2.5 Documentation state

- `docs/runbooks/vision-runtime-model-component-lifecycle.md` and the B3 plan reference the F3 plan by its `docs/superpowers/plans/…f3-finalizer-recovery-implementation.md` path. That file is not on `main`; it is on `origin/docs/s1-4-b3-f3-finalizer-plan` (`44e1f7b`). **Decision:** step D0 (§6.1) lands the reviewed, frozen document on `main` docs-only, byte-identical to the blob at `44e1f7b`, before F4-A opens. It is not behavior-bearing and invalidates nothing. The alternative (rewriting every reference to cite branch and SHA) is kept only as a fallback if the owner declines D0.
- PR #87 (open, unmerged) holds superseded interim evidence at `bb331c6`. **Decision:** step H1 (§6.1) closes it unmerged as a historical record, keeps its branch as the archive, and the checker refuses any artifact outside `evidence/<measured-sha12>/` (§22), so F4 cannot consume it.
- The S1.4 plan §7.4/§8 amendments and B3 plan §14/§16/§19/§21 already define B3-A, B3-B, the freeze order and the invalidation consequence. This plan does not restate them as new rules; where it is more specific, §29 records why.

---

## 3. Current qualification and harness survey: what still fits and what does not

| Area | Fits the repaired architecture? | Gap F4 must close |
|---|---|---|
| Record structure (`measuredSha`, `hosts`, `runs`, `suites`, `retainedArtifacts`, `measurements`, `units`, `closure`) | Yes. Keep. | Add `frozenConfiguration`, B3-A/B3-B artifact ids, storage-class evidence (§21). |
| Run/suite/JUnit/TRX provenance rules | Yes. Keep unchanged. | None. |
| B1 tooling and baseline | Yes. | Windows half never produced. |
| B2 tooling | Yes (F2 already targets 3.1 for the completion-peak term). | Never executed authoritatively. |
| B3 rules and harness | **No.** Synchronous criterion, 3.0 request, gate off. | Replace (§8, §9, §22). |
| B4 suite set | Partly. The six cited suites exist; the F3 suites that prove publication, recovery, fencing and the ambiguity windows are not cited. | Extend and add a proving-test map (§14). |
| B5 record schemas | Partly. No item for Finalizing, premature visibility or completion after asynchronous publication. | Schema v2 (§15). |
| B6 | Yes (PR #86 fixed the skips). | Rerun on the final SHA. |
| Disconnected | Record schema yes; no S1 runner; the 3.1 activation is not part of any install path. | Runbook and activation binding (§19). |
| Host identity | `MEASURED_HOST_FIELDS` measured by the B2 harness; storage class is typed in and was an assumption (`network`) at `bb331c6`. | Probe and evidence field (§17, §21). |
| Windows binding | Harness fields exist; no host. | §18. |

**Decision (required by the task): a separate Harness PR is required.** Every gap above is in `tools/qualification/*` or `tests/*`, which the S1.4 plan §2.1 and the checker's `BEHAVIOR_BEARING_SURFACE` treat as behavior-bearing evidence tooling. Measuring on the Harness PR's branch would produce evidence on an unmerged head that the checker rejects (`measured_sha_not_on_main`). So F4-A merges first, and the exact measurement SHA is its merge commit or a later one (§6, §25).

---

## 4. F1–F3 invalidation map

### 4.1 The `bb331c6 → 480afb0` diff, classified

Produced with `git diff --no-renames --name-only bb331c6 480afb0` (89 paths) and the checker's own `INVALIDATION_MAP` / `is_behavior_bearing` at `480afb0`.

| Class | Paths | Units invalidated by the checker's map |
|---|---|---|
| Worker contract surface (`src/vision/mavi_vision/common/*`, `worker/*`, `contracts/*`) | `common/control_plane.py`, `common/settings.py`, `worker/client.py`, `worker/main.py`, `worker/runner.py`, `contracts/README.md`, the 3.1 schemas and examples (4) | B3, B4, B5, B6, DISCONNECTED |
| Platform (`src/platform/*`) | 39 files: endpoints, hosted finalizer, health, options/policy/codes, validator, contracts, domain (`VisionJob`, `VisionJobStatus`, `FinalizationClaimState`, payload), EF configuration, migration `20260925020849_AddVisionFinalization`, snapshot, lifecycle, submission store, graph persistence, `ProcessingResultStore`, `StagingJanitor`, `appsettings.json` | B3, B4, B5, DISCONNECTED |
| Web (`src/web/mavi-web/*`) | `api/videos.ts` and four test files | B5, DISCONNECTED |
| Evidence tooling and workflow (unmapped surface → every unit) | `.github/workflows/task10-runtime-qualification.yml` (PR #86), `tools/qualification/s1_evidence.py`, `s1_memory.py`, `tests/test_s1_evidence.py` | B1, B2, B3, B4, B5, B6, DISCONNECTED |
| Test trees (invalidate through citation and shared support) | 26 files, including `ApiTestFactory.cs` and `FinalizationWorld.cs` (shared support of every cited `Mavi.IntegrationTests` suite) | every unit citing a `Mavi.IntegrationTests` or `Mavi.Application.Tests` suite: B2 (janitor), B3, B4, B5 |
| Not behavior-bearing | ADR-006, runbook, two plans, `tools/verify_repo.py` | none |

Not touched by F1–F3: `src/vision/mavi_vision/{evidence,quality,tracking,pipeline,video,storage,detection}/*`, the pipeline profile, `models/*`, `config/dependencies/*`, `src/vision/runtime/*`, `infrastructure/*`, `src/vision/pyproject.toml`. The offline dependency policy is unchanged, which is the first (static) half of "F3 introduces no hidden dependency" (§19).

### 4.2 Unit-by-unit consequence

| Unit | Status at `bb331c6` | Invalidated by F1–F3? | Why | F4 action |
|---|---|---|---|---|
| B1 | OPEN (Linux probe exact; no Windows) | **Partially in content, completely as a record.** The selector, scorer, encoder, tracker and profile are untouched, so the accepted baseline (63 Tracks / 8,284 candidates / 9 fallback Representatives / 0 mismatches) is expected to reproduce. But the record binds every unit to the measured SHA, `tools/qualification/*` changed (unmapped-surface rule), and no Windows run ever existed. | Rerun fully on the final SHA: Linux run + repeat + replay, Windows run + repeat, `s1_b1.py compare`. Keep the baseline file. A mismatch is stop condition 14 of the S1.4 plan. |
| B2 | OPEN (never run) | **Completely** (never measured; `s1_memory.py` and the worker client changed). | The completion-peak term builds the 3.1 body through the real worker client; bounds 1–3 measure untouched code but were never measured. | Run every preset and the staging lifecycle on both variants (§13). |
| B3 | FAIL (synchronous, 190.8 s max) | **Completely.** The criterion, harness and path are replaced. | Architecture repair. | B3-A and B3-B on both variants with new harnesses (§8, §9). |
| B4 | PASS at `bb331c6` | **Completely.** `src/platform/*`, worker contract and shared test support changed; the ambiguity windows moved to the submission and publication transactions. | The S1.4 plan §8 amendment. | Re-derive the suite set, add proving-test map, rerun from Quality Gate and Task 10 on the final SHA (§14). |
| B5 | OPEN | **Completely.** Platform, web (`phase` type) and status semantics changed; Finalizing is a new operator-visible state. | | Real-video path through the activated 3.1 hand-off and hosted finalizer; new Finalizing items (§15). |
| B6 | FAIL (3 unapproved skips) | **Completely.** Workflow changed (PR #86), worker package changed. | | Dispatch Task 10 at the final SHA, both variants (§16). |
| Disconnected | OPEN | **Completely.** Worker, platform and web changed; the Runtime Bundle must be built from the final SHA. | | §19. |
| Windows halves of B1/B2/B3 | absent | absent | No host. | §18. |
| Prerequisite product changes before M2 | n/a | **F4-C** (configuration and activation in `src/platform/**`, the worker default in `src/vision/mavi_vision/common/settings.py`) invalidates B3, B4, B5, B6 and DISCONNECTED; **U1** (Finalizing UI, `src/web/mavi-web/src/**`) invalidates B5 and DISCONNECTED. | Both merge before M2, so their invalidation is absorbed: nothing is measured authoritatively before them. | M2 is chosen after both (§7.1). |

Nothing from `bb331c6` is reusable as a PASS. The `bb331c6` record remains what it is: an interim historical record for a superseded SHA, cited by the closure record as history only.

---

## 5. Qualification architecture

```
D0    Docs: frozen F3 plan onto main (byte-identical to 44e1f7b)  ──merge──►  main
        ▼
F4-A  Harness PR (tools/qualification, tests/, docs)  ──merge──►  M1 (main)
        │ exploratory B3-A/B3-B on M1 (non-authoritative; both OS where available)
        │ freeze decision written from the exploratory outputs (§10)
        ▼
U1    Finalizing UI product PR (src/web only; Path A)  ──merge──►  main
        ▼
F4-C  Configuration/activation freeze PR (appsettings, worker default, runbook)  ──merge──►  M2 (main)
        │   M2 = first main commit containing F4-A, U1 and F4-C (§7.1); nothing product-bearing after it
        ▼  authoritative execution at M2, in the §25 order:
        │  exact-head CI (Quality Gate, Task 10 dispatch, Task 17) → B4 → B3-A → B3-B →
        │  crash harness → B1 → B2 → B5 → disconnected → B6 retention
        ▼
F4-E  Evidence PR (docs/qualification/stage2-s1 only)  ──merge──►  M3 (closure SHA)
        │ H1: PR #87 closed unmerged as historical (at F4-E opening, before closure)
        │ diff M2..M3 must be docs-only; post-merge workflows on M3
        ▼
      closure record (§26), acceptance register, roadmaps
```

U1 may merge before F4-A or between F4-A and F4-C; it must merge before M2. If the owner chooses Path B (no U1), the flow is the same without U1 and closure stays OPEN (§6.1).

Principles:

- **Two harness kinds, one checker.** .NET harnesses (`tests/Mavi.IntegrationTests/Qualification/`) measure the platform (B3-A, B3-B, crash, API contention); Python harnesses (`tools/qualification/`) measure the worker (B1, B2) and derive counts. The checker (`s1_evidence.py`) is the only thing that says PASS, and it says it only against retained, hash-verified files on a repository.
- **Every number has a producer.** No value in the record is typed in. B3-A/B3-B stats are recomputed from the harness output's raw samples by the checker; B1 counts from `s1_b1.py`; B2 values from `derive`; suite counts from TRX/JUnit.
- **Identity is measured, not declared.** Git SHA, clean tree, OS, CPU, cores, RAM, filesystem, storage class, .NET, PostgreSQL version and the finalizer configuration are captured by the harness process and compared with the record's host and configuration blocks.
- **The activated configuration is what B3 qualifies.** B3-A, B3-B, the crash harness, B5's real-video path and the disconnected run execute with `VisionFinalization:Enabled = true` and `MAVI_COMPLETION_SCHEMA_VERSION = 3.1`. By owner decision this becomes the shipped default in F4-C, subject to the freeze measurements (§10.5).
- **B3 needs both halves.** The checker cannot PASS B3 from B3-A alone or B3-B alone (B3 plan §17 guard), nor from one OS.

---

## 6. Harness-versus-evidence separation

| PR | Content | Behavior-bearing? | Evidence allowed on its branch? |
|---|---|---|---|
| **D0 Docs housekeeping** (branch `docs/s1-4-b3-f3-plan-on-main`) | The F3 plan file, byte-identical to `git show 44e1f7b:docs/superpowers/plans/2026-09-25-s1-4-b3-f3-finalizer-recovery-implementation.md` (blob hash compared in the PR). Nothing else. | No. | Not applicable. |
| **F4-A Harness** (branch `feature/s1-4-b3-f4-harness`) | Slices F4.1–F4.7 (§24): checker/schema redesign, B3-A harness, B3-B harness, crash/recovery harness, API-contention prober, B5 record v2 and visual-QA states, storage-class/host probes, disconnected runbook. Tests first, mutants recorded in the PR. | Yes (evidence tooling, `tests/*`, `tools/qualification/*`). No product code. | **No.** Diagnostic runs to prove the harness works are allowed and are never retained as evidence. |
| **U1 Finalizing UI** (separate product PR, not part of F4; Path A) | `src/web/mavi-web/src/**` only: surface the existing API `phase == "finalizing"`, distinguish Finalizing visually and in text from generic Running, keep Processing/Completed/Failed semantics, focused UI tests. No backend or finalizer change. | **Yes, product behavior** (web). Invalidates B5 and DISCONNECTED. | **No.** |
| **F4-C Configuration freeze** (branch `feature/s1-4-b3-f4-config-freeze`) | `appsettings.json` `VisionFinalization` frozen values and `Enabled = true`, worker `completion_schema_version` default `"3.1"` (§10.5), runbook table and deployment order, ADR-006 §7 status line. | **Yes, product behavior.** The only F4 slice that changes production behaviour. | **No.** Its merge commit is M2 when U1 is already on `main` (§7.1). |
| **F4-E Evidence** (branch `evidence/s1-4-f4-<sha12>`) | `docs/qualification/stage2-s1/` only: record, summary, retained files. | No. | It *is* the evidence, produced at M2 on the qualified hosts, committed as files. |
| **Closure follow-up** | Post-merge run identities, closure block, register and roadmap edits. Docs only. | No. | Post-merge verification only. |

Rules:

1. F4-A merges before any authoritative measurement (S1.4 plan §13). If review of F4-A changes a harness after exploratory runs, those runs are discarded.
2. F4-C always changes production behaviour, because it ships the activation (§10.5) even if every timing default is kept. Its merge commit, after U1, is M2. The freeze decision is written before F4-C opens.
3. Any commit to a §2.1 path after M2 and before M3, other than F4-E's own `docs/qualification/**` files, restarts §25 for the units the checker maps it to (`closure_rerun_required`).
4. A product defect found at any point stops execution; its fix is a separate PR; the measurement SHA moves; §25 restarts for the affected units.
5. UI work is never folded into F4-A, F4-C or F4-E. U1 is its own reviewed product PR.

### 6.1 Prerequisite and housekeeping steps

| Step | When | What | Effect on evidence |
|---|---|---|---|
| **D0** | before F4-A opens | Land the frozen F3 plan on `main` docs-only (table above). Fallback if the owner declines: one docs-only PR rewriting every `main`-tree reference to `docs/s1-4-b3-f3-finalizer-plan@44e1f7b`. | none (docs) |
| **U1** (Path A, default) | after or alongside F4-A, **before M2** | The Finalizing UI product PR (table above). Its tests include: a Processing page row for a job with `phase == "finalizing"` shows a Finalizing label that is not "Running"/"Progress"; `completed` shows counts; `failed` with a `vision_finalization_*` code is not labelled as an inference failure; the existing Processing/Completed/Failed tests still pass. | invalidates B5, DISCONNECTED; absorbed because M2 follows it |
| **Path B** (owner explicitly declines U1) | recorded before M2 | F4 still executes every unit. B5 stays **OPEN** on `finalizingStateDistinct`, S1.4 does **not** close and the closure record remains OPEN. B5 is never redefined to pass without a distinct Finalizing state. | none |
| **H1** | when F4-E opens, and in any case before the closure record is written | Close PR #87 unmerged with a comment (by the owner) stating it is superseded, non-authoritative interim evidence at `bb331c6`; keep its branch as the archive. Merging it docs-only is acceptable only for a stated archival reason, and then under `docs/qualification/stage2-s1/history/bb331c6/`, which the checker never accepts as evidence (§22). | none; the checker refuses `bb331c6` artifacts |

**Owner decision (2026-09-25): Path A.** U1 lands before M2. Path B remains described only as the consequence if U1 cannot be delivered; it is not the plan.

---

## 7. Exact-SHA authority and provenance

### 7.1 Choosing the measurement SHA

- M1 = the merge commit of F4-A on `main`. It is used only for exploratory measurement (§10.4).
- M2 = the first merge commit on `main` that contains F4-A, U1 (Path A) and F4-C, and after which no product-bearing change affecting qualification merges before measurement completes. In the default order it is the F4-C merge commit. It is recorded in the evidence record's `measuredSha` before the first authoritative command runs.
- M3 = the merge commit of F4-E; the closure SHA (§7.5).
- The SHA must be reachable from `main` (`verify_measured_shas`), a merge commit and not a branch head.
- An immutable tag `qual/s1-4/<M2>` is created at M2 for Task 10 dispatch (S1.4 plan §10.1).

### 7.2 What every artifact records

Every harness output carries an `environment` block from `QualificationGate.CaptureEnvironmentAsync` (or the Python `source_identity()` / `runtime_identity()` / `host_identity()`):

`gitSha`, `gitWorkingTreeClean`, `gitCommitObjectPresent`, `capturedAtUtc`, `os`, `osArchitecture`, `processArchitecture`, `dotnet` (or Python version and the locked package identities), `logicalCores`, `postgresVersion`, `postgresVersionFull`, `pg.*` settings, `isQualificationGradeDatabase`, `testAssemblyModuleId`, `testAssemblyBuiltUtc`; plus the harness-measured `host` block (`cpuModel`, `physicalCores`, `logicalCores`, `ramBytes`, `os`, `osBuild`, `stagingFilesystem`, `acceptedEvidenceFilesystem`, `storageClass`, `storageClassEvidence`), `variant`, and for platform harnesses the `configuration` block (the effective `VisionFinalizationOptions`).

The checker compares `environment.gitSha` with the unit's measured SHA, `gitWorkingTreeClean == "true"`, `host.*` with the record's host, `variant` with the metric's variant, `configuration` with `appsettings.json` at the measured SHA (`git show`), and refuses byte-identical outputs across variants.

### 7.3 CI and workflow identity binding

Unchanged from the S1.4 plan §10.1/§10.4 and the checker: every workflow run is cited by `runId`, `workflow`, `headSha` (read from the Actions API and required to equal the measured SHA), `conclusion == success`; artifact zips are downloaded, their SHA-256 compared with GitHub's digest and recorded on the retained file's entry. Task 10 is dispatched against `qual/s1-4/<M2>`; a cancelled or superseded run is not evidence.

### 7.4 OS, host, runtime and dependency identity

| Dimension | Linux binding | Windows binding |
|---|---|---|
| OS | `/etc/os-release` name/version, kernel from `platform.version()` / `RuntimeInformation.OSDescription` | `RuntimeInformation.OSDescription`, `platform.version()` (build number) |
| CPU | `/proc/cpuinfo` model, physical/logical cores | registry `ProcessorNameString`, `GetLogicalProcessorInformation` via the existing Python probe |
| RAM | `/proc/meminfo` | `GlobalMemoryStatusEx` (Python `ctypes`, exists in `_windows_host`) |
| Filesystem | `/proc/mounts` for the staging and evidence roots (`_linux_filesystem`), `DriveInfo.DriveFormat` | `DriveInfo.DriveFormat` (NTFS expected) |
| Storage class | §17.2 probe | §18.3 |
| .NET | `RuntimeInformation.FrameworkDescription` | same |
| Python and packages | Task 10 job records; local runs record `sys.version`, Pillow/libjpeg, numpy, av, torch identity (`runtime_identity()`) | same |
| PostgreSQL | `show server_version` (must be 18) | same |
| Model / profile | `identity.profileSha256` = SHA-256 of `src/vision/config/pipelines/phase1-detection-tracking-v1.json` at M2, compared with `models/qualifications/rtmdet-m-coco-phase1-v1.json.pipelineProfileSha256` (S1.4 plan §10.2; do not edit that record) | same |

### 7.5 Measured-SHA to closure-SHA diff

`git diff --no-renames --name-only M2 M3` is retained in `closure.changedPaths` and recomputed by the checker (`verify_git_diff`). Every path is classified with `invalidated_units`. The expected content is exactly F4-E's `docs/qualification/stage2-s1/**` files (not behavior-bearing). Any other path is classified and, if it maps to a unit, that unit is re-measured on M3 before closure (`closure_rerun_required`), which means a further evidence commit; the plan expects none.

**Behavior-bearing change after measurement invalidates the affected evidence.** This is not discretionary: the checker enforces it.

---

## 8. B3-A: durable hand-off qualification

### 8.1 What is measured

One complete completion-3.1 POST at the frozen worst shape, through the real HTTP endpoint, the real validator, real payload encoding, a real PostgreSQL payload-row insert and the real `Leased → Finalizing` transition, with the hosted finalizer **off** (`EnableVisionFinalizationHost = false`) so that nothing can seal or publish during the sample. That isolates the hand-off cost and proves the hand-off returns before any finalization work.

### 8.2 Worst shape (the frozen Evidence Set contract)

- 10,000 Tracks (`WorkerContractRules.MaximumCompletionTracks`), four Observations each (`MaximumTrackObservations`, the four roles), one trajectory each: **50,000 staged objects**, 50,001 eventual Artifact rows.
- Longest canonical Track ids and numbers (the `WorkerContractV3Tests` worst document shape), so the body is the largest a valid 3.1 request can be. Its serialized size is recorded and must stay within the existing budgets the checker already binds (`b3.dotnet-worst-shape-body-bytes ≤ 32 MiB`, proving test `WorstShapeBodyFitsUnderLimit`).
- **Objects really staged.** Every crop and trajectory the request names exists under `staging/{job}/attempt-0001/`, small and distinct. Although the 3.1 hand-off does not open them, the measured request must be one the finalizer can finalize (it is the B3-B input), and the checker's `stagedObjects == 50000` check kills the "tiny payload / nothing staged" mutant. Their bytes are recorded.
- A fresh job per sample (`ResetAndMigrateAsync`, seed video, `/process`, lease), as the old harness did, so no sample benefits from a warm payload row.

### 8.3 Harness: `S1HandOffScaleTests` (replaces `S1SealingScaleTests`)

File `tests/Mavi.IntegrationTests/Qualification/S1HandOffScaleTests.cs`, `[S1QualificationFact]`, output `s1-b3a-hand-off.<variant>.json`, schema `s1-b3a-hand-off-v1`.

Per sample:

1. Stage the 50,000 objects (outside the timer).
2. Start the clock; `POST /api/vision/jobs/{id}/complete` with the 3.1 body via `HttpClient` with an infinite timeout; stop at the response.
3. Assert: `200`, `state == "finalizing"`, `tracksSubmitted == 10000`; job status `Finalizing`; one `vision_finalization_payloads` row whose `PayloadLength` and hash are recorded; **zero** Track/Observation/Artifact rows for the run; **zero** files under the accepted-evidence root; `finalizationAcceptedAtUtc` set; claim triple all null.
4. Time the exact replay (`200`, `finalizing`, no second payload row).
5. Record `VisionFinalizationSubmissionTimings` from a second in-process `SubmitAsync` on a separate job (informational split: validation / encoding / persistence), the API process RSS (`Process.GetCurrentProcess().WorkingSet64`) before and after, and PostgreSQL `pg_stat_statements`-free row counts.

Worker release proof (item "prove worker released without waiting"): the response is returned while the job is `Finalizing` with zero graph rows and the finalizer host off; additionally, a lease call from the same worker id after the response succeeds for a *different* queued job, and the 3.1 job's `LeaseToken` no longer heartbeats (`FinalizingRefusesHeartbeat…` in the domain suite). The record states this as the release proof rather than a timing.

Envelope: `MAVI_S1_HANDOFF_SAMPLES` (default 30), `MAVI_S1_HANDOFF_REPEATS` (3), `MAVI_S1_HANDOFF_WARMUP` (1, excluded), `MAVI_S1_HANDOFF_TRACKS` (10,000). Non-authoritative reasons follow the old harness's `NonAuthoritativeReasons` (envelope, samples, repeats, warm-up, timeout override, PostgreSQL 18, clean tree, commit present, qualified variant) plus `finalizerHostEnabled == true` and `stagedObjects != 50000`.

### 8.4 Statistics and criterion

- Per repeat and overall: `n`, `min`, `p50`, `p95`, `max` (nearest-rank, as `Percentile`), `p50RunSpreadMs` across repeats; raw per-sample values retained.
- Clock: `Stopwatch` (monotonic).
- **Criterion (unchanged from the S1.4 plan §7.4 amendment and B3 plan §14.1): `max ≤ 15,000 ms` on each qualified CPU variant**, which is 2× headroom against the 30 s `WorkerSettings` default. The checker keeps `b3.worker-request-timeout-ms` bound to the default at the measured SHA and computes `min(15000, timeout/2)`. No repository evidence shows a formal change to 15 s; the B3 plan §21 item 10 reaffirms it. A max above 15 s on either variant is B3 FAIL and a stop-and-report.
- Recorded, not thresholded: replay stats, timing split, RSS delta, body bytes, payload bytes, staged bytes.
- Metrics: `b3a.hand-off-wall-ms.<variant>` (timing, limit ≤ 15,000), `b3a.replay-wall-ms.<variant>` (timing), `b3a.request-body-bytes`, `b3a.payload-row-bytes`, `b3a.api-rss-delta-bytes.<variant>`.

### 8.5 Platform and storage

Linux CPU and Windows CPU Development hosts (§17, §18), PostgreSQL 18 local to the host, staging and evidence roots on the host's declared filesystem. No CUDA: neither governing plan requires it for B3 and the hand-off does not touch the model runtime.

---

## 9. B3-B: asynchronous finalization envelope

### 9.1 What is measured

The full path: 3.1 hand-off → `Finalizing` → hosted finalizer claim → payload load and revalidation → batched sealing with claim extensions → in-memory graph build → publication transaction (row lock, relational graph persistence, visibility barrier, sequence, terminal transitions, save, commit) → `Completed`, at the same 10,000-Track / 50,000-object envelope with really staged objects, through the **real** `VisionFinalizationHostedService` (not a test-driven cycle, not a mocked finalizer), the real lifecycle, executor, accepted-evidence store and PostgreSQL, with the **frozen configuration** read from `appsettings.json` (the harness does not inject options; it passes `VisionFinalization:Enabled=true` only).

### 9.2 Harness: `S1FinalizationEnvelopeTests`

File `tests/Mavi.IntegrationTests/Qualification/S1FinalizationEnvelopeTests.cs`, `[S1QualificationFact]`, output `s1-b3b-finalization.<variant>.json`, schema `s1-b3b-finalization-v1`.

Per sample (one full finalization):

1. Fresh database and evidence root; stage 50,000 objects; hand off (B3-A path; its wall time is recorded too).
2. `t0 = FinalizationAcceptedAtUtc`. Poll `/api/health` and the job row until `Completed` (or terminal failure, which fails the sample and the run).
3. Record the **publication timeline** and the other intervals from test-only instrumentation (§9.2.1, §9.2.2). Every interval is the difference of two directly observed timestamps on one monotonic clock; **no metric is derived by subtracting one interval from another.** The executor's event 1504 (captured logger provider) is retained as a cross-check only, never as the source of a metric:
   - claim acquisition latency: first successful `ClaimNextAsync` return − `t0` (bounded below by the poll interval; recorded as such);
   - payload load: `LoadInputsAsync` entry → return (decorator);
   - payload revalidation and sealing-plan build: `LoadInputsAsync` return → first `ExtendClaimAsync` entry (the executor's payload checks, `Revalidate`, and `EvidenceSealingPlan.Build` run in exactly that bracket; the decorator proves no other lifecycle call occurs in it; the metric is named for both and is not split by subtraction);
   - sealing wall: first `ExtendClaimAsync` return → last `ExtendClaimAsync` return; per-batch wall between consecutive extension returns; extension count (must equal `ceil(50000 / SealingBatchSize)` + 1);
   - adoption: `Sealing.Adopted` from the outcome (0 on a clean sample; > 0 only in the crash harness);
   - in-memory graph build, relational graph persistence, publication transaction and visibility-barrier hold: §9.2.1 and §9.2.2;
   - total hand-off-to-publication: the UTC wall time the transaction interceptor records beside the *commit completed* ticks (§9.2.1) − `t0`, cross-checked against the job's `CompletedAtUtc`;
   - longest single SQL statement: max over intercepted commands of executed − executing, compared with `CommandTimeoutSeconds` at the SHA.
4. Sample the API host RSS every second during the run (peak, mean, baseline); record.
5. Run the API-contention prober (§20) concurrently.
6. **Premature visibility probe:** every second while `Finalizing`, `GET /api/videos/{id}/processing` must show `phase == "finalizing"` with `tracksCreated` unchanged from the hand-off view, the Track search for the run must return zero results, and any Track-detail URL must be 404; the first poll after `Completed` must show the counts. Any premature row is an integrity failure of the sample.

#### 9.2.1 Publication transaction and visibility-barrier hold

The F3 publication path (`VisionFinalizationLifecycle.PublishAsync`) runs, in one transaction: (1) begin; (2) `SELECT * FROM vision_jobs WHERE id = … FOR UPDATE` and the identity checks; (3) the run/video reads and the no-graph check (`Tracks.AnyAsync`); (4) `FinalizationGraphPersistence.AddAsync` (tracking of the whole graph plus one `SaveChangesAsync`); (5) `ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync`, which executes `SELECT pg_advisory_xact_lock(1296127561, 1412505908)` through `ExecuteSqlRawAsync`; (6) `AllocateSequenceAsync` (a raw `DbCommand`, invisible to EF interceptors); (7) the terminal transitions; (8) the final `SaveChangesAsync`; (9) `CommitAsync`. **The job row lock (2) is not the visibility barrier (5).** The barrier is what blocks first-page search and other publications, and it is acquired only after graph persistence.

**Metric definition.** `b3b.visibility-barrier-hold-ms` = *commit completed* − *barrier acquired*, for the publication transaction that committed. `b3b.visibility-barrier-wait-ms` = *barrier acquired* − *barrier command started* (time spent waiting for the lock, recorded). `b3b.publish-transaction-ms` = *commit completed* − *transaction begun*.

**Instrumentation seam (test-only, registered through `ApiTestFactory.ConfigureDbContext` → `AddInterceptors`, as `FinalizationWorld` already does for `SqlTrace`; production code unchanged):**

- `PublicationTimelineCommandInterceptor : DbCommandInterceptor` overriding the `…Executing`/`…Executed` and `CommandFailed` pairs for reader, non-query and scalar commands. For each command it records `Stopwatch.GetTimestamp()` at executing and at executed, the `CommandText`, `eventData.CommandId`, `eventData.ConnectionId`, `eventData.Context` identity, and the `DbTransaction` instance (`command.Transaction`).
- `PublicationTimelineTransactionInterceptor : DbTransactionInterceptor` overriding `TransactionStarted`, `TransactionCommitting`, `TransactionCommitted`, `TransactionRolledBack` and `TransactionFailed` (sync and async). It records the ticks, the UTC wall time, `eventData.TransactionId`, `eventData.ConnectionId` and the `DbTransaction` instance. `TransactionCommittedAsync` fires only after `DbTransaction.CommitAsync` has returned successfully, which is after PostgreSQL acknowledged `COMMIT`: that is *commit completed*.
- `PublicationTimelineSaveChangesInterceptor : SaveChangesInterceptor` overriding `SavingChanges`, `SavedChanges` and `SaveChangesFailed` (sync and async), recording timestamp and context identity.
- The lifecycle decorator records `PublishAsync` entry/return and the returned `VisionFinalizationTransition`.

**Identifying the barrier command.** A command is the barrier acquisition when its `CommandText`, whitespace-normalised, equals exactly `SELECT pg_advisory_xact_lock(1296127561, 1412505908)` (the `PublicationExclusiveSql` constant; the harness reads the constant's value by reflection at start and fails if it cannot, so a changed key cannot silently stop matching). The shared variant `pg_advisory_xact_lock_shared(…)` (search) never matches. The scene-activation path uses the same SQL, but the Scene Analytics host is off in the harness and the command must also belong to the publication transaction (below), so it cannot be confused.

**Acquisition versus start.** `pg_advisory_xact_lock` returns only when the lock is granted, so the command's *executed* timestamp (`NonQueryExecutedAsync`) is *barrier acquired*; its *executing* timestamp is *barrier command started*. The two are recorded separately and never substituted for each other.

**Correlation to one transaction.** A publication timeline is the set of events whose `DbTransaction` instance is reference-equal to the one started inside a `PublishAsync` entry/return window of the decorator, on the same `ConnectionId` and `TransactionId`. That transaction must contain, in this order: the `FOR UPDATE` on `vision_jobs` whose parameter equals the claimed job id (*row lock acquired* = its executed timestamp), the first `SavingChanges`/`SavedChanges` pair (graph persistence), exactly one barrier command, the second `SavingChanges`/`SavedChanges` pair, then `TransactionCommitting` and `TransactionCommitted`. Any other shape (a second barrier command, a missing `FOR UPDATE`, events from another transaction interleaved on that transaction instance) makes the sample an integrity failure, not a metric.

**Exclusion of failed transactions.** Only a timeline that ends in `TransactionCommitted` **and** whose `PublishAsync` returned `Published` yields hold, wait and publish-transaction values. A timeline ending in `TransactionRolledBack`, `TransactionFailed`, `SaveChangesFailed` or a non-`Published` transition is retained in the output under `rejectedTimelines` with its reason and is excluded from every successful-hold statistic. In a clean B3-B sample a rejected timeline is itself a sample failure (a clean run publishes once); in the crash harness they are expected and reported separately.

**Ordering invariant (asserted per sample by the harness, recomputed by the checker):** `rowLockAcquired < graphPersistenceStart ≤ graphPersistenceEnd < barrierCommandStarted ≤ barrierAcquired < commitCompleted`, so the hold is always at most `commitCompleted − graphPersistenceEnd` and never includes graph persistence. The raw timestamps (ticks, with `Stopwatch.Frequency`) are retained per sample; the output's `holdMs` must equal the checker's recomputation from them.

**Proof the metric is not the row-lock interval.** Two discriminators ship with the harness (F4.3):

1. *Delay injection (ordinary suite, small envelope).* `BarrierHoldExcludesGraphPersistence`: a test-only command interceptor sleeps 750 ms in the executing hook of the graph's first `INSERT INTO tracks` batch. Assert that the measured hold grows by less than 100 ms against a run without the delay, while *commit completed − row lock acquired* grows by at least 750 ms. A harness that timed from the row lock fails this test.
2. *Mutant (recorded in the F4-A PR).* Replace the hold start timestamp with `rowLockAcquired`. Expected: `BarrierHoldExcludesGraphPersistence` fails, the harness's ordering invariant fails, and the checker test `test_b3b_barrier_hold_is_recomputed_from_barrier_acquisition` refuses an output whose `holdMs` equals `commitCompleted − rowLockAcquired`.

**Pre-repair reference (B3 plan §14.3).** The B3 plan asks for no regression above the corresponding post-graph publication phase of the pre-repair path. That phase was not retained with this instrument at `bb331c6`, and the ≈ 2 s figure in PR #87 is a prototype observation of a different interval, so it is **not** used. Instead the same interceptors measure the synchronous `ProcessingResultStore` completion (unchanged by F3, same graph-then-barrier order) at M2 with the gate off and a 3.0 worst-shape request: one repeat of at least 5 samples, informational, `b3b.reference-sync-barrier-hold-ms.<variant>`. A B3-B hold above the reference max is reported for review, not auto-failed.

#### 9.2.2 Graph build versus graph persistence

Four different quantities, each with its own producer:

| Quantity | Where it runs | Start timestamp | End timestamp | Metric |
|---|---|---|---|---|
| In-memory graph build | `FinalizationGraphBuilder.Build` in the executor, after the last extension and before `PublishAsync` | last `ExtendClaimAsync` return (decorator) | `PublishAsync` entry (decorator) | `b3b.graph-build-ms.<variant>`, informational |
| Relational graph persistence | `FinalizationGraphPersistence.AddAsync` inside the publication transaction | executed timestamp of the no-graph check (`SELECT EXISTS … FROM tracks WHERE processing_run_id = …`), the last command before `AddAsync` | executing timestamp of the barrier command, the first command after `AddAsync` | `b3b.graph-persistence-ms.<variant>`, recorded (required by B3 plan §14.3) |
| Graph `SaveChanges` | the one `SaveChangesAsync` inside `AddAsync` | first `SavingChanges` in the publication transaction | its `SavedChanges` | `b3b.graph-savechanges-ms.<variant>`, recorded |
| Publication transaction / barrier hold | §9.2.1 | | | `b3b.publish-transaction-ms`, `b3b.visibility-barrier-hold-ms` |

The bracket for graph persistence contains only `AddAsync`. The harness proves it per sample: every command and `SaveChanges` event observed between its two endpoints belongs to the first `SavingChanges`/`SavedChanges` pair, and the pair lies inside the bracket. The graph-build bracket is proven likewise: no lifecycle call and no intercepted command occurs between its endpoints. A sample that violates either proof fails. Graph build is informational only; graph persistence is required.

Discriminators (F4.3): `GraphPersistenceIsMeasuredAroundAddAsync` (ordinary suite): with the 750 ms delay on the graph `INSERT`, `graph-persistence-ms` grows by at least 750 ms and `graph-build-ms` grows by less than 100 ms; without the delay `graph-persistence-ms > 0` and `graph-savechanges-ms ≤ graph-persistence-ms`. Checker tests refuse an output whose `graphPersistenceMs` is zero, is missing its raw endpoints, or equals `publishTransactionMs − Σ(SQL)` or any other value not equal to the recomputation from its two endpoints.

Envelope: `MAVI_S1_ENVELOPE_SAMPLES` (default 10 per repeat), `MAVI_S1_ENVELOPE_REPEATS` (3), `MAVI_S1_ENVELOPE_WARMUP` (1). Minimum authoritative: **n ≥ 30 total across ≥ 3 repeats**, warm-up excluded, per S1.4 plan §12. Budget: at the development host's ≈ 1.2 ms per sealed object plus ≈ 15 s graph persistence (PR #87 engineering observations), one sample is ≈ 90–150 s; 33 samples ≈ 1–1.5 h per OS. Throughput = 10,000 Tracks / total wall per sample and objects / seal wall, recorded.

Concurrency behaviour (recorded): one repeat hands off two jobs back to back with `MaxConcurrentFinalizations = 1` from configuration; the second must stay `Finalizing` and unclaimed until the first publishes (`liveClaims ≤ 1` throughout), and both publish exactly once. This is an integrity check, not a timing.

### 9.3 Criteria

| Metric | Rule | Source |
|---|---|---|
| `b3b.total-hand-off-to-publication-ms.<variant>` | timing; **`max ≤ ½ × MaximumFinalizationDurationSeconds × 1000`** with the frozen value (B3 plan §14.2) | pass/fail |
| `b3b.claim-extension-count.<variant>` | `== ceil(50000 / SealingBatchSize) + 1`; proves extension exercised and the batch size in force | pass/fail |
| `b3b.premature-visibility-observed.<variant>` | `== 0` | pass/fail |
| `b3b.publications-per-job.<variant>` | `== 1` | pass/fail |
| `b3b.longest-statement-ms.<variant>` | `≤ CommandTimeoutSeconds × 1000` at the SHA | pass/fail |
| `b3b.publication-timeline-valid.<variant>` | every successful sample has a complete §9.2.1 timeline satisfying the ordering invariant, and the §9.2.2 bracket proofs hold; `== samples` | pass/fail |
| `b3b.visibility-barrier-hold-ms.<variant>` | timing from *barrier acquired* to *commit completed* (§9.2.1), recomputed from raw timestamps; compared with `b3b.reference-sync-barrier-hold-ms.<variant>` and a hold above the reference max is reported for review, not auto-failed (B3 plan §14.3) | recorded |
| `b3b.graph-persistence-ms.<variant>`, `b3b.graph-savechanges-ms.<variant>` | timing around `FinalizationGraphPersistence.AddAsync` (§9.2.2); must be > 0 | recorded (required present) |
| `b3b.seal-wall-ms`, `b3b.publish-transaction-ms`, `b3b.visibility-barrier-wait-ms`, `b3b.claim-acquisition-ms`, `b3b.payload-load-ms`, `b3b.payload-revalidation-and-plan-ms`, `b3b.graph-build-ms` (each `.<variant>`) | timing, recorded, each from two direct timestamps | recorded |
| `b3b.reference-sync-barrier-hold-ms.<variant>` | synchronous-path reference with the same instrument (§9.2.1), n ≥ 5 | recorded |
| `b3b.api-host-rss-peak-bytes.<variant>`, `b3b.throughput-tracks-per-s.<variant>`, `b3b.throughput-objects-per-s.<variant>` | recorded | recorded |
| `b3b.orphan-bytes-after-faults.<variant>` | from the crash harness (§11), recorded | recorded |

"Worker independence": the harness never runs a worker process; the hand-off is issued by the test client and nothing of it survives the response. The crash harness adds the real-worker-process variant (§11 row 1).

No mocked finalizer, no in-memory shortcut: the harness registers only the timing decorator, the three timeline interceptors of §9.2.1 and the captured logger; the checker requires `hostedServiceUsed == true` and `optionsSource == "appsettings.json"` in the output and refuses an output whose `configuration` differs from `appsettings.json` at the SHA.

---

## 10. Configuration freeze methodology

### 10.1 Inputs

From the **exploratory** B3-B runs at M1 (both OS where available), with the development defaults in force.

All inputs are in **seconds**: harness milliseconds ÷ 1000, ticks ÷ `stopwatchFrequency`, with no intermediate rounding. Each input is the maximum of its own metric over every sample, warm-up included, of every available OS. The governing OS may differ per input. Field-level definitions are in the execution plan (`2026-09-25-s1-4-f4-m1-to-m2-execution-plan.md` §7.0).

- `S_batch_max`, `S_batch_p95`: wall between consecutive extension returns (one `SealingBatchSize` batch, including one extension round trip);
- `G_max`: in-memory graph build, last extension return → `PublishAsync` entry;
- `P_max`: publication transaction, begin → commit completed;
- `T_max`, `T_p95`: total hand-off-to-publication;
- the first-claim interval (claim return → initial extension return) and extension overhead (Σ extension round-trips / seal wall): **not retained by the M1 harness**. They are not used as inputs (§10.2, §10.7).

### 10.2 Rules

| Value | Rule | Rationale |
|---|---|---|
| `SealingBatchSize` | keep 200. The overhead trigger (> 5 %, raise) cannot be evaluated because extension round trips are not retained. If `S_batch_max > ClaimExtensionSeconds / 4` against the M1 value (300 s), stop and report: a changed batch size cannot be measured at M1 and is never estimated | batches bound how much work a lost claim wastes and how often ownership is re-proven |
| `ClaimExtensionSeconds` | `E_req = 4 × max(S_batch_max, G_max + P_max)`; `ClaimExtensionSeconds = max(M1 value, ceilTo(E_req, 30))` | a stalled batch must not lose the claim spuriously, **and** the last extension's grant must survive graph build and the publication transaction, whose claim-fenced completion re-proves ownership (§10.7); 4× is the margin |
| `ClaimSeconds` | `ClaimSeconds = max(M1 value, ClaimExtensionSeconds, ceilTo(4 × T_max, 60))` | the initial claim must survive claim → initial extension, an interval not retained but contained in hand-off → publication, so `T_max` bounds it; `ClaimSeconds ≥ ClaimExtensionSeconds` as the options validator requires |
| `MaximumFinalizationAttempts` | keep 3; if the crash harness shows adoption needs more, stop and report (not changed in F4-C) | three chances before a job is exhausted |
| `MaximumFinalizationDurationSeconds` | `M_req = max(MaximumFinalizationAttempts × (ClaimSeconds + 2 × T_max), 2 × T_max)`; `M_bound = ceilTo(M_req, 300)`; stop if `M_bound > 21600`, otherwise keep the M1 value (21,600 s) | the product recovery requirement: every permitted attempt can run to completion at twice the measured worst case, after waiting out a dead predecessor's claim |
| `PollIntervalSeconds` | keep 5 | contributes ≤ 5 s to the effective bound; API-host load negligible |
| `MaxConcurrentFinalizations` | keep 1 unless the API-contention record shows headroom **and** a product need is stated; F4 expects to keep 1 | the finalizer shares the API process |
| `PayloadCleanupGraceSeconds` | keep 0 | not timing-bearing |

`ceilTo(x, g) = g × ⌈x / g⌉`. **Never lower:** every rule yields a floor, and no value is frozen below its M1 committed value (§10.7).

The effective bound is computed and written into the freeze decision: `MaximumFinalizationDurationSeconds + ClaimSeconds + PollIntervalSeconds`. It must be operationally acceptable, and the record states it in hours.

If `M_bound` exceeds the development default (21,600 s), or the effective bound exceeds 24 h, stop and report: the measurement says the envelope is slower than the architecture assumed. With the `ClaimSeconds` rule, `M_bound ≤ 21600` holds exactly when `T_max ≤ 1200 s`. This is an activation stop, not a B3 criterion (§10.7).

### 10.3 The freeze is a reviewed decision, not a fit to the criterion

The B3-B criterion (`T_max ≤ ½ Max`) is satisfied by construction of the rule for `Max`. That is intended: the criterion checks that the frozen product limit leaves margin over the measured worst case, and the freeze must not be tightened later without re-measurement. What the rules do **not** do is pick values that merely make the checker green: each value is derived from a named measurement with a stated multiplier, and the freeze decision document (§10.6) shows the arithmetic.

### 10.4 Sequence

1. Merge F4-A → M1. Run exploratory B3-A and B3-B on each available OS. These outputs are retained under `docs/qualification/stage2-s1/exploratory/<M1-sha12>/` in the F4-C PR, labelled non-authoritative (`authoritative: false`, reason `exploratory-configuration-freeze`).
2. Apply §10.2. Write the freeze decision (§10.6).
3. F4-C commits `appsettings.json` (the frozen timing values, whether or not they differ from the development defaults, and `Enabled = true`), the worker default `"3.1"`, and the runbook configuration and deployment-order paragraphs (§10.5). Merge after U1 (Path A), so that its merge commit is M2 (§7.1). **A configuration commit changes behaviour; M2 is a new exact SHA and every authoritative measurement happens there.** The freeze never lands after authoritative measurement has started.
4. If the exploratory measurements fail the activation gate of §10.5, F4-C is not opened: F4 stops and reports.
5. Authoritative B3-B at M2 with the frozen values, both OS. If it fails its criterion, stop and report; do not re-freeze from the authoritative run.

### 10.5 Activation defaults (owner decision: ship 3.1 / Finalizing)

The shipped default at `480afb0` (`Enabled=false`, worker `3.0`) is the path that failed B3. **Owner decision (2026-09-25): the qualified shipped path becomes completion 3.1 / Finalizing, subject to the freeze measurements.** F4-C therefore sets, together with the frozen timing values:

- `src/platform/Mavi.Api/appsettings.json`: `VisionFinalization:Enabled = true`;
- `src/vision/mavi_vision/common/settings.py`: `completion_schema_version` default `"3.1"`, with the worker tests that pin the default flipped (`test_the_default_worker_emits_the_synchronous_completion`, `test_the_default_worker_refuses_a_hand_off_acknowledgement`, `test_the_default_worker_accepts_the_pre_activation_platform`, `test_a_platform_listing_only_completion_3_1_is_unsupported_for_the_default_worker` become their 3.1 counterparts), and the activation-gate tests (`VisionFinalizationActivationGateTests`) updated only where they assert the shipped default;
- the runbook: the activation sequence becomes the normal deployment order for this release, and the drain-before-disable procedure becomes the rollback path.
  - **Activation:** the platform on every host with the gate held off; the worker fleet stopped; the contract changed and verified on every host directly; then workers started on 3.1.
  - **Rollback:** the worker fleet stopped; drain; the contract changed back and verified on every host; then workers started on 3.0.
  - In both directions the worker fleet is stopped for the whole contract change, so no worker leases while hosts could advertise different completion contracts (execution plan §11.3).

"Subject to the freeze measurements" means: the activation lands in F4-C only if the exploratory B3-A and B3-B at M1 meet their criteria under the §10.2 rules (B3-A max ≤ 15 s on each available OS; B3-B max within ½ of the derived `MaximumFinalizationDurationSeconds`; no §30 stop condition such as a derived `M_bound` above the development default (§10.2), an effective bound above 24 h, premature visibility or more than one publication). If any of those fails, F4-C does not activate: F4 stops and reports, and the activation is re-decided after a separate product repair. With the activation shipped, B3 PASS, the disconnected run and B5's real-video path all describe the shipped default, and the §26 non-claim about an unactivated default does not apply.

### 10.6 Freeze decision document

`docs/qualification/stage2-s1/f4-configuration-freeze.md` records:
- the M1 SHA;
- hosts;
- exploratory outputs and hashes;
- the measured inputs per OS and pooled, with the governing OS of each input, all in seconds;
- the statement that the first-claim interval and extension overhead are not retained at M1, and that `ClaimSeconds` therefore uses the conservative `4 × T_max` bound;
- the rule arithmetic, including the never-lower comparison with each M1 value;
- the chosen values;
- the effective bound;
- the activation decision;
- reviewer sign-off.

The evidence record's `frozenConfiguration` block repeats the values, and the checker compares them with `appsettings.json` at M2.

### 10.7 Amendment (2026-09-25, execution-plan review): claim sizing and never-lower

This corrects rules of §10.2. It is not an architecture change. F3's lifecycle, the B3 criteria (§8.4, §9.3) and the checker are unchanged.

1. **`ClaimExtensionSeconds` must cover publication.** The original rule, `≥ 4 × S_batch_max`, sized only a batch, and was unsafe.
   - The executor extends the claim before sealing and after every batch (`VisionFinalizationExecutor`). The last extension precedes graph build and `PublishAsync`.
   - `VisionFinalizationLifecycle.PublishAsync` persists the graph, acquires the visibility barrier and allocates the sequence. It then calls `VisionJob.CompleteFinalization`, which re-proves `FinalizationOwnedBy(claimToken, now)`.
   - The claim live at that instant is the **last extension's grant** (`ClaimExtensionSeconds`), not the initial `ClaimSeconds` grant.
   - A batch-only extension (for example 30 s) could expire during graph persistence. The publication then rolls back as stale, and every retry repeats it until the job is exhausted.
   - Corrected rule (§10.2): `E_req = 4 × max(S_batch_max, G_max + P_max)`, all in seconds.
2. **`ClaimSeconds` uses a proven bound.** The first-claim interval is not retained at M1, and no retained per-batch value is a proven upper bound on it. It lies inside `[acceptedAtUtc, commitCompleted]`, so `T_max` bounds it; §10.2 uses `4 × T_max`. A future harness revision may retain the exact interval if a tighter value is wanted.
3. **Never lower.** The deadline runs from `FinalizationAcceptedAtUtc` for every `Finalizing` row, claimed or not. Reconciliation exhausts a never-claimed row at the deadline. With `MaxConcurrentFinalizations = 1`, lowering `MaximumFinalizationDurationSeconds` toward the per-job formula would exhaust a backlog of unattempted hand-offs. Lowering claim durations changes recovery latency, which F4 does not qualify. Every derived value is a floor over the M1 committed value.

---

## 11. Crash and recovery qualification matrix

Classification: **H** = executable qualification harness at the 10,000-Track envelope with a real process kill (`S1FinalizationRecoveryTests`, opt-in, output `s1-b3-crash-matrix.<variant>.json`); **I** = discriminating unit/integration evidence already in the Quality Gate (TRX-cited by B4 through the proving-test map, §14); **D** = documented, non-authoritative regression (cannot be executed genuinely in F4; stated with reason).

| # | Scenario | Class | Evidence (existing test at `480afb0`, or harness step) | Invariants proven |
|---|---|---|---|---|
| 1 | Worker death immediately after hand-off | **H** + I | H: a real `mavi_vision` worker process (the Task-10 fixture harness `tools/vision/dev/fixture_worker_harness.py` path, CPU) completes 3.1 and is `SIGKILL`ed on the `finalizing` acknowledgement; the hosted finalizer publishes. I: `WorkerDeathImmediatelyAfterHandOffDoesNotMatter` | worker independence; truthful terminal state |
| 2 | Host death before first claim | H + I | H: API host process (spawned `Mavi.Api` with the test configuration) killed after hand-off, before its first cycle; restarted host publishes. I: `HostDiesBeforeTheFirstClaimAndTheNextHostFinalizes`, `HostRecoversFinalizingRowsOnStartup` | staging survives; one publication |
| 3 | Host death after claim, before first seal | I | `HostDiesBeforeTheFirstSealAndTheReclaimSealsEverything`; `ExpiredClaimIsReclaimedWithARotatedTokenAndTheOldTokenIsDead` | rotated token; old token dead |
| 4 | Host death mid-seal | **H** + I | H: kill at ≈ 40 % of the seal (by object count from a progress file the harness's sealer decorator writes), restart, second host adopts the sealed objects (`Sealing.Adopted > 0`, `Created + Adopted == 50000`), publishes once. I: `HostDiesMidSealAndTheReclaimAdoptsWhatWasSealed` | identical evidence adopted; no compensation deletion; no duplicate sequence |
| 5 | Claim expiry mid-seal with a live reclaimant | I | `ClaimLostMidSealStopsWithoutWritingAndTheLiveClaimantPublishes` | stale claimant cannot alter outcome |
| 6 | Stale claimant after reclaim performs IO | I | `StaleClaimantCannotPublish`, `StaleClaimantCannotExtendFailOrNote`, `AnExpiredClaimCannotPublishEvenWithoutAReclaim` | harmless create-once IO only |
| 7 | All objects sealed, crash before publication | I | `HostDiesAfterAllSealsBeforePublicationAndTheReclaimAdoptsAndPublishes` | adoption; one publication |
| 8 | DB failure during graph persistence | I | `ADatabaseFaultDuringGraphPersistenceIsARetryWithNothingWritten`, `ADatabaseFaultDuringPublicationIsATransientRetry` | no partial visibility; transient |
| 9 | Ambiguous commit that succeeded | I | `AmbiguousCommitThatSucceededIsNotRepublishedAndTheNoteWritesNothing`, `AmbiguousCommitThatSucceededEndsAsLostAndIsNotRepublished` | no double publication; no duplicate sequence |
| 10 | Ambiguous commit that did not succeed | I | `AmbiguousCommitThatFailedIsNotedAndTheRetryPublishesOnce` | exactly one publication |
| 11 | Death after commit before cleanup | I | `ProcessDiesAfterCommitBeforeCleanupAndALaterCycleCleansThePayload`, `PayloadCleanupIsTerminalOnlyGraceBoundedAndIdempotent` | truthful terminal state; cleanup idempotent |
| 12 | Final permitted claimant crash | I | `FinalPermittedClaimantCrashIsExhaustedByReconciliation`, `FinalPermittedClaimantDiesAndTheHostExhaustsTheJob`, `ExhaustFinalizationTakesNoTokenRetainsHandOffFactsAndCannotPublish` | deterministic exhaustion; `vision_finalization_exhausted` |
| 13 | Absolute duration exhaustion with a live claim | I | `DurationExceededLiveClaimIsNotKilledImmediatelyAndIsExhaustedAfterItExpires`, `ExecutorStopsSealingWhenTheDeadlineIsReached`, `ExecutorPublishesAfterTheDeadlineIfSealingWasComplete`, `ClaimSqlAndDomainAgreeAtTheDeadlineInstant` | deadline refuses claim and extension at the authority boundary (F3 plan §17 item 5) |
| 14 | Two hosts racing one job | **H** + I | H: two spawned API hosts share the database and evidence root; exactly one 1504, `liveClaims ≤ 1`, one sequence. I: `TwoHostsRacingOneJobProduceExactlyOnePublication`, `ClaimIsExclusiveUnderConcurrency` | one live owner |
| 15 | Reconciliation racing publication | I | `ReconciliationSkipsALiveClaimAndARowLockedByAPublisher` | exhaustion cannot bypass a live claim |
| 16 | Janitor while Finalizing | I | `JanitorCyclesDuringFinalizingNeverRemoveTheInputAndTheFinalizerSucceeds`, `FinalizingJobCurrentAttemptIsPreservedIndefinitelyAndSupersededAttemptsAreReclaimed`, `FinalizingJobLaterAttemptIsPreservedAndReportedOnce`, `FinalizingThenTerminalKeepsTheGraceRule` | staging survives Finalizing |
| 17 | Malformed claim metadata | I | `MalformedClaimIsNeverClaimedOrExhaustedAndIsReportedOnce`, `MalformedClaimsAreReportedOncePerHostAndCounted`, `MalformedClaimIsNotClaimableNotExhaustibleNotOwned` | fail closed; visible in health |
| 18 | Worker permanently absent | I + D | I: rows 1, 11 (nothing in finalization needs the worker). D: the real-time statement "a job whose worker never returns still reaches a terminal state within the effective bound" cannot be executed at real clock in F4 (hours); it is proven with the injected clock (`MutableTimeProvider`) by rows 12–13 and stated as such | truthful terminal state within the bound |
| 19 | Publication ordering (graph before barrier, sequence last) | I | `PublicationCommitsTheGraphCompletionSequenceAndVideoTogether`, `NothingIsVisibleBeforeThePublicationCommit`, `PublicationRefusesAWrongAttemptOrDigestAsStale`, `PublicationFailsClosedWhenTheRunIsNotRunningOrAGraphAlreadyExists` | no partial visibility; no double publish |

The H harness records per scenario: kill point (object index, wall time), restart latency, adoption counts, orphan bytes (event 1509 when applicable), final state, publication count, sequence count, and it asserts the invariants; its output is cited by B3 (`b3.crash-matrix-output.<variant>`) and the checker requires every H row `passed`. Real process kills require the harness to spawn `Mavi.Api` as a child process with the test connection string and evidence root; that is test infrastructure in `tests/`, not product code.

Mutants the H harness must discriminate (applied to a scratch copy of the product during F4-A review, never committed): a finalizer that skips ownership re-proof under the row lock (row 14 must see two 1504s); a sealer that recreates instead of adopting (row 4 must see `Adopted == 0` with 50,000 created and refuse); a publication that writes the sequence before the graph (row 19 probe must see rows before `Completed`).

---

## 12. B1: deterministic Evidence Set selector

Decision: **rerun fully at M2, keep the accepted baseline.** F1–F3 did not touch the pipeline set, so the expected outcome is the same as at `bb331c6`: 63 Tracks, 8,284 candidates, 9 fallback Representatives, 0 mismatches in every comparison. The reasons a rerun is still mandatory: the record binds units to M2; `tools/qualification/*` changed; Windows B1 never existed (the accepted baseline has no Windows half, so the cross-variant comparison has never been derived); and no PASS is carried forward.

Execution at M2 (S1.4 plan §5.3, unchanged): original MOT17-02-FRCNN and MOT17-13-FRCNN files by SHA-256; the locally built `mmcv` wheel by SHA; Linux run, separate-process repeat, `--record-detections` / `--replay-detections`; Windows run and repeat on the qualified Windows host with the Windows golden pin; `s1_b1.py compare` → `b1-comparison.json`; the four counts must be 0. A divergence traced to the encoder cap on one variant is recorded as a trace with reviewer; an untraced one is stop condition 14.

Suites: the eight B1 suites from Task 10 at M2 on both variants (`task10:s1-boundary` and `task10:real-clip-harness` results). Without a Windows host B1 stays OPEN (§18).

---

## 13. B2: retirement, live memory and staging lifecycle

Governing plan §6.2 / §6.3 and the checker's `B2_BASE_MEASUREMENTS` are reviewed and found unchanged in requirement: per-live held-evidence bytes ≤ 544 KiB; buffered trajectory points ≤ 4,096 (one chunk); per-retired traced slope ≤ 16 KiB with duration and crop variations ≤ 10 % (undefined variation fails closed); process-memory retired slope ≤ 16 KiB (USS on Linux, `PrivateUsage` commit charge on Windows, tracemalloc off, ≥ 5,000 retirements); per-live process slope over ≥ 5 stepped live levels, reconciled with bound 1, recorded; completion peak recorded; staging peak within the run's derived bound; the §6.3 lifecycle checks; native ByteTrack adapter for every authoritative preset.

Decision: **run fully at M2 on both variants** (it was never run). Presets `b2-retained-baseline`, `b2-retained-long`, `b2-retained-large-crops`, `b2-process-memory`, `b2-completion-peak`, `b2-live-{4,8,16,32,64}`, then `staging-lifecycle`, then `derive`, each in its own process, on the host's declared staging filesystem. Budget ≈ 2.5 h per variant (Harness A record §3).

Separation: B2 measures the **Python worker process**; B3-B measures the **.NET API host process** (`b3b.api-host-rss-peak-bytes`). The record names them differently and the checker refuses a B2 metric that cites a B3-B artifact or vice versa (`measurement_unbound` already requires a unit's own artifact).

F2's change to `s1_memory.py` (completion body built as 3.1 through the real worker client) is verified by `tools/qualification/tests/test_s1_memory.py` in the Task-10 `s1-qualification-harness` step; B2 cites that step.

---

## 14. B4: contract, digest, durable hand-off, publication and rollback

Treated as **invalidated**. The re-derived suite set (all exist at `480afb0`):

| Suite | Proves |
|---|---|
| `src/vision/tests/test_worker_completion_v3.py` (Task 10, both variants) | worker 3.1 emission, golden byte equivalence, probe fencing (`…accepts_a_platform_listing_completion_3_1`, `…only_completion_3_0_is_unsupported_for_a_3_1_worker`), hand-off acknowledgement (`test_a_finalizing_acknowledgement_is_the_hand_off`, `…completed_acknowledgement_is_an_idempotent_replay`, `…malformed_or_foreign_acknowledgement_is_refused`), staging survives (`test_current_attempt_staging_survives_the_hand_off`) |
| `src/vision/tests/test_worker_client.py`, `test_worker_runner.py` | client/runner 3.1 behaviour |
| `tests/Mavi.Application.Tests/CompletionDigestGoldenTests`, `CompletionExchange31Tests` | digest v3 equality, 3.1 normalisation (`A31BodyNormalizesToV3AndKeepsTheV3Digest`), payload codec, phase mapping |
| `tests/Mavi.Domain.Tests/VisionFinalizationDomainTests` | state machine, fencing, deadline, exhaustion |
| `tests/Mavi.IntegrationTests/VisionResultCompletionV3ApiTests`, `VisionResultCompletionApiTests` | 2.0 synchronous path and 3.0-while-off (unchanged), v2 replay |
| `VisionFinalizationSubmissionApiTests` | durable hand-off, replay, concurrent identical/conflicting submissions, 3.0 refusal when active, body bound |
| `VisionResultCompletionCommitFailureTests` | **replay after ambiguous submission commit** (`CommitThatSucceededButReportedFailureIsResolvedByTheIdenticalRetry`, `FailureBeforeTheCommitWithAnUnconfirmedRollbackStillLeavesNothingCommitted`) |
| `VisionFinalizationActivationGateTests` | gate semantics |
| `VisionFinalizationLifecycleTests`, `VisionFinalizationPublicationTests`, `VisionFinalizationExecutorTests`, `VisionFinalizationHostTests`, `VisionFinalizationRecoveryTests` | publication transaction, ambiguous publication commit, retry/adoption, no compensation deletion (`NoAsynchronousFinalizationSourceReferencesAcceptedEvidenceDeletion`, `RetryAdoptsIdenticalAcceptedObjectsWithoutDeletingAnything`, `ConflictingAcceptedObjectFailsClosedAndIsNeverTouched`), PostgreSQL authority |
| `VisionFinalizationPersistenceTests`, `TrackEvidenceSetMigrationTests` | migration and read-back |

`B4_PROVING_TESTS` (new, §22): a map from each B4 property in the S1.4 plan §8 as amended (Python/.NET agreement; v2 replay; v3 replay idempotent; submission-commit ambiguity both ways; publication-commit ambiguity both ways; no duplicate sequence/graph; no compensation deletion; adoption; staging survives) to a named test above; the checker requires each to have passed in the cited TRX/JUnit. A test the map names that does not exist at the measured SHA is `proving_test_missing`, and `test_b4_proving_tests_exist_in_the_source` holds the map to the source tree so it cannot cite a renamed test.

B4 is run from the Quality Gate run at M2 (TRX) and the Task-10 `s1-boundary` step (JUnit), both variants for the Python suite. Artifact `b4.completion-v3-golden` stays; add `b4.completion-v3-1-example` (the 3.1 example and schema hashes).

---

## 15. B5: read, UI and operator truthfulness

### 15.1 Automated (Quality Gate at M2)

`TrackEvidenceSetReadApiTests`, the web suite, plus the F1 web tests (`videos.test.ts`, `ProcessingPage.test.tsx`, `ProcessingQueuePage.test.tsx`, `VideoImportPage.test.tsx`).

### 15.2 Real-video path (activated configuration)

Two clips (MOT17-02-FRCNN, MOT17-13-FRCNN) through `Video → import → VisionJob → real CPU worker (3.1) → hand-off → hosted finalizer → publication → GET Track detail → Investigation → Review`, on the Linux Development host with `Enabled=true` and worker `3.1`. Recorded per clip (record schema `s1-b5-real-video-record-v2`):

- `completionAccepted` (the `finalizing` acknowledgement), `finalizingObserved` (the processing status API showed `phase == "finalizing"` at least once with the pre-hand-off `tracksCreated`), `prematureVisibilityAbsent` (no Track search hit, no Track detail, no analytics readiness change while Finalizing), `completedAfterAsyncPublication` (phase `completed` with counts only after event 1504), `trackDetailVerified`, `evidenceSetVerified`, plus the S1.4 plan §9.2 characteristics (four-role Track, partial Track, long Track, crowded interval; recorded present or absent) and the declared-in-advance example rule.
- Failed finalization: a **fixture** item (never real accepted evidence): staging removed before the first claim → `vision_finalization_staging_missing`; the status API and Processing page show a failure that is not labelled as an inference failure (`FinalizationFailureIsNotLabelledAsAnInferenceFailure` is the automated twin). Labelled `fixture`.

### 15.3 Operator UI

Viewports 1366×768, 1440×900, 1920×1080, ≈ 2560×1080 through `tools/web-visual-qa` with new states `processing-finalizing`, `processing-failed-finalization` in `states.mjs` (fixture data driven by the API shapes), plus the existing Evidence Set states over real footage. Visual-QA record schema `s1-b5-visual-qa-v2` adds items `finalizingStateDistinct`, `failedFinalizationDistinct`, `noPrematureCounts`.

**Sequencing prerequisite (§2.4, §6.1).** At `480afb0` the Processing page renders `run.status`, never `phase`; a Finalizing job is shown as Running/Progress, so `finalizingStateDistinct` cannot pass on current `main`. The plan therefore depends on U1:

- **Path A (default).** U1, a small separate reviewed web PR, lands before M2. It surfaces the existing `phase == "finalizing"`, distinguishes Finalizing from Running in text and visually (not by colour alone, UI/UX specification §26), preserves Processing/Completed/Failed semantics, adds focused UI tests, and changes no backend. It invalidates B5 and DISCONNECTED, which is absorbed because M2 follows it. F4-A may build the visual-QA states before U1 merges, but authoritative B5 and disconnected evidence come only from M2. The `processing-finalizing` visual-QA state asserts the Finalizing label is present and the Running/Progress label is absent.
- **Path B (owner explicitly declines U1).** Every other unit still executes. B5 stays **OPEN** on `finalizingStateDistinct`, S1.4 does **not** close, and the closure record remains OPEN. The criterion is not relaxed.

F4 itself adds no UI code.

---

## 16. B6: Task-10 runtime qualification rerun

At M2: tag `qual/s1-4/<M2>`, `workflow_dispatch` Task 10 against the tag, verify `head_sha == M2`, both variants green with no skip outside `APPROVED_PAIRED_SKIPS` (PR #86 is merged, so the three probe tests run in `runtime-probe-real-torch`), retain the seven JUnit files and six JSON records per variant with hashes and the artifact digest from the API, bind `bytetrack-qualification.json.headSha` and `production-composition-qualification.json.headSha` to M2. Content-hash every retained file. Post-merge: Quality Gate `push` run on M3, Task 10 dispatch on `qual/s1-4/<M3>`, Task 17 on M3 (S1.4 plan §10.4). The RTMDet qualification record is not edited; its `pipelineProfileSha256` is reconciled (§7.4).

---

## 17. Linux qualification host

- Variant `linux-x86_64-cpu`, x86_64, Ubuntu 24.04 (the development container class that produced `bb331c6`: Intel Xeon @ 2.10 GHz, 4 vCPU, 15.7 GiB, kernel 6.18, ext4 on virtio) or a declared equivalent; Python 3.12.14 with the locked packages for B1/B2; .NET 10 SDK; PostgreSQL 18 local on the host (port and data directory recorded).
- Every local run: clean tree at M2 (`git status --porcelain` empty), `gitCommitObjectPresent`, `MAVI_QUALIFICATION=1`, `MAVI_QUALIFICATION_OUT` under the evidence staging directory, `MAVI_S1_*_EVIDENCE_ROOT` and `--work-root` on the declared filesystem.

### 17.2 Storage class probe (F4-A)

`process_memory.py`/`s1_memory.py host_identity()` and the .NET `QualificationGate` gain `storage_class(path)`: resolve the block device of the mount (`/proc/self/mountinfo` → `/sys/class/block/<dev>`), read `queue/rotational` (0 → `ssd`, 1 → `hdd`), `nvme*` → `nvme`, `vd*`/`xvd*`/virtio or a network filesystem type → `virtual` with the device name as evidence, otherwise `unknown`. The schema gains enum values `virtual` and `unknown` and the required field `storageClassEvidence` (the probe's raw reading). The `bb331c6` record's `network` assumption is not edited (PR #87 untouched); every new host block is probed. The checker refuses a host whose `storageClass` is `hosted-runner` for any timing metric of B3, and refuses `unknown` without evidence text.

---

## 18. Windows qualification strategy

### 18.1 What needs a Windows host

B3-A and B3-B (NTFS write-through publication is the Windows-specific cost), the crash harness H rows (process kill semantics differ), B2 (commit charge, native tracker), B1 Windows run and repeat, the disconnected run if the Windows variant is chosen (§19). B6 Windows is hosted CI and needs no local host.

### 18.2 Host requirements and binding

Windows 10/11 or Server x64 with the Development prerequisites (PostgreSQL 18, .NET 10 SDK, Python 3.12.10 with the locked packages incl. Pillow 11.3.0 / libjpeg-turbo 3.1.1 for the golden pin, ffmpeg), NTFS staging and evidence roots on a local disk. Binding per artifact: `variant == "windows-x86_64-cpu"` (`RuntimeVariant()`), OS build (`RuntimeInformation.OSDescription`, `platform.version()`), CPU from the registry, RAM from `GlobalMemoryStatusEx`, `DriveInfo.DriveFormat == "NTFS"`, .NET and Python identities, model/profile SHA, PostgreSQL 18 version string.

### 18.3 Storage class on Windows

`Get-PhysicalDisk | Select DeviceId, MediaType, BusType` output retained as an artifact (`host.windows-physical-disk`) with the disk that backs the evidence volume named; `storageClass` set from `MediaType` (SSD/HDD/NVMe from `BusType`), `storageClassEvidence` = the retained command output hash. No new .NET or Python dependency (no WMI library); it is an operator step with a retained output.

### 18.4 If no Windows host is producible

B1, B2 and B3 remain OPEN (their Windows halves are required by the checker's `QUALIFIED_CPU_VARIANTS`); S1.4 does not close. The record states "no qualified Windows Development host available" per unit with the date, and the closure record lists it as unresolved. Reducing the qualified variant set is a plan amendment for the owner, not an F4 decision (§30 question 3). Hosted `windows-latest` runners are `hosted-runner` storage and shared CPUs: acceptable for B6, refused for timing units by the checker.

---

## 19. Disconnected qualification strategy

1. Build the Runtime Bundle from M2 on a connected build host: `tools/vision/build_offline_bundle.py --source-commit <M2> --platform-variant linux-x86_64-cpu …`; retain the manifest (`sourceCommit == M2`, `platformVariant`, single `mavi-vision` wheel SHA-256). The companion binary kit is verified against M2's lock files (S1.4 plan §11).
2. Clean Development install on an isolated host (adapter disabled or deny-all outbound firewall; method recorded), with `VisionFinalization:Enabled=true` and `MAVI_COMPLETION_SCHEMA_VERSION=3.1` in the install configuration. **F4-A adds to the runbook's Development install steps the 3.1 activation configuration**, so that the disconnected run exercises the qualified path; no installer code changes.
3. `assert_outbound_internet_unavailable` before and after (retained outputs; five targets); system proxy state recorded (`netsh winhttp show proxy` on Windows; `env | grep -i proxy` and `/etc/apt` / pip index config on Linux); LAN mirror unreachable recorded.
4. Run: setup verification, worker start, real recorded video, 3.1 hand-off, finalizer publication, sealed Track evidence, Track detail, Review/Investigation; each outcome with its own retained evidence from the same local run (checker rule).
5. **Hidden-dependency proof for F3.** Static: `git diff bb331c6 M2 -- config/dependencies/ src/vision/pyproject.toml src/platform/**/*.csproj Directory.Packages.props src/web/mavi-web/package*.json` is empty for dependency additions (recorded as `disconnected.dependency-diff`). Dynamic: `strace -f -e trace=connect` (Linux) or the Windows Firewall dropped-packet log over the whole run; zero non-loopback attempts, retained.
6. Manifest/hash checks: bundle manifest, wheel hash, model pack manifest and the `resolved-config.json` identity; tool versions (`python --version`, `dotnet --version`, `node --version`) retained.

The disconnected variant is Linux unless a Windows host is available for both; the checker requires the host OS to match the declared variant.

---

## 20. API-host contention

Prober inside `S1FinalizationEnvelopeTests` (§9.2 step 5): a separate `HttpClient` issuing, at 2 requests/s, a rotation of `GET /api/health`, `GET /api/tracks/search?…` (against a previously completed run seeded before the sample), `GET /api/tracks/{id}` (Track detail with a four-role Evidence Set), `GET /api/videos/{id}/processing`. Recorded per endpoint: p50/p95/max latency and error count, **baseline** (30 s idle window before the hand-off) versus **during** finalization, with API-host RSS and process CPU time sampled every second.

Interpretation: **informational**, no invented threshold (B3 plan §14.7). It becomes a stop-and-report only if an endpoint returns 5xx, exceeds `RequestCancellationMiddleware`'s existing limit, or the prober's own client timeout (100 s default), during finalization. Metrics: `b3b.api-<endpoint>-baseline-p95-ms.<variant>`, `b3b.api-<endpoint>-during-p95-ms.<variant>`, `b3b.api-errors-during-finalization.<variant>` (`== 0`, pass/fail because an error is a functional failure, not a latency judgement), `b3b.api-host-cpu-seconds.<variant>`.

---

## 21. Evidence artifact schema and layout

```
docs/qualification/stage2-s1/
  s1-qualification-evidence.json              # the record (schema s1-qualification-evidence-v1, extended)
  s1-qualification-summary.md                 # human-readable
  f4-configuration-freeze.md                  # §10.6
  b1-accepted-real-clip-baseline.json         # unchanged
  exploratory/<M1-sha12>/b3a/, b3b/           # non-authoritative freeze inputs
  evidence/<M2-sha12>/
    quality-gate/{trx/*.trx, junit/mavi-web.xml}
    task10/<variant>/{junit/*.xml, *.json}
    b1/{linux,linuxRepeat,linuxReplay,windows,windowsRepeat}.summary.json, b1-comparison.json
    b2/<variant>/{<preset>.json, staging-lifecycle.json, b2-derived.json}
    b3a/<variant>/s1-b3a-hand-off.json
    b3b/<variant>/s1-b3b-finalization.json
    crash/<variant>/s1-b3-crash-matrix.json
    b4/{vision-job-complete-v3.1.example.sha256, …}
    b5/{real-video-record.json, visual-qa-record.json, captures/*.png}
    disconnected/{run-record.json, bundle-manifest.json, isolation-before.json, isolation-after.json,
                  dependency-diff.txt, connect-trace.txt, <outcome>.json…}
    hosts/<host-id>/{probe.json, windows-physical-disk.txt}
  .gitattributes                              # binary/large handling as in PR #87
```

Every harness output (machine-readable, JSON) carries: `schema`, `status` (`complete`), `authoritative` + `nonAuthoritativeReasons`, `runId`, `environment`, `host`, `variant`, `configuration` (platform harnesses), `shape` (tracks, observations, objects, bytes), `commands` (argv and env names used), `startedAtUtc`/`finishedAtUtc`, `samples` (raw per-sample values), `stats` (`n`, `min`, `p50`, `p95`, `max`, `p50RunSpreadMs`, `warmupExcluded`, `repeats`), and, for the record, its SHA-256 in `retainedArtifacts`. The B3-B output additionally carries, per sample, `publicationTimeline` (`stopwatchFrequency`, raw ticks for `transactionBegun`, `rowLockAcquired`, `graphPersistenceStart`, `graphSavingChanges`, `graphSavedChanges`, `graphPersistenceEnd`, `barrierCommandStarted`, `barrierAcquired`, `finalSavingChanges`, `finalSavedChanges`, `commitStarted`, `commitCompleted`, the transaction and connection ids, the barrier `CommandText`, the `PublishAsync` transition), `graphBuildBracket` (`lastExtensionReturned`, `publishEntered`), `bracketProofs` (booleans with the offending event if false), and `rejectedTimelines`; derived millisecond values are present for readability only and are recomputed by the checker. Record additions: `frozenConfiguration` (the `VisionFinalization` values, `effectiveBoundSeconds`, `activationDefault`), `hosts.*.storageClassEvidence`, `hosts.*.dotnetRuntime`, `hosts.*.postgresVersion`, `hosts.*.pythonVersion`; new artifact ids `b3a.hand-off-output.<variant>`, `b3b.finalization-output.<variant>`, `b3.crash-matrix-output.<variant>`, `b4.completion-v3-1-example`, `disconnected.dependency-diff`, `disconnected.connect-trace`.

Keys are added only where §22 names them; naming follows the existing `<unit>.<metric>.<variant>` convention and the existing schema's `additionalProperties: false` discipline.

---

## 22. Checker and schema changes (`tools/qualification/s1_evidence.py`, schema)

Remove (with their tests rewritten, not deleted silently): `SEALING_WALL_METRIC`, `SEALING_OUTPUT_ARTIFACT`, `WORST_CASE_SEALED_OBJECTS` as a sealing constant (kept as `WORST_CASE_OBJECTS = 50_000` for B3-A/B3-B shape checks), `_sealing_output`, the 2× rule on the synchronous wall in `_b3_headroom`, `completion_headroom_insufficient`, `sealing_output_unbound`/`sealing_output_mismatch`, the `S1SealingScaleTests.cs` entry of `ALWAYS_EVIDENCE`.

Add:

| Rule | Code | Discrimination test (each a mutation of the complete fixture record or of a retained file) |
|---|---|---|
| B3 requires `b3a.hand-off-wall-ms.<v>` (timing, ≤ min(15,000, timeout/2)) on both variants | `hand_off_bound_violated`, `variant_result_missing` | max 15,001 refused; Windows metric missing refused |
| B3 requires `b3b.total-hand-off-to-publication-ms.<v>` ≤ ½ frozen max, both variants; plus the §9.3 pass/fail metrics | `finalization_bound_violated` | value above ½ refused; **B3-A-only record refused** (`b3b_missing`); B3-B-only refused |
| B3-A output binding: schema `s1-b3a-hand-off-v1`, `tracks == 10000`, `stagedObjects == 50000`, `state == finalizing`, `finalizerHostEnabled == false`, `graphRowsAfterHandOff == 0`, `acceptedFilesAfterHandOff == 0`, git SHA, clean, variant, filesystem, host fields, stats recomputed from `samples` | `b3a_output_mismatch` | tracks 200 refused; `finalizerHostEnabled true` refused (a harness that waited for finalization); stats not equal to recomputation refused; a Linux output relabelled Windows refused (`variant`); byte-identical outputs across variants refused |
| B3-B output binding: schema `s1-b3b-finalization-v1`, `hostedServiceUsed`, `optionsSource == appsettings.json`, `configuration == appsettings.json@measuredSha` (`git show`), extension count formula, `prematureVisibilityObserved == 0`, `publicationsPerJob == 1`, API-contention block present, RSS series present, longest statement ≤ command timeout at SHA | `b3b_output_mismatch`, `frozen_configuration_mismatch` | configuration differing from appsettings refused; `MaximumFinalizationDurationSeconds` in the output larger than committed refused (deadline extension disabled / loosened mutant); extension count 0 refused (extension disabled mutant); premature visibility 1 refused (publication before graph mutant); publications 2 refused (double publish); RSS block absent with PASS refused; API block absent refused |
| `frozenConfiguration` block required for B3 PASS, equal to appsettings at SHA | `frozen_configuration_missing` | absent refused |
| Crash matrix: `b3.crash-matrix-output.<v>` with every H row `passed`, and `B3_PROVING_TESTS` extended with the I rows (test names of §11) required passed in the cited TRX | `crash_matrix_incomplete`, `proving_test_missing` | one row failed refused; a renamed test refused; `test_b3_proving_tests_exist_in_the_source` |
| B4 suite set and `B4_PROVING_TESTS` (§14) | `proving_test_missing` | each mapped property missing refused; source-existence test |
| B5 record v2 items | `b5_record_invalid` | `finalizingObserved false` refused; `prematureVisibilityAbsent false` refused |
| Storage class: enum + evidence; `hosted-runner` refused for B3 timings; `unknown` needs evidence | `storage_class_unbound` | typed `ssd` without evidence refused; `hosted-runner` on B3-A refused |
| Disconnected: `dependency-diff` and `connect-trace` artifacts required; activation configuration recorded in the run record (`activated: true`) | `disconnected_run_incomplete` | trace with one non-loopback attempt refused (**disconnected network access**); a run record without `activated` refused |
| Artifact from another run: every B3 artifact's `runId` must equal the `environment.runId` inside the file and the run it cites | `artifact_run_mismatch` | file from a different run id refused |
| SHA mismatch | existing `head_sha_mismatch`, `unit_sha_unbound`, plus `environment.gitSha` inside every output | output at another SHA refused |
| Windows reused from Linux | `variant` field + byte-identity refusal + `junit_variant_reused` analog for harness outputs (`output_variant_reused`) | Linux file copied under the Windows id refused |
| Visibility-barrier hold recomputed from raw ticks: `(commitCompleted − barrierAcquired) / frequency`; ordering invariant of §9.2.1; barrier `CommandText` equals the exclusive-lock SQL at the measured SHA (read with `git show` from `ProcessingVisibilityBarrier.cs`); only committed, `Published` timelines counted | `barrier_hold_unbound`, `publication_timeline_invalid` | `test_b3b_barrier_hold_is_recomputed_from_barrier_acquisition`: an output whose hold equals `commitCompleted − rowLockAcquired` refused; ordering violated refused; a shared-lock `CommandText` refused; a rolled-back timeline counted as a hold refused; a timeline with no `commitCompleted` refused |
| Graph persistence recomputed from its two endpoints; > 0; bracket proof true; `graph-savechanges ≤ graph-persistence`; no metric of §9.3 is accepted without both raw endpoints | `graph_persistence_unbound`, `metric_without_producer` | zero refused; value equal to `publishTransactionMs − Σ SQL` (subtraction mutant) refused; missing endpoints refused; bracket proof false refused |
| Every measurement of a platform harness must equal the checker's recomputation from the output's raw samples/timestamps; a typed-in value that disagrees is refused | `metric_without_producer` | record value edited by 1 ms refused |
| Stale or historical evidence: every retained artifact of a PASS unit must lie under `docs/qualification/stage2-s1/evidence/<measured-sha12>/` (or the closure SHA's), never `evidence/bb331c6/`, `history/` or `exploratory/` | `artifact_not_from_measured_sha` | a `bb331c6` JUnit cited refused; an exploratory B3-B output cited refused |
| B5 PASS requires `finalizingStateDistinct` passed in the visual-QA record on the measured SHA; Path B is recorded as OPEN | `b5_record_invalid` | item false or absent refused |

Every rule ships with its negative test in `tools/qualification/tests/test_s1_evidence.py` and is mutation-tested during F4-A review (each rule's condition inverted or removed must fail at least one test; the PR records the mutant list). `s1_evidence.py` remains standard library + `jsonschema`.

---

## 23. Measurement methodology (per metric)

| Element | Rule |
|---|---|
| Warm-up | ≥ 1 excluded sample per repeat, attested (`warmupExcluded`) |
| Samples | n ≥ 30 for per-item timings (B3-A, B3-B, API contention); B3-B may reach 30 across three repeats of 10 |
| Repeats | ≥ 3, each a fresh process where the harness allows (B2 presets: one process each; .NET harnesses: one process, fresh factory/database per sample) |
| Statistics | min, p50, p95, max (nearest rank), p50 run-to-run spread; raw samples retained; the checker recomputes |
| Clock | `Stopwatch` (.NET) / `time.perf_counter` (Python); wall clock only for timestamps |
| Environment identity | §7.2 on every output |
| Outliers | never removed; a max-bound failure is a failure even if p95 passes (the checker binds `max`) |
| Cache state | cold database per sample (reset and migrate), cold evidence root; page cache not flushed (recorded as "warm OS cache") |
| Fixture | frozen worst shape; object bytes recorded; the same generator on both OS |
| Counts | rows/objects/bytes asserted equal to the expected shape per sample |
| Thresholds | only those stated in §8.4, §9.3, §20; everything else recorded with a regression interpretation |
| Never average away a bound | a single sample above a max bound fails the unit |

---

## 24. Implementation slices

Each slice: files; tests first; invariants; commands; production behaviour changed?; evidence invalidated; authoritative measurement allowed yet?

### D0 Frozen F3 plan onto `main` (docs, before F4-A)
- **Files:** `docs/superpowers/plans/2026-09-25-s1-4-b3-f3-finalizer-recovery-implementation.md`, created from `git show 44e1f7b:<path>`; the PR states the blob hash and that `git hash-object` of the new file equals it.
- **Production behaviour:** no. **Invalidates:** nothing. **Authoritative:** not applicable.

### U1 Finalizing UI (separate product PR, not F4; Path A, before M2)
- **Files:** `src/web/mavi-web/src/features/processing/*` (and shared status components only if needed), with focused tests. No backend change.
- **Production behaviour:** **yes** (web). **Invalidates:** B5, DISCONNECTED. **Authoritative:** no; M2 follows it.

### F4.1 Checker and schema redesign (F4-A)
- **Files:** `tools/qualification/s1_evidence.py`, `s1-qualification-evidence.schema.json`, `tests/test_s1_evidence.py`, fixtures (a complete fixture record with B3-A/B3-B/crash/frozen-configuration blocks; sample outputs), `docs/qualification/2026-09-24-s1-4-harness-a.md` (a §2 addendum for the new rules).
- **Tests first:** every §22 negative test written red before the rule; `test_a_complete_record_passes_with_no_finding` updated.
- **Invariants:** no new dependency; a PASS still needs a repository; old records (`bb331c6`) are not edited and would now fail schema, which is correct (they are historical).
- **Commands:** `$PY -m pytest tools/qualification/tests -q`; `python tools/verify_repo.py`.
- **Production behaviour:** no. **Invalidates:** every unit (unmapped surface), already invalidated. **Authoritative measurement:** no.

### F4.2 B3-A harness (F4-A)
- **Files:** `tests/Mavi.IntegrationTests/Qualification/S1HandOffScaleTests.cs` (new), delete `S1SealingScaleTests.cs` (its `TheMeasuredEnvelopeIsTheEnforcedEnvelope`, `OnlyTheFullEnvelopeInAQualifiedEnvironmentIsAuthoritative`, `PercentileIsNearestRank` move to the new class), `QualificationGate.cs` (storage-class probe, configuration capture).
- **Tests first:** the three ordinary-suite facts above; a fact that the harness refuses to run with the finalizer host enabled; a fact that a reduced envelope is non-authoritative.
- **Invariants:** finalizer host off; zero graph rows after the response; output claims-then-overwrites (`Begin`/`Write`).
- **Commands:** `MAVI_QUALIFICATION=1 MAVI_QUALIFICATION_OUT=… MAVI_S1_HANDOFF_EVIDENCE_ROOT=… dotnet test tests/Mavi.IntegrationTests --filter "FullyQualifiedName~S1HandOffScaleTests"`; diagnostic at `MAVI_S1_HANDOFF_TRACKS=500` for review.
- **Production behaviour:** no. **Authoritative:** no (diagnostic only).

### F4.3 B3-B envelope harness and API-contention prober (F4-A)
- **Files:** `S1FinalizationEnvelopeTests.cs`, `Qualification/FinalizationTimingDecorator.cs` (test-only `IVisionFinalizationLifecycle` decorator), `Qualification/PublicationTimelineInterceptors.cs` (the command, transaction and save-changes interceptors of §9.2.1), `Qualification/PublicationTimeline.cs` (correlation, ordering invariant, bracket proofs, rejected timelines), `Qualification/ApiContentionProber.cs`; `ApiTestFactory` gains `ConfigurationOverrides` only if needed to pass `Enabled=true` with appsettings values (it already sets `VisionFinalization:Enabled` from `EnableAsynchronousFinalization`).
- **Tests first:** ordinary facts at a small envelope: `BarrierHoldExcludesGraphPersistence` and `GraphPersistenceIsMeasuredAroundAddAsync` (the 750 ms delay discriminators of §9.2.1/§9.2.2); `ATimelineWithoutCommitIsRejected` (a `CommitFaults`-style interceptor makes commit throw; the timeline lands in `rejectedTimelines` and yields no hold); `TheBarrierCommandIsTheExclusiveLockConstant` (reflection read of `PublicationExclusiveSql`; a shared-lock command is not matched); `TheReferenceSynchronousPathIsTimedWithTheSameInstrument`; the extension-count formula; the premature-visibility probe fails a sample when a Track row is inserted by hand during Finalizing; the decorator and interceptors change no outcome (the executor and publication tests pass with them registered). Mutants recorded in the PR: hold start replaced by `rowLockAcquired`; graph persistence computed by subtraction from `PublishAsync`; commit end replaced by `TransactionCommitting`.
- **Invariants:** real hosted service; options from appsettings; no product change; decorator and interceptors add timestamps only.
- **Commands:** `MAVI_QUALIFICATION=1 … dotnet test … --filter "FullyQualifiedName~S1FinalizationEnvelopeTests"`; diagnostic at `MAVI_S1_ENVELOPE_TRACKS=500`.
- **Production behaviour:** no. **Authoritative:** no.

### F4.4 Crash and recovery harness, B4 proving map (F4-A)
- **Files:** `S1FinalizationRecoveryTests.cs` (spawns `Mavi.Api` child processes; kills by PID; progress file via the `ControllableSealer`-style decorator), `B4_PROVING_TESTS` and `B3_PROVING_TESTS` extension in `s1_evidence.py`, source-existence tests.
- **Tests first:** the mutants of §11 applied on a scratch copy and recorded; ordinary fact that the harness refuses to run against a database it did not create.
- **Invariants:** exactly one 1504 per job; `Created + Adopted == 50000`; no `DeleteAcceptedAsync` (existing source scan).
- **Commands:** `MAVI_QUALIFICATION=1 … --filter "FullyQualifiedName~S1FinalizationRecoveryTests"`.
- **Production behaviour:** no. **Authoritative:** no.

### F4.5 B5 record v2 and visual-QA states (F4-A)
- **Files:** `s1_evidence.py` B5 rules, schema `s1-b5-real-video-record-v2`/`s1-b5-visual-qa-v2` in the checker's expectations, `tools/web-visual-qa/states.mjs` (+ fixtures), README. No `src/web` change: the distinct Finalizing rendering is U1's (§6.1).
- **Tests first:** checker negatives; visual-QA state self-test (`--states processing-finalizing --keep`).
- **Production behaviour:** no. **Authoritative:** no.

### F4.6 Host identity and storage-class probes, Windows binding (F4-A)
- **Files:** `tools/qualification/process_memory.py` / `s1_memory.py` (`storage_class`), `QualificationGate.cs` (`StorageClassOf`), `tests/test_s1_memory.py`, docs for the Windows `Get-PhysicalDisk` step.
- **Tests first:** parsing of `rotational`, device-name classification, `virtual` evidence; Windows probe test paired-skipped on Linux (added to `APPROVED_PAIRED_SKIPS` with its counterpart).
- **Production behaviour:** no. **Authoritative:** no.

### F4.7 Disconnected runbook and activation binding (F4-A)
- **Files:** `docs/runbooks/vision-runtime-model-component-lifecycle.md` (Development install: 3.1 activation configuration; disconnected S1 procedure incl. `strace`/firewall log and the dependency diff), `s1_evidence.py` disconnected rules (§22).
- **Production behaviour:** no. **Authoritative:** no.

**F4-A PR review gate:** all mutants killed and listed; `dotnet build MAVI.sln --configuration Release` warning-free; `python tools/verify_repo.py`; full `Mavi.IntegrationTests` serial run green (the new harnesses skip); `tools/qualification/tests` green on the qualified Task-10 job (both variants) via the PR's own Task-10 run. Merge → **M1**.

### F4.8 Exploratory measurement and configuration freeze (F4-C)
- **Files:** `docs/qualification/stage2-s1/f4-configuration-freeze.md`, `exploratory/<M1>/…`, `src/platform/Mavi.Api/appsettings.json` (frozen values, `Enabled = true`), `src/vision/mavi_vision/common/settings.py` (worker default `"3.1"`) and the default-pinning tests listed in §10.5, `VisionFinalizationActivationGateTests` where it asserts the shipped default, runbook table and deployment order, `VisionFinalizationOptionsTests` if defaults change, ADR-006 §7 status line.
- **Tests first:** options tests for the frozen values (validation rules hold: `ClaimExtensionSeconds ≤ ClaimSeconds ≤ MaximumFinalizationDurationSeconds`); worker default tests.
- **Invariants:** values derived by §10.2 from retained exploratory outputs; no other product change.
- **Production behaviour:** **yes** (timing values and the 3.1 / Finalizing activation). **Invalidates:** B3, B4, B5, DISCONNECTED (platform), B3/B4/B5/B6/DISCONNECTED (worker default). **Authoritative:** no on this branch; it merges after U1, and its merge commit is M2 (§7.1).

### F4.9 Authoritative execution at M2 (no code)
- §25 order, on the Linux and Windows hosts and the isolated host; outputs staged outside Git, then copied into `evidence/<M2>/` with hashes.
- **Authoritative:** yes.

### F4.10 Evidence PR, closure and post-merge (F4-E)
- **Files:** `docs/qualification/stage2-s1/**` only; then, after merge, the closure block, `docs/reviews/2026-09-23-visual-attributes-acceptance.md` B1–B6 rows, both capability roadmaps, the PR #87 disposition note (step H1: closed unmerged as historical).
- **Gate:** `s1_evidence.py check` reports `s1-evidence-record-valid` with the verdicts; the checker's diff rule on M2..M3; post-merge workflows on M3.
- **Production behaviour:** no.

---

## 25. Authoritative execution order (at M2)

Preconditions, in order: D0 merged; F4-A merged (M1); exploratory B3-A/B3-B at M1 and the freeze decision; U1 merged (Path A) or Path B recorded; F4-C merged; M2 fixed per §7.1. If any product-bearing change merges after M2 before step 12, the affected units restart.

1. Record `measuredSha = M2` and the host blocks (probed). Create tag `qual/s1-4/<M2>`.
2. Exact-head CI: Quality Gate `push` run on M2 (retain TRX/JUnit), Task 10 dispatched on the tag (retain per-variant JUnit and records), Task 17. Verify `head_sha`.
3. **B4** from step 2 (cheap; a failure here stops everything).
4. **B3-A** Linux, then Windows (≈ 1–2 h each incl. staging).
5. **B3-B** Linux, then Windows, with the API-contention prober and the premature-visibility probe (≈ 1.5–2 h each).
6. **Crash harness** Linux, then Windows (≈ 1 h each).
7. **B1** Linux (run, repeat, replay), Windows (run, repeat), compare.
8. **B2** all presets and lifecycle, Linux then Windows (≈ 2.5 h each), derive.
9. **B5** real-video path on Linux (two clips through the real worker, activated), visual QA at four widths, fixture failed-finalization item.
10. **Disconnected** run (bundle from M2, isolated host, probes, trace).
11. **B6** retention from step 2; reconcile the profile SHA.
12. Assemble the record; `s1_evidence.py check`; write the summary; open F4-E; step H1 (owner closes PR #87 unmerged as historical).
13. Merge F4-E → M3; run/verify post-merge workflows on M3; write the closure block; second `check`; confirm H1 is done before the closure record is final.

Any stop condition at a step halts the sequence; the record is committed in its current state as OPEN/FAIL with the reason (a truthful partial record is preferred to a delayed complete one).

---

## 26. Closure record structure

`s1-qualification-summary.md` at closure contains, in order:

1. Authoritative measured SHA (M2) and closure SHA (M3), tag names, the measured→closure diff and its classification.
2. Qualified identity: profile id/version/SHA (`503225be…` expected), selector/scorer/encoder, completion schema 3.1 / digest 3, qualified variants.
3. Harness and checker identity: F4-A merge SHA, `s1_evidence.py` SHA-256 at M2, schema version.
4. Host identity per host (Linux, Windows, disconnected): CPU, cores, RAM, OS/build, filesystems, storage class with evidence, .NET, Python, PostgreSQL, isolation method.
5. B1–B6 and disconnected verdict table with the unit's measured SHA and artifact ids.
6. B3-A statistics per variant (n, repeats, min/p50/p95/max, spread, bound, headroom) and the release proof.
7. B3-B statistics per variant for every §9.3 metric, kept as distinct fields: in-memory graph build, relational graph persistence and its `SaveChanges`, publication transaction, visibility-barrier wait and hold (from barrier acquisition to observed commit), the synchronous-path reference hold measured with the same instrument; the extension count, throughput and RSS peak.
8. Frozen configuration, effective bound, activation default decision, freeze-document reference.
9. Crash-matrix outcome: H rows with kill points and adoption counts; I rows with test names; the D row statement; orphan bytes.
10. API contention: baseline versus during, per endpoint; errors (0).
11. Invalidation map applied (§4) and the reruns performed.
12. Non-claims: Production qualification; CUDA/E2E (pending or recorded); model accuracy; Visual Attributes; S2; the RTMDet record unchanged; the shipped default configuration only if the activation did not land (§10.5; by owner decision it is expected to land); Windows halves if absent.
13. Unresolved items and open questions with owners.
14. Independent cold-review reference and the acceptance-register update.
15. Prerequisites: D0 merge SHA, U1 merge SHA (or the recorded Path B decision, with B5 OPEN), F4-C merge SHA, and PR #87's disposition (closed unmerged as historical, never cited as evidence).

---

## 27. Non-goals

No S2 capability binding, attributes, OCR/ANPR or ReID; no selector/scorer/profile change; no model accuracy or CUDA work; no workflow engine, separate finalizer process, distributed lock, orphan collector or accepted-evidence format change; no bulk COPY or parallel sealing (B3 plan §20: only if repaired-architecture measurement shows an independent operational need, and then as a separate reviewed slice, never inside F4); no UI change inside F4 (the Finalizing rendering is the separate U1 product PR, §6.1); no edit to `models/qualifications/*`; no edit to PR #87's content (it is closed unmerged as historical in step H1); no new dependency (`config/dependencies/offline-dependency-policy-v1.json` untouched; a harness needing one is redesigned). A genuine product failure stops F4 and is reported.

---

## 28. Completion criteria

F4 is complete when:

1. F4-A is merged with every §22 rule discrimination-tested and the §11 harness mutants recorded as killed.
2. The freeze decision exists, its values and `Enabled = true` are in `appsettings.json` at M2, the worker default is `"3.1"` at M2, and the effective bound is stated.
2a. D0 is merged, so no `main`-tree reference to the F3 plan dangles.
2b. U1 is merged before M2 (Path A), or Path B is recorded and the closure record is OPEN with B5 OPEN on `finalizingStateDistinct`.
2c. The B3-B barrier hold and graph persistence are recomputed by the checker from retained raw timestamps, and the §9.2.1/§9.2.2 discriminators and mutants are recorded as killed.
2d. PR #87 is closed unmerged as historical (or merged under `history/` for a stated archival reason), and no `bb331c6` artifact is cited.
3. The evidence record at M2 passes `s1_evidence.py check` against the repository with every unit's verdict truthful; B3 PASS requires B3-A and B3-B on both variants, the crash matrix, the frozen configuration and no premature visibility.
4. The measured→closure diff is docs-only, or every affected unit was re-measured on M3.
5. Post-merge Quality Gate, Task 10 and Task 17 on M3 are green with verified `head_sha`.
6. The closure record (§26), the acceptance register and the roadmaps agree; S1 is marked complete only if B1–B6 and the disconnected unit are all PASS, which includes B5's `finalizingStateDistinct`. Otherwise the record states exactly what is OPEN and why, and S1 stays open.
7. The independent cold review of the executed record raises no P1/P2.

---

## 29. Cold self-review (as a non-author)

| # | Attack surface | Finding | Sev | Amendment folded in |
|---|---|---|---|---|
| 1 | B3-A measured with nothing staged (a request the finalizer could not finalize) | The F2 diagnostic stages nothing; a harness copying it would be attackable as "tiny payload" | P2 | §8.2 requires 50,000 real staged objects; checker `stagedObjects == 50000` |
| 2 | B3-A harness silently waits for finalization (host on) and reports a longer, "safer" time, or a harness that never proves the worker was released | Would conflate B3-A with B3-B | P1 | §8.1 host off; checker refuses `finalizerHostEnabled true`; release proof §8.3 |
| 3 | B3-B with test-injected options rather than the frozen file | Would qualify a configuration nobody ships | P1 | §9.1 options from `appsettings.json`; checker `frozen_configuration_mismatch` via `git show` |
| 4 | Freeze tuned to pass the ½ criterion | The rule for `Max` satisfies it by construction | P2 (acknowledged) | §10.3 states it and requires the arithmetic; the criterion's value is the margin, and re-freezing from the authoritative run is forbidden (§10.4 item 5) |
| 5 | Config freeze commit measured on the wrong SHA | Exploratory at M1 mistaken for authoritative | P1 | §6 rule 2, §10.4, `authoritative: false` with reason on exploratory outputs; the checker refuses non-authoritative outputs |
| 6 | Shipped default still synchronous after closure | B3 PASS would describe a configuration the product does not run by default | P1 (decision) | Owner decision: F4-C ships 3.1 / Finalizing, gated on the freeze measurements (§10.5); if the gate fails, F4 stops rather than shipping an unqualified default |
| 7 | Windows evidence reused from Linux | Copy under another id | P2 | §22 byte-identity refusal + `variant` inside every output |
| 8 | Crash matrix "covered" only by clock-injected integration tests | Real process loss never exercised | P2 | §11 H rows with real kills at the envelope; D row stated honestly |
| 9 | Premature visibility judged only by the automated publication test | A regression in a read endpoint would pass | P2 | §9.2 step 6 live probe during every B3-B sample; §15.2 `prematureVisibilityAbsent` |
| 10 | Deadline extension disabled or loosened in the measured binary | Would pass timing | P2 | §22: output configuration equals committed; extension count formula; crash row 13 |
| 11 | Storage class typed in (`network` at `bb331c6` was an assumption) | Host identity unmeasured | P2 | §17.2, §18.3 probes and evidence field; `unknown` needs evidence |
| 12 | Disconnected run on the pre-activation path | Would prove the retired path offline | P1 | §19 step 2 activation in the install configuration; checker `activated: true` |
| 13 | Hidden dependency introduced by F1–F3 | Finalizer in-process, no policy change; but dynamic proof absent | P2 | §19 step 5 static diff + connect trace artifacts required |
| 14 | UI does not show Finalizing (§2.4) | B5 truthfulness cannot pass; F4 must not fix it | P1 (product gap) | Revision 2: U1 is a sequencing prerequisite of M2 (Path A, §6.1, §15.3); Path B keeps closure OPEN; the criterion is never relaxed |
| 15 | B1 carried forward because "nothing relevant changed" | Record binding and Windows absence make that unsound | P2 | §12 full rerun |
| 16 | B2 completion-peak term measured against 3.0 | F2 already moved it to 3.1; verify via its tests | P3 | §13 cites the Task-10 harness step |
| 17 | Checker passes B3 from B3-A alone / B3-B alone / one OS | B3 plan §17 guard | P1 | §22 explicit refusals and tests |
| 18 | API contention given an invented threshold | Would fail or pass on nothing | P3 | §20 informational; only functional errors fail |
| 19 | Timing decorator or prober changes production behaviour | Would measure a different system | P2 | §9.2: test-only decorator registered by the harness; executor tests pass with it; production code untouched (§27) |
| 20 | Closure diff includes a late "small" product fix | Would break §7.5 | P1 | Checker `closure_rerun_required`; §6 rule 3 |
| 21 | Task 10 run superseded by cancel-in-progress on `main` | `head_sha` drift | P2 | Tag dispatch (§7.1, §16) |
| 22 | The F3 plan cited by the runbook is not on `main` | Dangling reference; reviewers cannot find §17 | P2 (docs) | Revision 2: step D0 lands it byte-identical before F4-A |
| 23 | Two-host crash rows need two API processes on one host: port and evidence-root collisions | Harness infra risk | P3 | §11 note: child processes with distinct ports, shared DB and evidence root, in `tests/` |
| 24 | B3-B budget underestimated (n ≥ 30 full finalizations per OS) | ≈ 1.5–2 h per OS is acceptable; if a sample exceeds 10 min the envelope is slower than assumed | P3 | §9.2 budget stated; §10.2 stop rule on the bound |
| 25 | `MaxConcurrentFinalizations` frozen without justification | Task asks for justification | P3 | §10.2 keep 1 unless contention evidence and product need |

### 29.1 Cold self-review of revision 2

| # | Attack surface | Finding | Sev | Resolution |
|---|---|---|---|---|
| 26 | Barrier timestamp starts too early | Revision 1 timed from the job `FOR UPDATE`, which includes graph persistence | P1 (review) | §9.2.1: start = executed timestamp of the exact exclusive-lock command; delay discriminator and row-lock mutant; checker recomputation |
| 27 | Commit not actually observed | A `SaveChanges` or `TransactionCommitting` end would miss the server acknowledgement | P2 | End = `TransactionCommitted` (after `CommitAsync` returns); mutant "commit end = committing" recorded in F4.3 |
| 28 | Barrier command misidentified (shared lock, scene activation, a second transaction) | Would time the wrong lock | P2 | Exact constant read by reflection and by `git show` in the checker; shared variant never matches; Scene Analytics host off; transaction-instance correlation with the job's `FOR UPDATE` |
| 29 | Rolled-back or ambiguous publications counted in the hold | Would mix failed work into a success metric | P2 | Only `TransactionCommitted` + `Published`; others in `rejectedTimelines`; checker test |
| 30 | Graph persistence confused with graph build | Revision 1 subtracted SQL time from `PublishAsync` | P2 (review) | §9.2.2: four quantities, four producers, bracket proofs; subtraction mutant refused |
| 31 | Any metric computed by subtraction | Hidden in revision 1 for graph construction | P2 | §9.2 step 3: every interval is two direct timestamps; checker `metric_without_producer` |
| 32 | A harness metric with no direct producer | The pre-repair "≈ 2 s" barrier comparison was a prototype number | P2 | Replaced by a same-instrument synchronous-path reference at M2 (§9.2.1) |
| 33 | Checker trusts typed-in metric values | Values could be edited after the run | P2 | §22: every platform-harness value recomputed from raw samples/ticks |
| 34 | UI change landing after M2 | Would invalidate B5 and disconnected after measurement | P1 | §7.1 M2 definition requires U1; §25 preconditions; restart rule |
| 35 | Config freeze landing after measurement | Would measure unfrozen values | P1 | §10.4 step 3: F4-C merges before M2; never after authoritative measurement starts |
| 36 | B5 allowed to PASS without distinct Finalizing UI | Criterion quietly relaxed | P1 | §15.3 Path A/B; §22 B5 rule; §28 item 6 |
| 37 | PR #87 consumed as evidence | Stale `bb331c6` files cited | P2 | Step H1; §22 `artifact_not_from_measured_sha` |
| 38 | Frozen F3 plan still dangling | References unresolved during F4 | P2 (docs) | Step D0 before F4-A; §28 item 2a |
| 39 | Delay-injection discriminator itself flaky on a slow host | A 750 ms sleep against a 100 ms tolerance | P3 | Runs at a small envelope in the ordinary suite; the tolerance is an order of magnitude below the injected delay; if flaky, raise the delay, never the tolerance |
| 40 | Sequence allocation (raw `DbCommand`) invisible to EF interceptors | Not needed for the hold's endpoints, but a gap in the timeline | P3 | Recorded as not observable; it lies between two observed events (barrier acquired, final `SavingChanges`), so the hold is unaffected |

No P1 remains unaddressed inside the plan. The activation default and Path A are decided (§10.5, §6.1). The remaining owner decisions are the Windows and disconnected hosts (§30).

---

## 30. Open questions and stop-and-report items

**Decisions required before M2**

1. **Activation default. Decided (2026-09-25):** F4-C ships `VisionFinalization:Enabled = true` and the worker default `3.1`, subject to the freeze measurements (§10.5).
2. **Finalizing in the operator UI. Decided (2026-09-25): Path A.** U1 lands before M2 (§6.1, §15.3). If U1 cannot be delivered, B5 stays OPEN on `finalizingStateDistinct` and S1.4 does not close. F4 does not add UI code.
3. **Windows host.** A qualified Windows x64 Development host is required for B1/B2/B3 Windows halves. If none can be provided, S1.4 cannot close under the current plan; reducing the variant set is a plan amendment for the owner.
4. **F3 plan document.** Default: D0 lands the frozen file byte-identical before F4-A. Fallback only if the owner declines: rewrite the references to cite branch and SHA.
5. **PR #87.** Default: H1, the owner closes it unmerged as historical when F4-E opens; its branch stays as the archive; F4 never cites it as evidence and the checker refuses its artifacts. Docs-only merge under `history/` only for a stated archival reason.
6. **Disconnected host and variant.** Which isolated host (Linux recommended) and who executes the operator steps.

**Stop-and-report conditions during execution** (in addition to the S1.4 plan §14 and B3 plan §14): B3-A max > 15 s on either variant; B3-B total max > ½ frozen `Max`, or the §10.2 rule yields `M_bound` above the development default (equivalently `T_max > 1200 s`) or an effective bound above 24 h; any premature visibility; publications per job ≠ 1; a crash-matrix H row that does not converge or adopts fewer objects than were sealed; an API 5xx or timeout during finalization; a non-loopback connect attempt in the disconnected trace; a B1 mismatch; a B2 bound violation; any `pipelineProfileSha256` drift; a hidden dependency; a publication timeline that violates the §9.2.1 ordering or the §9.2.2 bracket proofs; any P1/P2 in the independent review of the executed record. Each stops F4, is reported with the retained output, and is repaired outside F4 on its own SHA.
