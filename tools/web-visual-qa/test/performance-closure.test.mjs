// S6/X3: a closure head carries its implementation's performance
// qualification only when nothing that renders, measures or budgets the
// product has changed; anything else is measured in full.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import { ARTIFACT, artifactProblems, ciRunId, decide } from '../performance-closure.mjs';

const HEAD = '05865b5fc09e76fafe1bed75695e897b3600b686';
const artifact = (over = {}) => ({
  verdict: 'PASS', implementationHead: HEAD, results: { faults: [], findings: [] },
  environment: { enforcement: { ciRun: `MAVI Quality Gate run 38204091363 (${HEAD.slice(0, 8)}), attempt 1` } },
  windowsContinuity: { head: HEAD }, ...over,
});

describe('the performance gate on a closure head', () => {
  it('carries the qualification across documentation and CI wiring only', () => {
    const v = decide({ artifact: artifact(), isAncestor: true, changed: ['docs/reviews/register.md', ARTIFACT, '.github/workflows/quality-gate.yml'] });
    assert.equal(v.mode, 'closure');
  });

  it('measures any change to the product, the harness, the budgets or fixtures', () => {
    for (const path of ['src/web/mavi-web/src/features/search/VisualSearchPage.tsx', 'tools/web-visual-qa/performance-budgets.mjs', 'tools/web-visual-qa/settle.mjs', 'tools/web-visual-qa/states.mjs', 'tools/web-visual-qa/fixtures/x.json', 'src/web/mavi-web/package-lock.json']) {
      const v = decide({ artifact: artifact(), isAncestor: true, changed: ['docs/a.md', path] });
      assert.equal(v.mode, 'measure', path);
      assert.match(v.reason, new RegExp(path.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')));
    }
  });

  it('measures the implementation head itself, a head not descended from it, and a failed or missing qualification', () => {
    assert.equal(decide({ artifact: artifact(), isAncestor: true, changed: [] }).mode, 'measure');
    assert.equal(decide({ artifact: artifact(), isAncestor: false, changed: ['docs/a.md'] }).mode, 'measure');
    assert.equal(decide({ artifact: artifact({ verdict: 'FAIL' }), isAncestor: true, changed: ['docs/a.md'] }).mode, 'measure');
    assert.equal(decide({ artifact: null, isAncestor: false, changed: [] }).mode, 'measure');
    assert.equal(decide({ artifact: artifact({ implementationHead: 'abc' }), isAncestor: true, changed: ['docs/a.md'] }).mode, 'measure');
  });

  it('refuses to carry an artifact whose own evidence is not clean or not one head', () => {
    assert.deepEqual(artifactProblems(artifact()), []);
    assert.ok(artifactProblems(artifact({ results: { faults: ['x'], findings: [] } })).length);
    assert.ok(artifactProblems(artifact({ windowsContinuity: { head: 'other' } })).length);
    assert.ok(artifactProblems(artifact({ environment: { enforcement: { ciRun: 'local' } } })).length);
    assert.equal(ciRunId(artifact()), '38204091363');
  });

  it('accepts the committed artifact as carriable evidence', () => {
    const committed = JSON.parse(readFileSync(new URL(`../../../${ARTIFACT}`, import.meta.url), 'utf8'));
    assert.deepEqual(artifactProblems(committed), []);
    assert.equal(committed.verdict, 'PASS');
  });
});
