# ADR-012 — Operator Interface Design Architecture

**Status:** Accepted; amended 2026-10-07 (Stage 3.5 — see *Amendment 2026-10-07* below)  
**Date:** 2026-09-20  
**Context:** Operator plane (React/TypeScript), following the independent UI/UX audit of `main@b99ce26f`  
**Specification:** `docs/architecture/ui-ux-design-specification.md` (v1.0 accepted here; v2.0 accepted by the 2026-10-07 amendment)

> ADR-010 is reserved by `docs/superpowers/plans/2026-09-20-audited-review-and-cases-plan.md` for operator identity, authorization and audit. ADR-011 freezes the scene-analytics lifecycle. This ADR takes the next number.

## Context

The operator application grew one feature at a time. Each surface was reasonable alone, and the result is not: eight pages carry at least two different layout grammars, `--content-max` is applied to workspaces that need width and to summaries that do not, colour carries both "selected" and "is a zone" with no separation, and the same operational condition is rendered differently on different pages. An independent audit also found three defects that are not stylistic — text on `--accent` fails AA at 3.45:1, the focus ring on `--accent-strong` fails the 3:1 non-text minimum at 2.35:1, and `features.css` references `var(--focus)`, which is defined nowhere, so keyboard focus on search result rows is invisible.

The capability roadmap makes this urgent rather than cosmetic. Scene Analytics slices 4–6, visual attributes, ANPR, similarity and event analytics each add operator surfaces. Built on the present foundation, each would add another grammar, and the cost of unifying them would rise with every stage.

This ADR records the decision to adopt a single frozen interface architecture before those surfaces are built. The detailed normative content — archetypes, tokens, state taxonomy, accessibility obligations, visual QA standard and the UI-1 → UI-5 programme — lives in the specification, which this ADR adopts by reference rather than duplicating.

## Decision 1 — One frozen set of workspace archetypes

Every operator surface belongs to exactly one of five archetypes — Ledger, Record, Workbench, Investigation, Review — and each archetype has exactly one layout implementation and one owner of scroll.

Rejected alternatives and why:

- **Per-page layout, as today.** It is what produced the divergence. It has no mechanism that makes the ninth page agree with the first eight.
- **A generic page-composition system.** More expressive than the product needs, and expressiveness is the failure mode here: a system that can express any layout will be used to express several. The archetype set is deliberately closed.

Consequences accepted: a genuinely novel surface must either fit an archetype or amend this decision, which is friction by design.

## Decision 2 — Colour carries exactly one meaning per role

Accent means selection, including canvas stroke and handles, and never resting geometry fill. Evidence and spatial hues occupy a separate token namespace from UI semantics. Operational state has one taxonomy applied identically on every surface.

The alternative — letting each feature choose hues that read well locally — is how the accent/geometry collision arose. An operator who has learned that accent means "selected" must not meet a screen where it means "this is a zone".

## Decision 3 — Design tokens are semantic, not flat

Semantic tokens with narrowly scoped component tokens replace the flat palette, so that a surface names its intent rather than a value. Feature CSS carries no colour, radius, duration or spacing literal.

Consequence accepted: roughly 110 tokens rather than 68, and one broad CSS diff at UI-1.

## Decision 4 — Accessibility and visual QA are acceptance criteria, not review opinions

Contrast, target size and keyboard reachability are stated as obligations with a defined verification surface, and the visual QA standard applies to every UI PR. Footage the product does not control is part of the test matrix, because a stroke that is legible over a test clip may be absent over a bright one.

## Decision 5 — The foundation is built before the surfaces that depend on it

The UI Foundation programme runs strictly sequentially as UI-1 → UI-2 → UI-3 → UI-4 → UI-5, and **Scene Analytics Slice 3 does not begin until UI-2 has merged with green post-merge `main`.** UI-1 alone does not lift the gate: UI-1 corrects the foundation, UI-2 establishes the grammar that later analytics surfaces must land on.

Rejected alternatives and why:

- **Continue Scene Analytics and fix the UI afterwards.** Slices 4–6 would each add a surface to the grammar being replaced, and the migration would then have to be re-done across them.
- **Run the UI programme in parallel with Slice 3 from the start.** Both touch the same frontend surfaces; the merge cost and the regression risk exceed the pause.

