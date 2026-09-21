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
  it('is one operable scrubber, not decoration', () => {
    renderTimeline();
    const slider = screen.getByRole('slider', { name: 'Person Track 7 timeline' });
    expect(slider).toHaveAttribute('aria-valuenow', '20000');
    expect(slider).toHaveAttribute('aria-valuemax', '100000');
    expect(slider).toHaveAttribute('aria-valuetext', '00:20.0 of 01:40.0');
    // The transitional player marked its timeline aria-hidden, which hid
    // meaningful evidence from everyone not using a pointer.
    expect(slider).not.toHaveAttribute('aria-hidden');
    // One scrubber. Two on a surface is a defect.
    expect(screen.getAllByRole('slider')).toHaveLength(1);
  });

  it('seeks where the pointer lands and clamps a scrub that leaves the track', () => {
    const onSeek = renderTimeline();
    const slider = screen.getByRole('slider');

    fireEvent.pointerDown(slider, { button: 0, clientX: 300 });
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

  it('seeks from the keyboard, so the timeline is reachable without a pointer', () => {
    const onSeek = renderTimeline();
    const slider = screen.getByRole('slider');

    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    expect(onSeek).toHaveBeenLastCalledWith(21_000);
    fireEvent.keyDown(slider, { key: 'ArrowLeft' });
    expect(onSeek).toHaveBeenLastCalledWith(19_000);
    fireEvent.keyDown(slider, { key: 'ArrowRight', shiftKey: true });
    expect(onSeek).toHaveBeenLastCalledWith(30_000);
    // Up and down move a slider too, and Home and End are its own ends —
    // distinct from the player's Home and End, which go to the subject.
    fireEvent.keyDown(slider, { key: 'ArrowUp' });
    expect(onSeek).toHaveBeenLastCalledWith(21_000);
    fireEvent.keyDown(slider, { key: 'ArrowDown' });
    expect(onSeek).toHaveBeenLastCalledWith(19_000);
    fireEvent.keyDown(slider, { key: 'Home' });
    expect(onSeek).toHaveBeenLastCalledWith(0);
    fireEvent.keyDown(slider, { key: 'End' });
    expect(onSeek).toHaveBeenLastCalledWith(100_000);
  });

  it('names every interval and marker in a list, as the accessible twin', () => {
    renderTimeline();
    const entries = screen.getAllByRole('listitem').map((item) => item.textContent);
    expect(entries).toEqual(['Track 7 interval: 00:10.0 to 00:18.0', 'Representative frame: 00:12.0']);
  });

  it('lists an analytical lane it does not draw, rather than dropping it', () => {
    // Specification decision 7 leaves the presentation of multiple analytical
    // interval types open until Slice 5 has real zone, dwell and stationary
    // facts to choose against. So the seam accepts the records and the
    // accessible twin names them, and nothing is drawn for a lane whose visual
    // grammar has not been decided. This is deliberate, not an omission.
    renderTimeline(vi.fn(), {
      intervals: [
        ...intervals,
        { id: 'dwell-1', startOffsetMs: 11_000, endOffsetMs: 13_000, label: 'Dwell in Forecourt', lane: 'dwell' },
      ],
    });

    const entries = screen.getAllByRole('listitem').map((item) => item.textContent);
    expect(entries).toContain('Dwell in Forecourt: 00:11.0 to 00:13.0');
    expect(document.querySelectorAll('.evidence-timeline__interval')).toHaveLength(1);
  });

  it('holds together when the duration is not yet known', () => {
    renderTimeline(vi.fn(), { durationMs: 0 });
    const slider = screen.getByRole('slider');
    expect(slider).toHaveAttribute('aria-valuemax', '0');
    expect(slider).toHaveAttribute('aria-valuenow', '0');
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
