# Stage 3.5 — UI/UX Professionalisation Programme: audit, architecture freeze and plan

**Status:** Architecture frozen (this document, specification v2.0 and the ADR-012 amendment of 2026-10-07). Implementation not started.
**Date:** 2026-10-07
**Baseline:** `main@98e5cd3f3ae8ca636ffbe2115c6b74b4ebcb2b16` (merge of PR #180; Stage 3 closed; UI-1 → UI-5 and Scene Analytics Slices 0–7 merged)
**Working label:** "Stage 3.5" is an owner-directed, cross-cutting product-quality programme that precedes capability Stage 4 (ANPR/OCR). It does not renumber capability stages 1–11.
**Governing documents:** `docs/architecture/ui-ux-design-specification.md` v2.0 (normative), `docs/decisions/ADR-012-operator-interface-design-architecture.md` (Amendment 2026-10-07), `AGENTS.md`.
**Exit gate:** `docs/reviews/2026-10-07-stage3-5-ui-ux-professionalisation-acceptance.md` (the only authoritative acceptance list; this plan references its row IDs).

Vocabulary used throughout, so that no reader mistakes one for another:

- **Observed** — seen in the real application (a named capture or a named file and line).
- **Inferred** — a design inference from an observation; the cause stated is the most likely one, not a measured one.
- **Frozen** — decided in specification v2.0 / the ADR amendment; implemented by a named slice.
- **Deferred** — recorded, not decided; owner or later slice.

---

## 1. Objective

Bring every operator surface to one professional standard — serious, quiet, dense, evidence-first, offline, trustworthy — by fixing the design system, the shared components and the archetypes, then finishing one reference surface per archetype and migrating the rest onto it. The standard is specification §2 (quality direction), §36 (craftsmanship), §37 (edge states), §38 (performance) and §25 (support tiers). The programme closes when the register says so, and Stage 4 begins after that.

## 2. Baseline verified

- `main` is exactly `98e5cd3f3ae8ca636ffbe2115c6b74b4ebcb2b16`; PR #180 is MERGED with that merge commit.
- `docs/reviews/2026-10-03-stage3-vehicle-subclass-acceptance.md` reads **STAGE 3 COMPLETE**, X1/X2/X3 PASS.
- Both roadmaps record Stage 3.5 as the next milestone (sequencing only, before this PR).
- Branch `stage3.5/ui-ux-architecture` was created from that exact commit. This PR is documentation only: no React component, production CSS, application behaviour, API contract, backend, dependency, font, light mode, mobile feature or Stage-4 content changes.

## 3. Method

In order: **inspect → audit → challenge → decide → freeze → cold review.**

1. **Read** the specification v1.0 in full, ADR-012, both roadmaps, the 2026-09-19 workspace record, the UI-1 → UI-5 records (specification §33) and `AGENTS.md`.
2. **Inventory the frontend from the router** (`src/web/mavi-web/src/app/router.tsx`, `AppShell.tsx`, `shared/workspace/*`, every page, every shared component, `styles/*.css`, tests, the visual-QA harness and its 125 fixture states).
3. **Inspect the real application** with the existing harness (`tools/web-visual-qa/run.mjs --keep`) against the production build, 125 states × 4 anchors (1366×768, 1440×900, 1920×1080, 2560×1080), and read the captures and their measurement sidecars. §4 states exactly what was inspected.
4. **Audit** per route and per journey; classify each finding P0–P3 and systemic / component / archetype / single-surface.
5. **Challenge** the v1.0 frozen decisions where the evidence showed them insufficient; **decide**; **freeze** in the specification (v2.0) and the ADR amendment; preserve history.
6. **Cold review** by an independent reader against the §19 checklist; material issues fixed before the PR.

## 4. What was inspected (exact)

**Code:** every file under `src/web/mavi-web/src/app`, `shared/workspace`, `shared/async`, `shared/ui`, `shared/status`, `shared/evidence` (heads), `features/*` page components and the Search, Review, Scene Editor and Analytics feature components named in §5; `styles/tokens.css`, `base.css`, `layout.css`, `components.css`, `workspace.css`, `features.css` (2,276 lines across the six files); the test setup and the names of the 62 test files (~852 cases); `tools/web-visual-qa/{run,cdp,assertions,states}.mjs` and its README.

**Visual pass (harness, real application, production build, intercepted fixtures, Chromium headless, `deviceScaleFactor 1`, `mobile: false`):** all 125 states at 1366×768, 1440×900, 1920×1080 and 2560×1080 — **500 captures, zero automated findings** (no horizontal overflow, no page error, no overlapping controls, every `var()` resolved, focus ring painted on every discovered control, width discipline, one Context Bar, archetype geometry and scroll ownership, inspector placement, no stray dialog/modal/inert). The captures read by eye for this audit, by state (at 1366×768 unless noted):

- Overview: `overview`, `overview-empty`, `overview-partial-failure`; `overview` at 2560.
- Cameras: `cameras`, `cameras-dense`, `cameras-empty`, `cameras-loading`, `cameras-unavailable`, `cameras-create`, `cameras-create-invalid`, `cameras-create-conflict`; `cameras` at 2560.
- Videos: `videos`, `videos-dense`, `videos-empty`, `videos-filtered-empty`, `videos-unavailable`, `videos-cameras-unavailable`; `videos-dense` at 2560.
- Processing queue: `processing-queue`, `processing-queue-dense` (also at 1920 — captured mid-load, see §5.4), `processing-queue-empty`, `processing-queue-row-unavailable`, `processing-queue-unavailable`, `processing-queue-analytics`.
- Import: `import`, `import-invalid`, `import-no-active-cameras`, `import-cameras-unavailable`.
- Processing detail: `processing-detail-completed` (also at 2560), `-running`, `-failed`, `-unavailable`, `processing-finalizing`, `processing-failed-finalization`, `processing-detail-analytics-ready`, `-stale`, `-failed`.
- Scene Editor: `scene-editor`, `-dense` (also at 2560), `-dirty`, `-long-identity`, `-unconfigured`, `-unavailable`.
- Search: `search` (also at 2560), `-loading`, `-empty`, `-unavailable`, `-invalid`, `-grid`, `-filtered`, `-filtered-unresolved`, `-field-errors`, `-no-timezone`, `-rail-overflow`, `-videos-unavailable`, `-long-names`, `-paged` (also at 1920), `-full-page`, `-continuation-failed`, `-inspecting` (also at 1920), `-inspecting-dense`, `-inspector-unavailable`, `-threshold` at 1440, `-ultrawide` at 2560, `-analytics-rail`.
- Review: `review` (also at 2560), `review-bright`, `review-multi-visit`, `review-overlap-3`.
- Analytics: see §5.5 (captured last in the sweep).

**Not inspected, and not claimed:** any width below 1366 (the harness default sweep has none, and the Tier B/C sweep is the first act of the harness-v2 slice, §9); the remaining Review fixture states beyond the four above (their geometry assertions passed; their appearance was not read by eye); keyboard-only operation end to end (the harness checks focus painting per control, not task completion by keyboard); a real touch device; zoom at 200%. Where this plan states a Tier B or C behaviour it is a **frozen design rule**, not an observation.

## 5. Audit findings

Severity: **P0** blocks operation; **P1** blocks a workflow or an accessibility obligation; **P2** a visible quality or consistency defect on a workflow surface; **P3** a detail. Layer: **systemic** (design system / shell), **archetype**, **component**, **surface** (single page).

### 5.1 Systemic and archetype findings (fixed at the layer named, never per page)

| ID | Sev | Layer | Finding | Evidence | Frozen response |
|---|---|---|---|---|---|
| F1 | P2 | archetype: Ledger | Every Ledger renders its table inside a viewport-high bordered frame regardless of content. Two rows, a spinner, an empty message or an unavailable alert sit top-left in a ~640px-tall box; at 2560 a ~750px column-capped table sits in a ~1800px frame. | Observed: `cameras`, `cameras-loading`, `cameras-unavailable`, `videos-filtered-empty`, `processing-queue` at 1366; `cameras`, `videos-dense` at 2560; `processing-queue-dense` at 1920. | §4.1 amended: containment bounds the table, state presentations uncontained at the table's top offset. Slice S1. |
| F2 | P2 | systemic: colour role | The accent-filled primary button is repeated on every row (`Process` ×14 in one Videos viewport; `Results` per queue row), against §8.1 "accent = *the* primary action". | Observed: `videos-dense`, `processing-queue-analytics`. | §8.1/§16 amended: one accent primary per surface; row actions secondary. Slice S1 (Button, row-action pattern). |
| F3 | P2 | systemic: state grammar | The §14.1 boundary is used by 3 of 10 surfaces (the three Ledgers); the rest select states by hand. Result: four placements of "unavailable" (page-top alert with a lone Retry below — `scene-editor-unavailable`; in-region alert with trailing Retry — `search-unavailable`; page-wide alert above an otherwise empty column — `processing-detail-unavailable`, `search-invalid`; hatched EmptyState for an unavailable media panel on Overview), two loading grammars (spinner text on Cameras, skeleton rows on Videos/Queue, "Searching visual intelligence…" on Search), three stacked amber alerts for one unavailable video list (`scene-editor-dense`), and two words for one missing-thumbnail condition (`No evidence` list vs `Evidence unavailable` grid). | Observed, captures named. Inferred cause: `AsyncBoundary.tsx` is opt-in; `OverviewPage`, `VideoImportPage`, `ProcessingPage`, `SceneEditorPage`, `VisualSearchPage`, `VideoReviewPage`, `AnalyticsPage` compose states ad hoc. | §14.1 amended (boundary everywhere; placement rule); §37.1 catalogue; `StateRegion` and `EvidencePlaceholder` primitives (§27). Slice S1. |
| F4 | P2 | systemic: shell IA | Rail label vs crumb mismatch (`Search` / `Visual Search`); Import crumbed under Videos but a rail peer; Review crumb `Evidence Review › …` with no owning section and nothing highlighted in the rail; Scene/Analytics highlight Cameras by accident of path prefix; two controls (`Back to search` + `Visual Search`) for one destination on Review. | Observed: `search`, `import`, `review`, `scene-editor` captures; `AppShell.tsx` nav and `ContextBar` usage per page. | §5 amended: one IA map; crumb derived; skip link; landmarks; labelled 32px collapse control. Slice S1. |
| F5 | **P1** | systemic: accessibility | No skip link; the Investigation drawer (<1600) and the Workbench drawer (1101–1149) are CSS-only overlays with no focus movement, no containment and no `inert`; `window.confirm` at `SceneEditorPage.tsx:293`, `:302` and `useUnsavedChangesGuard.ts:19` (§15 already forbids it); no automated structural accessibility assertion beyond focus-ring painting and token contrast. | Observed in code; drawers confirmed as overlays in `search-inspecting` at 1366 and `search-threshold` at 1440. | §5, §15, §20, §23 amended; `Dialog`, `Drawer` primitives; harness assertions. Slice S1 (primitives), S2 (assertions). |
| F6 | P2 | component: Field | Invalid state: amber border visually near-identical to the resting border, beside red helper text — two hues for one state and a weak cue. | Observed: `cameras-create-invalid`, `import-invalid`. | §12 amended (one error hue; scroll-to-first-invalid). Slice S1. |
| F7 | P2 | component: Button | Disabled primary rendered by opacity reads as a translucent primary ("half on"). | Observed: `scene-editor` (Save revision disabled), `scene-editor-unconfigured`. | §12 amended (tokens, not opacity). Slice S1. |
| F8 | P2 | archetype: Review | At 1366×768 the Evidence Player scrolls out of view while the rail's facts are read; the §4.5.1 sticky rule is declared (`.workspace__player { position: sticky }`) but ineffective. | Observed: `review`, `review-bright`, `review-multi-visit`, `review-overlap-3` at 1366 (player column empty at the scrolled position); harness sidecar reports `playerSticky: "sticky"` from computed style and `summaryTop: -474`. Inferred cause: `.workspace__review-grid { align-items: start }` makes the main column only as tall as its own content, so there is nothing to stick within. | §36.3 (sticky in the rendered page); §26 asserts rendered behaviour. Slice S2 (assertion) and S3-Review (fix). Severity P2 not P1 because the operator can scroll back; it is the one finding on the evidence surface that contradicts a v1.0 frozen rule in practice. |
| F9 | P2 | systemic: responsive | Nothing below 1366 is designed: the rail auto-collapses at ≤760 with its toggle hidden; stacking at ≤1100 is flex wrapping; the 1101–1149 band and all Tier B/C anchors are outside the default sweep. | Observed in `layout.css`, `workspace.css` media queries and `run.mjs` default widths; **not visually inspected** (see §4). | §25 support tiers; §26 widened sweep. Slices S2, S5. |
| F10 | P2 | systemic: visual regression | Harness assertions are sound but it does not run in CI, there is no layout assertion for pitch/primary count/containment/state placement/focus order, and a full pass is 500 captures read by a person. | Observed: `.github/workflows` has no harness job; `assertions.mjs` scope. | §26 amended (D10). Slice S2. |
| F11 | P2 | archetype: Ledger-summary | Overview has no attention content: four readouts, a recent-Tracks list and a status breakdown occupy ~55% of 1366×768 and far less at 2560 under the centred cap; the one thing an operator opens the product to learn (what failed, what is stale, what is unavailable) is not on it. | Observed: `overview`, `overview-partial-failure`, `overview` at 2560. | §4.1.1 amended: attention-first. Slice S3-Overview. |
| F12 | P2 | component: ToggleChip | Evidence-layer toggles (Zones, Trip lines, Crossings, Bounding box, Trajectory) show "on" as an accent border and accent text, not a filled pressed state; on/off is hard to read at a glance, against §12 pressed. | Observed: `search-inspecting` at 1920, `review` at 2560. | §27 `ToggleChip`. Slice S1. |
| F13 | P2 | archetype: Investigation | On submit with field errors the rail's error is above its scroll position and invisible; `search-field-errors` at 1366 shows no visible error. The keyboard legend (`j / k move · Enter open · Esc close`) is permanent header chrome; a per-row `#n` ordinal is noise. | Observed: `search-field-errors`, `search` captures. | §12 (scroll-to-first-invalid), §17 amended. Slices S1, S3-Search. |
| F14 | P3 | systemic: density | Ledger row pitch measures ~43px against the frozen 36–40 (8px cell padding around a 20px badge line). | Observed: `cameras-dense`, `videos-dense` (14 rows in ~600px). | §16 amended (measured; harness asserts). Slice S1. |
| F15 | P3 | systemic: hygiene | Dead CSS (`.rail-layout`, `.field--inline`, `.search-filter-grid`, `.field-help`, `.panel--form`, `.table--dense`, `.tabs`); `PageHeader` and its `.page-header` style retired with their one remaining use (Review's invalid state); `Tabs` unused; `.table--compact` referenced by Analytics but undefined; `IconName` is effectively `string`; `AnalyticsPage` lacks the `.page` wrapper and deep-imports workspace internals; eight inherited hover-text-colour violations allow-listed in `styles/tokens.test.ts`. | Observed in code. | §27 retire table. Slice S1. |
| F16 | P3 | component: ContextBar | Long identity (`north-gate-0900-very-long-original-file-name-for-truncation.mp4`) is not truncated; it fits at 1366 by luck and will push badges and actions at Tier B. | Observed: `processing-detail-running`; `scene-editor-long-identity` truncates the camera name but not the file name. | §27 refine ContextBar identity. Slice S1. |
| F17 | P3 | component: FileInput | The Import form's file control is the native button at native metrics beside token-styled controls. | Observed: `import`. | §27 `FileInput`. Slice S1. |
| F18 | P3 | systemic: disclosure | Forensic detail at the operational tier: polygon vertices at six decimals in the Scene Editor properties panel; the full Track GUID in the Review rail's first screen; scene-revision identity printed twice in one Investigation inspector; five crossings listed inline with no bound. | Observed: `scene-editor-long-identity`, `review`, `search-inspecting`, `search-inspecting-dense`. | §37.2 tiers; §20 amended. Slices S3-Scene, S3-Search, S3-Review. |
| F19 | P3 | systemic: copy | `Searching visual intelligence…`; `Frames processed: Final count after completion` shown on a *failed* run; standing prose subtitle on the Review Evidence Set panel; `Visual Search` as a product name in the crumb. | Observed: `search-loading`, `processing-detail-failed`, `review`, `search`. | §36.2 copy rule. Slices S3. |
| F20 | P3 | component: rail | Collapse toggle is a 26px icon-only ghost at the rail foot; API health line at 11px muted. | Observed: every capture. | §5 amended. Slice S1. |

### 5.2 Surface-specific findings (closed inside the owning reference or migration slice)

| Surface | Findings |
|---|---|
| Overview | F11; the media-by-status "unavailable" panel uses the hatched not-configured treatment (F3). |
| Cameras | F1, F6, F14; long names truncate with a pointer-only `title` (§16 amended). Dense state otherwise good. |
| Videos | F1, F2, F14. Dense state good. |
| Processing queue | F1, F2; failure code in mono inline beside the badge is the right pattern and is kept. `processing-queue-dense` at 1920 was captured before its rows loaded (two rows showing `Loading run…`) — a fixture timing artefact, recorded as not verified at 1920, to be made deterministic in S2. |
| Import | F6, F17; `import-no-active-cameras` nests a hatched block inside a bordered panel inside the Record column (containment depth 2, §11). |
| Processing detail | F3 (`-unavailable` leaves the primary column blank with no retry), F16, F19; the completed/running/failed/stale states are otherwise the best-finished Record states in the product and are kept as the Record reference. |
| Scene Editor | F5 (`window.confirm`), F7, F18, F3 (three stacked alerts); three ways to start drawing in the unconfigured state (mode strip, panel `+ Zone`/`+ Line`, placeholder buttons) — reduce to the mode strip plus the placeholder's one primary. Otherwise the strongest surface and the Workbench reference. |
| Search | F3, F12, F13, F18, F19; the list row's `No evidence` 96×64 black box reads as a broken image (→ `EvidencePlaceholder`); grid card metric labels wrap at 3-up; a long camera name makes a single very long row line (truncate at identity width). Continuation (`Load more`, `Retry load more` under an in-region alert) is the right pattern and is kept. |
| Review | F8, F18, F19, F4 (two back controls); the rail is otherwise well-ordered (summary → analytics → evidence set → identity). |
| Analytics | See §5.5. |

### 5.3 Journeys

| Journey | Finding |
|---|---|
| Import → Process → Status → Results | Coherent. Friction: Import's crumb says it lives under Videos (F4); the queue row's accent `Results` competes with the Context Bar (F2); the detail's `Open results` primary is correct. |
| Search → filter → scan → inspect → evidence → return | Coherent and keyboard-navigable in the list. Friction: legend as chrome and ordinals (F13); missing-thumbnail boxes (F3); drawer focus (F5); the return crumb from Review (F4). |
| Vehicle search → Car refinement → inspect → Review | Works; `Vehicle · Car` renders only when the server exposes it. No finding beyond the above. |
| Configure scene → analyse → search analytic → why matched → inspect | Coherent; the Scene Editor's dirty/save/revision chrome is the reference. Friction: stacked alerts (F3), vertices at tier 1 (F18), `window.confirm` (F5). |
| Cameras / Videos / Processing monitoring | Ledgers scan well when dense; sparse and failure states read as unfinished (F1, F3). Overview does not help the monitor (F11). |
| Error / retry / recovery | Every unavailable state has a retry *somewhere*; the somewhere differs four ways (F3). Continuation failure in Search is the model. Processing-detail unavailable has no retry. |

### 5.4 Harness and fixture findings

- `processing-queue-dense` at 1920 captured mid-load; the state needs a settled-network wait or a deterministic fixture delay. Slice S2.
- The sidecar's `playerSticky` reads computed style; the rendered behaviour must be measured (scroll, then check the player's viewport rectangle). Slice S2.
- Some Investigation captures show the rail at a non-zero scroll position (`search-filtered`, `search-analytics-rail`); this is the harness scrolling to a target, not a product defect, and is recorded so that no one reads it as one.

### 5.5 Analytics surfaces (Camera Analytics, Workbench)

Read by eye at 1366×768: `analytics-activity` (also at 2560), `-occupancy`, `-heatmap`, `-no-scene`, `-unavailable`, `-incomplete`, `-heatmap-too-large`. Their geometry assertions and those of `-line-crossings`, `-complete-zero`, `-heatmap-evidence-unreadable` and `-heatmap-sparse` passed at all four anchors.

| ID | Sev | Layer | Finding | Evidence |
|---|---|---|---|---|
| F21 | P2 | surface (F15 cause) | The Analytics workspace has no page gutter: the mode strip and the chart are flush against the navigation rail, and the inspector is flush against the right and bottom viewport edges. The only surface without the `.page` wrapper. | Observed: every `analytics-*` capture. |
| F22 | P2 | archetype: Workbench toolbar | The filter band is a three-row form, not a toolbar: a row of four unlabelled text presets (`Last hour … Last 7 days`), a row of labelled fields (From, To, Interval, Object class, Metric) with helper text beneath, and `Refresh` alone on a third row (or trailing the fields on Heatmap — the two modes differ). §4.1/§10 toolbar is one 32px band. | Observed: `analytics-activity`, `analytics-heatmap`. |
| F23 | P3 | disclosure | Tier-1 prose paragraphs in the inspector (`Not additive … counts each Track once`, `This is trajectory sample density …`, `Figures appear once a window has been read.`); the coverage strip prints a truncated revision identifier (`Revision aaaaaaaa…`) at tier 1. | Observed: `analytics-activity`, `-heatmap`, `-unavailable`, `-incomplete`. |
| F24 | P3 | component: table | The `By bucket` table's sticky header paints over a scrolled row (`22 SEPT 2026, 04:15` visible under `PERSON VEHICLE`). | Observed: `analytics-incomplete`. |
| F25 | P3 | state vocabulary | A camera with no scene shows the Context Bar badge `Coverage incomplete` (amber); the condition is *not configured* (§14), not partial coverage. | Observed: `analytics-no-scene`. |

What is right and is kept: the chart's use of width at 2560; the in-region unavailable alert with trailing Retry; the `too much to map` and `not every run analysed` states, which withhold rather than show partial figures and offer one action; the heatmap legend and scrim.

**Response:** F21, F22 and F25 close in S4 (Analytics migration onto the Workbench reference); F23 and F24 close in S1 (StateRegion/tier rules; table header stacking context).

## 6. Challenges to v1.0 and decisions

| v1.0 position | Challenge from evidence | Decision |
|---|---|---|
| §25 four desktop anchors; <1100 "functional, not optimised"; <768 "must not break" | Nothing below 1366 was designed or inspected; "must not break" is not a rule. | **Changed:** three support tiers with range rules (§25). Mobile workstation **not** adopted. |
| §11 "a border marks a scroll boundary" applied to the Ledger slot | Produces an empty frame around sparse content at every width. | **Changed:** containment bounds the table (§4.1). |
| §8.1 accent = the primary action | Interpreted per row; fourteen primaries per viewport. | **Clarified as frozen:** one per surface (§8.1, §16). |
| §14.1 boundary "implementation-flexible" | Flexibility became optionality; 3 of 10 adopters. | **Changed:** mandatory everywhere; placement and presentation fixed (§14.1, §37). |
| §26 "scripted browser pass" with screenshots never committed | Sound but unscaled: no CI, no layout assertions, 500 captures per pass. | **Changed:** CI layout assertions at every tier anchor; captures as expiring CI artefacts; pixel baselines rejected with reasons (§26). |
| §34.1 transitional clause | Expired by its own terms; still cited. | **Closed.** |
| §4.1.1 Overview centred summary | Not an attention surface. | **Kept centred; made attention-first.** |
| §4.2 Record centred at 1600 | 900px void each side at 2560. | **Reaffirmed** after measurement: a reading column is correct; regions content-sized. |
| §4.4 open decision 4 (results cap with nothing selected) | ~1300px empty at 2560 when nothing is inspected. | **Reaffirmed**: a column that moves on selection is worse. |
| §12 disabled = opacity; invalid = warning border | Translucent primaries; invalid near-invisible. | **Changed** (§12). |
| §31 mobile deferred | Owner asks for intentional degradation, not support. | **Kept deferred**; Tier C defines degradation only. |
| ADR-012 Decision 6 (no dependency) | Tempting for a11y engine / screenshot diffing. | **Reaffirmed**; nothing added. |

## 7. Non-goals (this programme)

Light palette; density preference; resizable panes; command palette (the `?` sheet and `g` keys are shell obligations and are in scope; a palette is not); a mobile analyst experience; a notification centre; the Wall archetype; any new UI dependency, font, icon set or framework; any API, domain, worker, binding or qualification change; any Stage-4 (ANPR/OCR) surface; decorative mockups; copying any other product's components or appearance.

## 8. Design-system changes (frozen; implemented in S1)

- **Tokens:** add `--control-disabled-bg`, `--text-disabled`, `--alert-max`, `--measure`, two scrollbar tokens, skeleton tokens matching row pitch; no primitive is referenced by a component; token count reported, not targeted.
- **Type, spacing, radii, borders, surfaces, elevation, icons, control heights, table density, content widths:** as §10, §11, §36 — unchanged values, now asserted.
- **Primitives added:** Dialog, Drawer, Tooltip, EvidencePlaceholder, FileInput, ToggleChip, StateRegion (§27). **Refined:** Button, Field, Alert, LoadingState, EmptyState, ContextBar, rail collapse control. **Retired:** PageHeader, Tabs, dead CSS, `IconName` as string, the hover allowlist.
- **Motion tokens:** unchanged (120/180ms; reduced motion zeroes).
- **Breakpoints:** 768, 1100, 1150, 1366, 1600 as range boundaries; new ones only by measurement.
- **Charts and heatmap:** unchanged scales (§32 decisions 2a, 2c); the legend and the coverage strip adopt the §37 state presentations.

## 9. Archetype implications

| Archetype | Change |
|---|---|
| Ledger | Table-bounded containment; uncontained states; secondary row actions; measured pitch; Tier B column collapse by priority; Tier C single-column list. |
| Ledger-summary | Attention-first Overview. |
| Record | Content-sized regions; identity truncation; unavailable-with-retry in the primary column; Tier C rail-first. |
| Workbench | Dialog replaces confirm; alerts consolidated; vertices to tier 3; one way to start drawing; Tier C unsupported state. |
| Investigation | Drawer primitive; legend to `?`; ordinals removed; EvidencePlaceholder; scroll-to-invalid; one vocabulary; inspector tiers. |
| Review | Rendered sticky player; one back route; tier-3 identity; Tier C full-width read-only. |

## 10. Reference surfaces (selected after the audit)

| Archetype | Reference | Why this one |
|---|---|---|
| Ledger-summary | Overview | First screen; carries the attention-first change. |
| Ledger | Videos | Densest Ledger; has filters, per-row actions, progress, failure codes, long names and every §14 state in fixtures. |
| Record | Processing detail | Already the best-finished Record; exercises progress, failure, stale analytics, diagnostics disclosure. |
| Workbench | Scene Editor | v1.0 reference; canvas, inspector, revisions, dirty state, confirm dialog. |
| Investigation | Search | Rail, chips, list/grid, continuation, drawer/in-place inspector, evidence set. |
| Review | Video Review | The evidence surface; player, timeline, rail, evidence set. |

Together they exercise every primitive in §27 and every state in §37.1.

## 11. Responsive matrix (frozen rule, to be inspected in S5)

| Anchor | Tier | What is asserted |
|---|---|---|
| 1366×768, 1440×900, 1920×1080, 2560×1080, 2560×1440 | A | Every §4 rule, every §34 item, the full state catalogue. |
| 1024×768 | B | Rail collapsed-with-toggle; Ledger priority collapse; Workbench inspector drawer; Investigation rail drawer; Record stacked; Review stacked; no overflow; all actions reachable. |
| 768×1024 | B | As 1024 with portrait stacking; toolbar wraps ≤2 rows. |
| 430×932, 390×844 | C | Menu-control rail; single-column Ledgers; Record rail-first; Workbench unsupported state; Investigation full-width drawers; Review read-only stack; no overflow; no clipped control. |
| 200% zoom at 1366×768 | C-equivalent | Same as 390–767 (effective 683px). |

## 12. Visual-QA strategy (frozen; see specification §26)

Harness kept; assertions extended; CI job (assertions only, artefacts expire); anchors widened to every tier; pixel baselines rejected; bounded human pass per PR; typography determinism recorded. No dependency added; the CI runner's existing Chromium and ffmpeg are used.

## 13. Accessibility strategy (frozen; §23)

WCAG 2.2 AA target; skip link, landmarks, Dialog/Drawer focus contracts, keyboard completeness, tab order = reading order, associated errors, reduced motion, 200% zoom reflow under Tier C; structural assertions in the harness; contrast from tokens; no engine added; 1.4.10 at 320px recorded as not targeted and the Workbench canvas at 200% zoom on 1366 recorded as a 1.4.4 exception.

## 14. Performance requirements (frozen; §38)

No layout shift, no jank, no expensive animation, no unnecessary spinners, immediate local feedback, layout preserved on refresh, stable query identity, large lists usable; harness measures CLS during loading→content, long tasks on first interaction, resolved font; **budgets set only from the first measured baseline, recorded in the register — no number is stated before measurement.**

## 15. Slices

Each slice is one PR (or a short run of PRs under one register row), independently reviewable and revertible, leaves `main` shippable, and runs the full test suite, typecheck, build, `verify_repo` and the §26 sweep for the surfaces it touches.

| Slice | Scope | Register rows | Depends on |
|---|---|---|---|
| **S0 — Audit and freeze** | This PR: specification v2.0, ADR-012 amendment, plan, register, roadmap/README pointers. No code. | A1–A6 | — |
| **S1 — Foundation** | Tokens (§8); primitives added/refined/retired (§27); Ledger containment (§4.1); one-primary rule; boundary adoption on every surface with the §37.1 presentations (no visual redesign of surfaces beyond what the primitives change); IA map, skip link, landmarks, rail control; `window.confirm` → Dialog; drawers → Drawer; invalid/disabled states; row pitch; truncation; dead CSS. | D1–D9 | S0 |
| **S2 — Harness v2** | New assertions (§26); tier anchors; deterministic waits; rendered-sticky and CLS/long-task measurement; CI job with artefact upload; baseline measurement recorded. | V1–V5, P1 | S1 (assertions target the primitives) |
| **S3a — Reference: Overview + Videos** | Attention-first Overview; Videos finished to §36; both inspected at every tier A anchor and every state. | R1, R2 | S1, S2 |
| **S3b — Reference: Processing detail** | Record finished; unavailable-with-retry; identity truncation; tiers. | R3 | S1, S2 |
| **S3c — Reference: Scene Editor** | Workbench finished; alerts consolidated; vertices tier 3; one drawing entry; Dialog in use. | R4 | S1, S2 |
| **S3d — Reference: Search** | Investigation finished; legend/ordinals; placeholder; scroll-to-invalid; inspector tiers; Drawer in use. | R5 | S1, S2 |
| **S3e — Reference: Review** | Rendered sticky player; one back route; identity tier 3; evidence set copy. | R6 | S1, S2 |
| **S4 — Migration** | Cameras and Processing queue (Ledger), Import (Record), Camera Analytics (Workbench) onto the references; nothing left on a pre-v2.0 pattern. | M1–M4 | S3a–S3e |
| **S5 — Tiers B and C** | Designed compositions per §25 table on every surface; the first Tier B/C inspection; `mobile: false` stays (no touch emulation claimed). | T1–T3 | S4 |
| **S6 — Accessibility and performance hardening** | Every §23 row asserted on every surface; keyboard-only completion of the six journeys; CLS/long-task budgets set from the S2 baseline and met. | X1–X4 | S5 |
| **S7 — Final acceptance** | Full 125-state sweep at every anchor; cold review; register closure; roadmap/README closure wording; Stage 4 unblocked. | C1–C5 | S6 |

Ordering is strict S0 → S1 → S2 → S3 → S4 → S5 → S6 → S7 except that S3a–S3e may run in parallel after S2.

## 16. Dependencies

None added, in any slice. Each slice's PR states this explicitly. If a slice finds it cannot meet a rule without a dependency, the rule is met another way or the rule is amended by ADR — the dependency is not added first.

## 17. Acceptance

The register is the only exit gate. Its structure: **A** (architecture and audit — this PR), **D** (design-system implementation), **V/P** (harness v2 and baseline measurement), **R** (reference surfaces), **M** (migration), **T** (tiers), **X** (accessibility/performance), **C** (closure). Closure conditions are specification §39. P2 single-surface and P3 findings open at closure are listed with an owner slice or an explicit, owner-accepted deferral; they do not block Stage 4 unless the register says so. "Looks better" is not an exit criterion anywhere.

## 18. Rollback

Every slice is a revert-able PR. S1 is the widest diff; it is split into PRs by primitive family (tokens+Button+Field; StateRegion+boundary adoption; Dialog+Drawer+Tooltip; shell IA; hygiene) so that any one family can be reverted without the others. Reference-surface PRs touch one feature directory each. The harness CI job can be disabled by workflow edit without touching product code. Specification v2.0 is additive and marks v1.0 text historical rather than deleting it, so a decision reversal is a dated amendment, not a restore.

## 19. Cold-review checklist (applied to this freeze and to every later slice's documentation)

1. No contradiction with ADR-012 Decisions 1–6 as written, or the contradiction is an explicit dated amendment.
2. No second design system, feature dialect or page-specific CSS system introduced or permitted.
3. No vague "premium" language standing in for a measurable rule; every craftsmanship standard names what is measured.
4. No imitation of another product's components, styling or appearance; the quality direction is a standard of finish, not a visual target.
5. No white space, oversized cards, decoration, motion or "AI-looking" effects admitted as quality.
6. Responsive rules are ranges, not snapshots; desktop compression is not accepted as responsiveness; nothing below Tier A is accepted as an operational workstation; mobile stays deferred.
7. No accessibility regression admitted; the WCAG 2.2 AA target and harness assertions are stated, and 1.4.10 at 320px is recorded as not targeted rather than claimed.
8. Visual QA is not subjective: the gate is deterministic assertions; the human pass is bounded and enumerated.
9. Scope is bounded: slices named, each independently reviewable and revertible; no rewrite PR; no stream of cosmetic PRs; non-goals stated.
10. Every systemic defect is assigned to the token, component or archetype layer, not to pages.
11. No premature implementation detail (no CSS values frozen that were not inspected; no component API beyond its contract).
12. No dependency, font, framework or engine added or permitted by default.
13. Nothing a Stage-4 (ANPR/OCR) surface could not follow: every rule is archetype-generic.
14. Long names, dense data, missing evidence, failures, stale and partial states, and large evidence sets are addressed, not assumed.
15. Every "observed" statement names a capture or a file; every inference is marked as one; nothing uninspected is described as inspected.
