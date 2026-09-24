import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TrackDetail } from '../../api/tracks';
import { EVIDENCE_PLAYER_ATTRIBUTE } from '../../shared/evidence/EvidencePlayer';
import {
  DISAGREEING_REPRESENTATIVE,
  evidenceObservation,
  evidenceSet,
  FULL_EVIDENCE_SET_ROLES,
  trackDetailWithEvidence,
} from '../../test/trackEvidenceFixtures';
import { TrackIdentity } from './TrackDetailsPanels';
import TrackEvidence from './TrackEvidence';
import TrackEvidenceSet from './TrackEvidenceSet';

/**
 * The Evidence Set as both hosts compose it: the Track's Evidence Player, and
 * beside it, outside the player's root, the Evidence Set and the Track
 * identity. Every assertion about "the video did not move" is made against
 * the one real player, not a mock of it.
 */
function Host({ detail }: { detail: TrackDetail }) {
  return (
    <>
      <TrackEvidence detail={detail} />
      <TrackEvidenceSet detail={detail} />
      <TrackIdentity detail={detail} />
    </>
  );
}

const full = () => trackDetailWithEvidence(evidenceSet(FULL_EVIDENCE_SET_ROLES));

function video(): HTMLVideoElement {
  return screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;
}

function seek(seconds: number) {
  video().currentTime = seconds;
  fireEvent(video(), new Event('seeked'));
}

function strip() {
  return screen.getByRole('list', { name: 'Evidence Set observations' });
}

function control(name: string | RegExp) {
  return within(strip()).getByRole('button', { name });
}

function inspection() {
  return screen.getByRole('figure', { name: /^Inspecting / });
}

let play: ReturnType<typeof vi.fn>;
/** Seconds of media the element reports; the fixture Track sits at 10–18 s. */
let mediaDuration = 600;
let pause: ReturnType<typeof vi.fn>;
let restore: Array<() => void> = [];

function override(target: object, name: string, descriptor: PropertyDescriptor) {
  const original = Object.getOwnPropertyDescriptor(target, name);
  Object.defineProperty(target, name, { configurable: true, ...descriptor });
  restore.push(() => {
    if (original) Object.defineProperty(target, name, original);
    else delete (target as Record<string, unknown>)[name];
  });
}

beforeEach(() => {
  window.localStorage.clear();
  // jsdom lays nothing out and plays nothing, so both are stood in for.
  override(HTMLElement.prototype, 'clientWidth', { get: () => 1000 });
  override(HTMLElement.prototype, 'clientHeight', { get: () => 300 });
  mediaDuration = 600;
  override(HTMLMediaElement.prototype, 'duration', { get: () => mediaDuration });
  play = vi.fn(() => Promise.resolve());
  pause = vi.fn();
  override(HTMLMediaElement.prototype, 'play', { value: play });
  override(HTMLMediaElement.prototype, 'pause', { value: pause });
});

afterEach(() => {
  restore.forEach((fn) => fn());
  restore = [];
});

describe('the Evidence Set strip', () => {
  it('shows a four-role v3 set in rank order with role labels and exact offsets', () => {
    render(<Host detail={full()} />);

    // Rank order, not time order: Early diverse is the earliest frame and still
    // third, because rank is the order.
    const names = within(strip()).getAllByRole('button').map((button) => button.getAttribute('aria-label'));
    expect(names).toEqual([
      'Representative · 00:12.0',
      'Near view · 00:14.6',
      'Early diverse · 00:10.4',
      'Late diverse · 00:16.8',
    ]);
    const items = within(strip()).getAllByRole('listitem');
    expect(items.map((item) => item.textContent)).toEqual([
      'Representative00:12.0',
      'Near view00:14.6',
      'Early diverse00:10.4',
      'Late diverse00:16.8',
    ]);
  });

  it('keeps DOM order equal to rank even when rank order runs against time, score and id order', () => {
    const observations = [
      evidenceObservation('Representative', 0, { videoOffsetMs: 16_000, selectionScore: 0.1, observationId: 'd' }),
      evidenceObservation('NearView', 1, { videoOffsetMs: 15_000, selectionScore: 0.9, observationId: 'c' }),
      evidenceObservation('EarlyDiverse', 2, { videoOffsetMs: 11_000, selectionScore: 0.5, observationId: 'b' }),
      evidenceObservation('LateDiverse', 3, { videoOffsetMs: 17_500, selectionScore: 0.7, observationId: 'a' }),
    ];
    render(<Host detail={trackDetailWithEvidence(observations)} />);

    const roles = within(strip()).getAllByRole('button').map((button) => button.getAttribute('data-role'));
    expect(roles).toEqual(['Representative', 'NearView', 'EarlyDiverse', 'LateDiverse']);
  });

  it('shows a Representative-only historical Track as a one-item set', () => {
    // Historical v2: its crop is a Thumbnail artifact, served the same way.
    render(<Host detail={trackDetailWithEvidence(evidenceSet(['Representative']))} />);

    expect(within(strip()).getAllByRole('button')).toHaveLength(1);
    expect(control('Representative · 00:12.0')).toHaveAttribute('aria-current', 'true');
    expect(within(inspection()).getByRole('img', { name: 'Representative · 00:12.0 evidence crop' })).toBeInTheDocument();
  });

  it.each([
    [['Representative', 'NearView'] as const],
    [['Representative', 'LateDiverse'] as const],
    [['Representative', 'EarlyDiverse', 'LateDiverse'] as const],
  ])('shows a partial set %j with no error for the omitted roles', (roles) => {
    render(<Host detail={trackDetailWithEvidence(evidenceSet(roles))} />);

    expect(within(strip()).getAllByRole('button').map((button) => button.getAttribute('data-role'))).toEqual([...roles]);
    // An omitted supplemental role is a valid bounded omission, not a failure.
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows the legacy shape as a plain statement, not an error and not fabricated evidence', () => {
    render(<Host detail={trackDetailWithEvidence([])} />);

    expect(screen.getByText('No Evidence Set was persisted for this Track.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Evidence Set observations' })).not.toBeInTheDocument();
    expect(screen.queryByRole('figure')).not.toBeInTheDocument();
  });
});

