import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import FaceKnownLimits, { FACE_KNOWN_LIMITS } from './FaceKnownLimits';

/**
 * The numbers are those of `docs/qualification/poc/known-limits.md` (faces section);
 * a change to either must change both.
 */
describe('PoC S6 face known limits', () => {
  it('states the measured numbers, the candidate semantics and the licence scope', () => {
    render(<FaceKnownLimits profile="poc-single-host" />);
    const limits = screen.getByRole('region', { name: 'Known limits: face intelligence' });
    expect(limits).toHaveTextContent('2 of 110');
    expect(limits).toHaveTextContent('99.8 %');
    expect(limits).toHaveTextContent('99.7 %');
    expect(limits).toHaveTextContent('0.2121');
    expect(limits).toHaveTextContent('not calibrated on CCTV');
    expect(limits).toHaveTextContent('research-only');
    expect(limits).toHaveTextContent('opt-in per camera');
    expect(limits).toHaveTextContent('Face candidates, not identification');
    expect(limits).toHaveTextContent('Profile poc-single-host (ADR-020)');
    expect(FACE_KNOWN_LIMITS).toMatchObject({ coverage: '2 of 110', lfwNative: '99.8 %', lfw32: '99.7 %', referenceThreshold: '0.2121' });
  });
});
