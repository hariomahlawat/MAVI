/**
 * What the one Evidence Player timeline can carry.
 *
 * These two types are the extension seam UI-5 exists to establish. Today the
 * only supplier is Track evidence: the subject interval and the representative
 * frame. Scene Analytics Slice 5 adds zone visits, crossings, dwell and
 * stationary intervals by supplying more of the same records rather than by
 * reaching into the player.
 *
 * The visual presentation of *analytical* lanes is deliberately not decided
 * here — see {@link SUBJECT_LANE}.
 */

/** A point in the media that means something: an instant, not a span. */
export type EvidenceTimelineMarker = {
  id: string;
  offsetMs: number;
  /** Operator wording. Used by the tick's title and by the accessible twin. */
  label: string;
  /** What kind of instant this is, for styling and for the twin's grouping. */
  kind: string;
};

/** A span of the media that means something. */
export type EvidenceTimelineInterval = {
  id: string;
  startOffsetMs: number;
  endOffsetMs: number;
  label: string;
  /** Which lane the interval belongs to. See {@link SUBJECT_LANE}. */
  lane: string;
};

/**
 * The one lane UI-5 draws.
 *
 * The subject interval — the Track, and later the event, the review is about —
 * has one obvious presentation and real data today, so it is drawn.
 *
 * Every other lane is accepted, listed in the accessible twin, and **not
 * drawn**. That is not an oversight: specification decision 7 leaves the
 * presentation of multiple analytical interval types open, to be chosen in
 * Slice 5 against real zone, dwell and stationary facts. Choosing between
 * stacked lanes and a single lane with glyphs now would mean deciding against
 * nothing, and a lane drawn for data that does not exist is explicitly
 * excluded from UI-5's scope.
 */
export const SUBJECT_LANE = 'subject';

/** Where an offset sits in the media, as a 0..1 ratio, clamped. */
export function ratioOf(offsetMs: number, durationMs: number): number {
  if (!Number.isFinite(offsetMs) || !Number.isFinite(durationMs) || durationMs <= 0) return 0;
  return Math.min(1, Math.max(0, offsetMs / durationMs));
}

/** The same thing as a CSS percentage string. */
export function percentOf(offsetMs: number, durationMs: number): string {
  return `${(ratioOf(offsetMs, durationMs) * 100).toFixed(4)}%`;
}

/**
 * The media offset a pointer at `clientX` names, given the track's rectangle.
 *
 * Clamped to the media: a pointer that leaves the track during a scrub keeps
 * seeking to the nearest end rather than producing an offset outside the media.
 */
export function offsetFromPointer(clientX: number, track: { left: number; width: number }, durationMs: number): number {
  if (!Number.isFinite(clientX) || track.width <= 0 || durationMs <= 0) return 0;
  const ratio = Math.min(1, Math.max(0, (clientX - track.left) / track.width));
  return ratio * durationMs;
}

/** An offset held inside the media, for keyboard seeking and nudges. */
export function clampOffset(offsetMs: number, durationMs: number): number {
  if (!Number.isFinite(offsetMs)) return 0;
  if (!Number.isFinite(durationMs) || durationMs <= 0) return Math.max(0, offsetMs);
  return Math.min(durationMs, Math.max(0, offsetMs));
}

/**
 * The analytical lane families Slice 5 draws, closing specification decision 7.
 *
 * Fixed families, not one row per object. Zone occupancy and stationary are
 * different facts that may overlap in time, so a single interval lane would
 * make an overlap visually ambiguous; one row per zone would let the timeline's
 * height grow with the scene. Each family therefore has a fixed vertical
 * position — itself a non-colour cue — and the zone family packs its visits
 * into a capped number of sub-rows.
 */
export const ZONE_LANE = 'zone';
export const STATIONARY_LANE = 'stationary';

/** Every lane the timeline draws, in fixed vertical order. */
export const DRAWN_LANES: readonly string[] = [SUBJECT_LANE, ZONE_LANE, STATIONARY_LANE];

