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

The `quality` job aggregates these lanes:

- the .NET test shards;
- the guard-coverage shards (the evidence-assembler mutation catalogue);
- the qualification test shards (`tools/qualification/tests`, split by test);
- Python vision;
- web and production host;
- repository contracts.

Tests in `src/vision/tests/test_runtime_metadata.py` hold three things:
- every sharded job's matrix covers each shard index exactly once for its shard count;
- the `quality` aggregate depends on every lane in `quality-gate.yml`;
- no job in `quality-gate.yml` uses `continue-on-error`.

### `Task 10 qualification`

The `Task 10 scope` job runs first, on the pull request's merge commit. It compares the changed paths against `tools/vision/task10-scope-paths.txt` using `tools/vision/task10_scope.py`.

- **`applicable=false`:** the CPU candidate and S1 harness jobs are skipped. The gate then passes only if the scope job succeeded and both of those jobs were skipped.
- **`applicable=true`:** the gate requires every Task 10 job to succeed and all retained evidence to verify.

Any doubt in the scope decision answers *applicable*. The decision note `docs/qualification/stage2-s1/2026-10-01-task10-harness-separation-and-mmcv-wheel-reuse.md` records the full contract.

### `qualification tooling windows`

This workflow still uses a path filter on `pull_request`. It does not start at all for a pull request outside that filter, so requiring it would leave unrelated pull requests waiting for a check that never reports.

When it does run, treat a red or missing result as a merge blocker in review.

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
- **Merging pull requests one after another.** Quality Gate cancels an in-progress run for the same ref. Rapid successive merges can cancel the push run on `main` for an earlier merge commit, so check that the latest `main` run completed.

## Changing CI

- Changes to `.github/workflows/task10-runtime-qualification.yml`, `tools/vision/task10_scope.py` or `tools/vision/task10-scope-paths.txt` always make Task 10 apply. Changes to the other workflows apply only if they match a path in the scope list.
- **Renaming an aggregate job** renames a required check. A branch rule is not part of a commit, so it cannot change together with the workflow. To rename one:
  1. Temporarily require both the old and the new name.
  2. Merge the rename.
  3. Remove the old name.

  Otherwise pull requests wait for whichever name the rule does not see. `tools/verify_repo.py` requires `quality` and `Task 10 qualification` to each be the name of exactly one workflow job.
