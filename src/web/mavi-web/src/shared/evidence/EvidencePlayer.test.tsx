import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import EvidencePlayer from './EvidencePlayer';
import {
  evidenceDrawSentence,
  layerPreferenceSentence,
  type EvidenceLayer,
  type NonSpatialEvidenceLayer,
  type SpatialEvidenceLayer,
} from './layers';
import { frameDurationSeconds } from './useEvidenceTransport';
import { SUBJECT_LANE } from './timeline';

const SOURCE = '/api/videos/v/content';

/** jsdom implements neither playback nor layout, so both are stood in for. */
function stubMedia() {
  const play = vi.fn(() => {
    Object.defineProperty(video(), 'paused', { configurable: true, value: false });
    fireEvent(video(), new Event('play'));
    return Promise.resolve();
  });
  const pause = vi.fn(() => {
    Object.defineProperty(video(), 'paused', { configurable: true, value: true });
    fireEvent(video(), new Event('pause'));
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'play', { configurable: true, value: play });
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', { configurable: true, value: pause });
  return { play, pause };
}

function video(): HTMLVideoElement {
  return screen.getByLabelText(/source video evidence$/) as HTMLVideoElement;
}

let restore: Array<() => void> = [];

beforeEach(() => {
  window.localStorage.clear();
  for (const [name, value] of Object.entries({ clientWidth: 800, clientHeight: 450 })) {
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, name);
    Object.defineProperty(HTMLElement.prototype, name, { configurable: true, get: () => value });
    restore.push(() => {
      if (original) Object.defineProperty(HTMLElement.prototype, name, original);
      else delete (HTMLElement.prototype as unknown as Record<string, unknown>)[name];
    });
  }
  // A finite duration, as an element with metadata would report.
  const duration = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'duration');
  Object.defineProperty(HTMLMediaElement.prototype, 'duration', { configurable: true, get: () => 600 });
  restore.push(() => {
    if (duration) Object.defineProperty(HTMLMediaElement.prototype, 'duration', duration);
  });
});

afterEach(() => {
  restore.forEach((fn) => fn());
  restore = [];
  vi.restoreAllMocks();
});

function renderPlayer(overrides: Partial<React.ComponentProps<typeof EvidencePlayer>> = {}) {
  return render(
    <EvidencePlayer
      sourceUrl={SOURCE}
      declaredDurationMs={600_000}
      declaredWidth={1920}
      declaredHeight={1080}
      frameRate={{ numerator: 25, denominator: 1 }}
      subject={{ label: 'Person Track 7', startOffsetMs: 10_000, endOffsetMs: 18_000 }}
      representative={{ offsetMs: 12_000 }}
      layers={[]}
      intervals={[{ id: 's', startOffsetMs: 10_000, endOffsetMs: 18_000, label: 'Track 7 interval', lane: SUBJECT_LANE }]}
      markers={[{ id: 'r', offsetMs: 12_000, label: 'Representative frame', kind: 'representative' }]}
      seekKey="track-1"
      preferenceScope="test"
      {...overrides}
    />,
  );
}

