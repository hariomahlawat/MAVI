import { SCENE_LIMITS } from '../../api/scene';
import Button from '../../shared/components/Button';
import { ContextBar } from '../../shared/workspace';

type SaveState = 'clean' | 'dirty' | 'saving' | 'saved' | 'readonly';

type Props = {
  cameraCode: string;
  cameraName: string;
  revisionNumber: number;
  saveState: SaveState;
  analyticsEnabled: boolean;
  note: string;
  canSave: boolean;
  blockedReason: string | null;
  confirmingDisable: boolean;
  onNoteChange: (note: string) => void;
  onReset: () => void;
  onSave: () => void;
  onCancelDisable: () => void;
  onReturnToActive: () => void;
};

const stateLabels: Record<SaveState, string> = {
  clean: 'Active',
  dirty: 'Unsaved changes',
  saving: 'Saving…',
  saved: 'Saved',
  readonly: 'Read only',
};

/**
 * The Scene Editor's fill of the shared Context Bar (§5).
 *
 * The bar itself — the band, its height, its stickiness and its three slots —
 * belongs to the shell now. What is left here is what only this surface knows:
 * which camera's scene this is, what will happen if it is saved, and the
 * controls that save it.
 *
 * Revision context is the first state to read and the easiest to get wrong, so
 * it leads the status group and states the revision, whether it is the active
 * one, and whether there is unsaved work. The read-only state keeps its own
 * treatment rather than a subtler shade of the same chip: mistaking a past
 * revision for the live one is the expensive error here.
 *
 * Two pieces of prose that used to sit in this band — the reason Save is
 * refusing, and the consequence of saving a scene with nothing enabled — now
 * live in the workspace's notices region. §5 limits the bar to identity, state
 * and actions, and a 44px band cannot hold a sentence without either truncating
 * it or growing. `aria-describedby` still ties both to the control they are
 * about, so nothing is lost to a screen reader by the move.
 */
export default function SceneContextBar({
  cameraCode,
  cameraName,
  revisionNumber,
  saveState,
  analyticsEnabled,
  note,
  canSave,
  blockedReason,
  confirmingDisable,
  onNoteChange,
  onReset,
  onSave,
  onCancelDisable,
  onReturnToActive,
}: Props) {
  const readOnly = saveState === 'readonly';

  return (
    <ContextBar
      // A past revision is not the live scene, and that is worth more than one
      // chip: the whole bar says so, as it did before the migration.
      tone={readOnly ? 'caution' : undefined}
      crumbs={[
        { label: 'Cameras', to: '/cameras' },
        // No camera record surface exists yet, so this crumb names the object
        // without linking; a crumb that navigates to a 404 is worse than one
        // that does not navigate.
        { label: cameraCode },
        { label: 'Scene' },
      ]}
      status={(
        <>
          {/* The name is not the identity — the code is — but it is what the
              operator recognises, so it stays beside it rather than being
              dropped for the sake of a tidier crumb trail. */}
          <span className="scene-context__name truncate">{cameraName}</span>

          <span className={`scene-context__revision is-${saveState}`}>
            <span className="scene-context__revision-number">
              {revisionNumber > 0 ? `Revision ${revisionNumber}` : 'No revision yet'}
            </span>
            {/* "Active" describes a revision. With none saved there is nothing
                to call active, and saying so beside "No revision yet" reads as
                a contradiction, so the state is simply left unsaid until it
                means something. */}
            {revisionNumber > 0 || saveState !== 'clean' ? (
              <span className="scene-context__revision-state">{stateLabels[saveState]}</span>
            ) : null}
          </span>

          <span className={`scene-context__analytics${analyticsEnabled ? '' : ' is-off'}`}>
            {analyticsEnabled ? 'Analytics on' : 'Analytics off'}
          </span>
        </>
      )}
      actions={readOnly ? (
        <Button variant="primary" icon="chevronLeft" onClick={onReturnToActive}>
          Return to active revision
        </Button>
      ) : (
        <>
          {saveState === 'dirty' || saveState === 'saving' ? (
            <label className="scene-context__note">
              <span className="visually-hidden">Revision note (optional)</span>
              <input
                value={note}
                maxLength={SCENE_LIMITS.maximumNoteLength}
                placeholder="Note (optional)"
                autoComplete="off"
                onChange={(event) => onNoteChange(event.target.value)}
              />
            </label>
          ) : null}
          <Button
            variant="ghost"
            disabled={saveState === 'saving'}
            onClick={confirmingDisable ? onCancelDisable : onReset}
          >
            {confirmingDisable ? 'Cancel' : 'Reset'}
          </Button>
          {/* A disabled button receives no pointer events, so a `title` on one
              is a tooltip nobody can open. Both explanations are rendered in
              the notices region and referenced from here. */}
          <Button
            variant="primary"
            disabled={!canSave}
            aria-describedby={
              confirmingDisable ? 'scene-disable-confirm' : blockedReason ? 'scene-save-blocked' : undefined
            }
            onClick={onSave}
          >
            {saveState === 'saving'
              ? 'Saving…'
              : confirmingDisable ? 'Save and disable analytics' : 'Save revision'}
          </Button>
        </>
      )}
    />
  );
}
