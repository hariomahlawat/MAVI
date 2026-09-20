import type { SceneRevisionSummary } from '../../api/scene';
import Button from '../../shared/components/Button';
import { formatDateTime } from '../../shared/time/time';

type Props = {
  history: SceneRevisionSummary[];
  displayTimeZoneId: string | undefined;
  activeRevisionNumber: number | null;
  viewingRevisionNumber: number | null;
  expanded: boolean;
  onView: (revisionNumber: number) => void;
  onReturnToActive: () => void;
};

/**
 * The revision strip.
 *
 * History matters but is not the work, so it takes one line until asked for,
 * and never a permanent column of the workspace. Collapsed it is a scannable
 * run of revision numbers; expanded it adds the date and the note that tell
 * them apart.
 *
 * Viewing is inspection only. A past revision is never loaded into the editable
 * draft, because submitting its identities would breach the stable-identity
 * rule the backend enforces: changes always start from the active revision.
 */
export default function RevisionHistory({
  history,
  displayTimeZoneId,
  activeRevisionNumber,
  viewingRevisionNumber,
  expanded,
  onView,
  onReturnToActive,
}: Props) {
  if (history.length === 0) {
    return (
      <div className="scene-revisions" id="scene-revision-strip">
        <span className="scene-revisions__label">Revisions</span>
        <span className="scene-revisions__none">None yet · saving creates revision 1</span>
      </div>
    );
  }

  const ordered = [...history].sort((left, right) => right.revisionNumber - left.revisionNumber);

  return (
    <div className={`scene-revisions${expanded ? ' is-expanded' : ''}`} id="scene-revision-strip">
      <span className="scene-revisions__label" id="scene-revisions-label">Revisions</span>

      <ul className="scene-revisions__list" aria-labelledby="scene-revisions-label">
        {ordered.map((entry) => {
          const isActive = entry.revisionNumber === activeRevisionNumber;
          const isViewing = entry.revisionNumber === viewingRevisionNumber;
          return (
            <li key={entry.revisionId}>
              <button
                type="button"
                className={[
                  'scene-revisions__chip',
                  isActive ? 'is-active' : '',
                  isViewing ? 'is-viewing' : '',
                  entry.analyticsEnabled ? '' : 'is-off',
                ].filter(Boolean).join(' ')}
                aria-pressed={isViewing}
                onClick={() => (isViewing ? onReturnToActive() : onView(entry.revisionNumber))}
              >
                <span className="scene-revisions__number">R{entry.revisionNumber}</span>
                {isActive ? <span className="scene-revisions__tag">Active</span> : null}
                {expanded ? (
                  <span className="scene-revisions__detail">
                    <span>{displayTimeZoneId ? formatDateTime(entry.createdAtUtc, displayTimeZoneId) : entry.createdAtUtc}</span>
                    <span className="truncate">
                      {entry.note ?? `${entry.zoneCount} zones · ${entry.tripLineCount} lines`}
                    </span>
                  </span>
                ) : null}
                <span className="visually-hidden">
                  {`${isViewing ? 'Viewing, ' : 'View '}revision ${entry.revisionNumber}, `
                    + `${entry.zoneCount} zones, ${entry.tripLineCount} trip lines, `
                    + `analytics ${entry.analyticsEnabled ? 'enabled' : 'disabled'}`}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {viewingRevisionNumber !== null ? (
        <Button size="sm" variant="ghost" icon="chevronLeft" onClick={onReturnToActive}>
          Back to active
        </Button>
      ) : null}
    </div>
  );
}
