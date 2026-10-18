# CI checks and merge gates

This note is for maintainers. It says which GitHub Actions checks gate a pull request into `main`, why only the aggregate checks are required, and how to read a run when a check is red or missing.

## Aggregate checks

Each gating workflow (Quality Gate, Task 10 and Qualification Tooling Windows) ends in one aggregate job. That job fails unless every lane it depends on succeeded. Other workflows, such as Task 12, Task 14 and Task 17, have no aggregate job and are not required checks. Require the aggregate, never the individual lanes: the lanes are matrix shards whose names and number change when CI is rebalanced.

| Check (job name) | Workflow | Runs on | Required for `main` |
|---|---|---|---|
| `quality` | `quality-gate.yml` | every pull request into `main` | yes |
| `Task 10 qualification` | `task10-runtime-qualification.yml` | every pull request into `main`; reports *not applicable* when Task 10 does not apply | yes |
| `qualification tooling windows` | `qualification-tooling-windows.yml` | only pull requests touching its path filter | no (see below) |

### `quality`

The workflow runs on every pull request so that `quality` always reports. Its first job, `quality scope`, reads the pull request's merge diff (`git diff --no-renames HEAD^1 HEAD` on the merge commit, both paths of a rename) and classifies every changed path with `tools/ci/quality_scope.py` against `tools/ci/quality-scope.json`. Each expensive lane then runs only if its scope output is not `false`; `repo contracts` always runs; a push to a gated branch runs every lane.

| Lane (jobs) | Scope output | Runs when a changed path matches |
|---|---|---|
| `repo contracts` | — (always) | every change: `tools/verify_repo.py` over the whole repository (documents, configuration, workflows and code), plus the scope classifier's own tests |
| `tooling tests` | `tooling` | `tools/phase1`, `tools/stage3`, `tools/benchmarks`, `tools/fixture`, `tools/requirements.txt`, `src/vision`, `contracts`, `tests/fixtures`, `config`, `models`, `sample-data`, `vendor`, `docs/qualification` |
| `dotnet shard 0–2` | `dotnet` | `src/platform`, `tests`, `MAVI.sln`, `Directory.Build.props`, `global.json`, `src/vision`, `contracts`, `config`, `database`, `tools/qualification`, `tools/stage3`, `tools/vision`, `docs/qualification` |
| `python vision` | `vision` | `src/vision`, `contracts`, `tools/requirements.txt`, `tools/verify_repo.py`, `tools/vision`, `tests/fixtures`, `config`, `models`, `sample-data`, every workflow, `docs/qualification` and the three documents its tests read |
| `guard coverage shard 0–3` | `guard` | `src/vision`, `tools/vision`, `tools/requirements.txt` |
| `qualification shard 0–3` | `qualification` | `tools/qualification`, `tools/requirements.txt`, `src/vision`, `contracts`, `tests`, `config`, `models`, every workflow, `docs/qualification` |
| `web and production host` | `web` | `src/web`, `src/platform`, `Directory.Build.props`, `global.json`, `config` |
| `visual harness unit / e2e-0/3 … e2e-2/3`, `visual sweep shard 0–3`, `visual aggregate`, `keyboard journeys shard 0–2`, `keyboard journeys aggregate`, `performance long tasks`, `performance reverse shard 0–3`, `performance budgets` | `visual` | `src/web`, `tools/web-visual-qa` |

The rules of the classifier, in order: a path in `always` (`.github/workflows/quality-gate.yml`, `tools/ci/**`) runs every lane; a path matching a lane's globs runs that lane; a path matching only an `inert` glob (`docs/**` outside the lane triggers above, Markdown, `.claude/**`, Git and editor metadata, the pull-request template) runs none; **a path matching nothing runs every lane**, as does an empty change list, an unreadable list or any error in the tool. Any doubt answers "run". A documentation-only pull request therefore runs `quality scope`, `repo contracts` and `quality` — about three minutes — and nothing else.

`quality` then accounts for every lane: the scope job must have succeeded; `repo contracts` must have succeeded; every other lane must be `success` where its scope output made it applicable and `skipped` where the output is `false`. A lane that failed, was cancelled, or is missing although applicable fails the gate; so does a lane that ran although the scope said it need not (a workflow defect). The TRX-per-project and web-JUnit checks apply when the `dotnet` and `web` lanes applied.

