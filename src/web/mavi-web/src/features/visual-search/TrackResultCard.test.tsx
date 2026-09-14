import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TrackSearchItem } from '../../api/tracks';
import { renderWithApp } from '../../test/renderWithApp';
import TrackResultCard from './TrackResultCard';

const base: TrackSearchItem = {
  id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21451',
  processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
  videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
  cameraId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
  cameraCode: 'CAM-01',
  cameraName: 'North Gate',
  objectClass: 'Person',
  startTimestampUtc: '2026-09-14T02:30:00Z',
  endTimestampUtc: '2026-09-14T02:30:08Z',
  startOffsetMs: 10_000,
  endOffsetMs: 18_000,
  durationMs: 8_000,
  detectionCount: 32,
  meanConfidence: 0.91,
  maxConfidence: 0.97,
  reviewStatus: 'Unreviewed',
  thumbnailArtifactId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21441',
  thumbnailContentUrl: '/api/artifacts/old/content',
  videoContentUrl: '/api/videos/018f3f5a-2f70-7a2b-8a12-2d02f4c21421/content',
};

describe('TrackResultCard', () => {
  it('resets thumbnail failure when a recycled card receives a new evidence URL', () => {
    const view = renderWithApp(<TrackResultCard track={base} displayTimeZoneId="Asia/Kolkata" />);
    const oldImage = screen.getByRole('img', { name: /representative evidence/i });
    fireEvent.error(oldImage);
    expect(screen.getByText('Evidence unavailable')).toBeInTheDocument();

    view.rerender(
      <TrackResultCard
        track={{ ...base, thumbnailContentUrl: '/api/artifacts/new/content' }}
        displayTimeZoneId="Asia/Kolkata"
      />,
    );

    expect(screen.getByRole('img', { name: /representative evidence/i }))
      .toHaveAttribute('src', '/api/artifacts/new/content');
  });
});