describe('crop inspection', () => {
  it('inspects rank 0 first and follows each selection, changing nothing in the source video', async () => {
    const user = userEvent.setup();
    render(<Host detail={full()} />);
    seek(20);
    const markersBefore = screen.getAllByRole('button', { name: /^Seek to / }).map((b) => b.textContent);

    expect(inspection()).toHaveAccessibleName('Inspecting Representative · 00:12.0');

    for (const name of ['Near view · 00:14.6', 'Early diverse · 00:10.4', 'Late diverse · 00:16.8', 'Representative · 00:12.0']) {
      await user.click(control(name));

      expect(inspection()).toHaveAccessibleName('Inspecting ' + name);
      expect(within(inspection()).getByRole('img', { name: name + ' evidence crop' })).toBeInTheDocument();
      // Exactly one control is the inspected one.
      const current = within(strip()).getAllByRole('button').filter((b) => b.getAttribute('aria-current') === 'true');
      expect(current).toHaveLength(1);
      expect(current[0]).toHaveAccessibleName(name);
      // The source video: same position, never played or paused.
      expect(video().currentTime).toBe(20);
      expect(play).not.toHaveBeenCalled();
      expect(pause).not.toHaveBeenCalled();
    }

    // The overlay state is the player's, and selection did not change it.
    expect(screen.getAllByRole('button', { name: /^Seek to / }).map((b) => b.textContent)).toEqual(markersBefore);
  });

  it('shows the selected crop in the inspection region with its facts, not as a source frame', async () => {
    const user = userEvent.setup();
    render(<Host detail={full()} />);

    await user.click(control('Near view · 00:14.6'));
    const figure = inspection();
    expect(within(figure).getByRole('img')).toHaveAttribute('src', '/api/artifacts/018f3f5a-2f70-7a2b-8a12-2d02f4c21482/content');
    expect(figure).toHaveTextContent('Near view');
    expect(figure).toHaveTextContent('00:14.6');
    expect(figure).toHaveTextContent('Frame 365');
    expect(figure).toHaveTextContent('93.0% confidence');
    // The crop is inside the Evidence Set, never inside the player's stage.
    expect(figure.closest('.evidence-player')).toBeNull();
  });

  it('selects with Enter and with Space, and neither plays the video', async () => {
    const user = userEvent.setup();
    render(<Host detail={full()} />);

    control('Near view · 00:14.6').focus();
    await user.keyboard('{Enter}');
    expect(inspection()).toHaveAccessibleName('Inspecting Near view · 00:14.6');

    control('Late diverse · 00:16.8').focus();
    await user.keyboard(' ');
    expect(inspection()).toHaveAccessibleName('Inspecting Late diverse · 00:16.8');

    expect(play).not.toHaveBeenCalled();
    expect(pause).not.toHaveBeenCalled();
  });
});

