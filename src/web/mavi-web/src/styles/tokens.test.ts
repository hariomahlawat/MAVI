import { describe, expect, it } from 'vitest';
import baseCss from './base.css?raw';
import componentsCss from './components.css?raw';
import featuresCss from './features.css?raw';
import layoutCss from './layout.css?raw';
import tokensCss from './tokens.css?raw';

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
    ];
    const missing = required.filter((name) => !declared.has(`--${name}`));
    expect(missing).toEqual([]);
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
