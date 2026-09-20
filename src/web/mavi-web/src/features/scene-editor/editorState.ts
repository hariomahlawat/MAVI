import { DEFAULT_SCENE_ZONE_KIND, SCENE_LIMITS, type ScenePoint, type SceneZoneKind } from '../../api/scene';
import {
  clampPoint,
  draftFromRevision,
  emptyDraft,
  isDraftDirty,
  nextLocalKey,
  roundCoordinate,
  type DraftTripLine,
  type DraftZone,
  type SceneDraft,
} from './sceneDraft';
import type { SceneRevision } from '../../api/scene';

/** What a pointer click on the frame currently means. */
export type EditorTool = 'select' | 'zone' | 'line';

/** What is selected, kept as a discriminated union so the three can never blur. */
export type Selection =
  | { kind: 'none' }
  | { kind: 'zone'; key: string; vertexIndex: number | null }
  | { kind: 'line'; key: string; endpoint: 'a' | 'b' | null };

/** Geometry being drawn, which is not part of the draft until it is finished. */
export type Drawing =
  | { kind: 'none' }
  | { kind: 'zone'; vertices: ScenePoint[] }
  | { kind: 'line'; a: ScenePoint };

export type EditorState = {
  /** The revision the draft was loaded from, kept for reset and for dirty comparison. */
  baseline: SceneDraft;
  draft: SceneDraft;
  tool: EditorTool;
  selection: Selection;
  drawing: Drawing;
  dirty: boolean;
};

export type EditorAction =
  | { type: 'loadActive'; revision: SceneRevision | null }
  | { type: 'reset' }
  | { type: 'setTool'; tool: EditorTool }
  | { type: 'select'; selection: Selection }
  | { type: 'addDrawingVertex'; point: ScenePoint }
  | { type: 'closeZone' }
  | { type: 'startLine'; point: ScenePoint }
  | { type: 'finishLine'; point: ScenePoint }
  | { type: 'cancelDrawing' }
  | { type: 'moveVertex'; key: string; vertexIndex: number; point: ScenePoint }
  | { type: 'nudgeVertex'; dx: number; dy: number }
  | { type: 'moveEndpoint'; key: string; endpoint: 'a' | 'b'; point: ScenePoint }
  | { type: 'updateZone'; key: string; changes: Partial<Omit<DraftZone, 'key' | 'zoneId' | 'vertices'>> }
  | { type: 'updateLine'; key: string; changes: Partial<Omit<DraftTripLine, 'key' | 'lineId' | 'a' | 'b'>> }
  | { type: 'deleteSelected' }
  | { type: 'deleteObject'; key: string }
  | { type: 'setNote'; note: string }
  | { type: 'setReferenceFrame'; videoAssetId: string; offsetMs: number }
  | { type: 'clearReferenceFrame' }
  | { type: 'savedRevision'; revision: SceneRevision };

/** One arrow-key press, in normalised units, as the plan freezes it. */
export const NUDGE_STEP = 0.001;

