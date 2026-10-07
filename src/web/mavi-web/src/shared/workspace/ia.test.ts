import { describe, expect, it } from 'vitest';
import {
  DESTINATIONS,
  SECTIONS,
  SURFACES,
  crumbsFor,
  destinationForKey,
  documentTitleFor,
  ownerOf,
  type SurfaceId,
} from './ia';

/**
 * §5 (amended in v2.0): one IA map, from which the rail, the crumb and the
 * title are all derived. These assert the map's own invariants; the shell and
 * the surfaces are asserted against it in `AppShell.test.tsx`.
 */
describe('the IA map', () => {
  it('records every §5 surface with the frozen owner', () => {
    const owners = Object.fromEntries(
      (Object.keys(SURFACES) as SurfaceId[]).map((surface) => [surface, ownerOf(surface)?.label ?? null]),
    );
    expect(owners).toEqual({
      overview: 'Overview',
      cameras: 'Cameras',
      scene: 'Cameras',
      analytics: 'Cameras',
      videos: 'Videos',
      import: 'Import',
      processing: 'Processing',
      'processing-detail': 'Processing',
      search: 'Search',
      review: 'Search',
      'not-found': null,
    });
  });

  it('groups the rail Operate then Investigate, in workflow order', () => {
    expect(SECTIONS.map((section) => [section.label, section.destinations.map((entry) => entry.label)])).toEqual([
      ['Operate', ['Overview', 'Cameras', 'Videos', 'Import', 'Processing']],
      ['Investigate', ['Search']],
    ]);
  });

  it('gives every destination one unique, mnemonic g key', () => {
    const keys = DESTINATIONS.map((entry) => entry.key);
    expect(new Set(keys).size).toBe(keys.length);
    for (const entry of DESTINATIONS) {
      expect(entry.key).toMatch(/^[a-z]$/);
      expect(entry.label.toLowerCase().startsWith(entry.key)).toBe(true);
      expect(destinationForKey(entry.key)).toBe(entry);
      expect(destinationForKey(entry.key.toUpperCase())).toBe(entry);
    }
    expect(destinationForKey('x')).toBeNull();
  });

  it('derives every frozen §5 crumb trail', () => {
    const labels = (surface: SurfaceId, object?: string) => crumbsFor(surface, object ? { object: { label: object } } : {}).map((crumb) => crumb.label);
    expect(labels('overview')).toEqual(['Overview']);
    expect(labels('cameras')).toEqual(['Cameras']);
    expect(labels('scene', 'CAM-01')).toEqual(['Cameras', 'CAM-01', 'Scene']);
    expect(labels('analytics', 'CAM-01')).toEqual(['Cameras', 'CAM-01', 'Analytics']);
    expect(labels('videos')).toEqual(['Videos']);
    expect(labels('import')).toEqual(['Import']);
    expect(labels('processing')).toEqual(['Processing']);
    expect(labels('processing-detail', 'gate.mp4')).toEqual(['Processing', 'gate.mp4']);
    expect(labels('search')).toEqual(['Search']);
    expect(labels('review', 'gate.mp4')).toEqual(['Search', 'gate.mp4', 'Review']);
    expect(labels('not-found')).toEqual(['Not found']);
  });

  it('makes the root crumb the rail label, links every crumb but the last, and lets Review return to its Investigation', () => {
    const scene = crumbsFor('scene', { object: { label: 'CAM-01' } });
    expect(scene[0]).toEqual({ label: 'Cameras', to: '/cameras' });
    expect(scene.at(-1)).toEqual({ label: 'Scene' });
    expect(crumbsFor('cameras')).toEqual([{ label: 'Cameras' }]);

    const from = '/search?objectClass=Person&track=t';
    expect(crumbsFor('review', { object: { label: 'gate.mp4' }, rootTo: from })[0]).toEqual({ label: 'Search', to: from });
    expect(crumbsFor('review', { object: { label: 'gate.mp4' } })[0]).toEqual({ label: 'Search', to: '/search' });
  });

  it('has one document-title rule: most specific first, full identity, product last', () => {
    expect(documentTitleFor(crumbsFor('overview'))).toBe('Overview — MAVI');
    expect(documentTitleFor(crumbsFor('scene', { object: { label: 'NORTH-PERIMETER-GATE-CAM-00042 · North perimeter vehicle entrance, outer gate' } })))
      .toBe('Scene — NORTH-PERIMETER-GATE-CAM-00042 · North perimeter vehicle entrance, outer gate — Cameras — MAVI');
    expect(documentTitleFor(crumbsFor('not-found'))).toBe('Not found — MAVI');
  });
});

/**
 * The map is the only place the static vocabulary is spelled. A page that
 * rendered its own breadcrumb trail, or a second route-to-title table, would
 * reintroduce the drift the audit found (F4).
 */
const SOURCES = import.meta.glob('/src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const PRODUCTION = Object.entries(SOURCES).filter(([path]) => !/\.test\.tsx?$/.test(path) && !path.startsWith('/src/test/'));

describe('no second IA table', () => {
  it('reads the production sources it guards', () => {
    expect(PRODUCTION.length).toBeGreaterThan(50);
    expect(PRODUCTION.some(([path]) => path.endsWith('/app/AppShell.tsx'))).toBe(true);
  });

  it('renders breadcrumbs only through the Context Bar and the shell', () => {
    const offenders = PRODUCTION
      .filter(([, source]) => /<Breadcrumbs\b/.test(source))
      .map(([path]) => path)
      .filter((path) => !path.endsWith('/shared/workspace/ContextBar.tsx') && !path.endsWith('/app/AppShell.tsx'));
    expect(offenders).toEqual([]);
  });

  // A regex on the path paired with a title — the pre-S1d shell's own shape.
  const PATH_TABLE = /sectionTitle|\[\s*\/\^\\\//;

  it('recognises the table it forbids', () => {
    expect('const sectionTitles: Array<[RegExp, string]> = [').toMatch(PATH_TABLE);
    expect(String.raw`  [/^\/review\//, 'Review'],`).toMatch(PATH_TABLE);
    expect("{ path: 'cameras', element: <CamerasPage />, handle: { surface: 'cameras' } }").not.toMatch(PATH_TABLE);
  });

  it('keeps no path-pattern table of section names', () => {
    const offenders = PRODUCTION.filter(([, source]) => PATH_TABLE.test(source)).map(([path]) => path);
    expect(offenders).toEqual([]);
  });

  it('names every route surface in the router, and only surfaces the map knows', () => {
    const router = SOURCES['/src/app/router.tsx'];
    const named = [...router.matchAll(/surface: '([a-z-]+)'/g)].map((match) => match[1]);
    expect(new Set(named)).toEqual(new Set(Object.keys(SURFACES)));
  });
});
