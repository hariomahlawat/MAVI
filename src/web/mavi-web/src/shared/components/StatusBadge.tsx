import { labelForStatus, toneForStatus, type Tone } from '../status/status';

type StatusBadgeProps = {
  /** A raw API status string; tone and label are derived centrally. */
  status?: string | null;
  /** Or an explicit tone + text for non-status uses (counts, classes). */
  tone?: Tone;
  children?: string;
  plain?: boolean;
  title?: string;
};

export default function StatusBadge({ status, tone, children, plain = false, title }: StatusBadgeProps) {
  const resolvedTone = tone ?? toneForStatus(status);
  const text = children ?? labelForStatus(status);
  return (
    <span
      className={`badge badge--${resolvedTone}${plain ? ' badge--plain' : ''}`}
      title={title}
      data-status={status ?? undefined}
    >
      {text}
    </span>
  );
}
