import { describe, expect, it } from 'vitest';
import baseCss from './base.css?raw';
import componentsCss from './components.css?raw';
import featuresCss from './features.css?raw';
import layoutCss from './layout.css?raw';
import tokensCss from './tokens.css?raw';
import workspaceCss from './workspace.css?raw';
import tokensTestSource from './tokens.test.ts?raw';

/**
 * Token-architecture integrity.
 *
 * These are the assertions that make the design system difficult to misuse.
 * The baseline shipped a `var(--focus)` that was never declared, so keyboard
 * focus on a search result row was invisible in production while every unit
 * test passed — a defect no DOM test could have caught. This file catches that
 * class of defect at the source.
 */

/** Every stylesheet the application ships, read as the bundler sees it. */
const SHEETS: Record<string, string> = {
  'base.css': baseCss,
  'components.css': componentsCss,
  'features.css': featuresCss,
  'layout.css': layoutCss,
  'tokens.css': tokensCss,
  'workspace.css': workspaceCss,
};
const cssFiles = Object.keys(SHEETS);
const read = (f: string) => SHEETS[f];

const tokens = tokensCss;
const featureCss = cssFiles.filter((f) => f !== 'tokens.css');

/** Custom properties declared anywhere in tokens.css. */
function declaredTokens(): Set<string> {
  return new Set(Array.from(tokens.matchAll(/^\s*(--[a-z0-9-]+)\s*:/gm), (m) => m[1]));
}

