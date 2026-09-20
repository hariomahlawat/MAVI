import { describe, expect, it } from 'vitest';
import type { SceneRevision } from '../../api/scene';
import { editorReducer, initialEditorState, NUDGE_STEP, type EditorAction, type EditorState } from './editorState';
import { draftAnalyticsEnabled, saveRequestFromDraft } from './sceneDraft';

const square = [
  { x: 0.2, y: 0.2 },
  { x: 0.6, y: 0.2 },
  { x: 0.6, y: 0.6 },
  { x: 0.2, y: 0.6 },
];

function revision(overrides: Partial<SceneRevision> = {}): SceneRevision {
  return {
    revisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21501',
    revisionNumber: 3,
    cameraId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
    createdAtUtc: '2026-09-20T06:00:00Z',
    createdBy: 'development-unattributed',
    note: 'Earlier note',
    referenceFrameVideoAssetId: null,
    referenceFrameOffsetMs: null,
    analyticsEnabled: true,
    zones: [{
      zoneId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21b01',
      name: 'Gate',
      kind: 'Restricted',
      enabled: true,
      vertices: square,
      loiteringThresholdSeconds: 45,
    }],
    tripLines: [{
      lineId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21c01',
      name: 'Kerb',
      enabled: true,
      a: { x: 0.1, y: 0.5 },
      b: { x: 0.9, y: 0.5 },
      directed: true,
      aToBLabel: 'inbound',
      bToALabel: 'outbound',
    }],
    ...overrides,
  };
}

function run(state: EditorState, ...actions: EditorAction[]): EditorState {
  return actions.reduce(editorReducer, state);
}

function drawZone(state: EditorState): EditorState {
  return run(
    state,
    { type: 'setTool', tool: 'zone' },
    { type: 'addDrawingVertex', point: { x: 0.1, y: 0.1 } },
    { type: 'addDrawingVertex', point: { x: 0.4, y: 0.1 } },
    { type: 'addDrawingVertex', point: { x: 0.4, y: 0.4 } },
    { type: 'closeZone' },
  );
}