describe('unavailable crops', () => {
  it('keeps an Observation whose crop fails to load, with its role and offset, in a box of the same size', async () => {
    const user = userEvent.setup();
    render(<Host detail={full()} />);

    const thumb = within(control('Near view · 00:14.6')).getByRole('img');
    const box = thumb.parentElement!;
    fireEvent.error(thumb);

    const failed = control('Near view · 00:14.6, evidence image unavailable');
    expect(failed).toHaveTextContent('Image unavailable');
    expect(failed).toHaveTextContent('Near view');
    expect(failed).toHaveTextContent('00:14.6');
    // The same box stays in place: the placeholder replaces the image inside it.
    expect(box.isConnected).toBe(true);
    expect(box).toHaveClass('evidence-set__thumb');
    expect(within(strip()).getAllByRole('button')).toHaveLength(4);

    await user.click(failed);
    expect(within(inspection()).getByText('Evidence image unavailable.')).toBeInTheDocument();
    expect(within(inspection()).queryByRole('img')).not.toBeInTheDocument();
    // Other crops are unaffected by one failure.
    expect(within(control('Early diverse · 00:10.4')).getByRole('img')).toBeInTheDocument();
  });

  it('states a crop that was never persisted explicitly, distinct from one that failed', async () => {
    const user = userEvent.setup();
    const observations = evidenceSet(['Representative', 'NearView']);
    observations[1] = { ...observations[1], evidenceArtifactId: null, evidenceContentUrl: null };
    render(<Host detail={trackDetailWithEvidence(observations)} />);

    const absent = control('Near view · 00:14.6, evidence image unavailable');
    expect(within(absent).queryByRole('img')).not.toBeInTheDocument();
    await user.click(absent);
    expect(within(inspection()).getByText('No evidence image was persisted for this observation.')).toBeInTheDocument();
  });

  it('keeps the crops readable when the source video fails', () => {
    render(<Host detail={full()} />);
    fireEvent.error(video());

    expect(screen.getByText(/Source video could not be loaded/i)).toBeInTheDocument();
    expect(within(inspection()).getByRole('img', { name: 'Representative · 00:12.0 evidence crop' })).toBeInTheDocument();
    expect(within(strip()).getAllByRole('img')).toHaveLength(4);
  });

  it('keeps the video usable when every crop fails', () => {
    render(<Host detail={full()} />);
    for (const img of within(strip()).getAllByRole('img')) fireEvent.error(img);

    expect(within(strip()).getAllByRole('button')).toHaveLength(4);
    expect(screen.queryByText(/Source video could not be loaded/i)).not.toBeInTheDocument();
    expect(video()).toHaveAttribute('src', '/api/videos/v/content');
  });
});

describe('keyboard ownership', () => {
  it('leaves the player grammar untouched when focus is on a crop control', async () => {
    const user = userEvent.setup();
    render(<Host detail={full()} />);
    seek(20);

    control('Near view · 00:14.6').focus();
    // J, L, arrows, Home, End and E: each would move the playhead from inside
    // the player. From the strip they are not player keys.
    await user.keyboard('j');
    await user.keyboard('J');
    await user.keyboard('l');
    await user.keyboard('{ArrowLeft}');
    await user.keyboard('{ArrowRight}');
    await user.keyboard('{Home}');
    await user.keyboard('{End}');
    await user.keyboard('e');
    await user.keyboard('E');

    expect(video().currentTime).toBe(20);
    expect(play).not.toHaveBeenCalled();
    expect(pause).not.toHaveBeenCalled();
    // Nor did any of them select a different crop.
    expect(inspection()).toHaveAccessibleName('Inspecting Representative · 00:12.0');
  });

  it('is a real test: the same keys do move the playhead from the player frame', async () => {
    const user = userEvent.setup();
    render(<Host detail={full()} />);
    seek(20);

    screen.getByRole('group', { name: /evidence frame/ }).focus();
    await user.keyboard('l');
    expect(video().currentTime).toBeCloseTo(21, 3);
    await user.keyboard('e');
    expect(video().currentTime).toBeCloseTo(12, 3);
  });

  it('sits outside the player root and carries the player subtree contract for result navigation', () => {
    render(<Host detail={full()} />);
    const set = screen.getByRole('region', { name: 'Evidence Set' });

    expect(set).toHaveAttribute(EVIDENCE_PLAYER_ATTRIBUTE, '');
    expect(set.closest('.evidence-player')).toBeNull();
    expect(set.querySelector('.evidence-player')).toBeNull();
  });
});