Consequence accepted: an explicit, deliberate pause in analytics delivery after Slice 2. After UI-2, backend and domain work may proceed in parallel with UI-3/UI-4/UI-5 where it introduces no frontend surface.

## Decision 6 — The design introduces no new dependency

The component system is built from the existing four frontend runtime dependencies. No UI framework, component library, geometry library, canvas library, charting library or state-management package is introduced, and no second visual language. Any font is bundled, with its licence and offline-catalogue entries landing in the same change.

This keeps ADR-003 intact: no CDN asset, no remote font, no telemetry, and no Internet dependency in production runtime behaviour.

## Consequences

- The specification is normative for frontend work from UI-1 onward. Existing screens are not retroactively non-conformant; each becomes conformant as its UI-n PR lands, per the transitional clause in specification §34.1 (closed by the 2026-10-07 amendment).
- Frontend PRs gain a conformance checklist and a visual QA obligation.
- Scene Analytics Slice 3 is gated as stated in Decision 5, and the roadmap documents record that gate.
- This ADR freezes design architecture only. It changes no domain model, contract, persistence or qualification decision, and no accepted ADR is superseded.

## Not decided here

Light palette (deferred, not refused), exact evidence hues, the timeline lane presentation for multiple analytical interval types, and the font choice — all recorded as open decisions in specification §32 and resolved by visual validation in the PR that needs them.

## Amendment 2026-10-07 (Stage 3.5 — UI/UX Professionalisation)

**Context.** The UI-1 → UI-5 programme this ADR gated is complete, Scene Analytics Slices 0–7 landed on its grammar, and Stage 3 closed on `main@98e5cd3f3ae8ca636ffbe2115c6b74b4ebcb2b16`. Before capability Stage 4 (ANPR/OCR), the owner directed a cross-cutting product-quality programme (working label *Stage 3.5*; it renumbers nothing). Its first act was an architecture audit of the real application at that baseline — code, every route, every §14 state, and a scripted visual pass of 125 fixture states at the four v1.0 anchors — recorded in `docs/superpowers/plans/2026-10-07-stage3-5-ui-ux-professionalisation.md`. The audit found that Decisions 1–6 hold: no surface has left its archetype, no colour role is crossed, no feature dialect exists, no dependency was added. It also found that the architecture, as frozen, was **insufficient** in five respects, each of which showed up on several surfaces at once and none of which a page-level fix could close. This amendment records the decisions that close them. The specification moves to **version 2.0**; v1.0 text is kept and marked historical, not rewritten.

### Decision 7 — Craftsmanship is an acceptance criterion, defined at the component layer

A surface is not complete because its functional tests pass. Specification §36 states the standard (alignment, rhythm, metrics, capitalisation, truncation, numerals, cursors, focus, state treatments, scrollbars, sticky regions, transitions, skeleton geometry, nothing-states) and §34 makes it conformance item 14. Every standard is an obligation on a token, component or archetype, so that a defect found on one surface is corrected on all of them by one change.

Rejected: **a polish pass per page.** It is what the v1.0 programme's "refine" rows amounted to in practice — the audit found the same empty-frame, same repeated-primary and same invalid-state defects on every Ledger and every form — and it leaves the ninth page free to differ from the first eight again. Also rejected: **stating the bar as a visual reference** ("make it look like X"). The bar is a standard of finish; MAVI does not clone another product's appearance.

Consequence accepted: slower first slices, because the primitives are fixed before any surface is, and a conformance checklist that is longer and partly measured by the harness rather than by review.

### Decision 8 — Three support tiers replace the desktop-snapshot viewport table

Specification §25 freezes **Tier A Workstation (≥1366)**, the only tier in which a workflow is accepted; **Tier B Compact (768–1365)**, every workflow possible with designed single-column and drawer compositions, not optimised for long use; **Tier C Narrow (390–767)**, intentional degradation for reading and status, with editing surfaces stating that they need a wider display. Rules are ranges between anchors, and breakpoints are derived from measured region minimums, as the 1600px Investigation threshold already was.

