# Visual QA harness

The repeatable procedure behind **§26 Visual QA standard** of
`docs/architecture/ui-ux-design-specification.md`.

§26 is normative and explicitly says unit tests do not satisfy it: focus
visibility, contrast as rendered, ultra-wide structure and overlay legibility
over real footage are not things jsdom can answer. This harness drives the real
production bundle in a real browser at the four acceptance widths, asserts what
can be asserted, and writes screenshots for the part that still needs a person.

## Running it

```bash
cd src/web/mavi-web && npm run build      # the harness runs the real bundle
cd - && node tools/web-visual-qa/run.mjs  # or add --build to do both
```

Useful flags:

| Flag | Effect |
|---|---|
| `--build` | run `npm run build` first |
| `--states cameras,search` | only these states (see `states.mjs`) |
| `--widths 1366,2560` | only these viewports |
| `--keep` | report findings but exit 0 |

Exit code 1 means an automated assertion failed. **A clean exit is necessary,
not sufficient** — §26 requires looking at the captures.

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
lives in `tools/`, outside the frontend package, and CI does not run it.

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

The four widths are the §25 acceptance viewports, so the Workbench's drawer
band — 1101 to 1149, where the inspector covers the stage — is outside them by
construction. Check it deliberately with `--widths 1120`; the drawer's own
behaviour (starts shut, toggles, closes, takes Escape only while open) is held
by `workspace.test.tsx`.

Overlap detection clips before it compares. `getBoundingClientRect` reports
where an element *would* be, so a row scrolled out of an inspector body still
reports a rect over whatever is painted there — which reads as an overlap
between two things nobody can see at once. Each element is therefore clipped by
every scrolling ancestor and by the viewport first, and one clipped to nothing
takes no part in the comparison.

Effective target sizes below 24×24 are reported per state in the JSON beside
each capture rather than failed, because §10.1 allows small canvas handles with
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
which is how the loading state is held still long enough to look at.

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
