# UI-5 — Evidence Player architecture note

**Base:** `main@b505a97` (PR #63 merged, post-merge CI green).
**Purpose:** the design recorded before implementation, as §33.6 UI-5 requires. It states the decomposition, what is deliberately deferred, and the two open §32 decisions this increment must not close.

## What already exists and is reused rather than rewritten

- `ReviewLayout` (`shared/workspace/layouts.tsx`) was built by UI-2 for exactly this migration: a two-column grid with the player at 65% of the working width or more, a sticky player column above 1100px, `useScrollPolicy('page')`. UI-5 corrects the track sizing so the floor is met exactly and the **surplus goes to the player**: the rail is the smaller of 35% minus the gap and its readable maximum of 440px, and the player is what is left. The percentage branch holds the floor at every width; past roughly 1500px of working width the rail stops growing and every further pixel is the player's, which is what §25 asks for on an ultra-wide display and what a fixed 65% cannot do. UI-5 migrates the Review page onto it and deletes the legacy `.review-layout` grid that §34.1 forbids extending.
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

A small discriminated union, not a plugin framework:

```ts
type EvidenceLayerBase = {
  id: string;
  label: string;
  available: boolean;
  unavailableReason?: string;
  render: (frame: PixelRect, currentOffsetMs: number) => ReactNode;
};

type EvidenceLayer =
  | (EvidenceLayerBase & { kind: 'spatial'; describe: (currentOffsetMs: number) => readonly EvidenceDescription[] })
  | (EvidenceLayerBase & { kind: 'non-spatial'; describe?: never });
```

`describe` is **required** on a spatial layer. An optional one would have left a
conformance hole the type system was quietly holding open: a Slice 5 zone layer
could have drawn geometry with no accessible equivalent and compiled cleanly.

### Where the §23 twin lives

**It is the layer control the operator already uses.** §23 says the twin is the
same control the pointer uses, not a parallel accessibility-only surface, so
there is no hidden spatial tree rendered beside the stage. Each layer has one
visible row — its toggle — and that row's control carries the layer's evidence
as its own accessible description. One layer object, one visible control, one
semantic object.

The raw SVG stage stays `aria-hidden`. That is not the parallel-surface problem
and does not become one: narrating path data helps nobody, and what is narrated
instead is the evidence, from the same data the layer draws from. Coordinates
are **normalised source-frame** values rather than projected pixels: a pixel
position describes whatever window the operator happens to have, while the
normalised position is the evidence. A layer that draws an unbounded number of
objects summarises — a real trajectory carries thousands of samples, and an
accessibility tree with thousands of entries in it is not accessible. Nothing
in the description is focusable, so the semantics cost no extra tab stop.

### Two states, never one

A description says what an object is and where it is. It deliberately does not
say whether it is on screen, because that is not one fact:

- **Layer preference** — enabled, hidden by the operator, unavailable. Generic,
  and the player's, since only the player knows the toggle.
- **Evidence applicability** — whether the layer has anything to assert at this
  playhead. Evidence-specific, and the layer's: a representative box applies
  only near the frame it was persisted for, a trajectory only inside its
  sampled range.

The two are composed into one drawing sentence rather than announced
separately. Announcing them separately is how "Shown on the frame." came to sit
beside "Not drawn here: the playhead is away from the frame it describes." An
enabled toggle is not by itself a claim that anything is on the frame.

The shell owns visibility (persisted per operator in local storage, §18.4) and renders the visible layers into one SVG stage aligned to the content rectangle. A layer that is unavailable states why next to its disabled control rather than only in a `title`, per §12. This replaces two hard-coded checkboxes and two `show*` booleans, so adding scene geometry in Slice 5 does not touch the media controller.

## Timeline and the extension seam

One timeline. It carries the full media range, the subject interval, markers and the playhead, and it seeks by pointer: click and scrub.

**It has no keyboard vocabulary of its own.** The §22 grammar is one contract for the whole player, so a timeline that answered the arrows or Home and End itself would give the same key two meanings on one surface depending on where focus sat. Arrows step a frame, J and L move a second, Home and End go to the subject — wherever focus is inside the player, the timeline included.

**Each mark is one element that is both the evidence and the named item.** The bar is a list; every interval and marker is a list item carrying its own name. There is no `aria-hidden` bar shadowed by a hidden description list, because a parallel accessibility-only surface is what §23 forbids — the twin has to be the thing the pointer sees.

The seam is two exported types:

```ts
type EvidenceTimelineMarker = { id: string; offsetMs: number; label: string; kind: string };
type EvidenceTimelineInterval = { id: string; startOffsetMs: number; endOffsetMs: number; label: string; lane: string };
```

**§32 decision 7 stays open.** UI-5 draws the `subject` lane and every marker, because those have one obvious presentation and real data today. It deliberately does **not** choose between stacked lanes and a single lane with glyphs for analytical intervals: an interval in any other lane is still a named evidence item and is not drawn, and a test pins that as deliberate. Slice 5 chooses the presentation against real zone, dwell and stationary facts, which is what the specification says that decision waits for.

**§32 decisions 2a, 2b and 2c stay open.** No event-marker, similarity or heatmap hue is invented. UI-5 renders only the frozen roles it actually draws: `--evidence-box`, `--evidence-track`, plus the halo and matte tokens.

## Keyboard scoping

The collision is real and specific: Investigation binds `j`/`k` on the window for result navigation, and the frozen player grammar binds `J`/`L` for ±1 second — the same physical keys.

So player shortcuts are **not** bound to the window. They are handled on the player's own container, which carries `data-evidence-player` and is focusable, so they fire only when focus is inside the player. Investigation's `isNavigationTarget` is extended to refuse any event originating inside that container, so the two never both act on one key press. Space and Enter are additionally ignored when the event target is a button, link or other control where the key already has native meaning, so the transport controls themselves keep working normally.

## Error states kept distinct

Source video failed, trajectory request failed, no trajectory exists, no representative frame exists, media still loading, and Track request failed remain six different statements. None of them is allowed to render as empty evidence.

## Out of scope

No zone or trip-line overlay, no crossing, dwell, stationary or loitering content, no analytical explanation panel, no event UI, no aggregate or heatmap surface, no backend change of any kind. Those belong to Scene Analytics Slice 5 and later capability stages, and this increment adds no placeholder standing in for them.
