# MAVI Stage 2 — S1.4 F4-C: configuration freeze and shipped activation (creates M2)

**Status:** execution-grade implementation plan. **Planning only:** nothing here is implemented.
**Base:** `main@10006d0174642beaf64f660716580ea865506bdc` (merge of PR #98, U1).
**Governing:**
- the execution plan `2026-09-25-s1-4-f4-m1-to-m2-execution-plan.md` §7–§9, §11–§14 (cited as "EP");
- the master plan `2026-09-25-s1-4-b3-f4-qualification-closure-implementation.md` §6, §7.1, §10, §21, §24 F4.8, §25 (cited as "MP");
- the asynchronous-finalization plan and the F3 plan (the lifecycle F4-C must not touch);
- the U1 plan;
- `docs/runbooks/vision-runtime-model-component-lifecycle.md` (cited as "the runbook").

**What F4-C is.** It freezes the configuration derived at M1, activates completion 3.1 and Finalizing as the shipped default, pins both with tests, and lands the freeze decision and the exploratory package.
- It adds no architecture.
- Its merge commit is **M2** (§9).
- No authoritative qualification happens on its branch, or before it merges.

**Implementation branch:** `feature/s1-4-b3-f4-config-freeze` (MP §6), created from `main` at or after `10006d0`.

---

## 1. Current state (surveyed at `10006d0`)

### 1.1 Identity points

| Point | SHA | Content |
|---|---|---|
| M1 | `aa30054478a13248d8bbfb6e1a228359b7d8645d` | merge of PR #95 (F4-A harness and checker) |
| docs | `9f9163f` (PR #96) | EP and MP amendments, runbook activation text. Not behaviour-bearing. |
| U1 plan | `737e945` (PR #97) | docs only |
| **U1** | **`10006d0174642beaf64f660716580ea865506bdc`** (PR #98) | the only behaviour-bearing change since M1: 10 files under `src/web/mavi-web/src/**` |

`git diff --name-only aa30054 10006d0` touches:
- `docs/superpowers/plans/**`;
- `docs/runbooks/vision-runtime-model-component-lifecycle.md` (PR #96);
- the 10 U1 web files.

It touches no harness, checker or fixture path (EP §4.1: `tests/Mavi.IntegrationTests/Qualification/**`, `tools/qualification/**`, `tools/web-visual-qa/**`). M1 therefore remains the valid exploratory target.

### 1.2 Shipped platform configuration

`src/platform/Mavi.Api/appsettings.json`, lines 56–66:

```json
"VisionFinalization": {
  "Enabled": false,
  "MaxConcurrentFinalizations": 1,
  "PollIntervalSeconds": 5,
  "ClaimSeconds": 300,
  "ClaimExtensionSeconds": 300,
  "MaximumFinalizationAttempts": 3,
  "MaximumFinalizationDurationSeconds": 21600,
  "SealingBatchSize": 200,
  "PayloadCleanupGraceSeconds": 0
},
```

- **Property names.** They are exactly those of `VisionFinalizationOptions` (`src/platform/Mavi.Application/Modules/Intelligence/VisionFinalizationOptions.cs`, `SectionName = "VisionFinalization"`). They are also the checker's `FROZEN_CONFIGURATION_KEYS` plus `Enabled` (`tools/qualification/s1_evidence.py`).
- **Other appsettings files.** `appsettings.Development.json` and `appsettings.Production.json` have **no** `VisionFinalization` section, so every environment inherits the base file. There is no `appsettings.Testing.json`.
- **C# initializer defaults** (used only when a key is absent): `Enabled` false, `ClaimSeconds` 300, `ClaimExtensionSeconds` 300, `MaximumFinalizationDurationSeconds` 21 600, `SealingBatchSize` 200, `MaximumFinalizationAttempts` 3, `PollIntervalSeconds` 5, `MaxConcurrentFinalizations` 1, `PayloadCleanupGraceSeconds` 0.
- **Validation.** `VisionFinalizationOptions.Validate()` is registered through `VisionFinalizationOptionsValidator` with `ValidateOnStart` (`Mavi.Infrastructure/DependencyInjection.cs:122–127, 151–159`), and it runs whether the gate is on or off. Its rules:
  - the ranges: `MaxConcurrent` 1–8, `Poll` 1–300, `Claim` 30–86 400, `Extension` 30–86 400, `Attempts` 1–20, `Max` 1–604 800, `Batch` 1–5000, `Grace` 0–86 400;
  - `ClaimExtensionSeconds ≤ ClaimSeconds`;
  - `MaximumFinalizationDurationSeconds ≥ ClaimSeconds`.

### 1.3 Protocol

`src/platform/Mavi.Contracts/Worker/WorkerContractRules.cs`:
- `SynchronousCompletionSchemaVersions = ["2.0","3.0"]` and `AsynchronousCompletionSchemaVersions = ["2.0","3.1"]`.
- `CompletionSchemaVersions(enabled)` drives the advertisement at `GET /api/vision/contract` (`VisionJobEndpoints.cs:21`).
- `IsAcceptedCompletionSchemaVersion(value, enabled)` drives acceptance, from the same gate.
- 3.0 is never reinterpreted as 3.1.

### 1.4 Worker

`src/vision/mavi_vision/common/settings.py:52`: `completion_schema_version: Literal["3.0", "3.1"] = "3.0"`, set by `MAVI_COMPLETION_SCHEMA_VERSION`.
- The worker probes before every lease and requires exactly its own version: no fallback, and 2.0 is not an option.
- 2.0 compatibility is **platform-side** (older workers); the current worker cannot emit it.
- The checker reads this line (`worker_completion_default`, regex `completion_schema_version: Literal\[[^\]]*\] = "([0-9.]+)"`) and requires `"3.1"` at the measured SHA (`activation_default_unqualified`). **F4-C must keep that line shape.**

### 1.5 How the checker binds F4-C (unchanged by F4-C)

`_frozen_configuration` (`s1_evidence.py:1639–1671`) requires, at M2:
- `appsettings.json`'s `VisionFinalization` to equal the record's `frozenConfiguration` key by key;
- `effectiveBoundSeconds == Max + Claim + Poll`;
- `Enabled is True`;
- the worker default `"3.1"`.

`_b3b_content` also requires the measured run's effective configuration to equal the committed one, `Enabled` included. So F4-C's committed values *are* what M2 is qualified against.

### 1.6 Tests that pin today's defaults

Probed on a throwaway local copy of `10006d0`, with the edits of §4 applied and never pushed.

| Suite | Result with `Enabled = true`, `ClaimSeconds = 480`, worker `"3.1"` |
|---|---|
| worker pytest (`src/vision/tests`) | **3 failures**:<br>- `test_worker_client.py::test_complete_uses_canonical_path_and_projects_runtime_provenance`<br>- `test_worker_client.py::test_complete_projects_physical_gpu_identity_and_resolution_reason`<br>- `test_worker_completion_v3.py::test_the_default_worker_accepts_the_pre_activation_platform`<br>Everything else passes: 2308 passed, 27 skipped. |
| checker tests (`tools/qualification/tests`) | 687 passed, 3 skipped. No change needed. |
| `tools/verify_repo.py` | passes, including with the §5 package committed |
| .NET Domain / Application | 281 / 502 passed |
| .NET Integration | 914 passed, 3 skipped. The one failure is a worktree artefact (§7.3). The suite overrides `VisionFinalization:Enabled` in `ApiTestFactory`, so it does not read the shipped flag. The shipped `ClaimSeconds = 480` flows into its hosts and breaks nothing. |

Two structural findings shape §6:
- **The worker "default" tests do not test the default.** `test_worker_completion_v3.py`'s `_settings`/`_run`/`_complete_golden` always pass `completion_schema_version` (default argument `"3.1"`), and the four "default worker" tests pass `version="3.0"` explicitly. Only one line (`assert default.completion_schema_version == "3.0"`) reads the real default. A replacement test that also passes the version would stay green even if the default were still `"3.0"`.
- **`ApiTestFactory` is part of the frozen harness in substance.** The B3 harnesses construct it (`S1HandOffScaleTests.cs:200`, `S1FinalizationEnvelopeTests.cs:225/304/596/764/876`, `S1FinalizationRecoveryTests.cs:162/422`). The file is outside the EP §4.1 path list, but changing it changes what the M1 harness ran. **F4-C does not modify `ApiTestFactory.cs`** (§10). The shipped-configuration tests bind the real file without it (§6.1).

### 1.7 Machine override (the rollback and activation-step-1 mechanism)

`src/platform/Mavi.Api/Startup/MachineConfigurationStartup.cs`:
- **Precedence.** `MAVI_MACHINE_CONFIG`, if set, names a JSON file layered after `appsettings*.json`. Environment variables are re-added last, so `VisionFinalization__Enabled` overrides everything.
- **Default path on Windows only:**
  - Development: `%ProgramData%\MAVI\Development\config\appsettings.development.machine.json`;
  - Production: `%ProgramData%\MAVI\config\appsettings.machine.json`.
- **On Linux `GetDefaultPath` returns `null`.** The only overrides there are `MAVI_MACHINE_CONFIG` and `VisionFinalization__Enabled=false`.
- **Runbook gap.** The runbook says only "`appsettings.<environment>.machine.json` or `MAVI_MACHINE_CONFIG`". That names no working Linux mechanism, and it misnames the Production file. §4.5 corrects the text.
- **Not committable.** Neither file lives in the repository: both are machine paths outside it.

### 1.8 Retained M1 exploratory package (outside the repository)

The staging directory holds a package for `docs/qualification/stage2-s1/exploratory/aa30054478a1/`, plus the freeze draft `f4-configuration-freeze.md` (status DRAFT; §9 Gate A "_Pending_"). Every entry of the draft manifest `exploratory-manifest.json` was re-hashed and matches, and the raw harness outputs are byte-identical (`cmp`) to what the harness wrote. Remaining gaps:
- four timestamp files (`evaluation/b3{a,b}-{started,finished}.txt`) are retained but not listed;
- the manifest schema is labelled `-draft-v1`.

§5 closes both.

---

## 2. Frozen M1 inputs (provenance and values)

### 2.1 Provenance

- **Measured SHA.** M1 `aa30054478a13248d8bbfb6e1a228359b7d8645d`.
- **Checkout.** A standalone clone detached at M1, built Release, with a clean tree (`gitSha = M1`, `gitWorkingTreeClean = "true"`, `gitCommitObjectPresent = "true"` in both outputs).
- **Configuration.** The committed M1 `VisionFinalization`. The harness set only `Enabled = true` test-locally (`optionsSource = appsettings.json`, `hostedServiceUsed = true`). There was no machine config and no `VisionFinalization__*` or `MAVI_COMPLETION_SCHEMA_VERSION` in the environment, and the command timeout was 30 s (Npgsql default).
- **Host** (`linux-dev-container`, F4-A probe):

  | Item | Value |
  |---|---|
  | OS | Ubuntu 24.04.4 LTS, kernel `6.18.44-fc-v37` |
  | CPU | Intel Xeon @ 2.10 GHz, 4 physical / 4 logical cores |
  | RAM | 16 877 547 520 B |
  | Filesystem | ext4 on `vda` (virtio) |
  | Storage class | `virtual` |
  | Runtimes | .NET 10.0.112; Python 3.13.12; PostgreSQL 18.6 |

- **Scope: Linux only.** No qualified Windows host was available. Per EP §4.3 this is acceptable for configuration selection: the activation gate is satisfied on each *available* exploratory OS. **Authoritative M2 B3 still requires Linux and Windows** before S1.4 can close (MP §18).

### 2.2 Checker evaluation (M1 rules, `_b3a_content` / `_b3b_content`)

- **B3-A:**
  - header problems `[]` and content findings `[]`;
  - n = 30 (3 repeats, 3 warm-up excluded);
  - max hand-off **2130.3733 ms** ≤ bound 15 000 ms;
  - p95 1649.98 ms.
- **B3-B:**
  - header problems `[]`, content findings `[]` and concurrency problems `[]`;
  - n = 30 (3 repeats, 3 warm-up excluded);
  - total max **113 978.856 ms**, p95 111 600.558 ms;
  - shape 10 000 Tracks / 40 000 observations / 50 000 staged objects.

### 2.3 Derivation inputs

Seconds, all samples including warm-up (EP §7.0); taken from `evaluation/derivation.json`.

| Input | Max | p95 | n | Governing OS |
|---|---|---|---|---|
| `S_batch` | **1.027195699** | 0.424813803 | 8250 | linux-x86_64-cpu |
| `G` | **0.15672437** | 0.136764233 | 33 | linux-x86_64-cpu |
| `P` | **19.595462485** | 18.79926825 | 33 | linux-x86_64-cpu |
| `T` | **113.978856** | 112.433788 | 33 | linux-x86_64-cpu |
| first-claim interval | **not retained at M1** | — | — | — |
| extension overhead | **not measured at M1** | — | — | — |

### 2.4 Arithmetic (EP §7.1–§7.7), never lowered below M1 (EP §7.8)

| Value | Rule | Arithmetic | M1 | Floor | **Frozen** |
|---|---|---|---|---|---|
| `SealingBatchSize` | 200 unless `S_batch_max > 75` (stop) | 1.027 ≤ 75 | 200 | — | **200** |
| `ClaimExtensionSeconds` | `max(300, ceilTo(4·max(S_batch_max, G_max+P_max), 30))` | `4 × max(1.027, 19.752) = 79.009` → 90 | 300 | 90 | **300** |
| `ClaimSeconds` | `max(300, Ext, ceilTo(4·T_max, 60))` | `4 × 113.979 = 455.915` → **480** | 300 | 480 | **480** |
| `MaximumFinalizationAttempts` | keep 3 | — | 3 | — | **3** |
| `MaximumFinalizationDurationSeconds` | `M_req = max(3·(480 + 2·113.979), 2·113.979) = 2123.873` → `M_bound = 2400 ≤ 21600`, so keep M1 | — | 21600 | 2400 (not a lower target) | **21600** |
| `PollIntervalSeconds` | keep | — | 5 | — | **5** |
| `MaxConcurrentFinalizations` | keep | — | 1 | — | **1** |
| `PayloadCleanupGraceSeconds` | keep | — | 0 | — | **0** |

- **Effective bound:** `21600 + 480 + 5 = 22085 s` (6.1347 h) ≤ 86 400 s.
- **`T_max ≤ 1200 s` activation stop** (EP §7.9): 113.98 s, which holds.
- **Activation gate** (EP §8): **PASS** on the available OS (Linux).
- **Only change from M1:** `ClaimSeconds` 300 → 480.

---

## 3. Target F4-C state

| Surface | Shipped value at M2 |
|---|---|
| `appsettings.json` `VisionFinalization` | `Enabled` **true**; the other values exactly §2.4's frozen column |
| Development / Production appsettings | still no `VisionFinalization` keys; every environment inherits the base |
| C# initializer defaults of `VisionFinalizationOptions` | **unchanged** (§4.3) |
| Platform contract, gate on | advertises and accepts exactly `["2.0","3.1"]`. Completion 3.0 is retired and refused with `worker_contract_version_unsupported`. 2.0 stays synchronous. 3.1 is the durable hand-off. |
| Platform contract, gate held off by override | exactly `["2.0","3.0"]`; 3.1 refused; no job can enter Finalizing |
| Worker default | `completion_schema_version` **`"3.1"`**. `"3.0"` stays selectable for rollback. There is no `"2.0"` option, no fallback and no auto-upgrade in either direction. |
| Finalizer host | unchanged code; runs when `Enabled = true` |

---

## 4. Product changes (exact)

### 4.1 `src/platform/Mavi.Api/appsettings.json`

Only these two lines in the `VisionFinalization` section change:

```diff
   "VisionFinalization": {
-    "Enabled": false,
+    "Enabled": true,
     "MaxConcurrentFinalizations": 1,
     "PollIntervalSeconds": 5,
-    "ClaimSeconds": 300,
+    "ClaimSeconds": 480,
     "ClaimExtensionSeconds": 300,
```

- No key is added, removed or reordered, and no other section changes.
- `ConnectionStrings:Mavi` gets no `Command Timeout`. The runtime command timeout stays 30 s, which the checker reads (`_runtime_command_timeout_seconds`).

### 4.2 `src/vision/mavi_vision/common/settings.py`

```diff
-    completion_schema_version: Literal["3.0", "3.1"] = "3.0"
+    completion_schema_version: Literal["3.0", "3.1"] = "3.1"
```

- The comment above it (l. 46–51) is rewritten to state the shipped truth:
  - 3.1 is the default and pairs with the activated platform;
  - `MAVI_COMPLETION_SCHEMA_VERSION=3.0` is the rollback setting and pairs with a platform held off;
  - the probe requires exactly this version.
- The `Literal` is unchanged: no `"2.0"`, no new value.
- **No fallback logic** is added anywhere in `mavi_vision/worker/**`.

### 4.3 C# defaults: deliberately unchanged

`VisionFinalizationOptions` initializers stay as they are.
- **Why.** The shipped value is the `appsettings.json` value, and that file is what the checker binds (§1.5). Changing the initializers would re-baseline F3 tests that use code defaults (`VisionFinalizationOptionsTests.DefaultsAreDisabledSingleConcurrencyAndValid`; `ConfigurationValidationTests`' `ClaimExtensionSeconds = 301` case relies on the code default `ClaimSeconds = 300`). That widens F4-C for no behavioural gain.
- **What changes.** Only the XML `<remarks>` text changes (doc only), because "the production default until the controlled activation" becomes false. It will say:
  - the shipped `appsettings.json` activates the gate and carries the F4 freeze (execution plan §7);
  - the initializers are the values for an absent key;
  - a machine override may hold the gate off (runbook).

### 4.4 Documentation that states the shipped defaults

These are docs only, in the same PR, and every one is named in MP §6/§24 F4.8 or states a now-false default.

| File | Edit |
|---|---|
| `docs/runbooks/vision-runtime-model-component-lifecycle.md` "Asynchronous finalization …" | "**Production default is off**" becomes "**Shipped default is on** (F4-C, M2)", with `Enabled = true` and worker 3.1. The activation and rollback sequences keep their order and wording exactly (§8), apart from the §4.5 override corrections. The **Configuration** line gets the frozen values (`ClaimSeconds` 480) and cites `docs/qualification/stage2-s1/f4-configuration-freeze.md`. "The timing values are development defaults" becomes "frozen by F4 from M1 measurement". Effective bound: 22 085 s ≈ 6.13 h. |
| same runbook, "Completion contract v3 deployment order" intro | "default `false` … default `3.0` … Until the F3 release turns both on" becomes the shipped state (gate on, worker 3.1), with 3.0 kept as the rollback pair |
| same runbook, disconnected step 3 | "Once F4-C ships these as defaults, confirm the defaults instead" becomes an instruction to confirm the shipped defaults. Setting them explicitly is no longer required. |
| `contracts/README.md` l. 19 and l. 30 | worker default **3.1**; "when the F3 release sets" becomes the shipped state since F4-C |
| `docs/decisions/ADR-006-platform-owned-accepted-evidence.md` §7 status line | "Activation … remains a separate, controlled step after F3 review" becomes "Activated as the shipped default by F4-C, whose merge commit is M2; values frozen in `docs/qualification/stage2-s1/f4-configuration-freeze.md`". No rule changes. |

Historical plans (async-finalization, F3, F4 master and execution plans) are **not** edited.

### 4.5 Runbook override corrections (P2, found while planning)

In activation step 1 and rollback step 4, replace "`appsettings.<environment>.machine.json` or `MAVI_MACHINE_CONFIG`" with the actual mechanisms:
- **Windows:** `%ProgramData%\MAVI\config\appsettings.machine.json` (Production), or `%ProgramData%\MAVI\Development\config\appsettings.development.machine.json` (Development);
- **any OS:** `MAVI_MACHINE_CONFIG=<file>`;
- **any OS, highest precedence:** the environment variable `VisionFinalization__Enabled=false`.

Also:
- State that on Linux there is **no default machine-config path**.
- Add to activation step 1: a worker host upgraded to the F4-C worker package before step 5 must set `MAVI_COMPLETION_SCHEMA_VERSION=3.0`, or it fails closed at the probe against the held-off fleet.
  - Failing closed is safe (it leases nothing), but it stalls processing.
  - The step's "workers keep running on 3.0" assumed the old package.
- Rollback step 6 already sets 3.0 explicitly: no change.

The sequence and its order do not change (§8).

---

## 5. Freeze document and exploratory evidence

### 5.1 Layout added by F4-C

```
docs/qualification/stage2-s1/
  f4-configuration-freeze.md                      # finalized from the staged draft (§5.3)
  exploratory/
    .gitattributes                                # "* -text": no EOL conversion, ever (§5.2)
    aa30054478a1/
      exploratory-manifest.json                   # sidecar; schema s1-f4-exploratory-manifest-v1
      b3a/linux-x86_64-cpu/s1-b3a-hand-off.linux-x86_64-cpu.json        # raw, unedited
      b3b/linux-x86_64-cpu/s1-b3b-finalization.linux-x86_64-cpu.json    # raw, unedited
      hosts/linux-dev-container/python-host-identity.json
      hosts/linux-dev-container/raw-host.txt
      evaluation/eval-b3a.json  eval-b3b.json  derivation.json  evaluate_m1.py
      evaluation/b3a.trx  b3a-console.log  b3b-console.log
      evaluation/b3a-launch.txt  b3b-launch.txt
      evaluation/b3a-started.txt  b3a-finished.txt  b3b-started.txt  b3b-finished.txt
```

Nothing is written under `evidence/`. This follows MP §21 (`exploratory/<M1-sha12>/b3a/, b3b/`) and EP §5.

**Expected hashes (SHA-256).** Re-verify these at copy time. Any mismatch stops F4-C.

| File | Bytes | SHA-256 |
|---|---|---|
| `b3a/…/s1-b3a-hand-off.linux-x86_64-cpu.json` | 26 924 | `7de35bb1e7269c62ad722305e0771afdc8df1eb9b1fa38f27e0db2c31e92219d` |
| `b3b/…/s1-b3b-finalization.linux-x86_64-cpu.json` | 2 095 951 | `e35f7e07e6fa250aec46fee994f83410ae7c5fe982bd902ad3a89b3c47cc05a4` |
| `hosts/…/python-host-identity.json` | 392 | `c1db34035d4176f16628726fd7f9148d734c6c34822fbf4ec44d3589d498f4fd` |
| `hosts/…/raw-host.txt` | 858 | `0f9aac2ba4bdabbbf7b7a23019fc4a7ed9651204bcb6a98b60f117a0348eb88f` |
| `evaluation/eval-b3a.json` | 2 358 | `3cb5c5e93cc092c0b63d477fda38591ecb54e23b4f83a945a5c24aa00952c4cf` |
| `evaluation/eval-b3b.json` | 21 955 | `1806099debd29f1a2afaf952fa46f5ff130b7a4846ccb267d72d7959202dc457` |
| `evaluation/derivation.json` | 1 946 | `f6b568f733bac5452648ab1a0ee08113823c372dbc58b15a6afae5815580d985` |
| `evaluation/evaluate_m1.py` | 10 673 | `b6ce3317893c9e45f159841086ba735daadd6e5ce22ac67f6de41e83a6d18eed` |
| `evaluation/b3a.trx` | 1 099 795 | `4ce4f7bee7719d6c492e3155d578dda7dd2ce65067a1089f59703fee55cbd553` |
| `evaluation/b3a-console.log` | 573 | `92b6c20ce744da1303c21fab198ab8cfb233e71a035f65f3c0aa3cc8547924b1` |
| `evaluation/b3b-console.log` | 457 | `a766f090ca2eacd205c72abfdf08b6d53c959fc4279d67f0fe5ab2d086f3f9e7` |
| `evaluation/b3a-launch.txt` | 720 | `54efb5195e6ef03b25200ac33d2dbf46f5088a9547b99155f385ee8d19aca5cc` |
| `evaluation/b3b-launch.txt` | 738 | `abac77fe2d9237e9dbed5ab5645a920c4c0eeecc4aa67773b3465309deafdb92` |
| `evaluation/b3a-started.txt` | 21 | `38ebfa7b614408fefb767123c680ab1d6899632568fa3846edf935af4c46f821` |
| `evaluation/b3a-finished.txt` | 21 | `a56b3f29ebeff7ef25fa087a411e85bcfeac8a5b5ef50de0fd5224c7bd81bfe1` |
| `evaluation/b3b-started.txt` | 21 | `731f72bbe77196ed0518de5fe2b9a0126f713f92ab6c206e8cb83e8759b5b7a1` |
| `evaluation/b3b-finished.txt` | 21 | `6d2104edd8dc18d825f3d84153d1ed70bbe9da13a13bd1114636ea35c319b8cb` |

`exploratory-manifest.json` is authored, not raw. Its final SHA-256 is computed after §5.2 step 3 and recorded in the freeze document.

### 5.2 Retention procedure

1. **Copy.** Copy the files with `cp -p`, never through an editor, from the originals the harness and evaluator wrote. That is the staging package, whose raw outputs were `cmp`-verified against the harness output directory.
2. **Verify each file.** For each file, `sha256sum` must equal §5.1. Any difference stops F4-C.
3. **Finalize the manifest** (the only authored JSON):
   - schema `s1-f4-exploratory-manifest-v1`;
   - top-level `m1Sha`, `authoritative: false`, `reason: "exploratory-configuration-freeze"`;
   - one entry per file of §5.1 (17), each with `file`, `sha256`, `bytes`, `os`, `m1Sha`, `role`, `harnessRunId` (the output's `runId` for the two harness outputs, `f82a7e1e48a9439baa99c41d2c2ead72` and `b9ab218ba50d493c98d9d14a1755eb42`; otherwise `null`), `authoritative: false` and `reason`;
   - the four timestamp files are added.
4. **Keep raw bytes byte-for-byte.** Do **not** edit the raw outputs' `authoritative: true` (EP §5).
   - The flag records only that the host and tree were qualified.
   - Exploratory status comes from three things: `environment.gitSha = M1`, which the checker refuses at M2 (`b3_output_mismatch`, "it measured … not M2"); the `exploratory/` path, which lies outside `evidence/<M2-sha12>/`; and the manifest.
5. **Byte stability.** Add `docs/qualification/stage2-s1/exploratory/.gitattributes` containing `* -text`.
   - All files are LF-only today (0 CR bytes), so committing does not change them.
   - But the root `.gitattributes` gives `.trx`/`.txt`/`.log` no `eol` rule, so a Windows checkout with `core.autocrlf=true` would rewrite them.
   - `-text` forbids that on every OS, and is more specific than the root `*.json text eol=lf`.
6. **Commit, then prove the committed blobs.** For every file, `git show HEAD:<path> | sha256sum` must equal the manifest. Also check `git check-attr text -- <path>` gives `unset`. The PR description records this check.
7. **Secret check.**
   - `grep -rn "Password=" exploratory/` shows only `Password=***`: the launch records were masked when written.
   - The stock local credential does not appear as a value anywhere.
   - `verify_repo`'s secret scan passes.

   *(Planning probe: all three hold, and `verify_repo` passes with the package committed on a local copy.)*

Size: the largest file is 2.1 MB, under `verify_repo`'s 10 MiB `MAX_UNAPPROVED_TRACKED_FILE_BYTES`. No Git LFS and no dependency are involved.

### 5.3 `f4-configuration-freeze.md` (finalized from the staged draft)

The final document contains:

1. **Status.**
   - It is the configuration-freeze decision, applied by F4-C.
   - "**No authoritative S1.4 qualification has started.** B1–B6 and disconnected remain OPEN."
   - "Nothing here is evidence."
2. **Identity.**
   - M1 SHA, with a clean standalone clone.
   - `main` at freeze, and the M1 → F4-C-base diff classification (§1.1).
   - Configuration in force at M1, and the absence of overrides.
3. **Host.** The §2.1 table. Linux only. **No Windows exploratory host was available**, together with the EP §4.3 consequence (authoritative M2 B3 needs both OS).
4. **Retained outputs.** Paths, bytes and SHA-256 (§5.1), plus the manifest path and its final SHA-256. It also restates the no-edit rule and the three exploratory protections.
5. **Checker evaluations.** §2.2, with `[]` findings for header, content and concurrency.
6. **Inputs.** §2.3: per-OS and pooled, the governing OS of each input, and the p95 values. First-claim interval "not retained at M1" and extension overhead "not measured at M1". `ClaimSeconds` uses the conservative `4 × T_max` bound, and a tighter value needs a harness revision.
7. **Rule arithmetic and chosen values.** §2.4:
   - M1 committed values, derived floors, frozen values, never-lowered comparison;
   - effective bound 22 085 s;
   - the `T_max ≤ 1200 s` consequence;
   - the ½-Max gate is constructional at M1, not independent evidence.
8. **Activation gate:** PASS (Linux).
9. **Harness constraints for M2** (recorded, not fixed):
   - **Standalone clone.** `QualificationGate.ReadGitSha` requires `.git` to be a **directory**, so a `git worktree` checkout records `gitSha = "unknown"` (the discarded first B3-A attempt). **Authoritative M2 runs must use a standalone clone** unless a later, separately qualified harness change lands.
   - **B3-B TRX.** No TRX was written for the B3-B run. It passed (`Passed: 1`, exit 0), and its console log and raw output are retained. None is required (§5.4).
10. **Not done.** No `evidence/` file exists, and M2 does not exist yet: F4-C's merge creates it.
11. **Independent review (Gate A).** The owner's or reviewer's sign-off on the exploratory record (EP §13 Gate A), with date and reviewer.
    - **F4-C does not write this sign-off itself.** It is a merge precondition (§12).
    - Until it is recorded, the section says "Pending" and F4-C stays draft.

### 5.4 B3-B TRX conclusion

**No authoritative M2 requirement mandates a TRX for the B3-B harness run.**
- The checker's B3 unit requires the harness JSON outputs `b3a.hand-off-output.<v>`, `b3b.finalization-output.<v>` and `b3.crash-matrix-output.<v>`.
- Each is bound to a `runs` entry of `kind: "local"` that carries `host`, `command`, `cleanTree: true` and `harnessRunId == output.runId` (`s1_evidence.py:1383–1400`, `1744–1745`).
- TRX/JUnit is required only for the listed Quality Gate suites and the B3/B4 proving tests. Those come from the M2 Quality Gate **workflow** run (`_suites`, `_junit`, `B3_PROVING_TESTS`, `B4_PROVING_TESTS`), never from the local harness run.

The missing M1 TRX therefore neither invalidates the exploration nor blocks M2. F4-C does not touch the harness or the logger. The M2 run instructions keep `--logger trx` as a best-effort supporting artefact: if it is missing again, record it; it is not blocking. A harness or logger repair, should one ever be wanted, would be a separate decision that invalidates the M1→M2 freeze (EP §4.1). It is never part of F4-C.

---

## 6. Tests

Test-first: each **red** test fails at `10006d0` before §4 is applied. Guards pass throughout.

### 6.1 .NET

**`tests/Mavi.IntegrationTests/ConfigurationValidationTests.cs`**

This file is not used by any harness. It already reads `appsettings.json` from `FindRepositoryRoot()`.

1. **red. `ShippedVisionFinalizationSectionIsTheF4Freeze`.** Parse `src/platform/Mavi.Api/appsettings.json`:
   - the `VisionFinalization` object has **exactly** the nine keys;
   - `Enabled == true`, `ClaimSeconds == 480`, `ClaimExtensionSeconds == 300`, `MaximumFinalizationAttempts == 3`, `MaximumFinalizationDurationSeconds == 21600`, `SealingBatchSize == 200`, `PollIntervalSeconds == 5`, `MaxConcurrentFinalizations == 1`, `PayloadCleanupGraceSeconds == 0`;
   - `ClaimExtensionSeconds ≤ ClaimSeconds ≤ MaximumFinalizationDurationSeconds`;
   - `Max + Claim + Poll == 22085`;
   - `appsettings.Development.json` and `appsettings.Production.json` have no `VisionFinalization` property (no committed environment override);
   - `ConnectionStrings:Mavi` has no `Command Timeout`.
2. **red. `ShippedVisionFinalizationSectionBindsValidatesAndActivatesTheContract`.**
   - Setup: build configuration from the **real file** (`AddJsonFile(<shipped>)`) plus the existing `BuildProvider` required values, which carry no `VisionFinalization` keys.
   - `IOptions<VisionFinalizationOptions>.Value` resolves, so the validator passes on start.
   - `Enabled` is true.
   - `ToPolicy()` gives claim 480 s, extension 300 s, attempts 3, max 21 600 s, batch 200, and `EffectiveMaximumFinalizationBound == 21 600 + 480 s`.
   - `WorkerContractRules.CompletionSchemaVersions(value.Enabled)` sequence-equals `["2.0","3.1"]`.
   - `IsAcceptedCompletionSchemaVersion("3.0", value.Enabled)` is false; `"2.0"` and `"3.1"` are true.
3. **guard (red for a missing or broken override). `AMachineOverrideHoldsTheShippedGateOff`.**
   - Setup: the same, with `VisionFinalization:Enabled = "false"` layered after the file. This is the precedence of a machine file or environment variable (§1.7).
   - Result: `["2.0","3.0"]`; 3.1 is not accepted; the frozen timing values are unchanged, because an override changes only the gate.
   - `BuildProvider` gains an optional base-file parameter. It is private to this test class.

**`tests/Mavi.IntegrationTests/VisionFinalizationActivationGateTests.cs`**

4. **guard, rename only.**
   - The four `ByDefault…` tests become `WhenTheGateIsHeldOff…`, and the section comment and class summary are updated. They still run through `ApiTestFactory`'s explicit `Enabled = false`, which is now exactly activation step 1 or a rollback.
   - Assertions are unchanged.
   - None of these names is in `B3_PROVING_TESTS` or `B4_PROVING_TESTS` (checked), so no checker map changes.
5. **guard, unchanged:**
   - `WhenActivatedTheProbeAdvertises31Retires30AndTheHandOffIsLive`;
   - `TheProbeAdvertisesExactlyTheVersionsTheEndpointAccepts(bool)`, which proves the endpoint uses the same gate as tests 2 and 3;
   - `VisionFinalizationSubmissionApiTests.V2CompletionIsStillSynchronousAndEchoesItsOwnVersion` (2.0 under activation);
   - `Retired30IsRefusedEvenWithAValidLeaseAndNeverReinterpreted`.

**Unchanged by design:**
- `VisionFinalizationOptionsTests`, because the code defaults are unchanged (§4.3);
- `ApiTestFactory.cs`, because the harness depends on it (§1.6);
- every F1–F3 lifecycle, publication, executor, host, recovery and janitor test.

### 6.2 Worker (`src/vision/tests`)

**`test_worker_completion_v3.py`**

- **Helper change.** `_settings(..., version: str | None = "3.1")`. `None` means the kwarg is **not passed**, so the test sees the real `WorkerSettings` default. `_run` and `_complete_golden` forward `None`.
- The four default tests become their 3.1 counterparts (MP §10.5). Each constructs settings with `version=None`.

6. **red. `test_the_default_worker_emits_the_hand_off_completion`:**
   - the body equals the 3.1 golden example byte for byte, and `schemaVersion == "3.1"`;
   - the `finalizing` acknowledgement is accepted as the hand-off.
7. **red. `test_the_default_worker_refuses_a_synchronous_acknowledgement`:** a 3.0-style echo raises `WorkerApiError("unexpected version")`, and nothing is guessed.
8. **red. `test_the_default_worker_accepts_the_activated_platform`:**
   - `WorkerSettings(...)` with no version has `completion_schema_version == "3.1"`;
   - the probe `["2.0","3.1"]` is accepted.
9. **red. `test_a_pre_activation_platform_is_unsupported_for_the_default_worker`:** the default worker against `["2.0","3.0"]` raises `PlatformContractUnsupported`. There is no fallback to 3.0 or 2.0, and no lease.
10. **guard, rollback pair kept.** A worker explicitly on `"3.0"`:
    - against `["2.0","3.0"]` completes synchronously (the 3.0 golden body, `schemaVersion "3.0"`);
    - against `["2.0","3.1"]` is unsupported.

    These are the existing explicit-3.0 cases:
    - The four current "default" test bodies already pass `version="3.0"`. They are kept, with their assertions, renamed `test_a_3_0_worker_…` so no name claims "default".
    - Tests 6–9 are added beside them.
    - The existing `test_a_platform_listing_only_completion_3_0_is_unsupported_for_a_3_1_worker` stays.

**`test_worker_settings.py`**

11. **red. `test_the_shipped_completion_default_is_3_1_and_3_0_remains_the_rollback_setting`:**
    - the default is `"3.1"`;
    - `MAVI_COMPLETION_SCHEMA_VERSION=3.0` loads `"3.0"`;
    - `"2.0"` and `"3.2"` are rejected by validation.

**`test_worker_client.py`**

12. **update, the two probe failures:**
    - `test_complete_uses_canonical_path_and_projects_runtime_provenance`;
    - `test_complete_projects_physical_gpu_identity_and_resolution_reason`.

    They use default settings, so they now assert `payload["schemaVersion"] == "3.1"` and answer with the 3.1 `finalizing` acknowledgement (the shape `test_worker_completion_v3._response_for` already builds). Every provenance assertion is unchanged. The stale "until the F3 release" comment is corrected.

Unchanged: every B4-mapped worker test (`test_worker_body_is_byte_equivalent_to_the_golden_example`, `test_a_finalizing_acknowledgement_is_the_hand_off`, `test_a_completed_acknowledgement_is_an_idempotent_replay`, `test_current_attempt_staging_survives_the_hand_off`).

### 6.3 Checker and evidence tooling

**No change.** `tools/qualification/tests` passes (687/3 skipped) with the §4 edits applied.
- It already models the activated source (`test_s1_evidence.py:192`, `:3141`).
- `_frozen_configuration` and `activation_default_unqualified` are the M2 binding, and F4-C satisfies them without editing them.
- Loosening, extending or re-pointing the checker is out of scope (§10).

### 6.4 Discrimination check before push

Apply each mutant alone, confirm at least one §6 test fails, then revert:

| Mutant | Must fail |
|---|---|
| `Enabled` back to false | test 1, test 2 |
| `ClaimSeconds` 300 | test 1, test 2 |
| `ClaimExtensionSeconds` 360 | test 1 |
| `MaximumFinalizationDurationSeconds` 2400 | test 1 |
| `SealingBatchSize` 100 | test 1 |
| `MaximumFinalizationAttempts` 4 | test 1 |
| `MaxConcurrentFinalizations` 2 | test 1 |
| a `VisionFinalization` block added to `appsettings.Production.json` | test 1 |
| worker default back to `"3.0"` | tests 6, 8, 11 |
| a `"2.0"` added to the `Literal` | test 11 |
| a probe fallback (accepting `["2.0","3.0"]` for a 3.1 worker) | test 9 and the existing split-brain test |

The PR records the table with each observed result.

---

## 7. Validation sequence

Run from a **standalone clone** of the F4-C head, never a worktree. The M1 `QualificationProvenanceTests` also needs `.git` to be a directory (§5.3 item 9). In a worktree it fails for that reason alone, as observed while planning.

### 7.1 Local, in order

```bash
# focused first
dotnet build MAVI.sln --configuration Release
dotnet test tests/Mavi.IntegrationTests --configuration Release --no-build \
  --filter "FullyQualifiedName~ConfigurationValidationTests|FullyQualifiedName~VisionFinalizationActivationGateTests|FullyQualifiedName~VisionFinalizationSubmissionApiTests"
(cd src/vision && python -m pytest -q tests/test_worker_completion_v3.py tests/test_worker_settings.py tests/test_worker_client.py)
# then everything
dotnet test tests/Mavi.Domain.Tests --configuration Release --no-build
dotnet test tests/Mavi.Application.Tests --configuration Release --no-build
dotnet test tests/Mavi.IntegrationTests --configuration Release --no-build     # serial by collection; needs PostgreSQL 18 via MAVI_TEST_DB_CONNECTION
(cd src/vision && python -m pytest -q)
python -m pytest -q -rs tools/qualification/tests
python -m pytest -q tools/phase1/tests
python tools/verify_repo.py
# web: no shared contract changes; run as a guard
(cd src/web/mavi-web && npm run typecheck && npm test && npm run build)
```

- `MAVI_QUALIFICATION` stays **unset**, so the B3 harnesses skip: **no B3-A/B3-B run happens**.
- No `MAVI_MACHINE_CONFIG` or `VisionFinalization__*` is set in the environment.
- Any smoke run (for example a host started to read `/api/vision/contract`) is labelled non-authoritative in the PR and is never retained.

### 7.2 CI

Exact-head CI on the PR head must be green:
- Quality Gate (the .NET TRX per project, worker pytest, checker tests, web);
- Task 10 runtime qualification, where it triggers;
- Task 17 acceptance.

The PR records run IDs and `head_sha`.

### 7.3 Planning probe results (throwaway local copy, not the PR)

| Check | Result |
|---|---|
| worker pytest | 3 expected failures (§1.6), all addressed by §6.2 |
| checker tests | pass |
| `verify_repo` | pass, package included |
| .NET Domain / Application | 281 / 502 pass |
| .NET build | Release, exit 0 |
| .NET Integration (PostgreSQL 18, `MAVI_QUALIFICATION` unset) | **914 passed, 3 skipped (the opt-in B3 harnesses), 1 failed**. The failure is `QualificationProvenanceTests.CaptureEmitsProvenanceSignalsThatDescribeThisRepository`: `gitCommitObjectPresent = "false"`, because the probe ran from a git **worktree**, the same `.git`-file limitation as §5.3 item 9. It passes from a standalone clone, which is why §7 requires one. No activation-related failure. |

---

## 8. Deployment and rollback contract (unchanged sequence)

F4-C does not simplify, reorder or weaken the worker-quiescent sequence on `main` (EP §11.3; runbook "Asynchronous finalization …"). It changes only the statement of defaults and the §4.5 override mechanics. The PR shows the sequence steps unchanged in its diff.

**Activation** (a deployment moving to M2's binary):
1. Deploy the F4-C platform on **every** API host with the gate **held off** by an override (§4.5). Workers stay on 3.0; an F4-C worker package must pin 3.0.
2. On each host **directly**, not through the load balancer, verify:
   - `details.visionFinalization.enabled = false`, with no options error;
   - `completionSchemaVersions` exactly `["2.0","3.0"]`;
   - `malformedClaims == 0`.
3. **Stop every worker.** Disable service-manager restart, and confirm no worker process runs on any worker host.
4. Wait: leased work returns to the queue at lease expiry (only that attempt's inference is lost).
5. Remove the override, or set `Enabled = true`, on every API host.
6. Restart every API host.
7. On each host **directly**, verify:
   - `enabled = true`;
   - exactly `["2.0","3.1"]`;
   - `malformedClaims == 0`.

   Do not continue until **every** host passes.
8. Only then start workers on 3.1, the package default.
9. In each worker's log, confirm the first lease followed a probe listing `"3.1"`, with no `vision_platform_contract_unsupported`.
10. Watch finalizer health: `finalizingJobs` rises and falls, `liveClaims ≤ hosts × MaxConcurrentFinalizations`, `malformedClaims = 0`.

**No worker leases while the API fleet could be in mixed contract state.**

**Rollback:**
1. Stop every worker and keep them stopped.
2. Leave every API host **enabled**, so the finalizer drains.
3. Require `finalizingJobs == 0`, `countsRefreshedAtUtc` within two `PollIntervalSeconds`, and `malformedClaims == 0`. If `malformedClaims > 0`, stop.
4. Hold the gate off with an override (§4.5) on **every** API host.
5. Restart every API host.
6. Verify each host directly: `enabled = false` and exactly `["2.0","3.0"]`.
7. Only after **every** host is verified, start workers with `MAVI_COMPLETION_SCHEMA_VERSION=3.0`. Confirm their first probe listed `"3.0"`.

**Never disable the gate while `Finalizing` rows exist.** Never start a worker while any host is unverified.

---

## 9. M2 declaration

- **Definition.** **M2 is exactly the merge commit of the F4-C PR on `main`** (EP §14, MP §7.1).
- **Merge method.** Merge commit only: no squash, no rebase. M2 is therefore a merge commit reachable from `main`.
- **Ancestry.** U1's merge `10006d0174642beaf64f660716580ea865506bdc` must be in its ancestry. Check with `git merge-base --is-ancestor 10006d0 <M2>`, exit 0.
- **The M1→M2 diff.** Record `git diff --no-renames --name-only aa30054 <M2>`, with every path classified:
  - behaviour-bearing: U1 (`src/web/mavi-web/src/**`) and F4-C (§4.1, §4.2, the tests of §6);
  - non-behavioural: docs (`docs/**`, `contracts/README.md`, the §4.3 comment-only C# remark);
  - evidence: the §5 package.
- **Stop conditions.** Stop if any of these appears in the diff:
  - `tests/Mavi.IntegrationTests/Qualification/**`, `tools/qualification/**` or `tools/web-visual-qa/**`;
  - `tests/Mavi.IntegrationTests/ApiTestFactory.cs`;
  - any other behaviour-bearing path.

  Any of these invalidates the derivation, and exploration restarts at a new M1.
- **Record after merge.** In the M2 declaration (the first step of the authoritative sequence, MP §25 step 1), record:
  - U1 merge SHA;
  - F4-C PR head;
  - F4-C merge SHA (M2);
  - the M1→M2 diff;
  - the frozen configuration;
  - `Enabled = true` and worker `"3.1"`.
- **Freeze after M2.** Until authoritative qualification completes, nothing may land that changes: product code, configuration, harness, checker, UI, dependencies or the worker default. The one exception is an explicit invalidation that re-creates M2.
  - The `VisionFinalization` values and the activation defaults are **never** re-frozen from authoritative M2 measurements (EP §14).
  - If M2 qualification fails, stop and report: the failure is fixed separately, followed by new exploration, freeze and M2 as required. The failed M2 is never relabelled.
- **Not in this plan.** The authoritative sequence itself (MP §25) is not part of F4-C.

---

## 10. Scope exclusions

F4-C does **not**:
- modify the finalizer algorithm, job lifecycle, claim semantics, publication transaction, visibility barrier, sequence allocation or Evidence Set semantics;
- modify the selector, scorer or profile, the B3 thresholds or any checker criterion;
- modify `tests/Mavi.IntegrationTests/Qualification/**`, `tools/qualification/**`, `tools/web-visual-qa/**` or `tests/Mavi.IntegrationTests/ApiTestFactory.cs`;
- change the C# option initializers (§4.3);
- change the U1 UI, dependencies or lock files;
- add bulk sealing, performance work or concurrency above 1;
- change attempts from 3;
- change the batch size from 200;
- lower any value below M1's;
- add a worker fallback or a `"2.0"` worker option;
- commit a machine override;
- run an authoritative B3-A or B3-B, or write anything under `evidence/`.

If implementation appears to need any of these, **stop and report**. Do not fold it in.

---

## 11. Cold-review checklist

| # | Attack | Refuted by | Sev |
|---|---|---|---|
| 1 | `Enabled` still false somewhere shipped | test 1: base `true`, and no `VisionFinalization` block in Development or Production; test 2 binds the real file | P1 |
| 2 | Machine override committed | the override paths lie outside the repo (§1.7); test 1 bans environment-file blocks; the diff shows no `*.machine.json` | P1 |
| 3 | Worker default still 3.0 | tests 6, 8 and 11 use the **real** default (`version=None`); the checker's `worker_completion_default` sees the same line | P1 |
| 4 | Platform advertises 3.0 with gate on | test 2 and the existing activated tests | P1 |
| 5 | 2.0 refused by accident | test 2 (`"2.0"` accepted); `V2CompletionIsStillSynchronousAndEchoesItsOwnVersion` | P1 |
| 6 | Worker gains fallback | test 9; the existing split-brain tests; the diff shows no `mavi_vision/worker/**` change | P1 |
| 7 | `ClaimSeconds` stays 300 | test 1, test 2; §6.4 mutant | P1 |
| 8 | `ClaimExtensionSeconds` raised without need | test 1 pins 300 (floor 90 < M1 300) | P2 |
| 9 | Max lowered to `M_bound` 2400 | test 1 pins 21 600; §6.4 mutant | P1 |
| 10 | Any M1 value lowered | test 1 exact values ≥ M1; the freeze doc's never-lowered row | P1 |
| 11 | Batch ≠ 200 | test 1; §6.4 mutant | P1 |
| 12 | Attempts ≠ 3 | test 1; §6.4 mutant | P1 |
| 13 | Concurrency ≠ 1 | test 1; §6.4 mutant | P1 |
| 14 | M1 output edited | §5.2 steps 2 and 6: hashes before and after commit equal §5.1; the manifest lists them | P1 |
| 15 | Exploratory output under `evidence/` | §5.1 layout; the checker refuses a cited artifact outside `evidence/<M2>` and any `gitSha ≠ M2` | P1 |
| 16 | Raw `authoritative: true` edited | §5.2 step 4; hash equality | P1 |
| 17 | Windows absence hidden | freeze doc item 3 and the PR text; §2.1 "Linux only" | P2 |
| 18 | F4-C claims Windows qualification | same; F4-C claims no qualification at all | P1 |
| 19 | Authoritative run before M2 | §7.1: `MAVI_QUALIFICATION` unset; no `evidence/` path in the diff | P1 |
| 20 | U1 missing from M2 ancestry | §9 `merge-base --is-ancestor`; the F4-C branch is cut from `main` ≥ `10006d0` | P1 |
| 21 | Harness or checker change slips in | §9 diff stop list, including `ApiTestFactory.cs` | P1 |
| 22 | Standalone-clone limitation forgotten | freeze doc item 9; §7 run from a clone | P2 |
| 23 | B3-B TRX ambiguous | §5.4 conclusion, bound to checker lines | P2 |
| 24 | Workers lease during mixed contract | §8 unchanged sequence; §4.5 pins 3.0 on early-upgraded workers | P1 |
| 25 | Rollback disables before drain | §8 rollback steps 1–3 unchanged | P1 |
| 26 | Squash or rebase merge | §9; §12 criterion 9 | P1 |
| 27 | Product change after M2 without invalidation | §9 freeze rule | P1 |
| 28 | C# defaults silently changed | §4.3; `VisionFinalizationOptionsTests` unchanged and green | P2 |
| 29 | Hollow "default" tests | §6.2 `version=None`; the §6.4 mutant "default 3.0" must fail | P2 |
| 30 | Linux override instructions unusable | §4.5 runbook correction | P2 |
| 31 | Gate A unsigned | §5.3 item 11; §12 criterion 1 | P2 |
| 32 | EOL rewrite breaks hashes on Windows | §5.2 step 5 `-text` | P2 |
| 33 | Credential committed | §5.2 step 7 | P1 |

---

## 12. Completion criteria (F4-C merge-ready)

1. **Gate A.** The exploratory record's independent review is recorded in the freeze document by the owner or reviewer, not by the F4-C author.
2. **Product diff.** Exactly §4.1 and §4.2, plus the §4.3 comment. The other changes are §4.4 and §4.5 docs, the §5 package and the §6 tests.
3. **Red then green.** Every §6 red test was seen red before §4, and all are green after. The §6.4 mutants are each caught.
4. **Validation.** The §7.1 suites are green from a standalone clone, and `verify_repo` passes.
5. **Package integrity.** The §5.2 hash and attribute checks pass on the committed blobs. The manifest lists all 17 files and has `authoritative: false`.
6. **CI.** Exact-head CI (§7.2) is green.
7. **Scope.** The §9 diff stop list is empty, as the PR shows.
8. **Review.** An independent cold review (EP §13 Gate C and §11 here) raises no P1 or P2.
9. **Merge.** A merge commit, with `10006d0` an ancestor. The merge SHA is recorded as **M2**.
10. **No authoritative qualification** has started before M2. The next step is MP §25 at M2, from a standalone clone, on Linux **and** Windows.
