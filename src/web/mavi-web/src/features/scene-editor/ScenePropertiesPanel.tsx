import { SCENE_LIMITS, SCENE_ZONE_KINDS, type SceneZoneKind } from '../../api/scene';
import { findLine, findZone, type Selection } from './editorState';
import type { DraftTripLine, DraftZone, SceneDraft } from './sceneDraft';
import type { SceneIssue } from './sceneValidation';

type Props = {
  draft: SceneDraft;
  selection: Selection;
  readOnly: boolean;
  issues: Map<string, SceneIssue[]>;
  onUpdateZone: (key: string, changes: Partial<Omit<DraftZone, 'key' | 'zoneId' | 'vertices'>>) => void;
  onUpdateLine: (key: string, changes: Partial<Omit<DraftTripLine, 'key' | 'lineId' | 'a' | 'b'>>) => void;
  onSelect: (selection: Selection) => void;
};

function coordinate(value: number): string {
  return value.toFixed(SCENE_LIMITS.coordinateDecimals);
}

/**
 * The inspector: everything about the selected object that is not its shape.
 *
 * Geometry belongs on the canvas, but a name, a kind or a label should never
 * require pointing at a picture, and nothing here opens a dialog. The selected
 * object's own coordinates are here too: they are what it is, they are the only
 * way to reach a vertex without a pointer, and keeping them out of the
 * navigator keeps the navigator the size of the scene. When nothing is selected
 * the panel reports the scene instead of going blank, because an empty panel
 * wastes the space and answers nothing.
 */
export default function ScenePropertiesPanel({
  draft,
  selection,
  readOnly,
  issues,
  onUpdateZone,
  onUpdateLine,
  onSelect,
}: Props) {
  if (selection.kind === 'zone') {
    const zone = findZone(draft, selection.key);
    if (zone) {
      return (
        <ZoneProperties
          zone={zone}
          vertexIndex={selection.vertexIndex}
          readOnly={readOnly}
          issues={issues.get(zone.key) ?? []}
          onUpdate={onUpdateZone}
          onSelect={onSelect}
        />
      );
    }
  }

  if (selection.kind === 'line') {
    const line = findLine(draft, selection.key);
    if (line) {
      return (
        <LineProperties
          line={line}
          endpoint={selection.endpoint}
          readOnly={readOnly}
          issues={issues.get(line.key) ?? []}
          onUpdate={onUpdateLine}
          onSelect={onSelect}
        />
      );
    }
  }

  return <SceneSummary draft={draft} />;
}

function SceneSummary({ draft }: { draft: SceneDraft }) {
  const enabledZones = draft.zones.filter((zone) => zone.enabled).length;
  const enabledLines = draft.tripLines.filter((line) => line.enabled).length;
  return (
    <div className="scene-inspector">
      <header className="scene-inspector__head">
        <h2>Scene</h2>
        <p>Nothing selected</p>
      </header>
      <dl className="scene-readout">
        <dt>Zones</dt>
        <dd>{draft.zones.length} ({enabledZones} enabled)</dd>
        <dt>Trip lines</dt>
        <dd>{draft.tripLines.length} ({enabledLines} enabled)</dd>
        <dt>Analytics</dt>
        <dd>{enabledZones + enabledLines > 0 ? 'Enabled by this scene' : 'Disabled by this scene'}</dd>
      </dl>
      <p className="scene-inspector__hint">Select an object on the frame or in the list to edit it.</p>
    </div>
  );
}

function Issues({ issues, id }: { issues: SceneIssue[]; id: string }) {
  if (issues.length === 0) return null;
  return (
    <ul className="scene-inspector__issues" id={id}>
      {issues.map((issue) => <li key={issue.message}>{issue.message}</li>)}
    </ul>
  );
}

