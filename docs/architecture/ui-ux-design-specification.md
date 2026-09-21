# MAVI UI/UX Design Specification

**Version:** 1.0
**Status:** Adopted. Normative for frontend work from UI-1 onward, subject to the transitional clause in §34.1.
**Design baseline:** `main@b99ce26f041b3fff25094b8a5ac6a84f7305fc87`
**Scope of authority:** the MAVI operator UI (`src/web/mavi-web`).
**Decision record:** `docs/decisions/ADR-012-operator-interface-design-architecture.md` accepts the architecture this document specifies. The ADR records the decisions and the trade-offs; this document is the normative detail.

Status markers used throughout:

| Marker | Meaning |
|---|---|
| **Frozen** | Settled. Implement as written. Changing it requires an explicit amendment to this document. |
| **Deferred** | Deliberately not built now. The architecture must not preclude it; no effort is spent on it. |
| **Open** | Genuinely undecided. Closed in the named PR (§32). |
| **Transitional** | True only during the UI-1 → UI-5 programme (§34.1). |

---

## 1. Purpose and scope

This document governs the visual design, layout architecture, interaction grammar and accessibility of the MAVI operator UI. It exists so that independent implementation sessions produce one coherent product rather than a set of individually reasonable pages.

**Governs:** workspace layout, design tokens, colour semantics, typography, density, interaction states, motion, operational-state vocabulary, tables, search, evidence presentation, spatial overlays, inspectors, forms, keyboard, accessibility, formatting, responsive behaviour, visual QA, and the shared component boundary.

**Does not govern:** backend contracts, API shape, analytics semantics, worker behaviour, or the capability roadmap sequence. Where a UI rule and an ADR conflict, the ADR wins and this document is amended.

**Conformance:** §34 defines what a frontend PR must satisfy; §34.1 defines what is expected during the migration programme.

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
- Below 1100px viewport width all archetypes stack to a single column and the page scrolls. Below 768px layout must not break, but is not an acceptance target (§25).

**Scroll-ownership summary (frozen, authoritative — §25 must agree with this table):**

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
| **Structure** | Context Bar → filter toolbar (one row, ≤5 controls) → table or list. |
| **Scroll owner** | The table body. The page does not scroll. |
| **Width** | Full width. Columns carry individual `max-width`; when total natural width is less than available, the table is **left-aligned and not stretched**. A Ledger must never become a sparse band of text across 2560px. |
| **Inspector** | None by default. MAY open a right drawer on row selection where a record has more detail than a row can carry. |
| **Responsive** | 1366: all columns visible, or the least-important column collapses into the primary cell. Never horizontal *page* scroll; the table body MAY scroll horizontally. |
| **Now** | Cameras, Videos, Processing Queue, **Overview (Ledger-summary variant — §4.1.1)** |
| **Future** | Events, Entities, Cases, cross-camera scene revisions |

#### 4.1.1 Overview — the Ledger-summary variant (frozen exception)

Overview is a **Ledger-summary variant**, not a standard Ledger.

| Rule | Status |
|---|---|
| Overview is a summary and attention surface, not a dense operational table. | Frozen |
| Overview **MAY remain centred at `--content-max`** rather than expanding to full width. | Frozen exception |
| Standard Ledgers (Cameras, Videos, Processing Queue, future Events/Entities/Cases) remain **full width and column-capped**. | Frozen |
| The exception applies to Overview alone and MUST NOT be generalised to any other Ledger. | Frozen |

Restated in §25 so the responsive rules and the archetype rules cannot drift apart.

### 4.2 Record — one entity's detail

