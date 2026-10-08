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
| `--workers 3` | parallel lanes (default: CPUs − 1, at most 4) |
| `--repeat 5` | prepare every selected case this many times, independently, and require one settled state |
| `--keep` | report blocking findings but exit 0 |

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
where code exists (`review.sticky-rendered`, `containment.depth`, the §25 tier
rules, the P1 measurements) and declared `future` with an execution policy where
it does not yet (200% zoom, reduced motion, keyboard journeys, the remaining
§23 rows).

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
DOM has stopped changing; and no request is in flight or newly started. A
request held open to keep a loading state is not "in flight" — it never
completes by design. Preparations wait for the consequence of each action, never
for a guessed duration. Every wait is bounded; a timeout refuses the state and
says what was still pending. Two deliberate exceptions, both documented in the
code: a footage state re-issues its seek at a bounded interval until the overlay
is drawn over a decoded frame (media decoding exposes no completion the page can
await), and `search-analytics-scene-degraded` moves the page clock past the
30-second stale time instead of sleeping through it.

**Measurements** (P1, V5), recorded per capture, never pass/fail:
cumulative layout shift during each loading-to-content transition (Layout
Instability API): the navigation's, from its first loading presentation to the
settled state (`perf.cls`), and — kept apart — one a preparation starts, from
that loading presentation to the state settling after it (`perf.clsPreparation`,
labelled with the interaction or `fixture preparation`); harness activity
between the two is in neither, and a transition that did not happen is
`not-applicable`, never 0. Long tasks during the state's first operator
interaction (`perf.longTasks`): only where the state names one (`interaction` in
`states.mjs` — a click, a submit, a key press), from the action until the settle probe
that confirmed its outcome, with the observers flushed (a long task that ran one of the harness's
settle probes is excluded and counted as `excludedAsHarness`); a preparation
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

Effective target sizes below 24×24 are reported as the `a11y.target-size` rule,
`measured/pending` against S6 / X1, because §10.1 allows small canvas handles with
a large hit area and requires a documented exception, not an automatic failure.

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
replaced by `_`. A state can override one in `states.mjs`: a literal value is
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
