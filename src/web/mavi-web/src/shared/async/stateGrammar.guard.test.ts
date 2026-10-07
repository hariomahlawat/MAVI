import { describe, expect, it } from 'vitest';

/**
 * A narrow architectural guard (§14.1, §37.1).
 *
 * It does not ban `isPending` or `isError`: mutations, continuation loading and
 * supporting requests legitimately read them. It bans the three things that
 * only ever meant a surface was presenting a region's state by hand — importing
 * the loading presentation directly, writing a retry the alert does not carry,
 * and naming missing evidence in a word other than the one vocabulary — so a
 * surface cannot drift back to its own grammar without this failing.
 */

const sources = import.meta.glob('../../features/**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const productionSources = Object.entries(sources).filter(([path]) => !path.includes('.test.'));

describe('surfaces present async state only through StateRegion', () => {
  it('finds the feature sources it guards', () => {
    expect(productionSources.length).toBeGreaterThan(20);
  });

  it('never imports the loading presentation directly', () => {
    const offenders = productionSources
      .filter(([, source]) => /from '[^']*components\/LoadingState'/.test(source))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });

  it('never imports the retired boundary', () => {
    const offenders = productionSources
      .filter(([, source]) => /AsyncBoundary/.test(source))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });

  it('never writes a "Try again" retry inside an alert body', () => {
    const offenders = productionSources
      .filter(([, source]) => />\s*Try again\s*</.test(source))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });

  it('gives every evidence image a fallback, so a failed load is never a broken image', () => {
    const offenders: string[] = [];
    for (const [path, source] of productionSources) {
      for (const tag of source.match(/<img[^>]*>/g) ?? []) {
        if (!/onError=/.test(tag)) offenders.push(`${path}: ${tag.slice(0, 80)}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('names missing evidence in one vocabulary', () => {
    const offenders = productionSources
      .filter(([, source]) => /['">]\s*(No evidence|Evidence unavailable|Image unavailable|Evidence image unavailable\.)\s*['"<]/.test(source))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});
