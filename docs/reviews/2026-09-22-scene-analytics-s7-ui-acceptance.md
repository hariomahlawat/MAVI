# Scene Analytics Slice 7 — operator workflow, accessibility and visual acceptance

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance` (PR #70), with PR #71 integrated by fast-forward
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`
**Tooling:** `tools/web-visual-qa/` (the §26 harness; no dependency added), run against the production bundle in Chromium

---

## Status: PASS — accessibility and visual QA PASS at all four widths; the operator workflow, including Search → Investigation, executed on real data

| Plan §25 item 13 part | Status |
|---|---|
| Accessibility acceptance across the analytics surfaces | **PASS** — automated §26 assertions plus a human capture pass; no P1/P2 (§3) |
| Visual QA at 1366×768 / 1440 / 1920 / 2560 | **PASS** — 53 analytics-related states at all four widths, 212 combinations, zero automated findings (§3) |
| Operator workflow acceptance on real data | **PASS** — executed end to end on the Development machine. The **Search → Investigation → Evidence Review** leg (runbook `docs/runbooks/scene-analytics-stage1-development-acceptance.md` §E) was run on the H.264 MOT17-CROWD run; the result is recorded in the Stage-1 acceptance register, action E |

Item 13 is therefore **PASS**.

## 1. What this slice changed in the frontend

One defect, fixed test-first: the browser trajectory parser accepted any finite coordinate while the application decoder requires a centre inside `[0, 1]` once rounded to the persisted six decimals (`NormalizedPoint.IsInRange`). The rule now has one frontend definition, `src/web/mavi-web/src/shared/evidence/normalizedPoint.ts`, mirroring the Domain's rounding. Later passes added:
- the C1 operator-contract test (`c1OperatorContract.test.tsx`);
- two visual-QA states;
- three browser production changes: a 10 s bound on local GET/HEAD reads, including trajectory artefacts, in `api/client.ts`; TanStack Query `networkMode: 'always'` in `app/queryClient.ts`, so a browser that reports itself offline does not pause loopback requests; and `position: relative` on the Ledger/Investigation scroll owners in `styles/workspace.css`, so visually hidden text no longer extends the page scroll.

The read bound came from a disconnected cold start in which Camera Scene stayed on *Loading scene…* indefinitely. A read that gets no response now becomes a recoverable failure with Retry, after one automatic retry. See the Stage-1 register, *Offline observations and the bounded-read fix*.

## 2. The matrix

Every state below ran at **1366×768, 1440×900, 1920×1080 and 2560×1080**.

| Representative state the plan names | Harness states |
|---|---|
| Analysed / complete | `analytics-activity`, `analytics-occupancy`, `analytics-line-crossings`, `review`, `review-zone-visit`, `review-crossing-atob`, `review-crossing-btoa`, `review-dwell-stationary`, `search-analytics-complete`, `processing-detail-analytics-ready` |
| Complete-zero (an observation, drawn as one) | `analytics-complete-zero` |
| Incomplete / pending | `analytics-incomplete`, `review-analytics-pending`, `search-analytics` |
| Stale | `review-analytics-stale`, `processing-detail-analytics-stale` |
| Failed | `processing-detail-analytics-failed` |
| Disabled / not configured | `analytics-no-scene`, `search-analytics-not-analysed` |
| Corrupt / unavailable evidence | `analytics-heatmap-evidence-unreadable`, `review-analytics-unavailable`, `review-geometry-unavailable`, `search-analytics-scene-unavailable`, `analytics-unavailable` |
| Refused scope | `analytics-heatmap-too-large` |
| Dense heatmap | `analytics-heatmap` (665 lit cells, 11,032 samples, 184 Tracks) |
| Sparse heatmap | **`analytics-heatmap-sparse`** — added: three lit cells, 11 samples, one Track |
| Historical revision | **`review-historical-revision`** — added: the detail pinned to revision 3 by a historical search's link while revision 4 is active |
| Dense evidence / overflow | `review-dense-markers`, `review-overflow-*`, `review-markers-same-offset`, `review-overlap-*` |
| Footage conditions | `review-bright`, `-dark`, `-saturated`, `-lowcontrast`, `-letterbox`, `-pillarbox`, `review-direction-letterbox`, `-pillarbox` |

## 3. What was checked, and what it found

**Automated, per state and width** (see `tools/web-visual-qa/README.md`): no horizontal page overflow; no uncaught page error; no overlapping interactive controls, clipped by every scrolling ancestor first; every `var()` resolves; each state reached the condition it claims (`expectText` / `forbidText`); exactly one Context Bar; archetype conformance — for the Workbench, stage ≥ 65% of working width, inspector 300–360 px, no page scroll at or above 1150 px, and only the inspector body owns scroll; for Review and Investigation, their own scroll-ownership rules; and **focus visibility on every focusable control**, by focusing each one.

**Result:** 212 state/viewport combinations, **zero automated findings**. Focus: 5,760 controls discovered, 5,540 checked, 220 skipped for a named reason (92 disabled, 40 that refuse focus, 88 zero-sized), with the accounting required to add up. All figures are from one single run of the whole analytics matrix at this head.

**The two new states.** `review-historical-revision` must show *Scene revision 3* and must **not** show revision 4's identity in the explanation; it does, and it names revision 4 under *Also analysed* — the historical facts are never presented under the current revision's name. `analytics-heatmap-sparse` must state *11 samples from 1 Track* and *The busiest cell holds 7 samples*; it does, with numeric legend ends, so a relative ramp over a handful of samples still reads as counts.

**Human pass over the captures** (§26 requires it), including the historical, sparse, dense and stale states at 1366 and 2560: stale is stated in words (*measured against an earlier revision or engine … not recomputed*), not by colour; the refusal and unreadable-evidence states draw no partial map; coverage is always textual; the summary beside the heatmap is the accessible equivalent of the matrix, which is correctly hidden from assistive technology rather than enumerated cell by cell.

**Screen-reader semantics** were checked as structure and accessible names — landmarks, the named `Scene analytics` and `Heatmap summary` regions, labelled controls — by the harness and the component suites. No assistive-technology product was run, and none is claimed.

### Findings

**P1: none. P2: none.** Three P3s, recorded for the backlog and not fixed in a hardening slice:

- **P3** — in the heatmap inspector's *Density map* panel, the definition paragraph sits directly under the key-value list with no separating space.
- **P3** — the lowest density step is close to the neutral matte, so a single-sample cell in a sparse map is hard to see. The numeric legend and the accessible summary carry the count; the step values themselves are held by `contrast.test.ts` under UI-spec decision 2c.
- **P3 (harness, not product)** — the heatmap fixture's served window differs from the window the controls show, because the fixture is fixed while the controls default to "now". It does not affect any assertion; noted so a reviewer reading a capture is not misled.

## 4. What remains

Nothing for item 13. The three P3s above stay on the backlog.