describe('Evidence Player transport', () => {
  it('uses no native browser controls', () => {
    renderPlayer();
    // Section 18 and section 30: native controls occupy the band where evidence
    // is drawn and behave differently in every browser.
    expect(video()).not.toHaveAttribute('controls');
  });

  it('plays and pauses from its own control', async () => {
    const media = stubMedia();
    const user = userEvent.setup();
    renderPlayer();

    await user.click(screen.getByRole('button', { name: 'Play' }));
    expect(media.play).toHaveBeenCalled();
    await user.click(await screen.findByRole('button', { name: 'Pause' }));
    expect(media.pause).toHaveBeenCalled();
  });

  it('steps by the source frame duration, not an assumed frame rate', async () => {
    const user = userEvent.setup();
    // 30000/1001 is the NTSC-derived rate an integer assumption gets wrong.
    renderPlayer({ frameRate: { numerator: 30_000, denominator: 1001 } });
    video().currentTime = 20;

    await user.click(screen.getByRole('button', { name: 'Next frame' }));
    expect(video().currentTime).toBeCloseTo(20 + 1001 / 30_000, 6);

    await user.click(screen.getByRole('button', { name: 'Previous frame' }));
    expect(video().currentTime).toBeCloseTo(20, 6);
  });

  it('refuses to step when the source declares no usable frame rate', async () => {
    const user = userEvent.setup();
    renderPlayer({ frameRate: { numerator: 0, denominator: 0 } });
    video().currentTime = 20;

    const next = screen.getByRole('button', { name: 'Next frame' });
    expect(next).toBeDisabled();
    await user.click(next);
    expect(video().currentTime).toBe(20);
  });

  it('jumps to the subject start, the representative frame and the subject end', async () => {
    const user = userEvent.setup();
    renderPlayer();

    await user.click(screen.getByRole('button', { name: /Start/ }));
    expect(video().currentTime).toBeCloseTo(10, 3);
    await user.click(screen.getByRole('button', { name: /Evidence/ }));
    expect(video().currentTime).toBeCloseTo(12, 3);
    await user.click(screen.getByRole('button', { name: /End/ }));
    expect(video().currentTime).toBeCloseTo(18, 3);
  });

  it('offers no evidence jump when no representative frame exists', () => {
    renderPlayer({ representative: undefined });
    expect(screen.queryByRole('button', { name: /Evidence/ })).not.toBeInTheDocument();
  });

  it('applies a bounded set of playback speeds to the media element', async () => {
    const user = userEvent.setup();
    renderPlayer();
    const speed = screen.getByLabelText('Speed');
    expect(within(speed).getAllByRole('option').map((option) => option.textContent)).toEqual(['0.25×', '0.5×', '1×', '2×']);

    await user.selectOptions(speed, '0.5');
    expect(video().playbackRate).toBe(0.5);
  });

  it('clamps a seek inside the media', async () => {
    const user = userEvent.setup();
    renderPlayer({ subject: { label: 'Person Track 7', startOffsetMs: -5_000, endOffsetMs: 9_000_000 } });

    await user.click(screen.getByRole('button', { name: /Start/ }));
    expect(video().currentTime).toBe(0);
    await user.click(screen.getByRole('button', { name: /End/ }));
    expect(video().currentTime).toBeCloseTo(599.999, 3);
  });

  it('shows the current position and the duration in player precision', () => {
    renderPlayer();
    fireEvent(video(), new Event('loadedmetadata'));
    expect(document.querySelector('.evidence-transport__time')).toHaveTextContent('00:10.0 / 10:00.0');
  });

  it('states that the source failed rather than showing an empty frame', () => {
    renderPlayer();
    fireEvent.error(video());
    expect(screen.getByText(/Source video could not be loaded/)).toBeInTheDocument();
  });
});

