# CI checks and merge gates

This note is for maintainers. It says which GitHub Actions checks gate a pull request into `main`, why only the aggregate checks are required, and how to read a run when a check is red or missing.

## Aggregate checks

Each workflow ends in one aggregate job. That job fails unless every lane it depends on succeeded, and it never uses `continue-on-error`. Require the aggregate, never the individual lanes: the lanes are matrix shards whose names and number change when CI is rebalanced.

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

The shard counts are pinned by tests in `src/vision/tests/test_runtime_metadata.py`. Every shard index must run exactly once, and the aggregate must depend on every lane.

### `Task 10 qualification`

The `Task 10 scope` job runs first, on the pull request's merge commit. It compares the changed paths against `tools/vision/task10-scope-paths.txt` using `tools/vision/task10_scope.py`.

- **`applicable=false`:** the CPU candidate and S1 harness jobs are skipped. The gate then passes only if the scope job succeeded and both of those jobs were skipped.
- **`applicable=true`:** the gate requires every Task 10 job to succeed and all retained evidence to verify.

Any doubt in the scope decision answers *applicable*. The decision note `docs/qualification/stage2-s1/2026-10-01-task10-harness-separation-and-mmcv-wheel-reuse.md` records the full contract.

### `qualification tooling windows`

This workflow still uses a path filter on `pull_request`. It does not start at all for a pull request outside that filter, so requiring it would leave unrelated pull requests waiting for a check that never reports.

When it does run, treat a red or missing result as a merge blocker in review.

## Reading a run

- **A required check shows "Expected — waiting for status".** The workflow did not start for this head. Check that the pull request targets `main`, and that the head commit is not marked to skip CI.
- **`Task 10 qualification` failed after `Task 10 scope` said `applicable=false`.** One of the heavy jobs was not skipped. This is a workflow defect, not a flaky run.
- **A shard failed.** Open that shard's log. Each qualification shard prints `shard i/n runs k of N collected tests`, and the `k` values across the shards sum to `N`.
- **Do not re-run a lane in place of reading it.** A second failure on the same head is a real failure.

## Changing CI

- Changes to `.github/workflows/`, to `tools/vision/task10_scope.py` or to `tools/vision/task10-scope-paths.txt` always make Task 10 apply.
- Renaming an aggregate job renames a required check. Update the branch rules on `main` in the same change, or every pull request will wait on the old name.