describe('scene editor state', () => {
  // Loading
  it('turns the active revision into an editable draft', () => {
    const state = initialEditorState(revision());

    expect(state.draft.baseRevisionNumber).toBe(3);
    expect(state.draft.zones).toHaveLength(1);
    expect(state.draft.zones[0].zoneId).toBe('018f3f5a-2f70-7a2b-8a12-2d02f4c21b01');
    expect(state.draft.zones[0].kind).toBe('Restricted');
    expect(state.dirty).toBe(false);
    // A note describes a save that has not happened, so it never carries over.
    expect(state.draft.note).toBe('');
  });

  it('starts from an empty draft when the camera has no scene', () => {
    const state = initialEditorState(null);

    expect(state.draft.baseRevisionNumber).toBe(0);
    expect(state.draft.zones).toHaveLength(0);
    expect(saveRequestFromDraft(state.draft).expectedRevisionNumber).toBe(0);
  });

  it('does not share geometry with the revision it was loaded from', () => {
    const source = revision();
    const state = run(initialEditorState(source), {
      type: 'moveVertex', key: '', vertexIndex: 0, point: { x: 0, y: 0 },
    });
    const moved = run(state, {
      type: 'moveVertex',
      key: state.draft.zones[0].key,
      vertexIndex: 0,
      point: { x: 0.9, y: 0.9 },
    });

    expect(moved.draft.zones[0].vertices[0]).toEqual({ x: 0.9, y: 0.9 });
    expect(source.zones[0].vertices[0]).toEqual({ x: 0.2, y: 0.2 });
  });

  // Stable identity
  it('keeps an existing identity and omits one for a new object', () => {
    const state = drawZone(initialEditorState(revision()));
    const request = saveRequestFromDraft(state.draft);

    expect(request.zones[0].zoneId).toBe('018f3f5a-2f70-7a2b-8a12-2d02f4c21b01');
    expect('zoneId' in request.zones[1]).toBe(false);
  });

  it('never gives a new object a persistent identity in the browser', () => {
    const state = drawZone(initialEditorState(null));

    expect(state.draft.zones[0].zoneId).toBeNull();
    expect(state.draft.zones[0].key).toMatch(/^zone-local-/);
  });

  it('omits a deleted object from the next revision', () => {
    const state = initialEditorState(revision());
    const deleted = run(state, { type: 'deleteObject', key: state.draft.zones[0].key });

    expect(saveRequestFromDraft(deleted.draft).zones).toHaveLength(0);
    expect(saveRequestFromDraft(deleted.draft).tripLines).toHaveLength(1);
    expect(deleted.dirty).toBe(true);
  });

  it('replaces local objects with the server-issued revision after a save', () => {
    const drawn = drawZone(initialEditorState(null));
    expect(drawn.draft.zones[0].zoneId).toBeNull();

    const saved = run(drawn, { type: 'savedRevision', revision: revision({ revisionNumber: 1 }) });

    expect(saved.draft.zones[0].zoneId).toBe('018f3f5a-2f70-7a2b-8a12-2d02f4c21b01');
    expect(saved.draft.baseRevisionNumber).toBe(1);
    expect(saved.dirty).toBe(false);
  });

  // Reset
  it('restores the active revision on reset', () => {
    const state = initialEditorState(revision());
    const edited = run(
      state,
      { type: 'updateZone', key: state.draft.zones[0].key, changes: { name: 'Renamed' } },
      { type: 'deleteObject', key: state.draft.tripLines[0].key },
    );
    expect(edited.dirty).toBe(true);

    const reset = run(edited, { type: 'reset' });

    expect(reset.draft.zones[0].name).toBe('Gate');
    expect(reset.draft.tripLines).toHaveLength(1);
    expect(reset.dirty).toBe(false);
    expect(reset.selection).toEqual({ kind: 'none' });
  });

  // Dirty tracking
  it('is not dirty merely because the operator selected, switched tool or wrote a note', () => {
    const state = initialEditorState(revision());
    const touched = run(
      state,
      { type: 'select', selection: { kind: 'zone', key: state.draft.zones[0].key, vertexIndex: 2 } },
      { type: 'setTool', tool: 'line' },
      { type: 'setNote', note: 'About to widen the gate' },
    );

    expect(touched.dirty).toBe(false);
    expect(touched.draft.note).toBe('About to widen the gate');
  });

  it('is dirty once the reference frame is chosen', () => {
    const state = initialEditorState(revision());
    const chosen = run(state, {
      type: 'setReferenceFrame',
      videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
      offsetMs: 4_500,
    });

    expect(chosen.dirty).toBe(true);
    expect(saveRequestFromDraft(chosen.draft).referenceFrameOffsetMs).toBe(4_500);
  });

  it('sends the reference pair whole or not at all', () => {
    const cleared = run(initialEditorState(revision({
      referenceFrameVideoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
      referenceFrameOffsetMs: 1_000,
    })), { type: 'clearReferenceFrame' });
    const request = saveRequestFromDraft(cleared.draft);

    expect(request.referenceFrameVideoAssetId).toBeNull();
    expect(request.referenceFrameOffsetMs).toBeNull();
  });

  it('returns to a clean draft when the same revision is loaded again', () => {
    const state = initialEditorState(revision());
    const edited = run(state, { type: 'updateZone', key: state.draft.zones[0].key, changes: { enabled: false } });

    expect(run(edited, { type: 'loadActive', revision: revision() }).dirty).toBe(false);
  });

  // Drawing
  it('creates nothing until a polygon has three vertices', () => {
    const state = run(
      initialEditorState(null),
      { type: 'setTool', tool: 'zone' },
      { type: 'addDrawingVertex', point: { x: 0.1, y: 0.1 } },
      { type: 'addDrawingVertex', point: { x: 0.4, y: 0.1 } },
      { type: 'closeZone' },
    );

    expect(state.draft.zones).toHaveLength(0);
    expect(state.drawing.kind).toBe('zone');
  });

  it('selects the zone it just closed and returns to the select tool', () => {
    const state = drawZone(initialEditorState(null));

    expect(state.draft.zones).toHaveLength(1);
    expect(state.tool).toBe('select');
    expect(state.selection).toEqual({ kind: 'zone', key: state.draft.zones[0].key, vertexIndex: null });
    expect(state.drawing).toEqual({ kind: 'none' });
    expect(state.dirty).toBe(true);
  });

  it('abandons an unfinished polygon without touching the draft', () => {
    const state = run(
      initialEditorState(null),
      { type: 'setTool', tool: 'zone' },
      { type: 'addDrawingVertex', point: { x: 0.1, y: 0.1 } },
      { type: 'cancelDrawing' },
    );

    expect(state.drawing).toEqual({ kind: 'none' });
    expect(state.draft.zones).toHaveLength(0);
    expect(state.dirty).toBe(false);
  });

  it('draws a trip line from two points', () => {
    const state = run(
      initialEditorState(null),
      { type: 'setTool', tool: 'line' },
      { type: 'startLine', point: { x: 0.1, y: 0.5 } },
      { type: 'finishLine', point: { x: 0.9, y: 0.5 } },
    );

    expect(state.draft.tripLines).toHaveLength(1);
    expect(state.draft.tripLines[0].a).toEqual({ x: 0.1, y: 0.5 });
    expect(state.draft.tripLines[0].b).toEqual({ x: 0.9, y: 0.5 });
    expect(state.draft.tripLines[0].lineId).toBeNull();
  });

  it('refuses a trip line whose endpoints are effectively the same point', () => {
    const state = run(
      initialEditorState(null),
      { type: 'setTool', tool: 'line' },
      { type: 'startLine', point: { x: 0.5, y: 0.5 } },
      { type: 'finishLine', point: { x: 0.502, y: 0.5 } },
    );

    expect(state.draft.tripLines).toHaveLength(0);
  });

  it('gives each new object a name that does not collide', () => {
    const first = drawZone(initialEditorState(null));
    const second = drawZone(first);

    expect(first.draft.zones[0].name).toBe('Zone 1');
    expect(second.draft.zones[1].name).toBe('Zone 2');
  });

  // Vertex editing
  it('nudges a selected vertex by exactly one step', () => {
    const state = initialEditorState(revision());
    const selected = run(state, {
      type: 'select',
      selection: { kind: 'zone', key: state.draft.zones[0].key, vertexIndex: 1 },
    });
    const nudged = run(selected, { type: 'nudgeVertex', dx: NUDGE_STEP, dy: 0 });

    expect(NUDGE_STEP).toBe(0.001);
    expect(nudged.draft.zones[0].vertices[1]).toEqual({ x: 0.601, y: 0.2 });
    expect(nudged.draft.zones[0].vertices[0]).toEqual({ x: 0.2, y: 0.2 });
  });

  it('keeps a nudge at the stored precision over many presses', () => {
    const state = initialEditorState(revision());
    let current = run(state, {
      type: 'select',
      selection: { kind: 'zone', key: state.draft.zones[0].key, vertexIndex: 0 },
    });
    for (let index = 0; index < 7; index += 1) {
      current = run(current, { type: 'nudgeVertex', dx: NUDGE_STEP, dy: NUDGE_STEP });
    }

    expect(current.draft.zones[0].vertices[0]).toEqual({ x: 0.207, y: 0.207 });
  });

  it('clamps a nudge at the edge of the frame', () => {
    const state = initialEditorState(revision({
      zones: [{
        zoneId: 'z', name: 'Edge', kind: 'General', enabled: true, loiteringThresholdSeconds: null,
        vertices: [{ x: 0, y: 0 }, { x: 0.4, y: 0 }, { x: 0.4, y: 0.4 }],
      }],
    }));
    const selected = run(state, {
      type: 'select',
      selection: { kind: 'zone', key: state.draft.zones[0].key, vertexIndex: 0 },
    });
    const nudged = run(selected, { type: 'nudgeVertex', dx: -NUDGE_STEP, dy: -NUDGE_STEP });

    expect(nudged.draft.zones[0].vertices[0]).toEqual({ x: 0, y: 0 });
  });

  it('nudges a selected trip line endpoint', () => {
    const state = initialEditorState(revision());
    const selected = run(state, {
      type: 'select',
      selection: { kind: 'line', key: state.draft.tripLines[0].key, endpoint: 'b' },
    });
    const nudged = run(selected, { type: 'nudgeVertex', dx: 0, dy: NUDGE_STEP });

    expect(nudged.draft.tripLines[0].b).toEqual({ x: 0.9, y: 0.501 });
    expect(nudged.draft.tripLines[0].a).toEqual({ x: 0.1, y: 0.5 });
  });

  it('does nothing when a whole object is selected rather than a vertex', () => {
    const state = initialEditorState(revision());
    const selected = run(state, {
      type: 'select',
      selection: { kind: 'zone', key: state.draft.zones[0].key, vertexIndex: null },
    });

    expect(run(selected, { type: 'nudgeVertex', dx: NUDGE_STEP, dy: 0 }).dirty).toBe(false);
  });

  it('clamps a dragged vertex to the frame', () => {
    const state = initialEditorState(revision());
    const dragged = run(state, {
      type: 'moveVertex',
      key: state.draft.zones[0].key,
      vertexIndex: 0,
      point: { x: 2, y: -3 },
    });

    expect(dragged.draft.zones[0].vertices[0]).toEqual({ x: 1, y: 0 });
  });

  // Disable semantics
  it('reports analytics disabled for an empty scene and for one with nothing enabled', () => {
    expect(draftAnalyticsEnabled(initialEditorState(null).draft)).toBe(false);

    const state = initialEditorState(revision());
    const allOff = run(
      state,
      { type: 'updateZone', key: state.draft.zones[0].key, changes: { enabled: false } },
      { type: 'updateLine', key: state.draft.tripLines[0].key, changes: { enabled: false } },
    );

    expect(draftAnalyticsEnabled(allOff.draft)).toBe(false);
    expect(allOff.draft.zones).toHaveLength(1);
  });

  it('reports analytics enabled when a single trip line is on', () => {
    const state = initialEditorState(revision());
    const onlyLine = run(state, {
      type: 'updateZone', key: state.draft.zones[0].key, changes: { enabled: false },
    });

    expect(draftAnalyticsEnabled(onlyLine.draft)).toBe(true);
  });

  // Selection
  it('clears the selection when the selected object is deleted', () => {
    const state = initialEditorState(revision());
    const selected = run(state, {
      type: 'select', selection: { kind: 'zone', key: state.draft.zones[0].key, vertexIndex: 0 },
    });
    const deleted = run(selected, { type: 'deleteSelected' });

    expect(deleted.selection).toEqual({ kind: 'none' });
    expect(deleted.draft.zones).toHaveLength(0);
  });

  it('keeps the selection when a different object is deleted', () => {
    const state = initialEditorState(revision());
    const selected = run(state, {
      type: 'select', selection: { kind: 'zone', key: state.draft.zones[0].key, vertexIndex: null },
    });
    const deleted = run(selected, { type: 'deleteObject', key: state.draft.tripLines[0].key });

    expect(deleted.selection).toEqual({ kind: 'zone', key: state.draft.zones[0].key, vertexIndex: null });
  });
});