| | |
|---|---|
| **Purpose** | Everything known about one object, plus its actions. |
| **Structure** | Context Bar → primary column (~70%) + facts rail (~30%). |
| **Scroll owner** | The page. |
| **Width** | **Centred at `min(--content-max, 100%)`.** Record is a reading surface, not a working surface; centring is correct here. |
| **Inspector** | The facts rail *is* the inspector; it is not additional. |
| **Responsive** | ≤1100: facts rail stacks below the primary column. |
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
- **Adaptation, not compression.** Below the viewport width at which the rule can be satisfied (approximately 1150px), the Workbench inspector MUST become an **overlay drawer** so the stage keeps the full working width. Below 1100px the workspace stacks per the shared rule above. The stage MUST NOT be compressed below the floor in order to keep a side-by-side inspector.
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
| **Responsive** | 1366, 1440 and 1500: rail + results, inspector as drawer. 1600+: three columns in place. |
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
| **Inspector** | The evidence rail: summary, representative frame, provenance. |
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

- Left rail navigation, 216px expanded / 56px collapsed, collapse state persisted in `localStorage` (`mavi.sidebar.collapsed`). Auto-collapse only below 760px.
- Brand mark and product name at the rail head; API health indicator at the rail foot.
- Primary navigation items are ordered by operator workflow, not alphabetically.
- **The topbar becomes the Context Bar.** It carries the current surface's identity, key state badges and primary actions. 44px, sticky, full width of the content column.
- Breadcrumb form: `Section › Object › Sub-surface` (for example `Cameras › CAM-01 › Scene`). A surface MUST NOT display only a parent section title while editing a child object.

**Rules:**

- Navigation MUST be grouped into labelled sections once more than approximately seven destinations exist. Planned groups: **Operate** (Overview, Cameras, Videos, Import, Processing) and **Investigate** (Search, and future Events, Entities, Cases). Items are added only when the destination exists.
- Rail badges MAY show a count only for *attention* states (for example failed processing). Counts are neutral-coloured numerals, never red dots.
- Icon-only rail items in the collapsed state MUST carry an accessible name; `title` is acceptable for this specific case.

**Prohibited:** top navigation bars, mega-menus, tabs inside the rail, a global search field in the shell before a global search exists, automatic rail collapse at desktop widths.

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
| Accent | Exactly two uses: **the primary action** and **selection**. Never decoration, never a status. |
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
| disabled | Opacity reduction, not a colour. |

**Rule:** status meaning is assigned centrally (`shared/status`). A screen MUST NOT map a status string to a tone locally.

### 8.3 Evidence and spatial colours

A **separate namespace** (`--evidence-*`, `--geo-*`). Roles are **frozen**. The hues of every role the product renders were frozen in UI-1; the event marker, the similarity rank and the heatmap scale remain open as sub-decisions 2a–2c (§32).

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

**Hues chosen in UI-1** (§32, open decision 2) for every role the product renders today: zone `--geo-zone` `#fb923c`, trip line `--geo-line` `#22d3ee`, A→B `--geo-dir-ab` `#f0abfc`, B→A `--geo-dir-ba` `#e879f9`, bounding box `--evidence-box` `#a78bfa`, trajectory `--evidence-track` `#2dd4bf`. They were selected by constrained optimisation for mutual separation under normal vision and protan/deuteran/tritan simulation, then validated over the §26 footage conditions. The event marker (2a), similarity rank (2b) and heatmap scale (2c) remain **open**: they have no surface that draws them, and this section requires a hue to be validated against real evidence. Each takes its value from the same namespace in the slice that first renders it.

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
- Floating layers: one drawer style (right, 420–480px) and one popover style. No other floating surfaces.
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
| **disabled** | Reduced opacity and `not-allowed` cursor. The *reason* MUST be stated adjacently when not obvious — never only in a `title` on a disabled control, which receives no pointer events. |
| **invalid** | `aria-invalid`, a warning border, and an inline message associated via `aria-describedby`. |
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

---

## 15. Feedback, confirmations and notifications

**Inline first.** The result of an action appears where the action was taken.

