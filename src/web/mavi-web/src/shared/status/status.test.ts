import { describe, expect, it } from 'vitest';
import { isActiveStatus, isVideoStatus, labelForStatus, toneForStatus } from './status';

describe('status vocabulary', () => {
  it('maps every API status to one tone', () => {
    expect(toneForStatus('Processed')).toBe('ok');
    expect(toneForStatus('Completed')).toBe('ok');
    expect(toneForStatus('Failed')).toBe('err');
    expect(toneForStatus('Rejected')).toBe('err');
    expect(toneForStatus('Queued')).toBe('info');
    expect(toneForStatus('Running')).toBe('active');
    expect(toneForStatus('Cancelled')).toBe('warn');
    expect(toneForStatus('NotQueued')).toBe('neutral');
    expect(toneForStatus(undefined)).toBe('neutral');
  });

  it('labels statuses for operators without inventing new ones', () => {
    expect(labelForStatus('NotQueued')).toBe('Not queued');
    expect(labelForStatus('Processing')).toBe('Processing');
    expect(labelForStatus(null)).toBe('Unknown');
  });

  it('knows which statuses are still moving', () => {
    expect(isActiveStatus('Queued')).toBe(true);
    expect(isActiveStatus('Running')).toBe(true);
    expect(isActiveStatus('Processed')).toBe(false);
    expect(isVideoStatus('Failed')).toBe(true);
    expect(isVideoStatus('Running')).toBe(false);
  });
});
