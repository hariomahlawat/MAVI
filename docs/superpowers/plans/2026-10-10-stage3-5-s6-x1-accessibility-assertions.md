# Stage 3.5 — S6/X1: every §23 obligation asserted (implementation plan)

**Status:** plan, cold-reviewed; no production or harness change made. Implementation opens as one PR after the owner has read this.
**Register row:** X1 — "Every §23 obligation asserted on every surface by the harness or by `styles/contrast.test.ts`, their manifest entries flipped to `blocking`; WCAG 1.4.10 at 320px recorded as not targeted and the Workbench canvas at 200% zoom on 1366 recorded as a 1.4.4 exception."
**Not in this plan:** X2 keyboard journeys, X3 performance budgets, X4 reduced motion, S7 closure.

## 1. Baseline

- `main@5db448a3` — the PR #201 merge (S5/T3). The acceptance register (`docs/reviews/2026-10-07-stage3-5-ui-ux-professionalisation-acceptance.md`) records T1, T2 and T3 PASS; X1–X4 and C1–C5 OPEN.
- Authoritative documents: the frozen specification `docs/architecture/ui-ux-design-specification.md` — §23 (Accessibility), §10.1 (Target size), §5 (skip link, landmarks), §15/§20 (Dialog/Drawer), §25 (tiers), §26 (harness and manifest), §34.2 (conformance per slice); the plan `docs/superpowers/plans/2026-10-07-stage3-5-ui-ux-professionalisation.md` §13 (accessibility strategy) and §15 (slice S6); ADR-012.
- Harness: `tools/web-visual-qa` (`manifest.mjs`, `assertions.mjs`, `engine.mjs`, `run.mjs`, `states.mjs`, `test/*.test.mjs`); static tests `src/web/mavi-web/src/styles/contrast.test.ts` and `tokens.test.ts`.
- Evidence read for this plan: the T3 exact-head full sweep on `6dffe137` (2,002 captures, 0 blocking; 87 `a11y.target-size` measured findings).

## 2. X1 scope

**Included.** Executable proof, on every applicable surface and tier, of each §23 row that has none today; the two product defects and one specification gap the target-size evidence exposes; the manifest transition that retires the placeholders `a11y.target-size` (measured/pending) and `a11y.section23-remaining` (future) for named, blocking entries; the register row X1 citing the manifest change, the 1.4.10 non-claim and the Workbench 1.4.4 exception (both already recorded by T3 and §23 — X1 cites, it does not re-record).

**Excluded (frozen elsewhere).** `prefers-reduced-motion` (X4, `a11y.reduced-motion`); the six keyboard-only journeys (X2, `a11y.keyboard-journeys`); performance budgets (X3); 200% zoom (T3, done); any change to T1/T2/T3 acceptance semantics; WCAG 1.4.10 at 320px (not targeted, §23); a third-party accessibility engine (§23, §34 item 11); mobile-workstation scope (§31); pixel baselines (§26); new dependencies; backend/API/domain changes.

## 3. §23 coverage matrix

Columns: requirement · surfaces/tiers · existing evidence · rule/test · sufficient? · gap · X1 change (product / test / manifest / none) · negative test · disposition.

