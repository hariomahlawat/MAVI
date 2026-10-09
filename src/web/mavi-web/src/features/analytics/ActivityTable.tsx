import { compactTimestamp, formatCount } from '../../shared/format/format';
import { METRICS, type ActivityReading } from './analyticsState';

/**
 * The chart's semantic twin: every bucket's start and value, in a real table.
 *
 * It is the accessible form of a plot that is deliberately hidden from
 * assistive technology, and it is also simply the readable form for anyone who
 * wants the numbers. It sits in the inspector because the inspector body is the
 * Workbench's only scroll owner (§4.3.2) and a bucket list is unbounded.
 */
export default function ActivityTable({
  reading,
  displayTimeZoneId,
}: {
  reading: ActivityReading;
  displayTimeZoneId: string;
}) {
  const rows = reading.series[0]?.points ?? [];
  if (rows.length === 0) return null;

  return (
    <table className="table analytics-table">
      <caption className="visually-hidden">
        {METRICS[reading.metric].label}
        {reading.subjectLabel ? ` for ${reading.subjectLabel}` : ''} by bucket. {reading.definition}
      </caption>
      <thead>
        <tr>
          <th scope="col">Bucket start</th>
          {reading.series.map((series) => (
            <th key={series.label} scope="col" className="num">{series.label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((point, index) => (
          <tr key={point.startUtc}>
            {/* The compact table form of §24: every bucket starts on a whole
                minute, so the seconds say nothing, and the current year is the
                least informative part of a column of today's buckets. */}
            <th scope="row">{compactTimestamp(point.startUtc, displayTimeZoneId)}</th>
            {reading.series.map((series) => (
              <td key={series.label} className="num">{formatCount(series.points[index]?.value ?? 0)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
