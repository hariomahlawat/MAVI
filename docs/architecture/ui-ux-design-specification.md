# MAVI UI/UX Design Specification

**Version:** 2.0 (Stage 3.5 architecture freeze, 2026-10-07)
**Status:** Adopted. Normative for all frontend work. Full conformance (§34) is the baseline from Stage 3.5 closure; during the Stage 3.5 programme the staged-conformance rule §34.2 states exactly what each slice must meet. The UI-1 → UI-5 transitional clause (§34.1) is closed.
**Design baseline (v1.0):** `main@b99ce26f041b3fff25094b8a5ac6a84f7305fc87`
**Audit baseline (v2.0):** `main@98e5cd3f3ae8ca636ffbe2115c6b74b4ebcb2b16` (Stage 3 closed; UI-1 → UI-5 and Scene Analytics Slices 0–7 merged)
**Scope of authority:** the MAVI operator UI (`src/web/mavi-web`).
**Decision record:** `docs/decisions/ADR-012-operator-interface-design-architecture.md` accepts the architecture this document specifies; its **Amendment 2026-10-07 (Stage 3.5)** accepts the v2.0 changes. The ADR records the decisions and the trade-offs; this document is the normative detail.
**Programme record:** the Stage 3.5 audit, decisions and slice sequence are in `docs/superpowers/plans/2026-10-07-stage3-5-ui-ux-professionalisation.md`; the exit gate is `docs/reviews/2026-10-07-stage3-5-ui-ux-professionalisation-acceptance.md`.

**What changed in 2.0.** Version 1.0 froze the architecture (archetypes, tokens, colour roles, state taxonomy, accessibility, visual QA) and the UI-1 → UI-5 programme that built it. Every surface now sits on that architecture, and the Stage 3.5 audit of the real application found that the architecture holds but the *product quality* on top of it does not yet: containment that reads as empty frames, a primary-action accent repeated on every row, four different placements of the same "unavailable" state, drawers that move no focus, native confirms still in use, responsive behaviour defined only at desktop snapshots, and a visual-QA method with no automated layout assertions beyond overflow and overlap. Version 2.0 therefore adds a quality direction (§2), the **product craftsmanship standard** (§36), the **edge-state and progressive-disclosure catalogue** (§37), **performance as UX** (§38), explicit **support tiers** replacing the v1.0 viewport table (§25), a revised **visual-regression strategy** (§26), a WCAG 2.2 AA target with harness-asserted obligations (§23), amended archetype, colour, state, shell, interaction, table, search, inspector and component rules where the audit found them insufficient (each marked *Amended in v2.0*), a conformance definition (§34) under which a surface is not complete merely because its functional tests pass, a staged-conformance rule for the programme that implements v2.0 (§34.2), and the programme pointer (§39). The UI-1 → UI-5 roadmap (§33) and its transitional clause (§34.1) are marked **Historical**, the mobile deferral (§31) is clarified, and v1.0 text that is no longer normative is kept rather than rewritten out of the record.

Status markers used throughout:

| Marker | Meaning |
|---|---|
| **Frozen** | Settled. Implement as written. Changing it requires an explicit amendment to this document. |
| **Deferred** | Deliberately not built now. The architecture must not preclude it; no effort is spent on it. |
| **Open** | Genuinely undecided. Closed in the named PR (§32). |
| **Historical** | A v1.0 rule or programme record that has completed or been superseded. Kept for the record; not normative. |
| **Amended in v2.0** | Changed by the Stage 3.5 freeze. The v1.0 text is kept beside it where the difference matters. |

---

## 1. Purpose and scope

This document governs the visual design, layout architecture, interaction grammar and accessibility of the MAVI operator UI. It exists so that independent implementation sessions produce one coherent product rather than a set of individually reasonable pages.

**Governs:** workspace layout, design tokens, colour semantics, typography, density, interaction states, motion, operational-state vocabulary, tables, search, evidence presentation, spatial overlays, inspectors, forms, keyboard, accessibility, formatting, responsive behaviour, visual QA, and the shared component boundary.

**Does not govern:** backend contracts, API shape, analytics semantics, worker behaviour, or the capability roadmap sequence. Where a UI rule and an ADR conflict, the ADR wins and this document is amended.

**Conformance:** §34 defines what a frontend PR must satisfy. §34.1, which governed the UI-1 → UI-5 migration period, is closed; no surface may rely on it. §34.2 governs the Stage 3.5 programme slices S1–S6 and expires at S7 closure.

**Precedence:** `AGENTS.md` and accepted ADRs > this specification > individual PR judgement.

**Two numbering schemes appear in this document and MUST NOT be conflated:**

- **Scene Analytics slices 0–7** — the eight slices of the Spatial & Temporal Track Analytics plan (`docs/superpowers/plans/2026-09-20-spatial-temporal-track-analytics.md`), which is capability stage 1. Slice 0 architecture/contracts, 1 geometry engine + scene configuration backend, 2 Scene Editor UI, 3 analytics lifecycle + derived-fact persistence, 4 Search integration + analytics readiness, 5 evidence overlays + explanation, 6 aggregates + heatmap, 7 hardening/performance/acceptance/qualification/docs closure.
- **Capability roadmap stages 1–11** — the product capability sequence in `docs/superpowers/plans/capability-roadmap.md` (stage 1 Spatial & Temporal Analytics, 2 Visual Attributes, 3 expanded classes, 4 ANPR/OCR, 5 Visual Similarity, 6 ReID, 7 Event/Behaviour Analytics, 8 richer structured search, 9 NL query, 10 audited review/cases, 11 live RTSP).

Where this document says "Slice *n*" it always means a Scene Analytics slice. This specification does not renumber either scheme.

---

## 2. Product design position

MAVI is a **professional, dark-first, offline Visual Intelligence workstation** used by trained operators for multi-hour sessions.

It must feel: **precise, quiet, dense, spatial, trustworthy.**

It must not feel: decorative, consumer, "AI-flavoured", tactical/military-cosplay, or like an admin dashboard.

Concretely, after four hours of continuous use:

- The operator's eyes have not repeatedly re-adapted between bright chrome and dark footage.
- The operator can tell at a glance whether a result set is *empty*, *unavailable*, or *not yet analysed*.
- The frame is the largest element on any surface that contains one.
- Every action performed hourly has a keyboard route.
- Nothing on screen exists to look impressive.

Credibility comes from clarity, information architecture and honest representation of evidence — never from styling.

**Quality direction (Amended in v2.0, frozen).** The bar is stated as a standard of *craftsmanship*, not as a visual reference: the finish and restraint associated with the best desktop tools (every pixel placed, nothing accidental, nothing decorative), the precision of a keyboard-first professional tool (density, speed, exact states), and MAVI's own evidence-first operational density. It is a quality target, not a visual target: MAVI MUST NOT clone another product's appearance, components or styling. Concretely it MUST remain serious, quiet, information-rich, offline and evidence-centric, and MUST NOT become a generic SaaS dashboard, a framework reskin, glassmorphism, tactical cosplay, oversized consumer cards, white space in place of structure, animation in place of state, or anything that "looks like AI". §36 states what this means at the level of a pixel; §34 makes it an acceptance condition.

---

## 3. Design principles

1. **Evidence first, chrome last.** On any surface containing footage, geometry or analytical results, evidence is the largest and most saturated element. Chrome is dark, flat and quiet.
2. **One grammar, five archetypes.** Every screen is an instance of a frozen archetype (§4). New capabilities select an archetype; they do not invent a layout.
3. **Colour meaning is product-wide.** A hue means one thing everywhere. UI semantic colours and evidence colours are separate namespaces and never borrow from each other (§8).
4. **State is never ambiguous.** The states in §14 are visually and verbally distinct. "Failed to load" is never rendered as "there is nothing here".
5. **Density is a feature.** Whitespace separates groups; it does not pad containers. One trained audience, one density.
6. **One selection per workspace.** A selected object appears identically selected in list, canvas, inspector and (where applicable) URL.
7. **Predictable over animated.** Motion explains a state change or it does not occur.
8. **Truthful precision.** Show the precision the data has, in the formats of §24, with the timezone discoverable.
9. **Keyboard-complete, pointer-fast.** Everything done hourly has a key; everything reachable by pointer is reachable by Tab.
10. **Offline by construction.** No asset, font, icon, style or script may require a network at runtime or from an uncontrolled source at build time.

---

## 4. Workspace archetypes

Five archetypes. **Frozen.** A sixth (Wall, for live multi-camera) is anticipated but explicitly not designed (§31).

Shared rules for all archetypes:

- Each begins with a **Context Bar** (§5): 44px, identity + state + primary actions.
- A large page title with a description sentence is **removed** from the product. Explanatory prose moves to a disclosure or is cut.
- Exactly one element owns vertical scroll per archetype.
- ~~Below 1100px viewport width all archetypes stack to a single column and the page scrolls. Below 768px layout must not break, but is not an acceptance target (§25).~~ **Amended in v2.0:** composition below Tier A is defined per archetype and per tier in §25, which is authoritative for responsive composition; this section is authoritative for scroll ownership at Tier A. The shared ≤1100px rule survives for the multi-column archetypes — Record, Workbench, Investigation and Review stack to a single column at ≤1100px and the page scrolls — while a Ledger, which has one column at every width, keeps the table body as its scroll owner and collapses columns per §25. Below 768px (Tier C) each archetype has the explicit degraded composition in §25; "must not break" is no longer the rule.

**Scroll-ownership summary (frozen, authoritative at Tier A — §25 must agree with this table, and states the ≤1100px page-scroll stacking for Record, Workbench, Investigation and Review):**

| Archetype | Owns vertical scroll | Page scrolls? |
|---|---|---|
| Ledger | table/list body | No |
| Record | the page | Yes |
| **Workbench** | inspector body only | **No — MUST fit the viewport at 1366×768** |
| Investigation | results list; inspector body independently | No |
| **Review** | the page | **Yes — Review MAY page-scroll** |

### 4.1 Ledger — operational lists

| | |
|---|---|
| **Purpose** | Scan, filter and act on many records of one kind. |
| **Structure** | Context Bar → filter toolbar (one row, ≤5 controls, at Tier A; §25 for B/C) → table or list. |
| **Scroll owner** | The table body. The page does not scroll. |
| **Width** | Full width. Columns carry individual `max-width`; when total natural width is less than available, the table is **left-aligned and not stretched**. A Ledger must never become a sparse band of text across 2560px. |
| **Inspector** | None by default. MAY open a right drawer on row selection where a record has more detail than a row can carry. |
| **Responsive** | 1366: all columns visible, or the least-important column collapses into the primary cell. Never horizontal *page* scroll; the table body MAY scroll horizontally. (Tier A; §25 for Tier B/C.) |
| **Now** | Cameras, Videos, Processing Queue, **Overview (Ledger-summary variant — §4.1.1)** |
| **Future** | Events, Entities, Cases, cross-camera scene revisions |

**Amended in v2.0 — Ledger body containment (frozen).** The audit found every Ledger rendering its table inside a viewport-high bordered frame regardless of content, so two rows, a loading spinner, an empty message or an unavailable alert each sat in the top-left corner of a large empty box, and at 2560px a 750px-wide column-capped table sat inside an 1800px-wide frame. The §11 rule is unchanged — a border marks a scroll boundary — but it is now applied to the *table*, not to the slot the table occupies:

- The containment border bounds the table's own extent. A table shorter than the available height is bordered to its content height; a table wider than the available width scrolls horizontally inside its border; the body container grows to the available height only when the table needs it. The frame never extends beyond the table's right edge on a wide display: the column cap and the containment cap are the same edge.
- The §14 state presentations for a Ledger — loading, empty, filtered-empty, unavailable — render **uncontained** on the base surface at the table's top offset, never inside, and never centred in, a viewport-high frame. Loading uses skeleton rows at the frozen row pitch when the row shape is known (every Ledger's is), so the content does not shift when it arrives (§38).
- The sticky header remains the table's, and the table body remains the scroll owner when it scrolls.

#### 4.1.1 Overview — the Ledger-summary variant (frozen exception)

Overview is a **Ledger-summary variant**, not a standard Ledger.

| Rule | Status |
|---|---|
| Overview is a summary and attention surface, not a dense operational table. | Frozen |
| Overview **MAY remain centred at `--content-max`** rather than expanding to full width. | Frozen exception |
| Standard Ledgers (Cameras, Videos, Processing Queue, future Events/Entities/Cases) remain **full width and column-capped**. | Frozen |
| The exception applies to Overview alone and MUST NOT be generalised to any other Ledger. | Frozen |
| **Amended in v2.0:** Overview is **attention-first**. Its first region is the attention list — failed and stalled processing runs, unavailable services, stale or incomplete analytics, and media awaiting processing — each row linking to the surface that acts on it; the status readouts and the recent-Tracks list follow. An Overview whose only content is counts is a summary without a purpose, which is what the audit found: four readouts and two half-empty panels occupying half of a 1366×768 viewport. When there is nothing needing attention the attention region says so in one line and does not reserve space. | Frozen |

Restated in §25 so the responsive rules and the archetype rules cannot drift apart. Open decision 6 (whether Overview survives once an Events Ledger exists) stays open; the attention-first rule is what Overview is *until then*.

### 4.2 Record — one entity's detail

| | |
|---|---|
| **Purpose** | Everything known about one object, plus its actions. |
| **Structure** | Context Bar → primary column (~70%) + facts rail (~30%). |
| **Scroll owner** | The page. |
| **Width** | **Centred at `min(--content-max, 100%)`.** Record is a reading surface, not a working surface; centring is correct here. *Reaffirmed in v2.0 after measurement:* at 2560px the centred Record leaves roughly 900px of base surface either side. That is a reading column on a wide display, not a defect, provided the Record's own regions are content-sized (a Record never pads a panel to fill height) and the facts rail keeps its fixed width rather than growing with the viewport. |
| **Inspector** | The facts rail *is* the inspector; it is not additional. |
| **Responsive** | ≤1100: facts rail stacks below the primary column. **Amended in v2.0:** at Tier C (§25) the facts rail stacks *above* the primary column when it carries identity (file, camera, recorded time), because on a narrow display the operator reads *what this is* before *what happened to it*. |
| **Now** | Processing detail |
| **Future** | Entity detail, Case detail, scene revision detail |

### 4.3 Workbench — canvas + inspector

| | |
|---|---|
| **Purpose** | Direct manipulation or interrogation of spatial content. |
| **Structure** | Context Bar → mode strip → **stage (grows)** + fixed inspector → optional footer strip. |
| **Scroll owner** | **None.** Only the inspector body scrolls. |
| **Width** | Full width. Inspector fixed at `minmax(300px, 360px)`; **all residual width after shell, inspector and required gutters goes to the stage.** |
| **Inspector** | Always present. Shows a workspace summary when nothing is selected; never blank. |
| **Now** | Scene Editor |
| **Future** | Heatmap view, occupancy view, spatial event authoring |

#### 4.3.1 Stage width rule (frozen, single formulation)

- The stage receives **all residual width** after the application rail, the fixed inspector and required gutters. The inspector is fixed; the stage absorbs everything else.
- **The stage MUST NOT be narrower than 65% of the workspace working width** (the content column minus page padding).
- At 1366×768 with the rail expanded and the inspector at its 300px minimum, this rule yields a stage of **approximately 800px (about 72% of the working width)** — comfortably above the floor. That figure is the expected outcome of the rule, not a second rule.
- **Adaptation, not compression.** Below the viewport width at which the rule can be satisfied (approximately 1150px), the Workbench inspector MUST become an **overlay drawer** so the stage keeps the full working width. At 1100px and below the workspace stacks per the shared rule above. The stage MUST NOT be compressed below the floor in order to keep a side-by-side inspector. **Confirmed in v2.0:** these measured thresholds are the Workbench's Tier B composition, restated unchanged in the §25 table — side by side with the 65% floor from the measured ~1150px threshold up, overlay drawer from 1101px up to that threshold, stacked (stage first, inspector below) at 768–1100px. The threshold is measured, not chosen: T1 records the value at which the floor is actually met, and the ~1150 figure is its expected outcome, not a second rule. Below 768px (Tier C) the Workbench does not render the editing canvas at all (§25); the stage-width rule has nothing to adapt there.
- **This MUST NOT be solved by making the inspector resizable.** Resizable panes remain deferred (§31).

