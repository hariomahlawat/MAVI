import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TrackDetail } from '../../api/tracks';
import { notConfiguredAnalytics } from '../../test/analyticsFixtures';
import TrackEvidence from './TrackEvidence';

const detail: TrackDetail = {
  id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21451',
  processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
  videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
  camera: { id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412', code: 'CAM-01', name: 'North Gate' },
  objectClass: 'Person',
  localTrackNumber: 7,
  startOffsetMs: 10_000,
  endOffsetMs: 18_000,
  startTimestampUtc: '2026-09-14T02:30:00Z',
  endTimestampUtc: '2026-09-14T02:30:08Z',
  durationMs: 8_000,
  detectionCount: 42,
  meanConfidence: 0.91,
  maxConfidence: 0.98,
  reviewStatus: 'Unreviewed',
  processing: { pipelineVersion: 'phase1', detectorName: 'RTMDet', detectorVersion: '1', trackerName: 'ByteTrack', trackerVersion: '1', completedAtUtc: '2026-09-14T02:40:00Z' },
  video: { recordingStartUtc: '2026-09-14T02:26:42Z', recordingEndUtc: '2026-09-14T02:36:42Z', durationMs: 600_000, width: 1920, height: 1080, frameRateNumerator: 25, frameRateDenominator: 1, videoContentUrl: '/api/videos/v/content' },
  representative: null,
  trajectoryArtifactId: null,
  trajectoryContentUrl: null,
  analytics: notConfiguredAnalytics(),
};

/** A controllable animation-frame scheduler: frames run only when the test says so. */
class FrameScheduler {
  private next = 1;
  readonly pending = new Map<number, FrameRequestCallback>();
  request = (callback: FrameRequestCallback): number => {
    const id = this.next++;
    this.pending.set(id, callback);
    return id;
  };
  cancel = (id: number): void => { this.pending.delete(id); };
  runFrame(): void {
    const [id, callback] = [...this.pending.entries()][0] ?? [];
    if (id === undefined || !callback) throw new Error('No frame pending.');
    this.pending.delete(id);
    callback(performance.now());
  }
}

let frames: FrameScheduler;
const originalRequest = window.requestAnimationFrame;
const originalCancel = window.cancelAnimationFrame;

beforeEach(() => {
  frames = new FrameScheduler();
  window.requestAnimationFrame = frames.request;
  window.cancelAnimationFrame = frames.cancel;
});

afterEach(() => {
  window.requestAnimationFrame = originalRequest;
  window.cancelAnimationFrame = originalCancel;
});

function playing(video: HTMLVideoElement, isPlaying: boolean) {
  Object.defineProperty(video, 'paused', { configurable: true, value: !isPlaying });
  Object.defineProperty(video, 'ended', { configurable: true, value: false });
}

function playhead(): number {
  // The timeline playhead is positioned from the current offset; read it back as a percentage.
  const element = document.querySelector('.evidence-timeline__playhead') as HTMLElement;
  return Number.parseFloat(element.style.left);
}

describe('Track evidence playhead lifecycle', () => {
  it('keeps exactly one frame loop alive through timeupdate and seeking while playing', () => {
    render(<TrackEvidence detail={detail} />);
    const video = screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;
    playing(video, true);

    fireEvent(video, new Event('play'));
    expect(frames.pending.size).toBe(1);

    // A second play event (e.g. after a stall) must not start a second loop.
    fireEvent(video, new Event('playing'));
    fireEvent(video, new Event('play'));
    expect(frames.pending.size).toBe(1);

    // timeupdate fires every ~250 ms during playback; it must not kill the loop.
    fireEvent(video, new Event('timeupdate'));
    expect(frames.pending.size).toBe(1);

    // Seeking while playing must not kill the loop either.
    video.currentTime = 15;
    fireEvent(video, new Event('seeked'));
    expect(frames.pending.size).toBe(1);

    // Each frame reschedules the next while playing, and publishes the playhead.
    video.currentTime = 16;
    act(() => frames.runFrame());
    expect(frames.pending.size).toBe(1);
    expect(playhead()).toBeCloseTo((16_000 / 600_000) * 100, 3);
  });

  it('stops the loop on pause and on end, and reflects the final position', () => {
    render(<TrackEvidence detail={detail} />);
    const video = screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;
    playing(video, true);
    fireEvent(video, new Event('play'));

    video.currentTime = 20;
    playing(video, false);
    fireEvent(video, new Event('pause'));
    expect(frames.pending.size).toBe(0);
    expect(playhead()).toBeCloseTo((20_000 / 600_000) * 100, 3);

    playing(video, true);
    fireEvent(video, new Event('play'));
    expect(frames.pending.size).toBe(1);
    Object.defineProperty(video, 'ended', { configurable: true, value: true });
    fireEvent(video, new Event('ended'));
    expect(frames.pending.size).toBe(0);
  });

  it('cancels the loop when the source is replaced and when the player unmounts', () => {
    const view = render(<TrackEvidence detail={detail} />);
    const first = screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;
    playing(first, true);
    fireEvent(first, new Event('play'));
    expect(frames.pending.size).toBe(1);

    view.rerender(
      <TrackEvidence detail={{ ...detail, video: { ...detail.video, videoContentUrl: '/api/videos/other/content' } }} />,
    );
    expect(frames.pending.size).toBe(0);
    const second = screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;
    expect(second).not.toBe(first);
    playing(second, true);
    fireEvent(second, new Event('play'));
    expect(frames.pending.size).toBe(1);

    view.unmount();
    expect(frames.pending.size).toBe(0);
  });

  it('does not schedule frames while paused, even when the media reports time updates', () => {
    render(<TrackEvidence detail={detail} />);
    const video = screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;
    playing(video, false);
    fireEvent(video, new Event('timeupdate'));
    fireEvent(video, new Event('seeked'));
    expect(frames.pending.size).toBe(0);
    expect(vi.isMockFunction(window.requestAnimationFrame)).toBe(false);
  });
});
