import { useEffect, useId, useState } from 'react';
import { BUCKET_SECONDS } from '../../api/analytics';
import type { TrackObjectClass } from '../../api/tracks';
import Button from '../../shared/components/Button';
import { configuredUtcToWallTime, configuredWallTimeToUtc } from '../../shared/time/wallTime';
import { Toolbar } from '../../shared/workspace';
import {
  WINDOW_PRESETS,
  type AnalyticsQueryState,
  type WindowPresetId,
} from './analyticsState';

/**
 * The analytical window as a toolbar band (§10, F22): which window, how finely,
 * and about which class — one 32px row of controls, not a form above a chart.
 *
 * Times are edited in the configured display zone and held as UTC, as every
 * other time field in the product is: the operator reasons in local wall time
 * and the wire never sees anything else. The zone itself is stated once, in the
 * Context Bar (§24), not under each field.
 *
 * The edited text is held here rather than converted on every keystroke.
 * Half-typed input is not a wall time, and a zone conversion of one either
 * throws or — worse — succeeds against something the operator did not mean, so
 * the committed UTC value only moves when the text is a whole, unambiguous
 * instant. A value that cannot be interpreted is reported for its own field and
 * the previous window stands until it is fixed.
 *
 * Without a configured display zone there is no safe conversion at all, so the
 * time fields are disabled and say why rather than silently assuming UTC.
 *
 * It decides nothing about whether the question may be asked: the refusals it
 * states are the page's (`queryProblem`, split into the window's and the
 * interval's), so the band and the request gate cannot disagree.
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
  windowProblem,
  bucketProblem,
  onChange,
  onPreset,
}: {
  state: AnalyticsQueryState;
  /** Null while the configured zone is unknown or unavailable. */
  displayTimeZoneId: string | null;
  /** The page's refusal of the window itself, owned by the To field. */
  windowProblem: string | null;
  /** The page's refusal of the interval (Activity only), owned by the Interval field. */
  bucketProblem: string | null;
  onChange: (patch: Partial<AnalyticsQueryState>) => void;
  onPreset: (preset: WindowPresetId) => void;
}) {
  const id = useId();
  const ids = { from: `${id}-from`, to: `${id}-to`, interval: `${id}-interval`, objectClass: `${id}-class`, problem: `${id}-problem` };
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

  const activity = state.mode === 'activity';
  const zoneMissing = displayTimeZoneId ? null : 'The display timezone is unavailable, so these times cannot be edited safely.';
  // One statement of what has to change, in the band it belongs to, named for
  // the field that repairs it — and that field carries it as its description.
  const owner: 'from' | 'to' | 'interval' | null = errors.from ? 'from'
    : errors.to || windowProblem ? 'to'
      : activity && bucketProblem ? 'interval'
        : null;
  const message = zoneMissing ?? errors.from ?? errors.to ?? windowProblem ?? (activity ? bucketProblem : null);
  const describe = (field: 'from' | 'to' | 'interval') => (owner === field || (zoneMissing && field !== 'interval') ? ids.problem : undefined);

  return (
    <Toolbar
      label="Analytics window"
      hint={message ? <span id={ids.problem} className="analytics-window__problem">{message}</span> : undefined}
    >
      <div className="analytics-window__presets" role="group" aria-label="Window presets">
        {WINDOW_PRESETS.map((preset) => (
          <Button key={preset.id} size="sm" variant="ghost" onClick={() => onPreset(preset.id)}>
            {preset.label}
          </Button>
        ))}
      </div>

      <label className="analytics-window__label" htmlFor={ids.from}>From</label>
      <input
        id={ids.from}
        type="datetime-local"
        disabled={!displayTimeZoneId}
        value={draft.from}
        aria-invalid={owner === 'from' || undefined}
        aria-describedby={describe('from')}
        onChange={(event) => edit('from', event.target.value)}
      />
      <label className="analytics-window__label" htmlFor={ids.to}>To</label>
      <input
        id={ids.to}
        type="datetime-local"
        disabled={!displayTimeZoneId}
        value={draft.to}
        aria-invalid={owner === 'to' || undefined}
        aria-describedby={describe('to')}
        onChange={(event) => edit('to', event.target.value)}
      />

      {/* The interval is Activity's axis; the heatmap has none, so it is not offered there. */}
      {activity ? (
        <>
          <label className="visually-hidden" htmlFor={ids.interval}>Interval</label>
          <select
            id={ids.interval}
            value={state.bucketSeconds}
            aria-invalid={owner === 'interval' || undefined}
            aria-describedby={describe('interval')}
            onChange={(event) => onChange({ bucketSeconds: Number(event.target.value) as AnalyticsQueryState['bucketSeconds'] })}
          >
            {BUCKET_SECONDS.map((seconds) => (
              <option key={seconds} value={seconds}>{`${bucketLabels[seconds] ?? `${seconds}s`} buckets`}</option>
            ))}
          </select>
        </>
      ) : null}

      <label className="visually-hidden" htmlFor={ids.objectClass}>Object class</label>
      <select
        id={ids.objectClass}
        value={state.objectClass ?? ''}
        onChange={(event) => onChange({ objectClass: (event.target.value || null) as TrackObjectClass | null })}
      >
        <option value="">All classes</option>
        <option value="Person">Person</option>
        <option value="Vehicle">Vehicle</option>
      </select>
    </Toolbar>
  );
}
