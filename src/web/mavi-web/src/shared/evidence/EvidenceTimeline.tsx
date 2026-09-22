import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { formatOffset } from '../format/format';
import {
  MARKER_TARGET_PX,
  MAX_ZONE_SUBROWS,
  overflowClusters,
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
  /**
   * The measured width of the track, which decides how close two marker
   * controls may sit before their targets overlap. It has to be measured
   * rather than assumed: this component is reused in the Investigation
   * inspector, whose track is far narrower than Review's, so the same offsets
   * are that much closer together in pixels there.
   */
  const [trackWidth, setTrackWidth] = useState(0);
  /** Which overflowed zone visit the operator has singled out, if any. */
  const [shownOverflow, setShownOverflow] = useState<string | null>(null);

  useEffect(() => {
    const element = trackRef.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      setTrackWidth(element.getBoundingClientRect().width);
    });
    observer.observe(element);
    setTrackWidth(element.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);

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

  const markerLayout = useMemo(
    () => layOutMarkers(markers, durationMs, trackWidth),
    [markers, durationMs, trackWidth],
  );
  const placedMarkers = markerLayout.placed;

  const zoneRowsUsed = zones.reduce(
    (highest, packed) => (packed.row === null ? highest : Math.max(highest, packed.row + 1)),
    0,
  );
  const overflowed = zones.filter((packed) => packed.row === null);
  const clusters = useMemo(() => overflowClusters(zones), [zones]);
  // Only one overflowed visit is ever drawn as its own band, so singling one
  // out can never add a row or paint over another.
  const shown = overflowed.find((packed) => packed.interval.id === shownOverflow)?.interval;
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
          if (packed.row === null) {
            // An overflowed visit keeps its place in the semantic list — every
            // visit is named individually whatever the drawing does — but it
            // takes no position of its own on the rail. Ticks at true starts
            // covered each other whenever two overflowed visits began
            // together, hiding the very evidence the rail exists to account
            // for. It is reachable as a control in the disclosure below.
            return (
              <li
                key={packed.interval.id}
                className="evidence-timeline__item evidence-timeline__unplaced"
                data-lane={ZONE_LANE}
                data-drawn="overflow"
                data-row="overflow"
                data-concurrent={String(packed.concurrent)}
              >
                <span className="visually-hidden">
                  {packed.interval.label}: {span(packed.interval)} — one of {packed.concurrent} overlapping
                  visits, listed under the overflow control below the timeline.
                </span>
              </li>
            );
          }
          return (
            <li
              key={packed.interval.id}
              className="evidence-timeline__item evidence-timeline__interval"
              data-lane={ZONE_LANE}
              data-drawn="true"
              data-row={String(packed.row)}
              data-concurrent={String(packed.concurrent)}
              style={{ ...band(packed.interval), top: `${layout.zoneRows[packed.row]}px` }}
            >
              <span className="visually-hidden">{packed.interval.label}: {span(packed.interval)}</span>
            </li>
          );
        })}

        {/*
          One band per disjoint run of overflowed visits, carrying that span's
          own concurrency. Runs cannot overlap each other by construction, so
          the rail stays one row and nothing is painted over; a single total for
          the whole timeline would say nothing about *where* the evidence is
          dense, which is the only thing the operator needs from an aggregate.
        */}
        {clusters.map((cluster) => (
          <li
            key={cluster.id}
            className="evidence-timeline__item evidence-timeline__overflow"
            data-concurrent={String(cluster.count)}
            style={{
              left: percentOf(cluster.startOffsetMs, durationMs),
              width: `calc(${percentOf(cluster.endOffsetMs, durationMs)} - ${percentOf(cluster.startOffsetMs, durationMs)})`,
              top: `${layout.zoneOverflow ?? 0}px`,
            }}
          >
            <span className="visually-hidden">
              {cluster.count} overlapping zone {cluster.count === 1 ? 'visit' : 'visits'} between{' '}
              {formatOffset(cluster.startOffsetMs, 'tenths')} and {formatOffset(cluster.endOffsetMs, 'tenths')},
              beyond what the timeline draws side by side.
            </span>
            <span aria-hidden="true" className="evidence-timeline__overflow-badge">+{cluster.count}</span>
          </li>
        ))}

        {/*
          The one overflowed visit the operator has singled out, drawn at its
          exact offsets so the interval can be seen rather than only read. Only
          ever one at a time, so recovering an exact interval can never add a
          row or cover another.
        */}
        {shown ? (
          <li
            className="evidence-timeline__item evidence-timeline__interval evidence-timeline__shown"
            data-lane={ZONE_LANE}
            data-drawn="true"
            data-shown="true"
            style={{ ...band(shown), top: `${layout.zoneOverflow ?? 0}px` }}
          >
            <span className="visually-hidden">Shown: {shown.label}: {span(shown)}</span>
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
              style={{ left: percentOf(placed.marker.offsetMs, durationMs), top: `${placed.row * MARKER_TARGET_PX}px` }}
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

      {/*
        Everything the rail could not give a place of its own.

        The timeline's height is fixed, so past a point evidence cannot each
        have a band or a 24px target on it — but "not drawn side by side" must
        not become "not reachable". This disclosure is the guarantee: every
        overflowed visit and every marker too dense to place is its own control
        here, seeking to its own exact offset. It costs one tab stop, and only
        when there is something in it.
      */}
      {overflowed.length > 0 || markerLayout.overflow.length > 0 ? (
        <details className="evidence-timeline__dense">
          <summary>
            {overflowed.length > 0 ? `${overflowed.length} overlapping zone ${overflowed.length === 1 ? 'visit' : 'visits'}` : ''}
            {overflowed.length > 0 && markerLayout.overflow.length > 0 ? ' and ' : ''}
            {markerLayout.overflow.length > 0 ? `${markerLayout.overflow.length} closely spaced ${markerLayout.overflow.length === 1 ? 'marker' : 'markers'}` : ''}
            {' not drawn side by side'}
          </summary>
          <ul className="evidence-timeline__dense-list">
            {overflowed.map((packed) => (
              <li key={packed.interval.id}>
                <button
                  type="button"
                  // Pressed rather than selected: this singles the interval out
                  // for drawing, and pressing it again puts the rail back.
                  aria-pressed={shownOverflow === packed.interval.id}
                  onClick={() => {
                    const next = shownOverflow === packed.interval.id ? null : packed.interval.id;
                    setShownOverflow(next);
                    if (next) onSeek(packed.interval.startOffsetMs);
                  }}
                >
                  {packed.interval.label}: {span(packed.interval)}
                </button>
              </li>
            ))}
            {markerLayout.overflow.map((marker) => (
              <li key={marker.id}>
                <button type="button" onClick={() => onSeek(marker.offsetMs)}>
                  Seek to {marker.label}: {formatOffset(marker.offsetMs, 'tenths')}
                </button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
