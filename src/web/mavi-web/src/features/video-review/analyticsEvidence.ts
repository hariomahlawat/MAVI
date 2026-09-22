import type { SceneRevision, SceneTripLine, SceneZone } from '../../api/scene';
import type {
  TrackDetailAnalytics,
  TrackDetailLineCrossing,
  TrackDetailZoneVisit,
} from '../../api/tracks';
import { formatDuration } from '../../shared/format/duration';
import { formatOffset } from '../../shared/format/format';
import type { EvidenceTimelineInterval, EvidenceTimelineMarker } from '../../shared/evidence/timeline';
import { STATIONARY_LANE, ZONE_LANE } from '../../shared/evidence/timeline';
import {
  crossingDirectionLabel,
  lineLabel,
  shortId,
  zoneLabel,
  type GeometryNames,
} from '../visual-search/analyticsLabels';

/**
 * Persisted Scene Analytics facts, turned into the Evidence Player's existing
 * records. Pure: no React, no query client, no media element, no DOM.
 *
 * The one rule that governs this whole module is that **nothing here derives an
 * analytical fact**. A zone visit exists because the engine persisted a zone
 * visit; a crossing is at the point the engine persisted, not at an intersection
 * recomputed from the browser's copy of the trajectory. The trajectory is raw
 * evidence that happens to be on the same screen, and recomputing analytics from
 * it would produce a second, unattributable answer that no operator could tell
 * apart from the persisted one.
 *
 * Geometry is likewise taken from the pinned revision the facts name, or not
 * taken at all: a fact whose zone cannot be resolved is still a fact and keeps
 * its stable id, but no outline is drawn from a revision that did not produce it.
 */

/** Where a crossing happened, in normalised source-frame coordinates. */
export type CrossingPoint = {
  id: string;
  lineId: string;
  crossingIndex: number;
  offsetMs: number;
  direction: TrackDetailLineCrossing['direction'];
  x: number;
  y: number;
  /** The operator's wording for this direction, from the pinned line when known. */
  directionLabel: string;
  lineName: string;
};

/** One zone from the pinned revision, with what this Track did in it. */
export type ZoneEvidence = {
  zone: SceneZone;
  name: string;
  /** This Track has at least one persisted visit or summary for this zone. */
  interacted: boolean;
  visitCount: number;
};

/** One trip line from the pinned revision, with what this Track did to it. */
export type LineEvidence = {
  line: SceneTripLine;
  name: string;
  interacted: boolean;
  crossingCount: number;
};

export type TrackAnalyticsEvidenceModel = {
  zones: ZoneEvidence[];
  lines: LineEvidence[];
  crossings: CrossingPoint[];
  intervals: EvidenceTimelineInterval[];
  markers: EvidenceTimelineMarker[];
  matchedZoneIds: ReadonlySet<string>;
  matchedLineIds: ReadonlySet<string>;
};

export const EMPTY_ANALYTICS_EVIDENCE: TrackAnalyticsEvidenceModel = {
  zones: [], lines: [], crossings: [], intervals: [], markers: [],
  matchedZoneIds: new Set(), matchedLineIds: new Set(),
};

/** Zone ids this Track has any persisted fact for. Visits and summaries both count. */
export function matchedZoneIds(analytics: TrackDetailAnalytics): ReadonlySet<string> {
  const ids = new Set<string>();
  for (const visit of analytics.zoneVisits) ids.add(visit.zoneId.toLowerCase());
  for (const summary of analytics.zoneSummaries) {
    if (summary.visitCount > 0 || summary.totalDwellMs > 0) ids.add(summary.zoneId.toLowerCase());
  }
  return ids;
}

/** Line ids this Track crossed. A line with no persisted crossing is context, not a match. */
export function matchedLineIds(analytics: TrackDetailAnalytics): ReadonlySet<string> {
  return new Set(analytics.lineCrossings.map((crossing) => crossing.lineId.toLowerCase()));
}

/** A stable, unique record id for one persisted visit. */
function visitId(visit: TrackDetailZoneVisit): string {
  return `zone-visit-${visit.zoneId}-${visit.visitIndex}`;
}