#### 4.3.2 Workbench viewport rule (frozen)

Workbench **MUST fit within the viewport without page scroll at 1366×768.** This is the one archetype with a hard no-page-scroll requirement, because the stage is a direct-manipulation surface and a scrolled canvas is a broken canvas.

### 4.4 Investigation — query, results, detail

| | |
|---|---|
| **Purpose** | Form a query, scan candidates, inspect one without losing the set. |
| **Structure** | Context Bar → filter rail (252px) + results (grows) + inspector. |
| **Scroll owner** | The results list; the inspector body scrolls independently. The page does not scroll. |
| **Width** | Full width. Results column capped at approximately 900px; **surplus width goes to the inspector**, because the inspector contains evidence. |
| **Inspector** | Appears on selection. **In-place third column only at viewport ≥1600px; below that it is a right overlay drawer** over the results column. Never below approximately 440px in place. The results column MUST NOT be compressed below approximately 560px. |
| **Responsive** | 1366, 1440 and 1500: rail + results, inspector as drawer. 1600+: three columns in place. (Tier A; §25 for Tier B/C.) |
| **Now** | Search |
| **Future** | Visual similarity, OCR/ANPR lookup, structured intelligence query, NL query |

**Amended in UI-4 (open decision 3, closed).** The threshold was a frozen default of 1500px, which this section permitted UI-4 to raise to 1600px if the 1500–1600 band read as cramped. It did, and worse than cramped. Three columns at their own minimums need 252 + 560 + 440 and two 16px gutters — 1284px of working width. A 1500px viewport leaves 1244 after the navigation rail and the page gutters, so at 1500 the layout overflowed its own contained column by 40px and the inspector's right edge, including its Open and Close controls, was clipped away with no scrollbar to reach it. Measured in a browser at 1440, 1500, 1550, 1599, 1600 and 1700; 1600 leaves 1344 and fits with room to spare. The threshold is **1600px**.

The inspector's 440px floor in place is the other half of the same finding. §4.4 says surplus width goes to the inspector, which says what happens when there is surplus and nothing about what happens when there is not: a layout that granted the results their 900px cap first left the inspector 60px at 1500 and 160px at 1600 — in place by the letter of the rule and unusable in fact. 440px is the width the drawer already uses, so the inspector is the same object either side of the threshold rather than two different ones.

**Open decision 4, closed: unchanged as specified.** Measured at 1920 the results are capped at 900px and the inspector takes 480px of surplus; at 2560 the results are still 900px and the inspector takes 1120px. The cap holds whether or not a Track is selected — an Investigation with nothing selected is still a scan surface, and a 2000px result row is no easier to read for having no inspector beside it.

### 4.5 Review — evidence-dominant record

| | |
|---|---|
| **Purpose** | Examine one piece of evidence in depth with its provenance. |
| **Structure** | Context Bar → Evidence Player (≥65% width) + evidence rail. |
| **Scroll owner** | **The page. Review MAY page-scroll.** |
| **Width** | Full width. The player takes surplus width. |
| **Inspector** | The evidence rail: summary, representative frame, provenance. For Stage 2 it also contains the bounded Track Evidence Set; Representative remains primary and supplemental observations are secondary review evidence. |
| **Now** | Video Review |
| **Future** | Event evidence, dwell/crossing playback, analytical review |

#### 4.5.1 Review viewport rule (frozen)

- Review is **not** required to fit one viewport. Provenance, attestation and long evidence content legitimately extend below the fold.
- **At 1366×768, the Evidence Player and the primary evidence summary MUST both be visible in the initial viewport** without scrolling. Everything below that MAY require scrolling.
- The Evidence Player **SHOULD remain sticky/pinned** within its column while longer evidence and provenance content scrolls, so the operator never reads a fact about evidence they cannot currently see.
- ≤1100: the rail stacks below the player; the sticky behaviour is released.

---

## 5. Application shell and navigation

**Frozen:**

- Left rail navigation, 216px expanded / 56px collapsed, collapse state persisted in `localStorage` (`mavi.sidebar.collapsed`). ~~Auto-collapse only below 760px.~~ **Amended in v2.0:** at Tier A (≥1366) the rail state is the operator's choice and is never changed automatically; at Tier B it is collapsed by default and expandable as an overlay; at Tier C it is a menu control (§25). The prohibition on automatic collapse below applies to Tier A.
- Brand mark and product name at the rail head; API health indicator at the rail foot.
- Primary navigation items are ordered by operator workflow, not alphabetically.
- **The topbar becomes the Context Bar.** It carries the current surface's identity, key state badges and primary actions. 44px, sticky, full width of the content column.
- Breadcrumb form: `Section › Object › Sub-surface` (for example `Cameras › CAM-01 › Scene`). A surface MUST NOT display only a parent section title while editing a child object.

**Rules:**

- Navigation MUST be grouped into labelled sections once more than approximately seven destinations exist. Planned groups: **Operate** (Overview, Cameras, Videos, Import, Processing) and **Investigate** (Search, and future Events, Entities, Cases). Items are added only when the destination exists.
- Rail badges MAY show a count only for *attention* states (for example failed processing). Counts are neutral-coloured numerals, never red dots.
- Icon-only rail items in the collapsed state MUST carry an accessible name; `title` is acceptable for this specific case.

**Prohibited:** top navigation bars, mega-menus, tabs inside the rail, a global search field in the shell before a global search exists, automatic rail collapse at desktop widths.

**Amended in v2.0 — one information-architecture map (frozen).** The audit found the shell describing the same surface three ways: the rail says *Search*, the Context Bar says *Visual Search*; Import is a rail peer of Videos but is crumbed beneath it; Scene and Analytics highlight *Cameras* while Review highlights nothing; the Review crumb offers no way back to the Investigation that opened it. The shell therefore gains one IA map, from which the rail, the Context Bar crumb and the document title are all derived:

| Surface | Rail section › item (highlighted) | Context Bar crumb |
|---|---|---|
| Overview | Operate › Overview | `Overview` |
| Cameras | Operate › Cameras | `Cameras` |
| Scene Editor | Operate › Cameras | `Cameras › {camera} › Scene` |
| Camera Analytics | Operate › Cameras | `Cameras › {camera} › Analytics` |
| Videos | Operate › Videos | `Videos` |
| Import | Operate › Import | `Import` |
| Processing Queue | Operate › Processing | `Processing` |
| Processing detail | Operate › Processing | `Processing › {video}` |
| Search | Investigate › Search | `Search` |
| Review | Investigate › Search | `Search › {video} › Review` — the first crumb returns to the Investigation with its URL state intact when Review was opened from one, and to `/search` otherwise |
| Not found | none — the one surface with no rail highlight | `Not found` (the shell and Context Bar are still rendered) |

- A rail label and its surface's root crumb are the same word.
- A child surface highlights the rail item of its owning section; nothing in the shell is ever un-highlighted while a surface is shown.
- The shell carries a **skip link** to the workspace as its first focusable element, and a landmark structure (`banner` for the rail head, `navigation` for the rail, `main` for the workspace) so assistive technology can move between them.
- The rail's collapse control is a labelled control with a visible icon at 32px, not a 26px icon-only ghost at the rail foot; its state is announced.
- The §22 `g`-then-letter destination keys and the `?` shortcut sheet are shell obligations and are implemented by Stage 3.5, not left to a feature.
- A new surface (for example the Stage-4 ANPR/OCR lookup, an Investigation per §4.4) adds one row to this map by amendment under its owning section; the rail, crumb and title follow from the row.

---

## 6. Theme architecture

**Frozen decision: Dark now. Light and System supported architecturally and deliberately deferred.**

| Rule | Level |
|---|---|
| The shipped theme is dark. | MUST |
| Semantic tokens MUST be defined such that a light palette can be added by redefining surface/text/border semantics only, without touching any component. | MUST |
| The light palette MUST NOT be implemented now. | MUST |
| `[data-theme]` attribute switching is the intended mechanism; components MUST NOT read the theme. | MUST |
| Evidence, video, canvas and overlay surfaces are **theme-invariant and remain dark** under any future theme. | MUST |
| Page-specific or feature-specific theme overrides. | MUST NOT |
| System-preference following. | Deferred until a light palette exists. |

When light is eventually introduced, its scope is Ledger, Record and forms only. A light Evidence Player or light canvas is out of scope permanently.

---

## 7. Design-token architecture

**Frozen: a primitive + semantic token architecture, with narrowly scoped component tokens only when semantically justified.**

**Primitives.** Raw values only (`--p-gray-950`, `--p-blue-500`, `--p-amber-400`, and so on). **Components MUST NOT reference primitives.**

**Semantic tokens.** The layer components use. Grouped as: surfaces, borders, text, accent, status, **evidence/spatial (separate namespace, §8.3)**, spacing, radius, typography, control metrics, stroke widths, elevation, motion, z-index.

**Component tokens.** Permitted **only** when one component is legitimately dimensioned or coloured differently across two archetypes (for example inspector padding). Each such token MUST carry a one-line comment stating why a semantic token was insufficient. Component tokens are the exception that keeps the architecture honest; they are not a third general-purpose layer, and they MUST NOT be created to avoid naming a missing semantic role.

**Rules:**

- A screen MUST NOT introduce a colour, radius, duration or spacing literal. Existing violations are removed in UI-1 where safe.
- Evidence tokens are declared once, outside any theme block.
- Token names are normative; primitive values are implementation detail.
- `--content-max` applies to Record and the Overview Ledger-summary variant only (§4.1.1, §25).

Target scale: approximately 110 semantic tokens (from 68 flat tokens at the design baseline). This is a guide, not a quota.

---

## 8. Colour semantics

Three namespaces. **Cross-borrowing is prohibited**, with exactly one sanctioned crossover, stated in §8.3.

### 8.1 UI semantic colours

| Role | Rule |
|---|---|
| Application background / surfaces | No more than four surface levels, semantically named (app, base, raised, overlay), plus an explicit inset surface for inputs. |
| Borders | `subtle` (decorative dividers and containment edges that carry no information), `panel` (containment edges that identify an interactive or scrollable region), `strong` (hover/emphasis), `focus-ring`. |
| Text | primary / secondary / muted. **Muted is the contrast floor at approximately 5.7:1; nothing lighter may carry text.** |
| Accent | Exactly two uses: **the primary action** and **selection**. Never decoration, never a status. **Amended in v2.0:** *the* primary action is singular. A surface has at most one accent-filled action at a time — the Context Bar's primary, or a form's submit when the form is the surface's purpose. Row actions, card actions and per-item actions are secondary or ghost. The audit measured fourteen accent-filled `Process` buttons in one Videos viewport and a `Results` primary on every queue row; an accent that appears fourteen times is a colour, not an instruction. |
| Focus | A dedicated focus-ring token with a dark inner offset, so the ring reaches at least 3:1 **on every surface including the primary button**. |

Contrast obligations differ by role: interactive boundaries, state indicators and focus rings carry the 3:1 requirement of §23; purely decorative dividers and containment borders MAY sit below it (§11, §23).

**Known defects corrected in UI-1:** text on `--accent` measures 3.45:1 (fails AA — text MUST only be painted on `--accent-strong`); the focus ring on `--accent-strong` measures 2.35:1 (fails the 3:1 non-text minimum); `features.css` references `var(--focus)`, which is defined nowhere, so keyboard focus on search result rows is currently invisible.

### 8.2 Operational / status colours

| Role | Notes |
|---|---|
| success, info, warning, error, neutral | Each is a triad: text / soft background / border, so badge, alert and dot agree. |
| processing / running | Info hue and a pulsing dot. Colour alone never signals activity. |
| **stale** | New. Warning hue, desaturated, paired with a dashed border. |
| **unavailable** | New. Neutral with a diagonal hatch (the Scene Editor placeholder treatment). |
| offline | Reuses error; no new hue. |
| disabled | ~~Opacity reduction, not a colour.~~ **Amended in v2.0 (S1a):** the disabled surface, border and text tokens of §12 — never an opacity, and never a status hue. |

**Rule:** status meaning is assigned centrally (`shared/status`). A screen MUST NOT map a status string to a tone locally.

### 8.3 Evidence and spatial colours

A **separate namespace** (`--evidence-*`, `--geo-*`). Roles are **frozen**. The hues of every role the product renders were frozen in UI-1; the event marker (2a) was closed in Scene Analytics Slice 5 and the heatmap scale (2c) in Slice 6, leaving the similarity rank (2b) open (§32).

| Role | Frozen constraint |
|---|---|
| bounding box | Distinct from track path; never a status hue. |
| track path / trajectory | Distinct from bounding box. |
| zone (resting) | **MUST NOT be the UI accent.** A resting zone and a selected row must not look alike. |
| trip line | Distinct weight from bounding boxes. |
| crossing direction A→B / B→A | Two evidence hues. **MUST NOT be success/warning hues** — direction is not correctness. Always accompanied by arrowheads and A/B letters. |
| event marker | Own hue and a glyph. |
| dwell / stationary interval | Hatched fill on the timeline, not a new hue. |
| heatmap | Perceptually-uniform sequential scale with a legend. **Red-to-green scales are prohibited.** |
| similarity / ReID candidate | Own hue and a rank numeral. Never a success hue. |
| **selected geometry** | **The UI accent, as stroke and handles only.** This is the single sanctioned crossover: on canvas, accent still means "selected", consistent with §8.1. Accent MUST NOT be a resting geometry fill. |
| halo | One theme-invariant halo token applied to every overlay layer. |

**Hues chosen in UI-1** (§32, open decision 2) for every role the product renders today: zone `--geo-zone` `#fb923c`, trip line `--geo-line` `#22d3ee`, A→B `--geo-dir-ab` `#f0abfc`, B→A `--geo-dir-ba` `#e879f9`, bounding box `--evidence-box` `#a78bfa`, trajectory `--evidence-track` `#2dd4bf`. They were selected by constrained optimisation for mutual separation under normal vision and protan/deuteran/tritan simulation, then validated over the §26 footage conditions. The event marker (2a) was closed in Scene Analytics Slice 5 and the heatmap scale (2c) in Slice 6, each against the first surface that draws it. The similarity rank (2b) remains **open**: it has no surface that draws it, and this section requires a hue to be validated against real evidence. It takes its value from the same namespace in the slice that first renders it.

A hue identifies a role; it cannot also be guaranteed to contrast with footage the product does not control. **The halo is what makes an overlay legible**, which is why it applies to every overlay layer and not per surface. Every evidence distinction MUST also carry a non-colour cue (glyph, dash pattern, letter, numeral, arrowhead): eight simultaneous overlay roles cannot be told apart by colour alone under colour-vision deficiency, and UI-1 measured that ceiling rather than assuming it away.

---

## 9. Typography

**Frozen:**

- Six type sizes (11 / 12 / 13 / 14 / 16 / 20 px). No further sizes.
- One label style: 11px uppercase, approximately 0.06em tracking, muted.
- Monospace is reserved for identifiers, hashes, failure codes and coordinates. **Not for timestamps** — tabular numerals suffice.
- All numeric columns and readouts use tabular figures.
- Negative letter-spacing on headings at 16px and below is removed.

