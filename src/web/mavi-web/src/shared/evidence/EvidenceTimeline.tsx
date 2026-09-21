import { useCallback, useEffect, useRef } from 'react';
import { formatOffset } from '../format/format';
import {
  clampOffset,
  offsetFromPointer,
  percentOf,
  SUBJECT_LANE,
  type EvidenceTimelineInterval,
  type EvidenceTimelineMarker,
} from './timeline';

type Props = {
  durationMs: number;
  currentOffsetMs: number;
  intervals: readonly EvidenceTimelineInterval[];
  markers: readonly EvidenceTimelineMarker[];
  /** What the timeline is a timeline of, for its accessible name. */
  subjectLabel: string;
  onSeek: (offsetMs: number) => void;
};

/**
 * The one timeline.
 *
 * A single scrub bar spanning the whole media, carrying the subject interval,
 * the markers and the playhead. Two scrub bars on one surface is a defect, so
 * this is both the evidence map and the transport scrubber.
 *
 * It is a real control, not decoration: a slider that seeks on click, drag and
 * keyboard, with the media offset as its value. The transitional player marked
 * its timeline `aria-hidden`, which hid meaningful evidence from anyone not
 * using a pointer; here the bar is operable and every interval and marker also
 * appears in a list, which is the accessible twin the specification requires
 * for spatial and temporal content.
 */
export default function EvidenceTimeline({
  durationMs,
  currentOffsetMs,
  intervals,
  markers,
  subjectLabel,
  onSeek,
}: Props) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const draggingRef = useRef(false);

  const seekFromClientX = useCallback((clientX: number) => {
    const element = trackRef.current;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    onSeek(offsetFromPointer(clientX, { left: rect.left, width: rect.width }, durationMs));
  }, [durationMs, onSeek]);

  // Pointer capture would be simpler, but jsdom does not implement it and the
  // scrub has to be testable; window listeners do the same job and are removed
  // as soon as the drag ends or the component goes away.
  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      if (!draggingRef.current) return;
      event.preventDefault();
      seekFromClientX(event.clientX);
    };
    const onUp = () => { draggingRef.current = false; };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    return () => {
      draggingRef.current = false;
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
    };
  }, [seekFromClientX]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    // The slider's own keys, which are the ones a keyboard operator expects
    // from a slider and what makes seeking reachable without a pointer. The
    // player's grammar (Space, J/L, E) reaches the container by bubbling; these
    // are taken here and stopped, because on the focused slider they mean the
    // slider's own movement rather than the player's frame step and jumps.
    const step = event.shiftKey ? 10_000 : 1_000;
    const seek = (offsetMs: number) => {
      event.preventDefault();
      event.stopPropagation();
      onSeek(clampOffset(offsetMs, durationMs));
    };
    switch (event.key) {
      case 'ArrowRight':
      case 'ArrowUp':
        seek(currentOffsetMs + step);
        break;
      case 'ArrowLeft':
      case 'ArrowDown':
        seek(currentOffsetMs - step);
        break;
      case 'Home':
        seek(0);
        break;
      case 'End':
        seek(durationMs);
        break;
      default:
    }
  };

  const subject = intervals.filter((interval) => interval.lane === SUBJECT_LANE);

  return (
    <div className="evidence-timeline">
      <div
        ref={trackRef}
        className="evidence-timeline__track"
        role="slider"
        tabIndex={0}
        aria-label={`${subjectLabel} timeline`}
        aria-valuemin={0}
        aria-valuemax={Math.max(0, Math.round(durationMs))}
        /* Never above the maximum: before metadata the duration is not known
           yet, and a value outside its own range is not a valid slider. */
        aria-valuenow={Math.min(Math.max(0, Math.round(durationMs)), Math.round(clampOffset(currentOffsetMs, durationMs)))}
        aria-valuetext={`${formatOffset(currentOffsetMs, 'tenths')} of ${formatOffset(durationMs, 'tenths')}`}
        onKeyDown={onKeyDown}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          draggingRef.current = true;
          event.currentTarget.focus();
          seekFromClientX(event.clientX);
        }}
      >
        {subject.map((interval) => (
          <div
            key={interval.id}
            className="evidence-timeline__interval"
            style={{
              left: percentOf(interval.startOffsetMs, durationMs),
              width: `calc(${percentOf(interval.endOffsetMs, durationMs)} - ${percentOf(interval.startOffsetMs, durationMs)})`,
            }}
            aria-hidden="true"
          />
        ))}
        {markers.map((marker) => (
          <div
            key={marker.id}
            className="evidence-timeline__marker"
            data-kind={marker.kind}
            style={{ left: percentOf(marker.offsetMs, durationMs) }}
            aria-hidden="true"
          />
        ))}
        <div
          className="evidence-timeline__playhead"
          style={{ left: percentOf(currentOffsetMs, durationMs) }}
          aria-hidden="true"
        />
      </div>

      {/*
        The accessible twin. Every interval and every marker is named here with
        its offsets, including intervals in lanes this timeline does not yet
        draw, so evidence is never available to a pointer alone.
      */}
      <ul className="evidence-timeline__legend visually-hidden">
        {intervals.map((interval) => (
          <li key={interval.id}>
            {interval.label}: {formatOffset(interval.startOffsetMs, 'tenths')} to {formatOffset(interval.endOffsetMs, 'tenths')}
          </li>
        ))}
        {markers.map((marker) => (
          <li key={marker.id}>{marker.label}: {formatOffset(marker.offsetMs, 'tenths')}</li>
        ))}
      </ul>
    </div>
  );
}
