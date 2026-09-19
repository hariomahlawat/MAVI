import type { ReactNode } from 'react';
import Icon, { type IconName } from './Icon';

type Tone = 'info' | 'error' | 'success' | 'warning';

const icons: Record<Tone, IconName> = {
  info: 'info',
  error: 'alert',
  success: 'check',
  warning: 'alert',
};

type AlertProps = {
  tone?: Tone;
  children: ReactNode;
};

export default function Alert({ tone = 'info', children }: AlertProps) {
  return (
    <div className={`alert alert--${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <Icon name={icons[tone]} />
      <div className="alert__body">{children}</div>
    </div>
  );
}
