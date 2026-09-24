import { describe, expect, it } from 'vitest';
import type { TrackSearchItem } from '../../api/tracks';
import { isDismissTarget, isNavigationTarget, nearEnd, neighbourId, selectedIndex } from './resultNavigation';

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
  });

  it('refuses a key press from inside the Evidence Player', () => {
    // Result navigation binds j and k on the window; the player's frozen
    // grammar binds J and L for one second either way. Without this, one press
    // inside the player would both nudge the media and move the selection.
    const player = document.createElement('div');
    player.setAttribute('data-evidence-player', '');
    const control = document.createElement('button');
    player.append(control);
    document.body.append(player);

    expect(isNavigationTarget(control)).toBe(false);
    expect(isNavigationTarget(player)).toBe(false);

    // The overlay stage is SVG, and an HTML-only guard would let it through.
    // Built by parsing rather than by namespace, because the repository
    // verification refuses a literal Internet URL in product source.
    player.insertAdjacentHTML('beforeend', '<svg></svg>');
    const stage = player.querySelector('svg');
    expect(stage).not.toBeInstanceOf(HTMLElement);
    expect(isNavigationTarget(stage)).toBe(false);

    const outside = document.createElement('button');
    document.body.append(outside);
    expect(isNavigationTarget(outside)).toBe(true);

    player.remove();
    outside.remove();
    expect(isNavigationTarget(null)).toBe(true);
  });

  it('lets Escape through from the evidence subtree, and from nowhere that types', () => {
    // No evidence grammar binds Escape, so the subtree that refuses J and K
    // does not refuse it (S1.3 plan §20.2). A text field still keeps it.
    const player = document.createElement('div');
    player.setAttribute('data-evidence-player', '');
    const control = document.createElement('button');
    player.append(control);
    player.insertAdjacentHTML('beforeend', '<svg></svg>');
    document.body.append(player);

    expect(isDismissTarget(control)).toBe(true);
    expect(isDismissTarget(player.querySelector('svg'))).toBe(true);
    expect(isNavigationTarget(control)).toBe(false);

    expect(isDismissTarget(document.createElement('input'))).toBe(false);
    expect(isDismissTarget(document.createElement('select'))).toBe(false);
    expect(isDismissTarget(document.createElement('textarea'))).toBe(false);
    expect(isDismissTarget(document.createElement('video'))).toBe(false);
    expect(isDismissTarget(null)).toBe(true);
    player.remove();
  });
});
