# Engineering decision: S1 checker case-identity repair after the M2 qualification

- **Date:** 2026-09-26
- **Scope:** qualification tooling only: `tools/qualification/s1_evidence.py` and its tests and fixtures.
- **Decision:** repair the two defects below. The repair requires a new measured qualification SHA. M2 is not qualified, and nothing here claims it is.

## Why M2 closure was impossible

The authoritative S1.4 campaign ran at M2 (`2853502136586fd2187f41679274cb4951258b8d`).
- Product-side results on Linux:
  - **Passed:** B1, B2, B3-A, B3-B and the crash matrix.
  - **Blocked:** the Windows halves, because no qualified Windows host was available.
- B4 and B6 passed.
- Packaging the evidence exposed two defects in the frozen M2 checker. Either one stops B3 from ever passing at M2, whatever the hosts:

1. **Duplicate xUnit display names.**
   - xUnit truncates long theory arguments (`···`), so distinct test cases can share one TRX display name.
   - Example: in the exact-M2 Quality Gate TRX (run 36209123413), two cases of `WorkerContractV3Tests.V3MembersRejectUnknownNamesAndFractionalIntegers` share a name. Their `testId`s are `bd241a78-…` and `f8c7ea38-…`, and the suite had 21 passes and 0 failures.
   - The same TRX holds four such groups, with 16 executions in total.
   - `suite_counts_from_junit` listed the shared name twice. The schema requires unique `passedTests`, and a suite entry must equal the retained TRX exactly.
   - So the required B3 suite had no valid entry, and neither did its proving test `WorstShapeBodyFitsUnderLimit`.
2. **.NET theory names.**
   - `test_function_name` stripped pytest `[params]` but not xUnit `(args)`.
   - So the passing theory cases of crash.17's proving tests could never match their function (4 of 4 cases passed for each):
     - `VisionFinalizationDomainTests::MalformedClaimIsNotClaimableNotExhaustibleNotOwned`;
     - `VisionFinalizationLifecycleTests::MalformedClaimIsNeverClaimedOrExhaustedAndIsReportedOnce`.

Under the frozen M2 qualification there is no post-M2 repair authority: a checker change that a qualification needs is an engineering decision, not a packaging fix. The M2 evidence package is kept as it was measured and is not edited.

## The repair

- **Case identity.** A TRX display name that more than one result of the same class shares gets that result's own `testId` appended: `Name(…) [testId=…]`.
  - The `testId` is VSTest's stable hash of the full test case, not a per-run value. 728 of the 731 test names present in both the `bb331c6` and M2 Integration runs kept identical `testId`s (compared as sets per name). The three that differ are cases of `StagingJanitorTests.TerminalJobAttemptIsRemovedAfterGraceNotBefore`, whose underlying test changed between the runs. No execution id is shared between the runs.
  - Names that are not shared keep their exact historical form.
  - Counts are unchanged, and every execution stays a distinct entry.
  - A result that repeats both name and `testId` still yields a duplicate, which the schema refuses. That case fails closed.
- **Function identity.** A case maps to its test function by the leading identifier of its member name, after the first `::`. That covers pytest `[params]`, xUnit `(args)` (including arguments that contain `[`, `(` or `::`) and disambiguated names. A longer name that merely starts with the function's name does not match.
- **Stricter proving rule.** A proving test is proven only when every one of its cases passed:
  - at least one case passed;
  - no case was skipped;
  - the suite result has no failed or errored case. Suite results don't name their failures, so this condition is suite-wide.
- **Unchanged:** thresholds, criteria, units and the schema. JUnit parsing is unchanged.

## Proof

- **Real fixtures.** Two pruned, verbatim fixtures come from the exact-M2 TRX:
  - `tools/qualification/tests/fixtures/m2-quality-gate-integration-theories.trx`, from source file SHA-256 `df79556a…83cb8`;
  - `…/m2-quality-gate-domain-theories.trx`, from `fb96a617…d4191`.
  - Only unrelated results and the run's console log were removed.
- **New tests:** they fail on the M2 checker and pass on the repair.
- **Mutations:** these are caught by the tests:
  - reverting `(args)` normalization;
  - collapsing duplicates by display name;
  - dropping one duplicate;
  - hiding a failed duplicate;
  - accepting a missing theory;
  - accepting a failing or skipped theory case;
  - breaking pytest `[params]` normalization;
  - a position-based disambiguator;
  - prefix matching.
- **End-to-end on the unmodified historical M2 record** plus the `WorkerContractV3Tests` entry:
  - the M2 checker reports `schema_invalid`;
  - the repaired checker reports 0 findings;
  - B3's remaining items become only the Windows halves and the two worst-shape body-byte values that no retained output emits.

## Consequence for qualification

- **The checker is part of the measured code.** It is covered by the §2.2 invalidation surface and the Task-10 `s1-qualification-harness` step. So the merge commit of this repair must become the new measured SHA, M3.
- **Every unit must be re-measured at M3.** No M2 unit, B4 and B6 included, carries forward.
- **Still required before S1.4 can close:**
  - the Windows host;
  - the authorized B5 path;
  - the disconnected prerequisites.
