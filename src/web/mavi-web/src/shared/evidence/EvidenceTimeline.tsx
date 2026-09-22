import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { formatOffset } from '../format/format';
import {
  MARKER_TARGET_PX,
  MAX_ZONE_SUBROWS,
  overflowSegments,
  overflowedIntervals,
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

/**
 * One piece of evidence the rail could not place, of either kind.
 *
 * Kept as a discriminated union rather than two parallel sequences so the
 * navigator is one cursor over one ordering: "3 of 17" has to count everything
 * that is recoverable, not everything of one sort.
 */
type DenseMember =
  | { kind: 'visit'; interval: EvidenceTimelineInterval }
  | { kind: 'marker'; marker: EvidenceTimelineMarker };

/** A dense member's identity, namespaced so a visit and a marker cannot collide. */
function memberId(member: DenseMember): string {
  return member.kind === 'visit' ? `visit:${member.interval.id}` : `marker:${member.marker.id}`;
}

/** What the disclosure states before it is opened. */
function denseSummary(visits: number, markers: number): string {
  const parts: string[] = [];
  if (visits > 0) parts.push(`${visits} zone ${visits === 1 ? 'visit' : 'visits'}`);
  if (markers > 0) parts.push(`${markers} ${markers === 1 ? 'marker' : 'markers'}`);
  return `${parts.join(' and ')} not drawn side by side`;
}

type Props = {
  durationMs: number;
  currentOffsetMs: number;
  intervals: readonly EvidenceTimelineInterval[];
  markers: readonly EvidenceTimelineMarker[];
  /** What the timeline is a timeline of, for its accessible name. */
  subjectLabel: string;
  /**
   * Stable identity of the evidence subject.
   *
   * The timeline is generic and must stay so: it knows nothing about Tracks.
   * It does need to know *that the subject changed*, because it holds one piece
   * of transient state — which dense member is being inspected — and evidence
   * ids are unique only within one subject. A zone visit is
   * `zone-visit-{zoneId}-{visitIndex}`, so two Tracks through the same zone
   * produce the same id, and a cursor kept across the switch would show the
   * next Track a selection its operator never made.
   */
  subjectKey: string;
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
  subjectKey,
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
  /**
   * Where the dense-evidence navigator is: **which member**, and **whose**.
   *
   * The member rather than its position, because the sequence is not fixed —
   * a resize changes how many markers the rail can place, so an index would
   * quietly come to mean a different piece of evidence. An id cannot: the same
   * member stays selected, or, if it is no longer recoverable, nothing is.
   */
  const [cursor, setCursor] = useState<{ key: string; id: string } | null>(null);
  const [seenSubject, setSeenSubject] = useState(subjectKey);
  if (seenSubject !== subjectKey) {
    // Reset **during render**, the documented way to derive state from a prop
    // that changed. An effect would run after the render that already drew the
    // previous subject's selection, so there would be one frame in which the
    // new Track showed the old Track's highlight; React instead re-runs this
    // component before committing anything.
    //
    // Cleared rather than remembered per subject: coming back to a Track is
    // navigation, not the operator choosing a visit, and resurrecting a
    // selection they made two Tracks ago would be a highlight nobody asked
    // for.
    setSeenSubject(subjectKey);
    setCursor(null);
  }

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
  const segments = useMemo(() => overflowSegments(zones), [zones]);

  /**
   * Everything the rail could not give a place of its own, in time order: the
   * zone visits beyond the capped sub-rows, then the markers too close
   * together to carry separate targets.
   *
   * One flat sequence, because the navigator that recovers them is one control
   * however much there is — the count of members changes, the count of controls
   * does not.
   */
  const dense = useMemo<DenseMember[]>(() => ([
    ...overflowedIntervals(zones).map((interval) => ({ kind: 'visit' as const, interval })),
    ...markerLayout.overflow.map((marker) => ({ kind: 'marker' as const, marker })),
  ]), [zones, markerLayout]);

  // The key is still compared on read: the reset above has not committed yet in
  // the render that triggers it. A member that is no longer dense — because the
  // rail widened and can place it again — is simply no longer selected.
  const found = cursor?.key === subjectKey
    ? dense.findIndex((member) => memberId(member) === cursor.id)
    : -1;
  const at = found === -1 ? null : found;
  const current = at === null ? null : dense[at];
  // Only ever one member is drawn at its own offsets, so recovering an exact
  // interval can never add a row or paint over another.
  const shown = current?.kind === 'visit' ? current.interval : undefined;
  const layout = timelineLayout({
    markerRows: placedMarkers.reduce((highest, placed) => Math.max(highest, placed.row + 1), 0),
    zoneRows: zoneRowsUsed,
    hasZoneOverflow: segments.length > 0,
    hasStationary: stationary.length > 0,
  });

  const overflowedVisitCount = dense.filter((member) => member.kind === 'visit').length;

  /**
   * Move the cursor and take the operator there.
   *
   * Stepping *is* the selection: the member is named, a visit is drawn at its
   * exact persisted offsets and the playhead goes to its exact persisted
   * millisecond. A separate "show" control would be a second button for what
   * the step already did.
   */
  const step = (by: number) => {
    const next = at === null
      ? (by > 0 ? 0 : dense.length - 1)
      : Math.min(dense.length - 1, Math.max(0, at + by));
    const member = dense[next];
    setCursor({ key: subjectKey, id: memberId(member) });
    onSeek(member.kind === 'visit' ? member.interval.startOffsetMs : member.marker.offsetMs);
  };

  const band = (interval: EvidenceTimelineInterval) => ({
    left: percentOf(interval.startOffsetMs, durationMs),
    width: `calc(${percentOf(interval.endOffsetMs, durationMs)} - ${percentOf(interval.startOffsetMs, durationMs)})`,
  });
  const span = (interval: EvidenceTimelineInterval) => (
    `${formatOffset(interval.startOffsetMs, 'tenths')} to ${formatOffset(interval.endOffsetMs, 'tenths')}`
  );
  /** A dense member named with its own exact offsets, never a rounded one. */
  const describeMember = (member: DenseMember) => (
    member.kind === 'visit'
      ? `${member.interval.label}: ${span(member.interval)}`
      : `${member.marker.label}: ${formatOffset(member.marker.offsetMs, 'tenths')}`
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
            // An overflowed visit has no position on this rail: a tick at its
            // true start covered its neighbours the moment two of them began
            // together, hiding the evidence the rail exists to account for.
            //
            // It is not named here either. The segments below state what is
            // in progress and when, and the navigator names and recovers each
            // visit individually — so one piece of evidence has one element,
            // rather than a name here and a control there.
            return null;
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
          The overflow density profile.

          One band per stretch of time over which exactly the same visits are
          open, from a sweep over their own boundaries — so `+N` is the number
          genuinely in progress together across that band, and never a tally of
          visits that merely touch end to end. Bands are consecutive boundary
          pairs, so they are disjoint and the rail stays one row.
        */}
        {segments.map((segment) => (
          <li
            key={segment.id}
            className="evidence-timeline__item evidence-timeline__overflow"
            data-lane={ZONE_LANE}
            // "density", not "overflow": this band is a stretch of time, not an
            // overflowed visit. No element on this rail stands for an
            // individual overflowed visit any more — the navigator names those,
            // one at a time — and keeping the two words apart is what lets the
            // harness check that.
            data-drawn="density"
            data-concurrent={String(segment.count)}
            style={{
              left: percentOf(segment.startOffsetMs, durationMs),
              width: `calc(${percentOf(segment.endOffsetMs, durationMs)} - ${percentOf(segment.startOffsetMs, durationMs)})`,
              top: `${layout.zoneOverflow ?? 0}px`,
            }}
          >
            <span className="visually-hidden">
              {segment.count} zone {segment.count === 1 ? 'visit' : 'visits'} in progress together from{' '}
              {formatOffset(segment.startOffsetMs, 'tenths')} to{' '}
              {formatOffset(segment.endOffsetMs, 'tenths')}, beyond what the timeline draws side by side.
            </span>
            <span aria-hidden="true" className="evidence-timeline__overflow-badge">+{segment.count}</span>
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
        The dense-evidence navigator.

        The timeline's height is fixed, so past a point evidence cannot each
        have a band or a 24px target — but "not drawn side by side" must not
        become "not reachable". This is how the rest stays reachable, and it is
        deliberately **not** a list of them.

        A list would put one permanent control on the surface per fact, so a
        hundred dense visits would cost a hundred tab stops between the timeline
        and the next control, and announce the same evidence the rail already
        accounts for. Instead one member is exposed at a time: the navigator is
        three controls — the disclosure, Previous and Next — whether there are
        four members or a hundred, and stepping to a member names it, draws a
        visit at its exact persisted offsets and seeks to its exact persisted
        millisecond.

        Previous and Next are ordinary buttons on purpose. Enter and Space are
        theirs by native semantics; the arrows, J, L, Home and End stay the
        player's (section 22), so nothing here gives a key a second meaning.
      */}
      {dense.length > 0 ? (
        <details
          className="evidence-timeline__dense"
          // Closing the navigator puts the rail back. Without this there is no
          // way out of a selection once both steps are at an end — with a
          // single dense member that is immediately — and an action the
          // operator cannot undo is worse than one more control would be.
          onToggle={(event) => {
            if (!(event.currentTarget as HTMLDetailsElement).open) setCursor(null);
          }}
        >
          <summary>
            {denseSummary(overflowedVisitCount, markerLayout.overflow.length)}
          </summary>
          <div className="evidence-timeline__navigator">
            {/*
              The member itself, announced politely as the operator steps. It
              is text rather than a control: the stepping is the interaction,
              and a third button here would be a control that does what the
              step already did.
            */}
            <p className="evidence-timeline__navigator-status" role="status">
              {current === null
                ? `Step through ${dense.length} ${dense.length === 1 ? 'item' : 'items'} one at a time.`
                : `${at! + 1} of ${dense.length} — ${describeMember(current)}`}
            </p>
            <div className="evidence-timeline__navigator-controls">
              <button
                type="button"
                onClick={() => step(-1)}
                disabled={at !== null && at === 0}
              >
                Previous
              </button>
              <button
                type="button"
                onClick={() => step(1)}
                disabled={at !== null && at === dense.length - 1}
              >
                Next
              </button>
            </div>
          </div>
        </details>
      ) : null}
    </div>
  );
}
