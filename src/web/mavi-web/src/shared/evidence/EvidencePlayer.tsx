import { useEffect, useMemo, useState, type ReactNode } from 'react';
import Alert from '../components/Alert';
import Button from '../components/Button';
import Icon from '../components/Icon';
import { formatOffset } from '../format/format';
import EvidenceTimeline from './EvidenceTimeline';
import {
  isLayerVisible,
  readLayerPreferences,
  writeLayerPreferences,
  type EvidenceLayer,
} from './layers';
import {
  PLAYBACK_RATES,
  frameDurationSeconds,
  useEvidenceTransport,
  type PlaybackRate,
  type SourceFrameRate,
} from './useEvidenceTransport';
import type { EvidenceTimelineInterval, EvidenceTimelineMarker } from './timeline';

/**
 * The attribute that marks the player's subtree.
 *
 * Surfaces with their own window-level shortcuts use it to refuse any key
 * press that came from inside the player. Investigation binds `j` and `k` for
 * result navigation and the player's frozen grammar binds `J` and `L` for one
 * second either way — the same physical keys — so one of the two has to know
 * about the other, and it is cheaper for the page to ignore the player's
 * subtree than for the player to know which page it is on.
 */
export const EVIDENCE_PLAYER_ATTRIBUTE = 'data-evidence-player';

/**
 * Whether an event came from inside an Evidence Player.
 *
 * Widened to `Element` rather than `HTMLElement` on purpose: the overlay stage
 * is SVG, so an HTML-only check would let an event originating there through to
 * a page's window shortcuts.
 */
export function isInsideEvidencePlayer(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(`[${EVIDENCE_PLAYER_ATTRIBUTE}]`) !== null;
}

/**
 * Whether a key press should be treated as a player shortcut rather than left
 * to the control that has focus.
 *
 * `Space` and `Enter` already activate a button or a link, and the arrows
 * already move a slider, a select or a text caret. Taking those keys from the
 * control the operator is actually using is the classic global-shortcut
 * regression, so a shortcut only fires when the focused element has no native
 * meaning for that key.
 */
function isShortcutTarget(target: EventTarget | null, key: string): boolean {
  if (!(target instanceof HTMLElement)) return true;
  if (target.isContentEditable) return false;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return false;
  const control = target.closest('button, a[href], [role="slider"], input, select, textarea');
  if (!control) return true;
  // On a control, only keys that control has no use for remain shortcuts.
  const native = control.getAttribute('role') === 'slider'
    ? ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', ' ', 'Enter']
    : [' ', 'Enter'];
  return !native.includes(key);
}

export type EvidenceSubject = {
  /** What the review is about, for accessible names. */
  label: string;
  startOffsetMs: number;
  endOffsetMs: number;
};

type Props = {
  /** Media source. Changing it is a source replacement. */
  sourceUrl: string;
  declaredDurationMs: number;
  declaredWidth: number;
  declaredHeight: number;
  frameRate?: SourceFrameRate;
  /** The interval the evidence is about: Start and End jump here. */
  subject: EvidenceSubject;
  /**
   * The representative evidence frame, when one is persisted. `E` seeks to it
   * and it is used as the poster so the frame is never black before metadata.
   */
  representative?: { offsetMs: number; posterUrl?: string };
  /** Overlay layers, drawn into the content rectangle in supplied order. */
  layers: readonly EvidenceLayer[];
  intervals: readonly EvidenceTimelineInterval[];
  markers: readonly EvidenceTimelineMarker[];
  /**
   * Where the playhead opens. Defaults to the subject's start; Review opens a
   * second earlier so the operator sees the subject enter.
   */
  initialOffsetMs?: number;
  /** Identity of the subject; changing it reopens at `initialOffsetMs`. */
  seekKey: string;
  /** Which operator preference bucket the layer toggles persist under. */
  preferenceScope: string;
  /** Denser presentation for the Investigation inspector. Presentation only. */
  compact?: boolean;
  /** Extra evidence notices, such as a failed trajectory request. */
  notices?: ReactNode;
};

