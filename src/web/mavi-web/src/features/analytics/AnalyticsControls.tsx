import { useEffect, useState } from 'react';
import { BUCKET_SECONDS } from '../../api/analytics';
import type { TrackObjectClass } from '../../api/tracks';
import Button from '../../shared/components/Button';
import Field from '../../shared/components/Field';
import { configuredUtcToWallTime, configuredWallTimeToUtc } from '../../shared/time/wallTime';
import {
  ACTIVITY_METRICS,
  METRICS,
  WINDOW_PRESETS,
  type ActivityMetric,
  type AnalyticsQueryState,
  type WindowPresetId,
} from './analyticsState';

/**
 * The common controls: which window, how finely, and about what.
 *
 * Times are edited in the configured display zone and held as UTC, as every
 * other time field in the product is: the operator reasons in local wall time
 * and the wire never sees anything else.
 *
 * The edited text is held here rather than converted on every keystroke.
 * Half-typed input is not a wall time, and a zone conversion of one either
 * throws or — worse — succeeds against something the operator did not mean, so
 * the committed UTC value only moves when the text is a whole, unambiguous
 * instant. A value that cannot be interpreted is reported on its own field and
 * the previous window stands until it is fixed.
 *
 * Without a configured display zone there is no safe conversion at all, so the
 * time fields are disabled and say why rather than silently assuming UTC.
 */

const bucketLabels: Record<number, string> = {
  60: '1 minute',
  300: '5 minutes',
  900: '15 minutes',
  3_600: '1 hour',
  21_600: '6 hours',
  86_400: '1 day',
};

export default function AnalyticsControls({
  state,
  displayTimeZoneId,
  problem,
  refreshing,
  onChange,
  onPreset,
  onRefresh,
}: {
  state: AnalyticsQueryState;
  /** Null while the configured zone is unknown or unavailable. */
  displayTimeZoneId: string | null;
  problem: string | null;
  refreshing: boolean;
  onChange: (patch: Partial<AnalyticsQueryState>) => void;
  onPreset: (preset: WindowPresetId) => void;
  onRefresh: () => void;
}) {
  const [draft, setDraft] = useState<{ from: string; to: string }>({ from: '', to: '' });
  const [errors, setErrors] = useState<{ from: string | null; to: string | null }>({ from: null, to: null });

  // The committed window is the source of truth: a preset, or a first load,
  // replaces whatever was being typed, because the operator asked for it.
  useEffect(() => {
    if (!displayTimeZoneId) return;
    setDraft({
      from: configuredUtcToWallTime(state.fromUtc, displayTimeZoneId),
      to: configuredUtcToWallTime(state.toUtc, displayTimeZoneId),
    });
    setErrors({ from: null, to: null });
  }, [state.fromUtc, state.toUtc, displayTimeZoneId]);

  const edit = (bound: 'from' | 'to', value: string) => {
    setDraft((current) => ({ ...current, [bound]: value }));
    if (!displayTimeZoneId) return;
    try {
      const utc = configuredWallTimeToUtc(value, displayTimeZoneId);
      setErrors((current) => ({ ...current, [bound]: null }));
      onChange(bound === 'from' ? { fromUtc: utc } : { toUtc: utc });
    } catch (error) {
      setErrors((current) => ({
        ...current,
        [bound]: error instanceof RangeError
          ? error.message
          : 'This time could not be interpreted in the display timezone.',
      }));
    }
  };

  const zoneHelp = displayTimeZoneId ?? 'Display timezone unavailable';
  const zoneMissing = 'The display timezone is unavailable, so these times cannot be edited safely.';

  return (
    <div className="analytics-controls">
      <div className="analytics-controls__presets" role="group" aria-label="Window presets">
        {WINDOW_PRESETS.map((preset) => (
          <Button key={preset.id} size="sm" variant="ghost" onClick={() => onPreset(preset.id)}>
            {preset.label}
          </Button>
        ))}
      </div>

      <Field label="From" help={zoneHelp} error={errors.from ?? (displayTimeZoneId ? null : zoneMissing)}>
        {(control) => (
          <input
            {...control}
            type="datetime-local"
            disabled={!displayTimeZoneId}
            value={draft.from}
            onChange={(event) => edit('from', event.target.value)}
          />
        )}
      </Field>

      <Field label="To" help={zoneHelp} error={errors.to ?? problem}>
        {(control) => (
          <input
            {...control}
            type="datetime-local"
            disabled={!displayTimeZoneId}
            value={draft.to}
            onChange={(event) => edit('to', event.target.value)}
          />
        )}
      </Field>

      <Field label="Interval">
        {(control) => (
          <select
            {...control}
            value={state.bucketSeconds}
            onChange={(event) => onChange({ bucketSeconds: Number(event.target.value) as AnalyticsQueryState['bucketSeconds'] })}
          >
            {BUCKET_SECONDS.map((seconds) => (
              <option key={seconds} value={seconds}>{bucketLabels[seconds] ?? `${seconds}s`}</option>
            ))}
          </select>
        )}
      </Field>

      <Field label="Object class" optional>
        {(control) => (
          <select
            {...control}
            value={state.objectClass ?? ''}
            onChange={(event) => onChange({ objectClass: (event.target.value || null) as TrackObjectClass | null })}
          >
            <option value="">All classes</option>
            <option value="Person">Person</option>
            <option value="Vehicle">Vehicle</option>
          </select>
        )}
      </Field>

      {state.mode === 'activity' ? (
        <Field label="Metric">
          {(control) => (
            <select
              {...control}
              value={state.metric}
              onChange={(event) => onChange({ metric: event.target.value as ActivityMetric })}
            >
              {ACTIVITY_METRICS.map((metric) => (
                <option key={metric} value={metric}>{METRICS[metric].label}</option>
              ))}
            </select>
          )}
        </Field>
      ) : null}

      <Button size="sm" variant="ghost" icon="refresh" onClick={onRefresh} disabled={refreshing}>
        {refreshing ? 'Refreshing…' : 'Refresh'}
      </Button>
    </div>
  );
}
