# Decision note: the S1 qualification-harness surface

- **Date:** 2026-10-01
- **Scope:** which files under `tools/qualification/` are S1 behavior-bearing, what Task 10 retains as the S1 qualification harness, and what triggers Task 10.
- **Follows:** PR #126, which narrowed Task 10's trigger from `tools/qualification/**` to the S1 harness files. That left the checker and the trigger inconsistent; this note resolves the inconsistency.

## Decision

The S1.4 plan §2.1 defines the behavior-bearing surface to include "the qualification harnesses used to produce evidence", and test trees only "when used as evidence". Every file under `tools/qualification/` was S1 harness code when the checker was written (2026-09-24). The checker encoded the surface as the broad glob `tools/qualification/*`.

Later-stage tooling has since arrived under the same directory:

- S2a provenance tests (2026-09-27);
- the S2c attribute corpus (2026-09-28);
- model selection (2026-09-29 onward);
- source acquisition (B0).

None of it produces S1 evidence, yet the broad glob made any change to it an unmapped behavior-bearing path, which invalidates **every** S1 unit (`invalidated_units` fallback). Task 10 also ran the whole `tools/qualification/tests` tree as the retained `s1-qualification-harness` suite, and B2 cited that directory. The result: S2c edits invalidated S1 evidence while, after PR #126, no longer triggering Task 10.

The S1 qualification harness is now named explicitly, as `s1_evidence.S1_QUALIFICATION_HARNESS`:

- `tools/qualification/s1_*` and `tools/qualification/s1-*`: the checker, B1 derivation, the B2 memory harness and the evidence schema;
- `tools/qualification/process_memory.py`;
- `tools/qualification/tests/conftest.py`;
- `tools/qualification/tests/fixtures/**`;
- `tools/qualification/tests/test_s1_*`.

This one set governs three things that must agree:

| | Before | After |
|---|---|---|
| S1 behavior-bearing paths under `tools/qualification/` | all of `tools/qualification/*` (and `*.ps1` there) | `S1_QUALIFICATION_HARNESS` only |
| Shared test support in `tools/qualification/tests` | every non-`test_*` file | only the S1 harness's own (`conftest.py`, `fixtures/**`) |
| Task 10 `s1-qualification-harness` step | `pytest tools/qualification/tests` | `pytest tools/qualification/tests/test_s1_*.py` |
| B2's qualification suite | `tools/qualification/tests` (directory) | `test_s1_b1.py`, `test_s1_evidence.py`, `test_s1_memory.py` |
| Task 10 trigger under `tools/qualification/` | the S1 files listed by name (PR #126) | exactly the same globs as `S1_QUALIFICATION_HARNESS` |

The S1 checker, its schema, its harness and its tests remain behavior-bearing. A change to any of them invalidates S1 units exactly as before and triggers exact-head Task 10. A new S1 harness file named by the convention (`s1_*`, `test_s1_*`, a fixture) is covered automatically. A new `test_s1_*` file also fails a test until B2 cites it.

The same change adds `src/vision/tests/test_runtime_errors.py`, which Task 10's `s1-boundary` step already ran, to Task 10's trigger. A test now requires every Task-10 step source to trigger Task 10.

## Trade-off accepted

- **Narrower invalidation.** S2a, S2c, model-selection and source-acquisition changes under `tools/qualification/` no longer invalidate S1 units, and they no longer force the native Task 10 build. This is a deliberate reading of §2.1, not a waiver. The 2026-09-27 closure-identity note requires such a change to be "deliberately redesigned and reviewed", and this note is that record.
- **Evidence scope.** The retained `s1-qualification-harness` JUnit now holds the S1 harness tests only. It is not the whole qualification test tree. B2's suites name those files.
- **No retroactive effect.** No S1 unit has a committed PASS record (S1 remains OPEN), so no retained evidence changes meaning.
- **Other coverage.** Later-stage qualification tooling is covered by:
  - the Quality Gate on Linux;
  - the Qualification Tooling Windows workflow, for Windows portability only. It is not S1 evidence: the checker refuses a suite result from that workflow.

## Unchanged

- Every other behavior-bearing surface, the invalidation map, the "unmapped behavior-bearing path invalidates every unit" fallback, and the measured-SHA and closure rules.
- S1.4's own measurement procedure. Task 10 is still run explicitly at the frozen head (§10.1).
