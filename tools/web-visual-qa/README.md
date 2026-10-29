# Visual QA harness

The repeatable procedure behind **§26 Visual QA standard** of
`docs/architecture/ui-ux-design-specification.md`.

§26 is normative and explicitly says unit tests do not satisfy it: focus
visibility, contrast as rendered, ultra-wide structure and overlay legibility
over real footage are not things jsdom can answer. This harness drives the real
production bundle in a real browser at every support-tier anchor, asserts what
can be asserted, and writes screenshots for the part that still needs a person.

## Running it

```bash
cd src/web/mavi-web && npm run build          # the harness runs the real bundle
cd - && node tools/web-visual-qa/run.mjs       # or add --build to do both
node --test 'tools/web-visual-qa/test/*.test.mjs'   # the harness's own tests
```

| Flag | Effect |
|---|---|
| `--build` | run `npm run build` first |
| `--states cameras,search` | only these states (see `states.mjs`) |
| `--tiers A` | only the anchors and probes of these support tiers |
| `--widths 1366,2560` | only these widths |
| `--zoom only` / `--zoom none` | only the 200% browser-zoom cases, or none of them (T3) |
| `--text-spacing only` / `--text-spacing none` | only the WCAG 1.4.12 text-spacing cases, or none of them (X1) |
| `--reduced-motion only` / `--reduced-motion none` | only the `prefers-reduced-motion: reduce` cases, or none of them (X4) |
| `--workers 3` | parallel lanes (default: CPUs − 1, at most 4) |
| `--repeat 5` | prepare every selected case this many times, independently, and require one settled state |
| `--keep` | report blocking findings but exit 0 |
| `--shard i/n` | run the i-th of n deterministic shards of the same plan (CI); the sweep-wide verdict is `aggregate.mjs`'s |

**Sharding (CI).** `run.mjs --shard i/n` partitions the plan it would otherwise
run whole: the unit is a state (every anchor, probe and 200% case of a state in
one shard), a loading Ledger and its table are kept together, and the states are
dealt round-robin in their registered order (`engine.partitionCases`), so the
same head gives the same shards every time. A shard judges each case it runs and
writes, beside its own results, the whole planned case list. It is never the
full sweep by itself: `node tools/web-visual-qa/aggregate.mjs --out DIR
shard0/results.json …` is, and it refuses to pass unless every shard is of the
same head, manifest, shard count and plan, the shard indices are 0…n−1 each
exactly once, every planned case ran in exactly one shard and reached its state,
no shard reported a harness error — and then applies the sweep-wide checks an
unsharded full run applies (`engine.sweepChecks`: a loading Ledger against its
table, pressed treatments proven somewhere, every operator surface judged at
200%, no blocking rule left unevaluated, overlay restoration judged at Tier A)
and fails on any blocking finding. The aggregate's `results.json` carries every
shard's cases and findings; its exit status is `run.mjs`'s. The lanes (T3's zoom,
X1's text spacing, X4's reduced motion) shard the same way: a lane's cases are
a state's cases, and `partitionCases` partitions plans; the aggregate proves
each lane's coverage over the union of the shards.

**Test groups (CI).** The harness's own tests run in four concurrent groups:
`MAVI_VQA_TEST_GROUP=unit` runs every file but skips the tests declared with
`e2eIt` — the long end-to-end runs of `run.mjs` in `zoom.test.mjs`,
`run.test.mjs`, `shard.test.mjs`, `a11y.test.mjs` and `motion.test.mjs`; `MAVI_VQA_TEST_GROUP=e2e-i/n` runs the i-th
of n groups of those, each test in exactly one group by its order in the file,
and nothing else from those files (`test/browser.mjs` `testGroup`, `e2eIt`,
`unitBlock`). The short `run.mjs` spawns in `engine.test.mjs` stay in the unit
group. `tools/verify_repo.py` holds that every test file using `e2eIt` is named
in the workflow's end-to-end step, so no such test can be skipped in every
group. Unset, everything runs in one process as before.

Exit status: **0** no blocking finding; **1** at least one blocking finding;
**2** the harness itself failed — a browser or server fault, a case that threw,
**a state it could not reach at any tier** (failed or unconfirmed preparation,
settle timeout, footage overlay never drawn), a finding or an evaluation the
manifest does not allow, or — on the full sweep — a blocking rule that never
evaluated anything where it blocks. A harness fault is never reported as a
finding, so no tier severity can soften it, and a later case that succeeds
does not clear an earlier fault. An unreached state's capture is kept for
diagnosis as `<state>--<viewport>--UNREACHED.png`, marked `valid: false` with
its `unreached.stage` and `reason`, and left out of the valid-capture counts.
**A clean exit is necessary, not sufficient** — §26 requires looking at the
captures.

Everything a run produced is in `.captures/`: one PNG and one JSON per
capture, and `results.json` — the manifest summary, every state's tier
applicability with its exclusion reasons, executions (scheduled, valid captures
by tier, unreached and errored cases with their stage and reason), every
finding with its rule, tier, surface, severity and owner, per-rule coverage,
the P1 measurements and any harness errors.

Two environment variables exist for the harness's own tests and nothing else:
`MAVI_VQA_OUT` writes the run somewhere other than `.captures/` (a directory it
names is replaced only if it is missing, empty or a previous output — it carries
a `.mavi-visual-qa-output` marker), and
`MAVI_VQA_STATES_MODULE` loads a module that re-exports `states.mjs` with test
states added (the deliberately unreachable state of `test/run.test.mjs`); a run
under it records `statesModule` and is never a full sweep.

