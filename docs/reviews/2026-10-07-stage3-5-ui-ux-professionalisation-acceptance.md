# Stage 3.5 — UI/UX Professionalisation Programme: Acceptance Register

**Status:** OPEN — architecture frozen (rows A1–A6); implementation in progress: S1a (PR #182) closed D1 and the S1a portion of D3; S1b (PR #183) closed D6 and added StateRegion and EvidencePlaceholder (D2 partial) and the Alert-adoption portion of D3.
**Date opened:** 2026-10-07
**Baseline:** `main@98e5cd3f3ae8ca636ffbe2115c6b74b4ebcb2b16` (merge of PR #180; Stage 3 closed)
**Governing documents:** `docs/architecture/ui-ux-design-specification.md` v2.0; `docs/decisions/ADR-012-operator-interface-design-architecture.md` (Amendment 2026-10-07); plan `docs/superpowers/plans/2026-10-07-stage3-5-ui-ux-professionalisation.md`.

This register is the only authoritative exit gate for Stage 3.5 (`docs/architecture/README.md`, "Documentation precedence" item 4). The plan references these row IDs rather than keeping a second list. **Conformance during the programme is specification §34.2:** a slice's PR asserts every v2.0 requirement whose enabling slice has merged and its own rows here, introduces or extends no deviation, and may leave open only findings recorded here against a later slice. The §26 assertion manifest records each harness rule as `blocking`, `measured/pending` or `not-applicable`; a rule blocks CI only once its implementing slice has merged (S1/S2 rules at S2; rendered stickiness at S3e; every assertion evaluated at a Tier B or C anchor, generic or tier-specific, at S5; the remaining §23/§38 rules at S6); at S7 every rule is `blocking` or `not-applicable` and §34 applies unqualified. **Nothing unexecuted is marked PASS.** A row becomes PASS only when its evidence is entered here: PR and merge commit, harness run and anchors, measured values, or the capture set read. "Looks better" is not evidence and is not an exit criterion anywhere in this register.

"Stage 3.5" is a working label for an owner-directed cross-cutting product-quality programme; capability stages 1–11 are not renumbered. Capability Stage 4 (ANPR/OCR) begins only after row C5 is PASS.

## Current verdict

**ARCHITECTURE FROZEN; S1a AND S1b LANDED.** A1–A6 PASS (PR #181). D1 PASS (S1a, PR #182). D6 PASS (S1b, PR #183). D2 and D3 OPEN with their landed portions recorded. Every other row is OPEN.

## Section A — Architecture and audit acceptance (this PR)

| Row | Requirement | Status | Evidence |
|---|---|---|---|
| A1 | Baseline verified: `main` exactly `98e5cd3f…`, PR #180 merged, Stage 3 register COMPLETE, X1/X2/X3 PASS, Stage 3.5 recorded as next in both roadmaps. | **PASS** | Verified 2026-10-07 on branch `stage3.5/ui-ux-architecture`; plan §2. |
| A2 | The real application inspected with the existing visual-QA harness, production build, all 125 fixture states at the four v1.0 anchors; captures read by eye for every route; exactly what was and was not inspected is recorded. | **PASS** | Plan §4: 500 captures, zero automated findings; captures listed per surface; widths below 1366 explicitly not inspected. Captures are working artefacts, not committed. |
| A3 | Audit recorded per route and per journey with P0–P3 severity and systemic/archetype/component/surface layer; systemic findings assigned to the design-system/component/archetype layer, never to page patches. | **PASS** | Plan §5 (F1–F25), §5.2, §5.3. |
| A4 | v1.0 frozen decisions challenged against evidence; each either changed by dated amendment or reaffirmed with the reason; history preserved (no v1.0 text deleted; historical markers). | **PASS** | Plan §6; specification v2.0 header, §25, §33, §34.1, §35; ADR-012 Amendment 2026-10-07 Decisions 7–12 and "reaffirmed". |
| A5 | Specification v2.0 and ADR-012 amendment consistent with each other, with both roadmaps and with the README; §34.1 closed; support tiers, craftsmanship, edge-state, performance and acceptance requirements present; no dependency, font, light mode, mobile feature, Stage-4 content, React component, production CSS or API change in the PR. | **PASS** | PR diff is documentation only (`git diff --stat`: 8 documentation files; no source, CSS, config, workflow or test file); `python tools/verify_repo.py` PASSED (run output in the PR); `git diff --check` reports only the ADR-012 header's pre-existing two-space Markdown hard breaks, which the edited status line keeps. Independent cold review against the plan §19 checklist performed before the PR opened (five material and fourteen minor points, all applied; recorded in the PR description). |
| A6 | Reference surfaces, slice sequence, responsive matrix, visual-QA strategy, accessibility strategy, performance requirements and rollback stated; no performance number invented. | **PASS** | Plan §9–§18; specification §38 states budgets are set only from measurement. |

## Section D — Design-system implementation (slice S1)

| Row | Requirement | Status | Evidence |
|---|---|---|---|
| D1 | Tokens added per plan §8; no component references a primitive; no colour/radius/duration/spacing literal in feature CSS; `styles/tokens.test.ts` allowlist emptied. | **PASS** | S1a, PR #182, head `977d24376fef612a3f353cf13ec6af941eaf5f71`. Tokens 160 → 168 declared (40 primitives, 120 semantic, 8 component): added `--control-disabled-bg`, `--control-disabled-border`, `--text-disabled`, `--measure` (68ch), `--alert-max` (880px), `--table-row-h` (40px), `--scrollbar-thumb`, `--scrollbar-track`, `--skeleton-bg`; removed `--disabled-opacity`; no synonym roles (asserted). `styles/tokens.test.ts` asserts every `var()` resolves, no `--p-*` in any consumer sheet, no colour/radius/spacing/duration literal in feature CSS (two `1px solid` borders moved to `--stroke-hair`; border width is not in this row's literal list and 12 remain in `features.css`), the hover allowlist is gone (all eight inherited hover text repaints corrected in `components.css`, `layout.css`, `workspace.css`, `features.css`; the ban is blanket), and the control-state contract (`tokens.test.ts` 27 tests, 13 of them the control-state block, including the cross-sheet checks that no consumer rule grows an `.empty` presentation and that exactly one disabled-button rule exists, painting only the disabled tokens); `styles/contrast.test.ts` 58 tests incl. error-hue and disabled floors. Full frontend suite 64 files / 966 tests, typecheck and production build green. Visual pass: Tier-A harness, 38 states × 1366×768/1440×900/1920×1080/2560×1080 = 152 captures on the final CSS, zero automated findings; captures read by eye for Overview, Cameras (incl. create, invalid, loading, empty, unavailable), Videos (dense, empty, filtered-empty), Processing queue, Import (incl. invalid, no cameras), Processing detail (completed, failed, unavailable), Scene Editor (enabled/disabled Save, unconfigured, dirty, dense), Search (field errors, empty, not-analysed hatched empty, scene-unavailable, loading, unavailable, inspecting), Review (incl. bright, geometry-unavailable), Analytics (activity, heatmap, unavailable, no-scene) — no material regression; evidence/spatial hues unchanged. Measured S1 defaults: `--measure` 68ch, skeleton default 8 rows; the §36.1 "24 between sections" step is **not** used by any current layout (regions are separated at 12/16, page padded at 20) and stays an unconfirmed default for the S3 reference surfaces. |
| D2 | Primitives added: Dialog, Drawer, Tooltip, EvidencePlaceholder, FileInput, ToggleChip, StateRegion — each with its §27 contract, tests, and keyboard/focus behaviour. | OPEN (partial) | **Landed in S1b** (PR #183, head `1eeb90548cd897499054aa81041ec9db16b73687`): `StateRegion` (`shared/async/StateRegion.tsx`; kinds page/column/panel/row/media; loading, unavailable, empty, degraded per §37.1; one alert per cause with Retry trailing; `SupportingRequestNotice` for requests with no region of their own; no TanStack Query import) with `StateRegion.test.tsx`; `EvidencePlaceholder` (`shared/evidence/EvidencePlaceholder.tsx`; frame-filling matte, one icon, `No image`, reason in the accessible name, never an `<img>`, spinner or alert) with `EvidencePlaceholder.test.tsx`. Neither moves focus; both are keyboard-inert presentations, the Retry they carry is a native button. **Remaining:** Dialog, Drawer, Tooltip, FileInput, ToggleChip. |
| D3 | Button disabled by tokens; Field invalid one hue with scroll-to-first-invalid; Alert max width and trailing action; LoadingState/EmptyState geometry per §36.3/§37.1; ContextBar identity truncation; rail collapse control 32px labelled. | OPEN (partial) | **Landed in S1a** (PR #182, head `977d24376fef612a3f353cf13ec6af941eaf5f71`): Button and inputs disabled by the three disabled tokens with no whole-control opacity and no variant exception (the ghost override was removed on cold review; a disabled ghost takes the same surface, border and text), including the pressed-and-disabled case, hover excluded for `:disabled`/`aria-disabled` (`Button.test.tsx`, `tokens.test.ts`); re-inspected `review-geometry-unavailable`, `review`, `scene-editor`, `scene-editor-unconfigured`, `scene-editor-dirty`, `search-inspecting`, `search-inspecting-evidence-unavailable` at 1366 and 2560; Field/input invalid state in one error hue (2px `--status-err` boundary + `--status-err` message, focus ring preserved; `Field.test.tsx`); Alert capped at `--alert-max`, trailing action slot unchanged; LoadingState skeleton rows static at `--table-row-h` pitch, default 8; EmptyState content-sized (`align-content: start`, `flex: 0 0 auto`, 24/16 padding, sentence at `--measure`; the Search `.results` column no longer grows it — Codex P2 on PR #182, re-captured `search-empty` and `search-analytics-not-analysed` at 1366: the hatched block is its own height at the top of the column). **Remaining:** ContextBar identity truncation and document title; rail collapse control (§5); scroll-to-first-invalid orchestration (form-level, not owned by the Field primitive — S1 shell/forms slice); ~~Alert trailing-action adoption on every call site (S1b with the boundary)~~ landed in S1b (PR #183, head `1eeb90548cd897499054aa81041ec9db16b73687`): every region and supporting-request Retry is the trailing action of its alert or a row action, and `Try again` buttons in alert bodies are gone (guarded by `stateGrammar.guard.test.ts`); the skeleton pitch is not yet shared by the table (`--table-row-h` binds the Ledger row in D4, and the sticky header row is not yet part of the skeleton); `.evidence-timeline__navigator-controls button:disabled` keeps a bespoke `--text-muted` treatment to fold into the disabled tokens. |
| D4 | Ledger containment bounds the table; state presentations uncontained at the table's top; row pitch 36–40 measured. | OPEN | |
| D5 | One accent-filled primary per surface; row actions secondary on every Ledger. | OPEN | |
| D6 | Async-state boundary on every data region of every surface; §37.1 presentation and placement; one vocabulary per state. | **PASS** | S1b, PR #183, head `1eeb90548cd897499054aa81041ec9db16b73687`. **Inventory:** every query on the ten surfaces is listed in the PR with its region kind, loading, first-load failure, success-empty, refresh-failure and retry path (≈45 regions and supporting requests). **Selection:** every one goes through `fromQuery`/`fromInfiniteQuery`/`combineStates` — regions into `StateRegion`, requests with no region of their own (camera names, display timezone, search rail video list) into `SupportingRequestNotice`, per-row processing status through `useVideoProcessing().stateOf`, and the two scene-geometry hooks and the trajectory layer through `fromQuery`; `AsyncBoundary` is retired. Remaining direct `isPending`/`isError` reads are mutations, Search continuation (`fetchNextPage`, deliberately not the region state), 404 → not-found/invalid-link routing, and the Overview figures' one multi-cause notice (one alert naming every failed inventory, selected through `fromQuery`). **Presentation:** §37.1 placement — inside the region it replaces, at its top, own height, uncontained; one alert per cause (Scene Editor's video list, Overview media panel `causeAnnouncedElsewhere`); Retry trailing; degraded keeps data beneath one warning; column skeletons where the row geometry is known (Ledgers at `--table-row-h`, Search at `--c-result-row-h`, Overview recent at `--c-recent-row-h`, Processing-detail video facts as key/value rows), inline loading where it is not (§37.1 asks for a skeleton only where the shape is known); media missing → `EvidencePlaceholder` `No image` everywhere, including on `<img>` load error. **Domain states kept with the caller** (not configured, not analysed, too much to map, finalizing, stale analytics). **Evidence:** `asyncState.test.ts`, `StateRegion.test.tsx`, `EvidencePlaceholder.test.tsx`, `stateGrammar.guard.test.ts`, surface regressions in Processing detail (alert inside its panel, Retry re-requests), Scene Editor (one alert, Context Bar kept), Videos (refresh failure keeps rows, no loading flash), Overview (one alert for one cause); full suite 68 files / 1000 tests, typecheck and production build green; Tier-A harness 52 states × Tier A = 204 captures plus 24 on the S1b implementation head and 20 (processing detail, search analytics) after the Codex fixes, zero automated findings, read by eye (PR #183 lists every state). **Not claimed:** the viewport-high Ledger frame around these states (D4) and Tier B/C (T1/T2). |
| D7 | IA map implemented: rail/crumb/title derived from one source; skip link; landmarks; `g` keys and `?` sheet. | OPEN | |
| D8 | No `window.confirm` in production code; both drawers on the Drawer primitive with focus contract. | OPEN | |
| D9 | PageHeader, Tabs, dead CSS, `.table--compact` reference removed; `IconName` closed union; AnalyticsPage on the `.page` wrapper; full test suite, typecheck, build, `verify_repo` green. | OPEN | |

## Section V/P — Harness v2 and baseline measurement (slice S2)

| Row | Requirement | Status | Evidence |
|---|---|---|---|
| V1 | Assertions added per specification §26 with the assertion manifest: rules implemented by S1 (row pitch, primary count, containment depth, state placement, skip link/landmarks, drawer/dialog focus, text overflow, `aria-pressed` style) are `blocking`; rendered stickiness (R6), Tier B/C rules (T1–T3) and the §23/§38 hardening rules (X1–X4) are `measured/pending` with their owning row named; no rule absent. | OPEN | |
| V2 | Default sweep at every tier anchor: 1366×768, 1440×900, 1920×1080, 2560×1080, 2560×1440, 1024×768, 768×1024, 430×932, 390×844; states declare applicable tiers. Tier A assertions block; every assertion evaluated at a Tier B or C anchor, generic or tier-specific, is `measured/pending` (reported, never failing) until T1/T2 flip it. | OPEN | |
| V3 | Deterministic waits (no mid-load captures: `processing-queue-dense` at 1920 reproduces settled). | OPEN | |
| V4 | CI job runs the harness on every frontend PR against the production build; the job fails only on `blocking` manifest entries and prints `measured/pending` results as diagnostics; captures uploaded as an expiring artefact; no npm dependency added; no screenshot committed. | OPEN | |
| V5 | Pixel-diff baselines **not** adopted; typography determinism recorded per state (resolved font family). | OPEN | |
| P1 | Baseline measured and recorded here: cumulative layout shift during loading→content per state and anchor; long tasks on first interaction; resolved font. **Budgets are entered in this row only after measurement and never before.** | OPEN | |

## Section R — Reference surfaces (slices S3a–S3e)

Each row requires: §34 items 1–15 and 17 asserted on the surface per §34.2 (item 16 is T1–T3; item 6's T3 and X1–X4 obligations and item 15's keyboard-only journeys are carried to those rows); every §37.1 state the surface reaches inspected at every Tier A anchor; the harness green; the capture set listed; and the surface's plan-§5 findings closed or explicitly carried to a named row.

| Row | Surface (archetype) | Status | Evidence |
|---|---|---|---|
| R1 | Overview (Ledger-summary) — attention-first per §4.1.1; F11 closed. | OPEN | |
| R2 | Videos (Ledger) — F1, F2, F14 closed; dense/long-name/empty/filtered-empty/unavailable states inspected. | OPEN | |
| R3 | Processing detail (Record) — F3 (unavailable with retry), F16, F19 closed; completed/running/failed/finalizing/failed-finalization/stale/unavailable inspected. | OPEN | |
| R4 | Scene Editor (Workbench) — F5 (Dialog), F7, F18, F3 (alert consolidation), one drawing entry; unconfigured/dirty/long-identity/dense/unavailable inspected. | OPEN | |
| R5 | Search (Investigation) — F3, F12, F13, F18, F19 closed; every `search-*` fixture inspected including drawer and in-place inspector, continuation and failure states. | OPEN | |
| R6 | Video Review (Review) — F8 (rendered sticky player at 1366 asserted; its manifest entry flipped to `blocking`), F18, F19, F4 closed; bright/dark/saturated/low-contrast/letterbox/pillarbox footage inspected. | OPEN | |

## Section M — Migration of remaining surfaces (slice S4)

M rows are held to the Section R standard (§34.2 S4 row).

| Row | Surface | Status | Evidence |
|---|---|---|---|
| M1 | Cameras (Ledger) onto R2. | OPEN | |
| M2 | Processing queue (Ledger) onto R2. | OPEN | |
| M3 | Import (Record) onto R3; F17; containment depth. | OPEN | |
| M4 | Camera Analytics (Workbench) onto R4; F21–F25. | OPEN | |

## Section T — Support tiers B and C (slice S5)

| Row | Requirement | Status | Evidence |
|---|---|---|---|
| T1 | Tier B compositions per §25 table on every surface — Workbench keeps the §4.3.1 progression (side by side ≥~1150, drawer from 1101 up to the measured threshold, stacked 768–1100; T1 records the measured threshold) and Investigation keeps its rail in place down to 1101; inspected at 1024×768 and 768×1024 plus a 1200×800 spot check of the 1101–1365 band; no overflow; every action reachable; Tier B manifest entries flipped to `blocking`. | OPEN | |
| T2 | Tier C degradation per §25 table on every surface; Workbench unsupported state (no editing canvas; Context Bar + read-only object summary + "editing requires at least 768px"); inspected at 430×932 and 390×844; no overflow, no clipped control; no workflow acceptance claimed; mobile remains deferred; Tier C manifest entries flipped to `blocking`. | OPEN | |
| T3 | 200% zoom at 1366×768 reflows under Tier C rules; its manifest entry flipped to `blocking`. | OPEN | |

## Section X — Accessibility and performance hardening (slice S6)

| Row | Requirement | Status | Evidence |
|---|---|---|---|
| X1 | Every §23 obligation asserted on every surface by the harness or by `styles/contrast.test.ts`, their manifest entries flipped to `blocking`; WCAG 1.4.10 at 320px recorded as not targeted and the Workbench canvas at 200% zoom on 1366 recorded as a 1.4.4 exception. | OPEN | |
| X2 | The six operator journeys (plan §5.3) completed keyboard-only, recorded step by step. | OPEN | |
| X3 | §38 budgets set from the P1 baseline, recorded here with tolerance, and met on every reference surface; no regression beyond tolerance. | OPEN | |
| X4 | Reduced motion verified: no transition or animation duration above 0 under `prefers-reduced-motion: reduce`. | OPEN | |

## Section C — Final closure (slice S7)

| Row | Requirement | Status | Evidence |
|---|---|---|---|
| C1 | No P0 or P1 finding open; no systemic P2 finding open (plan §5.1 F1–F13 and F21–F22 closed). | OPEN | |
| C2 | No surface relying on the closed §34.1 clause and no §34.2 exception remaining; every §34 item 1–17 asserted on every surface, with any C5-carried finding declared under item 13; every manifest entry `blocking` or `not-applicable`. | OPEN | |
| C3 | Full 125-state (or current) sweep green at every tier anchor; captures read; the pass enumerated in the closing PR. | OPEN | |
| C4 | Tests, typecheck, build and `verify_repo` green on the closing merge commit; independent cold review recorded. | OPEN | |
| C5 | Remaining P2 single-surface and P3 findings listed below with an owner slice or an explicit owner-accepted deferral; roadmaps and README carry closure wording; **Stage 4 unblocked.** | OPEN | |

### Findings carried at closure (P2 single-surface / P3)

*(Empty until C5. Each entry: finding ID, surface, owner slice or deferral with the owner's acceptance.)*

## Non-claims

- No width below 1366 has been inspected at this baseline; Tier B and C behaviour is frozen design, not observed behaviour.
- No performance figure is claimed; §38 budgets do not exist until P1 is PASS.
- Nothing here is Production qualification; Task 18 is unchanged.
- No dependency, font or framework is added by any slice; a slice that cannot meet a rule without one amends the rule by ADR instead.
