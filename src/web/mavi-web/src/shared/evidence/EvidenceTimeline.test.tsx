import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import featuresCss from '../../styles/features.css?raw';
import EvidenceTimeline from './EvidenceTimeline';
import {
  MAX_MARKER_ROWS,
  STATIONARY_LANE,
  SUBJECT_LANE,
  ZONE_LANE,
  clampOffset,
  offsetFromPointer,
  percentOf,
  ratioOf,
} from './timeline';

/**
 * One declaration block from the feature stylesheet, comments stripped.
 *
 * Prose in a comment can contain the very property a rule must not use, so the
 * comments come out before anything is matched.
 */
function ruleFor(selector: string): string | undefined {
  return featuresCss
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('}')
    .map((block) => block + '}')
    .find((block) => block.includes(selector));
}

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
    const items = screen.getAllByRole('listitem').filter((item) => item.textContent);
    expect(items.map((item) => item.textContent)).toEqual([
      'Track 7 interval: 00:10.0 to 00:18.0',
      'Seek to Representative frame: 00:12.0',
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
    const interval = screen.getAllByRole('listitem').find((i) => i.className.includes('__interval'))!;
    const marker = screen.getAllByRole('listitem').find((i) => i.className.includes('__marker'))!;
    // Shape and wording, not hue: an interval names a span and is a band, a
    // marker names one instant and is a control that seeks to it.
    expect(interval).toHaveClass('evidence-timeline__interval');
    expect(interval.textContent).toMatch(/\d to \d/);
    expect(interval.style.width).not.toBe('');
    expect(marker).toHaveClass('evidence-timeline__marker');
    expect(marker.textContent).not.toMatch(/\d to \d/);
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
    expect(dwell).not.toHaveAttribute('hidden');
    // Still named for everyone, still not given a shape nobody has chosen.
    expect(document.querySelectorAll('[data-drawn="true"]')).toHaveLength(1);
  });

  it('suppresses the undrawn band without deleting it from the accessibility tree', () => {
    // A DOM-text assertion alone is exactly what let this through: the markup
    // named the interval while the stylesheet removed it, which takes the
    // visually hidden name out of the accessibility tree along with the band.
    // jsdom applies no stylesheet, so the rule is read directly.
    const rule = ruleFor(".evidence-timeline__interval[data-drawn='false']");
    expect(rule, 'the undrawn-interval rule should exist').toBeDefined();
    expect(rule).not.toMatch(/display\s*:\s*none/);
    expect(rule).not.toMatch(/visibility\s*:\s*hidden/);
    expect(rule).not.toMatch(/content-visibility\s*:\s*hidden/);
    // It suppresses the band itself, which is what "named but not drawn" means.
    expect(rule).toMatch(/background\s*:\s*none/);
  });

  it('gives the scrub bar and every marker control a pointer target of at least 24px', () => {
    renderTimeline();
    // The track's height is computed from the lanes the evidence actually
    // needs, so it is read from the rendered element rather than the rule; the
    // marker rail alone is 24px, so the scrub surface can never be smaller.
    const track = screen.getByRole('list');
    expect(Number.parseInt(track.style.height, 10)).toBeGreaterThanOrEqual(24);

    const rule = ruleFor('.evidence-timeline__marker-button {');
    expect(rule, 'the marker control rule should exist').toBeDefined();
    expect(Number(/width:\s*(\d+)px/.exec(rule ?? '')?.[1])).toBeGreaterThanOrEqual(24);
    expect(Number(/height:\s*(\d+)px/.exec(rule ?? '')?.[1])).toBeGreaterThanOrEqual(24);
    // The tick drawn inside stays thin; the target is the button around it.
    const tick = ruleFor('.evidence-timeline__marker-tick {');
    expect(Number(/width:\s*(\d+)px/.exec(tick ?? '')?.[1])).toBeLessThan(24);
  });

  it('holds together when the duration is not yet known', () => {
    renderTimeline(vi.fn(), { durationMs: 0 });
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });
});

