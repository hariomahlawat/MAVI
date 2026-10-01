# Task 10: S1 harness separation and verified MMCV wheel reuse

- **Date:** 2026-10-01
- **Status:** Proposed. Draft PR; not merged.
- **Scope:** how the Task 10 workflow (`task10-runtime-qualification.yml`) is split into jobs, what evidence each job contributes, and when Task 10 may install an MMCV wheel it compiled in an earlier run.
- **Governing documents:**
  - ADR-005 §17, which this note amends; see "Amendment".
  - S1.4 plan §2.2 / §3 / §10.1.
  - `2026-10-01-s1-qualification-harness-surface.md` (#127).
  - Task 10 plan, "Freeze sequence".
  - Task 12 MMCV wheel reproducibility (`tools/vision/compare_wheel_reproducibility.py`).

## Problem

Task 10 ran one serial job per variant. On Windows the job took 16.8–17.4 min. Two parts dominated it:

- **MMCV compile, every run.** Median about 424 s on Windows and about 330 s on Linux.
- **S1 qualification harness.** 318–385 s on Windows. It ran after the full runtime graph was installed, even though it uses none of it.

## Evidence contract

### What the S1 harness actually imports

`tools/qualification/tests/test_s1_*.py` was run with `MAVI_RUN_QUALIFIED_BYTETRACK_TESTS=1` and the loaded modules were audited.

- **Loaded:** NumPy, SciPy, OpenCV, PyAV, `trackers` and `supervision`.
- **Never loaded:** `torch`, `torchvision`, `mmcv`, `mmengine` and `mmdet`.
- `trackers==2.6.0` declares no PyTorch dependency.
- On Linux without PyTorch installed, the harness collected and ran 719 tests: 719 passed and 1 was skipped. The skip is the approved OS-conditional `test_linux_probe_reads_this_process` skip. `task10_environment.py check-harness` accepts this.

The harness therefore does **not** need the full qualified graph. It does need the native ByteTrack stack, at exactly the versions the qualified candidate has.

### Which tests need which environment

| Task 10 JUnit step | Needs | Runs in |
|---|---|---|
| `runtime-tooling` | build tooling only; the ML tests are deselected and run in `runtime-probe-real-torch` | `cpu-candidate` (unchanged) |
| `s1-boundary` | the production boundary without ML imports, inside the candidate environment | `cpu-candidate` (unchanged) |
| `runtime-probe-real-torch` | PyTorch, MMEngine | `cpu-candidate` |
| `bytetrack-runtime` | the full graph | `cpu-candidate` |
| `real-clip-harness` | the full graph and real RTMDet | `cpu-candidate` |
| `production-processor-runtime` | the full graph and real RTMDet | `cpu-candidate` |
| `s1-qualification-harness` | the native tracker stack only (audit above) | **`s1-harness`** (new) |

The following all stay in the complete environment, as before:

- runtime probes;
- `runtime-probe.json` and `resolved-config.json`;
- the production runtime smoke test;
- ByteTrack qualification;
- production composition qualification;
- every B6 record.

Only the S1 harness moves.

### What Task 10 proves

On every head where Task 10 runs, for each variant:

1. **MMCV source.** The MMCV wheel installed in the candidate environment was compiled by Task 10 from the immutable commit `57c4e25e…` using the recipe `MMCV_BUILD_COMMAND`. One of two things holds:
   - it was compiled **in this run**, because the cache missed or the entry could not be verified; or
   - it was compiled in an earlier Task 10 run whose build identity is **byte-identical** to this job's. The wheel's hash, size, distribution, tag and RECORD consistency are verified before install.
   
   The provenance, which includes the producing run's ID, is retained as `mmcv-wheel.json`.
2. **Installed native binaries.** These checks run against the installed wheel in every run, whether the wheel was built or reused:
   - every import and native-op probe;
   - ByteTrack qualification;
   - real RTMDet inference.
   
   None of them is skipped on reuse.
3. **Runtime behaviour.** Every JUnit step except the harness runs in the complete candidate environment. The harness runs in an environment that the final gate proves is a subset of that candidate environment (see the next section).

What Task 10 **no longer** proves on a warm run is that MMCV *still compiles* on this head. It does not need to. A head cannot change any compile input without changing the identity key, and so forcing a rebuild:

- the source commit;
- the recipe;
- `MMCV_WITH_OPS`;
- the Python build;
- the PyTorch build and config;
- NumPy;
- the platform;
- the runner image;
- the MSVC, SDK or C++ toolchain;
- the cache tool itself.

### What Task 12 proves, unchanged

Task 12 compiles MMCV from source **twice**, independently, with deterministic flags and `MAX_JOBS=1`. It then compares the two wheels byte for byte (`compare_wheel_reproducibility.py`).

Task 12 never restores Task 10's cache. It shares no cache key with Task 10. This change does not touch it.

### How split-job evidence keeps its identity

Both jobs check out `github.event.pull_request.head.sha || github.sha` and fail unless `git rev-parse HEAD` equals that SHA. Each job writes a `mavi-task10-environment-v1` record containing:

- the head SHA and runtime variant;
- the Python version, implementation, build and compiler;
- the platform, `sysconfig` platform and runner image (`ImageOS`);
- every installed distribution with its version.

The final job, `task10-qualification`, runs with `if: always()` and needs both jobs. It fails unless:

- both `cpu-candidate` and `s1-harness` concluded `success`, so a failed, cancelled or skipped job fails the gate;
- for each variant, the harness JUnit exists. Every suite in it must be named after the variant, it must contain at least one test, and it must have no failure or error. Every skip must be one that `s1_evidence.is_approved_skip("task10:s1-qualification-harness", …)` approves;
- `compare` passes for each variant:
  - the head SHA, variant, Python and platform are identical;
  - every distribution in the harness environment exists in the candidate environment at the same version;
  - the harness has none of `torch`, `torchvision`, `mmcv`, `mmengine` or `mmdet`;
  - the candidate has all of them;
- the candidate's `mmcv-wheel.json` and its six other JUnit files are present and non-empty.

No job uses `continue-on-error`.

The S1 checker's contract is unchanged:

- Every JUnit file is still produced by a run of `task10-runtime-qualification.yml` and carries the variant as its suite name.
- The harness's artifact path still ends in `junit/s1-qualification-harness.xml`.
- `_run` requires the **run** to conclude `success`, and the run now succeeds only if the final gate does.

The harness JUnit is retained in a separate artifact, `s1-harness-<os>-py3.12`. The checker binds evidence by run, path, hash and suite name, never by artifact name, so it needs no change.

## Amendment to ADR-005 §17

ADR-005 §17 says a runtime qualifies only as one complete environment. That rule continues to govern **runtime qualification**: every probe, native binary check, ByteTrack and RTMDet check, and B6 record.

It is amended for the **S1 qualification-harness suite** (`task10:s1-qualification-harness`), which B2 cites. That suite may run in a separate job on the same head, variant, Python build and platform, in an environment that is a verified subset of the candidate environment. The final gate enforces the subset; it is not merely asserted.

- **Rationale.** The harness tests measurement tooling and the native tracker stack. They import none of the runtime graph that the complete-environment rule protects, as the audit above shows. Running them in the full environment added 5–6 min to the critical path on Windows and proved nothing additional.
- **Trade-off accepted.** The harness no longer shares a single interpreter process tree with PyTorch and the MM stack. A process-level interaction between them (for example, a shared native library loaded by both) would not be observed by the harness suite. Two things bound this risk:
  - such interactions are what the full-graph steps (`bytetrack-runtime`, `real-clip-harness`, `production-processor-runtime`) exercise, in the complete environment;
  - `compare` refuses any version divergence between the two environments.

## MMCV wheel reuse: trust model

- **Key.** The key is `task10-mmcv-wheel-v1-<variant>-<sha256 of the canonical identity>`. Restore uses that exact key. There are no `restore-keys`, so no prefix fallback ever restores a wheel built for a different identity.
  - `ImageOS`, such as `win25` or `ubuntu24`, is part of the key.
  - The runner image *version* is recorded in the provenance but is not part of the key. Two things stand behind that choice:
    - every input the image version could change that matters for a compile is already in the key: MSVC tools, SDK, `cl`, `c++` and libc;
    - the installed binary is probed in every run anyway.
- **On restore:**
  - `verify` exit 0 means the wheel is reused;
  - exit 3 (unverifiable: provenance missing, unreadable, of an unknown schema, or not exactly one wheel) means the entry is discarded and MMCV is rebuilt;
  - exit 2 or any other failure (integrity: identity mismatch, identity-hash mismatch, wheel name, hash or size mismatch, wrong distribution or tag, RECORD inconsistency) fails the job. It never falls back to a rebuild.
  
  The install step verifies again immediately before `pip install`.
- **Who can write entries other runs trust.** GitHub Actions scopes caches by ref:
  - a `pull_request` run can save entries that only that same PR's later runs can restore;
  - entries on the default branch are readable by every branch and PR, but only `push` runs on `main` write them.
  
  So an untrusted PR cannot publish a wheel that another PR or `main` later restores. A PR can only poison its own later runs, and those still pass `verify`, the native probes and real RTMDet.
- **Save.** The wheel is saved only when this run built it, after provenance is recorded. A reused entry is never re-saved.

## Measured results

Measured results come from GitHub Actions runs on this PR's heads and are recorded in the PR description. Expectations stated before measuring are labelled as estimates there.

## Unresolved questions

1. **Transitive version divergence between the two jobs.** Each job resolves its unpinned and range-pinned packages independently (`pytest`, `psutil`, `pydantic`…). A release published between the two installs would make `compare` fail. The gate fails closed rather than accepting the divergence. If this recurs, the fix is a shared constraints file, not a relaxed comparison.
2. **Does B2 require the harness and the runtime to share a process environment?** This note says no and amends ADR-005 accordingly. The amendment needs owner acceptance.
3. **Runner-image version in the key.** Excluding `ImageVersion` from the key lets a wheel be reused across weekly image updates that keep the same toolchain. If owners want a rebuild on every image update, adding it to the key is a one-line change. The cost is roughly one cold build per variant per week.
