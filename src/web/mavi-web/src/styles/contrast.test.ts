import { describe, expect, it } from 'vitest';
import baseCss from './base.css?raw';
import componentsCss from './components.css?raw';
import featuresCss from './features.css?raw';
import layoutCss from './layout.css?raw';
import tokensCss from './tokens.css?raw';
import workspaceCss from './workspace.css?raw';

/**
 * Contrast obligations of section 23, computed from the tokens themselves
 * rather than from numbers copied into a test. If someone edits a primitive,
 * this fails; if someone edits the test, the numbers still have to come out.
 *
 * The three defects this pins were real at the design baseline: text on
 * `--accent` measured 3.45:1 (fails AA), the focus ring on `--accent-strong`
 * measured 2.35:1 (fails the 3:1 non-text minimum), and control boundaries sat
 * at 1.31:1 against their own surface.
 *
 * Section 23 scopes the 3:1 obligation to boundaries that identify a control, a
 * state or information. Decorative dividers are exempt (section 11), so
 * `--border-subtle` is deliberately absent from the interactive table below.
 */

const tokens = tokensCss;

/** Resolve a token through however many var() indirections it is declared with. */
function resolve(name: string, seen = new Set<string>()): string {
  if (seen.has(name)) throw new Error(`cyclic token: ${name}`);
  seen.add(name);
  const match = tokens.match(new RegExp(`^\\s*${name}\\s*:\\s*([^;]+);`, 'm'));
  if (!match) throw new Error(`undeclared token: ${name}`);
  const value = match[1].trim();
  const indirect = value.match(/^var\(\s*(--[a-z0-9-]+)\s*\)$/);
  if (indirect) return resolve(indirect[1], seen);
  // `--status-stale` is declared as a colour-mix of two primitives and is
  // painted as text (the stale badge, alert and coverage icon), so it has to
  // resolve to a colour here, not to its declaration. A `color-mix(in srgb,
  // A p%, B)` is a linear blend of the two sRGB byte triples.
  const mix = value.match(/^color-mix\(in srgb,\s*var\(\s*(--[a-z0-9-]+)\s*\)\s*(\d+)%,\s*var\(\s*(--[a-z0-9-]+)\s*\)\s*\)$/);
  if (mix) {
    const weight = Number(mix[2]) / 100;
    const a = rgb(resolve(mix[1], new Set(seen)));
    const b = rgb(resolve(mix[3], new Set(seen)));
    return '#' + a.map((c, i) => Math.round(c * weight + b[i] * (1 - weight)).toString(16).padStart(2, '0')).join('');
  }
  return value;
}