function ZoneProperties({
  zone,
  vertexIndex,
  readOnly,
  issues,
  onUpdate,
  onSelect,
}: {
  zone: DraftZone;
  vertexIndex: number | null;
  readOnly: boolean;
  issues: SceneIssue[];
  onUpdate: Props['onUpdateZone'];
  onSelect: Props['onSelect'];
}) {
  const nameId = `zone-name-${zone.key}`;
  const issuesId = `zone-issues-${zone.key}`;
  const nameInvalid = zone.name.trim().length === 0;

  return (
    <div className="scene-inspector">
      <header className="scene-inspector__head">
        <h2 className="truncate" title={zone.name}>{zone.name || 'Unnamed zone'}</h2>
        <p>Zone{vertexIndex !== null ? ` · vertex ${vertexIndex + 1} selected` : ''}</p>
      </header>

      <Issues issues={issues} id={issuesId} />

      <div className="scene-fields">
        <label htmlFor={nameId}>Name</label>
        <input
          id={nameId}
          value={zone.name}
          disabled={readOnly}
          maxLength={SCENE_LIMITS.maximumNameLength}
          autoComplete="off"
          aria-invalid={nameInvalid || undefined}
          aria-describedby={issues.length > 0 ? issuesId : undefined}
          onChange={(event) => onUpdate(zone.key, { name: event.target.value })}
        />

        <label htmlFor={`zone-kind-${zone.key}`}>Type</label>
        <select
          id={`zone-kind-${zone.key}`}
          value={zone.kind}
          disabled={readOnly}
          onChange={(event) => onUpdate(zone.key, { kind: event.target.value as SceneZoneKind })}
        >
          {SCENE_ZONE_KINDS.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
        </select>

        <span className="scene-fields__label" aria-hidden="true">Enabled</span>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={zone.enabled}
            disabled={readOnly}
            onChange={(event) => onUpdate(zone.key, { enabled: event.target.checked })}
          />
          Evaluate this zone
        </label>

        <label htmlFor={`zone-loitering-${zone.key}`}>Loitering</label>
        <div className="scene-fields__inline">
          <input
            id={`zone-loitering-${zone.key}`}
            type="number"
            inputMode="numeric"
            min={1}
            max={SCENE_LIMITS.maximumLoiteringThresholdSeconds}
            value={zone.loiteringThresholdSeconds ?? ''}
            disabled={readOnly}
            placeholder="default"
            onChange={(event) => {
              const raw = event.target.value.trim();
              const parsed = raw === '' ? null : Number.parseInt(raw, 10);
              onUpdate(zone.key, {
                loiteringThresholdSeconds: parsed === null || Number.isNaN(parsed) ? null : parsed,
              });
            }}
          />
          <span>seconds</span>
        </div>
      </div>

      <section className="scene-inspector__points">
        <h3>Vertices<span>{zone.vertices.length}</span></h3>
        <ul aria-label={`Vertices of ${zone.name || 'Unnamed zone'}`}>
          {zone.vertices.map((vertex, index) => (
            <li key={`${zone.key}-vertex-${index}`}>
              <button
                type="button"
                className={`scene-inspector__point${vertexIndex === index ? ' is-selected' : ''}`}
                aria-pressed={vertexIndex === index}
                onClick={() => onSelect({ kind: 'zone', key: zone.key, vertexIndex: index })}
              >
                {`Vertex ${index + 1}: x ${coordinate(vertex.x)}, y ${coordinate(vertex.y)}`}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <dl className="scene-readout">
        <dt>Identity</dt>
        <dd className="scene-readout__id">{zone.zoneId ?? 'issued on save'}</dd>
      </dl>
    </div>
  );
}

function LineProperties({
  line,
  endpoint,
  readOnly,
  issues,
  onUpdate,
  onSelect,
}: {
  line: DraftTripLine;
  endpoint: 'a' | 'b' | null;
  readOnly: boolean;
  issues: SceneIssue[];
  onUpdate: Props['onUpdateLine'];
  onSelect: Props['onSelect'];
}) {
  const nameId = `line-name-${line.key}`;
  const issuesId = `line-issues-${line.key}`;
  const nameInvalid = line.name.trim().length === 0;

  return (
    <div className="scene-inspector">
      <header className="scene-inspector__head">
        <h2 className="truncate" title={line.name}>{line.name || 'Unnamed trip line'}</h2>
        <p>Trip line{endpoint ? ` · endpoint ${endpoint.toUpperCase()} selected` : ''}</p>
      </header>

      <Issues issues={issues} id={issuesId} />

      <div className="scene-fields">
        <label htmlFor={nameId}>Name</label>
        <input
          id={nameId}
          value={line.name}
          disabled={readOnly}
          maxLength={SCENE_LIMITS.maximumNameLength}
          autoComplete="off"
          aria-invalid={nameInvalid || undefined}
          aria-describedby={issues.length > 0 ? issuesId : undefined}
          onChange={(event) => onUpdate(line.key, { name: event.target.value })}
        />

        <span className="scene-fields__label" aria-hidden="true">Enabled</span>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={line.enabled}
            disabled={readOnly}
            onChange={(event) => onUpdate(line.key, { enabled: event.target.checked })}
          />
          Evaluate this line
        </label>

        <span className="scene-fields__label" aria-hidden="true">Directional</span>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={line.directed}
            disabled={readOnly}
            onChange={(event) => onUpdate(line.key, { directed: event.target.checked })}
          />
          Direction matters
        </label>

        <label htmlFor={`line-atob-${line.key}`}>A to B</label>
        <input
          id={`line-atob-${line.key}`}
          value={line.aToBLabel}
          disabled={readOnly}
          maxLength={SCENE_LIMITS.maximumDirectionLabelLength}
          autoComplete="off"
          onChange={(event) => onUpdate(line.key, { aToBLabel: event.target.value })}
        />

        <label htmlFor={`line-btoa-${line.key}`}>B to A</label>
        <input
          id={`line-btoa-${line.key}`}
          value={line.bToALabel}
          disabled={readOnly}
          maxLength={SCENE_LIMITS.maximumDirectionLabelLength}
          autoComplete="off"
          onChange={(event) => onUpdate(line.key, { bToALabel: event.target.value })}
        />
      </div>

      <p className="scene-inspector__hint">
        The arrows across the line show which way a Track must travel to count as each direction.
      </p>

      <section className="scene-inspector__points">
        <h3>Endpoints<span>2</span></h3>
        <ul aria-label={`Endpoints of ${line.name || 'Unnamed trip line'}`}>
          {(['a', 'b'] as const).map((which) => (
            <li key={which}>
              <button
                type="button"
                className={`scene-inspector__point${endpoint === which ? ' is-selected' : ''}`}
                aria-pressed={endpoint === which}
                onClick={() => onSelect({ kind: 'line', key: line.key, endpoint: which })}
              >
                {`Endpoint ${which.toUpperCase()}: x ${coordinate(line[which].x)}, y ${coordinate(line[which].y)}`}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <dl className="scene-readout">
        <dt>Identity</dt>
        <dd className="scene-readout__id">{line.lineId ?? 'issued on save'}</dd>
      </dl>
    </div>
  );
}
