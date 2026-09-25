# S1.4 qualification — PR B interim record at `bb331c6`

**Status: S1.4 is NOT closed. S1 is NOT complete.**

This record is evidence from execution at the measured SHA. It is not a closure record.

| Unit | Verdict | Reason |
|---|---|---|
| B1 | OPEN | The Linux real-clip probe is exact. No Windows run exists. |
| B2 | OPEN | Not run; deferred to the final measured SHA. |
| B3 | **FAIL** | Worst-case completion takes 190.8 s against the 15 s needed for 2× headroom. |
| B4 | **PASS** at `bb331c6` | Invalidated by any platform fix for B3. |
| B5 | OPEN | Not run; waits for the final SHA. |
| B6 | **FAIL** at `bb331c6` | 3 unapproved skips per variant; fixed by PR #86. |
| Disconnected | OPEN | No network-isolated host is available. |

- **Machine-readable record:** `s1-qualification-evidence.json`. `python tools/qualification/s1_evidence.py check docs/qualification/stage2-s1/s1-qualification-evidence.json` accepts it (`s1-evidence-record-valid`) with the verdicts above.
- **Retained files:** `evidence/bb331c6/`.
- **Plan:** `docs/superpowers/plans/2026-09-24-stage2-s1-4-hardening-qualification-implementation.md`.

## 1. Measured identity

