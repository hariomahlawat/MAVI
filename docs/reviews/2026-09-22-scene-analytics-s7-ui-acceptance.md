# Scene Analytics Slice 7 — operator workflow, accessibility and visual acceptance

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance`
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`

---

## Status: NOT EXECUTED in this pass

Exit-gate item 14 is **not met**. Nothing below is presented as acceptance.

## 1. What this pass did change in the frontend

One defect, fixed test-first: the browser trajectory parser accepted any finite coordinate while the application decoder requires a centre inside `[0, 1]` once rounded to the persisted six decimals (`NormalizedPoint.IsInRange`). A corrupt or hostile artefact could therefore be **drawn** as a position outside the frame while the server refused to derive anything from it — two different answers about the same sealed evidence.

The rule now has one frontend definition, `src/web/mavi-web/src/shared/evidence/normalizedPoint.ts`, mirroring the Domain's rounding (six decimals, banker's rounding) rather than approximating it. The tests fail against the pre-fix parser for the intended reason and include the complements — exactly 0 and exactly 1 remain valid, and a value that only *rounds* into range is accepted, so the check cannot pass by rejecting the frame's legitimate edges.

**Frontend suite: 821 tests pass; typecheck clean; production build succeeds.**

## 2. What item 14 requires and did not get

| Required | Status |
|---|---|
| Operator workflow acceptance — the full investigative path driven end to end against a real API | **NOT EXECUTED.** Requires a running stack; the existing per-surface tests cover components, not the journey |
| Accessibility acceptance across the analytics surfaces | **NOT EXECUTED in this pass.** The shared accessibility infrastructure and per-surface assertions from UI-2 to UI-5 are in place and green, but no Slice-7 audit was performed |
| Visual QA at 1366 / 1440 / 1920 / 2560 | **NOT EXECUTED in this pass.** The visual QA matrix from the UI slices covers the archetypes and the Slice-6 Analytics Workbench states; it was not re-driven at the four widths for this slice |

## 3. What must be run

1. Re-drive the visual QA matrix at 1366, 1440, 1920 and 2560, including the Analytics Workbench in both modes, the incomplete-coverage state and the refused-scope state.
2. Audit keyboard reachability and screen-reader semantics on the Analytics Workbench, the Investigation analytics rail and the Evidence Player's analytics lanes.
3. Drive the operator journey — import, process, configure scene, analyse, search, aggregate, inspect evidence — against a real API on the Development machine, and record where it breaks or misleads.

Until then item 14 stays **NOT EXECUTED**, and no claim of UI acceptance is made anywhere in this repository.
