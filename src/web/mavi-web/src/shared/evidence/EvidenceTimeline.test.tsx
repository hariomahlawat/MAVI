import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import featuresCss from '../../styles/features.css?raw';
import EvidenceTimeline from './EvidenceTimeline';
import {
  MAX_MARKER_ROWS,
  layOutMarkers,
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
      subjectKey="track-7"
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

/**
 * Open the dense-evidence navigator and walk it end to end, collecting what
 * each step named and where it seeked.
 *
 * Written as a walk rather than as a lookup of per-item controls on purpose:
 * the point of the navigator is that there are no per-item controls, so a test
 * that found one would be testing the design it replaced.
 */
async function walkDenseEvidence(user: ReturnType<typeof userEvent.setup>) {
  const disclosure = document.querySelector('.evidence-timeline__dense') as HTMLDetailsElement | null;
  if (!disclosure) return { names: [] as string[], total: 0 };
  fireEvent.click(disclosure.querySelector('summary')!);

  const status = () => disclosure.querySelector('[role="status"]')!.textContent ?? '';
  const next = () => screen.getByRole('button', { name: 'Next' });
  const names: string[] = [];
  await user.click(next());
  const total = Number(/of (\d+)/.exec(status())?.[1] ?? 0);
  names.push(status());
  for (let step = 1; step < total; step += 1) {
    await user.click(next());
    names.push(status());
  }
  return { names, total };
}

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

  it('never places a marker on a row where its target would still collide', async () => {
    const user = userEvent.setup();
    // Four markers packed tighter than one target's worth of media. Three rows
    // can hold three of them; the fourth has nowhere clear to go. The earlier
    // layout fell back to "the row with the largest gap" even when that gap was
    // still under the threshold, which put two 24px buttons on top of each
    // other and made the lower one unclickable.
    const onSeek = renderTimeline(vi.fn(), {
      markers: [0, 1, 2, 3].map((n) => ({
        id: `d${n}`, offsetMs: 30_000 + n * 20, label: `Crossed ${n}`, kind: 'crossing',
      })),
    });

    const placed = screen.getAllByRole('listitem').filter((i) => i.className.includes('__marker'));
    expect(placed).toHaveLength(3);
    // Every placed control is on a row of its own, so none covers another.
    expect(new Set(placed.map((i) => i.style.top)).size).toBe(3);

    // And the one that could not be placed is still recoverable at its own
    // exact offset — not merged into another control, not dropped. It is not a
    // control of its own: the navigator exposes it, which is what keeps the
    // number of controls fixed however dense the evidence gets.
    const { names, total } = await walkDenseEvidence(user);
    expect(total).toBe(1);
    expect(names[0]).toMatch(/1 of 1 — Crossed 3: 00:30.0/);
    expect(onSeek).toHaveBeenCalledExactlyOnceWith(30_060);
  });

  it('measures the track rather than assuming Review is the only host', () => {
    // The same offsets are far closer together in pixels in the narrower
    // Investigation inspector, so a threshold derived from Review's width
    // under-staggers there and the operator cannot hit the markers.
    const narrow = layOutMarkers(
      [0, 1, 2].map((n) => ({ id: `n${n}`, offsetMs: 1_000 + n * 2_000, label: `m${n}`, kind: 'crossing' })),
      100_000,
      400,
    );
    const wide = layOutMarkers(
      [0, 1, 2].map((n) => ({ id: `n${n}`, offsetMs: 1_000 + n * 2_000, label: `m${n}`, kind: 'crossing' })),
      100_000,
      1_600,
    );

    // 2s apart in a 100s media is 2% of the track. At 1600px that is 32px, so
    // three 24px targets fit in one row; at 400px it is 8px, so they must
    // stagger.
    expect(wide.placed.map((p) => p.row)).toEqual([0, 0, 0]);
    expect(narrow.placed.map((p) => p.row)).toEqual([0, 1, 2]);
    expect(narrow.overflow).toHaveLength(0);
  });

  it('keeps every marker reachable however dense, without unbounded rows', async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 12 }, (_, index) => ({
      id: `m${index}`, offsetMs: 30_000 + index * 20, label: `Crossed ${index}`, kind: 'crossing',
    }));
    const onSeek = renderTimeline(vi.fn(), { markers: many });

    const placed = screen.getAllByRole('listitem').filter((i) => i.className.includes('__marker'));
    expect(placed.length).toBeLessThanOrEqual(MAX_MARKER_ROWS);

    // Every one of the twelve is reachable at its own exact millisecond — on
    // the rail where there was clearance, through the navigator where there
    // was not — so none is merged away or left unreachable.
    const { total } = await walkDenseEvidence(user);
    expect(total + placed.length).toBe(12);
    // Each step went to a different persisted millisecond, so no two do the
    // same thing and nothing was rounded to a neighbour.
    const seeked = onSeek.mock.calls.map((call: unknown[]) => call[0] as number);
    expect(new Set(seeked).size).toBe(total);
    for (const offset of seeked) expect(many.some((m) => m.offsetMs === offset)).toBe(true);
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

