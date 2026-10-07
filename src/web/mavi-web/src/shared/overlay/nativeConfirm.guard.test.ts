import { describe, expect, it } from 'vitest';

/**
 * §15: consequential decisions are made in the product's Dialog. The browser's
 * native confirm cannot state a consequence in product language, and browsers
 * offer to suppress it, silently removing the safeguard. No production source
 * may call it, under any spelling that reaches the global.
 */
const SOURCES = import.meta.glob('/src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const PRODUCTION = Object.entries(SOURCES).filter(([path]) => !/\.test\.tsx?$/.test(path) && !path.startsWith('/src/test/'));
/** Comments may name the API they replaced; only code is guarded. */
const code = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const NATIVE = /\b(?:window|globalThis|self)\s*(?:\.\s*confirm\b|\[\s*['"`]confirm['"`]\s*\])|(?<![.\w])confirm\s*\(/;

describe('native confirmation guard', () => {
  it('reads the production sources it guards', () => {
    expect(PRODUCTION.length).toBeGreaterThan(50);
    expect(PRODUCTION.some(([path]) => path.endsWith('/useUnsavedChangesGuard.tsx'))).toBe(true);
    expect(PRODUCTION.some(([path]) => path.endsWith('/SceneEditorPage.tsx'))).toBe(true);
  });

  it('recognises every spelling it forbids, and not the product Dialog', () => {
    for (const bad of ['window.confirm("x")', 'globalThis.confirm(m)', "window['confirm'](m)", 'if (confirm(m)) go();']) {
      expect(bad).toMatch(NATIVE);
    }
    for (const fine of ['onConfirm()', 'confirmLabel="Discard"', 'blocker.proceed?.()', 'const confirmed = true;', 'props.confirm(x)']) {
      expect(fine).not.toMatch(NATIVE);
    }
    expect(code('/** replaces `window.confirm` */\n// window.confirm(x)\nrun();')).not.toMatch(NATIVE);
    expect(code('/** doc */\nif (window.confirm(m)) go();')).toMatch(NATIVE);
  });

  it('finds no native confirm in production code', () => {
    const offenders = PRODUCTION.filter(([, source]) => NATIVE.test(code(source))).map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});
