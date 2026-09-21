import type { TrackDetailAnalytics } from '../../api/tracks';
import KeyValue, { type KeyValueItem } from '../../shared/components/KeyValue';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp } from '../../shared/format/format';
import {
  crossingDirectionLabel,
  engineLabel,
  lineLabel,
  motionDirectionLabel,
  zoneLabel,
  type GeometryNames,
} from './analyticsLabels';

/**
 * The analytics facts for one Track and one identity, as a summary (plan §S:
 * "Slice 4 exposes these typed facts through the API and inspector summary
 * only; Slice 5 owns geometry drawing, timeline lanes and seek-to-evidence").
 *
 * The identity is stated first, because the same Track has different facts
 * under different revisions and an operator reading a dwell must know which
 * geometry it was measured against. A Track that was not analysed says so in
 * the readiness words the Processing surfaces already use — no fourth state
 * vocabulary — and a Track whose evidence could not be read says that rather
 * than showing nothing.
 */
const STATUS_WORDS: Record<TrackDetailAnalytics['status'], string> = {
  Analysed: 'Analysed',
  Unavailable: 'Evidence could not be analysed',
  Pending: 'Not analysed yet',
  Failed: 'Analysis failed for this run',
  Stale: 'Analysed with an earlier revision or engine',
  NotConfigured: 'No scene configured for this camera',
  Disabled: 'Analytics disabled by the scene revision',
};

export default function TrackAnalyticsSummary({
  analytics,
  geometry,
  displayTimeZoneId,
}: {
  analytics: TrackDetailAnalytics;
  geometry?: GeometryNames;
  displayTimeZoneId?: string;
}) {
  const identity = analytics.sceneRevisionId === null
    ? 'No scene revision'
    : `Revision ${analytics.sceneRevisionNumber ?? '?'} · ${engineLabel(analytics.algorithmVersion)}`;

  const items: KeyValueItem[] = [
    { label: 'Status', value: STATUS_WORDS[analytics.status] },
    { label: 'Identity', value: identity },
  ];

  if (analytics.status === 'Unavailable' && analytics.unavailableReason) {
    items.push({ label: 'Reason', value: analytics.unavailableReason, mono: true });
  }

  if (analytics.status === 'Analysed') {
    const visited = analytics.zoneSummaries.filter((summary) => summary.visitCount > 0);
    items.push({
      label: 'Zones',
      value: visited.length === 0
        ? 'No zone visited'
        : (
          <ul className="analytics-list">
            {visited.map((summary) => (
              <li key={summary.zoneId}>
                <strong>{zoneLabel(summary.zoneId, geometry)}</strong>
                {' · '}{summary.visitCount} {summary.visitCount === 1 ? 'visit' : 'visits'}
                {' · '}dwell {formatDuration(summary.totalDwellMs)}
                {summary.loitering ? <> · <span className="text-warn">Loitering</span></> : null}
              </li>
            ))}
          </ul>
        ),
    });

    const byLine = new Map<string, typeof analytics.lineCrossings>();
    for (const crossing of analytics.lineCrossings) {
      const list = byLine.get(crossing.lineId) ?? [];
      list.push(crossing);
      byLine.set(crossing.lineId, list);
    }
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
                {' · first '}{crossingDirectionLabel(crossings[0].direction, geometry?.lines.get(lineId.toLowerCase()))}
                {' at '}{displayTimestamp(crossings[0].timestampUtc, displayTimeZoneId)}
              </li>
            ))}
          </ul>
        ),
    });

    if (analytics.motion) {
      items.push({ label: 'Heading', value: analytics.motion.heading === 'None' ? 'No discernible direction' : motionDirectionLabel(analytics.motion.heading) });
      items.push({
        label: 'Stationary',
        value: analytics.motion.longestStationaryMs === 0
          ? 'Never stationary'
          : `${formatDuration(analytics.motion.longestStationaryMs)} longest · ${formatDuration(analytics.motion.totalStationaryMs)} total`,
      });
    }
  }

  if (analytics.otherIdentities.length > 0) {
    items.push({
      label: 'Also analysed',
      value: analytics.otherIdentities
        .map((other) => `Revision ${other.sceneRevisionNumber} · ${engineLabel(other.algorithmVersion)}`)
        .join(', '),
    });
  }

  return (
    <section className="analytics-summary" aria-label="Scene analytics">
      <h3 className="analytics-summary__title">Scene analytics</h3>
      <KeyValue items={items} />
    </section>
  );
}