describe('Evidence Player keyboard grammar', () => {
  function pressOnStage(key: string, options: Record<string, unknown> = {}) {
    // The stage is inside the player but is not itself a control, so it is where
    // a shortcut is expected to act.
    fireEvent.keyDown(screen.getByTestId('evidence-overlay'), { key, ...options });
  }

  it('binds Space, the arrows, J/L, Home/End and E', () => {
    const media = stubMedia();
    renderPlayer();
    video().currentTime = 20;

    pressOnStage(' ');
    expect(media.play).toHaveBeenCalled();

    pressOnStage('ArrowRight');
    expect(video().currentTime).toBeCloseTo(20.04, 4);
    pressOnStage('ArrowLeft');
    expect(video().currentTime).toBeCloseTo(20, 4);

    pressOnStage('l');
    expect(video().currentTime).toBeCloseTo(21, 4);
    pressOnStage('j');
    expect(video().currentTime).toBeCloseTo(20, 4);

    pressOnStage('Home');
    expect(video().currentTime).toBeCloseTo(10, 3);
    pressOnStage('End');
    expect(video().currentTime).toBeCloseTo(18, 3);
    pressOnStage('e');
    expect(video().currentTime).toBeCloseTo(12, 3);
  });

  it('keeps one meaning per key when the press comes from the timeline', () => {
    // The contract is the player's, not the timeline's. Before this was fixed
    // the timeline answered these keys itself: the arrows seeked a second and
    // Home and End went to media start and end, so the same key meant two
    // things on one surface depending on where focus was.
    const media = stubMedia();
    renderPlayer({ frameRate: { numerator: 30_000, denominator: 1001 } });
    const timeline = screen.getByRole('list', { name: /timeline evidence/ });
    const press = (key: string) => fireEvent.keyDown(timeline, { key });

    video().currentTime = 20;
    press('ArrowRight');
    // One source frame, at the rational rate — not one second.
    expect(video().currentTime).toBeCloseTo(20 + 1001 / 30_000, 6);
    press('ArrowLeft');
    expect(video().currentTime).toBeCloseTo(20, 6);

    // The subject runs 10s to 18s inside a 600s video, so subject start and end
    // are nowhere near media start and end.
    press('Home');
    expect(video().currentTime).toBeCloseTo(10, 3);
    press('End');
    expect(video().currentTime).toBeCloseTo(18, 3);

    // J and L remain the one-second path.
    press('l');
    expect(video().currentTime).toBeCloseTo(19, 3);
    press('j');
    expect(video().currentTime).toBeCloseTo(18, 3);

    press(' ');
    expect(media.play).toHaveBeenCalled();

    press('e');
    expect(video().currentTime).toBeCloseTo(12, 3);
  });

  it('is reachable by keyboard: the frame takes focus and the shortcuts act there', async () => {
    const media = stubMedia();
    const user = userEvent.setup();
    renderPlayer();

    // Shortcuts are scoped to the player, so there has to be something inside
    // it to focus. The frame is it, and it is one Tab away.
    await user.tab();
    const frame = screen.getByRole('group', { name: /evidence frame/ });
    expect(frame).toHaveFocus();

    await user.keyboard(' ');
    expect(media.play).toHaveBeenCalled();
  });

  it('does nothing on E when no representative frame exists', () => {
    renderPlayer({ representative: undefined });
    video().currentTime = 20;
    pressOnStage('e');
    expect(video().currentTime).toBe(20);
  });

  it('ignores a modified key press, so browser shortcuts still work', () => {
    const media = stubMedia();
    renderPlayer();
    pressOnStage(' ', { ctrlKey: true });
    pressOnStage(' ', { metaKey: true });
    expect(media.play).not.toHaveBeenCalled();
  });

  it('leaves Space and Enter to the control that has focus', async () => {
    const media = stubMedia();
    const user = userEvent.setup();
    renderPlayer();

    // Space on the Start button must jump to the start, not toggle playback:
    // taking a key from the control the operator is actually using is the
    // classic global-shortcut regression.
    screen.getByRole('button', { name: /Start/ }).focus();
    await user.keyboard(' ');
    expect(media.play).not.toHaveBeenCalled();
    expect(video().currentTime).toBeCloseTo(10, 3);
  });

  it('leaves typing alone inside a text field placed in the player', async () => {
    const media = stubMedia();
    const user = userEvent.setup();
    renderPlayer({
      notices: <label>Note<input /></label>,
    });

    await user.type(screen.getByLabelText('Note'), 'jell ');
    expect(media.play).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Note')).toHaveValue('jell ');
  });
});

