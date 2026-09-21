import { useCallback, useEffect, useRef } from 'react';
import { formatOffset } from '../format/format';
import {
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
 * A single bar spanning the whole media, carrying the subject interval, the
 * markers and the playhead. Two scrub bars on one surface is a defect, so this
 * is both the evidence map and the pointer scrubber.
 *
 * **It has no keyboard vocabulary of its own.** The Evidence Player's grammar
 * is one contract — arrows step a frame, J and L move a second, Home and End go
 * to the subject — and it holds wherever focus is inside the player, including
 * here. A timeline that redefined those keys for itself would give the same key
 * two meanings on one surface depending on where focus happened to be, which is
 * a contradiction in the product rather than a detail of this component. Coarse
 * seeking by pointer plus that one grammar is the whole interaction.
 *
 * **Each piece of evidence is one element that is both the mark and the
 * accessible item.** The marks are list items carrying their own names; there is
 * no `aria-hidden` bar shadowed by a hidden description list, because a parallel
 * accessibility-only surface is exactly what the specification forbids. Slice 5
 * adds crossings, zone visits, dwell and stationary intervals as more items of
 * the same shape.
 */
export default function EvidenceTimeline({
  durationMs,
  currentOffsetMs,
  intervals,
  markers,
  subjectLabel,
  onSeek,
}: Props) {
  const trackRef = useRef<HTMLUListElement | null>(null);
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

  return (
    <div className="evidence-timeline">
      <ul
        ref={trackRef}
        className="evidence-timeline__track"
        aria-label={`${subjectLabel} timeline evidence`}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          draggingRef.current = true;
          seekFromClientX(event.clientX);
        }}
      >
        {intervals.map((interval) => (
          <li
            key={interval.id}
            className="evidence-timeline__item evidence-timeline__interval"
            data-lane={interval.lane}
            // Only the subject lane is positioned as a band. Every other lane is
            // still a named item here, because the presentation of analytical
            // lanes is decided in Slice 5 against real facts and an item with no
            // agreed shape must not be invented — but it must not be dropped
            // from the evidence either.
            data-drawn={interval.lane === SUBJECT_LANE}
            style={interval.lane === SUBJECT_LANE
              ? {
                left: percentOf(interval.startOffsetMs, durationMs),
                width: `calc(${percentOf(interval.endOffsetMs, durationMs)} - ${percentOf(interval.startOffsetMs, durationMs)})`,
              }
              : undefined}
          >
            {/*
              The name lives inside the mark, so one element is both what the
              pointer sees and what a screen reader reads. Visually hidden
              because the bar is a few pixels tall, not because the text is a
              second copy of the evidence.
            */}
            <span className="visually-hidden">
              {interval.label}: {formatOffset(interval.startOffsetMs, 'tenths')} to {formatOffset(interval.endOffsetMs, 'tenths')}
            </span>
          </li>
        ))}
        {markers.map((marker) => (
          <li
            key={marker.id}
            className="evidence-timeline__item evidence-timeline__marker"
            data-kind={marker.kind}
            style={{ left: percentOf(marker.offsetMs, durationMs) }}
          >
            <span className="visually-hidden">{marker.label}: {formatOffset(marker.offsetMs, 'tenths')}</span>
          </li>
        ))}
        {/*
          The playhead is not evidence. It indicates where the transport is,
          which the time readout beside it already states, so it carries no
          accessible name of its own.
        */}
        <li
          className="evidence-timeline__playhead"
          style={{ left: percentOf(currentOffsetMs, durationMs) }}
          aria-hidden="true"
        />
      </ul>
    </div>
  );
}
