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
- On Linux without PyTorch installed, the harness collected 720 tests: 719 passed and 1 was skipped. The skip is `test_windows_probe_reads_commit_charge`, which is approved on the Linux variant. `task10_environment.py check-harness` accepts it.
- Only Linux was audited locally. The Windows harness without PyTorch is proven by CI on this change.

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
   - it was compiled in an earlier Task 10 run whose build identity is **byte-identical** to this job's. That run must be one that GitHub itself attests as trusted (see "Trust model"). The wheel's hash, size, distribution, tag and RECORD consistency are verified before install, and the producer's own uploaded record must name the same wheel hash.

   The provenance and the attestation are retained as `mmcv-wheel.json`. The final gate checks that record (`check-mmcv`):
   - it is this head's, this variant's and this run's;
   - a built wheel was built in this run, from this head;
   - a reused wheel carries a default-branch or same-head attestation of its producer.
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
- the build tools (`setuptools`, `wheel`, `ninja`, `pip`);
- the compiler environment (`CC`, `CXX`, `CFLAGS`, `CXXFLAGS`, `CPPFLAGS`, `LDFLAGS`, `DISTUTILS_USE_SDK`, `MSSdk`, the CUDA variables, every `MMCV_*` variable);
- the platform;
- the runner image;
- the MSVC, SDK or C++ toolchain;
- the cache tool and the wheel verifier it uses.

`MAX_JOBS` is deliberately not in the key: it changes build parallelism, not the output.

### What Task 12 proves, unchanged

Task 12 compiles MMCV from source **twice**, independently, with deterministic flags and `MAX_JOBS=1`. It then compares the two wheels byte for byte (`compare_wheel_reproducibility.py`).

Task 12 never restores Task 10's cache. It shares no cache key with Task 10. This change does not touch it.

### How split-job evidence keeps its identity

Both jobs check out `github.event.pull_request.head.sha || github.sha` and fail unless `git rev-parse HEAD` equals that SHA. The harness installs exactly `tools/vision/task10-s1-harness-requirements.txt`; every line of it is also a candidate install pin. Each job writes a `mavi-task10-environment-v1` record containing:

- the head SHA and runtime variant;
- the Python version, implementation, build and compiler;
- the platform, `sysconfig` platform and runner image (`ImageOS`);
- every installed distribution with its version;
- for the harness, the **dependency closure** of its requirements file, computed from the installed distributions' own declared requirements and markers.

The final job, `task10-qualification`, runs with `if: always()` and needs both jobs. It fails unless:

- both `cpu-candidate` and `s1-harness` concluded `success`, so a failed, cancelled or skipped job fails the gate;
- for each variant, the harness JUnit exists. Every suite in it must be named after the variant, it must contain at least one test, and it must have no failure or error. Every skip must be one that `s1_evidence.is_approved_skip("task10:s1-qualification-harness", …)` approves;
- `compare` passes for each variant:
  - the head SHA, variant, Python and platform are identical;
  - every distribution in the harness closure exists in the candidate environment at the same version;
  - the harness has none of `torch`, `torchvision`, `mmcv`, `mmengine` or `mmdet`;
  - the candidate has all of them;
- the candidate's `mmcv-wheel.json` passes `check-mmcv`, and its six other JUnit files are present and non-empty.

No job uses `continue-on-error`.

The S1 checker's contract is unchanged:

- Every JUnit file is still produced by a run of `task10-runtime-qualification.yml` and carries the variant as its suite name.
- The harness's artifact path still ends in `junit/s1-qualification-harness.xml`.
- `_run` requires the **run** to conclude `success`, and the run now succeeds only if the final gate does.

The harness JUnit is retained in a separate artifact, `s1-harness-<os>-py3.12`. The checker binds evidence by run, path, hash and suite name, never by artifact name, so it needs no change.

### Why the closure, not every installed distribution

The first CI run of this change (run 36817371563) failed the gate on Windows: `filelock`, `pipx` and `platformdirs` differed. The two Windows jobs had landed on different runner image versions (`20260828.587` for the candidate, `20260901.588` for the harness). The tool-cache Python on each image preinstalls a different `pipx` together with its dependencies.

None of those three is in the harness closure, so comparing every installed distribution reports a difference in something the harness never runs. The gate now compares the closure. Every installed distribution is still recorded, and the runtime-graph exclusion still applies to all of them.