The visual-QA lane is three jobs in parallel: the harness's own tests in four groups (`unit`, and the end-to-end runs of `run.mjs` — the T3 zoom negatives, the X1 text-spacing lane and the X4 reduced-motion lane among them — in three groups, each test in exactly one), the full sweep in four deterministic shards (`run.mjs --shard i/4`: a state and its loading-pair partner in one shard; since S6/X1 and S6/X4 the plan holds every state's anchor, probe, 200% zoom, text-spacing and reduced-motion cases, about 3,750 in all), and `visual aggregate`, which runs only when every shard succeeded and proves the sweep whole: same head, manifest and plan in every shard, every planned case run exactly once, reached and valid, no harness error, the sweep-wide checks (every operator surface judged at 200%, no blocking rule unevaluated, overlay restoration at Tier A, pressed treatments proven, loading Ledgers against their tables) and no blocking finding (`tools/web-visual-qa/aggregate.mjs`; the harness README, "Sharding (CI)"). The shards' captures are retained per shard (`visual-qa-captures-shard-i`), the aggregate as `visual-qa-captures`.

Beside them, since S6/X2, the keyboard journeys: the six frozen operator journeys of plan §5.3, and after them the Stage 4 PR-5 plate journey (plate search → inspect → seek), driven keyboard-only at 1366×768, 1024×768 and 768×1024 (21 executions) in three deterministic shards (`tools/web-visual-qa/journeys.mjs --shard i/3`), and `keyboard journeys aggregate`, which runs once every shard succeeded and proves them whole: every shard at the head, the registry's whole plan, each execution exactly once, none at Tier C, every pass carrying its evidence, no harness error (the harness README, "X2"). Each shard's step evidence is retained as `keyboard-journey-results-i`, the aggregate as `keyboard-journeys`.

Tests hold the graph together: `src/vision/tests/test_runtime_metadata.py` (every sharded matrix covers each index exactly once; `quality` depends on every job, requires each conditional lane by the same scope output that gates it, and nothing is `continue-on-error`; pull-request runs are cancelled by a newer head, pushes never), `tools/ci/tests/test_quality_scope.py` (the classifier: documents skip, web changes run web and visual, the workflow runs everything, renames count both paths, unknown paths run everything), `tools/qualification/tests/test_s1_evidence.py` (the retained evidence artifacts) and `tools/verify_repo.py` (the scope list, the scope job's outputs and `quality`'s requirements name the same lanes).

#### Concurrency

A pull request's runs share one concurrency group (its ref): a newer head cancels the run in progress. A push to `main` or another gated branch gets a group of its own (the run id), so it is neither cancelled by nor queued behind another push — GitHub otherwise keeps at most one running and one pending run per group, and a third push would cancel the pending one. Merging pull requests one after another therefore no longer loses the push run for an earlier merge commit. Unrelated pull requests have different refs and never cancel each other.

### `Task 10 qualification`

The `Task 10 scope` job runs first, on the pull request's merge commit. It compares the changed paths against `tools/vision/task10-scope-paths.txt` using `tools/vision/task10_scope.py`.

- **`applicable=false`:** the CPU candidate and S1 harness jobs are skipped. The gate then passes only if the scope job succeeded and both of those jobs were skipped.
- **`applicable=true`:** the gate requires every Task 10 job to succeed and all retained evidence to verify.

Any doubt in the scope decision answers *applicable*. The decision note `docs/qualification/stage2-s1/2026-10-01-task10-harness-separation-and-mmcv-wheel-reuse.md` records the full contract.

### `qualification tooling windows`

This workflow still uses a path filter on `pull_request`. It does not start at all for a pull request outside that filter, so requiring it would leave unrelated pull requests waiting for a check that never reports.

When it does run, treat a red or missing result as a merge blocker in review.

### Informational workflows (not gates)

`plate-search-scale-informational.yml` (job `plate search at scale (informational CI diagnostic, not a gate)`, Stage 4 PR-4) seeds the frozen 10^6-Track plate corpus on CI PostgreSQL and runs `PlateSearchScaleMeasurementTests` in mode `ci`: the plan shape of the real statements and a catastrophic bound (3 000 ms) that only a change of complexity class would exceed. It is not a Quality Gate lane, not in `quality.needs` and not a required check, and its result never blocks a merge. Its checkout is verified against the exact pull request head, and its output (artifact `plate-search-scale-informational-ci-diagnostic`, files `plate-search-scale-ci-diagnostic*`, outside `qualification-evidence/`) states `qualificationEvidence: false` and carries no budget. It is **not** qualification evidence and not Development evidence: the plan §2.8 budget of 300 ms is judged on the pinned Development host only (`docs/qualification/stage4/2026-10-13-plate-search-at-scale.md`). Only the budgeted query set (v1) is failed on plan shape; the diagnostic set v2 (declared limits, owner decision 2026-10-16) is reported per query and fails only on the catastrophic bound. A red run is a prompt to read the plans, not a merge gate. `src/vision/tests/test_runtime_metadata.py` (`test_the_plate_search_scale_workflow_is_informational_and_outside_the_quality_gate`) binds these properties.

