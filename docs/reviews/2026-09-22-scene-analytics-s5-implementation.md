# Scene Analytics Slice 5 — implementation review

**Branch:** `feature/scene-analytics-s5-evidence-explanation`.
**Implementation base:** `main@d6393532b0456ccf1fe2e24261b963ae7fab35ef` (PR #65, the Slice-5 plan merge; no commits on `main` between that and branching).
**Plan:** `docs/superpowers/plans/2026-09-22-scene-analytics-s5-evidence-explanation.md`.
**Pre-implementation review:** `docs/reviews/2026-09-22-scene-analytics-s5-plan-review.md`.

Written after implementation and before external review, as the record of what was built, what was decided where the plan left room, and what an independent cold pass found.

---

## 1. What the slice does

Persisted Scene Analytics facts become checkable against the source video on the one Evidence Player:

- zones and trip lines of the **exact pinned revision** are drawn through the existing projection path;
- every persisted line crossing is drawn at the point the engine recorded;
- zone visits and stationary intervals become bands on the one timeline, in fixed analytical lane families;
- real zone boundary crossings and line crossings become markers that seek to their own persisted millisecond;
- one explanation component states the facts and the identity they were measured against, in Review and in the Investigation inspector.

No backend change. No new dependency. No second player, clock, scrubber or timeline.

---

## 2. Decisions taken where the plan left room

### 2.1 Where the packing lives

The plan lists bounded zone packing under "pure evidence-model tests". It is implemented in `shared/evidence/timeline.ts` rather than in the analytics adapter, because packing is a property of *the timeline*, generic over intervals, and not a property of Scene Analytics: any future supplier of interval records gets it. `analyticsEvidence.ts` stays a transform from facts to records and says nothing about rows. Both modules are pure and independently tested.

### 2.2 Who fetches

`TrackEvidence` already received the trajectory as a prop rather than fetching it. The pinned revision follows that convention: the hosts call `useAnalyticsScene`, build the model with `buildAnalyticsEvidence`, and pass it down. The player and the adapter stay free of data fetching, and Review and the inspector demonstrably share one hook, one immutable cache key and one model.

### 2.3 When analytical geometry is drawn

A zone is where it was, for the whole media. The zone, line and crossing layers are therefore drawn whenever their layer is enabled, and `appliesNow` is true for all of them; the crossing's media time is stated in its description rather than implied by a glyph appearing and disappearing. This keeps the UI-5 rule that a layer never says "enabled" and "not drawn here" about something that is in fact on screen.

### 2.4 Overflow is a tick, not a band

An overflowed zone visit is drawn in the fixed overflow rail as a tick at its start offset, not as a band. A band there would paint over whatever already occupies the rail, which is the occlusion the cap exists to prevent. The visit keeps its own list item, its own name, its own offsets and its own position, so the exact persisted interval can still be identified and highlighted; the rail states how many visits it holds.

### 2.5 Names degrade to identifiers, never to another revision

When the pinned revision cannot be loaded, geometry is named by stable id. The Investigation inspector previously had the originating search's geometry names available and initially used them as a fallback; that was removed during the cold review (§5.2).

---

## 3. Decisions closed

### 3.1 UI specification decision 7 — analytical lane presentation

**Bounded stacked analytical lanes.** Three fixed families on the one timeline — subject, zone/dwell, stationary — each at a fixed vertical position, which is itself a non-colour cue. The two analytical families are hatched rather than newly coloured, and differ by hatch orientation as well as position.

A single undifferentiated lane was rejected because zone occupancy and stationary overlap in time and would be ambiguous. One row per zone was rejected because the timeline's height would then grow with the scene.

The zone family packs concurrent visits into at most three sub-rows: sorted by start, then end, then stable evidence id; endpoint-touching intervals may share a row, positive-duration overlaps may not. A fourth concurrent visit goes to the overflow rail. **A hundred overlapping visits render exactly as tall as four**, which is asserted rather than argued.

### 3.2 UI specification decision 2a — crossing evidence token

**`--evidence-crossing` = `#fde047`**, chosen by measurement, not by taste, over the first surface that draws an analytical instant.

Method as UI-1: linear-light sRGB, Viénot dichromat simulation for protan/deutan/tritan, CIEDE2000 in CIE L\*a\*b\*, against every frozen evidence role (`--evidence-box`, `--evidence-track`, `--geo-zone`, `--geo-line`, `--geo-dir-ab`, `--geo-dir-ba`).

| Candidate | Min ΔE00 across all four vision models | Worst pair | On the matte |
|---|---|---|---|
| **`#fde047` yellow-300** | **7.1** | dir-ab / tritan | 15.9:1 |
| `#f87171` red-400 | 7.0 | zone / tritan | 7.6:1 |
| `#a3e635` lime-400 | 6.8 | zone / deutan | 13.9:1 |
| `#fb7185` rose-400 | 6.3 | zone / tritan | 7.8:1 |
| `#4ade80` green-400 | 2.3 | line / tritan | 12.1:1 |
| `#facc15` yellow-400 | 1.9 | zone / deutan | 13.7:1 |
| `#fbbf24` amber-400 | 1.4 | zone / deutan | 12.6:1 |

For scale: the roles frozen in UI-1 come as close as **ΔE00 0.4** to one another (box versus B→A under protanopia), so the new role is separated by an order of magnitude more than the bar already accepted.

It is an evidence role in its own namespace — not a borrowed `--status-warn` — and the crossing glyph is a **diamond**, with a dashed outline for B→A, so hue is never the only cue. Rendered and checked across the §26 bright, dark, saturated, low-contrast, letterboxed and pillarboxed conditions at all four acceptance widths.

---

## 4. Bounding the accessible descriptions

A valid scene may hold 64 zones of 64 vertices. Four thousand spoken coordinates is a data dump, not an accessible equivalent of a polygon.

Each zone's description gives its state, its vertex count, its normalised extent, the first four vertices as orientation, and the number it did not name. Trip lines are given completely, because two endpoints are already bounded.

The descriptions are **built once when the evidence model is built**, not on each `describe(currentOffsetMs)` call: scene geometry does not move with the media. A test asserts that `describe` returns the *same array object* at every playhead position, so the O(all vertices) work cannot creep back into the per-frame path.

The same reasoning applies to drawing, and was missed on the first pass (§5.1).

---

## 5. What the cold review found in this implementation

An independent pass was made over the finished diff, against the plan's risk list and beyond it. Four things were found and fixed before review.

### 5.1 Geometry was re-projected on every animation frame

`render(frame, currentOffsetMs)` is called by the player on each frame while the media plays. The zone layer projected every vertex and rebuilt every point string each time, although none of it depends on the playhead: 64 zones of 64 vertices at 60fps is a quarter of a million operations a second producing an identical picture, on a product that targets a development laptop.

Fixed by memoising each analytical layer's drawing on the content rectangle, which is the only input that actually changes. Returning the same element also lets React skip reconciling the subtree. Pinned by a test.

### 5.2 Review and the inspector could name geometry differently

The inspector fell back to the originating *search's* geometry names when the pinned revision could not be loaded, while Review fell back to stable ids. For a stale or re-read Track the search's revision is not the revision the facts were measured against, so this was a quiet substitution of exactly the kind §6.1 forbids — and a divergence between two surfaces that must agree.

Removed. Both surfaces name geometry from the pinned revision or by stable id. The now-unused `geometry` prop was removed from `TrackInspector` and its call site.

### 5.3 A tested helper never reached the operator

`hasOverlappingStationary` existed and was tested, but nothing used it. Stationary is one fixed lane, so malformed overlapping intervals would have painted over each other silently — the exact failure the plan asks to be made visible.

The host now states the condition. The intervals are still drawn as given rather than repacked: a fact the engine should not have produced is something to report, not something to lay out more neatly until it looks intentional.

### 5.4 Two smaller ones

A self-contradictory summary line ("9s longest … 0 intervals") when the engine reports a longest stationary period with no interval list; and only the *first* crossing of a line carrying a time, which is not enough to check a crossing against the video. Both were found by reading rendered output rather than by a failing test.

---

## 6. Two visual-QA harness defects

Both reported collisions no operator could see, and both would have false-positived on any product code with the same shape.

1. **Closed disclosures.** Chromium lays out the content of a closed `<details>` and reports real rectangles for it while painting none of it. The detector inferred visibility from geometry. It now asks `checkVisibility`, the standards predicate for "would this be painted".
2. **Wrapped inline text.** An inline element that wraps has one box per line; its *union* rectangle covers everything between the start of the first line and the end of the last, including space its own siblings occupy. Comparing unions reported a collision every time a sentence wrapped around another inline element. The detector now compares line boxes.

Both changes are strictly more precise — line boxes are subsets of the union, and an unpainted element cannot collide with anything — so neither weakens the gate.

---

## 7. The trajectory fixture gap

UI-5's visual QA served no trajectory at all, so the rendered matrix could never show raw path evidence underneath the analytical overlays. The harness now serves one.

The bytes are **encoded from a JSON fixture at serve time** rather than committed: the repository stays text-only, the fixture is readable in review, and the encoder emits only the MessagePack subset the browser's own decoder accepts — so a fixture the browser refuses is a real disagreement rather than the harness writing something the worker never would. The encoder is forty lines of the format actually in play; no dependency was added.

---

## 8. Validation

| Gate | Result |
|---|---|
| Web Vitest | 715 tests across 49 files, green |
| `tsc -b` | clean |
| `vite build` | clean |
| `python tools/verify_repo.py` | clean |
| §26 visual QA | 358 state/viewport combinations, no findings |

Backend and .NET suites were not run: no backend, contract or shared file is touched. The one API-shaped change is a **test-only** harness route.

---

## 9. Dependency and offline impact

**None.** No npm, .NET, Python, native, model, OS, database or external asset dependency. `config/dependencies/offline-dependency-policy-v1.json` is unchanged because there is nothing to declare. Everything the harness needs it computes itself, offline.

---

## 10. Deferred

- **Slice 7 (recorded, unchanged):** the browser's `parseTrajectory` validates finite coordinates but does not enforce normalised `[0,1]` centres as strictly as the worker and the application decoder do. Correct worker output cannot reach that path, so it is not a Slice-5 blocker.
- **P3, new:** the overflow rail's aggregate count is stated once for the whole rail rather than per concurrent span. With the capped three sub-rows a span with more than three concurrent visits is already unusual, and the semantic list names every visit individually, so per-span counts would add layout for a case that has no evidence behind it yet. Worth revisiting if real scenes produce sustained high concurrency.

---

## 11. Not in this slice

Aggregates, heatmaps, Stage-7 event records, anomaly or intent claims, trajectory v2, metric speed or distance, live cameras, case management, operator confirmation workflow, a plugin framework, and any backend analytical rule. The crossing layer is deliberately named **Crossings** rather than "Events" so Stage-7 vocabulary is not pulled forward into a slice that does not implement it.
