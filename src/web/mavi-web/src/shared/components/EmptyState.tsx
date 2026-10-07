import type { ReactNode } from 'react';
import Button from './Button';
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

/**
 * The §37.1 filtered-empty presentation: the same geometry as empty, the
 * filter icon, one vocabulary, and *Clear filters* as the one secondary action.
 * It is never the authoritative "nothing exists": the inventory is real and
 * the filters simply exclude all of it.
 */
export function FilteredEmptyState({ subject, onClear }: { subject: string; onClear: () => void }) {
  return (
    <EmptyState
      icon="filter"
      title={`No ${subject} match these filters`}
      compact
      actions={<Button size="sm" onClick={onClear}>Clear filters</Button>}
    />
  );
}