describe('the rail re-measures when its host changes width', () => {
  /**
   * jsdom implements neither `ResizeObserver` nor layout, so a resize has to be
   * staged: one stub that remembers the callback, and a rectangle the test
   * changes underneath it. The component sees exactly the sequence a real
   * browser delivers — observe, then a callback after the box changed.
   */
  function stageResize(width: number) {
    const callbacks: Array<() => void> = [];
    class StubResizeObserver {
      constructor(callback: () => void) { callbacks.push(callback); }
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', StubResizeObserver);
    setTrackWidth(width);
    return (next: number) => {
      setTrackWidth(next);
      act(() => { for (const callback of callbacks) callback(); });
    };
  }

  function setTrackWidth(width: number) {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      left: 100, top: 0, right: 100 + width, bottom: 22,
      width, height: 22, x: 100, y: 0, toJSON: () => ({}),
    } as DOMRect);
  }

  /** Three crossings 2s apart in a 100s media: 2% of the track, whatever it is. */
  const spaced = [0, 1, 2].map((n) => ({
    id: `s${n}`, offsetMs: 1_000 + n * 2_000, label: `Crossed ${n}`, kind: 'crossing',
  }));

  const rowsOnRail = () => new Set(
    screen.getAllByRole('listitem')
      .filter((item) => item.className.includes('__marker'))
      .map((item) => item.style.top),
  );

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('staggers markers that stop fitting when the host narrows', async () => {
    const user = userEvent.setup();
    const resizeTo = stageResize(1_600);
    const onSeek = renderTimeline(vi.fn(), { markers: spaced });

    // 32px apart at 1600px: three 24px targets sit side by side on one row.
    expect(rowsOnRail().size).toBe(1);

    resizeTo(400);

    // 8px apart at 400px: side by side they would overlap, so they stagger.
    expect(rowsOnRail().size).toBe(3);
    // And each still seeks to its own persisted millisecond after the relayout.
    await user.click(screen.getByRole('button', { name: /Seek to Crossed 2: 00:05.0/ }));
    expect(onSeek).toHaveBeenCalledExactlyOnceWith(5_000);
  });

  it('collapses the stagger again when the host widens', async () => {
    const user = userEvent.setup();
    const resizeTo = stageResize(400);
    const onSeek = renderTimeline(vi.fn(), { markers: spaced });

    expect(rowsOnRail().size).toBe(3);

    resizeTo(1_600);

    // Rows exist to avoid collisions, not for their own sake: once there is
    // room the rail flattens rather than keeping a stagger nothing needs.
    expect(rowsOnRail().size).toBe(1);
    await user.click(screen.getByRole('button', { name: /Seek to Crossed 0: 00:01.0/ }));
    expect(onSeek).toHaveBeenCalledExactlyOnceWith(1_000);
  });

  it('keeps every marker reachable in media too short to separate them', async () => {
    const user = userEvent.setup();
    stageResize(400);
    // Half a second of media with three crossings in it. No width separates
    // them, so the rail cannot hold all three — and all three must still be
    // controls that seek to their own offset, including one at zero and one at
    // the very end of the media.
    const onSeek = renderTimeline(vi.fn(), {
      durationMs: 500,
      currentOffsetMs: 0,
      intervals: [],
      markers: [
        { id: 'a', offsetMs: 0, label: 'Crossed A', kind: 'crossing' },
        { id: 'b', offsetMs: 240, label: 'Crossed B', kind: 'crossing' },
        { id: 'c', offsetMs: 500, label: 'Crossed C', kind: 'crossing' },
      ],
    });

    // All three fit here — 30ms of clearance at 400px, and they are further
    // apart than that — so all three are controls on the rail, including the
    // one at zero and the one at the very end of the media.
    const controls = screen.getAllByRole('button', { name: /Seek to Crossed/ });
    expect(controls).toHaveLength(3);
    await user.click(screen.getByRole('button', { name: /Seek to Crossed C/ }));
    expect(onSeek).toHaveBeenCalledExactlyOnceWith(500);
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

  it('sends a fourth concurrent visit off the sub-rows and keeps it recoverable', async () => {
    const user = userEvent.setup();
    const onSeek = renderTimeline(vi.fn(), { intervals: zoneVisits });
    const drawn = screen.getAllByRole('listitem')
      .filter((i) => i.dataset.lane === ZONE_LANE && i.dataset.drawn === 'true');
    expect(drawn).toHaveLength(3);

    // The overflowed visit takes no position of its own: a tick at its true
    // start covered its neighbours the moment two of them began together. The
    // rail states what is in progress instead.
    expect(screen.getByText('+1')).toBeInTheDocument();

    // And it is still named individually, with its exact persisted offsets,
    // through the navigator — which is one control, not one per visit.
    const { names, total } = await walkDenseEvidence(user);
    expect(total).toBe(1);
    expect(names[0]).toContain('In Dock for 8s');
    expect(names[0]).toContain('00:22.0 to 00:30.0');
    expect(onSeek).toHaveBeenCalledExactlyOnceWith(22_000);
  });

  it('aggregates overflow by span, not as one total for the whole timeline', () => {
    // Two separate bursts of concurrency, far apart. A single total would say
    // "+4" somewhere on the right and tell the operator nothing about where the
    // evidence is dense.
    const burst = (at: number, index: number) => ([0, 1, 2, 3, 4].map((n) => ({
      id: `b${index}-${n}`,
      startOffsetMs: at + n * 100,
      endOffsetMs: at + 5_000,
      label: `Visit ${index}-${n}`,
      lane: ZONE_LANE,
    })));
    renderTimeline(vi.fn(), { intervals: [...burst(10_000, 0), ...burst(60_000, 1)] });

    const bands = [...document.querySelectorAll('.evidence-timeline__overflow')] as HTMLElement[];
    // Two dense regions, far apart. Each band covers its own stretch and states
    // what is genuinely in progress across it; the bands never overlap, so one
    // can never be drawn over another.
    expect(bands.length).toBeGreaterThanOrEqual(2);
    for (const band of bands) expect(band.style.width).not.toBe('');
    const lefts = bands.map((band) => Number.parseFloat(band.style.left));
    for (let i = 1; i < lefts.length; i += 1) expect(lefts[i]).toBeGreaterThan(lefts[i - 1]);
    // Two regions, so the density is stated in two places rather than once for
    // the whole timeline.
    expect(new Set(lefts).size).toBe(bands.length);
    expect(lefts.some((left) => left < 50)).toBe(true);
    expect(lefts.some((left) => left >= 50)).toBe(true);
  });

  it('clusters overflowed visits that start together instead of stacking ticks', async () => {
    // Four visits with the *same* start. The earlier drawing gave each a 2px
    // tick at its start, so all four landed on the same pixel and three were
    // invisible.
    renderTimeline(vi.fn(), {
      intervals: [0, 1, 2, 3].map((n) => ({
        id: `same-${n}`, startOffsetMs: 10_000, endOffsetMs: 20_000 + n * 1_000,
        label: `Visit ${n}`, lane: ZONE_LANE,
      })),
    });
    const bands = document.querySelectorAll('.evidence-timeline__overflow');
    // One band: the active set never changes across it, so a boundary that
    // changes nothing does not split it into two.
    expect(bands).toHaveLength(1);
    expect(bands[0].getAttribute('data-concurrent')).toBe('1');
    expect((bands[0] as HTMLElement).style.width).not.toBe('');
    // And the one that overflowed is still recoverable, named with its own
    // offsets, through the one navigator.
    const { names, total } = await walkDenseEvidence(userEvent.setup());
    expect(total).toBe(1);
    expect(names[0]).toMatch(/Visit \d/);
  });

  it('lets the operator recover one exact overflowed interval', async () => {
    const user = userEvent.setup();
    const onSeek = renderTimeline(vi.fn(), { intervals: zoneVisits });

    const disclosure = document.querySelector('.evidence-timeline__dense') as HTMLDetailsElement;
    fireEvent.click(disclosure.querySelector('summary')!);
    // Nothing is singled out until the operator steps to it.
    expect(document.querySelectorAll('[data-shown="true"]')).toHaveLength(0);

    await user.click(screen.getByRole('button', { name: 'Next' }));

    // Stepping names the visit, seeks to its persisted entry and draws it at
    // its exact persisted offsets — no rounding, no aggregate stand-in.
    expect(disclosure.querySelector('[role="status"]')!.textContent)
      .toMatch(/1 of 1 — In Dock for 8s: 00:22.0 to 00:30.0/);
    expect(onSeek).toHaveBeenCalledWith(22_000);
    const shown = document.querySelector('[data-shown="true"]') as HTMLElement;
    expect(shown).toBeTruthy();
    expect(shown.textContent).toContain('In Dock for 8s');
    expect(shown.style.left).not.toBe('');
    expect(shown.style.width).not.toBe('');

    // Only ever one drawn at a time, so recovery can never add a row.
    expect(document.querySelectorAll('[data-shown="true"]')).toHaveLength(1);
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
          subjectKey="track-7"
          onSeek={vi.fn()}
        />,
      );
      const height = view.getByRole('list', { name: /timeline evidence/ }).style.height;
      view.unmount();
      return height;
    };

    // Four concurrent visits already fill the capped rows plus the rail; a
    // hundred must not make the timeline any taller than that.
    expect(heightFor(100)).toBe(heightFor(4));
  });
});