Rejected: **keeping "functional, not optimised" below 1100 and "must not break" below 768.** The audit found that the product did not break there because nothing was designed there: the rail force-collapses with its toggle hidden and the stacking is flex wrapping. Rejected: **making narrow widths an operational workstation.** Tier C degrades on purpose; the mobile analyst experience stays deferred (§31) and no workflow is accepted below Tier A. Rejected: **desktop compression as responsiveness** — a Tier A layout shrunk until it fits is not Tier B behaviour.

Consequence accepted: two more tiers to design, assert and sweep, and a Workbench that refuses to render its canvas below 768px rather than rendering it unusably.

### Decision 9 — One state grammar, served everywhere, placed by rule

The §14.1 boundary becomes mandatory on every data region (the audit found it on three of ten surfaces), and §37 fixes the presentation of each state per region kind and its placement: inside the region it replaces, at the top, uncontained, retry trailing, one alert per cause, one vocabulary per state. Ledger containment is applied to the table, not to the slot (§4.1), so sparse, loading, empty and unavailable Ledgers no longer render as a viewport-high empty frame.

Rejected: **leaving state selection to each surface with the boundary as an option.** Optional architecture is per-page architecture; four retry placements and two words for one missing-thumbnail condition were the result.

### Decision 10 — Visual regression is gated by deterministic layout assertions in CI, not by pixels

The scripted harness is confirmed as the method and extended: it runs in CI on every frontend PR, assertions only, at every tier anchor, with captures kept as expiring CI artefacts; it gains assertions for row pitch, one primary per surface, containment depth, state placement, skip link and landmarks, drawer and dialog focus placement, rendered stickiness, text overflow and the tier rules; and it records layout-shift and long-task measurements so that §38 budgets can be set from a measured baseline.

Rejected: **pixel-diff screenshot baselines.** The UI font is the platform stack (§32 decision 1), so Windows and Linux captures differ by design; making them match would mean bundling a font *for the screenshots*, which Decision 6 and decision 1 reject, and masking or thresholds would make the gate either blind or flaky. Rejected: **adding an accessibility engine or a screenshot library.** Decision 6 stands; the obligations are asserted directly.

Consequence accepted: no automatic detection of a purely painterly regression (a wrong colour at the right size and place); the bounded human pass in §26 remains for that.

### Decision 11 — WCAG 2.2 AA is the accessibility target, with structural obligations asserted by the harness

§23 names the target and adds the shell and overlay obligations the audit found missing: a skip link and landmarks, drawer and dialog focus management, keyboard completeness for every overlay, 200% zoom at 1366 reflowing under Tier C rules, and the harness assertions that check them. Two gaps are recorded rather than claimed: WCAG 1.4.10 reflow at 320px is not targeted, and the Workbench canvas, which is not rendered below 768px, is a documented 1.4.4 exception at 200% zoom on a 1366-wide display.

### Decision 12 — Programme shape: foundation, then one reference surface per archetype, then migration by archetype

The programme (§39; plan and register linked there) runs: freeze → foundation primitives, tokens and state grammar → harness v2 → six reference surfaces (Overview, Videos, Processing detail, Scene Editor, Search, Review) → remaining surfaces by archetype → Tiers B and C → accessibility and performance hardening → closure. Each slice is independently reviewable and revertible.

Rejected: **one rewrite PR** (unreviewable, unrevertible, and the UI-1 → UI-5 experience already showed that a slice per layer is the reviewable unit). Rejected: **a stream of per-page cosmetic PRs** (Decision 7).

### Decisions reaffirmed unchanged

Decisions 1–4 and 6 stand as written. Decision 5's programme is complete and its gate lifted; the clause is historical. Specification §34.1 (transitional conformance) is **closed**: no surface may rely on it, and a legacy pattern is a register finding. §4.4 open decision 4 (results cap with nothing selected) is reaffirmed after measurement at 2560: a column that moves on selection is worse than a column with space beside it. The Record centring exception and the Overview centring exception stand; Overview additionally becomes attention-first (§4.1.1).

### Not decided here

Budgets for §38 (set from the first measured baseline in the register, never invented); the exact Tier B and C compositions beyond the §25 table (settled in the reference-surface slices by inspection); open decisions 2b and 6 (unchanged); any light palette, density preference, resizable pane, command palette or mobile experience (still deferred, §31). Nothing in this amendment changes a domain model, contract, persistence, qualification or capability-stage decision, and capability Stage 4 is gated on the register's closure of this programme.