`MAVI_VQA_RESPONSE_ORDER` (`natural`, the default, or `forward` — the
gate's) pins the data-response order; see *X3 (§38)* below.

## Harness v2 (Stage 3.5 S2)

**The assertion manifest** (`manifest.mjs`, register V1) has one entry per rule
and, for each support tier, its status there: `blocking`, `measured/pending`
(reported, never failing, with the owning slice and register row named) or
`not-applicable` (with the reason). Every finding names a rule and takes that
rule's severity at the tier of the width it was found at — from the manifest and
nowhere else.

**Surface scope.** `text.overflow` and `containment.depth` are `scope: 'surface'`
rules: blocking at Tier A wherever S1 owns the region (the shell, the Context
Bar, every Ledger, the Dialog host, the shortcut sheet, the skip link and every
StateRegion — a finding there carries `surface: 'foundation'`), and on a product
surface only once that surface's register row is accepted. `SURFACES` in
`manifest.mjs` lists each surface with its row (Search R5, Review R6, Camera
Analytics M4, …) and an `accepted` flag that the slice closing the row flips —
one surface at a time, never all together; `ROUTES` maps every state's route to
its surface and refuses a route it does not know. Until then a surface's
findings are `measured/pending` against its own row. A frame round nothing but
media (an image, a video, an evidence placeholder) is that object's edge, not a
containment level. A finding or an evaluation the manifest does not allow at that
tier, and a finding naming no rule, are harness faults. Until S5 flips them,
every rule evaluated at a Tier B or C width is `measured/pending`; the manifest
refuses anything else. Rules owned by later slices are registered now: measured
where code exists (`containment.depth`, the §25 tier rules, the P1
measurements; `review.sticky-rendered` was too until R6 made the pin render,
and now blocks at Tier A: the player still on screen after the page scrolls,
and clear of the Context Bar) and declared
`future` with an execution policy where
it does not yet (none remains: 200% zoom was until T3, reduced motion until
X4, and the keyboard journeys until X2, which asserts them through its own
producer, `journeys.mjs`).

**Tiers and states** (`states.mjs`, V2). The default sweep is every §25 anchor:
1366×768, 1440×900, 1920×1080, 2560×1080 and 2560×1440 (Tier A); 1024×768 and
768×1024 (Tier B); 430×932 and 390×844 (Tier C). A state applies at every tier
unless it names a tier policy, and a policy that leaves a tier out says why:
`footage-variant` (Tier A only — a footage condition differs from the canonical
Review state only in the video's pixels) and `breakpoint-probe` (only its probe
widths — it exists to settle a measured transition). Applicability is not
severity: a state cannot carry a severity, a known-issue list or any key the
model does not define. `probeWidths` adds the special widths a state is also
checked at — the 1120 Workbench drawer band, the 1440–1700 Investigation
threshold, 1600 for the Evidence Set — reported apart from the anchors.

**Deterministic settling** (`settle.mjs`, `engine.mjs`, V3). A capture is
taken when the page and the fixture server agree the state is reached, on two
consecutive probes: the page's expected text is shown and its forbidden text is
not; no loading presentation is on screen (or, for a state that `holds:
'loading'`, one is); images have loaded; a visible video has its metadata and
is not mid-seek (a page that seeks on load has done so); no finite transition is running; the
DOM has stopped changing; no request is in flight or newly started; and no
query is fetching or waiting out a retry's backoff (the app's query activity,
registered on the harness handle only when the harness installed it: the one
passive hook UI spec §26 (v2.2) permits, `harnessObservability.ts`). A
request held open to keep a loading state is not "in flight" — it never
completes by design. Preparations wait for the consequence of each action, never
for a guessed duration. Every wait is bounded; a timeout refuses the state and
says what was still pending. Two deliberate exceptions, both documented in the
code: a footage state re-issues its seek at a bounded interval until the overlay
is drawn over a decoded frame (media decoding exposes no completion the page can
await), and `search-analytics-scene-degraded` moves the page clock past the
30-second stale time instead of sleeping through it.

**Measurements** (P1, V5), recorded per capture, raw — a case never judges its own (the performance gate does, below: *X3 (§38)*):
cumulative layout shift during each loading-to-content transition (Layout
Instability API): the navigation's, from its first loading presentation to the
settled state (`perf.cls`), and — kept apart — one a preparation starts, from
that loading presentation to the state settling after it (`perf.clsPreparation`,
labelled with the interaction or `fixture preparation`); harness activity
between the two is in neither, and a transition that did not happen is
`not-applicable`, never 0. Long tasks during the state's first operator
interaction (`perf.longTasks`): only where the state names one (`interaction` in
`states.mjs` — a click, a submit, a key press), from the action until the settle probe
that confirmed its outcome, with the observers flushed (a settle probe's own
work inside a task is subtracted; what remains still counts if it is 50ms or
more, else the task is counted as `excludedAsHarness`); a preparation
of several steps marks `interaction-start` immediately before the one action it
names; a preparation that is fixture setup or a
condition check (a programmatic seek, a page-clock advance, scripted field
values) is `not-applicable`. And the resolved font — the
declared `font-family` stack and the platform fonts Chromium actually used for
the glyphs (`CSS.getPlatformFontsForNode`). Each measurement is `measured`,
`not-applicable`, `unsupported` or `failed`, with the reason.

**No pixel baselines** (V5): screenshots are diagnostic artefacts for the
human pass, never compared. The resolved font matters to the assertions too:
the Ubuntu CI runner resolves the stack to DejaVu Sans, wider than the Segoe UI
Variable of a Windows host, and so exercises the truncation and overflow rules
with metrics a Windows sweep does not.

**Overlay exit** (§15, §20): after the capture, Escape must close an open
Dialog or Drawer, leave nothing inert and return focus to its invoker — the
last element focused outside any modal before focus first entered that overlay,
recorded by the page observers. An overlay already open when the page settled
was opened by its URL and has no invoker; for it restoration is reported
`not-applicable` and only the close and inert checks apply. A full sweep in
which no Tier A Dialog or Drawer opened by an action had its restoration judged
is a harness fault. The focus pass that precedes it puts back both the scroll
positions and the focus it found.

**200% browser page zoom** (S5 / T3, §23: "200% browser zoom at 1366×768 (an
effective 683px) reflows under the Tier C rules of §25 with no horizontal scroll
and no lost control"). Every state swept at Tier C is also captured on the
1366×768 anchor with the **browser's own page zoom** at 200% — labelled
`1366x768@200%` and judged at Tier C, where its effective 683×384 falls — and
twelve states declare sixteen live zoom transitions (`zoomTransitions`: 100%→200%,
200%→100% and 100%→200%→100% on a page in use, with navigation, filters, the
Search inspector, a focused result, a dirty Scene draft, its discard
confirmation and its leave guard, Review transport focus, an invalid Import
field, a stored grid choice and URL filters). The zoom is set the way an operator
sets it for every page — Chrome's Settings → Appearance → Page zoom, through
that page's own `chrome.settingsPrivate` in a background window (`cdp.mjs`
`pageZoom`) — and read back. CDP has no page-zoom command: device-scale-factor
emulation, page-scale (pinch) and screenshot scaling are not page zoom, and a
CSS `zoom` or a narrower viewport is not either. T3 validated the method against
a reference zoom made by real OS-level Ctrl+= keypresses into a headed Chrome
window with a 1366×768 viewport, on all ten operator surfaces: identical page
zoom factor, viewport, devicePixelRatio and media queries, and every element's
geometry identical, where a shrunk 683×384 viewport and devicePixelRatio-2
emulation each differed. Both sides ran with scrollbars hidden, as the harness
always does; with classic scrollbars shown, the environment check (rightly)
refuses the 678px viewport of a page whose document scrolls, and the
compositions raised no other finding.

