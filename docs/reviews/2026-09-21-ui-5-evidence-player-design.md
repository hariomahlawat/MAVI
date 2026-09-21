# UI-5 — Evidence Player architecture note

**Base:** `main@b505a97` (PR #63 merged, post-merge CI green).
**Purpose:** the design recorded before implementation, as §33.6 UI-5 requires. It states the decomposition, what is deliberately deferred, and the two open §32 decisions this increment must not close.

## What already exists and is reused rather than rewritten

- `ReviewLayout` (`shared/workspace/layouts.tsx`) was built by UI-2 for exactly this migration: a 65/35 grid, a sticky player column above 1100px, `useScrollPolicy('page')`. UI-5 migrates the Review page onto it and deletes the legacy `.review-layout` grid that §34.1 forbids extending.
- `overlay.ts` — `contentRect`, `projectBox`, `projectPoint`, `isBoxVisibleAt`. The letterbox/pillarbox-correct projection path is already right and is not touched.
- `trajectory.ts` — `trajectoryPositionAt` returns null outside the sampled range. Kept exactly.
- `seek.ts` — the one-second-before-start review seek. Kept exactly.
- The animation-frame lifecycle in `TrackEvidencePlayer` and its `FrameScheduler` tests. §33.6 names this as tested logic to reuse; it moves into the controller unchanged in behaviour and keeps its tests.

## Decomposition

Two layers, plus the pure modules they rest on.

**`shared/evidence/useEvidenceTransport.ts` — the playback controller.**
Owns everything about the media element: current offset, playing, metadata readiness, media error, duration, playback rate, the measured content rectangle, and the single animation-frame loop. Exposes `play`, `pause`, `toggle`, `seekTo`, `stepFrames`, `nudgeSeconds`, `setRate`. The `<video>` remains the authoritative clock; the controller never keeps a second one, and the loop exists only while the element reports playing.

**`shared/evidence/EvidencePlayer.tsx` — the reusable shell.**
Frame, overlay stage, transport strip below the frame, one timeline, layer controls. Generic: it knows nothing about Tracks. Takes a source, a subject interval, timeline markers and intervals, and a list of overlay layers.

**`features/video-review/TrackEvidence.tsx` — the Track adapter.**
Composes the shell for a `TrackDetail`: the representative box layer, the trajectory layer, the subject interval, the representative marker and the Track's labels. Track-specific evidence stays feature-local, which is what §27 says about track provenance.

Promotion of the player to `shared/` is argued against the §27.1 four-point test in the PR body, as §34 item 10 requires.

## Overlay layer model

A small typed record, not a plugin framework:

```ts
type EvidenceLayer = {
  id: string;
  label: string;
  available: boolean;
  unavailableReason?: string;
  render: (frame: PixelRect, currentOffsetMs: number) => ReactNode;
};
```

The shell owns visibility (persisted per operator in local storage, §18.4) and renders the visible layers into one SVG stage aligned to the content rectangle. A layer that is unavailable states why next to its disabled control rather than only in a `title`, per §12. This replaces two hard-coded checkboxes and two `show*` booleans, so adding scene geometry in Slice 5 does not touch the media controller.

## Timeline and the extension seam

One timeline. It carries the full media range, the subject interval, markers and the playhead, and it is interactive: click to seek, pointer scrub, and keyboard seek from a focusable slider role. Every marker and every interval also appears in a visually-hidden list, which is the §23 accessible twin. The timeline is not `aria-hidden`, unlike the transitional implementation.

The seam is two exported types:

```ts
type EvidenceTimelineMarker = { id: string; offsetMs: number; label: string; kind: string };
type EvidenceTimelineInterval = { id: string; startOffsetMs: number; endOffsetMs: number; label: string; lane: string };
```

**§32 decision 7 stays open.** UI-5 draws the `subject` lane and every marker, because those have one obvious presentation and real data today. It deliberately does **not** choose between stacked lanes and a single lane with glyphs for analytical intervals: an interval in any other lane is listed in the accessible twin and not drawn, and a test pins that as deliberate. Slice 5 chooses the presentation against real zone, dwell and stationary facts, which is what the specification says that decision waits for.

**§32 decisions 2a, 2b and 2c stay open.** No event-marker, similarity or heatmap hue is invented. UI-5 renders only the frozen roles it actually draws: `--evidence-box`, `--evidence-track`, plus the halo and matte tokens.

## Keyboard scoping

The collision is real and specific: Investigation binds `j`/`k` on the window for result navigation, and the frozen player grammar binds `J`/`L` for ±1 second — the same physical keys.

So player shortcuts are **not** bound to the window. They are handled on the player's own container, which carries `data-evidence-player` and is focusable, so they fire only when focus is inside the player. Investigation's `isNavigationTarget` is extended to refuse any event originating inside that container, so the two never both act on one key press. Space and Enter are additionally ignored when the event target is a button, link or other control where the key already has native meaning, so the transport controls themselves keep working normally.

## Error states kept distinct

Source video failed, trajectory request failed, no trajectory exists, no representative frame exists, media still loading, and Track request failed remain six different statements. None of them is allowed to render as empty evidence.

## Out of scope

No zone or trip-line overlay, no crossing, dwell, stationary or loitering content, no analytical explanation panel, no event UI, no aggregate or heatmap surface, no backend change of any kind. Those belong to Scene Analytics Slice 5 and later capability stages, and this increment adds no placeholder standing in for them.