describe('analytical markers seek exactly', () => {
  const crossing = { id: 'x1', offsetMs: 12_345, label: 'Crossed Gate line Inbound', kind: 'crossing' };

  it('seeks to the persisted offset on pointer activation, not to where the pointer landed', async () => {
    const user = userEvent.setup();
    const onSeek = renderTimeline(vi.fn(), { markers: [crossing] });

    await user.click(screen.getByRole('button', { name: /Crossed Gate line Inbound/ }));
    // The exact persisted millisecond. A scrub-derived offset would be some
    // function of clientX and the track rectangle, and would never be 12345.
    expect(onSeek).toHaveBeenCalledWith(12_345);
    expect(onSeek).toHaveBeenCalledTimes(1);
  });

  it('does not let the press first drag the playhead to an approximate offset', () => {
    // The track scrubs on pointer-down. Before the marker stopped that
    // propagation, activating a crossing seeked twice: once to wherever the
    // press landed, then to the exact offset — a visible wrong jump, and a
    // drag that could carry the playhead away entirely.
    const onSeek = renderTimeline(vi.fn(), { markers: [crossing] });
    const button = screen.getByRole('button', { name: /Crossed Gate line/ });

    fireEvent.pointerDown(button, { button: 0, clientX: 300 });
    expect(onSeek).not.toHaveBeenCalled();

    // And the scrub never starts, so moving the pointer afterwards is not a seek.
    fireEvent.pointerMove(window, { clientX: 200 });
    expect(onSeek).not.toHaveBeenCalled();

    fireEvent.click(button);
    expect(onSeek).toHaveBeenCalledExactlyOnceWith(12_345);
  });

  it('seeks exactly from Enter and from Space', async () => {
    const user = userEvent.setup();
    const onSeek = renderTimeline(vi.fn(), { markers: [crossing] });
    const button = screen.getByRole('button', { name: /Crossed Gate line/ });

    button.focus();
    await user.keyboard('{Enter}');
    expect(onSeek).toHaveBeenLastCalledWith(12_345);
    await user.keyboard(' ');
    expect(onSeek).toHaveBeenLastCalledWith(12_345);
    expect(onSeek).toHaveBeenCalledTimes(2);
  });

  it('leaves the player grammar alone while a marker has focus', () => {
    // One contract for the whole player. A marker that answered the arrows
    // itself would give the same key two meanings depending on focus.
    const onSeek = renderTimeline(vi.fn(), { markers: [crossing] });
    const button = screen.getByRole('button', { name: /Crossed Gate line/ });
    button.focus();
    for (const key of ['ArrowLeft', 'ArrowRight', 'j', 'l', 'Home', 'End']) {
      fireEvent.keyDown(button, { key });
    }
    expect(onSeek).not.toHaveBeenCalled();
  });

  it('uses the same exact-seek control for the representative frame', () => {
    // Not two marker interaction contracts: the representative frame is an
    // instant like any other, and it seeks the same way.
    const onSeek = renderTimeline();
    fireEvent.click(screen.getByRole('button', { name: /Representative frame/ }));
    expect(onSeek).toHaveBeenCalledExactlyOnceWith(12_000);
  });
});

describe('dense markers stay usable', () => {
  it('keeps markers at different offsets separately activatable on different rows', async () => {
    const user = userEvent.setup();
    // Three crossings 200ms apart in a 100s media: far under the collision
    // threshold, so their 24px targets would otherwise overlap.
    const onSeek = renderTimeline(vi.fn(), {
      markers: [
        { id: 'a', offsetMs: 30_000, label: 'Crossed A', kind: 'crossing' },
        { id: 'b', offsetMs: 30_200, label: 'Crossed B', kind: 'crossing' },
        { id: 'c', offsetMs: 30_400, label: 'Crossed C', kind: 'crossing' },
      ],
    });

    const items = screen.getAllByRole('listitem').filter((i) => i.className.includes('__marker'));
    expect(items).toHaveLength(3);
    // Staggered onto distinct rows, so no target sits on top of another.
    expect(new Set(items.map((i) => i.style.top)).size).toBe(3);

    // Each remains its own control and seeks to its own offset.
    for (const [name, offset] of [['Crossed A', 30_000], ['Crossed B', 30_200], ['Crossed C', 30_400]] as const) {
      await user.click(screen.getByRole('button', { name: new RegExp(name) }));
      expect(onSeek).toHaveBeenLastCalledWith(offset);
    }
    expect(onSeek).toHaveBeenCalledTimes(3);
  });

  it('never grows the marker rail beyond its fixed row count', () => {
    const many = Array.from({ length: 30 }, (_, index) => ({
      id: `m${index}`, offsetMs: 30_000 + index * 50, label: `Crossed ${index}`, kind: 'crossing',
    }));
    renderTimeline(vi.fn(), { markers: many });
    const rows = new Set(
      screen.getAllByRole('listitem').filter((i) => i.className.includes('__marker')).map((i) => i.style.top),
    );
    expect(rows.size).toBeLessThanOrEqual(MAX_MARKER_ROWS);
  });

  it('clusters only what shares one exact destination, and names all of it', async () => {
    const user = userEvent.setup();
    // Two facts at the same instant: leaving one zone and entering the next.
    // One control, because there is one place to seek to — and its name has to
    // carry both, or the second piece of evidence would be unreachable.
    const onSeek = renderTimeline(vi.fn(), {
      markers: [
        { id: 'exit', offsetMs: 20_000, label: 'Left Forecourt', kind: 'zone-exit' },
        { id: 'entry', offsetMs: 20_000, label: 'Entered Loading bay', kind: 'zone-entry' },
      ],
    });

    const controls = screen.getAllByRole('button');
    expect(controls).toHaveLength(1);
    expect(controls[0]).toHaveAccessibleName(/Left Forecourt; Entered Loading bay/);
    await user.click(controls[0]);
    expect(onSeek).toHaveBeenCalledExactlyOnceWith(20_000);
  });

  it('never clusters markers at different offsets, however close', () => {
    renderTimeline(vi.fn(), {
      markers: [
        { id: 'a', offsetMs: 30_000, label: 'Crossed A', kind: 'crossing' },
        { id: 'b', offsetMs: 30_001, label: 'Crossed B', kind: 'crossing' },
      ],
    });
    // One millisecond apart is still two destinations, so it stays two controls.
    expect(screen.getAllByRole('button')).toHaveLength(2);
  });
});

