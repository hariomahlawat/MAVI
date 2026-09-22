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