| Item | Value |
|---|---|
| Measured SHA | `main@bb331c6825569b32ed280cfde21d6527071a7fb0` (the PR #85 merge; `main` had not advanced) |
| Pipeline profile | `phase1-detection-tracking-v1`, `1.2.0-candidate`, SHA-256 `503225be736d9622ed110aa69e49a83dde4ae02c858d5e8fa41e527b1c4b23fb` |
| Selector / scorer / encoder | `evidence-selector-v1-two-tier` / `quality-v2` / `evidence-jpeg-ladder-v1` |
| Completion schema / digest | 3.0 / 3 |
| Qualified CPU variants | `linux-x86_64-cpu` (Python 3.12.14), `windows-x86_64-cpu` (Python 3.12.10) |
| Local host (`dev-container-linux`) | Intel Xeon @ 2.10 GHz, 4 cores / 4 threads, 15.7 GiB RAM, Ubuntu 24.04.4 LTS, kernel 6.18.44, ext4 on a virtio block device |

The storage class cannot be determined from inside the VM. It is recorded as `network`, the nearest schema value; that is an assumption, not a measurement.

## 2. Exact-head workflows on `bb331c6` (Phase 1)

Every run below is a `push` run with its `head_sha` verified through the Actions API. Each artifact zip's SHA-256 equals GitHub's own artifact digest.

| Workflow | Run | Result | Artifact (SHA-256 of zip) |
|---|---|---|---|
| MAVI Quality Gate | [36049488875](https://github.com/hariomahlawat/MAVI/actions/runs/36049488875) | success | `quality-gate-test-results` `d1ce29b3…31f7e` |
| Task 10 Runtime Qualification | [36049488884](https://github.com/hariomahlawat/MAVI/actions/runs/36049488884) | success | Linux `cf447092…f356`, Windows `83ab1522…3727` |
| Task 10 Staging Security | [36049488976](https://github.com/hariomahlawat/MAVI/actions/runs/36049488976) | success | — |
| Task 17 Acceptance Validation | [36049488885](https://github.com/hariomahlawat/MAVI/actions/runs/36049488885) | success | — |

The Quality Gate's retained results, recounted by the checker:

| Suite | Passed | Skipped | Note |
|---|---|---|---|
| `Mavi.Application.Tests` | 454 | 0 | |
| `Mavi.Domain.Tests` | 209 | 0 | |
| `Mavi.IntegrationTests` | 757 | 1 | The skip is the opt-in sealing harness. |
| web | 895 | 0 | |

## 3. B6 — FAIL at `bb331c6`

Both variants' Task-10 records name `bb331c6` and their own variant, and every JUnit test suite is named after its variant. All steps pass with zero failures. Apart from `runtime-tooling`, every skip is a §3.1 paired-variant skip (33 pairs, each passing on the other variant).

`runtime-tooling` skips three `test_runtime_probe.py` tests on **both** variants. Torch and mmengine are installed in later steps:

| Test | Skip reason | Ran elsewhere? |
|---|---|---|
| `test_real_torch_scope_allows_reviewed_numpy_metadata_and_restores_globals` | no `torch` | Passed in `runtime-probe-real-torch`. |
| `test_real_torch_scope_rejects_unapproved_type_and_restores_globals` | no `torch` | Passed in `runtime-probe-real-torch`. |
| `test_reviewed_checkpoint_globals_cover_legacy_and_numpy2_numpy_aliases` | no `mmengine` | **Never executed by any qualified step.** |

These are not §3.1 skips, so B6 cannot pass (§14 stop condition 11). The checker refuses a B6 PASS with exactly these 6 `skip_not_approved` findings.

The fix is **[PR #86](https://github.com/hariomahlawat/MAVI/pull/86)**, which changes the workflow only:
- The tooling step deselects exactly these three tests.
- The post-install step runs exactly these three by node id.
- A guard runs pytest collection with the step's real arguments.

All three pass on the qualified Linux runtime. PR #86 changes the Task-10 workflow, an evidence path in §2.1, so its merge commit becomes the new measured SHA and every unit is re-measured there (§2.2).

## 4. B3 — FAIL (§7.4 headroom)

The authoritative sealing-scale run on `linux-x86_64-cpu`, output `evidence/bb331c6/b3/s1-b3-sealing-scale.linux-x86_64-cpu.json` (SHA-256 `acf825c2…52425b`):

- **Envelope (full, `authoritative: true`):**
  - 10,000 Tracks, 40,000 Observations, 50,000 sealed objects and 50,001 Artifact rows;
  - 30 samples × 3 repeats after 1 warm-up (n = 90);
  - the default worker timeout of 30,000 ms (`WorkerSettings`);
  - PostgreSQL 18.6, ext4, a clean tree at `bb331c6`.
- **Timing:**
  - **Completion:** min 78.8 s · p50 104.0 s · p95 130.8 s · **max 190.8 s**. The p50 run-to-run spread is 13.2 s.
  - **Exact replay:** p50 0.8 s, p95 1.2 s.
- **Verdict:** 2× headroom needs max ≤ 15.0 s. The measured headroom is 30 s / 190.8 s = **0.16×**. The checker reports `completion_headroom_insufficient`.
  - The maximum also exceeds the 120 s vision lease and the 120 s maximum worker timeout. So no supported timeout setting gives 2× headroom either.
  - The Windows (NTFS) sealing output was not produced; no qualified Windows host is available.

**Cause analysis (engineering observations, not evidence):**

| Observation | Setup | Finding |
|---|---|---|
| Syscall count | `strace -c` over 10,000 sealed objects | Exactly **12 `fsync` per object**. `EnsureDirectoryHierarchy` re-fsyncs the root-parent and 5-level directory chain on every object. Add the file flush, the parent after `link`, and the parent after removing the temporary name. |
| fsync-reduction prototype (not committed) | Each chain made durable once; housekeeping fsync dropped | 10 of 12 fsyncs removed. Completion only fell to **63–80 s**. |
| Phase split | The same prototype | Sealing loop 57–68 s (about 1.2 ms per object, sequential, inside `FOR UPDATE`). First `SaveChangesAsync` 12–15 s (about 100,000 tracked EF entities). Second 2 s. |

So trimming fsyncs is **not sufficient**. At the worst-case object count, sequential durable sealing plus change-tracked persistence cannot reach 15 s. B3 needs an architecture decision (ADR-013), which is the owner's call:

1. seal before taking the job lock, or asynchronously;
2. bulk persistence (COPY) plus concurrent or batched durable publication;
3. or a reviewed plan or contract change to the completion timeout model.

A focused fix PR follows only after that decision. Any `src/platform` fix invalidates B3, B4, B5 and the disconnected run (§2.2).

**Harness gap (recorded):** §7.4 asks for validation time and sealing/transaction time separately. `S1SealingScaleTests` records only the end-to-end completion time. This does not affect the verdict.

## 5. B1 — Linux probe exact; unit OPEN

The inputs are the original MOT17-02-FRCNN and MOT17-13-FRCNN 1080p files, whose SHA-256s match the baseline. They are run on the qualified `linux-x86_64-cpu` runtime:
- `mmcv` 2.1.0 is the parameter note's locally built wheel `dfc6313a…d6d4af`;
- torch 2.6.0+cpu with 4 threads;
- the same 4-vCPU host class as the parameter note.

| Comparison (exact, host timing excluded) | Mismatches |
|---|---|
| Run vs accepted baseline (`b1-accepted-real-clip-baseline.json`) | **0**: 63 Tracks, 8,284 candidates, 9 fallback Representatives |
| Repeat in a separate process vs run | **0** |
| Detector-independent replay vs run | **0**; the replay took 8.5–9.5 s, with no model runtime |
| Identity problems (profile, clips, variant, replay) | none |

The retained summaries are `evidence/bb331c6/b1/*.summary.json`. The detection recordings (8.4 MB and 13 MB; `d4db7054…1b05435`, `35e164b8…63973d7`) and the candidate CSVs stay outside Git, as licensed input derivatives.

B1 stays OPEN for two reasons:
- no Windows run or repeat exists, so `s1_b1.py compare` cannot derive the four counts;
- the final measured SHA will differ (PR #86).

## 6. B4 — PASS at `bb331c6`

The five B4 suites pass with zero skips and zero failures, recounted from the retained TRX and JUnit, and the pinned v3 golden is retained:
- `test_worker_completion_v3.py` (from Task 10 Linux `s1-boundary`);
- `CompletionDigestGoldenTests`;
- `VisionResultCompletionV3ApiTests`;
- `VisionResultCompletionApiTests`;
- `VisionResultCompletionCommitFailureTests`.

The checker accepts the PASS against the repository. A B3 platform fix would invalidate it, and it would then be rerun on the final SHA.

## 7. Not executed, and why

| Item | Blocker |
|---|---|
| B2 (all presets and lifecycle, both variants) | Deferred to the final measured SHA by owner decision. No qualified Windows host is available. |
| B5 (real-video E2E on two clips, four-viewport visual QA) | Waits for the final SHA, because the B3 platform fix invalidates B5. |
| All Windows halves (B1, B2, B3) | No Windows Development host is available to this execution environment. |
| Disconnected run | No network-isolated host is available. Hosted CI is not a substitute (§11). |

## 8. Non-claims

- No unit other than B4 is PASS, and B4 stands only at `bb331c6`.
- No Production, CUDA, model-accuracy, Visual Attributes or S2 claim is made.
- The RTMDet qualification record was not edited.
- No selector, scorer or profile value changed.
- No workflow, harness or product code is changed by this record. The only change proposed so far is PR #86.