describe('Evidence Player layers', () => {
  const layers: EvidenceLayer[] = [
    {
      kind: 'spatial',
      id: 'box',
      label: 'Bounding box',
      available: true,
      render: () => <rect data-testid="box-layer" />,
      describe: (offsetMs) => [{
        id: 'the-box',
        label: 'Person bounding box',
        detail: 'Normalised source frame: x 0.500, y 0.250.',
        appliesNow: offsetMs < 11_000,
        inapplicableReason: 'the playhead is away from the frame it describes',
      }],
    },
    {
      kind: 'spatial',
      id: 'path',
      label: 'Trajectory',
      available: false,
      unavailableReason: 'No trajectory was persisted.',
      render: () => null,
      describe: () => [],
    },
  ];

  /** The element bound to a layer control by aria-describedby. */
  function descriptionOf(label: string): HTMLElement[] {
    const control = screen.getByRole('button', { name: label });
    const ids = (control.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);
    return ids.map((id) => {
      const element = document.getElementById(id);
      expect(element, `aria-describedby points at a missing element: ${id}`).not.toBeNull();
      return element as HTMLElement;
    });
  }

  it('draws available layers, and states why an unavailable one is not offered', () => {
    renderPlayer({ layers });
    expect(screen.getByTestId('box-layer')).toBeInTheDocument();
    const unavailable = screen.getByRole('button', { name: 'Trajectory' });
    expect(unavailable).toBeDisabled();
    expect(screen.getByText('No trajectory was persisted.')).toBeInTheDocument();
  });

  it('toggles a layer, marks the control pressed and remembers the choice', async () => {
    const user = userEvent.setup();
    const view = renderPlayer({ layers });
    const toggle = screen.getByRole('button', { name: 'Bounding box' });
    expect(toggle).toHaveAttribute('aria-pressed', 'true');

    await user.click(toggle);
    expect(screen.queryByTestId('box-layer')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Bounding box' })).toHaveAttribute('aria-pressed', 'false');

    view.unmount();
    renderPlayer({ layers });
    expect(screen.queryByTestId('box-layer')).not.toBeInTheDocument();
  });

  it('renders correctly when layer storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    renderPlayer({ layers });
    expect(screen.getByTestId('box-layer')).toBeInTheDocument();
  });

  it('carries spatial semantics on the operator\'s own control, not on a parallel surface', () => {
    renderPlayer({ layers });

    // Section 23: the twin is the same control the pointer uses. There is no
    // standalone spatial-evidence tree anywhere on the surface — that is what a
    // parallel accessibility-only surface is, and it is exactly what the
    // previous implementation rendered beside the stage.
    expect(screen.queryByRole('group', { name: /spatial evidence/i })).not.toBeInTheDocument();
    // The spatial semantics exist in exactly one place, and that place is the
    // layer's own row. Anything naming this object anywhere else is a second
    // representation of it. (Visually hidden text elsewhere on the player is
    // the accessible *name* of something visible — a timeline mark, an
    // icon-only button — which is the opposite arrangement.)
    const naming = Array.from(document.querySelectorAll('*'))
      .filter((node) => node.textContent?.includes('Person bounding box'))
      .filter((node) => !node.querySelector('*'));
    expect(naming).toHaveLength(1);
    expect(naming[0].closest('.evidence-layers__item')).not.toBeNull();

    // One layer object, one visible row, and the semantics hang off that row's
    // own control rather than off a second representation of it.
    const [description] = descriptionOf('Bounding box');
    expect(description).toHaveTextContent('Normalised source frame: x 0.500, y 0.250.');
    expect(description.closest('.evidence-layers__item'))
      .toBe(screen.getByRole('button', { name: 'Bounding box' }).closest('.evidence-layers__item'));

    // The raw geometry stays hidden: narrating SVG path data helps nobody.
    expect(screen.getByTestId('evidence-overlay')).toHaveAttribute('aria-hidden', 'true');
    // And none of it is a focus stop; the semantics cost no extra tabbing.
    expect(description.tabIndex).toBeLessThan(0);
    expect(document.querySelectorAll('.evidence-layers__item [tabindex]')).toHaveLength(0);
  });

  it('gives each described object a list item rather than one flattened string', () => {
    // Section 23 asks for a *list* naming each object, its state and its
    // coordinates. Concatenating the objects into one hidden sentence loses
    // where one ends and the next begins, which matters as soon as a layer
    // describes more than one thing — a trajectory already does, and Slice 5
    // will add zones, lines and crossings through the same seam.
    renderPlayer({ layers: [{ ...(layers[0] as SpatialEvidenceLayer),
      describe: () => [
        { id: 'one', label: 'First object', detail: 'at x 0.100.', appliesNow: true },
        { id: 'two', label: 'Second object', detail: 'at x 0.900.', appliesNow: true },
      ],
    }, layers[1]] });

    const [description] = descriptionOf('Bounding box');
    const list = within(description).getByRole('list');
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('First object: at x 0.100. Drawn at the current position.');
    expect(items[1]).toHaveTextContent('Second object: at x 0.900. Drawn at the current position.');

    // Still inside the layer's own row, and still the only representation.
    expect(list.closest('.evidence-layers__item'))
      .toBe(screen.getByRole('button', { name: 'Bounding box' }).closest('.evidence-layers__item'));
    expect(screen.queryByRole('group', { name: /spatial evidence/i })).not.toBeInTheDocument();
    expect(within(list).queryAllByRole('button')).toHaveLength(0);
    expect(list.querySelectorAll('[tabindex]')).toHaveLength(0);
  });

  it('never states a layer preference and a draw state that contradict each other', async () => {
    const user = userEvent.setup();
    renderPlayer({ layers });
    const text = () => descriptionOf('Bounding box').map((node) => node.textContent).join(' ');
    const seek = (seconds: number) => {
      const element = video();
      element.currentTime = seconds;
      fireEvent(element, new Event('timeupdate'));
    };

    // Case B — enabled and the evidence applies here.
    seek(10);
    expect(text()).toContain('Layer enabled.');
    expect(text()).toContain('Drawn at the current position.');

    // Case A — still enabled, but the playhead has left the frame the box
    // describes. "Layer enabled" is a fact about the toggle and stays true;
    // the drawing statement is a different fact and changes on its own.
    seek(40);
    expect(text()).toContain('Layer enabled.');
    expect(text()).toContain('Not drawn here: the playhead is away from the frame it describes.');
    expect(text()).not.toContain('Drawn at the current position.');

    // Case C — switched off while the playhead sits on the representative
    // frame. The old wording said "Hidden by the layer control." and "Drawn at
    // the current position." in the same breath, which cannot both be true.
    await user.click(screen.getByRole('button', { name: 'Bounding box' }));
    seek(10);
    expect(text()).toContain('Layer hidden by operator.');
    expect(text()).not.toContain('Drawn at the current position.');
    expect(text()).toContain('Not drawn: the layer is switched off.');

    // Off and inapplicable at once names both reasons, and still claims nothing
    // is on screen.
    seek(40);
    expect(text()).toContain('Layer hidden by operator.');
    expect(text()).toContain('Not drawn: the layer is switched off, and the playhead is away from the frame it describes.');
  });

  it('leaves an unavailable layer with its reason and nothing invented to describe', () => {
    renderPlayer({ layers });
    const bound = descriptionOf('Trajectory');
    expect(bound).toHaveLength(1);
    expect(bound[0]).toHaveTextContent('No trajectory was persisted.');
    // Not "Layer unavailable." repeated beside a reason that already says so.
    expect(bound[0].textContent).not.toContain('Layer');
  });
});