`a11y.zoom-200` is the rule only a zoom case settles (`lane: 'zoom'`: the engine
refuses it in any other case). It blocks at Tier C (200%) and Tier A (zoomed
back to 100%), and is not applicable at Tier B, where no zoom case lands. In
every zoom case it proves the environment against §23's frozen condition
(`ZOOM_CONDITION`, never the states' own): the browser's page-zoom setting, the
zoom factor the browser applies (`Page.getLayoutMetrics`), the 1366×768
device-independent viewport behind it, the 683×384 CSS viewport, no pinch scale,
devicePixelRatio 2 and the Tier C media query — so the zoom left at 100%, or a
viewport merely shrunk, fails it; a transition is judged against the frozen 200%
at its zoomed step and 100% at the others, its starting step included. Then what
the 384px height can take from the page, judged by one account of what is seen
(`zoomVisibility`, read alike by the control sweep, the transition focus probe
and the text baseline): a box is *hidden* when it is not rendered, collapsed in either dimension to a pixel or less, its computed `visibility` hidden, transparent through its own or any ancestor's opacity (the root's included), or inside a box drawn at a pixel; *inert* when behind an open overlay; *reachable* when scrolling can bring it on screen (walking its clip chain outward, per axis: inside a scrolling box's extent on that axis, the box then standing in for it; inside a non-scrolling clip box; inside the page's extent where the page scrolls on that axis); *seen* where its box survives the viewport and its clipping ancestors; and it carries the *scale* transforms and the CSS `zoom` of its ancestors give its drawn size. Those ancestors come from `zoomClipChain`: overflow by CSS's containing-block rules — a fixed box escapes every ancestor up to the one that transforms, filters or contains it (else the viewport), an absolute box the static ancestors up to its positioned one, any other box is clipped by each ancestor, the walk resuming from each containing block by its own rules — while a `clip-path`, legacy `clip` or mask on any ancestor clips every descendant; the root is the last entry, its overflow (the body's, propagated) reaching every box but a fixed one. Each clips by its overflow padding box (in viewport coordinates: its layout client box scaled by the drawn box over the layout box where an ancestor transform scales it; a rotation is not modelled) or an `inset()` clip-path of plain px or % lengths (measured); any other clip-path shape, an `inset()` with a component the harness cannot resolve (a `calc()`, an em, a viewport unit), legacy clip or mask is reported as a loss the harness cannot measure. Every offered
control can then be brought into view with no more than a CSS pixel of its own
size cut off in either direction, and not only by focus scrolling a box — or the page — on an axis the operator cannot scroll; what a pointer hits across it (its middle and four points inset from its corners) is the control's own (`zoomOwn`: itself, its label, or the tooltip it is described by — never another's), and no layer the pointer passes through paints above it at those points (`zoomPaintsAt`, inferred from computed style — pixels are not read, and paint outside a box, an outline or a spread shadow, is not modelled: a replaced element or form control; an opaque background, any background image, an inset shadow or a backdrop-filter inside the padding box; in the border ring a coloured border, else the background painted under it; text of its own; a ::before or ::after likewise — judged by stack order, so an ancestor above its descendant is judged by its pseudo-elements alone, its own box being under the descendant); this is a sample at five points, not a proof against every cover; a control that is only a hit area — empty, with no background of its own, a grid card's select button — has its composition, and only it, as its face; a hidden control is offered only
where focus shows it (the skip link) or a visible label of its own stands for
it, which is then judged in its place; drawers and dialogs fit the viewport; no
font is sized in viewport units, directly or through a custom property;
truncated text keeps its full value within the keyboard's reach (§16 — the text
of a link to the row's detail or of a row's own selection control — one that
carries a selection state (aria-selected, aria-current) or is one of the
product's named selection controls, Search's result selector and the Scene
navigator's object selector — to its inspector (aria-pressed alone is a toggle's
state as well); else focus describes it through the Tooltip, compared by letters
and digits); the keyboard order — the order Tab visits, positive tabindex first
— of the Context Bar is its visual order, and at Tier C, in the workspace or
open overlay, the keyboard never steps back along a line or back up a column
(side-by-side columns, such as a Ledger row's action column, are read one after
another, and a control placed by its data — a timeline marker, positioned by
an inline `left`/`top`/`inset` on it or on an absolutely positioned ancestor,
never by a stylesheet — follows the data); the Evidence Player draws the whole picture undistorted — measured from
the footage's intrinsic size and its box for each `object-fit` (`contain` and
`scale-down` fit it; `none` draws it at natural size and crops it when it is
larger than the box; `cover` crops a different aspect; `fill` distorts one),
never taken from a list of safe values. A transition's starting state must be
the one it declares (its start tier's expected and forbidden text, after its
preparation and set-up), and every step a transition passes through — its 200%
start, or the 200% of a 100%→200%→100% path — settles on the state's declared
view at the tier it lands in (its expected and forbidden text there) and is
judged there by the same zoom checks as a load, before the zoom changes again;
only the final step before a transition's own action settles on loading alone,
the action producing what the transition declares.

**Text grows with the zoom (WCAG 1.4.4), by comparison.** Every zoom case
compares the text the page draws with a baseline, or it is a harness fault: a
200% load, and a transition that starts at 200%, against the same state reached
at 100% on the same 1366×768 viewport with the same fixtures (a probe's base
state; the baseline must be reached, at page zoom 1, and hold text, or the case
is a fault and never a pass); a change that zooms in, against the step before
it. Only text the operator can read counts — elements with a text node, and a
form control's value or chosen option — not hidden text (collapsed, transparent,
`visibility: hidden`, the visually-hidden pattern's 1px boxes), not unreachable
text (far off the page, or outside a clipped region), not text a measured
clip-path clips to nothing, not text under a layer
that paints opaquely at its middle (`zoomPaintsAt` at 0.95 alpha: a translucent
scrim dims text but leaves it readable, so text behind an open overlay, inert,
still counts; a scrim with a backdrop-filter does hide it — though covered text
keeps its words in the baseline, at the size it is drawn, without setting the
page's floor: the ledger's 11px badges under the shortcut sheet at 100% are no
shrink against the rail's 13px "Processing" once the 200% sheet leaves them
uncovered), not text under a
clip the harness cannot measure — a size being the drawn size, the CSS font size
as transforms and the CSS zoom of its ancestors scale it — and the rule is that
no text is drawn at 200% at a CSS size smaller than its counterpart at 100%,
since page zoom scales every CSS length alike and a composition may draw its
text larger, never smaller. In the same document an element is its own
counterpart. Across two compositions an element has no identity and its classes
do not name its component (`.truncate`, `code` are utilities shared across
sizes), so the counterpart is the same words at the smallest size they were
drawn at 100%, and words only the narrow composition draws are held to the
page's smallest text at 100%. That rule has one stated leniency: words a page
legitimately draws at two sizes (a time zone in the band and in a facts list)
are held to the smaller. The smallest matched ratio, times the browser's own
zoom factors, must be the frozen 2×: a "200%" the browser applies as 100% draws
its text at 1× and fails here as well as in the environment check. A case that
ends at 200% after its final action is compared again as it will be captured;
every comparison is recorded. Nothing matched at all is a fault (the physical
size is unproven), as is a page that offers controls — not disabled, not behind
an open overlay — of which none could be judged. The run records, per case, the
baseline's holders, the text compared, matched and unmatched, the physical ratio
and the number of comparisons; and, for the controls, the candidates, those
judged and the skips by reason. A live zoom change is judged as it happens:
focus — on a control, or on the main region a Dialog falls back to, judged
alike — not lost to the document or left on something hidden, transparent,
inert, out of view or covered, at every step, an overlay still open holding focus,
nothing left inert, text growing by the zoom's factor on a step that zooms in
(no piece of text is drawn smaller across the change — a composition may draw
it larger — as page zoom scales every CSS length alike; text the change mounts in place of another composition
is no smaller than the same words were before, or else than the smallest text
before; a step back out to 100% returns to the desktop type scale, which 1.4.4
does not judge), and the transition's own check (a draft kept with its geometry,
the editor's keys inert at 200%, a preference kept, focus on the control the new
composition offers). The full sweep is a harness fault unless every one of the
ten operator surfaces had a valid 200% capture that evaluated the rule.

**The documented exception, reported.** At 200% a Workbench is its §25 Tier C
unsupported state: the Scene Editor's editing, and Camera Analytics' activity
chart, heatmap and figures, are not available; each states that it needs a
display at least 768px wide and shows a read-only summary. §23 records this as
the Workbench's WCAG 1.4.4 exception; the run lists every such capture by
surface with the statement it gave (`executions.zoom.workbenchException`, and a
line in the summary), so the exception is stated, never passed silently. WCAG
1.4.10 reflow at 320 CSS px is not targeted (§23).

