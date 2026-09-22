# Scene Analytics Slice 5 — Pre-implementation Cold Review

**Date:** 2026-09-22  
**Reviewed planning branch:** `docs/scene-analytics-s5-plan-rebaseline`  
**Planning base:** `main@273718ca078b5d86879d5a166af6c9eaff4c1c28` (PR #64 merge)  
**Primary execution plan:** `docs/superpowers/plans/2026-09-22-scene-analytics-s5-evidence-explanation.md`

## Review posture

This review treated Slice 5 as if the implementation had not yet started. It checked the plan against the merged code/contracts rather than against earlier prose.

Surfaces inspected:

- `api/tracks.ts` analytical detail contract;
- `api/scene.ts` immutable scene revision contract;
- `shared/evidence/EvidencePlayer.tsx`;
- `shared/evidence/EvidenceTimeline.tsx` / `timeline.ts`;
- `shared/evidence/layers.ts`;
- `features/video-review/TrackEvidence.tsx`;
- `features/visual-search/TrackAnalyticsSummary.tsx`;
- `features/visual-search/useSceneGeometry.ts`;
- UI/UX specification §§18, 19, 23, 25, 32, 33.6;
- ADR-011 identity/lifecycle assumptions as already implemented by Slice 4;
- Stage-1 parent plan and both current capability roadmaps.

## Result

After the planning corrections recorded below:

- **P1 planning defects: 0**
- **P2 planning defects: 0**
- **P3 follow-ups: 1** — browser trajectory parser range parity, explicitly deferred to Slice 7.

The plan is implementation-ready after incorporating the subsequent PR review corrections for overlapping zone visits and bounded accessible geometry descriptions. On exact `main@273718ca078b5d86879d5a166af6c9eaff4c1c28`, both required post-merge workflows are green: Task 17 Acceptance Validation and MAVI Quality Gate.

## Defects found and corrected during the cold review

### 1. Stale architecture references

The parent plan still named the deleted pre-UI-5 Track-specific player and described Slice 4/UI-5 as open.

Corrected to the merged architecture:

- one shared `EvidencePlayer`;
- `TrackEvidence` as the Track adapter;
- one `useEvidenceTransport` media lifecycle;
- one `EvidenceTimeline`;
- typed spatial `EvidenceLayer` contract;
- Slice 4 merged as `b505a97`;
- UI-5 / PR #64 merged as `273718c`.

### 2. Raw one-sample evidence versus Scene Analytics sufficiency

The parent plan's `trajectory_too_short` wording could be read as declaring a one-sample trajectory invalid evidence.

The producer/domain permits one-observation Tracks, and UI-5 correctly renders the one persisted sample.

The plan now freezes the distinction:

- **raw evidence:** one sample is legitimate and reviewable;
- **Scene Analytics v1:** fewer than two samples cannot support path-derived zone/crossing/motion facts and may therefore produce `Unavailable / trajectory_too_short`.

Slice 5 must display both truths without suppressing raw evidence.

### 3. Historical revision geometry

The existing `useSceneGeometry` helper was designed primarily for names/filter composition and may resolve the active revision in current mode.

Slice 5 requires the full exact revision that produced the analytical facts.

The plan now requires:

- use `sceneRevisionNumber` from `TrackDetailAnalytics`;
- fetch that immutable revision directly;
- verify returned `revisionId` against expected `sceneRevisionId`;
- fail closed on mismatch/unavailability;
- never substitute active geometry for historical evidence.

No backend endpoint is required: the immutable revision API already exists.

### 4. Timeline decision was previously underspecified

UI decision 7 deliberately waited for real analytical facts.

The plan now chooses a bounded stacked presentation:

1. subject;
2. zone/dwell;
3. stationary.

This avoids:

- a second timeline;
- one row per zone;
- unbounded timeline height;
- a single ambiguous interval lane when stationary and dwell overlap.

Dwell/stationary use hatch/pattern + lane position, not new evidence hues.

The UI-spec decision remains formally open until rendered Slice-5 implementation is validated and merged.

### 5. Exact marker seeking

A normal timeline scrub computes time from pointer x and therefore cannot guarantee the exact persisted crossing offset.

The plan now requires marker activation as a real semantic control:

- pointer → exact `marker.offsetMs`;
- Enter/Space → exact `marker.offsetMs`;
- ≥24×24 effective target;
- marker pointer-down cannot first trigger approximate parent scrubbing;
- arrows/J/L/Home/End remain the Evidence Player grammar.

This applies generically to representative, crossing and boundary markers rather than adding analytics-specific playback logic.

### 6. Boundary semantics

A visit can begin inside a zone, end inside it, or be closed by a trajectory gap.

The plan now explicitly forbids fabricating entry/exit boundary markers in those cases.

Only persisted/derived facts that actually represent a boundary instant become markers.

### 7. Matched versus contextual geometry

A direct Review link does not necessarily carry the original search predicate.

The plan therefore does not invent a second “matched query” identity.

It distinguishes:

- geometry present in the pinned revision;
- geometry with persisted facts for the selected Track.

The Track detail remains the authority for complete evidence; the UI does not claim every displayed fact was part of the original search criterion.

### 8. Event-marker colour decision

The plan does not preselect a colour.

Slice 5 closes UI decision 2a only after:

- palette separation measurement;
- colour-vision simulation;
- real rendered footage checks;
- a glyph/non-colour cue.

The control is labelled **Crossings**, not Events, so Stage-7 event semantics are not pulled forward.

### 9. Browser visual-QA evidence gap

UI-5's harness did not serve a trajectory artefact.

For Slice 5 that would leave the most important combined surface under-tested.

The plan now requires a deterministic local msgpack trajectory fixture and test-only harness route so browser QA can render raw trajectory and analytical overlays together without changing production code.

### 10. Marker semantics and dense-marker collisions

The first rebaseline correctly required exact marker seeking, but it still left two implementation choices ambiguous:

- whether the list item itself should pretend to be a button;
- what happens when multiple 24×24 marker hit targets are too close to remain independently clickable.

The plan now freezes semantic HTML first: each marker is a real list item containing a real button. A bounded marker-packing rule must prevent different-offset controls from making each other pointer-inaccessible; same-offset evidence may cluster only when one activation has one exact common destination and all clustered evidence is named.

### 11. Incomplete analysed identity

An `Analysed` payload with missing revision id/number would be internally inconsistent. The plan now fails closed rather than letting a revision-dependent overlay guess current geometry.

### 12. Overlapping zone-visit occlusion

The initial fixed zone/dwell row bounded height but did not guarantee visual distinguishability when valid zone visits overlap. The plan now freezes deterministic bounded packing: up to 3 visual sub-rows plus one fixed overflow aggregate rail. Positive-duration overlaps cannot share a sub-row; fourth-or-greater concurrency is aggregated rather than painted over; every visit remains individually named in the semantic evidence list and can be identified/highlighted without creating unbounded rows.

### 13. Accessible geometry description bound

The initial wording could require every polygon vertex to be emitted into the always-mounted accessibility description. At the valid maximum of 64 zones with 64 vertices, that would be excessive and would repeat work on playhead-driven `describe` calls. The plan now bounds each zone description to vertex count, normalized extent, and at most 4 sample vertices, with any complete-coordinate disclosure explicitly on demand. Trip lines remain fully described because they have exactly two endpoints.

## Existing contract sufficiency

No backend/API change is required by the planned Slice-5 scope.

Existing detail facts already provide:

- analytical identity;
- status/unavailable reason;
- reference point;
- zone summaries;
- zone visits with entry/exit offsets and boundary flags;
- line crossings with offset, direction and normalized point;
- motion summary;
- stationary intervals.

Existing scene APIs provide immutable full revision geometry.

If implementation finds a missing persisted fact, it must stop and document the contract gap rather than deriving a substitute in the browser.

## Regression invariants carried forward

Slice 5 must preserve:

- one Evidence Player;
- one media controller/rAF loop;
- keyed source replacement behavior;
- rational frame stepping;
- one timeline;
- same-control spatial accessibility semantics;
- mandatory `describe` on spatial layers;
- exact persisted vs interpolated trajectory semantics;
- raw one-sample trajectory evidence;
- 24×24 timeline target discipline;
- Review ≥65% player floor;
- ultra-wide surplus-to-player rule;
- Review sticky/release threshold;
- Investigation shortcut isolation;
- PR #63 analytics identity propagation;
- malformed Review provenance fail-closed behavior.

## Non-goals confirmed

The plan contains no:

- aggregate/heatmap implementation;
- Stage-7 event records;
- trajectory-v2 worker change;
- metric motion;
- new dependency;
- live-camera work;
- second player/timeline;
- case/audit workflow.

## Deferred P3

The browser `parseTrajectory` checks finite coordinates but does not currently enforce normalized centre x/y within `[0,1]` as strictly as the worker/domain contract.

Correct worker-produced evidence cannot hit that path, so it is not a Slice-5 blocker.

It is now explicitly listed in Slice 7 hardening with a malformed-artifact discriminating test requirement.

## Final planning gate

Slice 5 implementation may start only when:

1. this planning update is merged;
2. PR #64 merge commit `273718ca078b5d86879d5a166af6c9eaff4c1c28` has green post-merge Task 17 Acceptance;
3. the same commit has green post-merge MAVI Quality Gate;
4. the implementation branch is created from that exact green `main` state (or a later `main` that contains only reviewed/merged changes);
5. no implementation begins from this documentation branch.

At that point the recommended implementation branch is:

`feature/scene-analytics-s5-evidence-explanation`