export function initialEditorState(revision: SceneRevision | null): EditorState {
  const draft = revision ? draftFromRevision(revision) : emptyDraft();
  return {
    baseline: draft,
    draft,
    tool: 'select',
    selection: { kind: 'none' },
    drawing: { kind: 'none' },
    dirty: false,
  };
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case 'loadActive':
    case 'savedRevision': {
      const revision = action.type === 'loadActive' ? action.revision : action.revision;
      const draft = revision ? draftFromRevision(revision) : emptyDraft();
      return {
        baseline: draft,
        draft,
        tool: 'select',
        // A save replaces temporary objects with server-issued ones, so the
        // previous selection keys no longer exist. The caller re-selects by
        // stable identity where it can.
        selection: { kind: 'none' },
        drawing: { kind: 'none' },
        dirty: false,
      };
    }

    case 'reset':
      return {
        ...state,
        draft: state.baseline,
        tool: 'select',
        selection: { kind: 'none' },
        drawing: { kind: 'none' },
        dirty: false,
      };

    case 'setTool':
      // Changing tool abandons anything half-drawn but never touches the draft.
      return { ...state, tool: action.tool, drawing: { kind: 'none' } };

    case 'select':
      return { ...state, selection: action.selection };

    case 'addDrawingVertex': {
      if (state.tool !== 'zone') return state;
      const existing = state.drawing.kind === 'zone' ? state.drawing.vertices : [];
      if (existing.length >= SCENE_LIMITS.maximumZoneVertices) return state;
      return { ...state, drawing: { kind: 'zone', vertices: [...existing, clampPoint(action.point)] } };
    }

    case 'closeZone': {
      if (state.drawing.kind !== 'zone') return state;
      // Nothing becomes an object until it is at least a triangle.
      if (state.drawing.vertices.length < SCENE_LIMITS.minimumZoneVertices) return state;
      if (state.draft.zones.length >= SCENE_LIMITS.maximumZonesPerRevision) return state;

      const zone: DraftZone = {
        key: nextLocalKey('zone'),
        zoneId: null,
        name: nextName(state.draft.zones.map((item) => item.name), 'Zone'),
        kind: DEFAULT_SCENE_ZONE_KIND,
        enabled: true,
        vertices: state.drawing.vertices,
        loiteringThresholdSeconds: null,
      };
      return withDraft(state, {
        ...state.draft,
        zones: [...state.draft.zones, zone],
      }, {
        tool: 'select',
        selection: { kind: 'zone', key: zone.key, vertexIndex: null },
        drawing: { kind: 'none' },
      });
    }

    case 'startLine':
      if (state.tool !== 'line') return state;
      return { ...state, drawing: { kind: 'line', a: clampPoint(action.point) } };

    case 'finishLine': {
      if (state.drawing.kind !== 'line') return state;
      if (state.draft.tripLines.length >= SCENE_LIMITS.maximumTripLinesPerRevision) return state;
      const b = clampPoint(action.point);
      // Too short to have a direction; the operator is told rather than
      // silently given a line the backend would reject.
      if (distance(state.drawing.a, b) < SCENE_LIMITS.minimumLineEndpointSeparation) return state;

      const line: DraftTripLine = {
        key: nextLocalKey('line'),
        lineId: null,
        name: nextName(state.draft.tripLines.map((item) => item.name), 'Line'),
        enabled: true,
        a: state.drawing.a,
        b,
        directed: false,
        aToBLabel: 'A to B',
        bToALabel: 'B to A',
      };
      return withDraft(state, {
        ...state.draft,
        tripLines: [...state.draft.tripLines, line],
      }, {
        tool: 'select',
        selection: { kind: 'line', key: line.key, endpoint: null },
        drawing: { kind: 'none' },
      });
    }

    case 'cancelDrawing':
      return { ...state, drawing: { kind: 'none' } };

    case 'moveVertex': {
      const zones = state.draft.zones.map((zone) => {
        if (zone.key !== action.key) return zone;
        const vertices = zone.vertices.map((vertex, index) =>
          index === action.vertexIndex ? clampPoint(action.point) : vertex);
        return { ...zone, vertices };
      });
      return withDraft(state, { ...state.draft, zones });
    }

    case 'nudgeVertex':
      return nudge(state, action.dx, action.dy);

    case 'moveEndpoint': {
      const tripLines = state.draft.tripLines.map((line) =>
        line.key === action.key ? { ...line, [action.endpoint]: clampPoint(action.point) } : line);
      return withDraft(state, { ...state.draft, tripLines });
    }

    case 'updateZone': {
      const zones = state.draft.zones.map((zone) =>
        zone.key === action.key ? { ...zone, ...action.changes } : zone);
      return withDraft(state, { ...state.draft, zones });
    }

    case 'updateLine': {
      const tripLines = state.draft.tripLines.map((line) =>
        line.key === action.key ? { ...line, ...action.changes } : line);
      return withDraft(state, { ...state.draft, tripLines });
    }

    case 'deleteSelected': {
      if (state.selection.kind === 'none') return state;
      return deleteByKey(state, state.selection.key);
    }

    case 'deleteObject':
      return deleteByKey(state, action.key);

    case 'setNote':
      // The note describes a save that has not happened, so it is not a change
      // to the scene and does not make the draft dirty.
      return { ...state, draft: { ...state.draft, note: action.note } };

    case 'setReferenceFrame':
      return withDraft(state, {
        ...state.draft,
        referenceFrameVideoAssetId: action.videoAssetId,
        referenceFrameOffsetMs: Math.max(0, Math.round(action.offsetMs)),
      });

    case 'clearReferenceFrame':
      return withDraft(state, {
        ...state.draft,
        referenceFrameVideoAssetId: null,
        referenceFrameOffsetMs: null,
      });

    default:
      return state;
  }
}

function deleteByKey(state: EditorState, key: string): EditorState {
  const zones = state.draft.zones.filter((zone) => zone.key !== key);
  const tripLines = state.draft.tripLines.filter((line) => line.key !== key);
  if (zones.length === state.draft.zones.length && tripLines.length === state.draft.tripLines.length) {
    return state;
  }
  const selectionCleared = state.selection.kind !== 'none' && state.selection.key === key;
  return withDraft(state, { ...state.draft, zones, tripLines }, {
    selection: selectionCleared ? { kind: 'none' } : state.selection,
  });
}

function nudge(state: EditorState, dx: number, dy: number): EditorState {
  const { selection } = state;
  if (selection.kind === 'zone' && selection.vertexIndex !== null) {
    const zones = state.draft.zones.map((zone) => {
      if (zone.key !== selection.key) return zone;
      const vertices = zone.vertices.map((vertex, index) =>
        index === selection.vertexIndex ? shift(vertex, dx, dy) : vertex);
      return { ...zone, vertices };
    });
    return withDraft(state, { ...state.draft, zones });
  }

  if (selection.kind === 'line' && selection.endpoint !== null) {
    const tripLines = state.draft.tripLines.map((line) =>
      line.key === selection.key
        ? { ...line, [selection.endpoint as 'a' | 'b']: shift(line[selection.endpoint as 'a' | 'b'], dx, dy) }
        : line);
    return withDraft(state, { ...state.draft, tripLines });
  }

  return state;
}

function shift(point: ScenePoint, dx: number, dy: number): ScenePoint {
  return clampPoint({
    x: roundCoordinate(point.x + dx),
    y: roundCoordinate(point.y + dy),
  });
}

function withDraft(state: EditorState, draft: SceneDraft, extra: Partial<EditorState> = {}): EditorState {
  return {
    ...state,
    ...extra,
    draft,
    dirty: isDraftDirty(draft, state.baseline),
  };
}

function distance(a: ScenePoint, b: ScenePoint): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** "Zone 1", "Zone 2", … skipping names already taken, so a new object is saveable at once. */
function nextName(existing: string[], prefix: string): string {
  const taken = new Set(existing.map((name) => name.trim().toLowerCase()));
  for (let index = 1; index <= existing.length + 1; index += 1) {
    const candidate = `${prefix} ${index}`;
    if (!taken.has(candidate.toLowerCase())) return candidate;
  }
  return `${prefix} ${existing.length + 1}`;
}

export function findZone(draft: SceneDraft, key: string): DraftZone | undefined {
  return draft.zones.find((zone) => zone.key === key);
}

export function findLine(draft: SceneDraft, key: string): DraftTripLine | undefined {
  return draft.tripLines.find((line) => line.key === key);
}

export type { SceneZoneKind };
