# S1.4 F4 configuration freeze — decision

**Status: decision applied by F4-C.** This is the exploratory configuration-freeze decision of the F4 execution plan (`docs/superpowers/plans/2026-09-25-s1-4-f4-m1-to-m2-execution-plan.md` §7–§9, master plan §10), applied by the F4-C change (`docs/superpowers/plans/2026-09-25-s1-4-f4c-configuration-freeze-activation.md`).

**Nothing here is evidence. No authoritative S1.4 qualification has started.** B1–B6 and the disconnected unit remain OPEN. Nothing here qualifies Windows, and nothing here closes S1.4.

F4-C ships the frozen values in `src/platform/Mavi.Api/appsettings.json` together with `VisionFinalization:Enabled = true`, and the worker default `completion_schema_version = "3.1"`. The F4-C merge commit becomes M2, the only SHA eligible for authoritative qualification. **The independent Gate A review of this record passed on 2026-09-26 with no P1/P2 findings (§11).** That review concerns this exploratory configuration-freeze record only; it is not authoritative qualification.

## 1. Identity

| Item | Value |
|---|---|
| M1 (measured SHA) | `aa30054478a13248d8bbfb6e1a228359b7d8645d` (merge of PR #95, F4-A) |
| `main` when F4-C was cut | `45472add5312add40fea41727b8faa803d9434db` (PR #99 merged). M1 → this `main` changes, apart from docs (`docs/superpowers/plans/**` and the runbook's activation and rollback section, PRs #96, #97, #99), only U1 (PR #98, merge `10006d0174642beaf64f660716580ea865506bdc`): ten files under `src/web/mavi-web/src/**`. No harness, checker or fixture path changed (`tests/Mavi.IntegrationTests/Qualification/**`, `tools/qualification/**`, `tools/web-visual-qa/**`), so M1 remains the exploratory target (execution plan §4.1, §14). |
| Checkout | A standalone clone detached at M1 (`.git` a directory, `HEAD` = M1), built Release with 0 warnings; `git status --porcelain` was empty before and after the build. Each output records `gitSha = M1`, `gitWorkingTreeClean = true` and `gitCommitObjectPresent = true`. |
| Configuration in force | Committed M1 `appsettings.json`, `VisionFinalization`: `Enabled false`, `MaxConcurrentFinalizations 1`, `PollIntervalSeconds 5`, `ClaimSeconds 300`, `ClaimExtensionSeconds 300`, `MaximumFinalizationAttempts 3`, `MaximumFinalizationDurationSeconds 21600`, `SealingBatchSize 200`, `PayloadCleanupGraceSeconds 0`. The harness set only `Enabled = true` test-locally, as F4-A designed (`optionsSource = appsettings.json`, `hostedServiceUsed = true`). |
| Overrides | None:<br>- no `appsettings.*.machine.json` and no `MAVI_MACHINE_CONFIG`;<br>- no `VisionFinalization__*` and no `MAVI_COMPLETION_SCHEMA_VERSION` in the environment;<br>- `MAVI_TEST_DB_CONNECTION` with no `Command Timeout`, so the effective command timeout is 30 s, the shipped runtime default;<br>- no `appsettings.Testing.json` exists;<br>- the Development and Production files carry no `VisionFinalization` keys.<br>The launch records `evaluation/b3{a,b}-launch.txt` record the environment, with the database password masked. |

**Discarded attempt (recorded, not used).** A first B3-A attempt ran from a `git worktree` checkout. The M1 harness's `QualificationGate.ReadGitSha` looks for a `.git` **directory**, but a worktree has a `.git` file. The output therefore began with `gitSha = "unknown"`, and it would not have been bound to M1. The run was stopped after about 10 minutes, before any sample was written. Its incomplete placeholder output was set aside; it is neither used nor retained. All measurements below come from the standalone clone (§9).

## 2. Host

| Item | Value (F4-A probe `s1_memory.host_identity`; raw readings retained) |
|---|---|
| Variant | `linux-x86_64-cpu` |
| OS / kernel | Ubuntu 24.04.4 LTS, kernel 6.18.44-fc-v37, x86_64 |
| CPU | Intel(R) Xeon(R) Processor @ 2.10GHz, 4 cores / 4 logical (1 thread per core) |
| RAM | 16,877,547,520 B (15.7 GiB) |
| Filesystem / storage | ext4 on `/dev/vda`. `storageClass = virtual`; evidence: `mount / fstype=ext4 device 254:0 -> vda; …/virtio1/block/vda/queue/rotational=1` |
| .NET / Python | .NET 10.0.12 (SDK 10.0.112) / Python 3.13.12 (probe venv) |
| PostgreSQL | 18.6 (Ubuntu 18.6-1.pgdg24.04+2), local port 5433, qualification-grade. `shared_buffers 128MB`, `work_mem 4MB`, `effective_cache_size 4GB`, `maintenance_work_mem 64MB`, `max_parallel_workers_per_gather 2`, `random_page_cost 4`, `jit on` |

This is the Linux Development host class the master plan declares for qualification (§17: Xeon @ 2.10 GHz, 4 vCPU, 15.7 GiB, kernel 6.18, ext4 on virtio). It is a cloud development container, **not a hosted CI runner**: its storage class is measured `virtual`, which the checker accepts for B3 timing, and it is not `hosted-runner`.

**Windows: no qualified Windows Development host was available.** The decision below is derived from the only available exploratory OS, Linux. Linux is not treated as representative of Windows. Authoritative S1.4 closure still requires the Windows half of B3 at M2 (master §18.4). If Windows measurements at M2 fail the frozen values, F4 stops; there is no re-freeze from M2 results (execution plan §14).

## 3. Retained exploratory outputs

Retained under `docs/qualification/stage2-s1/exploratory/aa30054478a1/` with the sidecar `exploratory-manifest.json` (schema `s1-f4-exploratory-manifest-v1`). The manifest lists all 17 retained files with their SHA-256, byte count, OS, role, M1 SHA and harness run where applicable, each with `authoritative: false` and reason `exploratory-configuration-freeze` (§3.1).

| File | SHA-256 | Harness run |
|---|---|---|
| `b3a/linux-x86_64-cpu/s1-b3a-hand-off.linux-x86_64-cpu.json` | `7de35bb1e7269c62ad722305e0771afdc8df1eb9b1fa38f27e0db2c31e92219d` | `f82a7e1e48a9439baa99c41d2c2ead72`, launched 2026-09-25T16:17:39Z, finished 2026-09-25T16:28:30Z |
| `b3b/linux-x86_64-cpu/s1-b3b-finalization.linux-x86_64-cpu.json` | `e35f7e07e6fa250aec46fee994f83410ae7c5fe982bd902ad3a89b3c47cc05a4` | `b9ab218ba50d493c98d9d14a1755eb42`, launched 2026-09-25T16:29:09Z, finished 2026-09-25T17:54:49Z |

The raw outputs are **unmodified**: they were made read-only on completion, and the committed copies hash identically (§3.1). Each raw output says `authoritative: true` with no non-authoritative reason, because the harness only knows the host, tree and database were qualified.

Their exploratory status is established by three things (execution plan §5):
- `environment.gitSha` = M1, which the checker refuses at M2;
- this `exploratory/` path, outside `evidence/<sha12>/`;
- the manifest.

The B3-B run's TRX logger wrote no file; its console log (`Passed 1/1, 1 h 25 m, exit 0`) is retained instead. No TRX is required (§9).

### 3.1 Every retained file

Paths are relative to `docs/qualification/stage2-s1/exploratory/aa30054478a1/`. Every file is byte-identical to what the harness, launcher or evaluator wrote. `docs/qualification/stage2-s1/exploratory/.gitattributes` (`* -text`) keeps them byte-stable on every checkout.

| File | Bytes | SHA-256 | Role |
|---|---|---|---|
| `b3a/linux-x86_64-cpu/s1-b3a-hand-off.linux-x86_64-cpu.json` | 26,924 | `7de35bb1e7269c62ad722305e0771afdc8df1eb9b1fa38f27e0db2c31e92219d` | raw B3-A harness output (unedited) |
| `b3b/linux-x86_64-cpu/s1-b3b-finalization.linux-x86_64-cpu.json` | 2,095,951 | `e35f7e07e6fa250aec46fee994f83410ae7c5fe982bd902ad3a89b3c47cc05a4` | raw B3-B harness output (unedited) |
| `hosts/linux-dev-container/python-host-identity.json` | 392 | `c1db34035d4176f16628726fd7f9148d734c6c34822fbf4ec44d3589d498f4fd` | F4-A host probe |
| `hosts/linux-dev-container/raw-host.txt` | 858 | `0f9aac2ba4bdabbbf7b7a23019fc4a7ed9651204bcb6a98b60f117a0348eb88f` | raw host readings |
| `evaluation/eval-b3a.json` | 2,358 | `3cb5c5e93cc092c0b63d477fda38591ecb54e23b4f83a945a5c24aa00952c4cf` | M1 checker evaluation, B3-A |
| `evaluation/eval-b3b.json` | 21,955 | `1806099debd29f1a2afaf952fa46f5ff130b7a4846ccb267d72d7959202dc457` | M1 checker evaluation, B3-B |
| `evaluation/derivation.json` | 1,946 | `f6b568f733bac5452648ab1a0ee08113823c372dbc58b15a6afae5815580d985` | execution plan §7 derivation |
| `evaluation/evaluate_m1.py` | 10,673 | `b6ce3317893c9e45f159841086ba735daadd6e5ce22ac67f6de41e83a6d18eed` | evaluation script (imports the M1 checker) |
| `evaluation/b3a.trx` | 1,099,795 | `4ce4f7bee7719d6c492e3155d578dda7dd2ce65067a1089f59703fee55cbd553` | `dotnet test` TRX of the B3-A run |
| `evaluation/b3a-console.log` | 573 | `92b6c20ce744da1303c21fab198ab8cfb233e71a035f65f3c0aa3cc8547924b1` | B3-A console log |
| `evaluation/b3b-console.log` | 457 | `a766f090ca2eacd205c72abfdf08b6d53c959fc4279d67f0fe5ab2d086f3f9e7` | B3-B console log (no TRX was written) |
| `evaluation/b3a-launch.txt` | 720 | `54efb5195e6ef03b25200ac33d2dbf46f5088a9547b99155f385ee8d19aca5cc` | B3-A launch record (password masked) |
| `evaluation/b3b-launch.txt` | 738 | `abac77fe2d9237e9dbed5ab5645a920c4c0eeecc4aa67773b3465309deafdb92` | B3-B launch record (password masked) |
| `evaluation/b3a-started.txt` | 21 | `38ebfa7b614408fefb767123c680ab1d6899632568fa3846edf935af4c46f821` | B3-A start time |
| `evaluation/b3a-finished.txt` | 21 | `a56b3f29ebeff7ef25fa087a411e85bcfeac8a5b5ef50de0fd5224c7bd81bfe1` | B3-A finish time |
| `evaluation/b3b-started.txt` | 21 | `731f72bbe77196ed0518de5fe2b9a0126f713f92ab6c206e8cb83e8759b5b7a1` | B3-B start time |
| `evaluation/b3b-finished.txt` | 21 | `6d2104edd8dc18d825f3d84153d1ed70bbe9da13a13bd1114636ea35c319b8cb` | B3-B finish time |

Sidecar manifest: `exploratory-manifest.json`, SHA-256 `bfaf69ba71e4b791228a59283e9b7c2674d55009eb251c64424e403e3fa566fb`.

## 4. Checker evaluation (M1 checker rules, `tools/qualification/s1_evidence.py` at M1)

Each output was evaluated with:
- the header rules of `_Checker._b3_output`: schema, status, authoritative, variant, `gitSha == M1`, clean tree, commit present, qualification-grade database;
- `_Checker._b3a_content`, or `_Checker._b3b_content` with M1's committed `VisionFinalization` section, M1's barrier SQL (`SELECT pg_advisory_xact_lock(1296127561, 1412505908)`, read with `git show`) and M1's runtime command timeout (30 s). The latter includes `visibility_problems` and `concurrency_problems`;
- `timing_stats` for statistics.

Script: `evaluation/evaluate_m1.py`. Results: `evaluation/eval-b3a.json` and `eval-b3b.json`.

| Output | Header findings | Content findings | Concurrency findings |
|---|---|---|---|
| B3-A | 0 | 0 | — |
| B3-B | 0 | 0 | 0 |

### 4.1 B3-A

| Item | Result |
|---|---|
| Shape | 10,000 Tracks, 40,000 observations, 50,000 staged objects; finalizer host **off**; completion 3.1 |
| Samples | 33 (3 repeats × (1 warm-up + 10)), **30 measured**, warm-up excluded |
| `handOffMs` (measured) | min 1,206.7 · p50 1,282.0 · p95 1,650.0 · max **2,130.4 ms**; p50 run spread 26.4 ms |
| Bound | `min(15,000, worker timeout 30,000 / 2) = 15,000 ms` → **holds** |
| Replay | min 710.3 · p50 882.2 · p95 1,005.3 · max 1,310.6 ms |
| Every sample | HTTP 200 and state `finalizing`; job `Finalizing`; one payload row; no published rows; no accepted-evidence file; accepted timestamp set; claim triple null; 50,000 staged; replay `finalizing`; worker released (same worker leased a different queued job) |

### 4.2 B3-B

| Item | Result |
|---|---|
| Shape / path | 10,000 Tracks, 50,000 staged objects; real `VisionFinalizationHostedService`; completion 3.1 hand-off; options from `appsettings.json` |
| Samples | 33 (3 repeats × (1 warm-up + 10)), **30 measured**; synchronous 3.0 reference: 5 samples (informational) |
| Total hand-off → publication (measured) | min 88.49 · p50 103.91 · p95 111.60 · max **113.98 s** |
| Publication transaction | p50 16.54 · max 18.80 s (measured); **19.60 s including warm-up** |
| Graph persistence (`AddAsync`) | p50 14.75 · max 16.64 s; graph `SaveChanges` max 16.22 s; > 0 on every sample |
| Graph build bracket | p50 0.101 · max 0.157 s |
| Barrier hold / wait | hold p50 1.857 · max 2.292 s; wait max 0.84 ms. The synchronous reference hold was 1.67–1.97 s (informational only). |
| Per sample (all 33) | 1 publication; 1 sequence allocation; 251 extensions (= ⌈50000/200⌉ + 1); 50,000 created, 0 adopted; 0 rejected timelines; bracket proofs and single barrier command true; every typed metric equal to its recomputation from raw ticks |
| Visibility | 0 violations. 169–200 Finalizing probes per sample, each with phase exactly `finalizing`, no count, no search hit and no Track row. 93–124 of them read Track detail inside the publication window (404). The same 3 ids return 200 after publication. |
| Concurrency (§9.2) | `MaxConcurrentFinalizations = 1`. **Overlap observed** in 1,613 atomic snapshots. First: job 1 `Finalizing` under a live claim, job 2 accepted 17:41:24.17 and `Finalizing`, never claimed, payload durable. Job 1 completed 17:42:52.97 and job 2 17:44:26.40. Max live claims 1; the second job was not claimed before the first published; both published once with one allocation each. |
| API contention | 0 errors during finalization on every sample (informational latencies retained per sample) |
| API host | RSS peak 1,498–2,171 MiB per sample (in-process host plus harness); process CPU 44.9–62.4 s per sample |
| Longest DB statement | 2.23 s ≤ 30 s effective command timeout |

The crash harness was **not run**: no recovery concern arose in B3-B (0 adopted, 0 rejected timelines, no stop condition), so execution plan §7.4 keeps `MaximumFinalizationAttempts = 3`.

## 5. Derivation inputs (execution plan §7.0)

All inputs are in **seconds**: harness ms ÷ 1000; ticks ÷ `stopwatchFrequency` (10⁹ on every sample). There is no intermediate rounding.

They are taken over **every sample including warm-up** (33 samples; 8,250 batch intervals), and each is the maximum of its own metric. Only Linux was available, so Linux governs every input.

| Input | Definition | Linux (per OS) | Pooled (governing) |
|---|---|---|---|
| `S_batch_max` | max `perBatchWallMs` / 1000 | 1.027196 s | 1.027196 s (Linux) |
| `G_max` | max (`publishEntered − lastExtensionReturned`) / f | 0.156724 s | 0.156724 s (Linux) |
| `P_max` | max (`commitCompleted − transactionBegun`) / f | 19.595462 s | 19.595462 s (Linux) |
| `T_max` | max `acceptedAtUtc → commitCompletedUtc` | 113.978856 s | 113.978856 s (Linux) |
| `S_batch_p95` / `T_p95` | nearest-rank p95 (recorded only) | 0.424814 s / 112.433788 s | — |
| First-claim interval | claim return → initial extension return | **not retained at M1** | bounded by `T_max` (§7.3) |
| Extension overhead | Σ extension round trips / seal wall | **not measured at M1** | — |

These inputs were recomputed independently from the raw output, with no shared code, and matched exactly.

## 6. Rule arithmetic and chosen values (execution plan §7.1–§7.8)

`ceilTo(x, g) = g × ⌈x / g⌉`. Never lower: frozen = `max(M1 value, derived floor)`.

| Value | M1 value | Arithmetic | Derived floor | **Frozen** |
|---|---|---|---|---|
| `SealingBatchSize` | 200 | `S_batch_max = 1.027 s ≤ 75 s`, so no stop; the overhead trigger cannot be evaluated | — | **200** |
| `ClaimExtensionSeconds` | 300 | `E_req = 4 × max(1.027196, 0.156724 + 19.595462) = 4 × 19.752187 = 79.008747` → `ceilTo(·, 30) = 90` | 90 | **300** |
| `ClaimSeconds` | 300 | `4 × T_max = 455.915424` → `ceilTo(·, 60) = 480`; `max(300, 300, 480)` | 480 | **480** |
| `MaximumFinalizationAttempts` | 3 | kept (§7.4); no crash evidence says otherwise | — | **3** |
| `MaximumFinalizationDurationSeconds` | 21600 | `M_req = max(3 × (480 + 2 × 113.978856), 2 × 113.978856) = max(2123.873, 227.958) = 2123.873` → `M_bound = ceilTo(·, 300) = 2400 ≤ 21600` | 2400 | **21600** |
| `PollIntervalSeconds` | 5 | kept (§7.6) | — | **5** |
| `MaxConcurrentFinalizations` | 1 | kept (§7.6) | — | **1** |
| `PayloadCleanupGraceSeconds` | 0 | kept (§7.6) | — | **0** |

Options validation holds: `ClaimExtensionSeconds 300 ≤ ClaimSeconds 480 ≤ MaximumFinalizationDurationSeconds 21600`.

**The only change from M1 is `ClaimSeconds` 300 → 480.** The first claim must survive claim → initial extension, and M1 retains that interval only inside hand-off → publication. `4 × T_max` is therefore the proven bound.

`ClaimExtensionSeconds` stays 300. The last extension's grant must cover graph build plus the publication transaction, whose floor is 90 s (4 × 19.75 s); 300 s is 15.2 × the measured `G + P`.

**Effective bound:** `21600 + 480 + 5 = 22085 s = 6.13 h`, which is ≤ 86,400 s.

## 7. Activation gate (execution plan §8)

| Condition | Result |
|---|---|
| B3-A max ≤ 15 s on every available OS | **PASS**: 2.130 s (Linux) |
| Every full-envelope output has zero checker findings | **PASS**: B3-A 0, B3-B 0 |
| B3-B max ≤ ½ frozen `MaximumFinalizationDurationSeconds` | **PASS**: 113.98 s ≤ 10,800 s. This is **constructional at M1**: it is implied by `M_bound ≤ 21600` (execution plan §7.9), so it is **not independent evidence**. It becomes an independent test only at M2, on new measurements against the frozen values. |
| `SealingBatchSize` stays 200; attempts stay 3 | **PASS** |
| No premature visibility; 1 publication per job; 1 sequence allocation per publication | **PASS** |
| Concurrency integrity, with observed overlap | **PASS** |
| No API 5xx or timeout | **PASS** |
| No hidden dependency | **PASS**: no dependency was changed or needed; the runs used the M1 tree as committed |
| No crash/recovery blocker | **PASS**: none discovered (crash harness not triggered) |
| `M_bound ≤ 21600` | **PASS**: 2400. This is equivalent to `T_max ≤ 1200 s`; measured 113.98 s. |
| Effective bound ≤ 24 h | **PASS**: 6.13 h |

**Activation gate: PASS on the available exploratory OS, Linux only.** No qualified Windows exploratory host was available.

## 8. Applied values (F4-C)

| Key | M1 committed | Derived floor | **Shipped at F4-C** |
|---|---|---|---|
| `Enabled` | false | — | **true** |
| `MaxConcurrentFinalizations` | 1 | — | **1** |
| `PollIntervalSeconds` | 5 | — | **5** |
| `ClaimSeconds` | 300 | 480 | **480** |
| `ClaimExtensionSeconds` | 300 | 90 | **300** |
| `MaximumFinalizationAttempts` | 3 | — | **3** |
| `MaximumFinalizationDurationSeconds` | 21600 | 2400 | **21600** |
| `SealingBatchSize` | 200 | — | **200** |
| `PayloadCleanupGraceSeconds` | 0 | — | **0** |
| worker `completion_schema_version` default | `"3.0"` | — | **`"3.1"`** |

The effective bound is `21600 + 480 + 5 = 22085 s` (≈ 6.13 h). No value is lower than its M1 value.

Values are **never re-frozen from authoritative M2 results** (execution plan §14). If an authoritative M2 run fails a criterion, F4 stops and reports. A new freeze requires a recorded failed-M2 outcome, a separate change or new exploration, a new F4-C and a new M2.

## 9. Constraints carried to M2 (recorded, not fixed here)

- **Standalone clone.** The frozen M1 harness helper `QualificationGate.ReadGitSha` requires `.git` to be a directory. A `git worktree` checkout therefore records `gitSha = "unknown"`: the discarded attempt of §1. The provenance test `QualificationProvenanceTests` fails in a worktree for the same reason. **Authoritative M2 runs, and F4-C's own validation, use a standalone clone**, unless a later, separately qualified harness change lands. F4-C does not modify the helper.
- **B3-B TRX.** No TRX was written for the exploratory B3-B run. The run passed (`Passed 1/1`, exit 0), and its raw output, console log and harness run identity (`b9ab218ba50d493c98d9d14a1755eb42`) are retained. **No TRX is required for a B3 harness run at M2.**
  - The checker binds each B3 harness output to a `runs` entry of `kind: "local"`, carrying `host`, `command`, `cleanTree: true` and `harnessRunId == output.runId`.
  - TRX/JUnit is required only for the Quality Gate suites and the B3/B4 proving tests, which come from the M2 Quality Gate workflow run.
  - At M2 the TRX logger stays a best-effort supporting artefact.
  - F4-C does not change the harness or the logger.
- **Windows.** Authoritative S1.4 closure requires the Windows half of B3 at M2 (master §18). The frozen values are not re-derived from Windows measurements at M2.

## 10. Not done here

- No authoritative S1.4 evidence. No `evidence/<sha12>/` file exists.
- M2 does not exist until F4-C merges. F4-C's PR head is only the M2 candidate.
- No Windows qualification and no S1.4 closure.

## 11. Independent review (Gate A)

- **Result:** PASS
- **Date:** 2026-09-26
- **Independent review:** completed on the committed exploratory package (execution plan §13 Gate A)
- **Findings:** no P1/P2 findings

What the review verified:

- **The package.**
  - The manifest lists exactly 17 retained M1 files.
  - All 17 SHA-256 values match the values pre-pinned in the merged F4-C plan (§5.1).
  - The raw `authoritative: true` values are untouched.
  - `exploratory/.gitattributes` (`* -text`) protects byte identity.
  - Nothing is under authoritative `evidence/`.
- **Provenance.**
  - The raw B3-A and B3-B outputs are bound to exact M1 `aa30054478a13248d8bbfb6e1a228359b7d8645d`, with clean-tree and commit-object provenance.
  - The launch records are bound to M1, with passwords masked.
  - PostgreSQL 18.6 and the qualified Linux Development host are recorded correctly.
- **The measurements.**
  - B3-A max hand-off is 2130.3733 ms, inside the 15 s bound.
  - The B3-B checker evaluation has zero header, content and concurrency findings.
  - The B3-B console shows a pass with exit 0. The missing local B3-B TRX is non-blocking (§9).
- **The derivation.**
  - Inputs: `S_batch_max = 1.027195699`, `G_max = 0.15672437`, `P_max = 19.595462485`, `T_max = 113.978856` (seconds).
  - Arithmetic:
    - extension floor 90 s → frozen 300 s;
    - claim floor 480 s → frozen 480 s;
    - `M_bound = 2400 s`, and the maximum duration is retained at 21600 s;
    - effective bound 22085 s;
    - `neverLowered = true`;
    - no stop conditions.
- **Scope.**
  - Windows exploratory absence is explicit and is not claimed as qualified.
  - M1 → candidate M2 has no changes under the frozen surfaces: `tests/Mavi.IntegrationTests/Qualification/**`, `tools/qualification/**`, `tools/web-visual-qa/**` and `tests/Mavi.IntegrationTests/ApiTestFactory.cs`.

This is the review of an **exploratory configuration-freeze record**, not authoritative qualification:
- no authoritative S1.4 qualification has started;
- Windows remains unqualified;
- M2 does not exist until F4-C merges.
