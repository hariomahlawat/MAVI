/**
 * Stage 3.5 S6/X3 (§38): a closure head carries its implementation's
 * qualification, rather than re-measuring it.
 *
 * The performance budgets are judged on the implementation head, whose exact
 * CI evidence the qualification artifact
 * (docs/qualification/stage3-5/s6-x3-performance-qualification.json) is
 * generated from. A commit after it that changes nothing the product renders,
 * nothing the harness measures and no budget — the register, the artifact,
 * CI wiring — cannot change that verdict, and re-measuring it would only sample
 * the same implementation again (a stochastic re-run, never new evidence about
 * the change). Such a head is judged `closure`: the gate validates that the
 * artifact passed, that its implementation head is this head's ancestor, that
 * every path changed since is closure-safe, and (in CI) that the
 * implementation head's own Quality Gate run succeeded. Any other change —
 * product, harness, budgets, fixtures, dependencies — is `measure`: the gate
 * runs in full.
 *
 *   node tools/web-visual-qa/performance-closure.mjs --decide    (writes mode= to $GITHUB_OUTPUT)
 */
import { execFileSync } from 'node:child_process';
import { appendFileSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '..', '..');
export const ARTIFACT = 'docs/qualification/stage3-5/s6-x3-performance-qualification.json';

/**
 * Paths that cannot change what the product renders, what the harness
 * measures or what the budgets are: documentation (the register, the
 * artifact), the CI wiring, and this check with the tests of its wiring.
 * Everything else — src/, the harness, the budgets, fixtures, configuration,
 * dependencies — is a change to the implementation and is measured.
 */
export const CLOSURE_SAFE = Object.freeze([
  /^docs\//,
  /^tools\/web-visual-qa\/README\.md$/,
  /^\.github\/workflows\/quality-gate\.yml$/,
  /^tools\/web-visual-qa\/performance-closure\.mjs$/,
  /^tools\/web-visual-qa\/test\/performance-closure\.test\.mjs$/,
  /^tools\/qualification\/tests\/test_s1_evidence\.py$/,
  /^src\/vision\/tests\/test_runtime_metadata\.py$/,
]);

/** `closure` when every changed path is closure-safe, else `measure`, with the reason. */
export function decide({ artifact, isAncestor, changed }) {
  if (!artifact) return { mode: 'measure', reason: 'no qualification artifact' };
  if (artifact.verdict !== 'PASS') return { mode: 'measure', reason: `the qualification artifact's verdict is ${artifact.verdict}` };
  if (!/^[0-9a-f]{40}$/.test(artifact.implementationHead ?? '')) return { mode: 'measure', reason: 'the qualification artifact names no implementation head' };
  if (!isAncestor) return { mode: 'measure', reason: `${artifact.implementationHead} is not an ancestor of this head` };
  const unsafe = changed.filter((path) => !CLOSURE_SAFE.some((re) => re.test(path)));
  if (unsafe.length) return { mode: 'measure', reason: `changed since ${artifact.implementationHead.slice(0, 8)}: ${unsafe.slice(0, 5).join(', ')}${unsafe.length > 5 ? ` and ${unsafe.length - 5} more` : ''}` };
  if (!changed.length) return { mode: 'measure', reason: 'this is the implementation head itself' };
  return { mode: 'closure', reason: `only closure-safe paths changed since the qualified implementation head ${artifact.implementationHead.slice(0, 8)}: ${changed.join(', ')}` };
}

/** The artifact's own evidence: one head throughout, a CI run named. */
export function artifactProblems(artifact) {
  const problems = [];
  const head = artifact?.implementationHead;
  if (artifact?.verdict !== 'PASS') problems.push(`verdict ${artifact?.verdict}`);
  if (artifact?.results?.faults?.length || artifact?.results?.findings?.length) problems.push('the artifact records faults or findings');
  if (artifact?.windowsContinuity && artifact.windowsContinuity.head !== head) problems.push(`the continuity run (${artifact.windowsContinuity.head}) is not of ${head}`);
  if (!ciRunId(artifact)) problems.push('the artifact names no CI run');
  return problems;
}

/** The implementation head's Quality Gate run, as the artifact records it. */
export function ciRunId(artifact) {
  const m = /\brun (\d+)\b/.exec(artifact?.environment?.enforcement?.ciRun ?? '');
  return m ? m[1] : null;
}

function main() {
  const git = (...args) => execFileSync('git', args, { cwd: REPO, encoding: 'utf8' }).trim();
  let artifact = null;
  try { artifact = JSON.parse(readFileSync(join(REPO, ARTIFACT), 'utf8')); } catch { /* measured below */ }
  let isAncestor = false;
  let changed = [];
  if (artifact?.implementationHead) {
    try { git('merge-base', '--is-ancestor', artifact.implementationHead, 'HEAD'); isAncestor = true; } catch { isAncestor = false; }
    if (isAncestor) changed = git('diff', '--name-only', artifact.implementationHead, 'HEAD').split('\n').filter(Boolean);
  }
  const verdict = decide({ artifact, isAncestor, changed });
  const problems = verdict.mode === 'closure' ? artifactProblems(artifact) : [];
  const mode = problems.length ? 'measure' : verdict.mode;
  const reason = problems.length ? `the qualification artifact cannot be carried: ${problems.join('; ')}` : verdict.reason;
  process.stdout.write(`performance gate mode: ${mode} — ${reason}\n`);
  if (process.env.GITHUB_OUTPUT) {
    appendFileSync(process.env.GITHUB_OUTPUT, `mode=${mode}\nimplementation=${artifact?.implementationHead ?? ''}\nrun=${mode === 'closure' ? ciRunId(artifact) : ''}\n`);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url) && process.argv.includes('--decide')) main();