**Pressed state** (`pressed.visible`, §12): every visible enabled
`aria-pressed` control is rendered in its other state and compared with itself
— its own, its descendants', its pseudo-elements' and its row's computed
appearance. The other state is the attribute flipped with the classes the
product pairs with it: read from the nearest peer in the other state (the one
with the fewest class differences, so an unrelated class is not mistaken for
the pressed one) or, with no such peer, the `is-` state classes the stylesheet
defines for the control's own class or its row's. Identical readings are a
finding, whether the control is pressed or not, isolated or grouped — except
an unpressed control whose stylesheet defines `is-` states for it but whose
pressed form the page never shows: that is *unproven* in that capture, not
passed, and on a full sweep every such control kind must be shown distinct in
some capture or it is a finding where first seen. Every
attribute, class and style is restored exactly, with transitions held, so the
probe leaves the page as it found it. Its limits: the stylesheet scan reads
compound selectors, not `:is()`/`:where()` lists or CSS nesting (the product
uses neither), so a state class defined only that way leaves an isolated
unpressed control a finding rather than unproven.

**CI** (V4): the `visual QA` job of the MAVI Quality Gate builds the production
bundle, runs `node --test 'tools/web-visual-qa/test/*.test.mjs'`, sweeps with three lanes and
uploads `.captures/` as the `visual-qa-captures` artefact (14 days), whether or
not the sweep failed.

## What it needs

- **Node 22+** — the CDP client uses the built-in global `WebSocket`.
- **A Chromium-family browser.** Found automatically at the usual Linux and
  Windows locations; override with `MAVI_CHROMIUM=/path/to/chrome`.
- **ffmpeg**, already a Development prerequisite, to generate the footage
  conditions.

No npm dependency is added for any of this, and that is deliberate. A browser
automation package would put a post-install browser download into a product
whose Development setup runs `npm ci --offline` from a canonical cache
(ADR-003, and the npm `changeRule` in
`config/dependencies/offline-dependency-policy-v1.json`). The harness therefore
lives in `tools/`, outside the frontend package; CI uses the Chromium and
ffmpeg of the hosted runner image.

## What is asserted automatically

From §26 — no horizontal page overflow, no uncaught page errors, no overlapping
interactive controls. Plus four the UI-1 acceptance criteria need:

- every `var()` a stylesheet references resolves at run time (the baseline
  shipped a `var(--focus)` that did not, so keyboard focus on a search result
  row was invisible while every unit test passed);
- **focus visibility on every focusable control the surface can show**, checked
  by actually focusing each one. Coverage is accounted for rather than capped:
  each state reports how many controls were discovered, how many were checked
  and how many were skipped for which named reason, and the pass fails when
  those do not add up. Controls are skipped only when they are disabled, inside
  an `inert` subtree, zero-sized, not visible, positioned off-screen (the
  visually-hidden pattern, where a capture cannot judge a ring), or when they
  refuse focus. Focus is then left on the first checked control, so every
  capture carries one real focus ring for the human pass without adding a state
  to the matrix;
- **width discipline in both directions** — a surface that declares
  `page--full` uses the viewport at 2560, and a surface that does not stays
  capped. The second half matters as much as the first: UI-1 must fix the cap
  without widening surfaces whose archetype migration belongs to UI-3 and UI-5;
- each state proves it reached the condition it claims (`expectText` /
  `forbidText`). Without this a slow query retry silently turns the
  "unavailable" check into a second loading check.

UI-2 adds two more:

- **exactly one Context Bar per page.** §5 says the topbar *becomes* the
  Context Bar. A surface that published its own while the shell still rendered
  the old band would show two, and every other assertion here would pass;
- **archetype conformance**, on any state that declares `archetype` in
  `states.mjs`. These are the §4 rules only a rendered page can settle: for a
  Workbench, that the stage takes at least 65% of the *working* width (measured
  as the workspace element's own width, not reconstructed from viewport
  arithmetic), that the inspector stays within its fixed 300–360px, that the
  page does not scroll at or above 1150px, and that nothing but the inspector
  body owns scroll. The measurements land in the JSON beside each capture, so a
  reviewer can read the numbers rather than take the pass on trust.

UI-3 adds the Ledger and Record halves of the same check:

- a Ledger declares no-page-scroll to the shell, its body is the **only**
  scrolling container (a wrapper inside it would make the sticky header stick
  to the wrong element), the header is genuinely `sticky` against that body,
  and at 2560 a sparse table is **left-aligned rather than stretched**, which
  is section 4.1's "a Ledger must never become a sparse band of text";
- a Record declares that the **page** scrolls, and has its primary/facts grid.

UI-4 adds the Investigation half, which is where the archetype has the most
geometry to get wrong:

- the rail is the fixed 252px of §4.4 and **owns its own scroll**, with no
  second scrolling box inside it. That second box is the defect UI-4 fixed, and
  it is invisible until the rail is taller than the viewport — so what is
  checked is the ownership, not the fact that today's rail happens to fit;
- the results column stays within the ~900px cap and above the ~560px floor,
  **whether or not a Track is selected**. An Investigation with nothing selected
  is still a scan surface;
- the inspector is an in-place third column or an overlay drawer, and which one
  is compared against the layout's **own declaration** rather than against a
  threshold written here. `.workspace--investigation` publishes
  `--inspector-placement` beside the media query that decides it; the harness
  reads that back and measures whether the geometry agrees. Moving the
  threshold from 1500 to 1600 is therefore an edit to `workspace.css` and to
  nothing in this directory — a number carried here could only confirm itself;
- in place, the inspector is the column that grew: if surplus width exists and
  the inspector is still narrow, the surplus went to the wrong column (§4.4,
  open decision 4);
- nothing on the surface claims modality. §20 makes the drawer non-modal so the
  results stay readable underneath, and a `role="dialog"`, `aria-modal` or
  `inert` anywhere in the workspace is a finding.

A breakpoint is settled by the widths either side of it and nowhere else:
`search-threshold` probes 1440, 1500, 1550, 1599, 1600 and 1700 — the threshold
is 1600 — and `scene-editor-drawer` probes 1120, inside the Workbench drawer
band. Both are `breakpoint-probe` states; their anchor geometry is their base
state's.

A fixture override may also be a **sequence**: `{ sequence: [pageOne,
'unavailable'] }` answers successive requests to the same path with successive
entries, the last one repeating. Cursor pagination is the reason — page one has
to succeed for there to be a continuation to fail — and the counters are rewound
between states and viewports, so the second width starts at page one rather than
where the first left off. Per-viewer storage is cleared from `/__blank`, a
same-origin document that boots nothing: storage belongs to the origin, and
loading the application to reach it would issue its API requests and start a
sequenced state one response late.

Fixture overrides also accept a method — `'POST /api/cameras'` — and an
explicit `{ status, body }` response, which is how the duplicate-code conflict
state reaches a real 409 without breaking the listing the page needs in order
to render the form at all. A state that asks for a failing response no longer
reports it as a resource error.

A surface that declares an archetype is also checked against the scroll policy
the shell was told to apply: a Workbench that has not declared no-page-scroll
is a finding whether or not today's content happens to fit, and a contained
column whose content exceeds it is reported as clipped rather than passing
quietly. `scene-editor-dense` is the state that exercises this — an inactive
camera, an unavailable video list, a revision that will not load and the
revision strip open, which is every fixed band this surface can have at once.

