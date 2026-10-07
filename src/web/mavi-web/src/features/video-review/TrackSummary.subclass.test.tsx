import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TrackDetail } from '../../api/tracks';
import { TrackSummary } from './TrackDetailsPanels';

/** Stage 3 X2: the Track detail shows the server-exposed subclass under its broad class. */
function detail(overrides: Partial<TrackDetail>): TrackDetail {
  return {
    camera: { id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412', code: 'CAM-01', name: 'North Gate' },
    objectClass: 'Vehicle',
    startTimestampUtc: '2026-09-14T02:30:00Z',
    endTimestampUtc: '2026-09-14T02:30:08Z',
    startOffsetMs: 10_000,
    endOffsetMs: 18_000,
    durationMs: 8_000,
    detectionCount: 32,
    meanConfidence: 0.91,
    maxConfidence: 0.97,
    ...overrides,
  } as TrackDetail;
}

describe('TrackSummary object class', () => {
  it('shows Vehicle · Car for an exposed car', () => {
    render(<TrackSummary detail={detail({ objectSubclass: 'car' })} displayTimeZoneId="Asia/Kolkata" />);
    expect(screen.getByText('Vehicle · Car')).toBeInTheDocument();
  });

  it('shows Vehicle alone when the server exposed no subclass', () => {
    render(<TrackSummary detail={detail({})} displayTimeZoneId="Asia/Kolkata" />);
    expect(screen.getByText('Vehicle')).toBeInTheDocument();
    expect(screen.queryByText(/Car/)).not.toBeInTheDocument();
  });
});
