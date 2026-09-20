import { describe, expect, it } from 'vitest';
import tokensCss from './tokens.css?raw';

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
  return indirect ? resolve(indirect[1], seen) : value;
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

describe('text contrast (4.5:1)', () => {
  it.each([
    ['--text-primary', '--surface-app'],
    ['--text-primary', '--surface-base'],
    ['--text-primary', '--surface-raised'],
    ['--text-secondary', '--surface-app'],
    ['--text-secondary', '--surface-base'],
    ['--text-secondary', '--surface-raised'],
    ['--text-muted', '--surface-app'],
    ['--text-muted', '--surface-base'],
    ['--text-muted', '--surface-raised'],
    ['--accent-text', '--surface-app'],
    ['--accent-text', '--surface-base'],
    ['--status-ok', '--status-ok-soft'],
    ['--status-warn', '--status-warn-soft'],
    ['--status-err', '--status-err-soft'],
    ['--status-info', '--status-info-soft'],
    ['--status-neutral', '--status-neutral-soft'],
  ])('%s on %s reaches AA', (fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5);
  });

  it('paints text on --accent-strong, never on --accent', () => {
    // The defect named in section 8.1: --accent cannot legally carry text.
    expect(contrast('--text-on-accent', '--accent-strong')).toBeGreaterThanOrEqual(4.5);
    expect(contrast('--text-on-accent', '--accent')).toBeLessThan(4.5);
  });
});

describe('non-text contrast (3:1)', () => {
  it.each(SURFACES)('the focus ring is visible on %s', (surface) => {
    expect(contrast('--focus-ring', surface)).toBeGreaterThanOrEqual(3);
  });

  it.each(['--accent', '--accent-strong', '--accent-hover'])(
    'the focus ring is visible on the primary action %s',
    (surface) => {
      expect(contrast('--focus-ring', surface)).toBeGreaterThanOrEqual(3);
    },
  );

  it.each(SURFACES)('an interactive control boundary is visible on %s', (surface) => {
    expect(contrast('--border-control', surface)).toBeGreaterThanOrEqual(3);
  });

  it.each(SURFACES)('the hover/emphasis boundary is visible on %s', (surface) => {
    expect(contrast('--border-strong', surface)).toBeGreaterThanOrEqual(3);
  });

  it('leaves decorative dividers below the interactive threshold on purpose', () => {
    // Section 11: a border that only groups content is not required to reach
    // 3:1, and raising every hairline to it would turn the product into a grid
    // of bright lines. This asserts the distinction is real, not accidental.
    expect(contrast('--border-subtle', '--surface-base')).toBeLessThan(3);
    expect(contrast('--border-control', '--surface-base')).toBeGreaterThanOrEqual(3);
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
