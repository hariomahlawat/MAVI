# Scene Analytics Slice 7 — semantic acceptance (corpus C1)

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance` (PR #70), with PR #71 integrated by fast-forward
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`
**Test:** `tests/Mavi.IntegrationTests/SemanticAcceptanceTests.cs`

---

## 1. The gap this closes

Before this pass the analytics stack had two disjoint bodies of semantic evidence:

- the **executor** tests drove real sealed trajectory bytes through the real decoder and the real engine, and asserted that facts appeared — `SampleCount > 0`, `DwellMs > 0`, one visit row;
- the **§S search** and **§T aggregate** tests answered correctly over facts a fixture **wrote by hand** (`SceneAnalyticsWorld.Facts`).

Nothing joined them. A divergence between what the engine derives and what the read side counts — a heading the engine spells one way and the predicate another, a dwell measured from a different boundary, a direction label inverted — would have passed both suites, because neither suite ever compared the two.

## 2. What C1 is

One authored trajectory over the fixture scene, whose expected answer is worked out **from the frozen rules, in a comment, before the test runs**, then asserted through the real decoder, the real engine, the fenced commit, the §S predicates and the §T aggregate.

The scene: zone `Gate`, the square x ∈ [0.1, 0.4], y ∈ [0.1, 0.4], loitering at 45 s; line `Kerb`, A (0.1, 0.5) to B (0.9, 0.5), directed left to right.

The path, 41 samples at 200 ms, inside the Track's declared 0–8000 ms span: up the frame through the line and into the zone, a drift inside it, then out and down through the line again.

### The hand-derived answer

| Quantity | Derivation | Expected |
|---|---|---|
| Line crossings | `Cross(A,B,p) = 0.8·(p.y−0.5)`; the on-line band is `ε·|AB| = 0.005·0.8`, so a sample takes a side once `|p.y−0.5| ≥ 0.005`. Both passes clear the band | exactly 2 |
| First direction | Moving **up** the frame through a left-to-right line is `AToB` by the frozen convention | `AToB` |
| Second direction | Moving **down** is `BToA`; 5.4 s apart and opposite, so 1 s repeat suppression cannot merge them | `BToA` |
| Zone visits | Containment is `y ≤ 0.4` along x = 0.25 | 1 entry, 1 exit |
| Dwell | Entry between t = 1800 (y = 0.404, outside) and t = 2000 (y = 0.36, inside); exit needs the ε margin `y > 0.405`, between t = 6400 and t = 6600 | `[4400, 4800]` ms |
| Loitering | 4.8 s against the zone's 45 s threshold | false |
| Heading | (0.25, 0.80) → (0.60, 0.78): dx = +0.35, dy = −0.02, displacement 0.351 ≥ 0.02 minimum; `atan2(dx, −dy)` = 86.7° lands in the East sector | `E` |
| Stationary | No 5 s run within the person threshold | none |

Where a value depends on an interpolation policy the plan does not freeze — the exact millisecond a boundary is deemed crossed — the assertion is the **bracket the samples themselves imply**, with its arithmetic written out, rather than a tolerance chosen to fit an observed number.

## 3. Result

All three tests pass. The engine's derived facts match the hand-derived table above; the §S predicates select the Track on each of them and reject their complements (six of the seven wrong headings, a dwell threshold above the derived dwell, `minStationaryMs`, `loitering`); the §T aggregate counts one entry, one exit, one unique Track, zero repeated visits, one crossing each way and one distinct Person.

## 4. Two predictions that were wrong, and the product was right

Both are now pinned where they had been documented only in a comment.

1. **Sampled occupancy.** I expected `peakOccupancy = 1` for a visit inside the window. Occupancy is **sampled at each bucket's start instant**, not integrated over the bucket (plan §4.2). A 4.8-second visit inside an hour-wide bucket whose start instant it does not span is never sampled, so the correct answer is zero — reporting one would be the aggregate claiming a measurement it never took. The test now asserts zero for the hour bucket **and** one for the same facts resolved to one-second buckets, with the peak instant falling inside the visit, so "zero" cannot be an occupancy series that never counts anything.

2. **Class series completeness.** I expected only the classes observed. Every class is emitted, with zero for the unobserved ones, so an operator reading a zero is reading a measured absence rather than a missing row. The test now asserts the full pair.

## 5. What C1 does **not** yet cover

The trace stops at the §S and §T read sides. It does not extend to the **bounded explanation**, the **heatmap** or the **UI projection** of the same authored path. Exit-gate item 2 (plan §25) therefore remains **PARTIAL**, not PASS: the cross-layer trace exists for the layers named above and does not exist for the other three.

**Corroboration since, and why it is not the same thing.** The Development-machine real-worker run exercised exactly those three missing layers on real data, and they agreed with one another: Evidence Review reported the Track's zone visit and heading under *Scene revision 2 · Engine v1*, and Activity and the Heatmap both counted the same 12 Person Tracks under the same identity with complete coverage. That is real evidence the layers are wired consistently. It is not C1, whose value is that a human states the exact expected answer before the run; nobody predicted the real video's facts in advance. Item 2 stays PARTIAL until the authored path is traced through the explanation, the heatmap and the UI projection.
