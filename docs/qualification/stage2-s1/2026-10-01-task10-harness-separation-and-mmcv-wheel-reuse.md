# Task 10: S1 harness separation and verified MMCV wheel reuse

- **Date:** 2026-10-01
- **Status:** Proposed; draft PR, not merged. Owner decisions of 2026-10-01:
  - Harness separation and verified wheel reuse are **accepted in principle**.
  - The ADR-005 §17 amendment is **formally accepted only after the implementation review**. Because this branch already runs the amended layout, **it must not merge before that formal acceptance**.
  - **Strict compiler identity stays.** Cache misses caused by runner-image changes are accepted as legitimate.
  - The PyPI cutoff is **drift reduction, not a lock**. The version-comparison gate remains essential.
  - "Task 10 qualification" must block merges when Task 10 applies, without leaving unrelated PRs waiting for a check that never runs (see "Required check").
- **Scope:** how the Task 10 workflow (`task10-runtime-qualification.yml`) is split into jobs, what evidence each job contributes, and when Task 10 may install an MMCV wheel it compiled in an earlier run.
- **Governing documents:**
  - ADR-005 §17, which this note proposes to amend; see "Amendment".
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

## Amendment to ADR-005 §17 (proposed; formal acceptance after implementation review)

ADR-005 §17 says a runtime qualifies only as one complete environment. That rule continues to govern **runtime qualification**: every probe, native binary check, ByteTrack and RTMDet check, and B6 record.

It is amended for the **S1 qualification-harness suite** (`task10:s1-qualification-harness`), which B2 cites. That suite may run in a separate job on the same head, variant, Python build and platform, in an environment that is a verified subset of the candidate environment. The final gate enforces the subset; it is not merely asserted.

- **Rationale.** The harness tests measurement tooling and the native tracker stack. They import none of the runtime graph that the complete-environment rule protects, as the audit above shows. Running them in the full environment added 5–6 min to the critical path on Windows and proved nothing additional.
- **Trade-off accepted.** The harness no longer shares a single interpreter process tree with PyTorch and the MM stack. A process-level interaction between them (for example, a shared native library loaded by both) would not be observed by the harness suite. Two things bound this risk:
  - such interactions are what the full-graph steps (`bytetrack-runtime`, `real-clip-harness`, `production-processor-runtime`) exercise, in the complete environment;
  - `compare` refuses any version divergence between the two environments.

## One PyPI resolution for both jobs

The harness and the candidate install at different times: the candidate installs its shared packages several minutes later on a cold run, and a re-run of failed jobs can be hours later. An unpinned or range-pinned package released in between made the gate fail on run 36819745957: `python-dotenv` 1.2.4 was published between the harness install at 05:26 and the re-run candidate install at 05:41.

Both jobs therefore do two things:
- pin `pip==26.2.1`;
- resolve every PyPI install with `--uploaded-prior-to <the head's committer time>`.

That cutoff is identical in both jobs and across re-runs, so both resolve the same versions whenever they install. Each environment record carries the cutoff, and `compare` requires it to be equal.

**The cutoff reduces drift; it is not a lock.** It does not cover:
- a release yanked between the two installs;
- a package already present in the runner's tool cache, which pip leaves in place when it satisfies the requirement;
- the PyTorch index, which publishes no upload times.

The **version comparison in the final gate remains the control**: it fails closed on any difference inside the harness closure, whatever the cause.

Under the cutoff of `a949a06`, a local dry run resolves the harness requirements completely for Python 3.12 on Linux and Windows (54 distributions, `python-dotenv` 1.2.3), and the candidate's PyPI pins too.

The PyTorch install uses the PyTorch index, which does not publish upload times. It is left without a cutoff; none of the packages it brings in is in the harness closure.

## MMCV wheel reuse: trust model

- **Key.** The key is `task10-mmcv-wheel-v1-<variant>-<sha256 of the canonical identity>-<UTC year and month>`. Restore uses that exact key. There are no `restore-keys`, so no prefix fallback ever restores a wheel built for a different identity.
  - `ImageOS`, such as `win25` or `ubuntu24`, is part of the identity.
  - The runner image *version* is recorded in the provenance but is not part of the identity. Two things stand behind that choice:
    - every input the image version could change that matters for a compile is already in the identity: the MSVC tools, SDK and `cl` banner, `c++` and libc;
    - the installed binary is probed in every run anyway.
  - The PyTorch configuration enters the identity **without** its `CPU capability usage` line. That line describes the runner's CPU, not the PyTorch build. On runs 36819776216 and 36820941092 the same PyTorch wheel reported AVX2 on one Ubuntu runner and AVX512 on the other, which changed the key, so the second run rebuilt.
  - **The month bucket.** An entry's whole life fits well inside the retention of the producer's evidence artifact (90 days by default), so an entry is never unattestable merely because that artifact has expired. An entry that does become unverifiable is replaced the next month instead of blocking reuse for good. The cost is one cold build per variant per month on the default branch.
