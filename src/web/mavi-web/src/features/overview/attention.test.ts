import { describe, expect, it } from 'vitest';
import type { AnalyticsReadiness, ProcessingRunStatus, ProcessingStatus, VideoAsset } from '../../api/videos';
import type { AsyncState } from '../../shared/async/asyncState';
import { attentionLookupIds, evaluateAttention } from './attention';

const CAMERA = 'cam-1';
function video(id: string, processingStatus: string, importedAtUtc = '2026-09-14T03:00:00Z'): VideoAsset {
  return {
    id, cameraId: CAMERA, originalFileName: `${id}.mp4`, recordingStartUtc: '2026-09-14T02:00:00Z', recordingEndUtc: '2026-09-14T02:10:00Z',
    recordingTimeZoneId: 'UTC', recordingUtcOffsetMinutes: 0, durationMs: 600_000, width: 1920, height: 1080,
    frameRateNumerator: 25, frameRateDenominator: 1, codecName: 'h264', processingStatus, importedAtUtc,
  };
}
function run(status: string, overrides: Partial<ProcessingRunStatus> = {}): ProcessingRunStatus {
  return {
    processingRunId: 'run', status, pipeline: 'p', pipelineVersion: '1', workerId: null, queuedAtUtc: '2026-09-14T03:00:00Z',
    startedAtUtc: null, completedAtUtc: null, progressPercent: 100, attemptCount: 1, failureCode: null, framesProcessed: 0,
    tracksCreated: 0, analyticsReadiness: 'Ready', phase: status === 'Completed' ? 'completed' : status === 'Failed' ? 'failed' : 'processing',
    ...overrides,
  };
}
const ready = (latestRun: ProcessingRunStatus | null, videoStatus = 'Processed'): AsyncState<ProcessingStatus> => ({ kind: 'ready', data: { videoStatus, latestRun } });
const completed = (readiness: AnalyticsReadiness) => ready(run('Completed', { analyticsReadiness: readiness }));
const codes = new Map([[CAMERA, 'CAM-01']]);

function evaluate(videos: VideoAsset[], states: Record<string, AsyncState<ProcessingStatus>> = {}, limit?: number) {
  return evaluateAttention({ videos, cameraCodes: codes, lookup: (id) => states[id], limit });
}

