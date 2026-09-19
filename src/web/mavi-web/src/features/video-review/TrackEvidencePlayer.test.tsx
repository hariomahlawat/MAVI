import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { TrackDetail } from '../../api/tracks';
import TrackEvidencePlayer from './TrackEvidencePlayer';

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
  representative: {
    observationId: 'o', sourceFrameNumber: 300, videoOffsetMs: 12_000, timestampUtc: '2026-09-14T02:30:02Z', confidence: 0.96, qualityScore: 0.9,
    boundingBox: { x: 0.5, y: 0.5, width: 0.25, height: 0.5 }, thumbnailArtifactId: null, thumbnailContentUrl: null,
  },
  trajectoryArtifactId: 'a',
  trajectoryContentUrl: '/api/artifacts/a/content',
};

const trajectory = [
  { offsetMs: 10_000, centerX: 0, centerY: 0 },
  { offsetMs: 14_000, centerX: 1, centerY: 1 },
];

// jsdom lays nothing out, so give the <video> the size of a 1000×300 element
// that letterboxes a 16:9 frame (frame 533.3×300 centred at x≈233.3).
const sizes = { clientWidth: 1000, clientHeight: 300 };
let restore: Array<() => void> = [];

beforeEach(() => {
  for (const [name, value] of Object.entries(sizes)) {
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, name);
    Object.defineProperty(HTMLElement.prototype, name, { configurable: true, get: () => value });
    restore.push(() => {
      if (original) Object.defineProperty(HTMLElement.prototype, name, original);
      else delete (HTMLElement.prototype as unknown as Record<string, unknown>)[name];
    });
  }
});

afterEach(() => {
  restore.forEach((fn) => fn());
  restore = [];
});

function seek(video: HTMLVideoElement, seconds: number) {
  video.currentTime = seconds;
  fireEvent(video, new Event('seeked'));
}

describe('TrackEvidencePlayer overlay', () => {
  it('shows the representative box only within its visibility window, projected into the letterboxed frame', () => {
    render(<TrackEvidencePlayer detail={detail} trajectory={trajectory} />);
    const video = screen.getByLabelText('Source video evidence') as HTMLVideoElement;

    // The playhead starts at Track start (10 s), 2 s before the representative frame.
    expect(screen.queryByTestId('bounding-box')).not.toBeInTheDocument();

    seek(video, 12.1);
    const box = screen.getByTestId('bounding-box');
    expect(Number(box.getAttribute('x'))).toBeCloseTo(233.33 + 0.5 * 533.33, 0);
    expect(Number(box.getAttribute('y'))).toBeCloseTo(150, 5);
    expect(Number(box.getAttribute('width'))).toBeCloseTo(133.33, 1);
    expect(Number(box.getAttribute('height'))).toBeCloseTo(150, 5);

    seek(video, 12.5);
    expect(screen.queryByTestId('bounding-box')).not.toBeInTheDocument();
  });

  it('draws the trajectory polyline and the interpolated current position, and hides both when unticked', () => {
    render(<TrackEvidencePlayer detail={detail} trajectory={trajectory} />);
    const video = screen.getByLabelText('Source video evidence') as HTMLVideoElement;
    const overlay = screen.getByTestId('evidence-overlay');

    expect(overlay.querySelector('polyline')).toHaveAttribute('points', '233.3,0.0 766.7,300.0');
    seek(video, 12);
    const current = overlay.querySelector('circle.trajectory-current');
    expect(Number(current?.getAttribute('cx'))).toBeCloseTo(500, 1);
    expect(Number(current?.getAttribute('cy'))).toBeCloseTo(150, 1);

    fireEvent.click(screen.getByLabelText(/^Trajectory/));
    expect(overlay.querySelector('polyline')).toBeNull();
    fireEvent.click(screen.getByLabelText('Bounding box'));
    expect(screen.queryByTestId('bounding-box')).not.toBeInTheDocument();
  });

  it('labels a Track without trajectory evidence instead of drawing one', () => {
    render(<TrackEvidencePlayer detail={{ ...detail, trajectoryArtifactId: null, trajectoryContentUrl: null }} />);
    expect(screen.getByLabelText('Trajectory (none)')).toBeDisabled();
    expect(screen.getByTestId('evidence-overlay').querySelector('polyline')).toBeNull();
  });
});