function rgb(hex: string): [number, number, number] {
  let h = hex.trim().replace('#', '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  if (h.length === 8) h = h.slice(0, 6);
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

function relativeLuminance(hex: string): number {
  const channel = (c: number) => {
    const v = c / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const [r, g, b] = rgb(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [relativeLuminance(resolve(a)), relativeLuminance(resolve(b))].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Every surface a control or a focus ring can be painted on. */
const SURFACES = [
  '--surface-app', '--surface-base', '--surface-raised', '--surface-raised-2', '--surface-inset',
];

/**
 * The region fills a page composes on top of the page surfaces: a selected
 * row or pressed control, and the soft fill of every status region (alert,
 * badge, coverage band, caution bar).
 */
const FILLS = [
  '--accent-soft',
  '--status-ok-soft', '--status-warn-soft', '--status-err-soft', '--status-info-soft',
  '--status-neutral-soft', '--status-stale-soft', '--status-unavailable-soft',
];

/** The text roles that inherit whatever surface they land on. */
const BODY_TEXT = ['--text-primary', '--text-secondary', '--text-muted', '--accent-text'];
/** Status hues painted as text on the page (a refusal, a warning, a tag). */
const STATUS_TEXT = [
  '--status-ok', '--status-warn', '--status-err', '--status-info', '--status-neutral', '--status-stale',
];

type Pair = [fg: string, bg: string];
const cross = (fgs: string[], bgs: string[]): Pair[] => fgs.flatMap((fg) => bgs.map((bg): Pair => [fg, bg]));

/**
 * Every text/surface pair the product paints, at 4.5:1 (section 23). The
 * coverage block below enumerates the stylesheets and refuses any painted
 * pair that is not in this table, so adding a `color` to a sheet means
 * adding its row here.
 */
const TEXT_PAIRS: Pair[] = [
  // Text that inherits its surface sits on every page surface, including the
  // hover step (--surface-raised-2) a row or button takes.
  ...cross(BODY_TEXT, SURFACES),
  ...cross(STATUS_TEXT, SURFACES),
  // Compositions the stylesheets cannot see from a selector alone: an alert's
  // sentence is body text on a status fill; the Context Bar's crumbs, subject
  // and zone note sit on the caution fill; a selected Ledger row, result row
  // or navigator item keeps its muted meta and its links on --accent-soft.
  ...cross(BODY_TEXT, FILLS),
  // Status text on the selection fill: a navigator warning or a refusal
  // inside a selected row.
  ...cross(STATUS_TEXT, ['--accent-soft']),
  // Badges, alerts and chips: a status hue on its own soft fill.
  ['--status-ok', '--status-ok-soft'],
  ['--status-warn', '--status-warn-soft'],
  ['--status-err', '--status-err-soft'],
  ['--status-info', '--status-info-soft'],
  ['--status-neutral', '--status-neutral-soft'],
  ['--status-stale', '--status-stale-soft'],
  ['--status-unavailable', '--status-unavailable-soft'],
  // The primary action, the active segment, the selected vertex, the skip link.
  ['--text-on-accent', '--accent-strong'],
  // The evidence placeholder: one word on the matte.
  ['--text-muted', '--evidence-matte'],
];

/**
 * A disabled control is exempt from the 4.5:1 text minimum but must still be
 * read (section 12): 3:1 is the floor. The pressed-and-disabled ToggleChip
 * mark inverts the pair (the disabled surface as the check on disabled text).
 */
const DISABLED_TEXT_PAIRS: Pair[] = [
  ['--text-disabled', '--control-disabled-bg'],
  ['--control-disabled-bg', '--text-disabled'],
];

/**
 * Every boundary, ring or indicator that identifies a control or a state, at
 * 3:1 (section 23). A boundary painted in the same rule as a state fill is an
 * edge of a region the fill and text already identify, and is decorative
 * under section 11 (the alert, badge and danger-button borders); the
 * enumeration below exempts exactly those, and nothing else.
 */
const NON_TEXT_PAIRS: Pair[] = [
  // The focus ring sits outside its element, on every surface in the product
  // including the primary action and the evidence matte a focused frame sits on.
  ...cross(['--focus-ring'], [...SURFACES, '--accent', '--accent-strong', '--accent-hover', '--evidence-matte']),
  // The scrollbar thumb on every scrolling surface (section 36.3).
  ...cross(['--scrollbar-thumb'], SURFACES),
  // An interactive control boundary.
  ...cross(['--border-control'], SURFACES),
  // Section 11: a border that identifies an interactive or scrollable region
  // is not decorative and carries the same 3:1 duty as a control boundary.
  // Naming the role and leaving it at the decorative value would make the
  // distinction nominal.
  ...cross(['--border-panel'], SURFACES),
  // The hover/emphasis boundary.
  ...cross(['--border-strong'], SURFACES),
  // Section 23: a boundary that identifies a state is not decorative. The
  // invalid boundary on a control's inset surface and on the page.
  ...cross(['--status-err'], [...SURFACES, '--control-disabled-bg']),
  // Selection cues drawn as a shape: the inset bar on a current result row or
  // navigator item (on --accent-soft), the ring on a selected card, the
  // inspected Evidence Set row, the drawing stage, and the pressed ToggleChip
  // mark (--accent as a filled box on the pressed button's --accent-soft).
  ...cross(['--accent'], [...SURFACES, '--accent-soft', '--evidence-matte']),
  // The ToggleChip's check glyph on its filled mark: a glyph, not text, so 3:1.
  ['--text-on-accent', '--accent'],
  // The sort glyph and the clustered timeline tick, both painted --text-muted.
  ...cross(['--text-muted'], SURFACES),
  // State dots and progress fills on the page and on the progress track, and
  // the disabled navigator dot drawn as a --status-neutral ring.
  ...cross(['--status-ok', '--status-warn', '--status-info', '--status-neutral'], SURFACES),
  // The stale cue is a dashed edge or underline (section 8.2): it is the
  // non-colour carrier of the state, so it is not decorative, and it is drawn
  // in the status hue itself (the `--status-*-border` tokens sit near 2:1 and
  // are reserved for the decorative edge of a filled region). On its own fill
  // (badge, alert, coverage band) and on the Ledger row it underlines.
  ['--status-stale', '--status-stale-soft'],
  ...cross(['--status-stale'], SURFACES),
  // A warning carried by a boundary alone: the read-only revision chip and the
  // analytics inspector's caution bar paint no fill. (--status-warn on every
  // page surface is covered with the indicators above.)
  // The active revision chip is identified by its border on the chip surface.
  ['--status-ok', '--surface-raised'],
  ['--status-ok', '--surface-raised-2'],
];

describe('text contrast (4.5:1)', () => {
  it.each(TEXT_PAIRS)('%s on %s reaches AA', (fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5);
  });

  it('keeps the error message readable on every form surface', () => {
    // The invalid message is the non-colour cue (section 12); it still has to
    // be read, and a form sits on the base or raised surface.
    expect(contrast('--status-err', '--surface-base')).toBeGreaterThanOrEqual(4.5);
    expect(contrast('--status-err', '--surface-raised')).toBeGreaterThanOrEqual(4.5);
  });

  it.each(DISABLED_TEXT_PAIRS)('disabled %s on %s stays legible at the 3:1 floor', (fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(3);
  });

  it('keeps a disabled label legible without claiming it is enabled', () => {
    // A disabled control is exempt from the 4.5:1 text minimum, and must still
    // be read (section 12). 3:1 is the floor pinned here; the disabled text
    // must also sit below the muted floor so the two states never collapse.
    expect(contrast('--text-disabled', '--control-disabled-bg')).toBeGreaterThanOrEqual(3);
    expect(contrast('--text-disabled', '--control-disabled-bg')).toBeLessThan(
      contrast('--text-muted', '--control-disabled-bg'),
    );
  });

  it('paints text on --accent-strong, never on --accent', () => {
    // The defect named in section 8.1: --accent cannot legally carry text.
    expect(contrast('--text-on-accent', '--accent-strong')).toBeGreaterThanOrEqual(4.5);
    expect(contrast('--text-on-accent', '--accent')).toBeLessThan(4.5);
  });
});

describe('non-text contrast (3:1)', () => {
  it.each(NON_TEXT_PAIRS)('%s is visible on %s', (fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(3);
  });

  it('leaves decorative dividers below the interactive threshold on purpose', () => {
    // Section 11: a border that only groups content is not required to reach
    // 3:1, and raising every hairline to it would turn the product into a grid
    // of bright lines. This asserts the distinction is real, not accidental.
    expect(contrast('--border-subtle', '--surface-base')).toBeLessThan(3);
    expect(contrast('--border-control', '--surface-base')).toBeGreaterThanOrEqual(3);
  });
});

/**
 * Coverage: the tables above are complete.
 *
 * Plan 2026-10-10 S6 X1, section 4 rows 1-2 and section 5.3. A contrast table
 * copied from the tokens proves only the pairs someone thought of. This block
 * reads every stylesheet the application ships, finds every token painted as
 * text and every token painted as a boundary or indicator, works out which
 * surfaces each can land on, and refuses any pair the tables do not check.
 *
 * The surface a painted token lands on is read from the stylesheet in this
 * order, and the first that answers wins, so a token painted on a specific
 * component surface is asserted against that surface and not against every
 * page surface:
 *
 *   1. the rule's own `background`, when it is a surface role;
 *   2. the resting surface of the same element: a rule whose subject is the
 *      same compound with its state (`.is-*`, `[aria-*]`, `:hover`, ...)
 *      stripped, and which paints a surface without repainting the text;
 *   3. the surface of an ancestor compound named in the selector
 *      (`.alert--error > .icon` lands on `.alert--error`'s fill);
 *   4. otherwise the element inherits the page: every surface in SURFACES. A
 *      rule that sets `background: transparent` also lands on the page.
 *
 * What the enumeration deliberately does not do: follow the DOM (an alert's
 * sentence on its fill, the crumbs on the caution bar — those compositions
 * are the explicit `cross(BODY_TEXT, FILLS)` rows), read SVG `fill`/`stroke`
 * (the evidence namespace is asserted against the halo above), or treat a
 * border painted alongside a state fill as identifying (section 11).
 */
describe('contrast coverage: every painted pair is in a table', () => {
  const SHEETS: Record<string, string> = {
    'base.css': baseCss,
    'components.css': componentsCss,
    'features.css': featuresCss,
    'layout.css': layoutCss,
    'workspace.css': workspaceCss,
  };

  /** A token that can be painted under text or a boundary. */
  const SURFACE_ROLE = /^--(surface-(app|base|raised|raised-2|inset)|status-[a-z]+-soft|accent(-soft|-strong|-hover)?|control-disabled-bg|evidence-matte|text-disabled)$/;
  /** A token that can be painted as text (or a glyph through `color`). */
  const TEXT_ROLE = /^--(text-(primary|secondary|muted|disabled|on-accent)|accent-text|status-(ok|warn|err|info|neutral|stale|unavailable)|control-disabled-bg)$/;
  /** A token that identifies a control, a state or a region when drawn as a line. */
  const BOUNDARY_ROLE = /^--(status-(ok|warn|err|info|neutral|stale|unavailable)(-border)?|accent|accent-strong|focus-ring|scrollbar-thumb|border-(control|panel|strong))$/;
  /** A token that identifies a state when drawn as a filled mark (a dot, a bar). */
  const INDICATOR_ROLE = /^--(status-(ok|warn|err|info|neutral|stale)|accent)$/;
  const BOUNDARY_PROPERTY = /^(border(-(top|right|bottom|left))?(-color)?|outline(-color)?|box-shadow|text-decoration(-color)?)$/;
  /** A `color` on one of these subjects paints a glyph, not a run of text. */
  const GLYPH_SUBJECT = /(\.icon|__mark|__tick|::before|::after)$/;
  const DISABLED_SELECTOR = /:disabled|\[disabled\]|aria-disabled|data-disabled/;

  interface Rule { file: string; selector: string; declarations: Map<string, string> }

  function parse(file: string, css: string): Rule[] {
    const scannable = css.replace(/\/\*[\s\S]*?\*\//g, '');
    const out: Rule[] = [];
    for (const match of scannable.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const declarations = new Map<string, string>();
      for (const declaration of match[2].split(';')) {
        const at = declaration.indexOf(':');
        if (at < 0) continue;
        declarations.set(declaration.slice(0, at).trim().toLowerCase(), declaration.slice(at + 1).trim());
      }
      for (const selector of match[1].split(',')) {
        const trimmed = selector.trim().replace(/\s+/g, ' ');
        if (trimmed && !trimmed.startsWith('@')) out.push({ file, selector: trimmed, declarations });
      }
    }
    return out;
  }

  const RULES = Object.entries(SHEETS).flatMap(([file, css]) => parse(file, css));

  const tokensIn = (value: string) => Array.from(value.matchAll(/var\(\s*(--[a-z0-9-]+)\s*\)/g), (m) => m[1]);
  const compounds = (selector: string) => selector.split(/\s*[>+~]\s*|\s+/).filter(Boolean);
  const subjectOf = (selector: string) => compounds(selector).at(-1) ?? '';
  /**
   * A state written into a compound: a state class or an attribute. A
   * pseudo-class (`:hover`, `:focus-within`) is a transient step of the same
   * element and is not a state here; a pseudo-element is not one either.
   */
  const STATE = /\.(is-[\w-]+|active)\b|\[[^\]]*\]|:(disabled|checked)\b/;
  /** The compound with its states, pseudo-classes and pseudo-elements stripped. */
  const resting = (compound: string) => compound.replace(/\.(is-[\w-]+|active)\b|\[[^\]]*\]|::?[\w-]+(\([^)]*\))?/g, '');

  /** The rule's own painted surface: a surface token, 'transparent', or null. */
  function ownSurface(rule: Rule): string | null {
    const value = rule.declarations.get('background-color') ?? rule.declarations.get('background');
    if (value === undefined) return null;
    if (/^(transparent|none)$/.test(value)) return 'transparent';
    const token = tokensIn(value)[0];
    return token && SURFACE_ROLE.test(token) ? token : null;
  }

  const add = (map: Map<string, Set<string>>, key: string, surface: string) => {
    if (!key) return;
    if (!map.has(key)) map.set(key, new Set());
    map.get(key)!.add(surface);
  };
  /**
   * Resting subject -> the surfaces an element takes when no state is written
   * anywhere in its selector (its own rule and its hover step). A rule that
   * carries a state (`.chip.is-active`, `input[aria-invalid]`, the mark of a
   * `.toggle-chip[aria-pressed]`) paints that state only and must not leak its
   * fill onto the element's other states.
   */
  const restingSurfaces = new Map<string, Set<string>>();
  /** Exact subject compound -> the surfaces (or 'transparent') any rule with that subject paints. */
  const exactSurfaces = new Map<string, Set<string>>();
  for (const rule of RULES) {
    const surface = ownSurface(rule);
    if (!surface) continue;
    const subject = subjectOf(rule.selector);
    add(exactSurfaces, subject, surface);
    // A `:not([aria-disabled])` on a hover rule excludes a state; it is not one.
    const stated = STATE.test(rule.selector.replace(/:not\([^)]*\)/g, ''));
    if (surface !== 'transparent' && !stated) add(restingSurfaces, resting(subject), surface);
  }

  /** The surfaces an element selected by `rule` can be painted on. */
  function surfacesOf(rule: Rule): string[] {
    const own = ownSurface(rule);
    if (own && own !== 'transparent') return [own];
    const found = new Set<string>();
    const parts = compounds(rule.selector);
    const subject = parts.at(-1) ?? '';
    for (const s of restingSurfaces.get(resting(subject)) ?? []) found.add(s);
    for (const ancestor of parts.slice(0, -1)) {
      for (const s of exactSurfaces.get(ancestor) ?? restingSurfaces.get(resting(ancestor)) ?? []) found.add(s);
    }
    // A bare element (`a`, `td`) is styled once and lands everywhere; the
    // surface a hover rule gives it in one context does not confine it.
    const bareElement = !/[.#[]/.test(resting(subject));
    if (own === 'transparent' || found.has('transparent') || found.size === 0 || bareElement) {
      for (const s of SURFACES) found.add(s);
    }
    found.delete('transparent');
    return Array.from(found);
  }

  const key = ([fg, bg]: Pair) => `${fg} on ${bg}`;
  const TEXT = new Set(TEXT_PAIRS.map(key));
  const DISABLED = new Set(DISABLED_TEXT_PAIRS.map(key));
  const NON_TEXT = new Set(NON_TEXT_PAIRS.map(key));

  /** Every token painted through `color`, with where it lands and what it is. */
  function paintedText() {
    const text: Pair[] = [];
    const glyph: Pair[] = [];
    const disabled: Pair[] = [];
    const where = new Map<string, string[]>();
    for (const rule of RULES) {
      const value = rule.declarations.get('color');
      if (!value) continue;
      const token = tokensIn(value)[0];
      if (!token || !TEXT_ROLE.test(token)) continue;
      const bucket = token === '--text-disabled' || token === '--control-disabled-bg' || DISABLED_SELECTOR.test(rule.selector)
        ? disabled
        : GLYPH_SUBJECT.test(subjectOf(rule.selector)) ? glyph : text;
      for (const surface of surfacesOf(rule)) {
        const pair: Pair = [token, surface];
        bucket.push(pair);
        where.set(key(pair), [...(where.get(key(pair)) ?? []), `${rule.file}: ${rule.selector}`]);
      }
    }
    return { text, glyph, disabled, where };
  }

  /** Every state or boundary token drawn as a line or a mark, with its surfaces. */
  function paintedBoundaries() {
    const identifying: Pair[] = [];
    const decorative: Pair[] = [];
    const where = new Map<string, string[]>();
    for (const rule of RULES) {
      const own = ownSurface(rule);
      const stateFill = own !== null && own !== 'transparent' && own !== '--evidence-matte';
      const dashed = Array.from(rule.declarations.entries())
        .some(([property, value]) => property.startsWith('border') && /\bdashed\b/.test(value));
      for (const [property, value] of rule.declarations) {
        const isBoundary = BOUNDARY_PROPERTY.test(property);
        const isFill = property === 'background' || property === 'background-color';
        if (!isBoundary && !isFill) continue;
        for (const token of tokensIn(value)) {
          if (isFill ? !INDICATOR_ROLE.test(token) : !BOUNDARY_ROLE.test(token)) continue;
          // Section 11: an edge drawn around a region the same rule fills is
          // the region's outline, not the carrier of its state. A dashed edge
          // is the carrier (section 8.2), and so is anything that is not a
          // border: a ring, an inset bar, an underline.
          const edgeOfFill = property.startsWith('border') && stateFill && !dashed
            && /^--(status-|accent)/.test(token);
          // Chrome boundaries (the ring, the control and panel edges) sit on
          // the page as well as on their own fill.
          const chrome = /^--(focus-ring|scrollbar-thumb|border-)/.test(token);
          const surfaces = isFill
            ? surfacesOf({ ...rule, declarations: new Map([...rule.declarations].filter(([p]) => !/^background/.test(p))) })
            : chrome ? Array.from(new Set([...SURFACES, ...surfacesOf(rule)])) : surfacesOf(rule);
          for (const surface of surfaces) {
            if (surface === token) continue;
            const pair: Pair = [token, surface];
            (edgeOfFill ? decorative : identifying).push(pair);
            where.set(key(pair), [...(where.get(key(pair)) ?? []), `${rule.file}: ${rule.selector} { ${property} }`]);
          }
        }
      }
    }
    return { identifying, decorative, where };
  }

  const painted = paintedText();
  const boundaries = paintedBoundaries();
  const unique = (pairs: Pair[]) => Array.from(new Map(pairs.map((p) => [key(p), p])).values());
  const missing = (pairs: Pair[], table: Set<string>, where: Map<string, string[]>) =>
    unique(pairs).filter((p) => !table.has(key(p))).map((p) => `${key(p)}  <- ${where.get(key(p))?.join(' | ')}`);

  it('parsed the stylesheets rather than an empty string', () => {
    // A regex that silently matched nothing would make every assertion below
    // vacuous; these floors are well under the real counts.
    expect(RULES.length).toBeGreaterThan(300);
    expect(unique(painted.text).length).toBeGreaterThan(40);
    expect(unique(boundaries.identifying).length).toBeGreaterThan(20);
    expect(new Set(painted.text.map(([t]) => t)).size).toBeGreaterThanOrEqual(10);
  });

  it('resolves a painted token to the surface the stylesheet gives it', () => {
    // Spot checks of the resolution order, so a change to it is visible.
    const find = (file: string, selector: string) => RULES.find((r) => r.file === file && r.selector === selector)!;
    expect(surfacesOf(find('components.css', '.badge--ok'))).toEqual(['--status-ok-soft']);
    expect(surfacesOf(find('components.css', '.alert--error > .icon'))).toEqual(['--status-err-soft']);
    expect(surfacesOf(find('layout.css', '.sidebar__nav a.active .icon'))).toEqual(['--accent-soft']);
    expect(surfacesOf(find('components.css', '.btn--ghost'))).toEqual(expect.arrayContaining(SURFACES));
    expect(surfacesOf(find('base.css', '.faint'))).toEqual(SURFACES);
    expect(surfacesOf(find('components.css', '.file-input[data-disabled] .file-input__name'))).toEqual(['--control-disabled-bg']);
  });

  it('checks every token painted as text at 4.5:1 on every surface it can land on', () => {
    expect(missing(painted.text, TEXT, painted.where)).toEqual([]);
  });

  it('checks every disabled text pair at the 3:1 floor', () => {
    expect(missing(painted.disabled, new Set([...DISABLED, ...NON_TEXT]), painted.where)).toEqual([]);
  });

  it('checks every glyph painted through color at 3:1', () => {
    // A glyph that is also in the 4.5:1 table is covered by the stricter test.
    expect(missing(painted.glyph, new Set([...NON_TEXT, ...TEXT]), painted.where)).toEqual([]);
  });

  it('checks every identifying boundary, ring and indicator at 3:1', () => {
    expect(missing(boundaries.identifying, NON_TEXT, boundaries.where)).toEqual([]);
  });

  it('exempts a border only where the same rule paints the state as a fill', () => {
    // The decorative set must be exactly the edges of filled status regions:
    // an edge whose rule paints no fill has nothing else to carry the state.
    for (const [token, surface] of unique(boundaries.decorative)) {
      expect(token, `${token} on ${surface}`).toMatch(/^--(status-[a-z]+-border|status-[a-z]+|accent|accent-strong)$/);
      expect(surface, `${token} on ${surface}`).toMatch(/^--(status-[a-z]+-soft|accent-soft|accent)$/);
    }
    // And a dashed stale edge is never among them.
    expect(unique(boundaries.decorative).some(([t]) => t === '--status-stale-border')).toBe(false);
  });

  it('enumerates only pairs that resolve to colours', () => {
    for (const pair of [...painted.text, ...painted.glyph, ...painted.disabled, ...boundaries.identifying]) {
      expect(() => contrast(pair[0], pair[1]), key(pair)).not.toThrow();
    }
  });
});

describe('evidence and spatial legibility', () => {
  const EVIDENCE = ['--evidence-box', '--evidence-track', '--geo-zone', '--geo-line', '--geo-dir-ab', '--geo-dir-ba'];

  it.each(EVIDENCE)('%s reads against the halo every overlay layer carries', (token) => {
    // Overlays are drawn over footage the product does not control, so the halo
    // is the only background they can rely on.
    expect(contrast(token, '--evidence-matte')).toBeGreaterThanOrEqual(3);
  });

  it('relies on the halo, not the hue, for legibility over bright footage', () => {
    // An evidence hue identifies a role; it cannot also be guaranteed to
    // contrast with footage the product does not control. --evidence-box over a
    // white frame is about 2.7:1. The halo is what makes the mark visible
    // there, which is why section 8.3 requires it on every overlay layer rather
    // than leaving each surface to solve it locally.
    const overWhite = (token: string) => {
      const [hi, lo] = [relativeLuminance(resolve(token)), relativeLuminance('#ffffff')].sort((a, b) => b - a);
      return (hi + 0.05) / (lo + 0.05);
    };
    expect(overWhite('--evidence-box')).toBeLessThan(3);
    expect(overWhite('--evidence-matte')).toBeGreaterThanOrEqual(3);
    // And the halo has a declared blur, so "the halo" is a real treatment
    // rather than a token nothing applies.
    expect(resolve('--evidence-halo-blur')).toBe('1.5px');
  });

  it('keeps every evidence hue distinct from the selection accent', () => {
    const accent = resolve('--accent').toLowerCase();
    for (const token of EVIDENCE) {
      expect(resolve(token).toLowerCase()).not.toBe(accent);
    }
  });

  it('gives each evidence role its own value', () => {
    const values = EVIDENCE.map((t) => resolve(t).toLowerCase());
    expect(new Set(values).size).toBe(EVIDENCE.length);
  });
});

/**
 * Specification decision 2c, recomputed rather than transcribed.
 *
 * The scale is defended by three properties, and each is asserted from the
 * tokens themselves so that editing a stop fails here rather than quietly
 * changing what a density map means.
 */
describe('heatmap scale (decision 2c)', () => {
  const HEAT = ['--heat-0', '--heat-1', '--heat-2', '--heat-3', '--heat-4'];

  it('rises monotonically in luminance, so density reads without colour at all', () => {
    // This is the property that survives greyscale printing and every form of
    // colour blindness: the map still says "more here than there".
    const luminances = HEAT.map((token) => relativeLuminance(resolve(token)));
    for (let index = 1; index < luminances.length; index++) {
      expect(luminances[index]).toBeGreaterThan(luminances[index - 1]);
    }
  });

  it('spans enough range for the ends to mean opposite things', () => {
    expect(contrast('--heat-4', '--heat-0')).toBeGreaterThan(10);
  });

  it('clears 3:1 at the top against every reference frame once the scrim is applied', () => {
    // Without the scrim the top of any light-ended scale vanishes on bright
    // footage, at about 1:1. The scrim is therefore part of the decision.
    const scrimmed = (frame: string) => {
      const darkened = frame.replace('#', '').match(/.{2}/g)!
        .map((pair) => Math.round(parseInt(pair, 16) * 0.5).toString(16).padStart(2, '0'))
        .join('');
      const [hi, lo] = [relativeLuminance(resolve('--heat-4')), relativeLuminance('#' + darkened)]
        .sort((a, b) => b - a);
      return (hi + 0.05) / (lo + 0.05);
    };

    for (const frame of ['#e8e6e0', '#14161a', '#1d4ed8', '#6b7280']) {
      expect(scrimmed(frame)).toBeGreaterThanOrEqual(3);
    }

    expect(resolve('--heat-scrim')).toBe('rgb(0 0 0 / 50%)');
  });

  it('is not a red-to-green scale and borrows no frozen evidence role', () => {
    const roles = ['--evidence-box', '--evidence-track', '--geo-zone', '--geo-line',
      '--geo-dir-ab', '--geo-dir-ba', '--evidence-crossing'];
    const evidence = new Set(roles.map((token) => resolve(token).toLowerCase()));
    for (const token of HEAT) {
      expect(evidence.has(resolve(token).toLowerCase())).toBe(false);
    }

    // Low chroma is the whole mechanism: every stop stays near its own grey, so
    // it competes with no hue and cannot read as a red/green judgement.
    for (const token of HEAT) {
      const [r, g, b] = rgb(resolve(token));
      expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThan(60);
    }
  });
});
