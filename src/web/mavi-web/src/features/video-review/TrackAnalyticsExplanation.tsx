import type { ReactNode } from 'react';
import type { TrackDetailAnalytics, TrackDetailZoneVisit } from '../../api/tracks';
import Alert from '../../shared/components/Alert';
import Button from '../../shared/components/Button';
import KeyValue, { type KeyValueItem } from '../../shared/components/KeyValue';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp, formatOffset } from '../../shared/format/format';
import {
  crossingDirectionLabel,
  engineLabel,
  lineLabel,
  motionDirectionLabel,
  zoneLabel,
  type GeometryNames,
} from '../../shared/evidence/analyticsLabels';
import { visitBoundaryNote } from './analyticsEvidence';
import type { AnalyticsSceneState } from './useAnalyticsScene';

/**
 * Why the Track's analytical evidence says what it says.
 *
 * One component for Review and for the Investigation inspector. `compact`
 * changes density and what starts collapsed — never which facts exist, and
 * never their wording: two surfaces showing the same Track under the same
 * identity must not be able to disagree about it.
 *
 * The identity leads, because the same Track has different facts under
 * different revisions and a dwell time means nothing without the geometry it
 * was measured against. Engineering diagnostics stay behind a disclosure rather
 * than being promoted into operator copy.
 */

/** The readiness vocabulary the Processing surfaces already use. No fourth set of words. */
const STATUS_WORDS: Record<TrackDetailAnalytics['status'], string> = {
  Analysed: 'Analysed',
  Unavailable: 'Evidence could not be analysed',
  Pending: 'Not analysed yet',
  Failed: 'Analysis failed for this run',
  Stale: 'Analysed with an earlier revision or engine',
  NotConfigured: 'No scene configured for this camera',
  Disabled: 'Analytics disabled by the scene revision',
};

/** What each state means for the operator's next move. Distinct, never collapsed. */
const STATUS_EXPLANATION: Record<TrackDetailAnalytics['status'], string> = {
  Analysed: '',
  Unavailable: 'The analysis ran for this Track but produced no facts.',
  Pending: 'This processing run has not been analysed yet. Facts appear once it has.',
  Failed: 'The analysis of this run did not complete, so no facts exist for it.',
  Stale: 'The facts below were measured against an earlier revision or engine than the one now current. They are not recomputed here.',
  NotConfigured: 'This camera has no scene configuration, so there is no geometry to measure against.',
  Disabled: 'The scene revision in force has no enabled geometry, so analytics were not run.',
};

/** `bbox-centre` as an operator reads it: a point in the image, not a position on the ground. */
export function referencePointLabel(referencePoint: string | null): string {
  if (!referencePoint) return 'Not stated';
  if (referencePoint === 'bbox-centre' || referencePoint === 'bbox_centre') return 'Box centre';
  return referencePoint;
}

/**
 * Items of one kind (crossings, or Review's visits) shown inline per panel
 * before the rest go behind a disclosure (§37.1 large data, N = 5).
 */
const INLINE_PER_PANEL = 5;

/**
 * A bounded list (§37.1, §37.2): the first items while the panel's budget
 * lasts, inline, and the rest of this group behind one closed disclosure.
 */
function bounded<T>(
  items: readonly T[],
  budget: { left: number },
  render: (items: readonly T[]) => ReactNode,
  noun: [singular: string, plural: string],
): ReactNode {
  const inline = items.slice(0, Math.max(0, budget.left));
  const rest = items.slice(inline.length);
  budget.left -= inline.length;
  return (
    <>
      {inline.length > 0 ? <ul className="analytics-list">{render(inline)}</ul> : null}
      {rest.length > 0 ? (
        <details className="disclosure">
          <summary>{`${rest.length} more ${rest.length === 1 ? noun[0] : noun[1]}`}</summary>
          <ul className="analytics-list disclosure__body">{render(rest)}</ul>
        </details>
      ) : null}
    </>
  );
}

function visitLine(visit: TrackDetailZoneVisit): string {
  const note = visitBoundaryNote(visit);
  return `${formatOffset(visit.entryOffsetMs, 'tenths')} to ${formatOffset(visit.exitOffsetMs, 'tenths')}`
    + ` · ${formatDuration(visit.dwellMs)}`
    + (note ? ` · ${note}` : '');
}

