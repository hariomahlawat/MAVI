import Button from '../../shared/components/Button';
import { Segmented, Toolbar } from '../../shared/workspace';
import type { Drawing, EditorTool } from './editorState';

type Props = {
  tool: EditorTool;
  drawing: Drawing;
  readOnly: boolean;
  historyOpen: boolean;
  drawingError: string | null;
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

const TOOLS = [
  { value: 'select', label: 'Select' },
  { value: 'zone', label: 'Zone' },
  { value: 'line', label: 'Trip line' },
] as const satisfies ReadonlyArray<{ value: EditorTool; label: string }>;

/**
 * The mode strip, on the shared toolbar band.
 *
 * Which tool is armed is the single most consequential piece of state on this
 * screen, so it is a segmented control that reads as one thing with one part
 * pressed, not three buttons that happen to sit together. The instruction line
 * appears only while a drawing tool is armed; standing tutorial text would be
 * noise for the operator who uses this daily.
 *
 * A refused gesture is answered here too, in place of the hint. The operator is
 * looking at the tool and the frame, not at a notice stack above both of them,
 * and a click that appeared to do nothing needs its explanation where the click
 * was aimed. The band's `hint` slot is exactly that line, which is why the
 * shared shell carries one.
 */
export default function SceneToolbar({
  tool,
  drawing,
  readOnly,
  historyOpen,
  drawingError,
  onToolChange,
  onCloseZone,
  onCancelDrawing,
  onToggleHistory,
}: Props) {
  const hint = readOnly ? null : hints[tool];

  return (
    <Toolbar
      label="Scene tools"
      hint={drawingError
        ? <span className="scene-toolbar__refusal" role="alert">{drawingError}</span>
        : hint ?? null}
      actions={(
        <Button
          size="sm"
          variant="ghost"
          icon="clock"
          aria-controls="scene-revision-strip"
          aria-expanded={historyOpen}
          onClick={onToggleHistory}
        >
          Revisions
        </Button>
      )}
    >
      {readOnly ? (
        <p className="scene-toolbar__readonly">Drawing tools are unavailable while a past revision is open.</p>
      ) : (
        <Segmented
          label="Drawing tools"
          value={tool}
          options={TOOLS}
          onChange={onToolChange}
        />
      )}

      {drawing.kind === 'zone' ? (
        <Button size="sm" icon="check" onClick={onCloseZone}>Finish zone</Button>
      ) : null}
      {drawing.kind !== 'none' ? (
        <Button size="sm" variant="ghost" onClick={onCancelDrawing}>Cancel</Button>
      ) : null}
    </Toolbar>
  );
}