| Mechanism | Rule |
|---|---|
| **Inline** | Default. Button label changes, row badge changes, field message appears. |
| **Banner** | For page-scope conditions that persist (offline, conflict, superseded revision, partial coverage). Never auto-dismissed. |
| **Transient feedback (toast)** | **No workflow may depend on a transient toast, and a persistent operational problem MUST NOT be delivered as one.** Brief, non-critical acknowledgement MAY use transient feedback where it materially improves clarity. A toast is never the only record of a failure. |
| **Modal / dialog** | **Routine editing MUST NOT require a modal.** A modal is acceptable only when temporarily blocking the underlying workspace is genuinely the correct interaction for a rare, consequential decision. Where an in-band two-step confirmation conveys the same consequence, it is preferred. |
| **Native `window.confirm`** | MUST be replaced. It cannot state consequences in product language, cannot be styled, and browsers offer to suppress it — silently removing the safeguard. |
| **Progress** | Determinate where the API supplies a percentage; indeterminate otherwise. Fabricated progress is prohibited. |

Confirmations state the **consequence**, not the question: "Saving disables analytics for CAM-01", not "Are you sure?".

---

## 16. Tables and data-heavy views

**Frozen:**

- One table primitive. Legacy and duplicate table styling is removed.
- **One logical line per row.** Names truncate; the full value lives in the inspector or on hover.
- **One status column, one badge per row.** Two badges describing the same thing in one row is a defect; a secondary run state appears only when it differs from the primary state.
- Numeric columns are right-aligned with tabular figures.
- Sticky header. A sticky first column only when a table exceeds approximately eight columns.
- Row actions sit at the row's trailing edge, consistently: one primary text action plus at most one icon-only action.
- **Filters live in a toolbar row above the table**, never inside the container header.
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
| Workbench | **Always present**, fixed width, shows a summary when nothing is selected. Becomes an overlay drawer below approximately 1150px per §4.3.1. |
| Investigation | **On selection**; in-place at 1600px and above, drawer below that (§4.4, open decision 3 closed in UI-4). |
| Review | The evidence rail; always present. |
| Ledger | **None by default.** MAY use a right drawer on selection. |
| Record | The facts rail *is* the inspector. There is no additional panel. |

**Rules:**

- Inspector width is fixed per archetype. **Resizable splitters are deferred** (§31) and MUST NOT be introduced to solve a width constraint (§4.3.1).
- The inspector body scrolls; its header is sticky.
- Selection synchronisation is mandatory: list, canvas and inspector always agree.
- `Esc` closes a drawer inspector; it does not close a permanent one.
- **A third permanent column on Ledger or Record is prohibited.**

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

**Desktop-first. Frozen acceptance expectations.** This section and §4 must agree; §4's scroll-ownership table is authoritative on scroll.

| Viewport | Expectation |
|---|---|
| **1366×768** | **Real acceptance viewport.** **Workbench MUST fit without page scroll**, with the stage at 65% or more of the workspace working width (approximately 800px in practice, §4.3.1). **Review MAY page-scroll, but the player and the primary evidence summary MUST both be visible in the initial viewport** (§4.5.1). Ledgers scroll the table body only. Investigation shows rail and results with the inspector as a drawer. No horizontal *page* scroll anywhere. No overlapping controls. |
| **1440×900** | As 1366. Investigation inspector remains a drawer. |
| **1920×1080** | All archetypes in full form; Investigation three columns in place. |
| **approximately 2560×1080** | **Ultra-wide is used, not capped.** Workbench, Investigation, Review and standard Ledgers occupy full width; surplus goes to the stage (Workbench), the inspector (Investigation), the player (Review). Standard Ledgers are **left-aligned and column-capped**, not stretched. **Record remains centred at `--content-max`. Overview, as the Ledger-summary variant, MAY also remain centred at `--content-max` (§4.1.1) — this is the only Ledger permitted to do so.** |
| **1100px and below** | Single-column stacking; the page scrolls. Functional, not optimised. |
| **below 768px** | Must not break. **Not an acceptance target.** |

