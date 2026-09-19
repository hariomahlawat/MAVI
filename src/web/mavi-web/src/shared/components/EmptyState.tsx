import type { ReactNode } from 'react';
import Icon, { type IconName } from './Icon';

export default function EmptyState({
  icon,
  title,
  children,
  actions,
  compact = false,
}: {
  icon?: IconName;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`empty${compact ? ' empty--compact' : ''}`} role="status">
      {icon ? <Icon name={icon} size="lg" /> : null}
      <strong>{title}</strong>
      {children ? <span>{children}</span> : null}
      {actions ? <div className="empty__actions">{actions}</div> : null}
    </div>
  );
}
