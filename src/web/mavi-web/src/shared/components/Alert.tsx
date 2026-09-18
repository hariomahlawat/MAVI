import type { ReactNode } from 'react';

type AlertProps = {
  tone?: 'info' | 'error' | 'success' | 'warning';
  children: ReactNode;
};

export default function Alert({ tone = 'info', children }: AlertProps) {
  return (
    <div className={`alert alert--${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  );
}