## Reading a run

### A required check shows "Expected — waiting for status"

The workflow did not run for the pull request's current head. The usual causes:

- **A skip marker on the head commit.** The markers are `[skip ci]`, `[ci skip]`, `[no ci]`, `[skip actions]`, `[actions skip]`, and a `skip-checks: true` trailer. There is no run to re-run. Push a new commit without the marker, for example `git commit --allow-empty -m "ci: run checks"`. A merge or squash message containing a marker also skips the push run on `main`.
- **Merge conflicts.** `pull_request` workflows do not run while the pull request cannot be merged. Resolve the conflict and push.
- **A first-time contributor's fork.** Its runs wait for a maintainer to approve them.
- **A retargeted base.** A pull request moved onto `main` without a new push has not triggered the workflows. Push a commit, or close and reopen the pull request.

### Other symptoms

- **`Task 10 qualification` failed after `Task 10 scope` said `applicable=false`.** One of the heavy jobs was not skipped. This is a workflow defect, not a flaky run.
- **A qualification shard failed.** Open that shard's log. Each qualification shard prints `shard i/n runs k of N collected tests`, and the `k` values across the shards sum to `N`.
- **Do not re-run a lane in place of reading it.** A second failure on the same head is a real failure.
- **Merging pull requests one after another.** Quality Gate cancels an in-progress run only for a pull request's own ref; a push run on `main` is never cancelled, so each merge commit keeps its run. Still check that the latest `main` run completed.
- **A lane shows "not applicable (skipped)" in `quality`'s log.** The scope job decided the change could not reach it. If you believe it should have run, the scope list (`tools/ci/quality-scope.json`) is missing a path: add it with a test in `tools/ci/tests/test_quality_scope.py`. A path the list does not know runs every lane, so an omission can only make CI slower, never skip a lane a known path reaches.
- **`visual aggregate` was skipped and `quality` failed on `visual-sweep`.** A sweep shard failed; open that shard's log and its `visual-qa-captures-shard-i` artifact. The aggregate runs only once every shard has succeeded.
- **`performance reverse shard i` failed.** The reverse-order lane (X3 determinism: the sweep's ordinary cases with data responses answered in reverse order) hit a harness fault; its visual findings never fail it (`--keep`). Its CLS is judged in `performance budgets`, which also fails when a reverse shard's results are missing or of another head.
- **`keyboard journeys shard i` failed.** A journey did not complete by keyboard: the log names the journey, viewport, step and why (a target not reached in its Tab bound, focus lost or invalid, a checkpoint not reached, pointer or scripted input). `keyboard-journey-results-i` holds the steps, the page's text and request log at the failure, and a capture. Reproduce locally with `node tools/web-visual-qa/journeys.mjs --journeys <id> --viewports <WxH>` against a fresh `npm run build`.
- **`keyboard journeys aggregate` failed.** The shards did not agree, an execution ran zero or two times, or a pass lacked its evidence: a workflow or harness defect, not a product finding.
- **`visual aggregate` failed with a harness error naming a shard.** The shards did not agree (head, manifest, plan) or a planned case ran zero or two times: a workflow or harness defect, not a product finding.

## Changing CI

- Changes to `.github/workflows/task10-runtime-qualification.yml`, `tools/vision/task10_scope.py` or `tools/vision/task10-scope-paths.txt` always make Task 10 apply. Changes to the other workflows apply only if they match a path in the scope list.
- **Renaming an aggregate job** renames a required check. A branch rule is not part of a commit, so it cannot change together with the workflow. To rename one:
  1. Temporarily require both the old and the new name.
  2. Merge the rename.
  3. Remove the old name.

  Otherwise pull requests wait for whichever name the rule does not see. `tools/verify_repo.py` requires `quality` and `Task 10 qualification` to each be the name of exactly one workflow job.
