import type { ReactNode } from 'react';
import Icon, { type IconName } from './Icon';

/**
 * "Nothing here" — never "we could not find out". A failed request renders an
 * Alert through the async boundary, not this component (section 14).
 *
 * `hatched` marks the not-configured and unavailable placeholders, which carry
 * a diagonal hatch so they are distinguishable from a plain empty result
 * without relying on the words alone.
 */
export default function EmptyState({
  icon,
  title,
  children,
  actions,
  compact = false,
  hatched = false,
}: {
  icon?: IconName;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
  compact?: boolean;
  hatched?: boolean;
}) {
  const className = ['empty', compact ? 'empty--compact' : '', hatched ? 'empty--hatched' : '']
    .filter(Boolean)
    .join(' ');

  return (
    <div className={className} role="status">
      {icon ? <Icon name={icon} size="lg" /> : null}
      <strong>{title}</strong>
      {children ? <span>{children}</span> : null}
      {actions ? <div className="empty__actions">{actions}</div> : null}
    </div>
  );
}
