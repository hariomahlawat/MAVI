import { describe, expect, it } from 'vitest';
import baseCss from '../styles/base.css?raw';
import componentsCss from '../styles/components.css?raw';
import featuresCss from '../styles/features.css?raw';
import layoutCss from '../styles/layout.css?raw';
import tokensCss from '../styles/tokens.css?raw';
import workspaceCss from '../styles/workspace.css?raw';

/**
 * The S1 foundation's retirements stay retired (Stage 3.5 S1e, register D9).
 *
 * These are architectural facts about the source tree, not formatting: a
 * retired component is not imported, a retired selector is not styled, a
 * Ledger's loading geometry comes from the one Ledger contract, and a surface
 * reaches the shared workspace through its public barrel. Each was true only by
 * convention before; this file is what makes a reintroduction fail.
 */

const SOURCES = import.meta.glob('/src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const THIS_FILE = '/src/app/foundation.test.ts';
const sources = Object.entries(SOURCES).filter(([path]) => path !== THIS_FILE);

const STYLESHEETS: Record<string, string> = {
  'base.css': baseCss,
  'components.css': componentsCss,
  'features.css': featuresCss,
  'layout.css': layoutCss,
  'tokens.css': tokensCss,
  'workspace.css': workspaceCss,
};

const withoutComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '');

describe('S1 foundation retirements (D9)', () => {
  it('retires PageHeader and Tabs: no file, no import (§27 Retire)', () => {
    const paths = Object.keys(SOURCES);
    expect(paths.filter((path) => /\/(PageHeader|Tabs)\.tsx$/.test(path))).toEqual([]);
    for (const [path, source] of sources) {
      expect(source, path).not.toMatch(/components\/(PageHeader|Tabs)['"]/);
    }
  });

  it('styles none of the retired selectors, under any spelling of their own name', () => {
    const RETIRED = [
      'rail-layout', 'field--inline', 'search-filter-grid', 'field-help',
      'panel--form', 'table--dense', 'table--compact', 'page-header', 'tabs',
    ];
    for (const [file, css] of Object.entries(STYLESHEETS)) {
      const rules = withoutComments(css);
      for (const name of RETIRED) {
        // `.tabs` and `.page-header__actions` are the selector; `.field__help`
        // (Field's own element) is a different name and is not matched.
        expect(rules, `${file}: .${name}`).not.toMatch(new RegExp(`\\.${name}(?![a-z0-9-])`));
        expect(rules, `${file}: .${name}__*`).not.toMatch(new RegExp(`\\.${name}__`));
      }
    }
  });

  it('references no retired class name from a component either', () => {
    for (const [path, source] of sources) {
      expect(source, path).not.toMatch(
        /[\s'"`](table--compact|table--dense|page-header|rail-layout|field--inline|field-help|panel--form|search-filter-grid)(?=[\s'"`]|__)/,
      );
    }
  });
});

describe('one Ledger loading contract (D3, §38)', () => {
  it('gives every standard Ledger the shared skeleton, which reserves the table header', () => {
    for (const page of [
      '/src/features/cameras/CamerasPage.tsx',
      '/src/features/videos/VideosPage.tsx',
      '/src/features/processing/ProcessingQueuePage.tsx',
    ]) {
      const source = SOURCES[page];
      expect(source, page).toBeDefined();
      expect(source, page).toContain('skeleton={LEDGER_SKELETON}');
      expect(source, page).not.toMatch(/skeleton=\{\{/);
    }
  });
});

describe('the shared workspace is reached through its barrel', () => {
  it('imports no workspace internal from outside the workspace', () => {
    for (const [path, source] of sources) {
      if (path.startsWith('/src/shared/workspace/')) continue;
      // Any spelling of the path: `../../shared/workspace/X` from a feature,
      // `../workspace/X` from a sibling under shared.
      expect(source, path).not.toMatch(/from ['"][^'"]*\/workspace\/[A-Za-z]/);
    }
  });
});