**Known defect (UI-1):** `.page` sets `width: min(--content-max, 100%)` while `.page--full` sets `max-width: none`; `max-width` cannot override `width`, so at the design baseline **every surface including Workbench and Investigation renders at 1600px with roughly 588px of dead space at 2560×1080**. This is the highest-impact layout defect in the product.

---

## 26. Visual QA standard

**Normative. Unit tests do not satisfy this requirement.**

**Every significant frontend PR MUST** be visually checked in a real browser at **1366×768, 1440×900, 1920×1080 and approximately 2560×1080**, across the states relevant to the change:

- populated, empty, loading, unavailable/error, selected/detail, long-name and dense-data, validation and conflict where applicable.

**Surfaces containing media or spatial content MUST additionally be checked against:**

- bright footage, dark footage, letterboxed and pillarboxed sources, and overlay visibility over each.

**Method:** a scripted browser pass against the real application with intercepted API fixtures. The harness and its fixtures **MUST NOT require production code to be altered to make inspection easier**. Generated screenshots are working artefacts and **MUST NOT be committed**.

**Automated assertions the harness SHOULD make:** no horizontal page overflow; no uncaught page errors; no element overlap in the checked states; and, on a surface that declares an archetype, the §4 geometry and scroll-ownership rules only a rendered page can settle.

**A contained column clips in both directions.** An archetype whose page does not scroll cannot produce a document-level horizontal scrollbar either, so a layout whose columns do not fit simply loses its right edge — controls and all — while every other assertion passes. The harness MUST check a contained column's width as well as its height. This is how the Investigation at 1500px was found to be clipping the inspector's own Open and Close controls (§4.4, open decision 3).

**A deliberate overlay is not an overlap.** A drawer covers what is behind it by design, so a pair where exactly one side sits inside a positioned overlay is the archetype working. Two elements inside the *same* overlay are still compared with each other.

**Reporting:** the PR states which viewports and states were checked and what the pass found. "No visual regressions" without an enumerated pass is not conformance.

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
| Analytics readiness and coverage indicators | **Slice 3, surfaced in Slice 4** | Ledger badge, Investigation coverage strip, Workbench context chip | `stale` and `partially available` tokens and taxonomy (§8.2, §14); UI-3 for the Ledger indicators |
| Search integration and analytics predicates | **Slice 4** | Investigation | UI-4 in place; committed-filter chips and coverage strip (§17) |
| Evidence overlays and explanation | **Slice 5** | Review and Investigation inspector | UI-5 in place; one player with lane extension points (§18) |
| Aggregates, occupancy, heatmap | **Slice 6** | Workbench | Workbench grammar from UI-2; sequential scale and legend; zone colour already separated from accent (§8.3) |
| Hardening, acceptance, qualification | **Slice 7** | — | Visual QA standard (§26) as part of acceptance evidence |
| Visual attributes | Capability stage 2 | Investigation filter chips and inspector key/value | committed-filter chips (§17) |
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
- Phone or mobile analyst experience.
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
| **2a** | Event-marker hue | **Scene Analytics Slice 5** (evidence overlays and explanation) | §8.3. From the `--geo-*` namespace, with its own glyph. Closed when Slice 5 first draws an event marker over real evidence. |
| **2b** | Similarity / ReID candidate hue | **Capability stage 5** (Visual Similarity / Find Similar) | §8.3. Own hue plus a rank numeral, never a success hue. Closed when the similarity UI exists. |
| **2c** | Heatmap scale | **Scene Analytics Slice 6** (aggregates and heatmap) | §8.3. A perceptually-uniform sequential scale with a legend; red-to-green is prohibited. Closed when the heatmap surface exists. |
| ~~**3**~~ | ~~Investigation in-place-inspector threshold (1500px default)~~ — **closed in UI-4: amended to 1600px** | Closed | §4.4. Measured at 1440, 1500, 1550, 1599, 1600 and 1700. Three columns at their minimums need 1284px of working width; 1500 leaves 1244 and clipped the inspector's own controls off the right edge of a contained column, with no scrollbar to reach them. 1600 leaves 1344. The same measurement gives the in-place inspector a 440px floor — the width its drawer already uses — because a layout that grants the results their 900px cap first leaves the inspector 60px at 1500 and 160px at 1600. |
| ~~**4**~~ | ~~Ultra-wide Investigation split ratio (results cap versus inspector growth)~~ — **closed in UI-4: unchanged as specified** | Closed | §4.4. Results capped at approximately 900px, surplus to the inspector: measured 900/480 at 1920 and 900/1120 at 2560. The cap holds with nothing selected too, which the default did not say and UI-4 settles: a scan column is a scan column whether or not there is an inspector beside it. |
| ~~**5**~~ | ~~Ledger sorting scope — which columns, client or server~~ — **closed in UI-3: client-side, per-Ledger, on the columns an operator actually re-orders by** | Closed | §16. **Cameras** sorts on Code (default, ascending), Name and State; Timezone and Actions do not sort. **Videos** sorts on File, Camera, Recorded (default, descending — the order the page already had) and Duration; Status does not, because it already has a filter and is operationally mutable, and Actions is not data. **Processing Queue** offers no operator-selectable sorting at all: its order *is* the operational statement — active, then failed, then completed, each bucket keeping the recording-start order it already had — and letting the operator re-order it would discard that meaning. Sorting stays client-side over inventories the API already returns whole: no endpoint changes, and no new URL parameter, so §17's "URL is the state of record" gains nothing to record. A sort is a view preference, not a shareable scope. |
| **6** | Whether Overview survives as a distinct surface once an Events Ledger exists | After Events lands | §4.1.1. |
| **7** | Timeline lane presentation for multiple analytical interval types (stacked lanes versus single lane with glyphs) | UI-5 defines the extension point; the presentation is chosen when the first analytical lane has real data (Slice 5) | §18. |

