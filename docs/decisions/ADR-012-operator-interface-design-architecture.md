# ADR-012 — Operator Interface Design Architecture

**Status:** Accepted  
**Date:** 2026-09-20  
**Context:** Operator plane (React/TypeScript), following the independent UI/UX audit of `main@b99ce26f`  
**Specification:** `docs/architecture/ui-ux-design-specification.md`

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

- The specification is normative for frontend work from UI-1 onward. Existing screens are not retroactively non-conformant; each becomes conformant as its UI-n PR lands, per the transitional clause in specification §34.1.
- Frontend PRs gain a conformance checklist and a visual QA obligation.
- Scene Analytics Slice 3 is gated as stated in Decision 5, and the roadmap documents record that gate.
- This ADR freezes design architecture only. It changes no domain model, contract, persistence or qualification decision, and no accepted ADR is superseded.

## Not decided here

Light palette (deferred, not refused), exact evidence hues, the timeline lane presentation for multiple analytical interval types, and the font choice — all recorded as open decisions in specification §32 and resolved by visual validation in the PR that needs them.
