import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TrackDetail, TrackPlateObservation, TrackPlates } from '../../api/tracks';
import TrackPlateReadings from './TrackPlateReadings';

const sourceId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21401';
const plate: TrackPlateObservation = {
  plateObservationId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21402',
  sourceObservationId: sourceId,
  role: 'NearView',
  offsetMs: 12400,
  sourceFrameNumber: 62,
  timestampUtc: '2026-10-17T10:00:12.400Z',
  box: { x: 10, y: 20, width: 80, height: 30, cropWidth: 640, cropHeight: 360 },
  detectorConfidence: 0.91,
  outcome: 'Read',
  readings: [{
    rank: 0,
    rawText: 'KA 01\nAB 1234',
    rawLineCount: 2,
    normalisedText: 'KA01AB1234',
    normalisationOutcome: 'ok',
    confidence: 0.95,
    formatClass: 'in-standard',
  }],
};
const ready: TrackPlates = {
  readiness: 'Ready',
  trackOutcome: 'Analysed',
  agreement: 'single',
  texts: [{ normalisedText: 'KA01AB1234', supportCount: 1, maxConfidence: 0.95,
    bestPlateObservationId: plate.plateObservationId }],
  observations: [plate],
};

function detail(plates: TrackPlates, objectClass: 'Person' | 'Vehicle' = 'Vehicle', url: string | null = null): TrackDetail {
  return {
    id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21450',
    objectClass,
    observations: [{
      observationId: sourceId,
      evidenceContentUrl: url,
      evidenceRole: 'NearView',
      videoOffsetMs: 12400,
    }],
    plates,
  } as TrackDetail;
}

describe('Stage-4 TrackPlateReadings', () => {
  it('shows a provisional model reading, multiline raw text and the real source seek', () => {
    const seek = vi.fn();
    render(<TrackPlateReadings detail={detail(ready)} compact matchedText="KA01AB1234" onSelectObservation={seek} />);
    expect(screen.getByText('Single reading')).toBeInTheDocument();
    expect(screen.getAllByText('KA01AB1234').length).toBeGreaterThan(0);
    expect(screen.getByText(/KA 01\s+AB 1234/)).toBeInTheDocument();
    expect(screen.getByText('No image')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /View source at/ }));
    expect(seek).toHaveBeenCalledWith(sourceId, 12400);
    expect(screen.queryByText(/Confirmed plate/)).not.toBeInTheDocument();
  });

  it.each([
    ['Pending', 'Plate reading pending'],
    ['Failed', 'Plate reading failed for this run'],
    ['Stale', 'Plate readings are from an earlier configuration'],
    ['NotConfigured', 'Plate reading is not configured in this installation'],
  ] as const)('does not expose stale facts in %s', (state, copy) => {
    render(<TrackPlateReadings detail={detail({ ...ready, readiness: state })} />);
    expect(screen.getByText(copy)).toBeInTheDocument();
    expect(screen.queryByText('KA01AB1234')).not.toBeInTheDocument();
  });

  it('distinguishes unavailable, empty and unreadable evidence', () => {
    const unavailable = render(<TrackPlateReadings detail={detail({
      ...ready, trackOutcome: 'Unavailable', unavailableReason: 'evidence_missing',
    })} />);
    expect(screen.getByText(/Plate reading unavailable for this track/)).toHaveTextContent('evidence_missing');
    unavailable.rerender(<TrackPlateReadings detail={detail({ ...ready, texts: [], observations: [] })} />);
    expect(screen.getByText('No plate found in the evidence')).toBeInTheDocument();
    unavailable.rerender(<TrackPlateReadings detail={detail({
      ...ready, texts: [], observations: [{ ...plate, outcome: 'Unreadable', readings: [] }],
    })} />);
    expect(screen.getByText('Unreadable plate')).toBeInTheDocument();
  });

  it('shows disagreements and rejected OCR as different facts, and never on a Person', () => {
    const r = render(<TrackPlateReadings detail={detail({
      ...ready,
      agreement: 'conflicting',
      texts: [...ready.texts, { ...ready.texts[0], normalisedText: 'KA01AB1284' }],
      observations: [{ ...plate, readings: [{
        ...plate.readings[0], rawText: 'AB#?', normalisationOutcome: 'rejected', normalisedText: undefined,
      }] }],
    })} />);
    expect(screen.getByText('Conflicting readings · 2 texts')).toBeInTheDocument();
    expect(screen.getByText('Not searchable — does not normalise to letters and digits')).toBeInTheDocument();
    const region = screen.getByRole('region', { name: 'Plate readings' });
    expect(within(region).getAllByRole('list').length).toBeGreaterThan(0);
    r.rerender(<TrackPlateReadings detail={detail(ready, 'Person')} />);
    expect(screen.queryByRole('region', { name: 'Plate readings' })).not.toBeInTheDocument();
  });

  it('bounds the initial observation list with an accessible disclosure', () => {
    const copies = Array.from({ length: 6 }, (_, i) => ({
      ...plate, plateObservationId: plate.plateObservationId + i,
    }));
    render(<TrackPlateReadings detail={detail({ ...ready, observations: copies })} />);
    const list = screen.getByRole('list', { name: 'Plate observations' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(5);
    fireEvent.click(screen.getByRole('button', { name: 'Show all 6 plate observations' }));
    expect(within(list).getAllByRole('listitem')).toHaveLength(6);
  });
});

