import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import EvidenceTimeline from './EvidenceTimeline';
import { SUBJECT_LANE, clampOffset, offsetFromPointer, percentOf, ratioOf } from './timeline';

const intervals = [
  { id: 'subject', startOffsetMs: 10_000, endOffsetMs: 18_000, label: 'Track 7 interval', lane: SUBJECT_LANE },
];
const markers = [
  { id: 'rep', offsetMs: 12_000, label: 'Representative frame', kind: 'representative' },
];

function renderTimeline(onSeek = vi.fn(), overrides: Partial<React.ComponentProps<typeof EvidenceTimeline>> = {}) {
  render(
    <EvidenceTimeline
      durationMs={100_000}
      currentOffsetMs={20_000}
      intervals={intervals}
      markers={markers}
      subjectLabel="Person Track 7"
      onSeek={onSeek}
      {...overrides}
    />,
  );
  return onSeek;
}

/** jsdom gives every element a zero rectangle, so the track needs a real one. */
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    left: 100, top: 0, right: 500, bottom: 22, width: 400, height: 22, x: 100, y: 0, toJSON: () => ({}),
  } as DOMRect);
});

describe('Evidence timeline', () => {
  it('has no keyboard vocabulary of its own', () => {
    const onSeek = renderTimeline();
    const track = screen.getByRole('list', { name: 'Person Track 7 timeline evidence' });

    // The player's grammar is one contract. A timeline that answered these keys
    // itself would give the same key two meanings on one surface depending on
    // where focus happened to be, so it answers none of them and they reach the
    // player by bubbling.
    for (const key of ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'j', 'l', ' ', 'e']) {
      fireEvent.keyDown(track, { key });
    }
    expect(onSeek).not.toHaveBeenCalled();

    // Nor is it a focus stop of its own: there is no slider widget to tab to.
    expect(screen.queryByRole('slider')).not.toBeInTheDocument();
    expect(track).not.toHaveAttribute('tabindex');
  });

  it('seeks where the pointer lands and clamps a scrub that leaves the track', () => {
    const onSeek = renderTimeline();
    const track = screen.getByRole('list');

    fireEvent.pointerDown(track, { button: 0, clientX: 300 });
    expect(onSeek).toHaveBeenLastCalledWith(50_000);

    fireEvent.pointerMove(window, { clientX: 200 });
    expect(onSeek).toHaveBeenLastCalledWith(25_000);

    // Past either end the seek holds at the end rather than leaving the media.
    fireEvent.pointerMove(window, { clientX: 9_999 });
    expect(onSeek).toHaveBeenLastCalledWith(100_000);
    fireEvent.pointerMove(window, { clientX: -50 });
    expect(onSeek).toHaveBeenLastCalledWith(0);

    // Releasing ends the scrub; later movement is not a seek.
    fireEvent.pointerUp(window);
    onSeek.mockClear();
    fireEvent.pointerMove(window, { clientX: 300 });
    expect(onSeek).not.toHaveBeenCalled();
  });

  it('gives each piece of evidence one element that is both the mark and the named item', () => {
    renderTimeline();

    // Not an aria-hidden bar shadowed by a hidden description list: the marks
    // themselves are the items, and they are the only representation.
    const items = screen.getAllByRole('listitem');
    expect(items.map((item) => item.textContent)).toEqual([
      'Track 7 interval: 00:10.0 to 00:18.0',
      'Representative frame: 00:12.0',
    ]);
    for (const item of items) {
      expect(item).not.toHaveAttribute('aria-hidden');
      // The element carrying the name is the element carrying the position.
      expect(item.className).toMatch(/evidence-timeline__(interval|marker)/);
      expect(item.style.left).not.toBe('');
    }
    // One list. A second one would be the parallel surface.
    expect(screen.getAllByRole('list')).toHaveLength(1);
  });

  it('distinguishes an interval from a marker by more than colour', () => {
    renderTimeline();
    const [interval, marker] = screen.getAllByRole('listitem');
    // Shape and wording, not hue: an interval names two offsets and is a band,
    // a marker names one and is a tick.
    expect(interval).toHaveClass('evidence-timeline__interval');
    expect(interval.textContent).toMatch(/ to /);
    expect(interval.style.width).not.toBe('');
    expect(marker).toHaveClass('evidence-timeline__marker');
    expect(marker.textContent).not.toMatch(/ to /);
    expect(marker.style.width).toBe('');
    expect(marker).toHaveAttribute('data-kind', 'representative');
  });

  it('names the playhead nothing, because it is not evidence', () => {
    renderTimeline();
    const playhead = document.querySelector('.evidence-timeline__playhead');
    expect(playhead).toHaveAttribute('aria-hidden', 'true');
    expect(playhead?.textContent).toBe('');
  });

  it('names an analytical lane it does not draw, rather than dropping it', () => {
    // Specification decision 7 leaves the presentation of multiple analytical
    // interval types open until Slice 5 has real zone, dwell and stationary
    // facts to choose against. The seam accepts the records and names them as
    // evidence; nothing is drawn for a lane whose visual grammar is undecided.
    renderTimeline(vi.fn(), {
      intervals: [
        ...intervals,
        { id: 'dwell-1', startOffsetMs: 11_000, endOffsetMs: 13_000, label: 'Dwell in Forecourt', lane: 'dwell' },
      ],
    });

    const dwell = screen.getByText('Dwell in Forecourt: 00:11.0 to 00:13.0').closest('li');
    expect(dwell).toHaveAttribute('data-lane', 'dwell');
    expect(dwell).toHaveAttribute('data-drawn', 'false');
    expect(dwell).not.toHaveAttribute('aria-hidden');
    // Still named for everyone, still not given a shape nobody has chosen.
    expect(document.querySelectorAll('[data-drawn="true"]')).toHaveLength(1);
  });

  it('holds together when the duration is not yet known', () => {
    renderTimeline(vi.fn(), { durationMs: 0 });
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });
});

describe('timeline geometry', () => {
  it('maps offsets to ratios and percentages, clamped to the media', () => {
    expect(ratioOf(50, 100)).toBe(0.5);
    expect(ratioOf(-10, 100)).toBe(0);
    expect(ratioOf(500, 100)).toBe(1);
    expect(ratioOf(10, 0)).toBe(0);
    expect(percentOf(25, 100)).toBe('25.0000%');
  });

  it('maps a pointer position to an offset inside the media', () => {
    const track = { left: 100, width: 400 };
    expect(offsetFromPointer(300, track, 100_000)).toBe(50_000);
    expect(offsetFromPointer(50, track, 100_000)).toBe(0);
    expect(offsetFromPointer(9_999, track, 100_000)).toBe(100_000);
    expect(offsetFromPointer(300, { left: 0, width: 0 }, 100_000)).toBe(0);
  });

  it('clamps an offset without inventing a duration it does not have', () => {
    expect(clampOffset(-5, 100)).toBe(0);
    expect(clampOffset(150, 100)).toBe(100);
    expect(clampOffset(Number.NaN, 100)).toBe(0);
    expect(clampOffset(150, 0)).toBe(150);
  });
});
