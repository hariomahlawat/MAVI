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
  /**
   * The largest number of intervals that are inside this one *at the same
   * instant*, itself included.
   *
   * Not a count of how many intervals it overlaps somewhere along its length.
   * A visit that overlaps one interval early and a different one late never
   * shared a moment with both, and calling it "one of three concurrent visits"
   * would claim a three-way overlap that never happened — a claim about the
   * evidence, not about the drawing.
   */
  concurrent: number;
};

/** Two spans share time, rather than merely touching at an endpoint. */
function overlaps(a: EvidenceTimelineInterval, b: EvidenceTimelineInterval): boolean {
  return a.startOffsetMs < b.endOffsetMs && b.startOffsetMs < a.endOffsetMs;
}

/**
 * The most intervals that share any one instant inside `interval`.
 *
 * Concurrency can only rise at a start, so probing the starts of the intervals
 * that overlap this one is enough to find the peak. Bounded evidence makes the
 * quadratic sweep the right trade for code that is obviously correct.
 */
function maxConcurrencyDuring(
  interval: EvidenceTimelineInterval,
  all: readonly EvidenceTimelineInterval[],
): number {
  const overlapping = all.filter((other) => other === interval || overlaps(interval, other));
  let highest = 1;
  for (const probe of overlapping) {
    const at = Math.max(probe.startOffsetMs, interval.startOffsetMs);
    if (at >= interval.endOffsetMs) continue;
    const here = overlapping.reduce(
      (count, other) => count + (other.startOffsetMs <= at && at < other.endOffsetMs ? 1 : 0),
      0,
    );
    if (here > highest) highest = here;
  }
  return highest;
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
    const concurrent = maxConcurrencyDuring(interval, sorted);

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
 * One stretch of time over which exactly the same overflowed visits are open.
 *
 * Derived by a **sweep line** over the overflowed intervals' own boundaries,
 * not by grouping intervals that happen to touch. The difference is the whole
 * point: grouping by transitive overlap puts [0,10], [5,15] and [14,20] in one
 * group of three, and no instant in that group ever holds three visits. A
 * segment's count is the size of the set that is actually open across it, so
 * it cannot describe an overlap that did not happen.
 *
 * Segments are consecutive boundary pairs, so they are **disjoint by
 * construction** and their bands can never paint over one another; the rail
 * stays one row whatever the evidence does.
 */
export type OverflowSegment = {
  id: string;
  startOffsetMs: number;
  endOffsetMs: number;
  /**
   * How many overflowed visits are in progress **simultaneously**, throughout
   * this segment. This is the number `+N` states, and it is a true
   * simultaneous count rather than a membership tally.
   */
  count: number;
  /** Those visits, in the order they start. */
  members: EvidenceTimelineInterval[];
};

/** Deterministic order for the overflowed set: by start, then end, then id. */
function byStartThenEndThenId(a: EvidenceTimelineInterval, b: EvidenceTimelineInterval): number {
  return a.startOffsetMs - b.startOffsetMs
    || a.endOffsetMs - b.endOffsetMs
    || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

/** The intervals that did not fit a sub-row, in a deterministic order. */
export function overflowedIntervals(packed: readonly PackedInterval[]): EvidenceTimelineInterval[] {
  return packed
    .filter((entry) => entry.row === null)
    .map((entry) => entry.interval)
    .sort(byStartThenEndThenId);
}

/**
 * The overflow density profile: disjoint segments, each with the set genuinely
 * open across it.
 *
 * Boundaries are the starts and ends of the overflowed intervals, so the active
 * set can only change at one of them; between two consecutive boundaries it is
 * constant. A segment is emitted only where something is open, and adjacent
 * segments holding **the same members** are coalesced, so a boundary that
 * changes nothing does not split a band in two.
 *
 * Intervals are half-open: one ending exactly where another begins is not an
 * overlap, here or in the packer.
 *
 * Cost is O(B log B + B·M) for M overflowed intervals and B ≤ 2M boundaries,
 * computed from the evidence alone. Nothing here depends on the playhead, so it
 * never runs on an animation frame.
 */
export function overflowSegments(packed: readonly PackedInterval[]): OverflowSegment[] {
  // A zero-length interval is open at no instant, so it cannot contribute to a
  // density band. It is still evidence: it keeps its turn in the navigator,
  // where it is named with the offsets it actually has rather than being
  // quietly repaired into a band.
  const overflowed = overflowedIntervals(packed)
    .filter((interval) => interval.startOffsetMs < interval.endOffsetMs);
  if (overflowed.length === 0) return [];

  const boundaries = [...new Set(
    overflowed.flatMap((interval) => [interval.startOffsetMs, interval.endOffsetMs]),
  )].sort((a, b) => a - b);

  const segments: OverflowSegment[] = [];
  for (let index = 0; index < boundaries.length - 1; index += 1) {
    const startOffsetMs = boundaries[index];
    const endOffsetMs = boundaries[index + 1];
    const members = overflowed.filter(
      (interval) => interval.startOffsetMs <= startOffsetMs && startOffsetMs < interval.endOffsetMs,
    );
    if (members.length === 0) continue;

    const open = segments[segments.length - 1];
    const sameMembers = open !== undefined
      && open.endOffsetMs === startOffsetMs
      && open.members.length === members.length
      && open.members.every((member, at) => member === members[at]);
    if (sameMembers) {
      open.endOffsetMs = endOffsetMs;
      continue;
    }
    segments.push({
      id: `overflow-${startOffsetMs}-${members[0].id}`,
      startOffsetMs,
      endOffsetMs,
      count: members.length,
      members,
    });
  }
  return segments;
}

/**
 * The track width assumed before the element has been measured.
 *
 * Deliberately the *narrow* case — the Investigation inspector's drawer, not
 * Review's wider column — because assuming a wide track under-staggers, and an
 * under-staggered marker is one the operator cannot click. The real width
 * replaces this as soon as the element is measured.
 */
export const ASSUMED_TRACK_WIDTH_PX = 400;

/** How many rows the marker rail may use. Fixed, so the rail height never grows. */
export const MAX_MARKER_ROWS = 3;

/**
 * One unit of marker evidence: a single instant, or several evidence items at
 * one instant.
 *
 * **The same shape whether or not the rail had room for it.** Clustering
 * happens once, before placement; a cluster that cannot be placed is still a
 * cluster. If the two paths carried different shapes the meaning of the
 * evidence would depend on the width of the panel showing it — one combined
 * control in a wide host, several identical steps in a narrow one — and there
 * would be two clustering rules to keep in agreement.
 */
export type MarkerCluster = {
  /** The marker that names the unit's position. */
  marker: EvidenceTimelineMarker;
  /** Every evidence item at this exact offset, in supplied order. */
  cluster: EvidenceTimelineMarker[];
};

/** A marker cluster the rail had room for, on its chosen row. */
export type PlacedMarker = MarkerCluster & { row: number };

/** The one name a cluster answers to, wherever it is shown. */
export function clusterName(cluster: readonly EvidenceTimelineMarker[]): string {
  return cluster.map((marker) => marker.label).join('; ');
}

export type MarkerLayout = {
  /** Controls placed on the rail. No two of these can overlap. */
  placed: PlacedMarker[];
  /**
   * The clusters too dense to place without covering another control.
   *
   * Same shape as {@link MarkerLayout.placed} minus the row it did not get, so
   * a cluster means the same thing on either side of the boundary. Nothing is
   * dropped and nothing is merged across offsets.
   */
  overflow: MarkerCluster[];
};

/**
 * Lay markers out so every one of them stays independently activatable.
 *
 * Markers at *exactly* the same offset become one control: they have one common
 * exact destination, so a second button would do the same thing, and the
 * cluster's accessible name carries every item at that instant. Markers at
 * *different* offsets are never merged — they seek to different places — and are
 * staggered onto different rows when their targets would otherwise overlap.
 *
 * The rail is bounded at {@link MAX_MARKER_ROWS} rows, and a marker that cannot
 * find a row with real clearance is **not placed at all**. An earlier version
 * fell back to the row with the largest gap, which still put two 24px targets
 * on top of each other once four markers packed tightly enough; the one
 * underneath was then unclickable, which is exactly the failure the staggering
 * exists to prevent. Density beyond the rail goes to the disclosure instead.
 *
 * `trackWidthPx` is the **measured** width of the rendered track. The threshold
 * has to come from it rather than from a constant, because this component is
 * reused in the Investigation inspector, whose track is far narrower than
 * Review's: the same offsets are that much closer together in pixels there.
 */
export function layOutMarkers(
  markers: readonly EvidenceTimelineMarker[],
  durationMs: number,
  trackWidthPx = 0,
): MarkerLayout {
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

  // The media span that one control's target covers at the measured width.
  const width = trackWidthPx > 0 ? trackWidthPx : ASSUMED_TRACK_WIDTH_PX;
  const separation = durationMs > 0 ? durationMs * (MARKER_TARGET_PX / width) : 0;

  const lastOnRow: number[] = [];
  const placed: PlacedMarker[] = [];
  const overflow: MarkerCluster[] = [];
  for (const candidate of clusters) {
    let chosen = -1;
    for (let row = 0; row < MAX_MARKER_ROWS; row += 1) {
      const previous = lastOnRow[row];
      if (previous === undefined || candidate.marker.offsetMs - previous >= separation) {
        chosen = row;
        break;
      }
    }
    if (chosen === -1) {
      // The whole unit, not its members: one exact destination stays one unit
      // of recovery whether or not the rail had room for it.
      overflow.push({ marker: candidate.marker, cluster: candidate.cluster });
      continue;
    }
    candidate.row = chosen;
    lastOnRow[chosen] = candidate.marker.offsetMs;
    placed.push(candidate);
  }
  return { placed, overflow };
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
  // At least one row even with no markers: the rail is what gives the scrub
  // surface its 24px pointer target, and the thin lanes below it come to ten
  // pixels between them. Capped at the top so the rail cannot grow with the
  // evidence.
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
