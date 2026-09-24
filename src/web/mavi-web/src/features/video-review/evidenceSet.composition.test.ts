import { describe, expect, it } from 'vitest';

/**
 * Architecture guards for the Evidence Set (S1.3 plan §8.1, §12.3).
 *
 * Read through Vite's glob, as `shared/evidence/composition.test.ts` does, so
 * they run in the same environment as the rest of the suite. Test files and
 * test fixtures are excluded: they are allowed to name what the product must
 * not do.
 */
const sources = import.meta.glob('../../**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

const files = Object.entries(sources)
  // Glob keys are relative to this file and Vite shortens them: '../../x' is
  // src/x, '../x' is src/features/x and './x' is a sibling.
  .map(([path, source]) => ({
    path: path.replace(/^\.\.\/\.\.\//, '').replace(/^\.\.\//, 'features/').replace(/^\.\//, 'features/video-review/'),
    source,
  }))
  .filter(({ path }) => !/\.test\.tsx?$/.test(path) && !path.startsWith('test/'));

const read = (path: string) => {
  const file = files.find((candidate) => candidate.path === path);
  if (!file) throw new Error('missing source ' + path);
  return file.source;
};

/** Source with comments removed, so prose about a pattern is not the pattern. */
const code = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');

const featureFiles = files.filter(({ path }) => path.startsWith('features/'));

describe('one web Representative authority', () => {
  it('leaves no feature reader of the compatibility Track-detail representative', () => {
    // `api/tracks.ts` keeps the field on the wire type; nothing in a feature
    // may read it. The rank-0 selector is the only Representative source.
    const readers = featureFiles
      .filter(({ source }) => {
        const body = code(source);
        return /\.representative\b/.test(body)
          || /\[\s*['"`]representative['"`]\s*\]/.test(body)
          || /\{[^{}]*\brepresentative\b[^{}]*\}\s*=\s*(?:props\.)?(?:detail|track|data)\b/.test(body);
      })
      .map(({ path }) => path);
    expect(readers).toEqual([]);
  });

  it('derives the Representative in exactly one place', () => {
    const definitions = featureFiles.filter(({ source }) => /export function representativeObservation\b/.test(source)).map(({ path }) => path);
    expect(definitions).toEqual(['features/video-review/evidenceSet.ts']);

    // Every Representative consumer goes through it.
    for (const path of [
      'features/video-review/TrackEvidence.tsx',
      'features/video-review/TrackDetailsPanels.tsx',
    ]) {
      expect(read(path), path).toMatch(/representativeObservation\(detail\)/);
    }
  });
});

describe('one Evidence Set implementation', () => {
  it('is mounted by both hosts from the same module', () => {
    const review = code(read('features/video-review/VideoReviewPage.tsx'));
    const inspector = code(read('features/visual-search/TrackInspector.tsx'));

    expect(review).toMatch(/import TrackEvidenceSet from '\.\/TrackEvidenceSet';/);
    expect(inspector).toMatch(/import TrackEvidenceSet from '\.\.\/video-review\/TrackEvidenceSet';/);
    expect(review.match(/<TrackEvidenceSet\b[^>]*\bdetail=\{detail\}/g)).toHaveLength(1);
    expect(inspector.match(/<TrackEvidenceSet\b[^>]*\bdetail=\{detail\}/g)).toHaveLength(1);
  });

  it('has no second implementation and no surviving Representative crop component', () => {
    const components = files.filter(({ path }) => /EvidenceSet\.tsx$/.test(path)).map(({ path }) => path);
    expect(components).toEqual(['features/video-review/TrackEvidenceSet.tsx']);

    // The only code that renders an Observation crop is the Evidence Set.
    const cropReaders = files.filter(({ source }) => /\bevidenceContentUrl\b/.test(code(source))).map(({ path }) => path).sort();
    expect(cropReaders).toEqual(['api/tracks.ts', 'features/video-review/TrackEvidenceSet.tsx']);

    const survivors = files.filter(({ source }) => /\bRepresentativeEvidence\b/.test(source)).map(({ path }) => path);
    expect(survivors).toEqual([]);
  });

  it('owns no media and no transport', () => {
    const source = read('features/video-review/TrackEvidenceSet.tsx');
    const body = code(source);

    expect(body).not.toMatch(/useEvidenceTransport/);
    expect(body).not.toMatch(/<(?:video|audio)\b/);
    expect(body).not.toMatch(/\.(?:play|pause)\(|currentTime|seekTo/);
    // It is never slotted into the shared player either.
    expect(body).not.toMatch(/<EvidencePlayer\b|<TrackEvidence\b/);
  });
});

describe('server-authored evidence URLs', () => {
  it('builds no artifact URL anywhere in feature code', () => {
    const builders = featureFiles
      .filter(({ source }) => /['"`]\/api\/artifacts\//.test(code(source)) || /\bevidenceArtifactId\b[^\n]*\/content/.test(code(source)))
      .map(({ path }) => path);
    expect(builders).toEqual([]);
  });
});