/** Custom properties referenced through var() in a stylesheet. */
function referencedTokens(css: string): string[] {
  return Array.from(css.matchAll(/var\(\s*(--[a-z0-9-]+)/g), (m) => m[1]);
}

/** Strip comments so prose about colours is not mistaken for a declaration. */
function withoutComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

describe('token integrity', () => {
  it('every var() reference in every stylesheet resolves to a declared token', () => {
    const declared = declaredTokens();
    const unresolved: string[] = [];
    for (const file of cssFiles) {
      for (const name of referencedTokens(read(file))) {
        if (!declared.has(name)) unresolved.push(`${file}: ${name}`);
      }
    }
    expect(unresolved).toEqual([]);
  });

  it('declares --focus-ring and never the undefined --focus of the baseline', () => {
    const declared = declaredTokens();
    expect(declared.has('--focus-ring')).toBe(true);
    expect(declared.has('--focus-ring-inner')).toBe(true);
    for (const file of cssFiles) {
      expect(referencedTokens(read(file))).not.toContain('--focus');
    }
  });

  it('declares every semantic group the specification requires', () => {
    const declared = declaredTokens();
    const required = [
      'surface-app', 'surface-base', 'surface-raised', 'surface-inset', 'surface-overlay',
      'border-subtle', 'border-panel', 'border-control', 'border-strong',
      'text-primary', 'text-secondary', 'text-muted', 'text-on-accent',
      'accent', 'accent-strong', 'accent-soft',
      'focus-ring',
      'status-ok', 'status-info', 'status-warn', 'status-err', 'status-neutral',
      'status-stale', 'status-unavailable', 'status-unavailable-hatch',
      'evidence-box', 'evidence-track', 'geo-zone', 'geo-line', 'geo-dir-ab', 'geo-dir-ba',
      'evidence-halo', 'evidence-matte',
      's-1', 'r-1', 'fs-0', 'control-h', 'stroke-hair', 'dur', 'z-sticky',
      // Stage 3.5 S1a (specification v2.0 sections 12, 14.1, 36): disabled is
      // a surface and a text colour, prose and alerts have a readable measure,
      // the scrollbar and the skeleton each have their own roles, and a
      // skeleton row shares the Ledger row pitch it precedes.
      'control-disabled-bg', 'control-disabled-border', 'text-disabled',
      'measure', 'alert-max', 'table-row-h',
      'scrollbar-thumb', 'scrollbar-track', 'skeleton-bg',
    ];
    const missing = required.filter((name) => !declared.has(`--${name}`));
    expect(missing).toEqual([]);
  });

  it('declares one role per concept, not a synonym per component', () => {
    // Section 7: a component token exists only where one component is
    // legitimately different across archetypes. The disabled state is one
    // state everywhere, so there is exactly one disabled surface and one
    // disabled text role, and the opacity the baseline used is gone.
    const declared = declaredTokens();
    expect(declared.has('--disabled-opacity')).toBe(false);
    const disabledRoles = Array.from(declared).filter((name) => /disabled/.test(name));
    expect(disabledRoles.sort()).toEqual(['--control-disabled-bg', '--control-disabled-border', '--text-disabled']);
    for (const file of cssFiles) {
      expect(referencedTokens(read(file))).not.toContain('--disabled-opacity');
    }
  });

  it('keeps primitives out of the stylesheets components consume', () => {
    const leaked: string[] = [];
    for (const file of featureCss) {
      for (const name of referencedTokens(read(file))) {
        if (name.startsWith('--p-')) leaked.push(`${file}: ${name}`);
      }
    }
    expect(leaked).toEqual([]);
  });
});

describe('feature CSS carries no design literals', () => {
  it('declares no colour outside the token layer', () => {
    const offenders: string[] = [];
    for (const file of featureCss) {
      const css = withoutComments(read(file));
      for (const line of css.split('\n')) {
        if (/#[0-9a-fA-F]{3,8}\b|(?<![\w-])rgba?\(|(?<![\w-])hsla?\(/.test(line)) {
          offenders.push(`${file}: ${line.trim()}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('declares no radius literal', () => {
    const offenders: string[] = [];
    for (const file of featureCss) {
      for (const line of withoutComments(read(file)).split('\n')) {
        const match = line.match(/border-radius:\s*([^;]+)/);
        if (match && /\d/.test(match[1]) && !match[1].includes('var(--r-')) {
          offenders.push(`${file}: ${line.trim()}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  /**
   * Spacing is the fourth literal the UI-1 acceptance criterion names, and the
   * hardest to check: a stylesheet is full of legitimate numbers. The rule here
   * is deliberately narrow — a *length literal in a spacing property* — so that
   * panel widths, control heights, grid tracks, breakpoints and glyph geometry
   * stay plain numbers, which is what they are.
   *
   * A genuinely structural value in a spacing property (a negative margin doing
   * border alignment, padding that clears a painted glyph) is allowed only when
   * the rule says why, in a `structural:` comment on or just above it. The cost
   * of the exception is having to justify it in writing.
   */
  const SPACING_PROPERTY = String.raw`padding|padding-(?:top|right|bottom|left|inline|block)(?:-start|-end)?`
    + String.raw`|margin|margin-(?:top|right|bottom|left|inline|block)(?:-start|-end)?`
    + String.raw`|gap|row-gap|column-gap|inset|inset-(?:inline|block)(?:-start|-end)?`;

  it('declares no spacing literal in a spacing property', () => {
    const offenders: string[] = [];
    for (const file of featureCss) {
      const raw = read(file);
      // Blank comments out so prose about pixels is not read as a declaration,
      // while keeping every offset and line number identical to the source.
      const scannable = raw.replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, ' '));
      const declaration = new RegExp(String.raw`(?<![-\w])(${SPACING_PROPERTY})\s*:\s*([^;{}]+)`, 'g');

      for (const match of scannable.matchAll(declaration)) {
        const value = match[2];
        if (!/-?\d*\.?\d+(px|rem|em)\b/.test(value)) continue;

        // A structural value is allowed only where the source says why. Look at
        // the declaration's own line plus the comment immediately preceding it:
        // anchoring to the line start matters because a rule may be written on
        // one long line, putting the declaration far from its comment.
        const at = match.index ?? 0;
        const lineStart = raw.lastIndexOf('\n', at) + 1;
        const lineEnd = raw.indexOf('\n', at) === -1 ? raw.length : raw.indexOf('\n', at);
        const justification = raw.slice(Math.max(0, lineStart - 320), lineEnd);
        if (justification.includes('structural:')) continue;

        const line = raw.slice(0, at).split('\n').length;
        offenders.push(`${file}:${line}: ${match[1]}: ${value.trim()}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('declares no transition or animation duration literal', () => {
    const offenders: string[] = [];
    for (const file of featureCss) {
      for (const line of withoutComments(read(file)).split('\n')) {
        if (!/(transition|animation)[^;:]*:/.test(line)) continue;
        // The reduced-motion override zeroes every duration and must stay literal.
        if (line.includes('0ms !important')) continue;
        if (/\d+\s*m?s\b/.test(line) && !line.includes('var(--dur')) {
          offenders.push(`${file}: ${line.trim()}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});

/**
 * Section 12 freezes one interaction rule that is easy to break by accident and
 * invisible to every other test: **text colour MUST NOT change on hover.** A
 * hover that repaints text reads as a state change rather than an affordance,
 * and on a status or sort indicator it actively lies.
 *
 * Until Stage 3.5 S1a the rule was asserted against an inventory of eight
 * inherited violations in shared controls, tolerated under the UI-1 → UI-5
 * transitional clause. That clause is closed (specification v2.0 section 34.1)
 * and S1a corrected all eight, so the inventory is empty and the ban is
 * blanket: a hover rule that declares `color` fails, whatever it is.
 */
describe('hover never repaints text (section 12)', () => {

  it('introduces no new hover rule that changes text colour', () => {
    const offenders: string[] = [];
    for (const file of cssFiles) {
      const css = withoutComments(read(file));
      // Rule bodies, paired with the selector that opens them.
      for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
        const selector = match[1].trim().replace(/\s+/g, ' ');
        if (!selector.includes(':hover')) continue;
        // `border-color` and `background-color` are allowed hover cues; only a
        // bare `color` declaration repaints the text itself.
        if (!/(^|;)\s*color\s*:/.test(match[2])) continue;
        offenders.push(`${file}: ${selector}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('has no allowlist at all (register row D1)', () => {
    // The ban is blanket: there is no inventory of tolerated selectors left in
    // this file for a later change to quietly extend — the only array literal
    // of selectors in the hover block would be one.
    const hoverBlock = tokensTestSource.slice(tokensTestSource.indexOf("describe('hover never repaints text"));
    const block = hoverBlock.slice(0, hoverBlock.indexOf('\n});'));
    expect(block).not.toMatch(/const\s+[A-Z_]+\s*(:\s*string\[\])?\s*=\s*\[/);
  });

  it('leaves the sort indicator its own non-hover state colour', () => {
    const css = withoutComments(read('components.css'));
    // The active column is still distinguished, and by more than colour: the
    // glyph in SortableColumn carries it too.
    expect(css).toMatch(/\[aria-sort="ascending"\][^{]*\{[^}]*color:/);
  });
});

describe('colour roles do not borrow across namespaces', () => {
  const features = read('features.css');

  it('never paints resting scene geometry with the UI accent', () => {
    // The resting zone fill is the case the specification calls out by name: a
    // resting zone and a selected row must not look alike.
    const restingZone = features.match(/\.scene-zone polygon \{[\s\S]*?\}/)?.[0] ?? '';
    expect(restingZone).toContain('--geo-zone');
    expect(restingZone).not.toContain('--accent');
  });

  it('never uses a status hue for a crossing direction', () => {
    const crossings = Array.from(
      features.matchAll(/\.scene-line__crossing--(atob|btoa)[^{]*\{([^}]*)\}/g),
      (m) => m[2],
    );
    expect(crossings.length).toBeGreaterThan(0);
    for (const rule of crossings) {
      expect(rule).not.toMatch(/--status-(ok|warn|err|info)\b/);
      expect(rule).toMatch(/--geo-dir-(ab|ba)/);
    }
  });

  it('keeps the evidence namespace out of UI status roles and vice versa', () => {
    const declaredEvidence = tokens.match(/--(evidence|geo)-[a-z0-9-]+:\s*var\(([^)]+)\)/g) ?? [];
    for (const decl of declaredEvidence) {
      expect(decl).not.toMatch(/var\(--status-/);
      expect(decl).not.toMatch(/var\(--accent/);
    }
  });
});

/**
 * Stage 3.5 S1a control-state contract (specification v2.0 sections 12, 13,
 * 36.3 and 38), asserted at the source: these are rules about how a state is
 * painted, which no DOM test in jsdom can see.
 */
describe('control states are painted by tokens, not by opacity (section 12)', () => {
  const components = withoutComments(read('components.css'));

  /**
   * The declaration block of the first rule whose selector list contains
   * `selector`, or, with `exact`, whose selector list is exactly `selector`.
   */
  function ruleFor(selector: string, exact = false): string {
    const match = Array.from(components.matchAll(/([^{}]+)\{([^{}]*)\}/g)).find((m) => {
      const list = m[1].trim().replace(/\s+/g, ' ');
      return exact ? list === selector : list.includes(selector);
    });
    if (!match) throw new Error(`no rule for ${selector}`);
    return match[2];
  }

  it('paints a disabled button with the disabled surface, border and text', () => {
    const rule = ruleFor('.btn:disabled');
    expect(rule).toContain('var(--control-disabled-bg)');
    expect(rule).toContain('var(--control-disabled-border)');
    expect(rule).toContain('var(--text-disabled)');
    expect(rule).toContain('not-allowed');
    expect(rule).not.toMatch(/opacity/);
  });

  it('paints a disabled input the same way', () => {
    const rule = ruleFor('input:disabled');
    expect(rule).toContain('var(--control-disabled-bg)');
    expect(rule).toContain('var(--text-disabled)');
    expect(rule).not.toMatch(/opacity/);
  });

  it('never dims a control with a whole-control opacity', () => {
    // Opacity remains legitimate for the activity pulse keyframes and for
    // evidence rendering; a *control* state rule must not use it.
    for (const match of components.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const selector = match[1].trim();
      if (!/:disabled|aria-disabled/.test(selector)) continue;
      expect(match[2], selector).not.toMatch(/opacity/);
    }
  });

  it('paints a pressed-and-disabled button as disabled, not as pressed', () => {
    // `.btn[aria-pressed="true"]` outranks `.btn:disabled` on specificity, so
    // the disabled rule must name the pressed case itself.
    const selector = Array.from(components.matchAll(/([^{}]+)\{([^{}]*)\}/g))
      .map((m) => m[1].trim().replace(/\s+/g, ' '))
      .find((s) => s.startsWith('.btn:disabled'));
    expect(selector).toContain('.btn[aria-pressed="true"]:disabled');
    expect(selector).toContain('.btn[aria-pressed="true"][aria-disabled="true"]');
  });

  it('does not offer a hover treatment to a disabled button', () => {
    for (const match of components.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const selector = match[1].trim();
      if (!selector.startsWith('.btn') || !selector.includes(':hover')) continue;
      expect(selector, selector).toContain(':not(:disabled)');
      expect(selector, selector).toContain(':not([aria-disabled="true"])');
    }
  });

  it('marks an invalid control and its message in one error hue', () => {
    const control = ruleFor('[aria-invalid="true"]');
    expect(control).toContain('var(--status-err)');
    expect(control).not.toContain('var(--status-warn)');
    expect(ruleFor('.field__error')).toContain('var(--status-err)');
  });

  it('keeps the invalid boundary under hover', () => {
    // The input hover rule outranks the invalid rule, so it must exclude it.
    for (const match of components.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const selector = match[1].trim();
      if (!/^(input|select)/.test(selector) || !selector.includes(':hover')) continue;
      expect(selector, selector).toContain(':not([aria-invalid="true"])');
    }
  });

  it('keeps the focus ring on an invalid control', () => {
    // The ring is an outline set in base.css; the invalid rule may add an
    // inset shadow but must not clear the outline or paint over the ring.
    const invalid = ruleFor('[aria-invalid="true"]');
    expect(invalid).not.toMatch(/outline/);
    const focused = ruleFor('[aria-invalid="true"]:focus-visible');
    expect(focused).toContain('var(--focus-ring-inner)');
  });

  it('caps an alert at the readable alert width', () => {
    expect(ruleFor('.alert', true)).toContain('var(--alert-max)');
  });

  it('gives a skeleton row the Ledger row pitch and no animation (sections 13, 38)', () => {
    const row = ruleFor('.skeleton__row', true);
    expect(row).toContain('var(--table-row-h)');
    expect(components).not.toMatch(/skeleton-pulse/);
    for (const match of components.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (!match[1].includes('.skeleton')) continue;
      expect(match[2], match[1].trim()).not.toMatch(/animation/);
    }
  });

  it('keeps an empty presentation content-sized', () => {
    const empty = ruleFor('.empty', true);
    expect(empty).toContain('align-content: start');
    expect(empty).not.toMatch(/min-height|height\s*:\s*100%/);
  });

  it('styles the platform scrollbar only in width and colour (section 36.3)', () => {
    const base = withoutComments(read('base.css'));
    expect(base).toMatch(/scrollbar-color:\s*var\(--scrollbar-thumb\)\s*var\(--scrollbar-track\)/);
    expect(base).toMatch(/scrollbar-width:\s*thin/);
    for (const file of cssFiles) {
      expect(read(file), file).not.toMatch(/::-webkit-scrollbar/);
    }
  });
});
