import { describe, expect, it } from 'vitest';
import type { TrackSearchItem } from '../../api/tracks';
import { isNavigationTarget, nearEnd, neighbourId, selectedIndex } from './resultNavigation';

const items = ['A', 'B', 'C', 'D'].map((id) => ({ id: `00000000-0000-0000-0000-00000000000${id}` }) as TrackSearchItem);

describe('result navigation', () => {
  it('finds the selected index case-insensitively', () => {
    expect(selectedIndex(items, '00000000-0000-0000-0000-00000000000b')).toBe(1);
    expect(selectedIndex(items, null)).toBe(-1);
    expect(selectedIndex(items, 'missing')).toBe(-1);
  });

  it('steps to neighbours, returns null at the edges, and starts at the first row when nothing is selected', () => {
    expect(neighbourId(items, '00000000-0000-0000-0000-00000000000b', 1)).toBe('00000000-0000-0000-0000-00000000000c');
    expect(neighbourId(items, '00000000-0000-0000-0000-00000000000b', -1)).toBe('00000000-0000-0000-0000-00000000000a');
    expect(neighbourId(items, '00000000-0000-0000-0000-00000000000a', -1)).toBeNull();
    expect(neighbourId(items, '00000000-0000-0000-0000-00000000000d', 1)).toBeNull();
    expect(neighbourId(items, null, 1)).toBe('00000000-0000-0000-0000-00000000000a');
    expect(neighbourId(items, null, -1)).toBeNull();
  });

  it('flags the tail of the loaded results for prefetching', () => {
    expect(nearEnd(items, '00000000-0000-0000-0000-00000000000a')).toBe(false);
    expect(nearEnd(items, '00000000-0000-0000-0000-00000000000b')).toBe(true);
    expect(nearEnd(items, null)).toBe(false);
  });

  it('never hijacks keys typed into form controls or media', () => {
    expect(isNavigationTarget(document.createElement('input'))).toBe(false);
    expect(isNavigationTarget(document.createElement('select'))).toBe(false);
    expect(isNavigationTarget(document.createElement('video'))).toBe(false);
    expect(isNavigationTarget(document.body)).toBe(true);
    expect(isNavigationTarget(null)).toBe(true);
  });
});