/**
 * How many visual sub-rows the zone/dwell family may use.
 *
 * Three is the cap that keeps the timeline's height fixed. A fourth concurrent
 * visit does not get a row; it goes to the overflow rail, because growing the
 * timeline with the evidence is what this cap exists to prevent.
 */
export const MAX_ZONE_SUBROWS = 3;

/** Where one interval was placed for drawing. Presentation only. */
export type PackedInterval = {
  interval: EvidenceTimelineInterval;
  /** Visual sub-row, or `null` when it went to the fixed overflow rail. */
  row: number | null;
  /** How many intervals in this family positively overlap it, itself included. */
  concurrent: number;
};

/** Two spans share time, rather than merely touching at an endpoint. */
function overlaps(a: EvidenceTimelineInterval, b: EvidenceTimelineInterval): boolean {
  return a.startOffsetMs < b.endOffsetMs && b.startOffsetMs < a.endOffsetMs;
}

/**
 * Deterministic bounded packing for one lane family.
 *
 * Sorted by start, then end, then stable evidence id, so the same facts always
 * produce the same picture — an operator comparing two screenshots of the same
 * Track must not see the bands move. Each interval takes the first sub-row it
 * does not positively overlap; intervals that merely touch at an endpoint may
 * share a row, because they are not concurrent.
 *
 * This is **presentation only**. Nothing here merges visits, changes an offset,
 * infers a fact or drops an interval: every input comes back out, and the
 * semantic list is built from the intervals rather than from this result.
 */
export function packIntervals(
  intervals: readonly EvidenceTimelineInterval[],
  maxRows: number = MAX_ZONE_SUBROWS,
): PackedInterval[] {
  const sorted = [...intervals].sort((a, b) => (
    a.startOffsetMs - b.startOffsetMs
    || a.endOffsetMs - b.endOffsetMs
    || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
  ));

  // The last interval occupying each row; a row is free when the candidate does
  // not positively overlap it. Sorting by start means only the latest interval
  // on a row can conflict.
  const rows: EvidenceTimelineInterval[] = [];
  return sorted.map((interval) => {
    const concurrent = sorted.reduce(
      (count, other) => count + (other === interval || overlaps(interval, other) ? 1 : 0),
      0,
    );

    let row: number | null = null;
    for (let index = 0; index < maxRows; index += 1) {
      const occupant = rows[index];
      if (!occupant || !overlaps(interval, occupant)) {
        rows[index] = interval;
        row = index;
        break;
      }
    }
    return { interval, row, concurrent };
  });
}

/**
 * How near two markers must be before their 24px targets collide.
 *
 * Expressed as a fraction of the media, because the timeline is laid out in
 * percentages and its pixel width is not known when the markers are placed.
 * The figure is the worst case the layout actually produces: at 1366x768 the
 * Review timeline is about 690px wide, and 24/690 is a little under 3.5%.
 * Staggering two markers that would not in fact have collided on a wider
 * display costs nothing; failing to stagger two that do makes one of them
 * unclickable.
 */
export const MARKER_COLLISION_RATIO = 0.035;

/** How many rows the marker rail may use. Fixed, so the rail height never grows. */
export const MAX_MARKER_ROWS = 3;

/** One marker control: a single instant, or several evidence items at one instant. */
export type PlacedMarker = {
  /** The marker that names the control's position. */
  marker: EvidenceTimelineMarker;
  /** Every evidence item at this exact offset, in supplied order. */
  cluster: EvidenceTimelineMarker[];
  row: number;
};

