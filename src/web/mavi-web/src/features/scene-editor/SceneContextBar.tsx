import { SCENE_LIMITS } from '../../api/scene';
import Button from '../../shared/components/Button';

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
  onNoteChange: (note: string) => void;
  onReset: () => void;
  onSave: () => void;
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
 * Where the operator is and what will happen if they save.
 *
 * Revision context is the first thing to read and the easiest to get wrong, so
 * it sits at the top in one line and states the revision, whether it is the
 * active one, and whether there is unsaved work. The read-only state is given
 * its own treatment rather than a subtler shade of the same chip: mistaking a
 * past revision for the live one is the expensive error here.
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
  onNoteChange,
  onReset,
  onSave,
  onReturnToActive,
}: Props) {
  const readOnly = saveState === 'readonly';

  return (
    <div className={`scene-context${readOnly ? ' scene-context--readonly' : ''}`}>
      <div className="scene-context__identity">
        <h1>{cameraCode}</h1>
        <span className="scene-context__name">{cameraName}</span>
      </div>

      <div className={`scene-context__revision is-${saveState}`}>
        <span className="scene-context__revision-number">
          {revisionNumber > 0 ? `Revision ${revisionNumber}` : 'No revision yet'}
        </span>
        {/* "Active" describes a revision. With none saved there is nothing to
            call active, and saying so beside "No revision yet" reads as a
            contradiction, so the state is simply left unsaid until it means
            something. */}
        {revisionNumber > 0 || saveState !== 'clean' ? (
          <span className="scene-context__revision-state">{stateLabels[saveState]}</span>
        ) : null}
      </div>

      <span className={`scene-context__analytics${analyticsEnabled ? '' : ' is-off'}`}>
        {analyticsEnabled ? 'Analytics on' : 'Analytics off'}
      </span>

      <span className="grow" />

      {readOnly ? (
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
            onClick={onReset}
          >
            Reset
          </Button>
          <Button
            variant="primary"
            disabled={!canSave}
            title={blockedReason ?? undefined}
            onClick={onSave}
          >
            {saveState === 'saving' ? 'Saving…' : 'Save revision'}
          </Button>
        </>
      )}
    </div>
  );
}