| # | §23 obligation (exact) | Surfaces / tiers | Existing automated evidence | Proving rule / test | Sufficient? | Gap | X1 change | Negative test | Disposition |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Text contrast ≥ 4.5:1 | All; tier-independent (tokens) | `contrast.test.ts` "text contrast (4.5:1)": every text token on every surface token; error text per form surface; disabled label; text on `--accent-strong` | static | Yes for the pairs enumerated; the enumeration must be shown complete | Audit: every `color:` token used by a stylesheet (`tokens.test.ts` already forbids literals) against every `--surface-*` it is painted on | test (extend tables if the audit finds a pair outside them) | A pair deliberately set below 4.5:1 in a scratch copy fails | **Already proven**; coverage audit in X1 |
| 2 | Non-text contrast ≥ 3:1: control boundaries, state indicators, graphical information, focus indicators (decorative dividers exempt) | All; tokens | `contrast.test.ts` "non-text contrast (3:1)": invalid boundary, scrollbar thumb, focus ring (`--focus-ring` on every surface), decorative dividers exempt on purpose; "evidence and spatial legibility"; "heatmap scale" | static | Yes for boundaries, focus ring, evidence hues, heatmap; **state indicators** (badge tones `--status-*` on their surfaces) to be confirmed in the tables | Audit badge/tone tokens × surfaces | test (extend if missing) | As row 1 | **Already proven**; coverage audit |
| 3 | Visible focus on every interactive element; never suppressed without an equivalent | All; A/B/C | `a11y.focus-visible` (blocking A/B/C since S1/T1/T2); `harness.focus-coverage` (every discovered control focus-checked or skipped for a named reason) | harness | Yes | — | none | exists (`assertions.test.mjs`) | **Already proven** |
| 4 | A control's accessible name **contains its visible label** | All; A/B/C | None. `tier.c-shell` checks the menu control and Context Bar actions are *named* (not that the name contains the label); `overlay.*` check the modal's name | — | No | Computed name (aria-labelledby → aria-label → content/`alt`/`<label>`; `title` last) must contain the control's visible text, whitespace-normalised, case-insensitive | test: new harness rule **`a11y.names`** | `<button aria-label="Save draft">Save</button>` passes (contains); `<button aria-label="Submit">Save</button>` fails | **X1 work** |
| 5 | Semantic HTML first; ARIA only where semantics are unavailable | All (source) | None executable; the codebase uses `role=` for status/group/region/presentation/tooltip/progressbar/img/dialog/alert only (audit of `src/**/*.tsx`) | — | No | A deterministic static test, not browser geometry: no `role` with a native equivalent (`button`, `link`, `checkbox`, `radio`, `textbox`, `list`, `listitem`, `heading`, `table`, `row`, `cell`, `navigation`, `main`, `banner`) on a generic element | test: `src/web/mavi-web/src/styles/aria.test.ts` (static, vitest) | A fixture string `<div role="button">` fails the matcher | **X1 work** (static) |
| 6 | A role's contract honoured or the role not claimed (no focusable children in a `listbox` option; `aria-expanded` requires a controlled region) | All; A/B/C | None for the contract; `pressed.visible` for `aria-pressed`; `overlay.*` for `dialog` naming | — | No | `[aria-expanded]` has `aria-controls` resolving to an element (or is `summary`); `[role=option]` has no focusable descendant; `[role=group|region]` named; `[aria-controls]` resolves | test: new harness rule **`a11y.role-contract`** | An expanded button without `aria-controls` fails; an option containing a button fails | **X1 work** |
| 7 | Status regions mounted before populated, so a mode change is announced | All; A/B/C | None. Live regions in the product: `AppShell` api-health (`role=status aria-live`), `AttentionRegion` lines, `TrackInspector` position, `EvidenceTimeline` navigator status, `LoadingState`/`EmptyState` (`role=status`), Scene Editor notices (`role=status`, rendered conditionally **with** their content), `SceneToolbar` refusal (`role=alert`) | — | No | Harness: every `[aria-live]`, `[role=status]`, `[role=alert]` rendered, not inside `aria-hidden`; and, where the harness observes loading→content (`perf.cls` window), the page's state region persists as one mounted element. Unit: each component that announces a change keeps its region mounted across the change (the conditional Scene Editor `role=status` paragraphs are the candidates for a product change: mount the region, toggle its text) | test (harness **`a11y.live-regions`** + vitest per component); product if the audit confirms the conditional regions | A region inserted together with its message fails the unit test; a hidden live region fails the harness rule | **X1 work** |
| 8 | Form fields labelled | Record/Investigation/Ledger filters/Workbench inspector; A/B/C | `Field` primitive binds `label[for]`; no harness proof over rendered pages (raw inputs outside `Field` exist: the `.checkbox` labels, toolbar inputs) | — | No | Every visible `input`/`select`/`textarea` has a label: `label[for]`, wrapping `label`, `aria-label` or `aria-labelledby` — a placeholder alone is not one | test: new harness rule **`a11y.form-fields`** | An input with only a placeholder fails | **X1 work** |
| 9 | Errors programmatically associated (and announced — amended row) | Validation states: `cameras-create-error`, `import-submit-error`, `search-invalid`, `search-field-errors-above`, `scene-editor-save-error`; A/B/C | `Field` sets `aria-invalid` + `aria-describedby`; no proof over rendered states | — | No | `[aria-invalid=true]` has `aria-describedby`/`aria-errormessage` resolving to rendered text; the message is inside `role=alert` or a live region, or the field is focused on submit (scroll-to-invalid, §16) | test: part of **`a11y.form-fields`** | An invalid field whose message is not referenced fails | **X1 work** |
| 10 | `prefers-reduced-motion` honoured globally | All | `tokens.test.ts` forbids duration literals outside tokens; emulation pass not built | `a11y.reduced-motion` (future, X4) | n/a to X1 | — | none | — | **Out of X1 scope** (X4) |
| 11 | Non-colour cue for every status and every evidence distinction | Ledgers, Overview, Review, Analytics; A/B/C | `StatusBadge` always renders text (`labelForStatus`); `contrast.test.ts`: evidence hues distinct and each role its own value, heatmap monotonic in luminance (reads without colour); timeline markers carry `data-kind` | static, partial | Text labels prove statuses; evidence **marker/interval** distinction by shape or glyph is not proven | Harness: every `.badge`/`[data-status]` has text; unit: `labelForStatus` distinct per status; audit `EvidenceTimeline` marker kinds for a non-colour distinction (glyph/stroke pattern) — product change if colour is the only cue | test: harness **`a11y.non-colour-cue`** + vitest; product if the audit finds a colour-only distinction | An empty badge fails; two statuses with one label fail | **X1 work** (audit may add one product change) |
| 12 | Effective pointer target ≥ 24×24 CSS px wherever practical; smaller targets need a documented exception (§10.1) | All; A/B/C | `a11y.target-size` measured/pending at A/B/C; 87 findings on `6dffe137` reducing to **two product root causes** (§4) | harness | No (two defects, one named exception, flip pending) | Fix the two defects; measure the *effective* target (the wrapping `label` of a checkbox/radio is its hit area); flip to blocking | product + test + manifest | A 14px checkbox without a 24px-tall label fails; a chip button shrunk by a long value fails | **X1 work** |
| 13 | Small visible canvas handles keep a 24×24 invisible hit area (§10.1) | Scene Editor (object/vertex selected); A/B (canvas not rendered at C) | None: the rule queries `button, a[href], input, select` — the SVG `.scene-handle__hit` is not measured. **Measured in code: `HANDLE_HIT_R = 11` → a 22px hit circle, under the 24px the specification requires** | — | No | Product: `HANDLE_HIT_R = 12`; harness: `.scene-handle__hit` bounding box ≥ 24×24 in the selected states, the `__mark` exempt by name | product + test (within `a11y.target-size`) | r=11 fails (22px) | **X1 work** (product defect) |
| 14 | Accessible twin for spatial content — canvas: a list naming each object, its state and its coordinates; the twin is the same control the pointer uses | Scene Editor; A/B; C n/a (unsupported state, no canvas) | `SceneObjectList` renders `ul[aria-label=Zones]`/`[aria-label="Trip lines"]` rows with selection; coordinates live in the properties panel, **not in the row** | unit tests of the list (selection) | No: "its coordinates" is not shown to be in the twin | Harness: drawn objects (`.scene-object` polygons/lines) count = list rows; each row names state (selected/invalid/disabled) and carries a coordinates summary; product: add a compact coordinates summary to each row if absent (audit at implementation) | product (likely) + test: harness **`a11y.spatial-twin`** | A drawn object with no row fails; a row without coordinates fails | **X1 work** |
| 15 | Accessible twin — every timeline interval has a list entry | Review (timeline); A/B/C where the timeline renders | `EvidenceTimeline` renders one `li` per interval and per marker, each the pointer's control | unit tests | Partly (no rendered-page proof) | Harness: `.evidence-timeline__interval` rows = intervals in the fixture; each has a name | test: within **`a11y.spatial-twin`** | An interval drawn without its `li` fails | **X1 work** (assertion only) |
| 16 | Tooltips carry no required information; `title` alone is never a control's only label (collapsed rail item the one exception) | All; A/B/C | None. `AppShell.tsx:273` sets `title` on the collapsed rail item (which also carries its label text) | — | No | Within `a11y.names`: a control whose only name source is `title` fails, except `.rail` items while collapsed; `role=tooltip` content is never the sole name | test: **`a11y.names`** | A `<button title="Delete">` with no text/aria-label fails | **X1 work** |
| 17 | Keyboard shortcuts do not fire in text-entry contexts | Shell (`?`), Search, Player, Scene Editor | `useGlobalShortcuts.ts` text-entry guard; unit tests: `AppShell.test.tsx:431`, `VisualSearchPage.test.tsx:1147`, `EvidencePlayer.test.tsx:291`; **Scene Editor keys (Delete, nudge) — no test found** | vitest | Mostly | One unit test for the Scene Editor's keys while typing in the inspector | test (vitest) | A Delete pressed in a focused field that removes the object fails | **X1 work** (one test) |
| 18 | Skip link and landmarks (§5) | All; A/B/C | `a11y.skip-link`, `a11y.landmarks` blocking | harness | Yes | — | none | exist | **Already proven** |
| 19 | Drawer and dialog focus management (§15, §20) | All overlays; A/B/C | `overlay.dialog`, `overlay.drawer` blocking (placement, containment, Escape, restoration, `inert`) | harness | Yes | — | none | exist | **Already proven** |
| 20 | Every drawer, dialog, menu and disclosure keyboard-complete | Overlays, shell menu, disclosures | `overlay.*` (Tab, Shift+Tab, Escape); `tier.c-shell` + `a11y.zoom-200` (menu); disclosures: native `details` or `aria-expanded` buttons | harness, partial | Yes for overlays and menu; disclosure completeness follows from row 6 | — | none beyond row 6 | — | **Already proven** (journey-level completeness is X2) |
| 21 | Tab order follows reading order on every archetype | All; A/B/C | Context Bar order and Tier C workspace order asserted only inside `a11y.zoom-200` (zoom cases); nothing at Tier A/B anchors | harness, zoom lane only | No | Extract `inOrder` from `zoomAssertions` into a shared helper; evaluate it at every anchor over the Context Bar, the workspace/page and an open overlay with the same two exemptions (side-by-side columns read one after another; data-placed controls) | test: new harness rule **`a11y.tab-order`** | A column-reverse stack fails; a reversed row fails | **X1 work** |
| 22 | 200% browser zoom at 1366×768 reflows under Tier C rules | All | `a11y.zoom-200` blocking A/C | harness | Yes | — | none | exist | **Already proven** (T3) |
| 23 | Workbench canvas at 200% on 1366 recorded as a WCAG 1.4.4 exception | Scene Editor, Camera Analytics | §23 text; T3 register row; the run reports `workbenchException` per surface | harness report | Yes | — | none (X1 row cites it) | — | **Already recorded** |
| 24 | WCAG 1.4.10 at 320px recorded as not targeted | — | §23; T3 register row | — | Yes | — | none (X1 row cites it) | — | **Already recorded** |
| 25 | Verification row: one `main`; skip link first in tab order; every control named; focus visible after each Tab; no focusable element inside `inert`; dialog/drawer placement; no `aria-pressed` without a pressed style | All | `a11y.landmarks`, `a11y.skip-link`, `a11y.focus-visible` + `harness.focus-coverage`, `overlay.*` ("nothing outside it focusable"), `pressed.visible` — all blocking; **"every control named"** has no rule | harness | All but one | "Every control named" = the non-empty half of row 4 | test: **`a11y.names`** | An unnamed icon button fails | **X1 work** (one gap) |
| 26 | Contrast derived from tokens in `contrast.test.ts`; no third-party engine | — | As rows 1–2; no engine in `package.json` | static | Yes | — | none | — | **Already proven** |