/**
 * Lay markers out so every one of them stays independently activatable.
 *
 * Two rules, in order. Markers at *exactly* the same offset become one control:
 * they have one common exact destination, so a second control would be a second
 * button that does the same thing, and the cluster's accessible name carries
 * every item at that instant. Markers at *different* offsets always stay
 * separate controls — they seek to different places — and are staggered onto
 * different rows when their targets would otherwise overlap.
 *
 * The rail is bounded: a marker that cannot find a clear row takes the row whose
 * nearest neighbour is furthest away, which is deterministic and is the best
 * available separation rather than an unbounded new row.
 */
export function layOutMarkers(
  markers: readonly EvidenceTimelineMarker[],
  durationMs: number,
): PlacedMarker[] {
  // Sorted by offset alone. `sort` is stable, so markers sharing an offset keep
  // the order the caller supplied — which is the order their evidence reads in
  // — while controls at different offsets are still ordered deterministically.
  const sorted = [...markers].sort((a, b) => a.offsetMs - b.offsetMs);

  const clusters: PlacedMarker[] = [];
  for (const marker of sorted) {
    const last = clusters[clusters.length - 1];
    if (last && last.marker.offsetMs === marker.offsetMs) {
      last.cluster.push(marker);
      continue;
    }
    clusters.push({ marker, cluster: [marker], row: 0 });
  }

  const separation = durationMs > 0 ? durationMs * MARKER_COLLISION_RATIO : 0;
  // The offset of the last control placed on each row.
  const lastOnRow: number[] = [];
  for (const placed of clusters) {
    let chosen = 0;
    let bestGap = -1;
    for (let row = 0; row < MAX_MARKER_ROWS; row += 1) {
      const previous = lastOnRow[row];
      if (previous === undefined) { chosen = row; bestGap = Number.POSITIVE_INFINITY; break; }
      const gap = placed.marker.offsetMs - previous;
      if (gap >= separation) { chosen = row; bestGap = Number.POSITIVE_INFINITY; break; }
      if (gap > bestGap) { bestGap = gap; chosen = row; }
    }
    placed.row = chosen;
    lastOnRow[chosen] = placed.marker.offsetMs;
  }
  return clusters;
}

/**
 * Where each lane family sits inside the track, in CSS pixels from its top.
 *
 * Computed rather than fixed so the timeline is only as tall as the evidence
 * needs, while staying bounded: the marker rail is capped at
 * {@link MAX_MARKER_ROWS} rows and the zone family at {@link MAX_ZONE_SUBROWS}
 * sub-rows plus one overflow rail, so no amount of evidence can grow it past
 * the worst case. It never grows with the number of zones, visits, crossings or
 * stationary intervals — only with how many of them are *concurrent*, and that
 * is capped.
 */
export type TimelineLayout = {
  markerRail: number;
  subject: number;
  zoneRows: number[];
  zoneOverflow: number | null;
  stationary: number | null;
  height: number;
};

/** A marker control's target, and the band and tick sizes drawn inside the lanes. */
export const MARKER_TARGET_PX = 24;
const LANE_STEP_PX = 6;
const BAND_PX = 4;

export function timelineLayout(options: {
  markerRows: number;
  zoneRows: number;
  hasZoneOverflow: boolean;
  hasStationary: boolean;
}): TimelineLayout {
  const markerRows = Math.min(MAX_MARKER_ROWS, Math.max(1, options.markerRows));
  const markerRail = markerRows * MARKER_TARGET_PX;

  let next = markerRail;
  const subject = next;
  next += LANE_STEP_PX;

  const zoneRows: number[] = [];
  for (let row = 0; row < Math.min(MAX_ZONE_SUBROWS, Math.max(0, options.zoneRows)); row += 1) {
    zoneRows.push(next);
    next += LANE_STEP_PX;
  }

  let zoneOverflow: number | null = null;
  if (options.hasZoneOverflow) { zoneOverflow = next; next += LANE_STEP_PX; }

  let stationary: number | null = null;
  if (options.hasStationary) { stationary = next; next += LANE_STEP_PX; }

  return { markerRail, subject, zoneRows, zoneOverflow, stationary, height: next + BAND_PX };
}
