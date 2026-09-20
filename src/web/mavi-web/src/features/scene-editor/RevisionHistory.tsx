import type { SceneRevisionSummary } from '../../api/scene';
import Button from '../../shared/components/Button';
import EmptyState from '../../shared/components/EmptyState';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDateTime } from '../../shared/time/time';

type Props = {
  history: SceneRevisionSummary[];
  /** The operator's configured display timezone; timestamps are never shown in browser time. */
  displayTimeZoneId: string | undefined;
  activeRevisionNumber: number | null;
  viewingRevisionNumber: number | null;
  onView: (revisionNumber: number) => void;
  onReturnToActive: () => void;
};

/**
 * Every revision this camera has had, newest first.
 *
 * Viewing is inspection only. A historical revision is never loaded into the
 * editable draft, because submitting its identities would break the
 * stable-identity rule the backend enforces: changes always start from the
 * revision that is currently active.
 */
export default function RevisionHistory({
  history,
  displayTimeZoneId,
  activeRevisionNumber,
  viewingRevisionNumber,
  onView,
  onReturnToActive,
}: Props) {
  if (history.length === 0) {
    return <EmptyState title="No revisions yet" compact>Saving the scene creates revision 1.</EmptyState>;
  }

  const ordered = [...history].sort((left, right) => right.revisionNumber - left.revisionNumber);

  return (
    <div className="stack stack--tight">
      {viewingRevisionNumber !== null ? (
        <div className="row">
          <Button size="sm" icon="chevronLeft" onClick={onReturnToActive}>Return to active revision</Button>
        </div>
      ) : null}

      <ul className="scene-history">
        {ordered.map((entry) => {
          const isActive = entry.revisionNumber === activeRevisionNumber;
          const isViewing = entry.revisionNumber === viewingRevisionNumber;
          return (
            <li key={entry.revisionId} className={`scene-history__item${isViewing ? ' is-selected' : ''}`}>
              <div className="scene-history__head">
                <strong>Revision {entry.revisionNumber}</strong>
                {isActive ? <StatusBadge tone="ok">Active</StatusBadge> : null}
                <StatusBadge tone={entry.analyticsEnabled ? 'info' : 'neutral'}>
                  {entry.analyticsEnabled ? 'Analytics enabled' : 'Analytics disabled'}
                </StatusBadge>
              </div>
              <div className="scene-history__meta">
                {displayTimeZoneId ? formatDateTime(entry.createdAtUtc, displayTimeZoneId) : entry.createdAtUtc} · {entry.zoneCount} zones · {entry.tripLineCount} trip lines
              </div>
              {entry.note ? <p className="scene-history__note">{entry.note}</p> : null}
              <div className="row">
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={isViewing}
                  onClick={() => onView(entry.revisionNumber)}
                >
                  {isViewing ? 'Viewing' : `View revision ${entry.revisionNumber}`}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