The same run shows the candidate resolving `torch`'s `filelock` and `yapf`'s `platformdirs` from that preinstalled tool cache. This behaviour predates this change: the qualified candidate graph is partly defined by the runner image. It is recorded here as an unresolved question, not changed.

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
- **Provenance is not trust.** A cache entry, provenance included, is written by whoever saved it. Any run on a ref can save any key in that ref's scope. A pull-request head runs the PR's own workflow, so an earlier, unreviewed head of a PR could patch the source or swap the wheel and record consistent provenance. Inside the entry, nothing can tell those bytes apart from honest ones.
- **Attestation.** On restore, `verify --attest` asks GitHub, not the entry, about the run the provenance names. The run must be all of the following:
  - a run of `task10-runtime-qualification.yml`;
  - in this repository (`repository` and `head_repository`, so not a fork);
  - **either** a `push` or `workflow_dispatch` run on the default branch, which runs reviewed code, **or** a run on exactly the head being qualified, which runs the same code as this run.

  The producer's own `mmcv-wheel.json` is then downloaded from its `runtime-probe-<os>-…` artifact. It must say `state: build`, name the same variant, its own head, and the same identity hash and wheel SHA-256.
  - An unknown, untrusted or unreachable producer, or a missing record, makes the entry **unverifiable**, so MMCV is rebuilt.
  - A trusted producer whose record disagrees is an **integrity violation**, so the job fails.

  The token is sent to the API only and is never forwarded on the artifact download redirect.
- **Pull-request runs never save.** A PR-scope entry would shadow `main`'s entry under the same key, and later heads could not trust it, so a PR save could only ever force rebuilds. PR runs therefore reuse only default-branch entries, and are cold otherwise.
- **Who writes entries that other refs read.** Only runs on the default branch: `push`, or `workflow_dispatch` on `main`. PRs into `feature/task-10-rtmdet-bytetrack` can also read that branch's scope, but the attestation trusts only default-branch producers or the same head.
- **Save.** The wheel is saved only when this run built it, after provenance is recorded, and never on `pull_request`. A reused entry is never re-saved.
- **Qualifying evidence.** S1 evidence is measured on a `main` SHA. Those push runs can read only `main`-scope entries, which only `main` writes.

## Branch protection

The required status check for Task 10 should be **Task 10 qualification**, the gate job, not the `CPU …` or `S1 harness …` matrix jobs. Otherwise a red harness job would not block a merge. This is a repository setting outside this change.

## Measured results

Measured results come from GitHub Actions runs on this PR's heads and are recorded in the PR description. Expectations stated before measuring are labelled as estimates there.

Because PR runs never save, a PR run is cold until `main` holds an entry for its identity. To measure warm reuse before merge, this change runs `workflow_dispatch` twice on its branch at the same head. The first run builds and saves in the branch scope; the second restores the entry, and the same-head attestation lets it reuse the wheel.

## Unresolved questions

1. **Transitive version divergence between the two jobs.** Each job resolves its unpinned and range-pinned packages independently (`pytest`, `psutil`, `pydantic`…). A release published between the two installs, or a preinstalled tool-cache version that lands inside the closure, would make `compare` fail. The gate fails closed rather than accepting the divergence. If this recurs, the fix is a shared constraints file, not a relaxed comparison.
2. **Does B2 require the harness and the runtime to share a process environment?** This note says no and amends ADR-005 accordingly. The amendment needs owner acceptance.
3. **Runner-image migrations.** Both jobs use `windows-latest`/`ubuntu-latest`, and `compare` checks `ImageOS`. During a gradual GitHub image migration, the two jobs of one variant can land on different images and fail with `platform_differs`. That fails closed. Pinning `windows-2025`/`ubuntu-24.04` would remove the risk, but it changes the matrix names and the artifact names they feed; it is left for owners to decide.
4. **Runner-image preinstalled packages in the candidate graph.** The candidate takes `filelock` (from `torch`) and `platformdirs` (from `yapf`) from the image's preinstalled tool cache rather than from a pin. This is a pre-existing gap in the "exact hashed locks" goal of ADR-005 §17. It concerns the candidate graph, not this change.
5. **Runner-image version in the key.** Excluding `ImageVersion` from the key lets a wheel be reused across weekly image updates that keep the same toolchain. If owners want a rebuild on every image update, adding it to the key is a one-line change. The cost is roughly one cold build per variant per week.