describe('dense evidence costs a fixed number of controls', () => {
  /**
   * The bound this suite asserts.
   *
   * Three: the disclosure that opens the navigator, Previous and Next. It does
   * not move with the evidence — that is the whole point of a navigator rather
   * than a list, and it is why 4, 12 and 100 members are all checked against
   * the same number.
   */
  const DENSE_CONTROL_BUDGET = 3;

  const crowd = (count: number) => Array.from({ length: count }, (_, index) => ({
    id: `v${index}`, startOffsetMs: 10_000 + index * 10, endOffsetMs: 50_000,
    label: `Visit ${index}`, lane: ZONE_LANE,
  }));

  /** Controls that exist because evidence is dense, open or closed. */
  const denseControls = () => {
    const disclosure = document.querySelector('.evidence-timeline__dense');
    if (!disclosure) return 0;
    return disclosure.querySelectorAll('summary, button').length;
  };

  it.each([4, 12, 100])('needs the same controls for %i dense visits', (count) => {
    renderTimeline(vi.fn(), { intervals: crowd(count), markers: [] });
    const disclosure = document.querySelector('.evidence-timeline__dense') as HTMLDetailsElement;
    fireEvent.click(disclosure.querySelector('summary')!);
    expect(denseControls()).toBe(DENSE_CONTROL_BUDGET);
  });

  it('creates no second evidence list, open or closed', () => {
    renderTimeline(vi.fn(), { intervals: crowd(100), markers: [] });
    // One list on the surface: the timeline itself. A hundred dense visits add
    // no parallel list of the same evidence, opened or not.
    const disclosure = document.querySelector('.evidence-timeline__dense') as HTMLDetailsElement;
    expect(document.querySelectorAll('ul')).toHaveLength(1);
    expect(document.querySelector('ul')).toHaveClass('evidence-timeline__track');
    fireEvent.click(disclosure.querySelector('summary')!);
    expect(document.querySelectorAll('ul')).toHaveLength(1);
    // And no dense member is named twice: the rail states density, the
    // navigator names one member at a time.
    const mentions = [...document.querySelectorAll('li, p')]
      .filter((node) => (node.textContent ?? '').includes('Visit 57:'));
    expect(mentions.length).toBeLessThanOrEqual(1);
  });

  it('reaches an arbitrary member of a hundred at its exact offsets', async () => {
    const user = userEvent.setup();
    const onSeek = renderTimeline(vi.fn(), { intervals: crowd(100), markers: [] });
    const disclosure = document.querySelector('.evidence-timeline__dense') as HTMLDetailsElement;
    fireEvent.click(disclosure.querySelector('summary')!);
    const status = () => disclosure.querySelector('[role="status"]')!.textContent ?? '';
    const railRows = () => new Set(
      [...document.querySelectorAll('.evidence-timeline__track > li')].map((i) => (i as HTMLElement).style.top),
    ).size;
    const rowsBefore = railRows();

    // Step to the fifth of ninety-seven and check it is that member, exactly.
    for (let i = 0; i < 5; i += 1) await user.click(screen.getByRole('button', { name: 'Next' }));
    // Three took the sub-rows, so the fifth recoverable member is Visit 7.
    expect(status()).toMatch(/^5 of 97 — Visit 7: /);
    // Its own persisted start, not the aggregate's and not a rounded one.
    expect(onSeek).toHaveBeenLastCalledWith(10_000 + 7 * 10);
    const shown = document.querySelector('[data-shown="true"]') as HTMLElement;
    expect(shown.textContent).toContain('Visit 7');
    // No new row appeared for it.
    expect(railRows()).toBe(rowsBefore);
  });

  it('stops at each end rather than wrapping past the evidence', async () => {
    const user = userEvent.setup();
    renderTimeline(vi.fn(), { intervals: crowd(4), markers: [] });
    const disclosure = document.querySelector('.evidence-timeline__dense') as HTMLDetailsElement;
    fireEvent.click(disclosure.querySelector('summary')!);
    const status = () => disclosure.querySelector('[role="status"]')!.textContent ?? '';

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(status()).toMatch(/^1 of 1 /);
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });
});