/**
 * How a visit began and ended, in operator wording.
 *
 * This exists so the timeline never implies a boundary crossing the engine did
 * not record. A Track already inside the zone when observation started did not
 * enter it; a visit closed because the samples stopped did not leave it. Saying
 * "entered" for either would be a fabricated event.
 */
export function visitBoundaryNote(visit: TrackDetailZoneVisit): string {
  const parts: string[] = [];
  if (visit.beganInside) parts.push('already inside when the Track was first observed');
  if (visit.closedByGap) parts.push('closed by a gap in the samples, not by leaving');
  else if (visit.endedInside) parts.push('still inside when the Track was last observed');
  return parts.join('; ');
}

export function zoneVisitInterval(
  visit: TrackDetailZoneVisit,
  names: GeometryNames | undefined,
): EvidenceTimelineInterval {
  const note = visitBoundaryNote(visit);
  return {
    id: visitId(visit),
    startOffsetMs: visit.entryOffsetMs,
    endOffsetMs: visit.exitOffsetMs,
    label: `In ${zoneLabel(visit.zoneId, names)} for ${formatDuration(visit.dwellMs)}`
      + (note ? ` (${note})` : ''),
    lane: ZONE_LANE,
  };
}

/**
 * Boundary markers for one visit — only where a boundary was actually crossed.
 *
 * The three persisted flags are the whole rule. `beganInside` means the entry
 * offset is where observation started, not where the Track came through the
 * edge. `closedByGap` means the exit offset is the last sample before the
 * trajectory went quiet. Neither is a crossing, and neither gets a marker.
 */
export function zoneBoundaryMarkers(
  visit: TrackDetailZoneVisit,
  names: GeometryNames | undefined,
): EvidenceTimelineMarker[] {
  const markers: EvidenceTimelineMarker[] = [];
  const name = zoneLabel(visit.zoneId, names);
  if (!visit.beganInside) {
    markers.push({
      id: `${visitId(visit)}-entry`,
      offsetMs: visit.entryOffsetMs,
      label: `Entered ${name}`,
      kind: 'zone-entry',
    });
  }
  if (!visit.endedInside && !visit.closedByGap) {
    markers.push({
      id: `${visitId(visit)}-exit`,
      offsetMs: visit.exitOffsetMs,
      label: `Left ${name}`,
      kind: 'zone-exit',
    });
  }
  return markers;
}

export function crossingMarker(
  crossing: TrackDetailLineCrossing,
  names: GeometryNames | undefined,
): EvidenceTimelineMarker {
  const line = names?.lines.get(crossing.lineId.toLowerCase());
  return {
    id: `crossing-${crossing.lineId}-${crossing.crossingIndex}`,
    offsetMs: crossing.offsetMs,
    label: `Crossed ${lineLabel(crossing.lineId, names)} ${crossingDirectionLabel(crossing.direction, line)}`,
    kind: 'crossing',
  };
}

export function stationaryIntervals(analytics: TrackDetailAnalytics): EvidenceTimelineInterval[] {
  const intervals = analytics.motion?.stationaryIntervals ?? [];
  return intervals.map((interval, index) => ({
    id: `stationary-${index}`,
    startOffsetMs: interval.startOffsetMs,
    endOffsetMs: interval.endOffsetMs,
    label: `Stationary for ${formatDuration(Math.max(0, interval.endOffsetMs - interval.startOffsetMs))}`,
    lane: STATIONARY_LANE,
  }));
}

/**
 * Whether persisted stationary intervals overlap one another.
 *
 * They are not expected to: the engine emits disjoint intervals for one Track.
 * The stationary family is drawn in one fixed row, so malformed overlapping
 * facts would silently paint over each other — a rendering that hides evidence
 * rather than showing it. Callers surface this instead of absorbing it.
 */
export function hasOverlappingStationary(intervals: readonly EvidenceTimelineInterval[]): boolean {
  const sorted = [...intervals].sort((a, b) => a.startOffsetMs - b.startOffsetMs);
  for (let index = 1; index < sorted.length; index += 1) {
    if (sorted[index].startOffsetMs < sorted[index - 1].endOffsetMs) return true;
  }
  return false;
}

