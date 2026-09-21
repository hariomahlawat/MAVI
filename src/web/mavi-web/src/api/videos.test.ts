import { describe, expect, it } from 'vitest';
import { processingPollInterval, type ProcessingStatus } from './videos';

function status(videoStatus: string, runStatus?: string): ProcessingStatus {
  return {
    videoStatus,
    latestRun: runStatus
      ? {
          processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
          status: runStatus,
          pipeline: 'phase1-detection-tracking',
          pipelineVersion: 'phase1-v1',
          workerId: null,
          queuedAtUtc: '2026-09-14T02:00:00Z',
          startedAtUtc: null,
          completedAtUtc: null,
          progressPercent: 0,
          attemptCount: 1,
          failureCode: null,
          framesProcessed: 0,
          tracksCreated: 0,
          analyticsReadiness: 'NotConfigured',
        }
      : null,
  };
}

describe('processing polling policy', () => {
  it.each([
    ['Queued', undefined],
    ['Processing', undefined],
    ['NotQueued', 'Queued'],
    ['NotQueued', 'Running'],
  ])('polls active state %s/%s at two seconds', (videoStatus, runStatus) => {
    expect(processingPollInterval(status(videoStatus, runStatus))).toBe(2_000);
  });

  it.each([
    ['Processed', 'Completed'],
    ['Failed', 'Failed'],
    ['NotQueued', undefined],
    ['Processed', undefined],
  ])('stops for terminal/non-active state %s/%s', (videoStatus, runStatus) => {
    expect(processingPollInterval(status(videoStatus, runStatus))).toBe(false);
  });

  it('does not poll before status is known', () => {
    expect(processingPollInterval(undefined)).toBe(false);
  });

  it('keeps polling a Processed video while its analytics are still pending, and stops for every other readiness (Slice 4)', () => {
    const pending = status('Processed', 'Completed');
    pending.latestRun!.analyticsReadiness = 'Pending';
    expect(processingPollInterval(pending)).toBe(2_000);

    for (const readiness of ['Ready', 'Failed', 'Stale', 'Disabled', 'NotConfigured'] as const) {
      const settled = status('Processed', 'Completed');
      settled.latestRun!.analyticsReadiness = readiness;
      expect(processingPollInterval(settled), readiness).toBe(false);
    }
  });
});