**Resolved in UI-1 — option A, a curated system stack.** The reasoning is recorded in §32 and in `tokens.css`.

| Option | Consequence |
|---|---|
| **A — curated system stack** (Segoe UI first, for the Windows deployment target) | Zero dependency, zero licence/catalogue work, zero offline risk. Rendering differs between the Windows target and the Linux CI/screenshot environment, so visual QA baselines are not pixel-comparable to production. |
| **B — bundled offline font** | Identical rendering everywhere including CI; guaranteed tabular figures. Requires licence retention, offline-dependency-policy and binary-catalogue entries, and packaging qualification. |

The token at the design baseline named "Inter" and shipped no `@font-face`, so the product silently rendered Segoe UI on Windows. UI-1 removed that claim: `--font-ui` now leads with Segoe UI and lists only families that exist on their platform, and no font is bundled. The determinism option B buys is worth nothing here, because §26 forbids committing screenshots and there are consequently no pixel baselines to keep stable.

---

## 10. Density, spacing and sizing

**Frozen:**

| Metric | Value |
|---|---|
| Control height (default) | 32px |
| Control height (small, in-row) | 26px |
| Table row target | 36–40px, **single line** |
| Toolbar height | 32px band |
| Spacing scale | 4px base, existing steps only |
| Form padding | 16px |
| Inspector padding | 12px |
| Toolbar padding | 8px |
| Icon sizes | 14 / 16 / 20px |

### 10.1 Target size (frozen, aligned to WCAG 2.2 Target Size (Minimum))

- Interactive pointer targets **SHOULD provide at least a 24×24 CSS px effective target area** wherever practical. "Effective" means the actual hit area, which may exceed the visible mark.
- **Small visible canvas handles MAY remain visually small** (a 3–4px vertex mark is correct for precision work), but their **invisible pointer hit area SHOULD be at least 24×24 CSS px**.
- If a smaller effective target is ever unavoidable, the implementation MUST satisfy and **document an applicable accessibility exception** in the PR. A target below 24×24 is never the product default.
- **Desktop controls MUST NOT be inflated to mobile touch sizes (44–48px).** MAVI remains a dense desktop workstation; the 32/26px control heights above stand.

### 10.2 Other density rules

- Two-line table cells are the exception, not the default. Long names truncate, with the full value available in the inspector or on hover.
- **User-selectable density is deferred** (§31).

---

## 11. Surfaces and containment

**Containment rule (frozen):** a border or panel marks **a scroll boundary or an editable region**. Nothing else earns one.

| Element | Contained? |
|---|---|
| A scrolling table or list | Yes |
| A form | Yes |
| An inspector | Yes |
| A canvas/stage | Yes |
| A summary, stat readout, heading group, key/value block | **No** |
| A panel already inside a contained panel | **Never** |

- Maximum nesting depth: **one** contained surface inside the workspace. Card-inside-card is a defect.
- Radii: 4px for controls, 6px for containers. Nothing rounder.
- Shadows are reserved for floating layers (drawers, popovers). Resting containers on a dark surface get a border, not a shadow.
- Floating layers: one drawer style and one popover style. No other floating surfaces. **Amended in v2.0:** the drawer is the §27 Drawer primitive — right-anchored, 420–480px (the Workbench inspector drawer keeps its 300–360px inspector width) at Tiers A and B, capped at the working width; full width at Tier C; the filter rail's Tier B/C drawer opens from the results or toolbar header. Exact Tier B/C drawer geometry is confirmed by inspection in S5 (T1/T2).
- A containment border that exists only to group content visually is decorative and is not required to meet the 3:1 boundary threshold (§8.1, §23). A border that identifies an interactive or scrollable region is not decorative and does carry that threshold.

---

## 12. Interaction-state grammar

| State | Required treatment |
|---|---|
| **hover** | Surface step +1 and/or stronger border. Text colour MUST NOT change on hover. |
| **focus** | 2px focus ring with a dark inner offset; visible on every surface including primary buttons. Never suppressed. |
| **selected** | Accent-soft fill **plus** a 3px inset accent bar (lists/rows) or accent stroke and handles (canvas). Not colour alone. |
| **pressed / active mode** | `aria-pressed` **and** a visible active fill (segmented control). A control with `aria-pressed` and no pressed style is a defect. |
| **dragging** | `grab` / `grabbing` cursor; the dragged handle takes the accent fill. |
| **disabled** | ~~Reduced opacity and `not-allowed` cursor.~~ **Amended in v2.0:** a disabled control takes the disabled surface and text tokens (`--control-disabled-bg`, `--text-disabled`), not opacity, so a disabled primary reads as *off* rather than as a translucent primary and its label stays legible (a disabled control is exempt from the §23 text minimum, but a label that cannot be read is still a defect). `not-allowed` cursor. The *reason* MUST be stated adjacently when not obvious — never only in a `title` on a disabled control, which receives no pointer events. |
| **invalid** | `aria-invalid`, ~~a warning border~~ **an error border and an error message of the same hue** (Amended in v2.0: the audit found an amber border beside red text, two hues for one state, and the amber border measured almost indistinguishable from the resting border), and an inline message associated via `aria-describedby`. On submit, the first invalid field is scrolled into view and focused; a rail or form that validates off-screen is a defect. |
| **saving** | The control's label changes ("Saving…") and the control disables. No spinner overlay. |
| **saved** | A state label in the Context Bar. No toast, no flash. |
| **processing** | Status badge, pulsing dot, and determinate progress where the API supplies a percentage. Never a fabricated percentage. |

---

## 13. Motion

**Frozen:**

- One standard duration (approximately 120ms) for state transitions; one slower duration (approximately 180ms) for drawer open/close. No other durations.
- **Animate:** hover surface/border, drawer translate, progress width, activity dot pulse.
- **MUST NOT animate:** route changes, layout reflow, selection highlight, table sort, value changes, focus ring, data arrival.
- `prefers-reduced-motion: reduce` disables all transition and animation duration globally. Already implemented; MUST be preserved.
- Motion that does not explain a state change is prohibited.

---

## 14. Operational-state taxonomy

**Frozen vocabulary.** Every surface MUST distinguish these. Conflating *unavailable* with *empty* is a defect class, not a nit.

| State | Visual | Copy pattern | Retry |
|---|---|---|---|
| **loading** | Inline spinner and label; skeleton only where row height is known | "Loading videos…" | — |
| **empty** (no data) | Icon, title, one sentence, primary action | "No videos imported yet" | — |
| **filtered-empty** | Filter icon, title, "Clear filters" | "No videos match these filters" | — |
| **not configured** | Hatched placeholder, title, action | "No scene configured" | — |
| **disabled** | Neutral badge and reason line | "Analytics disabled by this revision" | — |
| **unavailable** | **Warning/error alert — never the empty block** | "The video list is unavailable" | Yes |
| **unknown** | Neutral outlined state + explicit text/icon; never colour-only | "Analysed · value unknown" | No |
| **partially available** | Info strip with explicit counts | "4 of 7 runs analysed · 1 pending · 1 disabled" | — |
| **processing** | Info badge and determinate progress | "Processing · 63%" | — |
| **failed** | Error alert, operator sentence first, code in mono last | "Processing failed · `worker_lease_lost`" | Yes |
| **stale** | Dashed border and stale badge | "Analysed with revision 3 · active is 4" | Re-analyse (when it exists) |
| **offline** | Persistent banner and health indicator | "API unreachable since 11:42 · retrying" | Automatic |
| **conflict** | Warning alert and explicit reload action, edits preserved | "This changed since you began editing" | Reload |
| **permission denied** *(future)* | Error block, no retry | "You do not have access to …" | No |

### 14.1 Async-state boundary (frozen architecture, implementation-flexible)

The architectural intent is absolute: **unavailable must never silently become empty.** The mechanism is deliberately not coupled to any one data library.

| Rule | Level |
|---|---|
| The product MUST have a shared **async-state boundary** (a normalized async-state pattern) that selects exactly one of: **Loading · Error/Unavailable · Empty · Content**. | MUST |
| A caller MUST NOT be able to interpret *"data is undefined because the request failed"* as authoritative empty data. The boundary makes that state unrepresentable at the call site. | MUST |
| The boundary MAY adapt TanStack Query into a small normalized state object. It MAY equally adapt any other source. | MAY |
| The empty, loading and error presentations **SHOULD remain presentation-focused** — they render what they are told to render. | SHOULD |
| Presentational components MUST NOT be required to import or understand React Query. A compelling, documented implementation reason is required to deviate. | MUST |
| **Amended in v2.0:** every data region on every surface goes through the boundary. The audit found it adopted on three of ten surfaces, with the other seven selecting states by hand — and, as a direct result, four placements of the same unavailable alert, two words for one missing-thumbnail condition and a loading spinner on one Ledger beside skeleton rows on the next. The boundary selects the state; §37 fixes how each state is presented per region kind; a surface composes the two and adds nothing. | MUST |
| **Amended in v2.0 — placement.** A state presentation renders **inside the region it replaces**, at that region's top, uncontained (§4.1): a results column's unavailable alert sits where its first row would be, a panel's where its first value would be, a page's above its first region. Retry is the alert's trailing action, never a separate control below it. Alerts for one cause are one alert; a surface MUST NOT stack three warnings for one unavailable service. A page-level alert has a readable maximum width (`--alert-max`), left-anchored, not the full 2400px of an ultra-wide. | MUST |

---

## 15. Feedback, confirmations and notifications

**Inline first.** The result of an action appears where the action was taken.

| Mechanism | Rule |
|---|---|
| **Inline** | Default. Button label changes, row badge changes, field message appears. |
| **Banner** | For page-scope conditions that persist (offline, conflict, superseded revision, partial coverage). Never auto-dismissed. |
| **Transient feedback (toast)** | **No workflow may depend on a transient toast, and a persistent operational problem MUST NOT be delivered as one.** Brief, non-critical acknowledgement MAY use transient feedback where it materially improves clarity. A toast is never the only record of a failure. |
| **Modal / dialog** | **Routine editing MUST NOT require a modal.** A modal is acceptable only when temporarily blocking the underlying workspace is genuinely the correct interaction for a rare, consequential decision. Where an in-band two-step confirmation conveys the same consequence, it is preferred. |
| **Native `window.confirm`** | MUST be replaced. It cannot state consequences in product language, cannot be styled, and browsers offer to suppress it — silently removing the safeguard. **Amended in v2.0:** the audit found three `window.confirm` call sites still in production (Scene Editor reset and discard, the unsaved-changes route guard). The shared **Dialog** primitive (§27) replaces them in Stage 3.5 foundation slice; its contract is a consequence sentence, a named destructive action, a secondary cancel, focus moved in on open and restored on close, `Esc` cancels, and the surface behind it inert. |
| **Progress** | Determinate where the API supplies a percentage; indeterminate otherwise. Fabricated progress is prohibited. |

Confirmations state the **consequence**, not the question: "Saving disables analytics for CAM-01", not "Are you sure?".

---

## 16. Tables and data-heavy views

**Frozen:**

- One table primitive. Legacy and duplicate table styling is removed.
- **One logical line per row.** Names truncate; the full value lives in the inspector or on hover.
- **One status column, one badge per row.** Two badges describing the same thing in one row is a defect; a secondary run state appears only when it differs from the primary state.
- Numeric columns are right-aligned with tabular figures.
- Sticky header. A sticky first column only when a table exceeds approximately eight columns (no table does today; §36.3 lists it with the other permitted sticky elements).
- Row actions sit at the row's trailing edge, consistently: one ~~primary~~ **secondary** text action plus at most one icon-only action (Amended in v2.0, §8.1: a row never carries the accent-filled primary).
- **Amended in v2.0 — row pitch.** The 36–40px single-line target is measured, not aspired to: the harness asserts it (§26). The audit measured 43px (8px cell padding around a 20px badge plus line height); the row's vertical padding is the component token, and a badge inside a row uses the in-row 26px control metric, not the standalone one.
- **Amended in v2.0 — truncation.** A truncated cell exposes its full value by keyboard as well as pointer: `title` alone is pointer-only. The row's inspector or detail surface is the full-value home; where a Ledger has no inspector the full value appears on focus via the same tooltip the pointer gets (§27 Tooltip).
- **Filters live in a toolbar row above the table**, never inside the container header (at Tier A; §25 moves them to a drawer at Tier C).
- Sorting: only where meaningful; indicator required; client-side sorting is acceptable for small inventories. The per-Ledger scope is settled in §32 decision 5.
- Empty / filtered-empty / unavailable are three distinct treatments (§14).
- Identifiers (GUIDs) MUST NOT appear in table cells. They belong in inspectors and disclosures.

---

## 17. Search and investigation

**Frozen:**

- **URL is the state of record** for committed filters and selection. A shared or refreshed link reproduces the same view. Draft (uncommitted) filter edits are local and are not written to the URL.
- Committed filters are visible **as chips at the head of the results column**, each individually removable — not only inside the rail.
- The results header answers *why this set*: the active scope in operator language. Implementation detail (cursor strategy, page size) MUST NOT be standing copy.
- The filter rail is a set of grouped, scrolling field sections; it MUST NOT be laid out as a fixed-row container.
- Search and Reset are not visual peers: Search is primary, Reset is secondary.
- Result continuation after a failure is operator-driven (retry the page, or refresh the snapshot when it has expired). Automatic infinite retry is prohibited.
- Zero results, not-analysed and unavailable are three different messages with three different verbs (§14).
- Partial analytics coverage (Slice 4) appears as a coverage strip beneath the results header, using the coverage bucket vocabulary frozen in ADR-011.
- **Saved searches** (future) are named canonical URLs — no new state mechanism.
- **Amended in v2.0.** The keyboard legend (`j`/`k` move · `Enter` open · `Esc` close) is not standing header chrome; it lives in the `?` shortcut sheet (§22) and MAY appear once as a dismissible hint on first use. The per-row ordinal (`#1`, `#2`) is removed: position in a snapshot is not operator information. A result row's missing thumbnail is the §37 evidence placeholder, in one vocabulary shared with the grid card. A long camera or video name in a row truncates at the row's identity width; it never wraps the row to two lines (§16).
- **Reaffirmed in v2.0 (open decision 4).** With nothing selected at ≥1600px, the results column keeps its cap and the in-place inspector slot stays empty base surface — unbordered, with no placeholder panel. The alternative, widening the results until a selection is made, moves the scan column every time the operator opens or closes a Track, and a column that moves is worse than a column with space beside it.

---

## 18. Media and evidence

**One Evidence Player component** serves Review, the Investigation inspector, and future analytical playback. Multiple player implementations are prohibited.

**Frozen interaction model:**

1. **Frame.** Fills available width, black matte, overlays projected into the true content rectangle (letterbox/pillarbox aware). **Native browser video controls MUST NOT be used** — they occlude the lower region of the frame where evidence is drawn.
2. **Transport strip below the frame.** Play/pause, frame step, jump to Start / Evidence / End, speed, time readout. Editing and playback controls are never overlaid on the frame.
3. **One timeline.** A single timeline spanning the media duration, carrying the subject interval, the representative-frame tick, the playhead, and **extension lanes** for future analytical intervals (zone visits, crossings, dwell, stationary, events). Two scrub bars on one surface is a defect.
4. **Layer controls.** A compact toggle group (box / path / zones / lines / events), persisted per operator locally.
5. **Poster.** The representative frame is used as the poster, so the frame is never black before metadata arrives.
6. **Uncertainty.** Persisted samples and interpolated positions MUST be visually distinguishable (for example filled versus outlined). Nothing is drawn outside the sampled range. **Confidence MUST NOT be encoded as opacity** — faded evidence reads as unreliable rendering, not low confidence. Confidence is text.
7. **Accessible twin.** Every interval drawn on the timeline has a corresponding list entry (§23).

