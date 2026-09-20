import Button from '../../shared/components/Button';
import Icon from '../../shared/components/Icon';
import type { Selection } from './editorState';
import type { DraftTripLine, DraftZone, SceneDraft } from './sceneDraft';

type Props = {
  draft: SceneDraft;
  selection: Selection;
  readOnly: boolean;
  invalidKeys: ReadonlySet<string>;
  onSelect: (selection: Selection) => void;
  onDelete: (key: string) => void;
  onAddZone: () => void;
  onAddLine: () => void;
};

/**
 * The scene as a navigator rather than a picture.
 *
 * This is the same scene the canvas shows, listed: it shares one selection with
 * the canvas and names every object and its state. That makes it a fast way to
 * move around a busy scene with a pointer, and the only way to reach an object
 * without a pointer at all. It is the same control serving both, not an
 * accessibility annex.
 *
 * Its height follows the size of the scene, not the size of the selection: the
 * selected object's coordinates live in the inspector below, so selecting
 * something never pushes the rest of the scene out of view.
 *
 * It is a list of buttons rather than a listbox on purpose. A listbox option
 * may not contain focusable children, and each row here carries its own name
 * and delete controls; claiming the role would promise arrow-key
 * navigation that does not exist and would leave a screen-reader user pressing
 * Down against nothing. Selection is stated with `aria-pressed` on the control
 * that does the selecting.
 */
export default function SceneObjectList({
  draft,
  selection,
  readOnly,
  invalidKeys,
  onSelect,
  onDelete,
  onAddZone,
  onAddLine,
}: Props) {
  const empty = draft.zones.length === 0 && draft.tripLines.length === 0;

  return (
    <div className="scene-navigator">
      <div className="scene-panel__head">
        <h2>Scene objects</h2>
        {readOnly ? null : (
          <div className="scene-panel__actions">
            <Button size="sm" variant="ghost" onClick={onAddZone}>+ Zone</Button>
            <Button size="sm" variant="ghost" onClick={onAddLine}>+ Line</Button>
          </div>
        )}
      </div>

      {empty ? (
        <p className="scene-navigator__empty">
          {readOnly
            ? 'This revision has no geometry, so analytics were disabled while it was active.'
            : 'Nothing drawn yet. Choose Zone or Trip line above, or draw on the frame.'}
        </p>
      ) : null}

      {draft.zones.length > 0 ? (
        <section className="scene-navigator__group">
          <h3>Zones<span>{draft.zones.length}</span></h3>
          <ul aria-label="Zones">
            {draft.zones.map((zone) => (
              <ZoneRow
                key={zone.key}
                zone={zone}
                selected={selection.kind === 'zone' && selection.key === zone.key}
                invalid={invalidKeys.has(zone.key)}
                readOnly={readOnly}
                onSelect={onSelect}
                onDelete={onDelete}
              />
            ))}
          </ul>
        </section>
      ) : null}

      {draft.tripLines.length > 0 ? (
        <section className="scene-navigator__group">
          <h3>Trip lines<span>{draft.tripLines.length}</span></h3>
          <ul aria-label="Trip lines">
            {draft.tripLines.map((line) => (
              <LineRow
                key={line.key}
                line={line}
                selected={selection.kind === 'line' && selection.key === line.key}
                invalid={invalidKeys.has(line.key)}
                readOnly={readOnly}
                onSelect={onSelect}
                onDelete={onDelete}
              />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function StateDot({ enabled, invalid }: { enabled: boolean; invalid: boolean }) {
  if (invalid) {
    return <Icon name="alert" size="sm" className="scene-navigator__warn" />;
  }
  return (
    <span
      className={`scene-navigator__dot${enabled ? '' : ' is-off'}`}
      aria-hidden="true"
    />
  );
}

function ZoneRow({
  zone,
  selected,
  invalid,
  readOnly,
  onSelect,
  onDelete,
}: {
  zone: DraftZone;
  selected: boolean;
  invalid: boolean;
  readOnly: boolean;
  onSelect: (selection: Selection) => void;
  onDelete: (key: string) => void;
}) {
  const state = `${zone.kind}, ${zone.vertices.length} vertices, ${zone.enabled ? 'enabled' : 'disabled'}`;
  return (
    <li className={`scene-navigator__item${selected ? ' is-selected' : ''}`}>
      <div className="scene-navigator__row">
        <button
          type="button"
          className="scene-navigator__name"
          aria-pressed={selected}
          onClick={() => onSelect({ kind: 'zone', key: zone.key, vertexIndex: null })}
        >
          <StateDot enabled={zone.enabled} invalid={invalid} />
          <span className="truncate" title={zone.name}>{zone.name || 'Unnamed zone'}</span>
          <span className="visually-hidden">{`, ${state}${invalid ? ', has a problem' : ''}`}</span>
        </button>
        {readOnly ? null : (
          <Button size="sm" variant="ghost" icon="x" iconOnly onClick={() => onDelete(zone.key)}>
            {`Delete zone ${zone.name || 'Unnamed zone'}`}
          </Button>
        )}
      </div>
    </li>
  );
}

function LineRow({
  line,
  selected,
  invalid,
  readOnly,
  onSelect,
  onDelete,
}: {
  line: DraftTripLine;
  selected: boolean;
  invalid: boolean;
  readOnly: boolean;
  onSelect: (selection: Selection) => void;
  onDelete: (key: string) => void;
}) {
  const state = `${line.directed ? 'directional' : 'undirected'}, ${line.enabled ? 'enabled' : 'disabled'}`;
  return (
    <li className={`scene-navigator__item${selected ? ' is-selected' : ''}`}>
      <div className="scene-navigator__row">
        <button
          type="button"
          className="scene-navigator__name"
          aria-pressed={selected}
          onClick={() => onSelect({ kind: 'line', key: line.key, endpoint: null })}
        >
          <StateDot enabled={line.enabled} invalid={invalid} />
          <span className="truncate" title={line.name}>{line.name || 'Unnamed trip line'}</span>
          <span className="visually-hidden">{`, ${state}${invalid ? ', has a problem' : ''}`}</span>
        </button>
        {readOnly ? null : (
          <Button size="sm" variant="ghost" icon="x" iconOnly onClick={() => onDelete(line.key)}>
            {`Delete trip line ${line.name || 'Unnamed trip line'}`}
          </Button>
        )}
      </div>
    </li>
  );
}
