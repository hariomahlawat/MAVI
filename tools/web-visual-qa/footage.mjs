/**
 * The footage conditions section 26 requires overlays to be checked against.
 *
 * Generated with ffmpeg at run time rather than committed: the repository does
 * not carry video datasets, and the tracked-media gate in `verify_repo.py`
 * exists to keep it that way. Generation is deterministic, so two runs on two
 * machines look at the same frames.
 *
 * VP9 in WebM, because the Chromium builds used for this pass do not carry an
 * H.264 decoder and a clip that will not decode validates nothing.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Each condition is a `lavfi` source chosen to attack a different way an
 * overlay can become unreadable.
 */
export const CONDITIONS = {
  // Near-white: a pale stroke simply is not there without the halo.
  bright: { size: '1920x1080', filter: "color=c=0xf2f2f2:s=1920x1080:d=4,noise=alls=6:allf=t" },
  // Near-black: a dark halo has nothing to separate it from.
  dark: { size: '1920x1080', filter: "color=c=0x0c0c10:s=1920x1080:d=4,noise=alls=4:allf=t" },
  // Saturated: competes with every evidence hue at once.
  saturated: { size: '1920x1080', filter: 'testsrc2=s=1920x1080:d=4' },
  // Low contrast: mid-grey, where a mid-tone overlay disappears.
  lowcontrast: { size: '1920x1080', filter: "color=c=0x7a7d82:s=1920x1080:d=4,noise=alls=3:allf=t" },
  // 21:9 in a 16:9 element: letterbox bars the overlay must not be drawn into.
  letterbox: { size: '2560x1080', filter: 'smptebars=s=2560x1080:d=4' },
};

export function ensureFootage(mediaDir, condition = 'saturated') {
  mkdirSync(mediaDir, { recursive: true });
  const target = join(mediaDir, `${condition}.webm`);
  if (existsSync(target)) return target;

  const spec = CONDITIONS[condition];
  if (!spec) throw new Error(`unknown footage condition: ${condition}`);

  try {
    execFileSync('ffmpeg', [
      '-hide_banner', '-loglevel', 'error', '-y',
      '-f', 'lavfi', '-i', spec.filter,
      '-c:v', 'libvpx-vp9', '-b:v', '600k', '-cpu-used', '8', '-deadline', 'realtime',
      '-pix_fmt', 'yuv420p', '-t', '4',
      target,
    ], { stdio: ['ignore', 'ignore', 'pipe'] });
  } catch (error) {
    throw new Error(
      `ffmpeg could not generate the "${condition}" clip. ffmpeg is a Development ` +
      `prerequisite for this harness; see tools/web-visual-qa/README.md.\n${error}`,
    );
  }
  return target;
}
