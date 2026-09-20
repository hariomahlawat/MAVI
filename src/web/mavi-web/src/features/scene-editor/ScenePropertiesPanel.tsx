import { SCENE_LIMITS, SCENE_ZONE_KINDS, type SceneZoneKind } from '../../api/scene';
import EmptyState from '../../shared/components/EmptyState';
import type { Selection } from './editorState';
import type { DraftTripLine, DraftZone, SceneDraft } from './sceneDraft';
import { findLine, findZone } from './editorState';

type Props = {
  draft: SceneDraft;
  selection: Selection;
  readOnly: boolean;
  onUpdateZone: (key: string, changes: Partial<Omit<DraftZone, 'key' | 'zoneId' | 'vertices'>>) => void;
  onUpdateLine: (key: string, changes: Partial<Omit<DraftTripLine, 'key' | 'lineId' | 'a' | 'b'>>) => void;
};

/**
 * Everything about the selected object that is not its shape.
 *
 * The canvas is for geometry; a name, a kind or a label should never require
 * pointing at a picture. Stable identities appear as read-only detail, because
 * they belong to the server and an operator has no reason to edit one.
 */
export default function ScenePropertiesPanel({ draft, selection, readOnly, onUpdateZone, onUpdateLine }: Props) {
  if (selection.kind === 'none') {
    return <EmptyState title="Nothing selected" compact>Select a zone or trip line to edit its properties.</EmptyState>;
  }

  if (selection.kind === 'zone') {
    const zone = findZone(draft, selection.key);
    if (!zone) return <EmptyState title="Nothing selected" compact>The selected zone no longer exists.</EmptyState>;
    return <ZoneProperties zone={zone} readOnly={readOnly} onUpdate={onUpdateZone} />;
  }

  const line = findLine(draft, selection.key);
  if (!line) return <EmptyState title="Nothing selected" compact>The selected trip line no longer exists.</EmptyState>;
  return <LineProperties line={line} readOnly={readOnly} onUpdate={onUpdateLine} />;
}

function ZoneProperties({
  zone,
  readOnly,
  onUpdate,
}: {
  zone: DraftZone;
  readOnly: boolean;
  onUpdate: Props['onUpdateZone'];
}) {
  const nameId = `zone-name-${zone.key}`;
  const nameInvalid = zone.name.trim().length === 0;

  return (
    <div className="form-stack scene-properties">
      <label htmlFor={nameId}>
        Zone name
        <input
          id={nameId}
          value={zone.name}
          disabled={readOnly}
          maxLength={SCENE_LIMITS.maximumNameLength}
          autoComplete="off"
          aria-invalid={nameInvalid || undefined}
          aria-describedby={nameInvalid ? `${nameId}-error` : undefined}
          onChange={(event) => onUpdate(zone.key, { name: event.target.value })}
        />
      </label>
      {nameInvalid ? <p className="field-error" id={`${nameId}-error`}>A zone needs a name.</p> : null}

      <label htmlFor={`zone-kind-${zone.key}`}>
        Kind
        <select
          id={`zone-kind-${zone.key}`}
          value={zone.kind}
          disabled={readOnly}
          onChange={(event) => onUpdate(zone.key, { kind: event.target.value as SceneZoneKind })}
        >
          {SCENE_ZONE_KINDS.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
        </select>
      </label>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={zone.enabled}
          disabled={readOnly}
          onChange={(event) => onUpdate(zone.key, { enabled: event.target.checked })}
        />
        Enabled for analytics
      </label>

      <label htmlFor={`zone-loitering-${zone.key}`}>
        Loitering threshold (seconds, optional)
        <input
          id={`zone-loitering-${zone.key}`}
          type="number"
          inputMode="numeric"
          min={1}
          max={SCENE_LIMITS.maximumLoiteringThresholdSeconds}
          value={zone.loiteringThresholdSeconds ?? ''}
          disabled={readOnly}
          placeholder="Engine default"
          onChange={(event) => {
            const raw = event.target.value.trim();
            const parsed = raw === '' ? null : Number.parseInt(raw, 10);
            onUpdate(zone.key, {
              loiteringThresholdSeconds: parsed === null || Number.isNaN(parsed) ? null : parsed,
            });
          }}
        />
      </label>
      <p className="field-help">
        Leave empty to use the analytics engine default. Applies to persons dwelling in this zone.
      </p>

      <dl className="scene-properties__detail">
        <dt>Vertices</dt>
        <dd>{zone.vertices.length}</dd>
        <dt>Stable identity</dt>
        <dd><code>{zone.zoneId ?? 'issued on save'}</code></dd>
      </dl>
    </div>
  );
}

function LineProperties({
  line,
  readOnly,
  onUpdate,
}: {
  line: DraftTripLine;
  readOnly: boolean;
  onUpdate: Props['onUpdateLine'];
}) {
  const nameId = `line-name-${line.key}`;
  const nameInvalid = line.name.trim().length === 0;

  return (
    <div className="form-stack scene-properties">
      <label htmlFor={nameId}>
        Trip line name
        <input
          id={nameId}
          value={line.name}
          disabled={readOnly}
          maxLength={SCENE_LIMITS.maximumNameLength}
          autoComplete="off"
          aria-invalid={nameInvalid || undefined}
          aria-describedby={nameInvalid ? `${nameId}-error` : undefined}
          onChange={(event) => onUpdate(line.key, { name: event.target.value })}
        />
      </label>
      {nameInvalid ? <p className="field-error" id={`${nameId}-error`}>A trip line needs a name.</p> : null}

      <label className="checkbox">
        <input
          type="checkbox"
          checked={line.enabled}
          disabled={readOnly}
          onChange={(event) => onUpdate(line.key, { enabled: event.target.checked })}
        />
        Enabled for analytics
      </label>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={line.directed}
          disabled={readOnly}
          onChange={(event) => onUpdate(line.key, { directed: event.target.checked })}
        />
        Directed
      </label>
      <p className="field-help">
        Crossings record a direction either way. Marking a line directed says the operator cares which way it was crossed.
      </p>

      <label htmlFor={`line-atob-${line.key}`}>
        A to B label
        <input
          id={`line-atob-${line.key}`}
          value={line.aToBLabel}
          disabled={readOnly}
          maxLength={SCENE_LIMITS.maximumDirectionLabelLength}
          autoComplete="off"
          onChange={(event) => onUpdate(line.key, { aToBLabel: event.target.value })}
        />
      </label>

      <label htmlFor={`line-btoa-${line.key}`}>
        B to A label
        <input
          id={`line-btoa-${line.key}`}
          value={line.bToALabel}
          disabled={readOnly}
          maxLength={SCENE_LIMITS.maximumDirectionLabelLength}
          autoComplete="off"
          onChange={(event) => onUpdate(line.key, { bToALabel: event.target.value })}
        />
      </label>
      <p className="field-help">
        The A to B side is the left of the line from A towards B, which the canvas marks with an arrow.
      </p>

      <dl className="scene-properties__detail">
        <dt>Stable identity</dt>
        <dd><code>{line.lineId ?? 'issued on save'}</code></dd>
      </dl>
    </div>
  );
}