export default function TrackAnalyticsExplanation({
  analytics,
  scene,
  geometry,
  displayTimeZoneId,
  compact = false,
}: {
  analytics: TrackDetailAnalytics;
  /** The pinned revision's load state, so geometry problems are stated rather than hidden. */
  scene?: AnalyticsSceneState;
  /** Names from the pinned revision. Absent means stable ids, never another revision's names. */
  geometry?: GeometryNames;
  displayTimeZoneId?: string;
  compact?: boolean;
}) {
  const identity = analytics.sceneRevisionId === null
    ? 'No scene revision'
    : `Scene revision ${analytics.sceneRevisionNumber ?? '?'} · ${engineLabel(analytics.algorithmVersion)}`;

  const items: KeyValueItem[] = [
    { label: 'Status', value: STATUS_WORDS[analytics.status] },
    { label: 'Identity', value: identity },
  ];

  // The identity is stated once, in these rows (F18): there is no footer
  // restating it, so a revision with no facts still names its reference point.
  if (analytics.status === 'Analysed' || analytics.status === 'Stale' || analytics.sceneRevisionNumber !== null) {
    items.push({ label: 'Reference point', value: referencePointLabel(analytics.referencePoint) });
  }

  if (analytics.unavailableReason) {
    items.push({ label: 'Reason', value: analytics.unavailableReason, mono: true });
  }

  const hasFacts = analytics.zoneSummaries.length > 0
    || analytics.zoneVisits.length > 0
    || analytics.lineCrossings.length > 0
    || analytics.motion !== null;

  if (hasFacts) {
    const visitsByZone = new Map<string, TrackDetailZoneVisit[]>();
    for (const visit of analytics.zoneVisits) {
      const key = visit.zoneId.toLowerCase();
      visitsByZone.set(key, [...(visitsByZone.get(key) ?? []), visit]);
    }

    const visited = analytics.zoneSummaries.filter((summary) => summary.visitCount > 0);
    const visitBudget = { left: INLINE_PER_PANEL };
    const visitItems = (visits: readonly TrackDetailZoneVisit[]) => visits.map(
      (visit) => <li key={visit.visitIndex}>{visitLine(visit)}</li>,
    );
    items.push({
      label: 'Zones',
      value: visited.length === 0
        ? 'No zone visited'
        : (
          <ul className="analytics-list">
            {visited.map((summary) => {
              const visits = visitsByZone.get(summary.zoneId.toLowerCase()) ?? [];
              return (
                <li key={summary.zoneId}>
                  <strong>{zoneLabel(summary.zoneId, geometry)}</strong>
                  {' · '}{summary.visitCount} {summary.visitCount === 1 ? 'visit' : 'visits'}
                  {' · '}dwell {formatDuration(summary.totalDwellMs)}
                  {summary.loitering ? (
                    <>
                      {' · '}
                      {/*
                        `loiteringDwellMs` is the *total* dwell the rule measured,
                        not the amount by which it exceeded the threshold. Calling
                        all of it "past" the threshold overstated the excess by a
                        whole threshold's worth — 140s against a 60s rule read as
                        though the Track had loitered 140s too long. The persisted
                        fact is a total, so it is stated as one.
                      */}
                      <span className="text-warn">
                        Loitering: {formatDuration(summary.loiteringDwellMs)} dwell
                        {' '}against a {formatDuration(summary.loiteringThresholdSeconds * 1000)} threshold
                      </span>
                    </>
                  ) : null}
                  {/* Individual visits matter: two short visits and one long
                      one are different behaviour with the same total dwell.
                      Review lists them as a bounded list; the inspector keeps
                      them one disclosure away. */}
                  {visits.length > 0 && compact ? (
                    <details className="disclosure">
                      <summary>{visits.length === 1 ? 'Visit' : `${visits.length} visits`}</summary>
                      <ul className="analytics-list disclosure__body">{visitItems(visits)}</ul>
                    </details>
                  ) : null}
                  {visits.length > 0 && !compact ? bounded(visits, visitBudget, visitItems, ['visit', 'visits']) : null}
                </li>
              );
            })}
          </ul>
        ),
    });

    const crossingItems = (lineId: string, crossings: readonly (typeof analytics.lineCrossings)[number][]) => crossings.map((crossing) => (
      <li key={crossing.crossingIndex}>
        {crossingDirectionLabel(crossing.direction, geometry?.lines.get(lineId.toLowerCase()))}
        {' at '}{formatOffset(crossing.offsetMs, 'tenths')}
        {' · '}{displayTimestamp(crossing.timestampUtc, displayTimeZoneId)}
      </li>
    ));
    const byLine = new Map<string, typeof analytics.lineCrossings>();
    for (const crossing of analytics.lineCrossings) {
      byLine.set(crossing.lineId, [...(byLine.get(crossing.lineId) ?? []), crossing]);
    }
    // §37.1 large data, §37.2: on both surfaces the crossings are a bounded
    // list — the first five in the panel inline (direction and media time are
    // what an operator searched by), any after them one disclosure away.
    const crossingBudget = { left: INLINE_PER_PANEL };
    items.push({
      label: 'Line crossings',
      value: byLine.size === 0
        ? 'No line crossed'
        : (
          <ul className="analytics-list">
            {[...byLine.entries()].map(([lineId, crossings]) => (
              <li key={lineId}>
                <strong>{lineLabel(lineId, geometry)}</strong>
                {' · '}{crossings.length} {crossings.length === 1 ? 'crossing' : 'crossings'}
                {bounded(crossings, crossingBudget, (some) => crossingItems(lineId, some), ['crossing', 'crossings'])}
              </li>
            ))}
          </ul>
        ),
    });

    if (analytics.motion) {
      const motion = analytics.motion;
      items.push({
        label: 'Heading',
        // An image direction, never a compass bearing: the camera's "up" is not
        // north, and saying north would be a claim about the world.
        value: motion.heading === 'None'
          ? 'No discernible direction'
          : `${motionDirectionLabel(motion.heading)} (image direction)`,
      });
      items.push({
        label: 'Stationary',
        value: motion.longestStationaryMs === 0
          ? 'Never stationary'
          : `${formatDuration(motion.longestStationaryMs)} longest`
            + ` · ${formatDuration(motion.totalStationaryMs)} total`
            // Only when the intervals are actually there. A summary reporting a
            // longest stationary period beside "0 intervals" contradicts
            // itself, and the operator cannot tell which half to believe.
            + (motion.stationaryIntervals.length > 0
              ? ` · ${motion.stationaryIntervals.length}`
                + ` ${motion.stationaryIntervals.length === 1 ? 'interval' : 'intervals'}`
              : ''),
      });
    }
  }

  if (analytics.otherIdentities.length > 0) {
    items.push({
      label: 'Also analysed',
      // Context, not a substitute: the facts above belong to the identity this
      // review was opened against, and these are merely other answers that
      // exist for the same Track.
      value: analytics.otherIdentities
        .map((other) => `Revision ${other.sceneRevisionNumber} · ${engineLabel(other.algorithmVersion)}`)
        .join(', '),
    });
  }

  return (
    <section className="analytics-summary" aria-label="Scene analytics">
      {/* Review's rail panel already carries this title; the inspector has no
          host panel, so the summary names itself there. */}
      {compact ? <h3 className="analytics-summary__title">Scene analytics</h3> : null}

      {STATUS_EXPLANATION[analytics.status] ? (
        <p className="analytics-summary__state">{STATUS_EXPLANATION[analytics.status]}</p>
      ) : null}

      {/* Geometry problems are their own state. The facts stay; the outlines do
          not, and saying which is which is the whole point. */}
      {scene?.status === 'loading' ? (
        <p className="analytics-summary__state">
          Loading scene revision {scene.revisionNumber} so the geometry can be drawn.
        </p>
      ) : null}
      {scene?.status === 'unavailable' ? (
        <Alert
          tone="warning"
          actions={scene.retry ? <Button size="sm" onClick={scene.retry}>Retry scene revision</Button> : undefined}
        >
          {scene.reason === 'identity-mismatch'
            ? `The scene revision returned for revision ${scene.revisionNumber} is not the one these facts were measured against, so no zone or line geometry is drawn. The facts below are unaffected.`
            : `Scene revision ${scene.revisionNumber} could not be loaded, so no zone or line geometry is drawn. The facts below are unaffected, and geometry is named by its identifier.`}
        </Alert>
      ) : null}
      {scene?.status === 'incomplete-identity' ? (
        <Alert tone="warning">
          These facts do not name a complete scene revision, so the geometry they
          were measured against cannot be identified and none is drawn.
        </Alert>
      ) : null}

      <KeyValue items={items} />

      {/* Engineering diagnostics: useful when a fact looks wrong, not headline
          operator copy, so they stay closed. */}
      {analytics.sampleCount !== null ? (
        <details className="disclosure">
          <summary>Measurement detail</summary>
          <div className="disclosure__body">
            <KeyValue items={[
              { label: 'Samples', value: String(analytics.sampleCount) },
              { label: 'Gaps', value: `${analytics.gapCount ?? 0} · ${formatDuration(analytics.gapTotalMs ?? 0)} total` },
              ...(analytics.motion ? [
                { label: 'Path length', value: analytics.motion.pathLengthNormalised.toFixed(4) + ' (normalised)' },
                { label: 'Mean rate', value: analytics.motion.meanDisplacementRate.toFixed(4) + ' per second (normalised)' },
              ] : []),
              ...(analytics.sceneRevisionId ? [
                { label: 'Revision id', value: analytics.sceneRevisionId, mono: true },
              ] : []),
            ]} />
          </div>
        </details>
      ) : analytics.sceneRevisionId ? (
        <details className="disclosure">
          <summary>Measurement detail</summary>
          <div className="disclosure__body">
            <KeyValue items={[{ label: 'Revision id', value: analytics.sceneRevisionId, mono: true }]} />
          </div>
        </details>
      ) : null}

    </section>
  );
}
