import type { AnalyticsHeatmapResponse } from '../../api/analytics';
import KeyValue from '../../shared/components/KeyValue';
import Panel from '../../shared/components/Panel';
import { formatCount } from '../../shared/format/format';
import { formatDateTime } from '../../shared/time/time';
import { engineLabel, shortId } from '../../shared/evidence/analyticsLabels';
import CoverageStrip from '../../shared/evidence/CoverageStrip';

/**
 * What the map is, and — just as importantly — what it is not.
 *
 * The wording is required to say "trajectory sample density" and to refuse the
 * two readings an operator will otherwise reach for. It is not people density:
 * one Track that loitered leaves far more samples than five that walked
 * through. And it is not probability: nothing here predicts anything.
 */
export default function HeatmapInspector({
  response,
  displayTimeZoneId,
}: {
  response: AnalyticsHeatmapResponse;
  displayTimeZoneId: string;
}) {
  return (
    <>
      <Panel title="Density map">
        <KeyValue
          items={[
            { label: 'Trajectory samples', value: formatCount(response.sampleCount) },
            { label: 'Contributing Tracks', value: formatCount(response.trackCount) },
            { label: 'Grid', value: `${response.gridWidth} × ${response.gridHeight}` },
            { label: 'Busiest cell', value: `${formatCount(response.maxCellValue)} samples` },
          ]}
        />
        <p className="analytics-inspector__definition">
          This is <strong>trajectory sample density</strong>: how many recorded track positions fell in each
          cell of the frame. It is not people density — one Track that stayed put leaves far more samples
          than several that passed through — and it is not a probability or a prediction.
        </p>
      </Panel>

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
            {
              label: 'Window',
              value: `${formatDateTime(response.fromUtc, displayTimeZoneId)} — ${formatDateTime(response.toUtc, displayTimeZoneId)}`,
            },
            ...(response.objectClass ? [{ label: 'Object class', value: response.objectClass }] : []),
            ...(response.processingRunId
              ? [{ label: 'Processing run', value: shortId(response.processingRunId), mono: true }]
              : []),
          ]}
        />
      </Panel>

      <CoverageStrip coverage={response.coverage} scopeNoun="time window" />
    </>
  );
}
