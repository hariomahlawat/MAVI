import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import EvidencePlayer from './EvidencePlayer';
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
  const layers = [
    { id: 'box', label: 'Bounding box', available: true, render: () => <rect data-testid="box-layer" /> },
    { id: 'path', label: 'Trajectory', available: false, unavailableReason: 'No trajectory was persisted.', render: () => null },
  ];

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
