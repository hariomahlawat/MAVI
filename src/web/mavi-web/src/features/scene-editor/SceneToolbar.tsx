import Button from '../../shared/components/Button';
import type { Drawing, EditorTool } from './editorState';

type Props = {
  tool: EditorTool;
  drawing: Drawing;
  readOnly: boolean;
  historyOpen: boolean;
  onToolChange: (tool: EditorTool) => void;
  onCloseZone: () => void;
  onCancelDrawing: () => void;
  onToggleHistory: () => void;
};

const hints: Record<EditorTool, string | null> = {
  select: null,
  zone: 'Click to add a vertex · click the first vertex or press Enter to finish · Esc to cancel',
  line: 'Click the start point, then the end point · Esc to cancel',
};

/**
 * The mode strip.
 *
 * Which tool is armed is the single most consequential piece of state on this
 * screen, so it is a segmented control that reads as one thing with one part
 * pressed, not three buttons that happen to sit together. The instruction line
 * appears only while a drawing tool is armed; standing tutorial text would be
 * noise for the operator who uses this daily.
 */
export default function SceneToolbar({
  tool,
  drawing,
  readOnly,
  historyOpen,
  onToolChange,
  onCloseZone,
  onCancelDrawing,
  onToggleHistory,
}: Props) {
  const hint = readOnly ? null : hints[tool];

  return (
    <div className="scene-toolbar">
      {readOnly ? (
        <p className="scene-toolbar__readonly">Drawing tools are unavailable while a past revision is open.</p>
      ) : (
        <div className="segmented" role="group" aria-label="Drawing tools">
          <button
            type="button"
            className={`segmented__item${tool === 'select' ? ' is-active' : ''}`}
            aria-pressed={tool === 'select'}
            onClick={() => onToolChange('select')}
          >
            Select
          </button>
          <button
            type="button"
            className={`segmented__item${tool === 'zone' ? ' is-active' : ''}`}
            aria-pressed={tool === 'zone'}
            onClick={() => onToolChange('zone')}
          >
            Zone
          </button>
          <button
            type="button"
            className={`segmented__item${tool === 'line' ? ' is-active' : ''}`}
            aria-pressed={tool === 'line'}
            onClick={() => onToolChange('line')}
          >
            Trip line
          </button>
        </div>
      )}

      {drawing.kind === 'zone' ? (
        <Button size="sm" icon="check" onClick={onCloseZone}>Finish zone</Button>
      ) : null}
      {drawing.kind !== 'none' ? (
        <Button size="sm" variant="ghost" onClick={onCancelDrawing}>Cancel</Button>
      ) : null}

      {hint ? <p className="scene-toolbar__hint">{hint}</p> : null}

      <span className="grow" />

      <Button
        size="sm"
        variant="ghost"
        icon="clock"
        aria-expanded={historyOpen}
        onClick={onToggleHistory}
      >
        Revisions
      </Button>
    </div>
  );
}
