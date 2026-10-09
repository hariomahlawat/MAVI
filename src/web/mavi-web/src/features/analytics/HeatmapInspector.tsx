import type { AnalyticsHeatmapResponse } from '../../api/analytics';
import KeyValue from '../../shared/components/KeyValue';
import { formatCount } from '../../shared/format/format';
import { formatDateTime } from '../../shared/time/time';
import { engineLabel, shortId, type GeometryNames } from '../../shared/evidence/analyticsLabels';
import CoverageStrip from '../../shared/evidence/CoverageStrip';

/**
 * The coverage strip's revision, by number: the response names it, so the
 * strip says "Revision 4" rather than a shortened identifier (F23, §37.2: the
 * identifier is forensic, and it is in Provenance).
 */
export function revisionNames(revisionNumber: number | null): GeometryNames {
  return { zones: new Map(), lines: new Map(), revisionNumber };
}

/**
 * What the map is, and — just as importantly — what it is not (§37.2, F23).
 *
 * Tier 1: the figures, and in one line beside them the two readings an
 * operator will otherwise reach for and must not — it is trajectory sample
 * density, not people density, and not a probability. Tier 2: why (one Track
 * that loitered leaves far more samples than five that walked through), one
 * disclosure away, and the coverage, in view. Tier 3: the provenance, closed.
 * Sections inside the one inspector, not panels inside it (§11).
 */
export default function HeatmapInspector({
  response,
  displayTimeZoneId,
}: {
  response: AnalyticsHeatmapResponse;
  displayTimeZoneId: string;
}) {
  return (
    <div className="analytics-inspector">
      <section className="analytics-section" aria-label="Density map">
        <h3 className="analytics-section__title">Density map</h3>
        <KeyValue
          items={[
            { label: 'Trajectory samples', value: formatCount(response.sampleCount) },
            { label: 'Contributing Tracks', value: formatCount(response.trackCount) },
            { label: 'Grid', value: `${response.gridWidth} × ${response.gridHeight}` },
            { label: 'Busiest cell', value: `${formatCount(response.maxCellValue)} samples` },
          ]}
        />
        <p className="analytics-inspector__caution">
          Trajectory sample density — not people density, and not a probability or a prediction.
        </p>
        <details className="disclosure">
          <summary>How this is counted</summary>
          <p className="analytics-inspector__definition disclosure__body">
            This is <strong>trajectory sample density</strong>: how many recorded track positions fell in each
            cell of the frame. One Track that stayed put leaves far more samples than several that passed
            through, so a bright cell is where positions were recorded, not where more people were.
          </p>
        </details>
      </section>

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
        </div>
      </details>
    </div>
  );
}
