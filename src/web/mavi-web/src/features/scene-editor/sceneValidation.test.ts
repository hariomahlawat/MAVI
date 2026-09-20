import { describe, expect, it } from 'vitest';
import { SCENE_LIMITS } from '../../api/scene';
import { emptyDraft, nextLocalKey, type DraftTripLine, type DraftZone, type SceneDraft } from './sceneDraft';
import { issuesByKey, validateDraft } from './sceneValidation';

function zone(overrides: Partial<DraftZone> = {}): DraftZone {
  return {
    key: nextLocalKey('zone'),
    zoneId: null,
    name: 'Gate',
    kind: 'General',
    enabled: true,
    vertices: [{ x: 0.1, y: 0.1 }, { x: 0.4, y: 0.1 }, { x: 0.4, y: 0.4 }],
    loiteringThresholdSeconds: null,
    ...overrides,
  };
}

function line(overrides: Partial<DraftTripLine> = {}): DraftTripLine {
  return {
    key: nextLocalKey('line'),
    lineId: null,
    name: 'Kerb',
    enabled: true,
    a: { x: 0.1, y: 0.5 },
    b: { x: 0.9, y: 0.5 },
    directed: false,
    aToBLabel: 'A to B',
    bToALabel: 'B to A',
    ...overrides,
  };
}

function draft(overrides: Partial<SceneDraft> = {}): SceneDraft {
  return { ...emptyDraft(), ...overrides };
}

describe('client scene validation', () => {
  it('passes a scene the backend would accept', () => {
    expect(validateDraft(draft({ zones: [zone()], tripLines: [line()] }))).toEqual([]);
  });

  it('reports an empty name against the object that has it', () => {
    const subject = zone({ name: '   ' });
    const issues = validateDraft(draft({ zones: [subject] }));

    expect(issues).toHaveLength(1);
    expect(issues[0].key).toBe(subject.key);
    expect(issues[0].message).toBe('This zone needs a name.');
  });

  it('reports a duplicate zone name against both zones, ignoring case', () => {
    const first = zone({ name: 'Gate' });
    const second = zone({ name: 'gate' });
    const keys = validateDraft(draft({ zones: [first, second] })).map((issue) => issue.key);

    expect(keys).toEqual([first.key, second.key]);
  });

  it('does not collide a zone name with a trip line name', () => {
    expect(validateDraft(draft({ zones: [zone({ name: 'Gate' })], tripLines: [line({ name: 'Gate' })] }))).toEqual([]);
  });

  it('reports a polygon with too few vertices', () => {
    const subject = zone({ vertices: [{ x: 0.1, y: 0.1 }, { x: 0.4, y: 0.1 }] });
    const issues = validateDraft(draft({ zones: [subject] }));

    expect(issues.map((issue) => issue.message)).toContain('A zone needs at least 3 vertices.');
  });

  it('reports endpoints that are too close to give a line a direction', () => {
    const subject = line({ a: { x: 0.5, y: 0.5 }, b: { x: 0.502, y: 0.5 } });
    const issues = validateDraft(draft({ tripLines: [subject] }));

    expect(issues[0].key).toBe(subject.key);
    expect(issues[0].message).toMatch(/too close together/);
  });

  it.each([
    [0],
    [-1],
    [SCENE_LIMITS.maximumLoiteringThresholdSeconds + 1],
  ])('reports a loitering threshold of %i as out of range', (threshold) => {
    const issues = validateDraft(draft({ zones: [zone({ loiteringThresholdSeconds: threshold })] }));

    expect(issues.map((issue) => issue.message)).toContain(
      `A loitering threshold must be between 1 and ${SCENE_LIMITS.maximumLoiteringThresholdSeconds} seconds.`,
    );
  });

  it('accepts no loitering threshold at all', () => {
    expect(validateDraft(draft({ zones: [zone({ loiteringThresholdSeconds: null })] }))).toEqual([]);
  });

  it('reports an over-long direction label', () => {
    const subject = line({ aToBLabel: 'x'.repeat(SCENE_LIMITS.maximumDirectionLabelLength + 1) });
    const issues = validateDraft(draft({ tripLines: [subject] }));

    expect(issues[0].key).toBe(subject.key);
  });

  it('reports a count over the limit against the scene rather than an object', () => {
    const zones = Array.from({ length: SCENE_LIMITS.maximumZonesPerRevision + 1 }, (_, index) =>
      zone({ name: `Zone ${index}` }));
    const issues = validateDraft(draft({ zones }));

    expect(issues).toHaveLength(1);
    expect(issues[0].key).toBeNull();
  });

  it('groups issues by the object they belong to and drops scene-level ones', () => {
    const named = zone({ name: '' });
    const grouped = issuesByKey(validateDraft(draft({
      zones: [named],
      note: 'n'.repeat(SCENE_LIMITS.maximumNoteLength + 1),
    })));

    expect([...grouped.keys()]).toEqual([named.key]);
    expect(grouped.get(named.key)).toHaveLength(1);
  });
});
