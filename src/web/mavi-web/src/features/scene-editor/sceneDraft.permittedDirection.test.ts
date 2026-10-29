import { describe, expect, it } from 'vitest';
import type { SceneRevision } from '../../api/scene';
import { draftFromRevision, saveRequestFromDraft } from './sceneDraft';

// ADR-025 §6: a trip line's permitted direction is scene geometry. An edit made
// anywhere else in the editor must not drop it from the next revision.

function revision(permittedDirection: 'AToB' | 'BToA' | null, directed = true): SceneRevision {
  return {
    revisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21481',
    revisionNumber: 3,
    cameraId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
    createdAtUtc: '2026-10-29T10:00:00Z',
    createdBy: 'development-unattributed',
    note: null,
    referenceFrameVideoAssetId: null,
    referenceFrameOffsetMs: null,
    zones: [],
    tripLines: [{
      lineId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21490',
      name: 'Gate',
      enabled: true,
      a: { x: 0.1, y: 0.5 },
      b: { x: 0.9, y: 0.5 },
      directed,
      aToBLabel: 'In',
      bToALabel: 'Out',
      permittedDirection,
    }],
    analyticsEnabled: true,
  } as SceneRevision;
}

describe('permitted direction in the scene draft', () => {
  it('survives a load and save untouched', () => {
    const request = saveRequestFromDraft(draftFromRevision(revision('BToA')));
    expect(request.tripLines[0].permittedDirection).toBe('BToA');
  });

  it('is sent as null when the line has none, including from an older response without the field', () => {
    expect(saveRequestFromDraft(draftFromRevision(revision(null))).tripLines[0].permittedDirection).toBeNull();
    const legacy = revision(null);
    delete (legacy.tripLines[0] as { permittedDirection?: unknown }).permittedDirection;
    expect(saveRequestFromDraft(draftFromRevision(legacy)).tripLines[0].permittedDirection).toBeNull();
  });

  it('is cleared when the line stops being directed, which the server would otherwise refuse', () => {
    const draft = draftFromRevision(revision('AToB'));
    draft.tripLines[0] = { ...draft.tripLines[0], directed: false };
    expect(saveRequestFromDraft(draft).tripLines[0].permittedDirection).toBeNull();
  });
});
