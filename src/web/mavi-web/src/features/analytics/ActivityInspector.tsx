import type { AnalyticsAggregateResponse } from '../../api/analytics';
import KeyValue from '../../shared/components/KeyValue';
import Panel from '../../shared/components/Panel';
import { formatCount } from '../../shared/format/format';
import { formatDateTime } from '../../shared/time/time';
import { engineLabel, shortId } from '../../shared/evidence/analyticsLabels';
import CoverageStrip from '../../shared/evidence/CoverageStrip';
import { METRICS, type ActivityReading } from './analyticsState';

/**
 * What the selected metric means and what it totalled over the window.
 *
 * The counting definition is shown, not linked or hidden behind a tooltip: the
 * difference between "entries" and "distinct Tracks" changes what an operator
 * concludes, and every metric here has at least one plausible wrong reading.
 * Where a figure is not additive the inspector says so in the same breath,
 * because the next thing a reader does with a column of numbers is add it up.
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
    <>
      {reading && descriptor ? (
        <Panel title={descriptor.label} description={reading.subjectLabel ?? undefined}>
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
          {/*
            The tag is the cue; the definition is the reason. Repeating the
            reason as a second paragraph would only teach a reader to skip both.
          */}
          {!descriptor.additive ? <p className="analytics-inspector__caution">Not additive</p> : null}
          <p className="analytics-inspector__definition">{descriptor.definition}</p>
        </Panel>
      ) : null}

      <Panel title="Provenance">
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
      </Panel>

      <CoverageStrip coverage={response.coverage} scopeNoun="time window" />
    </>
  );
}
