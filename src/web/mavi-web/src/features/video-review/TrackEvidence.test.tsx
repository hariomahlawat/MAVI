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

/**
 * A Track the worker finalised on one observation.
 *
 * `mavi_vision/pipeline/finalization.py` requires `observation_count > 0` and
 * one trajectory point per observation, so exactly one sample is a complete,
 * valid Track rather than a broken one.
 */
const oneSample = [{ offsetMs: 12_000, centerX: 0.25, centerY: 0.75 }];

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

  /** The text bound to a layer's own control by aria-describedby. */
  function describedText(label: string): string {
    const control = screen.getByRole('button', { name: label });
    return (control.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean)
      .map((id) => document.getElementById(id)?.textContent ?? '')
      .join(' ');
  }

  it('names its spatial evidence on the layer control the operator uses', () => {
    render(<TrackEvidence detail={detail} trajectory={trajectory} />);

    // The stage itself stays hidden: narrating raw SVG geometry helps nobody.
    expect(screen.getByTestId('evidence-overlay')).toHaveAttribute('aria-hidden', 'true');
    // And there is no separate spatial tree beside it. Section 23 requires the
    // twin to be the control the pointer uses, so the semantics ride the layer
    // rows instead: one layer, one visible row, one semantic object.
    expect(screen.queryByRole('group', { name: /spatial evidence/i })).not.toBeInTheDocument();

    const box = describedText('Bounding box');
    // Normalised source-frame coordinates, which are the evidence. Projected
    // pixels would describe this viewport and change with the window.
    expect(box).toContain('x 0.500, y 0.500, width 0.250, height 0.500');
    expect(box).toContain('96% confidence');
    expect(box).toContain('00:12.0');

    const path = describedText('Trajectory');
    expect(path).toContain('2 samples');
    expect(path).toContain('00:10.0 to 00:14.0');
    expect(path).toContain('Starts at x 0.000, y 0.000 and ends at x 1.000, y 1.000');
    // Bounded on purpose: a real trajectory carries thousands of samples, so
    // the path is summarised and only the asserted position is enumerated.
    expect(path).not.toMatch(/sample .*sample .*sample/);
  });

  it('tells a persisted position from a derived one, and says when there is none', () => {
    render(<TrackEvidence detail={detail} trajectory={trajectory} />);
    const video = screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;

    seek(video, 10);
    expect(describedText('Trajectory')).toContain('A persisted sample the worker recorded.');
    seek(video, 12);
    expect(describedText('Trajectory')).toContain('Interpolated between the two surrounding samples');

    // Outside the sampled range the position is absent rather than missing:
    // "nothing here" and "nothing described" are different facts, and the
    // second one leaves the operator unable to trust either.
    seek(video, 40);
    expect(describedText('Trajectory')).toContain('No position is asserted at this playhead.');
    expect(describedText('Trajectory'))
      .toContain('Not drawn here: the playhead is outside the sampled range.');
  });

  it('never announces a layer preference and a draw state that contradict each other', async () => {
    const user = userEvent.setup();
    render(<TrackEvidence detail={detail} trajectory={trajectory} />);
    const video = screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;

    // Enabled and on the frame the box was persisted for.
    seek(video, 12);
    expect(describedText('Bounding box')).toContain('Layer enabled.');
    expect(describedText('Bounding box')).toContain('Drawn at the current position.');

    // Still enabled, playhead away. The toggle has not changed, so the
    // preference sentence must not change either — only the draw state does.
    seek(video, 40);
    expect(describedText('Bounding box')).toContain('Layer enabled.');
    expect(describedText('Bounding box'))
      .toContain('Not drawn here: the playhead is away from the frame it describes.');
    expect(describedText('Bounding box')).not.toContain('Drawn at the current position.');

    // Switched off while the playhead sits on the representative frame. The
    // previous wording said "Hidden by the layer control." and "Drawn at the
    // current position." at once, which cannot both be true.
    await user.click(screen.getByRole('button', { name: 'Bounding box' }));
    seek(video, 12);
    const hidden = describedText('Bounding box');
    expect(hidden).toContain('Layer hidden by operator.');
    expect(hidden).toContain('Not drawn: the layer is switched off.');
    expect(hidden).not.toContain('Drawn at the current position.');
    // Switching a layer off changes what is drawn, not what the evidence is.
    expect(hidden).toContain('x 0.500, y 0.500');
  });

  it('states unavailable evidence honestly, without inventing semantics for it', () => {
    render(<TrackEvidence detail={{ ...detail, trajectoryArtifactId: null, trajectoryContentUrl: null }} />);

    const control = screen.getByRole('button', { name: 'Trajectory' });
    expect(control).toBeDisabled();
    // The reason lives with the control and is bound to it, so it is stated
    // once, in the one place the operator is already looking.
    expect(describedText('Trajectory')).toContain('No trajectory was persisted for this Track.');
    expect(describedText('Trajectory')).not.toContain('Layer');
  });

  describe('a Track finalised on one observation', () => {
    it('treats one persisted sample as evidence, not as a trajectory too short to draw', () => {
      render(<TrackEvidence detail={detail} trajectory={oneSample} />);

      // The producer allows it, so the UI may not discard it. Before this was
      // fixed the layer was disabled and the operator was told the trajectory
      // had "too few samples to draw" — about evidence that exists.
      const control = screen.getByRole('button', { name: 'Trajectory' });
      expect(control).toBeEnabled();
      expect(control).toHaveAttribute('aria-pressed', 'true');
      expect(screen.queryByText(/too few samples/)).not.toBeInTheDocument();
      expect(screen.queryByText(/could not be loaded/)).not.toBeInTheDocument();
      expect(screen.queryByText(/No trajectory was persisted/)).not.toBeInTheDocument();
    });

    it('draws the sample and nothing the evidence does not contain', () => {
      render(<TrackEvidence detail={detail} trajectory={oneSample} />);

      expect(screen.getAllByTestId('trajectory-sample')).toHaveLength(1);
      // A line needs two points, and a hollow ring means "derived from two
      // surrounding samples". Neither exists here, so neither is drawn.
      expect(document.querySelector('.evidence-track')).toBeNull();
      expect(screen.queryByTestId('trajectory-interpolated')).not.toBeInTheDocument();
    });

    it('names the sample and asserts a position only where one was recorded', () => {
      render(<TrackEvidence detail={detail} trajectory={oneSample} />);
      const video = screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;
      const items = () => within(
        document.getElementById(
          screen.getByRole('button', { name: 'Trajectory' }).getAttribute('aria-describedby') ?? '',
        ) as HTMLElement,
      ).getAllByRole('listitem').map((item) => item.textContent ?? '');

      seek(video, 12);
      expect(items()[0]).toContain('One persisted sample of the Track centre, at 00:12.0');
      expect(items()[0]).toContain('x 0.250, y 0.750');
      expect(items()[0]).toContain('No line is drawn, because a line needs two samples.');
      expect(items()[1]).toContain('x 0.250, y 0.750');
      expect(items()[1]).toContain('A persisted sample the worker recorded.');
      expect(items()[1]).not.toContain('Interpolated');

      // Off the sample there is no evidence of position, and no motion is
      // invented in either direction.
      for (const seconds of [11, 13]) {
        seek(video, seconds);
        expect(items()[1]).toContain('No position is asserted at this playhead.');
        expect(items()[1]).toContain('Not drawn here: the playhead is not on the one persisted sample.');
      }
    });

    it('keeps the evidence when the operator switches the layer off', async () => {
      const user = userEvent.setup();
      render(<TrackEvidence detail={detail} trajectory={oneSample} />);

      await user.click(screen.getByRole('button', { name: 'Trajectory' }));
      expect(screen.queryByTestId('trajectory-sample')).not.toBeInTheDocument();
      const described = describedText('Trajectory');
      expect(described).toContain('Layer hidden by operator.');
      expect(described).toContain('x 0.250, y 0.750');
      expect(described).not.toContain('Drawn at the current position.');
    });

    it('stays distinct from a Track with no trajectory at all', () => {
      render(<TrackEvidence detail={{ ...detail, trajectoryArtifactId: null, trajectoryContentUrl: null }} />);
      const control = screen.getByRole('button', { name: 'Trajectory' });
      expect(control).toBeDisabled();
      expect(describedText('Trajectory')).toContain('No trajectory was persisted for this Track.');
      expect(screen.queryByTestId('trajectory-sample')).not.toBeInTheDocument();
    });

    it('stays distinct from a persisted artefact that yielded no samples', () => {
      render(<TrackEvidence detail={detail} trajectory={[]} />);
      const control = screen.getByRole('button', { name: 'Trajectory' });
      expect(control).toBeDisabled();
      expect(describedText('Trajectory')).toContain('The persisted trajectory contains no samples.');
      expect(describedText('Trajectory')).not.toContain('No trajectory was persisted');
    });
  });

  it('keeps raw one-sample evidence while analytics honestly reports it too short', () => {
    // Both are true at once and neither is fixed to match the other. The worker
    // finalises a Track on one observation, so the position is real evidence;
    // Scene Analytics v1 needs two samples for any path-derived fact, so
    // `trajectory_too_short` is an honest answer about a different question.
    render(
      <TrackEvidence
        detail={{
          ...detail,
          analytics: {
            ...detail.analytics,
            status: 'Unavailable',
            unavailableReason: 'trajectory_too_short',
            sampleCount: 1,
          },
        }}
        trajectory={oneSample}
      />,
    );

    // The raw evidence is not hidden because analytics are unavailable.
    expect(screen.getAllByTestId('trajectory-sample')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Trajectory' })).toBeEnabled();
    expect(describedText('Trajectory')).toContain('x 0.250, y 0.750');
    // And no analytical evidence is manufactured because raw evidence exists.
    expect(screen.queryByTestId('evidence-zone')).not.toBeInTheDocument();
    expect(screen.queryByTestId('evidence-crossing')).not.toBeInTheDocument();
    const lanes = screen.getAllByRole('listitem').map((item) => item.dataset.lane).filter(Boolean);
    expect(lanes).not.toContain('zone');
    expect(lanes).not.toContain('stationary');
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
