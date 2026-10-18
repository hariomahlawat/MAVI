import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import type { TrackItemPlate, TrackSearchItem } from '../../api/tracks';
import TrackResultCard from './TrackResultCard';
import TrackResultList from './TrackResultList';

/** Synthetic plate text only; never a real registration. */
const conflicting: TrackItemPlate = {
  matchedText: 'ZZ00TS0001', matchKind: 'contains', supportCount: 1, plateObservationCount: 4,
  distinctTextCount: 3, maxConfidence: 0.41, bestPlateObservationId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21499',
};

function item(plate: TrackItemPlate): TrackSearchItem {
  return {
    id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21451', processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
    videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421', cameraId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21411',
    cameraCode: 'CAM-1', cameraName: 'Gate', objectClass: 'Vehicle', startTimestampUtc: '2026-09-14T02:30:00Z',
    endTimestampUtc: '2026-09-14T02:30:08Z', startOffsetMs: 10_000, endOffsetMs: 18_000, durationMs: 8_000,
    detectionCount: 3, meanConfidence: 0.9, maxConfidence: 0.95, reviewStatus: 'Unreviewed',
    thumbnailArtifactId: null, thumbnailContentUrl: null, videoContentUrl: '/api/videos/x/content', plate,
  };
}

const context = 'objectClass=Vehicle&plateText=TS00';

describe('Stage-4 plate match: what a screen reader hears is what the operator sees (§17.2.3)', () => {
  it('announces support, confidence and other readings in the List view', () => {
    render(<MemoryRouter><TrackResultList items={[item(conflicting)]} selectedId={null} searchContext={context} onSelect={() => {}} /></MemoryRouter>);
    const row = within(screen.getByRole('list', { name: 'Track results' })).getAllByRole('listitem')[0];
    const select = within(row).getByRole('button', { name: /^Select / });
    expect(select).toHaveAccessibleName('Select Vehicle · CAM-1 · Gate · Read as ZZ00TS0001 · on 1 of 4 plates · 41% · 2 other readings');
    // The visible line states exactly the same facts.
    expect(within(row).getByText(/^Read as/)).toHaveTextContent('Read as ZZ00TS0001 · on 1 of 4 plates · 41% · 2 other readings');
  });

  it('announces the same facts in the Grid view', () => {
    render(<MemoryRouter><TrackResultCard track={item(conflicting)} searchContext={context} onSelect={() => {}} /></MemoryRouter>);
    expect(screen.getByRole('button', { name: /^Select / }))
      .toHaveAccessibleName('Select Vehicle · CAM-1 · Gate · Read as ZZ00TS0001 · on 1 of 4 plates · 41% · 2 other readings');
    expect(screen.getByText(/^Read as/)).toHaveTextContent('Read as ZZ00TS0001 · on 1 of 4 plates · 41% · 2 other readings');
  });

  it('states a consistent reading without inventing a conflict', () => {
    const consistent = { ...conflicting, supportCount: 3, plateObservationCount: 3, distinctTextCount: 1, maxConfidence: 0.97 };
    render(<MemoryRouter><TrackResultList items={[item(consistent)]} selectedId={null} searchContext={context} onSelect={() => {}} /></MemoryRouter>);
    expect(screen.getByRole('button', { name: /^Select / }))
      .toHaveAccessibleName('Select Vehicle · CAM-1 · Gate · Read as ZZ00TS0001 · on 3 of 3 plates · 97%');
  });
});
