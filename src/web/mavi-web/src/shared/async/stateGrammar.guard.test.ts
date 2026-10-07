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

/**
 * Every JSX `<img …>` opening tag in a source, through its closing `>` — an
 * arrow function's `=>` inside an attribute is not the end of the tag.
 */
function imgTags(source: string): string[] {
  const tags: string[] = [];
  for (const match of source.matchAll(/<img\b/g)) {
    let depth = 0;
    let end = match.index ?? 0;
    for (; end < source.length; end += 1) {
      const ch = source[end];
      if (ch === '{') depth += 1;
      else if (ch === '}') depth -= 1;
      else if (ch === '>' && depth === 0) break;
    }
    tags.push(source.slice(match.index, end + 1));
  }
  return tags;
}

function hasFallback(tag: string): boolean {
  return /\bonError=/.test(tag);
}

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
    const tags = productionSources.flatMap(([path, source]) => imgTags(source).map((tag) => ({ path, tag })));
    // Non-vacuous: the scanner must actually find the product's images.
    expect(tags.length).toBeGreaterThan(0);
    const offenders = tags.filter(({ tag }) => !hasFallback(tag)).map(({ path, tag }) => `${path}: ${tag.slice(0, 80)}`);
    expect(offenders).toEqual([]);
  });

  it('flags an <img> without onError and passes one with it (scanner self-check)', () => {
    const bare = imgTags('<span><img src="x" /></span>');
    const guarded = imgTags('<span><img src="x" onError={() => setFailed(true)} /></span>');
    expect(bare).toHaveLength(1);
    expect(hasFallback(bare[0])).toBe(false);
    expect(guarded).toHaveLength(1);
    expect(hasFallback(guarded[0])).toBe(true);
    // An element whose name merely starts with "img" is not an image.
    expect(imgTags('<imgx src="x" />')).toHaveLength(0);
  });

  it('names missing evidence in one vocabulary', () => {
    const offenders = productionSources
      .filter(([, source]) => /['">]\s*(No evidence|Evidence unavailable|Image unavailable|Evidence image unavailable\.)\s*['"<]/.test(source))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});