- **On restore:**
  - `verify` exit 0 means the wheel is reused.
  - Exit 3 means the entry is unverifiable: provenance missing, unreadable or of an unknown schema; not exactly one wheel; an unknown, untrusted or unreachable producer; or a missing producer record. MMCV is rebuilt in this job, and a `::warning::` annotation says so.
  - Exit 2 or any other failure is an integrity violation: identity mismatch, identity-hash mismatch, wheel name, hash or size mismatch, wrong distribution or tag, RECORD inconsistency, or a trusted producer whose records all disagree. The job fails; it never falls back to a rebuild.

  The install step verifies again immediately before `pip install`.
- **Provenance is not trust.** A cache entry, provenance included, is written by whoever saved it. Any run on a ref can save any key in that ref's scope. A pull-request head runs the PR's own workflow, so an earlier, unreviewed head of a PR could patch the source or swap the wheel and record consistent provenance. Inside the entry, nothing can tell those bytes apart from honest ones.
- **Attestation.** On restore, `verify --attest` asks GitHub, not the entry, about the run the provenance names. The run must be all of the following:
  - a run of `task10-runtime-qualification.yml`;
  - in this repository (`repository` and `head_repository`, so not a fork);
  - **either** a `push` or `workflow_dispatch` run whose `head_branch` is the default branch **and** whose head commit GitHub reports as contained in the default branch (`compare/<default>...<sha>` is `behind` or `identical`), so a tag named after the branch does not count; **or** a run on exactly the head being qualified, which runs the same code as this run.

  The producer's `mmcv-wheel.json` records are then downloaded from its `runtime-probe-<os>-…` artifacts. A re-run uploads one artifact per attempt. At least one record must say `state: build`, the same variant, its own head, and the same identity hash and wheel SHA-256.

  The token is sent to the API only, and is never forwarded on the artifact download redirect.
- **Who saves.** A run saves only when it built the wheel, after provenance is recorded, and only on:
  - a `push` to the default branch. These are the entries every ref can read.
  - a `workflow_dispatch`. Its entry stays in its own ref's scope, and only a run on the same head can attest it there. On the default branch it is a default-branch entry like a push's.

  Pull requests, and pushes to other branches such as `feature/task-10-rtmdet-bytetrack`, never save. Their entry would shadow the default branch's under the same key in their scope, and later heads could not attest it, so it could only ever force rebuilds. Those runs reuse default-branch entries and are cold otherwise.
- **Qualifying evidence.** S1 evidence is measured on a `main` SHA. Those push runs can read only `main`-scope entries, which only `main` writes.

## Required check

"Task 10 qualification" must block a merge when Task 10 applies to the pull request. It must not hold up a pull request that Task 10 does not apply to.

A path filter on the workflow's `pull_request` trigger cannot do both. GitHub does not start a path-filtered workflow for an unrelated pull request, so its checks never report, and a required check would stay pending forever.

The workflow therefore runs on **every** pull request into `main` and `feature/task-10-rtmdet-bytetrack`:

1. **`scope` (seconds).** It runs on the pull request's **merge commit** (`github.sha`), the commit GitHub runs the workflow from and used to read the path filter from. Its scope list, its tool and its diff therefore all describe the commit being qualified, including any glob `main` added after the PR branched.
   - It lists the changed paths with `git diff --no-renames --name-only -z HEAD^1 HEAD`. The first parent is the base branch, `--no-renames` lists both paths of a rename, and `-z` keeps unusual file names intact. No API and no file-count limit are involved.
   - It matches them against `tools/vision/task10-scope-paths.txt` with `tools/vision/task10_scope.py`. The list holds the same globs as the `push` trigger, and a test holds the two equal.
   - Only `*` and `**` are supported. The tool refuses a list using any other GitHub glob syntax (`?`, `+`, `[...]`, `{...}`, `!`). On the supported subset its matching is never narrower than GitHub's: `**/` also spans zero directories, and newlines inside paths are matched.
   - Changes to the scope list, the tool or the workflow always apply.
   - Any doubt answers *applies*: the checked-out commit is not `github.sha` or has no second parent, the diff fails, the list is unreadable or uses unsupported syntax, the file list is empty, or any other error occurs.
   - On `push` and `workflow_dispatch` the answer is always *applies*. Push keeps its path filter.
