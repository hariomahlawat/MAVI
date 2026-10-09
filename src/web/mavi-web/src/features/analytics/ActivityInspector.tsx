import type { AnalyticsAggregateResponse } from '../../api/analytics';
import KeyValue from '../../shared/components/KeyValue';
import { formatCount } from '../../shared/format/format';
import { formatDateTime } from '../../shared/time/time';
import { engineLabel, shortId } from '../../shared/evidence/analyticsLabels';
import CoverageStrip from '../../shared/evidence/CoverageStrip';
import ActivityTable from './ActivityTable';
import { revisionNames } from './HeatmapInspector';
import { METRICS, type ActivityReading } from './analyticsState';

/**
 * What the selected metric totalled over the window, how far to trust it, and
 * where it came from — in that order (§37.2, F23).
 *
 * One inspector, sections inside it rather than panels inside it (§11): the
 * Workbench inspector is the one contained surface, as the Scene Editor's is.
 *
 * Tier 1 is the figures and, beside them, the one qualification a reader acts
 * on before anything else — "Not additive", because the next thing anyone does
 * with a column of numbers is add it up. Tier 2 is the counting definition and
 * the coverage: the definition one disclosure away (its sentence is the
 * table's caption too), the coverage always in view, because it is the
 * difference between an observation and an absence of one. Tier 3 is the
 * provenance — revision, engine, window, bucket count — closed.
 */
export default function ActivityInspector({
  response,
  reading,
  displayTimeZoneId,
}: {
  response: AnalyticsAggregateResponse;
  reading: ActivityReading | null;
  displayTimeZoneId: string;
}) {
  const descriptor = reading ? METRICS[reading.metric] : null;

  return (
    <div className="analytics-inspector">
      {reading && descriptor ? (
        <section className="analytics-section" aria-label={descriptor.label}>
          <h3 className="analytics-section__title">
            {descriptor.label}
            {reading.subjectLabel ? <span className="analytics-section__subject">{reading.subjectLabel}</span> : null}
          </h3>
          <KeyValue
            items={reading.windowFigures.map((figure) => ({
              label: figure.label,
              value: figure.atUtc
                ? `${formatCount(figure.value)} — ${formatDateTime(figure.atUtc, displayTimeZoneId)}`
                : figure.value === 0 && figure.label.startsWith('Peak')
                  ? 'None'
                  : formatCount(figure.value),
            }))}
          />
          {!descriptor.additive ? <p className="analytics-inspector__caution">Not additive</p> : null}
          <details className="disclosure">
            <summary>How this is counted</summary>
            <p className="analytics-inspector__definition disclosure__body">{descriptor.definition}</p>
          </details>
        </section>
      ) : null}

      <CoverageStrip coverage={response.coverage} geometry={revisionNames(response.sceneRevisionNumber)} scopeNoun="time window" />

      <details className="disclosure">
        <summary>Provenance</summary>
        <div className="disclosure__body">
          <KeyValue
            items={[
              {
                label: 'Scene revision',
                value: response.sceneRevisionId === null
                  ? 'No scene configured'
                  : response.sceneRevisionNumber !== null
                    ? `Revision ${response.sceneRevisionNumber}`
                    : shortId(response.sceneRevisionId),
              },
              { label: 'Engine', value: engineLabel(response.algorithmVersion) },
              { label: 'Window', value: `${formatDateTime(response.fromUtc, displayTimeZoneId)} — ${formatDateTime(response.toUtc, displayTimeZoneId)}` },
              { label: 'Buckets', value: formatCount(response.buckets.length) },
              ...(response.objectClass ? [{ label: 'Object class', value: response.objectClass }] : []),
            ]}
          />
        </div>
      </details>

      {reading ? (
        <section className="analytics-section" aria-label="By bucket">
          <h3 className="analytics-section__title">By bucket</h3>
          <ActivityTable reading={reading} displayTimeZoneId={displayTimeZoneId} />
        </section>
      ) : null}
    </div>
  );
}