describe('the dense cursor follows the member, not its position', () => {
  it('keeps the same marker selected when a resize changes how many fit', async () => {
    const callbacks: Array<() => void> = [];
    class StubResizeObserver {
      constructor(callback: () => void) { callbacks.push(callback); }
      observe() {} unobserve() {} disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', StubResizeObserver);
    const setWidth = (width: number) => {
      vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
        left: 100, top: 0, right: 100 + width, bottom: 22,
        width, height: 22, x: 100, y: 0, toJSON: () => ({}),
      } as DOMRect);
    };
    const user = userEvent.setup();

    setWidth(400);
    renderTimeline(vi.fn(), {
      markers: Array.from({ length: 8 }, (_, index) => ({
        id: `m${index}`, offsetMs: 30_000 + index * 300, label: `Crossed ${index}`, kind: 'crossing',
      })),
    });

    const disclosure = document.querySelector('.evidence-timeline__dense') as HTMLDetailsElement;
    fireEvent.click(disclosure.querySelector('summary')!);
    const status = () => disclosure.querySelector('[role="status"]')!.textContent ?? '';
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByRole('button', { name: 'Next' }));
    const selected = /— (Crossed \d+):/.exec(status())?.[1];
    expect(selected).toBeDefined();

    // Widening lets the rail place more markers, so the dense sequence gets
    // shorter and everything after the change moves position. A cursor held by
    // position would now be pointing at different evidence; held by identity it
    // is either the same member or nothing.
    setWidth(1_600);
    act(() => { for (const callback of callbacks) callback(); });

    const after = disclosure.querySelector('[role="status"]')!.textContent ?? '';
    if (after.includes('—')) expect(after).toContain(selected!);
    vi.unstubAllGlobals();
  });
});

