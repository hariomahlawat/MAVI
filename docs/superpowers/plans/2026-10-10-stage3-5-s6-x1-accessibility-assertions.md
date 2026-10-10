# Stage 3.5 — S6/X1: every §23 obligation asserted (implementation plan)

**Status:** plan, revised after an independent cold review (CR-1…CR-9 and the governance correction) and cold-reviewed again (§18); no production, harness, manifest or register change is made by this document. Implementation opens as one PR after the owner has read it.
**Register row X1:** "Every §23 obligation asserted on every surface by the harness or by `styles/contrast.test.ts`, their manifest entries flipped to `blocking`; WCAG 1.4.10 at 320px recorded as not targeted and the Workbench canvas at 200% zoom on 1366 recorded as a 1.4.4 exception."
**Not in this plan:** X2 keyboard journeys, X3 performance budgets, X4 reduced motion, S7 closure.
**Revision 3** (after R1–R4): the media model stated and 1.2.x classed individually (§3.1); 1.3.2 given its own proof (`a11y.reading-order`); 1.4.12 executed in a bounded text-spacing lane; 1.4.13 proven behaviourally (`a11y.hover-content`); totals recalculated. **Revision 4** (after F1–F3): the third-party media wording made WCAG's Statement of Partial Conformance; the text-spacing lane covering every distinct responsive composition, blocking at A, B and C; stale counts corrected.

## 1. Baseline and authoritative requirements

