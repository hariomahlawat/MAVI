import type { ReactNode } from 'react';
import Button from './Button';
import Icon, { type IconName } from './Icon';

/**
 * "Nothing here" — never "we could not find out". A failed request is an Alert
 * through `StateRegion` (§37.1), and media that cannot be shown is the
 * `EvidencePlaceholder`; neither is this component.
 *
 * `hatched` marks a domain state that is not a plain empty result — a scene
 * not configured, analytics disabled by the scene, runs not analysed yet — so
 * it is distinguishable from "nothing here" without relying on the words alone.
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
