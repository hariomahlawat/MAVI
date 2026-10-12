import Button from '../../shared/components/Button';
import Icon from '../../shared/components/Icon';
import { Inspector } from '../../shared/workspace';
import type { Selection } from './editorState';
import { formatCoordinate, type DraftTripLine, type DraftZone, type SceneDraft } from './sceneDraft';

type Props = {
  draft: SceneDraft;
  selection: Selection;
  readOnly: boolean;
  /** A past revision is shown (rather than the active scene of an inactive camera). */
  historical: boolean;
  /** What to say while a past revision cannot be listed — loading or unavailable: its geometry is unknown, not absent. */
  pending?: string | null;
  /** The pending revision is loading (said in the shared loading grammar), rather than unavailable. */
  pendingLoading?: boolean;
  /**
   * How many zones and trip lines the loading revision has, from its summary in
   * the revision history: its rows are reserved in their own geometry while it
   * loads, so nothing below the list moves when they arrive (§36.3, §38).
   */
  pendingCounts?: { zones: number; tripLines: number };
  invalidKeys: ReadonlySet<string>;
  onSelect: (selection: Selection) => void;
  onDelete: (key: string) => void;
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
 * selected object's editable coordinates live in the inspector below, so
 * selecting something never pushes the rest of the scene out of view. Each
 * item still carries its object's actual geometry (§23): a trip line's two
 * endpoints inline, a zone's vertices behind a closed disclosure in the same
 * item, so the list is the canvas's twin and not a parallel surface. It
 * creates nothing: drawing starts in the mode strip, the one place that arms a
 * tool (§4.3).
 *
 * It is a list of buttons rather than a listbox on purpose. A listbox option
 * may not contain focusable children, and each row here carries its own name
 * and delete controls; claiming the role would promise arrow-key
 * navigation that does not exist and would leave a screen-reader user pressing
 * Down against nothing. Selection is stated with `aria-pressed` on the control
 * that does the selecting, and with `aria-current` so it is the same "current"
 * the result row and evidence set state.
 */
export default function SceneObjectList({
  draft,
  selection,
  readOnly,
  historical,
  pending = null,
  pendingLoading = false,
  pendingCounts,
  invalidKeys,
  onSelect,
  onDelete,
}: Props) {
  const empty = draft.zones.length === 0 && draft.tripLines.length === 0;

  if (pending && pendingLoading && pendingCounts && pendingCounts.zones + pendingCounts.tripLines > 0) {
    return (
      <Inspector label="Scene objects" title="Scene objects">
        <p className="visually-hidden">{pending}</p>
        <PendingGroup kind="zones" count={pendingCounts.zones} />
        <PendingGroup kind="lines" count={pendingCounts.tripLines} />
      </Inspector>
    );
  }

  return (
    <Inspector label="Scene objects" title="Scene objects">
      {pending ? (
        // Not "no geometry": a revision loading or unavailable has geometry
        // nobody has read, so the list says which, the loading in the shared
        // grammar; the stage carries the failure's alert and retry.
        <p className="scene-navigator__empty">
          {pendingLoading ? <span className="state-row state-row--loading">{pending}</span> : pending}
        </p>
      ) : empty ? (
        <p className="scene-navigator__empty">
          {historical
            ? 'This revision has no geometry, so analytics were disabled while it was active.'
            : 'No zones or trip lines yet.'}
        </p>
      ) : null}

      {draft.zones.length > 0 ? (
        <section className="scene-navigator__group scene-navigator__group--zones">
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
        <section className="scene-navigator__group scene-navigator__group--lines">
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
    </Inspector>
  );
}

/** A group of a loading revision: its heading and count, and a row per object in the rows' geometry. */
function PendingGroup({ kind, count }: { kind: 'zones' | 'lines'; count: number }) {
  if (count === 0) return null;
  return (
    <section className={`scene-navigator__group scene-navigator__group--${kind}`} aria-hidden="true" data-testid={`scene-navigator-pending-${kind}`}>
      <h3>{kind === 'zones' ? 'Zones' : 'Trip lines'}<span>{count}</span></h3>
      <ul>
        {Array.from({ length: count }, (_, index) => (
          <li key={index} className="scene-navigator__item scene-navigator__item--pending">
            <div className="scene-navigator__row">
              <span className="scene-navigator__name">
                <span className="scene-navigator__dot" />
                <span className="scene-navigator__bar" />
                {/* A name's own line box, so the row is a name's height. */}
                {' '}
              </span>
            </div>
            {kind === 'zones' ? (
              <div className="scene-navigator__coordinates"><div className="scene-navigator__summary-space">{'\u00a0'}</div></div>
            ) : (
              // The endpoints line has one fixed width (every coordinate is
              // printed to the same precision), so a hidden one of zeros wraps
              // exactly as the line's own will.
              <span className="scene-navigator__endpoints scene-navigator__placeholder">
                {`(${formatCoordinate(0)}, ${formatCoordinate(0)}) \u2192 (${formatCoordinate(0)}, ${formatCoordinate(0)})`}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
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
    <li
      className={`scene-navigator__item${selected ? ' is-selected' : ''}`}
      data-object-kind="zone"
      data-object-key={zone.key}
    >
      <div className="scene-navigator__row">
        <button
          type="button"
          className="scene-navigator__name"
          aria-pressed={selected}
          aria-current={selected ? 'true' : undefined}
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
      {/* The stored vertices, in order, as stored: a native disclosure so the
          navigator keeps the size of the scene and the geometry is one step
          away in the same item. Editing them is the inspector's job. */}
      <details className="scene-navigator__coordinates">
        <summary>Coordinates</summary>
        <ol className="scene-navigator__points">
          {zone.vertices.map((vertex, index) => (
            // Vertices are positional, not identified; a reorder re-renders the text.
            <li key={index}>{`${formatCoordinate(vertex.x)}, ${formatCoordinate(vertex.y)}`}</li>
          ))}
        </ol>
      </details>
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
    <li
      className={`scene-navigator__item${selected ? ' is-selected' : ''}`}
      data-object-kind="line"
      data-object-key={line.key}
    >
      <div className="scene-navigator__row">
        <button
          type="button"
          className="scene-navigator__name"
          aria-pressed={selected}
          aria-current={selected ? 'true' : undefined}
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
      {/* Two endpoints are short enough to state inline, A to B, as stored. */}
      <span className="scene-navigator__endpoints">
        {`(${formatCoordinate(line.a.x)}, ${formatCoordinate(line.a.y)}) → (${formatCoordinate(line.b.x)}, ${formatCoordinate(line.b.y)})`}
      </span>
    </li>
  );
}