describe('analytical lane families (decision 7)', () => {
  const zoneVisits = [
    { id: 'z1', startOffsetMs: 10_000, endOffsetMs: 30_000, label: 'In Forecourt for 20s', lane: ZONE_LANE },
    { id: 'z2', startOffsetMs: 15_000, endOffsetMs: 30_000, label: 'In Loading bay for 15s', lane: ZONE_LANE },
    { id: 'z3', startOffsetMs: 20_000, endOffsetMs: 30_000, label: 'In Yard for 10s', lane: ZONE_LANE },
    { id: 'z4', startOffsetMs: 22_000, endOffsetMs: 30_000, label: 'In Dock for 8s', lane: ZONE_LANE },
  ];

  it('draws each family at its own fixed vertical position', () => {
    renderTimeline(vi.fn(), {
      intervals: [
        ...intervals,
        { id: 'z1', startOffsetMs: 11_000, endOffsetMs: 14_000, label: 'In Forecourt for 3s', lane: ZONE_LANE },
        { id: 's1', startOffsetMs: 12_000, endOffsetMs: 13_000, label: 'Stationary for 1s', lane: STATIONARY_LANE },
      ],
    });

    const lanes = new Map(
      screen.getAllByRole('listitem')
        .filter((i) => i.dataset.lane)
        .map((i) => [i.dataset.lane, i.style.top]),
    );
    expect(lanes.size).toBe(3);
    // Three distinct positions: position is a non-colour cue for which family
    // an interval belongs to, and a shared row would erase it.
    expect(new Set(lanes.values()).size).toBe(3);
    for (const [, top] of lanes) expect(top).not.toBe('');
  });

  it('separates overlapping zone visits instead of painting them over each other', () => {
    renderTimeline(vi.fn(), { intervals: zoneVisits.slice(0, 3) });
    const drawn = screen.getAllByRole('listitem').filter((i) => i.dataset.lane === ZONE_LANE);
    expect(drawn).toHaveLength(3);
    expect(drawn.every((i) => i.dataset.drawn === 'true')).toBe(true);
    // Three concurrent visits, three distinct rows.
    expect(new Set(drawn.map((i) => i.style.top)).size).toBe(3);
  });

  it('sends a fourth concurrent visit to the overflow rail with its count, keeping its identity', () => {
    renderTimeline(vi.fn(), { intervals: zoneVisits });
    const zoneItems = screen.getAllByRole('listitem').filter((i) => i.dataset.lane === ZONE_LANE);
    expect(zoneItems).toHaveLength(4);

    const overflowed = zoneItems.filter((i) => i.dataset.drawn === 'overflow');
    expect(overflowed).toHaveLength(1);
    // Still named individually, still positioned at its own start: the exact
    // persisted interval can be identified and highlighted.
    expect(overflowed[0].textContent).toContain('In Dock for 8s');
    expect(overflowed[0].textContent).toContain('00:22.0 to 00:30.0');
    expect(overflowed[0].textContent).toContain('one of 4 overlapping visits');
    expect(overflowed[0].style.left).not.toBe('');
    // And the rail says how much is aggregated there.
    expect(screen.getByText('+1')).toBeInTheDocument();
  });

  it('keeps the timeline height bounded however many visits overlap', () => {
    const heightFor = (count: number) => {
      const view = render(
        <EvidenceTimeline
          durationMs={100_000}
          currentOffsetMs={0}
          intervals={Array.from({ length: count }, (_, index) => ({
            id: `v${index}`, startOffsetMs: index * 10, endOffsetMs: 50_000,
            label: `Visit ${index}`, lane: ZONE_LANE,
          }))}
          markers={[]}
          subjectLabel="Person Track 7"
          onSeek={vi.fn()}
        />,
      );
      const height = view.getByRole('list').style.height;
      view.unmount();
      return height;
    };

    // Four concurrent visits already fill the capped rows plus the rail; a
    // hundred must not make the timeline any taller than that.
    expect(heightFor(100)).toBe(heightFor(4));
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
