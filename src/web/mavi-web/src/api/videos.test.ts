import { describe, expect, it } from 'vitest';
import {
  FINALIZATION_FAILURE_CODE_PREFIX,
  isAnalyticsPending,
  isFinalizationFailure,
  isFinalizing,
  isProcessingActive,
  processingPollInterval,
  type AnalyticsReadiness,
  type ProcessingPhase,
  type ProcessingRunStatus,
  type ProcessingStatus,
} from './videos';

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
          phase: 'processing',
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

/** A run that differs from the fixture only in the fields a test names. */
function withRun(videoStatus: string, runStatus: string, extra: Partial<ProcessingRunStatus>): ProcessingStatus {
  const base = status(videoStatus, runStatus);
  return { ...base, latestRun: { ...base.latestRun!, ...extra } };
}

function runOf(phase: ProcessingPhase, failureCode: string | null, runStatus = 'Failed'): ProcessingRunStatus {
  return withRun('Failed', runStatus, { phase, failureCode }).latestRun!;
}

describe('run phase predicates (U1)', () => {
  it('reads Finalizing from the phase, never from the run status', () => {
    // Inference and finalization are both `Running`: only the phase tells them apart.
    expect(isFinalizing(withRun('Processing', 'Running', { phase: 'finalizing' }).latestRun)).toBe(true);
    expect(isFinalizing(withRun('Processing', 'Running', { phase: 'processing' }).latestRun)).toBe(false);
    expect(isFinalizing(withRun('Queued', 'Queued', { phase: 'queued' }).latestRun)).toBe(false);
    expect(isFinalizing(withRun('Processed', 'Completed', { phase: 'completed' }).latestRun)).toBe(false);
    expect(isFinalizing(null)).toBe(false);
    expect(isFinalizing(undefined)).toBe(false);
  });

  it('uses the domain finalization-failure prefix', () => {
    expect(FINALIZATION_FAILURE_CODE_PREFIX).toBe('vision_finalization_');
  });

  it('calls a failure a finalization failure only for a failed phase with the prefixed code', () => {
    expect(isFinalizationFailure(runOf('failed', 'vision_finalization_staging_missing'))).toBe(true);
    expect(isFinalizationFailure(runOf('failed', 'vision_finalization_exhausted'))).toBe(true);

    // An ordinary failure, and a failure with no code.
    expect(isFinalizationFailure(runOf('failed', 'worker_watchdog_timeout'))).toBe(false);
    expect(isFinalizationFailure(runOf('failed', null))).toBe(false);
    // The prefix alone does not make a run failed.
    expect(isFinalizationFailure(runOf('finalizing', 'vision_finalization_staging_missing', 'Running'))).toBe(false);
    // A prefix, not a substring, and the underscore is part of it.
    expect(isFinalizationFailure(runOf('failed', 'vision_finalization'))).toBe(false);
    expect(isFinalizationFailure(runOf('failed', 'xvision_finalization_a'))).toBe(false);
    expect(isFinalizationFailure(runOf('failed', 'worker_vision_finalization_a'))).toBe(false);
    expect(isFinalizationFailure(null)).toBe(false);
    expect(isFinalizationFailure(undefined)).toBe(false);
  });
});

describe('processing polling across run phases (U1)', () => {
  const readinesses: readonly AnalyticsReadiness[] = ['NotConfigured', 'Disabled', 'Pending', 'Ready', 'Failed', 'Stale'];

  it('keeps polling a Finalizing run until publication, whatever its analytics readiness', () => {
    for (const analyticsReadiness of readinesses) {
      const finalizing = withRun('Processing', 'Running', { phase: 'finalizing', progressPercent: 100, analyticsReadiness });
      expect(isProcessingActive(finalizing), analyticsReadiness).toBe(true);
      expect(processingPollInterval(finalizing), analyticsReadiness).toBe(2_000);
    }
  });

  it('keeps polling Queued and Running runs', () => {
    expect(processingPollInterval(withRun('Queued', 'Queued', { phase: 'queued', analyticsReadiness: 'Pending' }))).toBe(2_000);
    expect(processingPollInterval(withRun('Processing', 'Running', { phase: 'processing', analyticsReadiness: 'Pending' }))).toBe(2_000);
  });

  it('keeps polling a completed run whose analytics are pending', () => {
    const completed = withRun('Processed', 'Completed', { phase: 'completed', analyticsReadiness: 'Pending' });
    expect(isAnalyticsPending(completed)).toBe(true);
    expect(processingPollInterval(completed)).toBe(2_000);
  });

  it('never polls a terminal failed or cancelled run, even when its readiness reads Pending', () => {
    // The platform derives readiness for any run, and a run that never
    // completed is never analysed, so its `Pending` can never change.
    for (const failureCode of ['vision_finalization_staging_missing', 'worker_watchdog_timeout']) {
      const failed = withRun('Failed', 'Failed', { phase: 'failed', failureCode, analyticsReadiness: 'Pending' });
      expect(isAnalyticsPending(failed), failureCode).toBe(false);
      expect(processingPollInterval(failed), failureCode).toBe(false);
    }
    const cancelled = withRun('Failed', 'Cancelled', { phase: 'failed', analyticsReadiness: 'Pending' });
    expect(isAnalyticsPending(cancelled)).toBe(false);
    expect(processingPollInterval(cancelled)).toBe(false);
  });
});