describe('one source video, one timeline', () => {
  it('mounts no media of its own: the player video is the only video', () => {
    const { container } = render(<Host detail={full()} />);
    expect(container.querySelectorAll('video')).toHaveLength(1);

    const alone = render(<TrackEvidenceSet detail={full()} />);
    expect(alone.container.querySelectorAll('video, audio')).toHaveLength(0);
  });

  it('gives every Observation one exact-seek marker and the Representative exactly one', async () => {
    const user = userEvent.setup();
    // A short clip, so the rail has room for every marker side by side.
    mediaDuration = 20;
    render(<Host detail={trackDetailWithEvidence(evidenceSet(FULL_EVIDENCE_SET_ROLES), {
      video: { ...full().video, durationMs: 20_000 },
    })} />);

    const markers = screen.getAllByRole('button', { name: /^Seek to / });
    expect(markers.map((marker) => marker.textContent)).toEqual([
      'Seek to Early diverse evidence: 00:10.4',
      'Seek to Representative frame: 00:12.0',
      'Seek to Near view evidence: 00:14.6',
      'Seek to Late diverse evidence: 00:16.8',
    ]);
    expect(markers.filter((marker) => /Representative/.test(marker.textContent ?? ''))).toHaveLength(1);
    expect(document.querySelectorAll('.evidence-timeline__marker[data-kind="representative"]')).toHaveLength(1);
    expect(document.querySelectorAll('.evidence-timeline__marker[data-kind="evidence"]')).toHaveLength(3);

    // The existing marker path seeks to the exact persisted offset.
    await user.click(screen.getByRole('button', { name: 'Seek to Near view evidence: 00:14.6' }));
    expect(video().currentTime).toBeCloseTo(14.6, 6);
  });

  it('keeps a marker the saturated rail cannot place reachable, once, through the existing navigator', async () => {
    const user = userEvent.setup();
    // Four instants inside eight seconds of a ten-minute video: the timeline's
    // three marker rows are full, so its dense navigator carries the fourth.
    // Still one marker per Observation, and still an exact seek.
    render(<Host detail={full()} />);

    const placed = screen.getAllByRole('button', { name: /^Seek to / }).map((marker) => marker.textContent);
    expect(placed).toEqual([
      'Seek to Early diverse evidence: 00:10.4',
      'Seek to Representative frame: 00:12.0',
      'Seek to Near view evidence: 00:14.6',
    ]);

    const navigator = document.querySelector('.evidence-timeline__dense') as HTMLDetailsElement;
    fireEvent.click(navigator.querySelector('summary')!);
    await user.click(within(navigator).getByRole('button', { name: 'Next' }));
    expect(within(navigator).getByRole('status')).toHaveTextContent('1 of 1');
    expect(within(navigator).getByRole('status')).toHaveTextContent('Late diverse evidence');
    expect(video().currentTime).toBeCloseTo(16.8, 6);
  });
});

describe('rank 0 is the only Representative, whatever the compatibility object says', () => {
  function disagreeing() {
    return trackDetailWithEvidence(evidenceSet(FULL_EVIDENCE_SET_ROLES), { representative: DISAGREEING_REPRESENTATIVE });
  }

  it('drives the Representative marker and the E target from rank 0', async () => {
    const user = userEvent.setup();
    render(<Host detail={disagreeing()} />);

    expect(screen.getByRole('button', { name: 'Seek to Representative frame: 00:12.0' })).toBeInTheDocument();
    expect(screen.queryByText(/00:03\.3/)).not.toBeInTheDocument();

    seek(40);
    screen.getByRole('group', { name: /evidence frame/ }).focus();
    await user.keyboard('e');
    expect(video().currentTime).toBeCloseTo(12, 3);
  });

  it('drives the Representative bounding box and its description from rank 0', () => {
    render(<Host detail={disagreeing()} />);

    seek(12);
    expect(screen.getByTestId('bounding-box')).toBeInTheDocument();
    expect(screen.getByText(/persisted for the frame at 00:12\.0, 96% confidence/)).toHaveTextContent(
      'Normalised source frame: x 0.500, y 0.500, width 0.250, height 0.500.',
    );

    // At the compatibility object's offset nothing is drawn: it is not evidence here.
    seek(3.3);
    expect(screen.queryByTestId('bounding-box')).not.toBeInTheDocument();
  });

  it('drives the Track identity Representative scalars from rank 0', () => {
    render(<Host detail={disagreeing()} />);

    const value = (label: string) => screen.getByText(label).nextElementSibling?.textContent;
    expect(value('Source frame')).toBe('300');
    expect(value('Video offset')).toBe('00:12.0');
    expect(value('Representative confidence')).toBe('96.0%');
    expect(value('Quality score')).toBe('0.900');
    expect(screen.queryByText('9999')).not.toBeInTheDocument();
    expect(screen.queryByText('0.222')).not.toBeInTheDocument();
  });

  it('shows rank 0 as the Representative crop and never the compatibility crop', () => {
    const { container } = render(<Host detail={disagreeing()} />);

    expect(within(inspection()).getByRole('img')).toHaveAttribute('src', '/api/artifacts/018f3f5a-2f70-7a2b-8a12-2d02f4c21481/content');
    expect(container.innerHTML).not.toContain(DISAGREEING_REPRESENTATIVE.thumbnailContentUrl!);
    expect(container.innerHTML).not.toContain(DISAGREEING_REPRESENTATIVE.observationId);
  });
});