2. **`cpu-candidate` and `s1-harness`** run only when Task 10 applies.
3. **`task10-qualification` always reports:**
   - **Not applicable:** it passes only if `scope` succeeded and said so, *and* both Task 10 jobs were skipped.
   - **Applicable:** it requires `scope`, `cpu-candidate` and `s1-harness` to succeed, plus all the evidence checks.
   - Any other combination fails. A test runs the gate's decision under GitHub's bash flags for every combination of job results.

With this in place, "Task 10 qualification" can be a **required status check for every pull request into `main`**. Making it required is a repository setting outside this change. The `CPU …` and `S1 harness …` matrix checks should not be required: they are skipped on unrelated pull requests, and the gate already depends on them.

The trade-off: every pull request now runs a short `scope` job, and an applicable pull request waits for it, about 10–20 s, before its matrix starts.

**Trust boundary.** A pull request controls the workflow, the tool and the list it runs with, exactly as it controlled its own `paths:` filter before. A hostile edit could make Task 10 report "not applicable". The rule that edits to the scope machinery always apply guards against accidental narrowing only.
- **Difference from before:** a hostile edit used to leave a required check pending; now it can turn green.
- **The control is review.** Add a `CODEOWNERS` entry for `.github/workflows/task10-runtime-qualification.yml`, `tools/vision/task10_scope.py` and `tools/vision/task10-scope-paths.txt`, and require code-owner review. That is a repository change outside this PR.

**Merge queue.** The workflow has no `merge_group` trigger. If the repository enables a merge queue with this check required, the check will not report there until `merge_group` is added.

## Measured results

The measurements come from GitHub Actions runs on this change and are listed in the PR description, which separates measurements from estimates.

Pull-request runs never save, so a PR run is cold until `main` holds an entry for its identity. To measure warm reuse before merge, this change runs `workflow_dispatch` twice on its branch at the same head: the first run builds and saves in the branch scope, and the second restores the entry and, through the same-head attestation, reuses the wheel.

## Unresolved questions

1. **Divergence the cutoff does not cover** (the comparison gate catches it). A release yanked between the two installs, or a runner-image preinstalled package inside the closure, can still make `compare` fail. On Windows that is `colorama`, which `pytest` requires and the tool cache preinstalls. The gate fails closed. A committed constraints file for the closure would close this too, at the cost of maintaining it.
2. **Does B2 require the harness and the runtime to share a process environment?** This note says no and proposes amending ADR-005 accordingly. The owner has accepted it in principle; formal acceptance is pending the implementation review, and this PR must not merge before it.
3. **Runner-image migrations.** Both jobs use `windows-latest`/`ubuntu-latest`, and `compare` checks `ImageOS`. During a gradual GitHub image migration, the two jobs of one variant can land on different images and fail with `platform_differs`. That fails closed. Pinning `windows-2025`/`ubuntu-24.04` would remove the risk, but it changes the matrix names and the artifact names they feed; it is left for owners to decide.
4. **Runner-image preinstalled packages in the candidate graph.** The candidate takes `filelock` (from `torch`) and `platformdirs` (from `yapf`) from the image's preinstalled tool cache rather than from a pin. This is a pre-existing gap in the "exact hashed locks" goal of ADR-005 §17. It concerns the candidate graph, not this change.
5. **Runner-image version in the identity.** *Owner decision: keep strict compiler identity, and accept the cache misses runner-image changes cause.* For example, `cl` 19.51.36257 and 19.51.36260 landed on consecutive Windows runs (36824236111, 36825497153) and forced a legitimate rebuild. Excluding `ImageVersion` lets a wheel be reused across weekly image updates that keep the same toolchain. If owners want a rebuild on every image update, adding it is a one-line change. The cost is roughly one cold build per variant per week.
6. **Repository artifact retention.** The month bucket assumes the repository's artifact retention is at least about 32 days. With a shorter setting, reuse late in a month becomes unverifiable and rebuilds. That fails safe.
