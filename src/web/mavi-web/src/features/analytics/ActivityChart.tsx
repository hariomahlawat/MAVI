import { useId } from 'react';
import { formatCount } from '../../shared/format/format';
import { formatDateTime } from '../../shared/time/time';
import { METRICS, readingMaximum, type ActivityReading } from './analyticsState';

/**
 * The bucketed series, as bars, with a semantic twin beside it.
 *
 * Drawn with plain SVG rather than a charting library: the shapes are bars over
 * a linear axis, and a dependency that draws them would also bring its own
 * colours, tooltips and accessibility model into a surface whose wording and
 * state grammar are specified.
 *
 * The chart itself is `aria-hidden`. Section 11 of the plan is explicit that
 * hundreds of SVG rectangles must not be exposed as individual nodes; what
 * assistive technology gets instead is `ActivityTable`, which carries the same
 * numbers against their bucket start times and is the authoritative reading
 * either way.
 *
 * That table lives in the inspector rather than under the chart, and not for
 * taste: §4.3.2 gives the Workbench one scroll owner, the inspector body, and a
 * stage that grows but never scrolls. An arbitrarily long table under the chart
 * made the stage a second scroll owner, which the §26 harness catches.
 */

const VIEW_WIDTH = 1_000;
const VIEW_HEIGHT = 260;
const GUTTER_LEFT = 8;
const GUTTER_BOTTOM = 22;

export default function ActivityChart({
  reading,
  displayTimeZoneId,
}: {
  reading: ActivityReading;
  displayTimeZoneId: string;
}) {
  const captionId = useId();
  const maximum = readingMaximum(reading);
  const bucketCount = reading.series[0]?.points.length ?? 0;
  if (bucketCount === 0) return null;

  // An all-zero series is a real answer and must still draw an axis rather than
  // dividing by nothing: the baseline is the observation.
  const scale = maximum === 0 ? 0 : (VIEW_HEIGHT - GUTTER_BOTTOM) / maximum;
  const plotWidth = VIEW_WIDTH - GUTTER_LEFT * 2;
  const slot = plotWidth / bucketCount;
  const seriesCount = reading.series.length;
  const barWidth = Math.max((slot * 0.72) / seriesCount, 0.5);

  const first = reading.series[0].points[0];
  const last = reading.series[0].points[bucketCount - 1];

  return (
    <figure className="activity-chart" aria-labelledby={captionId}>
      <figcaption id={captionId} className="activity-chart__caption">
        {reading.subjectLabel ? <strong>{reading.subjectLabel}</strong> : null}
        <span className="faint">
          {formatDateTime(first.startUtc, displayTimeZoneId)} to {formatDateTime(last.endUtc, displayTimeZoneId)}
          {' · peak '}{formatCount(maximum)} {reading.unit}
        </span>
      </figcaption>

      <svg
        className="activity-chart__plot"
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        preserveAspectRatio="none"
        role="presentation"
        aria-hidden="true"
        focusable="false"
      >
        <line
          className="activity-chart__axis"
          x1={0}
          y1={VIEW_HEIGHT - GUTTER_BOTTOM}
          x2={VIEW_WIDTH}
          y2={VIEW_HEIGHT - GUTTER_BOTTOM}
        />
        {reading.series.map((series, seriesIndex) => (
          <g key={series.label} className={`activity-chart__series activity-chart__series--${seriesIndex + 1}`}>
            {series.points.map((point, index) => {
              const height = point.value * scale;
              return (
                <rect
                  key={point.startUtc}
                  x={GUTTER_LEFT + index * slot + seriesIndex * barWidth + (slot - barWidth * seriesCount) / 2}
                  y={VIEW_HEIGHT - GUTTER_BOTTOM - height}
                  width={barWidth}
                  height={height}
                />
              );
            })}
          </g>
        ))}
      </svg>

      <p className="visually-hidden">
        {reading.series.map((series) => `${series.label}: peak ${Math.max(...series.points.map((p) => p.value))} `
          + `${reading.unit} across ${bucketCount} buckets.`).join(' ')}
        {' '}The figures for each bucket are listed in the inspector.
      </p>

      {seriesCount > 1 ? (
        <ul className="activity-chart__legend">
          {reading.series.map((series, index) => (
            <li key={series.label}>
              <span className={`activity-chart__swatch activity-chart__swatch--${index + 1}`} aria-hidden="true" />
              {series.label}
            </li>
          ))}
        </ul>
      ) : null}

    </figure>
  );
}