describe('evaluateAttention', () => {
  it('reports nothing for a deployment whose every processed run is analysed', () => {
    const result = evaluate([video('a', 'Processed'), video('b', 'Processed')], { a: completed('Ready'), b: completed('Ready') });
    expect(result.items).toEqual([]);
    expect(result.pendingLookups).toBe(0);
    expect(result.unavailableLookups).toEqual([]);
    expect(result.analyticsScope).toEqual({ checked: 2, total: 2 });
  });

  it('reports a failed video from the inventory, with the run code where the lookup has it, linking to its run', () => {
    const result = evaluate([video('A1', 'Failed')], { A1: ready(run('Failed', { failureCode: 'vision_job_attempts_exhausted' }), 'Failed') });
    expect(result.items).toEqual([expect.objectContaining({
      condition: 'processing-failed', subject: 'A1.mp4 · CAM-01', code: 'vision_job_attempts_exhausted', to: '/processing/a1', actionLabel: 'Open run',
    })]);
  });

  it('keeps a failed video an item when its lookup fails, and says the lookup is unknown rather than healthy', () => {
    const result = evaluate([video('a', 'Failed')], { a: { kind: 'unavailable', error: new Error('503') } });
    expect(result.items).toHaveLength(1);
    expect(result.items[0].code).toBeNull();
    expect(result.unavailableLookups).toEqual(['a']);
    expect(result.unavailableDetails).toBe(1);
    expect(result.unknownAnalytics).toBe(0);
  });

  it('keeps a cached classification after a failed refresh but marks it as not current', () => {
    const degraded: AsyncState<ProcessingStatus> = { kind: 'ready', data: { videoStatus: 'Processed', latestRun: run('Completed', { analyticsReadiness: 'Stale' }) }, degraded: { error: new Error('503') } };
    const result = evaluate([video('a', 'Processed'), video('b', 'Processed')], { a: degraded, b: completed('Ready') });
    expect(result.items.map((item) => item.key)).toEqual(['analytics-stale:a']);
    expect(result.staleLookups).toEqual(['a']);
    expect(result.unavailableLookups).toEqual([]);
  });

  it('counts a processed video whose lookup failed as one whose need for attention is unknown', () => {
    const result = evaluate([video('a', 'Processed')], { a: { kind: 'unavailable', error: new Error('503') } });
    expect(result.items).toEqual([]);
    expect(result.unknownAnalytics).toBe(1);
  });

  it('distinguishes a failure while publishing from one during inference', () => {
    const result = evaluate([video('a', 'Failed')], { a: ready(run('Failed', { failureCode: 'vision_finalization_exhausted' }), 'Failed') });
    expect(result.items[0].reason).toMatch(/while publishing/);
  });

  it('reports analytics Failed and Stale of a completed run, and nothing for the operator choices or work on its way', () => {
    const videos = ['failed', 'stale', 'pending', 'notconfigured', 'disabled', 'ready'].map((id) => video(id, 'Processed'));
    const result = evaluate(videos, {
      failed: completed('Failed'), stale: completed('Stale'), pending: completed('Pending'),
      notconfigured: completed('NotConfigured'), disabled: completed('Disabled'), ready: completed('Ready'),
    });
    expect(result.items.map((item) => [item.condition, item.subject])).toEqual([
      ['analytics-failed', 'failed.mp4 · CAM-01'],
      ['analytics-stale', 'stale.mp4 · CAM-01'],
    ]);
  });

  it('ignores the readiness of a run that did not complete', () => {
    const result = evaluate([video('a', 'Processed')], { a: ready(run('Cancelled', { analyticsReadiness: 'Failed' })) });
    expect(result.items).toEqual([]);
  });

  it('aggregates media awaiting processing into one item that opens the filtered Videos ledger', () => {
    const result = evaluate([video('a', 'NotQueued'), video('b', 'NotQueued'), video('c', 'Queued'), video('d', 'Processing')]);
    expect(result.items).toEqual([expect.objectContaining({ condition: 'awaiting-processing', subject: '2 videos', to: '/videos?status=NotQueued' })]);
  });

  it('never reports a run still moving, and claims no stall', () => {
    const result = evaluate([video('a', 'Processing'), video('b', 'Queued')]);
    expect(result.items).toEqual([]);
  });

  it('orders failures first, then failed and stale analytics, then waiting media; newest first within each', () => {
    const result = evaluate([
      video('nq', 'NotQueued'),
      video('stale', 'Processed'),
      video('old', 'Failed', '2026-09-10T00:00:00Z'),
      video('new', 'Failed', '2026-09-12T00:00:00Z'),
      video('afail', 'Processed'),
    ], { stale: completed('Stale'), afail: completed('Failed') });
    expect(result.items.map((item) => item.key)).toEqual([
      'processing-failed:new', 'processing-failed:old', 'analytics-failed:afail', 'analytics-stale:stale', 'awaiting-processing',
    ]);
  });

  it('counts lookups still answering, so nothing is declared clear before they do', () => {
    const result = evaluate([video('a', 'Processed')], { a: { kind: 'loading' } });
    expect(result.pendingLookups).toBe(1);
    expect(result.items).toEqual([]);
  });

  it('states the analytics scope when it is bounded', () => {
    const videos = Array.from({ length: 5 }, (_, i) => video(`p${i}`, 'Processed', `2026-09-1${i}T00:00:00Z`));
    const states = Object.fromEntries(videos.map((v) => [v.id, completed('Stale')]));
    const result = evaluate(videos, states, 3);
    expect(result.analyticsScope).toEqual({ checked: 3, total: 5 });
    expect(result.items.map((item) => item.subject)).toEqual(['p4.mp4 · CAM-01', 'p3.mp4 · CAM-01', 'p2.mp4 · CAM-01']);
  });

  it('names a video without its camera code when the camera inventory is unavailable', () => {
    const result = evaluateAttention({ videos: [video('a', 'Failed')], cameraCodes: null, lookup: () => undefined });
    expect(result.items[0].subject).toBe('a.mp4');
  });
});

describe('attentionLookupIds', () => {
  it('looks up only the newest failed and processed videos, in a stable order', () => {
    const videos = [
      video('f-old', 'Failed', '2026-09-01T00:00:00Z'), video('f-new', 'Failed', '2026-09-05T00:00:00Z'),
      video('p1', 'Processed', '2026-09-02T00:00:00Z'), video('p2', 'Processed', '2026-09-03T00:00:00Z'), video('p3', 'Processed', '2026-09-04T00:00:00Z'),
      video('q', 'Queued'), video('n', 'NotQueued'),
    ];
    expect(attentionLookupIds(videos, 2)).toEqual(['f-new', 'f-old', 'p3', 'p2']);
    expect(attentionLookupIds([...videos].reverse(), 2)).toEqual(['f-new', 'f-old', 'p3', 'p2']);
  });
});