/**
 * The one Evidence Player.
 *
 * Generic: it plays a media source, draws whatever layers it is handed into the
 * true video content rectangle, and offers one timeline and one transport
 * strip. It knows nothing about Tracks, zones or events; Track evidence is
 * composed on top of it, and Scene Analytics will be composed the same way.
 *
 * Native browser controls are deliberately absent. They occupy the lower band
 * of the frame, which is exactly where evidence is drawn, and they behave
 * differently in every browser. The transport lives below the frame instead,
 * and nothing is ever overlaid on the evidence but the evidence itself.
 */
export default function EvidencePlayer({
  sourceUrl,
  declaredDurationMs,
  declaredWidth,
  declaredHeight,
  frameRate,
  subject,
  representative,
  layers,
  intervals,
  markers,
  initialOffsetMs,
  seekKey,
  preferenceScope,
  compact = false,
  notices,
}: Props) {
  const transport = useEvidenceTransport({
    sourceUrl,
    declaredDurationMs,
    declaredWidth,
    declaredHeight,
    frameRate,
    initialOffsetMs: initialOffsetMs ?? subject.startOffsetMs,
    seekKey,
  });

  const [preferences, setPreferences] = useState<Record<string, boolean>>(() => readLayerPreferences(preferenceScope));
  useEffect(() => {
    setPreferences(readLayerPreferences(preferenceScope));
  }, [preferenceScope]);

  const toggleLayer = (id: string, visible: boolean) => {
    setPreferences((current) => {
      const next = { ...current, [id]: visible };
      writeLayerPreferences(preferenceScope, next);
      return next;
    });
  };

  const visibleLayers = useMemo(
    () => layers.filter((layer) => isLayerVisible(layer, preferences)),
    [layers, preferences],
  );

  const { box, frame, currentOffsetMs, durationMs, playing, failed } = transport;
  const canStepFrames = frameDurationSeconds(frameRate) !== null;

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
    if (!isShortcutTarget(event.target, event.key)) return;
    switch (event.key) {
      case ' ':
        event.preventDefault();
        transport.toggle();
        break;
      case 'ArrowLeft':
        if (!canStepFrames) break;
        event.preventDefault();
        transport.stepFrames(-1);
        break;
      case 'ArrowRight':
        if (!canStepFrames) break;
        event.preventDefault();
        transport.stepFrames(1);
        break;
      case 'j':
      case 'J':
        event.preventDefault();
        transport.nudgeSeconds(-1);
        break;
      case 'l':
      case 'L':
        event.preventDefault();
        transport.nudgeSeconds(1);
        break;
      case 'Home':
        event.preventDefault();
        transport.seekTo(subject.startOffsetMs);
        break;
      case 'End':
        event.preventDefault();
        transport.seekTo(subject.endOffsetMs);
        break;
      case 'e':
      case 'E':
        // No representative frame means there is nowhere to go, so nothing happens.
        if (!representative) break;
        event.preventDefault();
        transport.seekTo(representative.offsetMs);
        break;
      default:
    }
  };

  return (
    <div
      className={compact ? 'evidence-player evidence-player--compact' : 'evidence-player'}
      onKeyDown={onKeyDown}
      {...{ [EVIDENCE_PLAYER_ATTRIBUTE]: '' }}
    >
      {/*
        The frame is focusable, which is what makes the keyboard grammar
        reachable. Shortcuts are scoped to this subtree rather than bound to the
        window, so without a focus target inside it none of them would ever
        fire; one Tab now lands here and the ring says so. The same in both
        hosts, because the semantics must not differ between them.
      */}
      <div
        className="evidence-player__frame"
        tabIndex={0}
        role="group"
        aria-label={`${subject.label} evidence frame. Space plays, arrows step one frame, J and L move one second, Home and End jump to the subject.`}
      >
        <video
          key={sourceUrl}
          ref={transport.videoRef}
          className="evidence-player__video"
          src={sourceUrl}
          poster={representative?.posterUrl}
          preload="metadata"
          playsInline
          aria-label={`${subject.label} source video evidence`}
          onError={transport.onError}
        >
          Your browser does not support HTML video playback.
        </video>

        {box.width > 0 && box.height > 0 ? (
          <svg
            className="evidence-player__stage"
            viewBox={`0 0 ${box.width} ${box.height}`}
            width={box.width}
            height={box.height}
            aria-hidden="true"
            data-testid="evidence-overlay"
          >
            {visibleLayers.map((layer) => (
              <g key={layer.id} data-layer={layer.id}>{layer.render(frame, currentOffsetMs)}</g>
            ))}
          </svg>
        ) : null}
      </div>

      {failed ? <Alert tone="error">Source video could not be loaded from the evidence API.</Alert> : null}
      {notices}

      <EvidenceTimeline
        durationMs={durationMs}
        currentOffsetMs={currentOffsetMs}
        intervals={intervals}
        markers={markers}
        subjectLabel={subject.label}
        onSeek={transport.seekTo}
      />

      <div className="evidence-transport">
        <Button
          size="sm"
          icon={playing ? 'pause' : 'play'}
          onClick={() => transport.toggle()}
          title="Play or pause (Space)"
        >
          {playing ? 'Pause' : 'Play'}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          icon="stepBack"
          iconOnly
          disabled={!canStepFrames}
          onClick={() => transport.stepFrames(-1)}
          title="Previous frame (Left arrow)"
        >
          Previous frame
        </Button>
        <Button
          size="sm"
          variant="ghost"
          icon="stepForward"
          iconOnly
          disabled={!canStepFrames}
          onClick={() => transport.stepFrames(1)}
          title="Next frame (Right arrow)"
        >
          Next frame
        </Button>
        <Button
          size="sm"
          variant="ghost"
          icon="skipStart"
          onClick={() => transport.seekTo(subject.startOffsetMs)}
          title="Jump to start (Home)"
        >
          Start
        </Button>
        {representative ? (
          <Button
            size="sm"
            variant="ghost"
            icon="target"
            onClick={() => transport.seekTo(representative.offsetMs)}
            title="Jump to the representative frame (E)"
          >
            Evidence
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="ghost"
          icon="skipEnd"
          onClick={() => transport.seekTo(subject.endOffsetMs)}
          title="Jump to end (End)"
        >
          End
        </Button>

        <span className="evidence-transport__time" aria-live="off">
          {formatOffset(currentOffsetMs, 'tenths')} / {formatOffset(durationMs, 'tenths')}
        </span>

        <label className="evidence-transport__rate">
          <span>Speed</span>
          <select
            value={transport.rate}
            onChange={(event) => transport.setRate(Number(event.target.value) as PlaybackRate)}
          >
            {PLAYBACK_RATES.map((value) => (
              <option key={value} value={value}>{value}×</option>
            ))}
          </select>
        </label>
      </div>

      <div className="evidence-layers" role="group" aria-label="Evidence layers">
        <Icon name="layers" size="sm" aria-hidden="true" />
        {layers.map((layer) => {
          const visible = isLayerVisible(layer, preferences);
          return (
            <span key={layer.id} className="evidence-layers__item">
              <Button
                size="sm"
                variant="ghost"
                aria-pressed={visible}
                disabled={!layer.available}
                onClick={() => toggleLayer(layer.id, !visible)}
              >
                {layer.label}
              </Button>
              {!layer.available && layer.unavailableReason ? (
                <span className="evidence-layers__reason">{layer.unavailableReason}</span>
              ) : null}
            </span>
          );
        })}
      </div>
    </div>
  );
}