---

## 33. UI implementation roadmap

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

- **Status.** The **active** UI Foundation increment. UI-1, UI-2 and UI-3 are merged and post-merge `main`
  is qualified, which is what lets this one begin. Open decisions 3 and 4 close here (§32): the in-place
  inspector threshold is **amended to 1600px** on measured evidence, and the ultra-wide split is
  **confirmed unchanged**.
- **Objective.** Migrate Search onto the Investigation archetype.
- **Scope.** Filter rail rebuilt as scrolling field sections; committed-filter chips at the results head; results hierarchy and header copy; inspector behaviour including the drawer below threshold; ultra-wide utilisation; keyboard behaviour preserved and extended; URL-state semantics preserved exactly. Closes open decisions 3 and 4 (§32).
- **Exclusions.** **No Slice 4 analytics predicates**; no coverage strip content; no saved searches; no natural-language query.
- **Prerequisites.** UI-2.
- **Acceptance.** Committed filters reproducible from the URL, unchanged; no overlapping controls at 1366 or 1440; the inspector threshold validated and either confirmed or amended in §4.4; keyboard navigation unchanged or improved; §26 visual QA pass.
- **Risks.** Medium — URL, keyboard and pagination interplay is subtle; existing tests must be preserved.
- **Relation to Scene Analytics.** **Must be in place before Slice 4 Search/readiness UI is added.**

### 33.6 UI-5 — Evidence Player + Review