The Workbench's drawer band — 1101 to 1149, where the inspector covers the
stage — lies in Tier B (§25), so the 1120 probe's findings are `measured/pending`
until S5 like every Tier B finding; the drawer's own behaviour (starts shut,
toggles, closes, takes Escape only while open) is held by `workspace.test.tsx`.

Overlap detection clips before it compares. `getBoundingClientRect` reports
where an element *would* be, so a row scrolled out of an inspector body still
reports a rect over whatever is painted there — which reads as an overlap
between two things nobody can see at once. Each element is therefore clipped by
every scrolling ancestor and by the viewport first, and one clipped to nothing
takes no part in the comparison.

Effective target sizes below 24×24 CSS px fail the `a11y.target-size` rule
(blocking at every tier since S6/X1): one discovery of what a pointer presses
(`a11y.mjs` `a11yPointerTargets` — native controls, a disclosure's summary,
widget roles, editable regions, the Scene Editor's `.scene-handle__hit`; never a
bare `[tabindex]`, which is a keyboard target), each measured by its effective
hit area — a checkbox or radio by the label that toggles it, a canvas handle by
its invisible hit circle (its 3.5px mark exempt, §10.1), everything else by its
own box — with the reading named in the finding.

## X1 (§23): the accessibility rules

Stage 3.5 S6/X1 closes the frozen §23 obligations as named rules in
`a11y.mjs`, each built on the T3 primitives (`zoomVisibility`, `zoomPaintsAt`,
`zoomOwn`) and, where a name or a role is the question, on Chromium's own
accessibility tree (`cdp.mjs` `axNames`: `Accessibility.getPartialAXTree`
per control — the computed name and the source that gave it). Nothing here is
an accessibility engine; every rule is one obligation.

