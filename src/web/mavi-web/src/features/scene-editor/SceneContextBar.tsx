import { SCENE_LIMITS } from '../../api/scene';
import Button from '../../shared/components/Button';
import { SHELL_QUERIES, useMediaQuery } from '../../shared/overlay/useMediaQuery';
import { ContextBar } from '../../shared/workspace';

type SaveState = 'clean' | 'dirty' | 'saving' | 'saved' | 'readonly';

type Props = {
  cameraCode: string;
  cameraName: string;
  revisionNumber: number;
  saveState: SaveState;
  /** Null while the revision shown is not known (a past revision loading or unavailable): nothing is claimed. */
  analyticsEnabled: boolean | null;
  note: string;
  canSave: boolean;
  blockedReason: string | null;
  /** The camera is inactive: Save is refused for that reason, stated in the mode strip. */
  inactive: boolean;
  /** A revision note is typed though the scene is back at its baseline: still the operator's input. */
  noteRetained: boolean;
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
  inactive,
  noteRetained,
  confirmingDisable,
  onNoteChange,
  onReset,
  onSave,
  onCancelDisable,
  onReturnToActive,
}: Props) {
  const readOnly = saveState === 'readonly';
  const narrow = useMediaQuery(SHELL_QUERIES.narrow);
  // Reset returns the draft — and its note — to the active revision; with no
  // changes and no note it has nothing to do, so it is not offered as if it
  // did (§12, F7). A note left behind when the geometry returns to its
  // baseline keeps its field and its Reset: it is never hidden input that a
  // later, unrelated save would carry.
  const nothingToReset = (saveState === 'clean' || saveState === 'saved') && !noteRetained;
  const showNote = saveState === 'dirty' || saveState === 'saving' || noteRetained;

  return (
    <ContextBar
      // A past revision is not the live scene, and that is worth more than one
      // chip: the whole bar says so, as it did before the migration.
      tone={readOnly ? 'caution' : undefined}
      surface="scene"
      // The camera is the object (§5: `Cameras › {camera} › Scene`): its code
      // is the identity and its name is what the operator recognises, so both
      // are the crumb, which truncates as one and is complete in the document
      // title. No camera record surface exists yet, so the crumb names the
      // object without linking; a crumb that navigates to a 404 is worse than
      // one that does not navigate.
      object={{ label: cameraName ? `${cameraCode} · ${cameraName}` : cameraCode }}
      status={(
        <>

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

          {analyticsEnabled === null ? null : (
            <span className={`scene-context__analytics${analyticsEnabled ? '' : ' is-off'}`}>
              {analyticsEnabled ? 'Analytics on' : 'Analytics off'}
            </span>
          )}
        </>
      )}
      // §25 Tier C: the editor is not drawn, so neither are its editing
      // actions — a Save of a draft the operator cannot see is not offered.
      // Returning from a past revision is a view change and stays.
      actions={narrow && !readOnly ? null : readOnly ? (
        <Button variant="primary" icon="chevronLeft" onClick={onReturnToActive}>
          Return to active revision
        </Button>
      ) : (
        <>
          {showNote ? (
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
            disabled={saveState === 'saving' || (!confirmingDisable && nothingToReset)}
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
              confirmingDisable
                ? 'scene-disable-confirm'
                : inactive ? 'scene-inactive-reason' : blockedReason ? 'scene-save-blocked' : undefined
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
