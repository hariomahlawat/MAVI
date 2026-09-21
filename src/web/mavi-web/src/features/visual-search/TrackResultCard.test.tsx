import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { TrackSearchItem } from '../../api/tracks';
import TrackResultCard from './TrackResultCard';
import { SELECT_CONTROL_CLASS, TRACK_ID_ATTRIBUTE } from './resultSelection';

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
  it('offers selection as a real control rather than a click handler on the card', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <MemoryRouter>
        <TrackResultCard track={base} displayTimeZoneId="Asia/Kolkata" onSelect={onSelect} />
      </MemoryRouter>,
    );

    // Reachable by keyboard, named, and operable by Enter and Space — none of
    // which an `onClick` on the `<article>` gave.
    const control = screen.getByRole('button', { name: 'Select Person · CAM-01 · North Gate' });
    await user.tab();
    expect(control).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledWith(base.id.toLowerCase());

    // The review link is its own control and does not select on the way out.
    onSelect.mockClear();
    await user.click(screen.getByRole('link', { name: 'Review evidence' }));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('carries the shared selection contract so the page need not know this markup', () => {
    render(
      <MemoryRouter>
        <TrackResultCard track={base} displayTimeZoneId="Asia/Kolkata" onSelect={() => {}} />
      </MemoryRouter>,
    );
    const control = screen.getByRole('button', { name: /^Select / });
    expect(control).toHaveClass(SELECT_CONTROL_CLASS);
    expect(control.getAttribute(TRACK_ID_ATTRIBUTE)).toBe(base.id.toLowerCase());
  });

  it('scrolls itself into view when it becomes the selection', () => {
    // j/k move the selection without moving focus, so the selected card being
    // on screen is the only thing that tells the operator where they are (§22).
    // `nearest` in both axes is what keeps it to the results list: a card
    // already visible is not scrolled, and the page cannot be scrolled at all.
    const scrollIntoView = vi.fn();
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scrollIntoView;
    try {
      const view = render(
        <MemoryRouter>
          <TrackResultCard track={base} displayTimeZoneId="Asia/Kolkata" onSelect={() => {}} />
        </MemoryRouter>,
      );
      expect(scrollIntoView).not.toHaveBeenCalled();

      view.rerender(
        <MemoryRouter>
          <TrackResultCard track={base} displayTimeZoneId="Asia/Kolkata" selected onSelect={() => {}} />
        </MemoryRouter>,
      );
      expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest', inline: 'nearest' });
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  it('resets thumbnail failure when a recycled card receives a new evidence URL', () => {
    const view = render(
      <MemoryRouter>
        <TrackResultCard track={base} displayTimeZoneId="Asia/Kolkata" />
      </MemoryRouter>,
    );
    const oldImage = screen.getByRole('img', { name: /representative evidence/i });
    fireEvent.error(oldImage);
    expect(screen.getByText('Evidence unavailable')).toBeInTheDocument();

    view.rerender(
      <MemoryRouter>
        <TrackResultCard
          track={{ ...base, thumbnailContentUrl: '/api/artifacts/new/content' }}
          displayTimeZoneId="Asia/Kolkata"
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole('img', { name: /representative evidence/i }))
      .toHaveAttribute('src', '/api/artifacts/new/content');
  });
});
