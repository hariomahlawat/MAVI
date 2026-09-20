import type { ReactNode } from 'react';
import Icon, { type IconName } from './Icon';

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
}: {
  tone?: Tone;
  children: ReactNode;
  /** A retry or reload belongs beside the sentence explaining it (section 15). */
  actions?: ReactNode;
}) {
  return (
    <div className={`alert alert--${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <Icon name={icons[tone]} />
      <div className="alert__body">{children}</div>
      {actions ? <div className="alert__actions">{actions}</div> : null}
    </div>
  );
}
