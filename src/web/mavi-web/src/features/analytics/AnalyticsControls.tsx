import { useEffect, useId, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { BUCKET_SECONDS } from '../../api/analytics';
import type { TrackObjectClass } from '../../api/tracks';
import Button from '../../shared/components/Button';
import { configuredUtcToWallTimeText, configuredWallTimeToUtc, WALL_TIME_FORMAT } from '../../shared/time/wallTime';
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
 * and the wire never sees anything else. They are typed in the product's own
 * format (`WALL_TIME_FORMAT`), never a `datetime-local` control's, whose
 * rendering is the browser locale's to choose (§24: the browser's format must
 * not silently differ from the product's). §24 also asks for the format and
 * the operative zone next to a wall-time field: one compact note serves From
 * and To together and describes both. The Context Bar still states the zone
 * the surface's times are shown in, once; this note is the input's rule, not a
 * second disclosure row.
 *
 * The edited text is held here rather than converted on every keystroke.
 * Half-typed input is not a wall time, and a zone conversion of one either
 * throws or — worse — succeeds against something the operator did not mean, so
 * the committed UTC value only moves when the text is a whole, unambiguous
 * instant. A value that cannot be interpreted is reported for its own field and
 * the previous window stands until it is fixed — and while it stands, the page
 * refuses the query (cold review F2): the field's error is the page's state,
 * not the band's, so Refresh, a mode switch and the automatic fetch cannot ask
 * the previous window while the window on screen is invalid.
 *
 * Without a configured display zone there is no safe conversion at all, so the
 * time fields are disabled and say why rather than silently assuming UTC.
 *
 * It decides nothing about whether the question may be asked: the refusals it
 * states are the page's (`queryProblem`, split into the window's and the
 * interval's), so the band and the request gate cannot disagree.
 */

/** A From/To draft that is not a whole wall time, by field. Owned by the page. */
export type DraftErrors = { from: string | null; to: string | null };

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
  draftErrors: errors,
  onDraftErrors: setErrors,
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
  /** The drafts that are not wall times; the page refuses the query while any is set. */
  draftErrors: DraftErrors;
  onDraftErrors: Dispatch<SetStateAction<DraftErrors>>;
  onChange: (patch: Partial<AnalyticsQueryState>) => void;
  onPreset: (preset: WindowPresetId) => void;
}) {
  const id = useId();
  const ids = {
    from: `${id}-from`, to: `${id}-to`, interval: `${id}-interval`, objectClass: `${id}-class`,
    problem: `${id}-problem`, format: `${id}-format`,
  };
  const [draft, setDraft] = useState<{ from: string; to: string }>({ from: '', to: '' });
  // A preset re-reads the committed window even when it names the same one:
  // the operator asked for that window, so an invalid draft over it goes.
  const [presetsApplied, setPresetsApplied] = useState(0);

  // The committed window is the source of truth for a bound whose committed
  // value moved, and for both on a first load, a zone change or a preset (which
  // the operator asked for, even when it names the same window). A bound that
  // did not move keeps the operator's text, valid or not (§21). A draft that
  // already names its committed instant is kept as typed too: `12:00` commits
  // before its seconds are typed, and rewriting it to `12:00:00` under the
  // cursor would corrupt what follows.
  const synced = useRef<{ fromUtc: string; toUtc: string; zone: string; presets: number } | null>(null);
  useEffect(() => {
    if (!displayTimeZoneId) return;
    const last = synced.current;
    const forced = last === null || last.zone !== displayTimeZoneId || last.presets !== presetsApplied;
    const replaceFrom = forced || last.fromUtc !== state.fromUtc;
    const replaceTo = forced || last.toUtc !== state.toUtc;
    synced.current = { fromUtc: state.fromUtc, toUtc: state.toUtc, zone: displayTimeZoneId, presets: presetsApplied };
    const names = (text: string, utc: string) => {
      try {
        return Date.parse(configuredWallTimeToUtc(text, displayTimeZoneId)) === Date.parse(utc);
      } catch {
        return false;
      }
    };
    setDraft((current) => ({
      from: replaceFrom && !names(current.from, state.fromUtc)
        ? configuredUtcToWallTimeText(state.fromUtc, displayTimeZoneId) : current.from,
      to: replaceTo && !names(current.to, state.toUtc)
        ? configuredUtcToWallTimeText(state.toUtc, displayTimeZoneId) : current.to,
    }));
    // A replaced bound, or a kept one that names its instant, is valid.
    setErrors((current) => ({ from: replaceFrom ? null : current.from, to: replaceTo ? null : current.to }));
  }, [state.fromUtc, state.toUtc, displayTimeZoneId, presetsApplied, setErrors]);

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
  const describe = (field: 'from' | 'to' | 'interval') => {
    const problem = owner === field || (zoneMissing && field !== 'interval') ? ids.problem : null;
    const format = field === 'interval' ? null : ids.format;
    return [format, problem].filter(Boolean).join(' ') || undefined;
  };

  return (
    <Toolbar
      label="Analytics window"
      hint={message ? <span id={ids.problem} className="analytics-window__problem">{message}</span> : undefined}
    >
      <div className="analytics-window__presets" role="group" aria-label="Window presets">
        {WINDOW_PRESETS.map((preset) => (
          <Button
            key={preset.id}
            size="sm"
            variant="ghost"
            onClick={() => {
              setPresetsApplied((count) => count + 1);
              onPreset(preset.id);
            }}
          >
            {preset.label}
          </Button>
        ))}
      </div>

      <label className="analytics-window__label" htmlFor={ids.from}>From</label>
      <input
        id={ids.from}
        type="text"
        className="analytics-window__time"
        size={WALL_TIME_FORMAT.length}
        autoComplete="off"
        spellCheck={false}
        placeholder={WALL_TIME_FORMAT}
        disabled={!displayTimeZoneId}
        value={draft.from}
        aria-invalid={owner === 'from' || undefined}
        aria-describedby={describe('from')}
        onChange={(event) => edit('from', event.target.value)}
      />
      <label className="analytics-window__label" htmlFor={ids.to}>To</label>
      <input
        id={ids.to}
        type="text"
        className="analytics-window__time"
        size={WALL_TIME_FORMAT.length}
        autoComplete="off"
        spellCheck={false}
        placeholder={WALL_TIME_FORMAT}
        disabled={!displayTimeZoneId}
        value={draft.to}
        aria-invalid={owner === 'to' || undefined}
        aria-describedby={describe('to')}
        onChange={(event) => edit('to', event.target.value)}
      />
      {/* §24: the format and the operative zone beside the fields — once for
          both, and the description of both. Never a guessed zone. */}
      <span id={ids.format} className="analytics-window__format">
        <code>{WALL_TIME_FORMAT}</code>{' '}
        {displayTimeZoneId ? <span>in <code>{displayTimeZoneId}</code></span> : <span>timezone unavailable</span>}
      </span>

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
        className="analytics-window__class"
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
