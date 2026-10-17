import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
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
    expect(screen.getByText('KA01AB1234')).toBeInTheDocument();
    expect(screen.getByText('KA 01\nAB 1234')).toBeInTheDocument();
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
