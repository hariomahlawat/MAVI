import type { Tone } from '../status/status';

export function clampPercent(value: number | null | undefined): number {
  if (value === null || value === undefined || !Number.isFinite(value)) return 0;
  return Math.min(100, Math.max(0, value));
}

export function formatPercent(value: number): string {
  return value.toFixed(value % 1 === 0 ? 0 : 1) + '%';
}

export default function Progress({
  value,
  tone = 'info',
  label,
  inline = false,
}: {
  value: number | null | undefined;
  tone?: Tone;
  label?: string;
  inline?: boolean;
}) {
  const percent = clampPercent(value);
  const fillClass = tone === 'err' ? 'progress__fill progress__fill--err'
    : tone === 'ok' ? 'progress__fill progress__fill--ok'
      : 'progress__fill';
  return (
    <div className={inline ? 'progress progress--inline' : 'progress'}>
      {label !== undefined ? (
        <div className="progress__label"><span>{label}</span><strong>{formatPercent(percent)}</strong></div>
      ) : null}
      <div
        className="progress__bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
        aria-label={label ?? 'Progress'}
      >
        <div className={fillClass} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