- **Objective.** One reusable evidence-player foundation.
- **Scope.** Custom transport; one timeline with lane extension points; overlay and layer controls; keyboard playback; poster and reference behaviour; uncertainty rendering; Review migrated to the Review archetype including the sticky-player rule (§4.5.1); the Investigation inspector uses the same component.
- **Exclusions.** **No analytical lanes for data that does not yet exist**; no Slice 5 overlay content; no event UI; no live or multi-camera work.
- **Prerequisites.** **UI-4.** UI-5 migrates the Investigation inspector onto the Evidence Player, so the Investigation workspace must already be on its archetype.
- **Acceptance.** Exactly one player implementation in the codebase; no native controls beneath overlays; one timeline; overlays correct under letterbox and pillarbox; **at 1366×768 the migrated Review page shows the player and the primary evidence summary in the initial viewport** (§4.5.1, §25) — the check deferred here from UI-2; §26 visual QA against bright, dark, saturated, low-contrast and letterboxed footage; existing player tests preserved or replaced with equivalents.
- **Risks.** Medium-high — media element lifecycle. The existing animation-frame and seek logic is tested and should be reused rather than rewritten.
- **Relation to Scene Analytics.** **Must be in place before Slice 5 evidence-overlay/explanation UI is added.** Slice 5 draws into this player's lanes.

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

A PR that cannot honestly assert items 1–12 is not conformant, regardless of test status.

### 34.1 Transitional conformance during UI-1 → UI-5 (Transitional)

Migration is incremental by design. The following governs the programme period and expires when UI-5 merges.

| Rule | Level |
|---|---|
| **New or materially reworked surfaces MUST conform** to this specification. | MUST |
| **Existing untouched legacy surfaces MAY remain temporarily non-conformant** until their scheduled migration PR. | MAY |
| **A migration PR is NOT non-conformant merely because out-of-scope legacy surfaces remain non-conformant.** Conformance is assessed against what the PR creates or materially reworks. | Frozen |
| A PR **MUST NOT introduce a new deviation**, and **MUST NOT extend or copy an existing legacy pattern** into new code. Touching a legacy surface incidentally does not oblige migrating it, but does oblige not making it worse. | MUST |
| A PR **SHOULD** name the legacy surfaces it deliberately left alone and the UI PR that owns them. | SHOULD |
| **Once UI-5 is merged, full frontend conformance becomes the expected baseline** and this transitional clause no longer applies. | Frozen |

---

## 35. Final design baseline

MAVI is a **dark-first, evidence-first, offline professional Visual Intelligence workstation**, built from **five frozen workspace archetypes** — Ledger (with the Overview Ledger-summary exception), Record, Workbench, Investigation, Review — on a **primitive and semantic design-token architecture with narrowly scoped component tokens only where semantically justified**, in which **UI colour and evidence colour are permanently separate namespaces**, with a **single unambiguous operational-state vocabulary served by a shared async-state boundary**, **URL-backed investigations**, **one reusable Evidence Player**, and **accessibility and browser-based visual QA as architecture rather than afterthought**.

**Frozen:** the five archetypes and their scroll ownership; Workbench fitting 1366×768 with a stage at 65% or more of working width; Review's page-scroll with player and primary summary above the fold; the Overview centring exception; the shell and Context Bar; the token architecture; colour role separation; the state taxonomy and the async-state boundary; density, target-size and containment rules; the interaction and motion grammar; the evidence and spatial visual hierarchy; responsive and ultra-wide acceptance at 1366, 1440, 1920 and approximately 2560; the visual QA standard; the §27.1 promotion test; and the sequential UI-1 → UI-2 → UI-3 → UI-4 → UI-5 programme with **Scene Analytics Slice 3 gated on UI-2 merging with green post-merge `main`**.

**Deferred, architecturally permitted:** light palette and System theme; selectable density; resizable panes; configurable layouts; command palette; mobile; notification centre; the Wall archetype for live multi-camera.

**Open, closed in the named PR:** the UI font decision (UI-1); the exact evidence hues (UI-1 visual validation); the Investigation inspector threshold and ultra-wide split (**closed in UI-4**: threshold amended to 1600px, split unchanged); the Ledger sorting scope (closed in UI-3); Overview's long-term fate (after Events); analytical timeline lane presentation (Slice 5).

**Transitional:** §34.1 governs conformance until UI-5 merges, after which full frontend conformance is the baseline.

Everything else is settled. Future work implements this specification or amends it explicitly.
