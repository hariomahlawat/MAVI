import { useId } from 'react';
import type { AnalyticsHeatmapResponse } from '../../api/analytics';
import { formatCount } from '../../shared/format/format';

/**
 * The density map, composited in source-frame coordinates over a neutral matte.
 *
 * Every cell is a rectangle whose fill is one of five steps of the decision-2c
 * scale, chosen by the cell's share of the largest cell in this answer. The
 * matrix is drawn, never animated and never smoothed: a blurred or interpolated
 * map would show density between two cells that nothing was measured in.
 *
 * The SVG is hidden from assistive technology. Plan §11 forbids enumerating the
 * cells one by one — a 128×72 grid is 9,216 nodes saying nothing — so the
 * accessible form is the summary beside it, which names the grid, the samples,
 * the contributing Tracks, the largest cell and where in the frame it is.
 */

const STEPS = 5;

export default function HeatmapStage({
  response,
  opacity,
  onOpacityChange,
}: {
  response: AnalyticsHeatmapResponse;
  opacity: number;
  onOpacityChange: (value: number) => void;
}) {
  const summaryId = useId();
  const opacityId = useId();
  const { gridWidth, gridHeight, values, maxCellValue } = response;

  // The brightest cell in this answer anchors the scale, so a quiet window is
  // still readable. The legend says what the ends mean, in counts, precisely
  // because the scale is relative and would otherwise imply an absolute one.
  const step = (value: number) => {
    if (value <= 0) return -1;
    if (maxCellValue <= 0) return 0;
    return Math.min(STEPS - 1, Math.floor(((value / maxCellValue) * STEPS)));
  };

  const peak = peakCell(values, gridWidth, gridHeight, maxCellValue);

  return (
    <div className="heatmap">
      <div className="heatmap__frame">
        <svg
          className="heatmap__matrix"
          viewBox={`0 0 ${gridWidth} ${gridHeight}`}
          preserveAspectRatio="xMidYMid meet"
          role="presentation"
          aria-hidden="true"
          focusable="false"
          style={{ opacity }}
        >
          {values.map((value, index) => {
            const level = step(value);
            if (level < 0) return null;
            return (
              <rect
                key={index}
                className={`heatmap__cell heatmap__cell--${level}`}
                x={index % gridWidth}
                y={Math.floor(index / gridWidth)}
                width={1}
                height={1}
              />
            );
          })}
        </svg>
      </div>

      <div className="heatmap__controls">
        <label htmlFor={opacityId}>Opacity</label>
        <input
          id={opacityId}
          type="range"
          min={20}
          max={100}
          step={5}
          value={Math.round(opacity * 100)}
          onChange={(event) => onOpacityChange(Number(event.target.value) / 100)}
        />
        <output htmlFor={opacityId}>{Math.round(opacity * 100)}%</output>

        <ul className="heatmap__legend">
          {/*
            Numeric endpoints, not a colour bar alone: the scale is relative to
            this answer's busiest cell, and without the counts a reader would
            take the top of it for an absolute quantity.
          */}
          <li className="heatmap__legend-end">0 samples</li>
          {Array.from({ length: STEPS }, (_, level) => (
            <li key={level} className={`heatmap__swatch heatmap__swatch--${level}`} aria-hidden="true" />
          ))}
          <li className="heatmap__legend-end">{formatCount(maxCellValue)} samples</li>
        </ul>
      </div>

      <p className="heatmap__summary" id={summaryId} role="region" aria-label="Heatmap summary">
        Trajectory sample density over a {gridWidth} by {gridHeight} grid:{' '}
        {formatCount(response.sampleCount)} samples from {formatCount(response.trackCount)}{' '}
        {response.trackCount === 1 ? 'Track' : 'Tracks'}.{' '}
        {maxCellValue > 0 && peak
          ? `The busiest cell holds ${formatCount(maxCellValue)} samples, ${peak}.`
          : 'No samples fell inside this window.'}
      </p>
    </div>
  );
}

/** Where the busiest cell sits, in words rather than in grid indices. */
function peakCell(values: number[], width: number, height: number, maximum: number): string | null {
  if (maximum <= 0) return null;
  const index = values.indexOf(maximum);
  if (index < 0) return null;

  const column = index % width;
  const row = Math.floor(index / width);
  const horizontal = column < width / 3 ? 'left' : column < (width * 2) / 3 ? 'centre' : 'right';
  const vertical = row < height / 3 ? 'upper' : row < (height * 2) / 3 ? 'middle' : 'lower';
  return `${vertical} ${horizontal} of the frame`;
}