| Rule | What it holds | Negative in `test/a11y.test.mjs` |
|---|---|---|
| `a11y.names` | every control has a computed name; where it shows a label, the name contains it (2.5.3, normalised: case, punctuation, whitespace); a `title` is never the only name — except the collapsed rail item (§23's one exception) | a label the name does not contain; an unnamed icon button; a title-only button |
| `a11y.form-fields` | every field labelled, never by its placeholder alone; an invalid field's error associated (`aria-describedby`/`aria-errormessage`) to rendered text and announced (`role=alert`/live) or focused | placeholder-only; unassociated; associated but silent |
| `a11y.role-contract` | referenced ids resolve; `aria-expanded` names a rendered region (or is a `summary`); an option holds nothing focusable; a listbox holds options; no native-equivalent role on a generic element, no native control re-roled; no naming is invented for `group`/`region` | each |
| `a11y.live-regions` | every live region rendered and outside `aria-hidden`; across a state's preparation no polite region appears already holding its message: a region the preparation inserts passes only if its text arrived in a later task than its insertion (a `MutationObserver` installed by `a11yLiveMark`, one callback per task, read by `a11yLiveCheck`) — a region that appears with its text in one task is an insertion to the accessibility tree, not a change; `role=alert`/assertive insert by contract; a region inside an overlay the preparation opened is mounted with it | a status inserted with its text; one mounted empty and filled in the same task |
| `a11y.tooltips` | a tooltip or `title` carries nothing required to operate: its control's name (N), the name with a key hint (K), a truncated value (V, §16), a timestamp's full form (F, §24), or text stated elsewhere on the page (S) | an instruction only in a tooltip |
| `a11y.shortcuts-in-text-entry` | the first text field focused, `?` (and Delete on the Scene Editor) pressed as real keys: no overlay opens, nothing is deleted, the key reaches the field (`probes.mjs`) | a handler that ignores the field; one that consumes the key |
| `a11y.tab-order` | per container, the keyboard visits the tab stops in the container's reading order (rows by overlap, left to right; a column-flow container down its column); adjacent stops never step back along a line, nor up a column where the composition is one; side-by-side containers are read one after another; a control placed by its data (an inline inset) follows the data (`a11yOrderFindings`, shared with the zoom lane) | reversed row; reversed column; an `order`-scattered grid |
| `a11y.state-cues` | a selected/current item differs from its peers by a non-colour property, a glyph, or a 3:1 luminance step (WCAG 1.4.1); invalid geometry is dashed; every badge has text and no two badges share text across tones; marker kinds differ in tick shape; an SVG mark by stroke width, dash, radius, or fill/stroke luminance | a same-lightness tint; solid invalid stroke; an empty badge; one tick shape |
| `a11y.focus-not-obscured` | after focus, a control's middle is not under a fixed or sticky painted layer (2.4.11 at the anchors; the zoom lane proves it at 200%) | a control under a fixed band |
| `a11y.spatial-twin` | every drawn `.scene-zone`/`.scene-line` has its `li[data-object-key]`, offering a control, naming a state, listing its actual coordinates (a zone: one per polygon vertex; a line: both endpoints); every timeline interval and marker is a named entry with its control | an object without a row; a row without coordinates; the wrong count; a marker without a control |
| `a11y.reading-order` | in a `tbody`, list, `dl`, the page's regions, a state region or the Context Bar, the document order of the rendered children is their visual order (1.3.2, non-focusable content included; absolutely positioned and data-placed children aside) | a reversed facts list; swapped regions |
| `a11y.text-spacing` | the lane (`--text-spacing only|none`): the WCAG 1.4.12 overrides served in the document head before first paint (`server.mjs` `TEXT_SPACING_CSS`), proven from computed style on every capture, at one canonical anchor of every distinct composition (`TEXT_SPACING_CONDITION`: 1366×768, 1024×768, 768×1024, 390×844) and each state's probe widths; every rule of the tier judges the case; the full sweep faults a planned spacing case missing or not in force (`engine.textSpacingCoverageFaults`) | content that clips only under the overrides |
| `a11y.hover-content` | the custom `Tooltip` driven through the input pipeline (`probes.mjs`): shown on focus and on hover, persistent while held, hoverable (the pointer moves onto it), dismissed by Escape without moving focus (not pressed while an overlay or inspector is open, whose Escape the exit probe judges), hidden once both leave; native `title` is the browser's and not driven | not hoverable; ignores Escape; fades under focus |

Stated limits: the names rule compares the computed name with the control's rendered text after a bounded normalisation (case, punctuation, whitespace); the state-cue luminance step composites every layer behind an element down to white, and reads only colours Chromium serialises as rgb/rgba (a `color()` result is never credited); a marked control with no sibling of its kind, in a row with no sibling row, is counted as unjudged (`measured.stateCues.unjudged`), never passed; the live-region rule judges mounting only across a state's preparation (the first load's loading → content transition is not judged) and counts frames by `requestAnimationFrame`; the tooltip rule's key hint is a bounded grammar (up to four words, no sentence punctuation, after the control's name); the spatial twin is held to the coordinates the drawing states in `data-points`/`data-endpoints`, in the list's own format; the hover probe does not press Escape on a trigger inside a closable overlay (its Escape is the exit probe's) and does not charge a focus move that came with an overlay closing; the shortcuts probe types into the first text-entry field only (number fields refuse the character by their nature); the reading-order and tab-order rules judge declared containers only, and treat a column-flow container as read down its columns.

## X4 (§13): reduced motion

`a11y.reduced-motion` is an assertion confined to its own lane (`lane:
'reduced-motion'`, blocking at A, B and C). A case of the lane loads the state
with Chromium emulating the preference itself — `cdp.mjs` `reducedMotion(true)`,
`Emulation.setEmulatedMedia` with `prefers-reduced-motion: reduce` — set on the
target before the case's first document. Every case sets it: `reduce` for the
lane, and `no-preference` pinned for every other case (`reducedMotion(false)`;
`null` clears the emulation), so no case inherits another's and no host setting
(an OS with animations off reports `reduce`) puts an ordinary case under reduced
motion. Every case proves the preference it ran under (`motionMedia`,
`a11y.mjs` `motionEnvironmentProblem`): a lane case that is not under `reduce`,
or an ordinary case that is, is not reached — a harness fault, never a pass. The lane's cases are the text-spacing
lane's: one canonical anchor per distinct composition (`REDUCED_MOTION_CONDITION`:
1366×768, 1024×768, 768×1024, 390×844 — 1440, 1920 and 2560 render Tier A's
composition again) plus each state's declared probe widths, judged by every rule
of their tier as well (a zero duration is behaviour too: a `transitionend` that
never fires).

| Part | What it checks | Fails on |
|---|---|---|
| the environment (`a11yMotionEnvironment`) | the preference read two ways that must agree: `matchMedia('(prefers-reduced-motion: reduce)')` and the CSS media evaluation of a probe element; a lane case where either is false is not reached (a harness fault, never a pass); an ordinary case where either is true likewise | a page that replaces `matchMedia`; emulation not applied; a reduced preference leaking into an ordinary case |
| the durations (`a11yReducedMotion`) | every element (rendered or not: a hidden element's transition runs when it is shown) and every `::before`/`::after` that generates a box: each entry of `transition-duration` and `animation-duration`, comma lists parsed, `s` and `ms`, must be 0 — strictly, whether or not keyframes or properties are named | a transition or animation left running; one non-zero entry in a list; a duration the harness cannot read |
| running animations | `document.getAnimations()`: an animation `running` at a non-zero rate whose iteration duration is positive — a CSS animation or transition the stylesheet missed (on any pseudo-element, `::marker` included), or a script-driven Web Animation the stylesheet cannot reach; a zero-duration, paused or finished one moves nothing and passes; a duration that is not a number (a timeline-relative one) is unreadable, a fault | a script `element.animate()` with a duration |
| coverage (`engine.reducedMotionCoverageFaults`, full sweep and aggregate) | every planned lane case ran, was reached, had the preference proven and judged at least one element | a composition or probe width missing; a case not reached, not proven or judging nothing |
| the control (`engine.normalMotionControlFaults`, full sweep and aggregate) | the ordinary cases, under the pinned normal preference, saw the activity pulse, the spinner and a transition run at a positive duration | a control that saw none of a site — the lane's zero for it would be unproven |

The control: every ordinary case measures, without judging, the motion its page
has under the normal preference (`normalMotion`: per site, the longest duration)
— the activity pulse at `--dur-pulse` (1.2s), the spinner at `--dur-spin` (0.8s),
the `--dur` (120ms) transitions — so the contract is proven to suppress motion
that exists, not motion that was never there; the full sweep faults if the
control saw the pulse, the spinner or a transition nowhere. The report states
both.

Stated limits: the computed durations read are each element's and its
`::before`'s and `::after`'s (the product styles no other pseudo-element with
motion); a `::marker`, `::placeholder` or `::selection` transition is not read
from computed style, though one *running* is caught by `getAnimations()`.
`getAnimations()` is a snapshot of the settled state, the document's own (no
iframes exist): a script animation that started and finished before it, motion
driven by `requestAnimationFrame` writing styles, and SMIL `<animate>` are not
seen — the product has none (its `requestAnimationFrame` uses are announcer and
layout timing). Smooth scrolling (`scroll-behavior`, `behavior: 'smooth'`) is not
a duration and is not read — the product uses neither. Delays are not judged (a
delayed zero-duration animation moves nothing). Strict, as §13 reads: a non-zero
duration fails even where no property or keyframes use it. Only the DOM present
at the settled state is judged; tooltips and overlays the later probes open are
covered by the universal `*` rule but not read.

## X3 (§38): the performance budgets

`perf.cls`, `perf.long-tasks` and `typography.resolved-font` are assertions
with their own producer (`producer: 'performance'`), blocking at every tier.
A case records its measurements raw (above); the **performance gate**
(`performance.mjs`) judges them against the one budget source,
`performance-budgets.mjs`, over the whole product — never a case its own, and
never the sweep's contended lanes for long tasks. Nothing is owned by X3:
`validateManifest` refuses an X3 owner anywhere.

- **Navigation CLS** by surface × tier, **preparation CLS** by surface ×
  transition (`by`): two families, each judged on its own, so a good
  navigation never excuses a bad state change. An explicit class names its
  states and is judged before its surface's. A new state on a known surface
  and tier inherits that class; a new surface, or a new preparation
  transition, has none and is a harness fault until it is qualified — a
  navigation budget is never lent to a preparation.
- **Long tasks**: the single-lane run (`run.mjs --long-tasks`, one worker:
  every state that declares an interaction, at its ordinary anchors and
  probes). A default class for every interaction, one for Search result
  selection (P1's only interaction with a long task) and, since the
  2026-10-29 long-task recalibration, one for the cold first interaction of
  three form-entry and rail interactions at 1366x768 (a class may name
  viewports; elsewhere its interactions are the zero class); their counts and
  durations are the budget source's, never restated here. A run on more
  lanes, or not the lane, is a fault.
- **Fonts**: the text renders in a platform font and the document holds no
  font face (`document.fonts.size`), so nothing can arrive late and swap. The
  resolved family is a diagnostic; no family is required across systems.
- Comparison in integer units (CLS in 1e-4, milliseconds whole): a value at
  `reference + tolerance` passes, one unit over fails.
- **The calibration's measured cases are the floor**: the budget source lists
  every case the calibration measured (both Linux samples agreed exactly); one
  that now answers `not-applicable` — its loading presentation renamed or
  removed, its interaction gone — is a fault, so nothing stops being judged
  without a person requalifying it.
- **Faults, not findings**: a measurement missing, `failed` or `unsupported`; a
  planned case missing, unplanned or twice (the plan is derived from
  `states.mjs`, not from the results); a case no class covers; a malformed
  budget table; results of different heads. Exit 2 for a fault, 1 for a
  finding.
- **Attribution, recorded and never judged**: a measured CLS window lists the
  data responses that landed in it (`cls.responses`: path and time) and each
  counted shift says where its sources moved (`entries[].moves`, previous and
  current rect); a long-task window lists the long animation frames that
  overlap it (`longTasks.frames`: duration, style-and-layout time and the
  scripts by entry point and source position). A finding can then be read from
  its own artifact: a shift right after a late response is the page
  re-laying out for that data; a long frame whose time is neither script nor
  style and layout is not the page's code.
- **Response order** (owner decisions, 2026-10-13 and 2026-10-15): the gate
  judges runs whose data responses were answered one at a time in the order
  the page issued them, so every intermediate layout of a load is painted and
  a case's CLS is a function of the bundle alone
  (`docs/reviews/2026-10-13-x3-performance-gate-determinism.md`, *CDP-forward
  method*; ADR-012 Decision 15). Under `MAVI_VQA_RESPONSE_ORDER=forward` —
  the sweep and the long-task lane; the judge faults any other run
  (`GATE_RESPONSE_ORDER`, `GATE_REQUEST_ADMISSION`):
  - the page numbers every schedulable request as it is made
    (`request-identity.mjs`: same origin, under `/api/`, any method, not a
    video stream — `request-class.mjs`, one rule for page and server);
  - the browser holds every `/api/` request before connection-pool admission
    (CDP Fetch) and `admission.mjs` admits the numbered ones in issue order,
    the next only on the server's exact acknowledgement of the previous
    identity or Chromium's report that it failed; the qualified artifact
    image (`/api/artifacts/{id}/content`) and video streams continue at once,
    outside the order; any other unnumbered request is a harness fault, and
    a second document becoming current within one admission window is too;
  - admission binds the fixture server to the case's document before its
    first request is released; the server refuses any other document's
    identity-bearing requests (a document the harness left, whatever epoch
    cookie it sends) before any fixture state, recorded but not a fault, and
    refuses a duplicate or out-of-order number of the bound document (a
    fault);
  - the fixture server answers the accepted ones in that order,
    `RESPONSE_SPACING_MS` apart; each case is one scheduler generation (a
    reset cancels the previous one's timers, drops its queue and clears the
    binding), and the epoch cookie remains a redundant defence.

  Each case's `requestTrace` (diagnostic) keeps the page's issue order, the
  admission order, the browser's transport outcome, the server's arrival and
  answer, and the page's completion times. `natural` (the default for local
  runs and the journeys) answers as requests arrive, with no identity or
  admission.
- **Drawn once**: the product draws a region when every answer that decides
  its final layout has settled (`holdUntilSettled`, §38), so the pinned order
  measures the loading-to-content transition, not a provisional layout. A
  per-row lookup never holds a ledger: the row draws at once in its final
  geometry, its pending values held by unseen placeholders.
- **One operator input per task**: a preparation that stands for several
  operator inputs (the Import form's camera, time and file) dispatches each in
  its own task, after a frame, as an operator's inputs arrive (the zone
  drawing's two vertex clicks likewise); dispatched back
  to back they were one task, and the lane measured three inputs (and the
  harness's own script) as one long task.

```bash
node tools/web-visual-qa/performance.mjs --sweep <aggregate results.json> --long-tasks <long-task results.json> [--out <dir>]
```

The **budgets are generated, never typed**: `performance-calibrate.mjs` derives
them from the P1 baseline and a same-head calibration — two Linux CI samples
(the enforcement environment), an uncontended Windows sweep and two
single-lane long-task runs (continuity with P1, which was measured on
Windows) — and the owner's recorded decisions (`DECISIONS`: the tolerances and
why, the explicit and environment-calibrated classes and why). Reference =
min(P1 class maximum, Linux class maximum), the ratchet; tolerance from
same-head repeatability per tier. It prints the review table and, with
`--write`, regenerates `performance-budgets.mjs`; it refuses to write while
the calibration contradicts a decision, or when a preparation transition P1
never measured has no decision (each is qualified by state, with its reason). The register's P1 row carries the
budget block, and `test/performance.test.mjs` fails if they disagree.

The long-task classes are owner decisions (`DECISIONS.longTasks`), not
derived values: the calibration's long-task runs only check them. To
re-decide them on new evidence without re-deriving any CLS class,
`--long-tasks-only --linux-long-tasks x.json,y.json [--windows-long-tasks …] [--linux-runs "<provenance>"]`
takes two single-lane Linux runs of one head and regenerates only the
long-task table. Every CLS class, its calibration and its measured sets are
carried byte for byte, and the write is refused if an interaction case that
was measured before is no longer measured. The first such recalibration
(2026-10-29) is recorded in the register with its evidence in
`docs/qualification/stage3-5/x3-long-task-recalibration-evidence.json`.

In CI, `performance-long-tasks` runs the lane in parallel with the sweep, and
`performance` (*performance budgets*) judges the visual aggregate and that run
of the same head; `quality` requires both. `performance-qualification.mjs`
generates `docs/qualification/stage3-5/s6-x3-performance-qualification.json`
from the head's CI evidence (and, for continuity, a Windows run of the head).

The qualification attaches to the **implementation head** the artifact names.
A later **closure head** that changes only documentation or CI wiring carries
it instead of sampling the same implementation again: both performance jobs
first run `performance-closure.mjs --decide`, which chooses `closure` only when
the artifact passed, its implementation head is an ancestor, and every path
changed since is closure-safe (`CLOSURE_SAFE`); the `performance` job then
confirms the implementation head's own Quality Gate run succeeded. Anything
else — product, harness, budgets, fixtures, dependencies — is `measure`, the
default whenever the decision is anything but `closure`.

## X2 (§23, plan §5.3): keyboard-only operator journeys

`a11y.keyboard-journeys` is an assertion with its own producer (`producer:
'journeys'`): blocking at Tier A and Tier B, not applicable at Tier C (no
workflow acceptance is claimed there — §25, T2). A journey crosses routes, so
it is never a sweep case: the sweep neither evaluates the rule nor faults for
not having done so (`engine.mjs` `vacuous` skips producer rules, `resolve`
refuses them in a case), and the journey aggregate is its evidence.

`journeys.mjs` runs the six frozen journeys of plan §5.3, registered in
`journey-registry.mjs` in the plan's order, and after them the journeys a later
plan appends (`LATER_ORDER`, each naming its plan; the six are never renamed,
merged, dropped or reordered), at the workstation compositions
(`JOURNEY_CONDITION`: 1366×768 Tier A, 1024×768 and 768×1024 Tier B) — 21
executions — the browser launched in `en-GB` (`--lang`) and the page's locale
emulated the same:

| # | Journey (`id`) | Starts at | What the operator does, by keyboard |
|---|---|---|---|
| 1 | Import → Process → Status → Results (`import-process-results`) | `/import` | camera, recording date and time, the MP4 by the file chooser, Import and process; the run's status while it runs and when done; Open results |
| 2 | Search → filter → scan → inspect → evidence → return (`search-inspect-evidence`) | `/search` | Object class Person, Search (the Filters drawer at Tier B); select a result, `j` `j` `k` `k`; the Evidence Player's `End`, `Home`, `→`; Open the review; the breadcrumb back; `Esc` — focus on the same result |
| 3 | Vehicle search → Car refinement → inspect → Review (`vehicle-car-review`) | `/search` | Vehicle, Search; Vehicle type Car, Search (the server's `objectSubclass=car`); inspect; Open — the review of that car |
| 4 | Configure scene → analyse → search analytic → why matched → inspect (`scene-analytic-why`) | `/cameras/{id}/scene` | Zone tool; on the frame, Shift+arrows and Space place four vertices, Enter completes; name it; Save revision; Processing → the video's detail → Re-analyse camera; Open results; Zone the new zone, Search; inspect — Scene analytics names the zone and revision 5 |
| 5 | Cameras / Videos / Processing monitoring (`monitoring`) | `/` | the rail to Cameras (24 cameras), a row's action; Videos (24), the failed video's Retry; Processing, the failed run's detail and its Retry processing |
| 6 | Error / retry / recovery (`error-retry-recovery`) | `/search` | Load more; the continuation fails (its own retry too); Retry load more; page two arrives, the snapshot ends — focus on its first new result |
| 7 | Plate search → inspect → seek (`plate-search-inspect-seek`; Stage 4 plan PR-5) | `/search` | Plate text `zz-00-ts-0001`, Exact, Search (the Filters drawer at Tier B) — the server's `plateText=ZZ00TS0001&plateMatch=exact`; the coverage line and the result's "Read as" name; inspect — each plate region drawn; View source at 00:02.2 — the player at 2.2 s, Near view inspected; the Late diverse crop — inspected, the player not moved |

**Real keys only.** After the one direct load of the journey's start, every
action is a key through the input pipeline (`cdp.mjs` `press`: `rawKeyDown`,
`char`, `keyUp`) — Tab, Shift+Tab, Enter, Space, Escape, arrows, Home/End,
`j`/`k`, the Evidence Player's grammar and the Scene Editor's. The operator
object (`createOperator`) is all a journey is given: `press`, `type`, `tabTo`,
`until`, `route`, `requested`, `chooseFile`, `enterDateTime`, `done`.
`enterDateTime` reads the focused `datetime-local`'s segment order from its
rendering (`DOM.describeNode` with `pierce`, observed, never set) — day, month,
year, hour, minute and, on a 12-hour clock, AM/PM follow the host's locale,
not the page's — and types each segment with keys. `tabTo` presses Tab (or
Shift+Tab) up to a strict bound and matches the focused control by its
accessible name and role from Chromium's accessibility tree (`axNames`), and,
where names repeat, by its row's text or its labelled landmark or group
(`within`); each stop is recorded and judged like any focus (lost, hidden or
covered on the way fails — the document only where a Tab left the page from
its last control, the browser's own cycle); never reached is a failure.
Checkpoints observe and never act: they are evaluated with V8's side-effect
check (`Runtime.evaluate` `throwOnSideEffect`), so one that would click, focus,
write a value, navigate or store fails the journey before it runs.
`requested` looks only at requests made after the operator's last key.

**The file chooser.** `chooseFile` requires focus on an `input[type=file]`,
presses its key (Enter), waits for `Page.fileChooserOpened` from the
interception the lane enabled, requires the chooser to belong to the focused
node, and only then answers it with the lane's upload fixture
(`DOM.setFileInputFiles` on that node). The boundary — the OS dialog is
outside the product — is recorded on the step.

**What is judged at every step** (`journeyFocusState`, the page guard): focus
exists, is not the document, is rendered and in view, is not under another
element at its middle, is inside an open modal overlay when there is one, is
not inert; a file input not itself drawn (the FileInput's transparent input,
framed by its `:focus-within` ring) is shown by its own visible label, judged in
its place — X1's rule, confined here to file inputs. The guard
(`JOURNEY_GUARD`, before every document) records trusted pointer, touch and
wheel input, scripted clicks and key, input, change and submit events, and
numbers each document: a
pointer event, a scripted event or a document after the start (a direct
navigation) fails the step. A keyboard-activated control's trusted `click` is
keyboard input and passes. Waits poll conditions (no fixed sleep); a bound
passed is a failure naming the step.

**The backend answers the operator.** The fixture server's scenario forms
`{ after: 'METHOD /path', before, then }` (an answer that changes only once
that request was received; nestable) and `{ query: [{ match, then }],
otherwise }` (by the request's query) make each journey's backend respond to
what the operator caused: the import exists after the operator's import,
revision 5 after their save — whose JSON body the request log keeps and the
journey checks (`requested(..., { body })`) — the continuation fails because
the operator asked for it. Setup before the start replaces no operator action.

**Evidence.** Each execution writes its steps — journey, step, action and key,
focus before and after (role, name, landmark), route before and after, the
expected and observed checkpoint, the Tab stops, pass — and its terminal
checkpoint, key count, pointer and scripted event counts, documents after the
start; a failure keeps the page's route, text, the request log and a capture
(diagnostic, never qualification evidence).

```bash
node tools/web-visual-qa/journeys.mjs --workers 3
```

`--journeys a,b` and `--viewports 1366x768` select (a selection is never X2's
evidence); `--shard i/n` runs execution k where k mod n = i;
`--aggregate --out DIR file…` proves the shards whole: same head and plan, the
registry's whole plan, every execution exactly once, none at Tier C, every pass
carrying its evidence (no pointer, nothing scripted, one document, a terminal
checkpoint), every shard having run this head's registry (its source hash; a
shard refuses `MAVI_VQA_JOURNEYS_MODULE`), no harness error. An `{ after }`
flips only on a mutation (a GET is a read the application may make by itself). Exit 0 all passed, 1 a journey failed, 2 a
harness fault. CI: `keyboard journeys shard 0–2` and `keyboard journeys
aggregate`, required by `quality`.

Stated limits: the journeys run against the fixture server and the production
build, not a live API; what the OS file chooser shows is outside the product
and is not driven (it is intercepted and answered). The journeys prove the
paths operators take complete by keyboard with focus valid throughout; they do
not prove every control on every surface is keyboard-operable (the X1 rules and
the sweep's focus checks do that per state), nor screen-reader announcements
beyond the accessible names they match. Tier C is not run.

## What still needs a person

Everything §26 lists that a machine cannot judge: weak text, unexpected bright
borders, wrapping that destroys density, oversized whitespace, colour-role
collisions, nested cards, and whether evidence geometry is actually readable
over each footage condition. Look at `.captures/`.

The focus check proves a ring is *painted*; whether it is legible against the
surface it lands on is the contrast suite's job for the token, and the capture's
job for the rendered result.

## Fixtures and footage

`fixtures/*.json` are served for `/api/...`; a file name is the path with `/`
replaced by `_`. The Stage 4 plate states (UI spec §17.2.8) and the plate
journey are served from `plate-fixtures.mjs`, shaped to the backend's plate
contracts (`TrackPlateContracts.cs`), with synthetic plate text only; their
source crops are `crops.json` `eeeeeee4`–`eeeeeee7`, cut at boxes the 1920×1080
footage divides exactly, so each plate region is drawn rather than refused. A state can override one in `states.mjs`: a literal value is
served as the response, `'unavailable'` answers 503, and `'hang'` never answers,
which is how the loading state is held still long enough to look at; such a
state declares `holds: 'loading'`, and settles on its loading presentation.

Footage is **generated by ffmpeg at run time**, not committed: the repository
does not carry video datasets and `tools/verify_repo.py` enforces that.
`footage.mjs` defines the five conditions §26 requires — bright, dark,
saturated, low-contrast and a 21:9 source for letterboxing — as deterministic
`lavfi` sources, encoded VP9/WebM because the Chromium builds used here carry no
H.264 decoder.

Captures land in `.captures/`, which is gitignored. §26: *"Generated
screenshots are working artefacts and MUST NOT be committed."*

Nothing here requires production code to be altered to make inspection easier,
which §26 also requires.

## S1.4 B3 asynchronous completion states

`processing-finalizing` and `processing-failed-finalization` are the operator states
of the asynchronous completion path (S1.4 B3 F4 plan §15.3). They are fixture data in
the shape `GET /api/videos/{id}/processing` returns, never real-video evidence. They
state the acceptance of the separate Finalizing UI PR (U1): a Finalizing job reads as
"Finalizing" rather than "Progress" and shows no count before publication, and a failed
finalization reads as "Finalization failed" with its `vision_finalization_*` code.

Until U1 lands, both states fail. That is the truthful result for B5
`finalizingStateDistinct` and `failedFinalizationDistinct`, not a harness defect.
Exclude them with `--states` only for work that does not own them.
