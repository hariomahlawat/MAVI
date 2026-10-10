import type { ReactNode } from 'react';
import Icon, { type IconName } from './Icon';
import { statusText, useStatusReport } from './StatusSlot';

/**
 * Tones follow the operational-state taxonomy (section 8.2, section 14).
 * `stale` is the warning hue desaturated and dashed, so the state is legible
 * without relying on colour.
 */
type Tone = 'info' | 'error' | 'success' | 'warning' | 'stale';

const icons: Record<Tone, IconName> = {
  info: 'info',
  error: 'alert',
  success: 'check',
  warning: 'alert',
  stale: 'alert',
};

export default function Alert({
  tone = 'info',
  children,
  actions,
  announce = true,
}: {
  tone?: Tone;
  children: ReactNode;
  /** A retry or reload belongs beside the sentence explaining it (section 15). */
  actions?: ReactNode;
  /**
   * Whether the sentence is said by a live region at all. A caller that has
   * already announced the cause passes false; nothing is said twice.
   */
  announce?: boolean;
}) {
  // A failure is assertive and announces on insertion by definition. A
  // polite tone is routed to the enclosing StatusSlot's announcer, which was
  // mounted before this alert appeared, so the sentence is a change there; only
  // an alert outside any slot carries `role="status"` itself.
  const assertive = tone === 'error';
  const routed = useStatusReport(statusText(children), announce && !assertive);
  const role = !announce ? undefined : assertive ? 'alert' : routed ? undefined : 'status';
  return (
    <div className={`alert alert--${tone}`} role={role}>
      <Icon name={icons[tone]} />
      <div className="alert__body">{children}</div>
      {actions ? <div className="alert__actions">{actions}</div> : null}
    </div>
  );
}