Counts: **26 obligations**; **12 already proven or recorded** (3, 18, 19, 20, 22, 23, 24, 26 fully; 1, 2 with a coverage audit; 10 out of scope to X4); **14 requiring X1 work** (4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 21, 25 — rows 4, 16 and 25 are one rule, `a11y.names`; rows 8 and 9 one rule, `a11y.form-fields`; rows 14 and 15 one rule, `a11y.spatial-twin`).

## 4. Current target-size inventory (deduplicated)

From the T3 full sweep on `6dffe137` (87 measured findings, all `a11y.target-size`):

| # | Element / component | Where | Measured | §10.1 reading | Smallest compliant implementation | Negative test |
|---|---|---|---|---|---|---|
| T1 | `.checkbox input` — `components.css:246` sizes it `var(--icon-sm)` = 14px | Scene Editor inspector (`ScenePropertiesPanel.tsx:190, 285, 296`: zone enabled, line enabled, line directional); Search filter rail (`SearchFilterRail.tsx:460`: Loitering). 9 Scene Editor states + 30 Search states; every tier; the 200% cases. 85 of the 87 findings | 14×14 | The **effective** target is the hit area, which may exceed the mark (§10.1): the wrapping `label.checkbox` toggles the input, so the label is the target. It must be ≥ 24px tall; today it is the text's line height (~16–18px). Desktop controls must not be inflated (§10.1): the mark stays 14px | `components.css`: `.checkbox { min-height: var(--control-min-target); }` (the label is inline-flex, so the mark stays centred); the assertion measures a checkbox/radio inside a `label` by the label's box (named exception: *a checkbox's effective target is its label*) | A `.checkbox` label with `min-height: 0` in a scratch stylesheet fails at 18px tall; a bare 14px checkbox with no label fails |
| T2 | `.chip button` (the committed-filter chip's remove control, `CommittedFilterChips.tsx:238`) — `components.css:496` sizes it `var(--control-min-target)` = 24px, but the chip is a flex row and a long value shrinks the button | Search at Tier C, long names (`search-long-names` at 430 and 390). 2 findings | 17×24, 15×24 | A genuine defect: the control is squeezed below its token | `components.css`: `.chip button { flex: 0 0 auto; }` and `.chip .truncate { min-width: 0; }` so the value, not the control, gives way | A chip with a 200-character value at 390px: the button measures 24×24; with `flex` reverted it fails |
| T3 | `.scene-handle__hit` — `SceneCanvas.tsx:327` `HANDLE_HIT_R = 11` | Scene Editor, object/vertex selected (`scene-editor-object-selected`, `scene-editor-vertex-selected`); Tier A and B. **Not in the findings** (SVG circles are outside the rule's selector) | 22×22 (r 11) | §10.1: the mark may be 3–4px (it is 3.5px); the **invisible hit area SHOULD be at least 24×24** — 22 is below it, with no exception documented | `HANDLE_HIT_R = 12`; the assertion measures every `.scene-handle__hit` in the selected states (≥ 24×24), the `.scene-handle__mark` exempt by name | r 11 fails (22px); r 12 passes |

Not defects: `input[type=range]` (`ReferenceFrameBar`, `HeatmapStage`) and the timeline marker buttons (`MARKER_TARGET_PX`) measure ≥ 24 (no findings); the in-row 26×26 retry (`StateRegion`) is above the minimum by design (§36.3).

No generic exemption is proposed. The one named reading — a checkbox's effective target is its wrapping label — is §10.1's own definition of "effective", scoped to `input[type=checkbox|radio]` inside a `label` (or referenced by `label[for]`), named in the assertion message, and covered by a negative.

## 5. Proposed implementation

### 5.1 Product (smallest compliant changes)

| File | Change | Why |
|---|---|---|
| `src/web/mavi-web/src/styles/components.css` | `.checkbox { min-height: var(--control-min-target); }` | T1 — the label is the effective target |
| `src/web/mavi-web/src/styles/components.css` | `.chip button { flex: 0 0 auto; }`; `.chip .truncate { min-width: 0; }` | T2 — the value yields, not the control |
| `src/web/mavi-web/src/features/scene-editor/SceneCanvas.tsx` | `HANDLE_HIT_R = 12` | T3 — §10.1's 24px hit area |
| `src/web/mavi-web/src/features/scene-editor/SceneObjectList.tsx` (+ `features.css`) | Each row carries a compact coordinates summary (zone: vertex count and bounding box; line: its two endpoints), visually secondary | Row 14 — "its coordinates" in the twin (confirm at implementation that it is absent today; if present elsewhere in the row, no change) |
| `src/web/mavi-web/src/features/scene-editor/SceneEditorPage.tsx`, `EvidenceTimeline.tsx` | Live regions that are rendered conditionally with their content (`role=status` paragraphs) are mounted empty and populated on change | Row 7 — only where the unit audit confirms the region appears with its text |
| `src/web/mavi-web/src/shared/evidence/EvidenceTimeline.tsx` (+ CSS) | Only if the row 11 audit finds a marker/interval kind distinguished by colour alone: a glyph or stroke pattern per kind | Row 11 |

No change to tokens, primitives' APIs, routes, API or backend. Nothing is inflated to touch sizes (§10.1).

### 5.2 Harness (`tools/web-visual-qa`)

| File | Change |
|---|---|
| `assertions.mjs` | Extend the pointer-target check (section 14 of `pageAssertions`): measure the effective target — the wrapping/for-`label` of a checkbox or radio; include `.scene-handle__hit`; keep `button, a[href], input, select`; name each reading in the message. New page-side functions, each a pure DOM read, each reporting `evaluated`: `a11y.names` (computed name per control; contains the visible text; not `title`-only except `.rail` collapsed items; `role=tooltip` not a sole name), `a11y.role-contract`, `a11y.form-fields` (labels; `aria-invalid` association and announcement), `a11y.live-regions`, `a11y.non-colour-cue`, `a11y.spatial-twin` (Scene Editor at A/B; timeline where rendered), `a11y.tab-order` (the `inOrder` helper extracted from `zoomAssertions` and shared, so the zoom lane and the anchors run one definition). The computed-name helper is one function (`accessibleNameOf`) reused by `a11y.names`, `a11y.form-fields` and `a11y.role-contract` — no second definition of a name |
| `manifest.mjs` | §7 below; `validateManifest` refuses an entry still owned by X1 after X1 (the T2/T3 pattern) |
| `states.mjs` | No new surface, no new Scene Editor state: `scene-editor-object-selected` and `scene-editor-vertex-selected` carry `tierPolicy: 'workbench-variant'`, which sweeps Tiers A and B (C excluded as the unsupported state). At most one addition: a Review state whose fixture has ≥ 2 markers of different kinds, if none does (row 11) |
| `run.mjs` | Report the new rules in the summary and CI table as every other rule; no new lane |
| `README.md` | One section per new rule: what is measured, the named readings/exemptions, the stated limits |
| `test/assertions.test.mjs`, `test/manifest.test.mjs` | Positive and negative fixtures per rule (§6) |

### 5.3 Static tests (`src/web/mavi-web/src`)

| File | Change |
|---|---|
| `styles/contrast.test.ts` | Coverage audit of rows 1–2: a test that enumerates every `--text-*` and `--status-*`/badge token actually painted (from the stylesheets) and asserts each is in the contrast tables; tables extended if the audit finds a pair |
| `styles/aria.test.ts` (new) | Row 5: no ARIA role with a native equivalent on a generic element in `src/**/*.tsx` |
| `shared/status/status.test.ts` (new or extended) | Row 11: `labelForStatus` distinct per status |
| `features/scene-editor/SceneEditorPage.test.tsx` | Row 17: Delete/nudge do nothing while typing in an inspector field |
| Component tests for each live region (`AppShell`, `AttentionRegion`, `TrackInspector`, `EvidenceTimeline`, Scene Editor notices) | Row 7: the region exists before the message and is the same node after it |

## 6. Test plan

Every change has a positive test, a negative that fails on the current implementation, and harness coverage where the obligation is about a rendered page.

| Change | Positive | Negative (fails today) | Harness coverage |
|---|---|---|---|
| T1 checkbox target | The Scene Editor and Search states measure ≥ 24 on the label; `a11y.target-size` clean | Fixture: `<label class="checkbox" style="min-height:0"><input type="checkbox">Evaluate</label>` fails with the label's height named | Full sweep at every tier; the 200% cases |
| T2 chip button | `search-long-names` at 390/430 clean | Fixture: a chip whose value is 200 characters at 390px fails when the button has `flex: 1 1 auto` | Tier C states |
| T3 handle hit area | `scene-editor-vertex-selected` passes with r 12 | Fixture: a `.scene-handle__hit` circle r 11 fails (22×22 named) | Scene Editor at A/B |
| `a11y.names` | Every surface clean | `aria-label` not containing the visible text; an unnamed icon button; a `title`-only button; a tooltip as the sole name; the collapsed rail item passes by its named exception | All tiers |
| `a11y.role-contract` | Clean | `aria-expanded` without a resolving `aria-controls`; an option containing a button; an unnamed `role=region` | All tiers |
| `a11y.form-fields` | Clean on the validation states | Placeholder-only input; `aria-invalid` without a resolving description; a description that is not rendered | All tiers, validation states |
| `a11y.live-regions` | Clean | A `role=status` inside `aria-hidden`; a region `display:none`; unit: a region inserted with its message | All tiers; the loading states |
| `a11y.non-colour-cue` | Clean | An empty `.badge`; two statuses sharing a label (unit) | Ledgers, Overview, Review, Analytics |
| `a11y.spatial-twin` | Scene Editor and Review clean | A drawn polygon without a row; a row without coordinates; a timeline interval without its `li` | Scene Editor A/B; Review where the timeline renders |
| `a11y.tab-order` | Clean at every anchor | A `column-reverse` stack; a `row-reverse` toolbar; the two exemptions pass (side-by-side columns; data-placed markers) | All tiers; the zoom lane keeps its own call of the shared helper |
| `aria.test.ts` | Current source passes | `<div role="button">` in a fixture string fails | — (static) |
| Contrast coverage | Current tables cover every painted pair | A painted pair removed from the table fails the coverage test | — (static) |
| Scene Editor shortcut guard | Typing in a field never deletes | Removing the guard fails the test | — (vitest) |

Fixtures are plain HTML in `assertions.test.mjs` under the existing `lane.page` helper; nothing is added to the product to make inspection easier (§26).

## 7. Manifest transition

| Entry | From | To | Tiers | Why |
|---|---|---|---|---|
| `a11y.target-size` | `measured/pending` (S6 / X1) at A, B, C | **`blocking`** | A, B, C (the Tier C zoom cases included, as every Tier C rule) | T1–T3 corrected; the effective-target reading named; no finding remains |
| `a11y.section23-remaining` | `future`, pending X1 | **removed** — replaced by the named entries below; the manifest test asserts it is gone and that no entry is owned by X1 | — | No umbrella rule reports PASS for obligations it does not assert |
| `a11y.names` | — | `assertion`, **blocking** | A, B, C | Rows 4, 16, 25 |
| `a11y.role-contract` | — | `assertion`, **blocking** | A, B, C | Row 6 |
| `a11y.form-fields` | — | `assertion`, **blocking** | A, B, C | Rows 8, 9 |
| `a11y.live-regions` | — | `assertion`, **blocking** | A, B, C | Row 7 |
| `a11y.non-colour-cue` | — | `assertion`, **blocking** | A, B, C | Row 11 |
| `a11y.spatial-twin` | — | `assertion`, **blocking** at A and B; at C `blocking` where the timeline renders, `not-applicable` for the canvas (the §25 unsupported state renders no canvas) | A, B; C by surface | Rows 14, 15 |
| `a11y.tab-order` | — | `assertion`, **blocking** | A, B, C | Row 21 |

Unchanged: `a11y.reduced-motion` (X4), `a11y.keyboard-journeys` (X2), `perf.*` (X3), every T1/T2/T3 entry. No already-blocking rule is weakened. The new entries flip to blocking in the X1 PR itself, since X1 is the implementing slice (§26: a rule blocks once its slice merges; the PR's own sweep must be clean first).

## 8. Verification

**During development (targeted, cheap):** `node --test tools/web-visual-qa/test/assertions.test.mjs tools/web-visual-qa/test/manifest.test.mjs`; `vitest run` on the touched test files; `MAVI_VQA_OUT=… node tools/web-visual-qa/run.mjs --states <touched states>` at the affected anchors (Scene Editor states, Search long names, the validation states, one Review state) — with the new rules first evaluated as `measured/pending` on a scratch manifest to read every finding before flipping.

**Exact-head qualification (once, on the head to be merged):** harness unit tests (all files); `vitest run` (all); `tsc -b`; `vite build`; the full Tier A/B/C sweep (every anchor, every state; 0 blocking, 0 harness errors); the full zoom sweep (`--zoom only`) because a shared assertion (`pageAssertions`, the `inOrder` helper) and two shared styles (`.checkbox`, `.chip`) change; `compare.mjs` against the merged T3 baseline on `6dffe137` (Tier A/B/C: no capture changes validity; the only finding delta is the 87 `a11y.target-size` measured findings gone and the new rules' evaluated counts); `tools/verify_repo.py`; `git diff --check`; exact-head CI (Linux, DejaVu Sans — the wide-font check that caught T3's last false positive is free there). The Windows wide-font diagnostic (`MAVI_VQA_STATES_MODULE`) is run once on the final head for the zoom cases, as in T3.

No full sweep after every edit; one targeted run per touched rule during development, one full qualification on the final head, and again only if a correction changes shared code.

## 9. Acceptance criteria for X1 PASS (machine-verifiable)

1. `manifest.mjs`: no entry has `owner` matching `/X1/`; `a11y.section23-remaining` is absent; the eight entries of §7 are `blocking` at every tier stated (the manifest test asserts each).
2. Full sweep on the exact head: every capture valid, **0 blocking**, 0 harness errors; `executions` shows each new rule **evaluated** on every state where it applies (`zoomCoverageFaults`-style coverage: a new rule never evaluated on a surface where it applies is a harness fault).
3. `a11y.target-size`: 0 findings at every tier; the three negatives fail on the pre-fix code (recorded in the PR by running them against the scratch revert).
4. Every new rule has at least one negative in `assertions.test.mjs` that fails when the product condition is violated, and the harness test suite passes.
5. `contrast.test.ts` coverage test passes and enumerates every painted text/badge token pair; `aria.test.ts` passes.
6. Frontend tests, typecheck, build, `verify_repo`, `git diff --check` green on the exact head; exact-head CI green.
7. Tier A/B/C comparison with `6dffe137`: no capture changes validity; no finding appears under an existing rule.
8. The register row X1 cites the manifest change, the 1.4.10 non-claim (§23; T3 row) and the Workbench 1.4.4 exception (§23; T3 row; `executions.zoom.workbenchException`).

## 10. Risks and decisions requiring owner judgement

1. **Coordinates in the canvas twin (row 14).** §23 says the list names each object's coordinates. The rows today name the object and its state; coordinates are in the properties panel of the selected object. The plan adds a compact summary to each row. If the owner reads "the twin" as the list *plus* the properties panel (the same control the pointer uses, in two parts), no product change is needed and the assertion checks the panel instead. **Decision: row summary (planned) or panel-only reading.**
2. **Conditional live regions (row 7).** If the audit confirms the Scene Editor's `role=status` notices appear with their text, keeping them mounted empty is a small product change on an accepted reference surface (R4). It changes no layout. **Decision: accept the change in X1 (planned) or record a documented deviation.**
3. **Evidence-kind distinction (row 11).** If timeline markers of different kinds differ by colour alone, a glyph per kind touches Review's accepted composition (R6). **Decision only if the audit finds it.**

No other decision is open: the target-size readings follow §10.1's own words; every other row has one evident implementation.

## 11. PR boundaries

**One PR** (`stage3.5/s6-x1-a11y`), register row X1, from `main@5db448a3` or later. The product changes are three CSS/constant edits and at most three small component changes on surfaces already accepted (R4, R6, R5); the harness changes are additive rules plus one extraction (`inOrder`). Nothing in the audit is independent enough to warrant a split, and splitting the manifest transition from the rules it names would leave the placeholders half-retired. If the row 14 decision goes to the panel-only reading, the PR shrinks; it does not split.

Review protocol as for T3: one independent cold review of the implementation head, corrections, then one Codex review; exact-head CI; register row; no merge of X2–X4 work inside it.

---

### Cold review of this plan (self, against the register and §23)

- Every row of the §23 table and both amended rows are in §3 (26 obligations); none is marked proven on the strength of related code alone — rows 1, 2, 17 and 20 state what is proven and what is audited.
- Scope held: X2 (journeys), X3 (budgets), X4 (reduced motion) are excluded where they arise (rows 10, 20); no T1/T2/T3 semantic changes; no dependency; no pixel baseline; no backend change; no mobile scope.
- The umbrella `a11y.section23-remaining` is retired, not satisfied; every replacement names one obligation.
- Target-size findings deduplicated to three root causes (two measured, one found in code); no generic exemption; the one effective-target reading is §10.1's definition, named and tested.
- Corrected during review: the canvas twin and the timeline twin were first one row — split (14, 15) because their tiers differ; `a11y.tab-order` first proposed its own order logic — replaced by extracting the zoom lane's helper so one definition serves both; the plan first listed a full sweep "after each rule" — reduced to targeted runs during development and one exact-head qualification.
