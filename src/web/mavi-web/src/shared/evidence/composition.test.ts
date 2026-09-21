import { describe, expect, it } from 'vitest';

/**
 * Every source file in the app, as text.
 *
 * Read through Vite's glob rather than the filesystem, which is the convention
 * the token-architecture tests already use and what keeps these assertions
 * running in the same environment as the rest of the suite.
 */
const sources = import.meta.glob('../../**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

const files = Object.entries(sources)
  .filter(([path]) => !/\.test\.tsx?$/.test(path))
  // Glob keys are relative to this file: '../../x' is src/x, and a sibling
  // comes back as './x'. Both are normalised to a path from src.
  .map(([path, source]) => ({
    path: path.replace(/^\.\.\/\.\.\//, '').replace(/^\.\//, 'shared/evidence/'),
    source,
  }));

/** Files that open a JSX `<video>` element, as opposed to mentioning one in prose. */
function videoMounts(): string[] {
  return files.filter(({ source }) => /^\s*<video$|^\s*<video\s/m.test(source)).map(({ path }) => path);
}

/**
 * Section 18 prohibits more than one Evidence Player implementation, and
 * section 30 names native media controls beneath evidence overlays as an
 * anti-pattern. Both are properties of the whole codebase rather than of any
 * one component, so they are asserted against the sources.
 *
 * The Scene Editor's reference frame is the one other media element, and it is
 * not an Evidence Player: section 27 keeps reference-frame transport
 * feature-specific, because it picks a still to draw geometry against rather
 * than reviewing evidence over time. It is named here so that a *third* media
 * element cannot appear unnoticed.
 */
describe('one Evidence Player', () => {
  it('is the only evidence surface that mounts a media element', () => {
    expect(videoMounts().sort()).toEqual([
      'features/scene-editor/SceneCanvas.tsx',
      'shared/evidence/EvidencePlayer.tsx',
    ]);
  });

  it('never uses native browser controls, and neither does any other media element', () => {
    for (const { path, source } of files) {
      expect(source, path).not.toMatch(/^\s*controls\s*$/m);
      expect(source, path).not.toMatch(/<video[^>]*\scontrols[\s/>]/);
    }
  });

  it('is what Review and the Investigation inspector both play evidence with', () => {
    const read = (path: string) => files.find((file) => file.path === path)?.source ?? '';
    const review = read('features/video-review/VideoReviewPage.tsx');
    const inspector = read('features/visual-search/TrackInspector.tsx');
    // Both mount the same Track adapter, which composes the one player.
    expect(review).toContain('<TrackEvidence detail={detail}');
    expect(inspector).toContain('<TrackEvidence detail={detail}');

    const adapter = read('features/video-review/TrackEvidence.tsx');
    expect(adapter).toContain("import EvidencePlayer from '../../shared/evidence/EvidencePlayer'");
    // The adapter composes; it does not reimplement playback.
    expect(adapter).not.toContain('requestAnimationFrame');
    expect(adapter).not.toMatch(/^\s*<video/m);
  });

  it('keeps one timeline: nothing else renders a scrubber', () => {
    const scrubbers = files
      .filter(({ source }) => /^\s*role="slider"/m.test(source))
      .map(({ path }) => path);
    expect(scrubbers).toEqual(['shared/evidence/EvidenceTimeline.tsx']);
  });

  it('holds the animation-frame loop in one place', () => {
    const loops = files
      .filter(({ source }) => /requestAnimationFrame/.test(source))
      .map(({ path }) => path)
      .filter((path) => path.startsWith('shared/evidence/') || path.startsWith('features/'));
    expect(loops).toEqual(['shared/evidence/useEvidenceTransport.ts']);
  });
});