describe('the navigator can be left as well as entered', () => {
  it('puts the rail back when it is closed', async () => {
    const user = userEvent.setup();
    renderTimeline(vi.fn(), {
      intervals: [
        ...[0, 1, 2].map((n) => ({
          id: `filler-${n}`, startOffsetMs: 0, endOffsetMs: 30_000,
          label: `Filler ${n}`, lane: ZONE_LANE,
        })),
        { id: 'z4', startOffsetMs: 4_000, endOffsetMs: 9_000, label: 'In Dock', lane: ZONE_LANE },
      ],
    });

    const disclosure = document.querySelector('.evidence-timeline__dense') as HTMLDetailsElement;
    fireEvent.click(disclosure.querySelector('summary')!);
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(document.querySelectorAll('[data-shown="true"]')).toHaveLength(1);

    // With one member both steps are at an end, so closing the navigator is
    // the way out — an action with no undo would be worse than a third control.
    disclosure.open = false;
    fireEvent(disclosure, new Event('toggle'));
    expect(document.querySelectorAll('[data-shown="true"]')).toHaveLength(0);
  });
});

describe('transient state belongs to the subject that made it', () => {
  /** Three long visits fill the sub-rows; the fourth overflows. */
  const crowded = (label: string) => ([
    ...[0, 1, 2].map((n) => ({
      id: `filler-${n}`, startOffsetMs: 0, endOffsetMs: 30_000,
      label: `Filler ${n}`, lane: ZONE_LANE,
    })),
    // The id a real adapter produces: zone and visit index, unique within one
    // Track and identical between two Tracks through the same zone.
    { id: 'zone-visit-forecourt-0', startOffsetMs: 4_000, endOffsetMs: 9_000, label, lane: ZONE_LANE },
  ]);

  const render1 = (key: string, label: string, currentOffsetMs = 0) => (
    <EvidenceTimeline
      durationMs={100_000}
      currentOffsetMs={currentOffsetMs}
      intervals={crowded(label)}
      markers={[]}
      subjectLabel={`Person ${key}`}
      subjectKey={key}
      onSeek={vi.fn()}
    />
  );

  async function selectTheOverflowedVisit(user: ReturnType<typeof userEvent.setup>) {
    const disclosure = document.querySelector('.evidence-timeline__dense') as HTMLDetailsElement;
    fireEvent.click(disclosure.querySelector('summary')!);
    await user.click(screen.getByRole('button', { name: 'Next' }));
  }

  it('does not carry one Track\'s selection into the next Track', async () => {
    const user = userEvent.setup();
    const view = render(render1('track-a', 'In Forecourt on Track A'));
    await selectTheOverflowedVisit(user);
    expect(document.querySelectorAll('[data-shown="true"]')).toHaveLength(1);

    // The inspector keeps this component mounted across Track navigation, and
    // Track B has a visit through the same zone — so the same evidence id. It
    // must come up with nothing selected: the operator chose on Track A, and
    // that says nothing about Track B.
    view.rerender(render1('track-b', 'In Forecourt on Track B'));

    expect(document.querySelectorAll('[data-shown="true"]')).toHaveLength(0);
    const status = document.querySelector('[role="status"]')!.textContent ?? '';
    expect(status).not.toContain('Track A');
    expect(status).not.toContain('Track B');
  });

  it('does not resurrect the old selection on the way back', async () => {
    const user = userEvent.setup();
    const view = render(render1('track-a', 'In Forecourt on Track A'));
    await selectTheOverflowedVisit(user);
    view.rerender(render1('track-b', 'In Forecourt on Track B'));
    view.rerender(render1('track-a', 'In Forecourt on Track A'));

    // Returning to a Track is not the operator selecting anything. Nothing is
    // shown until they step again.
    expect(document.querySelectorAll('[data-shown="true"]')).toHaveLength(0);
  });

  it('keeps the selection while the same subject is on screen', async () => {
    const user = userEvent.setup();
    const view = render(render1('track-a', 'In Forecourt'));
    await selectTheOverflowedVisit(user);
    expect(document.querySelectorAll('[data-shown="true"]')).toHaveLength(1);

    // The playhead moving is not a change of subject.
    view.rerender(render1('track-a', 'In Forecourt', 40_000));
    expect(document.querySelectorAll('[data-shown="true"]')).toHaveLength(1);
  });

  it('keeps the selection across a resize of the same subject', async () => {
    const callbacks: Array<() => void> = [];
    class StubResizeObserver {
      constructor(callback: () => void) { callbacks.push(callback); }
      observe() {} unobserve() {} disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', StubResizeObserver);
    const user = userEvent.setup();
    render(render1('track-a', 'In Forecourt'));
    await selectTheOverflowedVisit(user);
    expect(document.querySelectorAll('[data-shown="true"]')).toHaveLength(1);

    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      left: 100, top: 0, right: 1_700, bottom: 22, width: 1_600, height: 22, x: 100, y: 0, toJSON: () => ({}),
    } as DOMRect);
    act(() => { for (const callback of callbacks) callback(); });

    // Re-measuring the rail is not a change of subject either.
    expect(document.querySelectorAll('[data-shown="true"]')).toHaveLength(1);
    vi.unstubAllGlobals();
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