Extension points MUST exist for analytical lanes, but **lanes for data that does not yet exist MUST NOT be implemented** (§33.6).

---

## 19. Spatial-intelligence visual grammar

**Frozen hierarchy** (exact hues open per §8.3):

| Aspect | Rule |
|---|---|
| Stroke weights | Three only: hairline (indicators), standard (boxes, lines, paths), emphasis (selected). Non-scaling stroke always. |
| Zone fill | Low opacity; **MUST NOT exceed approximately 25%** — footage must remain readable through a zone. |
| Halo | Every overlay layer carries a tight dark halo; text labels use a matte-coloured paint-order stroke. Applied once as a layer treatment, not per shape. |
| Selected | Accent stroke and handles. One selected object per canvas. |
| Hover | Fill step only. Stroke colour MUST NOT change on hover. |
| Disabled geometry | Dashed neutral stroke, minimal fill, no handles. |
| Persisted versus inferred | Solid versus outlined/dotted. Never conflated. |
| Labels | Shown on hover/selection, except endpoint letters and event glyphs, which are always visible. |
| Direction | Perpendicular indicators with arrowheads **and** letters **and** labels. Colour is never the only direction cue. Direction indicators are drawn only where direction is semantically meaningful. |
| Heatmap | Sequential scale, legend and opacity control. Never composited over playing video without operator control of opacity. |
| Similarity / ReID | Candidate styling and rank numeral. A candidate MUST NOT be styled as a confirmed fact. |

---

## 20. Inspectors and contextual panels

| Archetype | Inspector |
|---|---|
| Workbench | **Always present**, fixed width, shows a summary when nothing is selected. Becomes an overlay drawer below approximately 1150px per §4.3.1 (from 1101px up to the measured threshold); at ≤1100px it is stacked below the stage, and at Tier C the editing canvas is not rendered (§25). |
| Investigation | **On selection**; in-place at 1600px and above, drawer below that (§4.4, open decision 3 closed in UI-4). |
| Review | The evidence rail; always present. |
| Ledger | **None by default.** MAY use a right drawer on selection. |
| Record | The facts rail *is* the inspector. There is no additional panel. |

**Rules:**

- Inspector width is fixed per archetype. **Resizable splitters are deferred** (§31) and MUST NOT be introduced to solve a width constraint (§4.3.1).
- The inspector body scrolls; its header is sticky.
- Selection synchronisation is mandatory: list, canvas and inspector always agree.
- `Esc` closes a drawer inspector; it does not close a permanent one.
- **Amended in v2.0 — drawer focus contract.** A drawer that opens on an action moves focus to its heading on open and returns it to the invoking control on close; its tab sequence is contained while it is an overlay; `Esc` closes it; the content it covers is `inert`. The audit found both drawers (Investigation below 1600px, Workbench inspector at 1101–1149px) implemented in CSS alone with no focus management. This is the shared **Drawer** primitive (§27); an archetype composes it, never re-implements it.
- **Amended in v2.0 — progressive disclosure.** An inspector presents its content in the three tiers of §37.2: operational facts first, explanation second (collapsed where long), forensic detail (identifiers, raw coordinates, engine and revision identity) last and collapsed by default. A fact is stated once per inspector; the audit found the scene-revision identity line printed twice in one Investigation inspector.
- **A third permanent column on Ledger or Record is prohibited.**
- **Stage-2 evidence-set rule:** Review/Investigation inspectors MAY expose multiple accepted Track observations, but Representative is always visually primary. Supplemental evidence is presented as a bounded evidence strip/list with role, timestamp and selection context; it MUST NOT compete with the Evidence Player as a second primary canvas.
- Track detail contracts used by these inspectors evolve from one representative observation to `observations[]`, while retaining a direct Representative reference for display convenience.

---

## 21. Forms and editing

**Frozen:**

- Labels above inputs. Optional fields are marked; required fields are not.
  - **Amended in UI-4 (query and filter rails only).** Where **every** field in a
    query or filter rail is optional and an empty query is a valid query,
    individual "optional" suffixes MAY be omitted: the optionality is a fact
    about the whole query rather than something that distinguishes one field
    from another, so marking all of them marks nothing and only lengthens every
    label the operator scans. The rule above is unchanged for ordinary
    create/edit forms, where "optional" still tells the operator which fields
    they may leave alone. This exception does not extend beyond query and
    filter rails.
- **Inline, field-level validation** with `aria-invalid` and a message associated via `aria-describedby`. Page-level alerts are reserved for server errors.
- **Dirty state appears in the Context Bar**; Save is disabled when there are no changes.
- Reset/Cancel is secondary and adjacent to Save, never its visual peer.
- Conflicts (HTTP 409) **preserve the operator's edits** and offer an explicit reload; a conflict attributable to a specific field highlights that field.
- **Routine create/edit MUST NOT require a modal** (§15). Inline forms, or a drawer on the owning Ledger, are preferred over a permanent second card beside the list.
- Where a save has a consequence beyond the record itself, that consequence MUST be stated before the operator commits. The Scene Editor's analytics-disabling two-step confirmation is the reference implementation.
- A background refetch MUST NOT overwrite unsaved operator work. The page states that the underlying record changed and leaves the draft intact.

---

## 22. Keyboard and expert workflows

A deliberately small set. Shortcuts MUST NOT fire while focus is in a text-entry context.

| Scope | Keys |
|---|---|
| Global | `/` focus the surface's primary filter; `g` plus a letter to a primary destination; `?` shortcut sheet |
| Lists | `j`/`k` or `↑`/`↓` move; `Enter` open; `Esc` close inspector |
| Evidence Player | `Space` play/pause; `←`/`→` frame step; `J`/`L` ±1s; `Home`/`End` subject start/end; `E` evidence frame; layer toggles |
| Workbench | Mode keys; `Enter` complete; `Esc` cancel; `Delete` remove selection; arrows nudge, `Shift`+arrows coarse nudge |
| Forms | `Ctrl+S` save when dirty; `Esc` cancel an in-band confirmation |

**`Backspace` MUST NOT be a destructive shortcut.** A command palette is **deferred** (§31).

---

## 23. Accessibility

Architecture, not remediation. Every PR asserts these.

| Requirement | Level |
|---|---|
| **Text contrast at least 4.5:1.** | MUST |
| **Interactive component boundaries, state indicators, meaningful graphical information and focus indicators at least 3:1 on the surface where they appear.** Decorative dividers and containment borders that are not required to identify a control, a state or information MAY be lower contrast (§8.1, §11). | MUST |
| Visible focus on every interactive element; focus never suppressed without an equivalent | MUST |
| An interactive control's accessible name **contains its visible label** | MUST |
| Semantic HTML first; ARIA only where semantics are unavailable | MUST |
| A role's contract is honoured or the role is not claimed (no focusable children inside a `listbox` option; `aria-expanded` requires a controlled region) | MUST |
| Status regions are mounted before they are populated, so a mode change is announced | MUST |
| Form fields labelled; errors programmatically associated | MUST |
| `prefers-reduced-motion` honoured globally | MUST |
| **Non-colour cue for every status and every evidence distinction** | MUST |
| **Effective pointer target at least 24×24 CSS px** wherever practical; small visible canvas handles keep a 24×24 invisible hit area; any smaller target requires a documented accessibility exception (§10.1) | SHOULD / documented exception |
| **Accessible twin for spatial content**: every canvas has a list naming each object, its state and its coordinates; every timeline interval has a list entry. The twin is the same control the pointer uses, not a parallel accessibility-only surface | MUST |
| Tooltips carry no information required to operate the product; `title` alone is never a control's only label (the collapsed rail item, §5, is the one sanctioned exception) | MUST |
| Keyboard shortcuts do not fire in text-entry contexts | MUST |
| **Amended in v2.0 — target: WCAG 2.2 Level AA.** The product is assessed against WCAG 2.2 AA as a whole, not against the rows above alone. Stage 3.5 adds to the obligations: a skip link and landmarks (§5); drawer and dialog focus management (§15, §20); every drawer, dialog, menu and disclosure keyboard-complete; tab order follows reading order on every archetype; error messages associated and announced; `prefers-reduced-motion` honoured; **200% browser zoom at 1366×768** (an effective 683px) reflows under the Tier C rules of §25 with no horizontal scroll and no lost control; non-colour cues for every state. **Documented exception:** the Workbench canvas is not rendered below 768px (§25 Tier C), so at 200% zoom on a 1366-wide display scene *editing* is unavailable while every other surface keeps its function; this is recorded as a WCAG 1.4.4 exception for the Workbench alongside the 1.4.10 non-claim below, not hidden behind the tier rule. | MUST |
| **Amended in v2.0 — verification.** The §26 harness asserts the structural obligations a rendered page can settle: one `main`, a skip link first in tab order, every control named, focus visible after each `Tab` in the sweep, no focusable element inside an `inert` region, dialog and drawer focus placement, and no `aria-pressed` control without a pressed style. Contrast remains derived from the tokens in `styles/contrast.test.ts`. No third-party accessibility engine is introduced (§34 item 11); the obligations are asserted directly. WCAG 1.4.10 reflow at 320 CSS px is **recorded as not targeted**: the narrowest supported width is Tier C's 390px (§25), and the gap is stated rather than claimed. | MUST |

---

## 24. Time, duration and numeric formatting

Centralised in shared formatters. Per ADR-004, the browser or operating-system timezone is never authoritative.

| Quantity | Standard |
|---|---|
| Absolute timestamp, table | Compact form that never wraps; year omitted when it is the current year; full form on hover or in the inspector |
| Absolute timestamp, inspector | Full form **with the display timezone visible** |
| Timezone disclosure | Stated once per surface in the Context Bar, not repeated as a key/value row on every panel |
| Media offset | `mm:ss.t` in players (tenths); `mm:ss` in lists |
| Duration | Zero-padded, consistent unit ladder |
| Confidence | Integer percent in lists; one decimal in inspectors. **One decimal in a dense list is false precision.** |
| Counts | Tabular figures with thousands separators |
| Identifiers | Mono; truncated with ellipsis in lists, full in inspectors |
| Wall-time input | The expected format and the operative timezone MUST be visible next to the field; the browser's locale format MUST NOT silently differ from the product's display format |

---

## 25. Responsive and ultra-wide behaviour

**Desktop-first. Frozen.** This section and §4 must agree; §4's scroll-ownership table is authoritative on scroll at Tier A, and the compositions below say where the page scrolls at Tier B and C.

**Amended in v2.0 — support tiers replace the v1.0 viewport table.** Version 1.0 defined behaviour at four desktop snapshots and said only "functional, not optimised" below 1100px and "must not break" below 768px. The audit found that the product does not break there because nothing was designed there: the rail force-collapses at 760px with its toggle hidden, the Ledgers and Investigation stack by accident of flex wrapping, and no state below 1366px was ever inspected. A rule that holds only at the widths someone happened to screenshot is not a responsive rule. Version 2.0 freezes three **support tiers**, each with a stated purpose, a stated acceptance, and behaviour defined as *ranges* between anchors, so that every width between two anchors is covered by the rule that spans them.

| Tier | Width range | Purpose | Acceptance |
|---|---|---|---|
| **A — Workstation** | **≥ 1366px** (anchors 1366×768, 1440×900, 1920×1080, ~2560×1080 and ~2560×1440) | The operational workstation: every archetype in full form; multi-hour use. | Every §4 rule; every §34 item; the §26 sweep at every anchor. **This is the only tier in which a workflow is accepted.** |
| **B — Compact** | **768px ≤ width < 1366px** (anchors 1024×768 landscape and 768×1024 tablet portrait; the measured ~1150 Workbench threshold, the drawer band below it and the ≤1100 stacking band of §4 all lie inside it and are unchanged) | A smaller laptop, a half-screen window, a tablet in landscape or portrait: the operator can do everything, with layouts that trade parallelism for space on purpose. | Designed single-column and drawer behaviours per the table below; no horizontal page overflow; no clipped or unreachable control; every §14 state distinguishable; the §26 sweep at both anchors. **Not optimised for multi-hour operation and not an acceptance viewport for a workflow.** |
| **C — Narrow** | **390px ≤ width < 768px** (anchors 390×844 and 430×932) | Reading, not operating: a quick check of status, a Record, a Review playback. **Not an operational workstation and not made one by this tier.** | Intentional degradation per the table below; no horizontal overflow; no clipped control; every action that is offered is reachable; editing surfaces state that they need a wider display rather than rendering unusably. **No workflow acceptance.** The mobile analyst experience stays deferred (§31). |
| below 390px | — | Not supported. | Nothing asserted. |

**Behaviour by archetype and tier (frozen).**

