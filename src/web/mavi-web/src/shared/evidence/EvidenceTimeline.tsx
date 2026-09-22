import { useCallback, useEffect, useMemo, useRef } from 'react';
import { formatOffset } from '../format/format';
import {
  MAX_ZONE_SUBROWS,
  STATIONARY_LANE,
  SUBJECT_LANE,
  ZONE_LANE,
  layOutMarkers,
  offsetFromPointer,
  packIntervals,
  percentOf,
  timelineLayout,
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
 * analytical lane families, the markers and the playhead. Two scrub bars on one
 * surface is a defect, so this is both the evidence map and the pointer
 * scrubber.
 *
 * **It has no keyboard vocabulary of its own.** The Evidence Player's grammar
 * is one contract — arrows step a frame, J and L move a second, Home and End go
 * to the subject — and it holds wherever focus is inside the player, including
 * here and including while a marker control has focus. A timeline that redefined
 * those keys for itself would give the same key two meanings on one surface
 * depending on where focus happened to be.
 *
 * **Markers are real controls that seek exactly.** A crossing happened at a
 * persisted millisecond; asking the operator to drag a scrub bar to it would
 * replace an exact fact with a pointer approximation. Each marker is therefore a
 * button that seeks to its own offset, and the scrub underneath it is
 * suppressed so a press on the marker cannot first drag the playhead somewhere
 * near it.
 *
 * **Each piece of evidence is one element that is both the mark and the
 * accessible item.** The marks are list items carrying their own names; there is
 * no `aria-hidden` bar shadowed by a hidden description list, because a parallel
 * accessibility-only surface is exactly what the specification forbids.
 *
 * **Analytical lanes are fixed families, not one row per object** (specification
 * decision 7). Zone occupancy and stationary are different facts that can
 * overlap, so each family has its own fixed vertical position; the zone family
 * packs concurrent visits into at most three sub-rows and sends the rest to one
 * overflow rail. The height is therefore bounded by concurrency, never by how
 * many zones, visits or crossings the evidence contains.
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

  const subject = useMemo(
    () => intervals.filter((interval) => interval.lane === SUBJECT_LANE),
    [intervals],
  );
  const zones = useMemo(
    () => packIntervals(intervals.filter((interval) => interval.lane === ZONE_LANE), MAX_ZONE_SUBROWS),
    [intervals],
  );
  const stationary = useMemo(
    () => intervals.filter((interval) => interval.lane === STATIONARY_LANE),
    [intervals],
  );
  // Every other lane is accepted and named, and still not drawn: a lane whose
  // visual grammar nothing has chosen must not be given an invented shape, and
  // must not be dropped from the evidence either.
  const undrawn = useMemo(
    () => intervals.filter((interval) => (
      interval.lane !== SUBJECT_LANE && interval.lane !== ZONE_LANE && interval.lane !== STATIONARY_LANE
    )),
    [intervals],
  );

  const placedMarkers = useMemo(() => layOutMarkers(markers, durationMs), [markers, durationMs]);

  const zoneRowsUsed = zones.reduce(
    (highest, packed) => (packed.row === null ? highest : Math.max(highest, packed.row + 1)),
    0,
  );
  const overflowed = zones.filter((packed) => packed.row === null);
  const layout = timelineLayout({
    markerRows: placedMarkers.reduce((highest, placed) => Math.max(highest, placed.row + 1), 0),
    zoneRows: zoneRowsUsed,
    hasZoneOverflow: overflowed.length > 0,
    hasStationary: stationary.length > 0,
  });

  const band = (interval: EvidenceTimelineInterval) => ({
    left: percentOf(interval.startOffsetMs, durationMs),
    width: `calc(${percentOf(interval.endOffsetMs, durationMs)} - ${percentOf(interval.startOffsetMs, durationMs)})`,
  });
  const span = (interval: EvidenceTimelineInterval) => (
    `${formatOffset(interval.startOffsetMs, 'tenths')} to ${formatOffset(interval.endOffsetMs, 'tenths')}`
  );

  return (
    <div className="evidence-timeline">
      <ul
        ref={trackRef}
        className="evidence-timeline__track"
        style={{ height: `${layout.height}px` }}
        aria-label={`${subjectLabel} timeline evidence`}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          draggingRef.current = true;
          seekFromClientX(event.clientX);
        }}
      >
        {/* The scrub rail the bar is drawn on, positioned under the marker rail. */}
        <li
          className="evidence-timeline__rail"
          style={{ top: `${layout.subject}px` }}
          aria-hidden="true"
        />

        {subject.map((interval) => (
          <li
            key={interval.id}
            className="evidence-timeline__item evidence-timeline__interval"
            data-lane={SUBJECT_LANE}
            data-drawn="true"
            style={{ ...band(interval), top: `${layout.subject}px` }}
          >
            {/*
              The name lives inside the mark, so one element is both what the
              pointer sees and what a screen reader reads. Visually hidden
              because the bar is a few pixels tall, not because the text is a
              second copy of the evidence.
            */}
            <span className="visually-hidden">{interval.label}: {span(interval)}</span>
          </li>
        ))}

        {zones.map((packed) => {
          const overflow = packed.row === null;
          return (
            <li
              key={packed.interval.id}
              className={overflow
                ? 'evidence-timeline__item evidence-timeline__overflow'
                : 'evidence-timeline__item evidence-timeline__interval'}
              data-lane={ZONE_LANE}
              data-drawn={overflow ? 'overflow' : 'true'}
              data-row={overflow ? 'overflow' : String(packed.row)}
              data-concurrent={String(packed.concurrent)}
              style={overflow
                // An overflowed visit is a tick at its start rather than a band:
                // a band would paint over the visit already occupying the rail,
                // which is the occlusion the cap exists to prevent. It keeps its
                // own position, its own name and its own identity, so focusing
                // or highlighting this exact persisted interval still works.
                ? { left: percentOf(packed.interval.startOffsetMs, durationMs), top: `${layout.zoneOverflow ?? 0}px` }
                : { ...band(packed.interval), top: `${layout.zoneRows[packed.row ?? 0]}px` }}
            >
              <span className="visually-hidden">
                {packed.interval.label}: {span(packed.interval)}
                {overflow ? ` — one of ${packed.concurrent} overlapping visits, shown in the overflow rail` : ''}
              </span>
            </li>
          );
        })}

        {overflowed.length > 0 ? (
          <li
            className="evidence-timeline__overflow-count"
            style={{ top: `${layout.zoneOverflow ?? 0}px` }}
            data-overflowed={String(overflowed.length)}
          >
            <span className="visually-hidden">
              {overflowed.length} zone {overflowed.length === 1 ? 'visit is' : 'visits are'} in the
              overflow rail because more visits overlap than the timeline draws side by side.
              {' '}Each is named individually in this list.
            </span>
            <span aria-hidden="true" className="evidence-timeline__overflow-badge">+{overflowed.length}</span>
          </li>
        ) : null}

        {stationary.map((interval) => (
          <li
            key={interval.id}
            className="evidence-timeline__item evidence-timeline__interval"
            data-lane={STATIONARY_LANE}
            data-drawn="true"
            style={{ ...band(interval), top: `${layout.stationary ?? 0}px` }}
          >
            <span className="visually-hidden">{interval.label}: {span(interval)}</span>
          </li>
        ))}

        {undrawn.map((interval) => (
          <li
            key={interval.id}
            className="evidence-timeline__item evidence-timeline__interval"
            data-lane={interval.lane}
            data-drawn="false"
          >
            <span className="visually-hidden">{interval.label}: {span(interval)}</span>
          </li>
        ))}

        {placedMarkers.map((placed) => {
          const names = placed.cluster.map((marker) => marker.label).join('; ');
          const at = formatOffset(placed.marker.offsetMs, 'tenths');
          return (
            <li
              key={placed.marker.id}
              className="evidence-timeline__item evidence-timeline__marker"
              data-kind={placed.marker.kind}
              data-cluster={String(placed.cluster.length)}
              style={{ left: percentOf(placed.marker.offsetMs, durationMs), top: `${placed.row * 24}px` }}
            >
              <button
                type="button"
                className="evidence-timeline__marker-button"
                // The exact persisted offset, never a position derived from
                // where the pointer happened to land.
                onClick={() => onSeek(placed.marker.offsetMs)}
                // The track below scrubs on pointer-down. Without this the press
                // that activates the marker would first seek to an approximate
                // offset and then to the exact one, so the playhead would visibly
                // land in the wrong place first and a drag would take over.
                onPointerDown={(event) => event.stopPropagation()}
                title={`${names} at ${at}`}
              >
                <span className="visually-hidden">Seek to {names}: {at}</span>
                <span className="evidence-timeline__marker-tick" aria-hidden="true" />
              </button>
            </li>
          );
        })}

        {/*
          The playhead is not evidence. It indicates where the transport is,
          which the time readout beside it already states, so it carries no
          accessible name of its own.
        */}
        <li
          className="evidence-timeline__playhead"
          style={{ left: percentOf(currentOffsetMs, durationMs), top: `${layout.markerRail}px` }}
          aria-hidden="true"
        />
      </ul>
    </div>
  );
}