- `main@5db448a3` — the PR #201 merge (S5/T3). The acceptance register (`docs/reviews/2026-10-07-stage3-5-ui-ux-professionalisation-acceptance.md`) records T1, T2 and T3 PASS; X1–X4 and C1–C5 OPEN.
- Frozen specification `docs/architecture/ui-ux-design-specification.md`: §23 (Accessibility — the 14 rows, the v2.0 target amendment "WCAG 2.2 Level AA **as a whole**", and the v2.0 verification amendment), §10.1 (Target size), §5 (skip link, landmarks), §15/§20 (Dialog/Drawer), §16 (truncation reachable by keyboard), §24 (full timestamp on hover or in the inspector), §25 (tiers), §26 (harness, manifest), §34.2 (conformance per slice). Plan §13 (accessibility strategy) and §15 (slice S6). ADR-012.
- Harness `tools/web-visual-qa`: `manifest.mjs` (`RULES`, `severityOf`, `validateManifest`), `assertions.mjs` (page-side assertions, `focusAssertions`, `zoomAssertions` and the T3 primitives `zoomVisibility`/`zoomPaintsAt`/`zoomOwn`), `semantics.mjs` + `cdp.mjs` `axRole` (Chromium's accessibility tree through `Accessibility.getPartialAXTree`), `engine.mjs`, `run.mjs`, `states.mjs`; static `src/web/mavi-web/src/styles/contrast.test.ts`, `tokens.test.ts`.
- Evidence read: the T3 exact-head full sweep on `6dffe137` (2,002 captures, 0 blocking; 87 `a11y.target-size` measured findings); the product source for every `title=`, `<Tooltip>`, `role=`, `aria-*`, state class and live region named below.

**The X1 gate.** Acceptance evidence for every §23 obligation is (1) a blocking per-tier rule of the §26 harness, or (2) `styles/contrast.test.ts` where the obligation is token/static contrast. Nothing else is acceptance evidence. Unit and component tests in §11 support implementation only. The register is not amended.

## 2. Exact X1 boundary

**In:** executable proof of every §23 row (the 14 rows and both amendments) through the gate; the WCAG 2.2 AA traceability of §3; the product defects that proof exposes (§6, §7, §8, §5); retirement of the placeholders `a11y.target-size` (measured/pending) and `a11y.section23-remaining` (future) for named blocking entries; the register row X1 citing the manifest change and the two already-recorded §23 statements (1.4.10 non-claim; Workbench 1.4.4 exception).

**Out:** `prefers-reduced-motion` (X4: `a11y.reduced-motion`, WCAG 2.3.3 is AAA; 2.2.2's mechanism — §3); the six keyboard-only journeys (X2: `a11y.keyboard-journeys`, 2.1.1 end to end); performance budgets (X3); 200% zoom (T3, done); any T1/T2/T3 semantic change; WCAG 1.4.10 at 320px; a third-party accessibility engine; mobile scope (§31); pixel baselines; dependencies; backend/API/domain changes.

## 3. WCAG 2.2 AA applicability and evidence matrix

§23 (v2.0): "The product is assessed against WCAG 2.2 Level AA as a whole, not against the rows above alone." The 55 Level A and AA success criteria of WCAG 2.2, each in exactly one class:

- **P** applicable, already proven by an existing blocking assertion (named);
- **X1** applicable, X1 work (the §4 row or §9 rule named);
- **X2** / **X4** applicable, owned there;
- **T3** satisfied by the accepted 200% zoom work;
- **NA** not applicable to MAVI (technical reason);
- **NC** explicitly recorded non-claim/exception frozen by §23;
- **TP** third-party / user-supplied content MAVI does not control, handled under WCAG's **Statement of Partial Conformance — Third Party Content**: where that content prevents full AA conformance, the page is **not claimed to conform fully** because of it; the statement says the page *would* conform at the stated level if the identified uncontrolled content were removed. The content is not excluded from scope — the claim is reduced to a partial-conformance statement that names it. MAVI's media model (§3.1) is the basis, not an invented exception;
- **D** applicable, satisfied by the frozen design with no executable form; the evidence is the design record cited (used only where no assertion is possible, and never for a §23 row).

### 3.1 MAVI's media model (the basis for 1.2.x and 1.4.2)

Read from the source: the web client plays the operator's imported file **as stored** — `ContentReadService` serves the `SourceVideo` artifact (`video/mp4`) and `EvidencePlayer` renders it in a `<video src>` with no `muted`, no `autoplay` and no track handling of its own; the platform neither authors, transcodes nor strips the media (no FFmpeg audio argument exists in the pipeline — frames are read from it, the file is not rewritten). Any audio, caption track or description a file carries is the operator's; MAVI adds none and removes none, and the browser's native player exposes a text track the file carries. Playback starts only on the operator's Play; the transport pauses and stops it. MAVI's **authored** application UI is everything around the footage — the evidence list, timeline, markers, summaries and twins — and it is subject to the full X1 qualification. The imported source video is operator-supplied content MAVI does not control, played as supplied, whose captions or audio description MAVI does not author. Under WCAG's **Statement of Partial Conformance — Third Party Content**, where that uncontrolled content prevents full AA conformance, the Review and Search surfaces are **not claimed to conform fully because of it**; the statement declares that they would conform at Level AA if the identified third-party content were removed. The media is not written out of scope — the claim is reduced, and the statement names what reduces it. No caption, transcript, audio-description or media-processing feature is added.

**Proposed register statement (X1 row):** "MAVI's authored application UI is qualified against WCAG 2.2 Level AA. Operator-supplied source video is identified as uncontrolled third-party content under WCAG's Statement of Partial Conformance — Third Party Content: MAVI plays it as supplied and does not author its captions or audio description, so the surfaces that present it are not claimed to conform fully because of that content; they would conform at Level AA if that identified third-party content were removed."

| SC | Name | Class | Evidence / reason |
|---|---|---|---|
| 1.1.1 | Non-text Content | X1 | Icon-only controls named (§9 `a11y.names`); decorative icons `aria-hidden` (`Icon`); canvas/timeline twins (§8, `a11y.spatial-twin`); heatmap read without colour (`contrast.test.ts` "heatmap scale") |
| 1.2.1 | Audio-only and Video-only (Prerecorded) | TP | MAVI authors no prerecorded audio-only or video-only media; the operator's footage is uncontrolled third-party content played as supplied (§3.1). The surfaces presenting it are not claimed to conform fully because of it; the partial-conformance statement names it. The evidence twin is MAVI's rendering of its analysis, not claimed as a WCAG media alternative |
| 1.2.2 | Captions (Prerecorded) | TP | Any speech is the operator's file's; MAVI authors no captions and strips none (a caption track a file carries is exposed by the native player). Uncontrolled third-party content under the partial-conformance statement |
| 1.2.3 | Audio Description or Media Alternative (Prerecorded) | TP | As 1.2.1: MAVI authors no synchronized media and no audio description; the footage is uncontrolled third-party content under the partial-conformance statement |
| 1.2.4 | Captions (Live) | NA | No live media: imports are files (§3.1); nothing is streamed live |
| 1.2.5 | Audio Description (Prerecorded) | TP | As 1.2.3 |
| 1.3.1 | Info and Relationships | P + X1 | `a11y.landmarks`, `tier.c-composition` semantics (table roles kept at Tier C via the AX tree), `ledger.column-fold` (folded values keep their header name); X1: form labels and error association (`a11y.form-fields`), role contracts (`a11y.role-contract`) |
| 1.3.2 | Meaningful Sequence | X1 | **`a11y.reading-order`** (§9.12) — the DOM order of content siblings in the sequential regions where order carries meaning equals their visual order; separate from focus order (2.4.3, `a11y.tab-order`); `tier.c-composition` already fixes the Tier C region order |
| 1.3.3 | Sensory Characteristics | D | No instruction in the product refers to shape, size, position or sound alone (the §37 state grammar is textual); recorded, not asserted |
| 1.3.4 | Orientation | NA | Desktop workstation; no orientation lock exists (§25 Tier B covers tablet portrait and landscape as compositions) |
| 1.3.5 | Identify Input Purpose | NA | No field collects information *about the user* (no name, address, credentials); the fields are filters, camera and scene data |
| 1.4.1 | Use of Color | P + X1 | `pressed.visible` (pressed); `a11y.focus-visible` (focus ring); X1: the state-cue inventory of §5 (`a11y.state-cues`) |
| 1.4.2 | Audio Control | D | The criterion concerns audio that plays automatically for more than 3 s. The player has no `autoplay` (§3.1): audio a file carries plays only on the operator's Play, and the transport pauses and stops it — the mechanism the SC asks for is the transport itself. Recorded (the absence of `autoplay` is one line in `review.composition`, not a new rule) |
| 1.4.3 | Contrast (Minimum) | P | `contrast.test.ts` "text contrast (4.5:1)" + X1 coverage audit (§4 row 1) |
| 1.4.4 | Resize Text | T3 + NC | `a11y.zoom-200` (text grows 2× at 200%); the Workbench 1.4.4 exception recorded (§23, T3 row) |
| 1.4.5 | Images of Text | D | No image of text in the product (icons are SVG glyphs; the brand mark is an SVG with its text as text); `tokens.test.ts` forbids `url()` images outside tokens — recorded |
| 1.4.10 | Reflow | NC | Recorded as not targeted at 320px (§23); 683px reflow is T3 |
| 1.4.11 | Non-text Contrast | P | `contrast.test.ts` "non-text contrast (3:1)" (boundaries, focus ring, scrollbar thumb, evidence, heatmap) + X1 coverage audit of the state tokens (§4 row 2) |
| 1.4.12 | Text Spacing | X1 | **`a11y.text-spacing`** (§9.13): a bounded lane that applies the SC's overrides (line height 1.5×, paragraph spacing 2×, letter spacing 0.12 em, word spacing 0.16 em) before first paint and re-runs the existing clipping, overlap, overflow, reachability and obscuration assertions on every state at one canonical anchor of every distinct responsive composition — 1366×768 (A), 1024×768 and 768×1024 (B landscape and portrait), 390×844 (C) — and at each state's declared probe widths |
| 1.4.13 | Content on Hover or Focus | X1 | **`a11y.hover-content`** (§9.14): the custom `Tooltip` proven in the browser — shown on focus and on hover, persistent while held, hoverable (the pointer moves onto it without it hiding), dismissed by Escape without moving focus; native `title` excluded (browser-controlled, not author content). The content classes (§7, `a11y.tooltips`) prove the separate §23 obligation |
| 2.1.1 | Keyboard | P + X2 | `a11y.focus-visible` + `harness.focus-coverage` (every control reachable and focused), `overlay.*` (Tab, Shift+Tab, Escape); the six journeys end to end are X2 |
| 2.1.2 | No Keyboard Trap | P | `overlay.dialog`/`overlay.drawer`: Escape leaves, focus restored to the invoker; the focus sweep leaves every control |
| 2.1.4 | Character Key Shortcuts | X1 | `a11y.shortcuts-in-text-entry` (§9): single-key shortcuts (`?`, `j`/`k`, `e`, Delete, nudges) are inactive in text-entry contexts — the §23 row; the "only when focused" exception of the SC is the product's design (component-scoped keys) |
| 2.2.1 | Timing Adjustable | D | The one time limit is a search snapshot's expiry (`search-snapshot-expired`): an essential server-consistency limit; the state names it and offers the re-run with the filters kept — swept, recorded |
| 2.2.2 | Pause, Stop, Hide | X4 | The one autonomous motion is the `.badge--active` pulse (`--dur-pulse` 1.2s, infinite); its mechanism is `prefers-reduced-motion` (X4). Recorded here so X4 closes it explicitly |
| 2.3.1 | Three Flashes | D | Nothing flashes; the pulse is 0.83 Hz, far below 3 Hz; `tokens.test.ts` forbids duration literals, so the token is the only period — recorded |
| 2.4.1 | Bypass Blocks | P | `a11y.skip-link` |
| 2.4.2 | Page Titled | X1 | `DocumentTitle` sets a title per surface; add the one-line check to `a11y.landmarks`: `document.title` non-empty and not the build default |
| 2.4.3 | Focus Order | X1 | `a11y.tab-order` |
| 2.4.4 | Link Purpose (In Context) | X1 | `a11y.names` (every link named; the name contains its visible text) |
| 2.4.5 | Multiple Ways | P | The rail (every surface) and the Overview's attention list/links (`shell.rail`, `a11y.landmarks`) |
| 2.4.6 | Headings and Labels | X1 | `a11y.form-fields` (labels), `a11y.names`; headings are the §37 grammar (`state.placement`) |
| 2.4.7 | Focus Visible | P | `a11y.focus-visible` |
| 2.4.11 | Focus Not Obscured (Minimum) | T3 + X1 | At 200%: the zoom lane's control sweep (focus not under a painted layer). At Tier A/B: X1 adds the same check to the existing focus sweep — after focusing, the control's centre is its own (`zoomOwn`/`zoomPaintsAt`, reused) and not under the sticky Context Bar or player (`a11y.focus-not-obscured`) |
| 2.5.1 | Pointer Gestures | D | Dragging a vertex is single-pointer; no multipoint or path gesture exists (recorded) |
| 2.5.2 | Pointer Cancellation | D | Actions fire on `click` (up-event); the canvas drag commits on pointer-up and Escape abandons (Scene Editor unit tests) — recorded |
| 2.5.3 | Label in Name | X1 | `a11y.names` — the §23 row |
| 2.5.4 | Motion Actuation | NA | No device-motion input |
| 2.5.7 | Dragging Movements | P | Vertex dragging has its keyboard/pointer-free alternative: the inspector's point list with nudge controls (`scene-inspector__point`; Scene Editor unit tests; swept states) — the §23 twin; recorded as proven by the accepted R4 surface |
| 2.5.8 | Target Size (Minimum) | X1 | `a11y.target-size` (§6, §9) — §10.1 is stricter (24×24 effective, no spacing exception) |
| 3.1.1 | Language of Page | P | `index.html` `lang="en"`; add to `a11y.landmarks` (one line) |
| 3.1.2 | Language of Parts | NA | Single-language product; no foreign-language passages |
| 3.2.1 | On Focus | D | Focus changes no context (no auto-submit, no navigation on focus); `overlay.*` prove placement only on explicit open — recorded |
| 3.2.2 | On Input | D | Filters apply on explicit commit (Search) or are announced (§37 grammar); a `select` change never navigates — recorded; `a11y.live-regions` proves the announcement |
| 3.2.3 | Consistent Navigation | P | `shell.rail`, `shell.context-bar` at every surface |
| 3.2.4 | Consistent Identification | P | One `Button`/`StatusBadge`/`StateRegion` grammar; `surface.one-primary`; `a11y.names` adds the per-control proof |
| 3.2.6 | Consistent Help | NA | No help mechanism beyond the shortcut sheet, which is the same control on every surface (`shell-shortcut-sheet`) |
| 3.3.1 | Error Identification | X1 | `a11y.form-fields` (identified in text, associated) |
| 3.3.2 | Labels or Instructions | X1 | `a11y.form-fields` (labels; §24 wall-time format visible next to the field) |
| 3.3.3 | Error Suggestion | D | Error messages state the correction (the §37 texts in the swept validation states) — recorded; the association is asserted |
| 3.3.4 | Error Prevention (Legal, Financial, Data) | P | Reversible/confirmed: scene discard and reload confirmations (`overlay.dialog`, `scene-editor-discard-dialog`, `scene-editor-reload-dialog`), the leave guard (T3) |
| 3.3.7 | Redundant Entry | NA | No multi-step process re-asks for entered data (filters persist in the URL; the import form is one step) |
| 3.3.8 | Accessible Authentication (Minimum) | NA | No authentication in the web client (on-premises; the host authenticates) |
| 4.1.2 | Name, Role, Value | P + X1 | `pressed.visible`, `overlay.*` (modal name, `aria-modal`), `tier.c-composition` (AX roles); X1: `a11y.names` (names from the AX tree), `a11y.role-contract` |
| 4.1.3 | Status Messages | X1 | `a11y.live-regions` |

Totals (each criterion in one primary class): 55 = **P 14** (1.3.1, 1.4.1, 1.4.3, 1.4.11, 2.1.1, 2.1.2, 2.4.1, 2.4.5, 2.4.7, 2.5.7, 3.2.3, 3.2.4, 3.3.4, 4.1.2 — four of them with an X1 part delivered by a §9 rule, and 2.1.1's journeys owned by X2) + **X1 15** (1.1.1, 1.3.2, 1.4.12, 1.4.13, 2.1.4, 2.4.2, 2.4.3, 2.4.4, 2.4.6, 2.5.3, 2.5.8, 3.1.1, 3.3.1, 3.3.2, 4.1.3) + **X4 1** (2.2.2) + **T3 2** (1.4.4, 2.4.11 at 200%; 2.4.11's A/B part is an X1 rule) + **NC 1** (1.4.10; the 1.4.4 exception is recorded with its T3 row) + **TP 4** (1.2.1, 1.2.2, 1.2.3, 1.2.5 — the operator's footage, by §3.1) + **NA 8** (1.2.4, 1.3.4, 1.3.5, 2.5.4, 3.1.2, 3.2.6, 3.3.7, 3.3.8) + **D 10** (1.3.3, 1.4.2, 1.4.5, 2.2.1, 2.3.1, 2.5.1, 2.5.2, 3.2.1, 3.2.2, 3.3.3). 14 + 15 + 1 + 2 + 1 + 4 + 8 + 10 = 55. Applicable to authored content (P + X1 + X4 + T3 + NC + D) = 43; third-party 4; not applicable 8. No criterion gets a new assertion that no §23 row, WCAG AA criterion or MAVI pattern calls for: the D rows are recorded, not asserted.

## 4. §23 detailed coverage matrix

Columns: obligation · surfaces/tiers · existing evidence · gate proof after X1 · gap · change kind · negative · disposition. Disposition is one of **proven** (gate evidence exists), **X1** (gate evidence to add), **X2/X4** (owned there), **recorded** (a §23 statement, not an assertion).

| # | §23 obligation | Surfaces / tiers | Existing evidence | Gate proof after X1 | Gap | Change | Negative | Disposition |
|---|---|---|---|---|---|---|---|---|
| 1 | Text contrast ≥ 4.5:1 (MUST) | all; tokens | `contrast.test.ts` text table | same, with a coverage test: every `color` token a stylesheet paints is in the table against every surface it is painted on | coverage not shown complete | test | a pair removed from the table fails the coverage test | **proven** (+audit) |
| 2 | Non-text contrast ≥ 3:1 — boundaries, state indicators, graphical information, focus (MUST) | all; tokens | `contrast.test.ts` non-text, evidence, heatmap tables | same, plus the badge/coverage state tokens (`--status-*`, `--status-*-border`) on their surfaces | state tokens to confirm in the table | test | as row 1 | **proven** (+audit) |
| 3 | Visible focus on every interactive element; never suppressed without an equivalent (MUST) | all; A/B/C | `a11y.focus-visible`, `harness.focus-coverage` blocking | same | — | none | exist | **proven** |
| 4 | Accessible name contains the visible label (MUST) | all; A/B/C | none | **`a11y.names`** (§9.1): Chromium's computed name per control (AX tree) contains the control's visible text | no rule | test | `aria-label="Submit"` on a button reading "Save" fails | **X1** |
| 5 | Semantic HTML first; ARIA only where unavailable (MUST) | all; A/B/C | none executable | **`a11y.role-contract`**: no native-equivalent role on a generic element; no native element re-roled away | no rule | test | `<div role="button" tabindex="0">` fails | **X1** |
| 6 | A role's contract honoured or not claimed: no focusable child in a `listbox` option; `aria-expanded` requires a controlled region (MUST) | all; A/B/C | `pressed.visible`; `overlay.*` | **`a11y.role-contract`** (§9.4, real ARIA contracts + the two §23 examples) | no rule | test | an expanded control whose region is absent; an option holding a button | **X1** |
| 7 | Status regions mounted before populated, so a mode change is announced (MUST) | all; A/B/C | none | **`a11y.live-regions`** (§9.5): rendered; and mounted-before-populated proven across every state's preparation | no rule; the Scene Editor's conditional `role=status` paragraphs are the known product candidates | test + product | a preparation inserting `<p role="status">` with its text fails | **X1** |
| 8 | Form fields labelled (MUST) | A/B/C | `Field` binds labels; no rendered-page proof | **`a11y.form-fields`**: every visible field has a label (AX-tree name non-empty and from a label/`aria-label`/`aria-labelledby`, not a placeholder) | no rule | test | placeholder-only input fails | **X1** |
| 9 | Errors programmatically associated (MUST); error messages associated and announced (amended) | validation states; A/B/C | `Field` sets `aria-invalid`/`aria-describedby` | **`a11y.form-fields`**: `aria-invalid` → description resolves to rendered text; the message is in a live/alert region or focus moves to the field (§16 scroll-to-invalid) | no rule | test | unreferenced message fails | **X1** |
| 10 | `prefers-reduced-motion` honoured globally (MUST) | all | `tokens.test.ts` (no duration literal) | `a11y.reduced-motion` | — | none | — | **X4** |
| 11 | Non-colour cue for every status and every evidence distinction (MUST); non-colour cues for every state (amended) | all; A/B/C | `pressed.visible`, `a11y.focus-visible`, `contrast.test.ts` (heatmap luminance, evidence hues) | **`a11y.state-cues`** over the §5 inventory | the inventory's "X1" rows; two selection cues background-only | test + product | §5 | **X1** |
| 12 | Effective pointer target ≥ 24×24 wherever practical; documented exception otherwise (SHOULD / documented exception, §10.1) | all; A/B/C | `a11y.target-size` measured/pending; 87 findings | **`a11y.target-size`** blocking over the one pointer-target discovery helper (§9.2) | four root causes (§6); the rule's reach | product + test + manifest | §6 | **X1** |
| 13 | Small visible canvas handles keep a 24×24 invisible hit area (§10.1) | Scene Editor; A/B | none (SVG outside the rule) | **`a11y.target-size`**: `.scene-handle__hit` ≥ 24×24, the mark exempt by name | `HANDLE_HIT_R = 11` → 22px | product + test | r 11 fails | **X1** |
| 14 | Accessible twin for every canvas: a list naming each object, its state **and its coordinates**; the same control the pointer uses (MUST) | Scene Editor; A/B (C: no canvas) | `SceneObjectList` rows (name, kind, vertex count, enabled/invalid); coordinates only in the selected object's properties panel | **`a11y.spatial-twin`** (§8): every drawn object has its list item; the item names its state; the item exposes its actual coordinates | coordinates not in the twin | product + test | an object without a row; a row without its vertices | **X1** |
| 15 | Accessible twin — every timeline interval has a list entry (MUST) | Review; A/B/C where the timeline renders | `EvidenceTimeline` renders one `li` per interval and marker (unit tests) | **`a11y.spatial-twin`**: intervals/markers drawn = list items, each named | no rendered-page proof | test | an interval without its `li` fails | **X1** |
| 16 | Tooltips carry no information required to operate the product; `title` alone is never a control's only label (collapsed rail item the one exception) (MUST) | all; A/B/C | none | **`a11y.tooltips`** (§7, §9.6): every tooltip/`title` text falls in a supplemental class; **`a11y.names`**: no control named by `title` alone except the collapsed rail item; the custom tooltip's hover/focus behaviour (WCAG 1.4.13) by **`a11y.hover-content`** (§9.14) | no rule; the audit of §7 | test (+ product where §7 finds required text) | a tooltip-only instruction fails; a `title`-only button fails; the collapsed rail item passes by its named exception | **X1** |
| 17 | Keyboard shortcuts do not fire in text-entry contexts (MUST) | Shell, Search, Review, Scene Editor | `useGlobalShortcuts` guard; unit tests for Shell, Search, Player | **`a11y.shortcuts-in-text-entry`** (§9.7) | no gate proof | test | a `?` opening the sheet from a focused field fails | **X1** |
| 18 | Skip link and landmarks (§5) (amended) | all | `a11y.skip-link`, `a11y.landmarks` | same (+ `document.title`, `lang`) | — | none | exist | **proven** |
| 19 | Drawer and dialog focus management (§15, §20) (amended) | overlays | `overlay.dialog`, `overlay.drawer` | same | — | none | exist | **proven** |
| 20 | Every drawer, dialog, menu and disclosure keyboard-complete (amended) | overlays, menu, disclosures | `overlay.*`, `tier.c-shell`, `a11y.zoom-200` (menu) | same + `a11y.role-contract` (disclosure region present when expanded) | — | none beyond row 6 | — | **proven** (journeys: X2) |
| 21 | Tab order follows reading order on every archetype (amended) | all; A/B/C | Context Bar and Tier C workspace order in the zoom lane only (consecutive pairs) | **`a11y.tab-order`** (§9.8) at every anchor; the zoom lane adopts the helper | no rule at A/B; the pair model passes a scattered grid | test | §9.8 | **X1** |
| 22 | Error messages associated and announced (amended) | validation states | as row 9 | `a11y.form-fields` + `a11y.live-regions` | — | (row 9) | — | **X1** (with 9) |
| 23 | 200% browser zoom at 1366×768 reflows under Tier C rules (amended) | all | `a11y.zoom-200` | same | — | none | exist | **proven** (T3) |
| 24 | Workbench canvas not rendered below 768 — recorded as a WCAG 1.4.4 exception (amended) | Workbench | §23 text; T3 row; `executions.zoom.workbenchException` | X1 row cites | — | none | — | **recorded** |
| 25 | Verification: one `main`; skip link first; **every control named**; focus visible after each Tab; no focusable inside `inert`; dialog/drawer placement; no `aria-pressed` without a pressed style; contrast from tokens; no engine (amended) | all | all blocking except "every control named" | `a11y.names` closes it | one gap | (row 4) | an unnamed icon button fails | **X1** (with 4) |
| 26 | WCAG 1.4.10 at 320px recorded as not targeted (amended) | — | §23; T3 row | X1 row cites | — | none | — | **recorded** |

**Counts (reconciled).** 26 rows = **proven 7** (1, 2, 3, 18, 19, 20, 23) + **recorded 2** (24, 26) + **X4 1** (10) + **X1 16** (4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 21, 22, 25). 7 + 2 + 1 + 16 = 26, each row in exactly one class (row 25's six already-closed items are proven by the rules it names; the row is X1 because its seventh item, "every control named", is not). The 16 X1 rows resolve to **ten named rules** (§9) plus the four product defects of §6 and the product changes of §5, §7, §8.

## 5. State / non-colour-cue inventory

Principle (WCAG 1.4.1 and §23): a state is cued without colour when it carries **text**, a **glyph or icon**, a **shape** (border style or width, a bar, stroke width, underline, skew), a **position/presence** (handles appear, an inspector opens, a row expands) or a **luminance step ≥ 3:1** against the unstated state; and it is exposed **programmatically** (`aria-pressed`, `aria-current`, `aria-selected`, `aria-invalid`, `disabled`, `data-status`, `open`) so the harness can locate it and AT can read it. Hue alone, or `::before` motion alone, is not a cue.

| State | Where (markup) | Cue today | Programmatic | Proof | Disposition |
|---|---|---|---|---|---|
| Pressed / active toggle | `.btn[aria-pressed]`, `.toggle-chip`, `Segmented` (`is-active`), `scene-inspector__point[aria-pressed]` | pressed style (background + border + mark) — **proven** by `pressed.visible` (a pressed style must exist, judged against the unpressed sibling) | `aria-pressed` | `pressed.visible` (blocking) | **proven**; `Segmented` to be confirmed as `aria-pressed`-marked (else X1 product: add it) |
| Focus | every control | ring (`--focus-ring`, 3:1) | `:focus-visible` | `a11y.focus-visible` | **proven** |
| Selected — Search result row | `.result-row[aria-current="true"]` | background **and** an inset 4px left bar (shape) | `aria-current` | `a11y.state-cues` | **X1 assertion** (cue exists) |
| Selected — Evidence set control | `.evidence-set__control[aria-current='true']` | border colour + inset 1px box-shadow (width step) | `aria-current` | `a11y.state-cues` | **X1 assertion** |
| Selected — Ledger row | `.table tbody tr.is-selected td` | **background only** | class only | — | **X1 product**: `aria-selected`/`aria-current` on the row and an inset bar as the result row has; then `a11y.state-cues` |
| Selected — Scene object (navigator) | `.scene-navigator__item.is-selected` | **background only**; the canvas shows handles (presence) | class only on the item | — | **X1 product**: `aria-current="true"` on the item's control and an inset bar; then `a11y.state-cues` |
| Selected — Scene object (canvas) | `.scene-zone.is-selected polygon`, `.scene-line.is-selected` | stroke width step + handles appear (shape, presence) | the twin's `aria-current` (above) | `a11y.state-cues` (handles present when selected) | **X1 assertion** |
| Selected — vertex | `.scene-handle.is-selected .scene-handle__mark`, `scene-inspector__point[aria-pressed]` | fill/stroke swap (luminance) + the pressed point in the inspector | `aria-pressed` | `pressed.visible` | **proven** |
| Track card selected | `.track-card.is-selected` | 2px accent ring (width step) | to confirm (`aria-current`/`aria-pressed`) | `a11y.state-cues` | **X1 assertion** (+ attribute if missing) |
| Current page (crumb) | `[aria-current="page"]` | weight 600 + colour | `aria-current` | `a11y.state-cues` | **X1 assertion** |
| Invalid field | `[aria-invalid="true"]` | error border + **message text** | `aria-invalid` | `a11y.form-fields` | **X1 assertion** (row 9) |
| Invalid scene object | `.scene-zone.is-invalid polygon` (stroke `--status-warn`) + navigator `Icon alert` + row text | canvas: **colour only**; twin: icon + text | `invalid` in the row | `a11y.state-cues` | **X1 product**: a dashed stroke (`stroke-dasharray`) for an invalid object on the canvas; the twin already cues |
| Disabled | `:disabled`, `[aria-disabled]` | disabled surface/border/text tokens (luminance), `cursor: not-allowed`; no hover | `disabled` | `contrast.test.ts` "paints a disabled button with the disabled surface…" + §4 row 2 audit (the disabled text token's step against the enabled one) | **proven** (the cue is the luminance step, asserted from tokens) |
| Loading | `LoadingState` (`role=status`, skeleton + text) | text ("Loading …") | `role=status` | `a11y.live-regions`, `state.placement` | **proven** by `state.placement` (text present) |
| Empty / unavailable / degraded | `StateRegion`, `EmptyState` (`role=status`), `.state-row--degraded`, `.alert--stale` (icon + text) | text + icon | `role=status`/`alert` | `state.placement` | **proven** |
| Stale / unavailable badge | `.badge--stale`, `.badge--unavailable` | text (+ dashed border on `coverage--stale`) | `data-status` | `a11y.state-cues` (badge has text) | **X1 assertion** |
| Processing statuses (queued, running, failed, complete, not queued) | `StatusBadge` (`labelForStatus`), `.badge--active::before` pulse | **text** per status | `data-status` | `a11y.state-cues`: every badge has non-empty text; `labelForStatus` distinct per status (page-side: no two statuses in one view share text with different tones) | **X1 assertion** |
| Success / ready / ok | `.badge--ok`, `.coverage--success` (icon) | text; icon | `data-status` | `a11y.state-cues` | **X1 assertion** |
| Evidence distinctions (timeline) | `[data-kind='crossing'|'zone-entry'|'zone-exit'|'evidence']` ticks: skewX ±20°, height 10px, lane position; `[data-lane]`; `[data-drawn='false']` | shape (skew, height), position (lane) | `data-kind`, `data-lane` | `a11y.state-cues`: ticks of different kinds differ in computed `transform`/height | **X1 assertion** (cue exists by design) |
| Evidence roles (halo, box, selection) | tokens | hue distinct + halo | — | `contrast.test.ts` "evidence and spatial legibility" | **proven** |
| Analytics coverage / heatmap | `.coverage--*` (icon + text), heatmap luminance scale | icon + text; luminance | `data-*`/text | `contrast.test.ts` "heatmap scale"; `a11y.state-cues` (coverage strip has icon and text) | **proven** (heatmap) / **X1 assertion** (coverage strip) |

Result: **proven 7, X1 assertion 11, X1 product 3** (Ledger row selection cue + attribute; Scene navigator selection cue + attribute; invalid object stroke pattern) — each a small CSS/attribute change on an accepted surface, none inflating sizes. `a11y.state-cues` is one rule over this inventory: for each programmatic state marker found, assert a non-colour cue by the principle above (text/glyph child, a computed-style difference against the unmarked sibling in a non-colour property, or a luminance ratio ≥ 3:1), and name the state in the finding.

## 6. Target-size inventory by unique root cause

From the T3 sweep on `6dffe137` (87 measured findings) and the source. Confirmed against the product: the checkbox mark may stay 14px with the label as the effective target; the chip control stays 24px with the text yielding; the handle's invisible target grows to 24 with the 3.5px mark unchanged; nothing is sized to 44–48px.

| # | Element | Where | Measured | §10.1 reading | Smallest compliant change | Negative |
|---|---|---|---|---|---|---|
| T1 | `.checkbox input` (`components.css:246`, `--icon-sm` 14px) | Scene Editor inspector (3 per object), Search filter rail (Loitering): 39 states, every tier; 85 findings | 14×14 | the effective target is the hit area, which may exceed the mark: the wrapping `label.checkbox` toggles the input | `components.css`: `.checkbox { min-height: var(--control-min-target); }`; the rule measures a checkbox/radio by its wrapping/for-label (named reading) | label at `min-height: 0` (~18px) fails; a bare 14px checkbox fails |
| T2 | `.chip button` (`CommittedFilterChips.tsx:238`; `components.css:496`, 24px token) | Search long names at 430/390; 2 findings | 17×24, 15×24 | squeezed below its token by the flex row | `.chip button { flex: 0 0 auto; }`, `.chip .truncate { min-width: 0; }` | a 200-char value at 390px with `flex: 1 1 auto` fails |
| T3 | `.scene-handle__hit` (`SceneCanvas.tsx:327`, `HANDLE_HIT_R = 11`) | Scene Editor object/vertex selected; A/B; not in the findings (SVG outside the old selector) | 22×22 | the invisible hit area SHOULD be ≥ 24×24; the 3.5px mark stays | `HANDLE_HIT_R = 12`; the rule measures `.scene-handle__hit`, the `__mark` exempt by name | r 11 fails |
| T4 | `summary` of disclosures — dense Evidence Timeline (`EvidenceTimeline.tsx:531`; `features.css:398`: 11px font, no padding/min-height) and `.disclosure summary` on Analytics, Processing, Review, Search, Scene Editor (`components.css:466`) | Review overflow states; inspectors; A/B/C; not in the findings (outside the old selector) | ~16px high (to be measured by the first targeted run) | a pointer-operable control below 24 with no exception | `.disclosure summary, .evidence-timeline__dense summary { min-height: var(--control-min-target); display: flex; align-items: center; }` | a `summary` at its line height fails |

Not defects: range inputs (≥ 24), timeline marker buttons (`MARKER_TARGET_PX`), the 26×26 in-row retry (§36.3). No generic exemption; the one named reading (T1) is §10.1's own definition of "effective".

## 7. Tooltip / required-information audit

Every `title=` and `<Tooltip>` in `src/web/mavi-web/src` (60 usages; `Panel`/`EmptyState`/`Inspector`/`Dialog` `title` props are headings, not tooltips, and are excluded). Classes: **N** the control's own name (compacted or icon-only control, the tooltip repeats the visible/accessible name); **K** name plus a keyboard hint (`· k or ↑`, `(Space)`) — the key is a convenience, the control operates by click and by focus+Enter; **V** the full value of truncated text, available without hover by §16 (keyboard reach, the `Truncated` pattern) or elsewhere on the surface; **F** a timestamp's full form on `<time>`, whose compact form is visible and whose full form is in the inspector (§24); **S** supplemental explanation also stated elsewhere on the surface; **R** required information available only in the tooltip — a defect.

| Usage | Class | Note |
|---|---|---|
| `AppShell.tsx:273` rail item `title` when collapsed; `:299` collapse `Tooltip`; `:333` menu `Tooltip` | N | the sanctioned collapsed-rail exception; the item also carries its label text for AT |
| `Button.tsx:68, :96` compacted `Button`/`ButtonLink` `Tooltip` = `children` | N | the label the compaction hid |
| `TrackInspector.tsx:104, :106, :112` "Previous result · k or ↑", "Next result · j or ↓", "Close inspector · Esc" | K | names + hints; the sheet lists the keys |
| `EvidencePlayer.tsx:317–368` "Play or pause (Space)", "Previous frame (Left arrow)", … | K | as above |
| `ReferenceFrameBar.tsx:140` "Pause"/"Play" | N | |
| `VideosPage.tsx:363`, `ProcessingQueuePage.tsx:297`, `TrackResultList.tsx:102`, `StateRegion.tsx:138` (compact retry) | N | icon-only controls; the `aria-label`/text is the same string — `a11y.names` proves the name is not `title`-only |
| `Truncated.tsx:53`, `ContextBar.tsx:155, :159`, `SceneObjectList.tsx:152, :191`, `ScenePropertiesPanel.tsx:158, :263`, `AttentionRegion.tsx:139`, `CommittedFilterChips.tsx:234`, `LedgerFold.tsx:22`, `EvidenceTimeline.tsx:478` | V | truncated names/values; the chip's full value is the filter itself (rail/drawer); the marker's names are in its list entry |
| `ActivityTable.tsx:44`, `ProcessingQueuePage.tsx:211, :265`, `VideosPage.tsx:271, :285` | F | `<time title=full>` with the compact form visible (§24) |
| `ProcessingQueuePage.tsx:174` `th title="Final count, recorded when the run completed"` | S | column explanation; the Record's provenance panel states it |
| `AnalyticsPage.tsx:296` `title="Adjust the window before refreshing."` on the disabled refresh | S | the same instruction is the page's `EmptyState` "Adjust the window" (`:368`) |
| `StatusBadge.tsx:19` `title` prop | S | used for a long status reason whose short label is the badge text; audit each call site at implementation — any reason that is operating information must be in text (candidate R) |
| `FileInput.tsx:82` `title=""` | — | suppresses the native file-input tooltip; no content |

Result: no **R** found in the source audit; one candidate to settle at implementation (`StatusBadge` `title` call sites). Product change only if a call site is R. This audit and `a11y.tooltips` prove the §23 content obligation; the custom tooltip's hover/focus behaviour (WCAG 1.4.13) is proven separately by `a11y.hover-content` (§9.14). `a11y.tooltips` (§9.6) proves the classes mechanically: a tooltip/`title` text must equal the control's computed name, or the name plus a trailing key hint, or the full text of a truncated element (`text-overflow` active) or a `<time>`'s `dateTime` formatted, or be present elsewhere in the page's text; anything else is a finding naming the control.

## 8. Accessible-spatial-twin design

§23 MUST: every canvas has a list naming each object, its state and its coordinates; the twin is the same control the pointer uses. The twin is `SceneObjectList`: one `li` per zone and per trip line, whose row button selects the object the pointer selects on the canvas.

- **Every object represented:** `a11y.spatial-twin` counts `.scene-zone` and `.scene-line` on the canvas and the `li` under `ul[aria-label="Zones"]` / `ul[aria-label="Trip lines"]`; equal, and each drawn object's key appears in a row.
- **State represented:** the row names kind, vertex count, enabled/disabled (`ZoneRow` state string) and invalid (icon + text); selection by `aria-current` (§5 product change).
- **Actual coordinates in the twin:** each `li` gains a `details` disclosure inside the same list item — "Coordinates" — listing the object's **actual vertices** as `(x, y)` in the stored coordinate system, in order (a zone: every vertex; a trip line: its two endpoints, inline in the row text as they are two). The disclosure is part of the item (same `li`, after the row button), so the twin stays one control per object, not a parallel surface; the operational reading stays compact (the row) with the full geometry one disclosure away in the same item. The properties panel keeps its editable point list for the selected object; it is where keyboard editing happens (2.5.7) and is not the twin.
- **Timeline:** `.evidence-timeline__interval` and `__marker` items are already the twin (one `li` per interval and marker, each the pointer's control, named with its subject and time); the rule proves count and names.
- **No parallel accessibility-only UI:** nothing is `visually-hidden`-only; the disclosure is visible to everyone.
- **Tiers:** Scene Editor at A and B (`workbench-variant`); C not applicable (no canvas, §25). Timeline at every tier it renders.

This is the frozen requirement implemented, not reinterpreted; the only choice left (§16) is presentation (disclosure in the item vs. inline), both compliant.

## 9. Proposed harness architecture

Reuse first: the T3 primitives (`zoomVisibility`, `zoomPaintsAt`, `zoomOwn`), the focus sweep, `axRole`'s CDP path, `settle`'s before/after hooks. No umbrella rule. Each rule is one page-side function (or one CDP read), reports `evaluated`, names the control and the reading in every finding, and has its negatives in `assertions.test.mjs`.

### 9.1 Chromium-computed accessible names (`a11y.names`)

`cdp.mjs` gains `axNodes(selector)` beside `axRole`: for every element matching the selector, `Accessibility.getPartialAXTree({ nodeId, fetchRelatives: false })` → the un-ignored node's `name.value` (and `name.sources` where present, which say whether the name came from `title`). No local name algorithm. Page side, one DOM read gives each control's **visible label**: its rendered text content (excluding `visually-hidden` and `aria-hidden` descendants), an `<img alt>`, or its `<label>`'s text. The assertion: every pointer/keyboard control (§9.2) has a non-empty computed name; where a visible label exists, the normalised computed name (whitespace, case, punctuation collapsed) **contains** the normalised visible label (2.5.3); a name whose only source is `title` is a finding, except a `.rail` item while the rail is collapsed (the §23 exception, matched by that selector and `aria-expanded="false"` on the rail control — one line, documented); a `role=tooltip` is never a name source on its own. Tiers A/B/C.

### 9.2 One pointer-target discovery helper (`interactiveControls`)

One helper in `assertions.mjs`, used by `a11y.target-size`, `a11y.names`, `a11y.focus-not-obscured` and the focus sweep (which today has its own selector), returning the rendered, non-inert controls of a root with their kind:

- **pointer targets** (`{ pointer: true }`, the §10.1 set): `button`, `a[href]`, `input` (not `hidden`), `select`, `textarea`, `summary`, elements with a widget role (`[role="button"|"link"|"checkbox"|"radio"|"switch"|"tab"|"menuitem"|"option"|"slider"]`), `[contenteditable="true"]`, and the canvas hit targets `.scene-handle__hit`;
- **keyboard-only / focus-only, excluded from pointer targets and documented**: `[tabindex="-1"]` programmatic focus targets (`main`, dialogs, inspectors), `[tabindex="0"]` scrollable regions (keyboard scrolling, not a pointer control), the skip link while visually hidden (focus reveals it; `a11y.skip-link` proves that), decorative `[role="presentation"]`;
- the keyboard set (`{ keyboard: true }`) is the focus sweep's current selector, kept as is.

Shown-ness is `zoomVisibility`'s account (rendered, not collapsed, not inert, not transparent). A control is measured by its **effective** box: a checkbox/radio by its wrapping or `for`-label; everything else by its own bounding box; an SVG hit target by its bounding box. Target size: width and height ≥ 24 CSS px, else a finding naming the element, its size and the reading used.

### 9.3 `a11y.form-fields`

Every rendered `input`/`select`/`textarea` (pointer set, text-entry kinds): computed name non-empty and not sourced from `placeholder` alone; `[aria-invalid="true"]` has `aria-describedby`/`aria-errormessage` resolving to rendered, non-empty text; that text is inside `[role="alert"]`/`[aria-live]`, or the field is the active element after the state's preparation (scroll-to-invalid, §16). Tiers A/B/C on every state with a field.

### 9.4 `a11y.role-contract`

Real ARIA contracts and the two §23 examples, nothing invented: `[aria-expanded]` (MAVI pattern: rail, menu, drawers, disclosures, history) has a controlled region — `aria-controls` resolving, or a native `details`, and when `true` that region is rendered; every `aria-controls`, `aria-labelledby`, `aria-describedby`, `aria-errormessage`, `aria-activedescendant` id resolves; `[role="option"]` has no focusable descendant; `[role="listbox"]` contains only options/groups; no native-equivalent role on a generic element and no native control re-roled (row 5); dialogs stay with `overlay.*`. No naming requirement on `group`/`region`.

### 9.5 `a11y.live-regions`

(i) every `[aria-live]`, `[role="status"]`, `[role="alert"]` is rendered and not inside `aria-hidden`; (ii) **mounted before populated**: `run.mjs` evaluates a marker before a state's `prepare` (the page records every live region present once the page has settled) and the check after it: every live region whose text is new must be a marked node; a region inserted with its text is a finding. Evaluated on every prepared state (notices, confirmations, refusals, position readouts); on an unprepared state (i) alone. Tiers A/B/C.

### 9.6 `a11y.tooltips`

For every `[title]` on or within a control and every `role=tooltip` content: the text falls in one of §7's classes N/K/V/F/S as defined there (name; name + trailing key hint; a truncated element's full text; a `<time>`'s `dateTime`; text present elsewhere in the page's rendered text), else a finding naming the control and the text. Tiers A/B/C.

### 9.7 `a11y.shortcuts-in-text-entry`

On every state offering a text-entry control, after its own assertions: focus the first such control, press `?` (every surface) and `Delete` (Scene Editor), evaluate: no dialog/sheet opened, no object removed (the twin's count unchanged), the keystroke reached the field (`?` in its value); then restore the value. A probe in `run.mjs` like the overlay probes; `not-applicable` by state where no field exists. Tiers A/B/C.

### 9.8 `a11y.tab-order`

One helper (the zoom lane's `inOrder` extracted and strengthened; the zoom lane calls it): tab stops grouped by their nearest flex/grid/flow container; each container's visual reading order established — rows by vertical overlap, left to right within a row, top to bottom across rows; a column-flow container (`flex-direction: column`, `grid-auto-flow: column`) read down its column — and the Tab sequence restricted to the container must be that order; containers read one after another in their own order. Two named exemptions kept: side-by-side columns are separate containers read one after another (a Ledger row's identity then its actions); controls placed by their data (inline position). Over the Context Bar, the workspace/page and an open overlay, at every anchor. Negatives: `column-reverse`; `row-reverse`; a wrapped three-column grid with `order` scattering its items so every consecutive pair is diagonal.

### 9.9 `a11y.state-cues`

Over the §5 inventory: for each programmatic state marker present on the page, a non-colour cue by the §5 principle (a text or glyph child; a computed-style difference against an unmarked sibling of the same class in a non-colour property — `border-style`, `border-width`, `box-shadow` extent, `font-weight`, `text-decoration`, `outline`, `transform`, `stroke-width`, `stroke-dasharray`, `::before` content; the presence of handles for a selected canvas object; or a luminance ratio ≥ 3:1), the state named in the finding. Badges: non-empty text; no two badges in one view share text with different tones. Timeline: ticks of different `data-kind` differ in computed `transform` or height.

### 9.10 `a11y.focus-not-obscured` (2.4.11 at A/B)

In the existing focus sweep, after focusing each control: its centre point is its own (`zoomOwn`) and not under a sticky/fixed painted layer (`zoomPaintsAt`) — the T3 check, at the anchors. At Tier C the zoom lane already proves it; the rule is evaluated by both so one definition serves.

### 9.11 `a11y.spatial-twin` and `a11y.target-size`

As §8 and §6. `a11y.landmarks` gains two one-line checks (`document.title`, `html[lang]`) for 2.4.2 and 3.1.1 rather than new rules.

### 9.12 `a11y.reading-order` (WCAG 1.3.2, apart from focus order)

The programmatic reading sequence is the DOM (and so the AX tree) order. Where visual order carries meaning, DOM order must equal it. Bounded to the sequential regions the archetypes declare — never an inference over arbitrary CSS: the direct children of the page's region containers (`main`'s `.page`/`.workspace` and their region children: Context Bar, stage/primary, inspector/facts, summary, provenance), table rows in a `tbody`, items of a `ul`/`ol`, `dt`/`dd` pairs of a `dl`, the parts of a `StateRegion`. For each such container, siblings are ordered visually (rows by vertical overlap, then left to right — the §9.8 row model reused on content boxes, not tab stops) and that order must be their DOM order; siblings placed by their data (inline position) and absolutely positioned overlays are left out, and side-by-side regions are compared by the container that holds them. A `flex-direction: *-reverse`, a CSS `order`, or a grid placement that reorders meaningful siblings is a finding naming the container and the two siblings. Tiers A/B/C (Tier C's region order is also fixed by `tier.c-composition`; this rule proves the siblings inside). Negative: a Record facts `dl` under `flex-direction: column-reverse` (its visual pairs read bottom-up) fails; a Review page whose summary and provenance are swapped by `order` fails; the Ledger row's identity-then-actions columns pass.

### 9.13 `a11y.text-spacing` (WCAG 1.4.12, a bounded lane)

A lane like the zoom lane (`lane: 'text-spacing'`; `--text-spacing only|none`): `browser.addInitScript` installs, before first paint, the SC's overrides as the user would — `* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important } p { margin-bottom: 2em !important }` — and the state is then captured and judged by the **existing** assertions, nothing new: `text.overflow` (no text outside its box), `page.text-overlap`, `page.control-overlap`, `page.horizontal-overflow`, `archetype.contained-clipping`, `ledger.actions-reachable`, the focus sweep (reachability, `a11y.focus-not-obscured`), `a11y.target-size`, with deterministic settling. Coverage — **one canonical anchor for every distinct responsive composition, never every width**: §25 freezes compositions as ranges, so the lane takes the narrowest acceptance anchor of each range (the tightest case for spacing) and each orientation Tier B distinguishes: **1366×768** (Tier A — 1440/1920/2560 render the same compositions wider, with surplus going to the stage/inspector/player, and are not duplicated), **1024×768 and 768×1024** (Tier B landscape and portrait — distinct: the 768–1100 band folds Ledger columns differently at 768 than at 1024, and the portrait height changes the stacked compositions' scroll), **390×844** (Tier C — 430 renders the same composition and is not duplicated), plus **each state's declared `probeWidths`** (the compositions the sweep itself declares distinct: the Investigation's in-place inspector at 1600, the Workbench's side-by-side band at 1150–1230, the crossing bands at 600–767). Every swept state at each of its applicable anchors: ~228 × 4 + ~80 probe captures ≈ 1,000 captures, bounded by composition coverage. The lane's own entry, `a11y.text-spacing`, is **blocking at A, B and C** and records that the overrides were in force (the page-side environment check reads the computed `line-height`/`letter-spacing`/`word-spacing` of `body` and a paragraph's margin, as the zoom lane proves its factor); the full sweep is a harness fault unless the lane judged every state at every one of its applicable anchors (`zoomCoverageFaults`-style). Negative: a fixture whose fixed-height cell fits its text at normal spacing and clips it under the override fails in the lane and passes outside it; a fixture whose spaced label pushes a button under a fixed band fails.

### 9.14 `a11y.hover-content` (WCAG 1.4.13, the custom tooltip's behaviour)

One behavioural probe over the product's `Tooltip` (`.tooltip-anchor` → `[role="tooltip"]`), on every state that renders one, at every tier, driven through CDP (`browser.press`, and `Input.dispatchMouseEvent` through `browser.cdp`) with no guessed sleeps — the tooltip's delay is read from the motion token the component reads (`--dur`) and each step polls the `hidden` attribute to settle: (1) focus the trigger → the tooltip is shown; (2) it stays shown while focus stays (a second settled read); (3) Escape → hidden, `document.activeElement` unchanged; (4) move the pointer to the trigger's centre → shown; (5) move the pointer onto the tooltip's own box → still shown (hoverable; the anchor wraps the tip, which the probe proves rather than assumes); (6) move the pointer away → hidden; (7) the tooltip is `aria-describedby`-linked, never the name (as `a11y.names`). Native `title` is excluded: the browser controls it and WCAG 1.4.13 does not require author control over it. Negatives in `assertions.test.mjs`: a tooltip rendered outside its anchor that hides on the trigger's `pointerleave` fails (5); one that ignores Escape fails (3); one that closes when focus merely stays fails (2). The `Tooltip` unit tests remain aids.

Thirteen rules in all: `a11y.names`, `a11y.form-fields`, `a11y.role-contract`, `a11y.live-regions`, `a11y.tooltips`, `a11y.shortcuts-in-text-entry`, `a11y.tab-order`, `a11y.state-cues`, `a11y.focus-not-obscured`, `a11y.spatial-twin`, `a11y.reading-order`, `a11y.text-spacing` (a lane), `a11y.hover-content` — plus `a11y.target-size` rebuilt on §9.2. Every finding names the control, the reading and, where a rule has a named exception, which one applied.

## 10. Product changes expected

| File | Change | For |
|---|---|---|
| `styles/components.css` | `.checkbox { min-height: var(--control-min-target); }` | T1 |
| `styles/components.css` | `.chip button { flex: 0 0 auto; }`; `.chip .truncate { min-width: 0; }` | T2 |
| `features/scene-editor/SceneCanvas.tsx` | `HANDLE_HIT_R = 12` | T3 |
| `styles/components.css`, `features.css:398` | `.disclosure summary, .evidence-timeline__dense summary { min-height: var(--control-min-target); display: flex; align-items: center; }` | T4 |
| `features/scene-editor/SceneObjectList.tsx` (+ `features.css`) | a "Coordinates" `details` inside each zone `li` listing its vertices; a trip line's endpoints in its row; `aria-current="true"` on the selected item's control and an inset selection bar | §8; §5 |
| `styles/components.css` (`.table tbody tr.is-selected`) + the Ledger that marks rows selected | `aria-selected`/`aria-current` on the row; an inset bar beside the background | §5 |
| `styles/features.css` (`.scene-zone.is-invalid`, `.scene-line.is-invalid`) | `stroke-dasharray` for invalid geometry | §5 |
| `features/scene-editor/SceneEditorPage.tsx` (notices), `EvidenceTimeline.tsx` (navigator status) | live regions mounted empty, populated on change — only where `a11y.live-regions` fires | §9.5 |
| `shared/workspace/Segmented.tsx` | `aria-pressed` on the active item if absent | §5 |
| `StatusBadge` call sites with `title` | the reason into text if a call site is class R | §7 |

No token, primitive API, route, API or backend change; nothing sized to 44–48px; T1/T2/T3 behaviour untouched.

## 11. Supporting unit / component tests

Development aids only — fast, local, never X1 acceptance evidence: `SceneEditorPage.test.tsx` (Delete/nudge inert while typing); live-region component tests (`AppShell`, `AttentionRegion`, `TrackInspector`, `EvidenceTimeline`, Scene Editor notices: the region exists before its message and is the same node after); `SceneObjectList.test.tsx` (coordinates rendered per object); `status.test.ts` (`labelForStatus` distinct per status); a static `aria.test.ts` (no native-equivalent role on a generic element in source). The acceptance proof for each is the §9 rule.

## 12. Manifest transition

| Entry | From | To | Tiers | Why |
|---|---|---|---|---|
| `a11y.target-size` | measured/pending (S6 / X1) A/B/C | **blocking** | A, B, C (zoom cases included) | T1–T4 corrected; §9.2 reach; no finding |
| `a11y.section23-remaining` | future, pending X1 | **removed** | — | replaced by the named entries; the manifest test asserts its absence and that no entry is owned by X1 |
| `a11y.names` | — | assertion, **blocking** | A, B, C | rows 4, 16, 25 |
| `a11y.form-fields` | — | assertion, **blocking** | A, B, C | rows 8, 9, 22 |
| `a11y.role-contract` | — | assertion, **blocking** | A, B, C | rows 5, 6 |
| `a11y.live-regions` | — | assertion, **blocking** | A, B, C | row 7 |
| `a11y.tooltips` | — | assertion, **blocking** | A, B, C | row 16 |
| `a11y.shortcuts-in-text-entry` | — | assertion, **blocking**; `not-applicable` by state without a field | A, B, C | row 17 |
| `a11y.tab-order` | — | assertion, **blocking** | A, B, C | row 21 |
| `a11y.state-cues` | — | assertion, **blocking** | A, B, C | row 11 |
| `a11y.focus-not-obscured` | — | assertion, **blocking** | A, B; C via the zoom lane's call | 2.4.11 |
| `a11y.spatial-twin` | — | assertion, **blocking** at A, B; at C blocking where the timeline renders, `not-applicable` for the canvas | A, B, C by surface | rows 14, 15 |
| `a11y.reading-order` | — | assertion, **blocking** | A, B, C | WCAG 1.3.2 (§9.12) |
| `a11y.text-spacing` | — | assertion, `lane: 'text-spacing'`, **blocking** at A, B and C (one canonical anchor per distinct composition, §9.13) | A, B, C | WCAG 1.4.12 |
| `a11y.hover-content` | — | assertion, **blocking**; `not-applicable` by state without a tooltip | A, B, C | WCAG 1.4.13 (§9.14) |

Unchanged: `a11y.reduced-motion` (X4), `a11y.keyboard-journeys` (X2), `perf.*` (X3), every T1/T2/T3 entry; no blocking rule weakened. `validateManifest` refuses any entry still owned by X1 (the T2/T3 pattern) and learns the second lane name (`text-spacing`) beside `zoom`. The new entries flip in the X1 PR itself (§26: a rule blocks once its slice merges; the PR's sweep is clean first).

## 13. Development verification

Targeted and cheap: `node --test tools/web-visual-qa/test/assertions.test.mjs tools/web-visual-qa/test/manifest.test.mjs`; `vitest run` on touched files; `run.mjs --states <touched>` at the affected anchors (Scene Editor states, Search long names, validation states, Review overflow, one Ledger, the shortcut sheet) with the new rules on a scratch manifest as `measured/pending` first, to read every finding before the flip. No full sweep per edit.

## 14. Exact-head qualification

Once, on the head to be merged: harness tests (all files); `vitest run`; `tsc -b`; `vite build`; the full Tier A/B/C sweep (0 blocking, 0 harness errors, every new rule evaluated on every applicable state — `zoomCoverageFaults`-style coverage faults for a rule never evaluated where it applies); the full zoom sweep (`--zoom only`: shared primitives, the focus sweep and shared styles change); the **text-spacing lane** over every state at 1366×768, 1024×768, 768×1024 and 390×844 and at its probe widths (`--text-spacing only`), its environment check proving the overrides were in force on every capture and the coverage fault proving every state was judged at every applicable anchor — this is how the qualification establishes that 1.4.12 was actually exercised on every distinct responsive composition; the hover-content probe's evaluated count across the states that render a tooltip; `compare.mjs` against the merged T3 baseline on `6dffe137` (no capture changes validity; no finding under an existing rule); the Windows wide-font diagnostic for the zoom cases; `tools/verify_repo.py`; `git diff --check`; exact-head Linux CI (DejaVu Sans). Repeated only if a correction changes shared code.

## 15. Machine-verifiable X1 PASS criteria

1. `manifest.mjs`: no entry owned by `/X1/`; `a11y.section23-remaining` absent; the fourteen entries of §12 blocking at every tier stated (manifest test).
2. Every §4 row marked **X1** names, in its "gate proof" column, a rule of §12 or `contrast.test.ts`; none names a vitest test (this table is the record).
3. Full sweep on the exact head: all captures valid, **0 blocking**, 0 harness errors; each new rule evaluated on every applicable state (coverage faults otherwise).
4. `a11y.target-size`: 0 findings over the §9.2 helper at every tier; T1–T4's negatives fail on the pre-fix code (recorded in the PR against a scratch revert).
5. Every new rule has a negative in `assertions.test.mjs` that fails when the condition is violated; the harness suite passes.
6. `contrast.test.ts` coverage test passes and enumerates every painted text/state token pair.
7. `a11y.spatial-twin`: on every Scene Editor state at A/B, drawn objects = list items and each item exposes its vertices; on Review, intervals/markers = items.
8. Frontend tests, typecheck, build, `verify_repo`, `git diff --check`, exact-head CI green; T3 comparison clean.
9. The register row X1 cites the manifest change, the 1.4.10 non-claim, the Workbench 1.4.4 exception and the §3.1 Statement of Partial Conformance — Third Party Content (in substance the proposed sentence there).
10. `a11y.text-spacing`: the lane's results show every swept state judged at 1366×768, 1024×768, 768×1024 and 390×844 and at each of its declared probe widths, with the overrides in force on every capture (`executions` records the computed spacing of `body` and a paragraph's margin per capture), 0 blocking at A, B and C; its negative fixture fails in the lane and passes outside it.
11. `a11y.hover-content`: evaluated on every state that renders a `[role="tooltip"]`, 0 blocking; its three negatives fail.
12. `a11y.reading-order`: evaluated on every state, 0 blocking; its negatives fail.

## 16. Genuine remaining owner decisions

Only design choices within a compliant solution; no §23 MUST is offered as a deviation.

1. **Coordinates presentation in the twin (§8):** a "Coordinates" disclosure inside each zone's list item (planned: compact row, full geometry one disclosure away in the same item) **or** the vertices inline in every row (denser inspector). Both satisfy §23.
2. **Selection bar vs. glyph (§5):** the Ledger row and Scene navigator selection cue as an inset bar (the Search result row's existing idiom, planned) **or** a leading check glyph. Both are non-colour cues.

Nothing else is open: live-region timing, the twin's coordinates, tooltip content and the target sizes are MUSTs with one evident implementation each.

## 17. PR boundary

**One PR** (`stage3.5/s6-x1-a11y`), register row X1, from `main@5db448a3` or later: four CSS/constant edits and the small component changes of §10 on accepted surfaces (R4, R5, R6, the Ledgers); thirteen additive harness rules on reused primitives and existing assertions, one CDP helper (`axNodes`), one discovery helper, one extraction (`inOrder`), three probes in `run.mjs` (shortcuts, live-region marker, hover content) and one bounded lane (text spacing, modelled on the zoom lane). The R1 media analysis found no independent policy issue: the third-party statement is a sentence in the register row, not a product change. No audit item is independent enough to split; splitting the manifest transition from its rules would leave the placeholders half-retired. Review as for T3: one independent cold review of the implementation head, corrections, one Codex review, exact-head CI, register row; no X2–X4 work inside.

## 18. Self cold-review

Against §23 and §10.1, the register's X1 wording, the S6 slice definition and the harness as it is:

1. **Can every frozen §23 MUST be traced to an acceptance proof?** Yes — §4 maps all 26 rows: 7 proven by existing blocking rules or `contrast.test.ts`, 2 recorded statements, 1 owned by X4 (`prefers-reduced-motion`, a §23 MUST whose slice is S6/X4 by the frozen plan), 16 to a named §12 rule.
2. **Does every X1 PASS proof come through the harness or `contrast.test.ts`?** Yes — §15 criterion 2 makes it a checkable property of §4; §11 tests are aids only; the register is not amended.
3. **Is any requirement weakened through interpretation?** No — the twin exposes actual vertices (not a bounding box); live regions are mounted before populated or it is a finding; the checkbox reading is §10.1's own definition of "effective"; nothing is a "documented deviation".
4. **Is any new requirement invented?** No — `role=group`/`region` naming is gone; the role contract is real ARIA plus the two §23 examples; the WCAG D rows are recorded, not asserted; `a11y.focus-not-obscured` is WCAG 2.4.11, which §23's "as a whole" brings in and the T3 lane already asserts at 200%.
5. **Are X2/X3/X4 cleanly separated?** Yes — journeys (2.1.1 end to end) to X2; the pulse's pause mechanism and reduced motion to X4 (named in §3 so X4 closes 2.2.2 explicitly); no budget set.
6. **Is it one bounded PR?** Yes — thirteen rules on existing primitives and assertions (one of them a bounded lane), `a11y.target-size` rebuilt, four product fixes, the §5/§8 changes on accepted surfaces; §17.

Corrections made in this review: the first draft's counts (12/14) did not reconcile — §4 now sums 7 + 2 + 1 + 16 = 26 with each row in one class; the "unit tests as proof" rows (5, 7, 17) now have gate rules; the local `accessibleNameOf` is replaced by the AX tree; the pointer-target set is one helper with documented exclusions; the twin exposes vertices; `group`/`region` naming dropped; the deviation option removed from §16; the WCAG matrix added with every AA criterion classed once.

Adopted from the independent review: CR-1 (§3), CR-2 (§1 gate, §4, §15), CR-3 (§9.2), CR-4 (§9.1), CR-5 (§5, §9.9), CR-6 (§7, §9.6), CR-7 (§8), CR-8 (§9.4), CR-9 (§4 counts), governance (§16). Not adopted: none.

**Second review round (R1–R4 on `d10a47d1`), answered:**

1. *Is 1.2.1–1.2.5 based on MAVI's actual media ownership and rendering?* Yes — §3.1 is read from `ContentReadService` and `EvidencePlayer`: the operator's file is served and played as stored, unmodified, unmuted, not autoplayed; MAVI authors no time-based media. Each criterion is classed on its own (1.2.4 NA — no live media; 1.2.1/1.2.2/1.2.3/1.2.5 TP under WCAG's own partial-conformance provision for third-party content). No exception is invented and no media feature is added.
2. *Is 1.3.2 proven independently of tab order?* Yes — `a11y.reading-order` (§9.12) compares DOM order with visual order of content siblings in the declared sequential regions, non-focusable content included; `a11y.tab-order` stays the focus-order proof (2.4.3). Negatives: a reversed facts list; swapped Review regions.
3. *Is 1.4.12 actually executed under the prescribed overrides?* Yes — the `a11y.text-spacing` lane installs the four overrides before first paint on every state at one canonical anchor of every distinct responsive composition (1366×768; 1024×768 and 768×1024; 390×844; the declared probe widths), proves them in force per capture, and re-runs the existing clipping/overlap/overflow/reachability/obscuration assertions; blocking at A, B and C; a coverage fault if any state or anchor is missed; a negative that clips only under the override.
4. *Does 1.4.13 now prove dismissible/hoverable/persistent?* Yes — `a11y.hover-content` (§9.14) drives focus, Escape and the pointer through CDP against the custom `Tooltip` and proves all three plus "shown on focus and hover", with native `title` excluded as browser-controlled; the content classes stay in `a11y.tooltips`.
5. *Did these changes expand X1 into a new programme?* No — three rules and one lane, all on existing assertions and primitives; no captions, transcripts or media pipeline; no engine; no baselines; still one PR (§17).
6. *Are the prior corrections preserved?* Yes — CR-1…CR-9 and the governance correction stand; only the rows, totals, rules, manifest, qualification and criteria touched by R1–R4 changed. Not adopted from R1–R4: none.

**Third round (F1–F3 on `43dc36b0`):** F1 — the third-party wording now follows WCAG's Statement of Partial Conformance — Third Party Content: the footage is uncontrolled operator-supplied content played as supplied; where it prevents full AA conformance the surfaces presenting it are not claimed to conform fully because of it, and would conform if it were removed; it is not written out of scope, and the authored UI stays under the full qualification (§3, §3.1, the 1.2.x rows, §15). F2 — the text-spacing lane covers one canonical anchor of every distinct responsive composition (1366×768; Tier B landscape 1024×768 and portrait 768×1024; 390×844; each state's probe widths), blocking at A, B and C, with duplicates of the same composition not run (§9.13, §12, §14, §15). F3 — "ten rules" corrected to thirteen; no stale A/C-only coverage, Tier B not-applicable, or "outside the authored conformance claim" wording remains. Not adopted from F1–F3: none.