describe('Stage-4 TrackPlateReadings: the plate region is drawn (success path)', () => {
  type FakeImage = { src: string; naturalWidth: number; naturalHeight: number; onload: null | (() => void); onerror: null | (() => void) };
  let images: FakeImage[] = [];
  let draws: unknown[][] = [];
  let restore: Array<() => void> = [];
  const override = (target: object, name: string, descriptor: PropertyDescriptor) => {
    const original = Object.getOwnPropertyDescriptor(target, name);
    Object.defineProperty(target, name, { configurable: true, ...descriptor });
    restore.push(() => { if (original) Object.defineProperty(target, name, original); else delete (target as Record<string, unknown>)[name]; });
  };
  beforeEach(() => {
    images = [];
    draws = [];
    // jsdom decodes no image and has no 2D context: both stand in, and the
    // decoded size is the crop size the box declares.
    class Decoded { src = ''; naturalWidth = 640; naturalHeight = 360; onload: null | (() => void) = null; onerror: null | (() => void) = null; constructor() { images.push(this); } }
    override(window, 'Image', { value: Decoded, writable: true });
    override(HTMLCanvasElement.prototype, 'getContext', { value: () => ({ drawImage: (...args: unknown[]) => draws.push(args) }) });
  });
  afterEach(() => { restore.forEach((fn) => fn()); restore = []; });

  it('cuts exactly the detector box from the source crop and shows it, never "No image"', () => {
    const { container } = render(<TrackPlateReadings detail={detail(ready, 'Vehicle', '/api/artifacts/aaa/content')} compact />);
    expect(screen.getByText('Loading plate image…')).toBeInTheDocument();
    // The source Observation's own server URL, not a constructed one.
    expect(images).toHaveLength(1);
    expect(images[0].src).toBe('/api/artifacts/aaa/content');

    act(() => images[0].onload!());

    expect(draws).toHaveLength(1);
    expect(draws[0][0]).toBe(images[0]);
    // The source rectangle is the box; the destination is the box at 1:1.
    expect(draws[0].slice(1)).toEqual([10, 20, 80, 30, 0, 0, 80, 30]);
    const canvas = container.querySelector('canvas') as HTMLCanvasElement;
    expect(canvas.width).toBe(80);
    expect(canvas.height).toBe(30);
    expect(screen.getByRole('img', { name: 'Detected plate region' })).toBeVisible();
    expect(screen.queryByText('No image')).not.toBeInTheDocument();
    expect(screen.queryByText('Loading plate image…')).not.toBeInTheDocument();
  });
});