describe('the spatial layer contract', () => {
  it('requires a spatial layer to supply its accessible semantics', () => {
    // A type-level assertion, checked by `tsc -b` rather than at runtime: if
    // `describe` were optional on a spatial layer — as it was when every layer
    // shared one shape — `undefined` would be assignable to it, the conditional
    // would resolve to `never`, and this declaration would not compile. A future
    // layer therefore cannot draw geometry without an accessible equivalent.
    type Describe = SpatialEvidenceLayer['describe'];
    const enforced: undefined extends Describe ? never : true = true;
    expect(enforced).toBe(true);

    // The discriminant is what makes that enforceable: a layer with nothing
    // spatial to say declares so rather than silently omitting the semantics.
    const plain: NonSpatialEvidenceLayer = {
      kind: 'non-spatial', id: 'matte', label: 'Matte', available: true, render: () => null,
    };
    expect(plain.describe).toBeUndefined();
  });

  it('separates the preference state from the evidence state', () => {
    const applies = { id: 'a', label: 'A', detail: 'at x 0.5.', appliesNow: true } as const;
    const away = {
      id: 'b', label: 'B', detail: 'at x 0.5.', appliesNow: false,
      inapplicableReason: 'the playhead is away from the frame it describes',
    } as const;

    expect(layerPreferenceSentence('enabled')).toBe('Layer enabled.');
    expect(layerPreferenceSentence('hidden')).toBe('Layer hidden by operator.');

    // Enabled is never by itself a claim that something is on the frame.
    expect(evidenceDrawSentence('enabled', applies)).toBe('Drawn at the current position.');
    expect(evidenceDrawSentence('enabled', away))
      .toBe('Not drawn here: the playhead is away from the frame it describes.');
    // And switched off is never accompanied by a claim that it is drawn.
    for (const item of [applies, away]) {
      expect(evidenceDrawSentence('hidden', item)).toContain('the layer is switched off');
      expect(evidenceDrawSentence('hidden', item)).not.toContain('Drawn at the current position.');
    }
  });
});

describe('frameDurationSeconds', () => {
  it('returns the exact rational frame duration', () => {
    expect(frameDurationSeconds({ numerator: 25, denominator: 1 })).toBeCloseTo(0.04, 10);
    expect(frameDurationSeconds({ numerator: 30_000, denominator: 1001 })).toBeCloseTo(1001 / 30_000, 12);
  });

  it('refuses a rate it cannot use rather than assuming one', () => {
    expect(frameDurationSeconds(undefined)).toBeNull();
    expect(frameDurationSeconds({ numerator: 0, denominator: 1 })).toBeNull();
    expect(frameDurationSeconds({ numerator: 25, denominator: 0 })).toBeNull();
    expect(frameDurationSeconds({ numerator: Number.NaN, denominator: 1 })).toBeNull();
  });
});
