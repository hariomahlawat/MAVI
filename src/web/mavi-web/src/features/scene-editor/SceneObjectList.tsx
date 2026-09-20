import { SCENE_LIMITS } from '../../api/scene';
import Button from '../../shared/components/Button';
import EmptyState from '../../shared/components/EmptyState';
import type { Selection } from './editorState';
import type { DraftTripLine, DraftZone, SceneDraft } from './sceneDraft';

type Props = {
  draft: SceneDraft;
  selection: Selection;
  readOnly: boolean;
  onSelect: (selection: Selection) => void;
  onDelete: (key: string) => void;
};

function coordinate(value: number): string {
  return value.toFixed(SCENE_LIMITS.coordinateDecimals);
}

/**
 * The scene as a list rather than a picture.
 *
 * This is not a convenience: it is how a keyboard or screen-reader user reads
 * and edits the scene at all. Every object, its state and every coordinate the
 * canvas draws is reachable here, and selection is shared with the canvas so
 * the two never disagree about what is being edited.
 */
export default function SceneObjectList({ draft, selection, readOnly, onSelect, onDelete }: Props) {
  const empty = draft.zones.length === 0 && draft.tripLines.length === 0;

  if (empty) {
    return (
      <EmptyState icon="layers" title="No geometry yet" compact>
        Draw a zone or a trip line, or save an empty scene to disable analytics for this camera.
      </EmptyState>
    );
  }

  return (
    <div className="scene-objects">
      {draft.zones.length > 0 ? (
        <section className="scene-objects__group" aria-labelledby="scene-objects-zones">
          <h3 id="scene-objects-zones">Zones ({draft.zones.length})</h3>
          <ul className="scene-objects__list" role="listbox" aria-label="Zones">
            {draft.zones.map((zone) => (
              <ZoneRow
                key={zone.key}
                zone={zone}
                selected={selection.kind === 'zone' && selection.key === zone.key}
                selectedVertex={selection.kind === 'zone' && selection.key === zone.key ? selection.vertexIndex : null}
                readOnly={readOnly}
                onSelect={onSelect}
                onDelete={onDelete}
              />
            ))}
          </ul>
        </section>
      ) : null}

      {draft.tripLines.length > 0 ? (
        <section className="scene-objects__group" aria-labelledby="scene-objects-lines">
          <h3 id="scene-objects-lines">Trip lines ({draft.tripLines.length})</h3>
          <ul className="scene-objects__list" role="listbox" aria-label="Trip lines">
            {draft.tripLines.map((line) => (
              <LineRow
                key={line.key}
                line={line}
                selected={selection.kind === 'line' && selection.key === line.key}
                selectedEndpoint={selection.kind === 'line' && selection.key === line.key ? selection.endpoint : null}
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

function ZoneRow({
  zone,
  selected,
  selectedVertex,
  readOnly,
  onSelect,
  onDelete,
}: {
  zone: DraftZone;
  selected: boolean;
  selectedVertex: number | null;
  readOnly: boolean;
  onSelect: (selection: Selection) => void;
  onDelete: (key: string) => void;
}) {
  return (
    <li className={`scene-objects__item${selected ? ' is-selected' : ''}`} role="option" aria-selected={selected}>
      <div className="scene-objects__row">
        <button
          type="button"
          className="scene-objects__name"
          onClick={() => onSelect({ kind: 'zone', key: zone.key, vertexIndex: null })}
        >
          {zone.name}
          <span className="scene-objects__meta">
            {zone.kind} · {zone.vertices.length} vertices · {zone.enabled ? 'enabled' : 'disabled'}
          </span>
        </button>
        {readOnly ? null : (
          <Button
            size="sm"
            variant="ghost"
            icon="x"
            iconOnly
            onClick={() => onDelete(zone.key)}
          >
            {`Delete zone ${zone.name}`}
          </Button>
        )}
      </div>

      {selected ? (
        <ul className="scene-objects__vertices" aria-label={`Vertices of ${zone.name}`}>
          {zone.vertices.map((vertex, index) => (
            <li key={`${zone.key}-vertex-${index}`}>
              <button
                type="button"
                className={`scene-objects__vertex${selectedVertex === index ? ' is-selected' : ''}`}
                aria-pressed={selectedVertex === index}
                onClick={() => onSelect({ kind: 'zone', key: zone.key, vertexIndex: index })}
              >
                {`Vertex ${index + 1}: x ${coordinate(vertex.x)}, y ${coordinate(vertex.y)}`}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function LineRow({
  line,
  selected,
  selectedEndpoint,
  readOnly,
  onSelect,
  onDelete,
}: {
  line: DraftTripLine;
  selected: boolean;
  selectedEndpoint: 'a' | 'b' | null;
  readOnly: boolean;
  onSelect: (selection: Selection) => void;
  onDelete: (key: string) => void;
}) {
  return (
    <li className={`scene-objects__item${selected ? ' is-selected' : ''}`} role="option" aria-selected={selected}>
      <div className="scene-objects__row">
        <button
          type="button"
          className="scene-objects__name"
          onClick={() => onSelect({ kind: 'line', key: line.key, endpoint: null })}
        >
          {line.name}
          <span className="scene-objects__meta">
            {line.directed ? 'directed' : 'undirected'} · {line.enabled ? 'enabled' : 'disabled'}
          </span>
        </button>
        {readOnly ? null : (
          <Button
            size="sm"
            variant="ghost"
            icon="x"
            iconOnly
            onClick={() => onDelete(line.key)}
          >
            {`Delete trip line ${line.name}`}
          </Button>
        )}
      </div>

      {selected ? (
        <ul className="scene-objects__vertices" aria-label={`Endpoints of ${line.name}`}>
          <li>
            <button
              type="button"
              className={`scene-objects__vertex${selectedEndpoint === 'a' ? ' is-selected' : ''}`}
              aria-pressed={selectedEndpoint === 'a'}
              onClick={() => onSelect({ kind: 'line', key: line.key, endpoint: 'a' })}
            >
              {`Endpoint A: x ${coordinate(line.a.x)}, y ${coordinate(line.a.y)}`}
            </button>
          </li>
          <li>
            <button
              type="button"
              className={`scene-objects__vertex${selectedEndpoint === 'b' ? ' is-selected' : ''}`}
              aria-pressed={selectedEndpoint === 'b'}
              onClick={() => onSelect({ kind: 'line', key: line.key, endpoint: 'b' })}
            >
              {`Endpoint B: x ${coordinate(line.b.x)}, y ${coordinate(line.b.y)}`}
            </button>
          </li>
        </ul>
      ) : null}
    </li>
  );
}
