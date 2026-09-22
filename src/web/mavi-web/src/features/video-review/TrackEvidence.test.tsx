import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
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
  representative: {
    observationId: 'o', sourceFrameNumber: 300, videoOffsetMs: 12_000, timestampUtc: '2026-09-14T02:30:02Z', confidence: 0.96, qualityScore: 0.9,
    boundingBox: { x: 0.5, y: 0.5, width: 0.25, height: 0.5 }, thumbnailArtifactId: null, thumbnailContentUrl: null,
  },
  trajectoryArtifactId: 'a',
  trajectoryContentUrl: '/api/artifacts/a/content',
  analytics: notConfiguredAnalytics(),
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
  // Layer visibility is a persisted operator preference, so one test switching a
  // layer off would otherwise decide what the next one renders.
  window.localStorage.clear();
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

describe('Track evidence overlay', () => {
  it('shows the representative box only within its visibility window, projected into the letterboxed frame', () => {
    render(<TrackEvidence detail={detail} trajectory={trajectory} />);
    const video = screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;

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
    render(<TrackEvidence detail={detail} trajectory={trajectory} />);
    const video = screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;
    const overlay = screen.getByTestId('evidence-overlay');

    expect(overlay.querySelector('polyline')).toHaveAttribute('points', '233.3,0.0 766.7,300.0');

    // Persisted samples are filled discs, one per recorded sample.
    expect(screen.getAllByTestId('trajectory-sample')).toHaveLength(2);

    seek(video, 12);
    // Strictly between the two samples, so the position is derived. The
    // interpolated marker is a distinct element, not a differently coloured
    // sample: shape carries the distinction, never opacity.
    const current = screen.getByTestId('trajectory-interpolated');
    expect(Number(current.getAttribute('cx'))).toBeCloseTo(500, 1);
    expect(Number(current.getAttribute('cy'))).toBeCloseTo(150, 1);
    expect(current.getAttribute('fill')).not.toBe('solid');

    fireEvent.click(screen.getByRole('button', { name: 'Trajectory' }));
    expect(overlay.querySelector('polyline')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Bounding box' }));
    expect(screen.queryByTestId('bounding-box')).not.toBeInTheDocument();
  });

  it('never calls an exact persisted sample interpolated', () => {
    // The samples are at 10,000 and 14,000. Landing on one is not a rarity:
    // jumping to representative evidence lands on a sample every time, because
    // the pipeline appends every observation to the trajectory and then picks
    // one of them as representative. Calling that a derived position states
    // something untrue about the evidence.
    render(<TrackEvidence detail={detail} trajectory={trajectory} />);
    const video = screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;

    for (const seconds of [10, 14]) {
      seek(video, seconds);
      expect(screen.getAllByTestId('trajectory-sample')).toHaveLength(2);
      expect(screen.queryByTestId('trajectory-interpolated')).not.toBeInTheDocument();
    }

    // And strictly between them it is derived, and says so.
    seek(video, 12);
    expect(screen.getByTestId('trajectory-interpolated')).toBeInTheDocument();
  });

  it('offers an unavailable trajectory layer with its reason, rather than an empty one', () => {
    render(<TrackEvidence detail={{ ...detail, trajectoryArtifactId: null, trajectoryContentUrl: null }} />);
    expect(screen.getByRole('button', { name: 'Trajectory' })).toBeDisabled();
    // "Unavailable" and "empty" are different facts, and the reason is beside
    // the control rather than only in a tooltip.
    expect(screen.getByText('No trajectory was persisted for this Track.')).toBeInTheDocument();
    expect(screen.getByTestId('evidence-overlay').querySelector('polyline')).toBeNull();
  });

  it('distinguishes a trajectory that failed to load from one that does not exist', () => {
    render(<TrackEvidence detail={detail} trajectoryError />);
    expect(screen.getByText('The persisted trajectory could not be loaded.')).toBeInTheDocument();
    expect(screen.getByText(/could not be loaded. The Track and its representative frame are unaffected/)).toBeInTheDocument();
  });

  it('describes its spatial evidence for anyone who cannot see the stage', () => {
    render(<TrackEvidence detail={detail} trajectory={trajectory} />);

    // The stage itself stays hidden: narrating raw SVG geometry helps nobody.
    expect(screen.getByTestId('evidence-overlay')).toHaveAttribute('aria-hidden', 'true');

    const twin = screen.getByRole('group', { name: /spatial evidence$/ });
    const box = within(twin).getByRole('region', { name: 'Bounding box' });
    // Normalised source-frame coordinates, which are the evidence. Projected
    // pixels would describe this viewport and change with the window.
    expect(box).toHaveTextContent('x 0.500, y 0.500, width 0.250, height 0.500');
    expect(box).toHaveTextContent('96% confidence');
    expect(box).toHaveTextContent('00:12.0');

    const path = within(twin).getByRole('region', { name: 'Trajectory' });
    expect(path).toHaveTextContent('2 samples');
    expect(path).toHaveTextContent('00:10.0 to 00:14.0');
    expect(path).toHaveTextContent('Starts at x 0.000, y 0.000 and ends at x 1.000, y 1.000');
    // Bounded on purpose: a real trajectory carries thousands of samples.
    expect(within(path).getAllByRole('listitem').length).toBeLessThanOrEqual(2);
  });

  it('tells a persisted position from a derived one in the accessible twin', () => {
    render(<TrackEvidence detail={detail} trajectory={trajectory} />);
    const video = screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;
    const path = () => within(screen.getByRole('group', { name: /spatial evidence$/ }))
      .getByRole('region', { name: 'Trajectory' });

    seek(video, 10);
    expect(path()).toHaveTextContent('A persisted sample the worker recorded.');
    seek(video, 12);
    expect(path()).toHaveTextContent('Interpolated between the two surrounding samples');
  });

  it('states unavailable evidence honestly in the twin, and keeps semantics when a layer is switched off', async () => {
    const user = userEvent.setup();
    render(<TrackEvidence detail={{ ...detail, trajectoryArtifactId: null, trajectoryContentUrl: null }} />);
    const twin = screen.getByRole('group', { name: /spatial evidence$/ });

    // The twin says there is nothing to describe; the reason itself lives with
    // the control and is bound to it, so it is stated once.
    expect(within(twin).getByRole('region', { name: 'Trajectory' }))
      .toHaveTextContent('No spatial evidence to describe.');
    const control = screen.getByRole('button', { name: 'Trajectory' });
    expect(control).toBeDisabled();
    expect(document.getElementById(control.getAttribute('aria-describedby') ?? ''))
      .toHaveTextContent('No trajectory was persisted for this Track.');

    // Switching a layer off changes what is drawn, not what the evidence is.
    await user.click(screen.getByRole('button', { name: 'Bounding box' }));
    const box = within(twin).getByRole('region', { name: 'Bounding box' });
    expect(box).toHaveTextContent('Hidden by the layer control.');
    expect(box).toHaveTextContent('x 0.500, y 0.500');
  });

  it('reprojects onto the replacement element when the source changes at the same size', () => {
    // The element is keyed by source, so a new video mounts. When the new media
    // declares the same dimensions the measuring callback keeps its identity,
    // and before this was fixed the metadata listener and the resize observer
    // stayed on the detached element: the overlay kept the old geometry and
    // misprojected every box and path on the new one.
    const other = {
      ...detail,
      id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21452',
      video: { ...detail.video, videoContentUrl: '/api/videos/other/content' },
    };
    const view = render(<TrackEvidence detail={detail} trajectory={trajectory} />);
    const first = screen.getByLabelText(/source video evidence$/);

    // The replacement reports a different intrinsic aspect, which only reaches
    // the overlay if the new element is the one being measured.
    Object.defineProperty(HTMLVideoElement.prototype, 'videoWidth', { configurable: true, get: () => 300 });
    Object.defineProperty(HTMLVideoElement.prototype, 'videoHeight', { configurable: true, get: () => 300 });
    restore.push(() => {
      delete (HTMLVideoElement.prototype as unknown as Record<string, unknown>).videoWidth;
      delete (HTMLVideoElement.prototype as unknown as Record<string, unknown>).videoHeight;
    });

    view.rerender(<TrackEvidence detail={other} trajectory={trajectory} />);
    const second = screen.getByLabelText(/source video evidence$/);
    expect(second).not.toBe(first);

    fireEvent(second, new Event('loadedmetadata'));
    // A square frame inside the 1000x300 element is 300 wide, centred at x=350.
    const overlay = screen.getByTestId('evidence-overlay');
    expect(overlay.querySelector('polyline')).toHaveAttribute('points', '350.0,0.0 650.0,300.0');
  });

  it('offers no bounding-box layer when no representative frame was persisted', () => {
    render(<TrackEvidence detail={{ ...detail, representative: null }} />);
    expect(screen.getByRole('button', { name: 'Bounding box' })).toBeDisabled();
    expect(screen.getByText('No representative frame was persisted for this Track.')).toBeInTheDocument();
    // With no representative frame there is nowhere for the evidence jump to go.
    expect(screen.queryByRole('button', { name: /Evidence/ })).not.toBeInTheDocument();
  });
});