| Archetype | Tier A | Tier B | Tier C |
|---|---|---|---|
| **Shell** | Rail expanded (216px) or collapsed (56px) by operator choice; Context Bar 44px. | Rail collapsed by default, expandable as an overlay; the collapse control stays visible and labelled. Context Bar 44px; its primary action keeps its label. | Rail is a top-of-page menu control opening an overlay; Context Bar wraps its identity to one truncated line with the primary action icon-plus-label at 32px. |
| **Ledger** | Full width, column-capped, body scrolls. | Columns collapse by stated priority into the primary cell (§4.1); the table still scrolls its body at every Tier B width (a Ledger is one column and has nothing to stack); a filter toolbar wraps to two rows at most. | A single-column list of the primary cell plus status; the row's action is reachable; filters move into a drawer. |
| **Ledger-summary (Overview)** | Centred at `--content-max`. | Regions stack in attention order. | Attention list only, then counts. |
| **Record** | Centred, primary ~70% + facts rail ~30%. | 1101–1365: the Tier A composition is fluid — the primary column shrinks and the facts rail holds a 280px minimum (a region minimum to be measured and confirmed in S3b); ≤1100: facts rail stacks below. | Facts rail stacks above the primary column when it carries identity, otherwise below (§4.2). |
| **Workbench** | Stage ≥65%, inspector fixed, no page scroll (§4.3.1, §4.3.2). | Exactly the §4.3.1 progression: **~1150–1365px** side by side, stage ≥65% of working width, fixed inspector, no page scroll; **1101px up to the measured ~1150 threshold** inspector as an overlay drawer (the §27 Drawer, opened from the mode strip's inspector control, which is the one control added at this width), stage at full working width, no page scroll; **768–1100px** single-column stacked composition per the shared §4 rule — stage first at full width, inspector below, the page scrolls. The mode strip MAY wrap; every editing control stays reachable at every width. | **Explicit unsupported state**: the Workbench renders its Context Bar, its read-only object summary and a one-sentence statement that editing needs a display of at least 768px; it does not render the editing canvas. |
| **Investigation** | Rail 252 + results + inspector (drawer <1600, in place ≥1600). | **1101–1365px**: rail in place beside the results (252 + ≥560 fits the working width down to 1101 with the shell rail collapsed), inspector as a drawer — the §4.4 drawer composition unchanged; **768–1100px**: stacked per the shared §4 rule — rail as a drawer opened from the results header, results full width, inspector as a drawer, page scrolls. | Results list full width; filters and inspector as full-width drawers; grid view unavailable. |
| **Review** | Player ≥65% + rail; player sticky. | 1101–1365: the Tier A composition is fluid — the player keeps its 65% floor and the rail shrinks to its 320px minimum (to be confirmed in S3e); ≤1100: rail stacks below the player; sticky released. | Player full width, then the summary, then provenance; transport keeps every control at ≥24px effective target. |

**Fluid rules between anchors (frozen).** A layout rule is stated as a range, never as a point. Where a region has a minimum and a maximum width, it is fluid between them and the breakpoint is where the minimum can no longer be met — the 1600px Investigation threshold (§4.4) and the ~1150px Workbench threshold (§4.3.1) are both derived this way and are the model, and both are kept unchanged by this section: a tier boundary (768, 1366) is a boundary of *acceptance*, never a breakpoint, and a measured breakpoint is never moved to coincide with one. New breakpoints are derived from measured minimums, not chosen round numbers. Desktop compression — shrinking a Tier A layout until it fits — is not Tier B behaviour; Tier B is a different composition of the same regions.

**Ultra-wide (unchanged from v1.0).** Ultra-wide is used, not capped. Workbench, Investigation, Review and standard Ledgers occupy full width; surplus goes to the stage (Workbench), the inspector (Investigation), the player (Review). Standard Ledgers are **left-aligned and column-capped**, not stretched, and (Amended in v2.0, §4.1) their containment is capped with them. Record remains centred at `--content-max`. Overview, as the Ledger-summary variant, MAY also remain centred at `--content-max` (§4.1.1) — this is the only Ledger permitted to do so. ~2560×1440 is added as an anchor because a 1440-high display exposes vertical fill: a region that pads itself to the viewport height is as much a defect at 1440 high as a frame that stretches to 2560 wide.

**Historical (v1.0).** The v1.0 table listed 1366×768 as "real acceptance viewport", 1440×900 "as 1366", 1920×1080 "all archetypes in full form", ~2560×1080 "used, not capped", "1100px and below: single-column stacking, functional, not optimised" and "below 768px: must not break, not an acceptance target". The Tier A rules above preserve every v1.0 obligation at the four original anchors. The v1.0 "known defect (UI-1)" — `.page` width capping Workbench and Investigation at 1600px on ultra-wide — was corrected in UI-1 and is recorded in §33.2.

---

## 26. Visual QA standard

**Normative. Unit tests do not satisfy this requirement.**

**Every significant frontend PR MUST** be visually checked in a real browser at ~~1366×768, 1440×900, 1920×1080 and approximately 2560×1080~~ **every applicable tier anchor (Amended in v2.0; the table below)**, across the states relevant to the change:

- populated, empty, loading, unavailable/error, selected/detail, long-name and dense-data, validation and conflict where applicable.

**Surfaces containing media or spatial content MUST additionally be checked against:**

- bright footage, dark footage, letterboxed and pillarboxed sources, and overlay visibility over each.

**Method:** a scripted browser pass against the real application with intercepted API fixtures. The harness and its fixtures **MUST NOT require production code to be altered to make inspection easier**. Generated screenshots are working artefacts and **MUST NOT be committed**.

**Automated assertions the harness SHOULD make:** no horizontal page overflow; no uncaught page errors; no element overlap in the checked states; and, on a surface that declares an archetype, the §4 geometry and scroll-ownership rules only a rendered page can settle.

**A contained column clips in both directions.** An archetype whose page does not scroll cannot produce a document-level horizontal scrollbar either, so a layout whose columns do not fit simply loses its right edge — controls and all — while every other assertion passes. The harness MUST check a contained column's width as well as its height. This is how the Investigation at 1500px was found to be clipping the inspector's own Open and Close controls (§4.4, open decision 3).

**A deliberate overlay is not an overlap.** A drawer covers what is behind it by design, so a pair where exactly one side sits inside a positioned overlay is the archetype working. Two elements inside the *same* overlay are still compared with each other.

**Reporting:** the PR states which viewports and states were checked and what the pass found. "No visual regressions" without an enumerated pass is not conformance.

**Amended in v2.0 — visual-regression strategy (frozen).** The scripted harness (`tools/web-visual-qa`) is confirmed as the method. The audit found its assertions sound and its reach too short: it does not run in CI, its default sweep covers only the four Tier A anchors, and everything it does not assert — row pitch, primary-button count, containment depth, state placement, focus order — is left to a person reading up to five hundred captures. The strategy is revised as follows; what is *not* adopted is stated with its reason.

| Decision | Status |
|---|---|
| **Deterministic layout and DOM assertions are the regression gate**, not pixels. The harness asserts, per state and width: no horizontal overflow; no page error; no overlapping controls; token resolution; focus visibility; archetype geometry and scroll ownership (all existing); and, added in Stage 3.5: table row pitch within 36–40px; at most one accent-filled primary per surface; containment nesting depth ≤1 and no viewport-high frame around sparse content; the §37 state presentation present inside its region; skip link, landmarks and drawer/dialog focus placement (§23); no text overflow outside its box; no `aria-pressed` without a pressed style; and the tier rules of §25 at the width being swept. | Frozen |
| **The default sweep covers every tier anchor**: 1366×768, 1440×900, 1920×1080, 2560×1080, 2560×1440 (Tier A); 1024×768, 768×1024 (Tier B); 430×932, 390×844 (Tier C). A state declares which tiers apply to it; a Workbench state at Tier C asserts the unsupported-state rendering, not the canvas. | Frozen |
| **The harness runs in CI** on every frontend PR, assertions only, against the production build; captures are uploaded as a CI artefact for human review and expire with the run. Nothing is committed. The runner needs a Chromium and ffmpeg, both already present on the hosted runner image; no npm dependency is added. | Frozen |
| **Assertion manifest (Stage 3.5, §34.2).** The harness may know every v2.0 rule from S2 onward, but a rule becomes a *blocking* CI assertion only when the slice that implements the behaviour has merged. The manifest (`tools/web-visual-qa`, one entry per rule **per tier**) records each rule, at each tier it is evaluated at, as **`blocking`**, **`measured/pending`** (evaluated and reported, never fails the build, with the owning slice named) or **`not-applicable`** (with the reason, for example a Tier C assertion on a state that declares Tier A only). Until T1/T2 flip them, every assertion evaluated at a Tier B or C anchor — generic (overflow, overlap, clipped column) or tier-specific — is `measured/pending`, because nothing below 1366px has been inspected at the baseline and S2 must not block on S5 behaviour. No rule silently disappears: a rule leaves `measured/pending` only by becoming `blocking` when its slice merges, and the register row for that slice cites the manifest change. At S7 every rule is `blocking` or `not-applicable`. | Frozen |
| **Pixel-diff screenshot baselines are not adopted.** The UI font is the platform stack (§32 decision 1), so a pixel baseline captured on Windows does not match a Linux runner and vice versa; making it match would mean bundling a font *for the screenshots*, which ADR-012 Decision 6 and §32 decision 1 reject. Masking, thresholds and per-platform baselines would make the gate either blind or flaky. Layout assertions are deterministic across platforms; they are the gate. Revisited only if a pinned Windows runner with a frozen font set becomes part of CI, and then by amendment. | Frozen |
| **The human pass is bounded.** A PR's visual pass is the *changed* surfaces at every applicable anchor plus the six reference surfaces (§39) at 1366 and 2560 as a canary; the full 125-state sweep is a release-gate activity, not a per-PR one. | Frozen |
| Typography determinism: the harness records the resolved `font-family` per state so a platform-font fallback is visible in the measurement, not silently absorbed. | Frozen |

---

## 27. Component-system rules

**No UI framework, no component library, no CSS-in-JS.** Plain CSS plus the existing conventions. Every added dependency carries offline packaging and qualification cost.

| Action | Components |
|---|---|
| **Keep as-is** | Icon, StatusBadge, Progress, Tabs, KeyValue, Button/ButtonLink (add the missing pressed style) |
| **Refine** | Panel (containment semantics, §11), Alert (action slot), the state presentations (§14.1), LoadingState (skeleton variant) |
| **Promote to shared** *(subject to §27.1)* | ContextBar, Toolbar (with hint slot), Segmented control, Inspector shell, field grid, history/revision strip, filter-rail section, result row, **EvidencePlayer**, async-state boundary |
| **Remain feature-specific** | Scene canvas geometry rendering, reference-frame transport, scene object navigator, track provenance panels |
| **Remove** | Legacy duplicate styles (alternate button, pill, chip, grid and table classes) — only where provably unreferenced |

**Amended in v2.0 — the Stage 3.5 component programme.** The table above is the v1.0 plan and was executed. The audit of the result adds the following, all under the §27.1 test and ADR-012 Decision 6 (no dependency):

| Action | Components |
|---|---|
| **Add (shared primitives the archetypes compose)** | **Dialog** (consequence confirmation, §15); **Drawer** (focus-managed overlay, §20; the Investigation and Workbench drawers migrate onto it); **Tooltip** (non-essential information, keyboard and pointer, §23 — never a control's only label); **EvidencePlaceholder** (the one missing-thumbnail / unavailable-evidence treatment, §37.1); **FileInput** (styled, labelled, the native control hidden but operable); **ToggleChip** (an `aria-pressed` chip with a filled pressed state, §12 — the evidence-layer toggles use it); **StateRegion** (the §37.1 per-region-kind presentation of the boundary's four states). |
| **Refine** | `Button` disabled state (tokens, not opacity, §12); `Field` invalid state (one hue, §12); `Alert` (max width, trailing action slot used consistently); `LoadingState` (skeleton geometry matches the content it precedes, §38); `EmptyState` (never stretched to fill a region: fixed geometry at the region's top, §4.1); `ContextBar` identity region (`min-width: 0`, ellipsis, full name by tooltip and in the document title); rail collapse control (§5). |
| **Retire** | `PageHeader` (one remaining use, Review's invalid state, moves to the Context Bar); `Tabs` (unused; reinstated under §27.1 when a Record needs it, §29); the undefined `.table--compact` reference; dead selectors (`.rail-layout`, `.field--inline`, `.search-filter-grid`, `.field-help`, `.panel--form`, `.table--dense`, `.page-header`, `.tabs`); the `INHERITED` hover-text-colour allowlist in `styles/tokens.test.ts` is emptied, not extended. |
| **Type** | `IconName` becomes a closed union of the shipped icon names; a surface cannot reference an icon that does not exist. |

Every addition is built from the existing runtime dependencies. If any one of them cannot be, it is not built, and the rule it serves is met another way.

### 27.1 Promotion test (frozen)

Use in two or more places makes a pattern a **candidate** for promotion — nothing more. Promote to shared **only when all four hold**:

1. **Semantics are the same** — the pattern means the same thing in each place, not merely looks the same.
2. **Interaction contract is the same** — the same events, the same states, the same keyboard behaviour.
3. **Accessibility contract is the same** — the same roles, names, relationships and announcements.
4. **Divergence is unlikely** — the two uses are not expected to pull apart as capabilities land.

**Explicit prohibitions:**

- **MUST NOT** abstract merely to remove duplicated JSX or CSS. Duplication is cheaper than the wrong abstraction.
- **Feature-specific behaviour remains local even when visually similar.** Visual similarity is not a promotion argument.
- Promotion is a deliberate act in a named PR, recorded in that PR, not a side effect of a refactor.
- If a promoted component later acquires a boolean or variant that exists solely to serve one caller, that is evidence the promotion was wrong; splitting it back out is the correct remedy.

---

## 28. Scene Editor as reference implementation

The Scene Editor is the reference for **Workbench**, and the source of several product-wide patterns. It is not a template to copy onto Ledger or Record.

**Generalise (UI-2), subject to the §27.1 promotion test:** Context Bar as page identity and state; mode strip with contextual instruction shown only while a mode is armed; stage-grows and inspector-fixed composition; separation of editing from media playback; halo'd evidence layers; navigator and inspector with one shared selection; in-band two-step confirmation for consequential saves; "unavailable is not empty"; read-only mode that **removes** tools rather than greying them; no identifiers in the navigator; a background refetch never overwriting unsaved work; refusal to ship controls for capabilities that do not exist.

**Keep local:** polygon and line drawing state machine; reference-frame pinning; revision chips; the analytics on/off chip; scene-specific validation.

**Correct as foundation work, not as Scene Editor work:** resting zone fill uses the UI accent at the design baseline (§8.3); crossing directions use success/warning hues (§8.3); native `window.confirm` calls remain (§15); the inherited ultra-wide width cap (§25); transport controls below the standard control height (§10).

---

## 29. Future capability compatibility

Scene Analytics slices are numbered 0–7; capability roadmap stages are numbered separately (§1).

| Capability | Where it lands | Archetype | Prerequisite from this specification |
|---|---|---|---|
| Analytics readiness and coverage indicators | **Slice 3, surfaced in Slice 4** | Ledger analytics-state column/text (**not a second row status badge**), Investigation coverage strip, Workbench context chip | `stale` and `partially available` tokens and taxonomy (§8.2, §14); UI-3 for the Ledger indicators; §16's one-badge-per-row rule remains in force |
| Search integration and analytics predicates | **Slice 4** | Investigation | UI-4 in place; committed-filter chips and coverage strip (§17) |
| Evidence overlays and explanation | **Slice 5 — merged in PR #66** | Review and Investigation inspector | One shared Evidence Player; exact-revision analytical overlays/explanation; bounded analytical lanes; decision 7 closed |
| Aggregates, occupancy, heatmap | **Slice 6** | Workbench | Workbench grammar from UI-2; sequential scale and legend; zone colour already separated from accent (§8.3) |
| Hardening, acceptance, qualification | **Slice 7** | — | Visual QA standard (§26) as part of acceptance evidence |
| Visual attributes | Capability stage 2 | Investigation filter section + committed-filter chips; inspector key/value + Evidence Set viewer; Review evidence rail | committed-filter chips (§17), explicit `unknown` state (§14), one-badge-per-row rule (§16) — a matched attribute value may appear on a result row only as plain secondary text, never as an additional badge or chip — bounded observations[] evidence presentation (§4.5/§20) |
| ANPR / OCR | Capability stage 4 | Investigation | none beyond §17 |
| Visual similarity | Capability stage 5 | Investigation | candidate styling and rank numeral (§19) |
| ReID / entity candidates | Capability stage 6 | Ledger to Record, plus canvas link glyph | candidate is not confirmed styling (§19) |
| Event / behaviour analytics | Capability stage 7 | Evidence Player timeline lane and Ledger (Events) | player lane extension points (§18) |
| Entities / Cases | Capability stage 10 | Ledger to Record with tabs | Record archetype and existing Tabs (§4.2) |
| Live cameras / multi-camera | Capability stage 11 | **A sixth "Wall" archetype, not designed now** | the Evidence Player must already be a self-contained component (§18) |

**Failure modes this specification is designed to prevent:** a fourth ad-hoc state vocabulary arriving with Slice 4 readiness UI; Slice 6 heatmap colours layered on a zone colour that equals the UI accent; a second player built for Slice 5 or for events.

---

## 30. Explicit anti-patterns

MAVI MUST NOT drift into:

- Dashboard-card proliferation; panels inside panels inside pages.
- Standing explanatory prose on every page.
- Implementation detail as operator copy (cursor strategy, page size, snapshot semantics).
- Duplicate state badges describing one thing in one row.
- Identifiers (GUIDs) in table cells.
- Native media controls beneath evidence overlays; a second scrub bar.
- `title` as a control's only label; tooltips carrying required information.
- Status colour used for evidence, or evidence colour used for status.
- One-decimal percentages in dense lists.
- Stat tiles that restate the table directly beneath them.
- Modal dialogs for routine editing; `window.confirm`.
- Workflows that depend on a transient toast.
- Decorative animation; animated route changes.
- Page-specific CSS systems, page-specific themes, or per-screen density.
- Legacy style aliases surviving a redesign.
- Excessive rounding, gradients, glow, HUD or tactical styling, "AI-looking" effects.
- Artificially capping spatial or investigative workspaces on wide displays.
- Abstracting shared components on visual similarity alone (§27.1).
- Inflating dense desktop controls to mobile touch sizes (§10.1).

---

## 31. Deferred capabilities

Deliberately deferred until a concrete operator need is recorded. **Deferral means the architecture must not preclude it and no effort is spent on it.**

- Full light palette; System theme following.
- User-selectable density.
- Resizable split panes (and explicitly: they MUST NOT be used to solve a width constraint, §4.3.1).
- Configurable or saveable workspace layouts.
- Command palette.
- Phone or mobile analyst experience. **Clarified in v2.0:** §25 Tier C defines how the product *degrades* on a narrow display so that nothing is broken or unreachable; it does not make a phone an operational workstation, and no workflow is accepted there. Designing a mobile analyst experience remains deferred and would be its own decision.
- Global notification centre.
- Decorative route animation.
- **Wall archetype** for live multi-camera (capability stage 11) — anticipated, not designed now.

---

## 32. Open design decisions

Only these remain open. A struck-through row is closed and kept for the record;
a decision that is only partly settled stays un-struck until every part of it is.

| # | Decision | Closed in | Notes |
|---|---|---|---|
| ~~**1**~~ | ~~UI font~~ — **closed in UI-1: curated system stack (option A)** | Closed | §9. Bundling buys identical rendering in CI, but §26 forbids committing screenshots, so there are no pixel baselines to keep stable and the determinism was worth nothing against a real licence, catalogue and packaging cost. `--font-ui` now leads with Segoe UI for the Windows target and names only families that genuinely exist on their platform; "Inter", which the product never shipped, is gone. |
| **2** | **Exact evidence and spatial hues** — **partially resolved in UI-1** | **Rendered roles frozen in UI-1; the three below stay open** | §8.3. **Frozen now, and no longer open:** zone `#fb923c`, trip line `#22d3ee`, A→B `#f0abfc`, B→A `#e879f9`, bounding box `#a78bfa`, trajectory `#2dd4bf`. Chosen by constrained optimisation for mutual separation under normal vision and protan/deuteran/tritan simulation, then validated over the §26 footage conditions; minimum separation ΔE 9.0 on the Scene Editor canvas and ΔE 14.3 on the Review overlay. **Still open:** sub-decisions 2a–2c below. §8.3 requires a hue to be validated against real evidence, and those three roles have no surface that draws any; inventing values for them now would be a decision made against nothing. |
| ~~**2a**~~ | ~~Event/crossing marker hue~~ — **closed in Scene Analytics Slice 5: `--evidence-crossing` = `#fde047`** | Closed | §8.3. Chosen by measurement over the first surface that draws an analytical instant, by the UI-1 method: CIEDE2000 in CIE L\*a\*b\* after Viénot dichromat simulation, against every frozen evidence role. Minimum separation **ΔE00 7.1** across normal, protan, deutan and tritan vision — the frozen UI-1 roles come as close as ΔE00 0.4 to one another — and 15.9:1 on the `--evidence-matte` halo. Candidates measured and rejected: rose `#fb7185` (6.3), lime `#a3e635` (6.8), green `#4ade80` (2.3), yellow `#facc15` (1.9), amber `#fbbf24` (1.4, indistinguishable from the zone role under deuteranopia). It is an evidence role in its own namespace, never a borrowed status colour, and the crossing glyph is a **diamond** with a dashed outline for B→A, so hue is not the only cue. Validated over the §26 bright, dark, saturated, low-contrast, letterboxed and pillarboxed conditions at all four acceptance widths. |
| **2b** | Similarity / ReID candidate hue | **Capability stage 5** (Visual Similarity / Find Similar) | §8.3. Own hue plus a rank numeral, never a success hue. Closed when the similarity UI exists. |
| **2c** | Heatmap scale | **CLOSED — Scene Analytics Slice 6** | §8.3. **Frozen:** `--heat-0` `#111827`, `--heat-1` `#27374d`, `--heat-2` `#44566e`, `--heat-3` `#7b8ea6`, `--heat-4` `#dde5ee`, with `--heat-scrim` `rgb(0 0 0 / 50%)`. Method as UI-1 and decision 2a: linear-light sRGB, Viénot dichromat simulation, CIEDE2000 in CIE L\*a\*b\*. A sequential scale has to cross the whole luminance range, so it passes near every hue on the way: viridis reaches 2.0 of `--evidence-crossing`, magma 1.4 of `--geo-zone` and cividis 1.4 of `--evidence-crossing`, against the 7.1 floor that closed 2a. Keeping chroma low instead reaches **7.8** from the nearest frozen role under any vision, with luminance rising monotonically 0.009 → 0.776 and adjacent steps 9.8 apart. Not a red-to-green scale. The scrim is part of the decision: without it the top of any light-ended scale measures ~1.02:1 on bright footage; at 50% it clears 3:1 against every §26 reference frame (bright 3.73, dark 15.49, saturated 10.82, low-contrast 9.09). Re-derived from the tokens in `styles/contrast.test.ts`. |
| ~~**3**~~ | ~~Investigation in-place-inspector threshold (1500px default)~~ — **closed in UI-4: amended to 1600px** | Closed | §4.4. Measured at 1440, 1500, 1550, 1599, 1600 and 1700. Three columns at their minimums need 1284px of working width; 1500 leaves 1244 and clipped the inspector's own controls off the right edge of a contained column, with no scrollbar to reach them. 1600 leaves 1344. The same measurement gives the in-place inspector a 440px floor — the width its drawer already uses — because a layout that grants the results their 900px cap first leaves the inspector 60px at 1500 and 160px at 1600. |
| ~~**4**~~ | ~~Ultra-wide Investigation split ratio (results cap versus inspector growth)~~ — **closed in UI-4: unchanged as specified** | Closed | §4.4. Results capped at approximately 900px, surplus to the inspector: measured 900/480 at 1920 and 900/1120 at 2560. The cap holds with nothing selected too, which the default did not say and UI-4 settles: a scan column is a scan column whether or not there is an inspector beside it. |
| ~~**5**~~ | ~~Ledger sorting scope — which columns, client or server~~ — **closed in UI-3: client-side, per-Ledger, on the columns an operator actually re-orders by** | Closed | §16. **Cameras** sorts on Code (default, ascending), Name and State; Timezone and Actions do not sort. **Videos** sorts on File, Camera, Recorded (default, descending — the order the page already had) and Duration; Status does not, because it already has a filter and is operationally mutable, and Actions is not data. **Processing Queue** offers no operator-selectable sorting at all: its order *is* the operational statement — active, then failed, then completed, each bucket keeping the recording-start order it already had — and letting the operator re-order it would discard that meaning. Sorting stays client-side over inventories the API already returns whole: no endpoint changes, and no new URL parameter, so §17's "URL is the state of record" gains nothing to record. A sort is a view preference, not a shareable scope. |
| **6** | Whether Overview survives as a distinct surface once an Events Ledger exists | After Events lands | §4.1.1. |
| ~~**7**~~ | ~~Timeline lane presentation for multiple analytical interval types~~ — **closed in Scene Analytics Slice 5: bounded stacked analytical lanes** | Closed | §18. Three fixed families on the one timeline — subject, zone/dwell, stationary — each at its own fixed vertical position, which is itself a non-colour cue. The two analytical families are **hatched, not newly coloured**: no hue was invented for dwell, and they differ by hatch orientation as well as by position. A single undifferentiated lane was rejected because zone occupancy and stationary overlap in time and would have been ambiguous; one row per zone was rejected because the timeline's height would grow with the scene. The zone family packs concurrent visits into at most **3** sub-rows by a deterministic rule (start, then end, then stable evidence id; endpoint-touching intervals may share a row, positive-duration overlaps may not); a fourth concurrent visit goes to one fixed overflow rail, which shows a **density profile**: a sweep over the overflowed visits' own boundaries yields disjoint bands, each stating how many are genuinely in progress together across it, so a band's count can never describe an overlap that did not happen — transitive grouping did, which is why it was replaced. An overflowed visit has no position on the rail and is not named there; its one element is its turn in a **bounded navigator** below the timeline, which exposes one member at a time — its position in the set, its own label and its own exact offsets — through a fixed three controls (the disclosure, Previous and Next) whether there are four members or a hundred. Stepping names the member, draws a visit at its exact persisted offsets and seeks to its exact persisted millisecond. There is therefore one semantic evidence list, no piece of evidence in it twice, and neither the rail's height nor the number of controls grows with the evidence; the navigator's transient selection is held against the subject that made it, so it cannot survive into another Track's evidence. Previous and Next are ordinary buttons, so Enter and Space are theirs by native semantics while the arrows, J, L, Home and End remain the player's (section 22). Height is therefore bounded by concurrency, never by the number of zones, visits or crossings: a hundred overlapping visits render exactly as tall as four. Crossings and real boundary entries and exits are **markers, not lanes**, and each is a real button that seeks to its own persisted millisecond. Marker separation is derived from the rail's **measured** width, not from a ratio fitted to one host, so the narrow Investigation inspector staggers where wide Review does not; a marker with no clear row is never placed where it would collide but joins the same bounded navigator, keeping its own exact destination. Only markers sharing one exact millisecond share a control, and that control names every fact it carries. |

---

## 33. UI implementation roadmap (Historical — programme complete)

**Status (v2.0):** UI-1 → UI-5 are all merged and the Scene Analytics gate they protected has long since lifted. This section is kept as the record of that programme and of the decisions closed inside it; it is no longer a plan. The Stage 3.5 programme that follows it is planned in `docs/superpowers/plans/2026-10-07-stage3-5-ui-ux-professionalisation.md` and summarised in §39.

Five PRs. Each merges independently and leaves the product shippable.

### 33.1 Programme sequence and the Scene Analytics gate (frozen)

The implementation programme is strictly sequential:

**UI-1 → UI-2 → UI-3 → UI-4 → UI-5**

1. **UI-1 Design Foundation** merges.
2. **UI-2 Shell + Workspace Grammar** merges.
3. **After UI-2 is merged and post-merge `main` is green, the design architecture is considered established.**
4. **Only then may Scene Analytics Slice 3 backend/domain work begin or proceed.** This is an intentional pause after Slice 2. UI-1 alone does not lift it.
5. After that point, backend/domain analytics work **MAY proceed in parallel** with the later UI migration PRs (UI-3, UI-4, UI-5) where it is safe to do so — that is, where it introduces no frontend surface.
6. **New user-facing analytics UI MUST land only on the relevant established workspace grammar.**
7. Specifically:
   - **UI-3** in place before readiness/coverage indicators are added to operational Ledgers.
   - **UI-4** in place before **Slice 4** Search/readiness UI is added.
   - **UI-5** in place before **Slice 5** evidence-overlay/explanation UI is added.
   - **Slice 6** heatmap UI uses the Workbench grammar established by **UI-2**.
   - **Slice 7** acceptance evidence includes the §26 visual QA standard.

A backend slice that would normally ship a UI surface before its gating UI PR merges MUST either defer that surface or ship it behind the archetype it will ultimately use.

### 33.2 UI-1 — Design Foundation

- **Status.** Implemented; see the UI-1 PR. Open decision 1 (font) is **closed** there. Open decision 2 is **partially resolved**: the six rendered evidence roles are frozen, and sub-decisions 2a–2c remain open against the slices that first draw them (§32).
- **Objective.** Establish the semantic design foundation and correct systemic defects, without recomposing pages.
- **Scope.** Primitive and semantic token architecture with narrowly scoped component tokens (§7); semantic UI state tokens including `stale` and `unavailable`; separate evidence/spatial token namespace with roles frozen and hues selected by visual validation; focus-ring and contrast corrections (the missing `--focus` reference, text on accent); `page--full` and ultra-wide structural correction; shared time, duration and confidence formatting; the **async-state boundary** (§14.1); Alert, Empty and Loading refinements; **font decision resolved and implemented**; visual QA harness and process formalised (§26); removal of clearly obsolete duplicate styles where provably safe.
- **Exclusions.** No page recomposition; no archetype layout classes; no light palette; no player work; no navigation change.
- **Prerequisites.** None.
- **Acceptance.** All token references resolve; no colour, radius, duration or spacing literals in feature CSS; every contrast obligation in §23 met on the surface where the element appears; the `page--full` structural defect is corrected so that a surface declaring full width actually renders full width at approximately 2560 — verified on Workbench and Investigation, the only two surfaces declaring it at the baseline, with no surface widened that did not already declare it; §25's remaining ultra-wide obligations land with the migration that gives each surface its archetype (Ledgers at UI-3, Review at UI-5); an async-state boundary exists and no call site can render empty while its request failed; full test suite, typecheck, build and `verify_repo` green; §26 visual QA pass across all four viewports; if a font is bundled, licence and offline catalogue entries land in the same PR.
- **Risks.** Broad CSS diff — mitigated by the existing test suite plus a full visual pass. Font bundling carries offline packaging cost, hence the narrow decision.
- **Relation to Scene Analytics.** Does **not** lift the Slice 3 gate.

### 33.3 UI-2 — Shell + Workspace Grammar

- **Status.** **Merged**, with post-merge `main` green. That lifted the Scene Analytics Slice 3 gate (§33.1), and Slice 3 has since been completed and merged. Open decisions 3 and 4 are untouched and remain UI-4's (§32); the Review archetype layout class exists and is composed at UI-5.
- **Objective.** Establish the product's common grammar.
- **Scope.** Shared ContextBar, Toolbar, Segmented control and Inspector shell (each subject to §27.1); archetype layout classes for all five archetypes including the Overview exception (§4.1.1); topbar to Context Bar relationship; navigation grouping architecture; scroll-ownership rules implemented per §4; responsive and ultra-wide behaviour per §25; **Scene Editor migrated onto the shared primitives with no behavioural change**.
- **Exclusions.** No Ledger or table redesign; no Search rework; no player work; no new destinations.
- **Prerequisites.** UI-1.
- **Acceptance.** Each archetype has exactly one layout implementation; Workbench fits 1366×768 without page scroll with the stage at 65% or more of working width; the Review archetype layout class exists and composes the player and primary-summary regions per §4.5.1 — the Review page itself is migrated onto it and that composition verified at UI-5 (§33.6), because UI-2 excludes player work; Scene Editor behaviour and its test suite unchanged; §26 visual QA pass.
- **Risks.** Scene Editor regression — covered by its existing tests plus visual QA.
- **Relation to Scene Analytics.** **Merging UI-2 with green post-merge `main` lifts the Slice 3 gate** (§33.1).

### 33.4 UI-3 — Existing Operational Surfaces

- **Status.** **Merged** (PR #60), with post-merge `main` green. UI-1 and UI-2 are merged before it; open
  decision 5, the Ledger sorting scope, closed here (§32). The six operational surfaces it covers are frozen:
  a later increment changes them only where its own scope requires it.
- **Objective.** Bring the operational pages onto the grammar.
- **Scope.** Overview, Cameras, Video Import, Videos, Processing, Processing Queue. Single-line rows and data density; table consistency; state taxonomy applied; filters moved to toolbars; form and editing consistency (inline validation, dirty state, camera creation without a permanent second card); removal of redundant card and panel hierarchy.
- **Exclusions.** No new data or endpoints; **no analytics readiness or coverage indicators** (they follow, on this grammar); no player work.
- **Prerequisites.** UI-2.
- **Acceptance.** Every page is a recognisable Ledger, Ledger-summary or Record; every §14 state reachable in these pages is correctly distinguished; no two-badge rows; no GUIDs in cells; §26 visual QA pass including long-name and dense-data states.
- **Risks.** Low.
- **Relation to Scene Analytics.** **Must be in place before readiness/coverage indicators are added to operational Ledgers.**

### 33.5 UI-4 — Investigation Workspace

- **Status.** **Merged** (PR #61, merge commit `9dbd74d7`). The Investigation migration is complete:
  Search is on `InvestigationLayout`, decisions 3 and 4 are closed, the in-place inspector threshold is
  **1600px**, and the ultra-wide split is **confirmed unchanged**. Post-merge Task 17 Acceptance #1010 and Quality Gate #1866 are both green on exact `main`, so Scene Analytics Slice 4 is unblocked.
- **Objective.** Migrate Search onto the Investigation archetype.
- **Scope.** Filter rail rebuilt as scrolling field sections; committed-filter chips at the results head; results hierarchy and header copy; inspector behaviour including the drawer below threshold; ultra-wide utilisation; keyboard behaviour preserved and extended; URL-state semantics preserved exactly. Closes open decisions 3 and 4 (§32).
- **Exclusions.** **No Slice 4 analytics predicates**; no coverage strip content; no saved searches; no natural-language query.
- **Prerequisites.** UI-2.
- **Acceptance.** Committed filters reproducible from the URL, unchanged; no overlapping controls at 1366 or 1440; the inspector threshold validated and either confirmed or amended in §4.4; keyboard navigation unchanged or improved; §26 visual QA pass.
- **Risks.** Medium — URL, keyboard and pagination interplay is subtle; existing tests must be preserved.
- **Relation to Scene Analytics.** **Must be in place before Slice 4 Search/readiness UI is added.** Slice 4's Investigation Analytics filter group, committed analytic chips, coverage strip and inspector analytics summary, and its Processing Ledger analytics column and Record readiness panel landed on this grammar and are merged on `main` through `b505a97`, with no change to the archetypes, the state taxonomy or the one-badge-per-row rule.

### 33.6 UI-5 — Evidence Player + Review

- **Objective.** One reusable evidence-player foundation.
- **Scope.** Custom transport; one timeline with lane extension points; overlay and layer controls; keyboard playback; poster and reference behaviour; uncertainty rendering; Review migrated to the Review archetype including the sticky-player rule (§4.5.1); the Investigation inspector uses the same component.
- **Exclusions.** **No analytical lanes for data that does not yet exist**; no Slice 5 overlay content; no event UI; no live or multi-camera work.
- **Prerequisites.** **UI-4.** UI-5 migrates the Investigation inspector onto the Evidence Player, so the Investigation workspace must already be on its archetype.
- **Acceptance.** Exactly one player implementation in the codebase; no native controls beneath overlays; one timeline; overlays correct under letterbox and pillarbox; **at 1366×768 the migrated Review page shows the player and the primary evidence summary in the initial viewport** (§4.5.1, §25) — the check deferred here from UI-2; §26 visual QA against bright, dark, saturated, low-contrast and letterboxed footage; existing player tests preserved or replaced with equivalents.
- **Risks.** Medium-high — media element lifecycle. The existing animation-frame and seek logic is tested and should be reused rather than rewritten.
- **Relation to Scene Analytics.** **Must be in place before Slice 5 evidence-overlay/explanation UI is added.** Slice 5 draws into this player's lanes.
- **Status.** **Merged and independently reviewed** in PR #64; merge commit `273718c`. The player is `shared/evidence/EvidencePlayer`, composed for Track evidence by `features/video-review/TrackEvidence` and mounted by both Review and the Investigation inspector; the media controller is `useEvidenceTransport`. Native controls are gone and a source-level test keeps them gone. The §22 grammar is one contract across the whole player: nothing inside it, the timeline included, redefines a key the grammar owns, and coarse timeline seeking is by pointer. Each timeline mark is one element that is both the visual evidence and the named list item, so there is no `aria-hidden` bar shadowed by a hidden description list; an interval in a lane that is not drawn keeps its place in the accessibility tree, since "named but not drawn" has to mean both halves. The spatial overlay's §23 twin **is the operator's own layer control**, not a second surface beside it: the raw SVG stage stays hidden from assistive technology, and each layer's objects, their normalised source-frame coordinates and their state are carried as the accessible description of the one visible row that layer already has — one layer object, one control, one semantic object — each described object a list item rather than one flattened string, bounded rather than enumerated where the evidence is large. The layer type is a discriminated union, so a layer that draws spatial content cannot be declared without its accessible equivalent. Layer *preference* state (enabled, hidden by the operator, unavailable) and evidence *applicability* at the playhead are separate facts composed into one sentence, so the player can never announce a layer as shown while the evidence says it is not drawn. Review's player takes the surplus on a wide display: the rail stops at its readable maximum and every further pixel is the player's, while the 65% floor holds at every width. The seam is `EvidenceTimelineMarker` and `EvidenceTimelineInterval`. **Scene Analytics Slice 5 / PR #66 subsequently closed decision 7 with bounded stacked analytical lanes and decision 2a with `--evidence-crossing = #fde047`; Scene Analytics Slice 6 closed decision 2c with the low-chroma heatmap ramp and its scrim.** Decision 2b (similarity) remains open until its first rendered capability surface.
- **Declared divergence (§34 item 13).** §18.5 asks for the representative frame as the poster. The only persisted image is the representative *crop* — the worker stores the bounding box cut out of the frame — and a poster fills the canvas, so that crop would be presented as the source frame with full-frame overlay coordinates drawn over it, and would persist through a slow or failed load. UI-5 therefore ships **no poster** and shows the matte. The rule closes when a full-frame artifact exists; the player still accepts a poster and documents that it must be one.

---

## 34. Definition of UI/UX conformance

A frontend PR claims conformance by satisfying all of:

1. **Archetype.** Every screen touched is an instance of a §4 archetype; no bespoke layout is introduced.
2. **Tokens.** No colour, radius, duration or spacing literal is introduced. Components reference semantic tokens (and justified component tokens), never primitives.
3. **Colour separation.** No UI status colour used for evidence; no evidence colour used for status. Accent appears only as primary action or selection (the §8.3 selected-geometry crossover excepted).
4. **State taxonomy.** Every §14 state reachable in the changed surfaces is correctly distinguished, through the async-state boundary (§14.1). No surface can render empty while its request failed.
5. **Interaction states.** Hover, focus, selected, pressed, dragging, disabled, invalid, saving, saved and processing follow §12. Focus is visible on the surface the control appears on.
6. **Accessibility.** Every §23 MUST is satisfied; contrast verified on the actual surface with the decorative/meaningful distinction applied correctly; effective targets at least 24×24 or a documented exception; spatial content has its accessible twin.
7. **Responsive.** Behaves per §25 at 1366, 1440, 1920 and approximately 2560; Workbench fits 1366 without page scroll; no horizontal page overflow; no overlapping controls.
8. **Visual QA.** A §26 pass has been performed and its viewports, states and findings are reported in the PR.
9. **Formatting.** Time, duration, confidence and numeric presentation follow §24 via shared formatters.
10. **Component boundary.** Any promotion to shared satisfies the §27.1 test and is recorded in the PR.
11. **Dependencies.** No new UI framework, component library or runtime dependency; any new asset is offline-packaged and catalogued.
12. **No prohibited patterns.** Nothing from §30 is introduced.
13. **Divergence declared.** Any necessary departure is stated explicitly in the PR with rationale and a proposed amendment.
14. **Craftsmanship (Amended in v2.0).** Every §36 standard holds on every surface touched: alignment, rhythm, metrics, capitalisation, truncation, numeric alignment, hit areas, cursors, focus and state treatments, scrollbars, sticky regions, transitions and skeleton geometry. A single-page cosmetic patch that leaves the same defect on a sibling surface is not conformance; the fix lands in the token, component or archetype that both share.
15. **Edge states (Amended in v2.0).** Every §37 state the surface can reach is rendered through the boundary and the per-region presentation, and has been inspected in the §26 sweep: populated, dense, long names, empty, filtered-empty, loading, unavailable, failed, stale, partial, missing evidence, large evidence sets, disabled, and keyboard-only.
16. **Support tiers (Amended in v2.0).** The surface behaves per §25 at every tier anchor applicable to it, with Tier B and C behaviour designed, not inherited from flex wrapping, and the §26 sweep run at those anchors.
17. **Performance as UX (Amended in v2.0).** No layout shift between a loading presentation and the content it precedes; no spinner where a skeleton or nothing is correct; local feedback is immediate; refresh preserves layout; the §38 measurements are recorded where the surface is one the harness measures.

A PR that cannot honestly assert items 1–17 is not conformant, regardless of test status — with one bounded, dated exception: during the Stage 3.5 programme, §34.2 states which items a slice must assert and which may remain open against a named later slice. **A frontend surface is not complete merely because its functional tests pass; it is complete when it meets the archetype, design-system, responsive, accessibility, performance and craftsmanship standards of this specification and has been visually verified in the real application at the supported widths and edge states.**

### 34.1 Transitional conformance during UI-1 → UI-5 (Historical — closed)

**Closed in v2.0.** UI-5 merged, and the clause expired by its own last row. No surface may rely on it: a legacy pattern the Stage 3.5 audit found is a finding in `docs/reviews/2026-10-07-stage3-5-ui-ux-professionalisation-acceptance.md`, not a tolerated deviation. The text is kept as the record of how migration was governed.

Migration is incremental by design. The following governed the programme period and expired when UI-5 merged.

| Rule | Level |
|---|---|
| **New or materially reworked surfaces MUST conform** to this specification. | MUST |
| **Existing untouched legacy surfaces MAY remain temporarily non-conformant** until their scheduled migration PR. | MAY |
| **A migration PR is NOT non-conformant merely because out-of-scope legacy surfaces remain non-conformant.** Conformance is assessed against what the PR creates or materially reworks. | Frozen |
| A PR **MUST NOT introduce a new deviation**, and **MUST NOT extend or copy an existing legacy pattern** into new code. Touching a legacy surface incidentally does not oblige migrating it, but does oblige not making it worse. | MUST |
| A PR **SHOULD** name the legacy surfaces it deliberately left alone and the UI PR that owns them. | SHOULD |
| **Once UI-5 is merged, full frontend conformance becomes the expected baseline** and this transitional clause no longer applies. | Frozen |

### 34.2 Stage 3.5 programme conformance (Added in v2.0, frozen; expires at S7 closure)

Stage 3.5 deliberately migrates the existing frontend to v2.0 in bounded slices (§39; plan §15). A rule that every intervening PR must already meet all seventeen §34 items would be either false or unmeetable, and §34.1 is not reopened to cover it. This subsection is the Stage 3.5 rule, and it is mechanical.

**Governing principle.** During S1–S6 a frontend PR MUST satisfy every v2.0 requirement whose enabling slice has already merged, MUST NOT introduce or extend any deviation, and MUST satisfy the acceptance-register rows its slice owns. Full §34 items 1–17 on every operator surface become mandatory at S7 closure, which has no migration exemption.

**Progression — when each obligation becomes blocking.**

| Slice | What the PR must assert | What may remain open (only as named register findings against a later slice) |
|---|---|---|
| **S1 — foundation** | §34 items 1–13 on everything it touches (item 4 through the boundary; item 6 limited to the §23 obligations frozen before v2.0 plus the §5, §15 and §20 obligations S1 implements; item 7 at the Tier A anchors; item 8 reported in the PR); the S1-owned rules in full: tokens (§7, §8), Ledger containment (§4.1), one primary (§8.1, §16), boundary everywhere with §37.1 presentation and placement (§14.1), IA map, skip link, landmarks and rail control (§5), Dialog, Drawer and Tooltip contracts (§15, §20, §27), invalid and disabled states (§12), row pitch and truncation (§16), the §27 retirements. Items 14, 15 and 17 for every *newly created or rebuilt* component. | Surface-level finish (items 14–15, 17 on a surface as a whole) until that surface's S3/S4 slice; item 16 (tiers B/C) until S5; S6's programme-wide obligations. |
| **S2 — harness v2** | As S1 for anything it touches; everything S1 made blocking is now asserted by the harness as `blocking` manifest entries; every later-slice rule, and every assertion evaluated at a Tier B or C anchor, is present as `measured/pending`, reported, never failing the build; P1 baseline measured and recorded. | As S1. |
| **S3a–S3e — reference surfaces** | On the reference surface: items 1–15 and 17 — every currently implemented v2.0 requirement and the complete Tier A standard, including §36 and §37 for that surface, every §37.1 state inspected at every Tier A anchor — with item 6 excluding the §23 obligations owned by T3 (200% zoom) and X1–X4, and item 15 excluding the keyboard-only journeys owned by X2. S3e additionally flips the rendered-stickiness manifest entry to `blocking` (R6). | Item 16 (Tier B/C) and T3 until S5; X1–X4 until S6; findings on *other* surfaces until S4. |
| **S4 — remaining surfaces** | The S3 standard, with the same item 6 and 15 carve-outs, on every remaining operator route; after S4 no surface is on a pre-v2.0 pattern. | Item 16 and T3 until S5; X1–X4 until S6. |
| **S5 — support tiers** | Item 16 on every applicable surface; the Tier B and C manifest entries become `blocking`. | S6 obligations. |
| **S6 — accessibility and performance hardening** | The remaining programme-wide §23 and §38 obligations (X1–X4), including the budgets set from the S2 baseline; their manifest entries become `blocking`. | Nothing by design; any residue is a P2 single-surface or P3 finding carried under C5 with an owner and declared under §34 item 13 — never a P0/P1 and never a §23 MUST. |
| **S7 — closure** | Items 1–17 on every current operator surface; every manifest entry `blocking` or `not-applicable`; no Stage 3.5 exception of any kind remains. | Nothing. |

**Distinctions that keep this from being a licence.**

- This is not permission for arbitrary legacy divergence. **Only a finding recorded in the Stage 3.5 register and assigned to a future slice may remain open**, and only until that slice.
- A slice MUST NOT make a deferred defect worse, and MUST NOT copy a known defect to another surface or into new code.
- A newly created or rebuilt component conforms to every rule already frozen for it, whatever slice it lands in.
- A P0 or P1 defect is not carried past the earliest slice capable of fixing it; if a slice can fix one, it does.
- A PR states, in its description, which §34 items it asserts, which it leaves open and against which register row; a PR that cannot make that statement truthfully is not conformant.
- S7 has no exemption. When C5 is PASS this subsection expires and §34 applies unqualified.

---

## 35. Final design baseline

MAVI is a **dark-first, evidence-first, offline professional Visual Intelligence workstation**, built from **five frozen workspace archetypes** — Ledger (with the Overview Ledger-summary exception), Record, Workbench, Investigation, Review — on a **primitive and semantic design-token architecture with narrowly scoped component tokens only where semantically justified**, in which **UI colour and evidence colour are permanently separate namespaces**, with a **single unambiguous operational-state vocabulary served by a shared async-state boundary**, **URL-backed investigations**, **one reusable Evidence Player**, and **accessibility and browser-based visual QA as architecture rather than afterthought**.

**Frozen:** the five archetypes and their scroll ownership; Workbench fitting 1366×768 with a stage at 65% or more of working width; Review's page-scroll with player and primary summary above the fold; the Overview centring exception; the shell and Context Bar; the token architecture; colour role separation; the state taxonomy and the async-state boundary; density, target-size and containment rules; the interaction and motion grammar; the evidence and spatial visual hierarchy; responsive and ultra-wide acceptance at 1366, 1440, 1920 and approximately 2560; the visual QA standard; the §27.1 promotion test; and the sequential UI-1 → UI-2 → UI-3 → UI-4 → UI-5 programme with **Scene Analytics Slice 3 gated on UI-2 merging with green post-merge `main`**.

**Deferred, architecturally permitted:** light palette and System theme; selectable density; resizable panes; configurable layouts; command palette; mobile; notification centre; the Wall archetype for live multi-camera.

**Open, closed in the named PR:** the UI font decision (UI-1); the exact evidence hues (UI-1 visual validation); the Investigation inspector threshold and ultra-wide split (**closed in UI-4**: threshold amended to 1600px, split unchanged); the Ledger sorting scope (closed in UI-3); Overview's long-term fate (after Events); analytical timeline lane presentation (Slice 5).

**Transitional (Historical):** §34.1 governed conformance until UI-5 merged. It is closed. **Staged (current, dated):** §34.2 governs the Stage 3.5 slices S1–S6 and expires at S7 closure, after which full frontend conformance is the unqualified baseline.

**Added in v2.0 (frozen):** the quality direction of §2; the three support tiers and the range-based responsive rules of §25; the Ledger containment and attention-first Overview rules of §4.1; the one-primary-per-surface rule of §8.1; the boundary-everywhere and placement rules of §14.1; the IA map, skip link and landmarks of §5; the Dialog, Drawer, Tooltip, EvidencePlaceholder, FileInput, ToggleChip and StateRegion primitives of §27; the WCAG 2.2 AA target and harness-asserted accessibility obligations of §23; the deterministic-assertion visual-regression strategy of §26; the craftsmanship standard of §36; the edge-state and progressive-disclosure catalogue of §37; performance as UX in §38; and the conformance definition of §34 under which a surface is not complete merely because its functional tests pass, with the staged-conformance rule of §34.2 for the programme that implements it.

Everything else is settled. Future work implements this specification or amends it explicitly.

---

## 36. Product craftsmanship standard (Added in v2.0, frozen)

Architecture decides what goes where. Craftsmanship decides whether it is right when it gets there. The audit found no surface that broke the architecture and no surface that would survive this section unchanged, which is why it exists. These standards are **component and token obligations**: when a surface fails one, the correction lands in the primitive the surface uses, so that every sibling surface is corrected by the same change. A page-local fix for a standard in this section is a §34 item 14 failure.

### 36.1 Geometry and rhythm

| Standard | Rule |
|---|---|
| **Alignment** | Edges that are meant to align, align to the pixel. Label and value columns in a key/value grid share one baseline grid; the Context Bar's identity, badges and actions share one vertical centre; an icon beside text is optically centred on the text's x-height, not geometrically centred on the line box. A 1–2px misalignment is a defect, not a nit. |
| **Spacing rhythm** | Every gap is a step on the 4px scale and the same gap means the same relationship everywhere: 4 within a control, 8 between related controls, 12 inside an inspector, 16 inside a form or between regions, 24 between sections (the §10 values; the 24 section step is a default to be confirmed by measurement in S1). No ad-hoc values; no `calc()` that produces one. |
| **Control metrics** | 32px default, 26px in-row, 44px Context Bar; inputs and buttons in one row share a height and a baseline. A native control (file input, date input, select) is styled to the same metrics or replaced by the §27 primitive; a native control at native height beside a 32px button is a defect. |
| **Row and line heights** | Table rows 36–40px single-line (measured); key/value rows 22–24px (measured ~23px on Processing detail); list rows with a thumbnail are the thumbnail's height plus one gutter step and no more. |
| **Borders and radii** | One border width (1px) for containment and controls; 2px only for focus and the selected inset bar. Radii 4px controls, 6px containers, pill for badges only. Nested radii are concentric (outer radius = inner radius + padding) or equal — a default rule, to be confirmed on the reference surfaces in S3; never a 6px container with 6px controls flush to its edge. |
| **Surfaces** | Four surface levels, used in order: a raised surface sits on a base surface, never on another raised surface; an input is inset on whichever surface holds it. A region that is not a scroll boundary or an editable region is not bordered (§11) and is not filled. |
| **Content widths** | Reading text wraps at a readable measure (`--measure`; the value is set in S1, ~68ch as the starting default); a key/value grid's value column, a form field and an alert have a readable maximum; a table, a canvas and a player do not. |

### 36.2 Text

| Standard | Rule |
|---|---|
| **Type scale** | The six-step scale (11/12/13/14/16/20) and nothing between; 11px only for section labels and tertiary metadata, never for a value. Weight carries hierarchy before size: a 13px semibold label and a 13px regular value are the common pair. |
| **Capitalisation** | Sentence case for every label, button, heading, message and menu item. Small-caps section labels (`SCENE OBJECTS`, `THRESHOLDS`) are rendered by `text-transform`, authored in sentence case. Product nouns (Track, Camera, Zone, Trip line, Scene, Revision) are capitalised as nouns; status words are not. No Title Case. |
| **Truncation** | One line per cell; `text-overflow: ellipsis` at the cell's own `max-width`; the full value is available by keyboard and pointer (§16) and in the surface's detail. Identifiers truncate in the middle when their suffix is the distinguishing part. Nothing wraps a row to two lines; nothing is clipped without an ellipsis. |
| **Numerals** | Tabular figures everywhere a number can change or be compared; numeric columns right-aligned; thousands separators; units after a non-breaking space; `—` for not applicable, never `0`, `-`, `n/a` or blank. |
| **Timestamps** | §24 unchanged: compact in lists (`14 Sept, 08:35`), full with timezone in inspectors; the timezone is stated once per surface in the Context Bar. A time never wraps. |
| **Confidence** | §24 unchanged: integer percent in lists, one decimal in inspectors. The mean and the maximum are labelled when both are shown. |
| **Copy** | Operator language, consequence-first, no marketing register (`Searching…`, not `Searching visual intelligence…`), no standing explanatory prose (§30), one vocabulary per state (§37.1), and a fact stated once per surface. |

### 36.3 Interaction finish

| Standard | Rule |
|---|---|
| **Hit areas** | §10.1 unchanged: ≥24×24 effective; icon-only controls at 32×32 in chrome and 26×26 in rows; adjacent targets separated by ≥4px or by a border. |
| **Cursors** | `pointer` on links and buttons; `default` on static text including badges; `grab`/`grabbing` on draggables; `not-allowed` on disabled; `text` only on editable text; `crosshair` only in a drawing mode. A pointer cursor on something that does nothing is a defect. |
| **Focus** | §12 unchanged: a 2px ring with a dark inner offset on every control on every surface; focus follows the §20 drawer and §15 dialog contracts; focus order equals reading order. |
| **Hover / pressed / selected / disabled** | §12 as amended: hover is surface, never text colour; pressed is `aria-pressed` plus a filled state; selected is accent-soft plus the inset bar; disabled is tokens, never opacity. A control has every state it can enter, and no control has a state it cannot. |
| **Tooltips** | The §27 Tooltip, one motion-token delay (the standard 120ms by default), on hover *and* focus, never carrying required information, never on a disabled control (§12). |
| **Scrollbars** | The platform scrollbar, styled only in width and track colour through the two scrollbar tokens; a scroll container shows its scrollbar only when it scrolls; a page never shows two vertical scrollbars at once. A scroll boundary is bordered (§11); nothing else is. |
| **Sticky regions** | The Context Bar, a table header (and the §16 sticky first column, where a table ever earns one), the Review player and an inspector header are the only sticky elements. A sticky element is sticky in the rendered page, not merely in its computed style — the audit found the Review player declared `sticky` inside a column too short to hold it, so it scrolled away with the facts about it (§4.5.1; §26 now asserts the rendered behaviour). |
| **Transitions** | §13 unchanged: 120ms state transitions, 180ms drawers, nothing else animates; data arrival, layout and selection never animate; reduced motion zeroes everything. |
| **Skeletons** | A skeleton has the geometry of the content it precedes (row count, row height, column widths, thumbnail size), so content arrival moves nothing (§38). A skeleton that is a generic grey block is a spinner with worse manners. |
| **Nothing states** | A region with nothing to show says so in one line at the region's top (§37.1); it does not reserve a viewport of space, stretch an empty-state icon across it, or draw a frame around nothing. |

### 36.4 What craftsmanship is not

It is not more white space, larger type, bigger radii, softer colours, shadows, gradients, blur, motion, illustration, or any element that exists to be noticed. It is not another product's component set. It is not a surface-by-surface polish pass. A change that makes one surface look better and leaves its sibling different has made the product worse.

---

## 37. Edge states and progressive disclosure (Added in v2.0, frozen)

### 37.1 Edge-state catalogue

§14 fixes the vocabulary and §14.1 the selector. This section fixes the **presentation per region kind**, so that the same state looks the same on every surface, which the audit found it does not. A region is one of: **page** (the whole workspace), **column** (a results list, a Ledger table, a Record's primary column), **panel** (a bordered inspector or facts block), **row/card** (one item), **media** (a thumbnail, poster or canvas).

| State | Page | Column | Panel | Row / card | Media |
|---|---|---|---|---|---|
| **loading** | Context Bar renders with identity; regions each render their own loading | Skeleton rows at the region's row pitch, count = the last known or a default (8, to be confirmed in S1) | Skeleton key/value rows | Skeleton of the row | Matte at the media's aspect, no spinner |
| **empty** | n/a | One line at the top: icon, title, one sentence, one secondary action; no frame, no fill | One line | n/a | n/a |
| **filtered-empty** | n/a | As empty with the filter icon and a *Clear filters* secondary | n/a | n/a | n/a |
| **not configured** | n/a | Hatched placeholder at the content's aspect (canvas) or the empty line (list) | One line with the action | n/a | Hatched at aspect |
| **unavailable** | One alert at the top of the workspace, `--alert-max` wide, retry trailing; regions that do not depend on the failed request still render | One alert at the top of the column, retry trailing; the column keeps its header | One alert inside the panel body, retry trailing | The row renders its identity and an inline *unavailable* text with retry as the row action | **EvidencePlaceholder**: matte at aspect, one icon, one short label (`No image`), no prose |
| **failed** | As unavailable with the §14 failed copy; code in mono last | As unavailable | As unavailable | Badge `Failed` + code in mono in the status cell | n/a |
| **stale** | n/a | Info strip beneath the header | Dashed border and `Stale` text | `Stale` text in the analytics cell, never a second badge | n/a |
| **partially available** | n/a | Info strip with counts | Counts line | n/a | n/a |
| **disabled** | n/a | n/a | Neutral text and reason line | Neutral text | n/a |
| **large data** | n/a | Virtualised or paged with an explicit continuation control; the header states the count and whether more exist | Bounded list with a disclosure beyond N (N per panel, default 5) | n/a | Bounded evidence strip (§20) |
| **long names** | Context Bar identity truncates with ellipsis; full name in the document title and by tooltip | Cell truncates (§16) | Value wraps to the readable measure, never beyond | Identity truncates | n/a |

Rules:

- One vocabulary per state. A missing thumbnail is `No image` in a list, a card, an inspector and a Review rail alike; the audit found `No evidence` beside `Evidence unavailable` for one condition.
- A state presentation never fills its region. It sits at the top of the region at its own height; the region's remaining space is base surface.
- Alerts for one cause are one alert (§14.1).
- Every state in this table that a surface can reach is a fixture in the §26 harness, and the sweep inspects it at every applicable tier.

### 37.2 Progressive disclosure tiers

Evidence remains visually dominant on every surface that has it (§18). Around it, information is presented in three tiers, in this order, on every archetype:

| Tier | Content | Presentation |
|---|---|---|
| **1 — Operational** | What the operator acts on: identity, class, camera, time, duration, confidence, status, the one next action. | Always visible; the first thing in the region. |
| **2 — Explanation** | Why: analytic facts (zones, crossings, dwell, heading), readiness and revision identity, coverage. | Visible when short; a bounded list with a disclosure beyond N when long (N per region; default 5, to be confirmed in S1 — five crossings inline, the sixth and after behind *Show all*). |
| **3 — Forensic** | Identifiers (Track ID, run ID, pipeline version), raw coordinates and vertices, engine identity, attestation, measurement detail. | Collapsed by default behind one disclosure per region; mono; copyable. Never in a list row or a Ledger cell (§16). |

A fact appears in exactly one tier and once per surface. The audit found scene-revision identity in tier 2 and again as a tier-3 footer line in the same inspector, and polygon vertices at six decimal places in tier 1 of the Scene Editor properties panel.

---

## 38. Performance as UX (Added in v2.0, frozen)

Perceived performance is a design property, and the rules below are obligations, not aspirations. **No number in this section is a measured value of the product; budgets are set only after the §26 harness has measured the baseline in the Stage 3.5 foundation slice**, and are recorded in the acceptance register when they exist. Nothing here is claimed as achieved.

| Rule | Level |
|---|---|
| **No layout shift** between a loading presentation and the content that replaces it, between a state change and its result, or on refresh. Skeletons match content geometry (§36.3); images and media reserve their aspect; fonts do not swap (the platform stack does not load). | MUST |
| **No jank on interaction**: hover, selection, drawer open, timeline scrub and canvas drag are composited transitions on transform and opacity, never on layout properties; nothing re-lays-out a list to highlight a row. | MUST |
| **No expensive animation**: nothing animates continuously except the processing pulse and the indeterminate progress, both honouring reduced motion (§13). | MUST |
| **No unnecessary spinners.** A spinner is for an operation of unknown shape and unknown duration. A list loads as skeleton rows; a value loads as a skeleton line; a submit disables its button and changes its label (§12 saving); a background refetch shows nothing. | MUST |
| **Immediate local feedback**: a control reflects its new state on the event that caused it, before any request; a request's outcome then confirms or reverts with a stated reason. | MUST |
| **Layout preserved on refresh**: the URL-backed state (§17) plus the persisted shell preferences reproduce the same layout; scroll position within a list is restored on back navigation. | MUST |
| **Stable query identity**: the TanStack Query cache key is the canonical URL state, so the same view never refetches because of parameter order, and a refetch never flashes the loading presentation over existing content (`placeholderData: keepPreviousData` in TanStack Query v5). | MUST |
| **Large lists stay usable**: a Ledger or result column with more than the viewport's rows keeps 36–40px rows, sticky headers and keyboard navigation at any count; a column that cannot stay responsive at its real counts is paged or virtualised, with an explicit continuation control (§17). | MUST |
| **Measurement**: the harness records, per state and anchor, cumulative layout shift during the loading-to-content transition (Layout Instability API), the count of long tasks during the first interaction, and the resolved font family; the first measured values become the baseline, and a later PR MUST NOT regress them beyond a tolerance the register states. | MUST (measure), budgets deferred to measurement |

---

## 39. Stage 3.5 — the professionalisation programme (Added in v2.0)

This section is the specification's pointer to the programme that implements v2.0; the plan and the register are authoritative for sequence and acceptance.

- **Plan:** `docs/superpowers/plans/2026-10-07-stage3-5-ui-ux-professionalisation.md` — audit findings, decisions, non-goals, slice sequence, rollback.
- **Register:** `docs/reviews/2026-10-07-stage3-5-ui-ux-professionalisation-acceptance.md` — the only exit gate.
- **Reference surfaces:** Overview (Ledger-summary), Videos (Ledger), Processing detail (Record), Scene Editor (Workbench), Search (Investigation), Review (Review). Each is finished to this specification first, inspected, and then used as the measure for migrating its archetype's remaining surfaces.
- **Sequence:** audit and freeze (this version) → foundation primitives, tokens and state grammar → harness v2 → reference surfaces, one per archetype → remaining surfaces by archetype → support tiers B and C → accessibility and performance hardening → final acceptance. Every slice is independently reviewable and revertible; there is no single rewrite and no stream of cosmetic patches. §34.2 states what each slice must assert and the §26 assertion manifest states which harness rules block at each point.
- **Closure:** no P0 or P1 finding open; no systemic P2 open; no surface relying on §34.1 and no §34.2 exception remaining; every §34 item asserted on every surface; the §26 sweep green at every tier anchor; tests, typecheck, build and `verify_repo` green. Remaining P2 single-surface and P3 findings are listed in the register with an owner slice or an explicit deferral; "looks better" is not an exit criterion.
- **Gate:** capability Stage 4 (ANPR/OCR) begins only after this programme is closed in the register. The programme renumbers nothing.