/**
 * The whole analytical evidence model for one Track and one pinned revision.
 *
 * `revision` is the revision the facts name, already verified by the caller, or
 * `undefined` when it could not be loaded. Facts do not disappear when geometry
 * does: the timeline records and crossing points are still evidence and are
 * still produced, named by stable id instead of by the operator's zone name.
 * What disappears is the outlines, because there is nothing truthful to draw.
 */
export function buildAnalyticsEvidence(
  analytics: TrackDetailAnalytics | undefined,
  revision: SceneRevision | undefined,
): TrackAnalyticsEvidenceModel {
  if (!analytics) return EMPTY_ANALYTICS_EVIDENCE;

  const names: GeometryNames | undefined = revision
    ? {
      zones: new Map(revision.zones.map((zone) => [zone.zoneId.toLowerCase(), zone])),
      lines: new Map(revision.tripLines.map((line) => [line.lineId.toLowerCase(), line])),
      revisionNumber: revision.revisionNumber,
    }
    : undefined;

  const zoneIds = matchedZoneIds(analytics);
  const lineIds = matchedLineIds(analytics);

  const visitsByZone = new Map<string, number>();
  for (const visit of analytics.zoneVisits) {
    const key = visit.zoneId.toLowerCase();
    visitsByZone.set(key, (visitsByZone.get(key) ?? 0) + 1);
  }
  const crossingsByLine = new Map<string, number>();
  for (const crossing of analytics.lineCrossings) {
    const key = crossing.lineId.toLowerCase();
    crossingsByLine.set(key, (crossingsByLine.get(key) ?? 0) + 1);
  }

  const zones: ZoneEvidence[] = (revision?.zones ?? []).map((zone) => {
    const key = zone.zoneId.toLowerCase();
    return {
      zone,
      name: zone.name || shortId(zone.zoneId),
      // A disabled zone was not evaluated by the engine that produced these
      // facts, so it can never be a match however the ids line up.
      interacted: zone.enabled && zoneIds.has(key),
      visitCount: visitsByZone.get(key) ?? 0,
    };
  });

  const lines: LineEvidence[] = (revision?.tripLines ?? []).map((line) => {
    const key = line.lineId.toLowerCase();
    return {
      line,
      name: line.name || shortId(line.lineId),
      interacted: line.enabled && lineIds.has(key),
      crossingCount: crossingsByLine.get(key) ?? 0,
    };
  });

  const crossings: CrossingPoint[] = analytics.lineCrossings.map((crossing) => {
    const line = names?.lines.get(crossing.lineId.toLowerCase());
    return {
      id: `crossing-${crossing.lineId}-${crossing.crossingIndex}`,
      lineId: crossing.lineId,
      crossingIndex: crossing.crossingIndex,
      offsetMs: crossing.offsetMs,
      direction: crossing.direction,
      // The persisted point, exactly. Never an intersection recomputed here.
      x: crossing.pointX,
      y: crossing.pointY,
      directionLabel: crossingDirectionLabel(crossing.direction, line),
      lineName: lineLabel(crossing.lineId, names),
    };
  });

  const intervals: EvidenceTimelineInterval[] = [
    ...analytics.zoneVisits.map((visit) => zoneVisitInterval(visit, names)),
    ...stationaryIntervals(analytics),
  ];

  const markers: EvidenceTimelineMarker[] = [
    ...analytics.zoneVisits.flatMap((visit) => zoneBoundaryMarkers(visit, names)),
    ...analytics.lineCrossings.map((crossing) => crossingMarker(crossing, names)),
  ];

  return { zones, lines, crossings, intervals, markers, matchedZoneIds: zoneIds, matchedLineIds: lineIds };
}

/** A crossing's media time, as the explanation and the marker both say it. */
export function crossingTimeLabel(offsetMs: number): string {
  return formatOffset(offsetMs, 'tenths');
}
